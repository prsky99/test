"""Anonymous daily traffic counts (11-09 outside-traffic plan, stage 0).

Every public request is counted once by entry (home, pages, Chat, MCP, A2A, agent API, gateway, documents)
and by client class (internal, browser, AI bot, signature verifier, script, headless, other), with status
class, known bot names and MCP client names. Nothing identifies a visitor: no IP address, user agent string,
URL beyond the entry name, query or body is stored. Distinct clients are counted with a random salt that
lives only in memory and changes every day.

Our own traffic is counted as "internal": loopback, addresses listed in TRAFFIC_INTERNAL_IPS or in
<dir>/internal-ips.txt (one per line, operator managed, never committed), and user agents of our own test
tools. Each process rewrites LOG_DIR/traffic/YYYY-MM-DD.<pid>.json at most once a minute.
`python -m agent_market.concierge.traffic [dir] [days]` prints a weekly summary.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

FLUSH_SECONDS = 60
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._/-]{0,39}')

# Our own test tools (UA tags used by site-owner QA, release checks and measurement scripts).
INTERNAL_UA = re.compile(r'site owner|\bQA\b|QA/|^qa[-0-9]|AgentScenarioQA|RecheckQA|ChatQA|FrontE2E|agentcon-|'
                         r'AgentConcierge|agentconcierge-qa|ops-check|qa-agent', re.I)
# Crawlers and AI fetchers, by the token each operator documents. The first match names the bot.
BOTS = ('GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'ClaudeBot', 'Claude-User', 'Claude-SearchBot', 'anthropic-ai',
        'PerplexityBot', 'Perplexity-User', 'Google-Extended', 'Googlebot', 'GoogleOther', 'bingbot', 'BingPreview',
        'Applebot', 'Amazonbot', 'meta-externalagent', 'FacebookBot', 'Bytespider', 'CCBot', 'DuckAssistBot',
        'YandexBot', 'Baiduspider', 'PetalBot', 'cohere-ai', 'MistralAI-User', 'YouBot')
BOT = re.compile('|'.join(re.escape(b) for b in BOTS), re.I)
VERIFIER = re.compile(r'identity[ -]check|BotAuth', re.I)
SCRIPT = re.compile(r'^(curl|wget|python|httpx|aiohttp|node|axios|undici|go-http|okhttp|java|deno|bun|ruby|php|'
                    r'libwww|Postman|insomnia)', re.I)
HEADLESS = re.compile(r'Headless|PhantomJS|Puppeteer|Playwright', re.I)
BROWSER = re.compile(r'^Mozilla/5\.0 .*(Chrome|Safari|Firefox|Edg)/', re.I)


def entry_of(method, path):
    """Short entry name for a request path, or None for paths not worth counting (assets, probes)."""
    if path.startswith('/new/en/assets/') or path.startswith('/assets/'):
        return None
    if path == '/':
        return 'home'
    if path.startswith('/new/en/') and path.endswith('.html'):
        return 'page'
    if path in ('/chat', '/chat/'):
        return 'chat'
    if path == '/mcp' or path.startswith('/mcp/'):
        return 'mcp'
    if path == '/a2a' or path.startswith('/a2a/'):
        return 'a2a'
    if path.startswith('/api/agent/'):
        return 'agent_api'
    if path.startswith('/api/gateway/'):
        return 'gateway'
    if path.startswith('/api/explore'):
        return 'explore'
    if path in ('/llms.txt', '/llms-full.txt', '/skill.md'):
        return 'llms'
    if path.startswith('/.well-known/'):
        return 'well_known'
    if path in ('/robots.txt', '/sitemap.xml') or path.startswith('/agents/category/'):
        return 'crawl'
    if path in ('/openapi.json', '/docs', '/redoc'):
        return 'openapi'
    if path.startswith(('/customer/', '/api/customer', '/api/workspace')):
        return 'workspace'
    if path.startswith('/api/'):
        return 'api_other'
    # Public growth pages (11-10): counted by family so crawler visits can stand in for index progress.
    if path == '/agents/tasks' or path.startswith('/agents/task/'):
        return 'tasks'
    if path.startswith('/agent/'):
        return 'agent_pages'
    if path == '/agents/best' or path.startswith(('/agents/best/', '/agents/compare/')):
        return 'rankings'
    if path.startswith('/reports/'):
        return 'reports'
    if path in ('/connect', '/badges') or path.startswith('/claude-plugins/'):
        return 'connect'
    return None


def client_of(ip, ua, internal_ips):
    """Client class and, for bots, the bot name."""
    ua = ua or ''
    if ip in internal_ips or INTERNAL_UA.search(ua):
        return 'internal', None
    bot = BOT.search(ua)
    if bot:
        return 'ai_bot', next(b for b in BOTS if b.lower() == bot.group(0).lower())
    if VERIFIER.search(ua):
        return 'verifier', None
    if HEADLESS.search(ua):
        return 'headless', None
    if BROWSER.search(ua):
        return 'browser', None
    if SCRIPT.search(ua):
        return 'script', None
    return 'other', None


# MCP clients that only list or check servers (registries, directories, uptime probes), by clientInfo.name.
PROBE_NAME = re.compile(r'probe|check|registry|catalog|index|scan|monitor|beat|rank|glama|smithery|pulse|directory|crawler|'
                        r'inspector|validator|health|test|atlas|bazaar|status', re.I)
RPC_ENTRIES = ('mcp', 'a2a')


def rpc_method(body):
    """JSON-RPC method name of one request body (batches count as 'batch'), or None."""
    if not body:
        return None
    try:
        data = json.loads(body[:65536])
    except (ValueError, UnicodeDecodeError):
        return 'unparsed'
    if isinstance(data, list):
        return 'batch'
    method = data.get('method') if isinstance(data, dict) else None
    return method if isinstance(method, str) and NAME.fullmatch(method) else ('other' if method else None)


def request_shape(method, path, headers):
    """Why a protocol request may fail, from its shape only (no values are stored)."""
    headers = headers or {}
    accept = (headers.get('accept') or '').lower()
    ctype = (headers.get('content-type') or '').split(';')[0].strip().lower()
    accept_class = ('json+sse' if 'application/json' in accept and 'text/event-stream' in accept else
                    'json' if 'application/json' in accept else 'sse' if 'text/event-stream' in accept else
                    'any' if '*/*' in accept else 'none' if not accept else 'other')
    return '|'.join((method, 'slash' if path.endswith('/') and len(path) > 1 else 'exact',
                     'accept=' + accept_class, 'ctype=' + (ctype if ctype in ('application/json', '') else 'other'),
                     'session=' + ('yes' if headers.get('mcp-session-id') else 'no')))


def mcp_client_name(body):
    """clientInfo.name of an MCP initialize request (a software name), or None."""
    if not body or b'"initialize"' not in body[:4096]:
        return None
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get('method') != 'initialize':
        return None
    info = (data.get('params') or {}).get('clientInfo') if isinstance(data.get('params'), dict) else None
    name = info.get('name') if isinstance(info, dict) else None
    match = NAME.fullmatch(name.strip()) if isinstance(name, str) else None
    return match.group(0) if match else 'unnamed'


def directory():
    """LOG_DIR/traffic, or None when LOG_DIR is unset (tests and ad-hoc runs keep counts in memory only;
    the service host always sets LOG_DIR for the frontend role)."""
    value = os.environ.get('LOG_DIR')
    return Path(value) / 'traffic' if value else None


def load_internal_ips(root=None):
    ips = {'127.0.0.1', '::1'}
    ips.update(v.strip() for v in os.environ.get('TRAFFIC_INTERNAL_IPS', '').split(',') if v.strip())
    root = root or directory()
    if root is not None:
        try:
            text = (Path(root) / 'internal-ips.txt').read_text()
            ips.update(line.strip() for line in text.splitlines() if line.strip() and not line.startswith('#'))
        except OSError:
            pass
    return ips


class Traffic:
    def __init__(self, root=None, clock=time.time):
        root = root if root is not None else directory()
        self.root, self.clock = (Path(root) if root is not None else None), clock
        self.lock = threading.Lock()
        self.internal_ips = load_internal_ips(self.root)
        self.day = None
        self.flushed = 0.0
        self._reset(self._today())

    def _today(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime('%Y-%m-%d')

    def _reset(self, day):
        self.day = day
        self.salt = secrets.token_bytes(32)  # memory only; a new day cannot be linked to the last
        self.requests = Counter()      # "entry|client" -> requests
        self.status = Counter()        # "entry|client|2xx" -> requests
        self.distinct = defaultdict(set)  # "entry|client" -> {short salted digests}
        self.bots = Counter()          # "bot|entry" -> requests
        self.mcp_clients = Counter()   # MCP clientInfo.name -> initialize requests (non-internal)
        self.rpc = Counter()           # "entry|rpc method|probe|real|unknown" -> requests (non-internal)
        self.errors = Counter()        # "entry|status|request shape|rpc method" -> 4xx/5xx protocol requests (non-internal)
        self.sessions = {}             # MCP session id -> 'probe' | 'real' (memory only, today)

    def observe(self, method, path, status, ip, ua, body=None, headers=None, response_headers=None, cause=None):
        entry = entry_of(method, path)
        if entry is None:
            return
        client, bot = client_of(ip, ua, self.internal_ips)
        key = entry + '|' + client
        digest = hmac.new(self.salt, ((ip or '') + '\n' + (ua or '')).encode('utf-8', 'replace'), hashlib.sha256).digest()[:8]
        with self.lock:
            today = self._today()
            if today != self.day:
                self._write_locked()
                self._reset(today)
            self.requests[key] += 1
            self.status[key + '|' + (str(status)[0] + 'xx' if isinstance(status, int) else 'other')] += 1
            bucket = self.distinct[key]
            if len(bucket) < 50_000:
                bucket.add(digest)
            if bot:
                self.bots[bot + '|' + entry] += 1
            if entry == 'mcp' and client != 'internal' and method == 'POST':
                name = mcp_client_name(body)
                if name:
                    self.mcp_clients[name] += 1
            if entry in RPC_ENTRIES and client != 'internal':
                rpc = rpc_method(body) if method == 'POST' else None
                kind = self._kind(entry, client, body, headers, response_headers)
                if rpc:
                    self.rpc[entry + '|' + rpc + '|' + kind] += 1
                if isinstance(status, int) and status >= 400:
                    # cause (11-10): our own security blocks (blocked_ip, policy_denied) are counted apart
                    # from protocol failures so a block window does not read as a client problem.
                    self.errors[entry + '|' + str(status) + (':' + cause if cause else '') + '|' + request_shape(method, path, headers) + '|' + (rpc or '-')] += 1
            if self.clock() - self.flushed >= FLUSH_SECONDS:
                self._write_locked()

    def _kind(self, entry, client, body, headers, response_headers):
        """'probe' for registries and checkers, 'real' for other clients, 'unknown' when it cannot be told."""
        if client == 'ai_bot':
            return 'probe'
        if entry != 'mcp':
            return 'real' if client in ('script', 'other', 'browser', 'headless') else 'unknown'
        name = mcp_client_name(body)
        if name:
            kind = 'probe' if PROBE_NAME.search(name) else 'real'
            sid = (response_headers or {}).get('mcp-session-id')
            if sid and len(self.sessions) < 100_000:
                self.sessions[sid[:64]] = kind
            return kind
        sid = (headers or {}).get('mcp-session-id')
        return self.sessions.get(sid[:64], 'unknown') if sid else 'unknown'

    def snapshot(self):
        with self.lock:
            return self._snapshot_locked()

    def _snapshot_locked(self):
        return {'day': self.day, 'updated': int(self.clock()), 'requests': dict(self.requests), 'status': dict(self.status),
                'distinct': {k: len(v) for k, v in self.distinct.items()}, 'bots': dict(self.bots),
                'mcp_clients': dict(self.mcp_clients.most_common(200)),
                'rpc': dict(self.rpc), 'errors': dict(self.errors.most_common(300))}

    def _write_locked(self):
        self.flushed = self.clock()
        if not self.requests or self.root is None:
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / f'{self.day}.{os.getpid()}.json'
            tmp = target.with_suffix('.tmp')
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as fh:
                json.dump(self._snapshot_locked(), fh, separators=(',', ':'))
            os.replace(tmp, target)
        except OSError:
            pass

    def flush(self):
        with self.lock:
            self._write_locked()


_SINGLETON = None


def recorder():
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Traffic()
    return _SINGLETON


# ---------------- summary ----------------

AGENT_ENTRIES = ('chat', 'mcp', 'a2a', 'agent_api', 'gateway')
EXTERNAL = ('browser', 'ai_bot', 'verifier', 'script', 'headless', 'other')


def load_day(root, day):
    merged = {'requests': Counter(), 'status': Counter(), 'distinct': Counter(), 'bots': Counter(), 'mcp_clients': Counter(),
              'rpc': Counter(), 'errors': Counter()}
    for path in sorted(Path(root).glob(day + '.*.json')):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for field in merged:
            merged[field].update(data.get(field) or {})
    return merged


GROWTH_ENTRIES = ('tasks', 'agent_pages', 'rankings', 'reports', 'connect')


def usage(day_data):
    """Real use versus registries and checkers for one day (the daily usage line, 11-10)."""
    req, dist, rpc = day_data['requests'], day_data['distinct'], day_data['rpc']
    count = lambda entry, methods, kind: sum(v for k, v in rpc.items()
                                             if k.split('|')[0] == entry and k.split('|')[1] in methods and k.split('|')[2] == kind)
    external = ('browser', 'script', 'other', 'headless', 'verifier')
    names = day_data['mcp_clients']
    return {'human_page_requests': sum(req.get(e + '|browser', 0) for e in ('home', 'page') + GROWTH_ENTRIES),
            'human_visitors': sum(dist.get(e + '|browser', 0) for e in ('home', 'page')),
            'chat_external': sum(req.get('chat|' + c, 0) for c in external),
            'explore_external': sum(req.get('explore|' + c, 0) for c in external),
            'mcp_sessions_real': count('mcp', ('initialize',), 'real'),
            'mcp_sessions_probe': count('mcp', ('initialize',), 'probe'),
            'mcp_tool_calls_real': count('mcp', ('tools/call',), 'real'),
            'mcp_tool_calls_probe': count('mcp', ('tools/call',), 'probe'),
            'mcp_tool_calls_unknown': count('mcp', ('tools/call',), 'unknown'),
            'a2a_messages_external': count('a2a', ('message/send', 'SendMessage', 'message/stream', 'SendStreamingMessage'), 'real'),
            'mcp_client_names_real': sum(1 for n in names if not PROBE_NAME.search(n)),
            'mcp_client_names_probe': sum(1 for n in names if PROBE_NAME.search(n)),
            'external_distinct_clients': sum(v for k, v in dist.items() if k.split('|')[1] in external),
            'protocol_errors': sum(day_data['errors'].values())}


def summarize(root, days=7, today=None):
    today = today or datetime.now(timezone.utc).date()
    rows = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        d = load_day(root, day)
        req, dist = d['requests'], d['distinct']
        get = lambda counter, entries, clients: sum(counter.get(e + '|' + c, 0) for e in entries for c in clients)
        rows.append({
            'day': day,
            'agent_requests': get(req, AGENT_ENTRIES, ('ai_bot', 'script', 'other', 'headless', 'verifier')),
            'agent_clients': get(dist, AGENT_ENTRIES, ('ai_bot', 'script', 'other', 'headless', 'verifier')),
            'chat_browser': get(req, ('chat',), ('browser',)),
            'mcp_clients': sum(d['mcp_clients'].values()),
            'mcp_client_names': len(d['mcp_clients']),
            'ai_bot_non_google': sum(v for k, v in d['bots'].items() if not k.split('|')[0].startswith('Google')),
            'ai_bot_google': sum(v for k, v in d['bots'].items() if k.split('|')[0].startswith('Google')),
            'human_pages': get(req, ('home', 'page'), ('browser',)),
            'human_visitors': get(dist, ('home', 'page'), ('browser',)),
            'growth_bot': sum(v for k, v in d['bots'].items() if k.split('|')[-1] in GROWTH_ENTRIES),
            'growth_human': get(req, GROWTH_ENTRIES, ('browser',)),
            'internal': sum(v for k, v in req.items() if k.endswith('|internal')),
            'external': sum(v for k, v in req.items() if not k.endswith('|internal')),
        })
    return rows


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else (directory() or Path('logs/service-frontend/traffic'))
    days = int(argv[2]) if len(argv) > 2 else 7
    rows = summarize(root, days)
    keys = list(rows[0]) if rows else []
    print('\t'.join(keys))
    for row in rows:
        print('\t'.join(str(row[k]) for k in keys))
    names, bots, growth = Counter(), Counter(), Counter()
    today = datetime.now(timezone.utc).date()
    for offset in range(days):
        d = load_day(root, (today - timedelta(days=offset)).isoformat())
        names.update(d['mcp_clients'])
        for key, value in d['bots'].items():
            bot, entry = key.split('|', 1)
            bots[bot] += value
            if entry in GROWTH_ENTRIES:
                growth[bot + ' ' + entry] += value
    print('MCP clients:', dict(names.most_common(15)))
    print('Bots:', dict(bots.most_common(15)))
    print('Growth pages by bot:', dict(growth.most_common(20)))
    errors, rows_usage = Counter(), []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        d = load_day(root, day)
        errors.update(d['errors'])
        rows_usage.append({'day': day, **usage(d)})
    print('Usage:')
    for row in rows_usage:
        print(' ', json.dumps(row))
    print('Protocol errors (entry|status|method|path|accept|ctype|session|rpc):', dict(errors.most_common(15)))


if __name__ == '__main__':
    main(sys.argv)

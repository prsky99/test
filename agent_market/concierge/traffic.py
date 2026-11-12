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


INTERNAL_MARK = 'internal'


def internal_request(ua, qa=None):
    """Our own measurements and checks: an internal User-Agent or the X-Agentcon-QA header (11-12 PM).

    The same rule the traffic report uses, plus the header, so visitors created by user_slo, the public full check
    or the deploy warm-up are counted apart. A forged header only moves the sender's own visit to 'internal'."""
    return bool(qa) or bool(INTERNAL_UA.search(ua or ''))


def client_of(ip, ua, internal_ips, qa=None):
    """Client class and, for bots, the bot name. X-Agentcon-QA (QA) marks our own measurements (11-12 PM)."""
    ua = ua or ''
    if qa or ip in internal_ips or INTERNAL_UA.search(ua):
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
def _classes():
    """The class lists of traffic_classes.json (11-12 PM: configuration, not a growing list in code)."""
    try:
        return json.loads((Path(__file__).with_name('traffic_classes.json')).read_text())
    except (OSError, ValueError):
        return {}


def _words(name):
    words = [w for w in _classes().get(name, []) if isinstance(w, str) and w]
    return re.compile('|'.join(re.escape(w) for w in words), re.I) if words else re.compile(r'(?!x)x')


# MCP clientInfo names of registries, evaluators and monitors ('probe' in the rpc counts and the funnel)
PROBE_NAME = _words('probe_client_names')
RPC_ENTRIES = ('mcp', 'a2a')
WELL_KNOWN_NAME = re.compile(r'/\.well-known/[A-Za-z0-9._-]{1,60}(?:/[A-Za-z0-9._-]{1,60})?')
# 4xx answers the protocols ask for (11-11): an auth-free MCP server answers 404 to OAuth discovery
# (RFC 9728, MCP authorization), and the MCP/A2A POST endpoints answer 405 to other methods. They
# are counted with ':spec' so they are not read as failures.
SPEC_404 = ('/.well-known/oauth-protected-resource', '/.well-known/oauth-authorization-server',
            '/.well-known/openid-configuration')


def spec_cause(entry, method, path, status):
    if status == 405 and entry in RPC_ENTRIES and method in ('GET', 'HEAD', 'DELETE'):
        return 'spec'
    if status == 404 and entry == 'well_known' and path.startswith(SPEC_404):
        return 'spec'
    return None


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


# 11-12 PM north star funnel: recommendation requests -> gateway connection pairs -> successful execution pairs.
RECOMMEND_TOOLS = ('find_agents', 'chat', 'search')
# Registry and uptime checkers by User-Agent. Narrower than PROBE_NAME (MCP clientInfo names), whose 'test',
# 'health' or 'index' would drop real clients when read from a User-Agent.
PROBE_UA = _words('probe_user_agents')
# Marketing contacts (11-12: ziwei-alliance-marketing sent 84 A2A messages a day)
OUTREACH_UA = _words('outreach_user_agents')


def tool_name(body):
    """params.name of one MCP tools/call request body, or None."""
    if not body or b'"tools/call"' not in body[:4096]:
        return None
    try:
        data = json.loads(body[:65536])
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get('method') != 'tools/call' or not isinstance(data.get('params'), dict):
        return None
    name = data['params'].get('name')
    return name if isinstance(name, str) and NAME.fullmatch(name) else None


def funnel_class(client, ua, client_name=None, session_kind=None):
    """'external', 'internal', 'probe' (registries, evaluators, monitors), 'outreach' (marketing contacts) or
    'crawler' (AI bots); only 'external' counts. CLIENT_NAME is an initialize request's clientInfo.name and
    SESSION_KIND what the session's initialize was judged to be, so later calls in a probe's session stay probe."""
    if client == 'internal':
        return 'internal'
    if client == 'ai_bot':
        return 'crawler'
    if OUTREACH_UA.search(ua or ''):
        return 'outreach'
    if (client in ('verifier',) or PROBE_UA.search(ua or '') or session_kind == 'probe'
            or (client_name and PROBE_NAME.search(client_name))):
        return 'probe'
    return 'external'


def recommend_surface(entry, method, body):
    """Which recommendation surface a request is (find_agents, chat, search, rest_chat, a2a, explore), or None."""
    if entry == 'explore' and method == 'GET':
        return 'explore'
    if entry == 'chat' and method == 'POST':
        return 'rest_chat'
    if entry == 'a2a' and method == 'POST' and rpc_method(body) in ('message/send', 'SendMessage'):
        return 'a2a'
    if entry == 'mcp' and method == 'POST':
        name = tool_name(body)
        return name if name in RECOMMEND_TOOLS else None
    return None


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
        self.bot_errors = Counter()    # "bot|entry|status[:cause]" -> 4xx/5xx answers to AI bots (11-11)
        self.mcp_clients = Counter()   # MCP clientInfo.name -> initialize requests (non-internal)
        self.rpc = Counter()           # "entry|rpc method|probe|real|unknown" -> requests (non-internal)
        self.errors = Counter()        # "entry|status|request shape|rpc method" -> 4xx/5xx protocol requests (non-internal)
        self.sessions = {}             # MCP session id -> 'probe' | 'real' (memory only, today)
        self.funnel = Counter()        # "recommend|surface|class|all|ok", "connect|class|...", "execute|class|..." (11-12)
        self.funnel_sets = defaultdict(set)  # "recommend|class" clients, "connect|class" / "execute|class" (client, agent) pairs

    def observe(self, method, path, status, ip, ua, body=None, headers=None, response_headers=None, cause=None,
                gateway=None):
        entry = entry_of(method, path)
        if entry is None:
            return
        client, bot = client_of(ip, ua, self.internal_ips, (headers or {}).get('x-agentcon-qa'))
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
                # 11-11: ClaudeBot got 151 4xx on agent pages and the day file only said "4xx"; the
                # status code (and our own block cause) per bot shows a 404 apart from a 429 or 403.
                if isinstance(status, int) and status >= 400:
                    self.bot_errors[bot + '|' + entry + '|' + str(status) + (':' + cause if cause else '')] += 1
            if entry == 'mcp' and client != 'internal' and method == 'POST':
                name = mcp_client_name(body)
                if name:
                    self.mcp_clients[name] += 1
            if isinstance(status, int) and status >= 400 and cause is None:
                cause = spec_cause(entry, method, path, status)
            if entry == 'well_known' and client != 'internal' and isinstance(status, int) and status >= 400:
                # Which discovery file was missing: the path name only, bounded (11-11).
                name = WELL_KNOWN_NAME.fullmatch(path)
                key = ('well_known|' + str(status) + (':' + cause if cause else '') + '|' + method + '|'
                       + (name.group(0) if name else 'other') + '|' + client)
                if key in self.errors or len(self.errors) < 2000:  # scanners cannot grow it without bound
                    self.errors[key] += 1
            if entry in RPC_ENTRIES and client != 'internal':
                rpc = rpc_method(body) if method == 'POST' else None
                kind = self._kind(entry, client, body, headers, response_headers)
                if rpc:
                    self.rpc[entry + '|' + rpc + '|' + kind] += 1
                if isinstance(status, int) and status >= 400:
                    # cause (11-10): our own security blocks (blocked_ip, policy_denied) are counted apart
                    # from protocol failures so a block window does not read as a client problem.
                    self.errors[entry + '|' + str(status) + (':' + cause if cause else '') + '|' + request_shape(method, path, headers) + '|' + (rpc or '-')] += 1
            self._funnel_locked(entry, method, status, ua, client, body, digest, gateway, headers)
            if self.clock() - self.flushed >= FLUSH_SECONDS:
                self._write_locked()

    def _funnel_locked(self, entry, method, status, ua, client, body, digest, gateway, headers=None):
        """North star funnel (11-12 PM): recommendation requests, gateway connections and successful executions.

        GATEWAY is what the gateway handler decided: {'step': 'connect'|'execute', 'ok': bool, 'rid': int}. Pairs
        are (this day's salted client digest, agent id); nothing that identifies a client is kept."""
        sid = ((headers or {}).get('mcp-session-id') or '')[:64]
        cls = funnel_class(client, ua, mcp_client_name(body) if entry == 'mcp' else None,
                           self.sessions.get(sid) if sid else None)
        ok = isinstance(status, int) and 200 <= status < 300
        surface = recommend_surface(entry, method, body)
        if surface:
            self.funnel['recommend|' + surface + '|' + cls + '|all'] += 1
            if ok:
                self.funnel['recommend|' + surface + '|' + cls + '|ok'] += 1
            bucket = self.funnel_sets['recommend|' + cls]
            if len(bucket) < 50_000:
                bucket.add(digest)
        # /api/gateway/* connections and executions, and the in-session MCP 'call' tool on /mcp (11-12 PM)
        if entry in ('gateway', 'mcp') and isinstance(gateway, dict) and gateway.get('step') in ('connect', 'execute'):
            step, done = gateway['step'], bool(gateway.get('ok')) and ok
            self.funnel[step + '|' + cls + '|attempt'] += 1
            if done:
                self.funnel[step + '|' + cls + '|ok'] += 1
                bucket = self.funnel_sets[step + '|' + cls]
                if len(bucket) < 50_000:
                    bucket.add(digest + str(gateway.get('rid')).encode())

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
                'bot_errors': dict(self.bot_errors),
                'mcp_clients': dict(self.mcp_clients.most_common(200)),
                'rpc': dict(self.rpc), 'errors': dict(self.errors.most_common(300)),
                'funnel': dict(self.funnel), 'funnel_distinct': {k: len(v) for k, v in self.funnel_sets.items()}}

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
              'rpc': Counter(), 'errors': Counter(), 'bot_errors': Counter()}
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
    names, bots, growth, bot_errors = Counter(), Counter(), Counter(), Counter()
    today = datetime.now(timezone.utc).date()
    for offset in range(days):
        d = load_day(root, (today - timedelta(days=offset)).isoformat())
        names.update(d['mcp_clients'])
        bot_errors.update(d['bot_errors'])
        for key, value in d['bots'].items():
            bot, entry = key.split('|', 1)
            bots[bot] += value
            if entry in GROWTH_ENTRIES:
                growth[bot + ' ' + entry] += value
    print('MCP clients:', dict(names.most_common(15)))
    print('Bots:', dict(bots.most_common(15)))
    print('Growth pages by bot:', dict(growth.most_common(20)))
    print('Bot 4xx/5xx (bot|entry|status[:cause]):', dict(bot_errors.most_common(20)))
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

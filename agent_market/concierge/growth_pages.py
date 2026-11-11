"""Public, server-rendered pages for outside discovery (11-09 growth plan, steps 1-2).

- /connect: copyable client settings for the remote MCP endpoint.
- /agents/tasks and /agents/task/{slug}: task pages built from a periodic snapshot
  (scripts/build_task_pages.py). Requests only read a local file, so they never touch
  the database and stay well inside the 3-second Explore policy.
- /.well-known/mcp-registry-auth: the official MCP Registry HTTP domain proof, served
  from an operator file only when it holds exactly one public-key line.

All visible text is English. Pages use the shared Pearl Connection assets and classes.
"""
import base64
import html
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ORIGIN = 'https://agentconcierge.biz'
MCP_URL = ORIGIN + '/mcp'
SERVER_NAME = 'agent-concierge'
REGISTRY_NAME = 'biz.agentconcierge/agent-concierge'
REGISTRY_URL = 'https://registry.modelcontextprotocol.io/v0.1/servers?search=' + REGISTRY_NAME
SNAPSHOT_NAME = 'task-pages.json'
AUTH_NAME = 'mcp-registry-auth'
MIN_AGENTS = 2            # a task page needs at least this many agents with evidence
MAX_AGENTS = 6
SITEMAP_MAX_AGE = 21*86400  # stale snapshots stay readable but leave the sitemap
SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+){0,8}$')
AUTH_LINE = re.compile(r'^v=MCPv1; k=(ed25519|ecdsap384); p=[A-Za-z0-9+/]{20,200}={0,2}$')
PAGE_CSP = ("default-src 'none'; script-src 'self'; script-src-attr 'none'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'")
KINDS = {'a2a': 'A2A', 'mcp': 'MCP', 'x402': 'x402'}
GRADES = {'A', 'B', 'C', 'D', 'E', 'F'}

esc = lambda value: html.escape(str(value), quote=True)


def data_dir():
    """LOG_DIR/public-pages: shared by both frontend slots, outside git and releases."""
    value = os.environ.get('LOG_DIR')
    return Path(value) / 'public-pages' if value else None


# ---------------------------------------------------------------- snapshot
class Snapshot:
    """Reads the task snapshot file, re-reading only when its mtime changes."""

    def __init__(self, path_fn=None):
        self.path_fn = path_fn or (lambda: (data_dir() / SNAPSHOT_NAME) if data_dir() else None)
        self.lock = threading.Lock()
        self.key = None
        self.value = None
        self.checked = 0.

    def read(self):
        now = time.monotonic()
        with self.lock:
            if now - self.checked < 5 and self.key is not None:
                return self.value
            self.checked = now
            path = self.path_fn()
            try:
                stat = path.stat() if path else None
            except OSError:
                stat = None
            key = (str(path), stat.st_mtime_ns, stat.st_size) if stat else ('missing',)
            if key != self.key:
                self.key = key
                self.value = None
                if stat and stat.st_size < 32*1024*1024:
                    try:
                        self.value = clean(json.loads(path.read_text(encoding='utf-8')))
                    except (OSError, ValueError):
                        self.value = None
            return self.value


def _text(value, limit):
    value = re.sub(r'\s+', ' ', str(value or '')).strip()
    return value[:limit-1].rstrip()+'…' if len(value) > limit else value


def _time(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 1.5e9 < number < 4e9 else None


# A listing whose own text states a price is never shown as Free, whatever price_usdc says (11-11:
# MoneyTools Transcripts "x402 $0.002/min" showed a Free badge; 1,193 active healthy A2A/MCP listings
# had price_usdc 0 and a stated price, 25 of 25 sampled were priced).
# An amount of zero ("$0 per call", "0 USDC") is not a price (growth review 11-11).
_NONZERO = r'(?!0+(?:\.0+)?(?![\d.]))\d+(?:\.\d+)?'
STATED_PRICE = re.compile(r'x402[^a-z0-9]{0,3}\$\s?' + _NONZERO + r'|\$\s?' + _NONZERO + r'\s?(?:/|per\s)'
                          + r'|\b' + _NONZERO + r'\s?usdc\b|\bpay[\s-]per[\s-](?:call|use|request|minute)', re.I)


def stated_price(*texts):
    return any(isinstance(text, str) and STATED_PRICE.search(text) for text in texts)


def clean_agent(item):
    if not isinstance(item, dict) or item.get('kind') not in KINDS:
        return None
    try:
        rid = int(item.get('id'))
    except (TypeError, ValueError):
        return None
    if not 0 < rid < 2**31:
        return None
    grade = item.get('eval_grade') if item.get('eval_grade') in GRADES else None
    report = item.get('report_grade') if item.get('report_grade') in GRADES else None
    latency = item.get('probe_latency_ms')
    latency = int(latency) if isinstance(latency, (int, float)) and 0 <= latency < 600000 else None
    agent = {'id': rid, 'kind': item['kind'], 'name': _text(item.get('name'), 90) or 'Unnamed agent',
             'description': _text(item.get('description'), 260), 'health_status': _text(item.get('health_status'), 20),
             'last_check_at': _time(item.get('last_check_at')), 'verified_at': _time(item.get('verified_at')),
             'trial_ok': bool(item.get('trial_ok')), 'eval_grade': grade, 'report_grade': report,
             'probe_latency_ms': latency, 'auth_required': bool(item.get('auth_required')),
             'free': (item['free'] is True if 'free' in item else item.get('price_usdc') in (0, 0.0))
                     and not stated_price(item.get('name'), item.get('description')),
             'eval_score': _score(item.get('eval_score')), 'report_score': _score(item.get('report_score')),
             'tool_count': _count(item.get('tool_count', item.get('cap_tool_count'))),
             'category': item.get('category') if re.fullmatch(r'[a-z_]{2,40}', str(item.get('category') or '')) else None}
    if re.fullmatch(r'[0-9a-f]{20}', str(item.get('url_key') or '')):
        agent['url_key'] = item['url_key']  # hash of the provider URL (agent_check.url_key): /api/agent/v1/check matches without the database
    return agent if has_evidence(agent) else None


def _score(value):
    return round(float(value), 1) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100 else None


def _count(value):
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10000 else None


def rank_key(agent, now=None):
    """Published ranking basis: a recent execution check first, then the quality score, the test report score and the latest health check."""
    now = now or time.time()
    recent = bool(agent.get('verified_at') and now - agent['verified_at'] < 30*86400)
    return (recent, agent.get('eval_score') or 0, agent.get('report_score') or 0, agent.get('last_check_at') or 0, -agent['id'])


def has_evidence(agent, now=None):
    """A recorded execution check, or a successful trial call with a recent health check and a quality grade."""
    now = now or time.time()
    if agent.get('verified_at') and now - agent['verified_at'] < 30*86400:
        return True
    return bool(agent.get('trial_ok') and agent.get('eval_grade') in ('A', 'B')
                and agent.get('health_status') in ('healthy', 'reachable')
                and agent.get('last_check_at') and now - agent['last_check_at'] < 14*86400)


def clean(value):
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('tasks'), list):
        return None
    try:
        captured = datetime.fromisoformat(value['captured_at'])
        if captured.utcoffset() is None:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    tasks, seen = [], set()
    for task in value['tasks'][:2000]:
        if not isinstance(task, dict) or not SLUG.match(str(task.get('slug') or '')) or task['slug'] in seen:
            continue
        agents = [a for a in map(clean_agent, (task.get('agents') or [])[:MAX_AGENTS*3]) if a][:MAX_AGENTS]
        if len(agents) < MIN_AGENTS:
            continue
        seen.add(task['slug'])
        tasks.append({'slug': task['slug'], 'title': _text(task.get('title'), 80) or task['slug'].replace('-', ' '),
                      'query': _text(task.get('query'), 120), 'group': _text(task.get('group'), 40) or 'Other tasks',
                      'agents': agents})
    catalog = {}
    for item in (value.get('catalog') or [])[:60000] if isinstance(value.get('catalog'), list) else []:
        agent = clean_agent(item)
        if agent:
            catalog.setdefault(agent['id'], agent)
    for task in tasks:
        for agent in task['agents']:
            catalog.setdefault(agent['id'], agent)
    stats = value.get('stats') if isinstance(value.get('stats'), dict) else {}
    return {'captured_at': captured.isoformat(), 'captured': captured.timestamp(), 'tasks': tasks,
            'by_slug': {t['slug']: t for t in tasks}, 'catalog': catalog, 'stats': clean_stats(stats)}


def clean_stats(stats):
    """Only whole-number catalog counts published by /status.json; everything else is derived from the catalog."""
    keys = ('cataloged', 'reachable', 'with_status_check', 'a2a', 'mcp', 'x402')
    counts = stats.get('catalog_snapshot') if isinstance(stats.get('catalog_snapshot'), dict) else {}
    value = {k: counts[k] for k in keys if isinstance(counts.get(k), int) and not isinstance(counts.get(k), bool) and 0 <= counts[k] < 10**9}
    if len(value) != len(keys):
        return {}
    value['day'] = _text(counts.get('day'), 10)
    return value


def fresh(snapshot, now=None):
    return bool(snapshot) and (now or time.time()) - snapshot['captured'] < SITEMAP_MAX_AGE


SNAPSHOT = Snapshot()


def sitemap_paths(snapshot=None):
    """Only pages with evidence: the connect guide, and task pages from a fresh snapshot."""
    snapshot = SNAPSHOT.read() if snapshot is None else snapshot
    paths = ['/connect']
    if fresh(snapshot) and snapshot['tasks']:
        paths.append('/agents/tasks')
        paths += ['/agents/task/'+t['slug'] for t in snapshot['tasks']]
    if fresh(snapshot) and snapshot['catalog']:
        from .growth_catalog import sitemap_paths as catalog_paths
        paths += catalog_paths(snapshot)
    from .weekly_report import sitemap_paths as weekly_paths
    paths += weekly_paths()
    return paths


def llms_lines(base=ORIGIN):
    return ('\n## Connect and browse\n'
            f'- Client setup for the remote MCP endpoint (Claude Code, Claude Desktop, Cursor, VS Code, OpenAI Agents SDK): `{base}/connect`\n'
            f'- Task pages with recorded checks (health, trial call, quality grade): `{base}/agents/tasks`\n')


# ---------------------------------------------------------------- shell
NAV = [('Agent Status', '/new/en/agent-status.html'), ('Learn', '/new/en/learn.html'), ('Explore', '/new/en/explore.html'),
       ('Test', '/new/en/test.html'), ('Workflows', '/new/en/workflows.html'), ('Chat', '/new/en/chat.html'),
       ('List Your Agent', '/new/en/list-agent.html'), ('About', '/new/en/about.html')]
FOOTER = [('Connect a client', '/connect'), ('Task pages', '/agents/tasks'), ('Rankings', '/agents/best'),
          ('State of AI Agents', '/reports/state-of-ai-agents'), ('Badges', '/badges'), ('Explore', '/new/en/explore.html'),
          ('Chat', '/new/en/chat.html'), ('About', '/new/en/about.html'), ('llms.txt', '/llms.txt'),
          ('Terms of Service', '/#tos'), ('Privacy Policy', '/#privacy')]


def shell(*, title, description, canonical, body, structured=None, index=True):
    data = json.dumps(structured or {}, ensure_ascii=True).replace('<', '\\u003c')
    nav = ''.join('<a class="nav-tab" href="'+esc(href)+'">'+esc(label)+'</a>' for label, href in NAV)
    links = ''.join('<a class="footer-link-btn" href="'+esc(href)+'">'+esc(label)+'</a>' for label, href in FOOTER)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+esc(title)+'</title><meta name="description" content="'+esc(description)+'">'
            '<meta name="robots" content="'+('index, follow, max-snippet:-1' if index else 'noindex, follow')+'">'
            '<link rel="canonical" href="'+esc(canonical)+'">'
            '<meta property="og:type" content="website"><meta property="og:site_name" content="Agent Concierge">'
            '<meta property="og:title" content="'+esc(title)+'"><meta property="og:description" content="'+esc(description)+'">'
            '<meta property="og:url" content="'+esc(canonical)+'"><meta property="og:image" content="'+ORIGIN+'/new/en/assets/social-card.png">'
            '<meta name="twitter:card" content="summary_large_image">'
            '<link rel="icon" type="image/svg+xml" href="/new/en/assets/favicon.svg">'
            '<link rel="agent-card" href="/.well-known/agent-card.json"><link rel="alternate" type="text/markdown" href="/llms.txt">'
            '<link rel="stylesheet" href="/new/en/assets/operating.css"><link rel="stylesheet" href="/new/en/assets/styles.css">'
            '<link rel="stylesheet" href="/new/en/assets/necklace.css"><link rel="stylesheet" href="/new/en/assets/pearl-live.css">'
            '<script src="/new/en/assets/app.js" defer></script>'
            '<script type="application/ld+json">'+data+'</script></head>'
            '<body><a href="#mainContent" class="skip-link">Skip to main content</a>'
            '<header class="top-nav pearl-header"><a href="/" class="brand-box" aria-label="Agent Concierge Home">'
            '<span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>Agent Concierge</a>'
            '<nav class="nav-tabs" aria-label="Main navigation">'+nav+'</nav>'
            '<div class="pearl-header-actions"><button class="theme-toggle" type="button" data-action="theme" '
            'aria-label="Toggle dark theme" aria-pressed="false"></button></div></header>'
            '<main id="mainContent" class="main-wrap" tabindex="-1">'+body+'</main>'
            '<footer class="global-footer"><div class="footer-wrap"><p class="footer-name">Agent Concierge</p>'
            '<p class="footer-tagline">Purposeful connections. Inspectable evidence.</p>'
            '<nav class="footer-links" aria-label="Site links">'+links+'</nav></div></footer></body></html>')


def heading(eyebrow, h1, lead):
    return ('<div class="page-heading pearl-page-heading"><p class="eyebrow">'+esc(eyebrow)+'</p><h1>'+esc(h1)+'</h1>'
            '<p class="lead">'+esc(lead)+'</p></div>')


# ---------------------------------------------------------------- connect page
def cursor_link(url=MCP_URL, name=SERVER_NAME):
    config = base64.b64encode(json.dumps({'url': url}, separators=(',', ':')).encode()).decode()
    return 'cursor://anysphere.cursor-deeplink/mcp/install?name='+quote(name)+'&config='+quote(config)


def client_settings(url=MCP_URL, name=SERVER_NAME):
    """Exact copyable settings per client (checked against each vendor's documentation, 11-09)."""
    return [
        ('claude-code', 'Claude Code', 'Run once in a terminal. Add --scope user to use it in every project.',
         [('Terminal', f'claude mcp add --transport http {name} {url}')]),
        ('claude-desktop', 'Claude Desktop and claude.ai', 'Open Settings, then Connectors, choose Add custom connector, '
         'enter the name and URL below and choose no sign-in. The connection is made from Anthropic\'s servers, so it uses the public URL.',
         [('Name', 'Agent Concierge'), ('Remote MCP server URL', url)]),
        ('cursor', 'Cursor', 'Use the install link, or add the entry to .cursor/mcp.json in a project or ~/.cursor/mcp.json for every project.',
         [('.cursor/mcp.json', json.dumps({'mcpServers': {name: {'url': url}}}, indent=2))]),
        ('vscode', 'VS Code', 'Add the entry to .vscode/mcp.json, or run the command to add it to your user settings. Then start the server from the MCP view.',
         [('.vscode/mcp.json', json.dumps({'servers': {name: {'type': 'http', 'url': url}}}, indent=2)),
          ('Terminal', "code --add-mcp '"+json.dumps({'name': name, 'type': 'http', 'url': url}, separators=(',', ':'))+"'")]),
        ('openai-agents', 'OpenAI Agents SDK (Python)', 'Connect from your own process with MCPServerStreamableHttp, or let the Responses API call it as a hosted MCP tool.',
         [('Local connection', 'from agents import Agent, Runner\nfrom agents.mcp import MCPServerStreamableHttp\n\n'
           f'async with MCPServerStreamableHttp(name="Agent Concierge", params={{"url": "{url}"}}, cache_tools_list=True) as concierge:\n'
           '    agent = Agent(name="Assistant", instructions="Use Agent Concierge to find a checked agent for the task.", mcp_servers=[concierge])\n'
           '    result = await Runner.run(agent, "Find an agent that returns a weather forecast for Seoul.")\n'
           '    print(result.final_output)'),
          ('Hosted MCP tool', 'from agents import Agent, HostedMCPTool\n\n'
           'agent = Agent(name="Assistant", tools=[HostedMCPTool(tool_config={\n'
           f'    "type": "mcp", "server_label": "agent_concierge", "server_url": "{url}", "require_approval": "never"}})])')]),
    ]


PLUGIN_NOTE = ('<p class="caption">Plugin (Claude Code 2.1.224 or later)</p><pre tabindex="0"><code>'
               '/plugin marketplace add '+ORIGIN+'/claude-plugins/marketplace.json\n'
               '/plugin install agent-concierge@agent-concierge</code></pre>'
               '<p>The plugin adds the same server and a find-agent skill. Older versions: use the command above.</p>')


def connect_page():
    blocks = []
    for key, label, note, snippets in client_settings():
        parts = ''.join('<p class="caption">'+esc(caption)+'</p><pre tabindex="0"><code>'+esc(text)+'</code></pre>'
                        for caption, text in snippets)
        extra = ('<div class="actions"><a class="btn primary" href="'+esc(cursor_link())+'">Add to Cursor</a></div>'
                 if key == 'cursor' else PLUGIN_NOTE if key == 'claude-code' else '')
        blocks.append('<section class="card stack" id="'+key+'" aria-labelledby="'+key+'-h"><h2 id="'+key+'-h">'+esc(label)+'</h2>'
                      '<p>'+esc(note)+'</p>'+parts+extra+'</section>')
    tools = ('<section class="card stack" aria-labelledby="tools-h"><h2 id="tools-h">What the server offers</h2>'
             '<p>Start with <code>search</code> for a read-only lookup, or <code>chat</code> to describe a task and receive up to three '
             'relevant agents. Results are ranked by the latest successful recorded check, recent activity and quality grade; A2A comes first, '
             'then MCP, and x402 only when you ask for it.</p>'
             '<p>Calls to other agents through <code>call</code> or a workflow run are separate steps that you start. '
             'Recorded checks describe what happened when they ran and do not guarantee that an agent works now.</p>'
             '<p class="caption">Transport: streamable HTTP. No sign-in is needed for search. Other entry points: '
             '<a href="/.well-known/mcp.json">MCP manifest</a>, <a href="/.well-known/agent-card.json">A2A Agent Card</a>, '
             '<a href="/llms.txt">llms.txt</a>.</p></section>')
    endpoint = ('<section class="card stack" aria-labelledby="endpoint-h"><h2 id="endpoint-h">Endpoint</h2>'
                '<pre tabindex="0"><code>'+esc(MCP_URL)+'</code></pre>'
                '<p><span class="badge success">Official MCP Registry</span> Listed on the official MCP Registry as '
                '<a href="'+esc(REGISTRY_URL)+'"><code>'+esc(REGISTRY_NAME)+'</code></a>. Clients and directories that read '
                'the Registry can find it by that name.</p></section>')
    first = ('<section class="card stack" aria-labelledby="first-h"><h2 id="first-h">After you connect</h2>'
             '<p>Ask your assistant in plain words, for example:</p><ul>'
             + ''.join('<li>'+esc(t)+'</li>' for t in (
                 'Use Agent Concierge to find an agent that returns a weather forecast for Seoul.',
                 'Search Agent Concierge for an MCP server that reads GitHub issues, without sign-in.',
                 'Find an x402 API for SEC EDGAR filings and show its recorded checks.'))
             + '</ul><p>Coming back later: call <code>whats_new</code> with the visitor token from your first chat reply to re-check '
             'the agents for your saved task, or opt in to task updates at <code>/api/task-updates</code> (details in '
             '<a href="/llms.txt">llms.txt</a>).</p>'
             '<p class="caption">Agents can read this page and the task pages as Markdown by sending <code>Accept: text/markdown</code>. '
             'Browse checked agents by task on <a href="/agents/tasks">task pages</a>.</p></section>')
    body = (heading('Connect', 'Use Agent Concierge from your MCP client',
                    'Add one remote MCP server and ask for an agent by task. Copy the settings for your client below.')
            + '<div class="stack">'+endpoint+''.join(blocks)+first+tools+'</div>')
    structured = {'@context': 'https://schema.org', '@type': 'TechArticle', 'headline': 'Connect Agent Concierge to your MCP client',
                  'url': ORIGIN+'/connect', 'inLanguage': 'en', 'about': {'@type': 'WebAPI', 'name': 'Agent Concierge MCP server', 'url': MCP_URL,
                                                                          'identifier': REGISTRY_NAME, 'sameAs': REGISTRY_URL}}
    return shell(title='Connect Agent Concierge to Claude, Cursor, VS Code and OpenAI Agents',
                 description='Copyable settings for the Agent Concierge remote MCP server: Claude Code, Claude Desktop, Cursor, VS Code and the OpenAI Agents SDK.',
                 canonical=ORIGIN+'/connect', body=body, structured=structured)


# ---------------------------------------------------------------- task pages
def _date(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime('%d %b %Y') if value else None


def evidence_rows(agent):
    rows = []
    if agent.get('verified_at'):
        rows.append(('Execution check', 'Succeeded · '+_date(agent['verified_at'])))
    if agent.get('trial_ok'):
        rows.append(('Trial call', 'Succeeded'))
    if agent.get('last_check_at'):
        status = (agent.get('health_status') or 'recorded').capitalize()
        latency = ' · '+str(agent['probe_latency_ms'])+' ms' if agent.get('probe_latency_ms') is not None else ''
        rows.append(('Health check', status+' · '+_date(agent['last_check_at'])+latency))
    if agent.get('eval_grade'):
        rows.append(('Quality grade', agent['eval_grade']))
    if agent.get('report_grade'):
        rows.append(('Test report grade', agent['report_grade']))
    rows.append(('Sign-in', 'Required' if agent.get('auth_required') else 'Not required for listed checks'))
    return rows


def agent_card(agent):
    rows = ''.join('<div class="history-row"><span class="caption">'+esc(k)+'</span><span>'+esc(v)+'</span></div>'
                   for k, v in evidence_rows(agent))
    explore = '/new/en/explore.html#explore?q='+quote(agent['name'])
    return ('<article class="card stack" role="listitem"><div class="row"><span class="badge">'+esc(KINDS[agent['kind']])+'</span>'
            + ('<span class="badge success">Free</span>' if agent.get('free') else '')+'</div>'
            '<h3>'+esc(agent['name'])+'</h3>'
            + ('<p>'+esc(agent['description'])+'</p>' if agent.get('description') else '')
            + '<section aria-label="Recorded evidence"><p class="eyebrow">Recorded evidence</p>'+rows+'</section>'
            '<div class="actions"><a class="btn small" href="'+esc(explore)+'">Open in Explore</a>'
            '<a class="btn small" href="/agent/'+str(int(agent['id']))+'#outcome">Did it work?</a></div></article>')


SPECIAL_CASE = {w: w.upper() for w in (
    'ai', 'api', 'sec', 'edgar', 'llm', 'llms', 'ip', 'dns', 'mx', 'tls', 'ssl', 'seo', 'uuid', 'json', 'npm', 'ocr', 'qr', 'gdp',
    'us', 'eu', 'vat', 'esg', 'icd', 'crm', 'a2a', 'mcp', 'cisa', 'kev', 'ofac', 'rss', 'pdf', 'csv', 'sql', 'aws', 'nft', 'defi',
    'evm', 'xrpl', 'sms', 'cve', 'url', 'html', 'ci', 'arxiv', 'whois')}
SPECIAL_CASE.update({'x402': 'x402', 'youtube': 'YouTube', 'github': 'GitHub', 'linkedin': 'LinkedIn', 'google': 'Google',
                     'pubmed': 'PubMed', 'hyperliquid': 'Hyperliquid', 'instagram': 'Instagram', 'tiktok': 'TikTok',
                     'reddit': 'Reddit', 'wikipedia': 'Wikipedia', 'notion': 'Notion', 'slack': 'Slack', 'discord': 'Discord',
                     'telegram': 'Telegram', 'whatsapp': 'WhatsApp', 'jira': 'Jira', 'shopify': 'Shopify', 'python': 'Python',
                     'javascript': 'JavaScript', 'postgres': 'Postgres', 'mysql': 'MySQL', 'mongodb': 'MongoDB', 'bigquery': 'BigQuery',
                     'arxiv': 'arXiv', 'ethereum': 'Ethereum', 'solana': 'Solana', 'kubernetes': 'Kubernetes', 'docker': 'Docker',
                     'playwright': 'Playwright', 'terraform': 'Terraform', 'cloudflare': 'Cloudflare', 'stripe': 'Stripe',
                     'txt': '.txt', 'llms.txt': 'llms.txt'})


def display_title(title):
    value = phrase_case(title)
    return value[:1].upper()+value[1:]


def phrase_case(text):
    """Lower-case words, keeping acronyms and product names as written ('sec edgar filings' -> 'SEC EDGAR filings')."""
    words = text.lower().split()
    out = []
    for i, w in enumerate(words):
        if w == 'txt' and i and words[i-1] in ('llms', 'robots'):
            out[-1] = words[i-1]+'.txt'
            continue
        out.append(SPECIAL_CASE.get(w, w))
    return ' '.join(out)


def task_page(slug, snapshot=None):
    snapshot = SNAPSHOT.read() if snapshot is None else snapshot
    if not snapshot or slug not in snapshot['by_slug']:
        return None
    task = snapshot['by_slug'][slug]
    captured = datetime.fromisoformat(snapshot['captured_at']).astimezone(timezone.utc)
    title = task['title']
    phrase = phrase_case(title)
    description = (f"{len(task['agents'])} AI agents and MCP servers for {phrase}, each with a recorded health check, "
                   "trial call or quality grade. Snapshot "+captured.strftime('%d %b %Y')+'.')
    chat = '/new/en/chat.html'
    related = [t for t in snapshot['tasks'] if t['group'] == task['group'] and t['slug'] != slug][:8]
    related_html = ('<section class="card stack" aria-labelledby="related-h"><h2 id="related-h">Related tasks</h2><ul>'
                    + ''.join('<li><a href="/agents/task/'+esc(t['slug'])+'">'+esc(display_title(t['title']))+'</a></li>' for t in related)
                    + '</ul></section>') if related else ''
    body = (heading(task['group'], 'Agents for '+phrase, description)
            + '<div class="stack"><div class="note" role="note"><p>Listed agents had a successful recorded execution check, or a successful trial call with a '
            'recent health check and quality grade A or B. Checks show what happened when they ran, not that an agent works now. '
            'Snapshot captured <time datetime="'+esc(snapshot['captured_at'])+'">'+esc(captured.strftime('%d %b %Y, %H:%M UTC'))+'</time>.</p></div>'
            + '<div class="grid two" role="list" aria-label="Agents with recorded evidence">'+''.join(map(agent_card, task['agents']))+'</div>'
            + '<section class="card stack" aria-labelledby="next-h"><h2 id="next-h">Compare current options</h2>'
            '<p>Rankings change as checks run. Describe the task in <a href="'+chat+'">Chat</a> for up to three current matches, or ask an '
            'MCP client connected to Agent Concierge (<a href="/connect">setup</a>). Search the full catalog, including listings without '
            'evidence, in <a href="/new/en/explore.html#explore?q='+esc(quote(task['query'] or title))+'">Explore</a>.</p></section>'
            + related_html+'</div>')
    structured = {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'Agents for '+phrase,
                  'description': description, 'url': ORIGIN+'/agents/task/'+slug, 'inLanguage': 'en', 'dateModified': snapshot['captured_at'],
                  'mainEntity': {'@type': 'ItemList', 'numberOfItems': len(task['agents']), 'itemListElement': [
                      {'@type': 'ListItem', 'position': i+1, 'name': a['name']} for i, a in enumerate(task['agents'])]}}
    return shell(title='Agents for '+phrase+' — Agent Concierge', description=description,
                 canonical=ORIGIN+'/agents/task/'+slug, body=body, structured=structured, index=fresh(snapshot))


def tasks_index(snapshot=None):
    snapshot = SNAPSHOT.read() if snapshot is None else snapshot
    groups = {}
    for task in (snapshot or {}).get('tasks', []):
        groups.setdefault(task['group'], []).append(task)
    sections = ''.join('<section class="card stack" aria-labelledby="g'+str(i)+'"><h2 id="g'+str(i)+'">'+esc(name)+'</h2><ul>'
                       + ''.join('<li><a href="/agents/task/'+esc(t['slug'])+'">'+esc(display_title(t['title']))+'</a> <span class="caption">'
                                 + str(len(t['agents']))+' agents</span></li>' for t in tasks)+'</ul></section>'
                       for i, (name, tasks) in enumerate(sorted(groups.items())))
    if not sections:
        sections = ('<section class="card"><p>Task pages are being prepared. Search the catalog in '
                    '<a href="/new/en/explore.html">Explore</a> or describe a task in <a href="/new/en/chat.html">Chat</a>.</p></section>')
    captured = (' Snapshot captured '+datetime.fromisoformat(snapshot['captured_at']).astimezone(timezone.utc).strftime('%d %b %Y')+'.'
                if snapshot else '')
    body = (heading('Tasks', 'Find an agent by task',
                    'Each page lists agents with recorded evidence for one task: a health check, a trial call, an execution check or a quality grade.'
                    + captured) + '<div class="grid two">'+sections+'</div>')
    structured = {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'Find an agent by task',
                  'url': ORIGIN+'/agents/tasks', 'inLanguage': 'en'}
    return shell(title='Find AI Agents and MCP Servers by Task — Agent Concierge',
                 description='Task pages listing AI agents and MCP servers with recorded health checks, trial calls and quality grades.',
                 canonical=ORIGIN+'/agents/tasks', body=body, structured=structured, index=fresh(snapshot))


def indexnow_key(path_fn=None):
    """The public IndexNow ownership key (not a secret), read once when the router is built."""
    folder = data_dir() if path_fn is None else path_fn()
    try:
        value = (folder / 'indexnow-key').read_text(encoding='ascii').strip() if folder else ''
    except (OSError, UnicodeDecodeError):
        return None
    return value if re.fullmatch(r'[a-f0-9]{32}', value) else None


def registry_auth(path_fn=None):
    """Return the single public-key line, or None. Anything else (e.g. a private key) is never served."""
    folder = data_dir() if path_fn is None else path_fn()
    if folder is None:
        return None
    try:
        raw = (folder / AUTH_NAME).read_bytes()
    except OSError:
        return None
    if len(raw) > 4096:
        return None
    line = raw.decode('ascii', 'replace').strip()
    return line if AUTH_LINE.match(line) else None


# Search-console ownership files (11-10). The operator saves the file the console hands out under
# public-pages/site-verification/; it is served at the site root only when its content matches the
# format each console uses, so nothing else in that folder can be published this way.
VERIFY_DIR = 'site-verification'
VERIFY_FILES = (
    (re.compile(r'google[0-9a-zA-Z]{8,64}\.html'), lambda n, t: t == 'google-site-verification: '+n, 'text/html; charset=utf-8'),
    (re.compile(r'naver[0-9a-zA-Z]{8,64}\.html'), lambda n, t: t == 'naver-site-verification: '+n, 'text/html; charset=utf-8'),
    (re.compile(r'BingSiteAuth\.xml'),
     lambda n, t: re.fullmatch(r'<\?xml version="1\.0"\?>\s*<users>\s*<user>[0-9A-F]{32}</user>\s*</users>', t) is not None,
     'application/xml'),
)


def site_verification(name, path_fn=None):
    """(content, media type) of a console ownership file, or None."""
    for pattern, valid, media in VERIFY_FILES:
        if pattern.fullmatch(name):
            break
    else:
        return None
    folder = data_dir() if path_fn is None else path_fn()
    if folder is None:
        return None
    try:
        raw = (folder / VERIFY_DIR / name).read_bytes()
    except OSError:
        return None
    if len(raw) > 2048:
        return None
    text = raw.decode('utf-8', 'replace').strip()
    return (text, media) if valid(name, text) else None


# ---------------------------------------------------------------- router
def growth_router(store=None):
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
    from starlette.concurrency import run_in_threadpool
    from .page_markdown import route_class
    router = APIRouter(route_class=route_class())  # Accept: text/markdown gets the Markdown view of each page
    # The front's default policy blocks scripts and stylesheets; these pages load only same-origin assets.
    page_headers = {'Cache-Control': 'public, max-age=300', 'Content-Security-Policy': PAGE_CSP}

    @router.get('/connect', include_in_schema=False)
    def connect():
        return HTMLResponse(connect_page(), headers=page_headers)

    @router.get('/agents/tasks', include_in_schema=False)
    async def tasks():
        return HTMLResponse(await run_in_threadpool(tasks_index), headers=page_headers)

    def not_found():
        return HTMLResponse(shell(title='Page not found — Agent Concierge', description='This page is not available.',
                                  canonical=ORIGIN+'/agents/tasks', index=False,
                                  body=heading('Not found', 'This page is not available',
                                               'Listings change as checks run. Choose a task or a ranking, or search the catalog.')
                                  + '<div class="actions"><a class="btn primary" href="/agents/tasks">Task pages</a>'
                                  '<a class="btn" href="/agents/best">Rankings</a><a class="btn" href="/new/en/explore.html">Explore</a></div>'),
                            status_code=404, headers={'Content-Security-Policy': PAGE_CSP})

    @router.get('/agents/task/{slug}', include_in_schema=False)
    async def task(slug: str):
        page = await run_in_threadpool(task_page, slug) if SLUG.match(slug) else None
        return HTMLResponse(page, headers=page_headers) if page else not_found()

    from .growth_catalog import install
    install(router, page_headers, not_found, store)

    from . import plugin_dist
    plugin_dist.install(router)

    from . import weekly_report
    weekly_report.install(router, page_headers, not_found)

    key = indexnow_key()
    if key:
        @router.get('/'+key+'.txt', include_in_schema=False)
        def indexnow_key_file():
            return PlainTextResponse(key, headers={'Cache-Control': 'public, max-age=3600'})

    def verification(name):
        found = site_verification(name)
        if found is None:
            return Response(status_code=404)
        return Response(found[0], media_type=found[1], headers={'Cache-Control': 'no-store'})

    @router.get('/google{code}.html', include_in_schema=False)
    def google_verification(code: str):
        return verification('google'+code+'.html')

    @router.get('/naver{code}.html', include_in_schema=False)
    def naver_verification(code: str):
        return verification('naver'+code+'.html')

    @router.get('/BingSiteAuth.xml', include_in_schema=False)
    def bing_verification():
        return verification('BingSiteAuth.xml')

    @router.get('/.well-known/mcp-registry-auth', include_in_schema=False)
    def mcp_registry_auth():
        line = registry_auth()
        if line is None:
            return Response(status_code=404)
        return PlainTextResponse(line+'\n', headers={'Cache-Control': 'no-store'})

    def moved(target):
        def endpoint():  # no parameters, so FastAPI reads nothing from the request
            return RedirectResponse(target, status_code=301)
        return endpoint

    # 11-11: agents also look for these discovery files under /.well-known/; point them at the real ones.
    for alias, target in (('/.well-known/llms.txt', '/llms.txt'),
                          ('/.well-known/mcp/server-card.json', '/.well-known/mcp/server.json')):
        router.add_api_route(alias, moved(target), methods=['GET', 'HEAD'], include_in_schema=False)

    return router

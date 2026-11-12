"""Separate Pearl Connection presentation on the existing frontend origin."""
import collections
import base64
import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
import threading
import time

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..broker.categories import CATEGORIES
from .verification_summary import execution_summary
from ..customer_identity_view import workspace_shell

ROOT = Path(__file__).resolve().parents[2] / 'new'
KINDS = [('a2a', 'A2A'), ('mcp', 'MCP'), ('x402', 'x402')]
STATUSES = ('healthy', 'reachable', 'failing', 'down', 'unknown')
CATEGORY_IDS = ('docs_knowledge', 'web_search', 'data_utility', 'database_analytics')


def public_page_available():
    return (ROOT/'en-manifest.json').is_file() and (ROOT/'en/index.html').is_file()


_asset_versions = {'at': None, 'map': {}}
ASSET_REFERENCE = re.compile(r'((?:href|src)="/new/en/assets/)([A-Za-z0-9_./-]+?)(?:\?v=[^"]*)?"')


def asset_version(body):
    """A short content digest; a changed file always gets a new URL."""
    return hashlib.sha256(body).hexdigest()[:16]


def versioned(value):
    """Point page references at content-addressed asset URLs, which browsers may keep."""
    assets = ROOT / 'en' / 'assets'
    try:
        files = [path for path in assets.rglob('*') if path.is_file() and not path.is_symlink()]
        stamp = (len(files), max((path.stat().st_mtime_ns for path in files), default=0))
    except OSError:
        return value
    if _asset_versions['at'] != stamp:
        versions = {}
        for path in files:
            versions[path.relative_to(assets).as_posix()] = asset_version(path.read_bytes())
        _asset_versions.update(at=stamp, map=versions)
    versions = _asset_versions['map']
    return ASSET_REFERENCE.sub(lambda m: m[1] + m[2] + ('?v=' + versions[m[2]] if m[2] in versions else '') + '"', value)


# 11-11 first paint (PM full check: 4-14 s on a first visit from Korea, every render-blocking file ~3.6 s through
# the LAX edge): a page asks for one stylesheet and one deferred script instead of five of each, and the tiny
# blocking session-bootstrap.js is inlined. The bundle URL names its files and content digest, so any slot can
# build it from the shipped files and browsers keep it for a year.
# Pages link the shared files either absolutely or relative to /new/en/ (the legal pages); a bundle URL is absolute.
STYLE_LINK = re.compile(r'<link rel="stylesheet" href="(?:/new/en/)?assets/([A-Za-z0-9_-]+)\.css(?:\?v=[^"]*)?">\s*')
DEFER_SCRIPT = re.compile(r'<script src="(?:/new/en/)?assets/([A-Za-z0-9_-]+)\.js(?:\?v=[^"]*)?" defer>\s*</script>\s*')
BLOCKING_BOOTSTRAP = '<script src="/new/en/assets/session-bootstrap.js"></script>'
BUNDLE_NAME = re.compile(r'[A-Za-z0-9_-]{1,40}')
BUNDLE_MAX = 12


def bundle_body(names, kind, root=None):
    """The concatenated files of one bundle, in page order; None if any name is not a shipped asset."""
    root = root or ROOT
    parts = []
    for name in names:
        path = root / 'en' / 'assets' / (name + '.' + kind)
        if not BUNDLE_NAME.fullmatch(name) or not path.is_file() or path.is_symlink():
            return None
        parts.append(path.read_bytes())
    joiner = b'\n' if kind == 'css' else b'\n;\n'
    body = joiner.join(parts) + b'\n'
    return versioned_css_urls(body, root) if kind == 'css' else body


# 11-11 (PM: page target 1 s; stale-while-revalidate only once old asset URLs keep working): an edge may hand a
# visitor HTML cached before a deploy, which names the previous bundle digests. When ?v= is not the current
# content, the same bytes are looked up in the earlier releases beside this one
# (gateway-data/services/releases/<name>/new), so that page still gets its own CSS and JS, not the new ones.
EARLIER_RELEASES = 8
EARLIER_SUFFIXES = ('.css', '.js', '.svg', '.png', '.webp', '.json', '.zip')
_earlier = collections.OrderedDict()
_earlier_lock = threading.Lock()


def earlier_roots():
    """The `new` folders of the most recent other releases, newest first; none outside a releases folder."""
    releases = ROOT.parent.parent
    if releases.name != 'releases':
        return []
    try:
        dirs = [d for d in releases.iterdir() if d.is_dir() and not d.is_symlink() and d != ROOT.parent
                and (d / 'new' / 'en' / 'assets').is_dir()]
        dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    except OSError:
        return []
    return [d / 'new' for d in dirs[:EARLIER_RELEASES]]


def earlier_asset(key, version, build):
    """Bytes an earlier release served for `key` with this digest, or None. build(root) gives that release's
    bytes for the key (or None); results per key are kept, so an unknown digest costs a dict lookup."""
    with _earlier_lock:
        found = _earlier.get(key)
        if found is not None:
            _earlier.move_to_end(key)
    if found is None:
        found = {}
        for root in earlier_roots():
            try:
                body = build(root)
            except OSError:
                body = None
            if body is not None:
                found.setdefault(asset_version(body), body)
        with _earlier_lock:
            _earlier[key] = found
            while len(_earlier) > 128:
                _earlier.popitem(last=False)
    return found.get(version)


def earlier_file(root, name):
    """One shipped asset of an earlier release (no links, nothing outside its assets folder)."""
    assets = (root / 'en' / 'assets').resolve()
    path = (root / 'en' / name)
    if '..' in name.split('/') or not path.is_file() or path.is_symlink() or assets not in path.resolve().parents:
        return None
    return path.read_bytes()


CSS_ASSET_URL = re.compile(rb"""url\((['"]?)([A-Za-z0-9_-]+\.(?:webp|png|svg|jpg|woff2?))\1\)""")


def versioned_css_urls(body, root=None):
    """url(pearl.webp) in a bundle gets the same ?v=<digest> as the page's <img>, so the file is fetched once
    and kept for a year (11-11: the home page loaded pearl.webp twice, once per address)."""
    def pin(match):
        path = (root or ROOT) / 'en' / 'assets' / match[2].decode()
        if not path.is_file() or path.is_symlink():
            return match[0]
        return b'url(' + match[1] + match[2] + b'?v=' + asset_version(path.read_bytes()).encode() + match[1] + b')'
    return CSS_ASSET_URL.sub(pin, body)


def bundled(value):
    head_end = value.find('</head>')
    for pattern, kind, tag in ((STYLE_LINK, 'css', '<link rel="stylesheet" href="{}">\n'),
                               (DEFER_SCRIPT, 'js', '<script src="{}" defer></script>\n')):
        found = list(pattern.finditer(value))
        if kind == 'css':
            found = [m for m in found if head_end < 0 or m.start() < head_end]
        if len(found) < 2:
            continue
        names = [m[1] for m in found]
        # A file linked twice applies at its last place; the bundle keeps that one so the cascade is unchanged.
        names = [n for i, n in enumerate(names) if n not in names[i + 1:]]
        if not 2 <= len(names) <= BUNDLE_MAX:
            continue
        body = bundle_body(names, kind)
        if body is None:
            continue
        url = '/new/en/assets/bundle.{}?f={}&amp;v={}'.format(kind, ','.join(names), asset_version(body))
        first = found[0]
        out, last = [], 0
        for m in found:
            out.append(value[last:m.start()])
            if m is first:
                out.append(tag.format(url))
            last = m.end()
        out.append(value[last:])
        value = ''.join(out)
    if BLOCKING_BOOTSTRAP in value:
        path = ROOT / 'en' / 'assets' / 'session-bootstrap.js'
        try:
            code = path.read_text().replace('</', '<\\/')
            value = value.replace(BLOCKING_BOOTSTRAP, '<script>' + code + '</script>', 1)
        except OSError:
            pass
    return value


# 11-12 (PM: A, measured 08:3x): past max-age the edge hands out its copy at once and refreshes it behind
# (UPDATING 0.85 s instead of an origin round trip), so a page left alone for a while no longer costs EXPIRED 3.8-4.9 s.
# No s-maxage: Cloudflare reads it as proxy-revalidate and never serves stale (noon bundle with s-maxage=300:
# all 10 pages EXPIRED 6.5 min after warming). The same bytes go to everyone, so browsers may keep it 5 min too.
# 11-12 19시 (PM approved): swr 600 -> 86400. Live pages are visited rarely, so a copy left alone for more than
# 15 min went EXPIRED and the visitor waited for the origin (user_slo 18:04: 3/3 EXPIRED, 1.06-2.25 s). Within a day
# the edge now answers UPDATING at once. Old copies name old assets, which earlier releases and panels-cache keep.
PUBLIC_PAGE_CACHE = 'public, max-age=300, stale-while-revalidate=86400'
INLINE_SCRIPT = re.compile(r'<script\b([^>]*)>(.*?)</script>', re.S | re.I)
DATA_TYPE = re.compile(r'\btype\s*=\s*["\']?(application/(?:ld\+)?json|text/plain|text/template)', re.I)


def inline_script_hashes(value):
    """Base64 sha256 of every inline script the browser runs (data blocks are not run), in page order."""
    out = []
    for match in INLINE_SCRIPT.finditer(value):
        attributes, body = match[1], match[2]
        if re.search(r'\bsrc\s*=', attributes, re.I) or DATA_TYPE.search(attributes):
            continue
        # The HTML parser turns CR LF and lone CR into LF before the browser hashes the text.
        body = body.replace('\r\n', '\n').replace('\r', '\n')
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        if digest not in out:
            out.append(digest)
    return out


CRITICAL_DIR = ROOT / 'en' / 'assets' / 'critical'
FULL_CSS_SWITCH = ("<script>document.querySelectorAll('link[data-full-css]').forEach(function(l){"
                   "function on(){l.media='all'}if(l.sheet)on();else l.addEventListener('load',on)})</script>\n")


def critical_css(value, page):
    """PM decision B (11-11): inline the page's first-screen CSS and load the bundle without blocking the first
    paint. Only pages with a built file (scripts/build_critical_css.py) change; removing the file turns it off
    (agentcon.env refuses new keys, so there is no environment switch)."""
    if not page:
        return value
    path = CRITICAL_DIR / (page.removesuffix('.html') + '.css')
    try:
        css = path.read_text() if path.is_file() and not path.is_symlink() else ''
    except OSError:
        css = ''
    match = re.search(r'<link rel="stylesheet" href="(/new/en/assets/bundle\.css\?[^"]+)">\n?', value)
    if not css or not match or '</style' in css.lower():
        return value
    replacement = ('<style data-critical-css>' + css + '</style>\n'
                   '<link rel="stylesheet" href="' + match[1] + '" media="print" data-full-css>\n' + FULL_CSS_SWITCH)
    return value[:match.start()] + replacement + value[match.end():]


# 11-11 (PM: page target 1 s, cut bytes): every live page carried the other eight panels as inactive
# <template>s, 121 KB of 214 KB (gzip 25 of 44 KB). Their markup moves to one script, panels.js?v=<digest>, which
# all pages share and browsers and the edge keep; the page keeps empty templates in place and the deferred
# panels-bootstrap.js (first in bundle.js) fills them before the shared handlers attach. The panel markup still
# comes from this response's own rendering (daily numbers included), so the digest changes when it does.
# With Workspace on, these four pages answer 303 -> /customer/sign-in (kept for outside links). Links inside our own
# pages go there directly, saving a round trip from Korea (PM 11-12 08:3x: sign-in 0.99-1.40 s through the 303).
ACCOUNT_LINK = re.compile(r'href="(?:/new/en/)?(?:sign-in|sign-up|workspace|account)\.html"')


def direct_account_links(value):
    return ACCOUNT_LINK.sub('href="/customer/sign-in"', value)


INACTIVE_PANEL = re.compile(r'<template data-inactive-panel="([a-z0-9_-]{1,40})">(.*?)</template>', re.S)
PANELS_KEPT = 32
PANELS_ON_DISK = 512
DIGEST = re.compile(r'[0-9a-f]{16}')
_panels = collections.OrderedDict()
_panels_lock = threading.Lock()
_panels_rebuilt = {'at': 0.0}


def panels_dir():
    """gateway-data/services/panels-cache beside the releases folder, shared by every release; None elsewhere.

    11-12 (PM: swr on public HTML): for up to s-maxage + swr after a deploy the edge may hand out HTML made by the
    previous release, naming its panels.js digest. The new process never rendered that digest, so the script each
    digest stood for is kept on disk and served exactly, like the earlier bundle digests (7ac34f2c)."""
    releases = ROOT.parent.parent
    return releases.parent / 'panels-cache' if releases.name == 'releases' else None


def keep_panels_on_disk(version, body):
    folder = panels_dir()
    if folder is None:
        return
    path = folder / (version + '.js')
    try:
        if path.is_file():
            return
        folder.mkdir(exist_ok=True)
        tmp = folder / ('.%s.%d.tmp' % (version, os.getpid()))
        tmp.write_bytes(body)
        tmp.replace(path)
        kept = sorted(folder.glob('*.js'), key=lambda f: f.stat().st_mtime)
        for old in kept[:max(0, len(kept) - PANELS_ON_DISK)]:
            old.unlink(missing_ok=True)
    except OSError:
        pass  # the page still works: an unknown digest gets every current panel briefly


def panels_from_disk(version):
    folder = panels_dir()
    if folder is None or not DIGEST.fullmatch(version or ''):
        return None
    path = folder / (version + '.js')
    try:
        if path.is_symlink() or not path.is_file():
            return None
        body = path.read_bytes()
    except OSError:
        return None
    return body if asset_version(body) == version else None


def split_panels(value):
    """Move inactive panel markup into the shared panels.js; unchanged when there is no bundle.js to run it."""
    found = INACTIVE_PANEL.findall(value)
    script = re.search(r'<script src="/new/en/assets/bundle\.js\?[^"]+" defer></script>', value)
    if not found or not script or not any(body.strip() for _, body in found):
        return value
    body = panels_script(dict(found))
    version = asset_version(body)
    with _panels_lock:
        known = version in _panels
        _panels[version] = dict(found)
        _panels.move_to_end(version)
        while len(_panels) > PANELS_KEPT:
            _panels.popitem(last=False)
    if not known:
        keep_panels_on_disk(version, body)
    value = INACTIVE_PANEL.sub(lambda m: '<template data-inactive-panel="%s"></template>' % m[1], value)
    script = re.search(r'<script src="/new/en/assets/bundle\.js\?[^"]+" defer></script>', value)  # offsets moved
    tag = '<script src="/new/en/assets/panels.js?v=%s" defer></script>' % version
    return value[:script.start()] + tag + value[script.start():]


def panels_script(panels):
    return ('window.__pearlPanels=Object.assign(window.__pearlPanels||{},'
            + json.dumps(panels, ensure_ascii=False, separators=(',', ':')) + ');\n').encode()


def panels_body(version):
    """(script for this digest or None, script with every panel known now or None)."""
    with _panels_lock:
        found = _panels.get(version)
        union = {}
        for panels in _panels.values():
            union.update(panels)
    return (panels_script(found) if found is not None else None), (panels_script(union) if union else None)


# 11-11 (PM stability: Chat at 375 px shifted 0.027-0.055 on load): pearl-ui.js turned the protocol <select>s into
# button groups after the first paint, and on phones the five Chat buttons wrap to two rows, pushing the
# conversation down 56 px. The page now arrives with the same group already drawn (and the select already hidden
# the way the script hides it); pearl-ui.js adopts a group marked data-for="<select id>" instead of building one.
# Labels must match segmented(...) in new/en/assets/pearl-ui.js (tests/test_prerendered_segmented.py checks it).
SEGMENTED = {
    'chatProtocol': ('Recommendation protocol', {'auto': 'Auto · A2A → MCP', 'any': 'A2A + MCP', 'a2a': 'A2A',
                                                 'mcp': 'MCP', 'x402': 'x402'}),
    'regKind': ('Agent protocol', {'a2a': 'A2A', 'mcp': 'MCP', 'x402': 'x402'}),
}
SELECT = re.compile(r'<select id="(%s)"([^>]*)>(.*?)</select>' % '|'.join(SEGMENTED), re.S)
OPTION = re.compile(r'<option value="([^"]*)"([^>]*)>(.*?)</option>', re.S)


def prerender_segmented(value):
    import html as _html

    def draw(match):
        sid, attrs, options = match[1], match[2], match[3]
        if 'pearl-native-select' in attrs:
            return match[0]
        label, labels = SEGMENTED[sid]
        found = OPTION.findall(options)
        if not found:
            return match[0]
        chosen = next((v for v, a, _ in found if re.search(r'\bselected\b', a)), found[0][0])
        attrs = re.sub(r'class="([^"]*)"', lambda m: 'class="%s pearl-native-select"' % m[1], attrs, count=1)
        if 'class="' not in attrs:
            attrs += ' class="pearl-native-select"'
        buttons = ''.join('<button type="button" data-value="%s" aria-pressed="%s">%s</button>' % (
            _html.escape(v), 'true' if v == chosen else 'false',
            _html.escape(labels.get(v) or _html.unescape(re.sub(r'<[^>]+>', '', text)).strip())) for v, _, text in found)
        group = '<div class="pearl-protocol-segmented" role="group" aria-label="%s" data-for="%s">%s</div>' % (
            _html.escape(label), sid, buttons)
        return '<select id="%s"%s tabindex="-1" aria-hidden="true">%s</select>%s' % (sid, attrs, options, group)
    return SELECT.sub(draw, value)


def page_response(value, *, public=False, page=None):
    """Use the same nonce policy for the default and named presentation routes."""
    value = critical_css(split_panels(versioned(bundled(prerender_segmented(value)))), page)
    if os.environ.get('MAIN_SPONSORED', '0') == '1':  # 11-11 Sponsored on main Explore and Chat; off by default
        value = re.sub(r'<body\b', '<body data-sponsored="on"', value, count=1)
    # 11-11 (PM decision A): the same bytes for every visitor, so the edge may keep a page for 60 seconds.
    # Inline scripts are allowed by their sha256 instead of a per-response nonce; files come from 'self'.
    hashes = inline_script_hashes(value)
    policy = ("default-src 'none'; script-src 'self'" + ''.join(" 'sha256-" + h + "'" for h in hashes) +
              "; script-src-attr 'none'; "
              "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
              "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; "
              "font-src 'self'; worker-src 'self'")
    headers = {'Content-Security-Policy': policy,
               'Cache-Control': PUBLIC_PAGE_CACHE if public else 'no-store',
               'X-Content-Type-Options': 'nosniff'}
    if not public:
        headers['X-Robots-Tag'] = 'noindex,noarchive'
    return HTMLResponse(value, headers=headers)


def default_public_page(bootstrap, structured_data, *, workspace_available=False, snapshot=None):
    """Serve the built publication at the existing public entry URL."""
    value = workspace_shell((ROOT/'en/index.html').read_text(), workspace_available)
    for id, content in [('appBootstrapData', bootstrap)]:
        value = re.sub(r'(<script\b[^>]*\bid="'+id+r'"[^>]*>).*?(</script>)',
                       lambda m: m[1]+content.replace('<', '\\u003c')+m[2], value, flags=re.S)
    value = re.sub(r'(<script\b[^>]*\btype="application/ld\+json"[^>]*>).*?(</script>)',
                   lambda m: m[1]+structured_data.replace('<', '\\u003c')+m[2], value, flags=re.S)
    from .public_metadata import apply_daily_home
    return page_response(apply_daily_home(value, snapshot), public=True, page='index.html')


def _catalog_status(store):
    """Only public aggregate data is exposed; all catalog metrics share one query."""
    now = time.time()
    native = getattr(store, 'public_catalog_metrics', None)
    if callable(native):
        rows, category_rows = native(now-86400, now)
    else:
        category_rows = None
        rows = store.query('''SELECT kind,health_status AS status,COUNT(*) AS n,
        SUM(CASE WHEN last_check_at IS NOT NULL THEN 1 ELSE 0 END) AS checked,
        SUM(CASE WHEN first_seen>=? AND first_seen<=? THEN 1 ELSE 0 END) AS new_count
        FROM resources WHERE active=1 AND kind IN ('a2a','mcp','x402')
        GROUP BY kind,health_status''', (now-86400, now))
    counts = {kind: {key: 0 for key in STATUSES} for kind, _ in KINDS}
    total = reachable = checked = additions = 0
    for record in rows:
        row = dict(record)
        total += row['n']
        checked += row['checked'] or 0
        additions += row['new_count'] or 0
        counts[row['kind']][row['status'] if row['status'] in STATUSES else 'unknown'] += row['n']
        if row['status'] in ('healthy', 'reachable'):
            reachable += row['n']
    categories = collections.Counter()
    if category_rows is None:
        category_rows = store.query('''SELECT category,COUNT(*) AS n FROM resources WHERE active=1
        AND kind IN ('a2a','mcp','x402') GROUP BY category''')
    for row in category_rows:
        categories[row['category']] += row['n']
    from datetime import datetime, timezone
    return {'captured_at_utc': datetime.fromtimestamp(now, timezone.utc).isoformat(),
            'cataloged': total, 'reachable': reachable, 'with_status_check': checked,
            'reachable_share': round(reachable*100/total, 1) if total else 0,
            'new_24h': additions, 'by_protocol': [
                {'kind': kind, 'label': label, 'n': sum(counts[kind].values()),
                 'reachable': counts[kind]['healthy']+counts[kind]['reachable'],
                 'status': counts[kind]} for kind, label in KINDS],
            'categories': [{'id': key, 'name': getattr(CATEGORIES[key], 'name_en', CATEGORIES[key].name),
                            'n': categories[key]} for key in CATEGORY_IDS],
            'execution_24h': execution_summary(store, now)}


def catalog_status(store):
    from .request_store import interactive_store
    with interactive_store(store,readonly=True) as reader:
        return _catalog_status(reader)


# Only what the Test form renders; counters and report history stay on the server.
TEST_AGENT_FIELDS = ('id', 'kind', 'name', 'description', 'url', 'category', 'tools', 'auth_method',
                     'eval_grade', 'health_status', 'connection_available', 'connection_readiness')


def current_fixed_content(value, filename):
    """Refresh the page's shipped examples or workflows from the frontend's warm bootstrap cache.

    UI policy 11-01: these pages open without any API call. The cache is rebuilt in the background
    for the home page, so this reads memory only; without a warm cache the shipped snapshot stays.
    """
    from .front import _bootstrap_snapshot_cache as cache
    with cache['lock']:
        data, fresh_agents = cache.get('data'), cache.get('example_agents') or {}
    if not isinstance(data, dict):
        return value
    match = re.search(r'(<script\b[^>]*\bid="appBootstrapData"[^>]*>)(.*?)(</script>)', value, flags=re.S)
    if not match:
        return value
    try:
        shipped = json.loads(match[2])
    except ValueError:
        return value
    if filename == 'workflows.html' and data.get('workflow_templates'):
        shipped['workflow_templates'] = data['workflow_templates']
    elif filename == 'test.html' and data.get('testbench_examples'):
        agents = {agent.get('id'): agent for agent in shipped.get('testbench_agents', [])}
        agents.update(fresh_agents)
        examples = [e for e in data['testbench_examples'] if e.get('available') and e.get('resource_id')]
        # Only examples whose connection details are on the page can open without a request.
        if examples and all(e['resource_id'] in agents for e in examples):
            shipped['testbench_examples'] = examples
            shipped['testbench_agents'] = [agents[rid] for rid in dict.fromkeys(e['resource_id'] for e in examples)]
    else:
        return value
    text = json.dumps(shipped, separators=(',', ':')).replace('<', '\\u003c')
    return value[:match.start(2)] + text + value[match.end(2):]


def install(app, front, *, workspace_access_enabled=False, workspace_link_enabled=False, root=None):
    """Register only reviewed static files; reuse existing API and request defenses."""
    directory = Path(root) if root is not None else ROOT
    manifest_path = directory / 'en-manifest.json'
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text())
    pages = (set(manifest['live_pages']) | set(manifest['presentation_only_pages'])
             | set(manifest.get('native_account_pages', [])))
    en = (directory / 'en').resolve()
    allowed_assets = {p.relative_to(en).as_posix() for p in (en/'assets').rglob('*')
                      if p.is_file() and not p.is_symlink() and p.suffix in EARLIER_SUFFIXES}
    design = (directory / 'design').resolve()
    allowed_design = {p.relative_to(design).as_posix() for p in design.rglob('*.png')
                      if p.is_file() and not p.is_symlink()}
    lock = threading.Lock()
    cache = {'at': 0, 'data': None}

    def read(base, name):
        path = (base/name).resolve()
        if not path.is_relative_to(base) or not path.is_file() or path.is_symlink():
            raise HTTPException(404, 'Page not found.')
        return path.read_bytes()

    @app.get('/new/en', include_in_schema=False)
    @app.get('/new/en/', include_in_schema=False)
    def index():
        return RedirectResponse('/new/en/index.html', status_code=307)

    @app.get('/new/en/{filename}', include_in_schema=False)
    def page(filename: str):
        if filename not in pages:
            raise HTTPException(404, 'Page not found.')
        if workspace_access_enabled and filename in ('workspace.html', 'account.html', 'sign-in.html', 'sign-up.html'):
            return RedirectResponse('/customer/sign-in', status_code=303, headers={'Cache-Control': 'no-store'})
        value = workspace_shell(read(en, filename).decode(),
                                workspace_access_enabled and workspace_link_enabled)
        if workspace_access_enabled:
            value = direct_account_links(value)
        if filename in manifest['live_pages']:
            from .public_metadata import apply_daily_home, home_metadata_payload, daily_home_text
            snapshot = front.daily_statistics.read()
            value = (apply_daily_home(value, snapshot) if filename == 'index.html'
                     else daily_home_text(home_metadata_payload(value, snapshot), snapshot))
        if filename in ('test.html', 'workflows.html'):
            value = current_fixed_content(value, filename)
        return page_response(value, public=filename in manifest['live_pages'], page=filename)

    @app.get('/new/en/assets/{filename:path}', include_in_schema=False)
    def asset(filename: str, request: Request):
        if filename == 'panels.js':
            wanted = request.query_params.get('v', '')
            body, union = panels_body(wanted)
            body = body or panels_from_disk(wanted)  # a digest an earlier process or release rendered
            # After a restart nothing is rendered yet: render the live pages once (at most once a minute, so
            # unknown digests cannot make every request render ten pages), then look again.
            if body is None and time.monotonic() - _panels_rebuilt['at'] > 60:
                _panels_rebuilt['at'] = time.monotonic()
                for name in sorted(manifest['live_pages']):
                    page(name)
                body, union = panels_body(wanted)
            immutable = body is not None
            body = body or union  # an older digest (numbers changed since): every current panel, briefly
            if body is None:
                raise HTTPException(404, 'Asset not found.')
            return Response(body, media_type='text/javascript; charset=utf-8', headers={
                'X-Content-Type-Options': 'nosniff', 'ETag': '"' + asset_version(body) + '"',
                'Cache-Control': 'public, max-age=31536000, immutable' if immutable
                else 'public, max-age=300, stale-while-revalidate=86400'})
        if filename in ('bundle.css', 'bundle.js'):
            kind = filename.rsplit('.', 1)[1]
            names = request.query_params.get('f', '').split(',')
            if not 0 < len(names) <= BUNDLE_MAX:
                raise HTTPException(404, 'Asset not found.')
            body, wanted = bundle_body(names, kind), request.query_params.get('v')
            if wanted and (body is None or asset_version(body) != wanted):
                body = earlier_asset((kind, tuple(names)), wanted,
                                     lambda root: bundle_body(names, kind, root)) or body
            if body is None:
                raise HTTPException(404, 'Asset not found.')
            version = asset_version(body)
            cache = ('public, max-age=31536000, immutable' if wanted == version
                     else 'public, max-age=300, stale-while-revalidate=86400')
            media = 'text/css; charset=utf-8' if kind == 'css' else 'text/javascript; charset=utf-8'
            return Response(body, media_type=media, headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': cache,
                                                             'ETag': '"' + version + '"'})
        name = 'assets/'+filename
        wanted = request.query_params.get('v')
        body = read(en, name) if name in allowed_assets else None
        if wanted and (body is None or asset_version(body) != wanted) and name.endswith(EARLIER_SUFFIXES):
            body = earlier_asset(('file', name), wanted, lambda root: earlier_file(root, name)) or body
        if body is None:
            raise HTTPException(404, 'Asset not found.')
        version=asset_version(body)
        # Public static files carry no visitor data. A URL naming this exact content is
        # immutable; an unversioned URL is kept briefly and revalidated by ETag.
        cache=('public, max-age=31536000, immutable' if request.query_params.get('v')==version
               else 'public, max-age=300, stale-while-revalidate=86400')
        headers={'X-Content-Type-Options':'nosniff','Cache-Control':cache,'ETag':'"'+version+'"'}
        tags=[tag.strip().removeprefix('W/') for tag in request.headers.get('if-none-match','').split(',')]
        if headers['ETag'] in tags or '*' in tags:return Response(status_code=304,headers=headers)
        return Response(body,media_type=mimetypes.guess_type(name)[0] or 'application/octet-stream',headers=headers)

    async def not_found(request,exc):
        from fastapi.exception_handlers import http_exception_handler
        from starlette.exceptions import HTTPException as StarletteHTTPException
        if (request.method!='GET' or 'text/html' not in request.headers.get('accept','').lower()
                or request.url.path.startswith(('/api/','/.well-known/','/mcp','/a2a','/admin','/internal','/customer'))):
            handler=app.exception_handlers.get(StarletteHTTPException,http_exception_handler)
            return await handler(request,exc)
        return HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Page not found | Agent Concierge</title>'
            '<meta name="robots" content="noindex"><link rel="stylesheet" href="/new/en/assets/styles.css"></head>'
            '<body><main class="container" id="main"><section class="card page-heading"><p class="eyebrow">404</p>'
            '<h1>Find your next connection.</h1><p>This page is unavailable. Continue from Home or explore the agent catalog.</p>'
            '<div class="actions"><a class="btn primary" href="/">Home</a>'
            '<a class="btn" href="/new/en/explore.html">Explore agents</a></div></section>'
            '<nav class="card" aria-label="Main navigation"><p class="eyebrow">Other pages</p><div class="actions">'
            + ''.join('<a class="btn" href="/new/en/'+page+'.html">'+label+'</a>' for page,label in (
                ('chat','Chat'),('workflows','Workflows'),('test','Test'),('learn','Learn'),
                ('agent-status','Agent Status'),('list-agent','List Your Agent'),('about','About')))
            + '</div></nav></main></body></html>',
            status_code=404,headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex',
                'Content-Security-Policy':"default-src 'none'; style-src 'self'; font-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
    app.add_exception_handler(404,not_found)

    @app.get('/new/design/{filename:path}', include_in_schema=False)
    def design_reference(filename: str):
        if filename not in allowed_design:
            raise HTTPException(404, 'Image not found.')
        return Response(read(design, filename), media_type='image/png', headers={'X-Content-Type-Options': 'nosniff'})

    @app.get('/api/pearl/status', include_in_schema=False)
    def status(request: Request):
        ip = front.security.resolve_ip(request)
        if not front.security.allow_explore(ip, base_limit=120):
            raise HTTPException(429, 'Please slow down.', headers={'Retry-After': '60'})
        with lock:
            if cache['data'] is None or time.time()-cache['at'] >= 15:
                cache['data'] = catalog_status(front.store)
                cache['at'] = time.time()
            return cache['data']

    @app.get('/api/pearl/access', include_in_schema=False)
    def access():
        return {'workspace_available': workspace_access_enabled and workspace_link_enabled}

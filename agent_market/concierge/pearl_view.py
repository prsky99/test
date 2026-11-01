"""Separate Pearl Connection presentation on the existing frontend origin."""
import collections
import hashlib
import json
import mimetypes
import re
from pathlib import Path
import secrets
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


def page_response(value, *, public=False):
    """Use the same nonce policy for the default and named presentation routes."""
    value = versioned(value)
    nonce = secrets.token_urlsafe(32)
    from .bootstrap_delivery import nonce_scripts
    value = nonce_scripts(value,nonce)
    policy = ("default-src 'none'; script-src 'nonce-" + nonce + "'; script-src-attr 'none'; "
              "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
              "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; "
              "font-src 'self'; worker-src 'self'")
    headers = {'Content-Security-Policy': policy, 'Cache-Control': 'no-store',
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
    return page_response(apply_daily_home(value, snapshot), public=True)


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


def current_fixed_content(value, filename):
    """Refresh the page's shipped examples or workflows from the frontend's warm bootstrap cache.

    UI policy 11-01: these pages open without any API call. The cache is rebuilt in the background
    for the home page, so this reads memory only; without a warm cache the shipped snapshot stays.
    """
    from .front import _bootstrap_snapshot_cache as cache
    with cache['lock']:
        data = cache.get('data')
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
        known = {agent.get('id') for agent in shipped.get('testbench_agents', [])}
        examples = [e for e in data['testbench_examples'] if e.get('available') and e.get('resource_id')]
        # Only examples whose connection details are shipped can open without a request.
        if examples and all(e['resource_id'] in known for e in examples):
            shipped['testbench_examples'] = examples
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
                      if p.is_file() and not p.is_symlink() and p.suffix in
                      ('.css', '.js', '.svg', '.png', '.webp', '.json', '.zip')}
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
        if filename in manifest['live_pages']:
            from .public_metadata import apply_daily_home, home_metadata_payload, daily_home_text
            snapshot = front.daily_statistics.read()
            value = (apply_daily_home(value, snapshot) if filename == 'index.html'
                     else daily_home_text(home_metadata_payload(value, snapshot), snapshot))
        if filename in ('test.html', 'workflows.html'):
            value = current_fixed_content(value, filename)
        return page_response(value, public=filename in manifest['live_pages'])

    @app.get('/new/en/assets/{filename:path}', include_in_schema=False)
    def asset(filename: str, request: Request):
        name = 'assets/'+filename
        if name not in allowed_assets:
            raise HTTPException(404, 'Asset not found.')
        body=read(en,name)
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

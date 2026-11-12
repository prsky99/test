"""11-10 growth: catalog-based task pages, Markdown views of public pages and the return-visit line."""
import time

from agent_market.concierge import growth_pages as g
from agent_market.concierge import task_catalog as tc
from agent_market.concierge.page_markdown import html_to_markdown
from tests.test_concierge import w  # noqa: F401 (fixture)
from tests.test_growth_pages import agent, client, snapshot, write  # noqa: F401 (fixture)

NOW = time.time()


def cleaned(rid, name, description, **extra):
    return g.clean_agent(agent(rid, name=name, description=description, **extra))


# ---------------------------------------------------------------- catalog-based task pages
def test_phrase_match_needs_the_whole_phrase():
    item = {'name': 'Filings desk', 'description': 'Recent SEC EDGAR filings by ticker.'}
    assert tc.phrase_match('sec edgar filings', item)
    assert tc.phrase_match('sec edgar filing', item)  # plural ending allowed
    assert not tc.phrase_match('edgar sec filings', item)  # word order matters
    assert not tc.phrase_match('text to image', {'name': 'Image tools', 'description': 'Resize an image. Extract text.'})
    assert not tc.phrase_match('gdp', {'name': 'gdpr check', 'description': ''})  # whole words only


def test_catalog_tasks_fill_short_tasks_and_add_catalog_phrases(monkeypatch):
    monkeypatch.setattr(tc, 'TASKS', {'Finance and crypto': ['stock prices', 'tax calculation']})
    monkeypatch.setattr(tc, 'CATALOG_TASKS', {'Finance and crypto': ['sec edgar filings', 'gdp data|gdp', 'funding rates']})
    catalog = [cleaned(1, 'Edgar A', 'SEC EDGAR filings for US companies.'),
               cleaned(2, 'Edgar B', 'Latest SEC EDGAR filings.', verified_at=NOW-3600),
               cleaned(3, 'Edgar C', 'Search SEC EDGAR filings.'),
               cleaned(4, 'Macro', 'GDP and inflation series.'),
               cleaned(5, 'Macro 2', 'Country GDP figures.'),
               cleaned(6, 'Tax helper', 'Tax calculation for invoices.'),
               cleaned(7, 'Tax 2', 'Sales tax calculation.'),
               cleaned(8, 'Funding', 'Perpetual funding rates.')]
    existing = [{'slug': 'stock-prices', 'title': 'Stock prices', 'query': 'stock prices', 'group': 'Finance and crypto',
                 'agents': catalog[:2]}]
    tasks = tc.catalog_tasks(existing, catalog)
    by_slug = {t['slug']: t for t in tasks}
    assert by_slug['stock-prices']['agents'] == catalog[:2]  # search results kept as they were
    assert [a['id'] for a in by_slug['tax-calculation']['agents']] == [6, 7]  # short task: two agents are enough (ties: lower id first)
    edgar = by_slug['sec-edgar-filings']
    assert edgar['agents'][0]['id'] == 2  # a recent execution check ranks first
    assert len(edgar['agents']) == 3 and edgar['query'] == 'sec edgar filings'
    assert 'gdp-data' not in by_slug and 'funding-rates' not in by_slug  # catalog-only pages need three listings
    assert len(tasks) == len(by_slug)  # no duplicate slugs
    assert g.clean({'version': 1, 'captured_at': '2026-11-10T00:00:00+00:00', 'tasks': tasks})['by_slug'].keys() == by_slug.keys()


def test_catalog_phrases_are_unique_and_valid_slugs():
    seen = {tc.slugify(p) for ps in tc.TASKS.values() for p in ps}
    for group, entries in tc.CATALOG_TASKS.items():
        assert group in tc.TASKS
        for entry in entries:
            title, _, term = entry.partition('|')
            slug = tc.slugify(title)
            assert g.SLUG.match(slug) and slug not in seen, entry
            assert term == '' or term.strip() == term
            seen.add(slug)


def test_assembler_snapshot_includes_catalog_tasks():
    assembler = tc.Assembler()
    items = [{'id': i, 'kind': 'x402', 'name': f'Desk {i}', 'description': 'Funding rates for perpetual futures.',
              'health_status': 'healthy', 'last_check_at': NOW-60, 'trial_ok': True, 'eval_grade': 'A'} for i in (1, 2, 3)]
    assembler.add(('catalog', 'finance', 'x402', True, 300), items)
    value = assembler.snapshot()
    assert 'funding-rates' in {t['slug'] for t in value['tasks']}


def test_phrase_case_keeps_acronyms_and_names():
    assert g.phrase_case('Sec edgar filings') == 'SEC EDGAR filings'
    assert g.phrase_case('llms txt') == 'llms.txt'
    assert g.phrase_case('youtube transcript') == 'YouTube transcript'
    assert g.display_title('ip reputation') == 'IP reputation'


# ---------------------------------------------------------------- Markdown views
def test_markdown_view_of_the_connect_page(client):
    c, _ = client
    md = c.get('/connect', headers={'Accept': 'text/markdown'})
    assert md.status_code == 200 and md.headers['content-type'].startswith('text/markdown')
    assert md.headers['vary'] == 'Accept' and 'x-robots-tag' not in md.headers
    text = md.text
    assert text.splitlines()[0] == '# Use Agent Concierge from your MCP client'  # no navigation label first
    assert '```\nclaude mcp add --transport http agent-concierge https://agentconcierge.biz/mcp\n```' in text
    assert '[llms.txt](https://agentconcierge.biz/llms.txt)' in text  # links become absolute
    assert 'whats_new' in text and '<' not in text.replace('<=', '')
    assert 'Toggle dark theme' not in text and 'Skip to main content' not in text
    html = c.get('/connect', headers={'Accept': 'text/html'})
    assert html.headers['content-type'].startswith('text/html') and html.headers['vary'] == 'Accept'
    assert c.get('/connect', headers={'Accept': 'text/html, text/markdown;q=0.5'}).headers['content-type'].startswith('text/html')


def test_markdown_view_of_task_pages_and_not_found(client):
    c, folder = client
    write(folder, snapshot())
    text = c.get('/agents/task/weather-forecast', headers={'Accept': 'text/markdown'}).text
    assert '# Agents for weather forecast' in text and '### Agent 1' in text
    assert '- Quality grade: A' in text and '- Trial call: Succeeded' in text
    assert 'Canonical page: https://agentconcierge.biz/agents/task/weather-forecast' in text
    missing = c.get('/agents/task/none', headers={'Accept': 'text/markdown'})
    assert missing.status_code == 404 and missing.headers['x-robots-tag'] == 'noindex'


def test_html_to_markdown_drops_scripts_and_svg():
    html = ('<html><head><title>T</title></head><body><main><h2>A</h2><script>alert(1)</script>'
            '<svg><text>chart label</text></svg><p>Hello <a href="/x">there</a><a href="/y">again</a></p></main></body></html>')
    text = html_to_markdown(html)
    assert 'alert' not in text and 'chart label' not in text
    assert '## A' in text and 'Hello [there](https://agentconcierge.biz/x) [again](https://agentconcierge.biz/y)' in text


# ---------------------------------------------------------------- return-visit line
def test_return_visit_line_in_mcp_and_first_a2a_reply(w):  # noqa: F811
    _, c, _ = w
    init = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                               'params': {'protocolVersion': '2025-06-18', 'clientInfo': {'name': 'Bot'}, 'capabilities': {}}})
    assert '`whats_new`' in init.json()['result']['instructions'] and '/api/task-updates' in init.json()['result']['instructions']
    first = c.post('/a2a', json={'jsonrpc': '2.0', 'id': 1, 'method': 'message/send', 'params': {'message': {
        'kind': 'message', 'role': 'user', 'messageId': 'm1', 'parts': [{'kind': 'text', 'text': 'find a weather API'}]}}}).json()
    res = first['result']
    data = next(p['data'] for p in res['parts'] if p['kind'] == 'data')
    assert "what's new" in data['return_visit'] and '/api/task-updates' in data['return_visit']
    assert 'Coming back later' not in res['parts'][0]['text']  # the answer text is unchanged
    again = c.post('/a2a', json={'jsonrpc': '2.0', 'id': 2, 'method': 'message/send', 'params': {'message': {
        'kind': 'message', 'role': 'user', 'messageId': 'm2', 'contextId': res['contextId'],
        'parts': [{'kind': 'text', 'text': 'details 1'}]}}}).json()
    data = next(p['data'] for p in again['result']['parts'] if p['kind'] == 'data')
    assert 'return_visit' not in data


# ---------------------------------------------------------------- search-console ownership files
def test_site_verification_files_are_served_only_in_console_format(client):
    c, folder = client
    proof = folder/g.VERIFY_DIR
    proof.mkdir()
    (proof/'google1234567890abcdef.html').write_text('google-site-verification: google1234567890abcdef.html\n')
    (proof/'naver0123456789abcdef0123456789abcdef.html').write_text('naver-site-verification: naver0123456789abcdef0123456789abcdef.html')
    (proof/'BingSiteAuth.xml').write_text('<?xml version="1.0"?>\n<users>\n<user>0123456789ABCDEF0123456789ABCDEF</user>\n</users>')
    (proof/'google0000000000000000.html').write_text('-----BEGIN PRIVATE KEY-----')  # wrong content is never served
    r = c.get('/google1234567890abcdef.html', headers={'Accept': 'text/markdown'})
    assert r.status_code == 200 and r.text == 'google-site-verification: google1234567890abcdef.html'
    assert c.get('/naver0123456789abcdef0123456789abcdef.html').status_code == 200
    bing = c.get('/BingSiteAuth.xml')
    assert bing.status_code == 200 and bing.headers['content-type'].startswith('application/xml')
    assert c.get('/google0000000000000000.html').status_code == 404
    assert c.get('/googleabcdefgh12345678.html').status_code == 404  # no file
    assert c.get('/google..%2Fx.html').status_code == 404
    assert g.site_verification('../BingSiteAuth.xml', lambda: folder) is None


def test_catalog_matching_uses_the_listing_lead_and_main_category(monkeypatch):
    monkeypatch.setattr(tc, 'TASKS', {'Search and web': []})
    monkeypatch.setattr(tc, 'CATALOG_TASKS', {'Search and web': ['google search']})
    catalog = [cleaned(1, 'Serp A', 'Google Search results as JSON.', category='web_search'),
               cleaned(2, 'Serp B', 'Use when an agent needs Google search results for a query.', category='web_search'),
               cleaned(3, 'Serp C', 'Google search organic results and snippets.', category='web_search'),
               cleaned(4, 'Ad mockups', 'Preview ads for Facebook, YouTube, Display and also Google Search.', category='commerce_marketing'),
               cleaned(5, 'Ad costs', 'Google Search CPC benchmarks.', category='commerce_marketing')]
    task = tc.catalog_tasks([], catalog)[0]
    # 4: the phrase is past the opening of the description; 5: outside the matches' main category
    assert [a['id'] for a in task['agents']] == [1, 2, 3]
    assert tc.lead({'name': 'n', 'description': 'Use when an agent needs Google search results'})['description'].startswith('Google search')


# ---------------------------------------------------------------- self-hosted Claude Code marketplace
def test_plugin_marketplace_and_archive(client, tmp_path):
    import hashlib
    import io
    import json
    import zipfile
    from pathlib import Path
    from agent_market.concierge import plugin_dist
    root = Path(__file__).resolve().parents[1]
    for name in plugin_dist.FILES:  # the served copy stays equal to the published source (release copies omit integrations/)
        if (root/'integrations/claude-code-plugin').is_dir():
            assert (root/'agent_market/concierge/claude_plugin'/name).read_bytes() == (root/'integrations/claude-code-plugin'/name).read_bytes(), name
    c, _ = client
    market = c.get('/claude-plugins/marketplace.json').json()
    entry = market['plugins'][0]
    assert market['name'] == entry['name'] == 'agent-concierge' and entry['source']['source'] == 'archive'
    url = entry['source']['url']
    assert url.startswith('https://agentconcierge.biz/claude-plugins/')
    archive = c.get(url.removeprefix('https://agentconcierge.biz'))
    assert archive.status_code == 200 and archive.headers['content-type'] == 'application/zip'
    assert hashlib.sha256(archive.content).hexdigest() == entry['source']['sha256']
    assert archive.content == c.get(url.removeprefix('https://agentconcierge.biz')).content  # same bytes every time
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert sorted(names) == sorted(plugin_dist.FILES)
    body = b''.join(zipfile.ZipFile(io.BytesIO(archive.content)).read(n) for n in names).decode()
    assert '127.0.0.1' not in body and 'localhost' not in body and '<owner>' not in body
    assert json.loads(zipfile.ZipFile(io.BytesIO(archive.content)).read('.mcp.json'))['mcpServers']['agent-concierge']['url'] == 'https://agentconcierge.biz/mcp'
    assert c.get('/claude-plugins/other.zip').status_code == 404


# ---------------------------------------------------------------- public cache for growth pages (11-10)
def test_public_growth_pages_are_cached_only_without_credentials(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from tests.test_concierge import populated
    from agent_market.concierge.front import create_front_app
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    (tmp_path/'public-pages').mkdir()
    monkeypatch.setattr(g, 'SNAPSHOT', g.Snapshot())
    write(tmp_path/'public-pages', snapshot())
    c = TestClient(create_front_app(populated().app.state.front))
    public = ['/connect', '/agents/tasks', '/agents/task/weather-forecast', '/badges', '/claude-plugins/marketplace.json']
    for path in public:
        r = c.get(path, headers={'Accept': 'text/html'})
        assert r.status_code == 200 and r.headers['cache-control'] == 'public, max-age=3600, stale-while-revalidate=86400', path
        assert 'accept' in r.headers['vary'].lower(), path
        assert r.headers.get('etag') and r.headers['x-content-type-options'] == 'nosniff', path
        assert c.get(path, headers={'Accept': 'text/html', 'If-None-Match': r.headers['etag']}).status_code == 304, path
        assert c.get(path, headers={'Cookie': '_ga=GA1.1.1; _gid=GA1.1.2'}).headers['cache-control'].startswith('public'), path
        for credential in ({'Cookie': 'acs_session=abc'}, {'Authorization': 'Bearer x'}, {'X-Visitor-Token': 'vt_x'}):
            assert c.get(path, headers=credential).headers['cache-control'] == 'no-store', (path, credential)
    md = c.get('/connect', headers={'Accept': 'text/markdown'})
    assert md.headers['content-type'].startswith('text/markdown') and md.headers['cache-control'].startswith('public')
    assert md.headers['etag'] != c.get('/connect', headers={'Accept': 'text/html'}).headers['etag']
    assert c.get('/agents/task/none').headers['cache-control'] == 'no-store'  # errors are not shared
    for path in ('/api/overview?x=1', '/mcp', '/new/en/workspace.html'):
        assert 'max-age=300' not in c.get(path).headers.get('cache-control', ''), path
    assert 'Claude Code 2.1.224 or later' in c.get('/connect').text
    llms = c.get('/llms.txt').text
    assert llms.count('Markdown copy of the same content') == 1 and llms.count('/reports/weekly') == 1

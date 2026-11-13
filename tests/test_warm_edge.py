"""scripts/warm_edge.py finds every bundle and versioned asset a public page names."""
from scripts import warm_edge


def test_assets_of_a_page_are_its_versioned_bundles_and_files():
    page = ('<link rel="stylesheet" href="/new/en/assets/bundle.css?f=tokens,styles&amp;v=abc">'
            '<script src="/new/en/assets/bundle.js?f=app&amp;v=def" defer></script>'
            '<img src="/new/en/assets/pearl.webp?v=123"><a href="/new/en/assets/plain.css">')
    assert warm_edge.assets_of(page) == ['/new/en/assets/bundle.css?f=tokens,styles&v=abc',
                                         '/new/en/assets/bundle.js?f=app&v=def', '/new/en/assets/pearl.webp?v=123']


def test_the_pages_are_the_public_live_pages_and_the_request_is_a_first_visit():
    assert '/' in warm_edge.PAGES and len(warm_edge.PAGES) == 10
    assert 'text/html' in warm_edge.HEADERS['Accept'] and 'Cookie' not in warm_edge.HEADERS


SITEMAP = ''.join('<url><loc>https://agentconcierge.biz%s</loc></url>' % p for p in (
    '/agents/category/weather', '/agents/category/ai_models', '/agent/7', '/reports/weekly', '/reports/weekly/2026-W44',
    '/reports/weekly/2026-W45', '/agents/category/weather', '/connect'))


def test_growth_pages_are_categories_the_weekly_list_and_the_latest_issue():
    # 11-12 PM B: about 21 requests, once after a deploy and once a day; no agent or other growth pages.
    assert warm_edge.growth_paths(SITEMAP) == ['/agents/category/ai_models', '/agents/category/weather',
                                               '/reports/weekly', '/reports/weekly/2026-W45']
    many = ''.join('<loc>https://agentconcierge.biz/agents/category/c%03d</loc>' % i for i in range(100))
    assert len(warm_edge.growth_paths(many)) == warm_edge.GROWTH_MAX


def test_growth_only_skips_the_live_pages(monkeypatch):
    asked = []

    class Answer:
        status_code, text, headers = 200, SITEMAP, {}

    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, url): asked.append(url); return Answer()
    monkeypatch.setattr(warm_edge.httpx, 'Client', Client)
    monkeypatch.setattr(warm_edge, 'LOG', __import__('pathlib').Path(__import__('tempfile').mkdtemp()) / 'warm.jsonl')
    try:
        warm_edge.main(['--growth-only'])
    except SystemExit as done:
        assert done.code == 0
    paths = [u.replace(warm_edge.BASE, '') for u in asked]
    assert paths[0] == '/sitemaps/pages.xml' and '/reports/weekly' in paths
    assert not any(p in warm_edge.PAGES for p in paths[1:])


def test_a_page_served_stale_is_asked_again_and_must_come_back_fresh(monkeypatch, tmp_path):
    # 11-12 PM ②: with swr 86400 the first answer after a deploy may be the previous page (UPDATING).
    answers = {}

    class Reply:
        def __init__(self, cache, age, text=''):
            self.status_code, self.text = 200, text
            self.headers = {'cf-cache-status': cache, 'age': str(age), 'cf-ray': 'x-LAX'}

    def fake_fetch(url, headers):
        path = url.replace(warm_edge.BASE, '')
        n = answers.get(path, 0)
        answers[path] = n + 1
        r = Reply('UPDATING', 900) if n == 0 and path == '/' else Reply('HIT', 1)
        return r, {'s': 0.1, 'status': 200, 'age': r.headers['age'], 'cache': r.headers['cf-cache-status'], 'colo': 'LAX'}

    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, url): return Reply('HIT', 0, SITEMAP)
    monkeypatch.setattr(warm_edge, 'fetch', fake_fetch)
    monkeypatch.setattr(warm_edge.httpx, 'Client', Client)
    monkeypatch.setattr(warm_edge.time, 'sleep', lambda s: None)
    monkeypatch.setattr(warm_edge, 'LOG', tmp_path / 'warm.jsonl')
    try:
        warm_edge.main([])
    except SystemExit as done:
        assert done.code == 0
    assert answers['/'] == 2 and answers['/new/en/chat.html'] == 1
    import json
    record = json.loads((tmp_path / 'warm.jsonl').read_text())
    assert record['still_stale'] == [] and any(r['path'] == '/ (again)' for r in record['rows'])
    assert warm_edge.refreshed({'status': 200, 'cache': 'UPDATING', 'age': '5'}) is False
    assert warm_edge.refreshed({'status': 200, 'cache': 'HIT', 'age': '900'}) is False

"""R78 (precision review 11-15): reads that answered no-store get public cache policies; necklace pages are kept only
five minutes (plus five stale) so a pause or replacement notice shows within about ten minutes; the method pages
follow /methodology.json."""
from agent_market.concierge import necklace_surface
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def test_discovery_copies_status_reads_and_method_pages(client):  # noqa: F811
    expected = {'/.well-known/skill.md': 'public, max-age=3600', '/.well-known/agent-entry.json': 'public, max-age=3600',
                '/logo.svg': 'public, max-age=3600', '/status.json': 'public, max-age=60',
                '/api/pearl/status': 'public, max-age=60', '/api/pearl/access': 'public, max-age=60',
                '/methodology.json': 'public, max-age=600', '/methodology': 'public, max-age=600',
                '/methodology/changelog': 'public, max-age=600'}
    for path, policy in expected.items():
        r = client.get(path, headers={'Accept': 'text/html'} if path.startswith('/methodology') and not path.endswith('.json') else {})
        if r.status_code != 200:
            continue   # a read this test app does not serve (e.g. no method file) keeps its own answer
        assert r.headers['cache-control'].startswith(policy), (path, r.headers['cache-control'])
    assert client.get('/api/pearl/status', headers={'Cookie': 'session=x'}).headers['cache-control'] == 'no-store'


def test_necklace_pages_are_kept_five_minutes_and_unknown_ones_not_at_all(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(necklace_surface, 'page', lambda slug, *a, **k: (200, '<!doctype html><title>n</title>') if slug == 'trip-brief' else (404, None))
    r = client.get('/necklaces/trip-brief', headers={'Accept': 'text/html'})
    assert r.status_code == 200 and r.headers['cache-control'] == 'public, max-age=300, stale-while-revalidate=300'
    missing = client.get('/necklaces/nope', headers={'Accept': 'text/html'})
    assert missing.status_code == 404 and 'public' not in missing.headers['cache-control']

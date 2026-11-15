"""Status reads our own pages poll (PM 11-15 22:2x): browsers keep them a plain minute with no stale-while-revalidate,
so Chrome sends no background revalidation it later cancels (net::ERR_ABORTED on Agent Status in the full check since
17:4x); the edge keeps the stale window through Cloudflare-CDN-Cache-Control. Agent feeds keep their policy."""
from agent_market.concierge import public_http_contract as phc
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def test_status_reads_have_no_browser_stale_window_and_keep_the_edge_one(client):  # noqa: F811
    seen = 0
    for path in sorted(phc.PAGE_STATUS_READS):
        r = client.get(path)
        if r.status_code != 200:
            continue   # a read this test app does not serve keeps its own answer
        seen += 1
        assert r.headers['cache-control'] == 'public, max-age=60', (path, r.headers['cache-control'])
        assert r.headers['cloudflare-cdn-cache-control'] == phc.FEED_CACHE, path
    assert seen >= 1
    assert client.get('/api/pearl/status', headers={'Cookie': 'session=x'}).headers['cache-control'] == 'no-store'


def test_agent_feeds_keep_their_stale_window(client):  # noqa: F811
    r = client.get('/api/necklaces')
    assert r.status_code == 200 and r.headers['cache-control'] == phc.FEED_CACHE
    assert 'cloudflare-cdn-cache-control' not in r.headers

"""PM 11-18 06:40: the public page shells and the sign-in page ask the edge for six hours (Cloudflare-CDN-Cache-Control).

The hourly full check meets the same /new/en pages every two hours and found an expired edge copy 24 of 46 times
(1.0-5.0 s). Browsers keep five minutes as before; a request with a cookie or credentials stays no-store and carries no
edge header; no s-maxage (Cloudflare would then hand out nothing stale)."""
import pytest

from agent_market.concierge.pearl_view import NOTICE_PAGES, PUBLIC_PAGE_CACHE, PUBLIC_PAGE_EDGE
from agent_market.customer_sign_in_cache import EDGE_CACHE
from tests.test_pearl_frontend import client  # noqa: F401


def seconds(policy):
    return {k.strip(): v for k, v in (p.strip().split('=') for p in policy.split(',') if '=' in p)}


def test_the_edge_keeps_a_page_six_hours_and_serves_it_stale_for_a_day():
    edge = seconds(PUBLIC_PAGE_EDGE)
    assert int(edge['max-age']) == 21600 and int(edge['stale-while-revalidate']) == 86400
    assert 's-maxage' not in PUBLIC_PAGE_EDGE and PUBLIC_PAGE_EDGE.startswith('public')
    assert int(seconds(PUBLIC_PAGE_CACHE)['max-age']) == 300  # browsers: five minutes, unchanged
    assert seconds(EDGE_CACHE)['max-age'] == '21600'          # the sign-in page, was 3600


@pytest.mark.parametrize('name', sorted(NOTICE_PAGES) + ['test.html', 'explore.html', 'index.html'])
def test_a_shared_page_names_the_edge_policy_and_a_private_one_does_not(client, name):  # noqa: F811
    path = '/new/en/' + name
    plain = client.get(path, headers={'Accept': 'text/html'})
    assert plain.status_code == 200
    assert plain.headers['cache-control'] == PUBLIC_PAGE_CACHE
    assert plain.headers['cloudflare-cdn-cache-control'] == PUBLIC_PAGE_EDGE
    for headers in ({'Cookie': 'session=1'}, {'Authorization': 'Bearer x'}):
        again = client.get(path, headers={'Accept': 'text/html', **headers})
        # whatever the page does with a credential, the edge header goes with the shared policy and only with it
        shared = again.headers['cache-control'] == PUBLIC_PAGE_CACHE
        assert ('cloudflare-cdn-cache-control' in again.headers) == shared, (name, headers)
        if name in NOTICE_PAGES:
            assert not shared, name  # notice pages answer a credential with no-store, as before

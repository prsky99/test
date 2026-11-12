"""11-12 19시 (PM approved): live public HTML keeps stale-while-revalidate for a day.

user_slo 18:04 measured all three pages EXPIRED (1.06-2.25 s): a copy left alone for more than max-age + swr
(15 min) sent the visitor to the origin. With swr 86400 the edge answers UPDATING at once within a day. What must
still hold: no s-maxage (Cloudflare then serves nothing stale), personal and sign-in answers stay no-store, a
response that sets a cookie is never shared, and old HTML can still load its old assets (tests in
test_earlier_asset_urls.py: earlier bundle digests and panels.js digests kept on disk).
"""
from agent_market.concierge.pearl_view import PUBLIC_PAGE_CACHE
from tests.test_direct_sign_in_links import published
from tests.test_pearl_frontend import client  # noqa: F401
from tests.test_public_page_cache import client as page_client  # noqa: F401


def test_the_live_page_policy_serves_stale_for_a_day_without_s_maxage():
    parts = dict(p.strip().split('=') if '=' in p else (p.strip(), True) for p in PUBLIC_PAGE_CACHE.split(','))
    assert parts['public'] is True and int(parts['max-age']) == 300
    assert int(parts['stale-while-revalidate']) >= 86400 and 's-maxage' not in parts and 'must-revalidate' not in parts


def test_sign_in_and_account_answers_stay_private(client):  # noqa: F811
    with published(client, True) as site:
        for path in ('/new/en/sign-in.html', '/new/en/workspace.html', '/new/en/account.html'):
            r = site.get(path, follow_redirects=False)
            assert r.status_code == 303 and r.headers['cache-control'] == 'no-store', path


def test_a_cookie_answer_is_never_given_the_shared_policy(page_client):  # noqa: F811
    r = page_client.get('/__cookie_test')
    assert 'set-cookie' in r.headers and r.headers['cache-control'] != PUBLIC_PAGE_CACHE
    assert 'public' not in r.headers['cache-control']

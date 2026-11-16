"""11-12 19시 (PM approved): live public HTML keeps stale-while-revalidate for a day.

user_slo 18:04 measured all three pages EXPIRED (1.06-2.25 s): a copy left alone for more than max-age + swr
(15 min) sent the visitor to the origin. With swr 86400 the edge answers UPDATING at once within a day. What must
still hold: no s-maxage (Cloudflare then serves nothing stale), personal answers stay no-store (the sign-in page
itself is cookie-free and kept 300 s since 46aa1389), a
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
        for path in ('/new/en/workspace.html', '/new/en/account.html'):
            r = site.get(path, follow_redirects=False)
            assert r.status_code == 303 and r.headers['cache-control'] == 'no-store', path
        # 11-14 PM: the old sign-in address is one fixed, cookie-free move (308) a cache may keep for a day
        r = site.get('/new/en/sign-in.html', follow_redirects=False)
        assert r.status_code == 308 and r.headers['cache-control'] == 'public, max-age=86400' and 'set-cookie' not in r.headers
        # PM 11-16 04:3x (46aa1389) and 09:5x: the sign-in page may be kept only while it is the same bytes for everyone,
        # sets no cookie and holds no personal value; whether the visitor is signed in comes from the status API after
        # it opens, and that answer, like every signed-in page, stays no-store.
        from agent_market.customer_sign_in_cache import BROWSER_CACHE
        session = 'customer_session=private-value-4821'
        first = site.get('/customer/sign-in')
        again = site.get('/customer/sign-in')
        signed = site.get('/customer/sign-in', headers={'Cookie': session})
        assert first.status_code == 200 and first.headers['cache-control'] == BROWSER_CACHE
        assert first.content == again.content == signed.content            # no nonce, nothing per visitor
        assert not any('set-cookie' in r.headers for r in (first, again, signed))
        assert 'private-value-4821' not in signed.text and 'nonce=' not in first.text
        for headers in ({}, {'Cookie': session}):
            status = site.get('/api/customer-auth/status', headers=headers)
            assert 'no-store' in status.headers['cache-control'], headers
            plan = site.get('/customer/plan', headers=headers, follow_redirects=False)
            assert 'no-store' in plan.headers['cache-control'], (headers, plan.status_code)


def test_a_cookie_answer_is_never_given_the_shared_policy(page_client):  # noqa: F811
    r = page_client.get('/__cookie_test')
    assert 'set-cookie' in r.headers and r.headers['cache-control'] != PUBLIC_PAGE_CACHE
    assert 'public' not in r.headers['cache-control']

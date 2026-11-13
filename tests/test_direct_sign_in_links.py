"""11-12 (PM 08:3x): links inside our pages go straight to /customer/sign-in instead of through the 303.

With Workspace on, /new/en/sign-in.html (and sign-up, workspace, account) answer 303 -> /customer/sign-in. That
redirect stays for links from outside, but following it costs one more round trip from Korea (sign-in measured
0.99-1.40 s on new connections, 11-12 08:2x). Our own pages now link to the destination directly.
"""
import re

from fastapi.testclient import TestClient

from agent_market.concierge.front import create_front_app
from agent_market.concierge.pearl_view import direct_account_links
from tests.test_pearl_frontend import ORIGIN, client  # noqa: F401

OLD = re.compile(r'href="(?:/new/en/)?(?:sign-in|sign-up|workspace|account)\.html"')


def test_only_account_page_links_change():
    page = ('<a href="sign-in.html">a</a><a href="/new/en/sign-up.html">b</a><a href="workspace.html">c</a>'
            '<option value="sign-in.html">d</option><a href="compare.html?page=sign-in.html">e</a>'
            '<a href="signed-out.html">f</a><a href="https://other.example/sign-in.html">g</a>')
    out = direct_account_links(page)
    assert out.count('href="/customer/sign-in"') == 3
    for kept in ('<option value="sign-in.html">', 'compare.html?page=sign-in.html', 'href="signed-out.html"',
                 'https://other.example/sign-in.html'):
        assert kept in out


def published(client, access):  # noqa: F811
    app = create_front_app(client.app.state.front, workspace_access_enabled=access, workspace_link_enabled=access,
                           manage_book_lifecycle=False)
    return TestClient(app, base_url=ORIGIN)


def test_with_workspace_on_pages_link_directly_and_the_old_address_still_redirects(client):  # noqa: F811
    with published(client, True) as site:
        page = site.get('/new/en/signed-out.html', headers={'Accept': 'text/html'})
        assert page.status_code == 200
        assert 'href="/customer/sign-in"' in page.text and not OLD.search(page.text)
        old = site.get('/new/en/sign-in.html', follow_redirects=False)
        # 11-14 PM: a fixed, cookie-free move a cache may keep for a day; the sign-in page itself stays no-store.
        assert old.status_code == 308 and old.headers['location'] == '/customer/sign-in'
        assert old.headers['cache-control'] == 'public, max-age=86400' and 'set-cookie' not in old.headers
        assert site.get('/new/en/sign-in.html', follow_redirects=False, headers={'Cookie': 'customer_session=x'}).headers['location'] == '/customer/sign-in'
        for other in ('sign-up.html', 'workspace.html', 'account.html'):
            moved = site.get('/new/en/' + other, follow_redirects=False)
            assert moved.status_code == 303 and moved.headers['cache-control'] == 'no-store', other


def test_with_workspace_off_the_static_pages_keep_their_links(client):  # noqa: F811
    with published(client, False) as site:
        page = site.get('/new/en/signed-out.html', headers={'Accept': 'text/html'})
        assert page.status_code == 200 and 'href="sign-in.html"' in page.text
        assert site.get('/new/en/sign-in.html', follow_redirects=False).status_code == 200

"""First visit on a phone: the consent strip must leave the header usable (11-10 fix of the 11-04 top strip).

11-11 (PM decision A): the strip sits in the page flow above the header, so it can never cover the header or
the menu; accepting and refusing are two equal 44px buttons (the separate close button is gone)."""
from urllib.parse import urlsplit

import pytest

from tests.test_front_workflow_browser import browser  # noqa: F401 (fixture)
from tests.test_pearl_frontend import ORIGIN, client  # noqa: F401 (fixture)


@pytest.mark.parametrize('size', [(390, 812), (375, 667), (320, 640)])
@pytest.mark.parametrize('path', ['/', '/new/en/explore.html', '/new/en/chat.html'])
def test_phone_consent_strip_leaves_the_menu_usable(client, browser, size, path):
    from playwright.sync_api import expect
    width, height = size
    context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))

    def serve(route):
        req = route.request
        url = urlsplit(req.url)
        if url.hostname != 'agentconcierge.biz' or req.method not in ('GET', 'HEAD'):
            return route.abort()
        res = client.request(req.method, url.path+('?'+url.query if url.query else ''), headers=req.headers, follow_redirects=False)
        route.fulfill(status=res.status_code, body=res.content,
                      headers={k: v for k, v in res.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', serve)
    try:
        page.goto(ORIGIN+path)
        banner = page.locator('#cookieConsentBanner')
        expect(banner).to_be_visible()  # no stored choice: the strip shows
        geometry = page.evaluate('''() => {
            const header = document.querySelector('header.pearl-header').getBoundingClientRect();
            const banner = document.querySelector('#cookieConsentBanner').getBoundingClientRect();
            const accept = document.querySelector('#btnAcceptAllCookies').getBoundingClientRect();
            const reject = document.querySelector('#btnRejectNonEssentialCookies').getBoundingClientRect();
            const menu = document.querySelector('[data-pearl-action="menu"]').getBoundingClientRect();
            const hit = document.elementFromPoint(menu.x + menu.width/2, menu.y + menu.height/2);
            return {headerTop: header.top, bannerTop: banner.top, bannerBottom: banner.bottom, position: getComputedStyle(document.querySelector('#cookieConsentBanner')).position,
                    acceptH: accept.height, rejectH: reject.height, acceptW: accept.width, rejectW: reject.width,
                    menuOnTop: !!hit.closest('[data-pearl-action="menu"]')};
        }''')
        assert geometry['menuOnTop'], geometry
        assert geometry['position'] != 'fixed' and geometry['bannerBottom'] <= geometry['headerTop'] + 1, geometry
        assert geometry['bannerBottom'] - geometry['bannerTop'] <= 160, geometry
        assert geometry['acceptH'] >= 44 and geometry['rejectH'] >= 44 and abs(geometry['acceptW'] - geometry['rejectW']) < 2, geometry
        page.get_by_role('button', name='Open navigation', exact=True).click()
        nav = page.locator('#navTabs')
        expect(nav).to_be_visible()
        first = nav.locator('.nav-tab').first
        box = first.bounding_box()
        assert page.evaluate('([x, y]) => !!document.elementFromPoint(x, y).closest("#navTabs")',
                             [box['x']+box['width']/2, box['y']+box['height']/2])  # the open menu draws above the strip
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
        assert not errors
    finally:
        context.close()

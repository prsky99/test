"""All workspace destinations remain discoverable on narrow customer screens."""
# ruff: noqa: F401, F811 -- shared isolated customer/browser fixtures
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_workspace_prelaunch_browser import (
    browser, customer_flow, open_studio, ready, routing, typed_release_world, typed_world,
)

EVIDENCE = Path('reports/workspace-human-centered-2026-10-25')


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_narrow_navigation_all_destinations_header_and_keyboard(customer_flow, browser, theme):
    context, page, errors, requests = open_studio(customer_flow, browser)
    try:
        ready(page)
        if theme == 'dark':
            page.locator('#workspace-theme').click()
        expect(page.locator('body')).to_have_attribute('data-theme', theme)
        links = page.locator('.workspace-sidebar a[data-workspace-section]')
        expect(links).to_have_count(8)
        for width in (760, 600, 480, 390, 360, 320):
            page.set_viewport_size({'width': width, 'height': 844})
            page.evaluate('scrollTo(0,0)')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            expect(page.locator('#workspace-menu')).to_be_visible()
            page.locator('#workspace-menu').click()
            expect(page.locator('#workspace-menu')).to_have_attribute('aria-expanded','true')
            if not page.locator('.workspace-manage').evaluate('(n)=>n.open'):
                page.locator('.workspace-manage > summary').click()
            assert page.locator('.workspace-sidebar').evaluate('(n)=>n.scrollWidth <= n.clientWidth')
            for link in links.all():
                expect(link).to_be_visible()
                assert link.evaluate('(n)=>{const r=n.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && r.height>=44}')
            controls = page.locator('.workspace-topbar a:visible, .workspace-topbar button:visible')
            boxes = [item.bounding_box() for item in controls.all()]
            assert all(box and box['x'] >= 0 and box['x'] + box['width'] <= width for box in boxes)
            for index, a in enumerate(boxes):
                for b in boxes[index + 1:]:
                    assert (a['x'] + a['width'] <= b['x'] + .5 or b['x'] + b['width'] <= a['x'] + .5
                            or a['y'] + a['height'] <= b['y'] + .5 or b['y'] + b['height'] <= a['y'] + .5)
            page.keyboard.press('Escape')
            expect(page.locator('#workspace-menu')).to_be_focused()
        page.locator('#workspace-menu').click()
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(EVIDENCE / ('navigation-320-' + theme + '.png')))
        page.keyboard.press('Tab')
        links.first.focus()
        for link in links.all():
            link.focus()
            expect(link).to_be_focused()
            assert link.evaluate('(n)=>getComputedStyle(n).outlineStyle != "none"')
        page.locator('#workspace-mobile-signout').focus();page.keyboard.press('Tab')
        expect(page.locator('#workspace-nav-close')).to_be_focused()
        page.locator('[data-workspace-section="account"]').click()
        expect(page).to_have_url('https://customer.test/customer/organizations#account')
        expect(page.locator('[data-workspace-section="account"]')).to_have_attribute('aria-current', 'page')
        page.set_viewport_size({'width': 1440, 'height': 1000})
        expect(page.locator('.workspace-sidebar')).to_be_visible()
        assert page.locator('.workspace-sidebar').evaluate('(n)=>getComputedStyle(n).flexDirection') == 'column'
        assert not errors
        assert not [method for method, _ in requests if method != 'GET']
    finally:
        context.close()

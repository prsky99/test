"""Renewed navigation stays in the console without widening staff authority."""

# ruff: noqa: F401,F811
from playwright.sync_api import expect

from tests.test_admin_next_browser import open_console, sign_in, ORIGIN
from tests.test_dashboard import dash
from tests.test_front_workflow_browser import browser


def test_renewed_management_links_reach_their_current_workflow(dash, browser):
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        expect(page.locator('a[href^="/admin/ui"]')).to_have_count(0)
        for route, screen, title in [
            ("/customers/staff", "W02", "직원 작업공간"),
            ("/security/audit", "S02", "관리자 작업 이력"),
            ("/customers/credits", "U07", "가입·크레딧"),
            ("/customers/specialists", "W07", "전문 도구"),
        ]:
            page.goto(ORIGIN + "/admin/next#" + route)
            expect(page.locator("#adm-main")).to_have_attribute("data-screen", screen)
            expect(page.locator(".adm-subnav a[aria-current=page]")).to_have_text(title)
            expect(page.locator(".adm-subnav a[aria-current=page]")).to_have_count(1)
        expect(page.locator('a[href^="/admin/ui"]')).to_have_count(0)
        assert not errors and not external
    finally:
        context.close()

"""Every designed unit opens against an isolated authenticated gateway, not a mockup."""

# ruff: noqa: F401,F811
import json
from pathlib import Path
import pytest
from playwright.sync_api import expect
from tests.test_dashboard import dash
from tests.test_front_workflow_browser import browser
from tests.test_admin_next_browser import open_console, sign_in, ORIGIN

ROOT = Path("reports/admin-redesign-implementation-2026-10-24")
DESIGN = json.loads(Path("docs/admin-redesign-2026-10-24/screens.json").read_text())


@pytest.mark.parametrize(
    "width,theme", [(1440, "light"), (768, "light"), (390, "dark")]
)
def test_all_71_screens_have_real_views_and_no_legacy_navigation(
    dash, browser, width, theme
):
    context, page, errors, external = open_console(
        dash, browser, width=width, theme=theme
    )
    from agent_market.workspace_admin_events import migrate

    migrate(dash[0].store, b"synthetic-reviewed-command-key-32")
    failures = []
    records = []
    http_errors = []
    page.on(
        "response",
        lambda response: http_errors.append((response.status, response.url))
        if response.status >= 400
        else None,
    )
    try:
        sign_in(page)
        for screen in DESIGN["screens"]:
            group = (
                "workflows"
                if screen["group"] == "specialists"
                else "home"
                if screen["group"] == "common"
                else screen["group"]
            )
            url = ORIGIN + "/admin/next#/" + group + "/" + screen["id"].lower()
            page.goto(url)
            try:
                expect(page.locator("#adm-main")).to_have_attribute(
                    "data-screen", screen["id"], timeout=15000
                )
                expect(page.locator("#adm-main h1").first).to_have_text(screen["title"])
                expect(page.locator("#adm-main")).not_to_contain_text(
                    "화면을 불러오지 못했습니다"
                )
                assert (
                    len(page.locator("#adm-main").inner_text().strip())
                    > len(screen["title"]) + 10
                )
                assert not page.evaluate(
                    "document.documentElement.scrollWidth>innerWidth"
                )
                assert page.locator('a[href^="/admin/ui"]').count() == 0
                record = {
                    "id": screen["id"],
                    "status": "pass",
                    "role": "superadmin",
                    "condition": "isolated initial load; existing fixture data",
                    "file": None,
                }
                (ROOT / "screenshots").mkdir(parents=True, exist_ok=True)
                record["file"] = screen["id"] + "-" + str(width) + "-" + theme + ".png"
                page.screenshot(
                    path=str(ROOT / "screenshots" / record["file"]), full_page=True
                )
                records.append(record)
            except Exception as error:
                failures.append(
                    (
                        screen["id"],
                        str(error)[:600],
                        page.locator("#adm-main").inner_text()[:400],
                    )
                )
        (ROOT / ("screen-results-" + str(width) + "-" + theme + ".json")).write_text(
            json.dumps(
                {
                    "scope": "Isolated authenticated real API and rendering; no production mutations",
                    "screens": records,
                    "failures": failures,
                    "console_errors": errors,
                    "external": external,
                    "http_errors": http_errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        assert not failures, failures
        assert not http_errors, http_errors
        assert not errors, errors
        assert not external, external
    finally:
        context.close()

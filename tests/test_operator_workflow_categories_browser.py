"""Category coverage, filtering and explicit template selection in the Pearl UI."""

# ruff: noqa: F401,F811 -- reusable isolated fixtures
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect
from agent_market.operator_workflow_categories import definitions, CATEGORY_NAMES
from agent_market.operator_workflow_templates import install
from tests.test_operator_workflow_categories import reviewed, proof_world, engine
from tests.test_owned_data_agents_activation import operating
from tests.test_front_workflow_browser import browser


@pytest.fixture(autouse=True)
def candidate_assets(monkeypatch):
    selected = os.environ.get("OPERATOR_CATEGORY_PRESENTATION_ROOT")
    if selected:
        from agent_market.concierge import pearl_view

        monkeypatch.setattr(pearl_view, "ROOT", Path(selected))


@pytest.mark.parametrize("width", [1440, 390])
def test_category_counts_filters_search_and_mobile_selection(
    browser, reviewed, proof_world, operating, width
):
    front, client, _, _, _ = operating
    install(front.store, proof_world.root / "isolated.sqlite3")
    install(
        front.store,
        reviewed.root / "isolated.sqlite3",
        recipes=definitions,
        minimum_per_category={k: 3 for k in CATEGORY_NAMES},
    )
    context = browser.new_context(viewport={"width": width, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def serve(route):
        req = route.request
        url = urlsplit(req.url)
        if url.hostname != "agentconcierge.biz":
            route.abort()
            return
        res = client.request(
            req.method,
            url.path + ("?" + url.query if url.query else ""),
            content=req.post_data,
            headers={
                k: v
                for k, v in req.headers.items()
                if k in ("accept", "content-type", "x-workflow-key")
            },
        )
        route.fulfill(
            status=res.status_code,
            body=res.content,
            headers={
                k: v
                for k, v in res.headers.items()
                if k not in ("content-length", "content-encoding", "transfer-encoding")
            },
        )

    context.route("**/*", serve)
    try:
        page.goto("https://agentconcierge.biz/#workflows")
        expect(page.locator("#pearlWorkflowChoiceState")).to_contain_text("25 published templates")
        assert page.locator("#pearlWorkflowChoices select").count()==0
        consent = page.get_by_role("button", name="Reject Non-Essential", exact=True)
        if consent.count() and consent.is_visible():
            consent.click()
        page.locator("#btnFrontWfViewTemplates").click()
        expect(page.locator("#frontTemplatesGrid .template-card")).to_have_count(8 if width > 700 else 4)
        if width==390:
            page.locator('.wf-library-category-details summary').click()
        for category in CATEGORY_NAMES:
            button = page.locator(
                '#frontTmplCategoryFilters [data-category="' + category + '"]'
            )
            expect(button).to_have_count(1)
            button.click()
            expect(button).to_have_attribute("aria-pressed", "true")
            expect(page.locator("#frontTemplatesGrid .template-card")).to_have_count(
                4 if category == "dev_tools" else 3
            )
        expect(
            page.locator('#frontTmplCategoryFilters [data-category="all"]')
        ).to_have_text("All Categories (25)")
        assert page.evaluate("document.documentElement.scrollWidth-innerWidth") <= 1
        out = Path("reports/operator-template-categories-2026-10-25/screenshots")
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / f"docs-category-{width}.png"), full_page=True)
        page.locator("#frontTmplSearchInput").fill("licensing")
        expect(page.locator("#frontTemplatesGrid .template-card")).to_have_count(1)
        page.locator("#frontTemplatesGrid .template-card").get_by_role(
            "button", name="Use workflow", exact=True
        ).click()
        expect(page.locator("#frontWfActiveName")).to_have_text(
            "Software Licensing Reference Pack"
        )
        expect(page.locator("#btnFrontRunWorkflow")).to_be_enabled()
        page.wait_for_function(
            '() => {const r=document.querySelector("#frontWfActiveName").getBoundingClientRect();return r.top>=-1&&r.top<innerHeight/2}'
        )
        assert not errors
    finally:
        context.close()

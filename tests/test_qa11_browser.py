"""QA11 browser reproducers on disposable apps; no production writes."""

# ruff: noqa: F811
import json
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from tests.test_single_agent_chat_browser import chat_page  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_customer_identity import customer  # noqa: F401

OUT = Path("reports/qa11-remediation-2026-10-30")


@pytest.mark.parametrize("chat_page", ["published"], indirect=True)
@pytest.mark.parametrize(
    "width,theme", [(1366, "light"), (390, "light"), (1366, "dark")]
)
@pytest.mark.parametrize("revision", ["baseline", "fixed"])
def test_test_page_initial_layout_is_stable(chat_page, width, theme, revision):
    page, requests, _, errors, _ = chat_page
    page.set_viewport_size({"width": width, "height": 900})
    page.emulate_media(color_scheme=theme)
    if revision == "baseline":
        assets = Path(
            "gateway-data/services/releases/qa10-remediation-frontend-20261029-r1/new/en/assets"
        )

        def original_asset(route):
            name = Path(urlsplit(route.request.url).path).name
            asset = assets / name
            if asset.is_file() and asset.suffix in (".css", ".js"):
                route.fulfill(
                    status=200,
                    body=asset.read_bytes(),
                    content_type="text/css"
                    if asset.suffix == ".css"
                    else "application/javascript",
                )
            else:
                route.fallback()

        page.route("**/new/en/assets/**", original_asset)
    page.add_init_script(
        "window.__shifts=[];new PerformanceObserver(l=>l.getEntries().forEach(e=>{if(!e.hadRecentInput)window.__shifts.push({value:e.value,sources:e.sources.map(s=>({node:s.node?.id||s.node?.className||s.node?.tagName,old:s.previousRect,new:s.currentRect}))})})).observe({type:'layout-shift',buffered:true});"
    )
    page.goto("https://agentconcierge.biz/new/en/test.html")
    page.wait_for_timeout(1800)
    shifts = page.evaluate("window.__shifts")
    cls = sum(row["value"] for row in shifts)
    data = {
        "width": width,
        "theme": theme,
        "cls": cls,
        "shifts": shifts,
        "requests": requests,
        "isolated": True,
        "revision": revision,
    }
    (OUT / f"test-cls-{revision}-{width}-{theme}.json").write_text(
        json.dumps(data, indent=2) + "\n"
    )
    page.screenshot(
        path=str(OUT / f"test-page-{revision}-{width}-{theme}.png"), full_page=True
    )
    assert not errors, errors
    if revision == "fixed":
        assert cls < 0.1, data


@pytest.mark.parametrize("chat_page", ["published"], indirect=True)
def test_broad_search_is_catalog_browsing_and_other_panels_stay_hidden(chat_page):
    from playwright.sync_api import expect

    page, _, _, errors, _ = chat_page
    page.goto("https://agentconcierge.biz/new/en/explore.html")
    page.locator("#xQ").fill("mcp")
    page.locator("#xGo").click()
    expect(page.locator("#xSearchHint")).to_contain_text("broad")
    expect(page.locator("#xResults .acard")).to_have_count(3)
    expect(page.locator("#secWorkflows")).not_to_be_visible()
    page.screenshot(path=str(OUT / "explore-broad-mcp.png"), full_page=True)
    assert not errors, errors


@pytest.mark.parametrize("chat_page", ["published"], indirect=True)
def test_chat_four_turns_keep_the_selected_recommendation(chat_page):
    from playwright.sync_api import expect

    page, _, bodies, errors, _ = chat_page
    page.goto("https://agentconcierge.biz/new/en/chat.html")
    for index, phrase in enumerate(
        (
            "MCP weather forecast",
            "tell me more about the second one",
            "can you tell me more about it",
            "how do I connect to it?",
        )
    ):
        page.locator("#chatInput").fill(phrase)
        page.locator("#chatInput").press("Enter")
        expect(page.locator("#chatSubmit")).to_be_enabled(timeout=10000)
        if index == 0:
            chosen = bodies[-1]["data"]["recommendations"][1]["id"]
        else:
            assert bodies[-1]["data"]["recommendations"][0]["id"] == chosen
    page.screenshot(path=str(OUT / "chat-four-turn.png"), full_page=True)
    assert not errors, errors


@pytest.mark.parametrize("chat_page", ["published"], indirect=True)
def test_all_ten_pages_have_usable_targets_in_four_conditions(
    chat_page, catalog, customer
):
    from agent_market.customer_identity_service import router_for

    page, _, _, errors, _ = chat_page
    catalog[2].app.include_router(
        router_for(
            customer.store, b"synthetic-customer-key-32bytes!!!", identity=customer.core
        )
    )
    routes = [
        "/",
        "/new/en/explore.html",
        "/new/en/chat.html",
        "/new/en/test.html",
        "/new/en/workflows.html",
        "/new/en/learn.html",
        "/new/en/agent-status.html",
        "/new/en/list-agent.html",
        "/new/en/about.html",
        "/customer/sign-in",
    ]
    rows = []
    for width, theme in (
        (1366, "light"),
        (390, "light"),
        (320, "light"),
        (1366, "dark"),
    ):
        page.set_viewport_size({"width": width, "height": 900})
        page.emulate_media(color_scheme=theme)
        for route in routes:
            page.goto("https://agentconcierge.biz" + route)
            small = page.evaluate("""() => [...document.querySelectorAll('a,button,input,select,textarea,[role=button],summary')].flatMap(e=>{
                const r=e.getBoundingClientRect(),s=getComputedStyle(e);
                if(!r.width||!r.height||s.display==='none'||s.visibility==='hidden'||e.closest('[aria-hidden=true]')||s.clipPath==='inset(50%)'||s.clip==='rect(0px, 0px, 0px, 0px)'||e.disabled)return [];
                if(e.tagName==='A'&&s.display==='inline')return [];
                if(r.width>=24&&r.height>=24)return [];
                if([...(e.labels||[])].some(l=>{const b=l.getBoundingClientRect();return b.width>=24&&b.height>=24}))return [];
                return [{id:e.id,tag:e.tagName,width:r.width,height:r.height,text:(e.textContent||e.getAttribute('aria-label')||'').trim().slice(0,60)}];
            })""")
            if route == "/customer/sign-in":
                skip = page.get_by_role("link", name="Skip to content", exact=True)
                skip.focus()
                hit = skip.bounding_box()
                assert hit and hit["width"] >= 24 and hit["height"] >= 24, hit
            rows.append(
                {
                    "route": route,
                    "width": width,
                    "theme": theme,
                    "effective_small_targets": small,
                }
            )
    (OUT / "all-pages-targets.json").write_text(json.dumps(rows, indent=2) + "\n")
    assert len(rows) == 40 and not [
        r for r in rows if r["effective_small_targets"]
    ], rows
    assert not errors, errors

"""Real Chromium UI journeys against an isolated PostgreSQL/localhost application."""

from pathlib import Path
import json
import socket
import threading
import time

from fastapi import FastAPI
from playwright.sync_api import sync_playwright, expect
import pytest
import uvicorn

from agent_market.ad_coin.v2.commercial import date_text
from agent_market.ad_coin.v2.http import router_for
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store, uid  # noqa: F401
from tests.test_ad_coin_v2_p1 import p1_suite as _fixture, _activate_campaign

p1_suite = _fixture
OUT = Path("reports/ad-coin-v6.2-ui-performance-2026-11-09")


@pytest.fixture
def live(p1_suite):
    service = p1_suite.service
    service.clock_ms = lambda: time.time_ns() // 1000000
    now = service.clock_ms()
    service.receipt_signer.set_key_status("kid-model-2026", "verify_only")
    service.receipt_signer.register_private_key("kid-ui", p1_suite.signing_key)
    service.receipt_signer.publish_key(
        "kid-ui", not_before_ms=now - 60000, verify_until_ms=now + 86400000
    )
    clearing = service.ledger.create_account(uid(), "external_clearing")
    service.ledger.post(
        "ui-fixture-funding",
        [(clearing, "-20000000"), (p1_suite.available, "20000000")],
        kind="model_seed",
    )
    _activate_campaign(
        p1_suite,
        starts_at=date_text(now - 1000),
        ends_at=date_text(now + 86400000),
        total_budget_atoms="10000000",
        daily_budget_atoms="5000000",
        gross_p1_atoms="1000000",
    )
    app = FastAPI()
    app.include_router(
        router_for(service, resolve_auth=p1_suite.resolver, include_workspace=True)
    )
    from fastapi.staticfiles import StaticFiles

    app.mount("/new/en/assets", StaticFiles(directory="new/en/assets"), name="shared-assets")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=0, log_level="error", access_log=False
        )
    )
    server_thread = threading.Thread(
        target=lambda: server.run(sockets=[sock]), daemon=True
    )
    stop = threading.Event()
    errors = []

    def work():
        while not stop.wait(0.1):
            try:
                service.workers.process_outbox(now_ms=service.clock_ms())
            except Exception as exc:
                errors.append(type(exc).__name__)

    worker = threading.Thread(target=work, daemon=True)
    server_thread.start()
    try:
        deadline = time.monotonic() + 5
        while (
            not server.started
            and server_thread.is_alive()
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert server.started
        worker.start()
        OUT.mkdir(parents=True, exist_ok=True)
        yield p1_suite, "http://127.0.0.1:" + str(sock.getsockname()[1])
        assert not errors, errors[:3]
    finally:
        stop.set()
        if worker.ident:
            worker.join(5)
        server.should_exit = True
        server_thread.join(5)
        sock.close()
        assert not server_thread.is_alive()


def browser_session(playwright, suite, base, **options):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(locale="en-US", **options)
    context.add_cookies(
        [
            {
                "name": "aiac_session",
                "value": suite.user_token,
                "url": base,
                "httpOnly": True,
                "sameSite": "Strict",
            },
            {
                "name": "aiac_csrf",
                "value": suite.user_csrf,
                "url": base,
                "sameSite": "Strict",
            },
        ]
    )
    return browser, context, context.new_page()


def enable_offers(page):
    page.get_by_role("button", name="Open my workspace", exact=True).click()
    expect(page.locator("#connect")).to_have_text("Refresh workspace")
    page.get_by_role("link", name="Your choices", exact=True).click()
    page.get_by_label("Receive optional ad offers").check()
    for label in ("Task category", "Language", "Broad region"):
        page.locator("#preferences-form").get_by_label(label, exact=True).check()
    page.get_by_role("button", name="Review changes", exact=True).click()
    expect(
        page.get_by_role("heading", name="Save these advertising choices?")
    ).to_be_visible()
    page.get_by_role("button", name="Confirm", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Your choices are saved")
    page.get_by_role("link", name="Rewards", exact=True).click()


def choose_offer(page):
    page.locator("#task-category").select_option("research")
    page.locator("#region").select_option("US")
    page.get_by_role("button", name="Find an offer", exact=True).click()
    expect(page.locator("#offer-card")).to_be_visible()


def test_immediate_shell_mobile_choices_dark_theme_and_no_prefetch(live):
    suite, base = live
    with sync_playwright() as p:
        browser, context, page = browser_session(
            p,
            suite,
            base,
            viewport={"width": 390, "height": 844},
            color_scheme="dark",
            reduced_motion="reduce",
        )
        errors = []
        requests = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(base + "/ad-coin/v2", wait_until="networkidle")
        expect(page.get_by_role("heading", level=1)).to_contain_text("Your choice.")
        assert not any("/api/" in url or "/ui/" in url for url in requests)
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.get_by_role("button", name="Open my workspace", exact=True).click()
        expect(page.locator("#connect")).to_have_text("Refresh workspace")
        page.get_by_role("link", name="Your choices", exact=True).click()
        assert not page.get_by_label("Receive optional ad offers").is_checked()
        assert not any(
            page.locator("input[name=context]").nth(n).is_checked() for n in range(3)
        )
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        body = page.locator("body").inner_text()
        for secret in (
            suite.user_token,
            suite.user_csrf,
            suite.user_owner,
            suite.user_principal_id,
        ):
            assert secret not in body
        page.screenshot(path=str(OUT / "mobile-choices-dark.png"), full_page=True)
        assert not errors, errors
        context.close()
        browser.close()


def test_browser_approved_view_earns_reward_without_click_or_quiz(live):
    suite, base = live
    with sync_playwright() as p:
        browser, context, page = browser_session(
            p,
            suite,
            base,
            viewport={"width": 1440, "height": 1100},
            color_scheme="light",
        )
        errors = []
        creative_requests = []
        page.add_init_script("""window.uiLongTasks=[];window.uiLongTaskObserver=false;
          if (PerformanceObserver.supportedEntryTypes.includes('longtask')) {
            window.uiLongTaskObserver=true;
            new PerformanceObserver(list=>window.uiLongTasks.push(...list.getEntries().map(x=>x.duration))).observe({entryTypes:['longtask']});
          }""")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: creative_requests.append(request.url)
            if request.url.endswith("/creative")
            else None,
        )
        page.goto(base + "/ad-coin/v2")
        enable_offers(page)
        choose_offer(page)
        expect(page.locator("#offer-terms")).to_have_text(
            "Your reward: 0.5 points."
        )
        assert not creative_requests
        page.screenshot(path=str(OUT / "desktop-offer.png"), full_page=True)
        page.get_by_role("button", name="Review & allow ad", exact=True).click()
        expect(
            page.get_by_role("heading", name="Allow this advertisement?")
        ).to_be_visible()
        assert not creative_requests
        page.get_by_role("button", name="Confirm", exact=True).click()
        expect(page.locator("#creative-card")).to_be_visible()
        expect(page.locator("#outcome-text")).to_contain_text(
            "Your reward is confirmed", timeout=28000
        )
        expect(page.locator("#balance")).to_have_text("0.5")
        assert len(creative_requests) == 1
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert not errors, errors
        metrics = page.evaluate("""() => ({paint:performance.getEntriesByType('paint').map(x=>({name:x.name,start_ms:x.startTime})),
          assets:performance.getEntriesByType('resource').filter(x=>['script','link'].includes(x.initiatorType)).map(x=>({bytes:x.encodedBodySize,duration_ms:x.duration})),
          long_task_observer:window.uiLongTaskObserver,long_tasks_ms:window.uiLongTasks,
          navigation:performance.getEntriesByType('navigation').map(x=>({bytes:x.encodedBodySize,dom_ready_ms:x.domContentLoadedEventEnd}))})""")
        (OUT / "browser-performance.json").write_text(
            json.dumps(metrics, indent=2) + "\n"
        )
        page.screenshot(path=str(OUT / "desktop-reward.png"), full_page=True)
        context.close()
        browser.close()


def test_browser_stop_halts_collection_and_campaign_draft_is_usable(live):
    suite, base = live
    with sync_playwright() as p:
        browser, context, page = browser_session(
            p, suite, base, viewport={"width": 1200, "height": 1000}
        )
        page.goto(base + "/ad-coin/v2")
        enable_offers(page)
        choose_offer(page)
        page.get_by_role("button", name="Review & allow ad", exact=True).click()
        page.get_by_role("button", name="Confirm", exact=True).click()
        expect(page.locator("#creative-card")).to_be_visible()
        page.get_by_role("button", name="Stop viewing", exact=True).click()
        expect(page.locator("#outcome-text")).to_contain_text(
            "No reward was issued", timeout=5000
        )
        expect(page.locator("#balance")).to_have_text("0")
        context.clear_cookies()
        context.add_cookies(
            [
                {
                    "name": "aiac_session",
                    "value": suite.editor_token,
                    "url": base,
                    "httpOnly": True,
                    "sameSite": "Strict",
                },
                {
                    "name": "aiac_csrf",
                    "value": "editor-csrf",
                    "url": base,
                    "sameSite": "Strict",
                },
            ]
        )
        page.reload()
        page.get_by_role("button", name="Open my workspace", exact=True).click()
        expect(page.locator("#connect")).to_have_text("Refresh workspace")
        page.get_by_role("link", name="Advertising", exact=True).click()
        page.get_by_role("button", name="New campaign", exact=True).click()
        page.get_by_label("Campaign name", exact=True).fill("Browser campaign")
        # 11-11: targeting is chosen on purpose (no preselected category or region)
        page.locator("#campaign-category").select_option(index=1)
        page.locator("#campaign-region").select_option(index=1)
        page.get_by_label("Advertisement text", exact=True).fill(
            "A focused research notebook for your next project."
        )
        page.locator("#sponsored-only").uncheck()  # this journey uses rewarded views (11-11: Sponsored-only is the default)
        page.locator("#total-budget").fill("4")
        page.locator("#daily-budget").fill("2")
        page.locator("#gross-reward").fill("1")
        page.get_by_role("button", name="Create draft", exact=True).click()
        expect(page.locator("#campaigns")).to_contain_text("Browser campaign")
        row = page.locator("[data-item=campaign]").filter(
            has=page.get_by_role("heading", name="Browser campaign", exact=True)
        )
        row.get_by_role("button", name="Request review", exact=True).click()
        expect(page.locator("#campaigns")).to_contain_text(
            "Independent review is pending"
        )
        from agent_market.ad_coin.v2.commercial import etag

        candidate = next(
            c
            for c in suite.service.store.all("ui_campaigns", (suite.advertiser, ""))
            if json.loads(c["payload_json"])["name"] == "Browser campaign"
        )
        review = suite.service.store.one(
            "review_latest", (candidate["current_revision_id"],)
        )
        evidence = suite.service.record_evidence(review["id"], "a" * 64)
        view = suite.service._review_view(review)
        response = suite.client.post(
            "/api/ad-coin/v2/reviews/" + review["id"] + "/decisions",
            json={
                "revision_hash": view["revision_hash"],
                "verdict": "eligible",
                "reason_code": "verified",
                "evidence_ref": evidence,
            },
            headers=suite.headers(
                "reviewer", **{"If-Match": etag(view), "x-mock-tls": "verified"}
            ),
        )
        assert response.status_code == 200, response.text

        def switch(role):
            token, csrf = (
                (suite.approver_token, "approver-csrf")
                if role == "approver"
                else (suite.editor_token, "editor-csrf")
            )
            context.clear_cookies()
            context.add_cookies(
                [
                    {
                        "name": "aiac_session",
                        "value": token,
                        "url": base,
                        "httpOnly": True,
                        "sameSite": "Strict",
                    },
                    {
                        "name": "aiac_csrf",
                        "value": csrf,
                        "url": base,
                        "sameSite": "Strict",
                    },
                ]
            )
            page.reload()
            page.get_by_role("button", name="Open my workspace", exact=True).click()
            expect(page.locator("#connect")).to_have_text("Refresh workspace")
            page.get_by_role("link", name="Advertising", exact=True).click()
            page.get_by_role("button", name="Show campaigns", exact=True).click()
            expect(page.locator("#campaigns")).to_contain_text("Browser campaign")

        switch("approver")
        before = int(suite.service.ledger.account(suite.available)["balance_atoms"])
        row.get_by_role("button", name="Review and start", exact=True).click()   # approve and start in one step
        expect(page.locator("#review-body")).to_contain_text("Total: 4 coins")
        page.get_by_role("button", name="Confirm", exact=True).click()
        expect(row).to_contain_text("Running")
        switch("editor")
        row.get_by_role("button", name="Pause", exact=True).click()
        expect(row).to_contain_text("Paused")
        switch("approver")
        row.get_by_role("button", name="Resume", exact=True).click()
        expect(row).to_contain_text("Running")
        assert (
            int(suite.service.ledger.account(suite.available)["balance_atoms"])
            == before - 4000000
        )
        page.screenshot(path=str(OUT / "advertiser-campaigns.png"), full_page=True)
        context.close()
        browser.close()


def test_keyboard_contrast_and_untrusted_creative_rendering(live):
    suite, base = live
    with sync_playwright() as p:
        browser, context, page = browser_session(
            p, suite, base, viewport={"width": 1440, "height": 1100}
        )
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/ad-coin/v2")
        page.keyboard.press("Tab")
        expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
        ratios = page.evaluate("""() => {
          const rgb=x=>x.match(/[\\d.]+/g).slice(0,3).map(Number).map(x=>x/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
          const lum=x=>{const c=rgb(x);return .2126*c[0]+.7152*c[1]+.0722*c[2]};
          const ratio=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
          const button=getComputedStyle(document.querySelector('.primary'));
          const body=getComputedStyle(document.body);
          return {button:ratio(button.color,button.backgroundColor),body:ratio(body.color,body.backgroundColor)};
        }""")
        assert min(ratios.values()) >= 4.5, ratios
        (OUT / "contrast.json").write_text(json.dumps(ratios, indent=2) + "\n")
        enable_offers(page)
        choose_offer(page)
        malicious = '<img src=x onerror="window.uiInjected=true">Untrusted ad text'

        def replace_creative(route):
            response = route.fetch()
            body = response.json()
            body["plain_text"] = malicious
            route.fulfill(response=response, json=body)

        page.route("**/exposure-sessions/*/creative", replace_creative)
        page.get_by_role("button", name="Review & allow ad", exact=True).click()
        page.get_by_role("button", name="Confirm", exact=True).click()
        expect(page.locator("#creative-text")).to_have_text(malicious)
        assert page.locator("#creative-text img").count() == 0
        assert page.evaluate("window.uiInjected===undefined")
        page.get_by_role("button", name="Stop viewing", exact=True).click()
        expect(page.locator("#outcome-text")).to_contain_text(
            "No reward was issued", timeout=5000
        )
        assert not errors, errors
        context.close()
        browser.close()


def test_revocation_clears_private_state_and_late_reads_cannot_restore_it(live):
    suite, base = live
    with sync_playwright() as p:
        browser, context, page = browser_session(
            p, suite, base, viewport={"width": 1200, "height": 1000}
        )
        page.goto(base + "/ad-coin/v2")
        page.get_by_role("button", name="Open my workspace", exact=True).click()
        expect(page.locator("#connect")).to_have_text("Refresh workspace")
        held = []

        def hold(route):
            response = route.fetch()
            held.append((route, response))

        page.route("**/wallets/*", hold)
        page.get_by_role("button", name="Refresh balance", exact=True).click()
        deadline = time.monotonic() + 3
        while not held and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert held
        suite.service.access.guards.revoke(suite.user_principal_id, 1)
        page.get_by_role("button", name="Refresh workspace", exact=True).click()
        expect(page.locator("#balance")).to_have_text("—")
        for route, response in held:
            route.fulfill(response=response)
        page.wait_for_timeout(150)
        expect(page.locator("#balance")).to_have_text("—")
        expect(page.locator("#connect")).to_have_text("Open my workspace")
        assert not page.get_by_label("Receive optional ad offers").is_checked()
        context.close()
        browser.close()


@pytest.mark.parametrize("stage", ["human-challenges", "human-consents", "exposure-sessions", "creative"])
def test_navigation_during_ad_approval_never_counts_hidden_view(live, stage):
    suite, base = live
    with sync_playwright() as p:
        browser, context, page = browser_session(
            p, suite, base, viewport={"width": 1200, "height": 1000}
        )
        page.goto(base + "/ad-coin/v2")
        enable_offers(page)
        choose_offer(page)
        held, evidence, errors = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: evidence.append(request.url)
                if request.url.endswith("/evidence") else None)

        def hold(route):
            held.append((route, route.fetch()))

        pattern = "**/exposure-sessions/*/creative" if stage == "creative" else "**/" + stage
        page.route(pattern, hold)
        page.get_by_role("button", name="Review & allow ad", exact=True).click()
        page.get_by_role("button", name="Confirm", exact=True).click()
        deadline = time.monotonic() + 3
        while not held and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert held, stage
        page.get_by_role("link", name="Your choices", exact=True).click()
        for route, response in held:
            route.fulfill(response=response)
        page.unroute(pattern, hold)
        expect(page.locator("#confirm-review")).not_to_have_attribute("aria-busy", "true")
        page.wait_for_timeout(1200)
        expect(page.locator('[data-view="preferences"]')).to_be_visible()
        expect(page.locator("#creative-card")).to_be_hidden()
        page.get_by_role("link", name="Rewards", exact=True).click()
        expect(page.locator("#creative-card")).to_be_hidden()
        expect(page.locator("#balance")).to_have_text("0")
        assert not evidence
        assert not errors, errors
        context.close()
        browser.close()

"""A new advertiser reaches the USDC quote and its confirming state with the keyboard (PM 11-15 walkthrough).

Real Chromium against the /ad-coin/v2 workspace with the real application, campaign, review and paid-booking routes
on a throwaway PostgreSQL cluster, a fake Base chain and a test receive address (never the real wallet). The operator
steps (approve the application, approve the review) are direct calls, as an operator would make them on the admin side.

Fixed by this walkthrough: after a confirmed choice focus returns to the opener or to the line that reports the result
(it fell to the page); the quote card's heading takes focus (it had no tabindex, so the card opened off screen with
focus on the page); a failed refresh of the booking list no longer replaces the payment's status line; the confirming
line says how to check again. tests/manual_quote_walkthrough_server.py serves the same world for a person to try.
"""
import secrets
import socket
import threading
import time

import pytest

from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import _activate_campaign, p1_suite  # noqa: F401

PAY_TO = "0x" + "1" * 40          # a test address on the fake chain, not the real receive wallet
PAYER = "0x" + "2" * 40


class FakeBase:
    """Just enough of a Base RPC: a transaction pays the exact amount to PAY_TO in a given block."""

    def __init__(self):
        self.txs, self.head = {}, 100

    def send(self, amount, block):
        tx = "0x" + secrets.token_hex(32)
        self.txs[tx] = (amount, block)
        return tx

    def receipt(self, tx):
        from agent_market.ad_coin.v2 import paid_bookings as paid
        from agent_market.chain import TRANSFER_TOPIC
        if tx not in self.txs:
            return None
        amount, block = self.txs[tx]
        topic = lambda a: "0x" + a[2:].rjust(64, "0")  # noqa: E731
        return {"status": "0x1", "blockNumber": hex(block), "blockHash": "0x%064x" % block,
                "logs": [{"address": paid.BASE_USDC, "topics": [TRANSFER_TOPIC, topic(PAYER), topic(PAY_TO)],
                          "data": hex(amount)}]}

    def block_number(self):
        return self.head

    def chain_id(self):
        from agent_market.ad_coin.v2 import paid_bookings as paid
        return paid.BASE_CHAIN_ID

    def call(self, method, *params):
        return {"number": hex(0)}


class QuoteWorld:
    """The workspace app plus the operator's side, built on the p1 suite."""

    def __init__(self, suite, *, plans=False):
        from fastapi import FastAPI
        from fastapi.staticfiles import StaticFiles
        from agent_market.ad_coin.v2 import paid_bookings as paid
        from agent_market.ad_coin.v2.advertiser_applications_http import router_for as applications_router
        from agent_market.ad_coin.v2.http import router_for
        from agent_market.ad_coin.v2.paid_bookings_http import router_for as paid_router
        from agent_market.ad_coin.v2.sponsored_booking import SponsoredBookings
        from agent_market.ad_coin.v2.sponsored_booking_http import router_for as coin_booking_router
        from scripts.ad_coin_v2_migrate import migrate_paid
        self.suite, service = suite, suite.service
        self.service = service
        service.clock_ms = lambda: time.time_ns() // 1_000_000
        migrate_paid(service.store)
        if plans:                                      # custom plans (11-15) open once their tables exist
            from scripts.ad_coin_v2_migrate import migrate_paid_plans
            migrate_paid_plans(service.store)
        _activate_campaign(suite)
        # The growth budget stays empty: a new advertiser gets no coins (PM 11:5x) and must still start a
        # Sponsored-only campaign and pay in USDC (PM 11:4x g).
        self.chain = FakeBase()
        self.bookings = paid.PaidBookings(service.store, paid.PaidConfig(pay_to=PAY_TO), rpc=self.chain,
                                          sanctions=paid.Sanctions(addresses=["0x" + "9" * 40]),
                                          taxonomy=service.taxonomy, regions=service.regions,
                                          krw_rate=lambda: "1390.0")
        app = FastAPI()
        app.include_router(router_for(service, resolve_auth=suite.resolver, include_workspace=True))
        app.include_router(paid_router(service, self.bookings, resolve_auth=suite.resolver))
        app.include_router(applications_router(service, resolve_auth=suite.resolver))
        app.include_router(coin_booking_router(service, SponsoredBookings(   # the coin bookings list, as in live_service
            service.store, service.ledger, taxonomy=service.taxonomy, regions=service.regions, access=service.access),
            resolve_auth=suite.resolver))
        app.mount("/new/en/assets", StaticFiles(directory="new/en/assets"), name="shared-assets")
        self.app = app

    def approve_applications(self):
        from agent_market.ad_coin.v2.advertiser_applications import decide, pending
        from agent_market.ad_coin.v2.economy import CoinEconomy
        from tests.test_ad_coin_v2_paid_bookings import operator
        service, done = self.service, []
        economy, op = CoinEconomy(service.store, service.ledger, service.access), operator(self.suite)
        for item in pending(service.access, op).get("items", []):
            key = item.get("id") or item.get("application_id")
            decide(service.access, economy, op, key, approve=True)
            done.append(key)
        return done

    def approve_reviews(self):
        from agent_market.ad_coin.v2 import operator_review
        from tests.test_ad_coin_v2_paid_bookings import operator
        op, done = operator(self.suite), []
        for item in operator_review.pending_reviews(self.service, op).get("items", []):
            key = item.get("id") or item.get("review_id")
            operator_review.decide(self.service, op, key, verdict="eligible", reason_code="verified")
            done.append(key)
        return done

    def pay(self, booking_id, block=99):
        """The advertiser's wallet sends the exact quoted amount; returns the transaction hash."""
        with self.service.store.atomic():
            row = self.service.store.one("paid_booking_get", (booking_id,))
        return self.chain.send(int(row["amount_units"]), block)

    def pay_plan(self, plan_id, block=99):
        with self.service.store.atomic():
            row = self.service.store.one("paid_plan_get", (plan_id,))
        return self.chain.send(int(row["amount_units"]), block)

    def serve(self):
        """Starts the app on a free localhost port; returns (base_url, stop)."""
        import uvicorn
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="error",
                                               access_log=False))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started

        def stop():
            server.should_exit = True
            thread.join(5)
            sock.close()
        return "http://127.0.0.1:%d" % sock.getsockname()[1], stop


@pytest.fixture
def world(p1_suite, request):  # noqa: F811
    built = QuoteWorld(p1_suite, plans=getattr(request, "param", False))
    base, stop = built.serve()
    try:
        yield built, base
    finally:
        stop()


def _focused(page):
    """'' when focus is on the page itself, else the element's id (or its tag when it has none)."""
    return page.evaluate("document.activeElement===document.body||!document.activeElement?'':"
                         "(document.activeElement.id||document.activeElement.tagName)")


@pytest.mark.parametrize("width", [1280, 375])
def test_new_advertiser_reaches_quote_and_confirming_by_keyboard(world, width):
    from playwright.sync_api import expect, sync_playwright
    built, base = world
    suite = built.suite
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(locale="en-US", viewport={"width": width, "height": 900})
            context.add_cookies([
                {"name": "aiac_session", "value": suite.user_token, "url": base, "httpOnly": True, "sameSite": "Strict"},
                {"name": "aiac_csrf", "value": suite.user_csrf, "url": base, "sameSite": "Strict"}])
            page = context.new_page()

            def open_advertising():
                page.goto(base + "/ad-coin/v2")
                page.get_by_role("button", name="Open my workspace", exact=True).click()
                expect(page.locator("#connect")).to_have_text("Refresh workspace")
                page.get_by_role("link", name="Advertising", exact=True).click()

            open_advertising()
            page.locator("#apply-name").fill("Paper Finder Test")      # no listing needed (user decision 11-15)
            page.get_by_role("button", name="Review application", exact=True).click()
            page.get_by_role("button", name="Confirm", exact=True).press("Enter")
            expect(page.locator("#notice")).to_contain_text("Your advertising account is open")
            assert _focused(page) not in ("", "review-title", "confirm-review")     # never the page or the closed card
            assert built.approve_applications() == []                               # approved at once, nobody waits
            expect(page.locator("#apply-form")).to_be_hidden()                      # f: folded into one line
            expect(page.locator("#apply-summary")).to_contain_text("Paper Finder Test")
            expect(page.locator("#advertiser")).to_contain_text("Paper Finder Test")  # e: the name, not a number

            open_advertising()
            page.get_by_role("button", name="New campaign", exact=True).click()
            page.locator("#campaign-name").fill("Paper Finder launch")
            page.locator("#campaign-category").select_option("research")
            page.locator("#campaign-region").select_option("US")
            page.locator("#campaign-text").fill("Searches 200M papers by topic and returns citations with abstracts.")
            page.get_by_role("button", name="Create draft", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Draft created")
            with page.expect_response(lambda r: "review" in r.url and r.request.method == "POST") as asked:
                page.get_by_role("button", name="Request review", exact=True).click()
            assert asked.value.ok
            assert built.approve_reviews()
            page.get_by_role("button", name="Show campaigns", exact=True).click()
            page.get_by_role("button", name="Review and start", exact=True).click()
            page.get_by_role("button", name="Confirm", exact=True).press("Enter")
            expect(page.locator("#notice")).to_contain_text("Campaign started")
            assert _focused(page) == "notice"          # the start button is re-rendered, so the result line

            page.get_by_role("button", name="Book a Sponsored day", exact=True).press("Enter")
            assert _focused(page) == "booking-day"
            page.wait_for_load_state("networkidle")
            expect(page.locator("#open-plan")).to_be_hidden()          # no plan tables yet: single days only
            for _ in range(4):                         # day, category, region, Book with coins, Pay 5 USDC
                page.keyboard.press("Tab")
            assert _focused(page) == "pay-usdc"
            with page.expect_response(lambda r: r.url.endswith("/paid-bookings") and r.request.method == "POST") as made:
                page.keyboard.press("Enter")
            quote = made.value.json()
            assert _focused(page) == "pay-title"       # the quote card is announced and scrolled into view
            amount = page.locator("#pay-amount").inner_text()
            assert amount == quote["amount_usdc"] and not amount.endswith("000000")   # the unique tail
            assert page.locator("#pay-to").inner_text().lower() == PAY_TO
            expect(page.locator("#pay-expiry")).to_contain_text("UTC")
            expect(page.locator("#pay-status")).to_have_text("Waiting for your payment.")
            assert page.evaluate("document.documentElement.scrollWidth") <= width

            for _ in range(3):                         # Copy amount, Copy address, Transaction hash
                page.keyboard.press("Tab")
            assert _focused(page) == "pay-tx"
            page.keyboard.type(built.pay(quote["id"]))
            page.keyboard.press("Enter")
            expect(page.locator("#pay-status")).to_contain_text("Press Confirm payment again to check")
            expect(page.locator("#bookings")).to_contain_text("confirming on Base")

            built.chain.head = 102                      # three confirmations
            page.get_by_role("button", name="Confirm payment", exact=True).press("Enter")
            expect(page.locator("#pay-status")).to_contain_text("Payment confirmed. Your placement is booked for ")
            expect(page.locator("#bookings")).to_contain_text("paid")
        finally:
            browser.close()


@pytest.mark.parametrize("world", [True], indirect=True)
def test_a_budget_becomes_plans_and_one_payment_books_them(world):
    """Custom plans (user decision 11-15): budget and audiences in, up to three plans out, one plan paid once."""
    from playwright.sync_api import expect, sync_playwright
    built, base = world
    suite = built.suite
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(locale="en-US", viewport={"width": 375, "height": 900})
            context.add_cookies([
                {"name": "aiac_session", "value": suite.user_token, "url": base, "httpOnly": True, "sameSite": "Strict"},
                {"name": "aiac_csrf", "value": suite.user_csrf, "url": base, "sameSite": "Strict"}])
            page = context.new_page()

            def open_advertising():
                page.goto(base + "/ad-coin/v2")
                page.get_by_role("button", name="Open my workspace", exact=True).click()
                expect(page.locator("#connect")).to_have_text("Refresh workspace")
                page.get_by_role("link", name="Advertising", exact=True).click()

            open_advertising()
            page.locator("#apply-name").fill("Plan Buyer")
            page.get_by_role("button", name="Review application", exact=True).click()
            page.get_by_role("button", name="Confirm", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Your advertising account is open")
            open_advertising()
            page.get_by_role("button", name="New campaign", exact=True).click()
            page.locator("#campaign-name").fill("Plan launch")
            page.locator("#campaign-category").select_option("research")
            page.locator("#campaign-region").select_option("US")
            page.locator("#campaign-text").fill("Searches papers by topic and returns citations with abstracts.")
            page.get_by_role("button", name="Create draft", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Draft created")
            with page.expect_response(lambda r: "review" in r.url and r.request.method == "POST"):
                page.get_by_role("button", name="Request review", exact=True).click()
            assert built.approve_reviews()
            page.get_by_role("button", name="Show campaigns", exact=True).click()
            page.get_by_role("button", name="Review and start", exact=True).click()
            page.get_by_role("button", name="Confirm", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Campaign started")

            page.get_by_role("button", name="Book a Sponsored day", exact=True).click()
            expect(page.locator("#open-plan")).to_be_visible()
            page.locator("#open-plan").press("Enter")
            assert _focused(page) == "plan-budget"
            page.keyboard.type("12")                               # two placements; 2 USDC left over is not charged
            page.get_by_role("button", name="Show plans", exact=True).press("Enter")
            first = page.locator("#plan-options button").first
            expect(first).to_be_focused()
            expect(page.locator("#plan-options")).to_contain_text("10 USDC")
            assert page.evaluate("document.documentElement.scrollWidth") <= 375
            with page.expect_response(lambda r: r.url.endswith("/paid-plans") and r.request.method == "POST") as made:
                first.press("Enter")
            plan = made.value.json()
            assert plan["placements"] == 2 and _focused(page) == "pay-title"
            assert page.locator("#pay-amount").inner_text() == plan["amount_usdc"] and plan["amount_usdc"].startswith("10.00")
            page.locator("#pay-tx").fill(built.pay_plan(plan["id"]))
            page.get_by_role("button", name="Confirm payment", exact=True).click()
            expect(page.locator("#pay-status")).to_contain_text("Press Confirm payment again to check")
            built.chain.head = 102
            page.get_by_role("button", name="Confirm payment", exact=True).click()
            expect(page.locator("#pay-status")).to_contain_text("Payment confirmed. 2 placements are booked")
            expect(page.locator("#bookings")).to_contain_text("paid")
        finally:
            browser.close()

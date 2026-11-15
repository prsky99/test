"""Manual walkthrough server for the advertiser USDC quote screen (PM 11-15 11:1x). Never touches production.

Run (blocks until logs/ops/quote-walkthrough/stop exists or 40 minutes pass):
  WALKTHROUGH=1 .venv/bin/python -m scripts.pytest_slot --team "AI AD Coin" --minutes 45 \
      tests/manual_quote_walkthrough_server.py
It writes logs/ops/quote-walkthrough/server.json with the local URL. The world is the one
tests/test_ad_coin_v2_paid_quote_browser.py drives (real /ad-coin/v2 workspace and routes, throwaway PostgreSQL,
fake Base chain, test receive address). Test-only helpers (this file only, never in the product):
  /__walkthrough/login?role=user|approver   sets the session cookies and opens /ad-coin/v2
  /__walkthrough/approve                    approves pending advertiser applications as the operator
  /__walkthrough/review                     approves pending campaign reviews as the operator
  /__walkthrough/wallet?booking=<id>        "sends" the exact quoted amount on the fake chain, returns the tx hash
  /__walkthrough/blocks?head=<n>            moves the fake chain head (confirmations)
The file is not named test_*, so normal test runs never collect it.
"""
import json
import os
import time
from pathlib import Path

import pytest

from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import p1_suite  # noqa: F401
from tests.test_ad_coin_v2_paid_quote_browser import QuoteWorld

OUT = Path("logs/ops/quote-walkthrough")


@pytest.mark.skipif(os.environ.get("WALKTHROUGH") != "1", reason="manual walkthrough server")
def test_serve_quote_walkthrough(p1_suite):  # noqa: F811
    from fastapi.responses import JSONResponse, RedirectResponse
    world = QuoteWorld(p1_suite)
    app = world.app

    @app.get("/__walkthrough/login")
    def login(role: str = "approver"):
        token, csrf = ((p1_suite.approver_token, "approver-csrf") if role == "approver"
                       else (p1_suite.user_token, p1_suite.user_csrf))
        reply = RedirectResponse("/ad-coin/v2", status_code=302)
        reply.set_cookie("aiac_session", token, httponly=True, samesite="strict")
        reply.set_cookie("aiac_csrf", csrf, samesite="strict")
        return reply

    @app.get("/__walkthrough/approve")
    def approve():
        return JSONResponse({"approved": world.approve_applications()})

    @app.get("/__walkthrough/review")
    def review():
        return JSONResponse({"approved_reviews": world.approve_reviews()})

    @app.get("/__walkthrough/wallet")
    def wallet(booking: str, block: int = 99):
        return JSONResponse({"tx_hash": world.pay(booking, block)})

    @app.get("/__walkthrough/blocks")
    def blocks(head: int):
        world.chain.head = head
        return JSONResponse({"head": world.chain.head})

    url, stop_server = world.serve()
    OUT.mkdir(parents=True, exist_ok=True)
    stop = OUT / "stop"
    if stop.exists():
        stop.unlink()
    (OUT / "server.json").write_text(json.dumps({"url": url, "advertiser": p1_suite.advertiser,
                                                 "started": time.strftime("%H:%M:%S")}))
    try:
        end = time.monotonic() + 40 * 60
        while not stop.exists() and time.monotonic() < end:
            time.sleep(1)
    finally:
        stop_server()

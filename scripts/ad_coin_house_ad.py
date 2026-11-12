"""Agent Concierge's own Sponsored placement (house ad), made on the server (PM 11-11).

One run, every step idempotent and audited, the same code paths as the advertiser and operator screens:

  1. issue this month's coins into the growth budget        (coins_issued; amount decided by the user)
  2. the "platform (server script)" principal applies for the house advertiser and approves it
                                                             (advertiser_applied / advertiser_approved)
  3. a Sponsored-only campaign: create, request review, operator decision 'eligible'
     (reason platform_house_ad), approve the budget with a fresh proof, activate
  4. book one Sponsored day (first-booking support from the growth budget)

The campaign activation switch (adc2_commercial_control) is turned on in step 3 (PM step 5); no other
campaign is started: the run checks that its own campaign is the only active one.

  .venv/bin/python -m scripts.ad_coin_house_ad plan
  .venv/bin/python -m scripts.ad_coin_house_ad run --issue-coins 10000 --day 2026-11-12 \\
      --dsn-file <dsn> --key-file <workflow key> --key-dir <AD_COIN_V2_KEY_DIR> --i-have-approval

The script principal has no sign-in path: its sessions exist only in this process's memory.
One database connection.
"""
import argparse
import json
import os
import sys
import time
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

BASE = "https://agentconcierge.biz/ad-coin/"
SCRIPT_PRINCIPAL = str(uuid5(NAMESPACE_URL, BASE + "platform-server-script"))
SCRIPT_OWNER = str(uuid5(NAMESPACE_URL, BASE + "platform-server-script/owner"))
HOUSE_NAME = "Agent Concierge"
HOUSE_LISTING = "https://agentconcierge.biz/new/en/index.html"
HOUSE_TEXT = ("Describe a task and Agent Concierge finds AI agents and tools that can do it, "
              "checked by real connection tests.")
SPONSORED_ONLY = "2"          # same marker as the advertiser screen (1ee7bb22)
REASON = "platform_house_ad"
DAY_MS = 86_400_000


def _principal(epoch=1):
    from agent_market.ad_coin.v2.identity import Kind, Principal
    return Principal(UUID(SCRIPT_PRINCIPAL), Kind.HUMAN, epoch, time.time() + 600, owner_id=UUID(SCRIPT_OWNER),
                     csrf_verified=True, audience="aiac-v2-model")


def _client(commercial):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.ad_coin.v2.auth_adapter import CredentialResolver
    from agent_market.ad_coin.v2.http import router_for
    resolver = CredentialResolver(commercial.store)
    token, csrf = "house-" + uuid4().hex, "house-csrf-" + uuid4().hex
    resolver.register_human_session(token, csrf, principal_id=SCRIPT_PRINCIPAL, owner_id=SCRIPT_OWNER)
    app = FastAPI()
    app.include_router(router_for(commercial, resolve_auth=resolver))

    def headers(**extra):
        return {"Authorization": "Bearer " + token, "X-CSRF-Token": csrf, "X-AIAC-Contract": "v6.2",
                "Idempotency-Key": str(uuid4()), **extra}
    return TestClient(app), headers


def _check(response, step):
    if response.status_code != 200:
        raise RuntimeError("%s failed: %s %s" % (step, response.status_code, response.text[:300]))
    return response.json()


def run(commercial, *, month, issue_atoms, day, category="research", region="US", now_ms=None):
    from agent_market.ad_coin.v2 import advertiser_applications as applications
    from agent_market.ad_coin.v2 import operator_review
    from agent_market.ad_coin.v2.access import COMMERCIAL_CAPABILITIES, HUMAN_CAPABILITIES, OPERATOR_CAPABILITY
    from agent_market.ad_coin.v2.commercial import date_text, etag
    from agent_market.ad_coin.v2.contracts import canonical_bytes
    from agent_market.ad_coin.v2.economy import CoinEconomy
    from agent_market.ad_coin.v2.identity import Kind
    from agent_market.ad_coin.v2.sponsored_booking import SponsoredBookings

    store, access = commercial.store, commercial.access
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    out = {}
    economy = CoinEconomy(store, commercial.ledger)
    out["issuance"] = economy.issue_monthly(month, int(issue_atoms))

    access.provision_principal(SCRIPT_PRINCIPAL, Kind.HUMAN, owner_id=SCRIPT_OWNER,
                               capabilities=HUMAN_CAPABILITIES | COMMERCIAL_CAPABILITIES | {OPERATOR_CAPABILITY})
    me = _principal()
    applied = applications.apply(access, me, display_name=HOUSE_NAME, listing_url=HOUSE_LISTING)
    advertiser = applied["application_id"]
    if applications.status_of(store, advertiser) == "pending":
        out["application"] = applications.decide(access, economy, me, advertiser, approve=True)
    for capability in sorted(COMMERCIAL_CAPABILITIES):
        access.grant(advertiser, SCRIPT_PRINCIPAL, capability)

    client, headers = _client(commercial)
    base = "/api/ad-coin/v2/advertisers/" + advertiser + "/campaigns"
    with store.atomic():
        mine = [c for c in store.all("ui_campaigns", (advertiser, "")) if c["state"] != "rejected"]
    if mine:
        campaign = _check(client.get(base + "/" + mine[0]["id"], headers=headers()), "read campaign")
    else:
        body = {"name": HOUSE_NAME, "asset_id": "model:aiac:v2", "total_budget_atoms": SPONSORED_ONLY,
                "daily_budget_atoms": SPONSORED_ONLY, "gross_p1_atoms": SPONSORED_ONLY, "budget_timezone": "UTC",
                "starts_at": date_text(now_ms), "ends_at": date_text(now_ms + 90 * DAY_MS),
                "task_categories": [category], "regions": [region], "creative_text": HOUSE_TEXT,
                "min_exposure_ms": 15000, "split_policy_id": "default_v5", "renderer_profile": "platform_text_v1"}
        campaign = _check(client.post(base, json=body, headers=headers()), "create campaign")
    if campaign["state"] == "draft":
        review = _check(client.post(base + "/" + campaign["id"] + "/review-request",
                                    json={"revision_hash": campaign["revision_hash"]},
                                    headers=headers(**{"If-Match": etag(campaign)})), "request review")
        out["review"] = operator_review.decide(commercial, me, review["id"], verdict="eligible", reason_code=REASON)
        campaign = _check(client.get(base + "/" + campaign["id"], headers=headers()), "read campaign")
    if campaign["state"] == "eligible" and campaign["approval_status"] != "approved":
        intended = commercial.contract.parse(
            "approveCampaign", canonical_bytes({"revision_hash": campaign["revision_hash"],
                                                "fresh_action_id": str(uuid4()), "fresh_action_proof": "p" * 43}),
            path_parameters={"advertiser_id": advertiser, "campaign_id": campaign["id"]}, if_match=etag(campaign))
        challenge = _check(client.post("/api/ad-coin/v2/human-challenges", json={
            "action": "approve_campaign", "target_id": campaign["id"], "target_revision_hash": campaign["revision_hash"],
            "request_digest": intended.semantic_digest}, headers=headers()), "fresh challenge")
        campaign = _check(client.post(base + "/" + campaign["id"] + "/approvals", json={
            "revision_hash": campaign["revision_hash"], "fresh_action_id": challenge["fresh_action_id"],
            "fresh_action_proof": challenge["proof_challenge"]}, headers=headers(**{"If-Match": etag(campaign)})),
            "approve budget")
    if campaign["state"] in ("eligible", "paused") and campaign["approval_status"] == "approved":
        access.set_model_activation(True)                           # PM step 5 (11-11)
        campaign = _check(client.post(base + "/" + campaign["id"] + "/activation",
                                      json={"revision_hash": campaign["revision_hash"]},
                                      headers=headers(**{"If-Match": etag(campaign)})), "activate")
    out["campaign"] = {"id": campaign["id"], "state": campaign["state"], "approval_status": campaign["approval_status"]}

    bookings = SponsoredBookings(store, commercial.ledger, taxonomy=commercial.taxonomy, regions=commercial.regions,
                                 access=access)
    booked = bookings.book(advertiser, campaign_id=campaign["id"], day=day, task_category=category, region=region,
                           request_id=uuid5(NAMESPACE_URL, BASE + "house-booking/" + day + "/" + category + "/" + region).hex,
                           now_ms=now_ms)
    out["booking"] = {k: booked.get(k) for k in ("id", "state", "paid_by", "replayed")}
    out["booking"]["day"] = day
    with store.atomic():
        active = [r["id"] for r in store.all("reconcile_active_campaigns", ())]
    out["advertiser_id"] = advertiser
    out["other_active_campaigns"] = [c for c in active if c != campaign["id"]]   # PM: must stay empty
    return out


def _house(store):
    """The house advertiser (same id the application step derives) and its active campaign, or (id, None)."""
    advertiser = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/applications/"
                           + SCRIPT_PRINCIPAL + "/" + HOUSE_LISTING))
    with store.atomic():
        row = store.one("advertiser_get", (advertiser,))
        campaigns = [c for c in store.all("ui_campaigns", (advertiser, "")) if c["state"] == "active"] if row else []
    return advertiser, row, (campaigns[0]["id"] if campaigns else None)


def _booking_id(advertiser, request_id):
    return str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/sponsored/" + advertiser + "/" + request_id))


def _request_id(day, category, region):
    return uuid5(NAMESPACE_URL, BASE + "house-booking/" + day + "/" + category + "/" + region).hex


def book_regions(commercial, *, day, regions, category="research", check=False, now_ms=None):
    """Book the house ad for one UTC day in more regions (11-12 PM: KR, JP, GB, DE), paid in free coins.

    check=True writes nothing and returns the plan. Otherwise: top up the house account from the growth
    budget by exactly the shortfall (operator grant, audited), then book each region (idempotent)."""
    from agent_market.ad_coin.v2.economy import CoinEconomy
    from agent_market.ad_coin.v2.sponsored_booking import PLACEMENTS_PER_DAY, PRICE_ATOMS, SponsoredBookings, day_ms_of
    store, access = commercial.store, commercial.access
    advertiser, row, campaign = _house(store)
    if row is None or campaign is None:
        raise RuntimeError("house advertiser or its active campaign is missing; run `run` first")
    day_ms = day_ms_of(day)
    plan, to_book = [], []
    with store.atomic():
        balance = int(store.one("account_get", (row["available_account"],))["balance_atoms"])
        for region in regions:
            existing = store.one("sponsored_booking_get", (_booking_id(advertiser, _request_id(day, category, region)),))
            taken = int(store.one("sponsored_booking_day_count", (day_ms, category, region))["n"])
            state = existing["state"] if existing else ("full" if taken >= PLACEMENTS_PER_DAY else "to_book")
            plan.append({"region": region, "state": state, "placements_taken": taken})
            if state == "to_book":
                to_book.append(region)
    shortfall = max(0, len(to_book) * PRICE_ATOMS - balance)
    out = {"advertiser_id": advertiser, "campaign_id": campaign, "day": day, "category": category, "plan": plan,
           "balance_atoms": str(balance), "top_up_atoms": str(shortfall), "written": False}
    if check or not to_book:
        return out
    me = _principal()
    if shortfall:
        out["top_up"] = CoinEconomy(store, commercial.ledger, access).operator_grant(
            me, account_id=row["available_account"], amount_atoms=shortfall,
            reason="house ad Sponsored days " + day + " " + ",".join(to_book),
            request_id=uuid5(NAMESPACE_URL, BASE + "house-topup/" + day + "/" + ",".join(to_book)).hex)
    bookings = SponsoredBookings(store, commercial.ledger, taxonomy=commercial.taxonomy, regions=commercial.regions,
                                 access=access)
    out["bookings"] = []
    for region in to_book:
        booked = bookings.book(advertiser, campaign_id=campaign, day=day, task_category=category, region=region,
                               request_id=_request_id(day, category, region), now_ms=now_ms)
        out["bookings"].append({"region": region, **{k: booked.get(k) for k in ("id", "state", "paid_by", "replayed")}})
    out["written"] = True
    return out


def cancel_regions(commercial, *, day, regions, category="research", check=False, now_ms=None):
    """Rollback, or free a placement for a paying advertiser: cancel the house bookings before the day starts
    (UTC). Coins go back to whoever paid (house account or growth budget); the placement is free again."""
    from agent_market.ad_coin.v2.sponsored_booking import SponsoredBookings
    store = commercial.store
    advertiser, _, _ = _house(store)
    bookings = SponsoredBookings(store, commercial.ledger, taxonomy=commercial.taxonomy, regions=commercial.regions,
                                 access=commercial.access)
    out = {"day": day, "cancelled": [], "skipped": [], "written": not check}
    for region in regions:
        booking_id = _booking_id(advertiser, _request_id(day, category, region))
        with store.atomic():
            existing = store.one("sponsored_booking_get", (booking_id,))
        if existing is None or existing["state"] != "booked":
            out["skipped"].append({"region": region, "state": existing["state"] if existing else "none"})
        elif check:
            out["cancelled"].append({"region": region, "id": booking_id, "would_cancel": True})
        else:
            out["cancelled"].append({"region": region, **bookings.cancel(advertiser, booking_id, now_ms=now_ms)})
    return out


DAILY_REGIONS = ("US", "KR", "JP", "GB", "DE")
DAILY_RESERVE_DAYS = 7          # stop when the growth budget would cover fewer days than this


def _utc_day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def daily(commercial, *, enabled, ledger_check, regions=DAILY_REGIONS, category="research", now_ms=None):
    """Once a day (docs/AD_COIN_HOUSE_AD_DAILY.md, user approval 11-12): make sure the house ad is booked for
    D+1 and D+2 (UTC) in every region. Stops, writing nothing, when the switch is off, the ledger check is not
    clean, the house advertiser does not have exactly one active campaign, or the growth budget holds fewer
    than DAILY_RESERVE_DAYS days. Returns a JSON-able record; 'alert' is true for a stop that needs people."""
    from agent_market.ad_coin.v2.points import GROWTH_ACCOUNT
    from agent_market.ad_coin.v2.sponsored_booking import PRICE_ATOMS
    store = commercial.store
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    today = now_ms - now_ms % DAY_MS
    days = [_utc_day(today + DAY_MS), _utc_day(today + 2 * DAY_MS)]
    advertiser, row, _ = _house(store)
    with store.atomic():
        active = [c for c in store.all("ui_campaigns", (advertiser, "")) if c["state"] == "active"] if row else []
        growth_row = store.one("account_get", (GROWTH_ACCOUNT,))
    growth = int(growth_row["balance_atoms"]) if growth_row else 0
    per_day = len(regions) * PRICE_ATOMS
    out = {"days": days, "regions": list(regions), "growth_atoms": str(growth), "per_day_atoms": str(per_day),
           "days_left": growth // per_day if per_day else None, "stopped": None, "alert": False, "results": []}
    if not enabled:
        out["stopped"] = "switch_off"
    elif len(active) != 1:
        out["stopped"], out["alert"] = "house_campaign_not_single", True
    elif not ledger_check(store).get("ok"):
        out["stopped"], out["alert"] = "ledger_not_clean", True
    elif growth < DAILY_RESERVE_DAYS * per_day:
        out["stopped"], out["alert"] = "growth_budget_low", True
    if out["stopped"]:
        if out["stopped"] != "house_campaign_not_single":
            out["results"] = [book_regions(commercial, day=d, regions=regions, category=category, check=True,
                                           now_ms=now_ms) for d in days]
        return out
    out["results"] = [book_regions(commercial, day=d, regions=regions, category=category, now_ms=now_ms) for d in days]
    with store.atomic():
        out["growth_atoms_after"] = str(int(store.one("account_get", (GROWTH_ACCOUNT,))["balance_atoms"]))
    out["ledger_after"] = ledger_check(store).get("ok")
    out["alert"] = not out["ledger_after"]
    return out


def _switch_on(root):
    """AD_COIN_HOUSE_AD_DAILY=1 in gateway-data/house-ad.env (absent or 0: off). Its own file, read only by this
    script: the services read sponsored.env and agentcon.env with a strict list of names, so a new name there
    would stop releases that do not know it (11-11 f7cd7a83)."""
    try:
        with open(os.path.join(root, "gateway-data/house-ad.env")) as handle:
            lines = [line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")]
    except OSError:
        return False
    return "AD_COIN_HOUSE_AD_DAILY=1" in lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("plan", "run", "book-regions", "cancel-regions", "daily"))
    parser.add_argument("--regions", default="KR,JP,GB,DE")
    parser.add_argument("--check", action="store_true", help="book-regions / cancel-regions: show the plan, write nothing")
    parser.add_argument("--issue-coins", type=int)
    parser.add_argument("--month", default=time.strftime("%Y-%m", time.gmtime()))
    parser.add_argument("--day", help="UTC day to book (tomorrow up to 30 days ahead)")
    parser.add_argument("--category", default="research")
    parser.add_argument("--region", default="US")
    parser.add_argument("--dsn-file")
    parser.add_argument("--key-file")
    parser.add_argument("--key-dir")
    parser.add_argument("--i-have-approval", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "plan":
        print(__doc__)
        return 0
    regions = [r.strip().upper() for r in args.regions.split(",") if r.strip()]
    if args.action == "daily":
        args.day = args.day or "auto"            # daily derives D+1 and D+2 itself
        regions = [r.strip().upper() for r in (args.regions if args.regions != "KR,JP,GB,DE" else ",".join(DAILY_REGIONS)).split(",")]
    if not (args.day and args.dsn_file and args.key_file and args.key_dir) or (args.action == "run" and not args.issue_coins):
        parser.error(args.action + " needs --day, --dsn-file, --key-file and --key-dir (run also --issue-coins)")
    if not args.check and not args.i_have_approval:
        parser.error(args.action + " writes the production ledger; pass --i-have-approval only after approval")
    os.environ["AD_COIN_V2_POOL_MAXIMUM"] = "1"
    os.environ["AD_COIN_V2_KEY_DIR"] = args.key_dir
    from agent_market.ad_coin.v2.live_service import build_live_service, default_key_vault, store_from_application
    from agent_market.ad_coin.v2.points import ATOMS_PER_COIN
    from scripts.ad_coin_v2_migrate import _connect
    runtime = _connect(args)
    try:
        commercial, _, _ = build_live_service(store_from_application(runtime.store), key_vault=default_key_vault())
        if args.action == "daily":
            from scripts.ad_coin_daily_ledger_check import check as ledger_check
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            enabled = _switch_on(root) and not args.check
            result = daily(commercial, enabled=enabled, ledger_check=ledger_check, regions=regions,
                           category=args.category)
            out_dir = os.path.join(root, "logs/ops/house-ad")
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, _utc_day(time.time() * 1000) + ".json"), "w") as handle:
                json.dump(result, handle, indent=1, sort_keys=True, default=str)
        elif args.action == "book-regions":
            result = book_regions(commercial, day=args.day, regions=regions, category=args.category, check=args.check)
        elif args.action == "cancel-regions":
            result = cancel_regions(commercial, day=args.day, regions=regions, category=args.category, check=args.check)
        else:
            result = run(commercial, month=args.month, issue_atoms=args.issue_coins * ATOMS_PER_COIN, day=args.day,
                         category=args.category, region=args.region)
    finally:
        runtime.close()
    print(json.dumps(result, sort_keys=True, default=str))
    return 1 if args.action == "daily" and result.get("alert") else 0


if __name__ == "__main__":
    sys.exit(main())

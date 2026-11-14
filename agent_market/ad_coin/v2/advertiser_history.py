"""One advertiser's history from existing records (no new table, 11-11).

- Operators (platform.operate) see everything on /ad-coin/v2/admin: application events, campaigns,
  coin bookings, paid USDC bookings and the coin balance.
- The advertiser's own updates inbox shows the changes that need their attention, built from the same
  records: application decision, campaign state, bookings, payments and refunds. Read/unread state
  stays in the advertiser's browser.
"""

import json

from .contracts import ContractError
from .ledger import identifier

APPLICATION_EVENTS = {"advertiser_applied": "Application received",
                      "advertiser_approved": "Application approved: you can create campaigns",
                      "advertiser_rejected": "Application not approved"}
CAMPAIGN_STATES = {"in_review": "In review", "eligible": "Passed review: approve the budget next",
                   "rejected": "Ad not approved: edit it and request a new review", "active": "Running",
                   "paused": "Paused", "suspended": "Suspended by AgentValCon"}
PAID_STATES = {"confirming": "Payment found, confirming on Base", "confirmed": "Payment confirmed: placement booked",
               "review": "Payment under review: we confirm the placement or return the payment to the wallet that paid",
               "refund_due": "Refund on the way to the wallet that paid", "refunded": "Refunded to the wallet that paid",
               "served": "Placement shown"}


def _paid_rows(store, advertiser_id):
    if not store.one("paid_bookings_table")["present"]:
        return []
    return store.all("paid_bookings_by_advertiser", (advertiser_id,))


def history(commercial, principal, advertiser_id):
    commercial.access.require_operator(principal)
    advertiser_id = identifier(advertiser_id)
    store = commercial.store
    with store.atomic():
        row = store.one("advertiser_get", (advertiser_id,))
        if row is None:
            raise ContractError("unknown_advertiser", 404)
        balance = store.one("account_get", (row["available_account"],))
        events = [{"event": e["event_type"], "status": e["status"], "at_ms": int(e["timestamp_ms"]),
                   "details": json.loads(e["details_json"])} for e in store.all("audit_for_target", (advertiser_id,))]
        campaigns = [{"id": c["id"], "name": json.loads(c["payload_json"]).get("name", ""), "state": c["state"],
                      "approval": c["approval_status"]} for c in store.all("ui_campaigns", (advertiser_id, ""))]
        coin = [{"id": b["id"], "day_ms": int(b["day_ms"]), "category": b["task_category"], "region": b["region"],
                 "coins": str(int(b["price_atoms"]) // 1_000_000), "state": b["state"]}
                for b in store.all("sponsored_bookings_by_advertiser", (advertiser_id,))]
        paid = [{"id": p["id"], "day_ms": int(p["day_ms"]), "amount_units": str(int(p["amount_units"])),
                 "state": p["state"], "tx_hash": p["tx_hash"], "payer": p["payer"], "note": p["note"],
                 "refund_tx_hash": p["refund_tx_hash"]} for p in _paid_rows(store, advertiser_id)]
    return {"advertiser_id": advertiser_id, "status": row["status"],
            "coin_balance": str(int(balance["balance_atoms"]) // 1_000_000) if balance else "0",
            "events": events, "campaigns": campaigns, "coin_bookings": coin, "paid_bookings": paid}


def updates(store, advertiser_id):
    """The advertiser's inbox; the caller has checked the advertiser authority."""
    advertiser_id = identifier(advertiser_id)
    items = []
    with store.atomic():
        for e in store.all("audit_for_target", (advertiser_id,)):
            if e["event_type"] in APPLICATION_EVENTS:
                items.append({"key": e["event_type"], "at_ms": int(e["timestamp_ms"]), "kind": "application",
                              "text": APPLICATION_EVENTS[e["event_type"]]})
        for c in store.all("ui_campaigns", (advertiser_id, "")):
            if c["state"] in CAMPAIGN_STATES:
                name = json.loads(c["payload_json"]).get("name", "")
                items.append({"key": "campaign:" + c["id"] + ":" + c["state"] + ":" + str(c["version"]), "at_ms": None,
                              "kind": "campaign", "text": name + " · " + CAMPAIGN_STATES[c["state"]]})
        for b in store.all("sponsored_bookings_by_advertiser", (advertiser_id,)):
            if b["state"] == "refunded":
                items.append({"key": "booking:" + b["id"] + ":refunded", "at_ms": int(b["created_ms"]), "kind": "booking",
                              "text": "Booking for " + _day(b["day_ms"]) + " cancelled or returned: coins are back in your balance"})
        for p in _paid_rows(store, advertiser_id):
            if p["state"] in PAID_STATES:
                items.append({"key": "paid:" + p["id"] + ":" + p["state"], "at_ms": int(p["confirmed_ms"] or p["quoted_ms"]),
                              "kind": "payment", "text": _day(p["day_ms"]) + " · " + PAID_STATES[p["state"]]})
    items.sort(key=lambda i: -(i["at_ms"] or 0))
    return {"items": items[:50]}


def _day(day_ms):
    import time
    return time.strftime("%Y-%m-%d", time.gmtime(int(day_ms) / 1000)) + " UTC"


REPORT_DAYS = 30
DAY_MS = 86_400_000


def sponsored_report(store, advertiser_id, *, now_ms):
    """Daily served counts of the advertiser's Sponsored placements (last 30 UTC days), by placement,
    category and region. No clicks, no people: only counts. 'available' is false until the count table exists."""
    advertiser_id = identifier(advertiser_id)
    since = int(now_ms) - int(now_ms) % DAY_MS - (REPORT_DAYS - 1) * DAY_MS
    with store.atomic():
        if not store.one("sponsored_impressions_table")["present"]:
            return {"available": False, "rows": [], "totals": {"explore": 0, "chat": 0}}
        names = {c["id"]: json.loads(c["payload_json"]).get("name", "") for c in store.all("ui_campaigns", (advertiser_id, ""))}
        rows = [{"day": _day(r["day_ms"]), "campaign_id": r["campaign_id"], "campaign": names.get(r["campaign_id"], ""),
                 "placement": r["placement"], "task_category": r["task_category"], "region": r["region"],
                 "served": int(r["served"])}
                for r in store.all("sponsored_impressions_for_advertiser", (advertiser_id, since))]
    totals = {"explore": 0, "chat": 0}
    for r in rows:
        totals[r["placement"]] += r["served"]
    return {"available": True, "rows": rows, "totals": totals, "days": REPORT_DAYS}

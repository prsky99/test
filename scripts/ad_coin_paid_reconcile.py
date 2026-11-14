"""Daily reconciliation of USDC paid bookings (F12, PM 11-14). Reads only: the database and Base, never writes.

  .venv/bin/python -m scripts.ad_coin_paid_reconcile --dsn-file <dsn> --key-file <workflow key> [--day 2026-11-14]

For one UTC day (default yesterday) it matches five records against each other:
  1. bookings   adc2_paid_bookings: received that day (confirmed_ms) or placed that day (day_ms)
  2. tx         the payment transaction on Base, read again: still there, same payer, same amount, same block
                as the last recorded block event (adc2_paid_booking_events, when the table exists)
  3. receipts   every USDC transfer that reached the receive address that day (eth_getLogs): each one must belong
                to a booking; an unmatched one is money in without a booking (refund by hand or attach it)
  4. served     a booking placed that day and settled served must have impressions that day (any placement)
  5. KRW        every received payment has a KRW rate, and the monthly export lists it with its KRW value
Writes logs/ops/payment-reconcile/<day>.json {ok, day, counts, findings}. Exit 1 when there is any finding.
"""
import argparse
import csv
import datetime
import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs/ops/payment-reconcile"
DAY_MS = 86_400_000
RECEIVED = ("confirmed", "served", "review", "refund_due", "refunded")
LOG_CHUNK = 5_000


def _units(value):
    return "%d.%06d" % divmod(int(value), 1_000_000)


def reconcile(bookings, *, receipts, transfers, impressions, last_blocks, export_rows, day_ms):
    """Pure check. bookings: dict rows; receipts: tx -> receipt|None|'unavailable'; transfers: [(tx, from, units)]
    into the receive address that day; impressions: (day, campaign, category, region) -> served count;
    last_blocks: booking id -> block hash recorded; export_rows: rows of the monthly CSV. Returns (counts, findings)."""
    from agent_market.chain import normalize, transfers_in
    findings, counts = [], {"bookings": len(bookings), "received": 0, "placed": 0, "transfers_in": len(transfers),
                            "received_units": 0}
    by_tx = {(b["tx_hash"] or "").lower(): b for b in bookings if b["tx_hash"]}
    exported = {r["booking_id"]: r for r in export_rows}

    def find(kind, booking=None, **detail):
        findings.append({"kind": kind, "booking_id": booking["id"] if booking else None, **detail})

    for b in bookings:
        received = b["state"] in RECEIVED and b["confirmed_ms"] is not None and \
            day_ms <= int(b["confirmed_ms"]) < day_ms + DAY_MS
        if received:
            counts["received"] += 1
            counts["received_units"] += int(b["amount_units"])
            receipt = receipts.get((b["tx_hash"] or "").lower())
            if receipt == "unavailable":
                find("chain_unreadable", b, tx=b["tx_hash"])
            elif receipt is None:
                find("payment_missing_on_chain", b, tx=b["tx_hash"])
            else:
                paid = [(frm, amt) for frm, to, amt in transfers_in(receipt, b["token"]) if to == normalize(b["pay_to"])]
                if int(receipt.get("status", "0x0"), 16) != 1 or not paid:
                    find("payment_not_as_recorded", b, tx=b["tx_hash"])
                elif {frm for frm, _ in paid} != {normalize(b["payer"] or "")}:
                    find("payer_differs", b, tx=b["tx_hash"])
                elif sum(a for _, a in paid) != int(b["amount_units"]) and b["state"] in ("confirmed", "served"):
                    find("amount_differs", b, tx=b["tx_hash"], paid=_units(sum(a for _, a in paid)))
                recorded = last_blocks.get(b["id"])
                if recorded and str(receipt.get("blockHash", "")).lower() != recorded:
                    find("block_differs_from_record", b, tx=b["tx_hash"])
            if not b["krw_rate"] and b["state"] in ("confirmed", "served"):
                find("krw_rate_missing", b)
            row = exported.get(b["id"])
            if row is None:
                find("missing_from_monthly_export", b)
            elif row["amount_usdc"] != _units(b["amount_units"]) or (row["tx_hash"] or "") != (b["tx_hash"] or ""):
                find("export_differs", b)
        if int(b["day_ms"]) == day_ms and b["state"] in ("served", "confirmed"):
            counts["placed"] += 1
            if b["state"] == "served" and not impressions.get((day_ms, b["campaign_id"], b["task_category"], b["region"])):
                find("served_without_impressions", b)
    for tx, frm, units in transfers:
        booking = by_tx.get(tx.lower())
        if booking is None:
            find("receipt_without_booking", None, tx=tx, sender=frm, amount=_units(units))
        elif booking["state"] in ("quoted", "confirming", "expired"):
            find("receipt_for_unconfirmed_booking", booking, tx=tx, state=booking["state"])
    return counts, findings


def block_at(rpc, timestamp_s):
    """The first block at or after a UTC timestamp (binary search on block timestamps)."""
    low, high = 0, rpc.block_number()

    def stamp(n):
        return int(rpc.call("eth_getBlockByNumber", hex(n), False)["timestamp"], 16)
    if stamp(high) < timestamp_s:
        return high + 1
    while low < high:
        mid = (low + high) // 2
        if stamp(mid) < timestamp_s:
            low = mid + 1
        else:
            high = mid
    return low


def transfers_to(rpc, token, pay_to, first, last):
    from agent_market.chain import TRANSFER_TOPIC, topic_to_address
    out, start = [], first
    while start <= last:
        end = min(last, start + LOG_CHUNK - 1)
        logs = rpc.call("eth_getLogs", {"address": token, "fromBlock": hex(start), "toBlock": hex(end),
                                        "topics": [TRANSFER_TOPIC, None, "0x" + pay_to[2:].rjust(64, "0")]})
        out += [(log["transactionHash"], topic_to_address(log["topics"][1]), int(log["data"], 16)) for log in logs]
        start = end + 1
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn-file", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--day", help="UTC day YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--rpc", default=os.environ.get("AD_COIN_PAID_RPC_URL", "https://mainnet.base.org"))
    args = parser.parse_args(argv)
    day = args.day or (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    day_ms = int(datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
    from agent_market.ad_coin.sql_registry import unchecked
    from agent_market.ad_coin.v2.live_service import store_from_application
    from agent_market.ad_coin.v2.paid_bookings import BASE_CHAIN_ID, BASE_USDC, pay_to_from_file
    from agent_market.chain import RPC
    from scripts.ad_coin_v2_migrate import _connect
    runtime = _connect(args)
    try:
        store = store_from_application(runtime.store)
        with unchecked(), store.atomic():
            db = store.database
            bookings = [dict(r) for r in db.all(
                "SELECT * FROM adc2_paid_bookings WHERE (confirmed_ms>=? AND confirmed_ms<?) OR day_ms=?",
                (day_ms, day_ms + DAY_MS, day_ms))]
            impressions = {}
            if db.one("SELECT to_regclass('adc2_sponsored_impressions') IS NOT NULL AS present")["present"]:
                for r in db.all("SELECT day_ms,campaign_id,task_category,region,SUM(served) AS n FROM "
                                "adc2_sponsored_impressions WHERE day_ms=? GROUP BY 1,2,3,4", (day_ms,)):
                    impressions[(int(r["day_ms"]), r["campaign_id"], r["task_category"], r["region"])] = int(r["n"])
            last_blocks = {}
            if db.one("SELECT to_regclass('adc2_paid_booking_events') IS NOT NULL AS present")["present"]:
                for b in bookings:
                    r = store.one("paid_event_last_block", (b["id"],))
                    if r is not None:
                        last_blocks[b["id"]] = r["block_hash"]
            month_start = datetime.datetime.fromtimestamp(day_ms / 1000, datetime.timezone.utc).replace(day=1)
            month_end = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            month_rows = [dict(r) for r in store.all("paid_bookings_month", (int(month_start.timestamp() * 1000),
                                                                             int(month_end.timestamp() * 1000)))]
    finally:
        runtime.close()
    export_rows = _export(month_rows)
    rpc = RPC(args.rpc)
    findings_extra, receipts, transfers = [], {}, []
    try:
        if rpc.chain_id() != BASE_CHAIN_ID:
            raise RuntimeError("not Base mainnet")
        for b in bookings:
            if b["tx_hash"]:
                try:
                    receipts[b["tx_hash"].lower()] = rpc.receipt(b["tx_hash"])
                except Exception:
                    receipts[b["tx_hash"].lower()] = "unavailable"
        pay_to = pay_to_from_file(os.path.join(ROOT, "gateway-data/usdc-receive-address.txt"))
        if pay_to:
            first, last = block_at(rpc, day_ms // 1000), block_at(rpc, (day_ms + DAY_MS) // 1000) - 1
            transfers = transfers_to(rpc, BASE_USDC, pay_to, first, last)
        else:
            findings_extra.append({"kind": "receive_address_unknown", "booking_id": None})
    except Exception as error:   # recorded, never hidden
        findings_extra.append({"kind": "chain_unreadable", "booking_id": None, "error": type(error).__name__})
    counts, findings = reconcile(bookings, receipts=receipts, transfers=transfers, impressions=impressions,
                                 last_blocks=last_blocks, export_rows=export_rows, day_ms=day_ms)
    findings += findings_extra
    counts["received_usdc"] = _units(counts.pop("received_units"))
    result = {"day": day, "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ok": not findings,
              "counts": counts, "findings": findings}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (day + ".json")).write_text(json.dumps(result, indent=1, sort_keys=True))
    print(json.dumps({"ok": result["ok"], "day": day, "counts": counts, "findings": [f["kind"] for f in findings][:10]}))
    return 0 if result["ok"] else 1


def _export(month_rows):
    """The monthly export as the operator downloads it (same code path), parsed back into rows."""
    from agent_market.ad_coin.v2.paid_bookings import PaidBookings

    class _Store:
        def atomic(self):
            from contextlib import nullcontext
            return nullcontext()

        def all(self, name, args):
            return month_rows

    class _Access:
        def require_operator(self, principal):
            return None
    text = PaidBookings.monthly_csv(type("S", (), {"store": _Store()})(), _Access(), None,
                                    datetime.datetime.fromtimestamp(int(month_rows[0]["confirmed_ms"]) / 1000,
                                                                    datetime.timezone.utc).strftime("%Y-%m")) \
        if month_rows else "confirmed_utc,booking_id,state,amount_usdc,payer,tx_hash,krw_per_usdc,amount_krw,refund_tx_hash\n"
    return list(csv.DictReader(io.StringIO(text)))


if __name__ == "__main__":
    sys.exit(main())

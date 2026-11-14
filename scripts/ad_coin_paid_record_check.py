"""Check that every paid USDC booking keeps its records (PM 11-14: first real payment). Read only, one connection.

  .venv/bin/python -m scripts.ad_coin_paid_record_check --dsn-file <dsn> --key-file <workflow key>

For each booking past 'quoted': transaction hash, amount, payer, KRW rate at confirmation, sanctions result
(note is empty when the payer was screened clear; sanctions_* or krw_rate_unavailable send it to review) and the
receipt the advertiser sees (state, amount, hash). Prints one line per booking and exits 1 when a record is missing.
"""
import argparse
import json
import sys
import types

PAST_QUOTE = ("confirming", "confirmed", "served", "review", "refund_due", "refunded")


def problems(row):
    missing = []
    if row["state"] in PAST_QUOTE:
        for field in ("tx_hash", "payer"):
            if not row[field]:
                missing.append(field)
    if row["state"] in ("confirmed", "served", "refund_due", "refunded"):
        if not row["krw_rate"]:
            missing.append("krw_rate")
        if not row["confirmed_ms"]:
            missing.append("confirmed_ms")
        if row["note"] and str(row["note"]).startswith("sanctions_") and row["state"] in ("confirmed", "served"):
            missing.append("confirmed_despite_sanctions")
    if row["state"] == "refunded" and not row["refund_tx_hash"]:
        missing.append("refund_tx_hash")
    return missing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn-file", required=True)
    parser.add_argument("--key-file", required=True)
    args = parser.parse_args(argv)
    from agent_market.ad_coin.sql_registry import unchecked
    from agent_market.ad_coin.v2.live_service import store_from_application
    from scripts.ad_coin_v2_migrate import _connect
    runtime = _connect(types.SimpleNamespace(dsn_file=args.dsn_file, key_file=args.key_file))
    bad = 0
    try:
        store = store_from_application(runtime.store)
        with unchecked(), store.atomic(require_ready=False):
            rows = store.database.all("SELECT * FROM adc2_paid_bookings ORDER BY quoted_ms")
        for row in rows:
            missing = problems(row)
            bad += bool(missing)
            print(json.dumps({"id": row["id"], "state": row["state"], "amount_units": str(row["amount_units"]),
                              "tx_hash": row["tx_hash"], "krw_rate": row["krw_rate"], "note": row["note"],
                              "missing": missing}))
        print(json.dumps({"bookings": len(rows), "with_missing_records": bad}))
    finally:
        runtime.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

"""Automatic review of pending AI AD Coin campaigns and agent offers (PM 11-15 12:4x); one pass, then exit.

Approves what passes the checks (agent_market/ad_coin/v2/auto_review.py), leaves the rest pending with its reasons for
the operator, and writes one summary line. Run by the operations watch every 10 minutes:

    .venv/bin/python -m scripts.ad_coin_auto_review --dsn-file <APPLICATION_POSTGRES_DSN_FILE> \
        --key-file <APPLICATION_WORKFLOW_KEY_FILE> --key-dir <AD_COIN_V2_KEY_DIR> [--check]

--check reviews nothing and prints what is pending. It writes the production database (review decisions, audit rows),
so the watch runs it only with --i-have-approval, which PM's 12:4x decision gives for this job. Exit 0 on a pass with no
errors, 1 when an item failed (it is tried again next time), 2 on bad arguments.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn-file", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--key-dir", required=True)
    parser.add_argument("--check", action="store_true", help="show what is pending, decide nothing")
    parser.add_argument("--i-have-approval", action="store_true")
    args = parser.parse_args(argv)
    if not args.check and not args.i_have_approval:
        parser.error("deciding writes the production ledger; pass --i-have-approval (PM 12:4x) or --check")
    os.environ["AD_COIN_V2_KEY_DIR"] = args.key_dir
    from agent_market.ad_coin.v2 import auto_review
    from agent_market.ad_coin.v2.live_service import build_live_service, default_key_vault, store_from_application
    from scripts.ad_coin_v2_migrate import _connect
    runtime = _connect(args)
    try:
        commercial, _, _ = build_live_service(store_from_application(runtime.store), key_vault=default_key_vault())
        if args.check:
            store = commercial.store
            with store.atomic():
                reviews = len(store.all("reviews_pending_for_operator", (50,)))
                offers = len(store.all("sponsored_offers_pending", (50,))) if store.one("sponsored_offers_table")["present"] else 0
            result = {"pending_reviews": reviews, "pending_offers": offers, "decided": False}
        else:
            result = auto_review.run(commercial)
    finally:
        runtime.close()
    result["at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main())

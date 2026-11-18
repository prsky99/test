"""Write the measured-reach snapshot for the operator budget table on /ad-coin/v2/admin (PM 11-18 19:13, 19:4x).

    .venv/bin/python -m scripts.ad_coin_reach_snapshot            # writes gateway-data/ads/reach-7d.json
    .venv/bin/python -m scripts.ad_coin_reach_snapshot --print    # prints it, writes nothing

Reads counts only: deploy/ops/adcoin-reach-7d.sql through scripts.prod_ro_sql (read-only, one connection) and the
necklace served log (agent_market.ad_coin.v2.sponsored_agent.necklace_ad_served) for the same 7 days. Meant for one
run a day (the 09:20 scheduled task); the screen re-reads the file when it changes and hides the table when it is older than 3 days.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "deploy/ops/adcoin-reach-7d.sql"


def main(argv=None):
    from agent_market.ad_coin.v2 import reach
    from agent_market.ad_coin.v2.sponsored_agent import necklace_ad_served, necklace_log_path
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--print", action="store_true", help="print the snapshot, write nothing")
    args = parser.parse_args(argv)
    run = subprocess.run([sys.executable, "-m", "scripts.prod_ro_sql", str(SQL)], cwd=ROOT, capture_output=True,
                         text=True, timeout=60)
    if run.returncode != 0:
        print("prod_ro_sql failed (%d): %s" % (run.returncode, run.stderr.strip()[-300:]), file=sys.stderr)
        return 1
    booked, shown = reach.parse_counts(run.stdout.splitlines())
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.gmtime(now - 86400))   # the window ends with yesterday (UTC)
    path = necklace_log_path()
    # the necklace log sums by count day including today, so its figure covers the 7 days to now (necklace_window)
    necklace = sum(necklace_ad_served(days=reach.WINDOW_DAYS, path=path).values()) if path else 0
    snapshot = reach.build_snapshot(booked, shown, necklace, measured_at=now, through_day=today)
    snapshot["necklace_window"] = "last 7 days to now"
    if args.print:
        print(json.dumps(snapshot, indent=1, sort_keys=True))
        return 0
    reach.write_snapshot(ROOT / reach.SNAPSHOT, snapshot)
    print("written %s: %s" % (reach.SNAPSHOT, json.dumps(snapshot, sort_keys=True)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

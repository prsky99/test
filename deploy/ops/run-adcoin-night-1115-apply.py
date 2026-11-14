"""Apply migrate-night-1115 to the production database (AI AD Coin, user-run after approval via PM, 11-15).

  .venv/bin/python deploy/ops/run-adcoin-night-1115-apply.py --dry-run   # checks only, touches nothing
  .venv/bin/python deploy/ops/run-adcoin-night-1115-apply.py             # checks, then the change

The change (scripts.ad_coin_v2_migrate migrate-night-1115), ad_coin_v2 schema only, no triggers:
  - adc2_sponsored_offers, adc2_sponsored_clicks (agent ads)
  - adc2_sponsored_impressions placement CHECK + 'mcp','a2a' (refused if any existing row would fail it)
  - adc2_paid_booking_events (F12 payment events)
Refuses unless, right before:
  1. the rehearsal command passed within 24 h against exactly the four releases active now
     (logs/ops/db-rehearsal/passed.json; db_change_rehearsal's own check compares only frontend and jobs)
  2. that rehearsal's report: verdict passed, apply ok, four releases ok before and after, every rollback check true,
     no impression row failing the new CHECK
  3. no copy rehearsal is running
After: public triggers still 5, the three tables and the new CHECK present, public pages answer.
Rollback SQL: deploy/ad_coin/rollback-agent-ads-tables-2026-11-14.sql, deploy/ad_coin/rollback-paid-events-2026-11-14.sql
Log: logs/ops/db-apply/adcoin-night-1115-<time>.json
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE = os.path.join(ROOT, "gateway-data/services/state.json")
PASSED = os.path.join(ROOT, "logs/ops/db-rehearsal/passed.json")
REPORT = os.path.join(ROOT, "logs/ops/db-rehearsal/night-1115-adcoin.json")
REHEARSED = os.path.join(ROOT, "gateway-data/ad-coin-commands/migrate-night-1115.cmd")
ENV = os.path.join(ROOT, "gateway-data/agentcon.env")
PUBLIC = "https://agentconcierge.biz"


def active_four():
    with open(STATE) as stream:
        services = json.load(stream)["services"]

    def release(entry):
        if "slots" in entry:
            slot = entry["slots"][entry["active"]]
            return slot["release"] if isinstance(slot, dict) else slot
        return entry["release"]
    return [release(services[role]) for role in ("frontend", "jobs", "admin", "execution")]


def reasons_before():
    sys.path.insert(0, ROOT)
    from scripts.db_change_rehearsal import change_digest
    reasons, releases = [], active_four()
    try:
        with open(REHEARSED) as stream:
            command = stream.read()
        with open(PASSED) as stream:
            record = json.load(stream).get(change_digest(None, command))
    except Exception as error:   # noqa: BLE001
        record, reasons = None, ["rehearsal record unreadable: " + type(error).__name__]
    if not record:
        reasons.append("no passed rehearsal of the rehearsed command")
    else:
        if time.time() - record["at"] > 24 * 3600:
            reasons.append("rehearsal older than 24 h")
        if sorted(record["releases"]) != sorted(releases):
            reasons.append("active releases changed since the rehearsal: %s -> %s" % (record["releases"], releases))
    try:
        with open(REPORT) as stream:
            report = json.load(stream)
        out = json.loads(((report.get("apply") or {}).get("stdout") or "{}").strip().splitlines()[-1])
    except Exception as error:   # noqa: BLE001
        report, out = {}, {}
        reasons.append("rehearsal report unreadable: " + type(error).__name__)
    if report.get("verdict") != "passed" or not (report.get("apply") or {}).get("ok"):
        reasons.append("rehearsal verdict %s" % report.get("verdict"))
    for phase in ("before", "after"):
        checks = report.get(phase) or {}
        if len(checks) < 4 or not all(v.get("ok") for v in checks.values()):
            reasons.append("rehearsal %s check not ok for four releases" % phase)
    if not out.get("ok") or not all(v is True for v in (out.get("rollback_checks") or {}).values()) \
            or len(out.get("rollback_checks") or {}) < 7:
        reasons.append("rollback checks not all true")
    if (out.get("migrated") or {}).get("impressions", {}).get("rows_failing_new_check"):
        reasons.append("impression rows failing the new CHECK in the rehearsal")
    busy = subprocess.run(["pgrep", "-f", r"python[^ ]* -m scripts[.]db_change_rehearsal"], capture_output=True)
    if busy.returncode == 0:
        reasons.append("a copy rehearsal is running")
    return reasons, releases


def env_value(name):
    with open(ENV) as stream:
        for line in stream:
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


def after_checks(dsn_file, key_file):
    sys.path.insert(0, ROOT)
    from agent_market.ad_coin.sql_registry import unchecked
    from agent_market.ad_coin.v2.live_service import store_from_application
    from scripts.ad_coin_v2_migrate import _connect
    runtime = _connect(argparse.Namespace(dsn_file=dsn_file, key_file=key_file))
    try:
        store = store_from_application(runtime.store)
        with unchecked(), store.atomic(require_ready=False):
            db = store.database
            triggers = int(db.one("SELECT count(*) AS n FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                                  "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' "
                                  "AND NOT t.tgisinternal")["n"])
            tables = {t: bool(db.one("SELECT to_regclass(?) IS NOT NULL AS present", (t,))["present"]) for t in
                      ("adc2_sponsored_offers", "adc2_sponsored_clicks", "adc2_paid_booking_events")}
            check = [r["def"] for r in db.all("SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE "
                                              "conrelid='adc2_sponsored_impressions'::regclass AND contype='c'")
                     if "placement" in r["def"]]
    finally:
        runtime.close()
    import httpx
    pages = {}
    for path in ("/ads/library.json", "/api/ad-coin/v2/sponsored/offer?category=web_search&surface=rest"):
        try:
            pages[path] = httpx.get(PUBLIC + path, timeout=10, headers={"X-Agentcon-QA": "adcoin-apply"}).status_code
        except Exception as error:   # noqa: BLE001
            pages[path] = type(error).__name__
    ok = triggers == 5 and all(tables.values()) and len(check) == 1 and "'mcp'" in check[0] \
        and all(v == 200 for v in pages.values())
    return ok, {"public_triggers": triggers, "tables": tables, "placement_check": check, "pages": pages}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    reasons, releases = reasons_before()
    result = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "releases": releases, "refused": reasons, "dry_run": args.dry_run}
    if not reasons and not args.dry_run:
        dsn, key = env_value("APPLICATION_POSTGRES_DSN_FILE"), env_value("APPLICATION_WORKFLOW_KEY_FILE")
        env = {k: v for k, v in os.environ.items() if k not in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE",
                                                                  "PGPASSWORD", "PGSERVICE")}
        run = subprocess.run([os.path.join(ROOT, ".venv/bin/python"), "-m", "scripts.ad_coin_v2_migrate",
                              "migrate-night-1115", "--dsn-file", dsn, "--key-file", key, "--i-have-approval"],
                             cwd=ROOT, env=env, capture_output=True, text=True)
        result["migrate"] = {"returncode": run.returncode, "stdout": run.stdout[-1500:], "stderr": run.stderr[-800:]}
        if run.returncode == 0:
            ok, detail = after_checks(dsn, key)
            result["after"] = detail
            result["ok"] = ok
        else:
            result["ok"] = False
    else:
        result["ok"] = not reasons
    out = os.path.join(ROOT, "logs/ops/db-apply")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "adcoin-night-1115-%s.json" % time.strftime("%Y%m%d-%H%M%S")), "w") as stream:
        json.dump(result, stream, indent=1)
    print(json.dumps(result, indent=1, ensure_ascii=False)[:3000])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

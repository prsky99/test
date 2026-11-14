"""Copy rehearsal command for the 11-15 night (PM 11-14): migrate-night-1115, then try both rollback SQL files.

  db_change_rehearsal run --data minimal --command "... -m scripts.ad_coin_night_1115_rehearse
      --dsn-file {dsn_file} --key-file {key_file} --i-have-approval"

Only for the disposable copy. Steps:
  1. migrate-agent-ads + migrate-paid-events (the change that will run in production)
  2. rollback-paid-events with one event row present: must stop with its "holds payment audit rows" error and keep
     the table (the row goes in with the booking foreign key dropped inside the same transaction; all rolled back)
  3. rollback-paid-events on the empty table: must drop it (inside a transaction that is rolled back)
  4. rollback-agent-ads: must drop both tables and put the explore/chat CHECK back (rolled back as well)
  5. the copy is left migrated, so the rehearsal then checks the four production releases against it
Prints one JSON line; exit 1 if any check fails.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAID_ROLLBACK = ROOT / "deploy/ad_coin/rollback-paid-events-2026-11-14.sql"
ADS_ROLLBACK = ROOT / "deploy/ad_coin/rollback-agent-ads-tables-2026-11-14.sql"


class _Undo(Exception):
    pass


def body(path):
    """The statements of a rollback file without its own BEGIN/COMMIT and comments (run inside our transaction)."""
    lines = [line for line in Path(path).read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("--") and line.strip().upper() not in ("BEGIN;", "COMMIT;")]
    return "\n".join(lines)


def _present(db, name):
    return bool(db.one("SELECT to_regclass(?) IS NOT NULL AS present", (name,))["present"])


def check_rollbacks(store):
    from agent_market.ad_coin.sql_registry import unchecked
    checks = {}
    db = store.database

    # 2. with a row: the guard stops the rollback, the table stays
    try:
        with unchecked(), store.atomic(require_ready=False):
            connection = store._connection()
            for fk in db.all("SELECT conname FROM pg_constraint WHERE conrelid='adc2_paid_booking_events'::regclass "
                             "AND contype='f'"):
                connection.execute('ALTER TABLE adc2_paid_booking_events DROP CONSTRAINT "%s"' % fk["conname"])
            connection.execute("INSERT INTO adc2_paid_booking_events (id, booking_id, at_ms, kind, actor) "
                               "VALUES ('rehearsal-row', 'rehearsal-booking', 0, 'reconcile', 'rehearsal')")
            connection.execute(body(PAID_ROLLBACK))
            checks["paid_events_rollback_stops_with_rows"] = False          # it should have raised
            raise _Undo()
    except _Undo:
        pass
    except Exception as error:   # noqa: BLE001 - the expected stop
        checks["paid_events_rollback_stops_with_rows"] = "holds payment audit rows" in str(error)
    with unchecked(), store.atomic(require_ready=False):
        checks["paid_events_table_kept"] = _present(db, "adc2_paid_booking_events")
        checks["paid_events_foreign_key_kept"] = bool(db.all(
            "SELECT 1 FROM pg_constraint WHERE conrelid='adc2_paid_booking_events'::regclass AND contype='f'"))

    # 3. empty: the rollback drops the table
    try:
        with unchecked(), store.atomic(require_ready=False):
            store._connection().execute(body(PAID_ROLLBACK))
            checks["paid_events_rollback_drops_when_empty"] = not _present(db, "adc2_paid_booking_events")
            raise _Undo()
    except _Undo:
        pass

    # 4. agent ads: both tables gone, the old CHECK back
    try:
        with unchecked(), store.atomic(require_ready=False):
            store._connection().execute(body(ADS_ROLLBACK))
            checks["agent_ads_rollback_drops_tables"] = not _present(db, "adc2_sponsored_offers") and \
                not _present(db, "adc2_sponsored_clicks")
            defs = [r["def"] for r in db.all("SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE "
                                             "conrelid='adc2_sponsored_impressions'::regclass AND contype='c'")
                    if "placement" in r["def"]]
            checks["agent_ads_rollback_restores_check"] = len(defs) == 1 and "'mcp'" not in defs[0] \
                and "'explore'" in defs[0]
            raise _Undo()
    except _Undo:
        pass

    # 5. the copy stays migrated
    with unchecked(), store.atomic(require_ready=False):
        checks["left_migrated"] = all(_present(db, t) for t in
                                      ("adc2_paid_booking_events", "adc2_sponsored_offers", "adc2_sponsored_clicks"))
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn-file", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--i-have-approval", action="store_true")
    args = parser.parse_args(argv)
    if not args.i_have_approval:
        parser.error("--i-have-approval is required (copy rehearsal only)")
    from agent_market.ad_coin.v2.live_service import store_from_application
    from scripts.ad_coin_v2_migrate import _connect, migrate_agent_ads, migrate_paid_events
    runtime = _connect(args)
    try:
        store = store_from_application(runtime.store)
        migrated = {**migrate_agent_ads(store), **migrate_paid_events(store)}
        checks = check_rollbacks(store)
    finally:
        runtime.close()
    ok = all(v is True for v in checks.values()) and migrated.get("paid_events_table") is True
    print(json.dumps({"ok": ok, "migrated": migrated, "rollback_checks": checks}, sort_keys=True, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

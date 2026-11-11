"""Task-level evidence tables (draft for the 11-11 decision request; user approval required).

Two tables in their own schema, task_evidence, so the public schema and its five attested triggers
do not change (11-10 outage: extra public triggers made every attachment fail):

  task_evidence.calls   one row per real call: listing, tool, task kind, source, outcome, latency, time.
                        Nothing about the caller, the arguments or the answer text. Kept 35 days.
  task_evidence.rollup  per listing, tool, task kind and source: attempts and successes in 30 days,
                        last success, median latency. Rebuilt by jobs every 10 minutes; requests read it.

Sources: gateway (calls through /api/gateway), real_task (the daily real-task scorer), test_screen
(the site's own test screen). One connection; the change is additive (CREATE ... IF NOT EXISTS).

    .venv/bin/python -m scripts.task_evidence_schema status   --dsn-file <dsn>
    .venv/bin/python -m scripts.task_evidence_schema migrate  --dsn-file <dsn> --i-have-approval
    .venv/bin/python -m scripts.task_evidence_schema rollback --dsn-file <dsn> --i-have-approval
"""
import argparse
import json
import sys

import psycopg

MIGRATE = (
    "SET lock_timeout='2s'",
    "CREATE SCHEMA IF NOT EXISTS task_evidence",
    """CREATE TABLE IF NOT EXISTS task_evidence.calls(
        id bigserial PRIMARY KEY,
        resource_id bigint NOT NULL,
        tool text NOT NULL DEFAULT '',
        task_kind text NOT NULL DEFAULT 'other',
        source text NOT NULL CHECK (source IN ('gateway','real_task','test_screen')),
        outcome text NOT NULL CHECK (outcome IN ('succeeded','failed','needs_key')),
        latency_ms integer,
        at double precision NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS calls_resource_at ON task_evidence.calls(resource_id, at)",
    "CREATE INDEX IF NOT EXISTS calls_at ON task_evidence.calls(at)",
    """CREATE TABLE IF NOT EXISTS task_evidence.rollup(
        resource_id bigint NOT NULL,
        tool text NOT NULL,
        task_kind text NOT NULL,
        source text NOT NULL,
        attempts_30d integer NOT NULL,
        successes_30d integer NOT NULL,
        needs_key_30d integer NOT NULL,
        last_success_at double precision,
        last_outcome text NOT NULL,
        median_latency_ms integer,
        updated_at double precision NOT NULL,
        PRIMARY KEY (resource_id, tool, task_kind, source))""",
)
ROLLBACK = ("SET lock_timeout='2s'", "DROP SCHEMA IF EXISTS task_evidence CASCADE")


def status(connection):
    tables = [row[0] for row in connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='task_evidence' ORDER BY 1").fetchall()]
    triggers = connection.execute("""SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal""").fetchone()[0]
    return {'tables': tables, 'public_triggers': triggers}


def run(connection, statements):
    before = status(connection)
    if before['public_triggers'] != 5:
        raise SystemExit('refused: public triggers %s' % before)
    with connection.transaction():
        for sql in statements:
            connection.execute(sql)
    after = status(connection)
    if after['public_triggers'] != 5:
        raise SystemExit('unexpected public trigger count %s' % after)
    return {'before': before, 'after': after}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('action', choices=('status', 'migrate', 'rollback'))
    parser.add_argument('--dsn-file', required=True)
    parser.add_argument('--i-have-approval', action='store_true')
    args = parser.parse_args(argv)
    if args.action != 'status' and not args.i_have_approval:
        parser.error(args.action + ' changes the database; pass --i-have-approval only after approval')
    with psycopg.connect(open(args.dsn_file).read().strip(), autocommit=True) as connection:
        if args.action == 'migrate':
            result = run(connection, MIGRATE)
        elif args.action == 'rollback':
            result = run(connection, ROLLBACK)
        else:
            result = status(connection)
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())

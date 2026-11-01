"""Create the console retention indexes on an existing PostgreSQL store without blocking writes.

Usage (operator, explicit; no server restart needed):
  .venv/bin/python -m scripts.admin_console_indexes --dsn-file gateway-data/postgres18/application.dsn          # check only
  .venv/bin/python -m scripts.admin_console_indexes --dsn-file gateway-data/postgres18/application.dsn --apply  # build

Each index is built with CREATE INDEX CONCURRENTLY outside any transaction, so the gateway keeps
writing while it builds. An interrupted concurrent build leaves an INVALID index; the check reports
it and --apply drops and rebuilds only that index.
"""
import argparse
import json
import time


def state(connection):
    from agent_market.admin_query_indexes import RETENTION_INDEXES
    result = {}
    for name, table, _, _ in RETENTION_INDEXES:
        row = connection.execute('''SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid=c.oid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=%s''', (name,)).fetchone()
        result[name] = {'table': table, 'state': 'missing' if row is None else 'valid' if row[0] else 'invalid'}
    return result


def build(connection):
    """Build missing or invalid retention indexes on an autocommit connection; returns seconds per index."""
    from agent_market.admin_query_indexes import RETENTION_INDEXES, retention_index_sql
    before, built = state(connection), {}
    for (name, _, _, _), statement in zip(RETENTION_INDEXES, retention_index_sql(concurrently=True)):
        if before[name]['state'] == 'valid':
            continue
        if before[name]['state'] == 'invalid':
            connection.execute('DROP INDEX CONCURRENTLY IF EXISTS ' + name)
        started = time.monotonic()
        connection.execute(statement)
        built[name] = round(time.monotonic() - started, 2)
    return before, built


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dsn-file', required=True)
    parser.add_argument('--apply', action='store_true', help='build missing or invalid indexes (default: check only)')
    args = parser.parse_args()
    from agent_market.application_runtime import _connect
    with open(args.dsn_file, encoding='utf-8') as handle:
        connection = _connect(handle.read().strip())  # autocommit: CONCURRENTLY cannot run in a transaction
    try:
        before, built = build(connection) if args.apply else (state(connection), {})
        print(json.dumps({'before': before, 'built_seconds': built, 'after': state(connection) if built else before,
                          'applied': args.apply}, indent=2, sort_keys=True))
    finally:
        connection.close()


if __name__ == '__main__':
    main()

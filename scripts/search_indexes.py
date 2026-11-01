"""Create the catalog search and vector queue indexes on an existing PostgreSQL store without blocking writes.

Usage (operator, explicit; no server restart needed):
  .venv/bin/python -m scripts.search_indexes --dsn-file gateway-data/postgres18/application.dsn          # check only
  .venv/bin/python -m scripts.search_indexes --dsn-file gateway-data/postgres18/application.dsn --apply  # build

Each index is built with CREATE INDEX CONCURRENTLY outside any transaction, so the gateway keeps
reading and writing while it builds. An interrupted concurrent build leaves an INVALID index; the
check reports it and --apply drops and rebuilds only that index. --apply also keeps the searched
table's visibility map current (per-table autovacuum threshold, then one plain VACUUM). Rows are
never changed; revert the threshold with ALTER TABLE resources RESET (autovacuum_vacuum_scale_factor,
autovacuum_vacuum_threshold).
"""
import argparse
import json
import time


def state(connection):
    from agent_market.admin_query_indexes import QUEUE_INDEXES, SEARCH_INDEXES, SEARCH_TABLE_SETTINGS
    result = {}
    for name, table, _, _ in SEARCH_INDEXES + QUEUE_INDEXES:
        row = connection.execute('''SELECT i.indisvalid,pg_relation_size(c.oid) FROM pg_class c JOIN pg_index i ON i.indexrelid=c.oid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=%s''', (name,)).fetchone()
        result[name] = {'table': table, 'state': 'missing' if row is None else 'valid' if row[0] else 'invalid',
                        'bytes': None if row is None else row[1]}
    for table in SEARCH_TABLE_SETTINGS:
        row = connection.execute('''SELECT c.reloptions,c.relallvisible,c.relpages FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=%s''', (table,)).fetchone()
        result['table:' + table] = {'settings': sorted(row[0] or []) if row else None,
                                    'all_visible_pages': row[1] if row else None, 'pages': row[2] if row else None}
    return result


def build(connection):
    """Build missing or invalid search and queue indexes on an autocommit connection; returns seconds per index."""
    from agent_market.admin_query_indexes import (QUEUE_INDEXES, SEARCH_INDEXES, SEARCH_TABLE_SETTINGS,
                                                  queue_index_sql, search_index_sql)
    before, built = state(connection), {}
    for (name, table, _, _), statement in zip(SEARCH_INDEXES + QUEUE_INDEXES,
                                              search_index_sql(concurrently=True) + queue_index_sql(concurrently=True)):
        if before[name]['state'] == 'valid':
            continue
        if before[name]['state'] == 'invalid':
            connection.execute('DROP INDEX CONCURRENTLY IF EXISTS ' + name)
        started = time.monotonic()
        connection.execute(statement)
        connection.execute('ANALYZE ' + table)
        built[name] = round(time.monotonic() - started, 2)
    for table, settings in SEARCH_TABLE_SETTINGS.items():
        wanted = sorted(key + '=' + value for key, value in settings)
        if not set(wanted) <= set(before['table:' + table]['settings'] or ()):
            connection.execute('ALTER TABLE ' + table + ' SET (' + ','.join(wanted) + ')')
            built['settings:' + table] = wanted
        started = time.monotonic()
        connection.execute('VACUUM (ANALYZE) ' + table)  # plain VACUUM: no exclusive lock, no row changes
        built['vacuum:' + table] = round(time.monotonic() - started, 2)
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

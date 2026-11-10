"""Per-kind halfvec HNSW for Explore vector search (draft D', 2026-11-11) and the resources filter cover (P2).

One HNSW graph over every kind answered a kind-filtered search with about 60 of 100 rows and
recall@100 0.26 after touching ~30,000 blocks, because live MCP listings are 12% of the vectors.
This adds agentcon_search.embeddings.kind, fills it from public.resources, and builds one partial
halfvec HNSW per kind. The application (postgres_ann.kind_search) uses them only when the column
and all three valid indexes exist, so the code may be deployed before or after this runs.

Nothing here touches public-schema triggers (the application checks there are exactly five).
Indexes are built CONCURRENTLY (writers are not blocked); the column is added with a 2 s lock
timeout. One connection. The old shared index stays; drop it only after a week (separate approval).

    .venv/bin/python -m scripts.embeddings_kind_indexes status   --dsn-file <dsn>
    .venv/bin/python -m scripts.embeddings_kind_indexes migrate  --dsn-file <dsn> [--cover] --i-have-approval
    .venv/bin/python -m scripts.embeddings_kind_indexes rollback --dsn-file <dsn> [--cover] --i-have-approval
"""
import argparse
import json
import sys
import time

import psycopg

KINDS = ('a2a', 'mcp', 'x402')
BATCH = 10000
COVER = 'resources_id_filter_cover'


def _connect(dsn_file):
    dsn = open(dsn_file).read().strip()
    connection = psycopg.connect(dsn, autocommit=True)
    connection.execute("SET statement_timeout='0'")
    connection.execute("SET maintenance_work_mem='512MB'")
    connection.execute("SET max_parallel_maintenance_workers=0")
    return connection


def status(connection):
    column = bool(connection.execute("""SELECT 1 FROM pg_attribute WHERE attrelid='agentcon_search.embeddings'::regclass
        AND attname='kind' AND NOT attisdropped""").fetchall())
    indexes = {name: (valid, size) for name, valid, size in connection.execute("""SELECT c.relname, i.indisvalid AND i.indisready,
        pg_relation_size(c.oid) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE (n.nspname='agentcon_search' AND c.relname LIKE 'embeddings_%%') OR (n.nspname='public' AND c.relname=%s)""",
        (COVER,)).fetchall()}
    missing = connection.execute('SELECT count(*) FROM agentcon_search.embeddings WHERE kind IS NULL').fetchone()[0] if column else None
    triggers = connection.execute("""SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal""").fetchone()[0]
    return {'kind_column': column, 'kind_missing': missing, 'indexes': indexes, 'public_triggers': triggers}


def _fill(connection):
    """Fill kind in id order, BATCH rows per short transaction. Returns rows changed."""
    changed, last = 0, 0
    while True:
        row = connection.execute("""SELECT max(resource_id) FROM (SELECT resource_id FROM agentcon_search.embeddings
            WHERE resource_id>%s ORDER BY resource_id LIMIT %s) batch""", (last, BATCH)).fetchone()
        if row[0] is None:
            return changed
        changed += connection.execute("""UPDATE agentcon_search.embeddings e SET kind=r.kind FROM public.resources r
            WHERE r.id=e.resource_id AND e.resource_id>%s AND e.resource_id<=%s AND e.kind IS DISTINCT FROM r.kind""",
            (last, row[0])).rowcount
        last = row[0]


def migrate(connection, cover=False):
    steps = {}
    began = time.monotonic()
    connection.execute("SET lock_timeout='2s'")
    connection.execute('ALTER TABLE agentcon_search.embeddings ADD COLUMN IF NOT EXISTS kind text')
    connection.execute("SET lock_timeout='0'")
    steps['add_column_s'] = round(time.monotonic() - began, 2)
    began = time.monotonic()
    steps['filled'] = _fill(connection)
    steps['fill_s'] = round(time.monotonic() - began, 1)
    for kind in KINDS:
        began = time.monotonic()
        name = 'embeddings_half_' + kind
        # An interrupted CONCURRENTLY build leaves an invalid index; replace it.
        if connection.execute("""SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n
                ON n.oid=c.relnamespace WHERE n.nspname='agentcon_search' AND c.relname=%s AND NOT i.indisvalid""",
                (name,)).fetchall():
            connection.execute('DROP INDEX CONCURRENTLY agentcon_search.' + name)
        connection.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS " + name + """ ON agentcon_search.embeddings
            USING hnsw ((embedding::public.halfvec(768)) public.halfvec_cosine_ops) WITH (m='16', ef_construction='64')
            WHERE kind='""" + kind + "'")
        steps[name + '_s'] = round(time.monotonic() - began, 1)
    if cover:
        began = time.monotonic()
        connection.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS ' + COVER +
                           ' ON public.resources (id) INCLUDE (kind, active, health_status, eval_security, eval_score)')
        steps[COVER + '_s'] = round(time.monotonic() - began, 1)
    connection.execute('ANALYZE agentcon_search.embeddings')
    # Rows written by code that did not know the column yet, while the indexes were built.
    steps['refilled'] = _fill(connection)
    return steps


def rollback(connection, cover=False):
    for kind in KINDS:
        connection.execute('DROP INDEX CONCURRENTLY IF EXISTS agentcon_search.embeddings_half_' + kind)
    if cover:
        connection.execute('DROP INDEX CONCURRENTLY IF EXISTS public.' + COVER)
    connection.execute("SET lock_timeout='2s'")
    connection.execute('ALTER TABLE agentcon_search.embeddings DROP COLUMN IF EXISTS kind')
    return {'rolled_back': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('action', choices=('status', 'migrate', 'rollback'))
    parser.add_argument('--dsn-file', required=True)
    parser.add_argument('--cover', action='store_true', help='also the resources filter cover index (P2)')
    parser.add_argument('--i-have-approval', action='store_true',
                        help='required for migrate/rollback: run only after the rehearsal passed and the user approved')
    args = parser.parse_args(argv)
    if args.action != 'status' and not args.i_have_approval:
        parser.error(args.action + ' changes the database; pass --i-have-approval only after approval')
    with _connect(args.dsn_file) as connection:
        if args.action == 'migrate':
            result = migrate(connection, cover=args.cover)
        elif args.action == 'rollback':
            result = rollback(connection, cover=args.cover)
        else:
            result = {}
        result['status'] = status(connection)
    print(json.dumps(result, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""Per-host cap on the a2a and x402 vector graphs (P1 ①, PM 11-13 03:1x K=1000, 20:4x x402 too).

One host filled the a2a graph (centralcity.ai, 217,896 of 224,004 vectors, 449 MB) and one the x402 graph
(market.datapackvibe.com, 82,201 of 128,137, none passing the search filter). A first read of those graphs
took 200-444 ms (a2a) and 257-367 ms (x402) per search on 11-13. Rule: one host contributes at most CAP
rows of one kind to that kind's graph, best first (rows that pass the search filter, then trial success,
then evaluation score, then id).

Rows are marked, never deleted. agentcon_search.embeddings.in_kind_graph is added as false for the
existing rows (metadata only) with default true for rows inserted later, so a new listing enters the
graph at once and only the rows within the cap are updated now (a2a about 7 thousand, x402 about 47
thousand). Two partial indexes, WHERE kind=<kind> AND in_kind_graph, are built CONCURRENTLY. The
application (postgres_ann.kind_search) uses them only when the column and both valid indexes exist, so
code and database may change in either order. The old per-kind indexes stay until a separate approval.

`refresh` re-applies the rule (rows added since, rank changes); jobs runs it later, it changes only
the rows whose mark differs. Nothing here touches public-schema triggers. One connection.

    .venv/bin/python -m scripts.embeddings_graph_cap status   --dsn-file <dsn>
    .venv/bin/python -m scripts.embeddings_graph_cap migrate  --dsn-file <dsn> --i-have-approval
    .venv/bin/python -m scripts.embeddings_graph_cap refresh  --dsn-file <dsn> --i-have-approval
    .venv/bin/python -m scripts.embeddings_graph_cap rollback --dsn-file <dsn> --i-have-approval
"""
import argparse
import json
import sys
import time

import psycopg

CAP = 1000
CAPPED_KINDS = ('a2a', 'x402')
INDEXES = {kind: 'embeddings_half_' + kind + '_cap' for kind in CAPPED_KINDS}
BATCH = 2000

# Rank within (kind, host): rows a search can return first, then trial success, evaluation score, id.
_RANKED = """SELECT e.resource_id, row_number() OVER (PARTITION BY e.kind, COALESCE(r.host, 'id:' || r.id::text)
        ORDER BY (r.active=1 AND r.health_status IN ('healthy','reachable')
                  AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')) DESC,
                 COALESCE(r.trial_ok,0) DESC, r.eval_score DESC NULLS LAST, e.resource_id) AS rank,
        e.in_kind_graph AS marked
    FROM agentcon_search.embeddings e JOIN public.resources r ON r.id=e.resource_id
    WHERE e.kind IN ('a2a','x402')"""


def _connect(dsn_file):
    dsn = open(dsn_file).read().strip()
    connection = psycopg.connect(dsn, autocommit=True)
    connection.execute("SET statement_timeout='0'")
    connection.execute("SET maintenance_work_mem='512MB'")
    connection.execute("SET max_parallel_maintenance_workers=0")
    return connection


def _has_column(connection):
    return bool(connection.execute("""SELECT 1 FROM pg_attribute WHERE attrelid='agentcon_search.embeddings'::regclass
        AND attname='in_kind_graph' AND NOT attisdropped""").fetchall())


def status(connection):
    column = _has_column(connection)
    marks = {}
    if column:
        for kind, marked, count in connection.execute("""SELECT kind, in_kind_graph, count(*) FROM agentcon_search.embeddings
                GROUP BY 1, 2 ORDER BY 1, 2""").fetchall():
            marks.setdefault(kind or 'none', {})['in' if marked else 'out'] = count
    indexes = {name: (valid, size) for name, valid, size in connection.execute("""SELECT c.relname, i.indisvalid AND i.indisready,
        pg_relation_size(c.oid) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='agentcon_search' AND c.relname LIKE 'embeddings_half_%%'""").fetchall()}
    triggers = connection.execute("""SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal""").fetchone()[0]
    return {'column': column, 'marks': marks, 'indexes': indexes, 'public_triggers': triggers}


def _mark(connection):
    """Set in_kind_graph to the rule for every a2a/x402 row whose mark differs, BATCH rows per transaction.
    Returns (rows set in, rows set out)."""
    changes = connection.execute('SELECT resource_id, rank <= %s FROM (' + _RANKED + ') ranked WHERE marked IS DISTINCT FROM (rank <= %s)',
                                 (CAP, CAP)).fetchall()
    counts = {True: 0, False: 0}
    for want in (True, False):
        ids = sorted(rid for rid, wanted in changes if wanted is want)
        for start in range(0, len(ids), BATCH):
            chunk = ids[start:start + BATCH]
            counts[want] += connection.execute("""UPDATE agentcon_search.embeddings SET in_kind_graph=%s
                WHERE resource_id = ANY(%s) AND in_kind_graph IS DISTINCT FROM %s""", (want, chunk, want)).rowcount
    return counts[True], counts[False]


def migrate(connection):
    steps = {}
    began = time.monotonic()
    connection.execute("SET lock_timeout='2s'")
    if not _has_column(connection):
        # false for the existing rows (no rewrite), then true for rows inserted from now on.
        connection.execute('ALTER TABLE agentcon_search.embeddings ADD COLUMN in_kind_graph boolean NOT NULL DEFAULT false')
        connection.execute('ALTER TABLE agentcon_search.embeddings ALTER COLUMN in_kind_graph SET DEFAULT true')
    connection.execute("SET lock_timeout='0'")
    steps['add_column_s'] = round(time.monotonic() - began, 2)
    began = time.monotonic()
    steps['set_in'], steps['set_out'] = _mark(connection)
    steps['mark_s'] = round(time.monotonic() - began, 1)
    for kind, name in INDEXES.items():
        began = time.monotonic()
        # An interrupted CONCURRENTLY build leaves an invalid index; replace it.
        if connection.execute("""SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n
                ON n.oid=c.relnamespace WHERE n.nspname='agentcon_search' AND c.relname=%s AND NOT i.indisvalid""",
                (name,)).fetchall():
            connection.execute('DROP INDEX CONCURRENTLY agentcon_search.' + name)
        connection.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS ' + name + """ ON agentcon_search.embeddings
            USING hnsw ((embedding::public.halfvec(768)) public.halfvec_cosine_ops) WITH (m='16', ef_construction='64')
            WHERE kind='""" + kind + "' AND in_kind_graph")
        steps[name + '_s'] = round(time.monotonic() - began, 1)
    connection.execute('ANALYZE agentcon_search.embeddings')
    # Rows inserted by publish while this ran come in marked; trim the capped hosts again.
    began = time.monotonic()
    steps['reset_in'], steps['reset_out'] = _mark(connection)
    steps['remark_s'] = round(time.monotonic() - began, 1)
    return steps


def refresh(connection):
    if not _has_column(connection):
        return {'refreshed': False, 'reason': 'no_column'}
    began = time.monotonic()
    set_in, set_out = _mark(connection)
    return {'refreshed': True, 'set_in': set_in, 'set_out': set_out, 'seconds': round(time.monotonic() - began, 1)}


def rollback(connection):
    for name in INDEXES.values():
        connection.execute('DROP INDEX CONCURRENTLY IF EXISTS agentcon_search.' + name)
    connection.execute("SET lock_timeout='2s'")
    connection.execute('ALTER TABLE agentcon_search.embeddings DROP COLUMN IF EXISTS in_kind_graph')
    return {'rolled_back': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('action', choices=('status', 'migrate', 'refresh', 'rollback'))
    parser.add_argument('--dsn-file', required=True)
    parser.add_argument('--i-have-approval', action='store_true',
                        help='required for migrate/refresh/rollback: run only after the rehearsal passed and the user approved')
    args = parser.parse_args(argv)
    if args.action != 'status' and not args.i_have_approval:
        parser.error(args.action + ' changes the database; pass --i-have-approval only after approval')
    with _connect(args.dsn_file) as connection:
        result = {'migrate': migrate, 'refresh': refresh, 'rollback': rollback}.get(args.action, lambda c: {})(connection)
        result['status'] = status(connection)
    print(json.dumps(result, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""Explicit additive AI AD Coin v2 migration into the application PostgreSQL database.

  plan     list what migrate would create (no database connection)
  status   report the v2 schema row and which adc2_* tables exist (read only)
  migrate  create the adc2_* tables, indexes, functions and triggers in the ad_coin_v2 schema (idempotent)
  public-status  count rows in adc2_* objects left in the application's public schema (read only)
  drop-public    drop those leftovers (2026-11-10 outage) when they hold no data; needs approval
  migrate-paid   create the paid Sponsored bookings table (USDC, 11-11) in ad_coin_v2; needs approval
  migrate-impressions  create the Sponsored served-count table (11-11) in ad_coin_v2; needs approval

migrate changes the production database, so it runs only with the operator's approval and
the --i-have-approval flag. No server launch, restart or data copy. One connection.

  .venv/bin/python -m scripts.ad_coin_v2_migrate plan
  .venv/bin/python -m scripts.ad_coin_v2_migrate status --dsn-file <dsn file> --key-file <workflow key file>
"""
import argparse
import json
import re
import sys


def plan():
    from agent_market.ad_coin.v2.schema import VERSION, statements
    sql = list(statements())
    text = ' '.join(sql)
    return {
        'schema_version': VERSION,
        'statements': len(sql),
        'tables': sorted(set(re.findall(r'CREATE TABLE IF NOT EXISTS (adc2_\w+)', text))),
        'indexes': len(re.findall(r'CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+)', text)),
        'functions': sorted(set(re.findall(r'CREATE OR REPLACE FUNCTION (\w+)', text))),
        'triggers': sorted(set(re.findall(r'CREATE (?:CONSTRAINT )?TRIGGER (\w+)', text))),
        'drops_or_deletes_data': any(re.match(r'\s*(DROP TABLE|DELETE|TRUNCATE)', s, re.I) for s in sql),
    }


def preflight(target):
    """The application store must still pass its own startup checks. `target` is an application
    store, or a callable returning a fresh autocommit connection to the same database.

    The 2026-11-10 outage: a migration that put triggers in the application's schema made every
    application connection fail. migrate runs this before and after, and stops on failure.
    """
    try:
        if callable(target):
            from agent_market.storage_adapter import open_store
            store = open_store('postgresql', connection=target())
            try:
                with store.tx(readonly=True):
                    store._validate_native_invariants()
            finally:
                store._connection.close()
        else:
            with target.tx(readonly=True):
                target._validate_native_invariants()
    except Exception as exc:
        raise RuntimeError('application store check failed: ' + type(exc).__name__ + ' ' + str(exc)) from None


def _connect(args):
    from agent_market.application_runtime import open_runtime_storage
    runtime = open_runtime_storage(':memory:', values={
        'APPLICATION_STORE_BACKEND': 'postgresql', 'APPLICATION_POSTGRES_DSN_FILE': args.dsn_file,
        'APPLICATION_WORKFLOW_KEY_FILE': args.key_file})
    runtime.store._admin_read_pool = None  # one connection only (prod connection budget)
    return runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('plan', 'status', 'migrate', 'public-status', 'drop-public', 'migrate-paid', 'migrate-impressions'))
    parser.add_argument('--dsn-file')
    parser.add_argument('--key-file')
    parser.add_argument('--i-have-approval', action='store_true',
                        help='Required for migrate: the operator approved this database change')
    args = parser.parse_args(argv)
    if args.action == 'plan':
        print(json.dumps(plan(), indent=1, sort_keys=True))
        return 0
    if not (args.dsn_file and args.key_file):
        parser.error(args.action + ' needs --dsn-file and --key-file')
    if args.action in ('migrate', 'drop-public', 'migrate-paid', 'migrate-impressions') and not args.i_have_approval:
        parser.error(args.action + ' changes the production database; pass --i-have-approval only after approval')
    from agent_market.ad_coin.v2.live_service import store_from_application
    runtime = _connect(args)
    try:
        import os
        os.environ['AD_COIN_V2_POOL_MAXIMUM'] = '1'
        if args.action in ('migrate', 'drop-public', 'migrate-paid', 'migrate-impressions'):
            preflight(runtime.store)  # stop before touching anything if the application is not healthy
        if args.action == 'migrate-paid':
            result = migrate_paid(store_from_application(runtime.store))
        elif args.action == 'migrate-impressions':
            result = migrate_impressions(store_from_application(runtime.store))
        elif args.action in ('public-status', 'drop-public'):
            result = public_leftovers(store_from_application(runtime.store), drop=args.action == 'drop-public')
        else:
            result = run(store_from_application(runtime.store), args.action)
        if args.action in ('migrate', 'drop-public', 'migrate-paid', 'migrate-impressions'):
            preflight(runtime.store)  # the application must still start afterwards
        print(json.dumps(result, sort_keys=True))
    finally:
        runtime.close()
    return 0


def run(store, action):
    """status or migrate on a v2 ModelStore; returns the table and schema state afterwards."""
    from agent_market.ad_coin.sql_registry import unchecked
    if action == 'migrate':
        store.migrate_model()
    with unchecked(), store.atomic(require_ready=False):  # operator inspection outside product SQL
        existing = [row['tablename'] for row in store.database.all(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE 'adc2%' ORDER BY 1")]
        schema = store.database.one('SELECT * FROM adc2_schema') if 'adc2_schema' in existing else None
    return {'existing_tables': len(existing), 'expected_tables': len(plan()['tables']),
            'schema': dict(schema) if schema else None}


def migrate_paid(store):
    """Create adc2_paid_bookings (idempotent). Rollback while empty: DROP TABLE ad_coin_v2.adc2_paid_bookings."""
    from agent_market.ad_coin.sql_registry import unchecked
    from agent_market.ad_coin.v2.paid_bookings import STATEMENTS
    with unchecked(), store.atomic(require_ready=False):
        for statement in STATEMENTS:
            store._connection().execute(statement)
        exists = store.database.one("SELECT count(*) AS n FROM pg_tables WHERE schemaname=current_schema() "
                                    "AND tablename='adc2_paid_bookings'")
    return {'paid_bookings_table': int(exists['n']) == 1}


def migrate_impressions(store):
    """Create adc2_sponsored_impressions (idempotent). Rollback: DROP TABLE ad_coin_v2.adc2_sponsored_impressions."""
    from agent_market.ad_coin.sql_registry import unchecked
    from agent_market.ad_coin.v2.sponsored import IMPRESSION_STATEMENTS
    with unchecked(), store.atomic(require_ready=False):
        for statement in IMPRESSION_STATEMENTS:
            store._connection().execute(statement)
        exists = store.database.one("SELECT count(*) AS n FROM pg_tables WHERE schemaname=current_schema() "
                                    "AND tablename='adc2_sponsored_impressions'")
    return {'sponsored_impressions_table': int(exists['n']) == 1}


# Rows a v2 migration itself writes; anything beyond these means real data and blocks the drop.
SEED_ROWS = {'adc2_schema': 1, 'adc2_assets': 1, 'adc2_commercial_control': 1}


def public_leftovers(store, *, drop=False):
    """adc2_* tables and functions in the public schema (left by the first, pre-schema migration)."""
    from psycopg import sql as psql
    from agent_market.ad_coin.sql_registry import unchecked
    with unchecked(), store.atomic(require_ready=False):
        database, connection = store.database, store._connection()
        tables = [row['tablename'] for row in database.all(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'adc2%' ORDER BY 1")]
        functions = [row['proname'] for row in database.all(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname LIKE 'adc2%' ORDER BY 1")]
        counts = {name: int(database.one(
            psql.SQL('SELECT count(*) AS n FROM public.{}').format(psql.Identifier(name)).as_string())['n'])
            for name in tables}
        data = {name: n for name, n in counts.items() if n > SEED_ROWS.get(name, 0)}
        result = {'tables': len(tables), 'functions': functions, 'rows': sum(counts.values()), 'data_tables': data}
        if drop:
            if data:
                raise RuntimeError('public adc2 tables hold data; not dropping: ' + ', '.join(sorted(data)))
            if tables:
                connection.execute(psql.SQL('DROP TABLE {} CASCADE').format(
                    psql.SQL(', ').join(psql.Identifier('public', name) for name in tables)).as_string())
            for name in functions:
                connection.execute(psql.SQL('DROP FUNCTION {}()').format(psql.Identifier('public', name)).as_string())
            result['dropped'] = True
    return result


if __name__ == '__main__':
    sys.exit(main())

"""Explicit additive AI AD Coin v2 migration into the application PostgreSQL database.

  plan     list what migrate would create (no database connection)
  status   report the v2 schema row and which adc2_* tables exist (read only)
  migrate  create the adc2_* tables, indexes, functions and triggers (idempotent); nothing else

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


def _connect(args):
    from agent_market.application_runtime import open_runtime_storage
    runtime = open_runtime_storage(':memory:', values={
        'APPLICATION_STORE_BACKEND': 'postgresql', 'APPLICATION_POSTGRES_DSN_FILE': args.dsn_file,
        'APPLICATION_WORKFLOW_KEY_FILE': args.key_file})
    runtime.store._admin_read_pool = None  # one connection only (prod connection budget)
    return runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('plan', 'status', 'migrate'))
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
    if args.action == 'migrate' and not args.i_have_approval:
        parser.error('migrate changes the production database; pass --i-have-approval only after approval')
    from agent_market.ad_coin.v2.live_service import store_from_application
    runtime = _connect(args)
    try:
        import os
        os.environ['AD_COIN_V2_POOL_MAXIMUM'] = '1'
        print(json.dumps(run(store_from_application(runtime.store), args.action), sort_keys=True))
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


if __name__ == '__main__':
    sys.exit(main())

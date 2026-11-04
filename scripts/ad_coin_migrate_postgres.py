"""Explicit additive AI AD Coin migration into the application PostgreSQL store.

  status   report whether the ad_coin_* tables exist and their row counts
  migrate  create the ad_coin_* tables and indexes (idempotent); nothing else
  copy     copy an existing AI AD Coin SQLite file into empty ad_coin_* tables

No server launch, restart or catalog change. Uses one store connection.

  .venv/bin/python -m scripts.ad_coin_migrate_postgres status \\
      --dsn-file <dsn file> --key-file <workflow key file>
"""
import argparse
import json
import re
import sqlite3


def table_names():
    from agent_market.ad_coin.db import SCHEMA
    return re.findall(r'CREATE TABLE IF NOT EXISTS (ad_coin_\w+)', SCHEMA)


def status(store):
    from agent_market.ad_coin.db import ApplicationStoreDatabase, schema_version
    database = ApplicationStoreDatabase(store, require_migrated=False)
    version = schema_version(database)
    counts = {}
    if version is not None:
        for name in table_names():
            counts[name] = database.one('SELECT COUNT(*) AS n FROM ' + name)['n']
    return {'schema_version': version, 'rows': counts}


def copy(store, sqlite_path):
    """Copy every ad_coin_* row from a SQLite file; refuses if the target already has rows."""
    from agent_market.ad_coin.db import ApplicationStoreDatabase, postgres_sql
    database = ApplicationStoreDatabase(store)
    source = sqlite3.connect('file:' + sqlite_path + '?mode=ro', uri=True)
    try:
        names = table_names()
        present = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        busy = [n for n in names if database.one('SELECT COUNT(*) AS n FROM ' + n)['n']
                and not (n == 'ad_coin_settings')]
        if busy:
            raise SystemExit('Target already has AI AD Coin rows in: ' + ', '.join(busy))
        copied = {}
        with store.tx():
            for name in names:
                if name not in present:
                    continue
                rows = source.execute('SELECT * FROM ' + name).fetchall()
                if not rows:
                    continue
                marks = ','.join('?' * len(rows[0]))
                sql = 'INSERT INTO ' + name + ' VALUES (' + marks + ')'
                if name == 'ad_coin_settings':
                    sql += ' ON CONFLICT(key) DO NOTHING'
                for row in rows:
                    store._execute(postgres_sql(sql), tuple(row))
                copied[name] = len(rows)
        return {'copied': copied}
    finally:
        source.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('status', 'migrate', 'copy'))
    parser.add_argument('--dsn-file', required=True)
    parser.add_argument('--key-file', required=True)
    parser.add_argument('--sqlite', help='AI AD Coin SQLite file for copy')
    args = parser.parse_args(argv)
    if args.action == 'copy' and not args.sqlite:
        parser.error('copy needs --sqlite')
    from agent_market.ad_coin.db import migrate
    from agent_market.application_runtime import open_runtime_storage
    runtime = open_runtime_storage(':memory:', values={
        'APPLICATION_STORE_BACKEND': 'postgresql', 'APPLICATION_POSTGRES_DSN_FILE': args.dsn_file,
        'APPLICATION_WORKFLOW_KEY_FILE': args.key_file})
    try:
        store = runtime.store
        store._admin_read_pool = None  # one connection only (prod connection budget)
        if args.action == 'migrate':
            result = migrate(store)
        elif args.action == 'copy':
            result = copy(store, args.sqlite)
        else:
            result = status(store)
        print(json.dumps(result, sort_keys=True))
    finally:
        runtime.close()


if __name__ == '__main__':
    main()

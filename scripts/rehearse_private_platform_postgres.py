"""Synthetic private-platform schema parity; never an application Store switch.

No caller database/DSN is accepted. Trusted current private schemas are built in
memory and exercised in a disposable Unix-socket-only PostgreSQL cluster.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster

PROFILE = 'private-platform-postgres-schema-v1'


def require(value):
    if value is not True:
        raise ValueError('Private schema rehearsal invariant failed.')


def schemas():
    from agent_market import (workspace_access, workspace_execution, customer_identity,
        customer_workspace_runtime, workspace_lifecycle, workspace_release, provider_claims,
        shadow_ledger, workflow_support, advancement_readiness, workflow_quality_review, workflow_product_composer)
    modules = (workspace_access, workspace_execution, customer_identity, customer_workspace_runtime,
               workspace_lifecycle, workspace_release, provider_claims, shadow_ledger,
               workflow_support, advancement_readiness, workflow_quality_review, workflow_product_composer)
    result = []
    for module in modules:
        value = module.SCHEMA
        result.extend((value,) if type(value) is str else value)
    return tuple(result)


def model():
    db = sqlite3.connect(':memory:')
    for sql in schemas():
        db.execute(sql)
    return db


def quoted(name):
    if type(name) is not str or not re.fullmatch('[a-z_][a-z0-9_]{0,62}', name):
        raise ValueError('Invalid trusted schema identifier.')
    return '"' + name + '"'


def specification(db):
    result = []
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in tables:
        columns = list(db.execute('PRAGMA table_info(' + quoted(table) + ')'))
        definitions, values = [], []
        for _, name, kind, required, _, pk in columns:
            # SQLite's mixed principal field now holds either a staff integer
            # or an opaque cu_ ID. PostgreSQL must never coerce that ID to BIGINT.
            mixed = table in ('workspace_private_tickets', 'workspace_private_runs') and name == 'actor_user_id'
            sql_type = 'TEXT' if mixed else {'TEXT': 'TEXT', 'INTEGER': 'BIGINT', 'REAL': 'DOUBLE PRECISION'}.get(kind)
            if sql_type is None:
                raise ValueError('Unmapped current private schema type.')
            definitions.append(quoted(name) + ' ' + sql_type + (' NOT NULL' if required or pk else ''))
            values.append('cu_' + 'a'*32 if mixed else
                          'Synthetic O\'Reilly; -- \u2603' if sql_type == 'TEXT' else 1 if sql_type == 'BIGINT' else 1.25)
        primary = [c[1] for c in sorted(columns, key=lambda c: c[5]) if c[5]]
        if primary:
            definitions.append('PRIMARY KEY (' + ','.join(map(quoted, primary)) + ')')
        uniques = []
        for index in db.execute('PRAGMA index_list(' + quoted(table) + ')').fetchall():
            if not index[2] or index[3] == 'pk':
                continue
            names = [r[0] for r in db.execute('SELECT name FROM pragma_index_info(?) ORDER BY seqno', (index[1],))]
            if not names or any(n is None for n in names):
                raise ValueError('Unsupported unique expression.')
            uniques.append(names)
            definitions.append('UNIQUE (' + ','.join(map(quoted, names)) + ')')
        result.append({'table': table, 'columns': [c[1] for c in columns], 'values': values,
                       'primary': primary, 'unique': uniques,
                       'ddl': 'CREATE TABLE ' + quoted(table) + ' (' + ','.join(definitions) + ')'})
    return result


def run():
    driver = _driver()
    db = model()
    try:
        specs = specification(db)
        for spec in specs:
            db.execute('INSERT INTO ' + quoted(spec['table']) + ' VALUES (' + ','.join('?' for _ in spec['columns']) + ')', spec['values'])
        db.commit()
        with _private_cluster(_tools()) as cluster:
            with driver.connect(host=cluster['socket'], port=55447, dbname='postgres', user='postgres',
                                connect_timeout=3, passfile=cluster['root']+'/no-password-file') as pg:
                with pg.cursor() as cur:
                    cur.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr()")
                    require(cur.fetchone() == ('', None, None))
                    for spec in specs:
                        cur.execute(spec['ddl'])
                        cur.execute('INSERT INTO ' + quoted(spec['table']) + ' VALUES (' + ','.join('%s' for _ in spec['columns']) + ')', spec['values'])
                        cur.execute('SELECT * FROM ' + quoted(spec['table']))
                        require(cur.fetchone() == tuple(spec['values']))
                pg.commit()
                with pg.cursor() as cur:
                    cur.execute('DELETE FROM customer_sessions')
                pg.rollback()
                with pg.cursor() as cur:
                    cur.execute('SELECT COUNT(*) FROM customer_sessions')
                    require(cur.fetchone()[0] == 1)
                    try:
                        with pg.transaction():
                            cur.execute('INSERT INTO workspace_private_runs SELECT * FROM workspace_private_runs')
                    except driver.errors.UniqueViolation:
                        duplicate_blocked = True
                    else:
                        raise AssertionError('Private replay uniqueness was lost.')
                pg.rollback()
        return {'profile': PROFILE, 'tables': [s['table'] for s in specs], 'table_count': len(specs),
                'schema_sha256': hashlib.sha256(json.dumps([s['ddl'] for s in specs], sort_keys=True).encode()).hexdigest(),
                'checks': {'unix_socket_only': True, 'all_private_tables_round_trip': True,
                           'opaque_customer_principal_preserved': True, 'transaction_rollback': True,
                           'duplicate_private_run_rejected': duplicate_blocked, 'temporary_cluster_removed': True},
                'synthetic': True, 'production_actions': 0, 'external_provider_calls': 0,
                'full_store_postgres_ready': False, 'production_cutover': False,
                'scope': 'Current private schema and synthetic scalar/constraint parity only; catalog, FTS/vector, application repositories, load and operating DR remain separate.'}
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists():
        parser.error('Use a new report path.')
    result = run()
    with destination.open('x') as target:
        target.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'tables'}))

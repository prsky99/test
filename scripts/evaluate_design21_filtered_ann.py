"""Compare filtered ANN with exact neighbors in a disposable Unix-only PG18.

No operator DSN, application records, model or provider calls are accepted.
The low-intrinsic-dimensional synthetic vectors test query semantics, not a
production embedding distribution, full provenance pipeline or operating SLO.
"""
import argparse
from contextlib import contextmanager, nullcontext
import getpass
import json
from pathlib import Path
import random
import struct
import tempfile
import time
from types import SimpleNamespace
import uuid

import psycopg
from psycopg import sql

from agent_market.legacy_vector_index import ModelDescriptor
from agent_market.postgres_ann import nearest, vector_literal
from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT


class QueryStore:
    def __init__(self, connection):
        self.connection = connection
        self._vector_index = SimpleNamespace()

    def _execute(self, sql, params=()):
        return self.connection.execute(sql, params)


class NamespaceCursor:
    def __init__(self, cursor, translate):
        self.cursor, self.translate = cursor, translate

    def __enter__(self):
        self.cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def copy(self, statement):
        return self.cursor.copy(self.translate(statement))


class NamespaceConnection:
    """Test-only fixed namespace mapping; never used by an application Store."""
    def __init__(self, connection, namespace, vector_schema):
        import re
        if not all(isinstance(value, str) and re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', value)
                   for value in (namespace, vector_schema)):
            raise ValueError('Only fixed safe test namespace identifiers are accepted.')
        self.connection, self.namespace, self.vector_schema = connection, namespace, vector_schema

    def translate(self, statement):
        import re
        statement = statement.replace('public.resources', self.namespace + '.resources')
        statement = re.sub(r'(?<![.\w])resources\b', self.namespace + '.resources', statement)
        return statement.replace('agentcon_search', self.namespace).replace('public.vector', self.vector_schema + '.vector')

    def execute(self, statement, args=()):
        if statement in ('CREATE EXTENSION vector', 'CREATE SCHEMA agentcon_search'):
            return self.connection.execute('SELECT 1')
        return self.connection.execute(self.translate(statement), args)

    def cursor(self):
        return NamespaceCursor(self.connection.cursor(), self.translate)

    def transaction(self, **kwargs):
        return self.connection.transaction(**kwargs)


@contextmanager
def local_owned_schema():
    """Rollback-only random namespace in the administrative database.

    The application database is never opened. Only fixed test SQL receives a
    namespace mapping; production search code keeps its reviewed fixed names.
    No HBA change, backend termination, server restart or force-drop is used.
    """
    base = Path(__file__).resolve().parents[1] / 'gateway-data/postgres18'
    pid = (base / 'data/postmaster.pid').read_text().splitlines()
    socket = base / 'run'
    if len(pid) < 5 or Path(pid[4]).resolve() != socket.resolve():
        raise ValueError('The project local PostgreSQL socket is unavailable.')
    port = int(pid[3])
    if not 1024 <= port <= 65535:
        raise ValueError('The project local PostgreSQL port is invalid.')
    namespace = 'agentcon_design21_' + uuid.uuid4().hex
    with psycopg.connect(host=str(socket),port=port,user=getpass.getuser(),dbname='postgres',
            connect_timeout=3,passfile='/private/tmp/no-design21-password-file',autocommit=True) as admin:
        if int(admin.execute("SELECT current_setting('server_version_num')").fetchone()[0]) < 180000:
            raise ValueError('This rehearsal requires PostgreSQL 18.')
        with tempfile.TemporaryDirectory(prefix='design21-owned-schema-',dir='/private/tmp') as directory:
            with admin.transaction(force_rollback=True):
                admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(namespace)))
                installed = admin.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'").fetchone()
                if not installed:
                    admin.execute(sql.SQL('CREATE EXTENSION vector WITH SCHEMA {}').format(sql.Identifier(namespace)))
                vector_schema = installed[0] if installed else namespace
                admin.execute(sql.SQL('SET LOCAL search_path TO {}, public').format(sql.Identifier(namespace)))
                result = {'connection':NamespaceConnection(admin,namespace,vector_schema),'root':directory,
                          'shared_local_server':True,'owned_schema_removed':False}
                yield result
            if admin.execute('SELECT to_regnamespace(%s)',(namespace,)).fetchone()[0] is not None:
                raise ValueError('The rollback-only test namespace was not removed.')
            result['owned_schema_removed'] = True


def run(rows=4096, *, shared_local=False):
    if type(rows) is not int or not 1000 <= rows <= 10000:
        raise ValueError('Use between 1000 and 10000 synthetic rows.')
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    tools = {name: str(binary / name) for name in ('initdb', 'pg_ctl')}
    descriptor = ModelDescriptor('design21-synthetic', revision='fixture-v1')
    rng = random.Random(21026)
    results = []
    with (local_owned_schema() if shared_local else _private_cluster(tools)) as cluster:
        directory = Path(cluster['root'])
        with (nullcontext(cluster['connection']) if shared_local else psycopg.connect(
                host=cluster['socket'],port=PORT,dbname='postgres',user='postgres',
                passfile='/private/tmp/no-design21-password-file',autocommit=True)) as pg:
            pg.execute('CREATE EXTENSION vector')
            pg.execute('CREATE SCHEMA agentcon_search')
            pg.execute('''CREATE TABLE resources(id bigint PRIMARY KEY,active integer,
                health_status text,eval_security text,kind text,category text,trial_ok integer)''')
            pg.execute('''CREATE TABLE agentcon_search.embeddings(resource_id bigint PRIMARY KEY,
                descriptor_hash text,embedding vector(768))''')
            with pg.transaction():
                with pg.cursor().copy('COPY resources FROM STDIN') as writer:
                    for i in range(1, rows + 1):
                        writer.write_row((i, 1, 'healthy', '', 'mcp' if i % 10 == 0 else 'a2a',
                                          'narrow' if i % 100 == 0 else 'general', int(i % 1000 == 0)))
                with pg.cursor().copy('COPY agentcon_search.embeddings FROM STDIN') as writer:
                    for i in range(1, rows + 1):
                        vector = [rng.uniform(-1, 1) for _ in range(16)] + [0.0] * 752
                        writer.write_row((i, descriptor.digest, '[' + ','.join(map(str, vector)) + ']'))
                for i, active, health, security in [(rows+1,0,'healthy',''),
                        (rows+2,1,'retired',''), (rows+3,1,'healthy','quarantine')]:
                    pg.execute('INSERT INTO resources VALUES(%s,%s,%s,%s,%s,%s,1)',
                               (i, active, health, security, 'mcp', 'narrow'))
                    pg.execute('INSERT INTO agentcon_search.embeddings VALUES(%s,%s,%s::vector)',
                               (i, descriptor.digest, '[1,' + ','.join(['0'] * 767) + ']'))
            pg.execute('''CREATE INDEX embeddings_cosine_hnsw ON agentcon_search.embeddings
                USING hnsw(embedding vector_cosine_ops) WITH(m=16,ef_construction=64)''')
            pg.execute('ANALYZE resources')
            pg.execute('ANALYZE agentcon_search.embeddings')
            store = QueryStore(pg)
            queries = [[rng.uniform(-1, 1) for _ in range(16)] + [0.0] * 752 for _ in range(8)]
            conditions = '''e.descriptor_hash=%s AND r.active=1 AND r.health_status!='retired'
                AND COALESCE(r.eval_security,'')!='quarantine'
                AND (%s::text IS NULL OR r.kind=%s) AND (%s::text IS NULL OR r.category=%s)
                AND (%s=0 OR r.trial_ok=1)'''
            for label, kind, category, verified in [('all',None,None,False),
                    ('protocol', 'mcp',None,False), ('category','mcp','narrow',False),
                    ('category_verified','mcp','narrow',True)]:
                for number, query in enumerate(queries):
                    literal = vector_literal(struct.pack('<768f', *query))
                    args = (descriptor.digest,kind,kind,category,category,int(verified))
                    with pg.transaction(force_rollback=True):
                        pg.execute('SET LOCAL enable_seqscan=off')
                        begin = time.perf_counter()
                        actual = nearest(store, struct.pack('<768f', *query), descriptor,
                                         kind=kind, category=category, verified_only=verified)
                        elapsed = (time.perf_counter()-begin)*1000
                        pg.execute('SET LOCAL enable_indexscan=off')
                        pg.execute('SET LOCAL enable_bitmapscan=off')
                        pg.execute('SET LOCAL enable_seqscan=on')
                        expected = [r[0] for r in pg.execute('''SELECT e.resource_id
                            FROM agentcon_search.embeddings e JOIN resources r ON r.id=e.resource_id
                            WHERE ''' + conditions + ' ORDER BY e.embedding <=> %s::vector LIMIT 10',  # noqa: S608 -- fixed fixture predicates; values are bound
                            (*args,literal)).fetchall()]
                    assert all(i <= rows for i in actual), 'An ineligible nearest vector escaped.'
                    recall = len(set(actual[:10]) & set(expected)) / len(expected) if expected else None
                    results.append({'selection':label,'query':number,'k':len(expected),
                                    'recall_at_k':recall,'returned':len(actual),'ann_ms':round(elapsed,2)})
            local_settings_reset = pg.execute("SELECT current_setting('hnsw.iterative_scan')").fetchone()[0] == 'off'
            plan = [r[0] for r in pg.execute('''EXPLAIN SELECT resource_id FROM agentcon_search.embeddings
                ORDER BY embedding <=> %s::vector LIMIT 10''', (literal,)).fetchall()]
            index_used = any('embeddings_cosine_hnsw' in row for row in plan)
    return {'scope':'synthetic_native_filtered_ann_vs_exact; no full application/provider acceptance',
            'rows':rows,'vector_dimensions':768,'nonzero_dimensions':16,'query_count':len(results),
            'results':results,'minimum_recall':min(r['recall_at_k'] for r in results if r['recall_at_k'] is not None),
            'settings_transaction_local':local_settings_reset,'hnsw_plan':index_used,
            'private_cluster_removed':not directory.exists() if not shared_local else None,
            'shared_local_server':shared_local,'owned_schema_removed':cluster.get('owned_schema_removed',False),
            'production_application_data_writes':0,'production_slo_certified':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=4096)
    parser.add_argument('--shared-local-test-schema',action='store_true',
                        help='Use a rollback-only random schema in local postgres admin DB; never open the application DB.')
    args = parser.parse_args()
    result = run(args.rows,shared_local=args.shared_local_test_schema)
    result['passed'] = (result['minimum_recall'] >= .95 and result['settings_transaction_local']
                        and result['hnsw_plan'] and (result['owned_schema_removed']
                            if result['shared_local_server'] else result['private_cluster_removed']))
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'results'}))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

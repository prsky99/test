"""Check or add only reviewed availability storage and retention indexes.

No server operation, conversation deletion, existing-table alteration or DSN output.
"""
import argparse
import json
from pathlib import Path

TABLE='public_availability_checks'
INDEXES={'agent_messages_retention':('agent_messages',('at','id')),
         'agent_interests_retention':('agent_interests',('updated','id'))}
EXPECTED=[('checked_at','double precision','NO'),('ok','bigint','NO'),
          ('status_code','bigint','YES'),('latency_ms','double precision','YES')]


def migrate(connection,*,apply=False):
    from agent_market.application_store_postgres import PROFILE,WRITER_LOCK
    catalog=json.loads(Path(__file__).resolve().parents[1].joinpath('agent_market/application_store_sql.json').read_text())
    ddl=[sql for sql in catalog['schema'] if sql.startswith('CREATE TABLE IF NOT EXISTS "'+TABLE+'" ')]
    if len(ddl)!=1:raise ValueError('reviewed_schema_required')
    created=False
    with connection.transaction():
        if not apply:connection.execute('SET TRANSACTION READ ONLY')
        connection.execute('SET LOCAL search_path TO public,pg_temp')
        connection.execute("SET LOCAL lock_timeout='1000ms'")
        connection.execute("SET LOCAL statement_timeout='5000ms'")
        if tuple(connection.execute('SELECT profile FROM application_store_state WHERE id=1').fetchone())!=(PROFILE,):
            raise ValueError('reviewed_application_required')
        exists=connection.execute('SELECT to_regclass(%s)',('public.'+TABLE,)).fetchone()[0] is not None
        if not exists and apply:
            connection.execute('SELECT pg_advisory_xact_lock(%s)',(WRITER_LOCK,))
            connection.execute(ddl[0]);created=True;exists=True
        if exists:
            actual=connection.execute('SELECT column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position',('public',TABLE)).fetchall()
            if list(map(tuple,actual))!=EXPECTED:raise ValueError('existing_schema_requires_review')
            keys=connection.execute("SELECT array_agg(a.attname ORDER BY k.ordinality) FROM pg_constraint c CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum,ordinality) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum WHERE c.conrelid=to_regclass(%s) AND c.contype='p' GROUP BY c.oid",('public.'+TABLE,)).fetchall()
            if len(keys)!=1 or list(keys[0][0])!=['checked_at']:raise ValueError('existing_schema_requires_review')
    indexes={}
    for name,(table,columns) in INDEXES.items():
        present=connection.execute('SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND indexname=%s',('public',name)).fetchone()
        if apply and not present:
            # Concurrent builds do not block ordinary inserts and deletes.
            with connection.cursor() as cur:
                cur.execute("SET statement_timeout='60000ms'")
                cur.execute("SET lock_timeout='1000ms'")
                try:cur.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS '+name+' ON public.'+table+' ('+','.join(columns)+')')
                finally:cur.execute('RESET statement_timeout');cur.execute('RESET lock_timeout')
            present=connection.execute('SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND indexname=%s',('public',name)).fetchone()
        valid=connection.execute('SELECT i.indisvalid,i.indisunique,t.relname FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid WHERE i.indexrelid=to_regclass(%s)',('public.'+name,)).fetchone() if present else None
        indexes[name]=bool(present and present[0].endswith('USING btree ('+', '.join(columns)+')') and valid and tuple(valid)==(True,False,table))
        if present and not indexes[name]:raise ValueError('existing_index_requires_review')
    return {'ready':exists and all(indexes.values()),'table_created':created,'retention_indexes':indexes,'existing_rows_modified':0,'services_changed':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--check',action='store_true');mode.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    try:
        from scripts.service_deploy import Deployment
        from scripts.agentcon_config import read_settings
        from agent_market.application_runtime import _private_bytes,_connect
        root=Path(__file__).resolve().parents[1];settings=read_settings(str(Deployment(root).settings))
        path=Path(settings['APPLICATION_POSTGRES_DSN_FILE']);path=path if path.is_absolute() else root/path
        with _connect(_private_bytes(str(path),16384).decode().strip()) as connection:result=migrate(connection,apply=args.apply)
    except Exception:
        print(json.dumps({'ready':False,'error':'reviewed_experience_migration_failed'}));return 1
    print(json.dumps(result,sort_keys=True));return 0 if result['ready'] else 1


if __name__=='__main__':raise SystemExit(main())

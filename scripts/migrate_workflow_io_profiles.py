"""Check or add only the reviewed empty I/O-profile table in the configured store.

No server operation, credential output, data replacement or fallback activation.
"""
import argparse
import json
from pathlib import Path


def migrate(connection, *, apply=False):
    from agent_market.application_store_postgres import PROFILE, WRITER_LOCK
    catalog=json.loads(Path(__file__).resolve().parents[1].joinpath('agent_market/application_store_sql.json').read_text())
    ddl=[v for v in catalog['schema'] if v.startswith('CREATE TABLE IF NOT EXISTS "workflow_io_profiles" ')]
    if len(ddl)!=1:raise ValueError('reviewed_schema_required')
    expected=[('id','text','NO'),('payload','text','NO'),('signature','text','NO'),
              ('created','double precision','NO'),('expires','double precision','NO'),('revoked','double precision','YES')]
    created=False
    with connection.transaction():
        connection.execute("SET LOCAL search_path TO public,pg_temp")
        connection.execute("SET LOCAL statement_timeout='5000ms'")
        connection.execute("SET LOCAL lock_timeout='1000ms'")
        if apply:connection.execute('SELECT pg_advisory_xact_lock(%s)',(WRITER_LOCK,))
        else:connection.execute('SET TRANSACTION READ ONLY')
        if tuple(connection.execute('SELECT profile FROM public.application_store_state WHERE id=1').fetchone())!=(PROFILE,):
            raise ValueError('application_profile_required')
        exists=connection.execute("SELECT to_regclass('public.workflow_io_profiles')").fetchone()[0] is not None
        if not exists and apply:connection.execute(ddl[0]);created=True;exists=True
        if exists:
            actual=connection.execute("SELECT column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name='workflow_io_profiles' ORDER BY ordinal_position").fetchall()
            if [tuple(r) for r in actual]!=expected:raise ValueError('existing_schema_requires_review')
            keys=connection.execute("SELECT array_agg(a.attname ORDER BY k.ordinality) FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum,ordinality) JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.attnum WHERE n.nspname='public' AND t.relname='workflow_io_profiles' AND c.contype='p' GROUP BY c.oid").fetchall()
            if len(keys)!=1 or list(keys[0][0])!=['id']:raise ValueError('existing_schema_requires_review')
    return {'ready':exists,'created':created,'fallback_settings_changed':False,'existing_rows_modified':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True);modes.add_argument('--check',action='store_true');modes.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    from scripts.service_deploy import Deployment
    control=Deployment(Path(__file__).resolve().parents[1]).control()
    try:result=migrate(control.connection,apply=args.apply)
    finally:control.close()
    print(json.dumps(result,sort_keys=True))
    return 0 if result['ready'] else 1


if __name__=='__main__':raise SystemExit(main())

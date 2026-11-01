"""Add only the reviewed template configuration table and its scoped index.

Uses the current private application DSN. Does not restart services, modify
customer data, enable fallback, change HBA or alter any existing table.
"""
import argparse
import json
from pathlib import Path
from agent_market.application_runtime import _private_bytes, _connect
from agent_market.application_store_postgres import PostgresApplicationStore, _normalized, PROFILE
from agent_market.workspace_template_hub import SCHEMA
from scripts.agentcon_config import read_settings
from scripts.service_deploy import Deployment

TABLE='workspace_template_records'


def migrate(connection, catalog, *, apply=False):
    statements={_normalized(e['sqlite']):e['postgres'] for e in catalog['statements']}
    with connection.transaction():
        connection.execute("SET LOCAL lock_timeout='1000ms'")
        connection.execute("SET LOCAL statement_timeout='5000ms'")
        connection.execute('SET LOCAL search_path TO public,pg_temp')
        profile=connection.execute('SELECT profile FROM application_store_state WHERE id=1').fetchone()
        if profile!=(PROFILE,):
            raise ValueError('Reviewed application schema required')
        before=connection.execute('SELECT to_regclass(%s)',('public.'+TABLE,)).fetchone()[0]
        if apply:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext('workspace-template-hub-schema-v1'))")
            for statement in SCHEMA:connection.execute(statements[_normalized(statement)])
        if before is None and not apply:
            return {'ready':False,'table_present':False,'mutations':0}
        actual=connection.execute('SELECT column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position',('public',TABLE)).fetchall()
        if tuple(actual)!=PostgresApplicationStore._expected_columns(None,TABLE):
            raise ValueError('Template schema differs; no automatic alteration allowed')
        primary=connection.execute("SELECT array_agg(a.attname ORDER BY k.position) FROM pg_constraint c JOIN unnest(c.conkey) WITH ORDINALITY k(number,position) ON true JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.number WHERE c.conrelid=to_regclass(%s) AND c.contype='p'",('public.'+TABLE,)).fetchone()[0]
        kinds=connection.execute("SELECT contype FROM pg_constraint WHERE conrelid=to_regclass(%s) AND contype<>'n'",('public.'+TABLE,)).fetchall()
        if primary!=['id'] or kinds!=[('p',)]:raise ValueError('Reviewed template constraints required')
        index=connection.execute('SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND tablename=%s AND indexname=%s',('public',TABLE,'idx_workspace_template_records_scope')).fetchone()
        if not index or not index[0].endswith('USING btree (workspace_id, kind, parent, created)'):
            raise ValueError('Reviewed template lookup index required')
        return {'ready':True,'table_present':True,'table_created':before is None,'customer_data_changed':False,'server_changes':0}


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--check',action='store_true');mode.add_argument('--apply',action='store_true');args=p.parse_args()
    root=Path(__file__).resolve().parents[1];settings=read_settings(str(Deployment(root).settings))
    dsn=_private_bytes(settings['APPLICATION_POSTGRES_DSN_FILE'],16384).decode().strip()
    catalog=json.loads((root/'agent_market/application_store_sql.json').read_text())
    with _connect(dsn) as connection:result=migrate(connection,catalog,apply=args.apply)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['ready'] else 1

if __name__=='__main__':raise SystemExit(main())

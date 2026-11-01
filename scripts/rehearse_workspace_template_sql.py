"""Native fixed template SQL in a disposable schema of the local metadata DB.

Does not connect to the application database, edit HBA, restart PostgreSQL or
change shared-memory settings. Its random schema is removed after verification.
"""
import json
import os
from pathlib import Path
import pwd
import secrets
from scripts.service_deploy import Deployment
from scripts.agentcon_config import read_settings
from agent_market.application_runtime import _private_bytes
from scripts.rehearse_storage_adapter_postgres import _driver
from agent_market.workspace_template_hub import SCHEMA
from agent_market.application_store_postgres import _normalized


def main():
    from psycopg import sql
    root=Path(__file__).resolve().parents[1]
    settings=read_settings(str(Deployment(root).settings))
    driver=_driver();options=driver.conninfo.conninfo_to_dict(_private_bytes(settings['APPLICATION_POSTGRES_DSN_FILE'],16384).decode().strip())
    if options.get('host')!=str(root/'gateway-data/postgres18/run'):
        raise RuntimeError('Configured local PostgreSQL socket required')
    catalog=json.loads((root/'agent_market/application_store_sql.json').read_text())
    entries={_normalized(e['sqlite']):e['postgres'] for e in catalog['statements']}
    schema='hub_sql_'+secrets.token_hex(8)
    checks={}
    with driver.connect(host=options['host'],port=options['port'],dbname='postgres',user=pwd.getpwuid(os.getuid()).pw_name,password='',
            passfile=str(root/'gateway-data/no-test-passfile'),connect_timeout=3,autocommit=True,sslmode='disable',gssencmode='disable',application_name='hub-sql-isolated-regression') as connection:
        def execute(statement,values=()):
            return connection.execute(entries[_normalized(statement)],values)
        assert int(connection.info.server_version)//10000==18
        with connection.transaction():
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            connection.execute(sql.SQL('SET LOCAL search_path TO {},pg_temp').format(sql.Identifier(schema)))
            for statement in SCHEMA:execute(statement)
            data=('one','ws_synthetic','draft','one',1,'{}','signed',1.0)
            execute('INSERT INTO workspace_template_records VALUES(?,?,?,?,?,?,?,?)',data)
            checks['insert_and_lookup']=execute('SELECT * FROM workspace_template_records WHERE id=? AND workspace_id=? AND kind=?',('one','ws_synthetic','draft')).fetchone()[4]==1
            checks['cross_workspace_denied']=execute('SELECT * FROM workspace_template_records WHERE id=? AND workspace_id=? AND kind=?',('one','ws_other','draft')).fetchone() is None
            update='UPDATE workspace_template_records SET revision=?,payload=?,signature=? WHERE id=? AND workspace_id=? AND revision=?'
            checks['cas_update']=execute(update,(2,'{}','changed','one','ws_synthetic',1)).rowcount==1
            checks['stale_cas_denied']=execute(update,(3,'{}','stale','one','ws_synthetic',1)).rowcount==0
            try:
                with connection.transaction():
                    execute('INSERT INTO workspace_template_records VALUES(?,?,?,?,?,?,?,?)',data)
            except driver.errors.UniqueViolation:checks['duplicate_denied']=True
            checks['history_order']=len(execute('SELECT id FROM workspace_template_records WHERE workspace_id=? AND kind=? ORDER BY created DESC LIMIT 100',('ws_synthetic','draft')).fetchall())==1
            checks['run_limit_count']=execute('SELECT COUNT(*) FROM workspace_template_records WHERE workspace_id=? AND kind=? AND created>?',('ws_synthetic','run',0.0)).fetchone()[0]==0
            checks['publication_index']=connection.execute('SELECT COUNT(*) FROM pg_indexes WHERE schemaname=%s AND indexname=%s',(schema,'idx_workspace_template_records_scope')).fetchone()[0]==1
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        checks['schema_removed']=connection.execute('SELECT to_regnamespace(%s)',(schema,)).fetchone()[0] is None
    assert all(checks.values()),checks
    print(json.dumps({'checks':checks,'postgresql_major':18,'operating_database_writes':0,'server_changes':0,'synthetic':True},sort_keys=True))

if __name__=='__main__':main()

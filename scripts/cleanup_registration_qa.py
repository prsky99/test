"""Delete only the owner-identified registration QA records; dry-run by default.

Uses the existing private PostgreSQL profile. Never prints credentials, message
bodies, addresses or visitor tokens. A mode-0600 backup precedes every mutation.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import time

RESOURCES={206598:('https://agentconcierge.biz/mcp','mcp'),206599:('https://example.com/','x402'),
    206602:('https://example.org/qa-cat','mcp'),206603:('https://example.net/qa-tos','mcp'),206604:('https://example.net/qa-time','mcp')}
INQUIRIES=['inq_IkQo5mjoerq3sO9njenbZWTu','inq_8Xi1PTM4_ZElknMm1Te_0yFH','inq_6huoOpZMbIlIB11OSglTOIjp',
    'inq_jd8YrSKN_ezrPIJXd97wzyo5','inq_Y7DNXSmdqowTLZ8sKCSCH6e-','inq_HjTfFz8-WCIMPuKLDj19v3ad','inq_5Hc1Rdliowgw0QDDbBun1830']
PRIVACY=['prv_az6qJ2k6YM74SbEH9P6XxTAE','prv_P6rsMnQJaXulBp_lBojlUJfg','prv_b0GwA9Wo4BFybiu5t2WIz31Y']
WATCHES=['tw_6a58cedad25142c171eb340344336e99','tw_447743df28596029c4f5dc1ed272735e']
SAFE_RESOURCE_TABLES={'admin_health_daily','adoption_changes','agent_test_reports','capability_eligibility',
    'connection_agents','connection_versions','health_checks','legacy_vector_generations','legacy_vector_heads',
    'legacy_vector_jobs','legacy_vector_provenance','resource_observation_generations','resource_observation_owners','vec_outbox'}
SAFE_VERSION_TABLES={'adoption_changes','capability_evidence','capability_approvals','capability_eligibility','agent_test_reports'}
SAFE_WATCH_TABLES={'agent_task_destination_checks','agent_task_permissions','agent_task_events','agent_marketing_permissions'}


def encode(value):
    if isinstance(value,(bytes,memoryview)):return {'base64':base64.b64encode(value).decode()}
    return str(value)


def deletion_order(connection, entries):
    """Respect actual database foreign keys, including migration-added keys."""
    nodes={(entry['schema'],entry['table']) for entry in entries}
    edges={node:set() for node in nodes}
    rows=connection.execute('''SELECT ns.nspname AS child_schema,cl.relname AS child,
        np.nspname AS parent_schema,cp.relname AS parent FROM pg_constraint co
        JOIN pg_class cl ON cl.oid=co.conrelid JOIN pg_namespace ns ON ns.oid=cl.relnamespace
        JOIN pg_class cp ON cp.oid=co.confrelid JOIN pg_namespace np ON np.oid=cp.relnamespace
        WHERE co.contype='f' ''').fetchall()
    for row in rows:
        child=(row['child_schema'],row['child']);parent=(row['parent_schema'],row['parent'])
        if child in nodes and parent in nodes and child!=parent:edges[child].add(parent)
    for node in nodes:
        if node not in {('public','resources'),('public','agent_task_watches')}:
            edges[node].update(nodes & {('public','resources'),('public','agent_task_watches')})
    ordered=[]
    while edges:
        ready=sorted(node for node in edges if not any(node in parents for parents in edges.values()))
        if not ready:raise RuntimeError('Linked-data dependency cycle; no deletion performed.')
        for node in ready:ordered.append(node);del edges[node]
    positions={node:index for index,node in enumerate(ordered)}
    return sorted(entries,key=lambda entry:positions[(entry['schema'],entry['table'])])


def collect(connection):
    from psycopg import sql
    entries=[]
    def select(table,column,values,schema='public'):
        rows=connection.execute(sql.SQL('SELECT * FROM {}.{} WHERE {}=ANY(%s)').format(
            sql.Identifier(schema),sql.Identifier(table),sql.Identifier(column)),(values,)).fetchall()
        if rows:entries.append({'schema':schema,'table':table,'column':column,'values':values,'rows':rows})
        return rows
    resources=select('resources','id',list(RESOURCES))
    for row in resources:
        if (row['name'],row['url'],row['kind'])!=('QA TEST - please delete',*RESOURCES[row['id']]):
            raise RuntimeError('Resource identity mismatch; no deletion performed.')
    inquiries=select('customer_inquiries','inquiry_id',INQUIRIES)
    if any(r['name']!='QA Tester' or r['email'].lower()!='qa@example.com' for r in inquiries):
        raise RuntimeError('Inquiry identity mismatch; no deletion performed.')
    select('privacy_requests','request_id',PRIVACY)
    watches=select('agent_task_watches','id',WATCHES)
    if any(r['visitor_id']!='av_3671f91d4277' for r in watches):
        raise RuntimeError('Watch owner mismatch; no deletion performed.')
    ids=[r['id'] for r in resources]
    versions=connection.execute('SELECT id FROM connection_versions WHERE resource_id=ANY(%s)',(ids,)).fetchall()
    versions=[r['id'] for r in versions]
    columns=connection.execute("SELECT table_schema,table_name,column_name FROM information_schema.columns WHERE table_schema IN ('public','agentcon_search') AND column_name IN ('resource_id','version_id','connection_version_id','watch_id','report_id') ORDER BY table_schema,table_name,column_name").fetchall()
    reports=connection.execute('SELECT id FROM agent_test_reports WHERE resource_id=ANY(%s)',(ids,)).fetchall()
    reports=[r['id'] for r in reports]
    for item in columns:
        schema,table,column=item['table_schema'],item['table_name'],item['column_name']
        values=ids if column=='resource_id' else versions if column in ('version_id','connection_version_id') else WATCHES if column=='watch_id' else reports
        if not values:continue
        rows=select(table,column,values,schema)
        allowed=(table in SAFE_RESOURCE_TABLES if column=='resource_id' else table in SAFE_VERSION_TABLES if column in ('version_id','connection_version_id') else table in SAFE_WATCH_TABLES if column=='watch_id' else table=='test_report_subject_claims')
        allowed=allowed or schema=='agentcon_search' and table=='embeddings' and column=='resource_id'
        if rows and not allowed:raise RuntimeError('Unreviewed linked table '+schema+'.'+table+'; no deletion performed.')
    select('resources_fts','rowid',ids)
    select('vec_resources','rowid',ids)
    # These two outcomes were identified by the owner, the exact QA visitor UA,
    # and the report timestamps. The real resources remain untouched.
    visitor=connection.execute('SELECT user_agent FROM agent_visitors WHERE id=%s',('av_fea05423e252',)).fetchone()
    outcomes=connection.execute('SELECT * FROM agent_outcomes WHERE visitor_id=%s AND resource_id=ANY(%s)',('av_fea05423e252',[1,34471])).fetchall()
    for row in outcomes:
        expected=(1,1793026447.7249138) if row['resource_id']==34471 else (0,1793026456.774891)
        if not visitor or not visitor['user_agent'].startswith('qa-agent/1.0') or row['success']!=expected[0] or abs(row['at']-expected[1])>0.001:
            raise RuntimeError('Outcome provenance mismatch; no deletion performed.')
        entries.append({'schema':'public','table':'agent_outcomes','column':'visitor_id','values':[row['visitor_id']],
            'rows':[row],'exact_outcome':row['resource_id']})
    feedback=connection.execute('SELECT * FROM feedback WHERE need_id=%s AND resource_id=1',('mcp_8109526e',)).fetchall()
    if feedback:
        if len(feedback)!=1 or feedback[0]['success']!=0 or abs(feedback[0]['created']-1793026456.9199)>0.001 or not any(r['resource_id']==1 for r in outcomes):
            raise RuntimeError('Feedback provenance mismatch; no deletion performed.')
        entries.append({'schema':'public','table':'feedback','column':'need_id','values':['mcp_8109526e'],'rows':feedback})
    return entries


def cleanup(connection,*,apply=False,backup_dir):
    from psycopg import sql
    from psycopg.rows import dict_row
    connection.row_factory=dict_row
    with connection.transaction():
        connection.execute("SET LOCAL statement_timeout='15s'")
        connection.execute("SET LOCAL lock_timeout='5s'")
        if apply:connection.execute('SELECT pg_advisory_xact_lock(%s)',(71498241526018,))
        else:connection.execute('SET TRANSACTION READ ONLY')
        entries=collect(connection)
        summary={}
        for entry in entries:summary[entry['table']]=summary.get(entry['table'],0)+len(entry['rows'])
        payload=json.dumps(entries,default=encode,sort_keys=True,indent=2).encode()
        directory=Path(backup_dir);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=directory/('backup-' if apply else 'plan-')
        target=target.with_name(target.name+str(time.time_ns())+'.json')
        descriptor=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(descriptor,'wb') as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
        removed={}
        if apply:
            # Children first; native DELETE triggers fence any in-flight vector publication.
            for entry in deletion_order(connection, entries):
                query=sql.SQL('DELETE FROM {}.{} WHERE {}=ANY(%s)').format(sql.Identifier(entry['schema']),sql.Identifier(entry['table']),sql.Identifier(entry['column']))
                parameters=(entry['values'],)
                if 'exact_outcome' in entry:
                    query+=sql.SQL(' AND resource_id=%s');parameters+= (entry['exact_outcome'],)
                count=connection.execute(query,parameters).rowcount
                removed[entry['table']]=removed.get(entry['table'],0)+count
            assert not collect(connection),'Remaining targeted data; transaction rolled back.'
        return {'applied':apply,'matched':summary,'deleted':removed,'backup_sha256':hashlib.sha256(payload).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    from scripts.agentcon_config import read_settings
    from agent_market.application_runtime import _connect,_private_bytes
    settings=read_settings('gateway-data/agentcon.env')
    if settings.get('APPLICATION_STORE_BACKEND')!='postgresql':raise RuntimeError('PostgreSQL profile required.')
    connection=_connect(_private_bytes(settings['APPLICATION_POSTGRES_DSN_FILE'],16384).decode().strip())
    try:result=cleanup(connection,apply=args.apply,backup_dir='reports/registration-hardening-2026-10-27/private')
    finally:connection.close()
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()

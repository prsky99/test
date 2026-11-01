"""Disposable Unix-only PostgreSQL renewal acceptance; never an operating DSN."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.rehearse_storage_adapter_postgres import _driver, _private_cluster, _tools, PORT


def contracts(connection):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.gateway import admin_auth
    from agent_market.gateway.dashboard import dashboard_router
    from agent_market.storage_adapter import open_store

    store = open_store('postgresql', connection=connection, initialize=True, workflow_key=b'n' * 32)
    try:
        store.upsert_resource({'key': 'renewal:synthetic', 'source': 'fixture', 'kind': 'mcp',
            'url': 'https://synthetic.example/mcp', 'name': 'Synthetic renewal agent',
            'description': 'Synthetic renewal acceptance', 'category': 'research', 'networks': [], 'details': {}})
        app = FastAPI()
        app.include_router(dashboard_router(store, None, None, None))
        with store.tx() as db:
            user = admin_auth.create_admin_user(db, 'renewal-fixture', 'Synthetic-password-42', 'Fixture', 'superadmin')
            raw = admin_auth.create_session(db, user['id'], user['username'], user['role'], user['name'])
        headers = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + raw}
        from agent_market.workspace_access import WorkspaceAccess, SessionActor
        access = WorkspaceAccess(store, b'n' * 32)
        with store.tx():
            assert access._actor(SessionActor(user['id'], admin_auth.session_reference(raw)))['role'] == 'superadmin'
        measurements = []
        paths = ['/home/bootstrap', '/gateway/summary?hours=24', '/gateway/controls', '/system/storage',
                 '/system/retention', '/system/retention/preview', '/catalog/agents?limit=2',
                 '/catalog/agents?limit=2&q=%25', '/public/summary', '/home/changes?since=0', '/system/activity', '/reviews']
        with TestClient(app, base_url='https://admin.test') as client:
            with store.tx() as db:
                seeded = admin_auth.create_admin_user(db, 'bootstrap-fixture', 'Bootstrap-fixture-password', 'Initial', 'superadmin')
                hashed, salt = admin_auth.hash_password('Bootstrap-fixture-password')
                store._execute('UPDATE admin_users SET password_hash=%s,salt=%s WHERE id=%s',
                    ('bootstrap$' + hashed, salt, seeded['id']))
            bootstrap = client.post('/admin/api/auth/login', headers={'X-Dashboard': '1'},
                json={'username': 'bootstrap-fixture', 'password': 'Bootstrap-fixture-password'})
            assert bootstrap.status_code == 200, bootstrap.text[:180]
            assert bootstrap.json()['user']['password_change_required']
            initial = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + bootstrap.json()['token']}
            assert client.get('/admin/api/v2/home/bootstrap', headers=initial).status_code == 428
            assert client.post('/admin/api/auth/change-password', headers=initial,
                json={'current_password': 'Bootstrap-fixture-password', 'new_password': 'PG-rotated-fixture-password'}).status_code == 200
            assert client.get('/admin/api/auth/me', headers=initial).status_code == 401
            with store.tx() as db:
                viewer = admin_auth.create_admin_user(db, 'viewer-fixture', 'Viewer-fixture-password', 'Viewer', 'viewer')
                viewer_raw = admin_auth.create_session(db, viewer['id'], viewer['username'], viewer['role'], viewer['name'])
            viewer_headers = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + viewer_raw}
            assert client.get('/admin/api/v2/home/bootstrap', headers=viewer_headers).status_code == 200
            assert client.get('/admin/api/visitors', headers=viewer_headers).status_code == 403
            for path in paths:
                started = time.monotonic()
                response = client.get('/admin/api/v2' + path, headers=headers)
                assert response.status_code == 200, (path, response.status_code, response.text[:180])
                assert 'no-store' in response.headers.get('cache-control', '')
                if path == '/home/bootstrap':
                    health = response.json()['overview']['health']
                    assert health['interval'] == 21600
                    assert {'checks_6h', 'ok_6h', 'overdue_6h', 'checks_2h'} <= set(health)
                measurements.append({'path': path, 'milliseconds': round((time.monotonic() - started) * 1000, 3)})
            activity = client.get('/admin/api/v2/system/activity', headers=headers).json()
            assert activity['available'] and 'held' in activity['writer'] and isinstance(activity['slow'], list)
            assert client.get('/admin/api/v2/system/activity', headers=viewer_headers).status_code == 403
            assert client.get('/admin/api/v2/reviews', headers=headers).json()['available'] is False  # WAC not migrated here
            first = client.get('/admin/api/v2/public/summary', headers=headers)
            assert client.get('/admin/api/v2/public/summary', headers={**headers, 'If-None-Match': first.headers['etag']}).status_code == 304
            assert client.get('/admin/api/v2/catalog/agents', headers={'X-Dashboard': '1'}).status_code == 401
            assert client.get('/admin/api/v2/catalog/agents', headers={**headers, 'Origin': 'https://untrusted.test'}).status_code == 403
            rid = client.get('/admin/api/v2/catalog/agents', headers=headers).json()['items'][0]['id']
            action = client.post('/admin/api/v2/catalog/agents/' + str(rid) + '/actions', headers=headers,
                json={'action': 'deactivate', 'reason': 'Synthetic renewal review', 'expected_active': True})
            assert action.status_code == 200, action.text[:180]
            assert not store.resource(rid)['active']
            # Specialist aliases must enforce real staff membership in the native database.
            actor = SessionActor(user['id'], admin_auth.session_reference(raw))
            ws = access.provision({'name': 'Synthetic specialist workspace', 'owner_id': user['id']}, actor)['id']
            specialist = '/admin/api/v2/workspace-panels/' + ws
            for suffix in ('/typed-flows', '/typed-flows/options', '/reliability/typed/options', '/evidence/options', '/quality/options', '/quality/assignments', '/lifecycle/preview', '/machine-updates/status', '/machine-updates/receivers/status', '/remote-a2a/options', '/remote-a2a/tasks', '/protocol-conformance', '/reliability/options', '/reliability/objects', '/reliability/inventory', '/reliability/evaluation/options', '/reliability/evaluation/status', '/reliability/routing/status', '/reliability/research/options', '/reliability/research/status', '/reliability/admission/status', '/app-factory/options', '/sdk-lifecycle', '/support-outcomes', '/advancement/ledger/options', '/advancement/ledger', '/advancement/runtime-meter', '/advancement/support', '/advancement/readiness', '/advancement/operating-preparation', '/advancement/sandbox-payments', '/advancement/agreements', '/product-composer/options', '/provider-claims', '/provider-claims/options', '/customers', '/advancement/agreements/options', '/advancement/agreements/summary'):
                result = client.get(specialist + suffix, headers=headers)
                assert result.status_code == 200 and 'no-store' in result.headers['cache-control'], result.text[:160]
                denied = client.get(specialist + suffix, headers=viewer_headers)
                assert denied.status_code == (401 if suffix == '/customers' else 404), (suffix, denied.status_code)
            for release_scope in ('/drafts/wd_'+'f'*32+'/snapshots/wss_'+'f'*32+'/release-v2/options', '/typed-flows/wtf_'+'f'*32+'/versions/wtv_'+'f'*32+'/release-v2/options'):
                absent = client.get(specialist + release_scope, headers=headers)
                assert absent.status_code in (400, 404), absent.text[:160]
                assert client.get(specialist + release_scope).status_code == 401
            invalid = {'flow_id': None, 'revision': 0, 'name': 'Invalid empty graph', 'definition': {'nodes': []}}
            assert client.post(specialist + '/typed-flows', headers=headers, json=invalid).status_code == 400
            audited = client.post(specialist + '/typed-flows', headers={**headers, 'X-Admin-Reason': 'Native audit boundary verification'}, json=invalid)
            assert audited.status_code == 400, audited.text[:160]
            with store.tx(readonly=True):
                assert store._execute("SELECT COUNT(*) FROM admin_audit_logs WHERE action='WORKSPACE_PANEL_CHANGE'").fetchone()[0] == 2
            for suffix in ('/remote-a2a/tasks', '/protocol-conformance/runs', '/protocol-conformance/cryptographic-check', '/reliability/objects', '/reliability/evaluation/control', '/reliability/research/manifests', '/reliability/admission/configure', '/app-factory/plan-reviews', '/app-factory/reviews', '/sdk-lifecycle', '/support-outcomes/records', '/advancement/ledger/approve', '/product-composer/prepare', '/provider-claims/prepare', '/customers', '/advancement/agreements'):
                rejected = client.post(specialist + suffix, headers={**headers, 'X-Admin-Reason': 'Native private protocol boundary'}, json={})
                assert rejected.status_code == 400, rejected.text[:160]
            # Link only a synthetic customer; changing roles cannot promote a staff account.
            synthetic_customer = 'cu_' + 'e' * 32
            with store.tx():
                store._execute('INSERT INTO customer_identities(id,issuer,subject_hash,active,revision,created,last_login) VALUES(%s,%s,%s,1,1,%s,%s)',
                    (synthetic_customer, 'https://accounts.google.com', 'e' * 64, time.time(), time.time()))
            customer_body = {'customer_id': synthetic_customer, 'role': 'viewer', 'active': True, 'revision': 0}
            customer_headers = {**headers, 'X-Admin-Reason': 'Native synthetic customer access review'}
            linked = client.post(specialist + '/customers', headers=customer_headers, json=customer_body)
            assert linked.status_code == 200 and linked.json()['customer']['revision'] == 1, linked.text[:160]
            assert client.post(specialist + '/customers', headers=customer_headers, json=customer_body).status_code == 409
            withdrawn = client.post(specialist + '/customers', headers=customer_headers,
                json={**customer_body, 'revision': 1, 'active': False})
            assert withdrawn.status_code == 200 and not withdrawn.json()['customer']['active'], withdrawn.text[:160]
            # Core private staff CRUD has its own reviewed namespace, not customer organization authority.
            staff_core = '/admin/api/v2/staff-workspaces'
            for suffix in ('', '/options', '/'+ws, '/'+ws+'/members', '/'+ws+'/drafts'):
                response = client.get(staff_core+suffix, headers=headers)
                assert response.status_code == 200 and 'no-store' in response.headers['cache-control'], response.text[:160]
            core_headers={**headers, 'X-Admin-Reason':'Native staff workspace scope review'}
            assert client.post(staff_core,headers=headers,json={'name':'No audit','owner_id':user['id']}).status_code == 400
            created_core=client.post(staff_core,headers=core_headers,json={'name':'Native isolated staff design','owner_id':user['id']})
            assert created_core.status_code == 200, created_core.text[:160]
            core_ws=created_core.json()['workspace']['id']
            draft_result=client.post(staff_core+'/'+core_ws+'/drafts',headers=core_headers,
                json={'name':'Native private draft','description':'Isolated fixture only','definition':{'nodes':[],'edges':[]}})
            assert draft_result.status_code == 200, draft_result.text[:160]
            draft_id=draft_result.json()['draft']['id']
            snapshot_result=client.post(staff_core+'/'+core_ws+'/drafts/'+draft_id+'/snapshots',headers=core_headers,json={'draft_revision':1})
            assert snapshot_result.status_code == 200, snapshot_result.text[:160]
            snapshot_id=snapshot_result.json()['snapshot']['id']
            artifact=client.get(staff_core+'/'+core_ws+'/drafts/'+draft_id+'/snapshots/'+snapshot_id+'/artifact',headers=headers)
            assert artifact.status_code == 200 and not artifact.json()['executable'], artifact.text[:160]
            assert client.get(staff_core+'/'+core_ws,headers=viewer_headers).status_code == 404
            for suffix in ('/credentials','/test-reports?limit=2','/capability-contracts','/connections/'+str(rid),'/overview'):
                response=client.get('/admin/api/v2/catalog-tools'+suffix,headers=headers)
                assert response.status_code == 200 and 'no-store' in response.headers['cache-control'], (suffix,response.text[:160])
                assert client.get('/admin/api/v2/catalog-tools'+suffix,headers=viewer_headers).status_code == 403
            rejected_tool=client.post('/admin/api/v2/catalog-tools/register/inspect',headers=core_headers,json={'url':'http://127.0.0.1/private'})
            assert rejected_tool.status_code == 400, rejected_tool.text[:160]
            # Explicitly migrate only the disposable fixture; exercise the new signed identity commands natively.
            from agent_market.workspace_admin_events import migrate
            migrate(store, store._workspace_admin_identity_key)
            other_login = client.post('/admin/api/auth/login', headers={'X-Dashboard': '1'},
                json={'username': 'bootstrap-fixture', 'password': 'PG-rotated-fixture-password'})
            assert other_login.status_code == 200
            reviewer = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + other_login.json()['token']}
            created = client.post('/admin/api/users', headers=headers, json={'username': 'reviewed-pg-user',
                'password': 'Reviewed-PG-fixture-password', 'role': 'operator', 'reason': 'Native creation verification'})
            assert created.status_code == 202, created.text
            def approve(response):
                item = response.json()['item']
                done = client.post('/admin/api/v2/reviews/' + item['id'] + '/approve', headers=reviewer,
                    json={'revision': item['revision'], 'reason': 'Native independent review'})
                assert done.status_code == 200 and done.json()['item']['status'] == 'applied', done.text
                return json.loads(done.json()['item']['result'])
            uid = approve(created)['user_id']
            assert '_credentials' not in client.get('/admin/api/v2/reviews', headers=headers).text
            updated = client.put('/admin/api/users/' + str(uid), headers=headers,
                json={'role': 'viewer', 'new_password': 'Replaced-PG-fixture-password', 'reason': 'Native role and password verification'})
            assert updated.status_code == 202, updated.text
            approve(updated)
            removed = client.request('DELETE', '/admin/api/users/' + str(uid), headers=headers, json={'reason': 'Native deletion verification'})
            assert removed.status_code == 202, removed.text
            approve(removed)
            # Native public-service writes use the same signed, independent review fence.
            public_base='/admin/api/v2/public/operations'
            for suffix in ('/options','/templates','/source/sns/feed','/source/security/rules'):
                response=client.get(public_base+suffix,headers=headers)
                assert response.status_code==200 and 'no-store' in response.headers['cache-control'],response.text[:180]
            def public_approve(response):
                assert response.status_code==202,response.text
                item=response.json()['review']
                done=client.post('/admin/api/v2/reviews/'+item['id']+'/approve',headers=reviewer,
                    json={'revision':item['revision'],'reason':'Native public independent review'})
                assert done.status_code==200 and done.json()['item']['status']=='applied',done.text
                return json.loads(done.json()['item']['result'])
            queued=client.post(public_base+'/sns',headers=headers,json={'action':'create','fields':{'body':'Synthetic native public update.'},'reason':'Native public post verification'})
            with store.tx(readonly=True):
                assert store._execute('SELECT COUNT(*) FROM sns_posts').fetchone()[0]==0
            public_approve(queued)
            with store.tx(readonly=True):
                assert store._execute('SELECT author FROM sns_posts').fetchone()[0]=='Agent Concierge'
            block=client.post(public_base+'/security',headers=headers,json={'action':'block','target':'203.0.113.91','fields':{'duration':3600},'reason':'Native restrictive verification'})
            assert block.status_code==200,block.text
            unblock=client.post(public_base+'/security',headers=headers,json={'action':'remove','target':'203.0.113.91','fields':{},'reason':'Native unblock verification'})
            with store.tx(readonly=True):
                assert store._execute('SELECT COUNT(*) FROM security_ip_rules').fetchone()[0]==1
            public_approve(unblock)
            # Fixed step-8 read projections and content-free operator assignment.
            insights='/admin/api/v2/insights'
            for suffix in ('/gateway','/agents/'+str(rid),'/assignments'):
                read=client.get(insights+suffix,headers=headers)
                assert read.status_code==200 and 'no-store' in read.headers['cache-control'],read.text
            with store.tx() as db:
                from agent_market.workspace_admin_events import execute
                execute(db,'case_insert',('case_native',synthetic_customer,ws,'new','normal',time.time(),time.time(),None,'Private fixture subject'))
                operator=admin_auth.create_admin_user(db,'operator-insights','Synthetic-operator-password','Operator','operator')
                operator_raw=admin_auth.create_session(db,operator['id'],operator['username'],operator['role'],operator['name'])
            graph_id=store.create_workflow({'name':'Native graph state fixture','nodes':[{'id':'probe','type':'agent','kind':'mcp','resource_id':rid,'data':{}}],'edges':[]})
            graph=client.get(insights+'/workflows/'+str(graph_id)+'/state',headers=headers)
            assert graph.status_code==200 and graph.json()['agents'][0]['id']==rid,graph.text
            assert set(graph.json()['agents'][0])=={'id','kind','active','health_status','eval_grade'}
            memo=client.post(insights+'/agents/'+str(rid)+'/notes',headers=headers,json={'note':'Synthetic native audit note','reason':'Native note projection verification'})
            assert memo.status_code==200,memo.text
            evidence=client.get(insights+'/agents/'+str(rid),headers=headers)
            assert evidence.status_code==200 and 'Synthetic native audit note' in evidence.text,evidence.text
            with store.tx(readonly=True) as db:
                from agent_market.workspace_admin_events import rows
                projected=rows(db,'case_operator_list',('',51))
                assert projected and set(projected[0])=={'id','status','priority','assigned_to','revision','updated'}
            op_headers={'X-Dashboard':'1','Authorization':'Bearer '+operator_raw}
            listing=client.get(insights+'/assignments',headers=op_headers)
            assert listing.status_code==200 and 'Private fixture subject' not in listing.text,listing.text
            body={'revision':1,'assigned_to':operator['id'],'reason':'Native operator assignment verification'}
            assigned=client.post(insights+'/assignments/case_native',headers=op_headers,json=body)
            assert assigned.status_code==200,assigned.text
            assert client.post(insights+'/assignments/case_native',headers=op_headers,json=body).status_code==409
            assert client.get('/admin/api/v2/requests/inquiries',headers=op_headers).status_code==403
            # Closure read models use the same native staff and private membership rules.
            from agent_market.admin_completion import sample_storage
            home_work=client.get('/admin/api/v2/home/work',headers=headers)
            assert home_work.status_code==200 and home_work.json()['cases']==1,home_work.text
            assert type(home_work.json()['reviews']) is int and type(home_work.json()['verified_agents']) is int,home_work.text
            operations=client.get('/admin/api/v2/customers/operations/options',headers=headers)
            assert operations.status_code==200,operations.text
            search=client.get('/admin/api/v2/home/workflows?q=Native',headers=headers)
            assert search.status_code==200 and draft_id in {v['id'] for v in search.json()['items']},search.text
            assert client.get('/admin/api/v2/home/workflows?q=Native',headers=op_headers).status_code==403
            if not store.resource(rid)['active']:
                active=client.post('/admin/api/v2/catalog/agents/'+str(rid)+'/actions',headers=headers,
                                   json={'action':'activate','expected_active':False,'reason':'Native CSV row verification'})
                assert active.status_code==200,active.text
            exported=client.get('/admin/api/v2/catalog/agents?format=csv',headers=headers)
            assert exported.status_code==200 and 'Synthetic renewal agent' in exported.text,exported.text
            assert client.get('/admin/api/v2/catalog/agents?format=csv',headers=op_headers).status_code==403
            assert sample_storage(store) and not sample_storage(store)
            evidence=client.get('/admin/api/v2/system/evidence',headers=headers)
            assert evidence.status_code==200 and len(evidence.json()['storage']['samples'])==1,evidence.text
            inquiry=store.record_customer_inquiry(category='general',name='Native fixture',email='native@example.test',subject='Native cursor fixture',message='Synthetic request')
            second_inquiry=store.record_customer_inquiry(category='general',name='Native fixture',email='native@example.test',subject='Native second cursor fixture',message='Synthetic request')
            request_list=client.get('/admin/api/v2/requests/inquiries?limit=1',headers=headers)
            assert request_list.status_code==200 and request_list.json()['items'][0]['inquiry_id']==second_inquiry,request_list.text
            cursor=request_list.json()['next_cursor']
            assert cursor
            next_page=client.get('/admin/api/v2/requests/inquiries',headers=headers,params={'limit':1,'cursor':cursor})
            assert next_page.status_code==200 and next_page.json()['items'][0]['inquiry_id']==inquiry,next_page.text
            error=client.get('/admin/api/v2/catalog/agents?limit=0',headers=headers)
            assert error.status_code==400 and error.json()['error_code']=='INVALID_REQUEST',error.text
            with store.tx(readonly=True):
                assert store._execute('SELECT COUNT(*) FROM security_ip_rules').fetchone()[0]==0
        return {'authenticated_gets': len(paths), 'checks': {'specialist_membership_and_audit': True, 'release_and_machine_aliases': True, 'remote_and_protocol_aliases': True, 'reliability_research_aliases': True, 'growth_product_simulation_aliases': True, 'agreement_identity_aliases': True, 'native_customer_link_revision_withdrawal': True, 'staff_core_crud_and_artifact': True, 'catalog_tools_roles_and_ssrf': True, 'reviewed_staff_accounts': True, 'public_read_and_reviewed_sns_security': True,'insights_and_content_free_operator_assignment':True,'renewal_closure_native_read_models':True, 'native_routes': True, 'etag': True, 'bootstrap_password_rotation': True, 'viewer_scope': True, 'native_workspace_staff_recheck': True,
            'individual_session_required': True, 'cross_origin_denied': True, 'reviewed_synthetic_mutation': True},
            'measurements': measurements, 'operating_writes': 0, 'external_provider_calls': 0,
            'scope': 'Disposable local PostgreSQL fixture; these timings are not an operating-load SLA.'}
    finally:
        store.close()


def worker():
    cluster = json.load(sys.stdin)
    connection = _driver().connect(host=cluster['socket'], hostaddr='', port=PORT, dbname='postgres', user='postgres',
        password='synthetic-unused-password', passfile=str(Path(cluster['root']) / 'no-password-file'),
        autocommit=True, connect_timeout=3, sslmode='disable', gssencmode='disable')
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr()")
            assert cursor.fetchone() == ('', None, None)
        print(json.dumps(contracts(connection)))
    finally:
        connection.close()


def rehearse():
    driver = _driver()
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment'])
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(driver.__file__).resolve().parent.parent)
        result = subprocess.run([sys.executable, '-B', '-c', 'from scripts.rehearse_admin_next_postgres import worker;worker()'],
            env=environment, input=json.dumps({'socket': cluster['socket'], 'root': cluster['root']}),
            text=True, capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError('Renewal PostgreSQL contracts failed: ' + result.stderr[-3000:])
        return {**json.loads(result.stdout), 'temporary_cluster_removed': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.parse_args()
    print(json.dumps(rehearse(), indent=2))

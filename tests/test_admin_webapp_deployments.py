"""Real controlled execution, scoped deployments and unchanged public export boundaries."""
from io import BytesIO
import json
import threading
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.dashboard import dashboard_router
from agent_market.workflow_apps import service_for, normalize_origins
from agent_market.workflow_webapp import build_package, export_config
from tests.test_workflow_runtime import runtime, save, node, wait
from tests.conftest import staff_headers

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


@pytest.fixture
def app_runtime(runtime):
    rt, rid, remote = runtime
    proxy = rt.proxy
    front = Front(rt.store, allow_private=True)
    front.proxy = front.workflows.proxy = proxy
    public = TestClient(create_front_app(front), base_url='https://agentconcierge.biz')
    app = FastAPI(); app.include_router(dashboard_router(rt.store, ':memory:', 'deployment-admin', None, front=front))
    admin = TestClient(app, base_url='https://admin.test')
    workflow = save(rt.store, [node(resource_id=rid, action='get_weather', input={'city':'Tokyo'})], is_template=1)
    yield rt, workflow, service_for(rt.store, rt), public, admin
    public.close(); admin.close()


def start(client, deployment, body=None, **headers):
    return client.post('/api/workflow-apps/' + deployment['app_id'] + '/runs', json=body or {}, headers={'X-Publish-Key':deployment['publish_key'], **headers})


def test_dynamic_input_and_capability_cannot_cross_deployments_or_legacy_api(app_runtime):
    rt, wf, apps, public, _ = app_runtime
    field = apps.candidates(apps.published(wf['id']))[0]
    deployment = apps.create(wf['id'], {'input_fields':[field['id']], 'allowed_origins':['https://customer.example']})
    result = start(public, deployment, {'input':{field['id']:'London'}}, Origin='https://customer.example')
    assert result.status_code == 202
    job = result.json(); outcome = wait(rt, job)
    assert outcome['status'] == 'succeeded'
    assert outcome['node_results'][0]['input'] == {'city':'London'}
    assert rt.store.get_workflow(wf['id'])['nodes'][0]['data']['input'] == {'city':'Tokyo'}
    route = '/api/workflow-apps/' + deployment['app_id'] + '/runs/' + job['run_id']
    headers = {'X-Publish-Key':deployment['publish_key'], 'X-Workflow-Key':job['run_key'], 'Origin':'https://customer.example'}
    observed = public.get(route, headers=headers)
    assert observed.status_code == 200 and 'input' not in observed.json()['node_results'][0]
    assert public.get('/api/workflows/runs/' + job['run_id'], headers={'X-Workflow-Key':job['run_key']}).status_code == 404
    assert public.get(route, headers={**headers, 'X-Workflow-Key':'a'*43}).status_code == 404
    assert public.get(route, headers={**headers, 'Origin':'https://attacker.example'}).status_code == 404
    other = apps.create(wf['id'], {})
    other_route = route.replace(deployment['app_id'], other['app_id'])
    assert public.get(other_route, headers={**headers, 'X-Publish-Key':other['publish_key']}).status_code == 404
    with rt.store.tx() as db: db.execute('UPDATE workflow_app_runs SET expires=0 WHERE run_id=?', (job['run_id'],))
    assert public.get(route, headers=headers).status_code == 404


@pytest.mark.parametrize('value', [12, None, "{{$node['private'].output}}", 'http://127.0.0.1/private', 'HTTP://127.0.0.1/private', 'https://[::1]/private', 'file:///etc/passwd', 'x'*4097])
def test_dynamic_inputs_are_bound_typed_and_bounded(app_runtime, value):
    rt, wf, apps, public, _ = app_runtime
    field = apps.candidates(apps.published(wf['id']))[0]
    deployment = apps.create(wf['id'], {'input_fields':[field['id']]})
    assert start(public, deployment, {'input':{field['id']:value}}).status_code == 400
    assert rt.history(wf['id']) == []


def test_graph_tool_key_and_workflow_changes_are_rejected(app_runtime):
    rt, wf, apps, public, _ = app_runtime
    deployment = apps.create(wf['id'], {})
    for body in ({'template_id':wf['id']}, {'nodes':[]}, {'input':{'url':'https://attacker.example'}}, {'input':'question'}):
        assert start(public, deployment, body).status_code == 400
    rt.store.update_workflow(wf['id'], {'nodes':[node(resource_id=wf['nodes'][0]['data']['resource_id'], action='get_weather', input={'city':'Paris'})], 'edges':[]})
    assert start(public, deployment).status_code == 400
    assert rt.history(wf['id']) == []


def test_plain_text_with_colon_remains_a_valid_application_input(app_runtime):
    rt, wf, apps, public, _ = app_runtime
    field = apps.candidates(apps.published(wf['id']))[0]
    deployment = apps.create(wf['id'], {'input_fields':[field['id']]})
    response = start(public, deployment, {'input':{field['id']:'Topic: agent news'}})
    assert response.status_code == 202
    assert wait(rt, response.json())['node_results'][0]['input']['city'] == 'Topic: agent news'


def test_limits_revocation_and_nonsecret_admin_listing(app_runtime):
    rt, wf, apps, public, admin = app_runtime
    deployment = apps.create(wf['id'], {'minute_limit':1})
    first = start(public, deployment); assert first.status_code == 202
    wait(rt, first.json())
    limited = start(public, deployment)
    assert limited.status_code == 429 and limited.headers['retry-after'] == '60'
    listed = apps.list(wf['id'])
    assert deployment['publish_key'] not in str(listed) and 'key_hash' not in str(listed)
    route = f"/admin/api/workflows/{wf['id']}/apps/{deployment['app_id']}"
    assert admin.delete(route).status_code in (401,403)
    assert admin.delete(route, headers=staff_headers(admin)).status_code == 200
    assert start(public, deployment).status_code == 404


def test_admin_packages_are_enhanced_while_public_package_remains_v1(app_runtime):
    rt, wf, apps, public, admin = app_runtime
    headers = staff_headers(admin)
    root = f"/admin/api/workflows/{wf['id']}/export-app"
    assert admin.get(root + '/options', headers=headers).json()['fields']
    response = admin.post(root + '/package', headers=headers, json={})
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as package:
        manifest = json.loads(package.read('app-manifest.json'))
        assert manifest['sdk_version'] == '1.1.0'
        assert manifest['app_id'].startswith('app_') and manifest['publish_key'].startswith('wfpk_')
        assert 'node_id' not in str(manifest) and 'credential_refs' not in str(manifest)
        assert 'weather.example' not in b''.join(package.read(n) for n in package.namelist()).decode()
        assert 'onFallback' in package.read('assets/agentconcierge-sdk.js').decode()
        assert 'cards = new Map()' in package.read('assets/app.js').decode()
    legacy, _ = build_package(export_config(wf))
    with ZipFile(BytesIO(legacy)) as package:
        manifest = json.loads(package.read('app-manifest.json'))
        assert manifest['sdk_version'] == '1.0.0' and 'app_id' not in manifest
        assert '/api/workflows/run' in package.read('assets/agentconcierge-sdk.js').decode()
    html = admin.post(root + '/html', headers=headers, json={})
    assert html.status_code == 200 and '<div id="workflowInputs">' in html.text
    assert 'src="assets/' not in html.text and 'href="assets/' not in html.text
    assert '1.1.0' in html.text


@pytest.mark.parametrize('origins', [['https://example.com/path'], ['null'], ['https://user:pass@example.com'], ['https://example.com?key=value'], ['*'], 'https://example.com'])
def test_invalid_origin_policies_are_rejected(origins):
    with pytest.raises(ValueError): normalize_origins(origins)


def test_daily_limit_and_application_key_validation(app_runtime):
    rt, wf, apps, public, _ = app_runtime
    deployment = apps.create(wf['id'], {'day_limit':1, 'minute_limit':30})
    first = start(public, deployment); assert first.status_code == 202; wait(rt, first.json())
    with rt.store.tx() as db: db.execute("DELETE FROM workflow_app_usage WHERE operation='start'")
    assert start(public, deployment).status_code == 429
    assert start(public, {**deployment,'publish_key':'wfpk_'+'a'*43}).status_code == 404
    response = public.options('/api/workflow-apps/' + deployment['app_id'] + '/runs', headers={'Origin':'https://customer.example','Access-Control-Request-Headers':'X-Publish-Key'})
    assert response.status_code == 204 and 'X-Publish-Key' in response.headers['access-control-allow-headers']


def test_capability_checked_cancellation_and_revocation_of_running_deployment(app_runtime):
    rt, wf, apps, public, _ = app_runtime
    remote = rt.proxy._http._transport
    entered, release = threading.Event(), threading.Event()
    original = remote.handle_request
    def blocked(request):
        if json.loads(request.content or '{}').get('method') == 'tools/call':
            entered.set(); release.wait(3)
        return original(request)
    remote.handle_request = blocked
    deployment = apps.create(wf['id'], {})
    try:
        job = start(public, deployment).json()
        assert entered.wait(2)
        route = '/api/workflow-apps/'+deployment['app_id']+'/runs/'+job['run_id']+'/cancel'
        assert public.post(route, headers={'X-Publish-Key':deployment['publish_key']}).status_code == 404
        response = public.post(route, headers={'X-Publish-Key':deployment['publish_key'],'X-Workflow-Key':job['run_key']})
        assert response.status_code == 200 and response.json()['cancel_requested'] is True
        apps.revoke(wf['id'], deployment['app_id'])
    finally:
        release.set()
    assert wait(rt, job)['status'] == 'cancelled'
    row = dict(rt.store.query('SELECT * FROM workflow_apps WHERE id=?',(deployment['app_id'],))[0])
    assert deployment['publish_key'] not in json.dumps(row) and row['active'] == 0


@pytest.mark.parametrize('raw', ['null','[]','{"input":NaN}','{"input":'+('['*1500)+(']'*1500)+'}', 'x'*16001])
def test_malformed_and_oversized_bodies_never_start_execution(app_runtime, raw):
    rt, wf, apps, public, _ = app_runtime
    deployment = apps.create(wf['id'], {})
    response = public.post('/api/workflow-apps/'+deployment['app_id']+'/runs', content=raw,
                           headers={'X-Publish-Key':deployment['publish_key'],'Content-Type':'application/json'})
    assert response.status_code in (400,413)
    assert rt.history(wf['id']) == []

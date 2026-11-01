"""Portable ZIP boundaries, arbitrary hosting origins and gateway-only SDK traffic."""
from io import BytesIO
from html import unescape
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from agent_market.workflow_webapp import build_package, export_config, GATEWAY
from tests.test_admin_security_browser import browser
from tests.test_workflow_runtime_browser import studio, login
from tests.conftest import STAFF, staff_session  # individual staff session; the machine token reads aggregates only

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

playwright = pytest.importorskip('playwright.sync_api')


def test_export_package_auth_and_minimal_configuration(tmp_path):
    store = Store(str(tmp_path / 'package.db')); front = Front(store)
    app = FastAPI(); app.include_router(dashboard_router(store, str(tmp_path / 'package.db'), 'package-admin', None, front=front))
    staff_session(store)
    client = TestClient(app)
    route = '/admin/api/workflows/1/export-app/package'
    assert client.post(route, json={}).status_code in (401, 403)
    headers = STAFF
    assert client.post(route, headers={'Authorization': 'Bearer package-admin'}, json={}).status_code in (401, 403)
    response = client.post(route, headers=headers, json={'api_origin': 'https://attacker.example', 'title': 'Injected'})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-disposition'].endswith('-webapp.zip"')
    with ZipFile(BytesIO(response.content)) as package:
        assert set(package.namelist()) == {'index.html', 'assets/agentconcierge-sdk.js', 'assets/app.js', 'assets/styles.css', 'README.md', 'app-manifest.json'}
        assert all(not n.startswith('/') and '..' not in n.split('/') for n in package.namelist())
        assert all((info.external_attr >> 16) & 0o777 == 0o644 for info in package.infolist())
        text = '\n'.join(package.read(n).decode() for n in package.namelist())
        assert 'attacker.example' not in text and 'package-admin' not in text
        assert 'resource_id' not in text and 'credential_refs' not in text
        assert 'agent-pulse-seven.vercel.app' not in text
        manifest = json.loads(package.read('app-manifest.json'))
        assert manifest['gateway'] == GATEWAY
        assert manifest['workflow_id'] == 1
        assert 'unsafe-inline' not in package.read('index.html').decode()
    with store.tx() as db: db.execute('UPDATE agent_workflows SET is_active=0 WHERE id=1')
    assert client.post(route, headers=headers, json={}).status_code == 400
    client.close(); store._db.close()


def test_builder_rejects_other_gateways_and_escapes_metadata():
    config = {'workflow_id': 1, 'title': '</script><img src=x onerror=alert(1)>', 'description': '"/><script>alert(1)</script>', 'api_origin': GATEWAY}
    data, filename = build_package(config)
    assert '/' not in filename and '\r' not in filename and '\n' not in filename
    with ZipFile(BytesIO(data)) as package:
        index = package.read('index.html').decode()
        assert '<img' not in index and '<script>alert' not in index
        assert '&lt;img' in index
        assert 'connect-src https://agentconcierge.biz' in index
        assert "script-src-attr 'none'" in unescape(index)
    with pytest.raises(ValueError): build_package({**config, 'api_origin': 'https://other.example'})
    with pytest.raises(ValueError): build_package({**config, 'workflow_id': True})


@pytest.mark.parametrize('hosting', ['https://customer.example', 'http://customer.test:8080'])
def test_admin_zip_runs_on_independent_host_and_subdirectory(studio, tmp_path, hosting):
    page, wid, front, errors, requests = studio
    login(page)
    page.evaluate('async id=>{await loadWorkflows();selectWorkflow(id);}', wid)
    page.locator('#btnExportAppFromCanvas').click()
    with page.expect_download() as event: page.locator('#btnDownloadStandaloneApp').click()
    assert event.value.suggested_filename.endswith('-webapp.zip')
    downloaded = tmp_path / 'webapp.zip'; event.value.save_as(downloaded)
    with ZipFile(downloaded) as package: files = {name: package.read(name) for name in package.namelist()}
    observations = []
    page.on('request', lambda request: observations.append(request))
    page.context.add_cookies([{'name': 'private_session', 'value': 'must-not-send', 'url': GATEWAY, 'sameSite': 'None', 'secure': True}])
    root = hosting + '/apps/weather/'

    def hosted(route):
        relative = route.request.url.removeprefix(root) or 'index.html'
        body = files.get(relative)
        if body is None: return route.fulfill(status=404, body='Not found')
        kind = 'application/javascript' if relative.endswith('.js') else 'text/css' if relative.endswith('.css') else 'text/html'
        route.fulfill(status=200, body=body, content_type=kind)

    page.context.route(hosting + '/**', hosted)
    page.goto(root)
    playwright.expect(page.locator('#appStatus')).to_have_text('Ready')
    page.locator('#runAppBtn').click()
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded')
    playwright.expect(page.locator('#stepsContainer')).to_contain_text('Tokyo: 22C')
    gateway_requests = [r for r in observations if r.url.startswith(GATEWAY + '/api/')]
    assert gateway_requests and any(r.method == 'POST' for r in gateway_requests)
    assert all(r.url.startswith(GATEWAY + '/api/workflow-apps/') for r in gateway_requests)
    assert all('authorization' not in r.all_headers() and 'cookie' not in r.all_headers() for r in gateway_requests)
    assert all(r.all_headers().get('origin') == hosting for r in gateway_requests)
    assert all('run_key' not in r.url and 'token=' not in r.url for r in gateway_requests)
    assert any('x-workflow-key' in r.headers for r in gateway_requests)
    # The wrapper exposes only an opaque handle, including to JSON serialization.
    observed = page.evaluate('''async id => {
      const client = AgentConciergeWorkflow.createClient();
      const handle = await client.run(id);
      const result = await client.wait(handle);
      const cancellation = await client.cancel(handle);
      let foreignHandleRejected=false;
      try { await client.status({runId:handle.runId}); } catch(e) { foreignHandleRejected=true; }
      return {handle:JSON.parse(JSON.stringify(handle)),status:result.status,cancellation:cancellation.cancel_requested,foreignHandleRejected,
        stored:Object.keys(localStorage),config:document.getElementById('wfData').textContent};
    }''', wid)
    assert set(observed['handle']) == {'runId', 'status'}
    assert observed['status'] == 'succeeded' and observed['foreignHandleRejected']
    assert observed['cancellation'] is True
    assert observed['stored'] == [] and 'run_key' not in observed['config']
    assert any(p.startswith('/api/workflow-apps/') and p.endswith('/runs') for _, p, _ in requests)
    assert front.workflows.history(wid)
    assert not errors


def test_sdk_rejects_injected_origin_and_invalid_id_before_network(studio):
    page, wid, _, errors, _ = studio
    page.goto('https://agentconcierge.biz/#workflows')
    page.wait_for_function('typeof createAgentConciergeClient === "function" && typeof buildWorkflowAppHTML === "function"')
    result = page.evaluate('''async () => {
      const client = createAgentConciergeClient();
      let invalid=false,foreignOrigin=false;
      try { await client.run('../admin'); } catch (e) { invalid=true; }
      try { buildWorkflowAppHTML({workflow_id:1,api_origin:'https://attacker.example'}); } catch(e) { foreignOrigin=true; }
      return {origin:client.origin,invalid,foreignOrigin};
    }''')
    assert result == {'origin': GATEWAY, 'invalid': True, 'foreignOrigin': True}
    assert not errors


@pytest.mark.parametrize('status,body', [(200, 'null'), (200, '<html>private server diagnostic</html>'), (500, '{"error":"private server diagnostic"}'), (200, '{"run_id":"invalid","run_key":"short"}')])
def test_sdk_does_not_expose_server_diagnostics_or_retry_start(studio, status, body):
    page, wid, _, errors, _ = studio
    page.goto('https://agentconcierge.biz/#workflows')
    page.wait_for_function('typeof createAgentConciergeClient === "function"')
    calls = []
    def invalid(route):
        calls.append(route.request.method)
        route.fulfill(status=status, content_type='application/json', body=body)
    page.context.route(GATEWAY + '/api/workflows/run', invalid)
    message = page.evaluate('''async id => {
      try { await createAgentConciergeClient().run(id); return 'unexpected'; }
      catch(e) { return e.message; }
    }''', wid)
    assert message != 'unexpected' and 'private server diagnostic' not in message
    assert calls == ['POST']
    assert not errors


def test_downloaded_fixed_app_pins_reviewed_graph_and_rejects_invalid_hash(studio, tmp_path):
    """A private saved template app must never silently run a changed public graph."""
    import copy
    from tests.workflow_package_helpers import open_hosted_package
    page,wid,front,errors,requests=studio
    page.goto(GATEWAY+'/#workflows')
    page.evaluate('async id=>{await loadFrontTemplates(true);loadFrontTemplateToCanvas(id)}',wid)
    with page.expect_download() as event:page.locator('#btnFrontExportApp').click()
    archive=tmp_path/'pinned.zip';event.value.save_as(archive)
    files=open_hosted_package(page,archive)
    assert b'definition_hash' in files['index.html']
    invalid=page.evaluate('''async wid=>{try{await AgentConciergeWorkflow.createClient().run(wid,{definitionHash:'invalid'});return false}catch{return true}}''',wid)
    assert invalid and not front.workflows.history(wid)
    workflow=front.store.get_workflow(wid);nodes=copy.deepcopy(workflow['nodes'])
    nodes[-1]['name']='Changed published step'
    front.store.update_workflow(wid,{'nodes':nodes})
    page.locator('#runAppBtn').click()
    playwright.expect(page.locator('#appStatus')).to_contain_text('could not',timeout=10000)
    assert not front.workflows.history(wid)
    assert any(method=='POST' and path=='/api/workflows/run' and json.loads(body or '{}').get('definition_hash') for method,path,body in requests)
    assert not errors

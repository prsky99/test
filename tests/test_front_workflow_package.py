"""Public download authorization, safe packages and browser execution from another host."""
from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store
from tests.test_admin_security_browser import browser
from tests.test_workflow_runtime_browser import studio
from tests.workflow_package_helpers import open_hosted_package

playwright = pytest.importorskip('playwright.sync_api')


def test_public_package_has_no_private_definitions_and_starts_no_execution(tmp_path):
    store = Store(str(tmp_path / 'public.db')); front = Front(store)
    client = TestClient(create_front_app(front), base_url='https://agentconcierge.biz')
    store.set_credential('TEST_KEY', 'private-provider-secret', 'test', '')
    response = client.get('/api/workflows/1/webapp?api_origin=https://attacker.example&title=Injected')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-disposition'].endswith('-webapp.zip"')
    with ZipFile(BytesIO(response.content)) as package:
        text = '\n'.join(package.read(name).decode() for name in package.namelist())
        assert 'private-provider-secret' not in text
        assert 'attacker.example' not in text and 'Injected' not in text
        assert '/admin/' not in text and 'resource_id' not in text
        assert 'credential_refs' not in text
        manifest = json.loads(package.read('app-manifest.json'))
        assert manifest['gateway'] == 'https://agentconcierge.biz' and manifest['workflow_id'] == 1
    assert front.workflows.history(1) == []
    client.close(); store._db.close()


def test_private_inactive_unsafe_or_absent_workflow_is_not_exported(tmp_path):
    store = Store(str(tmp_path / 'denials.db')); front = Front(store)
    client = TestClient(create_front_app(front))
    private = store.create_workflow({'name':'Private draft','nodes':[],'edges':[],'is_template':0})
    unsafe = store.create_workflow({'name':'Unsafe public template','nodes':[{'id':'step','type':'agent','kind':'mcp','data':{'credential_refs':{'api_key':'PRIVATE_KEY'}}}],'edges':[],'is_template':1})
    with store.tx() as db: db.execute('UPDATE agent_workflows SET is_active=0 WHERE id=1')
    for identity in (private, unsafe, 1, -1, 2147483648, 999999):
        response = client.get(f'/api/workflows/{identity}/webapp')
        assert response.status_code == 404
        assert response.headers.get('content-type','').startswith(('application/json','application/problem+json'))
    front.security.allow_probe = lambda *args, **kwargs: False
    assert client.get('/api/workflows/2/webapp').status_code == 429
    client.close(); store._db.close()


@pytest.mark.parametrize('entry', ['canvas', 'hub'])
def test_frontend_download_buttons_export_gateway_zip_and_run_on_other_host(studio, tmp_path, entry):
    page, wid, _, errors, requests = studio
    page.goto('https://agentconcierge.biz/#workflows')
    page.evaluate('async id=>{await loadFrontTemplates(true);loadFrontTemplateToCanvas(id);}', wid)
    if entry == 'canvas':
        button = page.locator('#btnFrontExportApp')
    else:
        page.locator('#btnFrontWfViewTemplates').click()
        page.locator('#frontTemplatesGrid .template-card').filter(has_text='Recorded Weather Pipeline').get_by_role('button',name='Preview Recorded Weather Pipeline',exact=True).click()
        button = page.locator('#wfLibraryPreview').get_by_role('button',name='Download Web App',exact=True)
    with page.expect_download() as event: button.click()
    assert event.value.suggested_filename == 'recorded-weather-pipeline-webapp.zip'
    path = tmp_path / (entry + '.zip'); event.value.save_as(path)
    files = open_hosted_package(page, path)
    assert json.loads(files['app-manifest.json'])['workflow_id'] == wid
    page.locator('#runAppBtn').click()
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded')
    playwright.expect(page.locator('#stepsContainer')).to_contain_text('Tokyo: 22C')
    assert any(method == 'GET' and url == f'/api/workflows/{wid}/webapp' for method, url, _ in requests)
    assert not errors


def test_download_error_recovers_buttons_without_private_error_output(studio):
    page, wid, _, errors, _ = studio
    page.goto('https://agentconcierge.biz/#workflows')
    page.evaluate('async id=>{await loadFrontTemplates(true);loadFrontTemplateToCanvas(id);}', wid)
    page.route('**/api/workflows/*/webapp', lambda route: route.fulfill(status=500, content_type='application/json', body='{"error":"private server diagnostic"}'))
    page.locator('#btnFrontExportApp').click()
    playwright.expect(page.locator('#btnFrontExportApp')).to_be_enabled()
    assert 'private server diagnostic' not in page.locator('body').inner_text()
    assert not errors


def test_hostile_published_copy_and_provider_output_are_text_in_package(studio, tmp_path):
    page, wid, front, errors, _ = studio
    attack = '<img src=x onerror="window.__packageXss=1">'
    front.store.update_workflow(wid, {'name':attack, 'description':attack})
    front.proxy._http._transport.call_result = {'content':[{'type':'text','text':attack}]}
    page.goto('https://agentconcierge.biz/#workflows')
    page.evaluate('async id=>{await loadFrontTemplates(true);loadFrontTemplateToCanvas(id);}', wid)
    with page.expect_download() as event: page.locator('#btnFrontExportApp').click()
    path = tmp_path / 'hostile.zip'; event.value.save_as(path)
    open_hosted_package(page, path)
    assert page.locator('h1').inner_text() == attack
    page.locator('#runAppBtn').click()
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded')
    playwright.expect(page.locator('#stepsContainer')).to_contain_text('__packageXss=1')
    assert json.loads(page.locator('#stepsContainer pre').inner_text())['content'][0]['text'] == attack
    assert page.locator('img').count() == 0
    assert page.evaluate('window.__packageXss || 0') == 0
    assert not errors

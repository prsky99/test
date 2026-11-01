"""Offline desktop browsers use actual exported typed SDK assets and test APIs."""
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

from playwright.sync_api import expect

from tests.test_workspace_typed_release import typed_release_world, typed_world, routing, sign_in, ORIGIN
from tests.test_front_workflow_browser import browser
from tests.test_workspace_execution_api import private_api

REPORT = Path('reports/advancement-batch7-2026-10-19/typed-sdk2')


def bridge(context, bff, gateway, external):
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        client = bff if url.hostname == 'customer.example' else gateway if url.hostname == 'agentconcierge.biz' else None
        if client is None:
            external.append(request.url); return route.abort()
        response = client.request(request.method, url.path+('?' +url.query if url.query else ''),
            headers=request.all_headers(), content=request.post_data, follow_redirects=False)
        headers = {k: v for k, v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')}
        if response.headers.get_list('set-cookie'): headers['set-cookie'] = '\n'.join(response.headers.get_list('set-cookie'))
        route.fulfill(status=response.status_code, headers=headers, body=response.content)
    context.route('**/*', serve)


def test_actual_exported_typed_sdk_whole_graph_review_fresh_consent_and_safe_output(typed_release_world, browser):
    s = typed_release_world; sign_in(s); before = len(s.w.calls)
    context = browser.new_context(viewport={'width': 1280, 'height': 1000}); page = context.new_page(); external=[]; errors=[]
    bridge(context, s.bff, s.gateway, external); page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(ORIGIN); expect(page.locator('#status')).to_contain_text('Customer app session confirmed')
    page.locator('#prepare').click(); expect(page.locator('#preview')).to_contain_text('Selected prior-output bindings:')
    expect(page.locator('#preview')).to_contain_text('followup'); expect(page.locator('#preview')).to_contain_text('Branch condition:')
    expect(page.locator('#authority')).not_to_be_checked(); expect(page.locator('#run')).to_be_disabled()
    assert len(s.w.calls) == before and 'primary.example' not in page.locator('#preview').inner_text()
    page.locator('#authority').check(); page.locator('#run').click(); expect(page.locator('#status')).to_have_text('Task completed.')
    assert len(s.w.calls) == before+2
    expect(page.locator('#output')).to_contain_text('Step: first'); expect(page.locator('#output')).to_contain_text('Step: followup')
    expect(page.locator('#authority')).not_to_be_checked(); expect(page.locator('#run')).to_be_disabled()
    assert page.locator('#output a,#output img,#output script').count() == 0
    page.locator('#history').click(); expect(page.locator('#runs button')).to_have_count(1)
    page.locator('#runs button').click(); expect(page.locator('#output')).to_contain_text('Step: followup')
    assert len(s.w.calls) == before+2 and not errors and not external
    assert page.evaluate('Object.keys(localStorage).length+Object.keys(sessionStorage).length') == 0
    REPORT.mkdir(parents=True, exist_ok=True); page.screenshot(path=str(REPORT/'customer-app.png'), full_page=True)
    page.locator('#prepare').click(); expect(page.locator('#authority')).not_to_be_checked(); expect(page.locator('#run')).to_be_disabled()
    context.close()


def test_actual_dashboard_fixed_asset_centered_management_and_download(typed_release_world, private_api, browser):
    s = typed_release_world
    actual = private_api.client.get('/admin/assets/workspace-typed-release-admin.js')
    assert actual.status_code == 200 and actual.content == Path('agent_market/gateway/workspace-typed-release-admin.js').read_bytes()
    assert actual.headers['cache-control'] == 'no-store'
    assert private_api.client.get('/admin/assets/workspace_typed_release.py').status_code == 404
    root = private_api.client.get('/admin/ui').text
    import re
    assert re.search(r'<script nonce="[A-Za-z0-9_=-]+" src="/admin/assets/workspace-typed-release-admin.js"', root)
    fixture = '''<!doctype html><html><head><style>:root{--bg:white;--text:#19243a;--line:#dce4ef}body{font:16px system-ui}dialog::backdrop{background:#19243a88}</style></head><body><select id="workspaceSelect"><option value="WS">Selected workspace</option></select><script>var token=TOKEN,currentUser={user_id:1,role:'superadmin'},state={tab:'workspaces'};async function api(path,options={}){const response=await fetch(path,{method:options.method||'GET',headers:{Authorization:'Bearer '+token,'X-Dashboard':'1',...(options.json?{'Content-Type':'application/json'}:{})},body:options.json?JSON.stringify(options.json):undefined,signal:options.signal});if(!response.ok)throw Error();return options.responseType==='blob'?response.blob():response.json();}</script><script src="/admin/assets/workspace-typed-release-admin.js"></script></body></html>'''.replace('WS', s.w.ws).replace('TOKEN', json.dumps(s.w.raw))
    context = browser.new_context(viewport={'width': 1280, 'height': 1000}, accept_downloads=True); page=context.new_page(); errors=[]
    def serve(route):
        request=route.request; url=urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz': return route.abort()
        if url.path == '/fixture': return route.fulfill(status=200, content_type='text/html; charset=utf-8', body=fixture)
        if url.path == '/admin/assets/workspace-typed-release-admin.js': return route.fulfill(status=200, content_type='application/javascript; charset=utf-8', body=actual.content)
        response=s.gateway.request(request.method, url.path, headers=request.all_headers(), content=request.post_data)
        route.fulfill(status=response.status_code, headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')}, body=response.content)
    context.route('**/*',serve); page.on('pageerror',lambda error: errors.append(str(error))); page.goto('https://agentconcierge.biz/fixture')
    page.evaluate('window.WorkspaceTypedReleaseAdmin.open('+json.dumps(s.w.ws)+','+json.dumps(s.flow['id'])+','+json.dumps(s.flow['version_id'])+')')
    dialog=page.locator('#workspaceTypedReleaseDialog'); expect(dialog).to_be_visible(); expect(page.locator('#workspaceTypedReleaseStatus')).to_contain_text('Current owner controls loaded')
    box=dialog.bounding_box(); assert abs(box['x']+box['width']/2-640) <= 2 and abs(box['y']+box['height']/2-500) <= 2
    expect(page.locator('#workspaceTypedDeploymentConsent')).not_to_be_checked(); expect(dialog.get_by_role('button', name='Issue typed deployment grant')).to_be_disabled()
    with page.expect_download() as downloaded: dialog.get_by_role('button', name='Download typed SDK 2 ZIP').click()
    with ZipFile(downloaded.value.path()) as archive:
        assert json.loads(archive.read('app-manifest.json'))['profile'] == 'workspace-typed-sdk-v2'
        assert 'Selected prior-output bindings' in archive.read('app-v2.js').decode()
    REPORT.mkdir(parents=True, exist_ok=True); page.screenshot(path=str(REPORT/'owner-management.png'))
    page.evaluate('currentUser=null;window.WorkspaceTypedReleaseAdmin.onSession()'); expect(dialog).to_have_count(0)
    assert not errors; context.close()

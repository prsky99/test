"""Offline Chromium drives named-session APIs and a controlled A2A transport."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_remote_a2a import remote


@pytest.fixture
def task_page(remote, browser):
    x = remote
    context = browser.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
    context.set_offline(True)
    page = context.new_page(); x.page = page
    x.browser_writes, x.browser_reads, x.external, x.errors, x.pending = [], [], [], [], []
    x.hold = False
    raw = x.w.headers['owner']['Authorization'][7:]
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><style nonce="fixture">body{font-family:system-ui;background:#f3f6fa;color:#172235}.card{border:1px solid #dce3ee;border-radius:12px}button,input,select,textarea{font:inherit;padding:9px;border:1px solid #cbd5e3;border-radius:8px}button{cursor:pointer}input[type=checkbox]{width:auto}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #527bf5;outline-offset:3px}dialog::backdrop{background:#14213988}</style></head><body><select id="workspaceSelect"><option value="WORKSPACE">Selected workspace</option><option value="other">Other workspace</option></select><script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};window.__settled=0;window.__hostile=0;async function api(path,options={}){try{const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw Object.assign(new Error('private_task_request'),{status:r.status});return await r.json()}finally{window.__settled++}}</script><script nonce="fixture" src="/admin/assets/workspace-remote-a2a-admin.js"></script></body></html>'''.replace('WORKSPACE', x.w.ws['id']).replace('TOKEN', json.dumps(raw))
    script = Path('agent_market/gateway/workspace-remote-a2a-admin.js').read_text()
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'admin.test': x.external.append(url.hostname); route.abort(); return
        if url.path == '/component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none';script-src 'nonce-fixture';style-src 'unsafe-inline' 'nonce-fixture';connect-src 'self';base-uri 'none'"}); return
        if url.path == '/admin/assets/workspace-remote-a2a-admin.js':
            route.fulfill(status=200, body=script, headers={'Content-Type': 'application/javascript'}); return
        (x.browser_reads if request.method == 'GET' else x.browser_writes).append({'path': url.path, 'body': request.post_data_json if request.method == 'POST' else None})
        response = x.client.request(request.method, url.path, headers=request.headers, content=request.post_data)
        result = {'status': response.status_code, 'body': response.content, 'headers': {k:v for k,v in response.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')}}
        if x.hold and request.method == 'POST': x.pending.append((route, result)); return
        route.fulfill(**result)
    context.route('**/*', serve)
    page.on('pageerror', lambda error: x.errors.append(str(error)))
    page.goto('https://admin.test/component')
    page.evaluate('(ws)=>WorkspaceRemoteA2AAdmin.open(ws)', x.w.ws['id'])
    expect(page.locator('#workspaceRemoteA2ADialog')).to_contain_text('Retained history loaded.')
    try: yield x
    finally: context.close()


def submit(x, text='Synthetic public task'):
    page = x.page
    page.locator('#remoteA2ABinding').select_option('0')
    page.locator('#remoteA2AText').fill(text)
    page.locator('#remoteA2ASendConsent').check()
    page.locator('#remoteA2ASendOnce').click()


def test_fresh_send_and_poll_authority_retains_task_and_text_only_result(task_page):
    x = task_page; page = x.page; dialog = page.locator('#workspaceRemoteA2ADialog')
    assert abs(dialog.bounding_box()['x'] + dialog.bounding_box()['width']/2 - 640) < 2
    assert not x.calls and not x.browser_writes
    expect(page.locator('#remoteA2ASendOnce')).to_be_disabled()
    page.locator('#remoteA2ABinding').select_option('0'); page.locator('#remoteA2AText').fill('First task')
    page.locator('#remoteA2ASendConsent').check(); page.locator('#remoteA2AText').fill('Changed task')
    expect(page.locator('#remoteA2ASendConsent')).not_to_be_checked()
    submit(x)
    expect(dialog).to_contain_text('One task submission was recorded.')
    assert len(x.calls) == 1 and x.calls[0]['method'] == 'message/send'
    assert re.fullmatch(r'rat_[a-f0-9]{32}', x.browser_writes[0]['body']['logical_id'])
    expect(page.locator('#remoteA2ASendConsent')).not_to_be_checked()
    expect(page.locator('#remoteA2AText')).to_have_value('')
    expect(page.locator('#remoteA2ApollOnce')).to_be_disabled()
    expect(page.locator('#remoteA2AcancelOnce')).to_be_disabled()
    x.control['state'] = 'completed'
    original = x.core.bindings[x.w.remote_rid].client.call
    hostile = '<img src=https://hostile.test/leak onerror="window.__hostile++"> retained result ' + 'x'*2200
    def output(*args, **kwargs):
        result = original(*args, **kwargs)
        result['artifacts'] = [{'parts': [{'kind': 'text', 'text': hostile}]}]
        return result
    x.core.bindings[x.w.remote_rid].client.call = output
    page.locator('#remoteA2ApollConsent').check(); page.locator('#remoteA2ApollOnce').click()
    expect(dialog).to_contain_text('One remote status request was recorded.')
    assert [call['method'] for call in x.calls] == ['message/send', 'tasks/get']
    expect(dialog).to_contain_text('This retained task is terminal.')
    page.get_by_role('button', name=re.compile('^Read retained task rtk_')).click()
    expect(dialog.get_by_label('Retained output preview')).to_contain_text('<img src=https://hostile.test/leak')
    expect(dialog).to_contain_text('The remote output was truncated.')
    assert len(x.calls) == 2 and page.evaluate('window.__hostile') == 0
    assert not dialog.locator('img').count() and not x.external and not x.errors
    assert 'task.example' not in dialog.inner_text() and 'remote-fixture-task' not in dialog.inner_text()


def test_cancel_requires_separate_fresh_authority_and_never_resubmits(task_page):
    x = task_page; page = x.page
    submit(x); expect(page.locator('#remoteA2ApollOnce')).to_be_disabled()
    page.locator('#remoteA2ApollConsent').check()
    expect(page.locator('#remoteA2AcancelOnce')).to_be_disabled()
    x.control['state'] = 'canceled'
    page.locator('#remoteA2AcancelConsent').check(); page.locator('#remoteA2AcancelOnce').click()
    expect(page.locator('#workspaceRemoteA2ADialog')).to_contain_text('One cancellation request was recorded.')
    assert [call['method'] for call in x.calls] == ['message/send', 'tasks/cancel']
    page.get_by_role('button', name='Read retained history', exact=True).click()
    expect(page.locator('#workspaceRemoteA2ADialog')).to_contain_text('Retained history loaded.')
    assert len(x.calls) == 2 and len(x.browser_writes) == 2
    assert not x.external and not x.errors


def test_unknown_boundary_history_and_reopen_do_not_replay(task_page):
    x = task_page; page = x.page; x.control['timeout'] = True
    submit(x)
    expect(page.locator('#workspaceRemoteA2ADialog')).to_contain_text('The external outcome is uncertain.')
    assert len(x.calls) == 1
    expect(page.locator('#remoteA2ApollConsent')).to_have_count(0)
    expect(page.locator('#remoteA2AcancelConsent')).to_have_count(0)
    page.get_by_role('button', name='Close', exact=True).click()
    page.evaluate('(ws)=>WorkspaceRemoteA2AAdmin.open(ws)', x.w.ws['id'])
    expect(page.locator('#workspaceRemoteA2ADialog')).to_contain_text('Retained history loaded.')
    page.get_by_role('button', name=re.compile('^Read retained task rtk_')).click()
    expect(page.locator('#workspaceRemoteA2ADialog')).to_contain_text('The external outcome is uncertain.')
    assert len(x.calls) == len(x.browser_writes) == 1 and not x.external and not x.errors


@pytest.mark.parametrize('change', ['workspace', 'session'])
def test_pending_response_cannot_restore_private_state_after_scope_change(task_page, change):
    x = task_page; page = x.page; x.hold = True
    submit(x)
    page.wait_for_function('()=>document.getElementById("remoteA2ASendOnce").disabled')
    assert len(x.pending) == 1 and len(x.calls) == 1
    if change == 'workspace': page.locator('#workspaceSelect').select_option('other')
    else: page.evaluate("token='';currentUser=null;WorkspaceRemoteA2AAdmin.onSession()")
    expect(page.locator('#workspaceRemoteA2ADialog')).to_have_count(0)
    for route, result in x.pending: route.fulfill(**result)
    page.wait_for_function('()=>window.__settled===3')
    expect(page.locator('#workspaceRemoteA2ADialog')).to_have_count(0)
    assert len(x.browser_reads) == 2 and len(x.browser_writes) == 1 and not x.external and not x.errors


def test_no_approved_binding_displays_unavailable_without_fake_target(task_page):
    x = task_page; page = x.page; x.core.bindings = {}
    page.get_by_role('button', name='Read retained history', exact=True).click()
    expect(page.locator('#workspaceRemoteA2ADialog')).to_contain_text('Remote A2A tasks are unavailable.')
    expect(page.locator('#remoteA2ABinding')).to_be_disabled()
    expect(page.locator('#remoteA2ABinding option')).to_have_count(1)
    expect(page.locator('#remoteA2ASendConsent')).not_to_be_checked()
    expect(page.locator('#remoteA2ASendOnce')).to_be_disabled()
    assert not x.calls and not x.browser_writes and not x.external and not x.errors


def test_dashboard_fixed_remote_asset_preserves_nonce_and_response_guards(private_api):
    w = private_api; page = w.client.get('/admin/ui')
    nonce = re.search(r"script-src 'nonce-([^']+)'", page.headers['content-security-policy']).group(1)
    assert f'<script nonce="{nonce}" src="/admin/assets/workspace-remote-a2a-admin.js"></script>' in page.text
    assert 'id="workspaceRemoteA2A"' in page.text
    response = w.client.get('/admin/assets/workspace-remote-a2a-admin.js')
    assert response.status_code == 200 and response.content == Path('agent_market/gateway/workspace-remote-a2a-admin.js').read_bytes()
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cross-origin-resource-policy'] == 'same-origin'
    assert w.client.get('/admin/assets/workspace_remote_a2a.py').status_code == 404

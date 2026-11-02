"""Downloaded ZIP and generated HTML show bounded, accessible execution feedback."""
import json
from types import SimpleNamespace
from urllib.parse import urlsplit
from zipfile import ZipFile

import pytest

from agent_market.workflow_webapp import GATEWAY, SOURCE, build_package
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright=pytest.importorskip('playwright.sync_api')
ROOT='https://downloaded.example/apps/workflow/'
RUN_ID='wr_'+'a'*32
RUN_KEY='private-capability-fixture-'+'k'*24


@pytest.fixture(params=['zip','generated-html'])
def downloaded_app(browser,tmp_path,request):
    config={'workflow_id':42,'title':'Recorded workflow','description':'Review recorded results.','api_origin':GATEWAY}
    archive,_=build_package(config)
    state=SimpleNamespace(files={},starts=[],cancels=[],held=[],hold_start=True,hold_cancel=False,
                          status='running',start_error=None,errors=[],external=[])
    context=browser.new_context(accept_downloads=True);page=context.new_page();state.page=page
    def reply(route,value,status=200):
        state.held=[held for held in state.held if held is not route]
        route.fulfill(status=status,content_type='application/json',body=json.dumps(value),
            headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'content-type,x-workflow-key','Access-Control-Allow-Methods':'GET,POST,OPTIONS'})
    state.reply=reply
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname=='builder.example':
            if url.path=='/package.zip':
                return route.fulfill(body=archive,headers={'Content-Type':'application/zip','Content-Disposition':'attachment; filename="workflow.zip"'})
            return route.fulfill(content_type='text/html',body='<html><body><a id="zip" href="/package.zip">Download</a></body></html>')
        if req.url.startswith(ROOT):
            name=req.url.removeprefix(ROOT)or'index.html';body=state.files.get(name)
            if body is None:return route.fulfill(status=404,body='Missing fixture file')
            mime='application/javascript'if name.endswith('.js')else'text/css'if name.endswith('.css')else'text/html'
            return route.fulfill(content_type=mime,body=body)
        if url.hostname!='agentconcierge.biz':
            state.external.append(url.hostname);return route.abort()
        if req.method=='OPTIONS':return reply(route,{},204)
        if url.path=='/api/workflows/run'and req.method=='POST':
            state.starts.append(route)
            if state.hold_start:state.held.append(route);return
            return reply(route,{'detail':'Private provider diagnostic'},500)if state.start_error else reply(route,{'run_id':RUN_ID,'run_key':RUN_KEY,'status':'queued'})
        if url.path==f'/api/workflows/runs/{RUN_ID}/cancel'and req.method=='POST':
            state.cancels.append(route)
            if state.hold_cancel:state.held.append(route);return
            state.status='cancelled';return reply(route,{'cancel_requested':True})
        if url.path==f'/api/workflows/runs/{RUN_ID}'and req.method=='GET':
            return reply(route,{'status':state.status,'node_results':[{'name':'Recorded step','status':state.status,'output':'Source-backed fixture result'}]})
        pytest.fail('Unexpected workflow request in the isolated download fixture')
    context.route('**/*',serve);page.on('pageerror',lambda error:state.errors.append(str(error)))
    page.goto('https://builder.example/')
    if request.param=='zip':
        with page.expect_download()as event:page.locator('#zip').click()
        path=tmp_path/'workflow.zip';event.value.save_as(path)
        with ZipFile(path)as package:state.files={name:package.read(name)for name in package.namelist()}
    else:
        page.evaluate(SOURCE.read_text())
        with page.expect_download()as event:
            page.evaluate('''config=>{
                const blob=new Blob([buildWorkflowAppHTML(config)],{type:'text/html'});
                const address=URL.createObjectURL(blob),anchor=document.createElement('a');
                anchor.href=address;anchor.download='workflow.html';anchor.click();
                setTimeout(()=>URL.revokeObjectURL(address),0);
            }''',config)
        path=tmp_path/'workflow.html';event.value.save_as(path);state.files={'index.html':path.read_bytes()}
    page.goto(ROOT);playwright.expect(page.locator('#appStatus')).to_have_text('Ready')
    try:yield state
    finally:
        for route in state.held:route.abort()
        page.wait_for_timeout(0)
        context.close()


def started(state):
    state.page.wait_for_function("() => document.querySelector('#runAppBtn').getAttribute('aria-busy') === 'true'")
    assert state.page.locator('#runAppBtn').is_disabled()
    playwright.expect(state.page.locator('[data-run-label]')).to_have_text('Running...')
    assert state.page.locator('[data-run-spinner]').is_visible()
    assert not state.page.locator('[data-run-ready]').is_visible()


def idle(state):
    playwright.expect(state.page.locator('#runAppBtn')).to_be_enabled()
    playwright.expect(state.page.locator('#runAppBtn')).to_have_attribute('aria-busy','false')
    playwright.expect(state.page.locator('[data-run-label]')).to_have_text('Run workflow')
    assert not state.page.locator('[data-run-spinner]').is_visible()
    assert state.page.locator('[data-run-ready]').is_visible()
    assert state.page.locator('#cancelAppBtn').is_disabled()
    assert RUN_KEY not in state.page.content()
    assert not state.errors and not state.external


def release_start(state):
    state.page.wait_for_function('() => document.querySelector("#appStatus").textContent === "Starting workflow..."')
    state.page.wait_for_timeout(20)
    assert len(state.starts)==1
    state.reply(state.starts[0],{'run_id':RUN_ID,'run_key':RUN_KEY,'status':'queued'})
    playwright.expect(state.page.locator('#cancelAppBtn')).to_be_enabled()


@pytest.mark.parametrize('terminal',['succeeded','failed','cancelled'])
def test_execution_stays_busy_until_terminal_and_double_dispatch_is_refused(downloaded_app,terminal):
    state=downloaded_app;page=state.page
    page.evaluate("() => { const button=document.querySelector('#runAppBtn'); void button.onclick(); void button.onclick(); }")
    started(state);release_start(state)
    started(state);state.status=terminal
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: '+terminal)
    idle(state)
    assert len(state.starts)==1


def test_start_failure_recovers_without_retries_or_private_diagnostics(downloaded_app):
    state=downloaded_app;state.hold_start=False;state.start_error=True
    state.page.locator('#runAppBtn').click()
    playwright.expect(state.page.locator('#appStatus')).to_have_text('The workflow request could not be completed.')
    idle(state)
    assert len(state.starts)==1 and 'Private provider diagnostic'not in state.page.content()


def test_request_timeout_restores_run_control(downloaded_app):
    state=downloaded_app;page=state.page;page.clock.install()
    page.locator('#runAppBtn').click();started(state)
    page.wait_for_timeout(20)
    page.clock.fast_forward(10001)
    idle(state)
    assert len(state.starts)==1


def test_stop_is_single_flight_and_run_restores_only_after_cancelled(downloaded_app):
    state=downloaded_app;page=state.page;state.hold_cancel=True
    page.locator('#runAppBtn').click();started(state);release_start(state)
    page.evaluate("() => { const button=document.querySelector('#cancelAppBtn'); void button.onclick(); void button.onclick(); }")
    page.wait_for_timeout(20)
    assert len(state.cancels)==1 and page.locator('#cancelAppBtn').is_disabled()
    started(state)
    state.reply(state.cancels[0],{'cancel_requested':True});state.status='cancelled'
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: cancelled')
    idle(state)


def test_late_cancellation_cannot_overwrite_the_next_run(downloaded_app):
    state=downloaded_app;page=state.page;state.hold_cancel=True
    page.locator('#runAppBtn').click();release_start(state)
    page.locator('#cancelAppBtn').click();page.wait_for_timeout(20)
    assert len(state.cancels)==1
    state.status='succeeded'
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded');idle(state)
    page.locator('#runAppBtn').click();started(state)
    state.reply(state.cancels[0],{'cancel_requested':True})
    page.wait_for_timeout(20)
    playwright.expect(page.locator('#appStatus')).to_have_text('Starting workflow...')
    assert len(state.starts)==2


@pytest.mark.parametrize('theme',['light','dark'])
def test_reduced_motion_keeps_clear_running_feedback_in_both_themes(downloaded_app,theme):
    state=downloaded_app;page=state.page;page.emulate_media(color_scheme=theme,reduced_motion='reduce')
    page.locator('#runAppBtn').click();started(state)
    assert page.locator('[data-run-spinner]').evaluate('element => getComputedStyle(element).animationName')=='none'
    assert page.locator('[data-run-spinner]').get_attribute('aria-hidden')=='true'
    assert page.locator('#appStatus').get_attribute('aria-live')=='polite'

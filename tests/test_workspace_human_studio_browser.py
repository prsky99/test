"""Task-based user journeys; real reviewed APIs, synthetic accounts/providers."""
# ruff: noqa: F401,F811
from pathlib import Path
from urllib.parse import urlsplit
import json
import httpx
import pytest
from playwright.sync_api import expect
from agent_market.customer_identity_service import COOKIE
from agent_market.workspace_app_factory import AppFactory
from agent_market.workflow_model_proposer import OllamaGraphProposer
from tests.test_customer_template_hub import hub_world, customer_flow, typed_release_world, typed_world, routing
from tests.test_front_workflow_browser import browser


def launch(x,browser,width=1440,real_model=False):
    calls=[]
    def model(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,headers={'content-type':'application/json'},json={'done':True,'message':{'role':'assistant','content':'{"query":"Python"}'}})
    if real_model:
        from scripts.agentcon_config import read_local_model_settings
        settings=read_local_model_settings('gateway-data/local-model.env')
        client=httpx.Client(trust_env=False,event_hooks={'request':[lambda r:calls.append(json.loads(r.content))]})
        proposer=OllamaGraphProposer(settings['WORKSPACE_MODEL_URL'],settings['WORKSPACE_MODEL_NAME'],client,provider='openai',allow_http=True)
    else:
        client=httpx.Client(transport=httpx.MockTransport(model))
        proposer=OllamaGraphProposer('http://127.0.0.1:11434','synthetic-model',client)
    x.core.factory.model_source=AppFactory(x.w.core,model_proposer=proposer)
    context=browser.new_context(offline=True,viewport={'width':width,'height':844 if width<600 else 1000},accept_downloads=True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];requests=[]
    page.on('pageerror',lambda e:errors.append(e.stack))
    def serve(route):
        r=route.request;u=urlsplit(r.url)
        if u.hostname!='customer.test':errors.append('Unexpected destination');return route.abort()
        requests.append((r.method,u.path))
        response=x.client.request(r.method,u.path,headers=r.headers,content=r.post_data,follow_redirects=False)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
    page.wait_for_timeout(200)
    assert not errors,errors
    expect(page.locator('#human-nav-create')).to_be_enabled()
    return context,page,errors,requests,calls,client


@pytest.mark.parametrize('width',[390,1440])
def test_first_screen_is_one_clear_task_and_navigation_preserves_it(hub_world,browser,width):
    x,*_=hub_world;before=len(x.w.calls);context,page,errors,requests,calls,client=launch(x,browser,width)
    try:
        expect(page.get_by_role('heading',name='What would you like to do?',exact=True)).to_be_visible()
        expect(page.locator('#model')).to_be_visible()
        assert page.locator('#model').evaluate('(b)=>b.getBoundingClientRect().bottom<=innerHeight')
        expect(page.locator('#human-builder')).to_be_hidden()
        expect(page.locator('#template-hub')).to_be_hidden()
        assert not page.locator('pre:visible').count()
        assert len(x.w.calls)==before and not calls
        page.locator('#objective').fill('My unfinished idea')
        page.locator('#human-nav-templates').click()
        expect(page.locator('#human-templates')).to_be_visible()
        page.locator('#human-nav-create').click()
        expect(page.locator('#objective')).to_have_value('My unfinished idea')
        page.locator('#human-nav-library').click()
        expect(page.locator('#human-library-empty')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),page.evaluate('''()=>[...document.querySelectorAll('body *')].filter(n=>n.getClientRects().length&&n.getBoundingClientRect().right>innerWidth+1).map(n=>({tag:n.tagName,id:n.id,classes:n.className,right:n.getBoundingClientRect().right})).slice(0,15)''')
        assert not [r for r in requests if r[0]=='POST'] and not errors
        dest=Path('reports/workspace-human-centered-2026-10-25');dest.mkdir(parents=True,exist_ok=True)
        page.locator('#human-nav-create').click();page.screenshot(path=str(dest/('create-'+str(width)+'.png')),full_page=True)
    finally:context.close();client.close()


def approve(page,label):
    expect(page.locator('#human-confirm')).to_be_visible()
    expect(page.locator('#human-confirm-yes')).to_be_disabled()
    page.locator('#human-confirm-check').check()
    page.locator('#human-confirm-yes').click()


def test_ai_to_review_single_credit_confirmation_and_real_test(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        before=len(x.w.calls)
        page.locator('#objective').fill('Find Python documentation in exactly two connected steps.')
        page.locator('#model-consent').check();page.locator('#model').click()
        expect(page.locator('#human-builder')).to_be_visible()
        expect(page.locator('#human-save')).to_be_enabled()
        assert len(calls)==1 and len(x.w.calls)==before
        assert not page.locator('pre:visible').count()
        page.locator('#human-save').click();approve(page,'save')
        expect(page.locator('#human-try')).to_be_enabled()
        assert len(x.w.calls)==before
        page.locator('#human-try').click();approve(page,'run')
        expect(page.locator('#results')).to_contain_text('Current documentation',timeout=20000)
        expect(page.locator('#human-download')).to_be_enabled()
        assert len(x.w.calls)==before+2
        assert not errors,errors
        page.screenshot(path='reports/workspace-human-centered-2026-10-25/ai-results.png',full_page=True)
    finally:context.close();client.close()


def test_template_edit_single_confirmation_run_results_and_download(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        page.locator('#human-nav-templates').click()
        page.locator('#hub-cards').get_by_role('button',name='Use or customize template').click()
        expect(page.locator('#human-template-builder')).to_be_visible()
        page.locator('#hub-field-query').fill('solar energy')
        page.locator('#hub-review').click();approve(page,'save')
        expect(page.locator('#human-template-try')).to_be_enabled()
        page.locator('#human-template-try').click();approve(page,'run')
        expect(page.locator('#hub-results')).to_contain_text('Current documentation',timeout=20000)
        with page.expect_download() as downloaded:page.locator('#hub-download').click()
        assert downloaded.value.suggested_filename=='my-workflow.zip'
        assert not errors,errors
        page.locator('#human-nav-library').click()
        expect(page.locator('#human-template-cards')).to_contain_text('Documentation Search')
        page.screenshot(path='reports/workspace-human-centered-2026-10-25/library.png',full_page=True)
    finally:context.close();client.close()


def generate_python(page):
    page.locator('#objective').fill('Find Python documentation in exactly two connected steps.')
    page.locator('#model-consent').check();page.locator('#model').click()
    expect(page.locator('#human-save')).to_be_enabled()


def test_cancel_save_never_spends_and_each_run_needs_fresh_permission(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        generate_python(page);count=len(requests)
        page.locator('#human-save').click();page.locator('#human-confirm').get_by_role('button',name='Cancel',exact=True).click()
        assert not [p for m,p in requests[count:] if m=='POST' and p.endswith('/commits')]
        page.locator('#human-save').click();approve(page,'save')
        expect(page.locator('#human-try')).to_be_enabled();count=len(x.w.calls)
        page.locator('#human-try').click()
        expect(page.locator('#human-confirm-check')).not_to_be_checked()
        page.locator('#human-confirm').get_by_role('button',name='Cancel',exact=True).click()
        assert len(x.w.calls)==count
        page.locator('#human-try').click();approve(page,'run')
        expect(page.locator('#results')).to_contain_text('Current documentation')
        page.locator('#human-try').click();expect(page.locator('#human-confirm-check')).not_to_be_checked()
        page.keyboard.press('Escape');assert not errors,errors
    finally:context.close();client.close()


def test_slow_generation_has_immediate_feedback_and_no_second_request(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    held=[]
    def hold(route):held.append(route)
    page.route('**/typed/reviews/model',hold)
    try:
        page.locator('#objective').fill('Find Python documentation using two steps.')
        page.locator('#model-consent').check();page.locator('#model').click()
        expect(page.locator('#model')).to_contain_text('Creating your workflow')
        expect(page.locator('#model')).to_be_disabled()
        expect(page.locator('#human-nav-templates')).to_be_disabled()
        page.wait_for_timeout(150)
        assert len(held)==1
        route=held.pop();request=route.request
        response=x.client.post(urlsplit(request.url).path,headers=request.headers,content=request.post_data)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('set-cookie','content-length','content-encoding')})
        expect(page.locator('#human-save')).to_be_enabled();assert len(calls)==1 and not errors
    finally:context.close();client.close()


@pytest.mark.parametrize('role',['viewer','runner'])
def test_roles_explain_edit_limits_without_offering_unusable_actions(hub_world,browser,role):
    from tests.test_customer_typed_authoring import save_run
    x,*_=hub_world;save_run(x)
    with x.s.identity.tx() as db:db.execute('UPDATE customer_workspace_links SET role=?,revision=revision+1 WHERE workspace_id=?',(role,x.ws))
    context,page,errors,requests,calls,client=launch(x,browser)
    try:
        expect(page.locator('#model')).to_be_disabled()
        expect(page.locator('#model-availability')).to_contain_text('Editing access')
        page.locator('#human-nav-library').click();page.locator('#workflow-cards .workflow-card').first.click()
        expect(page.locator('#human-builder')).to_be_visible()
        expect(page.locator('#name')).to_be_disabled()
        expect(page.locator('#human-download')).to_be_hidden()
        if role=='viewer':expect(page.locator('#human-try')).to_be_disabled()
        else:expect(page.locator('#human-try')).to_be_enabled()
        assert not errors and not calls
    finally:context.close();client.close()


def test_withdrawn_template_keeps_saved_inputs_readable_without_execution(hub_world,browser):
    from tests.test_customer_template_hub import proposed,saved
    x,rt,wf,_=hub_world;saved(x,proposed(x,wf))
    rt.fallback.set_control({'enabled':False,'revision':rt.fallback.control()['revision']},0)
    context,page,errors,requests,calls,client=launch(x,browser)
    try:
        before=len(x.w.calls);page.locator('#human-nav-library').click();page.locator('#human-template-cards button').first.click()
        expect(page.locator('#human-unavailable')).to_be_visible()
        expect(page.locator('#human-unavailable')).to_contain_text('solar energy')
        expect(page.locator('#human-unavailable')).to_contain_text('fresh verification')
        expect(page.locator('#human-template-builder')).to_be_hidden()
        assert len(x.w.calls)==before and not errors
    finally:context.close();client.close()


@pytest.mark.parametrize('theme',['light','dark'])
def test_mobile_drawer_keyboard_targets_and_no_overlap(hub_world,browser,theme):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser,390)
    try:
        if theme=='dark':page.locator('#workspace-theme').click()
        for width in (320,390,600,760):
            page.set_viewport_size({'width':width,'height':844});page.locator('#workspace-menu').click()
            expect(page.locator('#workspace-menu')).to_have_attribute('aria-expanded','true')
            expect(page.locator('#workspace-main')).to_have_attribute('inert','')
            if not page.locator('.workspace-manage').evaluate('(n)=>n.open'):page.locator('.workspace-manage > summary').click()
            for link in page.locator('#workspace-navigation a').all():
                expect(link).to_be_visible();assert link.evaluate('(n)=>{const b=n.getBoundingClientRect();return b.width>=40&&b.height>=40&&b.right<=innerWidth}')
            page.keyboard.press('Escape');expect(page.locator('#workspace-menu')).to_be_focused()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            boxes=[n.bounding_box() for n in page.locator('.workspace-topbar button:visible,.workspace-topbar .workspace-brand').all()]
            boxes=sorted(boxes,key=lambda b:b['x'])
            assert all(a['x']+a['width']<=b['x']+1 for a,b in zip(boxes,boxes[1:]))
        assert not errors
    finally:context.close();client.close()


def test_download_is_one_explicit_scoped_authorization_and_zip_action(hub_world,browser):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser)
    try:
        generate_python(page);page.locator('#human-save').click();approve(page,'save')
        expect(page.locator('#human-try')).to_be_enabled();page.locator('#human-try').click();approve(page,'run')
        expect(page.locator('#human-download')).to_be_enabled();page.locator('#human-download').click()
        page.locator('#origin').fill('https://my-workflow.example')
        page.get_by_role('button',name='Prepare download',exact=True).click()
        expect(page.locator('#human-confirm-copy')).to_contain_text('one hour')
        approve(page,'authorize')
        expect(page.locator('#download button')).to_be_enabled()
        with page.expect_download() as downloaded:page.locator('#download button').click()
        assert downloaded.value.suggested_filename=='agent-concierge-workflow.zip'
        assert len([p for m,p in requests if m=='POST' and p.endswith('/deployments')])==1
        assert not errors,errors
    finally:context.close();client.close()


def test_manual_input_selector_connects_prior_result_without_editing_json(hub_world,browser):
    x,*_=hub_world;queries=[];original=x.w.remote.handle_request
    def capture(request):
        body=json.loads(request.content) if request.content else {}
        if body.get('method')=='tools/call':queries.append(body['params']['arguments']['query'])
        return original(request)
    x.w.remote.handle_request=capture
    context,page,errors,requests,calls,client=launch(x,browser)
    try:
        page.locator('#human-manual').click()
        expect(page.locator('#step-editor')).to_be_visible()
        page.locator('[data-role=query]').first.fill('public battery recycling research')
        second=page.locator('[data-human-source]').nth(1)
        expect(second).to_have_value('step_1')
        second.select_option('')
        page.locator('[data-role=query]').nth(1).fill('independent energy research')
        second.select_option('step_1')
        bindings=json.loads(page.locator('[data-field=bindings]').nth(1).input_value())
        assert bindings=={'query':{'node_id':'step_1','path':['items',0,'title']}}
        assert not page.locator('pre:visible').count() and not calls
        page.locator('#human-review').click()
        expect(page.locator('#human-save')).to_be_enabled()
        page.screenshot(path='reports/workspace-human-centered-2026-10-25/manual-review.png',full_page=True)
        page.locator('#human-save').click();approve(page,'save')
        expect(page.locator('#human-try')).to_be_enabled()
        queries.clear();page.locator('#human-try').click();approve(page,'run')
        expect(page.locator('#results')).to_contain_text('All steps completed',timeout=20000)
        assert queries==['public battery recycling research','Current documentation']
        assert not errors and not calls
    finally:context.close();client.close()

"""Prelaunch Workspace journeys against real handlers and disposable identities."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from agent_market.customer_identity_service import COOKIE
from agent_market.workspace_release import DEPLOY_NOTICE
from tests.test_customer_typed_authoring import customer_flow, save_run  # noqa: F401
from tests.test_workspace_typed_release import typed_release_world  # noqa: F401
from tests.test_workspace_typed_flows import typed_world, routing  # noqa: F401
from tests.test_front_workflow_browser import browser
from tests.human_workspace_helpers import manual,load_first,edit_steps,library,confirm,new_idea  # noqa: F401

EVIDENCE = Path('reports/workspace-human-centered-2026-10-25')


def open_studio(x, browser, *, role=None, fail_session=False):
    if role:
        with x.s.identity.tx() as db:
            db.execute('UPDATE customer_workspace_links SET role=?,revision=revision+1 WHERE workspace_id=?', (role,x.ws))
    context=browser.new_context(viewport={'width':1440,'height':1000},color_scheme='light',offline=True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];requests=[];fail=[fail_session]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def forward(route):
        r=route.request;u=urlsplit(r.url)
        assert u.hostname=='customer.test'
        requests.append((r.method,u.path))
        # Retry a transient outage; 401 concealment has separate privacy regressions.
        if fail[0] and u.path=='/api/customer-auth/session':
            fail[0]=False;route.fulfill(status=503,content_type='application/json',body='{}');return
        response=x.client.request(r.method,u.path+('?' + u.query if u.query else ''),headers=r.headers,content=r.post_data,follow_redirects=False)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',forward)
    page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
    return context,page,errors,requests


def ready(page):
    expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')


def test_saved_graph_dirty_guard_discard_and_download_survive_reload(customer_flow,browser):
    x=customer_flow;flow,run=save_run(x)
    release=x.core.typed_releases.create(x.ws,flow['id'],flow['version_id'],{'run_id':run['id'],'ttl_seconds':600},x.actor)
    app=x.core.typed_releases.deploy(x.ws,flow['id'],flow['version_id'],release['id'],{'allowed_origins':['https://app.example'],'ttl_seconds':600,'minute_limit':5,'day_limit':20,'authorized':True,'notice':DEPLOY_NOTICE},x.actor)
    before=len(x.w.calls);context,page,errors,requests=open_studio(x,browser)
    try:
        ready(page);load_first(page)
        expect(page.locator('#name')).to_have_value(flow['name'])
        expect(page.locator('#results article')).to_have_count(2)
        expect(page.locator('#download button')).to_have_count(1)
        expect(page.locator('#prepare')).to_be_enabled()
        page.locator('#human-download').click()
        with page.expect_download() as download:
            page.locator('#download button').click()
        assert Path(download.value.path()).read_bytes().startswith(b'PK')
        expect(page.locator('#status')).to_have_text('Download requested. Check your browser downloads.')
        edit_steps(page)
        page.locator('#name').fill('Unsaved alternative')
        expect(page.locator('#prepare')).to_be_disabled()
        expect(page.locator('#download button')).to_have_count(0)
        expect(page.locator('#workflow-state')).to_contain_text('Unsaved proposal')
        load_first(page);expect(page.locator('#discard-dialog')).to_be_visible()
        page.get_by_role('button',name='Keep editing').click()
        expect(page.locator('#name')).to_have_value('Unsaved alternative')
        new_idea(page);page.get_by_role('button',name='Discard unsaved proposal').click()
        expect(page.locator('#name')).to_have_value('My workflow')
        expect(page.locator('#prepare')).to_be_disabled()
        load_first(page)
        expect(page.locator('#discard-dialog')).to_be_visible()
        page.get_by_role('button',name='Discard unsaved proposal').click()
        expect(page.locator('#name')).to_have_value(flow['name'])
        expect(page.locator('#download button')).to_have_count(1)
        page.screenshot(path=str(EVIDENCE/'studio-loaded-light.png'),full_page=True)
        page.locator('#workspace-theme').click()
        expect(page.locator('body')).to_have_attribute('data-theme','dark')
        page.screenshot(path=str(EVIDENCE/'studio-loaded-dark.png'))
        page.set_viewport_size({'width':390,'height':844})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(EVIDENCE/'studio-mobile.png'))
        page.reload();ready(page);load_first(page)
        expect(page.locator('#download button')).to_have_count(1)
        assert len(x.w.calls)==before and not errors
        endpoint=x.base+'/typed/flows/'+flow['id']+'/versions/'+flow['version_id']+'/releases/'+release['id']+'/deployments'
        assert x.client.get(endpoint).json()['deployments'][0]['app_id']==app['app_id']
        assert x.client.get(endpoint.replace(x.ws,'ws_'+'0'*32)).status_code==403
        assert x.client.get(endpoint,headers={'Origin':'https://evil.invalid'}).status_code==403
    finally:context.close()


@pytest.mark.parametrize('role',['viewer','runner','editor'])
def test_role_specific_studio_controls_and_no_implicit_provider_call(customer_flow,browser,role):
    x=customer_flow;save_run(x);before=len(x.w.calls)
    context,page,errors,requests=open_studio(x,browser,role=role)
    try:
        ready(page);load_first(page)
        if role=='viewer':expect(page.locator('#prepare')).to_be_disabled()
        else:expect(page.locator('#prepare')).to_be_enabled()
        if role!='editor':
            expect(page.locator('#name')).to_be_disabled()
            expect(page.locator('#new-flow')).to_be_disabled()
        expect(page.locator('#release')).to_be_disabled()
        expect(page.locator('#deploy')).to_be_disabled()
        assert len(x.w.calls)==before and not errors
    finally:context.close()


def test_retry_optional_failure_and_invalid_manual_json_keep_editor_usable(customer_flow,browser):
    x=customer_flow;context,page,errors,requests=open_studio(x,browser,fail_session=True)
    try:
        expect(page.locator('#retry-load')).to_be_visible()
        expect(page.locator('#signin')).to_be_hidden()
        expect(page.locator('#prepare')).to_be_disabled()
        page.locator('#retry-load').click();ready(page)
        assert not any('/task-outcomes' in path or '/a2a/' in path for _,path in requests)
        page.route('**/task-outcomes',lambda route:route.fulfill(status=503,content_type='application/json',body='{}'))
        library(page)
        page.locator('#feedback-panel > summary').click()
        expect(page.locator('#outcomes')).to_contain_text('optional feature is unavailable')
        manual(page)
        expect(page.locator('#review')).to_be_enabled()
        page.locator('#name').fill('Public research test')
        page.locator('.step-advanced').evaluate_all('ds=>ds.forEach(d=>d.open=true)')
        page.locator('[data-role=query]').first.fill('public research')
        page.locator('[data-field=input]').first.fill('{invalid')
        page.locator('#human-review').click()
        expect(page.locator('#status')).to_contain_text('Check your inputs')
        expect(page.locator('#review')).to_be_enabled()
        assert not x.core.typed.listing(x.ws,x.actor) and not errors
        assert not any(method=='POST' and path.endswith('/runs') for method,path in requests)
    finally:context.close()


@pytest.mark.parametrize('status',[409,503])
def test_ambiguous_run_requires_graph_history_and_optional_a2a_cannot_unlock_it(customer_flow,browser,status):
    x=customer_flow;save_run(x);before=len(x.w.calls)
    context,page,errors,requests=open_studio(x,browser)
    try:
        ready(page);load_first(page);page.locator('#human-try').click()
        expect(page.locator('#run-consent')).not_to_be_checked()
        page.route('**/typed/flows/*/runs',lambda route:route.fulfill(status=status,content_type='application/json',body='{}'),times=1)
        confirm(page)
        expect(page.locator('#prepare')).to_be_disabled()
        library(page)
        page.locator('#a2a-panel > summary').click()
        expect(page.locator('#a2a-status')).to_contain_text('No approved A2A')
        expect(page.locator('#prepare')).to_be_disabled()
        page.go_back()
        page.route('**/typed/flows/*/runs',lambda route:route.fulfill(status=503,content_type='application/json',body='{}'),times=1)
        page.locator('#human-refresh').click()
        expect(page.locator('#status')).to_contain_text('could not be confirmed')
        expect(page.locator('#prepare')).to_be_disabled()
        page.locator('#human-refresh').click()
        expect(page.locator('#prepare')).to_be_enabled()
        assert len(x.w.calls)==before and not errors
    finally:context.close()


def test_stage_keyboard_navigation_and_unsaved_signout_require_review(customer_flow,browser):
    x=customer_flow;context,page,errors,requests=open_studio(x,browser)
    try:
        ready(page)
        page.locator('#human-nav-create').focus();page.keyboard.press('Tab')
        expect(page.locator('#human-nav-templates')).to_be_focused();page.keyboard.press('Enter')
        expect(page.locator('#human-templates')).to_be_visible()
        page.locator('#human-nav-create').click()
        page.locator('#objective').fill('Find public research in three steps.')
        page.locator('#workspace-signout').click()
        expect(page.locator('#discard-dialog')).to_be_visible()
        page.get_by_role('button',name='Keep editing').click()
        expect(page.locator('#objective')).to_have_value('Find public research in three steps.')
        assert not any(method=='POST' and path.endswith('/logout') for method,path in requests)
        assert not errors
    finally:context.close()


def test_failed_download_retains_release_and_explicit_retry_does_not_run_or_debit(customer_flow,browser):
    x=customer_flow;flow,run=save_run(x)
    release=x.core.typed_releases.create(x.ws,flow['id'],flow['version_id'],{'run_id':run['id'],'ttl_seconds':600},x.actor)
    x.core.typed_releases.deploy(x.ws,flow['id'],flow['version_id'],release['id'],{'allowed_origins':['https://app.example'],'ttl_seconds':600,'minute_limit':5,'day_limit':20,'authorized':True,'notice':DEPLOY_NOTICE},x.actor)
    initial=x.core.credits.status(x.s.customer)['balance'];before=len(x.w.calls)
    context,page,errors,requests=open_studio(x,browser)
    try:
        ready(page);load_first(page);page.locator('#human-download').click()
        page.route('**/deployments/*/package',lambda route:route.fulfill(status=503,content_type='application/json',body='{}'),times=1)
        page.locator('#download button').click()
        expect(page.locator('#status')).to_contain_text('No workflow was rerun.')
        expect(page.locator('#download button')).to_be_enabled()
        assert sum(path.endswith('/package') for _,path in requests)==0
        assert x.core.credits.status(x.s.customer)['balance']==initial
        page.locator('#human-refresh').click()
        expect(page.locator('#status')).to_have_text('Your reviewed action is complete.')
        page.locator('#human-download').click()
        with page.expect_download() as event:page.locator('#download button').click()
        assert Path(event.value.path()).read_bytes().startswith(b'PK')
        expect(page.locator('#status')).to_have_text('Download requested. Check your browser downloads.')
        assert x.core.credits.status(x.s.customer)['balance']==initial
        assert len(x.w.calls)==before and not errors
    finally:context.close()


@pytest.mark.parametrize('stored,scheme,expected',[('dark','light','dark'),('light','dark','light'),('invalid','dark','dark')])
def test_public_theme_switch_parity_keyboard_persistence_and_small_header(customer_flow,browser,stored,scheme,expected):
    x=customer_flow;context,page,errors,requests=open_studio(x,browser)
    try:
        ready(page)
        context.add_init_script("if(!sessionStorage.getItem('test-theme-initialized')){sessionStorage.setItem('pearl-preview:theme',"+repr(stored)+");localStorage.removeItem('pearl-theme');sessionStorage.setItem('test-theme-initialized','1')}")
        page.emulate_media(color_scheme=scheme)
        page.reload();ready(page)
        toggle=page.locator('#workspace-theme')
        expect(toggle).to_have_attribute('class','theme-toggle')
        expect(toggle).to_have_attribute('aria-label','Toggle dark theme')
        expect(page.locator('body')).to_have_attribute('data-theme',expected)
        geometry=toggle.evaluate("e=>({width:e.offsetWidth,height:e.offsetHeight,radius:getComputedStyle(e).borderRadius,knob:getComputedStyle(e,'::before').left})")
        assert geometry=={'width':44,'height':30,'radius':'30px','knob':'18px' if expected=='dark' else '4px'}
        contrast=page.locator('.human-local-nav [aria-current=page]').evaluate("""e=>{const style=getComputedStyle(e),luminance=color=>{const rgb=color.match(/[0-9.]+/g).slice(0,3).map(Number).map(x=>{x/=255;return x<=.04045?x/12.92:Math.pow((x+.055)/1.055,2.4)});return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]},a=luminance(style.color),b=luminance(style.backgroundColor);return(Math.max(a,b)+.05)/(Math.min(a,b)+.05)}""")
        assert contrast>=4.5
        toggle.focus();page.keyboard.press('Space')
        changed='light' if expected=='dark' else 'dark'
        expect(toggle).to_have_attribute('aria-pressed',str(changed=='dark').lower())
        assert page.evaluate("sessionStorage.getItem('pearl-preview:theme')")==changed
        page.goto('https://customer.test/customer/plan?workspace='+x.ws)
        expect(page.locator('body')).to_have_attribute('data-theme',changed)
        page.locator('#workspace-theme').press('Enter')
        expect(page.locator('body')).to_have_attribute('data-theme',expected)
        for width in (1440,390,320):
            page.set_viewport_size({'width':width,'height':900})
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert page.locator('#workspace-theme').is_visible()
        assert not errors
    finally:context.close()


def test_unavailable_verified_agent_disables_ai_without_losing_draft_or_credits(customer_flow,browser):
    from agent_market.workspace_app_factory import AppFactory
    x=customer_flow;x.core.factory.model_source=AppFactory(x.w.core,model_proposer=lambda envelope:{})
    flow,_=save_run(x);initial=x.core.credits.status(x.s.customer)['balance']
    context,page,errors,requests=open_studio(x,browser)
    try:
        ready(page)
        page.locator('#objective').fill('Find public energy storage research.')
        page.locator('#model-consent').check();expect(page.locator('#model')).to_be_enabled()
        # Revoke only the disposable connection approvals while the tab stays open.
        with x.w.store.tx() as db:db.execute('DELETE FROM capability_approvals')
        page.locator('#human-check-availability').click()
        expect(page.locator('#model-availability')).to_contain_text('AI is unavailable.')
        expect(page.locator('#model-availability')).to_contain_text('template')
        expect(page.locator('#model')).to_be_disabled()
        expect(page.locator('#objective')).to_have_value('Find public energy storage research.')
        assert x.core.credits.status(x.s.customer)['balance']==initial
        assert not errors
    finally:context.close()


def test_credit_agreement_form_waits_for_confirmed_terms_and_account_state(customer_flow,browser):
    x=customer_flow;context,page,errors,requests=open_studio(x,browser);held=[]
    try:
        ready(page)
        page.route('**/api/customer-credits',lambda route:held.append(route))
        with page.expect_request('**/api/customer-credits'):
            page.goto('https://customer.test/customer/plan?workspace='+x.ws)
        expect(page.locator('#status')).to_have_text('Checking your current plan.')
        expect(page.locator('#enroll')).to_be_hidden()
        expect(page.locator('#join')).to_be_disabled()
        expect(page.locator('#terms-check')).to_be_disabled()
        response=x.client.get('/api/customer-credits')
        assert held
        held.pop().fulfill(status=response.status_code,content_type='application/json',body=response.text)
        expect(page.locator('#status')).to_have_text('Your plan and credit history are current.')
        expect(page.locator('#enroll')).to_be_hidden()
        expect(page.locator('#active')).to_be_visible()
        assert not errors
    finally:context.close()

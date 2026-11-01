"""Chromium follows the private customer review path using isolated handlers."""
import json
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect

from agent_market.customer_identity_service import COOKIE
from agent_market.workspace_app_factory import AppFactory
from tests.test_customer_typed_authoring import customer_flow
from tests.test_workflow_model_ollama import adapter
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world,routing,graph
from tests.test_front_workflow_browser import browser
from tests.workspace_credit_helpers import save_with_credit
from tests.human_workspace_helpers import library,manual,confirm,expert,edit_steps


def test_saved_workflow_pearls_match_actual_steps_and_fit_cards(customer_flow, browser, tmp_path):
    from agent_market.workspace_app_factory import NOTICE
    from tests.test_workspace_typed_flows import node
    x = customer_flow
    calls_before = len(x.w.calls)
    for count in (2, 5, 10):
        definition = {'nodes': [node('step_' + str(i), x.w.ids[i % 2],
            parent='step_' + str(i - 1) if i else None) for i in range(count)]}
        review = x.core.factory.prepare_plan(x.ws, {'name': f'{count} agent workflow',
            'definition': definition, 'base_flow_id': None, 'base_revision': None}, x.actor)
        x.core.factory.commit(x.ws, {'review_id': review['review_id'], 'authorized': True, 'notice': NOTICE}, x.actor)
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    context.set_offline(True)
    context.add_cookies([{'name': COOKIE, 'value': x.s.raw, 'url': 'https://customer.test',
                         'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
    page = context.new_page(); errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def handler(route):
        request = route.request; url = urlsplit(request.url)
        assert url.hostname == 'customer.test'
        response = x.client.request(request.method, url.path+('?'+url.query if url.query else ''), headers=request.headers,
                                    content=request.post_data, follow_redirects=False)
        route.fulfill(status=response.status_code, body=response.content,
            headers={k: v for k, v in response.headers.items()
                     if k not in ('content-length', 'content-encoding', 'set-cookie', 'transfer-encoding')})
    context.route('**/*', handler)
    try:
        page.goto('https://customer.test/customer/organizations/' + x.ws + '/flows')
        library(page)
        expect(page.locator('#workflow-cards .workflow-card')).to_have_count(3)
        for width, theme in [(1440, 'light'), (390, 'light'), (390, 'dark')]:
            page.set_viewport_size({'width': width, 'height': 1000})
            page.locator('body').evaluate('(el, theme) => el.dataset.theme = theme', theme)
            for count in (2, 5, 10):
                card = page.locator('.workflow-card').filter(has=page.get_by_text(f'{count} agent workflow', exact=True))
                expect(card.locator('.card-strand i')).to_have_count(count)
                expect(card.locator('.card-agent-count')).to_have_text(f"{count} agent step{'' if count == 1 else 's'}")
                assert card.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                assert card.locator('.card-strand i').last.evaluate('el => el.getBoundingClientRect().right <= el.closest("button").getBoundingClientRect().right')
            page.locator('#library').screenshot(path=str(tmp_path / f'workflow-card-pearls-{width}-{theme}.png'))
        page.locator('#workflow-search').fill('5 agent')
        expect(page.locator('.workflow-card')).to_have_count(1)
        page.locator('.workflow-card').click()
        expect(page.locator('#pearl-flow-preview .pearl')).to_have_count(5)
        expect(page.locator('.workflow-card')).to_have_attribute('aria-pressed', 'true')
        assert not errors and len(x.w.calls) == calls_before
    finally:
        context.close()


def test_private_customer_branch_review_test_release_feedback_and_withdrawal(customer_flow,browser):
    x=customer_flow;context=browser.new_context();context.set_offline(True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def handler(route):
        request=route.request;url=urlsplit(request.url)
        if url.hostname!='customer.test':
            external.append(request.url);route.abort();return
        response=x.client.request(request.method,url.path+('?'+url.query if url.query else ''),headers=request.headers,content=request.post_data,follow_redirects=False)
        if response.status_code>=400:errors.append(str(response.status_code)+':'+url.path)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items()
            if k not in ('content-length','content-encoding','set-cookie','transfer-encoding')})
    context.route('**/*',handler)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        manual(page)
        assert not errors
        before=len(x.w.calls)
        for _ in range(8):
            page.locator('#add').click()
        expect(page.locator('#add')).to_be_disabled()
        page.locator('.step-advanced').evaluate_all('ds=>ds.forEach(d=>d.open=true)')
        page.locator('[data-field=id]').first.fill('custom_step')
        page.get_by_role('button',name='Remove step',exact=True).nth(2).click()
        page.locator('#add').click()
        references=page.locator('[data-field=id]').evaluate_all('(inputs)=>inputs.map(input=>input.value)')
        assert references==['custom_step','step_2','step_4','step_5','step_6','step_7','step_8','step_9','step_10','step_1']
        assert len(set(references))==10
        assert len(x.w.calls)==before
        for _ in range(8):
            page.get_by_role('button',name='Remove step',exact=True).last.click()
        page.locator('#name').fill('Reviewed private customer research')
        page.locator('.step-advanced').evaluate_all('ds=>ds.forEach(d=>d.open=true)')
        for index,value in enumerate(graph(x.w)['nodes']):
            row=page.locator('#steps fieldset').nth(index)
            row.locator('[data-field=id]').fill(value['id'])
            row.locator('[data-field=choice]').select_option(str(value['resource_id'])+'|'+value['contract_id'])
            for key in ('input','bindings','after','when'):
                row.locator('[data-field='+key+']').fill(json.dumps(value[key]))
        page.locator('#human-review').click()
        expect(page.locator('#proposal')).to_contain_text('partial')
        expect(page.locator('#save')).to_be_disabled()
        assert len(x.w.calls)==before
        page.locator('#human-save').click()
        expect(page.locator('#human-confirm')).to_be_visible()
        expect(page.locator('#human-confirm-yes')).to_contain_text('1 credit')
        page.locator('#human-confirm').get_by_role('button',name='Cancel',exact=True).click()
        expect(page.locator('#status')).to_have_text('Save cancelled. No credits were used.')
        assert not x.core.typed.listing(x.ws,x.actor)
        save_with_credit(page)
        expect(page.locator('#history')).to_have_text('No retained tests for this workflow.')
        page.locator('#human-try').click()
        expect(page.locator('#test-review')).to_contain_text('prior_output_sharing')
        expect(page.locator('#run')).to_be_disabled()
        def deny_once(route):
            route.fulfill(status=429,headers={'Content-Type':'application/json','Retry-After':'60'},body='{}')
        pattern='**/typed/flows/*/runs'
        page.route(pattern,deny_once,times=1)
        confirm(page)
        expect(page.locator('#status')).to_contain_text('Wait one minute')
        expect(page.locator('#run')).to_be_disabled()
        assert len(x.w.calls)==before
        page.locator('#human-refresh').click()
        expect(page.locator('#status')).to_have_text('Your reviewed action is complete.')
        page.locator('#human-try').click()
        expect(page.locator('#test-review')).to_contain_text('prior_output_sharing')
        expect(page.locator('#run')).to_be_disabled()
        confirm(page)
        expect(page.locator('#history')).to_have_text('Workflow succeeded')
        expect(page.locator('#results')).to_contain_text('Current documentation')
        assert page.locator('#results script,#results img,#results iframe').count()==0
        assert len(x.w.calls)==before+2
        page.locator('#human-download').click()
        page.locator('#origin').fill('https://reviewed-app.example')
        page.get_by_role('button',name='Prepare download',exact=True).click();confirm(page)
        expect(page.locator('#revoke')).to_be_enabled()
        library(page)
        page.locator('#feedback-panel > summary').click()
        page.locator('#outcome').select_option('yes');page.locator('#corrections').fill('1')
        expect(page.locator('#record')).to_be_disabled()
        page.locator('#outcome-consent').check();page.locator('#record').click()
        expect(page.locator('#outcomes')).to_contain_text('1 retained task reports')
        page.locator('#withdrawals button').click()
        expect(page.locator('#outcomes')).to_contain_text('0 retained task reports')
        library(page);page.locator('#workflow-cards .workflow-card').first.click()
        page.locator('#human-download').click();page.get_by_text('Manage app access',exact=True).click()
        page.locator('#revoke').click();expect(page.locator('#revoke')).to_be_disabled()
        assert len(x.w.calls)==before+2 and not errors and not external
    finally:
        context.close()


def test_customer_concrete_model_requires_consent_and_support_patch_becomes_new_draft(customer_flow,browser):
    x=customer_flow;proposer,calls,client=adapter(x)
    before=len(x.w.calls)
    x.core.factory.model_source=AppFactory(x.w.core,model_proposer=proposer)
    context=browser.new_context();context.set_offline(True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def handler(route):
        request=route.request;url=urlsplit(request.url)
        if url.hostname!='customer.test':external.append(request.url);route.abort();return
        response=x.client.request(request.method,url.path+('?'+url.query if url.query else ''),headers=request.headers,content=request.post_data,follow_redirects=False)
        if response.status_code>=400:errors.append(str(response.status_code)+':'+url.path)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items()
            if k not in ('content-length','content-encoding','set-cookie','transfer-encoding')})
    context.route('**/*',handler)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        manual(page)
        page.locator('#name').fill('Reviewed model task')
        page.locator('#add').click()
        expect(page.locator('#steps fieldset')).to_have_count(3)
        page.locator('#human-nav-create').click()
        page.locator('#objective').fill('Find public documentation and supporting references')
        expect(page.locator('#model')).to_be_disabled()
        assert not calls
        page.route('**/typed/reviews/model',lambda route:route.fulfill(status=422,
            headers={'Content-Type':'application/json'},body='{}'),times=1)
        page.locator('#model-consent').check();page.locator('#model').click()
        expect(page.locator('#status')).to_contain_text('No new workflow was saved')
        expect(page.locator('#review')).to_be_enabled()
        expect(page.locator('#model')).to_be_disabled()
        assert len(calls)==0 and len(x.w.calls)==before
        page.locator('#model-consent').check();page.locator('#model').click()
        expect(page.locator('#proposal')).to_contain_text('partial')
        expect(page.locator('#steps fieldset')).to_have_count(2)
        expect(page.locator('#model-consent')).not_to_be_checked()
        expect(page.locator('#save')).to_be_disabled()
        assert len(calls)==1 and len(x.w.calls)==before
        save_with_credit(page)
        expect(page.locator('#history')).to_have_text('No retained tests for this workflow.')
        first=x.core.typed.listing(x.ws,x.actor)[0]
        edit_steps(page)
        expert(page);page.locator('#support-panel > summary').click()
        page.locator('#patch').fill(json.dumps([{'op':'replace','path':'/nodes/0/input','value':
            graph(x.w)['nodes'][0]['input']|{'query':'Revised public documentation'}}]))
        page.locator('#support').click()
        expect(page.locator('#proposal')).to_contain_text('Revised public documentation')
        expect(page.locator('#save')).to_be_disabled()
        save_with_credit(page)
        # The status names what finished instead of a generic completion line.
        expect(page.locator('#status')).to_have_text(re.compile(r'^Workflow (?:saved\. \d+ credits? used|changes saved)\.$'))
        flows=x.core.typed.listing(x.ws,x.actor)
        # 11-01: the support patch is the next revision of the same workflow, not a second copy.
        assert len(flows)==1 and flows[0]['id']==first['id'] and flows[0]['revision']==2
        assert x.core.typed.detail(x.ws,first['id'],x.actor)['definition']!=graph(x.w)
        assert len(calls)==1 and len(x.w.calls)==before and not errors and not external
    finally:
        context.close();client.close()

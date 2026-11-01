"""Real model, native customer UI, synthetic MCP and before/after-click screenshots."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit
import httpx,pytest
from playwright.sync_api import expect
from agent_market.customer_identity_service import COOKIE
from agent_market.workspace_app_factory import AppFactory
from agent_market.workflow_model_proposer import OllamaGraphProposer
from scripts.agentcon_config import read_local_model_settings
from tests.test_workspace_generation_diverse_live import matrix_world,customer_flow,typed_release_world,typed_world,routing
from tests.test_front_workflow_browser import browser
from tests.workspace_credit_helpers import save_with_credit
from tests.human_workspace_helpers import confirm
from tests.workflow_generation_cases import CASES,assess

pytestmark=pytest.mark.skipif(os.environ.get('LIVE_WORKFLOW_MATRIX')!='1',reason='Explicit real model opt-in required')
IDS=['docs_ten','news_then_docs','docs_then_news','three_topics','ko_three','three_results','unknown_weather','private_url']


@pytest.mark.parametrize('identity',IDS)
def test_customer_native_generation_review_save_run_or_clarification(matrix_world,browser,identity):
    x,trace=matrix_world;case=next(c for c in CASES if c['id']==identity);s=read_local_model_settings('gateway-data/local-model.env')
    model_calls=[]
    client=httpx.Client(trust_env=False,event_hooks={'request':[lambda r:model_calls.append(json.loads(r.content))]})
    x.core.factory.model_source=AppFactory(x.w.core,model_proposer=OllamaGraphProposer(s['WORKSPACE_MODEL_URL'],s['WORKSPACE_MODEL_NAME'],client,provider='openai',allow_http=True))
    width=390 if identity in ('docs_then_news','three_topics','ko_three','private_url') else 1440
    context=browser.new_context(offline=True,viewport={'width':width,'height':1000})
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];responses=[];review=None
    page.on('pageerror',lambda error:errors.append(str(error)))
    def serve(route):
        nonlocal review
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='customer.test':errors.append('Unexpected destination');route.abort();return
        res=x.client.request(req.method,url.path,headers=req.headers,content=req.post_data,follow_redirects=False)
        responses.append({'method':req.method,'path':url.path,'status':res.status_code})
        if url.path.endswith('/reviews/model'):review=res.json()
        route.fulfill(status=res.status_code,body=res.content,headers={k:v for k,v in res.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve);dest=Path('reports/workflow-generation-diverse-2026-10-23/browser');dest.mkdir(parents=True,exist_ok=True)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        page.locator('#objective').fill(case['prompt'])
        page.screenshot(path=str(dest/(identity+'-before-click.png')),full_page=True)
        page.locator('#model-consent').check();page.locator('#model').click()
        page.wait_for_function('()=>!busy',timeout=60000)
        assert review is not None
        if case['expected']=='review_required':
            expect(page.locator('#status')).to_have_text('AI proposal ready. Review the steps and exact inputs before saving.')
            checks=assess(case,review['review'],200);assert all(checks.values()),checks
            assert not x.w.calls and not trace
            page.screenshot(path=str(dest/(identity+'-fixed-review.png')),full_page=True)
            save_with_credit(page)
            expect(page.locator('#history')).to_have_text('No retained tests for this workflow.')
            assert not x.w.calls and not trace
            page.locator('#human-try').click()
            expect(page.locator('#human-confirm-yes')).to_be_disabled()
            confirm(page)
            expect(page.locator('#history')).to_have_text('Workflow succeeded',timeout=45000)
            page.screenshot(path=str(dest/(identity+'-fixed-result.png')),full_page=True)
            assert len(x.w.calls)+len(trace)==len(case['contracts'])
            expect(page.locator('#results article')).to_have_count(len(case['contracts']))
        elif case['expected']=='needs_details':
            expect(page.locator('#review-summary')).to_contain_text('This goal needs a different plan')
            expect(page.locator('#save')).to_be_disabled()
            assert not model_calls and not trace and not x.w.calls
            page.screenshot(path=str(dest/(identity+'-fixed-clarification.png')),full_page=True)
        else:
            expect(page.locator('#save')).to_be_disabled();assert not model_calls
            page.screenshot(path=str(dest/(identity+'-fixed-rejection.png')),full_page=True)
        assert not errors and not page.evaluate('()=>document.documentElement.scrollWidth>innerWidth+1')
        (dest/(identity+'.json')).write_text(json.dumps({'id':identity,'width':width,'page_errors':errors,'model_calls':len(model_calls),'api':responses,'review':review,'production_data_used':False},indent=2)+'\n')
    finally:context.close();client.close()

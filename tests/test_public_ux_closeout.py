# ruff: noqa: F401, F811 -- pytest fixture imports
"""Reported public UX defects with isolated data, no live provider calls."""
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from agent_market.concierge.request_store import interactive_store
from agent_market.concierge.selection import task_scope_matches
from agent_market.gateway.store import Store
from tests.test_pearl_frontend import client, pearl_page
from tests.test_front_workflow_browser import browser
from tests.test_workspace_growth import growth
from tests.test_workspace_typed_flows import typed_world, routing
from tests.test_workspace_model_proposal import request, response
from tests.test_fast_single_recommendation import catalog


def test_invoice_scope_requires_document_capability_not_json_vocabulary():
    task=['convert','pdf','invoices','json']
    assert not task_scope_matches(task,{'name':'IAM policy skills','description':'Buy policies as JSON','usage_tools':'[]'})
    assert task_scope_matches(task,{'name':'Invoice OCR','description':'Extract PDF invoices into structured JSON','usage_tools':'[]'})
    assert not task_scope_matches(task,{'name':'PDF reader','description':'Convert legal documents to JSON','usage_tools':'[]'})


def test_interactive_reader_does_not_wait_for_shared_catalog_lock(tmp_path):
    store=Store(str(tmp_path/'isolated.db')); acquired=threading.Event();release=threading.Event()
    def hold():
        with store._lock:acquired.set();release.wait(3)
    thread=threading.Thread(target=hold);thread.start();assert acquired.wait(1)
    try:
        with interactive_store(store,readonly=True) as reader:
            assert reader.query('SELECT COUNT(*) FROM resources')[0][0]==0
            with pytest.raises(Exception):reader._db.execute('DELETE FROM resources')
        assert not release.is_set()
    finally:release.set();thread.join();store._db.close()


def test_postgres_metrics_uses_existing_native_read_pool_not_sqlite():
    native=SimpleNamespace(backend='postgresql',_path=None)
    reader=object()
    @contextmanager
    def lease():yield SimpleNamespace(_store=reader)
    native._admin_read_pool=SimpleNamespace(reader=lease)
    with interactive_store(native,readonly=True) as current:assert current is reader
    with interactive_store(native) as current:assert current is native


def test_model_cannot_silently_substitute_docs_for_news_and_digest(growth):
    g=growth;calls=[];g.factory.model_proposer=lambda value:calls.append(value) or response(value)
    result=g.factory.prepare_model_proposal(g.w.ws,request(objective='Find news and research papers and write a digest'),g.w.actor)
    assert result['state']=='needs_details' and result['model_calls']==0
    assert result['missing_requirements'] and not calls and not g.w.calls
    assert not g.w.store.query('SELECT id FROM workspace_factory_reviews')


def test_returned_model_plan_must_cover_explicit_supported_news_goal(growth):
    g=growth;g.factory.model_proposer=response
    result=g.factory.prepare_model_proposal(g.w.ws,request(objective='Find news and public documentation'),g.w.actor)
    assert result['state']=='needs_details'
    assert not g.w.store.query('SELECT id FROM workspace_factory_reviews')


def test_human_results_sources_and_injection_are_safe(pearl_page):
    page,errors,_=pearl_page;page.goto('https://agentconcierge.biz/#test')
    data={'agent':'Research Papers','source':'Crossref','retrieved_at':'2026-10-20T05:00:00Z','data':{'items':[
        {'title':'Battery recycling','url':'https://doi.org/10.1/example','summary':'Recorded research'},
        {'title':'<img src=x onerror=alert(1)>','url':'javascript:alert(1)','summary':'<script>bad()</script>'}]}}
    page.evaluate('(data)=>renderTestbenchResult({output:JSON.stringify(data),execution_succeeded:true,tested_at:1792472400,latency_ms:15})',data)
    summary=page.locator('#tbOutputPre')
    assert 'Battery recycling' in summary.inner_text() and 'Crossref' in summary.inner_text()
    assert summary.locator('a').count()==1
    assert summary.locator('script,img').count()==0
    assert 'UTC' in page.locator('#tbKpiTime').inner_text()
    assert page.locator('#tbResponseWirePre').count()==1
    page.evaluate("window.frontWorkflowStarted=Date.now()-3000;showFrontRunOutputModal({status:'running',node_results:[]})")
    assert 'Elapsed: 3s' in page.locator('#frontWfRunModalBody').inner_text()
    assert '0ms' not in page.locator('#frontWfRunModalBody').inner_text()
    assert not errors


def test_route_scroll_cookie_rejection_and_contact_link(pearl_page):
    page,errors,_=pearl_page;page.goto('https://agentconcierge.biz/#about')
    page.evaluate('window.scrollTo(0,document.body.scrollHeight);switchTab("chat")')
    assert page.evaluate('window.scrollY')==0
    page.evaluate('location.hash="ai-transparency"')
    page.wait_for_function('document.getElementById("legalModal").open')
    page.evaluate('document.getElementById("legalModal").close();document.getElementById("btnRejectNonEssentialCookies").click()')
    assert not page.locator('#legalModal').evaluate('(node)=>node.open')
    assert not page.locator('dialog[open]').count()
    assert page.locator('a[data-service-mailbox="contact"]').first.get_attribute('href')=='mailto:contact@agentconcierge.biz'
    assert not errors


def test_chat_wait_budget_no_automatic_retry_and_restores_draft(pearl_page):
    page,errors,_=pearl_page;page.goto('https://agentconcierge.biz/#chat')
    page.clock.install()
    # The answer streams its progress; a request that never answers is stopped at 30 s and never re-sent.
    page.evaluate('''()=>{window.chatCalls=[];window.fetch=(path,options)=>{if(String(path)!=='/chat')return new Promise(()=>{});
        chatCalls.push(options.headers.Accept);return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(Error('aborted'),{name:'AbortError'}))))};
        window.chatDone=sendChat('Convert PDF invoices to JSON').then(()=>true)}''')
    page.clock.run_for(29000)
    assert page.evaluate("document.getElementById('chatForm').getAttribute('aria-busy')")=='true'
    page.clock.run_for(1500)
    result=page.evaluate('''async()=>{await chatDone;return {calls:chatCalls,input:document.getElementById('chatInput').value,
        busy:document.getElementById('chatForm').getAttribute('aria-busy'),progress:document.querySelectorAll('.chat-progress').length}}''')
    assert result=={'calls':['text/event-stream'],'input':'Convert PDF invoices to JSON','busy':'false','progress':0}
    assert not errors


def test_mobile_home_has_first_action_in_initial_viewport(pearl_page):
    page,errors,_=pearl_page
    page.set_viewport_size({'width':375,'height':812})
    page.goto('https://agentconcierge.biz/')
    box=page.locator('#home-task').bounding_box()
    assert box and box['y']+box['height']<812
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    assert not errors


def test_drawer_uses_plain_language_and_disables_unauthorized_test(pearl_page):
    page,errors,_=pearl_page;page.goto('https://agentconcierge.biz/#explore')
    page.evaluate("renderDrawerAgent({id:123,name:'Authorized documents',kind:'mcp',health_status:'healthy',auth_required:1,auth_method:'oauth2',auth_autonomy:'human_once',cap_tool_count:2,category:'docs_knowledge'},'live')")
    assert page.locator('#drawerTestBtn').is_disabled()
    assert 'One-time sign-in required' in page.locator('#drawerContent').inner_text()
    assert 'autonomy:' not in page.locator('#drawerContent').inner_text()
    assert not errors


def test_irrelevant_candidates_never_create_connection_versions(catalog):
    from tests.test_fast_single_recommendation import ask
    store,_,client,add,_=catalog
    add('IAM JSON policy marketplace',kind='a2a',description='JSON policy and skills purchasing')
    before=store.query('SELECT COUNT(*) FROM connection_versions')[0][0]
    result=ask(client,'Convert PDF invoices to JSON')
    assert not result['data'].get('recommendations')
    assert store.query('SELECT COUNT(*) FROM connection_versions')[0][0]==before


def test_busy_chat_returns_fixed_error_without_private_detail_or_automatic_replay(catalog):
    _,front,client,_,_=catalog
    def busy(*args):raise TimeoutError('synthetic-private-connection-detail')
    front.chat_payload=busy
    result=client.post('/chat',json={'message':'Find weather forecasts'})
    assert result.status_code==503 and result.json()['error_code']=='SERVICE_BUSY'
    assert 'synthetic-private' not in result.text and 'x-visitor-token' not in result.headers
    assert result.headers['retry-after']=='2'


def test_document_capabilities_cannot_be_combined_across_unrelated_tools():
    import json
    resource={'kind':'a2a','name':'Web and financial utilities','description':'General network utilities',
        'usage_tools':json.dumps([
            {'name':'search','description':'Filter web searches by PDF category'},
            {'name':'accounting','description':'Read invoices and billing documents'},
            {'name':'convert','description':'Convert currencies into structured JSON'}])}
    assert not task_scope_matches(['convert','pdf','invoices','json'],resource)
    resource['usage_tools']=json.dumps([{'name':'document_extract','description':'Extract PDF invoices into structured JSON'}])
    assert task_scope_matches(['convert','pdf','invoices','json'],resource)


def test_document_limitations_and_unadvertised_tools_do_not_pass_scope():
    import json
    task=['convert','pdf','invoices','json']
    resource={'name':'Business utilities','description':'Invoice document extraction',
              'usage_tools':json.dumps([{'name':'invoice_text_extraction',
                  'description':'Extract invoice fields from supplied text; no OCR or accounting posting.'}])}
    assert not task_scope_matches(task,resource)
    resource['usage_tools']=json.dumps([{'name':'invoice_ocr','description':'Extract PDF invoices into JSON'}])
    resource['usage_guide']=json.dumps({'tools':[{'name':'about_page_copy','description':'Create a business about page'}]})
    assert not task_scope_matches(task,resource)


def test_document_reply_uses_the_matching_advertised_tool(catalog):
    import json
    from tests.test_fast_single_recommendation import ask,chosen
    _,_,client,add,now=catalog
    tools=[{'name':'about_page','description':'Write company background'},
           {'name':'invoice_extract','description':'Extract PDF invoices into structured JSON'}]
    rid=add('Invoice Processor',kind='a2a',description='Extract PDF invoices into JSON',
            category='other',usage_guide=json.dumps({'tools':tools}),report_at=now-1)
    result=chosen(ask(client,'Convert PDF invoices to JSON'))
    assert result['id']==rid and result['tools']==['invoice_extract']


def test_document_no_match_is_not_replaced_with_text_only_invoices(catalog):
    import json
    from tests.test_fast_single_recommendation import ask
    _,_,client,add,now=catalog
    add('Invoice Text',kind='a2a',description='Extract invoice fields from text; no OCR.',
        category='other',usage_guide=json.dumps({'tools':[{'name':'invoice_text',
            'description':'Extract invoice fields from supplied text; no OCR.'}]}),report_at=now-1)
    assert ask(client,'Convert PDF invoices to JSON')['data']['recommendations']==[]


def test_a2a_discovery_does_not_inherit_x402_execution_capabilities():
    import json
    resource={'kind':'a2a','name':'Task tool marketplace','description':'Over A2A this agent answers one skill: it names the tools that do it. Actual calls use another protocol.',
              'usage_tools':json.dumps([{'name':'weather_forecast','description':'Weather forecast data through x402'}])}
    assert not task_scope_matches(['weather','forecast'],resource)
    assert task_scope_matches(['marketplace','discovery'],resource)


def test_actual_projected_text_envelope_renders_record_cards_and_cannot_inject(pearl_page):
    page,errors,_=pearl_page;page.goto('https://agentconcierge.biz/#workflows')
    text=('Recorded news source — https://example.org/news\nRetrieved: 2026-10-20T11:33:46Z\nData status: live\nQuery: artificial intelligence\n'
          'Title: A returned story | Url: https://example.org/article | Published at: 2026-10-20T08:30:35Z | Source: A public source\n'
          'Title: <img src=x onerror=alert(1)> | Url: javascript:alert(1) | Source: Untrusted text')
    page.evaluate('(text)=>showFrontRunOutputModal({status:"succeeded",duration_ms:5800,node_results:[{name:"Technology News",status:"succeeded",output:{text,truncated:true}}]})',text)
    content=page.locator('#pearlWorkflowResult')
    assert content.locator('.result-fact-list article').count()==2
    assert content.locator('.result-fact-list a').count()==1
    assert 'A returned story' in content.inner_text() and 'truncated' in content.inner_text()
    assert content.locator('img,script').count()==0
    page.evaluate('(text)=>renderTestbenchResult({execution_succeeded:true,output:text})',text)
    assert page.locator('#tbOutputPre .result-fact-list article').count()==2
    assert not errors


@pytest.mark.parametrize('phrase',['Pay-per-call over the x402 micropayment protocol.','Pay per call with x402.'])
def test_explicit_other_transport_does_not_imply_a2a_execution(phrase):
    import json
    resource={'kind':'a2a','name':'Public web APIs','description':'Public APIs. '+phrase,
        'usage_tools':json.dumps([{'name':'weather','description':'Weather forecast for a city'}])}
    assert not task_scope_matches(['weather','forecast'],resource)
    resource['kind']='x402'
    assert task_scope_matches(['weather','forecast'],resource)


def test_source_object_and_numeric_observation_context_remain_visible(pearl_page):
    page,errors,_=pearl_page;page.goto('https://agentconcierge.biz/#test')
    value={'source':{'name':'World Bank','url':'https://data.worldbank.org/'},'retrieved_at':'2026-10-20T10:00:00Z',
           'data':{'country_code':'US','indicator_name':'Population, total','unit':'people','items':[{'year':2025,'value':340000000,'url':'https://data.worldbank.org/indicator/EXAMPLE'}]}}
    page.evaluate('(value)=>renderTestbenchResult({execution_succeeded:true,output:JSON.stringify({structuredContent:value})})',value)
    text=page.locator('#tbOutputPre').inner_text()
    for fragment in ('World Bank','Population, total','people','US','340000000'):assert fragment in text
    assert not errors

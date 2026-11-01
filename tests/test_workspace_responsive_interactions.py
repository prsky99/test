# ruff: noqa: F811 -- imported pytest fixture
"""Immediate feedback, private read reuse and exact model selection boundaries."""
import json
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect

from agent_market.workflow_chatgpt import ChatGPTGraphProposer, private_write
from agent_market.workspace_access import WorkspaceInvalid, WorkspaceDenied
from tests.test_workflow_ai_providers import record, envelope, graph
from tests.test_front_workflow_browser import browser  # noqa: F401

JS=Path('new/live-assets/workspace-interactions.js').read_text()
BASE='/api/customer-organizations/ws_'+'a'*32+'/authoring/typed/flows'


@pytest.fixture
def interaction_page(browser):
    context=browser.new_context();page=context.new_page()
    page.route('https://customer.test/**',lambda route:route.fulfill(content_type='text/html',body='<body><button id="action">Read workflows</button></body>'))
    page.goto('https://customer.test/customer/organizations')
    page.evaluate("""()=>{window.calls=[];window.waiters=[];window.fetch=async(path,options)=>{calls.push({path,method:options.method||'GET',credentials:options.credentials,cache:options.cache});if(window.hold)await new Promise(resolve=>waiters.push(resolve));return new Response(JSON.stringify({serial:calls.length}),{status:window.failure||200,headers:{'Content-Type':'application/json'}})}}""")
    page.add_script_tag(content=JS)
    yield page
    context.close()


def test_read_cache_deduplicates_concurrent_calls_without_browser_storage(interaction_page):
    page=interaction_page
    result=page.evaluate("""async(path)=>{const values=await Promise.all([workspaceUI.request(path),workspaceUI.request(path)]);const first=await Promise.all(values.map(r=>r.json()));const next=await(await workspaceUI.request(path)).json();return {first,next,calls:window.calls,local:localStorage.length,session:sessionStorage.length}}""",BASE)
    assert len(result['calls'])==1 and result['first']==[result['next'],result['next']]
    assert result['local']==result['session']==0
    assert result['calls'][0]['credentials']=='same-origin' and result['calls'][0]['cache']=='no-store'


@pytest.mark.parametrize('suffix',['/api/customer-auth/session','/api/customer-credits',BASE+'/wtf_'+'b'*32+'/runs',BASE+'/wtf_'+'b'*32+'/versions/wtv_'+'c'*32+'/releases',BASE.replace('typed/flows','typed/options')])
def test_authority_credits_and_run_status_are_never_cached(interaction_page,suffix):
    page=interaction_page
    assert page.evaluate('async(path)=>{await workspaceUI.request(path);await workspaceUI.request(path);return calls.length}',suffix)==2


def test_mutation_error_and_manual_refresh_invalidate_reads(interaction_page):
    page=interaction_page
    result=page.evaluate("""async(path)=>{await workspaceUI.request(path);await workspaceUI.request('/api/customer-credits/enroll',{method:'POST',body:'{}'});await workspaceUI.request(path);await workspaceUI.request(path,{fresh:true});window.failure=403;await workspaceUI.request('/api/customer-auth/session');window.failure=0;await workspaceUI.request(path);return calls.map(c=>c.method)}""",BASE)
    assert result==['GET','POST','GET','GET','GET','GET']


def test_stale_inflight_read_is_not_cached_after_write(interaction_page):
    page=interaction_page
    page.evaluate('(path)=>{window.hold=true;window.first=workspaceUI.request(path)}',BASE)
    # Background reads do not show the feedback reserved for user actions.
    expect(page.locator('#workspace-progress')).to_be_hidden()
    page.wait_for_function('waiters.length===1')
    page.evaluate("async()=>{window.hold=false;await workspaceUI.request('/synthetic-write',{method:'POST'});waiters.shift()();await window.first}")
    assert page.evaluate('async(path)=>{await workspaceUI.request(path);return calls.length}',BASE)==3


def test_button_feedback_is_immediate_and_cleans_up_after_error(interaction_page):
    page=interaction_page
    page.evaluate("()=>{document.getElementById('action').onclick=async()=>{window.finish=workspaceUI.begin('Reading your workflow…');window.hold=true;try{await workspaceUI.request('/api/customer-auth/session')}finally{finish()}}}")
    page.locator('#action').click()
    expect(page.locator('#workspace-progress')).to_contain_text('Reading your workflow')
    expect(page.locator('#action')).to_have_attribute('aria-busy','true')
    page.wait_for_function('waiters.length===1')
    page.evaluate('()=>{waiters.shift()()}')
    expect(page.locator('#workspace-progress')).to_be_hidden()
    expect(page.locator('#action')).not_to_have_attribute('aria-busy','true')


def test_luna_light_uses_low_effort_and_requires_exact_completed_model(tmp_path):
    path=tmp_path/'credentials.json';private_write(path,record()|{'email':'owner@example.test'})
    model='gpt-5.6-luna';seen=[];text=json.dumps(graph())
    def respond(request):
        if request.url.path.endswith('/models'):return httpx.Response(200,json={'models':[{'slug':model,'visibility':'list'}]})
        value=json.loads(request.content);seen.append(value)
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=('data: '+json.dumps({'type':'response.completed','response':{'status':'completed','model':model,'output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}})+'\n\n').encode())
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result=ChatGPTGraphProposer(str(path),client,model=model,reasoning_effort='low',expected_email='OWNER@example.test')(envelope())
    assert result==graph() and seen[0]['model']==model and seen[0]['reasoning']=={'effort':'low'}
    assert seen[0]['store'] is False and 'owner@example.test' not in json.dumps(seen)


def test_wrong_chatgpt_account_is_rejected_before_catalog_or_inference(tmp_path):
    path=tmp_path/'credentials.json';private_write(path,record()|{'email':'other@example.test'});calls=[]
    with httpx.Client(transport=httpx.MockTransport(lambda r:calls.append(r))) as client:
        with pytest.raises(WorkspaceDenied):ChatGPTGraphProposer(str(path),client,model='gpt-5.6-luna',reasoning_effort='low',expected_email='owner@example.test')(envelope())
    assert not calls


@pytest.mark.parametrize('changes',[{'model':'unknown-model'},{'reasoning_effort':'light'},{'expected_email':'invalid'}])
def test_invalid_model_settings_never_fall_back(changes):
    with pytest.raises(WorkspaceInvalid):ChatGPTGraphProposer('unused',**changes)


@pytest.mark.parametrize('mutation',[None,'no_completion','wrong_model','duplicate_item','unfinished_item','different_final_text','missing_item','interrupted_delta'])
def test_completed_item_stream_requires_success_and_consistent_exact_output(tmp_path,mutation):
    from agent_market.workflow_chatgpt import MODEL
    path=tmp_path/'credentials.json';private_write(path,record());text=json.dumps(graph())
    item={'type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':text}]}
    done={'type':'response.output_item.done','output_index':1,'item':item}
    final={'type':'response.completed','response':{'status':'completed','model':MODEL,'output':[]}}
    events=[{'type':'response.output_text.delta','delta':text},done,final]
    if mutation=='no_completion':events.pop()
    elif mutation=='wrong_model':final['response']['model']='gpt-5.6-luna'
    elif mutation=='duplicate_item':events.insert(2,done)
    elif mutation=='unfinished_item':item['status']='in_progress'
    elif mutation=='different_final_text':final['response']['output']=[{'type':'message','content':[{'type':'output_text','text':text+' '}]}]
    elif mutation=='missing_item':events.remove(done)
    elif mutation=='interrupted_delta':events[0]['delta']=text[:-2]
    def respond(request):
        if request.url.path.endswith('/models'):return httpx.Response(200,json={'models':[{'slug':MODEL,'visibility':'list'}]})
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=b''.join(b'data: '+json.dumps(event).encode()+b'\n\n' for event in events))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        proposer=ChatGPTGraphProposer(str(path),client)
        if mutation is None:assert proposer(envelope())==graph()
        else:
            with pytest.raises(WorkspaceInvalid):proposer(envelope())


def test_cached_reads_expire_and_page_exit_clears_memory(interaction_page):
    page=interaction_page
    count=page.evaluate("""async(path)=>{await workspaceUI.request(path);const original=performance.now.bind(performance);Object.defineProperty(performance,'now',{value:()=>original()+11000,configurable:true});await workspaceUI.request(path);dispatchEvent(new Event('pagehide'));await workspaceUI.request(path);return calls.length}""",BASE)
    assert count==3


def test_read_cache_is_bounded_and_ambient_fetch_cannot_replace_transport(interaction_page):
    page=interaction_page
    count=page.evaluate("""async(base)=>{for(let i=0;i<21;i++)await workspaceUI.request(base+'/wtf_'+i.toString(16).padStart(32,'0'));await workspaceUI.request(base+'/wtf_'+'0'.repeat(32));return calls.length}""",BASE)
    assert count==22
    page.evaluate("()=>{window.fetch=async()=>new Response(JSON.stringify({value:'x'.repeat(270000)}),{headers:{'Content-Type':'application/json'}})}")
    # The installed helper retains its original transport; changing ambient
    # fetch cannot redirect an already installed private-page transport.
    assert page.evaluate('async(path)=>{await workspaceUI.request(path);return calls.length}',BASE)==23

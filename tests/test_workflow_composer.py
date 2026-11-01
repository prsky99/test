from tests.admin_public_helpers import prepare, approved
"""Compiler fixtures are not live evidence; dynamic tests use isolated MCP agents."""
import copy
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from agent_market.workflow_composer import Composer, intent_spec, SAVE, MODEL, PUBLISH
from agent_market.capability_registry import Registry
from tests.test_workflow_fallback import routing
from tests.test_workflow_fallback_api import routing_api, H
from tests.test_workflow_runtime import wait
from tests.test_admin_security_audit import login,session_headers
from agent_market.gateway.admin_auth import create_admin_user


def generate(rt,**options):return Composer(rt).generate({'prompt':'Python documentation search',**options},1)

def save(rt,envelope,**options):return Composer(rt).save({k:envelope[k] for k in ('proposal','signature')}|{'authority':True,'notice':SAVE,**options},1)


def test_draft_fixture_never_dispatches_saves_or_creates_success_evidence(routing):
    rt,wf,ids,calls,*_=routing;before=len(rt.store.query('SELECT * FROM capability_evidence'));count=len(rt.store.query('SELECT id FROM agent_workflows'))
    draft=generate(rt)
    assert draft['fixture_check']=={'status':'passed','provider_calls':0,'live_verified':False}
    assert not draft['saved'] and not draft['llm_used'] and len(draft['proposal']['candidates'])==3
    assert calls==[] and len(rt.store.query('SELECT * FROM capability_evidence'))==before
    assert len(rt.store.query('SELECT id FROM agent_workflows'))==count
    raw=json.dumps(draft)
    for private in ['primary.example','alternate.example','third.example','/Users/','credential_refs']:assert private not in raw


@pytest.mark.parametrize('body',[
 [],{}, {'prompt':[]},{'prompt':'weather flight and forex'}, {'prompt':'docs https://evil.example'},
 {'prompt':'docs <script>alert(1)</script>'},{'prompt':'docs api_key=secret'}, {'prompt':'docs user@example.org'},
 {'prompt':'docs','endpoint':'https://evil.example'},{'prompt':'x'*501},
 {'intent':{'objective':'docs','contracts':['products.compare.v1']}},
 {'intent':{'objective':'docs','contracts':['docs.search.v1'],'limit':True}},
 {'intent':{'objective':'docs','contracts':['docs.search.v1'],'data_class':'private'}},
 {'intent':{'objective':'docs','contracts':['docs.search.v1'],'language':'ko'}},
 {'intent':{'objective':'docs','contracts':['docs.search.v1'],'execution':'schedule'}},
 {'intent':{'objective':'docs','contracts':['docs.search.v1','docs.search.v1']}},
])
def test_intent_rejects_unsupported_sensitive_or_unbounded_inputs(body):
    with pytest.raises(ValueError):intent_spec(body)


@pytest.mark.parametrize('drift',['expired_evidence','approval','schema','signature','owner','expiry'])
def test_signed_draft_save_rechecks_current_evidence_scope_and_owner(routing,drift):
    rt,_,ids,calls,*_=routing;draft=generate(rt);selected=draft['proposal']['candidates'][0];rid=selected['pin']['resource_id']
    if drift=='expired_evidence':
        with rt.store.tx() as db:db.execute('UPDATE capability_evidence SET expires=0 WHERE version_id=?',(selected['pin']['version']['id'],))
    elif drift=='approval':Registry(rt.store).approve(rt.store.resource(rid),'docs.search.v1','search_docs')
    elif drift=='schema':
        with rt.store.tx() as db:db.execute("UPDATE resources SET usage_full_tools='[]' WHERE id=?",(rid,))
    elif drift=='signature':draft['proposal']['intent']['objective']='different docs'
    else:
        p=draft['proposal'];p['owner']=2 if drift=='owner' else p['owner'];p['expires']=0 if drift=='expiry' else p['expires'];draft['signature']=rt.authority.signature(p)
    with pytest.raises(ValueError):save(rt,draft)
    assert not calls


def test_explicit_replacement_uses_identical_inputs_and_resets_live_proof(routing):
    rt,*_=routing;first=generate(rt);candidate=first['proposal']['candidates'][1]
    second=Composer(rt).revise({k:first[k] for k in ('proposal','signature')}|{'selections':{'docs.search.v1':candidate['id']}},1)
    assert first['workflow']['nodes'][1]['data']['input']==second['workflow']['nodes'][1]['data']['input']
    assert first['workflow']['nodes'][1]['resource_id']!=second['workflow']['nodes'][1]['resource_id']
    assert first['proposal']['id']!=second['proposal']['id'] and second['saved'] is False
    assert second['proposal']['expires']==first['proposal']['expires']
    with pytest.raises(ValueError):Composer(rt).revise({k:first[k] for k in ('proposal','signature')}|{'selections':{'docs.search.v1':'cc_forged'}},1)


def test_generated_draft_explicit_live_test_and_immutable_publish_proof(routing):
    rt,_,_,calls,*_=routing;draft=generate(rt);identity=save(rt,draft)['id'];wf=rt.store.get_workflow(identity)
    assert not wf['is_template'] and not calls
    job=rt.submit(wf);run=wait(rt,job);assert run['status']=='succeeded',run
    proof=Composer(rt).validate_publish(wf,run['run_id']);assert proof==rt.store.query('SELECT digest FROM workflow_runs WHERE id=?',(run['run_id'],))[0][0]
    changed=copy.deepcopy(wf);changed['nodes'][1]['data']['input']['query']='Changed search'
    with pytest.raises(ValueError,match='changed'):Composer(rt).validate_publish(changed,run['run_id'])
    with rt.store.tx() as db:db.execute("UPDATE workflow_checkpoints SET signature='forged' WHERE run_id=? AND node_id!='start'",(run['run_id'],))
    with pytest.raises(ValueError,match='checkpoint'):Composer(rt).validate_publish(wf,run['run_id'])


def test_invalid_actual_output_fails_and_is_not_certified_by_fixture(routing):
    rt,_,_,calls,modes,*_=routing;draft=generate(rt);rid=draft['workflow']['nodes'][1]['resource_id'];host=rt.store.resource(rid)['url'].split('/')[2]
    wf=rt.store.get_workflow(save(rt,draft)['id']);modes[host]='invalid';run=wait(rt,rt.submit(wf))
    assert run['status']=='failed' and calls==[host]
    assert not rt.store.query("SELECT * FROM capability_evidence WHERE version_id=? AND scope='contract' AND dataset_version='composer-live-test-v1' AND outcome='succeeded'",(draft['proposal']['candidates'][0]['pin']['version']['id'],))
    with pytest.raises(ValueError):Composer(rt).validate_publish(wf,run['run_id'])


@pytest.mark.parametrize('attack',['endpoint','forged_candidate','input','duplicate'])
def test_model_output_cannot_create_tools_graphs_or_authority(routing,attack):
    rt,*_=routing;draft=generate(rt);plan=copy.deepcopy(draft['proposal']['plan'])
    if attack=='endpoint':plan['endpoint']='https://evil.example'
    elif attack=='forged_candidate':plan['steps'][0]['candidate_id']='invented'
    elif attack=='input':plan['steps'][0]['input']={'api_key':'secret'}
    else:plan['steps']*=2
    with pytest.raises(ValueError):Composer.validate_plan(plan,draft['proposal']['intent'],draft['proposal']['candidates'])


def test_model_is_explicit_bounded_and_receives_no_private_bindings(routing):
    rt,_,_,calls,*_=routing;seen=[]
    def handle(request):
        body=json.loads(request.content);seen.append(body);context=json.loads(body['messages'][1]['content'])
        candidate=context['candidates'][0]
        return httpx.Response(200,json={'message':{'content':json.dumps({'steps':[{'contract':candidate['contract'],'candidate_id':candidate['id']}]})}})
    client=httpx.Client(transport=httpx.MockTransport(handle));composer=Composer(rt,SimpleNamespace(http=client,ollama_url='http://127.0.0.1:11434',generation_model='isolated-model'))
    with pytest.raises(ValueError):composer.generate({'prompt':'docs search','planner':'model'},1)
    assert seen==[]
    result=composer.generate({'prompt':'docs search','planner':'model','model_authority':True,'model_notice':MODEL},1)
    assert result['llm_used'] and len(seen)==1 and calls==[]
    for private in ['primary.example','binding_hash','resource_id','approval','cv_','search_docs']:assert private not in json.dumps(seen)
    client.close()


def test_model_composer_uses_single_configured_openai_server(routing):
    rt, _, _, calls, *_ = routing
    seen = []
    def respond(message):
        assert str(message.url) == 'http://192.168.0.25:8000/v1/chat/completions'
        body = json.loads(message.content); seen.append(body)
        context = json.loads(body['messages'][1]['content'])
        first = context['candidates'][0]
        plan = {'steps': [{'contract': first['contract'], 'candidate_id': first['id']}]}
        return httpx.Response(200, json={'model': 'gemma4-e4b-mlx', 'choices': [{
            'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(plan)}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        engine = SimpleNamespace(http=client, ollama_url='http://127.0.0.1:11434',
            generation_url='http://192.168.0.25:8000/v1', generation_provider='openai',
            generation_model='gemma4-e4b-mlx')
        result = Composer(rt, engine).generate({'prompt': 'docs search', 'planner': 'model',
            'model_authority': True, 'model_notice': MODEL}, 1)
        assert result['llm_used'] and not result['saved'] and not calls
        assert len(seen) == 1 and seen[0]['chat_template_kwargs'] == {'enable_thinking': False}


@pytest.mark.parametrize('role',['operator','admin'])
def test_composer_requires_highest_admin_and_no_public_surface(routing_api,role):
    routing,public,admin=routing_api;rt,*_=routing
    with rt.store.tx() as db:create_admin_user(db,'composer-viewer','viewer-long-password','Viewer',role)
    token=login(admin,'composer-viewer','viewer-long-password').json()['token'];headers=session_headers(token)
    for path in ['/admin/api/workflows/ai-generate','/admin/api/workflow-composer/save','/admin/api/workflow-composer/revise','/admin/api/workflow-composer/publish']:
        assert admin.post(path,headers=headers,json={}).status_code==403
        assert admin.post(path,json={}).status_code in (401,403)
        assert public.post(path,json={}).status_code==404


def test_api_explicit_save_test_publish_no_store_and_legacy_publish_guard(routing_api):
    routing,public,admin=routing_api;rt,_,_,calls,*_=routing
    response=admin.post('/admin/api/workflows/ai-generate',headers=H,json={'prompt':'documentation search'})
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store';draft=response.json();assert not calls
    body={k:draft[k] for k in ('proposal','signature')}
    assert admin.post('/admin/api/workflow-composer/save',headers=H,json=body).status_code==400
    saved=admin.post('/admin/api/workflow-composer/save',headers=H,json={**body,'authority':True,'notice':SAVE});assert saved.status_code==200,saved.text
    wid=saved.json()['id'];assert not calls
    assert admin.post(f'/admin/api/workflows/{wid}/publish-template',headers=H,json={}).status_code in (400,409)
    job=admin.post(f'/admin/api/workflows/{wid}/run',headers=H,json={});assert job.status_code==202,job.text
    result=wait(rt,job.json());assert result['status']=='succeeded',result
    prepare(rt.store,H)
    response=admin.post('/admin/api/workflow-composer/publish',headers=H,json={'workflow_id':wid,'run_id':result['run_id'],'authority':True,'notice':PUBLISH,'reason':'Synthetic tested draft publication'})
    assert response.headers['cache-control']=='no-store' and not rt.store.get_workflow(wid)['is_template']
    assert approved(admin,H,response)['published']
    from agent_market.workflows import public_template
    projected=json.dumps(public_template(rt.store.get_workflow(wid)))
    assert 'composition' not in projected and 'binding_hash' not in projected
    job=public.post('/api/workflows/run',json={'template_id':wid});assert job.status_code==202,job.text
    assert wait(rt,job.json())['status']=='succeeded'
    package=public.get(f'/api/workflows/{wid}/webapp');assert package.status_code==200,package.text
    from zipfile import ZipFile
    from io import BytesIO
    with ZipFile(BytesIO(package.content)) as archive:
        contents='\n'.join(archive.read(n).decode('utf-8',errors='replace') for n in archive.namelist() if not n.endswith('/'))
    proof=draft['workflow']['nodes'][1]['data']['composition']['mac']
    assert proof not in contents and 'binding_hash' not in contents and 'primary.example' not in contents


@pytest.mark.parametrize('result',['oversize','redirect','invalid'])
def test_model_failure_never_falls_back_or_saves_a_draft(routing,result):
    rt,_,_,calls,*_=routing;requests=[]
    def handle(request):
        requests.append(request)
        if result=='oversize':return httpx.Response(200,content=b'x'*17000)
        if result=='redirect':return httpx.Response(302,headers={'Location':'https://untrusted.example/planner'})
        return httpx.Response(200,json={'message':{'content':'{"steps":[{"endpoint":"https://untrusted.example"}]}'}})
    with httpx.Client(transport=httpx.MockTransport(handle),follow_redirects=True) as client:
        composer=Composer(rt,SimpleNamespace(http=client,ollama_url='http://127.0.0.1:11434',generation_model='isolated-model'))
        count=len(rt.store.query('SELECT id FROM agent_workflows'))
        with pytest.raises(ValueError,match='approved bounded plan'):composer.generate({'prompt':'docs search','planner':'model','model_authority':True,'model_notice':MODEL},1)
        assert len(requests)==1 and not calls and len(rt.store.query('SELECT id FROM agent_workflows'))==count


def test_news_intent_fixture_and_actual_contract_validation(routing,monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from agent_market.collector import usage
    from agent_market.capability_contracts import run_test
    from tests.test_workflow_fallback import tool,output
    rt,_,ids,calls,_,_,remote=routing;news=tool('news.search.v1');news_output=lambda:output('news.search.v1')
    monkeypatch.setattr('tests.test_workflow_fallback.output',news_output);remote.tools=[news]
    for rid in ids:
        compact=usage.compact_tools([news]);rt.store.record_usage(rid,compact,usage.tools_hash(compact),{},None,{'ok':True},full_tools=[news])
        registry=Registry(rt.store);registry.approve(rt.store.resource(rid),'news.search.v1','search_news')
        async def runner(identity,**kwargs):
            response=rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments'])
            return {'execution_succeeded':response['ok'],'simulated':False,'output':response['result']}
        with ThreadPoolExecutor(max_workers=1) as pool:
            outcome=pool.submit(lambda:asyncio.run(run_test(registry,rt.store.resource(rid),'news.search.v1',{'query':'AI news','language':'en','limit':3,'from_utc':'2026-01-01T00:00:00Z'},runner))).result()
        assert outcome['ok']
    calls.clear();draft=generate(rt,prompt='latest AI news');assert not calls
    wf=rt.store.get_workflow(save(rt,draft)['id']);run=wait(rt,rt.submit(wf));assert run['status']=='succeeded',run
    assert Composer(rt).validate_publish(wf,run['run_id'])


def test_compiled_signed_snapshot_round_trips_existing_postgres_state_boundary(routing,monkeypatch):
    import os
    from pathlib import Path
    from scripts.rehearse_workflow_postgres import rehearse
    rt,*_=routing;draft=generate(rt);wf=rt.store.get_workflow(save(rt,draft)['id']);result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded'
    monkeypatch.setenv('PATH','/opt/homebrew/opt/postgresql@14/bin:'+os.environ.get('PATH',''))
    proof=rehearse(rt.store._path)
    from scripts.rehearse_workflow_postgres import TABLES
    assert set(proof['tables'])==set(TABLES) and proof['round_trip_equal'] and proof['tables']['workflow_checkpoints']>=2
    Path('reports/advancement-r07-2026-10-18/postgres-composer-rehearsal.json').write_text(json.dumps(proof,indent=2)+'\n')

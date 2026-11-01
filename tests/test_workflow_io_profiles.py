"""Generic transformed native schemas, real proxy code and isolated fallback."""
# ruff: noqa: F401,F811
import copy
from datetime import datetime, timezone
import json
import time

import httpx
import pytest

from agent_market.capability_contracts import CONTRACTS
from agent_market.capability_registry import Registry
from agent_market.collector import usage
from agent_market.workflow_fallback import RoutingDenied
from agent_market.workflow_io_profiles import NOTICE
from tests.test_workflow_fallback import routing, config, run
from tests.test_workflow_fallback_api import routing_api, H
from tests.test_workflow_runtime import wait, save, node
from tests.test_workflow_transforms import recipe, get, obj, literal


@pytest.fixture
def transformed(routing):
    rt,wf,ids,calls,modes,hooks,remote=routing
    canonical=CONTRACTS['docs.search.v1'];native_calls=[]
    native_input={'type':'object','properties':{'term':{'type':'string','minLength':1,'maxLength':500},
        'count':{'type':'integer','minimum':1,'maximum':10}},'required':['term','count'],'additionalProperties':False}
    item={'type':'object','properties':{k:{'type':'string'} for k in ('heading','href','body','rev','observed')},
        'required':['heading','href','body','rev','observed'],'additionalProperties':False}
    native_output={'type':'object','properties':{'records':{'type':'array','maxItems':10,'items':item},
        'state':{'type':'string','enum':['ready','unavailable']}},'required':['records','state'],'additionalProperties':False}
    tool={'name':'search_records','description':'Search public documentation records','inputSchema':native_input,'outputSchema':native_output,
        'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True}}
    original=remote.handle_request
    def handle(request):
        body=json.loads(request.content or '{}')
        if request.url.host=='alternate.example':
            if body.get('method')=='tools/list':return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'tools':[tool]}})
            if body.get('method')=='server/discover' and modes.get('alternate.example')=='revoke_preflight':
                hooks['revoke']()
            if body.get('method')=='tools/call':
                calls.append('alternate.example');native_calls.append(body['params']['arguments'])
                supplied=body['params']['arguments'];stamp=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
                value={'state':'ready','records':[{'heading':'Research: '+supplied['term'],'href':'https://source.example/article',
                    'body':'Public record for '+supplied['term'],'rev':'2026','observed':stamp}]}
                if modes.get('alternate.example')=='unavailable':value={'state':'unavailable','records':[]}
                if modes.get('alternate.example')=='unknown':raise httpx.ReadTimeout('Isolated response loss')
                return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'content':[],'structuredContent':value}})
        return original(request)
    remote.handle_request=handle
    rt.store.record_usage(ids[1],usage.compact_tools([tool]),usage.tools_hash(usage.compact_tools([tool])),{},None,{'ok':True},full_tools=[tool])
    Registry(rt.store).approve(rt.store.resource(ids[1]),'docs.search.v1',tool['name'])
    input_recipe=recipe(obj(term=get('/query'),count=get('/limit')),canonical['input_schema'],native_input)
    output_recipe=recipe(obj(items={'op':'map','value':get('/records'),'item':obj(title=get('/heading'),url=get('/href'),
        excerpt=get('/body'),version=get('/rev'),retrieved_at={'op':'utc','value':get('/observed')})},partial=literal(False)),native_output,canonical['output_schema'])
    body={'profile':{'resource_id':ids[1],'tool':tool['name'],'contract_id':'docs.search.v1',
        'input_transform':input_recipe,'output_transform':output_recipe,'status_checks':[{'path':'/state','allowed':['ready']}]},
        'cases':[{'query':q,'language':'en','limit':2} for q in ('solar energy','ocean monitoring','battery recycling')],
        'authority':True,'notice':NOTICE}
    profile=rt.io_profiles.create(body,1,lambda:True)
    yield routing,profile,body,native_calls


def activate_transformed(transformed,monkeypatch):
    routing,profile,_,_=transformed;rt,wf,ids,*_=routing
    pairs=[{'node_id':'search','resource_id':ids[1],'contract_id':'docs.search.v1','alternate_io_profile':profile['id']}]
    config(rt,wf,ids,pairs=pairs)
    assert wait(rt,rt.submit(wf))['status']=='succeeded'
    config(rt,wf,ids,'canary',pairs=pairs)
    rt.fallback.set_control({'enabled':True,'revision':0},1)
    monkeypatch.setattr(rt.fallback,'sample',lambda _:0)
    routing[3].clear()


def test_actual_native_schema_checks_create_a_signed_resource_bound_profile(transformed):
    routing,profile,_,native_calls=transformed;rt,_,ids,*_=routing
    assert profile['cases']==3 and len(native_calls)==3
    assert native_calls[0]=={'term':'solar energy','count':2}
    pin=rt.fallback.pin(ids[1],'docs.search.v1',io_profile=profile['id'])
    assert pin['io_profile']==profile['id'] and len(pin['io_profile_hash'])==64
    with pytest.raises(ValueError):rt.io_profiles.get(profile['id'],resource_id=ids[0])
    with pytest.raises(RoutingDenied):rt.fallback.pin(ids[1],'docs.search.v1')


def test_generic_proof_also_works_for_a_previously_fixed_adapter_connection(transformed,monkeypatch):
    routing,profile,_,_=transformed;rt,_,ids,*_=routing
    monkeypatch.setattr('agent_market.capability_adapters.profile',lambda *args:{'id':'other-fixed-profile','implementation_hash':'old'})
    assert rt.fallback.pin(ids[1],'docs.search.v1',io_profile=profile['id'])['io_profile']==profile['id']
    rt.io_profiles.revoke(profile['id'])
    projection=Registry(rt.store).projection(rt.store.resource(ids[1]),strict=True)
    assert not next(c for c in projection['capability_contracts'] if c['id']=='docs.search.v1')['verified']


@pytest.mark.parametrize('failure',['error','invalid','preflight'])
def test_heterogeneous_alternative_transforms_input_and_output_once(transformed,monkeypatch,failure):
    activate_transformed(transformed,monkeypatch)
    routing,profile,_,native_calls=transformed;rt,wf,_,calls,modes,*_=routing
    modes['primary.example']=failure;before=len(native_calls)
    result=run(rt,wf)
    assert result['status']=='succeeded',result
    assert calls==(['alternate.example'] if failure=='preflight' else ['primary.example','alternate.example'])
    assert len(native_calls)==before+1 and native_calls[-1]=={'term':'documentation','count':2}
    item=result['node_results'][0]
    assert item['fallback_used'] and item['attempts']==2
    assert item['data']['structuredContent']['items'][0]['title']=='Research: documentation'
    assert item['data']['structuredContent']['partial'] is False


def test_uncertain_primary_does_not_use_transformation_as_a_retry_permission(transformed,monkeypatch):
    activate_transformed(transformed,monkeypatch)
    routing,_,_,native_calls=transformed;rt,wf,_,calls,modes,*_=routing
    modes['primary.example']='unknown';before=len(native_calls)
    result=run(rt,wf)
    assert result['status']=='failed' and calls==['primary.example']
    assert len(native_calls)==before


def test_provider_failure_cannot_be_converted_to_empty_success(transformed,monkeypatch):
    activate_transformed(transformed,monkeypatch)
    routing,_,_,_=transformed;rt,wf,_,calls,modes,*_=routing
    modes['primary.example']='error';modes['alternate.example']='unavailable'
    assert run(rt,wf)['status']=='failed'
    assert calls==['primary.example','alternate.example']


@pytest.mark.parametrize('change',['revoke','tamper','expires','approval','binding','implementation'])
def test_changed_profile_is_not_reused_for_activation(transformed,change,monkeypatch):
    routing,profile,_,_=transformed;rt,_,ids,*_=routing
    if change=='revoke':rt.io_profiles.revoke(profile['id'])
    elif change=='implementation':monkeypatch.setattr('agent_market.workflow_io_profiles.implementation',lambda:'changed')
    else:
        with rt.store.tx() as db:
            if change=='tamper':db.execute("UPDATE workflow_io_profiles SET signature='tampered' WHERE id=?",(profile['id'],))
            elif change=='expires':db.execute('UPDATE workflow_io_profiles SET expires=0 WHERE id=?',(profile['id'],))
            elif change=='approval':db.execute('UPDATE capability_approvals SET created=? WHERE version_id=?',(time.time()+1,rt.io_profiles.get(profile['id'])['version']['id']))
            elif change=='binding':db.execute("UPDATE resources SET url='https://changed.example/mcp' WHERE id=?",(ids[1],))
    with pytest.raises(ValueError):rt.fallback.pin(ids[1],'docs.search.v1',io_profile=profile['id'])


def test_revocation_between_preflight_and_dispatch_prevents_business_call(transformed,monkeypatch):
    activate_transformed(transformed,monkeypatch)
    routing,profile,_,native_calls=transformed;rt,wf,_,calls,modes,hooks,_=routing
    modes['primary.example']='error';modes['alternate.example']='revoke_preflight'
    hooks['revoke']=lambda:rt.io_profiles.revoke(profile['id']);before=len(native_calls)
    result=run(rt,wf)
    assert result['status']=='failed' and len(native_calls)==before
    assert calls==['primary.example']


def test_generic_profile_cannot_override_shared_dependency_rejection(transformed):
    routing,profile,_,_=transformed;rt,wf,ids,*_=routing
    with rt.store.tx() as db:db.execute('UPDATE resources SET details=? WHERE id=?',
        (json.dumps({'remotes':[{'url':'https://primary.example/mcp'}]}),ids[1]))
    with pytest.raises(ValueError):config(rt,wf,ids,pairs=[{'node_id':'search','resource_id':ids[1],
        'contract_id':'docs.search.v1','alternate_io_profile':profile['id']}])


def test_literal_provenance_and_failed_test_cases_never_create_profiles(transformed):
    routing,_,body,_=transformed;rt,*_=routing
    initial=len(rt.io_profiles.list());bad=copy.deepcopy(body)
    bad['profile']['output_transform']['expression']['fields']['items']['item']['fields']['retrieved_at']=literal(datetime.now(timezone.utc).isoformat())
    with pytest.raises(ValueError,match='timestamps'):rt.io_profiles.create(bad,1,lambda:True)
    bad=copy.deepcopy(body);bad['cases'][1]['language']='other'
    with pytest.raises(ValueError):rt.io_profiles.create(bad,1,lambda:True)
    assert len(rt.io_profiles.list())==initial


def test_json_text_cannot_hide_fabricated_source_records_in_a_profile(transformed):
    routing,_,body,native_calls=transformed;rt,*_=routing
    bad=copy.deepcopy(body);before=len(native_calls)
    fake={'items':[{'title':'Invented','url':'https://source.example/invented','excerpt':'Invented',
        'version':'2026','retrieved_at':datetime.now(timezone.utc).isoformat()}],'partial':False}
    bad['profile']['output_transform']['expression']={'op':'parse_json','value':literal(json.dumps(fake))}
    with pytest.raises(ValueError,match='original provider'):rt.io_profiles.create(bad,1,lambda:True)
    assert len(native_calls)==before


def test_generic_status_conditions_can_compare_provider_echo_to_original_input(transformed):
    routing,_,body,_=transformed;rt,*_=routing
    candidate=copy.deepcopy(body)
    candidate['profile']['status_checks'].append({'path':'/records/0/heading','equals_input':'/query'})
    before=len(rt.io_profiles.list())
    with pytest.raises(ValueError,match='status'):rt.io_profiles.create(candidate,1,lambda:True)
    assert len(rt.io_profiles.list())==before


def test_transform_test_rejects_personal_contact_input_without_dispatch(transformed):
    routing,_,body,native_calls=transformed;rt,*_=routing
    candidate=copy.deepcopy(body);candidate['cases'][0]['query']='person@example.invalid'
    before=len(native_calls)
    with pytest.raises(ValueError,match='non-sensitive'):rt.io_profiles.create(candidate,1,lambda:True)
    assert len(native_calls)==before


def test_public_alternative_uses_transform_but_hides_private_profile(routing_api,transformed,monkeypatch):
    routing,public,_=routing_api;rt,wf,_,_,modes,*_=routing
    activate_transformed(transformed,monkeypatch);modes['primary.example']='error'
    response=public.post('/api/workflows/run',json={'template_id':wf['id'],'allow_fallback':True,'fallback_notice':'readonly-fallback-v1'})
    assert response.status_code==202,response.text
    result=wait(rt,response.json());assert result['status']=='succeeded'
    retrieved=public.get('/api/workflows/runs/'+response.json()['run_id'],headers={'X-Workflow-Key':response.json()['run_key']})
    assert retrieved.status_code==200 and retrieved.json()['node_results'][0]['fallback_used']
    for private in ('io_profile','input_transform','output_transform','signature','alternate.example'):
        assert private not in retrieved.text


def test_primary_profile_runs_normally_without_fallback_permission(transformed):
    routing,profile,_,_=transformed;rt,_,ids,*_=routing
    wf=save(rt.store,[node('native',resource_id=ids[1],tool='search_records',io_profile=profile['id'],
        input={'query':'custom input','language':'en','limit':1})])
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded' and not result['node_results'][0].get('fallback_used')
    assert result['node_results'][0]['data']['structuredContent']['items'][0]['title']=='Research: custom input'


def test_profiles_are_revoked_by_restore_quarantine(transformed):
    from agent_market.workflow_backup import quarantine
    routing,profile,_,_=transformed;rt,*_=routing
    with rt.store.tx() as db:quarantine(db)
    with pytest.raises(ValueError,match='revoked'):rt.io_profiles.get(profile['id'])


def test_transform_admin_api_preview_permissions_csrf_and_no_public_route(routing_api):
    routing,public,admin=routing_api;rt,*_=routing
    route='/admin/api/workflow-io-profiles'
    for path in (route,route+'/schemas?resource_id=1&tool=search_docs&contract_id=docs.search.v1'):
        assert public.get(path).status_code==404
        assert admin.get(path).status_code in (401,403)
        assert admin.get(path,headers={**H,'Authorization':'Bearer fallback-test-secret'}).status_code in (401,403)
    payload={'recipe':recipe(obj(number={'op':'integer','value':get('/value')})),'input':{'value':'12'}}
    assert admin.post(route+'/preview',json=payload).status_code in (401,403)
    assert admin.post(route+'/preview',headers={**H,'Origin':'https://evil.example'},json=payload).status_code==403
    response=admin.post(route+'/preview',headers=H,json=payload)
    assert response.status_code==200 and response.json()=={'output':{'number':12},'provider_calls':0}
    assert response.headers['cache-control']=='no-store'
    assert not rt.io_profiles.list()
    headers={**H,'Content-Type':'application/json'}
    assert admin.post(route+'/preview',headers=headers,content=b'['*1100+b'0'+b']'*1100).status_code==400
    assert admin.post(route+'/verify',headers=headers,content=b'['*1100+b'0'+b']'*1100).status_code in (400,409)
    oversized=json.dumps({'recipe':payload['recipe'],'input':{'value':'x'*64000}}).encode()
    assert admin.post(route+'/preview',headers=headers,content=oversized).status_code==413


def test_real_verification_api_persists_and_revokes_with_individual_authority(routing_api,transformed):
    routing,public,admin=routing_api;rt,*_=routing
    _,_,body,_=transformed
    url='/admin/api/workflow-io-profiles/verify'
    assert public.post(url,json=body).status_code==404
    assert admin.post(url,json=body).status_code in (401,403)
    assert admin.post(url,headers={**H,'Authorization':'Bearer fallback-test-secret'},json=body).status_code in (401,403)
    assert admin.post(url,headers={**H,'Origin':'https://evil.example'},json=body).status_code==403
    response=admin.post(url,headers=H,json=body)
    assert response.status_code==200,response.text
    identity=response.json()['id'];assert rt.io_profiles.get(identity)['cases']==3
    assert admin.delete('/admin/api/workflow-io-profiles/'+identity,headers=H).status_code==200
    with pytest.raises(ValueError):rt.io_profiles.get(identity)


def test_real_tcp_shutdown_with_distinct_native_schemas(transformed,monkeypatch):
    from pathlib import Path
    from agent_market.concierge.proxy import McpProxy
    from tests.test_workflow_fallback_tcp import Provider, LoopbackRoutes
    from agent_market.workflow_fallback import NOTICE as FALLBACK_NOTICE
    routing,_,body,_=transformed;rt,wf,ids,*_=routing
    native_spec=json.loads(rt.store.resource(ids[1])['usage_full_tools'])[0]
    def native_result(arguments):
        return {'content':[],'structuredContent':{'state':'ready','records':[{
            'heading':'TCP native result: '+arguments['term'],'href':'https://source.example/tcp',
            'body':'A live isolated socket response for '+arguments['term'],'rev':'2026',
            'observed':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}]}}
    primary=Provider('primary');alternate=Provider('alternate',tools=[native_spec],result_factory=native_result)
    client=httpx.Client(transport=LoopbackRoutes({'primary.example':primary,'alternate.example':alternate}))
    previous=rt.proxy;rt.proxy=McpProxy(rt.store,allow_private=True,http=client)
    try:
        profile=rt.io_profiles.create(body,1,lambda:True)
        pairs=[{'node_id':'search','resource_id':ids[1],'contract_id':'docs.search.v1','alternate_io_profile':profile['id']}]
        config(rt,wf,ids,pairs=pairs);assert wait(rt,rt.submit(wf))['status']=='succeeded'
        config(rt,wf,ids,'canary',pairs=pairs);rt.fallback.set_control({'enabled':True,'revision':0},1)
        monkeypatch.setattr(rt.fallback,'sample',lambda _:0)
        primary.calls.clear();alternate.calls.clear();primary.close()
        result=wait(rt,rt.submit(wf,allow_fallback=True,fallback_notice=FALLBACK_NOTICE))
        assert result['status']=='succeeded',result
        assert not primary.calls and alternate.calls==[{'term':'documentation','count':2}]
        item=result['node_results'][0]
        assert item['fallback_used'] and item['data']['structuredContent']['items'][0]['title']=='TCP native result: documentation'
        report={'checked_at':time.time(),'scope':'Real loopback TCP with different native schemas; isolated fixture data, not independent public providers.',
            'primary_listener_closed':True,'primary_business_calls_after_shutdown':0,'alternative_business_calls':1,
            'canonical_input':{'query':'documentation','language':'en','limit':2},'native_input':alternate.calls[0],
            'normalized_title':item['data']['structuredContent']['items'][0]['title'],'result':result['status'],
            'fallback_used':True,'operating_mutations':0,'production_activation':False}
        Path('reports/agent-fallback-validation-2026-10-24/transformed-tcp.json').write_text(json.dumps(report,indent=2)+'\n')
    finally:
        for future in rt.futures.values():future.result(timeout=5)
        primary.close();alternate.close();client.close();rt.proxy=previous

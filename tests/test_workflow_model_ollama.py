"""Concrete Ollama HTTP proposals remain private, bounded and separately reviewed."""
from dataclasses import FrozenInstanceError
import json

import httpx
import pytest

from agent_market.workspace_access import WorkspaceConflict,WorkspaceDenied,WorkspaceInvalid
from agent_market.workspace_app_factory import NOTICE
from agent_market.workflow_model_proposer import OllamaGraphProposer
from tests.test_workspace_growth import growth
from tests.test_workspace_typed_flows import typed_world,routing,graph
from tests.test_workspace_model_proposal import request


def adapter(g, *, change=None, payload=None, status=200, headers=None):
    calls=[]
    def respond(message):
        assert str(message.url)=='http://127.0.0.1:11434/api/chat'
        calls.append(json.loads(message.content))
        if change:change()
        value=payload if payload is not None else json.dumps({'done':True,'message':{
            'role':'assistant','content':json.dumps(graph(g.w))}})
        return httpx.Response(status,content=value,headers={'Content-Type':'application/json',**(headers or {})})
    client=httpx.Client(transport=httpx.MockTransport(respond))
    return OllamaGraphProposer('http://127.0.0.1:11434','synthetic-model',client),calls,client


def test_real_adapter_serializes_only_approved_context_and_returns_exact_typed_review(growth):
    g=growth;proposer,calls,client=adapter(g)
    try:
        g.factory.model_proposer=proposer
        review=g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
        assert len(calls)==1 and calls[0]['model']=='synthetic-model'
        assert not calls[0]['stream'] and not calls[0]['think']
        shared=json.loads(calls[0]['messages'][1]['content'])
        assert set(shared)=={'public_objective','search_topic','language'}
        assert shared['public_objective']==request()['objective'] and shared['language']=='en'
        raw=json.dumps(calls)
        for secret in (g.w.raw,g.w.actor.session_ref,g.w.ws,'primary.example','Reviewed advisory graph'):
            assert secret not in raw
        assert review['definition']==graph(g.w)
        assert review['model_calls']==1 and review['agent_calls']==0 and not review['automatic_execution']
        assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_typed_flows')
        result=g.factory.commit(g.w.ws,{'review_id':review['review_id'],'authorized':True,'notice':NOTICE},g.w.actor)
        assert result['id'] and not g.w.calls and not client.is_closed
    finally:client.close()


@pytest.mark.parametrize('endpoint',[
    'http://public.example','http://127.0.0.1:0','https://user:password@example.test',
    'https://example.test/api/chat','https://example.test?key=secret','https://example.test/#secret',
    'file:///tmp/model','https://example.test\\private','https://example.test/%2f',
])
def test_operator_endpoint_rejects_unsafe_or_noncanonical_origins(endpoint):
    with pytest.raises(WorkspaceInvalid):OllamaGraphProposer(endpoint,'synthetic-model')


def test_config_is_immutable_and_default_off_and_transport_guard_checks_before_send(growth):
    g=growth;proposer,calls,client=adapter(g)
    with pytest.raises(FrozenInstanceError):proposer.model='replacement-model'
    with pytest.raises(WorkspaceDenied):g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    envelope=[]
    g.factory.model_proposer=lambda value:envelope.append(value) or graph(g.w)
    g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    def denied():raise WorkspaceDenied()
    try:
        with pytest.raises(WorkspaceDenied):proposer.propose(envelope[0],_guard=denied)
        assert not calls
        with pytest.raises(WorkspaceInvalid):proposer(envelope[0]|{'private_draft':'unapproved'})
        assert not calls
    finally:client.close()


@pytest.mark.parametrize('mutation',['authority','adapter_aba','candidate'])
def test_concrete_model_response_cannot_survive_authority_or_adapter_or_candidate_change(growth,mutation):
    g=growth
    def change():
        if mutation=='adapter_aba':
            g.factory.model_proposer=None;g.factory.model_proposer=proposer
        else:
            with g.w.store.tx() as db:
                if mutation=='authority':db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?',(g.w.ws,))
                else:db.execute("UPDATE resources SET url='https://changed.example/mcp' WHERE id=?",(g.w.ids[0],))
    proposer,calls,client=adapter(g,change=change);g.factory.model_proposer=proposer
    try:
        with pytest.raises((WorkspaceConflict,WorkspaceDenied)):
            g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
        assert len(calls)==1 and not g.w.calls and not g.w.store.query('SELECT id FROM workspace_factory_reviews')
    finally:client.close()


@pytest.mark.parametrize('payload,headers,status',[
    ('{"done":true,"done":false,"message":{}}',{},200),
    ('{"done":NaN,"message":{}}',{},200),
    (json.dumps({'done':True,'message':{'role':'assistant','content':'{"nodes":[],"nodes":[]}'}}),{},200),
    (json.dumps({'done':True,'message':{'role':'assistant','content':'{"nodes":[]}','tool_calls':[{}]}}),{},200),
    (json.dumps({'done':False,'message':{'role':'assistant','content':'{"nodes":[]}'}}),{},200),
    ('x'*65537,{},200),
    ('{}',{'Content-Encoding':'gzip'},200),
    ('{}',{'Content-Type':'text/html'},200),
    ('{}',{'Location':'https://outside.test'},302),
])
def test_untrusted_http_response_never_creates_a_review_or_retries(growth,payload,headers,status):
    g=growth;proposer,calls,client=adapter(g,payload=payload,headers=headers,status=status)
    g.factory.model_proposer=proposer
    try:
        with pytest.raises((WorkspaceInvalid,WorkspaceConflict)):
            g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
        assert len(calls)==1 and not g.w.calls and not g.w.store.query('SELECT id FROM workspace_factory_reviews')
    finally:client.close()


@pytest.mark.parametrize('model,budget',[('gemma4-e4b-mlx',128),('google/gemma-4-E4B-it',128),('gemma3:1b',256),('gemma4-other',256)])
def test_e4b_query_budget_keeps_schema_and_non_thinking_json(model,budget):
    from scripts.benchmark_macmini_model import envelope
    calls=[]
    def respond(request):
        body=json.loads(request.content);calls.append(body)
        return httpx.Response(200,headers={'content-type':'application/json'},json={'model':model,'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'{"query":"Python"}'}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        p=OllamaGraphProposer('http://127.0.0.1:8000/v1',model,client,provider='openai')
        result=p.propose(envelope('Find Python documentation using exactly ten steps'))
    assert len(result['nodes'])==10
    assert calls[0]['max_tokens']==budget and calls[0]['temperature']==0
    assert calls[0]['chat_template_kwargs']=={'enable_thinking':False}
    assert calls[0]['response_format']['json_schema']['strict']

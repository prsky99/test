"""Bounded startup embedding warmup preserves natural-language retrieval."""
import json
from unittest.mock import Mock
import httpx
import pytest
from fastapi.testclient import TestClient
from agent_market.gateway.rag import RagEngine


def reply(request):
    return httpx.Response(200,json={'embeddings':[[1.0]+[0.0]*767]})


def test_warmup_is_bounded_coalesced_and_separate_from_customer_query_cache():
    requests=[]
    def transport(request):requests.append(json.loads(request.content));return reply(request)
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        engine=RagEngine(http=http)
        assert engine.warm_discovery_embedding()
        assert engine.warm_discovery_embedding()
        assert len(requests)==1 and requests[0]['keep_alive']==-1
        assert not engine._query_embeddings
        assert engine.discovery_embedding('Translate a product review into English')
        assert len(requests)==2 and requests[1]['input']==['Translate a product review into English']
        engine.embed_revision='changed-declared-model'
        assert engine.warm_discovery_embedding() and len(requests)==3


@pytest.mark.parametrize('status,body',[(503,{}),(200,{'embeddings':[[0.0]*768]}),(200,{'embeddings':[[1.0]]}),(302,{})])
def test_failed_or_invalid_warmup_never_claims_model_readiness(status,body):
    with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(status,json=body))) as http:
        engine=RagEngine(http=http)
        assert engine.warm_discovery_embedding() is False
        assert engine._embedding_warmed is None and not engine._query_embeddings


def test_disabled_embedding_has_no_warmup_network_call():
    with httpx.Client(transport=httpx.MockTransport(lambda req:pytest.fail('Disabled embeddings must stay offline'))) as http:
        engine=RagEngine(http=http);engine.embeddings_enabled=False
        assert not engine.warm_discovery_embedding()


@pytest.mark.parametrize('role,success',[('frontend',True),('frontend',False),('admin',True)])
def test_startup_warmup_precedes_ready_and_never_runs_on_admin(monkeypatch,role,success):
    from agent_market.config import GatewayConfig
    from agent_market.gateway.store import Store
    from agent_market.concierge.front import Front
    from agent_market.service_host import create_service_app,probe_token
    from tests.test_service_split import Control
    from tests.test_market import NET
    calls=[];app=None
    def warm(engine):
        assert not app.state.ready;calls.append(True);return success
    monkeypatch.setattr(RagEngine,'warm_discovery_embedding',warm)
    for method in ('bootstrap_snapshot','bootstrap_snapshot_json','live_counts'):
        monkeypatch.setattr(Front,method,lambda self:{})
    config=GatewayConfig(NET,None,':memory:','test-secret',1,3600,900,True,False,
                         concierge_llm='off',embedding_enabled=True)
    store=Store()
    try:
        app=create_service_app(config,role,store=store,control=Control(),release='synthetic-warmup')
        with TestClient(app) as client:
            assert calls==([True] if role=='frontend' else [])
            assert client.get('/internal/service/ready').status_code==404
            data=client.get('/internal/service/ready',headers={'x-service-probe':probe_token(Control.key)}).json()
            assert data['ready'] is True
            assert data['embedding_warmup']==(success if role=='frontend' else None)
    finally:store._db.close()


def test_concurrent_startup_calls_share_warmup_and_failed_warmup_can_retry():
    from concurrent.futures import ThreadPoolExecutor
    calls=[]
    def transport(request):
        calls.append(1)
        return httpx.Response(503,json={}) if len(calls)==1 else reply(request)
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        engine=RagEngine(http=http)
        assert not engine.warm_discovery_embedding()
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert all(pool.map(lambda _:engine.warm_discovery_embedding(),range(4)))
        assert len(calls)==2


def test_warmup_status_is_not_reused_after_its_short_coalescing_window(monkeypatch):
    from agent_market.gateway import rag
    clock=[100.0];monkeypatch.setattr(rag.time,'monotonic',lambda:clock[0])
    calls=[]
    def transport(request):calls.append(1);return reply(request)
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        engine=RagEngine(http=http)
        assert engine.warm_discovery_embedding()
        clock[0]=131.0
        assert engine.warm_discovery_embedding() and len(calls)==2


def test_task_model_ping_is_one_token_and_never_pauses_the_model_path():
    from agent_market.concierge.llm import LocalLLM
    bodies=[]
    def transport(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]})
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        model=LocalLLM('http://model.test:8000/v1','m',http=http,provider='openai',allow_http=True)
        assert model.ping() and bodies[0]['max_tokens']==1
    with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(503,json={}))) as http:
        model=LocalLLM('http://model.test:8000/v1','m',http=http,provider='openai',allow_http=True)
        assert model.ping() is False and model._broken_until==0.0


def test_busy_task_model_is_not_pinged():
    from agent_market.concierge.llm import LocalLLM
    with httpx.Client(transport=httpx.MockTransport(lambda req:pytest.fail('busy model must not be pinged'))) as http:
        model=LocalLLM('http://model.test:8000/v1','m',http=http,provider='openai',allow_http=True,concurrency=1)
        model._slots.acquire()
        assert model.ping()


def test_keep_warm_repeats_until_stopped():
    import threading
    from agent_market import service_host
    rounds=[]
    front=Mock(rag_engine=Mock(embeddings_enabled=True),language_model=Mock())
    front.rag_engine.warm_discovery_embedding.side_effect=lambda:rounds.append(1) or True
    front.language_model.ping.return_value=True
    assert service_host.warm_models(front)==(True,True)
    stop=threading.Event()
    worker=threading.Thread(target=service_host.keep_models_warm,args=(front,stop,0.01));worker.start()
    while len(rounds)<4:stop.wait(0.01)
    stop.set();worker.join(1)
    assert not worker.is_alive()
    assert service_host.warm_models(Mock(rag_engine=None,language_model=None))==(None,None)

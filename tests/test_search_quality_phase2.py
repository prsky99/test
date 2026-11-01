"""Projection freshness, ranking bounds, local repair and private telemetry."""
import json

import pytest

from agent_market.concierge.capability_retrieval import ProjectionCache
from agent_market.concierge.retrieval_policy import order
from agent_market.concierge.retrieval_metrics import capture
from agent_market.workflow_plan_repair import compile_with_repair
from agent_market.workspace_access import WorkspaceInvalid
from agent_market.search_quality import Recorder, dashboard, observed
from agent_market.gateway.store import Store
from tools.evaluate_discovery_workflow import context
from tests.test_dashboard import dash  # noqa: F401
from tests.test_admin_next import login


def resource(identity, *, tools=None, description='Weather information'):
    return {'id':identity,'name':'Public weather provider','description':description,
            'usage_full_tools':json.dumps(tools or []),'kind':'mcp'}


def test_projection_cache_is_content_addressed_and_immutable():
    cache=ProjectionCache(maximum=2)
    row=resource(1,tools=[{'name':'weather_forecast','description':'City weather forecast',
        'inputSchema':{'properties':{'city':{'default':'secret-marker'}}}}])
    first,hit=cache.project(row);assert not hit
    second,hit=cache.project(row);assert hit and first is second
    assert 'secret-marker' not in repr(first)
    row['usage_full_tools']='[{"name":"new_schema","description":"Changed weather schema"}]'
    changed,hit=cache.project(row);assert not hit and changed.revision!=first.revision
    cache.project(resource(2));cache.project(resource(3,description='Different'))
    assert len(cache.values)<=2


def test_projection_limits_and_bad_json_do_not_invent_tools():
    cache=ProjectionCache()
    for value in ('broken','['*1000,'x'*70000):
        row=resource(1);row['usage_full_tools']=value
        assert not cache.project(row)[0].tools
    small=ProjectionCache(maximum_bytes=10)
    small.project(resource(1,description='Very long description'))
    assert not small.values and small.bytes==0


@pytest.mark.parametrize('version,supported',[('0.7.4',False),('0.8.0',True),('0.8.2',True),('unknown',False)])
def test_ann_iteration_is_version_gated_and_transaction_local(version,supported):
    from agent_market.postgres_ann import configure_scan
    from types import SimpleNamespace
    commands=[]
    def execute(sql):
        commands.append(sql)
        return SimpleNamespace(fetchone=lambda:(version,))
    store=SimpleNamespace(_execute=execute,_vector_index=SimpleNamespace())
    assert configure_scan(store,filtered=True)is supported
    assert any('hnsw.iterative_scan'in q for q in commands)is supported
    assert all(q.startswith(('SELECT','SET LOCAL'))for q in commands)


def test_reranking_shadow_preserves_ids_and_active_is_bounded_stable():
    rows=[resource(1),resource(2,tools=[{'name':'weather_forecast','description':'Weather forecast for city temperatures'}])]
    with capture() as metrics:
        assert order('city weather forecast',rows,mode='shadow')==rows
    ranked=order('city weather forecast',rows,mode='on')
    assert [r['id']for r in ranked]==[2,1]
    assert metrics['counts']['rerank_order_changed']==1
    assert order('city weather forecast',rows,mode='on',budget_ms=-1)==rows
    tail=rows+[resource(i)for i in range(3,70)]
    assert order('city weather forecast',tail,mode='on')[40:]==tail[40:]
    assert order('Find the agent named Public weather provider',rows,mode='on')==rows


def test_unrelated_tools_are_not_merged_into_one_capability():
    rows=[resource(1,tools=[{'name':'city','description':'City directory'}, {'name':'weather','description':'Weather history'}]),
          resource(2,tools=[{'name':'city_weather','description':'City weather forecast'}])]
    assert order('city weather forecast',rows,mode='on')[0]['id']==2


def test_only_bounded_english_query_omission_can_be_locally_repaired():
    ctx=context('Find documentation about FastAPI and PostgreSQL using two steps')
    strict={'query':'FastAPI documentation'}
    with pytest.raises(WorkspaceInvalid):compile_with_repair(ctx,strict)
    value,count=compile_with_repair(ctx,strict,attempts=1)
    assert count==1 and len(value['nodes'])==2
    text=json.dumps(value)
    assert 'FastAPI' in text and 'PostgreSQL' in text
    assert strict=={'query':'FastAPI documentation'}
    assert compile_with_repair(ctx,{'query':'FastAPI PostgreSQL documentation'},attempts=1)[1]==0


@pytest.mark.parametrize('value',[{'query':'wrong','agents':[{'resource_id':999,'contract_id':'invented'}]},
    {'nodes':[{'contract_id':'docs.search.v1','input':{'query':'wrong'}}]}, {'query':None}, {'query':'wrong','secret':'x'}])
def test_malformed_or_invented_graphs_are_never_repaired(value):
    with pytest.raises(WorkspaceInvalid):compile_with_repair(context('Find Python documentation using two steps'),value,attempts=1)


def test_quality_metrics_are_bounded_and_never_keep_user_text():
    store=Store()
    try:
        store._service_role='frontend';r=Recorder(store);store._search_quality_recorder=r
        for _ in range(2051):
            r.record('explore','matched',1,{'stages_ms':{'lexical':.1},'counts':{'exact_shortcuts':1}})
        value=dashboard(store)
        row=next(x for x in value['rows']if x['surface']=='explore')
        assert row['requests']==2051 and row['sample_count']==2048 and row['p95_ms']==1
        assert value['production_slo_certified']is False
        assert not any(k in json.dumps(value)for k in ('"query":','"token":','"prompt":','"arguments":'))
    finally:store._db.close()


def test_observation_is_nested_safe_and_failure_does_not_change_response():
    store=Store()
    try:
        @observed('explore')
        def run(s,n):return run(s,n-1)if n else {'items':[1]}
        assert run(store,2)=={'items':[1]}
        assert store._search_quality_recorder.snapshot()['surfaces'][0]['requests']==1
        @observed('recommendation')
        def bad(s):raise ValueError('private-marker')
        with pytest.raises(ValueError):bad(store)
        assert 'private-marker'not in json.dumps(store._search_quality_recorder.snapshot())
    finally:store._db.close()


def test_admin_quality_screen_requires_personal_auth_and_returns_aggregate(dash):
    world,client=dash;store=world.store
    endpoint='/admin/api/v2/public/search-quality'
    assert client.get(endpoint).status_code in (401,403)
    r=Recorder(store);store._search_quality_recorder=r
    r.record('explore','matched',20,{'stages_ms':{},'counts':{}})
    response=client.get(endpoint,headers=login(client))
    assert response.status_code==200 and response.json()['rows']
    assert 'no-store'in response.headers['cache-control']

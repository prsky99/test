"""300 labeled synthetic acceptance tasks through real discovery and plan code.

Uses disposable data only. Fixture evidence is synthetic; no Provider business
execution, remote model, real customer or production SLA measurement occurs.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store
from agent_market.gateway.rag import RagEngine
from agent_market.capability_registry import Registry
from agent_market.collector import usage
from agent_market.infra.redis_hub import RedisHub
from agent_market.workflow_goal_policy import search_topic
from agent_market.workflow_model_proposer import compile_proposal
from agent_market.workspace_goal_coverage import missing
from agent_market.workspace_access import WorkspaceInvalid
from scripts.quality_fixture_context import context
from agent_market.search_quality import percentile

FAMILIES = {
 'weather': ('Weather forecast temperature city worldwide', 'weather_forecast', ['Weather forecast', 'City weather forecast', '날씨 예보', 'Weather forecast; exclude translation']),
 'docs': ('Search documentation for libraries and frameworks including Python JavaScript FastAPI PostgreSQL API references', 'documentation_search', ['Python documentation', 'FastAPI documentation', 'PostgreSQL documentation', 'Python documentation; exclude news']),
 'news': ('General news search headlines all topics technology AI sports world news', 'news_search', ['News headlines', 'Technology news', 'Sports news', 'News search; exclude translation']),
 'paper': ('Academic research papers scholarly journal articles search', 'research_paper_search', ['Research papers', 'Academic papers', 'Scholarly articles', 'Research papers; exclude news']),
 'translation': ('Text translation English Korean Japanese documents and sentences', 'text_translation', ['Text translation', 'Translate English text into Korean', 'Document translation', 'Text translation; exclude news']),
 'code': ('Code review pull requests security audit source code', 'code_review', ['Code review', 'Review pull requests', 'Code security audit', 'Code review; exclude news']),
 'transcription': ('Audio transcription speech to text subtitles timestamps Korean English', 'audio_transcription', ['Audio transcription', 'Transcribe audio with timestamps', 'Spoken interview into searchable text', 'Audio transcription; exclude translation']),
 'web': ('Web search internet websites public pages query', 'web_search', ['Web search', 'Search the web', '인터넷 검색', 'Web search; exclude news']),
 'finance': ('Stock equities Nasdaq NYSE earnings stock market price quotes', 'stock_quotes', ['Stock prices', 'Nasdaq stock quotes', 'Equity prices', 'Stock market prices; exclude crypto']),
}
UNKNOWN = ['Telepathic unicorn teleportation', 'Teleport a physical package instantly', 'Read unspoken private thoughts', 'Reverse time yesterday']


def tasks():
    cases = []
    prompts = [(family, q) for family, (_, _, queries) in FAMILIES.items() for q in queries] + [('unknown', q) for q in UNKNOWN]
    for surface, variants in [('explore', ('{}', 'Find {}', 'Please find {}')), ('chat', ('{}', 'Find {}'))]:
        for family, q in prompts:
            for n, pattern in enumerate(variants):
                cases.append({'name': surface+' '+family+' '+q+' '+str(n+1), 'surface': surface,
                              'query': pattern.format(q), 'expected_family': family})
    for subject in ('Python', 'Docker', 'Kubernetes', 'FastAPI', 'PostgreSQL', 'Terraform', 'JavaScript', 'Rust', 'TypeScript', 'Redis'):
        for count in (2,3,4,5,6):
            cases.append({'name':'Documentation '+subject+' '+str(count)+' steps','surface':'workflow',
                'query':f'Find documentation about {subject} using exactly {count} steps',
                'expected_contracts':['docs.search.v1']*count, 'expected':'accepted'})
    for subject in ('Python', 'Docker', 'Kubernetes', 'FastAPI', 'PostgreSQL', 'Terraform'):
        for limit in (1,2,3,4,5):
            cases.append({'name':'News then docs '+subject+' top '+str(limit),'surface':'workflow',
                'query':f'Find top {limit} news about {subject} then documentation using exactly two steps',
                'expected_contracts':['news.search.v1','docs.search.v1'], 'expected':'accepted'})
    for action in ('email the results','book a flight','translate the results','write a summary'):
        for subject in ('Python', 'Docker', 'Kubernetes', 'FastAPI', 'PostgreSQL'):
            cases.append({'name':'Unsupported '+action+' '+subject,'surface':'workflow',
                          'query':'Find documentation about '+subject+' and '+action, 'expected':'rejected'})
    assert len(cases)==300
    return cases


def seed(store):
    now=time.time(); gold={}
    for family,(description,tool,_) in FAMILIES.items():
        rid=store.upsert_resource({'key':'quality-fixture:'+family,'source':'synthetic-quality-fixture',
            'kind':'mcp','url':'https://quality-'+family+'.example/mcp','name':'Quality '+family,
            'description':description,'category':'docs_knowledge' if family=='docs' else 'general','price_usdc':0,'details':{}})
        specs=[{'name':tool,'description':description,'inputSchema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']},
                'annotations':{'readOnlyHint':True,'destructiveHint':False}}]
        compact=usage.compact_tools(specs)
        store.record_usage(rid,compact,usage.tools_hash(compact),{'tools':specs},None,{'ok':True},full_tools=specs)
        store.record_health(rid,'healthy',200,1,None,now+21600,auth_observed=False)
        store.record_evaluation(rid,{'score':95,'grade':'A','security':'ok','coverage':100})
        registry=Registry(store);version=registry.current(store.resource(rid))
        registry.record(version,scope='execution',outcome='succeeded',started=now-2,finished=now-1)
        gold[family]=rid
    return gold


def evaluate(store):
    gold=seed(store); rows=[]; request_times=defaultdict(list)
    offline=RedisHub();offline._closed=True
    engine=RagEngine();engine.embeddings_enabled=True
    engine.discovery_embedding=lambda query:None
    def no_http(*args,**kwargs): raise AssertionError('External HTTP is forbidden in quality fixtures.')
    with patch.object(RedisHub,'_instance',offline), patch.object(httpx.HTTPTransport,'handle_request',no_http):
        front=Front(store,rag_engine=engine)
        # Distinct synthetic callers keep the real limiter below each quota;
        # this benchmark measures retrieval, not a 600-request abuse campaign.
        front.security.resolve_ip=lambda request:request.headers.get('X-Quality-Fixture-IP','192.0.2.1')
        with TestClient(create_front_app(front)) as client:
            for mode in ('off','on'):
                engine.explore_rerank_mode=mode
                for ordinal,case in enumerate(tasks()):
                    started=time.perf_counter(); actual=[]; passed=False
                    if case['surface']=='explore':
                        response=client.get('/api/explore',params={'q':case['query'],'kind':'mcp','limit':20},headers={'X-Quality-Fixture-IP':'192.0.2.'+str(ordinal+1)})
                        if response.status_code==200: actual=[r['id']for r in response.json()['items']]
                        passed=response.status_code==200 and (not actual if case['expected_family']=='unknown' else gold[case['expected_family']] in actual[:3])
                    elif case['surface']=='chat':
                        response=client.post('/chat',json={'message':case['query'],'data':{'protocol':'mcp'}},headers={'X-Quality-Fixture-IP':'192.0.2.'+str(ordinal+1)})
                        if response.status_code==200:actual=[r['id']for r in response.json().get('data',{}).get('recommendations',[])]
                        passed=response.status_code==200 and (not actual if case['expected_family']=='unknown' else gold[case['expected_family']] in actual[:3])
                    else:
                        try:
                            if missing(case['query'],{'docs.search.v1','news.search.v1'}):raise WorkspaceInvalid()
                            plan=compile_proposal(context(case['query']),{'query':search_topic(case['query'])})
                            passed=case['expected']=='accepted' and [r['contract_id']for r in plan['nodes']]==case['expected_contracts']
                        except WorkspaceInvalid:passed=case['expected']=='rejected'
                    elapsed=(time.perf_counter()-started)*1000;request_times[(mode,case['surface'])].append(elapsed)
                    rows.append({'name':case['name'],'surface':case['surface'],'mode':mode,'passed':passed,'milliseconds':round(elapsed,1)})
    summary=[{'mode':m,'surface':s,'tasks':len(v),'p50_ms':percentile(v,.5),'p95_ms':percentile(v,.95)}for(m,s),v in request_times.items()]
    return {'scope':'labeled_synthetic_discovery_and_plan_acceptance','backend':getattr(store,'backend','sqlite'),
            'unique_tasks':300,'runs':600,'passed':sum(r['passed']for r in rows),'results':rows,'timing':summary,
            'gold_resources':gold,'provider_business_calls':0,'remote_model_calls':0,'actual_provider_execution_evaluated':False,
            'production_slo_certified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reference-sqlite',action='store_true',help='Explicit historical reference only; default is private PostgreSQL GIN/HNSW.')
    args=parser.parse_args()
    if not args.reference_sqlite:
        from scripts.rehearse_quality_native_indexes import run
        result=run()
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:result[k]for k in ('unique_tasks','runs','passed','retrieval_backend')}))
        return 0
    with tempfile.TemporaryDirectory(prefix='quality-acceptance-') as folder:
        store=Store(str(Path(folder)/'synthetic.sqlite3'))
        try: result=evaluate(store)
        finally:store._db.close()
    result['source_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in
        [Path(__file__),Path('agent_market/concierge/retrieval_policy.py'),Path('agent_market/workflow_goal_policy.py')]}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k]for k in ('unique_tasks','runs','passed','provider_business_calls','production_slo_certified')}))
    return 0 if result['passed']==result['runs'] else 1


if __name__=='__main__':raise SystemExit(main())

"""Full adoption contracts on an owned schema; no live accounts or providers."""
import json
import time
from types import SimpleNamespace


def contracts(connect,factory):
    import httpx
    from agent_market.agent_access.storage import migrate,transaction,enqueue
    from agent_market.agent_access.service import for_front
    from agent_market.agent_access.tasks import NOTICE
    from agent_market.capability_registry import Registry
    from agent_market.capability_contracts import validate
    from agent_market.collector import usage
    from agent_market.concierge.front import Front,create_front_app
    from agent_market.concierge.proxy import McpProxy
    from fastapi.testclient import TestClient
    from tests.test_workflow_fallback import tool,output
    from tests.test_mcp_proxy import MockRemoteMcp
    connection=connect();store=factory(connection,workflow_key=b'b'*32)
    front=None;checks={};calls=[]
    try:
        migrate(store);assert migrate(store)['tables']==6
        specs=[tool()];remote=MockRemoteMcp(specs,call_result=output())
        original=remote.handle_request
        def handle(request):
            if json.loads(request.content or'{}').get('method')=='tools/call':calls.append(True)
            return original(request)
        remote.handle_request=handle
        http=httpx.Client(transport=remote)
        proxy=McpProxy(store,allow_private=True,http=http)
        front=Front(store);front.proxy=proxy;front.workflows.proxy=proxy
        core=for_front(front)
        ids=[]
        for index in range(2):
            rid=store.upsert_resource({'key':'synthetic-adoption-'+str(index),'source':'mcp-registry','kind':'mcp',
                'url':'https://adoption-'+str(index)+'.example/mcp','name':'Documentation library '+str(index),
                'description':'Search documentation for any library or framework','category':'dev_tools','price_usdc':0,'details':{}})
            store.record_usage(rid,usage.compact_tools(specs),usage.tools_hash(usage.compact_tools(specs)),{},None,None,full_tools=specs)
            store.record_health(rid,'healthy',200,1,None,time.time()+21600,auth_observed=False)
            store.record_evaluation(rid,{'score':95,'grade':'A','security':'ok','coverage':100})
            version=Registry(store).approve(store.resource(rid),'docs.search.v1','search_docs')
            arguments={'query':'documentation','language':'en','limit':2}
            start=time.time();result=proxy.execute(rid,'search_docs',arguments,public=True)
            assert result['ok'];validate('docs.search.v1',arguments,result['result']['structuredContent'])
            Registry(store).record(version,scope='contract',outcome='succeeded',started=start,finished=time.time(),contract_id='docs.search.v1',dataset='adoption-fixture-v1')
            ids.append(rid)
        calls.clear();visitor=front.book.create('rest','SyntheticAdoptionNative','synthetic-adoption-native')
        class Identity:
            def _session(self,db,reference,customer):
                if(reference,customer)!=('fixture-session','fixture-customer'):raise ValueError('invalid fixture')
                return {'id':reference}
        core.tasks.identity_core=Identity()
        prepared=core.tasks.prepare(visitor.id,ids[0],'docs.search.v1',arguments)
        assert not calls
        grant=core.tasks.authorize(visitor.id,prepared['preparation_id'],SimpleNamespace(customer_id='fixture-customer',session_ref='fixture-session'),
            {'authorized':True,'input_sharing':True,'notice':NOTICE})['grant']
        run=core.tasks.execute(visitor.id,prepared['preparation_id'],grant,'native-once')
        assert run['status']=='succeeded',run
        assert core.tasks.execute(visitor.id,prepared['preparation_id'],grant,'native-once')==run
        assert len(calls)==1
        checks['native_single_use_encrypted_prepare_grant_idempotent_execution']=True
        stored=store.query('SELECT * FROM adoption_preparations WHERE id=? AND owner=?',(prepared['preparation_id'],visitor.id))[0]
        assert 'documentation'not in stored['sealed']
        checks['native_preparation_plaintext_not_stored']=True
        core.events.publish();feed=core.events.feed('mcp',limit=1)
        assert feed['items']and feed['_next_cursor']
        second=core.events.feed('mcp',feed['_next_cursor'],1)
        assert second['items']and second['items'][0]['id']!=feed['items'][0]['id']
        checks['native_committed_cursor_and_event_page']=True
        selected=core.catalog.discover({'task':'public documentation search','protocol':'mcp'})
        assert selected['items']and len(json.dumps(selected).encode())<=8192
        digest=selected['selected_contract']['schema_digest']
        cached=core.catalog.discover({'task':'public documentation search','protocol':'mcp','known_schema_digests':[digest]})
        assert cached['schema_cached']and'tools_schema'not in cached['selected_contract']
        checks['native_compact_batch_contract_and_schema_cache']=True
        client=TestClient(create_front_app(front))
        first=client.get('/api/feed/verified.json?protocol=mcp')
        assert first.status_code==200
        assert client.get('/api/feed/verified.json?protocol=mcp',headers={'If-None-Match':'W/'+first.headers['etag']}).status_code==304
        category=client.get('/agents/category/dev_tools')
        assert category.status_code==200 and 'Documentation library' in category.text
        assert 'adoption-0.example' not in category.text
        assert client.head('/llms.txt').status_code==200
        assert client.head('/agents/category/dev_tools').content==b''
        checks['native_bounded_category_current_evidence_and_document_head']=True
        checks['native_http_feed_conditional_and_category_page']=True
        from agent_market.concierge.task_updates import NOTICE_VERSION,DESTINATION_NOTICE
        watch=front.updates.create(visitor.id,{'task':'public documentation search','protocol':'mcp','channel':'poll',
            'authority':True,'task_updates':True,'notice_version':NOTICE_VERSION,'destination_confirmed':True,
            'destination_notice_version':DESTINATION_NOTICE})
        dependency=core.events.dependency(visitor.id,watch['id'],ids[0],authorized=True,notice='agent-dependency-watch-v1',
            contract_id='docs.search.v1',event_types=['verified','health_changed'])
        assert dependency['version_id']and dependency['contract_id']=='docs.search.v1'
        assert core.events.notify()==1 and core.events.notify()==0
        store.record_health(ids[0],'unreachable',503,1,None,time.time()+21600,auth_observed=False)
        assert core.events.publish()and core.events.notify()==1
        front.updates.action(visitor.id,watch['id'],'stop')
        assert core.events.notify()==0
        checks['native_dependency_version_contract_event_filter_dedupe_withdrawal']=True
        from tests.report_fixtures import execution_report
        from agent_market.concierge.report_evidence import measured_report
        report_ids=[execution_report(store,rid,time.time(),title='Synthetic batch proof',
            slug='synthetic-batch-'+str(rid))for rid in ids]
        original_execute=store._execute;queries=[]
        def counted(sql,*args,**kwargs):
            queries.append(sql)
            return original_execute(sql,*args,**kwargs)
        store._execute=counted
        try:
            before={rid:store.get_test_report(rid)for rid in report_ids}
            unbatched_queries=len(queries);queries.clear()
            batched,view=store.recommendation_report_evidence(report_ids)
            batched_queries=len(queries)
        finally:store._execute=original_execute
        assert 0<batched_queries<=4 and unbatched_queries>batched_queries, (batched_queries,unbatched_queries)
        for report in batched.values():
            assert measured_report(report,store.resource(report['resource_id']),view,time.time())
            assert before[report['id']]['execution_measured']
        checks['native_report_evidence_batch_preserves_validation']=True
        baseline_method=store.recommendation_report_evidence
        store.recommendation_report_evidence=None
        try:baseline_ids=[r['id']for r in front.rec.search('documentation',kind='mcp',limit=3)]
        finally:store.recommendation_report_evidence=baseline_method
        assert baseline_ids==[r['id']for r in front.rec.search('documentation',kind='mcp',limit=3)]
        checks['native_batched_and_unbatched_recommendations_identical']=True
        version=Registry(store).current(store.resource(ids[-1]))
        stamp=time.time()
        Registry(store).record(version,scope='execution',outcome='failed',started=stamp,finished=stamp)
        fresh,fresh_view=store.recommendation_report_evidence(report_ids)
        changed=next(r for r in fresh.values()if r['resource_id']==ids[-1])
        assert not measured_report(changed,store.resource(ids[-1]),fresh_view,time.time())
        checks['native_report_batch_rejects_newer_execution_failure']=True
        assert all(checks.values())
        return {'checks':checks,'external_provider_calls':0,'synthetic_provider_calls':len(calls),'operating_accounts_used':False,
            'report_validation_queries':{'unbatched':unbatched_queries,'batched':batched_queries,'reports':len(report_ids)}}
    finally:
        if front:front.book.close()
        store.close();connection.close()


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--run',action='store_true',required=True);parser.parse_args()
    from scripts.rehearse_b2a_retention_postgres import schema_rehearsal
    print(json.dumps(schema_rehearsal(adoption=True),sort_keys=True))


if __name__=='__main__':main()

"""Verify local schema recovery and actual fixture execution on owned PostgreSQL."""
import time


def contracts(connect,factory):
    import httpx
    from agent_market.capability_registry import Registry,known_schema_failure
    from agent_market.concierge.proxy import McpProxy
    from agent_market.owned_data_agents.activation import install,check_sources
    from agent_market.owned_data_agents.catalog import SPECS
    from agent_market.owned_data_agents.engine import DataAgents
    from tests.test_owned_data_agents import source
    store=factory(connect(),workflow_key=b'q'*32);checks={}
    http=httpx.Client(transport=httpx.MockTransport(source))
    try:
        resources=install(store,'https://agentconcierge.biz')
        # Reproduce a reviewed old local pin. This is a disposable fixture, never an operating update.
        with store.tx():
            store._execute("UPDATE resources SET details='{}',content_hash='legacy-qa7-fixture' WHERE source='agentconcierge-owned'")
        registry=Registry(store);rid=resources['technology-news'];now=time.time()
        old=registry.current(store.resource(rid))
        registry.approve(store.resource(rid),'news.search.v1',SPECS['technology-news']['tool'])
        registry.record(old,scope='execution',outcome='failed',started=now-1,finished=now,code='SCHEMA_CHANGED')
        assert known_schema_failure(store,store.resource(rid))
        install(store,'https://agentconcierge.biz')
        new=registry.current(store.resource(rid))
        assert new['id']!=old['id'] and not known_schema_failure(store,store.resource(rid))
        assert not registry.projection(store.resource(rid))['connection_readiness']['verified_callable']
        checks['failed_old_pin_preserved_and_no_fake_verification']=True
        core=store._owned_data_engine=DataAgents(http=http)
        check_sources(store,core,resources);proxy=McpProxy(store)
        for identity,spec in SPECS.items():
            result=proxy.execute(resources[identity],spec['tool'],dict(spec['example']),public=True)
            assert result['ok'],(identity,result)
            assert result['result']['structuredContent']['agent']==identity
        checks['seven_registered_sources_execute_with_exact_schemas']=True
        assert registry.projection(store.resource(rid))['connection_readiness']['verified_callable']
        checks['actual_completed_execution_establishes_verification']=True
        install(store,'https://agentconcierge.biz')
        assert registry.current(store.resource(rid))['id']==new['id']
        checks['repeat_install_keeps_the_same_version']=True
        return {'checks':checks}
    finally:
        http.close();store.close()

"""A rejected full contract stays blocked across an unrelated health recovery."""
import copy
import json
import time

from agent_market.capability_registry import Registry, known_schema_failure
from agent_market.collector import usage
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_managed_agent_gateway import managed, rpc  # noqa: F401


def survey(store,rid,tools):
    compact=usage.compact_tools(tools)
    store.record_usage(rid,tools=compact,digest=usage.tools_hash(compact),guide={},
                       changes=None,trial=None,full_tools=tools)


def drift(managed):
    store,front,client,_,rid,calls,remote=managed
    original=copy.deepcopy(remote.tools)
    original[0]['outputSchema']={'type':'object','properties':{'reading':{'type':'string'}}}
    survey(store,rid,original)
    remote.tools=copy.deepcopy(original)
    remote.tools[0]['outputSchema']['properties']['source']={'type':'string'}
    result=front.proxy.execute(rid,'get_weather',{'city':'Tokyo'})
    assert result['error_code']=='SCHEMA_CHANGED' and not result['ok']
    assert not any(json.loads(call.content or'{}').get('method')=='tools/call'for call in calls)
    return store,front,client,rid,calls,remote


def test_health_recovery_and_evidence_expiry_do_not_erase_schema_failure(managed):
    store,front,client,rid,calls,_=drift(managed)
    assert known_schema_failure(store,store.resource(rid))
    with store.tx()as db:
        db.execute("UPDATE resources SET health_status='healthy',last_status_code=200 WHERE id=?",(rid,))
        db.execute('UPDATE capability_evidence SET expires=?',(time.time()-1,))
    assert known_schema_failure(store,store.resource(rid))
    before=len(calls)
    from agent_market.concierge.execution_availability import resource_execution_availability
    availability=resource_execution_availability(store.resource(rid),store=store,kind='mcp',
        tool='get_weather',arguments={'city':'Tokyo'})
    assert not availability['available'] and availability['reason_code']=='SCHEMA_CHANGED'
    direct=front.proxy.execute(rid,'get_weather',{'city':'Tokyo'})
    assert direct['error_code']=='SCHEMA_CHANGED' and not direct['ok']
    result=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}).json()
    assert result['error_code']=='SCHEMA_CHANGED' and not result.get('execution_succeeded')
    native=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}})
    assert native.status_code == 400 and 'schema' in native.json()['detail']
    assert len(calls)==before


def test_reviewed_new_full_schema_has_a_new_version_and_retains_old_history(managed):
    store,front,client,rid,calls,remote=drift(managed)
    registry=Registry(store);old=registry.current(rid)
    survey(store,rid,remote.tools)
    with store.tx()as db:db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
    new=registry.current(rid)
    assert old['id']!=new['id'] and not known_schema_failure(store,store.resource(rid))
    result=front.proxy.execute(rid,'get_weather',{'city':'Tokyo'})
    assert result['ok'] and result['hash_verified']
    assert sum(json.loads(call.content or'{}').get('method')=='tools/call'for call in calls)==1
    assert store.query("SELECT 1 FROM capability_evidence WHERE version_id=? AND code='SCHEMA_CHANGED'",(old['id'],))


def test_unrelated_failure_is_not_a_contract_change_marker(managed):
    store,_,_,_,rid,_,_=managed
    registry=Registry(store);version=registry.current(rid);now=time.time()
    registry.record(version,scope='execution',outcome='failed',started=now,finished=now,code='UPSTREAM_NETWORK')
    assert not known_schema_failure(store,store.resource(rid))

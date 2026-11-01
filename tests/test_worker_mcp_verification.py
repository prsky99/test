"""Signed Worker completion qualifies discovery once without a second dispatch."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_market.concierge.discovery_state import execution_state
from agent_market.edge_gateway.config import EdgeError
from tests.test_edge_gateway import edge, catalog, ORIGIN, service_request  # noqa: F401
from tests.test_edge_gateway_catalog import enable, mcp_resource


def claimed(edge, catalog, monkeypatch):
    enable(edge,monkeypatch);rid=mcp_resource(edge,catalog)
    version=execution_state(edge.store,edge.store.resource(rid))['version_id']
    with edge.store.tx()as db:db.execute('DELETE FROM capability_evidence WHERE version_id=?',(version,))
    value={'resource_id':rid,'input':{'tool':'get_weather','arguments':{'city':'Tokyo'}},
        'idempotency_key':'worker-evidence','run_authority':True,'sharing_authority':True}
    grant=edge.service.prepare(edge.principal,ORIGIN,value)
    binding=edge.service.claim(grant['access_token'],ORIGIN,grant['run_id'],value['input'],'worker')
    return rid,grant,binding


@pytest.mark.parametrize('outcome',['succeeded','failed','outcome_unknown'])
def test_signed_worker_completion_projects_current_evidence_once(edge,catalog,monkeypatch,outcome):
    rid,grant,binding=claimed(edge,catalog,monkeypatch)
    body={'run_id':grant['run_id'],'attempt_id':binding['attempt_id'],'outcome':outcome}
    assert service_request(edge,'complete',body).status_code==200
    state=execution_state(edge.store,edge.store.resource(rid))
    assert state['verified']is(outcome=='succeeded')
    evidence=edge.store.query("SELECT * FROM capability_evidence WHERE dataset_version='edge-worker-execution-v1'")
    assert len(evidence)==1
    assert evidence[0]['scope']=='execution' and evidence[0]['version_id']==state['version_id']
    assert evidence[0]['outcome']==('unknown'if outcome=='outcome_unknown'else outcome)
    original=(evidence[0]['id'],evidence[0]['finished'],evidence[0]['expires'])
    edge.clock[0]+=30
    assert service_request(edge,'complete',body).status_code==200
    evidence=edge.store.query("SELECT * FROM capability_evidence WHERE dataset_version='edge-worker-execution-v1'")
    assert len(evidence)==1 and (evidence[0]['id'],evidence[0]['finished'],evidence[0]['expires'])==original
    assert not edge.calls


def test_late_schema_change_does_not_verify_new_connection(edge,catalog,monkeypatch):
    rid,grant,binding=claimed(edge,catalog,monkeypatch)
    before=execution_state(edge.store,edge.store.resource(rid))['version_id']
    tools=json.loads(edge.store.resource(rid)['usage_full_tools']);tools[0]['description']+=' Changed contract.'
    with edge.store.tx()as db:db.execute('UPDATE resources SET usage_full_tools=? WHERE id=?',(json.dumps(tools),rid))
    edge.service.finish(grant['run_id'],binding['attempt_id'],'succeeded')
    state=execution_state(edge.store,edge.store.resource(rid))
    assert state['version_id']!=before and state['verified']is False
    assert not edge.store.query("SELECT * FROM capability_evidence WHERE dataset_version='edge-worker-execution-v1'")
    assert not edge.calls


def test_failed_projection_can_recover_without_dispatch_or_fresh_timestamps(edge,catalog,monkeypatch):
    rid,grant,binding=claimed(edge,catalog,monkeypatch)
    from agent_market.capability_registry import Registry
    with monkeypatch.context()as patch:
        patch.setattr(Registry,'record',lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('isolated projection failure')))
        with pytest.raises(RuntimeError):edge.service.finish(grant['run_id'],binding['attempt_id'],'succeeded')
    row=edge.store.query('SELECT * FROM edge_gateway_runs WHERE id=?',(grant['run_id'],))[0]
    assert row['state']=='succeeded'
    edge.clock[0]+=30
    edge.service.finish(grant['run_id'],binding['attempt_id'],'succeeded')
    evidence=edge.store.query("SELECT * FROM capability_evidence WHERE dataset_version='edge-worker-execution-v1'")
    assert len(evidence)==1 and evidence[0]['finished']==row['finished'] and not edge.calls


def test_unauthenticated_worker_completion_cannot_publish_evidence(edge,catalog,monkeypatch):
    rid,grant,binding=claimed(edge,catalog,monkeypatch)
    response=edge.client.post('/api/edge-gateway-internal/v1/complete',json={
        'run_id':grant['run_id'],'attempt_id':binding['attempt_id'],'outcome':'succeeded'})
    assert response.status_code==401
    assert not execution_state(edge.store,edge.store.resource(rid))['verified']
    with pytest.raises(EdgeError):edge.service.finish(grant['run_id'],'ea_'+'0'*32,'succeeded')
    assert not edge.calls


def test_parallel_completion_notices_publish_one_original_evidence(edge,catalog,monkeypatch):
    rid,grant,binding=claimed(edge,catalog,monkeypatch)
    def finish(_):
        return edge.service.finish(grant['run_id'],binding['attempt_id'],'succeeded')
    with ThreadPoolExecutor(max_workers=4)as pool:
        assert all(r['ok']for r in pool.map(finish,range(8)))
    evidence=edge.store.query("SELECT * FROM capability_evidence WHERE dataset_version='edge-worker-execution-v1'")
    assert len(evidence)==1 and execution_state(edge.store,edge.store.resource(rid))['verified']
    assert not edge.calls

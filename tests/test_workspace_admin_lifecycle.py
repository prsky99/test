"""Existing real workflow cores with the new transactional recording enabled."""
# ruff: noqa: F401,F811
import json
import time

import pytest

from agent_market.workspace_admin_events import drain, migrate
from agent_market.workspace_admin_control import WorkspaceAdminControl
from tests.test_customer_authoring import authoring, release_world, private_api, execute_test
from tests.test_workspace_growth import growth
from tests.test_workspace_typed_flows import typed_world, routing, save, run
from tests.test_workspace_model_proposal import request, response


def test_enabled_customer_execution_records_source_truth_without_outputs(authoring):
    x=authoring;migrate(x.w.store,x.identity.key)
    ops=WorkspaceAdminControl(x.identity,x.access)
    result=execute_test(x)
    assert result['status']=='succeeded'
    assert drain(x.w.store)['projected']>=3
    events=ops.events(x.actor,x.customer.customer_id)['events']
    assert any(e['event_type']=='execution.succeeded' for e in events)
    detail=ops.operation(x.actor,result['id'])
    assert detail['authoritative_state']['status']=='succeeded'
    assert 'output' not in json.dumps(detail)
    assert x.raw_cookie not in json.dumps(detail)


@pytest.mark.parametrize('failure',[False,True])
def test_enabled_model_generation_records_bounded_pair_without_objective(growth,failure):
    g=growth;migrate(g.w.store,b'm'*32)
    def model(envelope):
        if failure:raise RuntimeError('Private provider error must not be recorded')
        return response(envelope)
    g.factory.model_proposer=model
    if failure:
        from agent_market.workspace_access import WorkspaceConflict
        with pytest.raises(WorkspaceConflict):g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    else:
        assert g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)['state']=='review_required'
    assert drain(g.w.store)['projected']>=2
    raw=g.w.store.query("SELECT event_type,payload FROM workspace_admin_events WHERE event_type LIKE 'generation.%'")
    assert len(raw)==2
    assert raw[-1]['event_type']==('generation.unknown' if failure else 'generation.completed')
    assert request()['objective'] not in str(raw) and 'Private provider error' not in str(raw)


def test_enabled_typed_chain_records_final_source_and_node_status(typed_world):
    w=typed_world;migrate(w.store,b'm'*32)
    flow=save(w);response,_=run(w,flow);result=response['run']
    assert result['status']=='succeeded'
    drain(w.store)
    events=w.store.query("SELECT event_type,object_id,outcome FROM workspace_admin_events WHERE event_type='execution.succeeded'")
    assert events and events[0]['object_id']==result['id']

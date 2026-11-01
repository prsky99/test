"""Configured advisory proposals share minimal public input and never execute."""
from copy import deepcopy
import json
import threading

import pytest

from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from agent_market.workspace_app_factory import MODEL_NOTICE, MODEL_PROFILE, NOTICE
from agent_market.workspace_typed_flows import LIMITS as TYPED_LIMITS
from tests.test_workspace_growth import growth
from tests.test_workspace_typed_flows import typed_world, routing


def request(**changes):
    return {'objective':'Find public documentation and current reference material',
            'name':'Reviewed advisory graph', 'authorized':True, 'notice':MODEL_NOTICE,
            'data_attestation':'public_objective_without_personal_or_private_data', **changes}


def response(envelope):
    candidates=[item for item in envelope['candidates'] if item['contract_id']=='docs.search.v1']
    return {'nodes':[dict(candidate,input={'query':'Public documentation','language':'en','limit':2})
                     for candidate in candidates[:2]]}


def test_model_proposal_is_default_off_and_never_reinterprets_bounded_intent(growth):
    g=growth
    options=g.factory.options(g.w.ws,g.w.actor)
    assert options['model_proposal_configured'] is False
    with pytest.raises(WorkspaceDenied):g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_factory_reviews')
    bounded=g.factory.prepare_intent(g.w.ws,{'purpose':'Build an arbitrary future service','name':'Public task',
        'resource_ids':None,'from_utc':None,'criteria':[]},g.w.actor)
    assert bounded['state']=='needs_details'


def test_model_receives_only_public_objective_approved_candidate_metadata_and_public_schemas(growth):
    g=growth; seen=[]
    def proposer(envelope):
        assert not g.w.store._db.in_transaction
        seen.append(deepcopy(envelope)); return response(envelope)
    g.factory.model_proposer=proposer
    review=g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    assert len(seen)==1 and set(seen[0])=={'profile','objective','candidates','contracts','limits','output_profile'}
    assert seen[0]['profile']==MODEL_PROFILE
    assert all(set(item)=={'resource_id','contract_id'} for item in seen[0]['candidates'])
    raw=json.dumps(seen[0])
    for private in (g.w.ws,g.w.raw,g.w.actor.session_ref,'https://primary.example','https://alternate.example','Reviewed advisory graph'):
        assert private not in raw
    assert review['state']=='review_required' and review['model_calls']==1 and review['agent_calls']==0
    assert review['general_natural_language_planner'] is False and review['automatic_execution'] is False
    assert all(node['bindings']=={} and node['when'] is None for node in review['definition']['nodes'])
    assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_typed_flows')
    saved=g.factory.commit(g.w.ws,{'review_id':review['review_id'],'authorized':True,'notice':NOTICE},g.w.actor)
    assert saved['id'] and not g.w.calls
    assert len(g.w.store.query('SELECT id FROM workspace_typed_flows'))==1
    assert g.factory.commit(g.w.ws,{'review_id':review['review_id'],'authorized':True,'notice':NOTICE},g.w.actor)['replayed']


@pytest.mark.parametrize('change',[
    {'authorized':False},{'notice':'implicit'},{'data_attestation':'private_data_allowed'},
    {'objective':'Fetch https://private.example/path'},{'objective':'Bearer synthetic-token'},
    {'objective':'Ask person@example.com'},{'objective':'Ask person%40example.com'},
    {'objective':'Ask person&#64;example.com'},{'objective':'Read /Users/example/private.json'}])
def test_private_or_unapproved_objective_is_rejected_before_any_model_call(growth,change):
    g=growth;calls=[];g.factory.model_proposer=lambda envelope:calls.append(envelope) or response(envelope)
    with pytest.raises(WorkspaceInvalid):g.factory.prepare_model_proposal(g.w.ws,request(**change),g.w.actor)
    assert calls==[] and not g.w.calls


@pytest.mark.parametrize('mutation',['foreign_resource','contract','extra_tool','bindings','url','secret','too_many','single_node','response_metadata'])
def test_model_output_cannot_inject_tools_urls_authority_or_unreviewed_graph_operations(growth,mutation):
    g=growth
    def proposer(envelope):
        value=response(envelope)
        if mutation=='foreign_resource':value['nodes'][0]['resource_id']=2147483647
        elif mutation=='contract':value['nodes'][0]['contract_id']='shell.execute.v1'
        elif mutation=='extra_tool':value['nodes'][0]['tool']='delete_files'
        elif mutation=='bindings':value['nodes'][0]['bindings']={'query':{'node_id':'remote','path':['secret']}}
        elif mutation=='url':value['nodes'][0]['input']['query']='Fetch https://private.example'
        elif mutation=='secret':value['nodes'][0]['input']['token']='synthetic-secret'
        elif mutation=='too_many':value['nodes']*=TYPED_LIMITS['nodes']//len(value['nodes'])+1
        elif mutation=='single_node':value['nodes']=value['nodes'][:1]
        else:value['approved']=True
        return value
    g.factory.model_proposer=proposer
    with pytest.raises((WorkspaceInvalid,WorkspaceDenied,WorkspaceConflict)):
        g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_factory_reviews')


@pytest.mark.parametrize('mutation',['authority','schema','adapter'])
def test_model_response_cannot_publish_a_review_after_current_authority_or_candidate_change(growth,mutation):
    g=growth
    def proposer(envelope):
        value=response(envelope)
        if mutation=='authority':
            with g.w.store.tx() as db:db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?',(g.w.ws,))
        elif mutation=='schema':
            with g.w.store.tx() as db:db.execute("UPDATE resources SET url='https://changed.example/mcp' WHERE id=?",(value['nodes'][0]['resource_id'],))
        else:g.factory.model_proposer=None
        return value
    g.factory.model_proposer=proposer
    with pytest.raises((WorkspaceConflict,WorkspaceDenied)):
        g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    assert not g.w.store.query('SELECT id FROM workspace_factory_reviews') and not g.w.calls


def test_model_timeout_creates_no_review_and_does_not_claim_remote_cancellation(growth,monkeypatch):
    g=growth;finished=threading.Event()
    def delayed(envelope):
        finished.wait(2);return response(envelope)
    g.factory.model_proposer=delayed
    monkeypatch.setattr('agent_market.workspace_app_factory.MODEL_SECONDS',0.01)
    try:
        with pytest.raises(WorkspaceConflict):g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
        assert not g.w.store.query('SELECT id FROM workspace_factory_reviews') and not g.w.calls
    finally:finished.set()


def test_disabled_model_source_cannot_commit_an_old_advisory_review(growth):
    g=growth;g.factory.model_proposer=response
    review=g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    g.factory.model_proposer=None
    with pytest.raises(WorkspaceDenied):
        g.factory.commit(g.w.ws,{'review_id':review['review_id'],'authorized':True,'notice':NOTICE},g.w.actor)
    assert not g.w.store.query('SELECT id FROM workspace_typed_flows') and not g.w.calls


@pytest.mark.parametrize('invalid',['cycle','nonfinite','oversize'])
def test_model_response_is_bounded_plain_json_before_review_validation(growth,invalid):
    g=growth
    def proposer(envelope):
        value=response(envelope)
        if invalid=='cycle':value['nodes'][0]['input']['query']=value
        elif invalid=='nonfinite':value['nodes'][0]['input']['limit']=float('nan')
        else:value['nodes'][0]['input']['query']='x'*20000
        return value
    g.factory.model_proposer=proposer
    with pytest.raises(WorkspaceInvalid):g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    assert not g.w.store.query('SELECT id FROM workspace_factory_reviews') and not g.w.calls


def test_model_proposal_staff_api_requires_current_scope_origin_and_separate_save(growth):
    g=growth;g.factory.model_proposer=response
    path=g.base+'/app-factory/model-proposals'
    assert g.client.post(path,json=request()).status_code==401
    assert g.client.post(path,json=request(),headers=g.headers|{'Origin':'https://outside.test'}).status_code==403
    assert g.client.post(path,json=request(model_url='https://untrusted.example'),headers=g.headers).status_code==400
    value=g.client.post(path,json=request(),headers=g.headers)
    assert value.status_code==200,value.text
    assert value.headers['cache-control']=='no-store' and value.json()['result']['state']=='review_required'
    assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_typed_flows')

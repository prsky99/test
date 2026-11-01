import pytest

from agent_market.workspace_access import WorkspaceInvalid
from tests.test_workspace_growth import growth
from tests.test_workspace_typed_flows import typed_world,routing,graph
from tests.test_workspace_model_proposal import request


def test_model_can_propose_declared_branch_and_projection_for_exact_review(growth):
    g=growth;g.factory.model_proposer=lambda envelope:graph(g.w)
    result=g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    assert result['definition']['nodes'][1]['when']['path']==['partial']
    assert result['definition']['nodes'][1]['bindings']['query']['path']==['items',0,'title']
    assert result['agent_calls']==0 and not g.w.calls


@pytest.mark.parametrize('path',['/nodes/0/tool','/nodes/0/input/query','/nodes/0/__proto__','/nodes/6/input'])
def test_support_patch_never_allows_arbitrary_paths(growth,path):
    g=growth;flow=g.w.core.save(g.w.ws,{'flow_id':None,'revision':0,'name':'Original task','definition':graph(g.w)},g.w.actor)
    with pytest.raises(WorkspaceInvalid):
        g.factory.prepare_support_patch(g.w.ws,{'flow_id':flow['id'],'revision':1,'version_id':flow['version_id'],
            'name':'Reviewed change','patch':[{'op':'replace','path':path,'value':{}}],
            'documents':['safe-change-review']},g.w.actor)
    assert not g.w.calls


def test_listed_subjects_become_one_search_step_each(growth):
    # 2026-10-21: "documentation for 10 topics: ..." produced a two-step plan.
    g=growth;g.factory.model_proposer=lambda envelope:graph(g.w)
    body=request()|{'objective':'Find documentation for 3 topics: Docker, Kubernetes and Terraform'}
    result=g.factory.prepare_model_proposal(g.w.ws,body,g.w.actor)
    nodes=result['definition']['nodes']
    assert [node['input']['query'] for node in nodes]==['Docker documentation','Kubernetes documentation','Terraform documentation']
    assert all(node['after']==[] and node['bindings']=={} for node in nodes)
    approved={node['resource_id'] for node in graph(g.w)['nodes']}
    assert {node['resource_id'] for node in nodes}==approved and not g.w.calls


def test_follow_up_steps_keep_the_model_plan(growth):
    g=growth
    def proposal(envelope):
        value=graph(g.w);value['nodes'][0]['input']['query']='Stripe webhooks documentation'
        return value
    g.factory.model_proposer=proposal
    body=request()|{'objective':'Search documentation for Stripe webhooks, then cross-check with a second documentation source'}
    result=g.factory.prepare_model_proposal(g.w.ws,body,g.w.actor)
    assert len(result['definition']['nodes'])==2 and result['definition']['nodes'][1]['bindings']

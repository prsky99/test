"""Semantic expectations cover subjects, data flow, counts and unsupported goals."""
import pytest
from agent_market.workspace_access import WorkspaceInvalid
from agent_market.workflow_model_proposer import OllamaGraphProposer,compile_proposal
from agent_market.workflow_goal_policy import scoped_context,goal_sequence,search_topic
from agent_market.workspace_goal_coverage import missing
from scripts.benchmark_macmini_model import envelope
from tests.workflow_generation_cases import CASES,assess


@pytest.mark.parametrize('case',CASES,ids=[c['id'] for c in CASES])
def test_supported_meaning_or_explicit_clarification_before_a_review(case):
    ctx=envelope(case['prompt'])
    if case['expected']=='rejected':
        with pytest.raises(WorkspaceInvalid):OllamaGraphProposer._public_context(ctx)
        return
    if case['expected']=='needs_details':
        try:
            unavailable=missing(case['prompt'],{'docs.search.v1','news.search.v1'})
            scoped=scoped_context(ctx)
            assert unavailable or goal_sequence(scoped) is None
        except WorkspaceInvalid:pass
        return
    assert not missing(case['prompt'],{'docs.search.v1','news.search.v1'})
    value=compile_proposal(scoped_context(ctx),{'query':search_topic(case['prompt'])})
    result={'state':'review_required','definition':value}
    checks=assess(case,result,200)
    assert all(checks.values()),checks


def test_api_plural_equivalence_does_not_remove_named_topic_gate():
    ctx=envelope('Find documentation about news APIs using two steps')
    assert compile_proposal(ctx,{'query':'news API documentation'})['nodes']
    with pytest.raises(WorkspaceInvalid):compile_proposal(ctx,{'query':'Python documentation'})


@pytest.mark.parametrize('objective,query',[
 ('Find Python documentation using three steps','Python 3.8 documentation'),
 ('Find Python 3.12 documentation using two steps','Python documentation'),
 ('Find Python 3.12 documentation using two steps','Python 3.11 documentation'),
])
def test_named_versions_cannot_be_added_removed_or_changed(objective,query):
    with pytest.raises(WorkspaceInvalid):compile_proposal(envelope(objective),{'query':query})


def test_model_cannot_leak_workflow_step_count_into_a_search_query():
    ctx=envelope('Find documentation about summarization algorithms using two steps')
    value=compile_proposal(ctx,{'query':'two step summarization algorithms documentation'})
    assert value['nodes'][0]['input']['query']=='summarization algorithms documentation'
    assert len(value['nodes'])==2


@pytest.mark.parametrize('modifier',['connected','sequential','linked','read-only connected','connected read-only'])
def test_natural_step_qualifiers_preserve_requested_count_and_topic(modifier):
    objective='Find Rust documentation using exactly ten '+modifier+' steps.'
    value=compile_proposal(scoped_context(envelope(objective)),{'query':'Rust'})
    assert len(value['nodes'])==10
    assert all(n['contract_id']=='docs.search.v1' for n in value['nodes'])
    assert value['nodes'][-1]['bindings']['query']['node_id']=='step_9'


@pytest.mark.parametrize('count',['one','eleven','20'])
def test_qualified_step_count_cannot_silently_fall_back_to_two(count):
    with pytest.raises(WorkspaceInvalid):scoped_context(envelope('Find Rust documentation using '+count+' connected steps.'))


def test_independent_step_qualifier_preserves_independent_inputs():
    value=compile_proposal(scoped_context(envelope('Find Rust documentation in ten independent steps.')),{'query':'Rust'})
    assert len(value['nodes'])==10
    assert all(n['input']['query']=='Rust' and not n['bindings'] and not n['after'] for n in value['nodes'])


@pytest.mark.parametrize('objective,query',[
 ('Find documentation about Connected Papers using two connected steps','papers'),
 ('Find documentation about Linked Data using two linked steps','unrelated scheduling'),
])
def test_step_qualifiers_do_not_weaken_named_subject_preservation(objective,query):
    with pytest.raises(WorkspaceInvalid):compile_proposal(scoped_context(envelope(objective)),{'query':query})

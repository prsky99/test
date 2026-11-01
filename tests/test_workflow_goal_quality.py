"""Request meaning constrains approved agents before any review or execution."""
import pytest
from scripts.benchmark_macmini_model import envelope
from agent_market.workflow_goal_policy import goal_sequence, scoped_context, validate_goal, search_topic
from agent_market.workflow_model_proposer import compile_proposal, proposal_schema
from agent_market.workspace_access import WorkspaceInvalid
from agent_market.workspace_goal_coverage import missing
from tests.test_workspace_growth import growth
from tests.test_workspace_typed_flows import typed_world, routing
from tests.test_workspace_model_proposal import request, response


@pytest.mark.parametrize('objective,expected',[
 ('Find Python documentation using exactly five steps',['docs.search.v1']*5),
 ('Find documentation using two steps. Do not search news.',['docs.search.v1']*2),
 ('Find news using two steps, without documentation',['news.search.v1']*2),
 ('Find battery recycling news then supporting documentation using exactly two steps',['news.search.v1','docs.search.v1']),
 ('Find Python documentation then related news using two steps',['docs.search.v1','news.search.v1']),
 ('Find news then documentation then news using three steps',['news.search.v1','docs.search.v1','news.search.v1']),
 ('Find documentation for 3 topics: Docker, Kubernetes and Terraform',['docs.search.v1']*3),
])
def test_recognized_goals_assign_types_order_and_count(objective,expected):
    ctx=envelope(objective)
    assert goal_sequence(ctx)==expected
    assert set(proposal_schema(ctx)['properties'])=={'query'}
    result=compile_proposal(ctx,{'query':search_topic(objective)})
    assert [n['contract_id'] for n in result['nodes']]==expected
    assert len(result['nodes'])==len(expected)
    assert all(n['resource_id'] in (17,23) for n in result['nodes'])


@pytest.mark.parametrize('objective',[
 'Find news and documentation using exactly three steps',
 'Find news documentation using two steps',
 'Find documentation using one step',
 'Find documentation using 11 steps',
 'Find documentation using two steps and three tasks',
])
def test_ambiguous_or_unsupported_count_needs_clarity(objective):
    with pytest.raises(WorkspaceInvalid):goal_sequence(envelope(objective))


def test_no_news_requirement_is_added_from_a_prohibition():
    objective='Find Python documentation using two steps. Do not search news.'
    assert not missing(objective,{'docs.search.v1'})
    assert {c['contract_id'] for c in scoped_context(envelope(objective))['candidates']}=={'docs.search.v1'}


def test_previously_accepted_irrelevant_or_reversed_pairs_are_rejected():
    for objective in ('Find documentation using two steps','Find news then documentation using two steps'):
        with pytest.raises(WorkspaceInvalid):
            compile_proposal(envelope(objective),{'query':'Python documentation','agents':envelope(objective)['candidates']})


def test_query_only_cannot_bypass_unknown_goal_or_unavailable_candidates():
    with pytest.raises(WorkspaceInvalid):compile_proposal(envelope('Find public information'),{'query':'Python'})
    with pytest.raises(WorkspaceInvalid):scoped_context(envelope('Find news then documentation using two steps')|{'candidates':[{'resource_id':17,'contract_id':'docs.search.v1'}]})


def test_legacy_full_nodes_must_also_match_goal():
    with pytest.raises(WorkspaceInvalid):
        validate_goal(envelope('Find documentation using two steps'),[{'contract_id':'docs.search.v1'},{'contract_id':'news.search.v1'}])
    with pytest.raises(WorkspaceInvalid):validate_goal(envelope('Find documentation using two steps'),[{},{}])


def test_named_topic_cannot_disappear_into_generic_documentation():
    with pytest.raises(WorkspaceInvalid):compile_proposal(envelope('Find Python documentation using five steps'),{'query':'public documentation'})


def test_repeated_searches_prefer_distinct_approved_candidates_without_changing_types():
    ctx=envelope('Find Python documentation using three steps')
    ctx['candidates'].append({'resource_id':31,'contract_id':'docs.search.v1'})
    value=compile_proposal(ctx,{'query':'Python documentation'})
    assert [n['resource_id'] for n in value['nodes']]==[17,31,17]


def test_factory_rejects_semantically_wrong_custom_adapter_and_never_retains_review(growth):
    g=growth
    def wrong(ctx):
        value=response(ctx);value['nodes'][0]['contract_id']='news.search.v1'
        return value
    g.factory.model_proposer=wrong
    with pytest.raises(WorkspaceInvalid):g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
    assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_factory_reviews')


def test_ambiguous_goal_returns_clarification_without_model_or_agent_call(growth):
    g=growth;calls=[];g.factory.model_proposer=lambda ctx:calls.append(ctx) or response(ctx)
    result=g.factory.prepare_model_proposal(g.w.ws,request(objective='Find news and documentation using three steps'),g.w.actor)
    assert result['state']=='needs_details' and result['model_calls']==0 and not calls and not g.w.calls


def test_supporting_follow_up_continues_the_first_subject():
    """QA 15: "then find supporting documentation" became an independent "supporting research" search."""
    from agent_market.workspace_goal_coverage import topics
    from agent_market.workflow_goal_policy import independent, validate_query, GoalQueryMismatch
    import pytest as _pytest
    goal = 'Find recent public research about battery recycling, then find supporting documentation.'
    assert topics(goal) == [] and not independent({'objective': goal})
    with _pytest.raises(GoalQueryMismatch):
        validate_query({'objective': goal}, 'supporting research')
    assert topics('Find Docker documentation, then Kubernetes documentation.') == ['Docker documentation', 'Kubernetes documentation']


def test_cross_kind_follow_up_searches_the_request_topic():
    """QA 17: a news headline searched as a paper query returned an unrelated pharmacy paper."""
    from agent_market.workflow_model_proposer import topic_followups
    title = {'query': {'node_id': 'step_1', 'path': ['items', 0, 'title']}}
    news = {'id': 'step_1', 'contract_id': 'news.search.v1', 'input': {'query': 'artificial intelligence news', 'language': 'en', 'limit': 1}, 'bindings': {}, 'after': []}
    docs = {'id': 'step_2', 'contract_id': 'docs.search.v1', 'input': {'language': 'en', 'limit': 1}, 'bindings': title, 'after': ['step_1']}
    goal = {'objective': 'Find artificial intelligence news, then supporting documentation in two steps.'}
    changed = topic_followups(goal, [news, docs])[1]
    assert changed['input']['query'] == 'artificial intelligence research' and changed['bindings'] == {}
    assert changed['after'] == ['step_1'] and docs['bindings'] == title  # the original plan is not mutated
    # An explicitly requested title search and same-kind chains keep the reviewed binding.
    assert topic_followups({'objective': 'Find AI news, then search papers using the returned title.'}, [news, docs])[1]['bindings'] == title
    same = dict(news, contract_id='docs.search.v1', input={'query': 'battery recycling research', 'language': 'en', 'limit': 1})
    assert topic_followups({'objective': 'Find battery recycling research in two connected steps.'}, [same, docs])[1]['bindings'] == title


def test_separately_listed_subjects_become_one_step_each():
    """QA 17: both steps searched "Docker documentation and Kubernetes documentation"."""
    from agent_market.workspace_goal_coverage import topics
    from agent_market.workflow_goal_policy import requested_steps, independent
    goal = 'Find Docker documentation and Kubernetes documentation separately.'
    assert topics(goal) == ['Docker documentation', 'Kubernetes documentation']
    assert requested_steps({'objective': goal}) == 2 and independent({'objective': goal})
    assert topics('Find Docker docs, Redis docs and Kafka docs independently.') == ['Docker documentation', 'Redis documentation', 'Kafka documentation']
    assert topics('Find Docker documentation separately.') == []


def test_listed_aspects_keep_the_named_product():
    """QA 19: "Kubernetes documentation about rollouts and rollbacks" searched without "Kubernetes"
    and Context7 returned Argo Rollouts and Salesforce pages."""
    from agent_market.workspace_goal_coverage import topics
    assert topics('Find Kubernetes documentation about deployment rollouts and rollbacks') == [
        'Kubernetes deployment rollouts documentation', 'Kubernetes rollbacks documentation']
    assert topics('React docs on hooks, context and suspense') == [
        'React hooks documentation', 'React context documentation', 'React suspense documentation']
    assert topics('Find Kubernetes documentation about Kubernetes probes and rollbacks') == [
        'Kubernetes probes documentation', 'Kubernetes rollbacks documentation']
    # Lead verbs, articles and kind words are not a product name.
    assert topics('Find documentation for Docker and Kubernetes') == ['Docker documentation', 'Kubernetes documentation']
    assert topics('Please look up the official docs for FastAPI, Django and Flask') == [
        'FastAPI documentation', 'Django documentation', 'Flask documentation']
    assert topics('Find research papers about battery recycling and solid-state batteries') == [
        'battery recycling research', 'solid-state batteries research']

"""Intent ambiguity and reviewed new drafts do not mutate an in-flight graph."""
import copy

import pytest

from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from agent_market.workspace_app_factory import NOTICE
from tests.test_workspace_growth import growth, review_body
from tests.test_workspace_typed_flows import typed_world, routing, save
from tests.test_workspace_execution_api import private_api


def intent(g, **changes):
    return {'purpose': 'Documentation about research then documentation about references',
            'name': 'Reviewed intent workflow', 'resource_ids': g.w.ids[:2], 'from_utc': None, 'criteria': [], **changes}


def commit(g, review):
    return g.factory.commit(g.w.ws, {'review_id': review['review_id'], 'authorized': True, 'notice': NOTICE}, g.w.actor)


def test_supported_intent_creates_reviewed_ordered_plan_then_one_new_draft(growth):
    g = growth
    review = g.factory.prepare_intent(g.w.ws, intent(g), g.w.actor)
    assert review['state'] == 'review_required' and not review['general_natural_language_planner']
    assert review['definition']['nodes'][1]['after'] == ['step_1']
    assert not review['definition']['nodes'][1]['bindings'] and not g.w.calls
    saved = commit(g, review); again = commit(g, review)
    assert saved['id'] == again['id'] and again['replayed'] and not g.w.calls


@pytest.mark.parametrize('purpose', ['Build whatever I want', 'Documentation then send a message', 'News and documentation then documentation'])
def test_ambiguous_or_unsupported_intent_requests_details_without_guessing(growth, purpose):
    g = growth; before = g.w.store.query('SELECT COUNT(*) FROM workspace_factory_reviews')[0][0]
    review = g.factory.prepare_intent(g.w.ws, intent(g, purpose=purpose), g.w.actor)
    assert review['state'] == 'needs_details' and review['questions'] and not g.w.calls
    assert g.w.store.query('SELECT COUNT(*) FROM workspace_factory_reviews')[0][0] == before


def test_replanning_saves_the_next_revision_and_preserves_the_original_version(growth):
    """11-01: an edit is the next revision of the same workflow; the earlier version stays as it was."""
    g = growth; original = save(g.w); before = g.w.core.detail(g.w.ws, original['id'], g.w.actor)
    definition = copy.deepcopy(before['definition']); definition['nodes'][1]['bindings'].pop('query', None)
    definition['nodes'][1]['input']['query'] = 'Reviewed new request'
    review = g.factory.prepare_plan(g.w.ws, {'name': 'Reviewed new draft', 'definition': definition,
        'base_flow_id': original['id'], 'base_revision': original['revision']}, g.w.actor)
    assert not review['new_draft_only'] and {'node_id': definition['nodes'][1]['id'], 'change': 'input'} in review['changes']
    saved = commit(g, review)
    assert saved['id'] == original['id'] and saved['revision'] == original['revision'] + 1
    assert saved['version_id'] != before['version_id'] and not g.w.calls
    listed = [flow for flow in g.w.core.listing(g.w.ws, g.w.actor) if flow['id'] == original['id']]
    assert len(listed) == 1


def test_stale_base_revision_cannot_commit_a_review(growth):
    g = growth; original = save(g.w); current = g.w.core.detail(g.w.ws, original['id'], g.w.actor)
    review = g.factory.prepare_plan(g.w.ws, {'name': 'New proposal', 'definition': current['definition'],
        'base_flow_id': original['id'], 'base_revision': original['revision']}, g.w.actor)
    g.w.core.save(g.w.ws, {'flow_id': original['id'], 'revision': original['revision'],
                         'name': 'Changed by another editor', 'definition': current['definition']}, g.w.actor)
    with pytest.raises(WorkspaceConflict): commit(g, review)
    assert not g.w.calls


def test_plan_api_rejects_idor_unknown_fields_and_cross_origin(growth):
    g = growth; review = g.factory.prepare(g.w.ws, review_body(g), g.w.actor)
    body = {'name': 'Explicit plan', 'definition': review['definition'], 'base_flow_id': None, 'base_revision': None}
    path = g.base+'/app-factory/plan-reviews'
    assert g.client.post(path, json=body).status_code == 401
    assert g.client.post(path, json=body, headers=g.headers | {'Origin': 'https://outside.test'}).status_code == 403
    assert g.client.post(path, json=body | {'auto_execute': True}, headers=g.headers).status_code == 400
    response = g.client.post(path, json=body, headers=g.headers)
    assert response.status_code == 200 and response.json()['result']['new_draft_only']
    assert response.headers['cache-control'] == 'no-store' and not g.w.calls

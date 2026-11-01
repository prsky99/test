"""Bind browser execution intent to the exact reviewed public graph."""

import copy
import time

import pytest

from tests.test_execution_availability import published  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401


def test_graph_changed_between_review_and_post_is_rejected_without_dispatch(published):
    store, front, client, _, workflow_ids, calls = published
    wid = workflow_ids[0]
    reviewed = next(t for t in client.get('/api/workflows/templates').json()['templates'] if t['id'] == wid)
    nodes = copy.deepcopy(store.get_workflow(wid)['nodes'])
    nodes[1]['data']['input']['query'] = 'Updated informational query'
    store.update_workflow(wid, {'nodes': nodes})
    result = client.post('/api/workflows/run', json={'template_id': wid,
                         'definition_hash': reviewed['definition_hash']})
    assert result.status_code == 409 and 'changed' in result.json()['error']
    assert not calls and not front.workflows.futures
    current = next(t for t in client.get('/api/workflows/templates').json()['templates'] if t['id'] == wid)
    assert current['definition_hash'] != reviewed['definition_hash']
    result = client.post('/api/workflows/run', json={'template_id': wid,
                         'definition_hash': current['definition_hash']})
    assert result.status_code == 202
    handle=result.json()
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        retained=client.get('/api/workflows/runs/'+handle['run_id'],
            headers={'X-Workflow-Key':handle['run_key']}).json()
        if retained['status'] in ('succeeded','failed','cancelled'):break
        time.sleep(.01)
    assert retained['status']=='succeeded',retained
    assert len(calls) == 2


@pytest.mark.parametrize('value', [None, True, {}, 'short', 'A' * 64])
def test_invalid_review_binding_is_rejected_before_execution(published, value):
    _, front, client, _, workflow_ids, calls = published
    response = client.post('/api/workflows/run', json={'template_id': workflow_ids[0],
                            'definition_hash': value})
    assert response.status_code == 400
    assert not calls and not front.workflows.futures

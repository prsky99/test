"""An unavailable approved catalog is an honest empty state, not authorization."""
import pytest

from tests.test_workflow_controlled_pairs_api import BASE, H, routing_api
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing


@pytest.mark.parametrize('missing', ['news', 'docs', 'both', 'one_doc'])
def test_pair_options_report_missing_approved_candidates_without_calls(routing_api, missing):
    routing, _, admin = routing_api
    rt, _, _, calls, *_ = routing
    with rt.store.tx() as db:
        if missing in ('news', 'both'):
            db.execute("DELETE FROM capability_approvals WHERE contract_id='news.search.v1'")
        if missing in ('docs', 'both'):
            db.execute("DELETE FROM capability_approvals WHERE contract_id='docs.search.v1'")
        elif missing == 'one_doc':
            db.execute("DELETE FROM capability_approvals WHERE version_id IN (SELECT version_id FROM capability_approvals WHERE contract_id='docs.search.v1' ORDER BY version_id LIMIT 1) AND contract_id='docs.search.v1'")
    before = rt.store._db.total_changes
    response = admin.get(BASE + '/options', headers=H)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    body = response.json()
    assert body['ok'] is True and body['available'] is False
    expected = []
    if missing in ('news', 'both'):
        assert body['sources'] == []
        expected.append('NEWS_SOURCE_UNAVAILABLE')
    if missing in ('docs', 'both', 'one_doc'):
        assert len(body['targets']) < 2
        expected.append('DOCUMENTATION_TARGETS_UNAVAILABLE')
    assert body['unavailable_reasons'] == expected
    assert all(set(item) == {'id', 'label'} for item in body['sources'] + body['targets'])
    assert not calls and rt.store._db.total_changes == before
    assert not rt.store.query('SELECT id FROM workflow_runs')
    attempted = admin.post(BASE + '/prepare', headers=H, json={
        'objective': 'Latest Python news', 'source_id': 'cc_unavailable',
        'target_a_id': 'cc_unavailable_a', 'target_b_id': 'cc_unavailable_b'})
    assert attempted.status_code == 409
    assert not calls and not rt.store.query('SELECT id FROM workflow_runs')


def test_complete_pair_catalog_is_available_and_existing_composer_stays_strict(routing_api):
    routing, _, admin = routing_api
    rt, _, _, calls, *_ = routing
    response = admin.get(BASE + '/options', headers=H)
    assert response.status_code == 200
    assert response.json()['available'] is True
    assert response.json()['unavailable_reasons'] == []
    with rt.store.tx() as db:
        db.execute("DELETE FROM capability_approvals WHERE contract_id='news.search.v1'")
    with pytest.raises(ValueError, match='No matching registered agents'):
        rt.composer.candidates('news.search.v1')
    assert rt.composer.candidates('news.search.v1', allow_empty=True) == []
    assert not calls

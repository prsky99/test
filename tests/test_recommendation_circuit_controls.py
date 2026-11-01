"""Recommendation exclusion, evidence retention and demand provenance regressions."""
import json
import time

import pytest

from agent_market.concierge.memory import VisitorBook
from agent_market.concierge.recommendation_circuit import controls_for, remediate_sqlite
from agent_market.concierge.selection import _term_in
from tests.test_fast_single_recommendation import catalog, ask
from tests.test_dashboard import dash, H


def outcomes(store, rid, success, count=3, at=None, prefix='customer'):
    with store.tx() as db:
        for i in range(count):
            db.execute('INSERT OR REPLACE INTO agent_outcomes VALUES (?,?,?,?)',
                       (f'{prefix}-{i}', rid, int(success), at or time.time()))


def seed_unmet(store, task, *, visitor='customer', channel='rest'):
    now = time.time()
    with store.tx() as db:
        db.execute('''INSERT OR IGNORE INTO agent_visitors
            (id,token_hash,name,channel,user_agent,fingerprint,lang,first_seen,last_seen,visits,visit_days,messages,tier)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (visitor, visitor+'-hash', 'Customer', channel, 'production-agent/1.0', visitor+'-fingerprint',
             'en', now-300, now-60, 1, 1, 1, 'new'))
        db.execute('INSERT INTO agent_messages (visitor_id,at,role,channel,text,data) VALUES (?,?,?,?,?,?)',
                   (visitor, now-240, 'concierge', channel, 'No match.', json.dumps({
                       'record_version': 1, 'intent': 'find', 'status': 'no_match',
                       'protocol_filter': 'any', 'task': task, 'recommendations': []})))


def test_global_circuit_is_never_relaxed_for_recommendation_or_details(catalog):
    store, _, client, add, now = catalog
    rid = add('Weather Circuit', report_at=now-1)
    initial = ask(client)
    outcomes(store, rid, False)
    assert rid in VisitorBook(store).global_failing_resources()
    assert ask(client)['data']['recommendations'] == []
    details = client.post('/chat', headers={'X-Visitor-Token': initial['visitor']['token']},
                          json={'message': 'details 1'})
    assert details.status_code == 200
    assert details.json()['data']['recommendations'] == []


def test_manual_trip_overrides_success_history_without_fabricating_outcomes(dash):
    world, client = dash
    outcomes(world.store, 1, True, count=10)
    before = world.store.query('SELECT * FROM agent_outcomes')
    response = client.post('/admin/api/agent-telemetry/remediate', headers=H,
                           json={'action': 'trip_circuit', 'resource_id': 1})
    assert response.status_code == 200, response.text
    assert response.json()['circuit_open'] is True
    assert 1 in VisitorBook(world.store).global_failing_resources()
    assert world.store.query('SELECT * FROM agent_outcomes') == before
    body = client.get('/admin/api/agent-telemetry?source=live', headers=H).json()
    row = next(r for r in body['failing_agents'] if r['resource_id'] == 1)
    assert row['circuit_open'] and row['fail_count'] == 0 and row['success_count'] == 10


def test_reset_preserves_history_and_new_failures_can_reopen(dash):
    world, client = dash
    outcomes(world.store, 1, False, at=time.time()-60)
    before = [dict(row) for row in world.store.query('SELECT * FROM agent_outcomes')]
    assert 1 in VisitorBook(world.store).global_failing_resources()
    response = client.post('/admin/api/agent-telemetry/remediate', headers=H,
                           json={'action': 'reset_circuit', 'resource_id': 1})
    assert response.status_code == 200, response.text
    assert response.json()['history_preserved'] and response.json()['cleared'] == 0
    assert response.json()['circuit_open'] is False
    assert [dict(row) for row in world.store.query('SELECT * FROM agent_outcomes')] == before
    assert 1 not in VisitorBook(world.store).global_failing_resources()
    outcomes(world.store, 1, False, prefix='new-customer')
    assert 1 in VisitorBook(world.store).global_failing_resources()


def test_legacy_admin_trip_remains_open_until_explicit_reset(dash):
    world, _ = dash
    with world.store.tx() as db:
        db.execute('INSERT INTO agent_outcomes VALUES (?,?,?,?)', ('__admin_cb_1__', 1, 0, time.time()-30))
    outcomes(world.store, 1, True, count=10)
    assert 1 in VisitorBook(world.store).global_failing_resources()
    remediate_sqlite(world.store, 1, 'reset_circuit', time.time())
    assert 1 not in VisitorBook(world.store).global_failing_resources()
    assert len(world.store.query('SELECT * FROM agent_outcomes')) == 11


def test_real_workflow_demand_is_kept_and_simulations_use_stored_channel(dash):
    world, client = dash
    task = 'Create an image generation workflow for product photos'
    seed_unmet(world.store, task)
    seed_unmet(world.store, 'book a hotel workflow', visitor='approved-simulation', channel='admin-test')
    live = client.get('/admin/api/agent-telemetry?source=live', headers=H).json()
    assert any(row['task'] == task for row in live['unmet_queries'])
    assert live['kpis']['synthetic_probe_count'] == 0
    all_sources = client.get('/admin/api/agent-telemetry?source=all', headers=H).json()
    assert all_sources['kpis']['synthetic_probe_count'] == 1
    assert all(row['task'] != 'book a hotel workflow' for row in all_sources['unmet_queries'])


def test_unmet_totals_include_demand_beyond_the_review_and_display_budgets(dash):
    world, client = dash
    for i in range(27):
        seed_unmet(world.store, f'ocean bathymetry sonar field {i}')
    body = client.get('/admin/api/agent-telemetry?source=live', headers=H).json()
    assert body['kpis']['unmet_query_count'] == 27
    assert body['kpis']['unmet_queries_displayed'] == len(body['unmet_queries']) == 15
    assert body['kpis']['unmet_queries_rechecked'] == 20
    assert body['kpis']['unmet_queries_pending_review'] == 7


def test_resolve_without_a_candidate_returns_conflict_and_keeps_demand(dash):
    world, client = dash
    task = 'ocean bathymetry sonar feed'
    seed_unmet(world.store, task)
    response = client.post('/admin/api/agent-telemetry/remediate', headers=H,
                           json={'action': 'resolve_unmet', 'task': task})
    assert response.status_code == 409
    body = client.get('/admin/api/agent-telemetry?source=live', headers=H).json()
    assert any(row['task'] == task for row in body['unmet_queries'])


def test_cross_protocol_recovery_is_visible_and_cv_is_bidirectional(catalog):
    _, _, client, add, now = catalog
    add('Weather MCP', report_at=now-1)
    body = ask(client, 'find an A2A weather forecast API', data={'protocol': 'a2a'})
    assert body['data']['recommendations'] == []
    assert body['data']['cross_protocol_hint']['available_protocol'] == 'mcp'
    assert body['data']['cross_protocol_hint']['message'] in body['reply']
    assert _term_in('resume', 'cv') and _term_in('cv', 'resume')


@pytest.mark.parametrize('rid', [True, -1, 0, 2**100, '1 OR 1=1', '\uff11'])
def test_invalid_remediation_ids_are_rejected_without_writes(dash, rid):
    world, client = dash
    response = client.post('/admin/api/agent-telemetry/remediate', headers=H,
                           json={'action': 'trip_circuit', 'resource_id': rid})
    assert response.status_code == 400
    assert controls_for(world.store) == {}


def test_remediation_requires_staff_session(dash):
    world, client = dash
    response = client.post('/admin/api/agent-telemetry/remediate',
                           json={'action': 'trip_circuit', 'resource_id': 1})
    assert response.status_code in (401, 403)
    assert controls_for(world.store) == {}

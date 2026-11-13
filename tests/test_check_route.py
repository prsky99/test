"""Check-and-Route (PM 11-14 super-gap 2): verify an agent, route a role, from the verify snapshot only.

Unverified results and results without an accuracy check are never listed as pearls; necklaces appear only while
the necklace surface offers them; no promise words.
"""
import json

import pytest

from agent_market.concierge import check_route as cr
from agent_market.concierge import necklace_surface as ns
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def role_result(role, score, verified, accuracy='answer set', necklaces=()):
    return {'role': role, 'tool': 'get_' + role.split('.')[0], 'outcome': 'succeeded', 'score': score,
            'score_items': {'data_quality': {'accuracy': 25 if verified else 0}}, 'accuracy_source': accuracy,
            'verified_pearl': verified, 'final_pearl': False, 'tested_at': '2026-11-14T04:01:41+0900', 'data_time': None,
            'response_sha256': 'ab' * 32, 'version': 1, 'signed_report': None, 'better_alternatives': [], 'necklaces': list(necklaces)}


@pytest.fixture
def snap(tmp_path, monkeypatch):
    data = {'generated': '2026-11-14T05:11:11+0900', 'methodology': 'v1',
            'verified_rule': {'min_score': 85, 'successes_on_different_days': 2},
            'roles': {
                'weather.forecast.v1': {'field': 'travel', 'final_pearl': 11, 'verified': [11, 12],
                                        'ranking': [{'id': 11, 'tool': 'forecast', 'score': 93, 'verified': True},
                                                    {'id': 12, 'tool': 'weather', 'score': 88, 'verified': True},
                                                    {'id': 13, 'tool': 'wx', 'score': 70, 'verified': False}],
                                        'necklaces': [{'necklace': 'trip-brief', 'status': 'live', 'slot': 'weather', 'members': [11]}]},
                'papers.search.v1': {'field': 'research', 'final_pearl': None, 'verified': [],
                                     'ranking': [{'id': 21, 'tool': 'search_papers', 'score': 65, 'verified': False}], 'necklaces': []}},
            'agents': {'11': {'id': 11, 'name': 'Forecast One', 'kind': 'mcp', 'grade': 'A', 'tool_fingerprint': 'f1',
                              'roles': [role_result('weather.forecast.v1', 93, True, necklaces=['trip-brief'])]},
                       '12': {'id': 12, 'name': 'Weather Two', 'kind': 'mcp', 'grade': 'A', 'tool_fingerprint': 'f2',
                              'roles': [role_result('weather.forecast.v1', 88, True)]},
                       '13': {'id': 13, 'name': 'Wx Three', 'kind': 'mcp', 'grade': 'B', 'tool_fingerprint': 'f3',
                              'roles': [role_result('weather.forecast.v1', 70, False, accuracy='none (no answer set)')]},
                       '21': {'id': 21, 'name': 'Papers', 'kind': 'mcp', 'grade': 'B', 'tool_fingerprint': 'f4',
                              'roles': [role_result('papers.search.v1', 65, False, accuracy='none (no answer set)')]}}}
    (tmp_path / 'exports/pearls').mkdir(parents=True)
    (tmp_path / 'exports/pearls/verify-snapshot.json').write_text(json.dumps(data))
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    return data


def test_verify_reports_the_agents_own_state_with_verified_alternatives(snap):
    text, data = cr.verify(13)
    role = data['roles'][0]
    assert role['verified_pearl'] is False and role['accuracy_source'].startswith('none')
    assert [a['agent_id'] for a in role['better_alternatives']] == [11, 12]
    assert 'not verified' in text and 'Method: https://agentconcierge.biz/methodology' in text
    assert cr.verify(999) is None and cr.verify('13') is None


def test_best_for_role_lists_only_verified_pearls_and_offered_necklaces(snap, monkeypatch):
    text, data = cr.best_for_role('weather.forecast.v1')
    assert [p['agent_id'] for p in data['verified_pearls']] == [11, 12] and 13 not in [p['agent_id'] for p in data['verified_pearls']]
    assert data['necklaces'] == []  # trip-brief is not offered by the necklace surface
    monkeypatch.setattr(ns, 'by_slug', lambda slug, snapshot=None: {'slug': slug, 'name': 'Trip Brief'})
    monkeypatch.setattr(ns, 'offered', lambda entry, now=None: True)
    _, data = cr.best_for_role('weather.forecast.v1')
    assert data['necklaces'][0]['mcp_tool'] == 'necklace_trip_brief'
    text, data = cr.best_for_role('papers.search.v1')
    assert data['verified_pearls'] == [] and data['final_pearl'] is None and 'no verified pearl yet' in text
    assert cr.best_for_role('nope.v1') is None and cr.best_for_role('../x') is None
    for word in ('best ', 'guaranteed', '#1'):
        assert word not in text


def test_rest_and_mcp_surfaces_answer_from_the_snapshot(snap, client):  # noqa: F811
    r = client.get('/api/verify?agent_id=13')
    assert r.status_code == 200 and r.json()['roles'][0]['score'] == 70
    assert client.get('/api/verify?agent_id=999').status_code == 404
    assert client.get('/api/roles/weather.forecast.v1/best').json()['verified_pearls'][0]['agent_id'] == 11
    assert client.get('/api/roles/nope.v1/best').status_code == 404
    assert 'weather.forecast.v1' in client.get('/api/roles').json()['roles']
    call = lambda name, args: client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                                        'params': {'name': name, 'arguments': args}}).json()['result']
    assert call('verify_agent', {'agent_id': 11})['structuredContent']['roles'][0]['verified_pearl'] is True
    assert call('best_for_role', {'role': 'papers.search.v1'})['structuredContent']['verified_pearls'] == []
    assert call('verify_agent', {'agent_id': 999})['structuredContent'] == {'found': False, 'text': 'We have not tested this agent yet.'}

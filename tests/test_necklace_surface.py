"""Public necklace surface (PM 11-14): it shows the workflow team's judged snapshot and never judges.

Only a live necklace that passed the 95% gate, with two or more pearls, a positive delta, a retest within 48 hours
and at most two AgentValCon fallbacks after the external ones, is offered. Held and retired necklaces keep a page
with the suspension notice and run nothing; a retired page moves to its replacement after 30 days.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge import necklace_surface as ns
from tests.test_pearl_frontend import client  # noqa: F401 - fixture

NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def pearl(rid, role, alternates=()):
    return {'resource_id': rid, 'role': role, 'tool': 'get_' + role.replace(' ', '_'), 'required': True, 'pearl': True,
            'alternates': [{'resource_id': r, 'tool': 't', 'kind': k} for r, k in alternates]}


def necklace(slug, status='live', **extra):
    value = {'slug': slug, 'name': slug.replace('-', ' ').title(), 'summary': 'Weather and exchange rate for one city.',
             'version': 1, 'definition_digest': 'd', 'template_id': 31, 'status': status, 'held_reason': None,
             'gate_passed_at': iso(NOW - timedelta(days=2)),
             'pearls': [pearl(133020, 'weather', [(133511, 'external'), (900001, 'agentcon')]), pearl(140112, 'exchange rate')],
             'input_schema': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']},
             'completion': {'runs': 30, 'completed': 29, 'completed_external_only': 26, 'since': '2026-11-13T03:00:00Z',
                            'retested_at': iso(NOW - timedelta(hours=3))},
             'quality': {'cases_7d': 30, 'success_rate': 0.9, 'best_single_rate': 0.7, 'delta_pp': 20.0,
                         'tested_at': iso(NOW - timedelta(hours=3))},
             'cost': {'usdc_per_run': 0, 'p50_ms': 3200, 'p95_ms': 4800}, 'replaces_templates': [], 'replaced_at': None}
    value.update(extra)
    return value


@pytest.fixture
def snapshot():
    return {'schema': ns.SCHEMA, 'generated_at': iso(NOW), 'necklaces': [
        necklace('trip-brief'),
        necklace('paper-digest', status='held', held_reason='completion_low', held_at=iso(NOW - timedelta(hours=5))),
        necklace('old-brief', status='retired', replaced_by='trip-brief', replaced_at=iso(NOW - timedelta(days=3))),
        necklace('ancient-brief', status='retired', replaced_by='trip-brief', replaced_at=iso(NOW - timedelta(days=31))),
        necklace('not-approved', gate_passed_at=None),
        necklace('stale', quality={'cases': 30, 'success_rate': 0.9, 'best_single_rate': 0.7, 'delta_pp': 20.0,
                                   'tested_at': iso(NOW - timedelta(hours=49))}),
        necklace('no-gain', quality={'cases': 30, 'success_rate': 0.7, 'best_single_rate': 0.7, 'delta_pp': 0.0,
                                     'tested_at': iso(NOW)}),
        necklace('one-pearl', pearls=[pearl(1, 'weather')]),
        necklace('bad-fallbacks', pearls=[pearl(1, 'weather', [(9, 'agentcon'), (2, 'external')]), pearl(3, 'rate')]),
    ], 'events': [
        {'slug': 'trip-brief', 'kind': 'launched', 'at': iso(NOW - timedelta(days=2)), 'reason': None, 'replaced_by': None},
        {'slug': 'paper-digest', 'kind': 'held', 'at': iso(NOW - timedelta(hours=5)), 'reason': 'completion_low', 'replaced_by': None},
        {'slug': 'old-brief', 'kind': 'retired', 'at': iso(NOW - timedelta(days=3)), 'reason': None, 'replaced_by': 'trip-brief'},
    ]}


def test_only_gated_fresh_better_multi_pearl_necklaces_are_offered(snapshot):
    offered = [e['slug'] for e in ns.live(snapshot, NOW)]
    assert offered == ['trip-brief']
    assert ns.sitemap_paths(snapshot, NOW) == ['/necklaces/trip-brief']
    listed = {i['slug']: i for i in ns.listing(snapshot=snapshot, now=NOW)['necklaces']}
    # stopped necklaces stay listed with their notice during the 30 days; never-approved ones never appear
    assert set(listed) == {'trip-brief', 'paper-digest', 'old-brief'}
    assert listed['trip-brief']['offered'] and listed['trip-brief']['mcp_tool'] == 'necklace_trip_brief'
    assert listed['trip-brief']['a2a_skill'] == 'necklace-trip-brief'
    assert listed['trip-brief']['pearls'][0]['alternates'] == {'external': 1, 'agentcon': 1}
    assert not listed['paper-digest']['offered'] and listed['paper-digest']['notice']['necklace_status'] == 'held'


def test_a_live_page_shows_measured_numbers_completion_and_pearls(snapshot):
    status, value = ns.page('trip-brief', snapshot=snapshot, now=NOW)
    assert status == 200
    for text in ('+20.0 points (90% vs 70%)', '27/30 cases (last 7 days)', 'free', '3.2 s; slowest 5% within 4.8 s',
                 '29 of 30 test runs finished (since 2026-11-13)', 'Without AgentValCon fallbacks', '26 of 30',
                 '1 external + 1 AgentValCon fallback', 'Last retest', '/agent/133020', 'necklace_trip_brief',
                 'necklace-trip-brief', 'index, follow'):
        assert text in value, text
    assert 'role="status"' not in value  # no suspension notice on a running necklace
    for word in ('guaranteed', 'always', 'Guaranteed'):
        assert word not in value


def test_a_missing_value_hides_its_line(snapshot):
    entry = snapshot['necklaces'][0]
    entry['completion'] = {}
    entry['cost'] = {}
    _, value = ns.page('trip-brief', snapshot=snapshot, now=NOW)
    assert 'Recent completion' not in value and 'Cost per run' not in value and 'Typical time' not in value


def test_held_and_retired_pages_show_the_notice_and_offer_no_run(snapshot):
    status, held = ns.page('paper-digest', snapshot=snapshot, now=NOW)
    assert status == 200 and 'role="status"' in held and 'This necklace is paused.' in held
    assert ns.REASONS['completion_low'] in held and 'Run it' not in held and 'noindex, follow' in held
    status, retired = ns.page('old-brief', snapshot=snapshot, now=NOW)
    assert status == 200 and 'This necklace has stopped.' in retired and 'href="/necklaces/trip-brief"' in retired
    assert 'Open Trip Brief' in retired and 'Run it' not in retired


def test_after_thirty_days_a_retired_page_moves_and_unknown_pages_are_404(snapshot):
    assert ns.page('ancient-brief', snapshot=snapshot, now=NOW) == (301, '/necklaces/trip-brief')
    assert ns.page('not-approved', snapshot=snapshot, now=NOW) == (404, None)
    assert ns.page('nope', snapshot=snapshot, now=NOW) == (404, None)
    assert ns.page('../etc', snapshot=snapshot, now=NOW) == (404, None)


def test_agents_get_one_line_in_the_old_template_frame(snapshot):
    old = ns.by_slug('old-brief', snapshot)
    line = ns.agent_line(old, snapshot=snapshot)
    assert line.startswith('Necklace old-brief no longer runs (') and line.endswith('use necklace trip-brief: https://agentconcierge.biz/necklaces/trip-brief')
    assert ns.agent_line(ns.by_slug('paper-digest', snapshot)).startswith('Necklace paper-digest is paused (completion_low, since ')
    assert ns.agent_line(ns.by_slug('trip-brief', snapshot)) is None


def test_feed_lists_public_events_newest_first(snapshot):
    value = ns.feed(snapshot=snapshot)
    assert value['version'] == 'https://jsonfeed.org/version/1.1'
    kinds = [i['_necklace']['kind'] for i in value['items']]
    assert kinds == ['held', 'launched', 'retired']
    retired = value['items'][2]
    assert 'Use https://agentconcierge.biz/necklaces/trip-brief instead.' in retired['content_text']


def test_llms_section_lists_only_offered_necklaces(snapshot):
    text = ns.llms_section(snapshot=snapshot, now=NOW)
    assert '## Necklaces you can run' in text and 'necklace_trip_brief' in text and 'paper-digest' not in text
    assert ns.llms_section(snapshot={'necklaces': []}, now=NOW) == ''


def test_routes_read_the_snapshot_file_and_ignore_other_schemas(tmp_path, monkeypatch, snapshot):
    root = tmp_path
    (root / 'gateway-data/necklaces').mkdir(parents=True)
    path = root / 'gateway-data/necklaces/necklaces.json'
    path.write_text(json.dumps(snapshot))
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(root))
    app = FastAPI()
    app.include_router(ns.necklace_router())
    client = TestClient(app)
    assert client.get('/api/necklaces').status_code == 200
    assert client.get('/api/feed/necklaces.json').headers['content-type'].startswith('application/feed+json')
    assert client.get('/necklaces/paper-digest').status_code == 200
    assert client.get('/necklaces/nope').status_code == 404
    path.write_text(json.dumps({**snapshot, 'schema': 'something-else'}))
    import os
    os.utime(path, None)
    assert client.get('/api/necklaces').json()['necklaces'] == []


def test_llms_and_sitemap_put_offered_necklaces_first_and_stay_unchanged_without_any(tmp_path, monkeypatch, snapshot):
    from agent_market.concierge.front import llms_txt
    from agent_market.concierge.growth_pages import sitemap_paths
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    empty_llms = llms_txt('https://agentconcierge.biz', {}, None)
    assert 'Necklaces you can run' not in empty_llms and '/necklaces/' not in ' '.join(sitemap_paths({'tasks': [], 'catalog': [], 'captured': 0}))
    (tmp_path / 'gateway-data/necklaces').mkdir(parents=True)
    live = necklace('trip-brief', quality={'cases': 30, 'success_rate': 0.9, 'best_single_rate': 0.7, 'delta_pp': 20.0,
                                           'tested_at': iso(datetime.now(timezone.utc))})
    (tmp_path / 'gateway-data/necklaces/necklaces.json').write_text(json.dumps({**snapshot, 'necklaces': [live]}))
    text = llms_txt('https://agentconcierge.biz', {}, None)
    assert text.index('## Necklaces you can run') < text.index('Compact remote MCP')
    assert sitemap_paths({'tasks': [], 'catalog': [], 'captured': 0})[0] == '/necklaces/trip-brief'


@pytest.mark.parametrize('cumulative, shown', [
    (None, False), ({'cases': 60, 'passed': 60}, False), ({'cases': 110, 'passed': 108}, False),
    ({'cases': 110, 'passed': 109}, True), ({'cases': 200, 'passed': 200}, True)])
def test_verified_95_only_after_110_cumulative_retests_with_at_most_one_failure(snapshot, cumulative, shown):
    """PM 11-14 (workflow 98fe294c): before that, only the measured n/N."""
    entry = snapshot['necklaces'][0]
    if cumulative:
        entry['quality']['cumulative'] = cumulative
    _, value = ns.page('trip-brief', snapshot=snapshot, now=NOW)
    assert ('Verified 95%' in value) is shown and ('95%' in value) is shown
    assert '27/30 cases (last 7 days)' in value
    assert ns.public_item(entry, now=NOW)['quality']['verified_95'] is shown


def mcp(client, name, arguments):
    return client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                     'params': {'name': name, 'arguments': arguments}}).json()


@pytest.fixture
def mcp_site(tmp_path, monkeypatch, snapshot):
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    (tmp_path / 'gateway-data/necklaces').mkdir(parents=True)
    now = datetime.now(timezone.utc)
    live_one = necklace('trip-brief', gate_passed_at=iso(now - timedelta(days=1)),
                        quality={'cases_7d': 30, 'success_rate': 0.9, 'best_single_rate': 0.7, 'delta_pp': 20.0, 'tested_at': iso(now)})
    held = necklace('paper-digest', status='held', held_reason='completion_low', held_at=iso(now))
    path = tmp_path / 'gateway-data/necklaces/necklaces.json'
    path.write_text(json.dumps({**snapshot, 'necklaces': [live_one, held]}))
    return path


def test_mcp_lists_offered_necklaces_and_details_and_never_runs_a_held_one(mcp_site, client, monkeypatch):  # noqa: F811
    names = [t['name'] for t in client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()['result']['tools']]
    assert 'necklace_trip_brief' in names and 'necklace_details' in names and 'necklace_paper_digest' not in names
    details = mcp(client, 'necklace_details', {'slug': 'trip-brief'})['result']
    assert details['isError'] is False and details['structuredContent']['mcp_tool'] == 'necklace_trip_brief'
    held = mcp(client, 'necklace_paper_digest', {'city': 'Paris'})['result']
    assert held['isError'] is True and held['structuredContent']['ran'] is False
    assert held['content'][0]['text'].startswith('Necklace paper-digest is paused (completion_low')
    not_wired = mcp(client, 'necklace_trip_brief', {'city': 'Paris'})['result']
    assert not_wired['structuredContent']['error_code'] == 'not_wired' and not_wired['structuredContent']['ran'] is False
    calls = []
    monkeypatch.setattr(ns, 'RUN', lambda front, entry, arguments, source: calls.append((entry['slug'], arguments, source))
                        or {'ok': True, 'output': {'brief': 'sunny, 1 EUR = 1.08 USD'}, 'stages': {'weather': 1}})
    ran = mcp(client, 'necklace_trip_brief', {'city': 'Paris'})['result']
    assert ran['isError'] is False and ran['structuredContent']['ran'] is True and calls == [('trip-brief', {'city': 'Paris'}, 'mcp')]


def test_without_necklaces_the_tool_list_is_unchanged(tmp_path, monkeypatch, client):  # noqa: F811
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    names = [t['name'] for t in client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()['result']['tools']]
    assert not any(n.startswith('necklace_') for n in names)


def a2a(client, text):
    r = client.post('/a2a', json={'jsonrpc': '2.0', 'id': 1, 'method': 'message/send', 'params': {
        'message': {'role': 'user', 'messageId': 'm1', 'parts': [{'kind': 'text', 'text': text}]}}}).json()['result']
    return r['parts'][0]['text'], r['parts'][1]['data']


def test_a2a_card_lists_necklace_skills_and_run_necklace_follows_the_same_rules(mcp_site, client, monkeypatch):  # noqa: F811
    card = client.get('/.well-known/agent-card.json').json()
    skill = next(s for s in card['skills'] if s['id'] == 'necklace-trip-brief')
    assert skill['examples'] == ['run necklace trip-brief {"city":"<city>"}'] and 'necklace-paper-digest' not in str(card['skills'])
    text, data = a2a(client, 'run necklace trip-brief')
    assert data['error_code'] == 'needs_arguments' and 'run necklace trip-brief {"city":"<city>"}' in text
    text, data = a2a(client, 'run necklace paper-digest {"city": "Paris"}')
    assert data['ok'] is False and data['ran'] is False and text.startswith('Necklace paper-digest is paused')
    text, data = a2a(client, 'run necklace nope {}')
    assert data['error_code'] == 'unknown_necklace'
    calls = []
    monkeypatch.setattr(ns, 'RUN', lambda front, entry, arguments, source: calls.append(source) or {'ok': True, 'output': 'done'})
    text, data = a2a(client, 'run necklace trip-brief {"city": "Paris"}')
    assert data['ok'] is True and calls == ['a2a'] and text.startswith('Ran necklace trip-brief.')
    text, data = a2a(client, 'run necklace trip-brief {"city": ')
    assert data['error_code'] == 'bad_arguments' and calls == ['a2a']


def test_parse_reads_only_the_run_necklace_command():
    assert ns.parse_a2a('run necklace trip-brief {"city": "Paris"}') == ('trip-brief', {'city': 'Paris'})
    assert ns.parse_a2a('Run Necklace trip-brief') == ('trip-brief', None)
    assert ns.parse_a2a('run 1 {"city": "Paris"}') is None and ns.parse_a2a('find a necklace') is None

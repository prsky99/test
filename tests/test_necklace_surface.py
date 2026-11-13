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
             'quality': {'cases': 30, 'success_rate': 0.9, 'best_single_rate': 0.7, 'delta_pp': 20.0,
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
    for text in ('+20.0 points (90% vs 70%)', '90% of 30 cases', 'free', '3.2 s (95%: 4.8 s)',
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

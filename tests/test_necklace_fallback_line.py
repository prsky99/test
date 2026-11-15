"""PM 13:53 decision 3 (11-15): a necklace's public page and /api/necklaces entry say how far a run can fall back.

The judge's snapshot carries entry['fallback'] (workflow team): depth 'agentvalcon' (every required slot ends in one of
our own agents) or 'external' (named slots have outside members only). The page shows the snapshot value with no promise;
a malformed value shows nothing rather than a guess."""
from agent_market.concierge import necklace_surface as ns

ENTRY = {'slug': 'quakes-near-address', 'name': 'Quakes near an address', 'summary': 'Recent earthquakes near a place.',
         'status': 'held', 'gate_passed_at': '2026-11-15T00:00:00Z', 'pearls': []}


def snapshot(value):
    return {'schema': ns.SCHEMA, 'necklaces': [{**ENTRY, 'fallback': value}], 'events': []}


def test_external_names_the_slots_and_says_the_run_stops():
    value = {'depth': 'external', 'slots_without_own': ['location', 'quakes']}
    line = 'Fallback: other providers only for location, quakes (no AgentValCon backup yet). If they all fail, the run stops.'
    assert ns.fallback_line({'fallback': value}) == line
    status, page = ns.page('quakes-near-address', snapshot=snapshot(value))
    assert status == 200 and '<p class="muted necklace-fallback">' + line + '</p>' in page
    assert ns.public_item({**ENTRY, 'fallback': value})['fallback'] == value


def test_agentvalcon_depth_has_no_slot_list():
    value = {'depth': 'agentvalcon', 'slots_without_own': []}
    assert ns.fallback_line({'fallback': value}).endswith('then an AgentValCon backup, for every step.')
    assert ns.public_item({**ENTRY, 'fallback': value})['fallback'] == value


def test_missing_or_malformed_values_show_nothing():
    for value in (None, 'external', {'depth': 'internal'}, {'depth': 'external', 'slots_without_own': []},
                  {'depth': 'agentvalcon', 'slots_without_own': ['location']},
                  {'depth': 'external', 'slots_without_own': ['<b>x</b>']}, {'depth': 'external', 'slots_without_own': 'location'}):
        assert ns.fallback_line({'fallback': value}) is None, value
        assert 'fallback' not in ns.public_item({**ENTRY, 'fallback': value}), value
    status, page = ns.page('quakes-near-address', snapshot=snapshot(None))
    assert status == 200 and 'necklace-fallback' not in page

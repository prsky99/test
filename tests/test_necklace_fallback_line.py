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
                  {'depth': 'external', 'slots_without_own': ['<b>x</b>']}, {'depth': 'external', 'slots_without_own': 'location'},
                  {'depth': 'agentvalcon', 'slots_without_own': [], 'own_coverage': {'location': {'country': ['us']}}},
                  {'depth': 'agentvalcon', 'slots_without_own': [], 'own_coverage': {'location': {'country': []}}},
                  {'depth': 'agentvalcon', 'slots_without_own': [], 'own_coverage': {'location': {'region': ['US']}}},
                  {'depth': 'external', 'slots_without_own': ['location'], 'own_coverage': {'location': {'country': ['US']}}}):
        assert ns.fallback_line({'fallback': value}) is None, value
        assert 'fallback' not in ns.public_item({**ENTRY, 'fallback': value}), value
    status, page = ns.page('quakes-near-address', snapshot=snapshot(None))
    assert status == 200 and 'necklace-fallback' not in page


def test_partial_own_backup_names_its_limit():
    value = {'depth': 'agentvalcon', 'slots_without_own': [], 'own_coverage': {'location': {'country': ['US']}}}
    line = ns.fallback_line({'fallback': value})
    assert line.endswith('for every step. Our backup is partial: for location it takes U.S. inputs only.')
    assert ns.public_item({**ENTRY, 'fallback': value})['fallback'] == value
    mixed = {'depth': 'external', 'slots_without_own': ['quakes'], 'own_coverage': {'location': {'country': ['US', 'CA']}}}
    assert ns.fallback_line({'fallback': mixed}).endswith(
        'the run stops. Our backup is partial: for location it takes U.S. and CA inputs only.')
    assert ns.fallback({'fallback': {**value, 'own_coverage': {}}}) == {'depth': 'agentvalcon', 'slots_without_own': []}


SCOPE = ('National public holidays only: regional (state or province) holidays are not included. A place in an overseas '
         "territory is answered with the holidays of the country it belongs to, which can differ from the territory's own.")


def test_scope_notice_is_shown_before_a_run():
    """Workflow 36b92e0d: the definition's scope sentence, until now used only to refuse, is also shown up front."""
    status, page = ns.page('quakes-near-address', snapshot={'schema': ns.SCHEMA, 'events': [],
                                                           'necklaces': [{**ENTRY, 'scope_notice': SCOPE}]})
    assert status == 200 and '<p class="necklace-scope"><strong>Scope:</strong> National public holidays only' in page
    assert "territory&#x27;s own." in page                      # escaped as text
    assert ns.public_item({**ENTRY, 'scope_notice': SCOPE})['scope_notice'] == SCOPE
    for value in (None, '', '   ', 7, 'x' * 601):
        assert ns.scope_notice({'scope_notice': value}) is None
        assert 'scope_notice' not in ns.public_item({**ENTRY, 'scope_notice': value})
    assert 'necklace-scope' not in ns.page('quakes-near-address', snapshot=snapshot(None))[1]


def _approvals(tmp_path, monkeypatch, rows):
    import json
    folder = tmp_path / 'gateway-data/necklaces'
    folder.mkdir(parents=True)
    (folder / 'approvals.json').write_text(json.dumps({'substitutes': rows}), encoding='utf-8')
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))


CONNECT_ROW = {'resource_id': 'avc:tls-certificate', 'agent_id': 'tls-certificate', 'tool': 'check_tls_certificate',
               'state': 'approved', 'at': '2026-11-18T21:31:38+0900',
               'gate_record': {'connect_test': 'gateway-data/necklaces/connect/website-trust-brief.jsonl', 'runs': '3/3 ok'}}
DNS_ROW = {'resource_id': 'avc:dns-spf-dmarc', 'agent_id': 'dns-spf-dmarc', 'tool': 'lookup_spf_dmarc',
           'state': 'approved', 'at': '2026-11-18T21:31:38+0900', 'gate_record': {'connect_test': 'x', 'runs': '3/3 ok'}}
TRUST = {**ENTRY, 'slug': 'website-trust-brief', 'fallback': {'depth': 'agentvalcon', 'slots_without_own': []}, 'pearls': [
    {'role': 'registration', 'resource_id': 52559, 'tool': 'whois_lookup', 'kind': 'external', 'required': True,
     'standing': 'verified_pearl', 'alternates': [{'agent_id': 'rdap-domain', 'kind': 'agentcon', 'tool': 'lookup_domain'}]},
    {'role': 'mail_auth', 'resource_id': 39800, 'tool': 'dns_records', 'kind': 'external', 'required': True,
     'standing': 'verified_pearl', 'alternates': [{'agent_id': 'dns-spf-dmarc', 'kind': 'agentcon', 'tool': 'check_spf_dmarc'}]},
    {'role': 'tls', 'resource_id': None, 'tool': 'check_tls_certificate', 'kind': 'agentcon', 'required': True,
     'standing': 'provisional', 'alternates': []},
    {'role': 'crawlers', 'resource_id': 267572, 'tool': 'check_llms_txt', 'kind': 'external', 'required': False,
     'alternates': []}]}


def test_a_step_without_an_outside_fallback_never_reads_other_providers_are_tried(tmp_path, monkeypatch):
    """PM 21:33 (11-18): the page said 'other providers are tried ... for every step' while two steps had no outside
    fallback. The line comes from each required step's members and approvals.json, the source the run itself uses."""
    _approvals(tmp_path, monkeypatch, [CONNECT_ROW, DNS_ROW])
    line = ns.fallback_line(TRUST)
    assert 'other providers are tried' not in line and 'for every step' not in line
    # rdap-domain has no passed check here; dns-spf-dmarc is found by its agent though the definition names its tool
    # differently; tls is led by our own agent; the optional crawlers step is not listed
    assert line == ('Fallback per step: registration: no fallback yet; mail_auth: our own agent; tls: our own agent, '
                    'no other provider yet. If a step’s fallbacks also fail, the run stops.')
    item = ns.public_item(TRUST)
    assert [p['alternates']['agentcon'] for p in item['pearls']] == [0, 1, 0, 0]    # unchecked ones are not counted
    every = {**TRUST, 'pearls': [dict(p, alternates=p['alternates'] + [{'kind': 'external', 'resource_id': 9}])
                                 for p in TRUST['pearls'][:2]]}
    assert ns.fallback_line(every) == ('Fallback per step: registration: other providers; mail_auth: other providers, '
                                       'then our own agent. If a step’s fallbacks also fail, the run stops.')


def test_our_agent_approved_by_connection_runs_claims_no_accuracy(tmp_path, monkeypatch):
    """PM 21:33: tls-certificate's approval (three connection runs, 21:31) was not read, because the row's resource_id
    is 'avc:tls-certificate' and the snapshot lead has none; and its note must not claim a held-out or accuracy check."""
    _approvals(tmp_path, monkeypatch, [CONNECT_ROW])
    tls = TRUST['pearls'][2]
    assert ns.substitute_checked(tls) and ns.own_checked_note(tls) == ns.OWN_CONNECTED_NOTE
    assert 'accuracy is not scored' in ns.OWN_CONNECTED_NOTE and '30-case' not in ns.OWN_CONNECTED_NOTE
    status, page = ns.page('website-trust-brief', snapshot={'schema': ns.SCHEMA, 'events': [], 'necklaces': [
        {**TRUST, 'status': 'preview', 'preview': {'gate_passed': False, 'note': 'Preview — test runs in progress'}}]})
    assert status == 200 and 'no passed substitute check' not in page and 'held-out' not in page

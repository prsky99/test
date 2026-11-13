"""PM pearl audit 11-14: role task test v2 (content checks, failures kept, stacked versions, score, final pearl)."""
import time

import pytest

from scripts import report_v2 as V


@pytest.fixture(autouse=True)
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'OUT', tmp_path)
    return tmp_path


def result(rid=1, role='fx.rate', tool='convert', outcome='succeeded', excerpt='1 USD = 0.92 EUR on 2026-11-14',
           host='api.example.com', latency=300, args=None, started=None):
    return {'id': rid, 'role': role, 'tool': tool, 'outcome': outcome, 'excerpt': excerpt, 'host': host,
            'latency_ms': latency, 'arguments': {'from': 'USD', 'to': 'EUR'} if args is None else args,
            'started': started or time.time(), 'reason': None if outcome == 'succeeded' else 'tool error'}


def test_content_checks_per_role():
    assert V.judge('fx.rate', '1 USD = 0.92 EUR', {})['passed'] == 2
    assert V.judge('fx.rate', 'rate unavailable', {})['passed'] == 0
    cve = V.judge('cve.kev', 'CVE-2021-44228 CVSS 10.0 critical, known exploited', {'cve_id': 'CVE-2021-44228'})
    assert cve['passed'] == cve['total'] == 2


def test_a_failure_is_kept_and_scores_low():
    v = V.save_version(result(outcome='failed', excerpt=''))
    assert v['version'] == 1 and v['content_verdict'] == 'not run'
    assert v['quality']['score'] < V.PASS_MARK


def test_versions_stack():
    first = V.save_version(result(started=time.time() - 2 * V.DAY))
    second = V.save_version(result())
    assert (first['version'], second['version']) == (1, 2)
    assert second['quality']['evidence']['repeat'] == 10         # two successful days in the last 7 (5 a day)


def test_no_arguments_and_collector_message_score_less():
    assert V.save_version(result(args={}))['quality']['evidence']['arguments'] == 0
    collector = dict(result(rid=2), source='collector message')
    assert V.save_version(collector)['quality']['evidence']['arguments'] == 5


@pytest.fixture
def accurate(monkeypatch):
    """Answers that matched an answer set and are fresh, so ranking is what is under test."""
    monkeypatch.setattr(V.DQ, 'accuracy', lambda *a, **k: (25, 'answer set test', []))
    monkeypatch.setattr(V.DQ, 'freshness', lambda role, text, now=None: (10, 'test', '2026-11-14T09:00'))


def test_rank_final_pearl_and_failure_domains(accurate):
    V.save_version(result(rid=1, host='a.caseyjhand.com', latency=200))
    V.save_version(result(rid=2, host='b.caseyjhand.com', latency=250))      # same failure domain: no second place
    V.save_version(result(rid=3, host='fx.other.com', latency=1500))
    V.save_version(result(rid=4, host='bad.example.org', outcome='failed', excerpt=''))
    ranked = V.rank(V.latest_versions())[V.canonical('fx.rate')]
    places = {m['resource_id']: m['rank'] for m in ranked['members']}
    assert places[1] == 1 and places[2] is None and places[3] == 2 and places[4] is None
    assert ranked['provisional_pearl'] == 1 and ranked['final_pearl'] is None      # one day only
    assert ranked['fallbacks'] == [3] and ranked['domain'] == 'finance'


def test_below_the_mark_is_not_a_final_pearl():
    V.save_version(result(rid=5, excerpt='no data', latency=9000))
    assert V.rank(V.latest_versions())[V.canonical('fx.rate')]['final_pearl'] is None


def test_registrable_domain():
    assert V.registrable('met-mcp-worker.workers.dev') == 'met-mcp-worker.workers.dev'
    assert V.registrable('openalex.caseyjhand.com') == 'caseyjhand.com'
    assert V.registrable('api.example.co.uk') == 'example.co.uk'


def test_role_task_case_scores_the_full_answer():
    case = V.case_for('cve.kev', day=0)
    assert case and case['role'] == 'cve.exploited.v1'
    if case['expect'].get('kev') is True:
        text = case['input']['cve_id'] + ' is in the CISA KEV catalog (known exploited).'
    else:
        text = case['input']['cve_id'] + ' is not in the CISA KEV catalog.'
    good = V.save_version({**result(rid=9, role='cve.kev', tool='kev', excerpt=text[:20]), 'case': case, 'full_text': text})
    acc = good['data_quality']['accuracy']
    assert good['case_id'] == case['case_id'] and acc['source'].startswith('answer set ' + case['case_id'])
    assert acc['points'] in (0, 25) and (acc['points'] == 25 or acc['reasons'])


def test_no_case_for_roles_without_tasks():
    assert V.case_for('no.such.role') is None
    assert V.case_for('fx.rate', day=0)['role'] == 'fx.rate.v1'          # 11-14 bc0aabce


def test_measurement_windows():
    import time as _t
    def at(h, m):
        return _t.mktime((2026, 11, 15, h, m, 0, 0, 0, -1))
    assert V.quiet_now(at(9, 12)) and not V.quiet_now(at(9, 56)) and not V.quiet_now(at(10, 5))
    assert not V.quiet_now(at(4, 30)) and V.quiet_now(at(5, 12))


def test_one_day_is_provisional_two_days_confirm(accurate):
    V.save_version(result(rid=11, latency=200))
    ranked = V.rank(V.latest_versions())[V.canonical('fx.rate')]
    assert ranked['final_pearl'] is None and ranked['provisional_pearl'] == 11
    V.save_version(result(rid=11, latency=200, started=time.time() - V.DAY))
    ranked = V.rank(V.latest_versions())[V.canonical('fx.rate')]
    assert ranked['final_pearl'] == 11 and ranked['provisional_pearl'] is None


def test_one_list_of_role_names():
    """PM 11-14: the workflow contracts, the role tasks and our files use the same role names."""
    import json
    from pathlib import Path
    known = V.known_roles()
    contracts = {p.name[:-5] for p in (V.ROOT / 'agent_market/necklaces/contracts').glob('*.json')}
    assert contracts <= known
    assert V.canonical('cve.kev') == 'cve.exploited.v1' and V.canonical('fx.rate.v1') == 'fx.rate.v1'
    assert V.short('cve.exploited.v1') == 'cve.kev'
    V.save_version(result(rid=21, role='cve.kev', tool='t', excerpt='CVE-2021-44228 critical'))
    assert set(V.rank(V.latest_versions())) <= known
    groups = V.ROOT / 'reports/pearls-2026-11-14/role_groups.json'
    if groups.exists():
        names = set(json.loads(groups.read_text()).get('roles', {}))
        assert all(V.canonical(n) in known for n in names)


def test_new_queue_spreads_roles_domains_and_hosts():
    cands = [('domain.lookup.v1', 1, 'whois', 'a.x.com'), ('domain.lookup.v1', 2, 'whois', 'b.x.com'),   # same domain
             ('domain.lookup.v1', 3, 'whois', 'c.y.com'), ('ip.lookup.v1', 4, 'ip_info', 'h.z.com'),
             ('ip.lookup.v1', 5, 'ip_info', 'h.z.com'), ('ip.lookup.v1', 6, 'ip_info', 'h.z.com'), ('ip.lookup.v1', 7, 'ip_info', 'h.z.com')]
    q = V.new_queue([], cands, limit=10, per_host=3)
    ids = [c['id'] for c in q]
    assert 2 not in ids and {1, 3, 4} <= set(ids)                 # one per registrable domain in a role
    assert all(c['kind'] == 'new' for c in q) and len(q) == 3        # h.z.com: same domain as 4 in ip.lookup


def test_retest_queue_takes_the_top_members():
    for rid, lat in ((31, 200), (32, 300), (33, 400)):
        V.save_version(result(rid=rid, host=f'h{rid}.example{rid}.com', latency=lat))
    q = V.retest_queue(V.latest_versions(), day=0)
    assert [c['id'] for c in q][:2] == [31, 32] and all(c['kind'] == 'retest' for c in q)


def test_catalog_roles_have_checks_and_names():
    from scripts import role_catalog
    assert len(role_catalog.ROLES) >= 30 and all(r.endswith('.v1') for r in role_catalog.ROLES)
    assert role_catalog.roles_for_tool('whois_lookup') == ['domain.lookup.v1']
    v = V.save_version(result(rid=41, role='timezone.time.v1', tool='get_time', excerpt='New York 08:41 EST', args={'timezone': 'America/New_York'}))
    assert v['judgement']['passed'] == v['judgement']['total'] == 2 and v['domain'] == 'reference'


def test_moving_prices_are_judged_by_range_format_and_time(monkeypatch):
    monkeypatch.setattr(V, 'reference_value', lambda url, ttl=600: 100000.0)
    ok = V.judge('crypto.price.v1', 'BTC price 101,250.50 USD, updated 2026-11-15T09:12Z', {})
    assert ok['passed'] == ok['total'] == 4
    off = V.judge('crypto.price.v1', 'BTC price 90,000 USD, updated 2026-11-15T09:12Z', {})
    assert off['passed'] == 3                                     # 10% away: the range check fails
    monkeypatch.setattr(V, 'reference_value', lambda url, ttl=600: None)
    unknown = V.judge('stock.quote.v1', 'AAPL last 231.40 USD as of 16:00', {})
    assert unknown['passed'] == 3 and unknown['not_checked_live']  # no reference: not passed, said so



def test_data_quality_decides_the_score():
    """PM 11-14: no answer source -> no accuracy points -> never 85; an unclean answer fails the version."""
    plain = V.save_version(result(rid=51, role='airport.lookup.v1', tool='airport', excerpt='ICN Incheon International Airport'))
    assert plain['data_quality']['accuracy']['points'] == 0 and plain['quality']['score'] < V.PASS_MARK
    demo = V.save_version(result(rid=52, excerpt='[DEMO] sample data: 1 USD = 0.92 EUR on 2026-11-14'))
    assert demo['outcome'] == 'failed' and 'unclean' in demo['reason']
    blank = V.save_version({**result(rid=53, role='papers.search.v1', tool='search_papers', excerpt=''),
                            'full_text': '{"title": "Attention Is All You Need", "authors": [], "year": 2017, "journal": null}'})
    assert blank['data_quality']['completeness']['blanks'] == 2 and blank['data_quality']['completeness']['points'] < 10
    assert 'Blank fields: 2' in blank['quality']['text'] and 'Accuracy checked against' in blank['quality']['text']


def test_freshness_rules():
    from scripts import data_quality as DQ
    now = V.time.mktime((2026, 11, 14, 12, 0, 0, 0, 0, -1))
    assert DQ.freshness('events.search.v1', 'Festival on 2020-05-15', now)[0] == 0          # 47538: a past date
    assert DQ.freshness('events.search.v1', 'Concert on 2026-11-20', now)[0] == 10
    assert DQ.freshness('news.search.v1', 'no date at all', now)[0] == 0
    assert DQ.freshness('fx.rate.v1', '{"date": "2026-11-13", "rate": 0.92}', now)[0] == 10
    assert DQ.freshness('airport.lookup.v1', 'ICN', now)[0] == 10                            # fixed facts


def test_dynamic_references():
    from scripts import data_quality as DQ
    assert DQ.dynamic_match('rate', 0.92, '100 USD = 92.10 EUR', {'amount': 100}, 0.02)
    assert not DQ.dynamic_match('rate', 0.92, '100 USD = 80 EUR', {'amount': 100}, 0.02)
    assert DQ.dynamic_match('temperature_c', 8.0, 'Seoul now 10°C, cloudy', None, 3)
    assert not DQ.dynamic_match('temperature_c', 8.0, 'Seoul now 70°F', None, 3)
    assert DQ.dynamic_match('latest_version', '5.1.0', 'express 5.1.0 published', None)


def test_rag_role_tasks_cover_every_role():
    """PM 11-14: by 11-16 every role is judged against an answer set or a same-time public reference."""
    from scripts import role_catalog
    for role in role_catalog.ROLES:
        assert V.case_for(role, day=0) or role_catalog.live_spec(role), role
    for case in V.role_tasks_rag():
        assert case['truth_sources'] and all(t['url'].startswith('https://') and t['checked_on'] for t in case['truth_sources'])


def test_same_time_references():
    from scripts import data_quality as DQ
    import datetime as dt
    ny = dt.datetime(2026, 11, 14, 15, 2)
    assert DQ.dynamic_match('clock_tz', ny, 'It is 15:04 in New York', None, 5)
    assert not DQ.dynamic_match('clock_tz', ny, 'It is 09:30 in New York', None, 5)
    places = ['120 km SSE of Tobelo, Indonesia', '45 km W of Ovalle, Chile']
    assert DQ.dynamic_match('usgs_places', places, 'M5.4 near Tobelo, Indonesia') and not DQ.dynamic_match('usgs_places', places, 'M5.0 Fiji')
    assert DQ.dynamic_match('scorecard', 7.2, 'OpenSSF score 7.4/10', None, 0.5)


def test_versions_are_signed_when_a_key_exists(tmp_path, monkeypatch):
    """운영·SRE EVIDENCE_SIGNING.md: DSSE over the JCS evidence; without a key nothing is signed."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from agent_market import evidence_signing as ES
    monkeypatch.setattr(V, 'SIGNING', tmp_path / 'signing')
    assert V.save_version(result(rid=61))['signed_report'] is None
    key = Ed25519PrivateKey.generate()
    entry = ES.key_entry(key, '2026-01-01T00:00:00Z', '2030-01-01T00:00:00Z')
    (tmp_path / 'signing').mkdir()
    pem = tmp_path / 'signing' / f"{entry['keyid']}.pem"
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    pem.chmod(0o600)
    doc = {'keys': [entry], 'revoked': []}
    (tmp_path / 'signing' / 'agentvalcon-keys.json').write_text(__import__('json').dumps(doc))
    monkeypatch.setattr(V, 'ROOT', tmp_path)
    v = V.save_version(result(rid=62))
    failed = V.save_version(result(rid=62, outcome='failed', excerpt=''))       # failures stay in the chain
    paths = [tmp_path / v['signed_report'], tmp_path / failed['signed_report']]
    assert [p.name for p in paths] == ['1.json', '2.json']
    envelopes = [__import__('json').loads(p.read_text()) for p in paths]
    bodies = ES.verify_chain(envelopes, doc)
    body = bodies[0]
    assert body['kind'] == 'test_report' and body['resource_id'] == 62 and body['methodology_version'] == 'v1'
    assert body['response_sha256'] == v['response_hash'] and 'excerpt' not in body and body['prev'] is None
    assert body['status'] in ('none', 'provisional', 'verified') and body['total_score'] == v['quality']['score']
    assert set(body['data_quality']) >= {'freshness_age_days', 'blank_ratio', 'clean'} and bodies[1]['outcome'] == 'failed'
    import pytest as _pytest
    with _pytest.raises(ES.SigningError):
        ES.verify_chain(envelopes[1:], doc)                                    # dropping version 1 breaks the chain


def test_reference_sources_respect_their_terms(monkeypatch):
    """PM 11-14: Open-Meteo (non-commercial) is replaced by MET Norway; an answer from MET Norway is not judged by MET
    Norway; references whose terms are not confirmed are suspended, not used."""
    from scripts import data_quality as DQ
    monkeypatch.setattr(DQ, '_met_temperature', lambda url: 8.0)
    DQ._CACHE.clear()
    case = {'case_id': 'weather-seoul', 'role': 'weather.forecast.v1', 'input': {'city': 'Seoul'},
            'expect': {'must_include_any': ['°C'], 'dynamic': {'temperature_c': 'https://api.open-meteo.com/v1/forecast?latitude=37.5665&longitude=126.978', 'tolerance': 3}}}
    from agent_market.necklaces import role_tasks
    assert DQ.accuracy(case, 'Seoul 9°C now', None, role_tasks=role_tasks)[0] == DQ.WEIGHTS['accuracy']
    own = DQ.accuracy(case, 'Seoul 9°C now (data: MET Norway, api.met.no)', None, role_tasks=role_tasks)
    assert own[0] == 0 and 'not checked' in own[1]
    suspended = DQ.accuracy(None, 'BTC 68,900 USD', None, live={'reference': 'x', 'tolerance': 0.02, 'terms_ok': False, 'note': 'n'})
    assert suspended[0] == 0 and suspended[1].startswith('public reference suspended')

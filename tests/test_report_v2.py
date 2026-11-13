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
    assert second['quality']['evidence']['repeat'] == 6          # two successful days in the last 7


def test_no_arguments_and_collector_message_score_less():
    assert V.save_version(result(args={}))['quality']['evidence']['arguments'] == 0
    collector = dict(result(rid=2), source='collector message')
    assert V.save_version(collector)['quality']['evidence']['arguments'] == 7.5


def test_rank_final_pearl_and_failure_domains():
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
    assert good['judgement']['total'] == 1 and good['case_id'] == case['case_id']
    assert good['judgement']['passed'] == 1 or good['judgement']['reasons']


def test_no_case_for_roles_without_tasks():
    assert V.case_for('no.such.role') is None
    assert V.case_for('fx.rate', day=0)['role'] == 'fx.rate.v1'          # 11-14 bc0aabce


def test_measurement_windows():
    import time as _t
    def at(h, m):
        return _t.mktime((2026, 11, 15, h, m, 0, 0, 0, -1))
    assert V.quiet_now(at(9, 12)) and not V.quiet_now(at(9, 56)) and not V.quiet_now(at(10, 5))
    assert not V.quiet_now(at(4, 30)) and V.quiet_now(at(5, 12))


def test_one_day_is_provisional_two_days_confirm():
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

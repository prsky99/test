"""PM 11-16 17:5x: three test windows a day (80 new + 40 retests each) and the new queue order."""
import sys
import time
import types

import pytest

from scripts import report_v2 as V


@pytest.fixture(autouse=True)
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'OUT', tmp_path)
    return tmp_path


def at(hour, minute=12):
    return time.mktime((2026, 11, 16, hour, minute, 0, 0, 0, -1))


def test_window_number_by_hour():
    assert [V.window_number(at(h)) for h in (9, 14, 15, 18, 19, 20, 23)] == [1, 1, 2, 2, 2, 3, 3]


def version(rid, role, score=90.0, outcome='succeeded', tested=None, evaluator='old'):
    return {'resource_id': rid, 'role': role, 'tool': 't', 'outcome': outcome, 'quality': {'score': score},
            'tested': tested or time.time() - 3 * V.DAY, 'evaluator_version': evaluator, 'registrable_domain': f'd{rid}.com'}


def test_first_batch_necklace_roles_follow_the_pm_order_and_leave_the_second_batch_out():
    assert V.NECKLACE_NEW_ROLES[:2] == ('mcp.registry.lookup.v1', 'github.repo.v1')
    assert V.NECKLACE_NEW_ROLES[-2:] == ('geocode.address.v1', 'weather.forecast.v1')
    assert not {'news.search.v1', 'sec.filings.v1', 'company.profile.v1', 'stock.quote.v1', 'fx.rate.v1',
                'timezone.time.v1', 'holiday.calendar.v1'} & set(V.NECKLACE_NEW_ROLES)
    import role_catalog
    assert set(V.NECKLACE_NEW_ROLES) <= set(role_catalog.ROLES)


def test_queue_priority_puts_untested_roles_then_new_necklace_roles_then_roles_without_a_pearl():
    versions = [version(1, 'fx.rate.v1'), version(2, 'news.search.v1'), version(3, 'weather.forecast.v1')]
    ranked = {'fx.rate.v1': {'final_pearl': 1}, 'news.search.v1': {'final_pearl': None},
              'weather.forecast.v1': {'final_pearl': None}}
    roles = ['fx.rate.v1', 'news.search.v1', 'weather.forecast.v1', 'company.profile.v1', 'holiday.calendar.v1']
    order = V.queue_priority(versions, ranked, roles=roles)
    assert order[0] == 'papers.search.v1'                                       # PM 18:2x: topic necklace's papers seat
    assert order[1:3] == ('company.profile.v1', 'holiday.calendar.v1')          # nothing tested yet
    assert order.index('weather.forecast.v1') < order.index('news.search.v1')    # first-batch necklace role first
    assert 'fx.rate.v1' not in order                                              # has a final pearl
    assert len(order) == len(set(order))


def test_rejudge_takes_85_plus_and_top_three_first():
    versions = [version(1, 'fx.rate.v1', 60), version(2, 'fx.rate.v1', 88), version(3, 'book.search.v1', 50),
                version(4, 'fx.rate.v1', 70)]
    out = V.rejudge_queue(versions, terms={}, ranks={(3, 'book.search.v1'): 2})
    assert [x['id'] for x in out][:2] == [2, 3] and {x['id'] for x in out[2:]} == {1, 4}


def test_members_tested_today_are_left_out():
    now = time.time()
    versions = [version(1, 'fx.rate.v1', tested=now), version(2, 'fx.rate.v1', tested=now - 2 * V.DAY)]
    assert V.tested_today(versions, now) == {(1, 'fx.rate.v1')}


def test_near_members_come_after_the_second_day_and_skip_is_applied_before_the_limit(monkeypatch):
    members = [{'resource_id': 1, 'tool': 't', 'rank': 1, 'success_days': 1, 'best_recent_score': 90},
               {'resource_id': 2, 'tool': 't', 'rank': 2, 'success_days': 1, 'best_recent_score': 78},
               {'resource_id': 3, 'tool': 't', 'rank': 3, 'success_days': 1, 'best_recent_score': 82},
               {'resource_id': 4, 'tool': 't', 'rank': 4, 'success_days': 0, 'best_recent_score': 40}]
    monkeypatch.setattr(V, 'rank', lambda versions: {'fx.rate.v1': {'members': members}})
    assert [c['id'] for c in V.retest_queue([], day=0)][:3] == [1, 3, 2]
    assert [c['id'] for c in V.retest_queue([], day=0, limit=2, skip={(1, 'fx.rate.v1')})] == [3, 2]


class FakePacer:
    state = {}

    def __init__(self, **_):
        self.state = FakePacer.state

    def save(self):
        pass


def test_each_window_gets_its_own_120_and_the_day_stops_at_360(monkeypatch):
    FakePacer.state = {'role_tests': 90, 'new_tests': 55, 'retests': 35, 'refusals': 0}
    calls = []
    monkeypatch.setitem(sys.modules, 'pearl_batch', types.SimpleNamespace(Pacer=FakePacer, STATE_DIR=None))
    monkeypatch.setitem(sys.modules, 'role_tool_test', types.SimpleNamespace(
        resources=lambda ids: {}, test_one=lambda http, c, r, p: calls.append(c['id']) or {'outcome': 'failed'}))
    monkeypatch.setattr(V, 'quiet_now', lambda: True)
    monkeypatch.setattr(V, 'save_once_more', lambda result: True)
    monkeypatch.setattr(V, 'case_for', lambda role: None)
    monkeypatch.setattr(V, 'window_number', lambda now=None: 3)
    queue = [{'role': 'fx.rate.v1', 'id': i, 'tool': 't', 'kind': 'retest' if i < 60 else 'new'} for i in range(200)]
    V.run(queue)
    state = FakePacer.state
    assert state['windows']['3'] == {'role_tests': 90, 'new_tests': 55, 'retests': 35}
    assert (state['retests'], state['new_tests'], state['role_tests']) == (75, 135, 210)   # 40 + 80 in this window
    V.run(queue)                                       # a second start in the same window gets nothing more
    assert state['role_tests'] == 210 and len(calls) == 120


def test_later_windows_have_their_own_done_file_and_launchd_starts_all_three():
    import plistlib
    from pathlib import Path
    from scripts import pearl_daily
    assert [pearl_daily.window_suffix(n) for n in (1, 2, 3)] == ['', '-w2', '-w3']
    root = Path(__file__).resolve().parents[1] / 'deploy/launchd'
    for folder in ('ops', 'ops-pinned'):
        plist = plistlib.loads((root / folder / 'biz.agentconcierge.opsauto.pearltests.plist').read_bytes())
        starts = [(x['Hour'], x['Minute']) for x in plist['StartCalendarInterval']]
        assert starts == [(9, 12), (15, 12), (20, 12)]
        assert all(V.window_number(at(h, m)) == n for n, (h, m) in enumerate(starts, 1))


def test_papers_candidates_all_go_first_in_terms_order():
    cands = [('papers.search.v1', i, 't', f'p{i}.example') for i in range(1, 7)] + \
            [('weather.forecast.v1', 10 + i, 't', f'w{i}.example') for i in range(3)]
    terms = {1: 'prohibits', 2: None, 5: 'silent', 6: 'allowed'}
    out = V.new_queue([], cands, limit=9, terms=terms, priority=V.queue_priority([], {}, roles=['weather.forecast.v1']))
    assert [x['id'] for x in out][:5] == [6, 5, 2, 3, 4] and 1 not in [x['id'] for x in out]


def test_the_queue_keeps_only_members_the_ledger_still_lets_role_tests_call(tmp_path):
    import json as _json
    from agent_market import provider_budget as B
    day = B.today()
    (tmp_path / f'{day}.json').write_text(_json.dumps({'domains': {
        'used.com': {'total': 4, 'by': {'role_tests': 4}}, 'paused.com': {'total': 0, 'by': {}, 'paused': True}}}))
    (tmp_path / f'plan-{day}.json').write_text(_json.dumps({'holds': {'held.com': {'gate': 10 ** 6}}}))
    item = lambda rid, kind='new': {'role': 'fx.rate.v1', 'id': rid, 'tool': 't', 'kind': kind}
    hosts = {(1, 't'): 'a.used.com', (2, 't'): 'paused.com', (3, 't'): 'held.com', (4, 't'): 'free.com',
             (5, 't'): 'x.free.com', (6, 't'): 'other.com', (7, 't'): 'r.com'}
    out = V.fit_budget([item(7, 'retest')], [], [item(i) for i in range(1, 7)], hosts, directory=tmp_path)
    assert [x['id'] for x in out] == [7, 4, 6]      # used share, paused, gate hold and a second free.com member left out


def test_tools_outside_their_role_are_never_ranked():
    v = lambda rid: {'resource_id': rid, 'role': 'fx.rate.v1', 'tool': 'get_rate', 'outcome': 'succeeded', 'quality': {'score': 90.0},
                     'tested': time.time(), 'registrable_domain': f'd{rid}.com', 'domain': 'finance', 'judgement': {}}
    assert ('fx.rate.v1', 59569) in V.NOT_THIS_ROLE and ('stock.quote.v1', 46568) in V.NOT_THIS_ROLE
    ranked = V.rank([v(59569)])
    assert 'fx.rate.v1' not in ranked or not ranked['fx.rate.v1']['members']


def test_first_picks_lead_the_new_candidates(tmp_path):
    f = tmp_path / 'picks.json'
    f.write_text('[{"role": "timezone.time.v1", "id": 84607}, {"role": "fx.rate.v1", "id": 9}, {"role": "fx.rate.v1", "id": 8}]')
    cands = [('timezone.time.v1', 84607, 'current_time', 'plumbkit.dev'), ('timezone.time.v1', 84607, 'convert_timezone', 'plumbkit.dev'),
             ('fx.rate.v1', 9, 'rate', 'x.com'), ('fx.rate.v1', 8, 'rate', 'y.com')]
    out = V.first_picks(cands, {9: 'prohibits'}, {(8, 'fx.rate.v1')}, path=f)
    assert out == [{'role': 'timezone.time.v1', 'id': 84607, 'tool': 'current_time', 'kind': 'new'}]
    assert V.first_picks(cands, {}, set(), path=tmp_path / 'none.json') == []

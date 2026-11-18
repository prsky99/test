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
    # PM 11-18 21:00: eight windows at 07, 09, 11, 13, 15, 17, 20 and 23; before 07:00 is window 0
    assert [V.window_number(at(h)) for h in (0, 6, 7, 9, 10, 14, 15, 18, 19, 20, 23)] == [0, 0, 1, 2, 2, 4, 5, 6, 6, 7, 8]


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
    order = V.queue_priority(versions, ranked, roles=roles, terms={1: 'allowed'}, seats=[])
    assert order[0] == 'papers.search.v1'                                       # PM 18:2x: topic necklace's papers seat
    assert order[1:3] == ('company.profile.v1', 'holiday.calendar.v1')          # nothing tested yet
    assert order.index('weather.forecast.v1') < order.index('news.search.v1')    # first-batch necklace role first
    assert 'fx.rate.v1' not in order                                              # has a final pearl
    assert len(order) == len(set(order))


def test_rejudge_takes_85_plus_and_top_three_first():
    versions = [version(1, 'fx.rate.v1', 60), version(2, 'fx.rate.v1', 88), version(3, 'book.search.v1', 50),
                version(4, 'fx.rate.v1', 70)]
    out = V.rejudge_queue(versions, terms={}, ranks={(3, 'book.search.v1'): 2})
    assert {x['id'] for x in out[:2]} == {2, 3} and {x['id'] for x in out[2:]} == {1, 4}   # role order from PRIORITY_ROLES


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
    # one confirming day (user 11-18): 1 (90, one day) is a pearl, retested twice a week (not on day 0); 82 before 78
    assert [c['id'] for c in V.retest_queue([], day=0)][:2] == [3, 2] and 1 not in [c['id'] for c in V.retest_queue([], day=0)]
    assert [c['id'] for c in V.retest_queue([], day=0, limit=1, skip={(3, 'fx.rate.v1')})] == [2]


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
    assert (state['retests'], state['new_tests'], state['role_tests']) == (55, 155, 210)   # 20 + 100 in this window
    V.run(queue)                                       # a second start in the same window gets nothing more
    assert state['role_tests'] == 210 and len(calls) == 120


def test_later_windows_have_their_own_done_file_and_launchd_starts_all_three():
    import plistlib
    from pathlib import Path
    from scripts import pearl_daily
    assert [pearl_daily.window_suffix(n) for n in (0, 1, 2, 8)] == ['-w0', '', '-w2', '-w8']
    root = Path(__file__).resolve().parents[1] / 'deploy/launchd'
    for folder in ('ops', 'ops-pinned'):
        plist = plistlib.loads((root / folder / 'biz.agentconcierge.opsauto.pearltests.plist').read_bytes())
        starts = [(x['Hour'], x['Minute']) for x in plist['StartCalendarInterval']]
        assert starts == [(h, 12) for h in V.WINDOW_HOURS]
        assert all(V.window_number(at(h, m)) == n for n, (h, m) in enumerate(starts, 1))


def test_papers_candidates_all_go_first_in_terms_order():
    cands = [('papers.search.v1', i, 't', f'p{i}.example') for i in range(1, 7)] + \
            [('weather.forecast.v1', 10 + i, 't', f'w{i}.example') for i in range(3)]
    terms = {1: 'prohibits', 2: None, 5: 'silent', 6: 'allowed'}
    out = V.new_queue([], cands, limit=9, terms=terms, priority=V.queue_priority([], {}, roles=['weather.forecast.v1'], terms={}, seats=[]))
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


def test_a_tested_first_pick_leads_the_retests_instead(tmp_path):
    f = tmp_path / 'picks.json'
    f.write_text('[{"role": "timezone.time.v1", "id": 84607}]')
    cands = [('timezone.time.v1', 84607, 'current_time', 'plumbkit.dev')]
    assert V.first_picks(cands, {}, set(), path=f, tested={(84607, 'timezone.time.v1')}) == []
    assert V.pick_ids(path=f) == {(84607, 'timezone.time.v1')}


def test_public_necklace_seats_without_a_usable_final_pearl_come_next_after_papers():
    seats = V.public_seat_roles()
    assert seats[:4] == ['web.grounding.v1', 'papers.search.v1', 'encyclopedia.summary.v1', 'news.search.v1']
    assert {'sec.filings.v1', 'cve.record.v1', 'cve.exploited.v1'} <= set(seats)
    versions = [version(1, 'news.search.v1'), version(2, 'cve.record.v1')]
    ranked = {'news.search.v1': {'final_pearl': 1}, 'cve.record.v1': {'final_pearl': 2}}
    order = V.queue_priority(versions, ranked, roles=['news.search.v1', 'cve.record.v1', 'fx.rate.v1'],
                             terms={1: 'silent', 2: 'prohibits'}, seats=['news.search.v1', 'cve.record.v1'])
    assert order[0] == 'papers.search.v1' and order[1] == 'cve.record.v1'   # a prohibited pearl fills no seat
    assert 'news.search.v1' not in order                                     # a usable final pearl fills it


def test_role_task_summary_counts_our_stored_versions_only():
    assert V.role_task_summary(9, 'fx.rate.v1', 'convert') == {}
    V.save_version({'id': 9, 'role': 'fx.rate.v1', 'tool': 'convert', 'outcome': 'failed', 'excerpt': '', 'host': 'a.example.com',
                    'latency_ms': 300, 'arguments': {'from': 'USD', 'to': 'EUR'}, 'started': time.time() - 60, 'reason': 'tool error'})
    out = V.role_task_summary(9, 'fx.rate.v1', 'convert')
    assert out['tasks_run'] == 1 and out['tasks_correct'] == 0 and out['success_days'] == 0
    assert out['last_checked'].endswith('+09:00') and set(out) == {'tasks_run', 'tasks_correct', 'success_days', 'last_checked'}


def evidence(rid, tested, **missing):
    """A passing version with every test evidence v1 key, minus the ones named in MISSING."""
    v = {'resource_id': rid, 'role': 'fx.rate.v1', 'tool': 'convert', 'outcome': 'succeeded', 'tested': tested,
         'quality': {'score': 92.0}, 'data_quality': {'accuracy': {'points': 10}, 'clean': {'points': 5}},
         'endpoint': 'https://a.example.com/mcp', 'tool_fingerprint': 'f1', 'evaluator_version': 'e1',
         'answer_set': 'a1', 'case_id': 'c1', 'response_hash': 'h1'}
    for key in missing:
        v.pop(key)
    return v


def test_evidence_numbers_count_complete_versions_only_and_the_rank_run_reports_the_gap(monkeypatch):
    """Source review C04 (PM 11-17 10:4x): a version missing an evidence key is run, never correct or a success day;
    passing() and the rank keep it; summary.json counts the passing outside versions that miss a key."""
    now = time.time()
    stored = [evidence(9, now - 2 * V.DAY), evidence(9, now - V.DAY, tool_fingerprint=1), evidence(9, now - 60)]
    monkeypatch.setattr(V, 'versions_of', lambda rid, role: list(stored))
    assert all(V.passing(v) for v in stored) and not V.evidence_complete(stored[1])
    out = V.role_task_summary(9, 'fx.rate.v1', 'convert', now=now)
    assert out['tasks_run'] == 3 and out['tasks_correct'] == 2 and out['success_days'] == 2
    # 11-17 production: the 28 passing versions without a tool fingerprint are all our own fallbacks
    own = [evidence(f'avc:sec-filings', now - 60, tool_fingerprint=1) for _ in range(28)]
    assert V.passing_missing_keys(own + stored[::2]) == {'outside': 0, 'own_fallbacks': 28}
    assert V.passing_missing_keys(stored + own) == {'outside': 1, 'own_fallbacks': 28}
    failed = {**evidence(5, now), 'outcome': 'failed', 'case_id': None}
    assert V.passing_missing_keys([failed]) == {'outside': 0, 'own_fallbacks': 0}   # only passing versions count


def test_board_line_warns_when_a_passing_outside_version_misses_an_evidence_key():
    s = V.summary([], {}, 10, now=time.time())
    s['passing_missing_keys'] = {'outside': 0, 'own_fallbacks': 28}
    assert '경고' not in V.funnel_line(s)
    s['passing_missing_keys'] = {'outside': 2, 'own_fallbacks': 28}
    assert '증거 필수 키가 빠진 외부 버전 2건' in V.funnel_line(s)
    s.pop('passing_missing_keys')
    assert '경고' not in V.funnel_line(s)                     # an older summary.json without the field


def test_role_groups_are_written_outside_git_and_published_once_a_night(out, monkeypatch, tmp_path):
    """PM 11-17: the pearl runs write role_groups.json under exports (three times a day); the copy in git, which the
    deployed necklace code reads inside its release, changes only by 'publish-groups' for the night bundle."""
    import inspect
    assert V.groups_file() == out / 'final' / 'role_groups.json'
    source = inspect.getsource(V.publish)
    assert 'groups_file().write_text' in source and 'GROUPS.write_text' not in source
    published = tmp_path / 'git' / 'role_groups.json'
    published.parent.mkdir()
    published.write_text('{"roles": {}}')
    monkeypatch.setattr(V, 'GROUPS', published)
    V.groups_file().parent.mkdir(parents=True)
    V.groups_file().write_text('{"generated": "2026-11-17 20:16", "roles": {"fx.rate.v1": {}}}')
    called = []
    monkeypatch.setattr(V, 'publish', lambda board=True: called.append(board))
    V.main(['publish-groups'])
    assert called == []                                          # no ranking, nothing on the board
    assert published.read_text() == V.groups_file().read_text()


def test_the_final_pearl_is_the_best_verified_member_and_a_first_day_leader_is_provisional(monkeypatch):
    """PM 11-17 16:4x (charter 0): website.ai_readiness lost its final pearl 132732 (confirmed, 92.1, 1 of 2 recent
    tasks) when two first-day candidates at 1/1 ranked above it."""
    now = time.time()

    def v(rid, score, domain):
        return {'resource_id': rid, 'role': 'website.ai_readiness.v1', 'tool': 't', 'outcome': 'succeeded',
                'quality': {'score': score}, 'tested': now - 60, 'domain': 'web', 'registrable_domain': domain,
                'data_quality': {'accuracy': {'points': 25}}}
    confirmed, fresh, second = v(132732, 92.1, 'a.com'), v(37811, 88.0, 'b.com'), v(436744, 85.0, 'c.com')
    days = {132732: 2, 37811: 1, 436744: 1}
    recent = {132732: [confirmed, {**confirmed, 'quality': {'score': 70.0}}], 37811: [fresh], 436744: [second]}
    monkeypatch.setattr(V, 'success_days', lambda rid, role, tool, now, **k: days[rid])
    monkeypatch.setattr(V, 'recent_tasks', lambda x, now=None: recent[x['resource_id']])
    monkeypatch.setattr(V, 'stale_answer', lambda xs: False)
    role = V.rank([confirmed, fresh, second])['website.ai_readiness.v1']
    assert [m['resource_id'] for m in role['members'] if m['rank'] == 1] == [37811]     # the rank order is unchanged
    # one confirming day (user 11-18): the first-day leader at 85+ is confirmed and takes the final place
    assert role['final_pearl'] == 37811 and role['provisional_pearl'] is None
    days.update({37811: 0, 436744: 0})                      # no qualifying day: the best confirmed member below it
    role = V.rank([confirmed, fresh, second])['website.ai_readiness.v1']
    assert role['final_pearl'] == 132732 and role['provisional_pearl'] is None

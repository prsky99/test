"""scripts/night_tests.py and the ops watch step that starts it (운영·SRE, PM 11-15 16:52). Nothing runs pytest here."""
import json
from datetime import datetime

from scripts import night_tests as nt
from scripts import ops_auto

XML = '''<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="4">
<testcase classname="tests.test_storage_inventory" name="test_a"><failure message="x"/></testcase>
<testcase classname="tests.test_explore_retest_fixes.TestFix" name="test_b"><error message="y"/></testcase>
<testcase classname="tests.test_ok" name="test_c"/>
<testcase classname="tests.test_ok" name="test_d"><skipped/></testcase>
</testsuite></testsuites>'''


def test_failures_and_the_test_file_behind_a_class(tmp_path):
    (tmp_path / 'tests').mkdir()
    for name in ('test_storage_inventory', 'test_explore_retest_fixes', 'test_ok'):
        (tmp_path / 'tests' / f'{name}.py').write_text('')
    x = tmp_path / 'r.xml'
    x.write_text(XML)
    total, failing = nt.failures(x)
    assert total == 4 and len(failing) == 2
    assert nt.test_file('tests.test_explore_retest_fixes.TestFix', tmp_path) == 'tests/test_explore_retest_fixes.py'
    assert nt.test_file('tests.test_storage_inventory', tmp_path) == 'tests/test_storage_inventory.py'


def test_owner_is_read_from_the_last_commit_text():
    git = lambda *a: 'abc1234 Explore retest fixes (검색과 RAG, PM 11-11)'   # noqa: E731
    assert nt.owner('tests/test_x.py', git) == ('검색과 RAG', 'abc1234')
    assert nt.owner('tests/test_y.py', lambda *a: 'def5678 Some change')[0] == 'PM 배정'


def test_first_seen_stays_and_old_failures_go_to_pm(monkeypatch):
    state = nt.update_state(['tests/a.py::t1'], '2026-11-12', {})
    state = nt.update_state(['tests/a.py::t1', 'tests/b.py::t2'], '2026-11-16', state)
    assert state['first_seen'] == {'tests/a.py::t1': '2026-11-12', 'tests/b.py::t2': '2026-11-16'}
    handed, closed = [], []
    monkeypatch.setattr(ops_auto, 'TEAM', dict(ops_auto.TEAM))
    record = {'day': '2026-11-16', 'failing': ['tests/a.py::t1', 'tests/b.py::t2'], 'teams_before': ['워크플로우']}
    git = lambda *a: 'abc Something (운영·SRE 11-15)' if a[-1] == 'tests/a.py' else 'def Something (agent team)'  # noqa: E731
    out = nt.report(record, state, git, handoff=lambda k, t: handed.append((k, t)), close=lambda k, n: closed.append(k))
    kinds = [k for k, _ in handed]
    assert 'night_tests|운영·SRE' in kinds and 'night_tests|에이전트 팀' in kinds and 'night_tests_stale' in kinds
    assert 'night_tests|워크플로우' in closed and out['stale'] == ['tests/a.py::t1']


def test_the_watch_starts_it_once_between_0515_and_0540(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_auto, 'NIGHT_TESTS_STATE', tmp_path / 's.json')
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'a.md')
    started = []
    at = lambda h, m: (lambda: datetime(2026, 11, 16, h, m).timestamp())   # noqa: E731
    assert ops_auto.night_tests(clock=at(22, 30), launch=started.append) is None
    assert ops_auto.night_tests(clock=at(22, 40), launch=lambda cmd: 75) == 'refused'    # heavy_slot said no
    assert ops_auto.night_tests(clock=at(22, 50), launch=lambda cmd: started.append(cmd)) == 'started'
    assert ops_auto.night_tests(clock=at(22, 51), launch=started.append) is None      # once a night
    assert len(started) == 1 and 'scripts.heavy_slot' in started[0] and started[0][-1] == 'run'


def test_an_evening_run_may_take_an_hour_but_the_day_stays_30_minutes():
    from scripts import heavy_slot
    assert heavy_slot.night_only('night full pytest', [], 50, datetime(2026, 11, 15, 22, 40)) is None
    assert '30 minutes' in heavy_slot.night_only('night full pytest', [], 50, datetime(2026, 11, 15, 15, 0))


def test_the_watch_tells_a_refusal_from_a_failure(tmp_path, monkeypatch):
    """11-16 PM source review: only 75 was a refusal, and a crash in the first seconds was recorded as started."""
    monkeypatch.setattr(ops_auto, 'NIGHT_TESTS_STATE', tmp_path / 's.json')
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'a.md')
    monkeypatch.setattr(ops_auto, 'TEAM', dict(ops_auto.TEAM))
    lines = []
    monkeypatch.setattr(ops_auto, 'board_handoff', lambda kind, text: lines.append((kind, text)))
    at = lambda h, m: (lambda: datetime(2026, 11, 16, h, m).timestamp())   # noqa: E731
    assert ops_auto.night_tests(clock=at(22, 40), launch=lambda cmd: 77) == 'refused' and not lines
    assert ops_auto.night_tests(clock=at(22, 41), launch=lambda cmd: 1) == 'failed'
    assert lines and lines[0][0] == 'night_tests_run' and '종료 1' in lines[0][1]
    assert not (tmp_path / 's.json').exists()                                  # the next round tries again
    assert ops_auto.night_tests(clock=at(22, 42), launch=lambda cmd: None) == 'started'


def test_a_run_without_a_result_goes_to_the_board():
    lines = []
    nt.no_result({'day': '2026-11-16', 'error': 'timeout', 'seconds': 3000}, handoff=lambda k, t: lines.append((k, t)))
    assert lines == [('night_tests_run', f'밤 전체 시험 2026-11-16: {nt.TIMEOUT_S // 60}분 시간 초과, 3000초 — 그날 밤 전체 시험 결과가 없습니다')]


def test_it_runs_the_working_tree_also_from_the_pinned_code_folder(tmp_path):
    """PM 11-16: from gateway-data/ops-code/<commit> (no tests/, no .git) the run still uses the working tree."""
    repo = tmp_path / 'repo'
    (repo / 'tests').mkdir(parents=True)
    (repo / '.git').mkdir()
    (repo / 'gateway-data').mkdir()
    pinned = repo / 'gateway-data/ops-code/abc'
    pinned.mkdir(parents=True)
    (pinned / 'gateway-data').symlink_to(repo / 'gateway-data')
    assert nt.repo_root(repo) == repo
    assert nt.repo_root(pinned) == repo.resolve()


def test_the_limit_is_90_minutes_and_the_slowest_table_is_read():
    """PM 11-17 night: 50 min timed out three nights running; --durations=30 shows what takes the time."""
    assert nt.TIMEOUT_S == 90 * 60 and nt.INTERRUPT_GRACE_S == 120
    lines = ['.....', '============================= slowest 30 durations =============================',
             '12.31s call     tests/test_a.py::test_x', '3.02s setup    tests/test_b.py::test_y', '',
             '(28 durations < 0.005s hidden.  Use -vv to show these durations.)', '=== 5 passed in 20s ===']
    assert nt.slowest_tests(lines) == ['12.31s call     tests/test_a.py::test_x', '3.02s setup    tests/test_b.py::test_y']
    assert nt.slowest_tests(['=== 1 passed ===']) == []

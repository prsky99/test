import json

import pytest

from scripts import stability_gate as gate

TODAY = '2026-11-20'
REAL_REFRESH = gate.refresh_availability


@pytest.fixture(autouse=True)
def no_production_db(monkeypatch):
    """judge() reads the minute availability checks from the production DB; tests never do."""
    monkeypatch.setattr(gate, 'refresh_availability', lambda ops, run=None: {})


def write(path, rows):
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')


def slo_day(day, runs=24, breach_at=None):
    return [{'at': f'{day} {h:02d}:02', 'breaches': ({'explore': {}} if h == breach_at else {})} for h in range(runs)]


def setup(tmp_path, slo_days=7, full_failed=0, passed=28, unexplained=0):
    days = [f'2026-11-{d:02d}' for d in range(20 - slo_days, 20)]
    write(tmp_path / 'user-slo.jsonl', [r for d in days for r in slo_day(d)])
    write(tmp_path / 'public-full-check.jsonl',
          [{'at': f'2026-11-{d} 10:00', 'failed': full_failed if d == 19 else 0} for d in (17, 18, 19)])
    write(tmp_path / 'real-task-score.jsonl', [{'at': '2026-11-19T19:30:00+00:00', 'passed': passed, 'tasks': 30}])
    (tmp_path / 'error-ledger').mkdir()
    (tmp_path / 'error-ledger' / '2026-11-19.json').write_text(json.dumps({'unexplained': unexplained}))


def test_gate_opens_only_when_all_four_hold(tmp_path):
    setup(tmp_path)
    r = gate.judge(TODAY, tmp_path)
    assert r['open'] and r['user_slo']['streak'] == 7 and r['full_check']['streak'] == 3
    assert r['real_tasks']['day'] == '2026-11-20'        # 19:30 UTC is the next KST day


def test_each_measure_closes_the_gate(tmp_path):
    for kwargs in ({'slo_days': 6}, {'full_failed': 1}, {'passed': 26}, {'unexplained': 2}):
        folder = tmp_path / str(len(list(tmp_path.iterdir())))
        folder.mkdir()
        setup(folder, **kwargs)
        assert not gate.judge(TODAY, folder)['open'], kwargs


def test_a_breach_a_thin_day_or_a_gap_breaks_the_streak(tmp_path):
    days = {'2026-11-19': slo_day('2026-11-19'), '2026-11-18': slo_day('2026-11-18', breach_at=3),
            '2026-11-17': slo_day('2026-11-17')}
    assert gate.streak(gate.slo_days([r for rows in days.values() for r in rows]), TODAY) == 1
    assert gate.streak(gate.slo_days(slo_day('2026-11-19', runs=5)), TODAY) == 0      # too few runs
    assert gate.streak(gate.slo_days(slo_day('2026-11-18')), TODAY) == 0              # yesterday missing
    assert gate.streak(gate.slo_days(slo_day(TODAY, breach_at=1) + slo_day('2026-11-19')), TODAY) == 1


def test_missing_records_close_and_the_board_line_is_replaced(tmp_path):
    r = gate.judge(TODAY, tmp_path)
    assert not r['open'] and r['error_ledger']['unexplained'] is None
    board = tmp_path / 'board.md'
    board.write_text('# 운영 현황판\n\n> 공지\n\n## 무거운 작업\n')
    gate.update_board(gate.board_line(r), board)
    gate.update_board(gate.board_line(r), board)
    text = board.read_text()
    assert text.count(gate.MARK) == 1 and text.index(gate.MARK) < text.index('> 공지')
    assert '닫힘' in text and '장부 없음' in text


def test_the_line_says_what_stays_frozen_and_reports_the_final_and_interim_targets_apart(tmp_path):
    """11-14: the final gate is a quality measure and no longer holds the USDC switch (payment stability standard);
    interim reached is the fast-growth signal."""
    r = gate.judge(TODAY, tmp_path)
    line = gate.board_line(r)
    assert 'USDC 결제 스위치·광고주 유치' not in line and 'USDC 결제 스위치는 결제 안정 기준으로 판단' in line
    assert '새 기능 동결' not in line
    assert '최종 목표 관문(품질 지표) 닫힘' in line and '차선 목표 미달' in line
    r['interim'] = {**(r.get('interim') or {}), 'ok': True}
    assert '차선 목표 달성(빠른 성장 신호)' in gate.board_line(r)


def operational(days, checks=1440, longest=1):
    return {d: {'checks': checks, 'failed': 3, 'longest_failed_run': longest} for d in days}


def payment_setup(tmp_path, tests=None):
    setup(tmp_path)
    for d in (16, 17, 18, 19):
        (tmp_path / 'error-ledger' / f'2026-11-{d}.json').write_text(json.dumps({'unexplained': 0}))
    if tests is not None:
        (tmp_path / 'payment-flow-tests').mkdir()
        (tmp_path / 'payment-flow-tests' / '2026-11-19.json').write_text(json.dumps(tests))


def test_payment_standard_needs_all_three_on_three_days(tmp_path):
    """11-14 user decision: the USDC switch follows the payment stability standard, not the 7-day final gate."""
    passing = {'at': '2026-11-19 10:00', 'network': 'base-sepolia', 'passed': 12, 'total': 12, 'includes_failure_cases': True}
    payment_setup(tmp_path, passing)
    days = [f'2026-11-{d}' for d in (17, 18, 19)]
    r = gate.judge(TODAY, tmp_path, availability=operational(days))
    assert r['payment']['days'] == 3 and r['payment']['tests']['ok'] and r['payment']['met']
    line = gate.board_line(r)
    assert '결제 안정 기준 3/3일(충족' in line and 'USDC 결제 스위치·광고주 유치' not in line
    # a 5-minute outage on one day, a thin day, or an unexplained error breaks the days
    assert gate.judge(TODAY, tmp_path, availability={**operational(days), '2026-11-18': operational(['x'], longest=5)['x']})['payment']['days'] == 1
    assert gate.judge(TODAY, tmp_path, availability=operational(days, checks=900))['payment']['days'] == 0
    (tmp_path / 'error-ledger' / '2026-11-19.json').write_text(json.dumps({'unexplained': 1}))
    assert gate.judge(TODAY, tmp_path, availability=operational(days))['payment']['days'] == 0


def test_payment_tests_must_all_pass_and_include_failure_cases(tmp_path):
    days = [f'2026-11-{d}' for d in (17, 18, 19)]
    for tests, ok in (({'passed': 11, 'total': 12, 'includes_failure_cases': True}, False),
                      ({'passed': 12, 'total': 12, 'includes_failure_cases': False}, False),
                      ({'passed': 0, 'total': 0, 'includes_failure_cases': True}, False), (None, False)):
        folder = tmp_path / str(len(list(tmp_path.iterdir())))
        folder.mkdir()
        payment_setup(folder, tests)
        r = gate.judge(TODAY, folder, availability=operational(days))
        assert r['payment']['tests']['ok'] is ok and not r['payment']['met'] and r['payment']['days'] == 3


def test_refresh_merges_the_daily_rows_and_keeps_old_days(tmp_path):
    (tmp_path / gate.AVAILABILITY).write_text(json.dumps({'2026-11-01': {'checks': 1, 'failed': 0, 'longest_failed_run': 0}}))
    days = REAL_REFRESH(tmp_path, run=lambda: 'SET\n2026-11-18|1438|40|3\n2026-11-19|1436|2|1\n')
    assert days['2026-11-18'] == {'checks': 1438, 'failed': 40, 'longest_failed_run': 3} and '2026-11-01' in days
    assert json.loads((tmp_path / gate.AVAILABILITY).read_text()) == days
    assert REAL_REFRESH(tmp_path, run=lambda: (_ for _ in ()).throw(OSError('no db'))) == days


def test_met_is_recorded_once(tmp_path):
    r = {'judged_at': '2026-11-20 09:00', 'payment': {'met': True, 'days': 3}}
    assert gate.record_met(r, tmp_path) and not gate.record_met(r, tmp_path)
    assert not gate.record_met({'judged_at': 'x', 'payment': {'met': False}}, tmp_path / 'x')

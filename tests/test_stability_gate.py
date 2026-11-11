import json

from scripts import stability_gate as gate

TODAY = '2026-11-20'


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

"""The interim user target is judged on the same samples as the final one (11-14 user decision via PM)."""
import json

from scripts import stability_gate as gate
from scripts.slo_targets import FINAL, INTERIM, attainment


def run(at, explore=1.5, recommend=1.8, page=0.9, connect_ok=True, answered=True):
    return {'at': at,
            'explore': {'samples': [{'s': explore, 'status': 200, 'total': 5}, {'s': 1.0, 'status': 200, 'total': 3}]},
            'recommend': {'samples': [{'s': recommend, 'answered': answered}]},
            'pages': {'samples': [{'s': page, 'status': 200}]},
            'connect': {'ok': connect_ok}}


def test_targets_are_the_user_decisions():
    assert (FINAL['explore_s'], FINAL['recommend_s'], FINAL['page_s']) == (2.0, 2.0, 1.0)
    assert (INTERIM['explore_s'], INTERIM['recommend_s'], INTERIM['page_s']) == (3.0, 5.0, 3.0)


def test_one_run_against_both_targets():
    r = run('2026-11-14 02:00', explore=2.6, recommend=4.0, page=2.5)
    final, interim = attainment(r, FINAL), attainment(r, INTERIM)
    assert not final['ok'] and interim['ok']
    assert final['parts'] == {'explore': {'passed': 1, 'n': 2}, 'recommend': {'passed': 0, 'n': 1}, 'pages': {'passed': 0, 'n': 1}}
    assert final['sample_rate'] == 0.25 and interim['sample_rate'] == 1.0
    assert not attainment(run('x', connect_ok=False), INTERIM)['ok']           # connect keeps its own verdict
    assert not attainment(run('x', answered=False), INTERIM)['ok']             # an unanswered request never passes
    assert not attainment({'explore': {'samples': [{'s': 0.5, 'status': 200, 'total': 0}]}}, INTERIM)['ok']  # 0 results


def test_the_gate_reports_the_interim_streak_and_rates_without_opening_on_them(tmp_path):
    rows = [run(f'2026-11-{d:02d} {h:02d}:00', explore=2.5) for d in range(7, 14) for h in range(12)]
    for r in rows:   # as user_slo records them: a run over the final target has breaches
        r['breaches'] = {} if attainment(r, FINAL)['ok'] else {'explore': {'bad_count': 1}}
    (tmp_path / 'user-slo.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
    result = gate.judge(today='2026-11-14', ops=tmp_path)   # streaks end yesterday
    assert result['user_slo_interim']['streak'] == 7 and result['user_slo_interim']['ok']
    assert result['user_slo']['streak'] == 0 and not result['open']
    assert result['slo_rates']['final']['run_rate'] == 0.0 and result['slo_rates']['interim']['run_rate'] == 1.0
    line = gate.board_line(result)
    assert '차선 목표 user_slo 7/7일' in line and '7일 달성률 최종 0%·차선 100%' in line

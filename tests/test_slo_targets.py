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
    assert result['user_slo_interim']['streak'] == 7 and result['user_slo_interim']['ok'] and result['user_slo_interim']['need'] == 3
    assert result['user_slo']['streak'] == 0 and not result['open']
    assert result['slo_rates']['final']['run_rate'] == 0.0 and result['slo_rates']['interim']['run_rate'] == 1.0
    line = gate.board_line(result)
    assert '차선 속도(하루 회차 90% 이상) 7/3일' in line and '7일 달성률 최종 0%·차선 100%' in line


def test_the_interim_target_needs_speed_and_quality_and_records_the_supporting_measures(tmp_path):
    """11-14 02:3x (user via PM): interim = the three speeds and real_task_score 27/30; connection share (90%) and the
    Chat comparison (99/110) are recorded, not judged."""
    rows = [run(f'2026-11-{d:02d} {h:02d}:00', explore=2.5) for d in range(7, 14) for h in range(12)]
    for r in rows:
        r['breaches'] = {'explore': {'bad_count': 1}}
        r['connect'] = {'ok': True, 'samples': [{'tools': 4}, {'tools': 0}]}         # 50% of connections
    (tmp_path / 'user-slo.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
    (tmp_path / 'chat-gate').mkdir()
    (tmp_path / 'chat-gate' / 'a.json').write_text(json.dumps(
        {'active': 'rel-1', 'active_verdicts': {f'c{i}': i < 100 for i in range(110)}}))

    def judged(passed, previous=26):
        (tmp_path / 'real-task-score.jsonl').write_text(
            json.dumps({'at': '2026-11-12T19:07:00+00:00', 'tasks': 30, 'passed': previous}) + '\n'
            + json.dumps({'at': '2026-11-13T07:40:16+00:00', 'tasks': 30, 'passed': passed}) + '\n')
        return gate.judge(today='2026-11-14', ops=tmp_path)

    low, high, lucky = judged(24), judged(27), judged(27, previous=25)
    assert not lucky['interim']['quality'] and lucky['interim']['previous_real_tasks'] == 25   # one lucky pass is not enough
    assert low['interim']['speed'] and not low['interim']['quality'] and not low['interim']['ok']
    assert high['interim']['ok'] and not high['open']                             # never opens the gate
    assert high['interim']['connect']['rate'] == 0.5 and not high['interim']['connect_ok']   # recorded, not judged
    assert high['interim']['chat'] == {'passed': 100, 'total': 110, 'release': 'rel-1', 'file': 'a.json'}
    assert high['interim']['chat_ok']
    assert '차선 달성 통과(속도 통과, 품질 실제 과제 27/30 목표 27·직전 26 목표 26; 보조 연결 표본 50%·Chat 100/110)' in gate.board_line(high)


def test_an_interim_day_passes_with_ninety_percent_of_its_runs_and_three_days_make_the_speed(tmp_path):
    """PM 02:5x: one tail sample no longer fails a whole day; a run with any slow sample is still a failed run."""
    rows = []
    for d in range(10, 14):
        for h in range(20):
            slow = (d == 10 and h < 3) or (d >= 11 and h < 2)          # 11-10: 17/20 = 85%; later days 18/20 = 90%
            rows.append({**run(f'2026-11-{d:02d} {h:02d}:00', explore=3.5 if slow else 1.0), 'breaches': {'x': 1} if slow else {}})
    (tmp_path / 'user-slo.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
    days = gate.interim_days(rows)
    assert not days['2026-11-10']['ok'] and days['2026-11-11']['ok'] and days['2026-11-11']['run_rate'] == 0.9
    result = gate.judge(today='2026-11-14', ops=tmp_path)
    assert result['user_slo_interim']['streak'] == 3 and result['interim']['speed']
    assert result['user_slo']['streak'] == 0 and not result['open']                # the final gate is unchanged

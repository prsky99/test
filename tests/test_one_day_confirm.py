"""User 11-18 (via PM 19:2x, logs/ops/decisions.jsonl): one day of 85+ confirms a pearl, no second day. The 85 mark,
the role task verdicts and the scores stay as they were: the repeat evidence keeps its two-day scale (REPEAT_DAYS)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_v2 as V  # noqa: E402
from agent_market import pearls_public as P  # noqa: E402


def test_one_day_confirms_and_the_score_scale_does_not_move():
    assert V.CONFIRM_DAYS == 1 and V.REPEAT_DAYS == 2 and V.PASS_MARK == 85


def test_the_repeat_points_of_a_first_day_stay_half():
    r = {'outcome': 'succeeded', 'role': 'fx.rate.v1', 'tool': 't', 'id': 1, 'arguments': {'q': 'x'}, 'latency_ms': 500,
         'data_quality': {}}
    one, two = V.quality(r, 1), V.quality(r, 2)
    assert two['score'] - one['score'] == V.DQ.EVIDENCE_WEIGHTS['repeat'] / 2


def _m(rid, score, days, outcome='succeeded'):
    return {'resource_id': rid, 'id': rid, 'tool': 't', 'score': score, 'best_recent_score': score, 'success_days': days,
            'tested': '2026-11-18 20:20', 'recent_tasks': 1, 'recent_pass_rate': 1.0, 'outcome': outcome}


def test_a_first_day_member_at_85_is_listed_as_verified():
    summary = {'generated': '2026-11-18T21:20:00+0900', 'rules': {'pass_mark': 85, 'confirm_days': V.CONFIRM_DAYS,
                                                                   'evaluator_version': 'dq-x'}}
    groups = {'roles': {'fx.rate.v1': {'domain': 'finance', 'final_pearl': 1, 'provisional_pearl': None,
                                       'members': [_m(1, 90.0, 1), _m(2, 86.0, 1), _m(3, 84.0, 1), _m(4, 95.0, 1, 'failed')]}}}
    levels = {p['resource_id']: p['level'] for p in P.build(summary, groups, {})['pearls']}
    assert levels == {1: 'final', 2: 'verified'}


def test_an_old_file_without_the_rule_reads_one_day():
    summary = {'generated': '2026-11-18T21:20:00+0900', 'rules': {'pass_mark': 85, 'evaluator_version': 'dq-x'}}
    groups = {'roles': {'fx.rate.v1': {'domain': 'finance', 'final_pearl': None, 'provisional_pearl': None,
                                       'members': [_m(2, 86.0, 1)]}}}
    assert [p['level'] for p in P.build(summary, groups, {})['pearls']] == ['verified']


def test_a_first_day_member_below_85_is_retested_first_not_twice_a_week(monkeypatch):
    # PM 11-18 19:4x: the 80-84.9 one-day members take the retest room the second days left
    def member(rid, score, days, rank=1):
        return {'resource_id': rid, 'tool': 't', 'rank': rank, 'success_days': days, 'score': score, 'best_recent_score': score}
    roles = {'x.v1': {'members': [member(1, 83.0, 1), member(2, 90.0, 1, rank=2), member(3, 71.0, 1, rank=3)]}}
    monkeypatch.setattr(V, 'rank', lambda versions: roles)
    day = next(d for d in range(7) if (d + 2) % 7 not in V.CONFIRMED_RETEST_DAYS)
    out = [c['id'] for c in V.retest_queue([], day=day, now=1_800_000_000)]
    assert out[:2] == [1, 3] and 2 not in out

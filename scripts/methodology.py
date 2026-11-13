"""AgentValCon Verification Method v1 as data (PM 11-14 super-gap strategy, supplement 1).

Every number comes from the code that applies it (scripts/report_v2.py, scripts/data_quality.py,
agent_market/collector/evaluation.py, agent_market/provider_budget.py); nothing is typed by hand, so the public page
cannot drift from the scoring. The withheld answer sets are not published: each role shows one example input and the
kinds of checks, never the expected values (a published answer could be served to game the score).

    .venv/bin/python -m scripts.methodology                 # writes docs/methodology/methodology.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

OUT = ROOT / 'docs/methodology/methodology.json'
VERSION = 'v1'


def _gate():
    """Gate numbers from agent_market/necklaces/gate_rules (운영·SRE 897baf3a); held-out sets are not in it."""
    from agent_market.necklaces import gate_rules
    return {**gate_rules.summary(), 'answer_sets': 'withheld'}


def _freshness(rule):
    if rule is None:
        return 'fixed facts (not time-bound)'
    if rule[0] == 'age':
        return f'data time within {rule[1]} days'
    if rule[0] == 'future':
        return 'dates today or later'
    return f'clock time within {rule[1]} minutes of now'


def _check_kinds(case):
    expect = case.get('expect') or {}
    kinds = []
    if expect.get('must_include_all') or expect.get('must_include_any'):
        kinds.append('expected facts appear in the answer')
    if expect.get('numeric'):
        kinds.append('numeric fields match')
    if 'kev' in expect:
        kinds.append('KEV listing stated correctly')
    if expect.get('dynamic'):
        kinds.append('same-time public reference: ' + ', '.join(k for k in expect['dynamic'] if k != 'tolerance'))
    if expect.get('published_within_days'):
        kinds.append('published recently')
    return kinds


def build():
    import data_quality as DQ
    import report_v2 as V
    import role_catalog as R
    from agent_market.collector import evaluation
    from agent_market import provider_budget
    roles = []
    for role in sorted(R.ROLES):
        case = V.case_for(role, day=0)
        live = R.live_spec(role)
        roles.append({
            'role': role, 'field': V.domain_of(role),
            'example_input': (case or {}).get('input') or R.catalog_input(role) or None,
            'answer_source': ('answer set (withheld)' if case else
                              'none (public reference suspended until its terms are confirmed)' if live and live.get('terms_ok') is False
                              else 'same-time public reference' if live else 'none'),
            'checks': _check_kinds(case) if case else (['same-time public reference within %d%%' % round(live['tolerance'] * 100)] if live else []),
            'freshness': _freshness(DQ.FRESHNESS.get(role)),
        })
    return {
        'name': 'AgentValCon Verification Method',
        'version': VERSION,
        'candidates': {'grade_minimum': 'A', 'grade_thresholds': {g: t for t, g in evaluation.GRADES},
                       'also_required': ['active', 'healthy in the last 7 days', 'not quarantined or under security review']},
        'role_test': {'calls_per_test': 1, 'read_only_tools_only': True, 'no_credentials_or_payment': True,
                      'tests_per_day': V.ROLE_DAILY_LIMIT, 'new_candidates_per_day': V.NEW_A_DAY, 'retests_per_day': V.RETEST_A_DAY,
                      'per_registrable_domain_per_day': provider_budget.SHARE['role_tests'],
                      'stop_domain_for_the_day_on': 429, 'answer_judged_up_to_bytes': 20000, 'excerpt_kept_chars': 1000,
                      'answer_hash': 'sha256'},
        'score': {'total': sum(DQ.WEIGHTS.values()) + sum(DQ.EVIDENCE_WEIGHTS.values()) + DQ.WRITING_WEIGHT,
                  'data_quality': DQ.WEIGHTS, 'evidence': DQ.EVIDENCE_WEIGHTS, 'report_text': DQ.WRITING_WEIGHT,
                  'latency_points': [{'up_to_ms': ms, 'points': p} for ms, p in DQ.LATENCY_STEPS],
                  'accuracy_rule': 'points only when the answer matches an answer set or a public reference at the same time; '
                                   'no answer source means 0',
                  'clean_answer_failures': sorted(DQ.UNCLEAN),
                  'completeness_rule': 'null, empty, N/A and unknown values lower the score by their share'},
        'verified_pearl': {'min_score': V.PASS_MARK, 'successes_on_different_days': V.CONFIRM_DAYS},
        'final_pearl': {'rule': 'the top verified pearl of a role', 'one_place_per_registrable_domain_in_a_role': True,
                        'reranked': 'daily'},
        'necklace_gate': _gate(),
        'roles': roles,
        'limits': ['One call per test with one input; a role is judged on a small number of tasks.',
                   'Answer sets are withheld; examples show inputs only.',
                   'Live checks depend on the public reference being available at test time; when it is not, accuracy is not awarded.'],
    }


def main():
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + '\n', encoding='utf-8')
    print(f"{OUT.relative_to(ROOT)}: {len(data['roles'])} roles, score total {data['score']['total']}")


if __name__ == '__main__':
    main()

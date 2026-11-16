import json

from scripts import value_drivers as vd


def test_sql_rows_parse_into_payment_and_cohorts():
    text = "cohort|2026-11-02|213|0\ncohort|2026-11-09|626|3\npayment||0|0\nnoise\n"
    got = vd.parse_sql(text)
    assert got['first_usdc_payment'] == {'value': 0, 'first_at': None}
    assert got['returning_cohorts'][-1] == {'week': '2026-11-09', 'visitors': 626, 'returned_other_day': 3}
    paid = vd.parse_sql("payment|1794830400000|2|0\n")['first_usdc_payment']
    assert paid['value'] == 2 and paid['first_at'].startswith('2026-11-')


def test_interim_speed_counts_only_runs_that_met_every_target(tmp_path):
    path = tmp_path / 'slo.jsonl'
    rows = [{'at': str(i), 'attainment': {'interim': {'ok': i % 2 == 0}}} for i in range(30)]
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\nnot json\n')
    got = vd.interim_speed(path)
    assert got['runs'] == 24 and got['value'] == 12 and got['met'] is True


def test_usable_pearls_counts_external_pearls_with_allowed_or_silent_terms(tmp_path, monkeypatch):
    from agent_market.necklaces import model
    verdict = {1: 'allowed', 2: 'silent', 3: 'prohibits', 4: 'unknown'}
    monkeypatch.setattr(model, 'terms_status', lambda m: verdict[m['resource_id']])
    members = [{'pearl': True, 'kind': 'external', 'resource_id': rid, 'standing': 'verified_pearl'} for rid in verdict]
    members += [{'pearl': True, 'kind': 'external', 'resource_id': 1, 'standing': 'verified_pearl'},     # same member
                {'pearl': True, 'kind': 'agentcon', 'resource_id': 2},                                   # ours
                {'pearl': False, 'kind': 'external', 'resource_id': 2}]                                 # not a pearl
    path = tmp_path / 'members.json'
    path.write_text(json.dumps({'members': members}))
    assert vd.usable_pearls(path) == {'value': 2, 'by_standing': {'verified_pearl': 2}}


def test_summary_is_one_board_line():
    line = {'day': '2026-11-16', 'public_necklaces': {'value': 0}, 'external_successes': {'value': 0},
            'usable_pearls': {'value': 8}, 'interim_speed': {'value': 5, 'runs': 24, 'aim': 12},
            'real_task': {'value': 24, 'tasks': 30, 'aim': 27},
            'first_usdc_payment': {'value': 0, 'first_at': None},
            'returning_cohorts': [{'week': '2026-11-09', 'visitors': 626, 'returned_other_day': 0},
                                  {'week': '2026-11-16', 'visitors': 156, 'returned_other_day': 0}]}
    text = vd.summary(line)
    assert '\n' not in text and '첫 USDC 없음' in text and '재방문 0/626(주 2026-11-09)' in text
    assert '차선 속도 5/24(목표 12)' in text

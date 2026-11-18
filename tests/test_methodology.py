"""PM 11-14: methodology v1 is generated from the scoring code and never publishes expected answers."""
import json

from scripts import data_quality as DQ, methodology as M, report_v2 as V


def test_numbers_come_from_the_code():
    data = M.build()
    assert data['score']['data_quality'] == DQ.WEIGHTS and data['score']['evidence'] == DQ.EVIDENCE_WEIGHTS
    assert data['score']['total'] == 100 and data['verified_pearl']['min_score'] == V.PASS_MARK
    assert data['verified_pearl']['successes_on_different_days'] == V.CONFIRM_DAYS
    assert data['score']['evaluator_version'] == V.EVALUATOR_VERSION and 'KST' in data['verified_pearl']['days_count_when']
    rt = data['role_test']       # PM 21:02: the report_v2 limits are per window, a day is that times the windows
    assert rt['tests_per_window'] == V.ROLE_DAILY_LIMIT and rt['windows_per_day'] == V.WINDOWS_A_DAY
    assert rt['tests_per_day'] == V.ROLE_DAILY_LIMIT * V.WINDOWS_A_DAY
    assert (rt['new_candidates_per_day'], rt['retests_per_day']) == (V.NEW_A_DAY * V.WINDOWS_A_DAY, V.RETEST_A_DAY * V.WINDOWS_A_DAY)
    assert ('on a KST day' in data['verified_pearl']['days_count_when']) == (V.CONFIRM_DAYS == 1)


def test_no_expected_answers_are_published():
    text = json.dumps(M.build())
    for secret in ('Incheon', 'Austen', 'CVE-2021-23337', 'HWUPKR0MPOU8FGXBT394', '2026-11-26', 'Tokyo', '"expect"', 'must_include'):
        assert secret not in text, secret


def test_changelog_names_the_current_version():
    """성장·유통 618f48e6: the page reads dateModified from the newest changelog entry; bump both together."""
    from pathlib import Path
    log = json.loads((Path(M.ROOT) / 'docs/methodology/changelog.json').read_text())
    assert log[0]['version'] == M.VERSION and log[0]['date'] and log[0]['changes']
    assert not any('pending' in c for c in log[0]['changes']) or M.build()['necklace_gate'].get('status')


def test_the_v1_5_changelog_numbers_are_the_code_limits():
    """PM 21:02: the changelog is written by hand, so its numbers are checked against report_v2's limits."""
    from pathlib import Path
    entry = next(e for e in json.loads((Path(M.ROOT) / 'docs/methodology/changelog.json').read_text())
                 if e['version'] == 'v1.5')
    text = ' '.join(entry['changes'])
    w = V.WINDOWS_A_DAY
    for number in (f'{w} windows a day', f'at most {V.NEW_A_DAY} new candidates and {V.RETEST_A_DAY} retests',
                   f'({V.ROLE_DAILY_LIMIT} tests; {V.FALLBACK_LIMIT} when', f'at most {V.NEW_A_DAY * w} new candidates',
                   f'{V.RETEST_A_DAY * w} retests', 'not counts of tests run'):
        assert number in text, number
    assert ('one KST day' in text) == (V.CONFIRM_DAYS == 1)

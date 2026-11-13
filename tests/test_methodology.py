"""PM 11-14: methodology v1 is generated from the scoring code and never publishes expected answers."""
import json

from scripts import data_quality as DQ, methodology as M, report_v2 as V


def test_numbers_come_from_the_code():
    data = M.build()
    assert data['score']['data_quality'] == DQ.WEIGHTS and data['score']['evidence'] == DQ.EVIDENCE_WEIGHTS
    assert data['score']['total'] == 100 and data['verified_pearl'] == {'min_score': V.PASS_MARK, 'successes_on_different_days': V.CONFIRM_DAYS}
    assert data['role_test']['tests_per_day'] == V.ROLE_DAILY_LIMIT


def test_no_expected_answers_are_published():
    text = json.dumps(M.build())
    for secret in ('Incheon', 'Austen', 'CVE-2021-23337', 'HWUPKR0MPOU8FGXBT394', '2026-11-26', 'Tokyo', '"expect"', 'must_include'):
        assert secret not in text, secret

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


def test_changelog_names_the_current_version():
    """성장·유통 618f48e6: the page reads dateModified from the newest changelog entry; bump both together."""
    from pathlib import Path
    log = json.loads((Path(M.ROOT) / 'docs/methodology/changelog.json').read_text())
    assert log[0]['version'] == M.VERSION and log[0]['date'] and log[0]['changes']
    assert not any('pending' in c for c in log[0]['changes']) or M.build()['necklace_gate'].get('status')

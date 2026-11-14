"""Payment flow report in the operations format, and the per-booking record check (PM 11-14)."""
from scripts.ad_coin_paid_record_check import problems
from scripts.ad_coin_payment_flow_report import REQUIRED, summarize

FLOW = [{'case': name, 'passed': True, 'got': 'ok'} for name in
        ('exact payment confirms the booking', 'underpaid payment goes to review', 'overpaid payment goes to review',
         'another token is refused', 'payment after the quote expired is kept', 'one transaction pays one booking',
         'a payer on the sanctions list is held')]
CHAIN = {'chain_ok': True, 'tx_hash': '0x' + 'a' * 64, 'cases': [{'case': 'exact', 'passed': True, 'got': 'confirmed'}]}


def test_all_cases_present_and_passed():
    result = summarize(FLOW, CHAIN, now=0)
    assert result['network'] == 'base-sepolia' and result['passed'] == result['total'] == 8
    assert result['includes_failure_cases'] and result['failed'] == []


def test_a_missing_case_or_a_failure_is_reported():
    result = summarize([c for c in FLOW if 'sanctions' not in c['case']] + [{'case': 'x', 'passed': False, 'got': 'boom'}],
                       {**CHAIN, 'chain_ok': False}, now=0)
    names = [f['name'] for f in result['failed']]
    assert not result['includes_failure_cases'] and 'missing failure case: sanctioned' in names
    assert 'flow: x' in names and 'base-sepolia: chain id' in names and len(REQUIRED) == 6


def test_record_check_names_what_is_missing():
    base = {'tx_hash': '0x1', 'payer': '0x2', 'krw_rate': '1380', 'confirmed_ms': 1, 'note': None, 'refund_tx_hash': None}
    assert problems({**base, 'state': 'confirmed'}) == []
    assert problems({**base, 'state': 'confirmed', 'krw_rate': None}) == ['krw_rate']
    assert problems({**base, 'state': 'served', 'note': 'sanctions_match'}) == ['confirmed_despite_sanctions']
    assert problems({**base, 'state': 'refunded'}) == ['refund_tx_hash']
    assert problems({**base, 'state': 'quoted', 'tx_hash': None, 'payer': None}) == []

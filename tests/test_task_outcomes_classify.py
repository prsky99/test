"""Recommendation order reads task outcomes classified from the answer itself (concierge.task_outcomes)."""
import json

from agent_market.concierge.task_outcomes import classify


def _answer(payload, is_error=False):
    return {'content': [{'type': 'text', 'text': json.dumps(payload)}], 'isError': is_error}


def test_an_answer_that_says_it_failed_is_a_failure_without_is_error():
    """11-15 real task a01: convertfilefast answered {"status": "error", ...} with isError false."""
    assert classify(_answer({'status': 'error', 'detail': "Conversion '03762-to-txt' is not supported.",
                             'supported_targets_for_source': None})) == 'failed'
    assert classify(_answer({'state': 'failed', 'reason': 'upstream timeout'})) == 'failed'


def test_an_ordinary_answer_with_a_status_field_still_succeeds():
    ok = {'status': 'ok', 'text': 'Attention Is All You Need. ' * 20, 'pages': 15}
    assert classify(_answer(ok)) == 'succeeded'


def _message(text):
    return {'kind': 'message', 'role': 'agent', 'parts': [{'kind': 'text', 'text': text}]}


def test_an_answer_that_only_sells_the_work_needs_a_key():
    """11-16 real tasks p13 and a13: the scorer counted these answers as paid; they had counted as successes."""
    from agent_market.concierge.task_outcomes import PAYWALL
    bounty = ('ArgonautWorks provides three machine-buyable tools: (1) check GitHub bounty viability, (2) calculate '
              'cross-time-zone meeting overlap at https://argonaut-schedule-fit.example/api/v1/overlap. Read '
              'https://argonaut-bounty-signal.example/.well-known/x402 for exact inputs.')
    arn = 'Found 5 relevant ARN tools. Discovery did not execute or charge them.\n{"discoveryOnly": true, "matches": []}'
    assert classify(_message(bounty)) == 'needs_key'
    assert classify(_message(arn)) == 'needs_key'
    assert classify(_answer({'error': 'Payment required', 'price': '0.01 USDC'})) == 'needs_key'
    assert PAYWALL.search('Pay via x402 to run this tool.')


def test_an_answer_about_x402_services_still_succeeds():
    """A directory of x402 services names the word and did its task."""
    listing = {'services': [{'name': 'weather x402', 'url': 'https://w.example', 'price': '0.001'}] * 6,
               'note': 'x402 resources indexed today, sorted by calls.'}
    assert classify(_answer(listing)) == 'succeeded'


def test_a_paywall_as_often_as_success_puts_the_listing_last():
    from agent_market.concierge.task_outcomes import standing
    assert standing({'succeeded': 1, 'needs_key': 1}) == -1
    assert standing({'succeeded': 5, 'needs_key': 1}) == 1
    assert standing({'succeeded': 1, 'failed': 1}) == 1
    assert standing({'succeeded': 2}) == 1

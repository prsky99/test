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

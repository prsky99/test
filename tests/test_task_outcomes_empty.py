"""11-11 real tasks p13/p08: an answer that found nothing is not a task success."""
from agent_market.concierge.task_outcomes import classify


def text(value):
    return {'content': [{'type': 'text', 'text': value}], 'isError': False}


def test_answers_that_found_nothing_are_failures():
    finz = ('FinzData datasets matching your request:\n- none matched; try simpler words (e.g. "earnings", "rates") '
            'or ask for the catalog. Point-in-time data, certified backtests and positioning history are available.')
    assert classify({'parts': [{'kind': 'text', 'text': finz}]}) == 'failed'
    authors = ('{"query":"retrieval augmented generation","returned":0,"offset":0,"total_matches":0,"authors":[],'
               '"counts_note":"Works, citations and h-index are as reported by the OpenAlex author record and may lag."}')
    assert classify(text(authors)) == 'failed'
    assert classify(text('No results found for "zzqx". Try another spelling or a broader query, '
                         'or ask for the list of supported sources and the date ranges each one covers.')) == 'failed'


def test_real_answers_with_counts_or_no_alerts_stay_successes():
    assert classify(text('{"returned":2,"total_matches":2,"authors":[{"name":"P. Lewis"},{"name":"E. Perez"}]}')) == 'succeeded'
    assert classify(text('No active weather alerts for California right now.')) == 'succeeded'
    assert classify(text('{"returned":0,"items":[{"id":1}]}')) == 'succeeded'  # a list says otherwise
    assert classify(text('Seoul 21:04 KST, New York 07:04 EST')) == 'succeeded'

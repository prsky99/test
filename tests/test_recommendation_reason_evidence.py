"""2nd review steps 5-7 (2026-11-04): condition-first order, task reasons, evidence with unknowns."""
from agent_market.concierge.fast_chat import FastConcierge, condition_first, recommendation_reason
from agent_market.concierge.recommendation_evidence import evidence


def item(name, *, matched=(), unknown=(), violated=(), tools=('get_forecast',), description=''):
    return {'id': hash(name) % 1000, 'kind': 'mcp', 'name': name, 'description': description, 'tools': list(tools),
            'tools_schema': [{'name': t, 'description': ''} for t in tools],
            'task_fit': {'matched': list(matched), 'unknown': list(unknown), 'violated': list(violated)}}


def test_the_candidate_meeting_more_conditions_leads():
    first = item('Seoul weather', matched=['region'], unknown=['forecast'])
    second = item('Korea weather', matched=['region', 'forecast'])
    assert [i['name'] for i in condition_first('weather forecast for Seoul tomorrow', [first, second])] == \
        ['Korea weather', 'Seoul weather']


def test_order_is_kept_without_conditions_and_off_subject_listings_never_rise():
    plain = [item('A weather'), item('B weather')]
    assert condition_first('weather forecast', plain) == plain
    on = item('Weather API', unknown=['forecast'])
    off = item('Shop status', matched=['forecast'], tools=('order_status',))
    assert condition_first('weather forecast', [on, off])[0]['name'] == 'Weather API'


def test_reason_names_the_task_tool_and_conditions_not_matched_words():
    reason = recommendation_reason('flight status', item('FlightAware', matched=['no_api_key'], unknown=['region'],
                                                        tools=('flight_status',)))
    assert reason['text'] == 'Chosen for "flight status" through its flight_status tool; meets no API key; not confirmed: the requested region.'
    assert 'covers' not in reason['text']


def test_brief_uses_the_reason_and_never_the_word_list():
    value = {**item('FlightAware', tools=('flight_status',)), 'url': 'https://example.com/mcp', 'active_checked_at': 1762250000,
             'matched_terms': ['flight', 'status'], 'reason': {'text': 'Chosen for "flight status" through its flight_status tool.'}}
    text = FastConcierge._brief(value)
    assert 'Why: Chosen for "flight status"' in text and 'the listing covers' not in text


def test_evidence_states_unknown_instead_of_implying_a_pass():
    empty = evidence({})
    assert empty == {'health_checked_at': None, 'trial_call': {'status': 'unknown', 'report_id': None, 'at': None},
                     'selected_tool_check': 'unknown', 'unknown': ['health_checked_at', 'trial_call', 'selected_tool_check']}
    full = evidence({'active_checked_at': 1762250000, 'test_report': {'id': 7, 'success': False, 'created_at': 1762240000},
                     'task_verification': {'status': 'verified'}})
    assert full['health_checked_at'].startswith('2025-11-04T') and full['trial_call']['status'] == 'failed'
    assert full['trial_call']['report_id'] == 7 and full['selected_tool_check'] == 'passed' and full['unknown'] == []


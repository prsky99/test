"""One condition verdict per requested condition, and the task's subject first (11-04 review A-1, A-4)."""
from agent_market.concierge.fast_chat import merged_fit, subject_first


def test_no_api_key_is_judged_from_the_access_record():
    open_item = {'auth_required': False, 'task_fit': {'matched': [], 'unknown': [], 'violated': []}}
    keyed = {'auth_required': True, 'auth_method': 'api_key'}
    oauth = {'auth_required': True, 'auth_method': 'oauth2'}
    assert merged_fit(['no_api_key'], open_item) == {'matched': ['no_api_key'], 'unknown': [], 'violated': [], 'status': 'match'}
    assert merged_fit(['no_api_key'], keyed)['violated'] == ['no_api_key']
    assert merged_fit(['no_api_key'], oauth)['status'] == 'unknown'
    assert merged_fit([], open_item)['matched'] == []  # nothing requested, nothing claimed


def test_recorded_conditions_join_the_tool_constraints():
    item = {'task_fit': {'matched': ['pdf_input'], 'unknown': [], 'violated': []},
            'condition_check': {'matched': ['region'], 'unknown': ['language_pair'], 'violated': []}}
    fit = merged_fit([], item)
    assert fit['matched'] == ['pdf_input', 'region'] and fit['unknown'] == ['language_pair'] and fit['status'] == 'unknown'


def test_the_listing_that_names_the_subject_leads():
    shop = {'name': 'Camden Tools Shopping Agent', 'description': 'Order status by order number',
            'tools_schema': [{'name': 'order_status', 'description': 'Track an order with its number'}]}
    town = {'name': 'Agent Town', 'description': 'Status board for agents'}
    flights = {'name': 'FlightAware MCP', 'description': 'Live flight tracking',
               'tools_schema': [{'name': 'flight_status', 'description': 'Flight status by flight number'}]}
    ordered = subject_first('check flight status by flight number', [shop, town, flights])
    assert ordered[0] is flights and ordered[1:] == [shop, town]  # the rest keep their order
    # A first candidate that names the subject keeps its place, even if another says more words.
    clock = {'name': 'Clock tools', 'description': 'Convert time between zones'}
    fuller = {'name': 'Time zone converter', 'description': 'Convert time between time zones'}
    assert subject_first('convert time between time zones', [clock, fuller])[0] is clock


def test_generic_requests_keep_the_search_order():
    items = [{'name': 'A'}, {'name': 'B'}]
    assert subject_first('check the status', items) == items

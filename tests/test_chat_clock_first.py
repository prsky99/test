"""Real-task p13 (11-13~15): a clock question led with a market-data agent whose text says "point-in-time"."""
# ruff: noqa: F401,F811 -- reuse the isolated catalog fixture
import json

from agent_market.concierge.fast_chat import CLOCK_TASK, clock_first, clock_named
from tests.test_fast_single_recommendation import catalog, ask


def test_clock_words_are_read_as_the_clock_capability_only():
    assert CLOCK_TASK.search('What time is it in New York and in Seoul right now?')
    assert CLOCK_TASK.search('current time in New York') and CLOCK_TASK.search('timezone conversion New York Seoul')
    assert not CLOCK_TASK.search('real-time crypto price') and not CLOCK_TASK.search('time series forecasting')
    market = {'id': 1, 'name': 'Market Research', 'description': 'answers with point-in-time data', 'tools': ['backtest']}
    clock = {'id': 2, 'name': 'Zones', 'description': 'Current time and time differences for any IANA time zone'}
    tool = {'id': 3, 'name': 'Utils', 'description': 'handy helpers', 'tools': ['get_current_time']}
    assert not clock_named(market) and clock_named(clock) and clock_named(tool)
    assert clock_first([market, clock, tool]) == [clock, market, tool]
    assert clock_first([market]) == [market]


def _listing(add, now, name, description, tool, tool_description, seconds, category='data_utility'):
    spec = {'name': tool, 'description': tool_description,
            'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']},
            'annotations': {'readOnlyHint': True}}
    return add(name, report_at=now - seconds, description=f'{name}: {description}', category=category,
               usage_guide=json.dumps({'tools': [spec]}))


def test_a_clock_question_is_answered_by_a_listing_that_tells_the_time(catalog):
    _, front, client, add, now = catalog
    market = _listing(add, now, 'Point Data', 'answers market questions with point-in-time data in New York and Seoul',
                      'point_in_time_data', 'Point-in-time market history for New York listed stocks', 1, 'trading_derivatives')
    clock = _listing(add, now, 'City Clock', 'current time and time zone conversion for any city',
                     'get_time', 'Current local time in a city', 300)
    search = front.concierge.rec.search

    def market_first(task, *args, **kwargs):     # production ranked the market agent alone for the question
        found = search(task, *args, **kwargs)
        return [item for item in found if item['id'] != clock] if 'what time' in str(task).lower() else found
    front.concierge.rec.search = market_first
    recs = ask(client, 'What time is it in New York and in Seoul right now?')['data']['recommendations']
    assert recs and recs[0]['id'] == clock and market not in [r['id'] for r in recs][:1]

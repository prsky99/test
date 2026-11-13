"""After a failed run the answer says how to get past it (growth plan 7 item 4, PM 11-14 04:3x order).

Every failure code has one fix line; bad input names the tool's required arguments with example values; the MCP
call tool and the A2A "run" command both carry it (same run_admitted_call path)."""
import json

from agent_market.concierge import execution_errors
from tests.test_a2a_run import conversation, item, send  # noqa: F401 - fixture
from tests.test_fast_single_recommendation import catalog  # noqa: F401 - fixture used by managed
from tests.test_managed_agent_gateway import managed  # noqa: F401 - fixture
from tests.test_mcp_proxy import WEATHER_TOOL


def test_every_failure_code_has_a_fix_line():
    assert set(execution_errors.FIXES) == set(execution_errors.MESSAGES)
    assert all(text.endswith('.') and len(text) < 220 for text in execution_errors.FIXES.values())
    assert execution_errors.fix_for('something else') == execution_errors.FIXES['EXECUTION_FAILED']


def test_bad_input_names_the_required_arguments():
    text = execution_errors.fix_for('INVALID_INPUT', WEATHER_TOOL)
    assert 'for example {"city":' in text and text.endswith('(fill in the values).')
    assert execution_errors.fix_for('INVALID_INPUT') == execution_errors.FIXES['INVALID_INPUT']


def test_a_failed_mcp_call_says_how_to_fix_it(managed):  # noqa: F811
    store, front, client, add, rid, calls, remote = managed
    private = add('Private Weather', auth_observed=1)
    r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'call', 'arguments': {'resource_id': private, 'tool': 'get_weather', 'arguments': {'city': 'Paris'}}}})
    result = r.json()['result']
    assert result['isError'] is True
    execution = result['structuredContent']['execution']
    assert execution['fix'] and 'How to fix: ' + execution['fix'] in result['content'][0]['text']


def test_a_failed_a2a_run_carries_the_same_fix_line(conversation):  # noqa: F811
    store, front, client, add, rid, calls, ctx, listed = conversation
    private = add('Private Weather 2', auth_observed=1)
    listed['items'] = [item(private, WEATHER_TOOL)]
    _, text, data = send(client, 'run 1 ' + json.dumps({'city': 'Paris'}), ctx)
    assert data['ok'] is False and data['execution']['fix'] and 'How to fix: ' in text

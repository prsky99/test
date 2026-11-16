"""Agent team 11-16 (PM due 11-20): the trial call stores the server's fingerprint-v1 in trial_info."""
from agent_market.collector.capabilities import stamp_fingerprint
from agent_market.tool_fingerprint import VERSION, server_fp

TOOLS = [{'name': 'get_rate', 'description': 'FX rate', 'inputSchema': {'type': 'object'}}]


def test_a_trial_gets_the_server_fingerprint_of_its_tool_list():
    trial = stamp_fingerprint({'tool': 'get_rate', 'ok': True}, TOOLS)
    assert trial['server_fp'] == server_fp(TOOLS) and trial['fp_version'] == VERSION == 'fingerprint-v1'
    assert not trial['server_fp'].startswith('sha256:') and len(trial['server_fp']) == 64


def test_no_trial_or_no_tool_list_adds_nothing():
    assert stamp_fingerprint(None, TOOLS) is None
    assert stamp_fingerprint({'tool': 'x'}, None) == {'tool': 'x'}

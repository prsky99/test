"""PM 11-13 22:4x: the public agent detail sends one copy of the tool list. usage_guide.tools repeated agent.tools
(listing 52185: 236 KB, 120 KB tools + 115 KB usage_guide.tools, gzip 75 KB) and dropped one deeply nested tool."""
import json

from agent_market.collector import usage
from tests.test_fast_single_recommendation import catalog  # noqa: F401  (fixture used by managed)
from tests.test_managed_agent_gateway import managed  # noqa: F401  (fixture)


def big_tool(n):
    """About the size of one of 52185's 36 tools: a long description and a dozen described inputs."""
    properties = {f'field_{k}': {'type': 'string', 'description': f'Input {k} of tool {n}. ' + 'Explains the accepted values. ' * 4}
                  for k in range(12)}
    return {'name': f'get_report_{n}', 'description': f'Get report {n}. ' + 'Returns a structured summary of the record. ' * 14,
            'inputSchema': {'type': 'object', 'properties': properties, 'required': ['field_0']},
            'annotations': {'readOnlyHint': True}}


def test_detail_carries_one_copy_of_a_large_tool_list(managed):
    store, front, client, _, rid, calls, remote = managed
    remote.tools = [big_tool(n) for n in range(36)]
    compact = usage.compact_tools(remote.tools)
    store.record_usage(rid, tools=compact, digest=usage.tools_hash(compact), guide={}, changes=None, trial={'ok': True})
    response = client.get(f'/api/agents/{rid}')
    agent = response.json()['agent']
    assert len(agent['tools']) == 36
    assert agent['usage_guide'].get('tools_ref') == 'agent.tools' and 'tools' not in agent['usage_guide']
    tools_bytes = len(json.dumps(agent['tools']))
    assert tools_bytes > 60000                                   # a 52185-sized list
    # The whole answer is the tool list once plus a bounded remainder, never the list twice.
    assert len(response.content) < tools_bytes + 20000, (len(response.content), tools_bytes)

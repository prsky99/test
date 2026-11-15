"""E12 (PM 11-15): what the Claude Connectors Directory asks of every tool, checked on both MCP servers.

claude.com/docs/connectors/building/submission: every tool includes a title and the applicable readOnlyHint or
destructiveHint. Our /mcp listed 13 of 16 tools without a title and /mcp/compact all five (11-15 public tools/list)."""
from agent_market.agent_access import contracts
from agent_market.concierge.mcp_contract import mcp_tools


def missing(tools):
    out = []
    for tool in tools:
        notes = tool.get('annotations') or {}
        if not (tool.get('title') and notes.get('title')):
            out.append((tool['name'], 'title'))
        if 'readOnlyHint' not in notes and 'destructiveHint' not in notes:
            out.append((tool['name'], 'hint'))
    return out


def test_every_main_tool_has_a_title_and_a_hint():
    tools = mcp_tools()
    assert len(tools) >= 15 and missing(tools) == []


def test_every_compact_tool_has_a_title_and_a_hint():
    build = [getattr(contracts, n) for n in dir(contracts) if n.endswith('tools') and callable(getattr(contracts, n))]
    assert build, 'compact tool builder not found'
    tools = build[0]()
    assert len(tools) == 5 and missing(tools) == []

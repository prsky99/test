"""Smaller MCP discovery answers without losing information (11-11 PM: find_agents was ~12.8 KB).

Only exact repeats are removed from `search`/`find_agents` structuredContent; every value an agent
needs stays once:
- a recommendation's display_name when it equals name, usage_endpoint when it equals url (both are the
  gateway URL), revalidate_after_sec when it equals the answer's own, and an empty capability_contracts;
- a next step tool's legacy `parameters` map when it equals inputSchema.properties, and its
  revalidate_after_sec when it equals the answer's own;
- the two MCP gateway notes every MCP card repeats word for word (optional tools/list, report after the
  call) move to one top-level `connect_notes`; each card keeps its POST line and its tools/call example.
Recommendation order, ids, tools_schema, contracts, reasons and evidence are unchanged.
"""
from .connections import gateway_mcp_steps

_SHARED_MCP_NOTES = tuple(gateway_mcp_steps('')[i] for i in (1, 3))


def _card(item, revalidate):
    if not isinstance(item, dict):
        return item, False
    item = dict(item)
    if 'display_name' in item and item['display_name'] == item.get('name'):
        del item['display_name']
    if 'usage_endpoint' in item and item['usage_endpoint'] == item.get('url'):
        del item['usage_endpoint']
    if revalidate is not None and item.get('revalidate_after_sec') == revalidate:
        del item['revalidate_after_sec']
    if item.get('capability_contracts') == []:
        del item['capability_contracts']
    steps = item.get('connect_steps')
    moved = False
    if item.get('kind') == 'mcp' and isinstance(steps, list) and all(note in steps for note in _SHARED_MCP_NOTES):
        item['connect_steps'] = [step for step in steps if step not in _SHARED_MCP_NOTES]
        moved = True
    return item, moved


def _next_step(step, revalidate):
    if not isinstance(step, dict):
        return step
    step = dict(step)
    if revalidate is not None and step.get('revalidate_after_sec') == revalidate:
        del step['revalidate_after_sec']
    tool = step.get('tool')
    if isinstance(tool, dict) and 'parameters' in tool:
        schema = tool.get('inputSchema')
        if isinstance(schema, dict) and tool['parameters'] == schema.get('properties'):
            step['tool'] = {k: v for k, v in tool.items() if k != 'parameters'}
    return step


def compact_discovery(structured):
    """A copy of a search/find_agents structuredContent with exact repeats removed."""
    if not isinstance(structured, dict):
        return structured
    result = dict(structured)
    revalidate = result.get('revalidate_after_sec')
    moved = False
    for key in ('recommendations', 'alternatives'):
        if isinstance(result.get(key), list):
            cards = []
            for item in result[key]:
                card, notes = _card(item, revalidate)
                moved = moved or notes
                cards.append(card)
            result[key] = cards
    if isinstance(result.get('next_steps'), list):
        result['next_steps'] = [_next_step(step, revalidate) for step in result['next_steps']]
    if moved:
        result['connect_notes'] = list(_SHARED_MCP_NOTES)
    return result

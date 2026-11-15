"""What a first-time agent reads about coming back (PM 11-15 11:5x, revisit review P2-P4).

llms.txt opens with what the service does and why to use it on every call; ads and the x402 note come after. The
return-visit lines lead with what works with no token (check_agent, report, asking again) and do not claim that a
check calls the agent (it reads our recorded status)."""
from agent_market.concierge import front, mcp_contract
from agent_market.concierge.front import llms_txt


def test_llms_opens_with_what_it_does_and_the_every_call_reasons():
    text = llms_txt('https://agentconcierge.biz', {}, None)
    head = '\n'.join(text.splitlines()[:8])
    assert 'Tell it a task' in head and 'Use it each time you call an agent' in head
    assert '/api/agent/v1/check?url=' in head and 'report' in head and '/api/feed/verified.json' in head
    assert text.index('Use it each time') < text.index('Sponsored placements') < text.index('Compact remote MCP')
    assert text.index('Use it each time') < text.index('x402 listings come from earlier records')
    assert 'x402' not in head


def test_return_visit_lines_lead_with_what_needs_no_token():
    for line in (front.RETURN_VISIT, front.A2A_RETURN_VISIT):
        assert line.index('check') < line.index('/api/task-updates')
        assert 'answers now' not in line
    assert '`whats_new`' in front.RETURN_VISIT and "what's new" in front.A2A_RETURN_VISIT


def test_tool_descriptions_point_to_check_before_each_call():
    tools = {t['name']: t['description'] for t in mcp_contract.TOOLS} if hasattr(mcp_contract, 'TOOLS') else None
    source = open(mcp_contract.__file__, encoding='utf-8').read()
    assert 'run check_agent on its endpoint' in source and 'Use it before each call' in source
    if tools:
        assert 'check_agent' in tools['find_agents']

"""E2 variant B tool descriptions (PM 11-15): short, and each says what the tool is for, when to use it and what it
returns. The live descriptions stay until the search team wires the A/B split."""
from agent_market.concierge import check_route, mcp_contract


def test_variant_b_is_short_and_has_purpose_when_and_returns():
    for name, text in mcp_contract.DESCRIPTIONS_B.items():
        assert len(text) <= 260, (name, len(text))
        assert 'Use ' in text and 'Returns ' in text and 'Read-only' in text, name
        assert 'answers now' not in text   # a check reads our records; it never calls the agent


def test_variant_b_names_live_tools():
    live = {t['name'] for t in mcp_contract.TOOLS} if hasattr(mcp_contract, 'TOOLS') else set()
    live |= {t['name'] for t in getattr(check_route, 'TOOLS', [])}
    source = open(mcp_contract.__file__, encoding='utf-8').read() + open(check_route.__file__, encoding='utf-8').read()
    for name in mcp_contract.DESCRIPTIONS_B:
        assert name in live or ("'" + name + "'") in source or ('"' + name + '"') in source, name

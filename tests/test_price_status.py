"""11-12 (PM ⑦): agent answers carry price_status; a listing that states a price is never price 0 / free."""
from agent_market.concierge.connections import public_agent
from agent_market.concierge.engine import price_text
from agent_market.concierge.growth_pages import stated_price as page_rule
from agent_market.concierge.price_status import price_fields, stated_price


def test_price_fields():
    assert price_fields('mcp', 0, 'Weather', 'Forecasts for any city') == (0, 'free')
    assert price_fields('mcp', 0, 'MoneyTools Transcripts', 'x402 $0.002/min transcripts') == (None, 'paid_or_unknown')
    assert price_fields('a2a', 0, 'Data agent', 'Costs 0.01 USDC per request') == (None, 'paid_or_unknown')
    assert price_fields('mcp', 0, 'Pay-per-call search', '') == (None, 'paid_or_unknown')
    assert price_fields('mcp', 0, 'Open tool', 'Free: $0 per call, 0 USDC') == (0, 'free')  # zero is not a price
    assert price_fields('mcp', None, 'Tool', 'no price info') == (None, 'paid_or_unknown')
    assert price_fields('x402', 2000, 'Quote', 'x402 $0.002/call') == (2000, 'paid')
    assert price_fields('x402', None, 'Quote', '') == (None, 'paid_or_unknown')
    assert price_fields('x402', 0, 'Quote', '') == (0, 'free')  # the Free badge test; unknown amounts are null
    assert page_rule is stated_price  # pages and agent answers use one rule


def test_public_cards_carry_the_status_and_cards_without_a_price_stay_without_one():
    paid = public_agent({'id': 7, 'kind': 'mcp', 'name': 'Transcripts', 'description': 'x402 $0.002/min',
                         'price_usdc': 0}, store=None)
    assert paid['price_usdc'] is None and paid['price_status'] == 'paid_or_unknown'
    free = public_agent({'id': 8, 'kind': 'mcp', 'name': 'Weather', 'description': 'Forecasts', 'price_usdc': 0}, store=None)
    assert free['price_usdc'] == 0 and free['price_status'] == 'free'
    # The description may come from the resource when the card value leaves it out.
    from_resource = public_agent({'id': 9, 'kind': 'a2a', 'price_usdc': 0},
                                 resource={'id': 9, 'kind': 'a2a', 'description': 'Each call costs 0.05 USDC'}, store=None)
    assert from_resource['price_status'] == 'paid_or_unknown'
    bare = public_agent({'id': 10, 'kind': 'mcp', 'name': 'Agent'}, store=None)
    assert 'price_status' not in bare


def test_chat_price_text():
    assert price_text(0, 'mcp', 'free') == 'free to call (may need an account)'
    assert price_text(None, "mcp", "paid_or_unknown") == "paid or unknown (the provider states a price)"
    assert price_text(2000, 'x402', 'paid') == '$0.002 USDC per call'


def test_texts_that_used_to_say_free_for_a_missing_price():
    import pathlib
    from agent_market.concierge import notify
    owner = next(c for c in vars(notify).values() if isinstance(c, type) and hasattr(c, '_format_tools_text'))
    text = owner._format_tools_text(None, [{'name': 'Transcripts', 'kind': 'mcp', 'price_usdc': None,
                                             'price_status': 'paid_or_unknown', 'description': 'x402 $0.002/min'}])
    assert 'Paid or unknown' in text and 'Free' not in text
    detail = pathlib.Path(__file__).resolve().parents[1].joinpath('new/en/assets/operating.js').read_text()
    assert 'a.price_status === "paid_or_unknown" ? "Paid or unknown" : "Free"' in detail

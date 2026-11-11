"""One price rule for every answer about a listing (11-11 PM: the Free badge rule also for agent answers).

Collection stores price_usdc 0 for most MCP and A2A listings whose provider never stated a price, while
1,193 active listings say in their own name or description that calls cost money ("$0.002/min",
"0.01 USDC", "pay-per-call"; sample 25/25 paid). Answers to agents therefore carry a price_status next to
price_usdc, and a listing that states a price has price_usdc null instead of 0:

- "free": no stated price and a price of 0 (the public Free badge uses the same test)
- "paid": an x402 listing with a known amount per call (price_usdc, in micro-USDC)
- "paid_or_unknown": the listing states a price, or the amount is not known
An amount of zero ("$0 per call", "0 USDC") is not a stated price.
"""
import re

_NONZERO = r'(?!0+(?:\.0+)?(?![\d.]))\d+(?:\.\d+)?'
STATED_PRICE = re.compile(r'x402[^a-z0-9]{0,3}\$\s?' + _NONZERO + r'|\$\s?' + _NONZERO + r'\s?(?:/|per\s)'
                          + r'|\b' + _NONZERO + r'\s?usdc\b|\bpay[\s-]per[\s-](?:call|use|request|minute)', re.I)


def stated_price(*texts):
    return any(isinstance(text, str) and STATED_PRICE.search(text) for text in texts)


def price_fields(kind, price, name=None, description=None):
    """(price_usdc, price_status) for an answer. KIND is kept for callers; the rule is the same for every kind."""
    known = isinstance(price, (int, float)) and not isinstance(price, bool)
    if known and price > 0:
        return price, 'paid'
    if stated_price(name, description):
        return None, 'paid_or_unknown'
    if known and price == 0:  # the Free badge test; collection stores an unknown x402 amount as null
        return price, 'free'
    return None, 'paid_or_unknown'

"""Decide, after an organic Chat or Explore answer, whether a paid upgrade exists.

Runs as its own request after the answer has been shown, so it adds nothing to
the Chat or Explore response time. It reads only catalog facts (price, quality
grade, health) of the agents the organic answer already returned, in that
order. It never sees sponsors, bids or wallets and never re-ranks.
"""
import math
import re

from .config import COIN_VALUE_WON
from .exchange import eligible_for_sponsorship, selection_digest

USD_WON = 1380                       # planning rate (plan v3); not a payment rate
COIN_GRADES = frozenset(('A', 'B'))  # coin acceptance needs grade B or better
LIVE = frozenset(('healthy', 'reachable'))
MAX_IDS = 10
SPONSOR_MAX_WON = 50_000           # above this a sponsor cannot cover one run in test mode
QUOTE_MAX_WON = 1_000_000


def price_won(price_usdc):
    """Catalog x402 prices are USDC base units (6 decimals)."""
    if type(price_usdc) is not int or price_usdc <= 0:
        return 0
    won = price_usdc / 1_000_000 * USD_WON
    return max(COIN_VALUE_WON, math.ceil(won / COIN_VALUE_WON) * COIN_VALUE_WON)


def category_of(value):
    text = re.sub(r'[^a-z0-9]+', '_', str(value or '').lower()).strip('_')[:40]
    if len(text) < 2 or not text[0].isalpha():
        return 'general'
    return text


def facts(resource):
    price = price_won(resource.get('price_usdc'))
    grade = str(resource.get('eval_grade') or '').upper()[:1] or None
    health = resource.get('health_status') or 'unknown'
    accepts = bool(price) and grade in COIN_GRADES and health in LIVE and bool(resource.get('active', 1))
    reasons = []
    if not price:
        reasons.append('free')
    if price and grade not in COIN_GRADES:
        reasons.append('grade_below_b' if grade else 'not_graded')
    if price and health not in LIVE:
        reasons.append('not_live')
    return {'id': resource['id'], 'name': resource.get('name'), 'kind': resource.get('kind'),
            'price_won': price, 'price_coins': price // COIN_VALUE_WON, 'grade': grade, 'health': health,
            'accepts_coins': accepts, 'reasons': reasons, 'category': category_of(resource.get('category'))}


def upgrade_check(read_resource, ids):
    """`ids` are the organic answer's agent ids in its own order; the first is
    the top recommendation. `read_resource(id)` returns a catalog row or None."""
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_IDS or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError('recommendation_ids must list 1 to 10 catalog ids from the answer.')
    rows = []
    for rid in ids:
        row = read_resource(rid)
        if row:
            rows.append(facts(row))
    digest = selection_digest({'recommendation_ids': ids})
    result = {'profile': 'ai-ad-coin-upgrade-check-v1', 'selection_digest': digest, 'checked': rows,
              'upgrade_available': False, 'sponsorable': False, 'target': None, 'quote_request': None,
              'order_preserved': True, 'reads': ['price', 'quality_grade', 'health']}
    if not rows:
        result['reason'] = 'no_catalog_rows'
        return result
    top = rows[0]
    if top['accepts_coins']:
        target, why = top, 'top_recommendation_is_paid'
    elif not top['price_won']:
        target = next((r for r in rows[1:] if r['accepts_coins']), None)
        why = 'paid_alternative_in_answer'
    else:
        target, why = None, 'top_paid_but_not_eligible'
    if not target:
        result['reason'] = why if why == 'top_paid_but_not_eligible' else 'no_eligible_paid_agent'
        return result
    price = target['price_won']
    sponsorable = eligible_for_sponsorship(price) and price <= SPONSOR_MAX_WON
    result['sponsorable'] = sponsorable
    result['sponsorship_note'] = (None if sponsorable else
        'below_sponsorship_minimum: pay with coins or use the free result' if price < 500 else
        'above_sponsorship_cap: a sponsor cannot cover one run of this price')
    if price > QUOTE_MAX_WON:
        result.update({'upgrade_available': True, 'reason': why, 'target': target, 'quote_request': None})
        return result
    result.update({
        'upgrade_available': True, 'reason': why, 'target': target,
        'note': ('The free result stays available. The paid agent is shown only because the answer '
                 'already listed it; compare what each can do before asking the person.'),
        'quote_request': {'selection': {'recommendation_ids': ids},
                          'task': {'provider': 'r' + str(target['id']), 'task_ref': 'resource-' + str(target['id']),
                                   'price_won': target['price_won'], 'category': target['category']}}})
    return result

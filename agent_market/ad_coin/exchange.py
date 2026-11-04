"""Task sponsorship auction and the coin products offered beside it.

The auction sees only the task the organic recommender already chose: provider,
price and a coarse category. It cannot change that choice; the packet carries a
digest of the organic selection so anyone can check it afterwards.
"""
import hashlib
import math

from .config import (COIN_VALUE_WON, MAX_SPONSORED_OPTIONS, MIN_SPONSORED_TASK_COINS, TASK_SHARE_BPS)
from .receipts import canonical

CATEGORY = r'[a-z][a-z0-9_]{1,40}(/[a-z][a-z0-9_]{1,40})?'
INCREMENT_WON = 10
# Coin products (plan v3, section 7). Advertiser price per completed product.
COIN_PRODUCTS = {
    'P2': {'name': 'View and confirm', 'min_ms': 15000, 'needs_answer': True},
}


def selection_digest(selection):
    """sha256 over the organic selection exactly as the recommender returned it."""
    return 'sha256:' + hashlib.sha256(canonical(selection)).hexdigest()


def task_floor_won(price_won):
    return math.ceil(price_won * 10000 / TASK_SHARE_BPS / INCREMENT_WON) * INCREMENT_WON


def relevance(campaign_categories, task_category):
    if task_category in campaign_categories:
        return 1.0
    parent = task_category.split('/', 1)[0]
    if parent in campaign_categories or any(c.split('/', 1)[0] == parent for c in campaign_categories):
        return 0.6
    return 0.0


def eligible_for_sponsorship(price_won):
    return price_won // COIN_VALUE_WON >= MIN_SPONSORED_TASK_COINS


def run_task_auction(campaigns, task_category, price_won):
    """Second-price auction over relevance-weighted bids.

    `campaigns`: dicts with id, bid_won, categories (set), escrow_won.
    Returns {'winner', 'price_won', 'floor_won', 'ranked'} or None.
    The winner pays max(floor, the runner-up's weighted bid / its own weight +
    increment), never more than its own bid, so bidding the true value is safe."""
    if not eligible_for_sponsorship(price_won):
        return None
    floor = task_floor_won(price_won)
    ranked = []
    for campaign in campaigns:
        weight = relevance(campaign['categories'], task_category)
        if weight <= 0 or campaign['bid_won'] < floor or campaign['escrow_won'] < floor:
            continue
        ranked.append((campaign['bid_won'] * weight, weight, campaign))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[2]['id']))
    score, weight, winner = ranked[0]
    if len(ranked) > 1:
        runner_score = ranked[1][0]
        price = math.ceil(runner_score / weight / INCREMENT_WON) * INCREMENT_WON + INCREMENT_WON
    else:
        price = floor
    price = min(max(price, floor), winner['bid_won'])
    price = min(price, winner['escrow_won'])
    return {'winner': winner, 'price_won': int(price), 'floor_won': floor,
            'ranked': [item[2]['id'] for item in ranked]}


def coin_option_count(price_won, reward_won_each):
    """How many P2 products cover the task, if any."""
    if reward_won_each <= 0:
        return None
    count = math.ceil(price_won / reward_won_each)
    return count if count <= MAX_SPONSORED_OPTIONS else None

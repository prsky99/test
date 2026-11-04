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


MAX_STEPS = 20
MAX_CALLS = 1000


def _allocate(micro_lines, total_won):
    """Split a total rounded once to whole coins across lines, largest remainders first,
    so line amounts are whole won and add up exactly."""
    floors = [m // 1_000_000 for m in micro_lines]
    left = total_won - sum(floors)
    order = sorted((i for i, m in enumerate(micro_lines) if m), key=lambda i: (-(micro_lines[i] % 1_000_000), i))
    k = 0
    while left > 0 and order:
        floors[order[k % len(order)]] += 1
        left -= 1
        k += 1
    return floors


def bundle_check(read_resource, steps):
    """Price a task bundle the organic plan already chose: steps of catalog agents and
    how many calls each needs. One run of the bundle is the unit a sponsor can cover;
    single x402 calls are mostly far below the 50-coin minimum."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError('bundle needs 1 to 20 steps.')
    clean = []
    for step in steps:
        if (not isinstance(step, dict) or type(step.get('resource_id')) is not int or step['resource_id'] <= 0
                or type(step.get('calls')) is not int or not 1 <= step['calls'] <= MAX_CALLS):
            raise ValueError('Each step needs a catalog resource_id and 1 to 1000 calls.')
        clean.append({'resource_id': step['resource_id'], 'calls': step['calls']})
    digest = selection_digest({'bundle': clean})
    result = {'profile': 'ai-ad-coin-bundle-check-v1', 'selection_digest': digest, 'upgrade_available': False,
              'sponsorable': False, 'lines': [], 'quote_request': None, 'order_preserved': True}
    micro, rows = [], []
    for step in clean:
        row = read_resource(step['resource_id'])
        if not row:
            result['reason'] = 'unknown_step'
            result['unknown'] = step['resource_id']
            return result
        fact = facts(row)
        unit = row.get('price_usdc') if type(row.get('price_usdc')) is int and row.get('price_usdc') > 0 else 0
        micro.append(unit * USD_WON * step['calls'])
        rows.append((step, fact))
    blocked = [f['id'] for s, f in rows if f['price_won'] and not f['accepts_coins']]
    total_micro = sum(micro)
    total = math.ceil(total_micro / 1_000_000 / COIN_VALUE_WON) * COIN_VALUE_WON if total_micro else 0
    split = _allocate(micro, total) if total else [0] * len(rows)
    result['lines'] = [{'resource_id': f['id'], 'name': f['name'], 'calls': s['calls'], 'won': won,
                        'grade': f['grade'], 'health': f['health'], 'accepts_coins': f['accepts_coins'] or not f['price_won']}
                       for (s, f), won in zip(rows, split)]
    result['price_won'] = total
    result['price_coins'] = total // COIN_VALUE_WON
    if not total:
        result['reason'] = 'all_steps_free'
        return result
    if blocked:
        result['reason'] = 'bundle_has_ineligible_step'
        result['blocked'] = blocked
        return result
    costliest = max(rows, key=lambda item: micro[rows.index(item)])[1]
    sponsorable = eligible_for_sponsorship(total) and total <= SPONSOR_MAX_WON
    result.update({'upgrade_available': True, 'reason': 'paid_bundle', 'sponsorable': sponsorable,
                   'sponsorship_note': None if sponsorable else (
                       'below_sponsorship_minimum: pay with coins or use the free result' if total < 500 else
                       'above_sponsorship_cap: a sponsor cannot cover one run of this price')})
    if total <= QUOTE_MAX_WON:
        result['quote_request'] = {'selection': {'bundle': clean}, 'task': {
            'provider': 'bundle', 'task_ref': 'bundle-' + digest[7:23], 'price_won': total,
            'category': costliest['category'],
            'lines': [{'provider': 'r' + str(line['resource_id']), 'calls': line['calls'], 'won': line['won']}
                      for line in result['lines']]}}
    return result


MAX_RUNS = 100
NOT_FOUND = {'workflow': 'workflow_not_published', 'test_product': 'unknown_test_product',
             'private_workflow': 'private_workflow_unavailable'}
PREFIX = {'workflow': 'workflow-', 'test_product': 'product-', 'private_workflow': 'private-'}


def workflow_steps(workflow):
    """Agent nodes of a published workflow, merged per catalog agent, one call per run.

    Every branch is counted, so the quote is an upper bound: a router branch that
    does not run is refunded line by line after the run. Disabled nodes and
    triggers, routers and transforms cost nothing. Agent nodes without a catalog
    id cannot be priced and are listed so the person can see them."""
    counts, order, unpriced = {}, [], []
    for node in workflow.get('nodes') or []:
        if not isinstance(node, dict) or node.get('type', 'agent') != 'agent':
            continue
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        if node.get('disabled') or data.get('disabled') or node.get('is_active') is False or data.get('is_active') is False:
            continue
        rid = node.get('resource_id') or data.get('resource_id')
        if type(rid) is not int or rid <= 0:
            unpriced.append(str(node.get('name') or node.get('id') or 'step')[:80])
            continue
        per_run = data.get('calls_per_run', 1)
        per_run = per_run if type(per_run) is int and 1 <= per_run <= 100 else 1
        if rid not in counts:
            order.append(rid)
        counts[rid] = counts.get(rid, 0) + per_run
    branching = any(isinstance(n, dict) and n.get('type') == 'router' for n in workflow.get('nodes') or [])
    return [{'resource_id': rid, 'calls': counts[rid]} for rid in order], unpriced, branching


def workflow_check(read_workflow, read_resource, template_id, runs=1):
    """Price `runs` runs of a published workflow as one sponsorable task."""
    if type(template_id) is not int or not 0 < template_id < 2 ** 31:
        raise ValueError('template_id must be a positive integer.')
    return check_definition(read_workflow(template_id), read_resource, runs, 'workflow', template_id)


def check_definition(workflow, read_resource, runs, label, ident):
    if type(runs) is not int or not 1 <= runs <= MAX_RUNS:
        raise ValueError('runs must be 1 to 100.')
    profile = 'ai-ad-coin-' + label.replace('_', '-') + '-check-v1'
    if not workflow:
        return {'profile': profile, 'upgrade_available': False, 'sponsorable': False,
                'reason': NOT_FOUND.get(label, 'unknown_' + label),
                'quote_request': None}
    per_run, unpriced, branching = workflow_steps(workflow)
    info = {'id': workflow.get('id', ident), 'name': workflow.get('name'), 'runs': runs, 'kind': label,
            'definition_hash': workflow.get('definition_hash'), 'upper_bound': branching,
            'unpriced_steps': unpriced}
    if not per_run:
        return {'profile': profile, 'upgrade_available': False, 'sponsorable': False,
                'reason': 'no_catalog_steps', 'workflow': info, 'quote_request': None}
    if len(per_run) > MAX_STEPS:
        return {'profile': profile, 'upgrade_available': False, 'sponsorable': False,
                'reason': 'too_many_paid_agents', 'workflow': info, 'quote_request': None}
    steps = [{'resource_id': s['resource_id'], 'calls': min(s['calls'] * runs, MAX_CALLS)} for s in per_run]
    result = bundle_check(read_resource, steps)
    result['profile'] = profile
    result['workflow'] = info
    if unpriced and result.get('upgrade_available'):
        result['note'] = ('Some agent steps have no catalog price and are not covered: '
                          + ', '.join(unpriced[:5]) + '.')
    if result.get('quote_request'):
        digest = (workflow.get('definition_hash') or '')[:12]
        result['quote_request']['selection'] = {'bundle': steps, label: {
            'id': info['id'], 'definition_hash': info['definition_hash'], 'runs': runs}}
        result['selection_digest'] = selection_digest(result['quote_request']['selection'])
        prefix = PREFIX.get(label, label + '-')
        result['quote_request']['task']['task_ref'] = (prefix + str(info['id']) + ('-' + digest if digest else '')
                                                      + '-x' + str(runs))[:96]
    return result

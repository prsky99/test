"""Agent-facing Sponsored offer slot on MCP and A2A answers (agent ad plan (A), PM 11-14, due 11-18).

This module is on the organic side and never imports ad_coin (tests/test_ad_coin.py::
test_organic_selection_cannot_import_ad_coin, no exception). The ad side registers one provider with register();
until it does, nothing is attached. Rules:
- the slot is filled only after the organic answer is final, and the provider gets facts about that answer
  (surface, tool, task categories, role field, broad region) but never the results themselves or the query text,
  so an ad cannot change what was found or its order;
- the offer goes into a separate `sponsored` list (at most one item) after the results, and its text line, labelled
  "Sponsored:", comes after the organic text;
- the slot is always offered (user decision 11-15: there is no free opt-out; ad-free answers will be a paid monthly
  subscription once usage grows). An `ads` argument or header is ignored and removed before the organic tools run;
- a provider error, a slow provider or a malformed offer leaves the slot empty; the organic answer never fails.
The offer's fields are the AD Coin team's schema (agent_market/ad_coin/v2/sponsored_offer.py, agent_block); this module
only checks the label, caps sizes and strips control characters, so that an offer cannot pose as an instruction line.
Facts: the ad side never reads judging data, so the independent facts (grade, recent health, latest test report) are
filled here, from our own records for the offer's endpoint, and shown even when they are low. They are read through
the check_agent index and the verify snapshot, kept ten minutes per endpoint, and only for an offer being shown.
"""
import re
import time

_PROVIDER = None
_SOURCES = {'store': None, 'base': 'https://agentconcierge.biz'}
FACT_KEYS = ('grade', 'report_score', 'report_url', 'report_signature', 'data_at', 'health_7d')
FACT_NOTE = 'Measured by AgentValCon; advertising cannot change it.'
FACT_SECONDS = 600
_FACTS = {}
LABEL = 'Sponsored'
DESCRIPTION_LINE = ('Ads: at most one offer labelled "Sponsored" may follow the results in a separate `sponsored` field; '
                    'it never changes the results.')
# Machine-readable disclosure on every offer (PM 11-21 assignment, 11-16): set here on the organic side after the
# provider's fields are cleaned, so an advertiser can neither drop nor change it. The ad stays in its own `sponsored`
# field, apart from the results, the ranking and the evidence (`facts` are ours and say so).
AFFECTS = {'ranking': False, 'selection': False, 'test_results': False}
STATEMENT = 'Advertising does not affect ranking, selection or test results.'
MAX_LINE = 400
MAX_FIELD = 2000
SLOW_SECONDS = 0.05      # the provider is an in-memory lookup; a slower call is noted, never retried
_CONTROL = re.compile(r'[\x00-\x1f\x7f  ]+')
_STATS = {'calls': 0, 'filled': 0, 'errors': 0, 'slow': 0}


def register(provider):
    """The ad side's provider: provider(context) -> dict | None. None unregisters."""
    global _PROVIDER
    _PROVIDER = provider


def configure(store=None, base=None):
    """front.py: where facts are read from (our catalog store) and the public base for relative links."""
    if store is not None:
        _SOURCES['store'] = store
    if base:
        _SOURCES['base'] = base.rstrip('/')


def registered():
    return _PROVIDER is not None


def stats():
    return dict(_STATS)


def _header(headers, name):
    try:
        return (headers.get(name) or '') if headers is not None else ''
    except Exception:
        return ''


def strip_option(arguments):
    """Arguments without `ads` (an old opt-out an agent may still send; ignored since 11-15), so the organic tools see
    exactly what they saw before this slot existed and the request never fails on it."""
    return {k: v for k, v in arguments.items() if k != 'ads'} if isinstance(arguments, dict) and 'ads' in arguments else arguments


def context(surface, tool, structured=None, headers=None, task=None):
    """Facts about a finished answer that an ad may be matched on: never its results or the visitor. The task text goes
    only to the ad side's sensitive-topic rule (no ad on medical, legal or financial advice), which does not keep it."""
    structured = structured if isinstance(structured, dict) else {}
    items = structured.get('recommendations') if isinstance(structured.get('recommendations'), list) else []
    categories = [i.get('category') for i in items if isinstance(i, dict) and isinstance(i.get('category'), str)]
    top = structured.get('category') if isinstance(structured.get('category'), str) else None
    qa = bool(_header(headers, 'x-agentcon-qa'))
    return {'surface': surface, 'tool': tool, 'category': top, 'categories': categories,
            'role': structured.get('role') if isinstance(structured.get('role'), str) else None,
            'role_field': structured.get('field') if isinstance(structured.get('field'), str) else None,
            'task': task[:500] if isinstance(task, str) else (structured.get('task') if isinstance(structured.get('task'), str) else ''),
            'region': _header(headers, 'cf-ipcountry').upper()[:2],
            'counted': _header(headers, 'early-data') != '1' and not qa}


PRICE_LINE = '5 USDC on Base per placement per day, or a custom plan sized to your budget; paid once per booking from your own wallet (no prepaid balance, no stored funds)'


KEYLESS_STEPS = (
    'POST /api/ad-coin/v2/sponsor with {name, text, url, category, region, day | budget_usdc}: returns order_id, '
    'status_url and read_key (shown once; it cannot be recovered)',
    'GET /api/ad-coin/v2/sponsor/{order_id} with header X-Read-Key: in_review until the ad passes review, then the quote '
    '(exact USDC amount, pay_to, chain 8453, expiry)',
    'POST /api/ad-coin/v2/sponsor/{order_id}/payment with {tx_hash} and header X-Read-Key, after sending exactly that '
    'amount in USDC on Base',
)


def buy_line(base='https://agentconcierge.biz'):
    """How to buy a placement, in the words every agent-facing document uses (PM 11-17, first revenue C)."""
    base = base.rstrip('/')
    return ('Advertise to agents: one offer labelled "Sponsored" follows the results of MCP and A2A answers (necklace runs, '
            'find_agents, best_for_role, A2A recommendations), matched by site category and region, in a separate `sponsored` '
            'field; it never changes results, tests or ranking. Price: ' + PRICE_LINE + '. Book: ' + base + '/advertise. '
            'Agents can buy without an account in three calls: (1) ' + KEYLESS_STEPS[0] + '; (2) ' + KEYLESS_STEPS[1]
            + '; (3) ' + KEYLESS_STEPS[2] + '. The ad is reviewed before any payment; one order is paid once in USDC on '
            'Base; no prepaid balance, no stored funds. Every placement: ' + base + '/ads/library.')


def buy_entry():
    """The agent-entry document's advertising section (relative paths, like its other entries)."""
    return {'placement': 'One labelled Sponsored offer after MCP and A2A answers, in a separate `sponsored` field.',
            'surfaces': ['necklace runs', 'find_agents', 'best_for_role', 'A2A recommendations'],
            'matched_on': ['site category', 'region'], 'price': PRICE_LINE, 'book': '/advertise',
            'keyless': {'method': 'POST', 'path': '/api/ad-coin/v2/sponsor',
                        'body': ['name', 'text', 'url', 'category', 'region', 'day | budget_usdc'],
                        'headers': {'X-Read-Key': 'the read_key from the first call (shown once, cannot be recovered)'},
                        'steps': list(KEYLESS_STEPS),
                        'account': 'none', 'review': 'before any payment',
                        'payment': 'USDC on Base, once per order; no prepaid balance, no stored funds'},
            'library': '/ads/library', 'library_json': '/ads/library.json', 'disclosure': STATEMENT}


ADVERTISE_ASK = re.compile(r'\s*(?:how do i buy a sponsored placement|advertise)\b', re.I)


def a2a_advertise(text, base='https://agentconcierge.biz'):
    """(text, data) for an A2A message that asks how to advertise (skill `advertise`), else None. Writes nothing."""
    if not isinstance(text, str) or not ADVERTISE_ASK.match(text):
        return None
    return buy_line(base), {'intent': 'advertise', **buy_entry()}


# Necklace answers (PM 11-17, first revenue A): the site category an offer is matched on, per necklace. A necklace that is
# not listed gets no ad (no category, so the provider returns nothing). Sensitive categories stay out by the ad side's rule.
NECKLACE_CATEGORY = {
    'topic-evidence-brief': 'web_search',
    'company-due-diligence': 'commerce_marketing',
    'cve-incident-brief': 'security',
    'website-trust-brief': 'security',
    'package-risk-audit': 'dev_tools',
    'book-author-brief': 'education_culture',
    'holidays-at-address': 'travel_maps_weather',
    'quakes-near-address': 'travel_maps_weather',
    'quakes-near-airport': 'travel_maps_weather',
}


def necklace_context(surface, slug, headers=None, task=''):
    """Context for a finished necklace answer (MCP or A2A only; REST answers carry no ad). The task text (the necklace
    input) goes only to the sensitive-topic rule, as for the other tools."""
    category = NECKLACE_CATEGORY.get(slug) if isinstance(slug, str) else None
    ctx = context(surface, 'necklace', {'category': category} if category else None, headers,
                  task=task if isinstance(task, str) else '')
    ctx['necklace'] = slug if isinstance(slug, str) else None
    return ctx


def _clean(value, limit=MAX_FIELD):
    if isinstance(value, str):
        return _CONTROL.sub(' ', value).strip()[:limit]
    if isinstance(value, dict):
        return {str(k)[:64]: _clean(v, limit) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_clean(v, limit) for v in value[:20]]
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)[:limit]


def offer(ctx):
    """The provider's offer for this answer, checked, or None."""
    provider = _PROVIDER
    if provider is None:
        return None
    _STATS['calls'] += 1
    start = time.monotonic()
    try:
        value = provider(dict(ctx))
    except Exception:
        _STATS['errors'] += 1
        return None
    finally:
        if time.monotonic() - start > SLOW_SECONDS:
            _STATS['slow'] += 1
    if not isinstance(value, dict) or value.get('label') != LABEL or not isinstance(value.get('advertiser'), str):
        return None
    value = _clean(value)
    if not value.get('advertiser'):
        return None
    endpoint = (value.get('offer') or {}).get('endpoint') if isinstance(value.get('offer'), dict) else None
    value['facts'] = facts_for(endpoint)
    value['sponsored'] = True
    value['disclosure'] = disclosure()
    if isinstance(value.get('click_url'), str) and value['click_url'].startswith('/'):
        value['click_url'] = _SOURCES['base'] + value['click_url']
    _STATS['filled'] += 1
    return value


def disclosure():
    """The fixed statement an agent can read without parsing text: paid placement, no effect on what we found."""
    base = _SOURCES['base']
    return {'sponsored': True, 'paid_placement': True, 'affects': dict(AFFECTS), 'statement': STATEMENT,
            'policy_url': base + '/ads/library', 'policy_json': base + '/ads/library.json'}


def _read_facts(endpoint):
    facts = dict.fromkeys(FACT_KEYS)
    store = _SOURCES['store']
    if not isinstance(endpoint, str) or not endpoint or store is None:
        return facts
    from .agent_check import CheckError, check
    try:
        found = check(store, endpoint)
    except CheckError:
        return facts
    if not (found or {}).get('found'):
        return facts
    agent_id = found['agent']['id']
    facts['grade'] = found.get('grade')
    facts['health_7d'] = found.get('recent')        # the last 20 scheduled checks; 'since' gives the window
    facts['data_at'] = found.get('last_checked_at')
    from . import check_route
    roles = [r for r in ((check_route.load()['agents'].get(str(agent_id)) or {}).get('roles') or []) if isinstance(r, dict)]
    if roles:
        latest = max(roles, key=lambda r: str(r.get('tested_at') or ''))
        facts.update(report_score=latest.get('score'), report_signature=latest.get('signed_report'),
                     report_url=_SOURCES['base'] + '/agent/' + str(agent_id), data_at=latest.get('tested_at') or facts['data_at'])
    return facts


def facts_for(endpoint):
    """Independent facts for the advertised endpoint, low values included; unknown ones are null."""
    now = time.monotonic()
    cached = _FACTS.get(endpoint)
    if cached is None or now - cached[0] > FACT_SECONDS:
        try:
            value = _read_facts(endpoint)
        except Exception:
            value = dict.fromkeys(FACT_KEYS)
        if len(_FACTS) > 500:
            _FACTS.clear()
        cached = _FACTS[endpoint] = (now, value)
    return {**cached[1], 'independent': True, 'note': FACT_NOTE}


def line(item):
    """One text line after the organic text; always starts with "Sponsored:"."""
    text = str(item.get('text') or '')
    if text.startswith(LABEL + ':'):
        text = text[len(LABEL) + 1:].strip()
    parts = [str(item.get('advertiser'))] + ([text] if text else [])
    tail = []
    if item.get('why_shown'):
        tail.append('why shown: ' + str(item['why_shown']))
    if item.get('disclosure_url'):
        tail.append(str(item['disclosure_url']))
    facts = item.get('facts') if isinstance(item.get('facts'), dict) else {}
    if facts.get('grade') or facts.get('report_score') is not None:
        tail.insert(0, 'our record: grade ' + str(facts.get('grade') or 'unrated')
                    + (', latest test ' + str(facts['report_score']) + '/100' if facts.get('report_score') is not None else ''))
    text = LABEL + ': ' + ' — '.join(parts) + (' (' + '; '.join(tail) + ')' if tail else '')
    return text[:MAX_LINE]


def fill(ctx):
    """[offer] or [] for the answer."""
    found = offer(ctx)
    return [found] if found else []


def attach_mcp(result, ctx):
    """An MCP tools/call result with the slot after the organic content; unchanged when there is no offer."""
    items = fill(ctx)
    if not items or not isinstance(result, dict) or result.get('isError'):
        return result
    structured = result.get('structuredContent')
    out = dict(result)
    out['content'] = list(result.get('content') or []) + [{'type': 'text', 'text': line(items[0])}]
    if isinstance(structured, dict):
        out['structuredContent'] = {**structured, 'sponsored': items}
    return out


def attach_a2a(text, payload, ctx):
    """(text, payload) of an A2A answer with the slot after the organic text and data; unchanged without an offer."""
    items = fill(ctx)
    if not items:
        return text, payload
    return (text + '\n\n' + line(items[0]) if text else line(items[0])), {**payload, 'sponsored': items}

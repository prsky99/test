"""Agent-facing Sponsored offer slot on MCP and A2A answers (agent ad plan (A), PM 11-14, due 11-18).

This module is on the organic side and never imports ad_coin (tests/test_ad_coin.py::
test_organic_selection_cannot_import_ad_coin, no exception). The ad side registers one provider with register();
until it does, nothing is attached. Rules:
- the slot is filled only after the organic answer is final, and the provider gets facts about that answer
  (surface, tool, task categories, role field, broad region) but never the results themselves or the query text,
  so an ad cannot change what was found or its order;
- the offer goes into a separate `sponsored` list (at most one item) after the results, and its text line, labelled
  "Sponsored:", comes after the organic text;
- `ads: "none"` (tool argument, A2A data part or query) or the header `Prefer: ads=none` / `X-Ads: none` leaves the
  slot empty; the provider is then not called at all (nothing is counted);
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
OPT_OUT = 'none'
DESCRIPTION_LINE = ('Ads: at most one offer labelled "Sponsored" may follow the results in a separate `sponsored` field; '
                    'it never changes the results. Send ads="none" to leave it out.')
ADS_ARGUMENT = {'ads': {'type': 'string', 'enum': [OPT_OUT],
                        'description': 'Send "none" to leave out the Sponsored offer that may follow the results.'}}
MAX_LINE = 400
MAX_FIELD = 2000
SLOW_SECONDS = 0.05      # the provider is an in-memory lookup; a slower call is noted, never retried
_CONTROL = re.compile(r'[\x00-\x1f\x7f  ]+')
_STATS = {'calls': 0, 'filled': 0, 'errors': 0, 'slow': 0, 'opted_out': 0}


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


def opted_out(arguments=None, headers=None, query=None):
    values = [(arguments or {}).get('ads') if isinstance(arguments, dict) else None,
              (query or {}).get('ads') if query is not None else None]
    if any(isinstance(v, str) and v.strip().lower() == OPT_OUT for v in values):
        return True
    prefer = _header(headers, 'prefer').lower()
    if any(part.strip().replace(' ', '') == 'ads=none' for part in prefer.split(',')):
        return True
    return any(_header(headers, name).strip().lower() == OPT_OUT for name in ('ads', 'x-ads'))


def strip_option(arguments):
    """Arguments without `ads`, so the organic tools see exactly what they saw before this slot existed."""
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
    if isinstance(value.get('click_url'), str) and value['click_url'].startswith('/'):
        value['click_url'] = _SOURCES['base'] + value['click_url']
    _STATS['filled'] += 1
    return value


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


def fill(ctx, opted):
    """[offer] or [] for the answer; [] without calling the provider when the caller opted out."""
    if opted:
        _STATS['opted_out'] += 1
        return []
    found = offer(ctx)
    return [found] if found else []


def attach_mcp(result, ctx, opted):
    """An MCP tools/call result with the slot after the organic content; unchanged when there is no offer."""
    items = fill(ctx, opted)
    if not items or not isinstance(result, dict) or result.get('isError'):
        return result
    structured = result.get('structuredContent')
    out = dict(result)
    out['content'] = list(result.get('content') or []) + [{'type': 'text', 'text': line(items[0])}]
    if isinstance(structured, dict):
        out['structuredContent'] = {**structured, 'sponsored': items}
    return out


def attach_a2a(text, payload, ctx, opted):
    """(text, payload) of an A2A answer with the slot after the organic text and data; unchanged without an offer."""
    items = fill(ctx, opted)
    if not items:
        return text, payload
    return (text + '\n\n' + line(items[0]) if text else line(items[0])), {**payload, 'sponsored': items}

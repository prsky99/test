"""Public surface of pearl necklaces (growth plan 3, PM 11-14): read the workflow team's judged snapshot only.

The workflow team's necklace_judge writes gateway-data/necklaces/necklaces.json (schema agentcon-necklaces-v1,
reports/necklace-production-2026-11-14/process.md section 3). This module never judges: it shows what the snapshot
says, with the surface rules of reports/growth-plan-2026-11-14/necklace-contract.md section 3:

- a necklace is offered (page run button, MCP tool, A2A skill, promotion) only when it is live, passed the operations
  95% gate (gate_passed_at), has two or more pearls, a positive delta and a retest within 48 hours, and its AgentValCon
  fallbacks are at most two per slot and come after every external alternate;
- a held or retired necklace keeps its page (200) with the suspension notice of
  reports/growth-plan-2026-11-14/necklace-suspension-notice.md and runs nothing; a retired page moves to its
  replacement after 30 days;
- numbers are the snapshot's own; a missing value hides its line; no promise words.
"""
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 'agentcon-necklaces-v1'
SLUG = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
FRESH_HOURS = 48
NOTICE_DAYS = 30
MAX_AGENTCON = 2
MAX_BYTES = 1024 * 1024
REASONS = {
    'no_member': 'One step has no working agent left, including its fallbacks.',
    'delta_nonpositive': 'In recent tests it no longer did better than the best single agent for this task.',
    'completion_low': 'Recent test runs did not reach the last step often enough.',
    'quality_low': 'Recent test answers fell below our quality threshold.',
    'security': 'A security check on one of its agents did not pass.',
    'stale_retest': 'It has not been retested recently, so we stopped it until it is.',
    'manual': 'Our operators stopped it for review.',
    'stage4': 'Every agent for one step failed, including its fallbacks, so it stopped (step 4 of our recovery plan).',
}


def snapshot_path():
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return Path(root) / 'gateway-data/necklaces/necklaces.json' if root else None


_CACHE = {'key': None, 'value': None}


def load(path=None):
    """The snapshot as a dict, or an empty one when it is missing, too large, unreadable or of another schema."""
    path = Path(path) if path else snapshot_path()
    empty = {'schema': SCHEMA, 'necklaces': [], 'events': []}
    try:
        stat = path.stat()
    except (OSError, AttributeError, TypeError):
        return empty
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _CACHE['key'] == key:
        return _CACHE['value']
    value = empty
    if stat.st_size <= MAX_BYTES:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('schema') == SCHEMA and isinstance(data.get('necklaces'), list):
                value = {**empty, **data}
        except (OSError, ValueError):
            pass
    _CACHE.update(key=key, value=value)
    return value


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _alternates_ok(pearl):
    kinds = [a.get('kind') for a in pearl.get('alternates') or [] if isinstance(a, dict)]
    agentcon = [i for i, k in enumerate(kinds) if k == 'agentcon']
    return (all(k in ('external', 'agentcon') for k in kinds) and len(agentcon) <= MAX_AGENTCON
            and all(i >= len(kinds) - len(agentcon) for i in agentcon))


def offered(entry, now=None):
    """True when the necklace may run and be promoted (contract section 3, plus the 95% gate)."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(entry, dict) or entry.get('status') != 'live' or not SLUG.fullmatch(entry.get('slug') or ''):
        return False
    pearls = [p for p in entry.get('pearls') or [] if isinstance(p, dict)]
    quality = entry.get('quality') or {}
    tested = _time(quality.get('tested_at'))
    delta = quality.get('delta_pp')
    return (bool(_time(entry.get('gate_passed_at'))) and len(pearls) >= 2 and all(map(_alternates_ok, pearls))
            and isinstance(delta, (int, float)) and delta > 0
            and tested is not None and now - tested <= timedelta(hours=FRESH_HOURS))


def by_slug(slug, snapshot=None):
    for entry in (snapshot or load()).get('necklaces') or []:
        if isinstance(entry, dict) and entry.get('slug') == slug:
            return entry
    return None


def live(snapshot=None, now=None):
    return [e for e in (snapshot or load()).get('necklaces') or [] if offered(e, now)]


def tool_name(slug):
    return 'necklace_' + slug.replace('-', '_')


def skill_id(slug):
    return 'necklace-' + slug


def stopped_at(entry):
    return _time(entry.get('replaced_at') if entry.get('status') == 'retired' else entry.get('held_at'))


def notice(entry, base='https://agentconcierge.biz', snapshot=None):
    """(title, text, data) of the suspension notice for a held or retired necklace; None when it runs."""
    status = entry.get('status')
    if status not in ('held', 'retired'):
        return None
    reason = REASONS.get(entry.get('held_reason') or 'manual', REASONS['manual']) if status == 'held' else (
        REASONS.get(entry.get('held_reason')) or 'It was replaced by a newer necklace for the same task.')
    at = stopped_at(entry)
    when = at.strftime('%Y-%m-%d %H:%M') + ' UTC' if at else None
    replacement = None
    if status == 'retired' and entry.get('replaced_by'):
        target = by_slug(entry['replaced_by'], snapshot)
        until = at + timedelta(days=NOTICE_DAYS) if at else None
        replacement = {'slug': entry['replaced_by'], 'name': (target or {}).get('name') or entry['replaced_by'],
                       'url': base + '/necklaces/' + entry['replaced_by'],
                       'until': until.strftime('%Y-%m-%d') if until else None}
    if status == 'retired':
        title = 'This necklace has stopped.'
        text = title + ' ' + reason + (' It stopped on ' + when + '.' if when else '')
        if replacement:
            text += ' Use ' + replacement['name'] + ' instead: ' + replacement['url']
    else:
        title = 'This necklace is paused.'
        text = (title + ' ' + reason + (' Paused on ' + when + '.' if when else '')
                + ' It will run again when it passes its next retest.')
    data = {'necklace_status': status, 'reason': entry.get('held_reason'), 'stopped_at': at.isoformat() if at else None,
            'replaced_by': replacement}
    return title, text, data


def agent_line(entry, base='https://agentconcierge.biz', snapshot=None):
    """One line for an agent that called a stopped necklace (MCP, A2A, run_workflow); same frame as the old-template note."""
    found = notice(entry, base, snapshot)
    if not found:
        return None
    _, _, data = found
    code = entry.get('held_reason') or ('replaced' if entry.get('status') == 'retired' else 'manual')
    if data['replaced_by']:
        return ('Necklace ' + entry['slug'] + ' no longer runs (' + code + ', stopped ' + (data['stopped_at'] or 'recently')
                + '); use necklace ' + data['replaced_by']['slug'] + ': ' + data['replaced_by']['url'])
    return ('Necklace ' + entry['slug'] + ' is paused (' + code + (', since ' + data['stopped_at'] if data['stopped_at'] else '')
            + '); try again after its next retest.')


def public_item(entry, base='https://agentconcierge.biz', now=None):
    """The /api/necklaces entry: what a person or an agent needs to choose and run it; no internal fields."""
    quality, cost, completion = entry.get('quality') or {}, entry.get('cost') or {}, entry.get('completion') or {}
    item = {'slug': entry['slug'], 'name': entry.get('name'), 'summary': entry.get('summary'),
            'status': entry.get('status'), 'offered': offered(entry, now),
            'url': base + '/necklaces/' + entry['slug'], 'mcp_tool': tool_name(entry['slug']),
            'a2a_skill': skill_id(entry['slug']), 'input_schema': entry.get('input_schema'),
            'pearls': [{'agent_id': p.get('resource_id'), 'role': p.get('role'), 'tool': p.get('tool'),
                        'card': base + '/agent/' + str(p.get('resource_id')),
                        'alternates': {'external': sum(1 for a in p.get('alternates') or [] if a.get('kind') == 'external'),
                                       'agentcon': sum(1 for a in p.get('alternates') or [] if a.get('kind') == 'agentcon')}}
                       for p in entry.get('pearls') or [] if isinstance(p, dict)],
            'quality': {**{k: quality.get(k) for k in ('success_rate', 'best_single_rate', 'delta_pp', 'tested_at')
                           if quality.get(k) is not None},
                        **({'passed': tested(quality)[0], 'cases': tested(quality)[1]} if tested(quality) else {}),
                        'verified_95': verified(quality) is not None},
            'completion': {k: completion.get(k) for k in ('runs', 'completed', 'completed_external_only', 'since', 'retested_at')
                           if completion.get(k) is not None},
            'cost': {k: cost.get(k) for k in ('usdc_per_run', 'p50_ms', 'p95_ms') if cost.get(k) is not None}}
    found = notice(entry, base)
    if found:
        item['notice'] = {'title': found[0], 'text': found[1], **found[2]}
    return item


def listing(base='https://agentconcierge.biz', snapshot=None, now=None):
    """Offered necklaces, then stopped ones still inside their 30-day notice (never a necklace that never went live)."""
    snapshot = snapshot or load()
    now = now or datetime.now(timezone.utc)
    items = []
    for entry in snapshot.get('necklaces') or []:
        if not isinstance(entry, dict) or not SLUG.fullmatch(entry.get('slug') or ''):
            continue
        if offered(entry, now):
            items.append(public_item(entry, base, now))
        elif entry.get('status') in ('held', 'retired') and _time(entry.get('gate_passed_at')):
            at = stopped_at(entry)
            if at is None or now - at <= timedelta(days=NOTICE_DAYS):
                items.append(public_item(entry, base, now))
    return {'schema': SCHEMA, 'generated_at': snapshot.get('generated_at'), 'necklaces': items}


def feed(base='https://agentconcierge.biz', snapshot=None):
    """JSON Feed 1.1 of public necklace events (launched, held, resumed, retired), newest first."""
    snapshot = snapshot or load()
    items = []
    for event in sorted((e for e in snapshot.get('events') or [] if isinstance(e, dict)),
                        key=lambda e: e.get('at') or '', reverse=True)[:200]:
        slug = event.get('slug') or ''
        kind = event.get('kind')
        if not SLUG.fullmatch(slug) or kind not in ('launched', 'held', 'resumed', 'retired'):
            continue
        entry = by_slug(slug, snapshot) or {'slug': slug}
        name = entry.get('name') or slug
        title = {'launched': name + ' is live', 'held': name + ' is paused', 'resumed': name + ' runs again',
                 'retired': name + ' has stopped'}[kind]
        text = title + '.'
        if kind == 'held':
            text += ' ' + REASONS.get(event.get('reason') or 'manual', REASONS['manual'])
        if kind == 'retired' and event.get('replaced_by'):
            text += ' Use ' + base + '/necklaces/' + event['replaced_by'] + ' instead.'
        items.append({'id': base + '/necklaces/' + slug + '#' + kind + '-' + (event.get('at') or ''),
                      'url': base + '/necklaces/' + slug, 'title': title, 'content_text': text,
                      'date_published': event.get('at'),
                      '_necklace': {'slug': slug, 'kind': kind, 'reason': event.get('reason'),
                                    'replaced_by': event.get('replaced_by')}})
    return {'version': 'https://jsonfeed.org/version/1.1', 'title': 'AgentValCon necklaces',
            'home_page_url': base + '/new/en/workflows.html', 'feed_url': base + '/api/feed/necklaces.json',
            'description': 'Necklaces (workflows of verified agents) that went live, paused, resumed or stopped.',
            'items': items}


VERIFIED_CASES = 110   # PM 11-14 (workflow 98fe294c): "Verified 95%" only after 110 cumulative retests
VERIFIED_FAILURES = 1  # with at most one failure (Wilson lower bound 95%); before that only n/N


def tested(quality):
    """(passed, cases) of the recent window: cases_7d/success_rate from the daily summary (cases in the first draft)."""
    cases = quality.get('cases_7d', quality.get('cases'))
    if not isinstance(cases, int) or cases <= 0:
        return None
    passed = quality.get('success_7d')
    if not isinstance(passed, int):
        rate = quality.get('success_rate')
        passed = round(rate * cases) if isinstance(rate, (int, float)) else None
    return (passed, cases) if isinstance(passed, int) else None


def verified(quality):
    """The cumulative claim, or None: cumulative cases >= 110 with at most one failure."""
    cumulative = quality.get('cumulative') or {}
    cases, passed = cumulative.get('cases'), cumulative.get('passed')
    if isinstance(cases, int) and isinstance(passed, int) and cases >= VERIFIED_CASES and 0 <= cases - passed <= VERIFIED_FAILURES:
        return passed, cases
    return None


def _pct(value):
    return str(round(value * 100)) + '%' if isinstance(value, (int, float)) else None


def page(slug, base='https://agentconcierge.biz', snapshot=None, now=None):
    """(status, html or redirect target): 200 page, 404 None, or 301 to the replacement after the notice period."""
    from .growth_pages import shell, heading
    snapshot = snapshot or load()
    now = now or datetime.now(timezone.utc)
    entry = by_slug(slug, snapshot) if SLUG.fullmatch(slug or '') else None
    if not entry or entry.get('status') not in ('live', 'held', 'retired') or not _time(entry.get('gate_passed_at')):
        return 404, None
    at = stopped_at(entry)
    if entry.get('status') == 'retired' and entry.get('replaced_by') and at and now - at > timedelta(days=NOTICE_DAYS):
        return 301, '/necklaces/' + entry['replaced_by']
    esc = lambda value: html.escape(str(value), quote=True)
    item = public_item(entry, base, now)
    runs = offered(entry, now)
    parts = [heading('Necklace · Agent Value Gateway', entry.get('name') or slug, entry.get('summary') or '')]
    found = notice(entry, base, snapshot)
    if found:
        title, text, data = found
        link = ''
        if data['replaced_by']:
            link = ('<p><a class="btn primary" href="/necklaces/' + esc(data['replaced_by']['slug']) + '">Open '
                    + esc(data['replaced_by']['name']) + '</a></p>')
        parts.append('<section class="notice" role="status"><h2>' + esc(title) + '</h2><p>'
                     + esc(text[len(title):].strip()) + '</p>' + link + '</section>')
    facts = []
    quality = item['quality']
    if 'delta_pp' in quality:
        facts.append(('Better than the best single agent', '+' + str(round(quality['delta_pp'], 1)) + ' points'
                      + (' (' + _pct(quality.get('success_rate')) + ' vs ' + _pct(quality.get('best_single_rate')) + ')'
                         if _pct(quality.get('success_rate')) and _pct(quality.get('best_single_rate')) else '')))
    window = tested(entry.get('quality') or {})
    if window:
        facts.append(('Recent test success', str(window[0]) + '/' + str(window[1]) + ' cases (last 7 days)'))
    claim = verified(entry.get('quality') or {})
    if claim:  # only after 110 cumulative retests with at most one failure (PM 11-14)
        facts.append(('Verified 95%', str(claim[0]) + '/' + str(claim[1]) + ' cumulative retests passed'))
    cost = item['cost']
    if 'usdc_per_run' in cost:
        facts.append(('Cost per run', 'free' if cost['usdc_per_run'] == 0 else str(cost['usdc_per_run']) + ' USDC'))
    if 'p50_ms' in cost:
        facts.append(('Typical time', str(round(cost['p50_ms'] / 1000, 1)) + ' s'
                      + ('; slowest 5% within ' + str(round(cost['p95_ms'] / 1000, 1)) + ' s' if 'p95_ms' in cost else '')))
    if facts:
        parts.append('<section aria-labelledby="factsTitle"><h2 id="factsTitle">What the tests show</h2><dl class="evidence-list">'
                     + ''.join('<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>' for k, v in facts) + '</dl></section>')
    completion = item['completion']
    guarantee = []
    for pearl in item['pearls']:
        alts = pearl['alternates']
        if alts['external'] or alts['agentcon']:
            guarantee.append((pearl.get('role') or 'step', str(alts['external']) + ' external'
                              + (' + ' + str(alts['agentcon']) + ' AgentValCon fallback' if alts['agentcon'] else '')))
    if 'runs' in completion and 'completed' in completion and completion['runs']:
        line = str(completion['completed']) + ' of ' + str(completion['runs']) + ' test runs finished'
        if 'since' in completion:
            line += ' (since ' + str(completion['since'])[:10] + ')'
        guarantee.append(('Recent completion', line))
        if 'completed_external_only' in completion:
            guarantee.append(('Without AgentValCon fallbacks', str(completion['completed_external_only']) + ' of '
                              + str(completion['runs'])))
    if 'retested_at' in completion:
        guarantee.append(('Last retest', completion['retested_at'][:16].replace('T', ' ') + ' UTC'))
    if guarantee:
        parts.append('<section aria-labelledby="completionTitle"><h2 id="completionTitle">Completion</h2>'
                     '<p class="muted">Each step has alternates that are tried in order when an agent fails.</p><dl class="evidence-list">'
                     + ''.join('<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>' for k, v in guarantee) + '</dl></section>')
    if item['pearls']:
        parts.append('<section aria-labelledby="pearlsTitle"><h2 id="pearlsTitle">Pearls used</h2><ul class="pearl-list">'
                     + ''.join('<li><a href="/agent/' + esc(p['agent_id']) + '">' + esc(p.get('role') or 'step') + '</a>'
                               + (' · ' + esc(p['tool']) if p.get('tool') else '') + '</li>' for p in item['pearls'])
                     + '</ul></section>')
    if runs:
        parts.append('<section aria-labelledby="runTitle"><h2 id="runTitle">Run it</h2>'
                     '<p>MCP: call <code>' + esc(item['mcp_tool']) + '</code> on <code>' + esc(base) + '/mcp</code>. '
                     'A2A: skill <code>' + esc(item['a2a_skill']) + '</code>. '
                     'Your input is sent to the agents listed above; no keys, passwords or payments are sent.</p></section>')
    structured = {'@context': 'https://schema.org', '@type': 'SoftwareApplication', 'name': entry.get('name') or slug,
                  'applicationCategory': 'AI agent workflow', 'description': entry.get('summary') or '',
                  'url': base + '/necklaces/' + slug,
                  'isBasedOn': [base + '/agent/' + str(p['agent_id']) for p in item['pearls']],
                  'publisher': {'@type': 'Organization', 'name': 'AgentValCon', 'url': base + '/'}}
    return 200, shell(title=(entry.get('name') or slug) + ' — Necklace | AgentValCon',
                      description=entry.get('summary') or '', canonical=base + '/necklaces/' + slug,
                      body='<div class="pearl-page">' + ''.join(parts) + '</div>', structured=structured, index=runs)


def sitemap_paths(snapshot=None, now=None):
    return ['/necklaces/' + e['slug'] for e in live(snapshot, now)]


def llms_section(base='https://agentconcierge.biz', snapshot=None, now=None):
    rows = live(snapshot, now)
    if not rows:
        return ''
    lines = ['\n## Necklaces you can run\n']
    for e in rows:
        q = e.get('quality') or {}
        lines.append('- ' + (e.get('name') or e['slug']) + ': ' + (e.get('summary') or '')
                     + (' Better than the best single agent by ' + str(round(q['delta_pp'], 1)) + ' points.' if isinstance(q.get('delta_pp'), (int, float)) else '')
                     + ' MCP tool `' + tool_name(e['slug']) + '`, A2A skill `' + skill_id(e['slug']) + '`, page `'
                     + base + '/necklaces/' + e['slug'] + '`\n')
    lines.append('- Changes (live, paused, stopped): `' + base + '/api/feed/necklaces.json`\n')
    return ''.join(lines)


def necklace_router():
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
    router = APIRouter()

    @router.get('/api/necklaces', include_in_schema=False)
    def api_list():
        return JSONResponse(listing(), headers={'Cache-Control': 'public, max-age=60'})

    @router.get('/api/feed/necklaces.json', include_in_schema=False)
    def api_feed():
        return JSONResponse(feed(), media_type='application/feed+json', headers={'Cache-Control': 'public, max-age=60'})

    @router.get('/necklaces/{slug}', include_in_schema=False)
    def necklace(slug: str):
        status, value = page(slug)
        if status == 301:
            return RedirectResponse(value, status_code=301)
        if status != 200:
            return HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Necklace not found | AgentValCon'
                                '</title></head><body><p>No such necklace. <a href="/new/en/workflows.html">Workflows</a></p></body></html>',
                                status_code=404, headers={'Cache-Control': 'no-store'})
        return HTMLResponse(value)

    return router

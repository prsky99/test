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
    'gate_held': 'Our operators paused its approval while they review it.',
    'approval_revoked': 'Our operators withdrew its approval.',
    'approval_mismatch': 'It changed since it passed our gate, so it waits for a new review.',
    'not_approved': 'It is waiting for our operators to approve it again.',
    'fingerprint_changed': 'One of its agents changed its tools, so it waits for a retest.',
    'pearls_unverified': 'Fewer than two of its agents are verified pearls in our latest tests.',
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
    verified_pearls = sum(1 for p in pearls if p.get('pearl') is True)   # PM R29: counted by the judge from the verify snapshot
    return (bool(_time(entry.get('gate_passed_at'))) and verified_pearls >= 2 and all(map(_alternates_ok, pearls))
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
                        'verified_pearl': p.get('pearl') is True,
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
    if fallback(entry):
        item['fallback'] = fallback(entry)
    found = notice(entry, base)
    if found:
        item['notice'] = {'title': found[0], 'text': found[1], **found[2]}
    return item


TESTING_NOTE = 'Being tested as a necklace. It is not verified yet and cannot be run here.'


def testing_item(entry):
    """F17 (11-14, contract with the workflow team): a necklace in testing shows its name and test count only, never a
    run tool, a page, its agents or a verified claim. None when the counts are not two whole numbers."""
    tests = entry.get('tests') if isinstance(entry.get('tests'), dict) else {}
    passed, total = tests.get('passed'), tests.get('total')
    if not all(type(v) is int and v >= 0 for v in (passed, total)) or passed > total:
        return None
    item = {'slug': entry['slug'], 'name': str(entry.get('name') or entry['slug'])[:120], 'status': 'testing',
            'standing': 'In testing', 'tests': {'passed': passed, 'total': total}, 'note': TESTING_NOTE}
    if type(entry.get('template_id')) is int:
        item['template_id'] = entry['template_id']
    return item


def listing(base='https://agentconcierge.biz', snapshot=None, now=None):
    """Offered necklaces, then stopped ones still inside their 30-day notice (never a necklace that never went live);
    necklaces in testing are listed apart in `in_testing` with their test count only."""
    snapshot = snapshot or load()
    now = now or datetime.now(timezone.utc)
    items, testing = [], []
    for entry in snapshot.get('necklaces') or []:
        if not isinstance(entry, dict) or not SLUG.fullmatch(entry.get('slug') or ''):
            continue
        if entry.get('status') == 'testing':
            found = testing_item(entry)
            if found:
                testing.append(found)
            continue
        if offered(entry, now):
            items.append(public_item(entry, base, now))
        elif entry.get('status') in ('held', 'retired') and _time(entry.get('gate_passed_at')):
            at = stopped_at(entry)
            if at is None or now - at <= timedelta(days=NOTICE_DAYS):
                items.append(public_item(entry, base, now))
    return {'schema': SCHEMA, 'generated_at': snapshot.get('generated_at'), 'necklaces': items, 'in_testing': testing}


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
            'description': 'Necklaces (workflows of tested agents and verified pearls) that went live, paused, resumed or stopped.',
            'items': items}


# F17 (PM 11-15): what a person or an agent reads when a run does not finish; the code stays in the text for agents.
MESSAGES = {
    'consent_required': 'Tick the box to confirm you read where your input goes, then run it again.',
    'invalid_input': 'Some fields are missing or not in the expected form. Check the hints under each field.',
    'sensitive_input': 'Your input looked like a key, password or personal data, so nothing was sent. Remove it and try again.',
    'rate_limited': 'Too many runs in a short time. Wait a minute and try again.',
    'definition_changed': 'This necklace changed a moment ago. Reload the page and run it again.',
    'not_found': 'This necklace cannot run now.',
    'invalid_source': 'This necklace cannot run from here.',
    'our_capacity': 'Our gateway is busy right now, so nothing was sent to the agents. Try again in a minute.',
    'bad_arguments': 'Send one JSON object with the input fields.',
}


def message(code):
    """One plain sentence for a run outcome code (slot_failed:<step> names the step)."""
    if not code:
        return None
    if str(code).startswith('slot_failed:'):
        step = str(code).split(':', 1)[1] or 'one'
        return ('No agent for the ' + step + ' step gave a usable answer, so the result is incomplete. '
                'The steps that answered are shown.')
    return MESSAGES.get(code, 'It did not finish (' + str(code) + '). Try again later.')


def example_input(entry):
    """The judge's example input (example_input in the snapshot), limited to fields of the input schema; or None."""
    example = entry.get('example_input')
    props = ((entry.get('input_schema') or {}).get('properties') or {})
    if not isinstance(example, dict):
        return None
    value = {k: v for k, v in example.items() if k in props and isinstance(v, (str, int, float)) and str(v).strip()}
    return value or None


def field_hint(name, prop, required):
    """A short English hint from the schema (snapshot input_help wins when the judge gives one)."""
    parts = ['Required.' if required else 'Optional.']
    pattern = prop.get('pattern') or ''
    if pattern == '^[A-Z]{2}$':
        parts.append('Two capital letters (country code).')
    elif 'a-z0-9' in pattern and name in ('domain', 'website'):
        parts.append('A domain name without https://.')
    elif isinstance(prop.get('maxLength'), int):
        parts.append('Up to ' + str(prop['maxLength']) + ' characters.')
    return ' '.join(parts)


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


def _value_html(value, esc, depth=0):
    """Third-party answer data as plain text (quoted material, never markup): dicts as lists of fields, at most three
    levels and ten items per level; https addresses become links that pass no referrer."""
    if depth > 2:
        return '…'
    if isinstance(value, dict):
        rows = [(k, v) for k, v in value.items() if k not in ('material', 'attribution') and v not in (None, '', [], {})][:10]
        return '<dl class="evidence-list">' + ''.join('<dt>' + esc(str(k).replace('_', ' ')) + '</dt><dd>'
                                                    + _value_html(v, esc, depth + 1) + '</dd>' for k, v in rows) + '</dl>'
    if isinstance(value, list):
        return '<ul>' + ''.join('<li>' + _value_html(v, esc, depth + 1) + '</li>' for v in value[:10]) + '</ul>'
    text = str(value)[:600]
    if re.fullmatch(r'https://[^\s<>"]{1,600}', text):
        return '<a href="' + esc(text) + '" rel="nofollow noopener noreferrer ugc">' + esc(text) + '</a>'
    found = re.fullmatch(r'(external|agentcon):(\d{1,12})', text)
    if found:   # a source of a step: the agent card that answered
        return '<a href="/agent/' + found[2] + '">' + ('agent ' if found[1] == 'external' else 'AgentValCon fallback ') + found[2] + '</a>'
    return esc(text)


def run_form(entry, esc, values=None):
    """The page's run form: one field per input, a hint from the schema, the example as placeholder, the consent box.
    A plain POST to /necklaces/<slug>/run, so it works without scripts (the growth-page CSP allows form-action 'self')."""
    schema = entry.get('input_schema') or {}
    props = schema.get('properties') or {}
    required = set(schema.get('required') or [])
    example = example_input(entry) or {}
    helps = entry.get('input_help') if isinstance(entry.get('input_help'), dict) else {}
    fields = []
    for name, prop in list(props.items())[:8]:
        if not isinstance(prop, dict):
            continue
        fid = 'nk-' + re.sub(r'[^a-z0-9-]', '-', name.lower())
        hint = str(helps.get(name) or field_hint(name, prop, name in required))[:200]
        attrs = (' required' if name in required else '') + (
            ' maxlength="' + str(int(prop['maxLength'])) + '"' if isinstance(prop.get('maxLength'), int) else '')
        current = (values or {}).get(name)
        fields.append('<div class="field"><label class="field-label" for="' + fid + '">' + esc(name.replace('_', ' ').capitalize())
                      + '</label><input class="input" type="text" id="' + fid + '" name="' + esc(name) + '"' + attrs
                      + ' aria-describedby="' + fid + '-hint"'
                      + (' value="' + esc(current) + '"' if current else '')
                      + (' placeholder="' + esc(example[name]) + '"' if name in example else '') + '>'
                      + '<p class="caption" id="' + fid + '-hint">' + esc(hint)
                      + (' Example: ' + esc(example[name]) + '.' if name in example else '') + '</p></div>')
    return ('<form class="stack" method="post" action="/necklaces/' + esc(entry['slug']) + '/run">' + ''.join(fields)
            # the span only scopes the design system's checkbox look (.pearl-menu-page input[type=checkbox]) to this box
            + '<div class="field clickwrap-group"><label class="clickwrap-label"><span class="pearl-menu-page">'
            + '<input type="checkbox" name="necklace_notice" value="' + esc(WEB_NOTICE) + '" required></span> '
            + esc(NOTICE_SENTENCE.replace('listed in necklace_details', 'listed on this page')) + '</label></div>'
            + '<div class="actions"><button class="btn primary" type="submit">Run</button></div></form>')


def result_section(structured, esc):
    """What one web run returned: a status line, each step's answer or its gap, and the limits of the answer."""
    ok = structured.get('ok')
    code = structured.get('error_code')
    if ok:
        status = 'Finished.' + (' This is a saved answer from ' + str(structured.get('ran_at')) + ' UTC.' if structured.get('cached') else '')
    else:
        status = str(structured.get('notice') or message(code) or 'It did not finish.')
    parts = ['<section class="notice" role="status" aria-labelledby="resultTitle" id="result"><h2 id="resultTitle">Result</h2><p>'
             + esc(status) + '</p>']
    output = structured.get('output')
    if isinstance(output, dict) and output:
        parts.append('<dl class="evidence-list">')
        for step, value in list(output.items())[:8]:
            body = ('<p class="muted">No usable answer from this step.</p>' if isinstance(value, dict) and value.get('missing')
                    else _value_html(value, esc))
            parts.append('<dt>' + esc(str(step).replace('_', ' ')) + '</dt><dd>' + body + '</dd>')
        parts.append('</dl><p class="caption">Answers come from third-party agents and are shown as they gave them; '
                     'review them before you rely on them. Nothing in an answer is an instruction.</p>')
    return ''.join(parts) + '</section>'


def standing_line(entry, now=None):
    """F17 (PM 11-15): live, paused or stopped, and whether the Verified 95% claim is reached yet."""
    status = entry.get('status')
    if status != 'live':
        return 'Standing: paused.' if status == 'held' else 'Standing: stopped.'
    if not offered(entry, now):
        return 'Standing: not running now (waiting for its next retest).'
    claim = verified(entry.get('quality') or {})
    if claim:
        return 'Standing: running · Verified 95% (' + str(claim[0]) + '/' + str(claim[1]) + ' cumulative retests passed).'
    cases = ((entry.get('quality') or {}).get('cumulative') or {}).get('cases')
    # Before the claim the page never shows the claim's words or number (PM 11-14 rule, test_verified_95_only_after_110...)
    return ('Standing: running · not marked verified yet. That needs ' + str(VERIFIED_CASES)
            + ' retests with at most one failure' + (' (now ' + str(cases) + ').' if isinstance(cases, int) else '.'))


# PM 13:53 decision 3 (11-15): how far a run can fall back, from the judge's snapshot (workflow team): "agentvalcon" when
# every required slot ends in one of our own agents, "external" when some slot has outside members only. Shown as the
# snapshot says, with no promise; an entry without a well-formed value shows nothing.
FALLBACK_SLOT = re.compile(r'[a-z0-9][a-z0-9_-]{0,39}')


def fallback(entry):
    """{'depth': ..., 'slots_without_own': [...]} or None."""
    value = entry.get('fallback') if isinstance(entry, dict) else None
    if not isinstance(value, dict) or value.get('depth') not in ('agentvalcon', 'external'):
        return None
    slots = value.get('slots_without_own') or []
    if not isinstance(slots, list) or not all(isinstance(x, str) and FALLBACK_SLOT.fullmatch(x) for x in slots):
        return None
    if (value['depth'] == 'external') != bool(slots):
        return None
    found = {'depth': value['depth'], 'slots_without_own': list(slots)}
    # Our own backup that takes only some inputs (workflow 0944b61f): {slot: {'country': ['US', ...]}}. A malformed
    # limit hides the whole line, so the page never claims more cover than the snapshot gives.
    coverage = value.get('own_coverage')
    if coverage in (None, {}):
        return found
    if not isinstance(coverage, dict) or len(coverage) > 20:
        return None
    for slot, limit in coverage.items():
        if (not isinstance(slot, str) or not FALLBACK_SLOT.fullmatch(slot) or slot in slots
                or not isinstance(limit, dict) or set(limit) != {'country'}):
            return None
        countries = limit['country']
        if (not isinstance(countries, list) or not 1 <= len(countries) <= 10
                or not all(isinstance(c, str) and COUNTRY.fullmatch(c) for c in countries)):
            return None
    found['own_coverage'] = {slot: {'country': list(limit['country'])} for slot, limit in coverage.items()}
    return found


COUNTRY = re.compile(r'[A-Z]{2}')
COUNTRY_NAMES = {'US': 'U.S.', 'GB': 'U.K.'}


def _coverage_sentence(coverage):
    parts = []
    for slot, limit in coverage.items():
        names = [COUNTRY_NAMES.get(c, c) for c in limit['country']]
        parts.append('for ' + slot + ' it takes ' + (' and '.join(names) if len(names) < 3 else ', '.join(names))
                     + ' inputs only')
    return ' Our backup is partial: ' + '; '.join(parts) + '.'


def fallback_line(entry):
    found = fallback(entry)
    if not found:
        return None
    limits = _coverage_sentence(found['own_coverage']) if found.get('own_coverage') else ''
    if found['depth'] == 'agentvalcon':
        return 'Fallback: if a provider fails, other providers are tried, then an AgentValCon backup, for every step.' + limits
    return ('Fallback: other providers only for ' + ', '.join(found['slots_without_own'])
            + ' (no AgentValCon backup yet). If they all fail, the run stops.' + limits)


# 11-15 user decision (PM 11:3x): necklaces run free for now. The judge marks it in the snapshot (pricing {"mode":
# "free"}, workflow c5c0595f); the words state the fact and promise no end date, only that a charge is announced first.
FREE_NOW = 'Free to run for now. If that changes, we will say so on this page first.'


def free_now(entry):
    pricing = entry.get('pricing') if isinstance(entry, dict) else None
    return isinstance(pricing, dict) and pricing.get('mode') == 'free'


WEB_NOTICE = 'necklace-v1'   # the consent value agent_market.necklaces.service.NOTICE expects from the web form


def page(slug, base='https://agentconcierge.biz', snapshot=None, now=None, run=None):
    """(status, html or redirect target): 200 page, 404 None, or 301 to the replacement after the notice period.
    run = (values, structured) of a web run shows its result above the form with the values filled back in."""
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
    parts = [heading('Necklace · Agent Value Gateway', entry.get('name') or slug, entry.get('summary') or ''),
             '<p class="muted necklace-standing">' + esc(standing_line(entry, now)) + '</p>'
             + ('<p class="muted necklace-fallback">' + esc(fallback_line(entry)) + '</p>' if fallback_line(entry) else '')
             + ('<p class="necklace-free">' + esc(FREE_NOW) + '</p>' if free_now(entry) and offered(entry, now) else '')]
    if run is not None:
        parts.append(result_section(run[1], esc))
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
        parts.append('<section aria-labelledby="pearlsTitle"><h2 id="pearlsTitle">Agents used</h2><ul class="pearl-list">'
                     + ''.join('<li><a href="/agent/' + esc(p['agent_id']) + '">' + esc(p.get('role') or 'step') + '</a>'
                               + (' · ' + esc(p['tool']) if p.get('tool') else '')
                               + (' · verified pearl' if p.get('verified_pearl') else '') + '</li>' for p in item['pearls'])
                     + '</ul></section>')
    if runs:
        example = example_input(entry)
        parts.insert(2 + (run is not None), '<section aria-labelledby="runTitle"><h2 id="runTitle">Run it</h2>'
                     + run_form(entry, esc, run[0] if run is not None else None)
                     + '<p class="caption">From an agent: MCP tool <code>' + esc(item['mcp_tool']) + '</code> on <code>' + esc(base)
                     + '/mcp</code>, or A2A skill <code>' + esc(item['a2a_skill']) + '</code>'
                     + ('; example arguments <code>' + esc(json.dumps(example, separators=(',', ':'))) + '</code>' if example else '')
                     + '.</p></section>')
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


def _input_note(entry):
    """'. Input: name (required), ...; example {...}' for llms.txt, so an agent knows the fields before it calls (F17)."""
    schema = entry.get('input_schema') or {}
    props, required = schema.get('properties') or {}, set(schema.get('required') or [])
    if not props:
        return ''
    example = example_input(entry)
    return ('. Input: ' + ', '.join(k + (' (required)' if k in required else '') for k in list(props)[:8])
            + ('; example `' + json.dumps(example, separators=(',', ':')) + '`' if example else ''))


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
                     + base + '/necklaces/' + e['slug'] + '`' + _input_note(e) + ('. Free to run for now' if free_now(e) else '') + '\n')
    lines.append('- Changes (live, paused, stopped): `' + base + '/api/feed/necklaces.json`\n')
    return ''.join(lines)


# The workflow team's public run entry, injected at app assembly (create_front_app):
#   necklace_surface.RUN = agent_market.necklaces.service.run_for_surface        (PM F05, 11-14)
# Signature: run(front, entry, arguments, source, meta) -> {'ok', 'output', 'stages', 'error_code'}; meta is the
# request's {ip, ua, qa, principal, internal_ips} so the run event can tell outside callers from our own checks.
RUN = None


def request_meta(front, request):
    """The request facts a run event needs (never the body). Unknown pieces stay None: such a run is not external."""
    if request is None:
        return None
    try:
        ip = front.security.resolve_ip(request) if front is not None else None
    except Exception:
        ip = None
    from .traffic import load_internal_ips
    try:
        internal_ips = frozenset(load_internal_ips())
    except Exception:
        internal_ips = frozenset()
    headers = request.headers
    return {'ip': ip, 'ua': headers.get('user-agent'), 'qa': headers.get('x-agentcon-qa'),
            'principal': headers.get('x-agentcon-principal'), 'internal_ips': internal_ips}
NOTICE_SENTENCE = ('Your input is sent to the agents listed in necklace_details; if one fails, the same input may go to a '
                   'listed alternate. No credentials or payments are sent. Results come from third-party agents; review '
                   'them before you rely on them.')


def tools(snapshot=None, now=None):
    """MCP tools for offered necklaces, plus necklace_details when there is at least one (none while nothing is live)."""
    rows = live(snapshot, now)
    if not rows:
        return []
    out = []
    for e in rows:
        window = tested(e.get('quality') or {})
        claim = verified(e.get('quality') or {})
        evidence = (' Verified 95%: ' + str(claim[0]) + '/' + str(claim[1]) + ' cumulative retests passed.' if claim
                    else ' Recent tests: ' + str(window[0]) + '/' + str(window[1]) + ' passed.' if window else '')
        out.append({'name': tool_name(e['slug']), 'title': e.get('name') or e['slug'],
                    'description': ('Necklace (a workflow of tested agents, ' + str(sum(1 for p in e.get('pearls') or [] if isinstance(p, dict) and p.get('pearl') is True)) + ' verified pearls): ' + (e.get('summary') or '') + evidence
                                    + (' Example arguments: ' + json.dumps(example_input(e), separators=(',', ':')) + '.'
                                       if example_input(e) else '')
                                    + (' ' + FREE_NOW.replace('on this page', 'on its page') if free_now(e) else '')
                                    + ' ' + NOTICE_SENTENCE),
                    'inputSchema': e.get('input_schema') or {'type': 'object'},
                    'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False,
                                    'openWorldHint': True}})
    out.append({'name': 'necklace_details', 'title': 'Necklace details',
                'description': ('Read one necklace before you run it: its pearls (agents) and alternates per step, recent '
                                'test results, completion and cost. Read-only.'),
                'inputSchema': {'type': 'object', 'required': ['slug'], 'additionalProperties': False,
                                'properties': {'slug': {'type': 'string', 'pattern': SLUG.pattern, 'maxLength': 40}}},
                'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True,
                                'openWorldHint': False}})
    return out


def entry_for_tool(name, snapshot=None):
    if not isinstance(name, str) or not name.startswith('necklace_') or name == 'necklace_details':
        return None
    slug = name[len('necklace_'):].replace('_', '-')
    return by_slug(slug, snapshot) if SLUG.fullmatch(slug) else None


def details(slug, base='https://agentconcierge.biz', snapshot=None, now=None):
    """(text, structured) for necklace_details, or None for an unknown or never-approved necklace."""
    entry = by_slug(slug, snapshot) if SLUG.fullmatch(slug or '') else None
    if not entry or not _time(entry.get('gate_passed_at')):
        return None
    item = public_item(entry, base, now)
    lines = [item['name'] + ': ' + (item['summary'] or '')]
    if 'notice' in item:
        lines.append(item['notice']['text'])
    for p in item['pearls']:
        lines.append('- ' + (p.get('role') or 'step') + ': ' + ('verified pearl ' if p.get('verified_pearl') else 'agent ')
                     + str(p['agent_id']) + ' (' + p['card'] + '), alternates '
                     + str(p['alternates']['external']) + ' external + ' + str(p['alternates']['agentcon']) + ' AgentValCon')
    return '\n'.join(lines), item


def call(front, name, arguments, source='mcp', base='https://agentconcierge.biz', snapshot=None, now=None, meta=None):
    """(text, structured, is_error) for a necklace tool call; runs nothing unless the necklace is offered and RUN is wired."""
    entry = entry_for_tool(name, snapshot)
    if entry is None or not _time(entry.get('gate_passed_at')):
        return None
    if not offered(entry, now):
        line = agent_line(entry, base, snapshot) or ('Necklace ' + entry['slug'] + ' is not running now.')
        found = notice(entry, base, snapshot)
        return line, {'necklace': entry['slug'], 'ran': False, **(found[2] if found else {})}, True
    if RUN is None:
        return ('Necklace ' + entry['slug'] + ' cannot run here yet; open ' + base + '/necklaces/' + entry['slug'] + '.',
                {'necklace': entry['slug'], 'ran': False, 'error_code': 'not_wired'}, True)
    if not isinstance(arguments, dict):
        return (MESSAGES['bad_arguments'] + ' Necklace ' + entry['slug'] + ' did not run (bad_arguments).',
                {'necklace': entry['slug'], 'ran': False, 'error_code': 'bad_arguments'}, True)
    result = RUN(front, entry, arguments, source, meta) or {}
    ok = bool(result.get('ok'))
    refused = result.get('error_code') in REFUSED      # nothing was run (input, consent, scope, limits)
    if ok:
        text = 'Ran necklace ' + entry['slug'] + '. ' + (
            '(Saved answer from ' + str(result.get('ran_at')) + ' UTC.) ' if result.get('cached') else '')
    else:
        lead = str(result['notice']) if result.get('notice') else (message(result.get('error_code')) or '')
        text = (lead + ' ' if lead else '') + 'Necklace ' + entry['slug'] + (
            ' did not run (' if refused else ' did not finish (') + str(result.get('error_code') or 'failed') + '). '
    text += json.dumps(result.get('output'), ensure_ascii=False)[:4000]
    return text, {'necklace': entry['slug'], 'ran': not refused, 'ok': ok, 'stages': result.get('stages'),
                  'error_code': result.get('error_code'), 'output': result.get('output'),
                  'cached': bool(result.get('cached')), 'ran_at': result.get('ran_at'),
                  **({'notice': result['notice']} if result.get('notice') else {})}, not ok


REFUSED = {'invalid_input', 'consent_required', 'sensitive_input', 'rate_limited', 'out_of_scope', 'definition_changed',
           'not_found', 'invalid_source'}


A2A_RUN = re.compile(r'^\s*run\s+necklace\s+([a-z][a-z0-9-]{0,39})\b(.*)$', re.I | re.S)


def example_arguments(schema, example=None):
    props = (schema or {}).get('properties') or {}
    keys = [k for k in ((schema or {}).get('required') or list(props)[:2]) if isinstance(k, str)]
    return {k: (example or {}).get(k, '<' + k + '>') for k in keys}


def skills(base='https://agentconcierge.biz', snapshot=None, now=None):
    """A2A card skills for offered necklaces (none while nothing is live)."""
    out = []
    for e in live(snapshot, now):
        example = 'run necklace ' + e['slug'] + ' ' + json.dumps(example_arguments(e.get('input_schema'), example_input(e)),
                                                                   separators=(',', ':'))
        out.append({'id': skill_id(e['slug']), 'name': e.get('name') or e['slug'],
                    'description': 'Necklace (a workflow of tested agents, ' + str(sum(1 for p in e.get('pearls') or [] if isinstance(p, dict) and p.get('pearl') is True)) + ' verified pearls): ' + (e.get('summary') or '')
                                   + (' ' + FREE_NOW.replace('on this page', 'on its page') if free_now(e) else '') + ' Send: ' + example
                                   + ' ' + NOTICE_SENTENCE + ' Details: ' + base + '/necklaces/' + e['slug'],
                    'tags': ['necklace', 'workflow'], 'examples': [example]})
    return out


def parse_a2a(text):
    """(slug, arguments | None | 'invalid') for 'run necklace <slug> {...}', or None when the text is not that command."""
    match = A2A_RUN.match(text or '')
    if not match:
        return None
    slug, rest = match[1].lower(), match[2].strip()
    if not rest:
        return slug, None
    try:
        value = json.loads(rest)
    except ValueError:
        return slug, 'invalid'
    return (slug, value) if isinstance(value, dict) else (slug, 'invalid')


def a2a_answer(front, text, base='https://agentconcierge.biz', snapshot=None, now=None, meta=None):
    """(reply text, data) for an A2A 'run necklace' message, or None when it is not one."""
    wanted = parse_a2a(text)
    if wanted is None:
        return None
    slug, arguments = wanted
    entry = by_slug(slug, snapshot) if SLUG.fullmatch(slug) else None
    if entry is None or not _time(entry.get('gate_passed_at')):
        return 'There is no necklace named ' + slug + '. See ' + base + '/api/necklaces', {'intent': 'necklace', 'ok': False,
                                                                                              'error_code': 'unknown_necklace'}
    if arguments is None and offered(entry, now):
        example = 'run necklace ' + slug + ' ' + json.dumps(example_arguments(entry.get('input_schema'), example_input(entry)),
                                                            separators=(',', ':'))
        return 'Send: ' + example + ' (fill in the values).', {'intent': 'necklace', 'ok': False, 'error_code': 'needs_arguments',
                                                               'example': {'text': example}}
    answer = call(front, tool_name(slug), arguments if isinstance(arguments, dict) else 'invalid', 'a2a', base, snapshot, now,
                  meta)
    reply, data, failed = answer
    return reply, {'intent': 'necklace', 'ok': not failed, **data}


MAX_RUN_BODY = 16384


def necklace_router(front=None):
    from fastapi import APIRouter, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
    router = APIRouter()

    @router.post('/api/necklaces/{slug}/run', include_in_schema=False)
    async def api_run(slug: str, request: Request):
        """Web run (the page's Run button): one JSON object of inputs plus necklace_notice=necklace-v1 (the consent
        checkbox, never stored). Same rules as MCP and A2A: nothing runs unless the necklace is offered."""
        headers = {'Cache-Control': 'no-store'}
        if front is not None and not front.limit.allow(front.security.resolve_ip(request)):
            return JSONResponse({'ran': False, 'error_code': 'rate_limited'}, status_code=429, headers=headers)
        raw = await request.body()
        try:
            arguments = json.loads(raw) if 0 < len(raw) <= MAX_RUN_BODY else None
        except ValueError:
            arguments = None
        if not SLUG.fullmatch(slug or ''):
            return JSONResponse({'ran': False, 'error_code': 'unknown_necklace'}, status_code=404, headers=headers)
        answer = await run_in_threadpool(call, front, tool_name(slug), arguments if isinstance(arguments, dict) else 'invalid',
                                         'web', front.base(request) if front is not None else 'https://agentconcierge.biz',
                                         None, None, request_meta(front, request))
        if answer is None:
            return JSONResponse({'ran': False, 'error_code': 'unknown_necklace'}, status_code=404, headers=headers)
        text, structured, failed = answer
        return JSONResponse({**structured, 'text': text}, status_code=200, headers=headers)

    @router.post('/necklaces/{slug}/run', include_in_schema=False)
    async def form_run(slug: str, request: Request):
        """The page form (F17, PM 11-15): the same rules as /api/necklaces/<slug>/run, answered with the page and its result."""
        from urllib.parse import parse_qsl
        from .growth_pages import PAGE_CSP
        headers = {'Cache-Control': 'no-store', 'Content-Security-Policy': PAGE_CSP}
        entry = by_slug(slug) if SLUG.fullmatch(slug or '') else None
        if entry is None:
            return RedirectResponse('/necklaces/' + (slug if SLUG.fullmatch(slug or '') else ''), status_code=303)
        props = (entry.get('input_schema') or {}).get('properties') or {}
        raw = await request.body()
        form = dict(parse_qsl(raw.decode('utf-8', 'replace'), keep_blank_values=False)) if 0 < len(raw) <= MAX_RUN_BODY else {}
        values = {k: v.strip() for k, v in form.items() if k in props and v.strip()}
        if front is not None and not front.limit.allow(front.security.resolve_ip(request)):
            structured = {'ran': False, 'ok': False, 'error_code': 'rate_limited'}
        else:
            arguments = dict(values, **({'necklace_notice': form['necklace_notice']} if form.get('necklace_notice') else {}))
            answer = await run_in_threadpool(call, front, tool_name(slug), arguments, 'web',
                                             front.base(request) if front is not None else 'https://agentconcierge.biz',
                                             None, None, request_meta(front, request))
            structured = answer[1] if answer else {'ran': False, 'ok': False, 'error_code': 'not_found'}
        status, value = page(slug, run=(values, structured))
        if status != 200:
            return RedirectResponse('/necklaces/' + slug, status_code=303)
        return HTMLResponse(value, headers=headers)

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
        from .growth_pages import PAGE_CSP   # 11-15 F17 audit: the default CSP blocked the page's stylesheets
        return HTMLResponse(value, headers={'Content-Security-Policy': PAGE_CSP})

    return router

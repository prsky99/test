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
    'pearls_unverified': 'Our latest member tests could not be read.',
    'members_unqualified': 'Fewer than two of its agents passed our member tests lately.',
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


PREVIEW_NOTE = 'Preview — test runs in progress'


def preview_tests(entry):
    """(passed, total) of a preview necklace's test runs, or None (workflow team contract 11-18: entry['preview']['tests'])."""
    block = entry.get('preview') if isinstance(entry, dict) and isinstance(entry.get('preview'), dict) else {}
    tests = block.get('tests') if isinstance(block.get('tests'), dict) else {}
    passed, total = tests.get('passed'), tests.get('total')
    if all(type(v) is int and v >= 0 for v in (passed, total)) and passed <= total and total > 0:
        return passed, total
    return None


PROMO_KEYS = ('quality', 'cost', 'completion', 'comparison')


def public_view(entry):
    """What the public surfaces may print about an entry (PM 11-18 17:3x): for a preview necklace no accuracy, speed, cost or
    comparison figure (it has no measured round yet), so those blocks are dropped; offered() still reads the original."""
    if isinstance(entry, dict) and entry.get('status') == 'preview':
        return {k: v for k, v in entry.items() if k not in PROMO_KEYS}
    return entry


def own_members(entry, now=None):
    """(counted, label, until) of the time-limited exception for necklaces built with our own agents (PM 11-18 16:55,
    entry['own_members'] from the judge), or None: a whole number of members 1..10, a label, and a last day (Asia/Seoul)
    that has not passed. The exception adds to the member count only; it never makes a member a pearl."""
    block = entry.get('own_members') if isinstance(entry, dict) and isinstance(entry.get('own_members'), dict) else None
    if not block:
        return None
    counted, label, until = block.get('counted'), block.get('label'), block.get('until')
    if type(counted) is not int or not 1 <= counted <= 10 or type(label) is not str or not 0 < len(label.strip()) <= 80:
        return None
    try:
        last = datetime.strptime(str(until), '%Y-%m-%d').replace(tzinfo=timezone(timedelta(hours=9))) + timedelta(days=1)
    except ValueError:
        return None
    return (counted, label.strip(), str(until)) if (now or datetime.now(timezone.utc)) < last else None


def has_preview(entry):
    """True when the judge marked the entry as a preview: entry['preview'] with gate_passed false (workflow team 11-18 17:2x).
    Test counts are optional: without a measured round the block has only the note and the page shows no number."""
    block = entry.get('preview') if isinstance(entry, dict) and isinstance(entry.get('preview'), dict) else {}
    return block.get('gate_passed') is False


def connect_check(entry, now=None):
    """(last_at, ok) of the daily connection check, or None when the entry has none (workflow team 11-18: entry['connect'] =
    {passed_at, last_at, last_ok}). A live necklace with this block is judged by the connection run, not by delta or a retest."""
    block = entry.get('connect') if isinstance(entry, dict) and isinstance(entry.get('connect'), dict) else None
    if block is None:
        return None
    return _time(block.get('last_at')), block.get('last_ok') is True


def opened(entry):
    """True once the necklace was ever shown as open: it passed the gate, or it runs as a preview (never both claims)."""
    return bool(_time(entry.get('gate_passed_at'))) or (entry.get('status') in ('preview', 'held') and has_preview(entry))


def offered(entry, now=None):
    """True when the necklace may run and be promoted (contract section 3, plus the 95% gate)."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(entry, dict) or entry.get('status') not in ('live', 'preview') or not SLUG.fullmatch(entry.get('slug') or ''):
        return False
    pearls = [p for p in entry.get('pearls') or [] if isinstance(p, dict)]
    quality = entry.get('quality') or {}
    tested = _time(quality.get('tested_at'))
    delta = quality.get('delta_pp')
    # PM 16:03 (user instruction d4670360): two members that answer, verified pearls or provisional ones, as the judge
    # marks them (standing); two verified pearls is the aim, not the condition. The answer gate below is unchanged.
    members = sum(1 for p in pearls if member_status(p) in MEMBER_LABELS) + (own_members(entry, now) or (0,))[0]
    # a preview necklace runs without the gate; the judge's preview block (gate_passed false) stands in for it and never carries a gate claim
    cleared = (bool(_time(entry.get('gate_passed_at'))) if entry.get('status') == 'live' else has_preview(entry))
    if entry.get('status') == 'preview':
        # PM 17:3x (workflow team): the judge does not ask a preview for a positive delta and leaves quality empty before the first
        # retest (it holds a preview itself after 72 hours without one and when the retest goes stale), so the surface only
        # refuses a preview whose recorded retest is older than the freshness window.
        recent = tested is None or now - tested <= timedelta(hours=FRESH_HOURS)
        return cleared and members >= 2 and all(map(_alternates_ok, pearls)) and recent
    check = connect_check(entry)
    if entry.get('status') == 'live' and check is not None:
        # the connection gate (PM 11-18): no accuracy score, so no delta or retest; the last daily connection run must have passed
        # and be recent. The judge holds the entry itself (connect_failed, connect_stale) when it does not.
        last, ok = check
        return cleared and members >= 2 and all(map(_alternates_ok, pearls)) and ok and last is not None and now - last <= timedelta(hours=FRESH_HOURS)
    return (cleared and members >= 2 and all(map(_alternates_ok, pearls))
            and isinstance(delta, (int, float)) and delta > 0
            and tested is not None and now - tested <= timedelta(hours=FRESH_HOURS))


def by_slug(slug, snapshot=None):
    for entry in (snapshot or load()).get('necklaces') or []:
        if isinstance(entry, dict) and entry.get('slug') == slug:
            return entry
    return None


def live(snapshot=None, now=None):
    """Open necklaces that passed the gate; a preview is not promoted in recommendation answers."""
    return [e for e in (snapshot or load()).get('necklaces') or [] if isinstance(e, dict) and e.get('status') == 'live' and offered(e, now)]


def available(snapshot=None, now=None):
    """Necklaces that can be run now: live ones and previews (the tool lists), never promoted as results of a question."""
    return [e for e in (snapshot or load()).get('necklaces') or []
            if isinstance(e, dict) and e.get('status') in ('live', 'preview') and offered(e, now)]


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


# PM 16:03 (user instruction d4670360): a necklace may start with a provisional member and swap in a pearl later.
# Each step says which it is; a provisional member never reads as a pearl.
MEMBER_LABELS = {'verified_pearl': 'Verified pearl', 'provisional': 'Under verification'}
NOT_COUNTED = 'Not passing our member tests now'
PROVISIONAL_NOTE = ('Under verification: the agent answered our test for this step recently but has not yet reached the '
                    'verified-pearl bar. When a verified pearl is available for the step, it takes the place.')
OWN_PROVISIONAL_NOTE = ('AgentValCon agent, under verification: our own agent for this step, which passed our substitute '
                        'check; it leads until a verified pearl is available.')
# user decision 11-18: our own substitute is approved by three connection runs; its accuracy is not scored
OWN_CONNECTED_NOTE = ('AgentValCon agent: our own agent for this step. It passed three connection runs on different '
                      'inputs, answering in the step\u2019s form within the time budget; its accuracy is not scored. It '
                      'leads until a verified pearl is available.')
OWN_UNCHECKED_NOTE = ('AgentValCon agent, not yet checked: our own agent for this step has no passed substitute check on '
                      'record.')
CHECKED_SUBSTITUTE = ('approved', 'provisional')


def approvals_path():
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return Path(root) / 'gateway-data/necklaces/approvals.json' if root else None


_APPROVALS = {'key': None, 'value': {}}


def substitute_checked(pearl, path=None):
    """PM 11-16: our own agent leading a step is said to have passed its substitute check only when the latest
    record for it in approvals.json substitutes (same resource_id and tool) is approved or provisional with a gate
    record; revoked, unknown or unreadable is not."""
    if not isinstance(pearl, dict):
        return False
    path = Path(path) if path else approvals_path()
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if _APPROVALS['key'] != key:
            latest = {}
            for row in json.loads(path.read_text(encoding='utf-8')).get('substitutes') or []:
                if isinstance(row, dict) and isinstance(row.get('at'), str):
                    k = (row.get('resource_id'), row.get('tool'))
                    if k not in latest or row['at'] >= latest[k]['at']:
                        latest[k] = row
            _APPROVALS.update(key=key, value=latest)
    except (OSError, ValueError, AttributeError, TypeError):
        return False
    row = _approval_row(pearl)
    return bool(row) and row.get('state') in CHECKED_SUBSTITUTE and bool(row.get('gate_record'))


def _approval_row(pearl):
    """The latest approvals.json row for our own agent (PM 21:33, 11-18): ops writes resource_id 'avc:<agent_id>', while
    a snapshot lead of ours has no resource_id, so the row is found by (resource_id, tool), then ('avc:' + agent_id,
    tool), then by the tool alone when exactly one of our own agents has it."""
    rows = _APPROVALS['value']
    tool = pearl.get('tool')
    if (pearl.get('resource_id'), tool) in rows:
        return rows[(pearl.get('resource_id'), tool)]
    if pearl.get('agent_id'):
        # by the agent, as the run itself finds it (judge.load_substitutes keys on agent_id and role): a definition
        # may name our agent's tool differently from the approval row (dns-spf-dmarc, 11-18)
        found = [row for (rid, _), row in rows.items() if rid == 'avc:' + str(pearl['agent_id'])]
        return max(found, key=lambda row: row['at']) if found else None
    if pearl.get('resource_id') is None:
        found = [row for (rid, t), row in rows.items() if t == tool and str(rid).startswith('avc:')]
        if len(found) == 1:
            return found[0]
    return None


def substitute_record(pearl, path=None):
    """The approval row when substitute_checked, else None."""
    return _approval_row(pearl) if substitute_checked(pearl, path) else None


# PM 11-16 06:5x: a required step with no usable outside member runs on our own agent alone; the page and the agent
# texts say so per step, from the judge's snapshot (never a hard-coded list), and the note goes away by itself once an
# outside member that passes our tests is attached.
EXTERNAL_PENDING = 'Runs on our own agent; external alternative being added.'


def usable_external(pearl):
    """Outside members this step can fall to: the judge's external_usable when given, else the lead and alternates of
    kind external whose standing counts (or, in a snapshot without standing, every external one)."""
    if not isinstance(pearl, dict):
        return 0
    given = pearl.get('external_usable')
    if type(given) is int and given >= 0:
        return given
    members = [pearl] + [a for a in pearl.get('alternates') or [] if isinstance(a, dict)]
    external = [m for m in members if m.get('kind', 'external' if m is pearl else None) == 'external']
    if any('standing' in m for m in members):
        return sum(1 for m in external if m.get('standing') in MEMBER_LABELS)
    return len(external)


def external_pending(pearl):
    return isinstance(pearl, dict) and pearl.get('required', True) is not False and usable_external(pearl) == 0


def pending_roles(entry):
    return [str(p.get('role') or 'step') for p in entry.get('pearls') or [] if external_pending(p)]


def own_provisional_note(snapshot=None):
    """Our own agent leading a step became a member by passing its substitute gate, not by a score (workflow 11-16):
    the line uses the judge's member_rules.provisional.own_substitute wording when there is one."""
    rules = (snapshot or load()).get('member_rules')
    own = ((rules or {}).get('provisional') or {}).get('own_substitute') if isinstance(rules, dict) else None
    if not isinstance(own, str) or not own.strip() or len(own) > 200 or '<' in own:
        return OWN_PROVISIONAL_NOTE
    return ('AgentValCon agent, under verification: our own agent for this step, which ' + ' '.join(own.split())
            + '; it leads until a verified pearl is available.')


def own_checked_note(pearl, snapshot=None):
    """Which check our own agent passed, from its approval row: connection runs (connect_test) or the held-out gate."""
    row = substitute_record(pearl) or {}
    record = row.get('gate_record') if isinstance(row.get('gate_record'), dict) else {}
    return OWN_CONNECTED_NOTE if record.get('connect_test') else own_provisional_note(snapshot)


def provisional_note(snapshot=None):
    """PM 11-16 (workflow 17:3x): an outside provisional member answered its role test within the window with a score
    of at least the provisional bar, below the verified-pearl bar; it has not 'passed and awaits a second day'. The
    numbers are the judge's (snapshot member_rules); without them the sentence carries none."""
    rules = (snapshot or load()).get('member_rules')
    rules = rules if isinstance(rules, dict) else {}
    p = rules.get('provisional') if isinstance(rules.get('provisional'), dict) else {}
    v = rules.get('verified_pearl') if isinstance(rules.get('verified_pearl'), dict) else {}
    low, within = _rule_number(p.get('min_score')), _rule_number(p.get('within_days'))
    high, days = _rule_number(v.get('min_score')), _rule_number(v.get('successes_on_different_days'))
    if None in (low, within, high, days):
        return PROVISIONAL_NOTE
    return ('Under verification: the agent answered our test for this step within the last ' + format(within, 'g')
            + ' days with a score of at least ' + format(low, 'g') + ', below the verified-pearl bar (' + format(high, 'g')
            + (' or more on its role task' if days == 1 else ' or more on ' + format(days, 'g') + ' different days')
            + '). When a verified pearl is available for the step, '
            'it takes the place.')


_SOURCES = {'key': None, 'value': {}}


def _notes(entry):
    """The kept notes of a necklace (necklace_sources.json): {'sources', 'accuracy_scope', 'attribution'}, any missing."""
    path = Path(__file__).with_name('necklace_sources.json')
    try:
        key = path.stat().st_mtime_ns
        if _SOURCES['key'] != key:
            value = {}
            for slug, raw in json.loads(path.read_text(encoding='utf-8')).items():
                if slug.startswith('_'):
                    continue
                raw = {'sources': raw} if isinstance(raw, str) else raw if isinstance(raw, dict) else {}
                one = {k: ' '.join(raw[k].split()) for k in ('sources', 'accuracy_scope')
                       if isinstance(raw.get(k), str) and raw[k].strip()}
                att = raw.get('attribution') if isinstance(raw.get('attribution'), dict) else {}
                links = [{'label': ' '.join(str(x.get('label')).split())[:40], 'url': x['url']}
                         for x in att.get('links') or [] if isinstance(x, dict) and isinstance(x.get('url'), str)
                         and re.fullmatch(r'https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~/%-]*)?', x['url']) and x.get('label')]
                if isinstance(att.get('text'), str) and att['text'].strip():
                    one['attribution'] = {'text': ' '.join(att['text'].split())[:200], 'links': links}
                if one:
                    value[slug] = one
            _SOURCES.update(key=key, value=value)
    except (OSError, ValueError):
        return {}
    return _SOURCES['value'].get((entry or {}).get('slug'), {}) if isinstance(entry, dict) else {}


MEMBER_TOKEN = re.compile(r'\{member:([0-9]{1,9})@([a-z][a-z0-9_.]*\.v[0-9]{1,3})\}')
VERIFIED_MEMBER = 'a verified third-party agent'
UNVERIFIED_MEMBER = 'a third-party agent under verification'


def _member_words(match, snapshot=None):
    """PM 11-17: a member's standing in the sentence is read from the verify snapshot when the page is drawn, never
    fixed in necklace_sources.json; anything but verified_pearl for that agent and role reads 'under verification'."""
    try:
        from .check_route import load
        agent = ((snapshot or load()).get('agents') or {}).get(match[1]) or {}
        verified = any(isinstance(r, dict) and r.get('role') == match[2] and r.get('verified_pearl') is True
                       for r in agent.get('roles') or [])
    except Exception:
        verified = False
    return VERIFIED_MEMBER if verified else UNVERIFIED_MEMBER


def sources_note(entry, snapshot=None):
    """The 'what each step uses' sentence for a necklace, or None. {member:<id>@<role>} tokens are filled from the
    verify snapshot (exports/pearls/verify-snapshot.json) at the time the page is drawn."""
    text = _notes(entry).get('sources')
    return MEMBER_TOKEN.sub(lambda m: _member_words(m, snapshot), text) if text else text


def accuracy_scope(entry):
    """Where the accuracy was measured, when it covers only part of what the necklace answers (e.g. US locations)."""
    return _notes(entry).get('accuracy_scope')


def attribution(entry):
    """{'text', 'links'} a source's terms require next to its data (e.g. MET Norway), or None."""
    return _notes(entry).get('attribution')


def attribution_text(entry):
    att = attribution(entry)
    if not att:
        return None
    return att['text'] + (' Licence: ' + ', '.join(l['label'] + ' ' + l['url'] for l in att['links']) + '.' if att['links'] else '')


def shown_summary(entry):
    """The judged summary followed by the sources sentence and a required attribution where kept."""
    summary = (entry.get('summary') or '') if isinstance(entry, dict) else ''
    extra = ' '.join(x for x in (sources_note(entry), attribution_text(entry)) if x)
    return (summary + ' ' + extra).strip() if extra else summary


def member_status(pearl):
    """'verified_pearl', 'provisional' or None from the judge's snapshot (standing; a snapshot without it: the pearl
    flag, which means a verified pearl only). Any other value counts as None and never reads as a pearl."""
    if not isinstance(pearl, dict):
        return None
    if 'standing' in pearl:
        return pearl['standing'] if pearl['standing'] in MEMBER_LABELS else None
    return 'verified_pearl' if pearl.get('pearl') is True else None


def _rule_number(value):
    return value if type(value) in (int, float) and value >= 0 else None


def member_rules_text(snapshot=None):
    """The methodology's member paragraph (PM 16:03), worded from the judge's snapshot member_rules (workflow f9ba1876):
    its numbers are the judge's, never a copy. A rule whose numbers are missing or null is left out; no rules, None."""
    rules = (snapshot or load()).get('member_rules')
    if not isinstance(rules, dict):
        return None
    sentences = []
    verified = rules.get('verified_pearl') if isinstance(rules.get('verified_pearl'), dict) else {}
    score, days = _rule_number(verified.get('min_score')), _rule_number(verified.get('successes_on_different_days'))
    if score is not None and days is not None:
        sentences.append('A step is led by a verified pearl when its agent scored at least ' + format(score, 'g')
                         + (' in our test reports.' if days == 1 else ' in our test reports on ' + format(days, 'g') + ' different days.'))
    provisional = rules.get('provisional') if isinstance(rules.get('provisional'), dict) else {}
    p_score, within, reports = (_rule_number(provisional.get('min_score')), _rule_number(provisional.get('within_days')),
                                _rule_number(provisional.get('reports')))
    own = provisional.get('own_substitute')
    if p_score is not None and within is not None and reports is not None:
        sentences.append('Until a pearl is available, a step may be led by a provisional member: an agent that scored '
                         'at least ' + format(p_score, 'g') + ' in ' + ('a test report' if reports == 1 else
                                                                       format(reports, 'g') + ' test reports')
                         + ' within the last ' + format(within, 'g') + ' days'
                         + (', or our own substitute that ' + html.escape(' '.join(own.split())[:200], quote=True) if isinstance(own, str) and own.strip() else '')
                         + '. A pearl takes its place when one is verified.')
    if not sentences:
        return None
    return ' '.join(sentences) + (' Either way, the necklace&#39;s answers pass the same gate before it is offered, and '
                                  'its page says which kind leads each step.')


def pending_sentence(entry):
    """'' or one sentence naming the steps that run on our own agent alone (PM 11-16 06:5x)."""
    roles = pending_roles(entry)
    if not roles:
        return ''
    return ('The ' + ', '.join(roles) + (' steps run' if len(roles) > 1 else ' step runs')
            + ' on our own agent; an external alternative is being added.')


def members_phrase(entry):
    """'2 verified pearls' or '1 verified pearl and 1 agent under verification' (agents read it in tool descriptions)."""
    standings = [member_status(p) for p in entry.get('pearls') or [] if isinstance(p, dict)]
    pearls, provisional = standings.count('verified_pearl'), standings.count('provisional')
    parts = ([str(pearls) + ' verified pearl' + ('s' if pearls != 1 else '')] if pearls else []) + (
        [str(provisional) + ' agent' + ('s' if provisional != 1 else '') + ' under verification'] if provisional else [])
    return ' and '.join(parts) or 'no member passing our tests now'


def public_member_id(member):
    """What a public answer shows as the member's id: the catalog id of an outside agent, and for one of our own agents
    ('agentcon') only "AgentValCon agent (<role>)", never its internal id (PM 11-18: internal names such as the
    personality fortune members stay inside the definition)."""
    if member.get('kind') == 'agentcon':
        return 'AgentValCon agent (' + str(member.get('role') or 'step') + ')'
    return member.get('resource_id') if member.get('resource_id') is not None else member.get('agent_id')


def public_item(entry, base='https://agentconcierge.biz', now=None):
    """The /api/necklaces entry: what a person or an agent needs to choose and run it; no internal fields."""
    shown = public_view(entry)
    quality, cost, completion = shown.get('quality') or {}, shown.get('cost') or {}, shown.get('completion') or {}
    item = {'slug': entry['slug'], 'name': entry.get('name'), 'summary': entry.get('summary'),
            **({'sources': sources_note(entry)} if sources_note(entry) else {}),
            **({'attribution': attribution(entry)} if attribution(entry) else {}),
            'status': entry.get('status'), 'offered': offered(entry, now),
            'url': base + '/necklaces/' + entry['slug'], 'mcp_tool': tool_name(entry['slug']),
            'a2a_skill': skill_id(entry['slug']), 'input_schema': entry.get('input_schema'),
            'pearls': [{'agent_id': public_member_id(p),
                        'role': p.get('role'), 'tool': p.get('tool'), 'kind': p.get('kind') or 'external',
                        'verified_pearl': member_status(p) == 'verified_pearl', 'standing': member_status(p),
                        # an AgentValCon lead (kind agentcon) has no catalog resource, so no catalog card
                        # a catalog card only for an outside member with a catalog id; our own agents ('avc:…') have none
                        'card': (base + '/agent/' + str(p['resource_id']) if p.get('kind') != 'agentcon'
                                 and re.fullmatch(r'[1-9][0-9]{0,9}', str(p.get('resource_id') or '')) else None),
                        'external_usable': usable_external(p), 'external_pending': external_pending(p),
                        'alternates': {'external': sum(1 for a in p.get('alternates') or [] if a.get('kind') == 'external'),
                                       'agentcon': sum(1 for a in p.get('alternates') or []
                                                       if a.get('kind') == 'agentcon' and substitute_checked(a))}}
                       for p in entry.get('pearls') or [] if isinstance(p, dict)],
            'quality': {**{k: quality.get(k) for k in ('success_rate', 'best_single_rate', 'delta_pp', 'delta_pairs',
                                                        'delta_necklace_rate', 'tested_at')
                           if quality.get(k) is not None},
                        **({'single_basis': SINGLE_BASIS} if quality.get('best_single_rate') is not None else {}),
                        **({'passed': tested(quality)[0], 'cases': tested(quality)[1]} if tested(quality) else {}),
                        'verified_95': verified(quality) is not None},
            'completion': {k: completion.get(k) for k in ('runs', 'completed', 'completed_external_only', 'since', 'retested_at')
                           if completion.get(k) is not None},
            'cost': {k: cost.get(k) for k in ('usdc_per_run', 'p50_ms', 'p95_ms') if cost.get(k) is not None}}
    if own_members(entry, now):
        item['own_members'] = dict(zip(('counted', 'label', 'until'), own_members(entry, now)))
    if entry.get('status') == 'preview' or preview_tests(entry):
        item['preview'] = {'note': PREVIEW_NOTE, 'gate_passed': False,
                           **({'tests': {'passed': preview_tests(entry)[0], 'total': preview_tests(entry)[1]}} if preview_tests(entry) else {})}
    if fallback(entry):
        item['fallback'] = fallback(entry)
    if scope_notice(entry):
        item['scope_notice'] = scope_notice(entry)
    if comparison(shown):
        item['comparison'] = public_comparison(comparison(shown))
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


def live_count(snapshot=None, now=None):
    """How many necklaces are open now, past the gate (judged snapshot only; none in testing, preview, held or retired)."""
    snapshot = snapshot or load()
    now = now or datetime.now(timezone.utc)
    return sum(1 for entry in snapshot.get('necklaces') or []
               if isinstance(entry, dict) and SLUG.fullmatch(entry.get('slug') or '') and entry.get('status') != 'testing'
               and entry.get('status') == 'live' and offered(entry, now))


def preview_count(snapshot=None, now=None):
    """How many necklaces run as a preview now (status preview, offered; never counted with the open ones)."""
    snapshot = snapshot or load()
    now = now or datetime.now(timezone.utc)
    return sum(1 for entry in snapshot.get('necklaces') or []
               if isinstance(entry, dict) and entry.get('status') == 'preview' and offered(entry, now))


def verifying_count(snapshot=None):
    """Necklaces in verification (PM 21:43): the judge's count of not-yet-open necklaces in their connection test; the
    public card counts live and preview ones, so the two never overlap. None when the snapshot has no count."""
    value = ((snapshot or load()).get('verifying') or {}).get('count')
    return value if type(value) is int and value >= 0 else None


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


SINGLE_BASIS = ('On the same cases and days, each member agent alone was given the whole task; the best of them is '
                'compared with the necklace on those cases.')


def single_line(quality):
    """PM 11-16: the single-agent baseline says what was compared. Each member answering the whole task alone usually
    covers one step, so a bare "+N points" reads as more than it is. Both rates come from the same paired cases
    (delta_necklace_rate and best_single_rate over delta_pairs, daily.paired_delta); without those, nothing is said."""
    q = quality if isinstance(quality, dict) else {}
    pairs, mine, theirs, delta = q.get('delta_pairs'), q.get('delta_necklace_rate'), q.get('best_single_rate'), q.get('delta_pp')
    if type(pairs) is not int or pairs < 1 or not _pct(mine) or not _pct(theirs) or not isinstance(delta, (int, float)):
        return None
    return ('On the same ' + str(pairs) + ' cases, the best single member agent answering the whole task alone got '
            + _pct(theirs) + '; the necklace got ' + _pct(mine) + ' (' + ('+' if delta >= 0 else '') + str(round(delta, 1))
            + ' points).')


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
    if status == 'preview':
        if not offered(entry, now):
            return 'Standing: preview, not running now (waiting for its next retest).'
        tests = preview_tests(entry)
        return ('Standing: ' + PREVIEW_NOTE + (' (' + str(tests[0]) + ' of ' + str(tests[1]) + ' test runs passed so far)' if tests else '') + '.')
    if status != 'live':
        return 'Standing: paused.' if status == 'held' else 'Standing: stopped.'
    if not offered(entry, now):
        return 'Standing: not running now (waiting for its next retest).'
    check = connect_check(entry)
    if check is not None:       # no accuracy claim exists for a connection-gated necklace: say what is checked, and when
        return 'Standing: running · connected end to end and checked every day' + (' (last check ' + check[0].strftime('%Y-%m-%d') + ').' if check[0] else '.')
    claim = verified(entry.get('quality') or {})
    if claim:
        return 'Standing: running · Verified 95% (' + str(claim[0]) + '/' + str(claim[1]) + ' cumulative retests passed).'
    # PM 22:30 (11-18): the held-out retests that the "110 retests" sentence waited for are switched off (user
    # decision 11-18: the gate is the connection test), so it could never be reached. A live necklace without a
    # connection line yet says what comes next, with the number from the gate's own rules.
    return 'Standing: running · ' + connection_pending_text() + '.'


def connection_pending_text():
    try:
        from ..necklaces.gate_rules import summary
        runs = summary()['necklace']['stage_2_connection_runs']
    except Exception:          # noqa: BLE001 - the page never breaks on the rules module; it says no number then
        runs = None
    return ('its connection test (' + str(runs) + ' runs on different inputs) has not run yet; once it passes, one '
            'connection run a day keeps it open' if isinstance(runs, int) else
            'its connection test has not run yet; once it passes, one connection run a day keeps it open')


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


def step_fallbacks(entry):
    """[(role, outside, own)] for each required step from the snapshot's members (PM 21:33, 11-18): outside fallbacks
    are the external alternates, our own counts only with a passed check in approvals.json; a step our own agent leads
    has outside None. Empty when the snapshot has no members."""
    out = []
    for p in entry.get('pearls') or [] if isinstance(entry, dict) else []:
        if not isinstance(p, dict) or p.get('required', True) is False:
            continue
        alts = [a for a in p.get('alternates') or [] if isinstance(a, dict)]
        outside = sum(1 for a in alts if a.get('kind') == 'external')
        own = sum(1 for a in alts if a.get('kind') == 'agentcon' and substitute_checked(a))
        out.append((str(p.get('role') or 'step'), None if p.get('kind') == 'agentcon' else outside, own))
    return out


def _step_phrase(role, outside, own):
    if outside is None:
        return role + ': our own agent' + (', other providers after it' if own else ', no other provider yet')
    if outside and own:
        return role + ': other providers, then our own agent'
    if outside:
        return role + ': other providers'
    return role + (': our own agent' if own else ': no fallback yet')


def fallback_line(entry):
    found = fallback(entry)
    if not found:
        return None
    limits = _coverage_sentence(found['own_coverage']) if found.get('own_coverage') else ''
    steps = step_fallbacks(entry)
    if steps and not all(outside and own for _, outside, own in steps):
        # a step without an outside fallback (or without a checked backup of ours) never reads "other providers are
        # tried ... for every step": each step says what it really falls to
        return ('Fallback per step: ' + '; '.join(_step_phrase(*s) for s in steps)
                + '. If a step\u2019s fallbacks also fail, the run stops.' + limits)
    if found['depth'] == 'agentvalcon':
        return 'Fallback: if a provider fails, other providers are tried, then an AgentValCon backup, for every step.' + limits
    return ('Fallback: other providers only for ' + ', '.join(found['slots_without_own'])
            + ' (no AgentValCon backup yet). If they all fail, the run stops.' + limits)


def scope_notice(entry):
    """The definition's scope sentence (workflow 36b92e0d), or None. It is the same text the runner uses to refuse an
    input outside the scope; pages, /api/necklaces and the MCP tool show it before a run, as written."""
    value = entry.get('scope_notice') if isinstance(entry, dict) else None
    if not isinstance(value, str):
        return None
    value = ' '.join(value.split())
    return value if 1 <= len(value) <= 600 else None


# User instruction 11-15 (plan reports/necklace-promotion-orders-2026-11-15, 3.2): why a necklace, in plain words, with
# no number. Shown only where an offered necklace is (pages, llms.txt, MCP and A2A descriptions), never while none is.
WHY = ('Why a necklace: an agent that finds several agents, calls each one and merges their answers spends tokens and '
       'time on every step, and under a time limit it can settle on a wrong answer. A necklace does those steps in one '
       'call: agents we tested, in a fixed order, with fallbacks, returning one answer.')
WHY_SHORT = 'One call instead of finding, calling and merging several agents yourself.'
_SIDES = ('calls', 'tokens', 'seconds', 'accuracy')


def steps_count(entry):
    """How many agents this necklace joins (PM 16:21: say the real number, never more): the judge's comparison.slots,
    else the required members; None when neither is known."""
    value = (entry.get('comparison') or {}).get('slots') if isinstance(entry.get('comparison'), dict) else None
    if type(value) is int and value >= 1:
        return value
    required = [p for p in entry.get('pearls') or [] if isinstance(p, dict) and p.get('required', True)]
    return len(required) or None


def steps_sentence(entry):
    n = steps_count(entry)
    return 'This necklace joins ' + str(n) + ' agents in one call.' if n and n >= 2 else ''


def comparison(entry):
    """The measured pair from the judge's snapshot (plan 3.1): same cases, same day, the necklace against an agent that
    calls the member tools itself. None unless every value is a plain number; worse values are shown as they are."""
    value = entry.get('comparison') if isinstance(entry, dict) else None
    if not isinstance(value, dict):
        return None
    cases, at = value.get('cases'), value.get('measured_at')
    if type(cases) is not int or cases < 1 or not isinstance(at, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', at):
        return None
    sides = {}
    for side in ('with', 'without'):
        row = value.get(side)
        if not isinstance(row, dict):
            return None
        for key in _SIDES:
            v = row.get(key)
            if type(v) not in (int, float) or v < 0 or (key == 'accuracy' and v > 1):
                return None
        sides[side] = {key: row[key] for key in _SIDES}
    found = {'cases': cases, 'measured_at': at, **sides}
    since = value.get('since')   # the earliest run in the window (value.comparison); the date shown is then a period
    if isinstance(since, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', since) and since < at:
        found['since'] = since
    if type(value.get('slots')) is int and value['slots'] >= 2:
        found['slots'] = value['slots']
    full = value.get('without_full')   # PM 15:14: the path without a necklace including finding tools and merging answers
    if isinstance(full, dict) and all(type(full.get(k)) in (int, float) and full.get(k) >= 0 for k in _SIDES[:3]):
        estimated = full.get('estimated')
        if estimated is None or (isinstance(estimated, list) and all(isinstance(x, str) for x in estimated)):
            found['without_full'] = {**{k: full[k] for k in _SIDES[:3]}, 'estimated': list(estimated or [])}
    return found


COMPARISON_BASIS = {
    'with': ('Measured on the necklace itself in our test runs of the last seven days (gate runs, daily retests and '
             'our own runs; medians per case; tokens are text length / 4).'),
    'without': ("From the same runs' records, not a separate run: an agent calling the same agents itself; seconds "
                "assume each step's calls are sent at the same time; tokens are text length / 4. Its accuracy was not "
                "measured and is not given."),
}


def public_comparison(found):
    """The comparison as the public API and notices give it (PM 11-16 display rules): the direct path's accuracy (never
    run) and the full value with finding and merging (estimated) are left out, and each side says where it comes from."""
    out = {'cases': found['cases'], 'measured_at': found['measured_at'], **({'since': found['since']} if found.get('since') else {}),
           'with': {**found['with'], 'tokens_unit': 'text length / 4'},
           'without': {**{k: v for k, v in found['without'].items() if k != 'accuracy'}, 'tokens_unit': 'text length / 4',
                       'source': "from the same runs' records, not a separate run"},
           'basis': dict(COMPARISON_BASIS)}
    if found.get('slots'):
        out['slots'] = found['slots']
    return out


def comparison_line(entry):
    """The judge's comparison in words, under the PM's display rules (11-16, workflow source table 16:3x):
    - 'Measured' only for what our test runs measured on the necklace itself: its seconds and accuracy, with the number
      of cases and the date; its tokens only with '(text length / 4)' next to the number;
    - the agent calling the members itself was not run separately: its calls, tokens and seconds come from the same
      runs' records and are said to; its seconds assume each step's calls are sent at the same time;
    - not shown: that agent's accuracy (never run) and the full value with finding and merging (estimated). The
      necklace's single call is said in words, not as a measured number."""
    found = comparison(entry)
    if not found:
        return None
    w, wo = found['with'], found['without']
    num = lambda v: format(round(v), ',')
    sec = lambda v: format(round(v, 1), 'g')
    pct = lambda v: str(round(v * 100)) + '%'
    # PM 11-16 16:11 and workflow 16:2x: the cases are every scored run of the last seven days (gate runs, the daily
    # retests after opening and the workflow team's own runs), so they are 'test runs', dated from first to last.
    period = (found['since'] + ' \u2013 ' if found.get('since') else '') + found['measured_at']
    return ('Measured in our test runs on ' + str(found['cases']) + ' cases (' + period + '): one call, '
            'a median of ' + sec(w['seconds']) + ' s per case, ' + pct(w['accuracy']) + ' correct'
            + (' (' + accuracy_scope(entry) + ')' if accuracy_scope(entry) else '') + ', about ' + num(w['tokens'])
            + ' tokens (text length \u00f7 4). From the same runs\' records (not a separate run), an agent calling the same '
            + (str(found['slots']) + ' ' if found.get('slots') else '') + 'agents itself would make ' + num(wo['calls'])
            + ' calls and handle about ' + num(wo['tokens']) + ' tokens (text length \u00f7 4), taking about '
            + sec(wo['seconds']) + ' s if it sent each step\'s calls at the same time. Finding the tools and merging the '
            'answers are not counted.')


WHY_PLACEHOLDER = '<div data-necklace-why></div>'


def why_card(snapshot=None, now=None):
    """Home and Workflows (PM 16:03): the reason, up to three offered necklaces and the request link, rendered into the
    pages' placeholder by pearl_view; '' while none is offered, so the pages never show a necklace that is not there."""
    # PM 21:41 (11-18, user decision: once one necklace is public, home and status show it): previews are listed too,
    # after the open ones, with a "Preview" tag and never a gate claim
    rows = [*live(snapshot, now), *[e for e in available(snapshot, now) if e.get('status') == 'preview']]
    if not rows:
        return ''
    esc = lambda value: html.escape(str(value), quote=True)
    links = ''.join('<li><a href="/necklaces/' + esc(e['slug']) + '">' + esc(e.get('name') or e['slug']) + '</a>'
                    + (' <span class="necklace-preview-tag">' + esc(PREVIEW_TAG) + '</span>'
                       if e.get('status') == 'preview' else '') + '</li>'
                    for e in rows[:3])
    return ('<section class="card necklace-why-card" aria-label="Necklaces"><h3>Necklaces: tested agents in one call</h3>'
            '<p>' + esc(WHY) + '</p><ul>' + links + '</ul><div class="actions"><a class="btn" href="/necklaces">'
            'All necklaces</a> <a class="btn" href="/necklaces/request">Request a necklace</a></div></section>')


PREVIEW_TAG = 'Preview'
INDEX_LEAD = ('Each necklace joins agents of different roles into one call. Open ones passed our gate; '
              'previews run while their test runs are in progress.')


def index_page(base='https://agentconcierge.biz', snapshot=None, now=None):
    """/necklaces (PM 21:41, 11-18): every necklace that can be run now, open ones first, each with its standing, one
    line and a run link. A preview says "Preview — test runs in progress" and no figure; nothing else is shown."""
    from .growth_pages import shell, heading
    rows = [*live(snapshot, now), *[e for e in available(snapshot, now) if e.get('status') == 'preview']]
    esc = lambda value: html.escape(str(value), quote=True)
    items = ''.join(
        '<li class="necklace-index-item"><h2><a href="/necklaces/' + esc(e['slug']) + '">' + esc(e.get('name') or e['slug'])
        + '</a></h2><p class="necklace-index-standing">' + esc(PREVIEW_NOTE if e.get('status') == 'preview' else 'Open')
        + '</p><p>' + esc(e.get('summary') or '') + '</p><p><a href="/necklaces/' + esc(e['slug'])
        + '#runTitle">Run it</a></p></li>'      # one line: the sources and credits are on the necklace's own page
        for e in rows)
    body = (heading('Necklaces', 'Necklaces', INDEX_LEAD)
            + ('<ul class="necklace-index">' + items + '</ul>' if rows else '<p>No necklace can be run yet.</p>')
            + '<p><a class="btn" href="/necklaces/request">Request a necklace</a></p>')
    structured = {'@context': 'https://schema.org', '@type': 'ItemList', 'name': 'Necklaces',
                  'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'url': base + '/necklaces/' + e['slug'],
                                       'name': e.get('name') or e['slug']} for i, e in enumerate(rows)]}
    return shell(title='Necklaces | AgentValCon', description=INDEX_LEAD, canonical=base + '/necklaces',
                 body='<div class="pearl-page">' + body + '</div>', structured=structured, index=bool(rows))


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
    if not entry or entry.get('status') not in ('live', 'preview', 'held', 'retired') or not opened(entry):
        return 404, None
    at = stopped_at(entry)
    if entry.get('status') == 'retired' and entry.get('replaced_by') and at and now - at > timedelta(days=NOTICE_DAYS):
        return 301, '/necklaces/' + entry['replaced_by']
    esc = lambda value: html.escape(str(value), quote=True)
    item = public_item(entry, base, now)
    view = public_view(entry)               # no accuracy, speed or comparison figure on a preview page
    runs = offered(entry, now)
    att = attribution(entry)
    # PM 22:33 (11-18, user: no page that is hard to read): the heading's lead is the one-sentence summary; the
    # sources sentences move to their own top-level section, which the common frame draws as a card
    lead = entry.get('summary') or ''
    parts = [heading('Necklace · Agent Value Gateway', entry.get('name') or slug, lead),
             # a source whose terms require attribution (MET Norway, agent team 11-16) is credited with its licence links
             ('<p class="muted necklace-attribution">' + esc(att['text'])
              + (' Licence: ' + ', '.join('<a href="' + esc(l['url']) + '" rel="license noopener">' + esc(l['label']) + '</a>'
                                          for l in att['links']) + '.' if att['links'] else '') + '</p>' if att else '')
             +
             '<p class="muted necklace-standing">' + esc(standing_line(entry, now)) + '</p>'
             + ('<p class="muted necklace-built">' + esc(own_members(entry, now)[1]) + '</p>' if own_members(entry, now) else '')
             + ('<p class="necklace-scope"><strong>Scope:</strong> ' + esc(scope_notice(entry)) + '</p>' if scope_notice(entry) else '')
             + ('<p class="muted necklace-fallback">' + esc(fallback_line(entry)) + '</p>' if fallback_line(entry) else '')
             + ('<p class="necklace-free">' + esc(FREE_NOW) + '</p>' if free_now(entry) and offered(entry, now) else '')
             + (('<p class="necklace-why">' + esc(WHY) + (' ' + esc(steps_sentence(entry)) if steps_sentence(entry) else '') + '</p>'
                 + ('<p class="muted necklace-measured">' + esc(comparison_line(view)) + '</p>' if comparison_line(view) else ''))
                if offered(entry, now) else '')]
    if sources_note(entry):
        parts.append('<section aria-labelledby="sourcesTitle"><h2 id="sourcesTitle">What each step uses</h2>'
                     '<p class="necklace-sources">' + esc(sources_note(entry)) + '</p></section>')
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
    if single_line(view.get('quality')):
        facts.append(('Against its best single member', single_line(view.get('quality'))))
    window = tested(view.get('quality') or {})
    if window:
        facts.append(('Recent test success', str(window[0]) + '/' + str(window[1]) + ' cases (last 7 days)'))
    claim = verified(view.get('quality') or {})
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
        parts.append('<section aria-labelledby="completionTitle"><h2 id="completionTitle">'
                     + ('Fallbacks by step' if entry.get('status') == 'preview' else 'Completion') + '</h2>'
                     '<p class="muted">Each step has alternates that are tried in order when an agent fails.</p><dl class="evidence-list">'
                     + ''.join('<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>' for k, v in guarantee) + '</dl></section>')
    if item['pearls']:
        parts.append('<section aria-labelledby="pearlsTitle"><h2 id="pearlsTitle">Agents used</h2><ul class="pearl-list">'
                     + ''.join(('<li><a href="/agent/' + esc(p['card'].rsplit('/', 1)[1]) + '">' + esc(p.get('role') or 'step') + '</a>'
                                if p.get('card') else '<li>' + esc(p.get('role') or 'step') + ' · AgentValCon agent')
                               + (' · ' + esc(p['tool']) if p.get('tool') else '')
                               + ' · <span class="necklace-member necklace-member-' + esc(p['standing'] or 'none') + '">'
                               + esc(MEMBER_LABELS.get(p['standing'], NOT_COUNTED)) + '</span>'
                               + (' · <span class="necklace-external-pending">' + esc(EXTERNAL_PENDING) + '</span>'
                                  if p.get('external_pending') else '') + '</li>' for p in item['pearls'])
                     + '</ul>' + ('<p class="muted necklace-provisional-note">' + esc(provisional_note(snapshot)) + '</p>'
                                  if any(p['standing'] == 'provisional' and p.get('card') for p in item['pearls']) else '')
                     + ''.join('<p class="muted necklace-own-note">' + esc(note) + '</p>' for note in dict.fromkeys(
                         own_checked_note(p, snapshot) if substitute_checked(p) else OWN_UNCHECKED_NOTE
                         for p in (entry.get('pearls') or []) if isinstance(p, dict) and p.get('kind') == 'agentcon'
                         and member_status(p) == 'provisional'))
                     + '</section>')
    if runs:
        example = example_input(entry)
        parts.insert(2 + (run is not None), '<section aria-labelledby="runTitle"><h2 id="runTitle">Run it</h2>'
                     + run_form(entry, esc, run[0] if run is not None else None)
                     + '<p class="caption">From an agent: MCP tool <code>' + esc(item['mcp_tool']) + '</code> on <code>' + esc(base)
                     + '/mcp</code>, or A2A skill <code>' + esc(item['a2a_skill']) + '</code>'
                     + ('; example arguments <code>' + esc(json.dumps(example, separators=(',', ':'))) + '</code>' if example else '')
                     + '.</p></section>')
    structured = {'@context': 'https://schema.org', '@type': 'SoftwareApplication', 'name': entry.get('name') or slug,
                  'applicationCategory': 'AI agent workflow', 'description': shown_summary(entry),
                  'url': base + '/necklaces/' + slug,
                  'isBasedOn': [p['card'] for p in item['pearls'] if p.get('card')],
                  'publisher': {'@type': 'Organization', 'name': 'AgentValCon', 'url': base + '/'}}
    return 200, shell(title=(entry.get('name') or slug) + ' — Necklace | AgentValCon',
                      description=shown_summary(entry), canonical=base + '/necklaces/' + slug,
                      body='<div class="pearl-page">' + ''.join(parts) + '</div>', structured=structured, index=runs)


def sitemap_paths(snapshot=None, now=None):
    open_now = live(snapshot, now)
    listed = open_now or [e for e in available(snapshot, now) if e.get('status') == 'preview']
    return (['/necklaces'] if listed else []) + ['/necklaces/' + e['slug'] for e in open_now]


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
    lines = ['\n## Necklaces you can run\n', WHY + '\n\n']
    for e in rows:
        q = e.get('quality') or {}
        lines.append('- ' + (e.get('name') or e['slug']) + ': ' + shown_summary(e)
                     + (' ' + single_line(q) if single_line(q) else '')
                     + ' MCP tool `' + tool_name(e['slug']) + '`, A2A skill `' + skill_id(e['slug']) + '`, page `'
                     + base + '/necklaces/' + e['slug'] + '`' + _input_note(e) + ('. Free to run for now' if free_now(e) else '')
                     + ('. ' + comparison_line(e) if comparison_line(e) else '')
                     + (' ' + pending_sentence(e) if pending_sentence(e) else '') + '\n')
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


DETAIL_PROPERTY = {'type': 'string', 'enum': ['full', 'brief'], 'default': 'full',
                   'description': 'full (default) or brief: the same facts, values and links in fewer tokens.'}


def with_detail(schema):
    """The necklace's input schema plus the optional response option detail (PM 11-17); the definition is unchanged."""
    schema = dict(schema or {'type': 'object'})
    schema['properties'] = dict(schema.get('properties') or {}, detail=DETAIL_PROPERTY)
    return schema


def tools(snapshot=None, now=None):
    """MCP tools for offered necklaces, plus necklace_details when there is at least one (none while nothing is live)."""
    rows = available(snapshot, now)
    if not rows:
        return []
    out = []
    for original in rows:
        e = {**public_view(original), 'slug': original['slug']}
        window = tested(e.get('quality') or {})
        claim = verified(e.get('quality') or {})
        evidence = (' Verified 95%: ' + str(claim[0]) + '/' + str(claim[1]) + ' cumulative retests passed.' if claim
                    else ' Recent tests: ' + str(window[0]) + '/' + str(window[1]) + ' passed.' if window else '')
        out.append({'name': tool_name(e['slug']), 'title': e.get('name') or e['slug'],
                    'description': ('Necklace (a workflow of tested agents: ' + members_phrase(e) + '): ' + shown_summary(e) + ' ' + WHY_SHORT + evidence
                                    + (' ' + comparison_line(e) if comparison_line(e) else '')
                                    + (' ' + pending_sentence(e) if pending_sentence(e) else '')
                                    + (' Scope: ' + scope_notice(e) if scope_notice(e) else '')
                                    + (' Example arguments: ' + json.dumps(example_input(e), separators=(',', ':')) + '.'
                                       if example_input(e) else '')
                                    + (' ' + FREE_NOW.replace('on this page', 'on its page') if free_now(e) else '')
                                    + ' ' + NOTICE_SENTENCE),
                    'inputSchema': with_detail(e.get('input_schema')),
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
    if not entry or not opened(entry):
        return None
    item = public_item(entry, base, now)
    lines = [item['name'] + ': ' + (item['summary'] or '') + (' ' + item['sources'] if item.get('sources') else '')]
    if 'notice' in item:
        lines.append(item['notice']['text'])
    for p in item['pearls']:
        own = p.get('kind') == 'agentcon'     # our own agent: no id and no card, only its role (public_member_id)
        lines.append('- ' + (p.get('role') or 'step') + ': ' + ('AgentValCon agent' if own else ('verified pearl ' if p.get('verified_pearl') else 'agent ') + str(p['agent_id']))
                     + ('' if p.get('verified_pearl') else ' (under verification)' if p.get('standing') else ' (not passing our member tests now)')
                     + ('' if own else ' (' + (p['card'] or 'AgentValCon agent') + ')') + ', alternates '
                     + str(p['alternates']['external']) + ' external + ' + str(p['alternates']['agentcon']) + ' AgentValCon'
                     + ('; ' + EXTERNAL_PENDING[0].lower() + EXTERNAL_PENDING[1:-1] if p.get('external_pending') else ''))
    return '\n'.join(lines), item


def call(front, name, arguments, source='mcp', base='https://agentconcierge.biz', snapshot=None, now=None, meta=None):
    """(text, structured, is_error) for a necklace tool call; runs nothing unless the necklace is offered and RUN is wired."""
    entry = entry_for_tool(name, snapshot)
    if entry is None or not opened(entry):
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
                  **({'notice': result['notice']} if result.get('notice') else {}),
                  **({'retry_after_s': result['retry_after_s']} if result.get('retry_after_s') else {})}, not ok


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
    for original in available(snapshot, now):
        e = public_view(original)
        example = 'run necklace ' + e['slug'] + ' ' + json.dumps(example_arguments(e.get('input_schema'), example_input(e)),
                                                                   separators=(',', ':'))
        out.append({'id': skill_id(e['slug']), 'name': e.get('name') or e['slug'],
                    'description': 'Necklace (a workflow of tested agents: ' + members_phrase(e) + '): ' + shown_summary(e) + ' ' + WHY_SHORT
                                   + (' ' + comparison_line(e) if comparison_line(e) else '')
                                   + (' ' + pending_sentence(e) if pending_sentence(e) else '')
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
    if entry is None or not opened(entry):
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
        if front is not None and not front.limit.allow(ip := front.security.resolve_ip(request)):
            # PM 11-17 08:5x: when to come back, in the header and (for agents) in the body
            wait = front.limit.retry_after(ip)
            from ..necklaces.service import note_refusal
            note_refusal(None, slug if SLUG.fullmatch(slug or '') else None, 'rate_limited', 'web_ip')
            return JSONResponse({'ran': False, 'error_code': 'rate_limited', 'retry_after_s': wait}, status_code=429,
                                headers={**headers, 'Retry-After': str(wait)})
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
        if structured.get('error_code') == 'rate_limited' and structured.get('retry_after_s'):
            headers['Retry-After'] = str(structured['retry_after_s'])   # HTTP 200 + ok:false stays for callers
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

    @router.get('/api/pearls/public', include_in_schema=False)
    def api_pearls():
        # PM 11-18: the verified pearls (final, verified) for the Explore card badge; one small list, no visitor data
        from . import pearl_badge
        return JSONResponse({'schema': 'agentcon-pearl-levels-v1', 'levels': pearl_badge.public_levels(),
                             'direct': pearl_badge.direct_ids(), 'direct_note': pearl_badge.DIRECT_NOTE,
                             'counts': pearl_badge.counts(), 'necklaces_live': live_count(), 'necklaces_preview': preview_count(),
                             'method': pearl_badge.METHOD_URL}, headers={'Cache-Control': 'public, max-age=60'})

    @router.get('/api/feed/necklaces.json', include_in_schema=False)
    def api_feed():
        return JSONResponse(feed(), media_type='application/feed+json', headers={'Cache-Control': 'public, max-age=60'})

    @router.get('/necklaces', include_in_schema=False)
    def necklaces_index(request: Request):
        from .growth_pages import PAGE_CSP
        base = front.base(request) if front is not None else 'https://agentconcierge.biz'
        return HTMLResponse(index_page(base), headers={'Content-Security-Policy': PAGE_CSP})

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

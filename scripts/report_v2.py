"""Test report v2: role task test with a content check, every outcome kept, a quality score, and the final pearl
ranking (PM pearl audit 11-14, design reports/report-v2-2026-11-14/README.md).

Stage 1 writes files only (exports/pearls, not in git); no database is written. A stacked version table in the
database is stage 2, after a rehearsal and approval.

    .venv/bin/python -m scripts.report_v2 import reports/pearls-2026-11-14/role_tests.json   # reuse calls already made
    .venv/bin/python -m scripts.report_v2 run reports/pearls-2026-11-14/role_candidates_1115.json
    .venv/bin/python -m scripts.report_v2 rank                                                 # ranking, role_groups, board
"""
import datetime as dt
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

OUT = ROOT / 'exports/pearls'
GROUPS = ROOT / 'reports/pearls-2026-11-14/role_groups.json'
RAG_TASKS = ROOT / 'agent_market/necklaces/role_tasks/role-tasks-rag-v1.jsonl'
SIGNING = ROOT / 'gateway-data/signing'        # 운영·SRE deploy/EVIDENCE_SIGNING.md: keys doc, <keyid>.pem, envelopes/
PRODUCTION_SIGNING = SIGNING


def signing_dir():
    """Where keys and envelopes live: SIGNING, or AGENTCON_SIGNING_DIR while SIGNING is the default (tests/conftest.py
    points every test run at a temporary folder; precision review R04, 11-15)."""
    import os
    if SIGNING == PRODUCTION_SIGNING and os.environ.get('AGENTCON_SIGNING_DIR'):
        return Path(os.environ['AGENTCON_SIGNING_DIR'])
    return SIGNING


def signing_allowed(folder):
    """Never sign into the production evidence folder from a test run (R04: from 11-17 the key exists)."""
    import os
    return not (os.environ.get('PYTEST_CURRENT_TEST') and Path(folder).resolve() == PRODUCTION_SIGNING.resolve())
METHODOLOGY_VERSION = 'v1'
BOARD = ROOT / 'logs/ops/status-board.md'
RULES = 'v2-2026-11-14'
# Evaluation rules version (current-state review 11-14 F01-F03, F10). Versions scored under different evaluator
# versions never count together as repeated successes; rescoring writes a score file per version, never over a version.
EVALUATOR_VERSION = 'dq-2026-11-15d'
from agent_market.necklaces import gate_rules  # noqa: E402  (운영·SRE 897baf3a: one source for the gate numbers)
PASS_MARK = gate_rules.REPORT_SCORE


def rank_rule():
    """The ranking rule in words, from the weights and pass mark the scoring code applies (R81, 11-15)."""
    return (f'quality score out of {sum(DQ.WEIGHTS.values()) + sum(DQ.EVIDENCE_WEIGHTS.values()) + DQ.WRITING_WEIGHT} '
            f'(data quality {sum(DQ.WEIGHTS.values())} + evidence {sum(DQ.EVIDENCE_WEIGHTS.values())} '
            f'+ report text {DQ.WRITING_WEIGHT}), one place per registrable domain; '
            f'ranked by the pass rate of the last {RECENT_DAYS} days\' role tasks; '
            f'#1 at {PASS_MARK}+ with at least {int(PEARL_PASS_RATE * 100)}% of them passed is the final pearl, '
            f'#2-#3 are external fallbacks')
CONFIRM_DAYS = 2            # PM 11-14: a final pearl needs successes on two different days; before that it is provisional
DAY = 86400
ROLE_DAILY_LIMIT = 120      # PM 11-14 (charter 0): 80 new candidates + 40 retests a day; 60 when refusals pass 5%
NEW_A_DAY, RETEST_A_DAY, FALLBACK_LIMIT = 80, 40, 60
# Our role names -> the workflow team's role task contracts (agent_market/necklaces/role_tasks, v1 11-14).
CASE_ROLE = {'papers.search': 'papers.search.v1', 'encyclopedia.summary': 'encyclopedia.summary.v1',
             'news.search': 'news.search.v1', 'package.advisories': 'package.advisories.v1',
             'package.metadata': 'package.health.v1', 'cve.kev': 'cve.exploited.v1', 'cve.record': 'cve.record.v1',
             'company.lookup': 'company.registry.v1', 'topic.answer': 'web.grounding.v1',
             'software.incident': 'software.incident.v1', 'website.ai_readiness': 'website.ai_readiness.v1',
             'country.indicator': 'country.indicator.v1', 'fx.rate': 'fx.rate.v1', 'weather.forecast': 'weather.forecast.v1',
             'events.search': 'events.search.v1'}


SHORT = {contract: short for short, contract in CASE_ROLE.items()}
import role_catalog  # noqa: E402
import data_quality as DQ  # noqa: E402
# Roles RAG judges with its default field/word checks until an answer set exists (PM 11-14: 30 roles by 11-21).
RAG_ROLES = {role for role, spec in role_catalog.ROLES.items() if spec.get('checks')}
ROLE_DOMAIN_V1 = {'domain.lookup.v1': 'internet', 'place.search.v1': 'travel', 'book.search.v1': 'reference',
                  'crypto.price.v1': 'finance', 'stock.quote.v1': 'finance', 'geocode.address.v1': 'maps',
                  'ip.lookup.v1': 'internet', 'timezone.time.v1': 'reference', 'dictionary.define.v1': 'reference',
                  'translate.text.v1': 'language', 'github.repo.v1': 'developer', 'holiday.calendar.v1': 'reference',
                  'sec.filings.v1': 'business', 'airport.lookup.v1': 'travel', 'unit.convert.v1': 'reference',
                  'earthquake.feed.v1': 'science', 'cve.record.v1': 'security', 'software.incident.v1': 'security',
                  'website.ai_readiness.v1': 'internet', 'web.grounding.v1': 'reference'}


def is_own_fallback(rid):
    """AgentValCon's own fallback agents use the id namespace avc:<agent_id> (PM 11-14, plan A): their versions,
    scores and signed chains are kept, but they never compete with external pearls (last in every chain)."""
    return isinstance(rid, str) and rid.startswith('avc:')


def _parity(rid, day):
    import zlib
    number = rid if isinstance(rid, int) else zlib.crc32(str(rid).encode('utf-8'))
    return (day + number) % 2


def canonical(role):
    """One list of role names (PM 11-14): the workflow team's contract ids (cve.exploited.v1), ours mapped onto them."""
    role = str(role or '')
    return CASE_ROLE.get(role, role if role.endswith('.v1') else role + '.v1')


def short(role):
    """The name role_tool_test and the default checks use (ROLE_VALUES, CHECKS)."""
    return SHORT.get(role, role[:-3] if role.endswith('.v1') else role)


def domain_of(role):
    return ROLE_DOMAIN.get(short(canonical(role))) or ROLE_DOMAIN_V1.get(canonical(role), 'other')


def known_roles():
    """Every role name in use: workflow contracts, workflow role tasks, and RAG's default-check roles."""
    names = {path.name[:-5] for path in (ROOT / 'agent_market/necklaces/contracts').glob('*.json')}
    try:
        from agent_market.necklaces import role_tasks
        names |= set(role_tasks.by_role())
    except Exception:
        pass
    return names | {canonical(r) for r in CASE_ROLE} | {canonical(r) for r in RAG_ROLES}


def quiet_now(now=None):
    """Outside the measurement windows (:55-:10 every hour, 03:50-05:10)."""
    t = time.localtime(now)
    minutes = t.tm_hour * 60 + t.tm_min
    return not (t.tm_min >= 55 or t.tm_min < 10 or 230 <= minutes < 310)


def role_tasks_rag():
    from agent_market.necklaces import role_tasks
    return role_tasks.load(RAG_TASKS) if RAG_TASKS.exists() else []


def case_for(role, day=None):
    """One role task for ROLE, rotating by day so every case is used over the week; None when the role has none."""
    try:
        from agent_market.necklaces import role_tasks
        cases = role_tasks.by_role().get(canonical(role), [])
        if not cases and RAG_TASKS.exists():      # 11-14: RAG's verified tasks for the roles without a workflow set
            cases = role_tasks.by_role(RAG_TASKS).get(canonical(role), [])
    except Exception:
        return None
    if not cases:
        return None
    day = int(time.strftime('%j')) if day is None else day
    # A rotating case (PM 11-15 10:24: a CVE added to KEV in the last 30 days, replaced weekly) is asked every other
    # day, so a stale copy meets it within two days; the fixed cases rotate on the days between.
    rotating = [c for c in cases if c.get('rotating')]
    fixed = [c for c in cases if not c.get('rotating')]
    if rotating and fixed:
        return rotating[(day // 2) % len(rotating)] if day % 2 == 0 else fixed[(day // 2) % len(fixed)]
    return cases[day % len(cases)]


def rotating_case(v):
    """True for a version tested on a rotating (weekly recent) case."""
    return bool(v.get('case_rotating')) or str(v.get('case_id') or '').startswith('kev-recent-')


def stale_answer(recent):
    """PM 11-15 10:24: the newest rotating-case version among a member's recent tasks missed the accurate answer
    (it does not know a recent KEV addition): a stale copy, never a pearl, whatever its other tasks."""
    rot = [x for x in recent if rotating_case(x)]
    if not rot:
        return False
    newest = max(rot, key=lambda x: float(x.get('tested') or 0))
    return not ((newest.get('data_quality') or {}).get('accuracy') or {}).get('points')

# The pearl's field comes from its role, not the catalog category (audit: a domain search filed under finance).
ROLE_DOMAIN = {'papers.search': 'research', 'encyclopedia.summary': 'reference', 'news.search': 'news',
               'package.advisories': 'security', 'package.metadata': 'developer', 'package.risk': 'security',
               'country.indicator': 'economics', 'fx.rate': 'finance', 'weather.forecast': 'weather',
               'events.search': 'events', 'cve.kev': 'security', 'company.lookup': 'business',
               'topic.answer': 'reference'}

YEAR = r'\b(?:19|20)\d{2}\b'
DATE = r'\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}\b'
NUMBER = r'(?<![\w.])\d+(?:[.,]\d+)?(?![\w.])'


def _arg(args, *names):
    for key, value in (args or {}).items():
        if any(name in key.lower() for name in names) and isinstance(value, str):
            return value
    return None


def _has(pattern, text):
    return bool(re.search(pattern, text, re.I))


def _mentions(value, text):
    return bool(value) and value.lower().split()[0] in text.lower()


# Default content checks per role until the workflow team's answer sets arrive (design section 1).
CHECKS = {
    'papers.search': [('title line', lambda t, a: _has(r'"?title"?\s*[:=]|^\s*[-*\d.]+\s+\S.{15,}', t) or len(t) > 200),
                      ('year or identifier', lambda t, a: _has(YEAR + r'|\b10\.\d{4,}/|arxiv', t))],
    'encyclopedia.summary': [('subject echoed', lambda t, a: _mentions(_arg(a, 'title', 'query', 'q', 'topic', 'page', 'term'), t)),
                             ('80+ characters of prose', lambda t, a: len(re.sub(r'\s+', ' ', t)) >= 80)],
    'news.search': [('a date', lambda t, a: _has(DATE + '|' + YEAR, t)), ('a headline line', lambda t, a: _has(r'#{1,4} \S|"title"|^\s*[-*]\s+\S.{15,}', t))],
    'package.advisories': [('package echoed', lambda t, a: _mentions(_arg(a, 'name', 'package', 'query', 'q', 'software', 'product') or 'lodash', t)),
                           ('advisory id or none stated', lambda t, a: _has(r'GHSA-|CVE-\d{4}-\d+|no (?:known )?vulnerabilit', t))],
    'package.metadata': [('package echoed', lambda t, a: _mentions(_arg(a, 'package', 'name', 'query', 'q') or 'react', t)),
                         ('version number', lambda t, a: _has(r'\b\d+\.\d+\.\d+\b', t))],
    'package.risk': [('repository echoed', lambda t, a: _has(r'react', t)), ('a score', lambda t, a: _has(r'score', t) and _has(NUMBER, t))],
    'country.indicator': [('country named', lambda t, a: _has(r'\bKOR\b|korea|\bUS\b|united states|' + re.escape(str(_arg(a, 'country', 'iso', 'code') or 'KOR')), t)),
                          ('a number', lambda t, a: _has(NUMBER, t)), ('a year', lambda t, a: _has(YEAR, t))],
    'fx.rate': [('both currencies', lambda t, a: _has(r'\bUSD\b', t) and _has(r'\bEUR\b', t)),
                ('a non-zero rate', lambda t, a: any(float(n.replace(',', '.')) > 0 for n in re.findall(r'\d+[.,]\d+', t)))],
    'weather.forecast': [('temperature', lambda t, a: _has(r'°|\btemp|\b-?\d+(?:\.\d+)?\s?(?:c|f)\b|celsius|fahrenheit', t)),
                         ('a day or date', lambda t, a: _has(DATE + r'|today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2}', t))],
    'events.search': [('an event line', lambda t, a: _has(r'"name"|^\s*[-*\d.]+\s+\S.{8,}|#{1,4} \S', t)),
                      ('a date', lambda t, a: _has(DATE + r'|\d{4}-\d{2}-\d{2}', t))],
    'cve.kev': [('CVE echoed', lambda t, a: _has(r'CVE-2021-44228', t) or _has(r'CVE-\d{4}-\d+', t)),
                ('severity, CVSS or KEV status', lambda t, a: _has(r'cvss|severity|critical|high|known exploited|\bkev\b', t))],
    'company.lookup': [('company echoed', lambda t, a: _has(r'apple', t)),
                       ('an identifier', lambda t, a: _has(r'\blei\b|\bcik\b|registration|registry|company number|ein|duns|address|incorporat', t))],
    'topic.answer': [('topic echoed', lambda t, a: _has(r'model context protocol|\bmcp\b', t)), ('a sentence', lambda t, a: len(t) >= 80)],
}


_REFERENCE = {}


def reference_value(url, ttl=600):
    """A public reference value (Coinbase spot, the last regular-market stock price), cached for ten minutes; None when unavailable."""
    hit = _REFERENCE.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = None
    try:
        # R16 (precision review, PM 11-15): through the shared outside-call ledger like every other answer-key read
        # (data_quality._fetch_json: 'reference_checks' share, 429 stops the domain for the day).
        data = DQ._fetch_json(url)
        if data is not None:
            if 'coinbase' in url:
                value = float(data['data']['amount'])
            elif 'finance/chart' in url:   # last regular-market price (Stooq's CSV page answered 'does not exist', 11-14)
                value = float(data['chart']['result'][0]['meta']['regularMarketPrice'])
    except Exception:
        value = None
    _REFERENCE[url] = (time.time(), value)
    return value


def within_reference(text, reference, tolerance):
    numbers = [float(n.replace(',', '')) for n in re.findall(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?', text or '')]
    return any(abs(n - reference) <= tolerance * reference for n in numbers if n > 0)


# Default checks written for the role catalog's own sample input (ICN, Pride and Prejudice, python.org, Apple, New
# York...). When the version ran a role task (case), these never judge it: the case's own expectation takes their
# place (ops/PM 11-15 14:2x, an LAX answer was checked for "Incheon").
SAMPLE_BOUND = {'react named', 'domain echoed', 'Paris', 'address or coordinates', 'author', 'bitcoin named',
                'AAPL named', 'latitude 38.89', 'longitude -77.03', '8.8.8.8 echoed', 'Google or AS15169', 'zone named',
                'word echoed', 'a definition', 'French greeting', 'Independence Day', 'Thanksgiving',
                'Apple or CIK 320193', 'Incheon', '16.09', 'repository echoed', 'both currencies', 'company echoed',
                'topic echoed'}


def absence_case(case):
    """A case whose right answer is that no record exists (sec-none-*, 운영·SRE 11-15 16:1x): it forbids record
    patterns (must_not_match), so the role's default checks, which look for a record (a form type, a company),
    are not asked of it; its answer set is the whole judgement."""
    return bool(((case or {}).get('expect') or {}).get('must_not_match'))


def judge(role, text, args, case=None, structured=None):
    checks = []
    rules = CHECKS.get(role) or [(name, lambda t, a, _p=pattern: _has(_p, t))
                                 for name, pattern in role_catalog.default_checks(canonical(role))]
    if case:
        from agent_market.necklaces import role_tasks
        rules = [] if absence_case(case) else [(name, rule) for name, rule in rules if name not in SAMPLE_BOUND]
        rules.append((f"answer set {case['case_id']}",
                      lambda t, a, _c=case: role_tasks.score(_c, t, structured)[0]))
    for name, rule in rules:
        try:
            passed = bool(rule(text or '', args or {}))
        except (ValueError, TypeError):
            passed = False
        checks.append({'check': name, 'passed': passed})
    live = role_catalog.live_spec(canonical(role))
    not_live = []
    if live and live.get('terms_ok') is False:
        # R16: a reference suspended until its terms are confirmed (Coinbase, Yahoo) is never called; the check is
        # recorded as not checked, the same way assess() gives it no accuracy points.
        not_live.append(live['reference'])
        checks.append({'check': 'within the public reference (not checked: reference suspended until its terms are confirmed)',
                       'passed': False})
    elif live:
        reference = reference_value(live['reference'])
        if reference is None:
            not_live.append(live['reference'])
            checks.append({'check': 'within the public reference (not checked: reference unavailable)', 'passed': False})
        else:
            checks.append({'check': f"within {int(live['tolerance'] * 100)}% of the public reference {reference:g}",
                           'passed': within_reference(text, reference, live['tolerance'])})
    out = {'rules': RULES, 'checks': checks, 'passed': sum(c['passed'] for c in checks), 'total': len(checks)}
    if not_live:
        out['not_checked_live'] = not_live
    return out


def registrable(host):
    host = (host or '').lower().strip('.')
    for platform in ('workers.dev', 'onrender.com', 'vercel.app', 'pages.dev', 'netlify.app', 'herokuapp.com', 'fly.dev',
                     'github.io', 'railway.app', 'deno.dev', 'run.app', 'replit.app', 'web.app', 'firebaseapp.com'):
        if host.endswith('.' + platform):
            return host[:-len(platform) - 1].split('.')[-1] + '.' + platform
    parts = host.split('.')
    if len(parts) >= 3 and parts[-2] in ('co', 'com', 'org', 'net', 'ac', 'gov') and len(parts[-1]) == 2:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


def latency_points(ms):
    if ms is None:
        return 0
    return 10 if ms <= 1000 else 8 if ms <= 2000 else 5 if ms <= 5000 else 2 if ms <= 10000 else 0


def report_text(r):
    """The English report body: what was sent, what came back, how the data was judged, and what was not."""
    dq = r.get('data_quality') or {}
    lines = [f"Role task test for {r['role']}: tool `{r['tool']}` was called once, read-only, "
             f"with arguments {json.dumps(r.get('arguments') or {}, ensure_ascii=False)}."]
    if r['outcome'] == 'succeeded':
        acc, fresh, comp = dq.get('accuracy', {}), dq.get('freshness', {}), dq.get('completeness', {})
        lines.append(f"It answered in {r.get('latency_ms')} ms. Accuracy checked against: {acc.get('source', 'none')} "
                     f"({'matched' if acc.get('points') else 'not matched'}). Data time: {fresh.get('newest') or 'not stated'} "
                     f"(rule: {fresh.get('rule')}). Blank fields: {comp.get('blanks', 0)}"
                     + (f" of {comp['fields']}" if comp.get('fields') else '') + '.')
    else:
        lines.append(f"Outcome: {r['outcome']} ({r.get('reason') or 'no reason given'}).")
    lines.append('Limits: one call with one input; accuracy is only claimed where an answer set or a public reference '
                 'at the same time was compared.')
    return ' '.join(lines)


def writing_points(r, text):
    """10 points: limits stated (4), the input disclosed (3), the accuracy source, data time and blanks named (3)."""
    share = DQ.WRITING_WEIGHT / 10
    points = 4 * share if 'Limits:' in text else 0
    points += 3 * share if r.get('arguments') is not None and 'arguments' in text else 0
    points += 3 * share if r['outcome'] != 'succeeded' or ('Accuracy checked against' in text and 'Data time' in text) else 0
    return round(points, 1)


def consistency_points(r, now):
    """5 when the same input on another day gave the same result (fixed facts: the same answer hash or accuracy)."""
    folder = version_dir(r['resource_id'], r['role'])
    today = time.strftime('%Y-%m-%d', time.localtime(r['tested']))
    for path in sorted(folder.glob('*.json'), reverse=True) if folder.exists() else []:
        try:
            v = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if v.get('tool') != r['tool'] or v.get('outcome') != 'succeeded' or v.get('arguments') != r.get('arguments'):
            continue
        if time.strftime('%Y-%m-%d', time.localtime(v['tested'])) == today:
            continue
        same_acc = (v.get('data_quality') or {}).get('accuracy', {}).get('points') == r['data_quality']['accuracy']['points']
        if DQ.FRESHNESS.get(r['role']) is None:
            return DQ.WEIGHTS['consistency'] if (v.get('response_hash') == r.get('response_hash') or same_acc) else 0
        return DQ.WEIGHTS['consistency'] if same_acc else 0
    return 0


def quality(r, success_days):
    """Data 60 + evidence 30 + report text 10 (PM 11-14 data quality decision)."""
    args = r.get('arguments')
    dq = r.get('data_quality') or {}
    if r['outcome'] == 'succeeded':
        data = {k: dq.get(k, {}).get('points', 0) for k in ('accuracy', 'freshness', 'completeness', 'clean', 'consistency')}
        full = DQ.EVIDENCE_WEIGHTS
        evidence = {'arguments': 0 if not args else (full['arguments'] / 2 if r.get('source') == 'collector message' else full['arguments']),
                    'repeat': min(full['repeat'], full['repeat'] / CONFIRM_DAYS * success_days), 'latency': DQ.latency_points(r.get('latency_ms'))}
    else:
        data = {k: 0 for k in ('accuracy', 'freshness', 'completeness', 'clean', 'consistency')}
        evidence = {'arguments': 0 if not args else DQ.EVIDENCE_WEIGHTS['arguments'], 'repeat': 0, 'latency': 0}
    text = report_text(r)
    write = writing_points(r, text)
    return {'score': round(sum(data.values()) + sum(evidence.values()) + write, 1), 'data': data,
            'evidence': evidence, 'writing': write, 'text': text}


def assess(r, text, structured, case):
    """Fill r['data_quality'] from the whole answer; an unclean answer fails the version (PM 11-14)."""
    import hashlib
    r['response_hash'] = hashlib.sha256((text or '').encode('utf-8')).hexdigest() if text else None
    r['evaluator_version'] = EVALUATOR_VERSION
    if r['outcome'] != 'succeeded':
        r['data_quality'] = {}
        return
    issues = DQ.clean_issues(text, role=r['role'])
    review = DQ.clean_review(text, role=r['role'])
    live = role_catalog.live_spec(r['role'])
    from agent_market.necklaces import role_tasks
    acc_points, source, reasons = DQ.accuracy(case, text, structured, live=live,
                                              live_value=reference_value(live['reference']) if live and live.get('terms_ok') is not False else None,
                                              role_tasks=role_tasks)
    fresh_points, rule, newest = DQ.freshness(r['role'], text, structured=structured, args=r.get('arguments'))
    comp_points, blanks, fields, comp_detail = DQ.completeness(text, structured, role=r['role'], args=r.get('arguments'))
    if comp_points is None:                     # a text answer: the share of the role's fact checks it passes
        j = r.get('judgement') or {}
        comp_points = (max(0, round(DQ.WEIGHTS['completeness'] * j['passed'] / j['total'] - 2 * blanks, 1))
                       if j.get('total') else 0)
        comp_detail += f" {j.get('passed', 0)}/{j.get('total', 0)}" if j.get('total') else ' (none for this role: unconfirmed)'
    r['data_quality'] = {'accuracy': {'points': acc_points, 'source': source, 'reasons': reasons},
                         'freshness': {'points': fresh_points, 'rule': rule, 'newest': newest},
                         'completeness': {'points': comp_points, 'blanks': blanks, 'fields': fields, 'detail': comp_detail},
                         'clean': {'points': 0 if issues else DQ.WEIGHTS['clean'], 'issues': issues, 'review': review}}
    r['data_quality']['consistency'] = {'points': consistency_points(r, time.time())}
    r['evaluator_version'] = EVALUATOR_VERSION
    if issues:
        r['outcome'], r['reason'] = 'failed', 'unclean answer: ' + ', '.join(issues)


def version_dir(rid, role):
    return OUT / 'reports' / str(rid) / canonical(role).replace('/', '_')


def migrate_names():
    """Move versions saved under the old short names (fx.rate) to the contract ids (fx.rate.v1), once."""
    for folder in list((OUT / 'reports').glob('*/*')) if (OUT / 'reports').exists() else []:
        target = folder.parent / canonical(folder.name)
        if not folder.is_dir() or target == folder:
            continue
        target.mkdir(exist_ok=True)
        for path in folder.glob('*.json'):
            v = json.loads(path.read_text())
            v['role'] = canonical(v['role'])
            (target / path.name).write_text(json.dumps(v, indent=1, ensure_ascii=False))
            path.unlink()
        folder.rmdir()


def kst_day(ts):
    import zoneinfo
    return dt.datetime.fromtimestamp(float(ts), zoneinfo.ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d')


_WORKFLOW_CASES = None


def answer_set(r, case=None):
    """Which answers judged the version: the workflow set, the RAG set or a same-time public reference (F01)."""
    global _WORKFLOW_CASES
    case_id = (case or {}).get('case_id') or r.get('case_id')
    if case_id:
        if _WORKFLOW_CASES is None:
            try:
                from agent_market.necklaces import role_tasks
                _WORKFLOW_CASES = {c['case_id'] for c in role_tasks.load()}
            except Exception:
                _WORKFLOW_CASES = set()
        return 'workflow:role-tasks-v1' if case_id in _WORKFLOW_CASES else 'rag:role-tasks-rag-v1'
    live = role_catalog.live_spec(r['role'])
    return 'live:' + str(live.get('reference')) if live else None


def qualification(v):
    """The contract a repeated success must share (F01): resource, role, tool, endpoint, tool definition, evaluator
    version and answer set."""
    return (v.get('tool'), v.get('endpoint'), v.get('tool_fingerprint'), v.get('evaluator_version'), v.get('answer_set'))


def qualifies(v, now):
    """A success that counts toward repetition: accurate, clean, tested in the last 7 days and not in the future."""
    dq = v.get('data_quality') or {}
    tested = float(v.get('tested') or 0)
    return (v.get('outcome') == 'succeeded' and bool((dq.get('accuracy') or {}).get('points'))
            and (dq.get('clean') or {}).get('points', DQ.WEIGHTS['clean']) > 0
            and tested <= now + 300 and now - tested <= 7 * DAY)


def load_version(path):
    """A stored version with its newest score file for the current evaluator version laid over it."""
    v = json.loads(path.read_text())
    score = path.parent / 'scores' / f'{path.stem}.{EVALUATOR_VERSION}.json'
    if score.exists():
        try:
            v.update(json.loads(score.read_text()))
        except (OSError, ValueError):
            pass
    v['_path'] = str(path)
    return v


def versions_of(rid, role):
    folder = version_dir(rid, role)
    out = []
    for path in sorted(folder.glob('*.json')) if folder.exists() else []:
        try:
            out.append(load_version(path))
        except (OSError, ValueError):
            continue
    return out


def success_days(rid, role, tool, now, extra=None, ref=None):
    """Different KST days with a qualifying success under REF's contract (the latest version of TOOL when REF is
    None). EXTRA is the time of REF itself while it is being saved. Earlier contracts are kept but never counted."""
    stored = [v for v in versions_of(rid, role) if v.get('tool') == tool]
    if ref is None:
        ref = max((v for v in stored if float(v.get('tested') or 0) <= now + 300),
                  key=lambda v: float(v.get('tested') or 0), default=None)    # a future-dated record never leads
        if ref is None:
            return 0
    key = qualification(ref)
    days = {kst_day(v['tested']) for v in stored if qualification(v) == key and qualifies(v, now)}
    if extra is not None and qualifies(ref, now):
        days.add(kst_day(extra))
    return len(days)


def attempt_id(result, now=None):
    """An immutable id of one test attempt (F10): the same attempt imported twice is the same id. A result without a
    start time uses the save time (R09), so two such failures are two attempts."""
    import hashlib
    started = result.get('started') or (time.time() if now is None else now)
    basis = {'id': result.get('id'), 'role': canonical(result.get('role')), 'tool': result.get('tool'),
             'started': repr(float(started)), 'endpoint': result.get('endpoint'),
             'arguments': result.get('arguments')}
    return result.get('attempt_id') or hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:24]


def write_new(path, text):
    """Write TEXT to PATH atomically and never over an existing file: temp file, fsync, hard link, directory fsync."""
    import os
    tmp = path.parent / f'.{path.name}.tmp-{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.link(tmp, path)                      # fails when PATH exists: a version is never overwritten
    finally:
        tmp.unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_replace(path, text):
    """Atomic replace for files that are meant to change (score files, signing envelopes are written once)."""
    import os
    tmp = path.parent / f'.{path.name}.tmp-{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class folder_lock:
    """One writer per (resource, role) folder while a version is numbered and stored (F10)."""
    def __init__(self, folder):
        self.path = folder / '.lock'

    def __enter__(self):
        import fcntl
        self.fh = open(self.path, 'a+')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        import fcntl
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def save_version(result, now=None):
    """One more immutable version for (resource, role); earlier versions stay and the same attempt is stored once."""
    now = time.time() if now is None else now
    tested = float(result.get('started') or now)
    aid = attempt_id(result, now)
    folder = version_dir(result['id'], result['role'])
    folder.mkdir(parents=True, exist_ok=True)
    with folder_lock(folder):
        same = sorted(folder.glob(f'*-{aid[:12]}.json'))
        if same:
            again = load_version(same[0])       # the same attempt again: nothing new is stored
            again.pop('_path', None)
            return again
        r = {'resource_id': result['id'], 'role': canonical(result['role']), 'domain': domain_of(result['role']),
             'tool': result['tool'], 'arguments': result.get('arguments'), 'outcome': result['outcome'],
             'reason': result.get('reason'), 'latency_ms': result.get('latency_ms'), 'http': result.get('http'),
             'excerpt': (result.get('excerpt') or '')[:1000], 'host': result.get('host'),
             'endpoint': result.get('endpoint'), 'tool_fingerprint': result.get('tool_fingerprint'),
             'fingerprint_version': result.get('fingerprint_version'),
             'registrable_domain': registrable(result.get('host')), 'source': result.get('source', 'role tool call'),
             'tested': tested, 'attempt_id': aid}
        case = result.get('case')
        text = result.get('full_text') or r['excerpt']
        r['judgement'] = judge(short(r['role']), text, r['arguments'], case, result.get('structured')) if r['outcome'] == 'succeeded' else \
            {'rules': RULES, 'checks': [], 'passed': 0, 'total': 0}
        if case:
            r['case_id'] = case['case_id']
            if case.get('rotating'):
                r['case_rotating'] = case['rotating']
        assess(r, text, result.get('structured'), case)
        r['evaluator_version'] = EVALUATOR_VERSION
        r['answer_set'] = answer_set(r, case)
        acc = (r.get('data_quality') or {}).get('accuracy', {})
        r['content_verdict'] = ('not run' if r['outcome'] != 'succeeded' else
                                'accurate' if acc.get('points') else 'no answer source' if acc.get('source', '').startswith('none')
                                else 'not accurate')
        earlier = [v for v in versions_of(r['resource_id'], r['role']) if v.get('tool') == r['tool'] and qualifies(v, now)]
        if any(qualification(v) != qualification(r) for v in earlier):
            r['revalidation'] = 'the tool contract, endpoint, evaluator or answer set changed; earlier successes are kept but not counted'
        r['version'] = len(list(folder.glob('*.json'))) + 1
        days = success_days(r['resource_id'], r['role'], r['tool'], now, extra=tested, ref=r)
        r['quality'] = quality(r, days)
        stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(tested))
        name = f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]', '_', r['tool'])[:60]}-{aid[:12]}"
        keep_answer(r, folder, name, result)
        r['signed_report'] = sign_version(r, case, name)
        write_new(folder / f'{name}.json', json.dumps(r, indent=1, ensure_ascii=False))
    return r


ANSWERS = 'answers'


def keep_answer(r, folder, name, result):
    """R11 (precision review): the whole answer the test judged (text up to role_tool_test's 20,000 characters and the
    structured content) is kept beside the version, so a later evaluator judges the same answer, not the 1,000-character
    excerpt. Immutable like the version; the version records its file and sha256."""
    import hashlib
    if not (result.get('full_text') or result.get('structured')):
        return
    body = json.dumps({'full_text': result.get('full_text') or '', 'structured': result.get('structured')},
                      ensure_ascii=False, sort_keys=True).encode()
    (folder / ANSWERS).mkdir(exist_ok=True)
    try:
        write_new(folder / ANSWERS / f'{name}.json', body.decode())
    except FileExistsError:
        pass
    r['answer_file'] = f'{ANSWERS}/{name}.json'
    r['answer_sha256'] = hashlib.sha256(body).hexdigest()


def stored_answer(path, v):
    """(full text, structured) kept for the version at PATH, or None when none was kept or it no longer matches."""
    import hashlib
    if not v.get('answer_file'):
        return None
    try:
        body = (Path(path).parent / v['answer_file']).read_bytes()
    except OSError:
        return None
    if hashlib.sha256(body).hexdigest() != v.get('answer_sha256'):
        return None
    answer = json.loads(body)
    return answer.get('full_text') or '', answer.get('structured')


def sign_score(v, path, fields):
    """R11: a score file is signed like a version (EVIDENCE_SIGNING.md): what was judged (the version file's and the
    kept answer's sha256), by which evaluator, and the verdict. None without a key."""
    import hashlib
    key = signing_key()
    if key is None or not signing_allowed(signing_dir()):
        return None
    from agent_market import evidence_signing as ES
    evidence = {'type': 'test_score', 'report': Path(path).stem, 'resource_id': v['resource_id'], 'role': v['role'],
                'tool': v.get('tool'), 'report_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                'answer_sha256': v.get('answer_sha256'),
                **{k: fields.get(k) for k in ('evaluator_version', 'outcome', 'content_verdict', 'verdict_basis', 'quality')}}
    folder = signing_dir() / 'envelopes' / 'test_score' / str(v['resource_id']) / v['role']
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f'{Path(path).stem}.{EVALUATOR_VERSION}.json'
    write_replace(out, json.dumps(ES.sign(evidence, key), indent=1))
    try:
        return str(out.relative_to(ROOT))
    except ValueError:
        return str(out)


def signing_key(now=None):
    """The private key of the newest key valid now whose PEM file exists (11-17 운영 키); None when there is none."""
    from datetime import datetime, timezone
    from agent_market import evidence_signing as ES
    folder = signing_dir()
    if not signing_allowed(folder):
        return None
    try:
        doc = json.loads((folder / 'agentvalcon-keys.json').read_text())
    except (OSError, ValueError):
        return None
    when = datetime.fromtimestamp(now or time.time(), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    revoked = {r.get('keyid') for r in doc.get('revoked', [])}
    for key in sorted(doc.get('keys', []), key=lambda k: k.get('not_before', ''), reverse=True):
        path = folder / f"{key.get('keyid')}.pem"
        if key.get('keyid') in revoked or not (key.get('not_before', '') <= when <= key.get('not_after', '')) or not path.exists():
            continue
        try:
            return ES.load_private_key(path)
        except Exception:
            return None
    return None


def version_status(r):
    """provisional / verified / none at signing time (charter 0): accuracy compared, 85+, and two different days."""
    acc = ((r.get('data_quality') or {}).get('accuracy') or {}).get('points')
    if r['outcome'] != 'succeeded' or not acc or r['quality']['score'] < PASS_MARK:
        return 'none'
    days = success_days(r['resource_id'], r['role'], r['tool'], time.time(), extra=r['tested'], ref=r)
    return 'verified' if days >= CONFIRM_DAYS else 'provisional'


def evidence_for(r, case):
    """The signed fields of a test_report (EVIDENCE_SIGNING.md 1, 22df08aa): no withheld answers, the response only as
    sha256; `prev` is added by sign_chained."""
    import hashlib
    dq = r.get('data_quality') or {}
    acc = dq.get('accuracy') or {}
    source = {'source': acc.get('source') or 'none'}
    if case:
        source['answer_set_sha256'] = hashlib.sha256(json.dumps(case, sort_keys=True).encode('utf-8')).hexdigest()
    newest = (dq.get('freshness') or {}).get('newest')
    age = None
    if newest:
        try:
            from datetime import datetime
            age = round((r['tested'] - datetime.fromisoformat(newest).timestamp()) / DAY, 2)
        except ValueError:
            age = None
    comp = dq.get('completeness') or {}
    clean = dq.get('clean') or {}
    return {'kind': 'test_report', 'resource_id': r['resource_id'], 'role': r['role'], 'tool': r['tool'],
            'endpoint': r.get('endpoint') or r.get('host'), 'tool_fingerprint': r.get('tool_fingerprint'),
            'fingerprint_version': r.get('fingerprint_version'),
            'report_version': r.get('version'), 'input': r.get('arguments') or {}, 'response_sha256': r.get('response_hash'),
            'outcome': r['outcome'],
            'score_items': {'data_quality': r['quality'].get('data'), 'evidence': r['quality'].get('evidence'),
                            'report_text': r['quality'].get('writing')},
            'total_score': r['quality']['score'], 'status': version_status(r),
            'data_quality': {'freshness_age_days': age, 'freshness_rule': (dq.get('freshness') or {}).get('rule'),
                             'blank_ratio': (round(comp['blanks'] / comp['fields'], 3) if comp.get('fields') else None),
                             'blank_fields': comp.get('blanks'),
                             'clean': ('failed: ' + ', '.join(clean['issues'])) if clean.get('issues') else
                                      ('passed' if clean else None)},
            'accuracy_source': source, 'data_as_of': newest, 'methodology_version': METHODOLOGY_VERSION,
            'tested_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(r['tested']))}


def sign_version(r, case, name=None):
    """The next link of the (resource, role) chain under gateway-data/signing/envelopes/test_report/<id>/<role>/
    <report_version>.json, failures included (a dropped version breaks verify_chain); None without a key."""
    key = signing_key()
    if key is None:
        return None
    from agent_market import evidence_signing as ES
    if not signing_allowed(signing_dir()):
        return None
    folder = signing_dir() / 'envelopes' / 'test_report' / str(r['resource_id']) / r['role']
    folder.mkdir(parents=True, exist_ok=True)
    earlier = sorted((p for p in folder.glob('*.json') if p.stem.isdigit()), key=lambda p: int(p.stem))
    previous = json.loads(earlier[-1].read_text()) if earlier else None
    envelope = ES.sign_chained(evidence_for(r, case), key, previous=previous)
    path = folder / f"{r.get('version')}.json"
    write_new(path, json.dumps(envelope, indent=1))
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)                     # a test's temporary signing folder


def import_fallbacks(folder=None):
    """Stack the own fallback agents' role-task results (에이전트 팀 writes exports/pearls/avc-results-<date>.json) as
    report v2 versions. The .imported mark beside each file lists the results already stacked (id, role, start time),
    so a file the team appends to later in the day adds only its new results."""
    folder = Path(folder or OUT)
    done = 0
    for path in sorted(folder.glob('avc-results-*.json')):
        mark = path.with_suffix('.imported')
        seen = set(mark.read_text().split('\n')) if mark.exists() else set()
        data = json.loads(path.read_text())
        added = []
        for result in data.get('results', []) if isinstance(data, dict) else data:
            key = f"{result.get('id')}|{result.get('role')}|{result.get('started')}"
            if key in seen or not is_own_fallback(result.get('id')) or \
                    result.get('outcome') not in ('succeeded', 'failed', 'skipped'):
                continue
            save_version(result)
            added.append(key)
            done += 1
        if added or not mark.exists():
            mark.write_text('\n'.join(sorted(seen | set(added))).strip() + '\n')
    return done


def previous_score(path):
    """The newest score file of the version at PATH written by another evaluator ({} when none)."""
    path = Path(path)
    files = [p for p in (path.parent / 'scores').glob(f'{path.stem}.*.json')
             if p.name != f'{path.stem}.{EVALUATOR_VERSION}.json'] if (path.parent / 'scores').exists() else []
    for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            fields = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        return {k: fields[k] for k in ('outcome', 'reason', 'data_quality', 'content_verdict', 'evaluator_version',
                                       'answer_set', 'judgement') if k in fields}
    return {}


def rescore():
    """Score every stored version again with the current evaluator. The version files stay as they are; each result
    goes to <folder>/scores/<version>.<EVALUATOR_VERSION>.json (F10: no overwrite) and is signed when a key exists.

    R11 (precision review, 11-15): a version is judged again only from the whole answer kept at test time
    (answers/<version>.json, sha256 checked). Without it (versions stored before R11, 158 of 280 on 11-15) the stored
    verdict is carried unchanged under the current evaluator and says so (verdict_basis); a 1,000-character excerpt
    never turns a failure into a success or a success into a failure again."""
    from agent_market.necklaces import role_tasks
    every = role_tasks.load() + (role_tasks.load(RAG_TASKS) if RAG_TASKS.exists() else [])
    cases = {c['case_id']: c for c in every}
    judged = []
    for path in sorted((OUT / 'reports').glob('*/*/*.json')) if (OUT / 'reports').exists() else []:
        try:
            v = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        case = cases.get(v.get('case_id'))
        v['role'] = canonical(v['role'])
        answer = stored_answer(path, v)
        if answer is not None:
            text, structured = answer
            if v.get('outcome') == 'failed' and str(v.get('reason', '')).startswith('unclean answer'):
                v['outcome'], v['reason'] = 'succeeded', None       # judged again below
            if v['outcome'] == 'succeeded':
                v['judgement'] = judge(short(v['role']), text, v.get('arguments'), case, structured)
            assess(v, text, structured, case)
            v['answer_set'] = answer_set(v, case)
            acc = (v.get('data_quality') or {}).get('accuracy', {})
            v['content_verdict'] = ('not run' if v['outcome'] != 'succeeded' else 'accurate' if acc.get('points')
                                    else 'no answer source' if acc.get('source', '').startswith('none') else 'not accurate')
            v['verdict_basis'] = 'judged again on the whole answer kept at test time'
        else:
            # The verdict in force is the newest earlier score file over the version. It is carried with its own
            # evaluator label, so successes judged by different evaluators still never count together (F01).
            v.update(previous_score(path))
            v['verdict_basis'] = (f"carried from {v.get('evaluator_version') or 'an earlier evaluator'}: the whole answer "
                                  'was not kept, so the verdict is not judged again (R11)')
            v.setdefault('answer_set', answer_set(v, case))
        folder = path.parent / 'scores'
        folder.mkdir(exist_ok=True)
        fields = {k: v.get(k) for k in ('outcome', 'reason', 'data_quality', 'content_verdict', 'evaluator_version',
                                         'answer_set', 'judgement', 'verdict_basis')}
        write_replace(folder / f'{path.stem}.{EVALUATOR_VERSION}.json', json.dumps(fields, indent=1, ensure_ascii=False))
        judged.append(path)
    now = time.time()
    for path in judged:                         # repetition reads every version under the same evaluator
        v = load_version(path)
        v['quality'] = quality(v, success_days(v['resource_id'], v['role'], v['tool'], now, ref=v))
        v['rescored'] = time.strftime('%Y-%m-%d %H:%M')
        score = path.parent / 'scores' / f'{path.stem}.{EVALUATOR_VERSION}.json'
        fields = json.loads(score.read_text())
        fields.update(quality=v['quality'], rescored=v['rescored'])
        fields['signed_score'] = sign_score(v, path, fields)
        write_replace(score, json.dumps(fields, indent=1, ensure_ascii=False))
    return len(judged)


def latest_versions():
    latest = {}
    for path in (OUT / 'reports').glob('*/*/*.json') if (OUT / 'reports').exists() else []:
        try:
            v = load_version(path)
        except (OSError, ValueError):
            continue
        v.pop('_path', None)
        v['role'] = canonical(v['role'])
        key = (v['resource_id'], v['role'], v['tool'])
        if key not in latest or v['tested'] > latest[key]['tested']:
            latest[key] = v
    return list(latest.values())


RECENT_DAYS = 7          # R12: a member is ranked on the role tasks it was given over the last week, not one day's case
PEARL_PASS_RATE = 0.5   # R12: #1 is a pearl when at least half of those recent tasks passed (85+ and accurate)


def passing(v):
    """A version that passed its task: succeeded, accuracy compared and met, and 85+."""
    acc = ((v.get('data_quality') or {}).get('accuracy') or {}).get('points')
    return v.get('outcome') == 'succeeded' and bool(acc) and (v.get('quality') or {}).get('score', 0) >= PASS_MARK


def recent_tasks(v, now=None):
    """The newest version per role task (case) of V's tool under V's evaluator over RECENT_DAYS (R12, precision
    review 11-15): the task rotates daily, so the latest version alone switched a #1 off one day in three."""
    now = time.time() if now is None else now
    newest = {}
    for x in versions_of(v['resource_id'], v['role']):
        if x.get('tool') != v.get('tool') or x.get('evaluator_version') != v.get('evaluator_version') or \
                not (now - RECENT_DAYS * DAY <= float(x.get('tested') or 0) <= now + 300):
            continue
        case = x.get('case_id') or ''
        if case not in newest or x['tested'] > newest[case]['tested']:
            newest[case] = x
    return list(newest.values()) or [v]


def rank(versions):
    """Per role: by the pass rate over the recent role tasks, then quality score; one place per registrable domain;
    #1 is the final pearl when at least half of its recent tasks passed at 85+ on two different days (R12)."""
    roles = defaultdict(list)
    for v in versions:
        if not is_own_fallback(v['resource_id']):          # own fallbacks never compete with external pearls
            roles[v['role']].append(v)
    out = {}
    now = time.time()
    for role, members in roles.items():
        # Ties (e.g. no answer source yet, accuracy 0 for all) go to the answer that passed more field checks for the
        # role, so a billing envelope (130453) does not lead a role over real advisories (47161).
        fit = lambda v: (v.get('judgement') or {}).get('passed', 0) / max(1, (v.get('judgement') or {}).get('total', 0))
        recent = {id(v): recent_tasks(v, now) for v in members}
        rate = lambda v: sum(1 for x in recent[id(v)] if passing(x)) / len(recent[id(v)])
        best = lambda v: max([x['quality']['score'] for x in recent[id(v)] if passing(x)] or [v['quality']['score']])
        members.sort(key=lambda v: (-rate(v), -v['quality']['score'], -fit(v), v.get('latency_ms') or 10 ** 9))
        seen, ranked = set(), []
        for v in members:
            entry = {k: v.get(k) for k in ('resource_id', 'tool', 'outcome', 'reason', 'latency_ms', 'host',
                                           'registrable_domain', 'arguments', 'content_verdict', 'version')}
            # PM 11-14: a version with no accuracy comparison (0 points) never appears on a pearl candidate screen.
            entry['pearl_screen'] = bool(((v.get('data_quality') or {}).get('accuracy') or {}).get('points'))
            entry.update(score=v['quality']['score'], domain=v['domain'], tested=time.strftime('%Y-%m-%d %H:%M', time.localtime(v['tested'])),
                         success_days=success_days(v['resource_id'], role, v['tool'], now),
                         recent_tasks=len(recent[id(v)]), recent_pass_rate=round(rate(v), 2), best_recent_score=best(v),
                         stale=stale_answer(recent[id(v)]))
            usable = (v['outcome'] == 'succeeded' or rate(v) > 0) and v['registrable_domain'] not in seen
            entry['rank'] = len([e for e in ranked if e['rank']]) + 1 if usable else None
            if usable:
                seen.add(v['registrable_domain'])
            ranked.append(entry)
        top = next((e for e in ranked if e['rank'] == 1), None)
        good = bool(top and top['best_recent_score'] >= PASS_MARK and top['recent_pass_rate'] >= PEARL_PASS_RATE
                    and not top['stale'])
        out[role] = {'domain': domain_of(role), 'members': ranked,
                     'final_pearl': top['resource_id'] if good and top['success_days'] >= CONFIRM_DAYS else None,
                     'provisional_pearl': top['resource_id'] if good and 1 <= top['success_days'] < CONFIRM_DAYS else None,
                     'fallbacks': [e['resource_id'] for e in ranked if e['rank'] in (2, 3)],
                     'needs_agentcon_fallback': len([e for e in ranked if e['rank'] and e['rank'] >= 2]) <= 1}
    return out


def refusal_note():
    """PM 11-14: provider refusals (429/403) of today's role tests; above 5% the limit goes back to 30."""
    try:
        import pearl_batch as PB
        state = PB.Pacer(state_dir=PB.STATE_DIR).state
        tests, refused = int(state.get('role_tests', 0)), int(state.get('refusals', 0))
    except Exception:
        return ''
    if not tests:
        return ''
    rate = 100 * refused / tests
    return f" · 오늘 역할 시험 {tests}건 중 제공자 거절 {refused}건({rate:.1f}%{', 5% 넘음 → 30건으로 되돌림' if rate > 5 else ''})"


SUMMARY = 'final/summary.json'   # PM 11-14 14:2x: the one file the board and the heartbeat read for pearl numbers


def summary(versions, ranked, candidates_a=None, now=None):
    """The official pearl numbers and how they are counted (PM 11-14 14:2x)."""
    own = [v for v in versions if is_own_fallback(v['resource_id'])]
    outside = [v for v in versions if not is_own_fallback(v['resource_id'])]
    ok = sum(v['outcome'] == 'succeeded' for v in outside)
    return {
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(now)),
        'rules': {'evaluator_version': EVALUATOR_VERSION, 'pass_mark': PASS_MARK, 'confirm_days': CONFIRM_DAYS,
                  'counted': 'the latest version of each (resource, role, tool), scored by the evaluator version above',
                  'excluded': "AgentValCon's own fallback agents (avc: ids) are counted only in own_fallbacks",
                  'final_pearl': 'rank 1 of a role at the pass mark with successes on two different KST days',
                  'provisional_pearl': 'rank 1 at the pass mark with one success day so far'},
        'candidates_grade_a': candidates_a,
        'reports': len(outside), 'succeeded': ok, 'failed': len(outside) - ok,
        'best_score': max((v['quality']['score'] for v in outside), default=0),
        'at_or_above_pass_mark': sum(v['quality']['score'] >= PASS_MARK for v in outside),
        'final_pearls': sum(1 for r in ranked.values() if r['final_pearl']),
        'provisional_pearls': sum(1 for r in ranked.values() if r.get('provisional_pearl')),
        'roles_ranked': len(ranked),
        'verified_pearls': verified(outside),
        'targets': TARGETS,
        'roles_needing_own_fallback': sorted(role for role, r in ranked.items() if r['needs_agentcon_fallback']),
        'own_fallbacks': {'versions': len(own),
                          'agents_at_or_above_pass_mark': len({v['resource_id'] for v in own if v['quality']['score'] >= PASS_MARK})},
    }


def funnel_line(s):
    """The board line, from the official numbers only."""
    at = time.strftime('%m-%d %H:%M', time.strptime(s['generated'][:19], '%Y-%m-%dT%H:%M:%S'))
    own = s['own_fallbacks']
    return (f"{at} 진주 깔때기(검색과 RAG, 공식 숫자 exports/pearls/{SUMMARY}, 평가 {s['rules']['evaluator_version']}, avc: 제외): "
            f"후보 A {s['candidates_grade_a'] if s['candidates_grade_a'] is not None else '?'} → "
            f"v2 보고서 {s['reports']}(성공 {s['succeeded']}·실패 {s['failed']}, 외부 최고 {s['best_score']:g}점) → "
            f"85점 이상 {s['at_or_above_pass_mark']} → 최종 진주 확정 {s['final_pearls']}·잠정 {s['provisional_pearls']}"
            f"(역할 {s['final_pearls'] + s['provisional_pearls']}/{s['roles_ranked']}, 확정은 서로 다른 날 2회 성공) · "
            f"검증 확정 {s['verified_pearls']} / 목표 {s['targets']['verified']}, 최종 진주 역할 {s['final_pearls']} / 목표 {s['targets']['roles']} · "
            f"외부 대체 1개 이하(AgentValCon 대체 필요): {', '.join(s['roles_needing_own_fallback']) or '없음'}"
            + (f" · 자체 대체 {own['agents_at_or_above_pass_mark']}개 85점 이상(순위·깔때기 제외)" if own['versions'] else ''))


def funnel(versions, ranked, candidates_a=None):
    return funnel_line(summary(versions, ranked, candidates_a))


def verified(versions):
    """Verified pearls (charter 0): latest version at 85+ with successes on two different days, any rank."""
    now = time.time()
    return sum(1 for v in versions if v['quality']['score'] >= PASS_MARK
               and success_days(v['resource_id'], v['role'], v['tool'], now) >= CONFIRM_DAYS)


def usable_pearls(versions, ranked, terms=None, now=None):
    """PM 11-15 14:32: pearls the workflow terms table lets a necklace run. The counts above keep their definition;
    this says how many of them are usable (terms not 'prohibits') and, for a role whose final pearl is prohibited, who
    the best usable member is and whether it would be a final pearl itself."""
    terms = member_terms() if terms is None else terms
    now = now or time.time()
    banned = lambda rid: terms.get(rid) == 'prohibits'
    # counted like verified(): one per latest version (a resource can be verified in two roles)
    verified_items = [(v['resource_id'], v['role']) for v in versions if v['quality']['score'] >= PASS_MARK
                      and success_days(v['resource_id'], v['role'], v['tool'], now) >= CONFIRM_DAYS]
    finals = {role: r['final_pearl'] for role, r in ranked.items() if r.get('final_pearl')}
    replaced = {}
    for role, rid in finals.items():
        if not banned(rid):
            continue
        best = next((m for m in sorted((m for m in ranked[role]['members'] if m.get('rank')), key=lambda m: m['rank'])
                     if not banned(m['resource_id'])), None)
        replaced[role] = {'prohibited': rid, 'usable_first': None if best is None else {
            'resource_id': best['resource_id'], 'tool': best['tool'], 'rank': best['rank'], 'score': best['score'],
            'best_recent_score': best['best_recent_score'], 'success_days': best['success_days'],
            'final_pearl_by_itself': bool(best['best_recent_score'] >= PASS_MARK and best['recent_pass_rate'] >= PEARL_PASS_RATE
                                          and not best['stale'] and best['success_days'] >= CONFIRM_DAYS)}}
    usable_roles = [role for role, rid in finals.items() if not banned(rid)]
    covered = usable_roles + [role for role, r in replaced.items() if (r['usable_first'] or {}).get('final_pearl_by_itself')]
    return {'rule': "usable = the member's terms in agent_market/necklaces/member_terms.json are not 'prohibits' "
                    "(allowed, silent or not yet checked)",
            'verified_prohibited': [{'resource_id': rid, 'role': role} for rid, role in verified_items if banned(rid)],
            'verified_usable': sum(1 for rid, _ in verified_items if not banned(rid)),
            'final_prohibited': replaced,
            'final_usable': len(usable_roles),
            'roles_with_a_usable_final_pearl': len(covered)}


DEFINITIONS = ROOT / 'agent_market/necklaces/definitions'
PROVISIONAL = 'final/provisional_members.json'
PROVISIONAL_MIN = 70     # PM 11-15 16:03 (user instruction d4670360): the floor for a provisional necklace member


def necklace_roles(folder=DEFINITIONS):
    """{role: [necklace ids]} for the roles the necklace definitions use."""
    out = {}
    for path in sorted(Path(folder).glob('*.json')):
        for role in sorted(set(re.findall(r'"([a-z_]+(?:\.[a-z_]+)+\.v\d+)"', path.read_text()))):
            out.setdefault(canonical(role), []).append(path.stem)
    return out


def resource_status(ids):
    """{resource id: (active, eval_grade, health_status)} for IDS, read only; None when the database cannot be read."""
    ids = sorted({i for i in ids if isinstance(i, int)})
    if not ids:
        return {}
    try:
        import psycopg
        dsn = (ROOT / 'gateway-data/postgres18/application.dsn').read_text().strip()
        with psycopg.connect(dsn, autocommit=True, options='-c default_transaction_read_only=on -c statement_timeout=20000') as c:
            rows = c.execute('SELECT id, active, eval_grade, health_status FROM public.resources WHERE id = ANY(%s)',
                             (ids,)).fetchall()
        return {r[0]: (r[1], r[2], r[3]) for r in rows}
    except Exception:
        return None


def provisional_members(status, terms=None, roles=None, now=None, versions=None):
    """PM 11-15 16:03: members a necklace may use until a pearl is found, per role the necklace definitions use.

    Floor: active now, read-only (every tested tool passed is_relay_safe_tool), terms not prohibits, and at least one
    role-task version in the last 7 days that succeeded, met the accuracy check and scored PROVISIONAL_MIN or more.
    Our own fallbacks (avc:) are listed apart. STATUS None means activity could not be read: nobody is listed then."""
    now = now or time.time()
    terms = member_terms() if terms is None else terms
    roles = necklace_roles() if roles is None else roles
    if versions is None:
        versions = []
        for path in (OUT / 'reports').glob('*/*/*.json') if (OUT / 'reports').exists() else []:
            try:
                versions.append(load_version(path))
            except (OSError, ValueError):
                continue
    best = {}
    for v in versions:
        role = canonical(v.get('role') or '')
        dq = v.get('data_quality') or {}
        score = (v.get('quality') or {}).get('score') or 0
        tested = float(v.get('tested') or 0)
        if role not in roles or v.get('outcome') != 'succeeded' or not (dq.get('accuracy') or {}).get('points') \
                or (dq.get('clean') or {}).get('points', 1) <= 0 or score < PROVISIONAL_MIN \
                or not (now - 7 * DAY <= tested <= now + 300):
            continue
        key = (v['resource_id'], role, v.get('tool'))
        b = best.setdefault(key, {'resource_id': v['resource_id'], 'role': role, 'tool': v.get('tool'),
                                  'best_score': 0, 'best_day': None, 'latest_day': None, 'passes': 0, 'cases': set()})
        b['passes'] += 1
        b['cases'].add(v.get('case_id'))
        if score > b['best_score']:
            b['best_score'], b['best_day'] = round(score, 1), kst_day(tested)
        b['latest_day'] = max(filter(None, (b['latest_day'], kst_day(tested))))
    out = {'generated': time.strftime('%Y-%m-%d %H:%M'), 'source': 'scripts/report_v2.py provisional_members',
           'rule': f'active now, read-only tool, terms not prohibits, one role-task pass with {PROVISIONAL_MIN}+ '
                   'and the accuracy check met in the last 7 days (PM 11-15 16:03)',
           'status_read': status is not None, 'roles': {}}
    for role, necklaces in sorted(roles.items()):
        members, own, left_out = [], [], []
        for b in sorted((b for b in best.values() if b['role'] == role), key=lambda b: (-b['best_score'], str(b['resource_id']))):
            row = {k: b[k] for k in ('resource_id', 'tool', 'best_score', 'best_day', 'latest_day', 'passes')}
            row['cases'] = sorted(c for c in b['cases'] if c)
            rid = b['resource_id']
            if is_own_fallback(rid):
                own.append(row); continue
            row['terms'] = terms.get(rid, 'unknown')
            st = (status or {}).get(rid)
            row['grade'] = st[1] if st else None
            if status is None:
                row['why_out'] = 'activity not read'
            elif not st or st[0] != 1:
                row['why_out'] = 'not active'
            elif row['terms'] == 'prohibits':
                row['why_out'] = 'terms prohibit'
            (left_out if row.get('why_out') else members).append(row)
        out['roles'][role] = {'necklaces': necklaces, 'members': members, 'own_fallbacks': own, 'left_out': left_out}
    out['roles_with_a_member'] = sum(1 for r in out['roles'].values() if r['members'])
    out['roles_without'] = sorted(role for role, r in out['roles'].items() if not r['members'])
    return out


def candidates_a():
    try:
        import psycopg
        dsn = (ROOT / 'gateway-data/postgres18/application.dsn').read_text().strip()
        with psycopg.connect(dsn, autocommit=True, options='-c default_transaction_read_only=on -c statement_timeout=20000') as c:
            return c.execute("""SELECT count(*) FROM public.resources WHERE active=1 AND eval_grade='A' AND health_status='healthy'
                AND COALESCE(eval_security,'') NOT IN ('quarantine','review')""").fetchone()[0]
    except Exception:
        return None


def resource_grades(ids):
    """{resource id: eval_grade} for IDS, read only; None when the database cannot be read (nothing is split then)."""
    ids = sorted({i for i in ids if isinstance(i, int)})
    if not ids:
        return {}
    try:
        import psycopg
        dsn = (ROOT / 'gateway-data/postgres18/application.dsn').read_text().strip()
        with psycopg.connect(dsn, autocommit=True, options='-c default_transaction_read_only=on -c statement_timeout=20000') as c:
            return dict(c.execute('SELECT id, eval_grade FROM public.resources WHERE id = ANY(%s)', (ids,)).fetchall())
    except Exception:
        return None


def grade_trials(versions, grades, now=None):
    """PM 11-15 14:19 (ga): non-A members are tested but never counted as pearls (the pearl candidate stays active
    grade A). 85+ marks a grade re-evaluation; 85+ on two different days while still not A is a case where the grade
    misses real quality, listed for the PM."""
    now = now or time.time()
    out = {'rule': 'tested, not counted: a pearl candidate is active grade A; 85+ asks for a grade re-evaluation',
           'versions': len(versions), 'reevaluate': [], 'passed_twice_not_a': []}
    for v in versions:
        if v['quality']['score'] < PASS_MARK:
            continue
        days = success_days(v['resource_id'], v['role'], v['tool'], now)
        item = {'resource_id': v['resource_id'], 'grade': grades.get(v['resource_id']), 'role': v['role'],
                'tool': v['tool'], 'score': v['quality']['score'], 'success_days': days}
        out['reevaluate'].append(item)
        if days >= CONFIRM_DAYS:
            out['passed_twice_not_a'].append(item)
    return out


def write_board(line):
    lines = BOARD.read_text(encoding='utf-8').split('\n')
    at = [i for i, l in enumerate(lines) if l.startswith('## 넘기는 일')]
    if len(at) == 1:
        lines.insert(at[0] + 1, '- ' + line)
        BOARD.write_text('\n'.join(lines), encoding='utf-8')


TARGETS = {'verified': 200, 'roles': 30}   # 11-28 (charter 0, PM 11-14); 12-26: 1,000 and 100


def publish(board=True):
    migrate_names()
    versions = latest_versions()
    grades = resource_grades(v['resource_id'] for v in versions)
    trials = [v for v in versions if grades and not is_own_fallback(v['resource_id'])
              and grades.get(v['resource_id']) not in (None, 'A')]
    versions = [v for v in versions if not any(v is t for t in trials)]
    ranked = rank(versions)
    day = time.strftime('%Y-%m-%d')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'scores-{day}.json').write_text(json.dumps(
        [{k: v[k] for k in ('resource_id', 'role', 'tool', 'outcome', 'content_verdict', 'version')} | {'quality': v['quality']}
         for v in versions], indent=1, ensure_ascii=False))
    (OUT / f'final-{day}.json').write_text(json.dumps(ranked, indent=1, ensure_ascii=False))
    # Keep the fields the workflow team reads (11-14: id, name, coverage) from the first cut of role_groups.json.
    known = {}
    try:
        for role in json.loads(GROUPS.read_text()).get('roles', {}).values():
            for m in role.get('members', []):
                known[m.get('id', m.get('resource_id'))] = {k: m[k] for k in ('name', 'coverage') if m.get(k)}
    except (OSError, ValueError, AttributeError):
        pass
    for role in ranked.values():
        for m in role['members']:
            m['id'] = m['resource_id']
            m.update(known.get(m['resource_id'], {}))
            m.setdefault('coverage', 'not stated')
    GROUPS.write_text(json.dumps({'generated': time.strftime('%Y-%m-%d %H:%M'), 'source': 'scripts/report_v2.py (role task test v2)',
                                  'rank_rule': rank_rule(),
                                  'roles': ranked}, indent=1, ensure_ascii=False))
    official = summary(versions, ranked, candidates_a())
    official['usable'] = usable_pearls(versions, ranked)
    official['grade_trials'] = grade_trials(trials, grades or {}) if grades is not None else \
        {'rule': 'grades unavailable: nothing split this time', 'versions': None}
    (OUT / 'final').mkdir(parents=True, exist_ok=True)
    write_replace(OUT / SUMMARY, json.dumps(official, indent=1, ensure_ascii=False))
    try:
        found = provisional_members(None)                       # first pass only gathers the ids to read
        ids = {m['resource_id'] for r in found['roles'].values() for m in r['left_out']}
        write_replace(OUT / PROVISIONAL, json.dumps(provisional_members(resource_status(ids)), indent=1, ensure_ascii=False))
    except Exception as e:                                       # the pearl numbers above never wait on this list
        print('provisional members not written:', e)
    line = funnel_line(json.loads((OUT / SUMMARY).read_text())) + refusal_note()   # the board reads the file only
    if board:
        write_board(line)
    return line


# Precision review R08 (11-15): a skip for our own reason is not a test of the provider; it is not stored and the
# candidate stays in the queue. A failed member is tried again after 1, 2 and then 4 days instead of leaving for good.
OUR_SIDE_SKIPS = ('provider limit for today',)
FAILURE_BACKOFF_DAYS = (1, 2, 4)


def our_side_skip(result):
    return result.get('outcome') == 'skipped' and str(result.get('reason') or '') in OUR_SIDE_SKIPS


def failures_in_a_row(rid, role, tool):
    count = 0
    for v in sorted(versions_of(rid, role), key=lambda v: float(v.get('tested') or 0), reverse=True):
        if v.get('tool') != tool:
            continue
        if v.get('outcome') == 'succeeded':
            break
        count += 1
    return count


def failure_due(v, now):
    """A failed latest version comes back after 1, 2, then 4 days (by failures in a row)."""
    if v.get('outcome') == 'succeeded' or is_own_fallback(v['resource_id']):
        return False
    streak = failures_in_a_row(v['resource_id'], v['role'], v['tool'])
    wait = FAILURE_BACKOFF_DAYS[min(max(streak, 1), len(FAILURE_BACKOFF_DAYS)) - 1]
    return now - float(v.get('tested') or 0) >= wait * DAY - 3600       # an hour's slack for the daily start time


CONFIRMED_RETEST_DAYS = (0, 3)   # R18: a confirmed pearl is tested again twice a week, by its own weekday offset


def retest_queue(versions, day=None, limit=RETEST_A_DAY, now=None):
    """Today's retests, most useful first (R18, precision review 11-15: 40 a day capped confirmations at about 40):
    1. any member at 85+ with one success day, whatever its rank (the second day confirms it), best score first;
    2. ranks 1-2 every day and 3-5 every other day, while not confirmed;
    3. confirmed members twice a week;
    4. failed members whose backoff has passed (R08)."""
    import zlib
    day = int(time.strftime('%j')) if day is None else day
    now = time.time() if now is None else now
    second, ranked, confirmed = [], [], []
    for role, entry in sorted(rank(versions).items()):
        for m in entry['members']:
            if not m['rank']:
                continue
            c = {'role': role, 'id': m['resource_id'], 'tool': m['tool'], 'kind': 'retest', 'rank': m['rank']}
            days = m.get('success_days') or 0
            if days >= CONFIRM_DAYS:
                number = m['resource_id'] if isinstance(m['resource_id'], int) else zlib.crc32(str(m['resource_id']).encode())
                if (day + number) % 7 in CONFIRMED_RETEST_DAYS:
                    confirmed.append(c)
            elif days == CONFIRM_DAYS - 1 and (m.get('best_recent_score') or m.get('score') or 0) >= PASS_MARK:
                second.append((-(m.get('best_recent_score') or m.get('score') or 0), m['rank'], c))
            elif m['rank'] <= 2 or (m['rank'] <= 5 and _parity(m['resource_id'], day) == 0):
                ranked.append(c)
    out = [c for _, _, c in sorted(second, key=lambda t: (t[0], t[1]))] + sorted(ranked, key=lambda c: c['rank']) + \
        sorted(confirmed, key=lambda c: c['rank'])
    failed = [{'role': v['role'], 'id': v['resource_id'], 'tool': v['tool'], 'kind': 'retest', 'rank': None, 'after_failure': True}
              for v in sorted(versions, key=lambda v: float(v.get('tested') or 0)) if failure_due(v, now)]
    return (out + failed)[:limit]


def catalog_candidates():
    """(role, id, tool, host) for every active A, healthy, relay-safe MCP tool whose name fits a role (read only)."""
    import psycopg
    from agent_market.collector.usage import is_relay_safe_tool
    dsn = (ROOT / 'gateway-data/postgres18/application.dsn').read_text().strip()
    found = []
    with psycopg.connect(dsn, autocommit=True, options='-c default_transaction_read_only=on -c statement_timeout=60000') as c:
        for rid, host, tools in c.execute("""SELECT id, host, usage_tools FROM public.resources WHERE active=1 AND kind='mcp'
                AND eval_grade='A' AND health_status='healthy' AND COALESCE(eval_security,'') NOT IN ('quarantine','review')
                AND usage_tools IS NOT NULL"""):
            try:
                tools = json.loads(tools)
            except (TypeError, ValueError):
                continue
            for tool in tools if isinstance(tools, list) else []:
                if isinstance(tool, dict) and tool.get('name') and is_relay_safe_tool({**tool, 'required': tool.get('required') or []}):
                    for role in role_catalog.roles_for_tool(tool['name']):
                        found.append((role, rid, tool['name'], host))
    return found


# PM 11-15 09:5x: the first necklace candidate's four roles have no verified pearl yet; their untested candidates go
# first (several a round), still one per registrable domain in a role and 3 per host.
# PM 11-15 13:53: the roles whose next pearl opens a necklace, in this order (workflow readiness table). Earlier in
# the tuple = earlier in every round; each gets PRIORITY_PICKS a round, the other roles one each after them.
# PM 14:22: web.grounding second (Pipeworx 50972 left topic-evidence-brief's required web seat on terms).
# PM 11-15 16:07: demand order from the outside survey (reports/necklace-demand-2026-11-15), replacing 13:53's.
PRIORITY_ROLES = ('company.registry.v1', 'encyclopedia.summary.v1', 'sec.filings.v1', 'domain.lookup.v1',   # 1 due diligence
                  'web.grounding.v1', 'papers.search.v1',                                              # 2 topic brief
                  'cve.exploited.v1', 'cve.record.v1',                                                 # 3 CVE brief
                  'package.advisories.v1', 'package.health.v1',                                        # 4 package risk
                  'github.repo.v1', 'package.risk.v1', 'news.search.v1',                               # 5 new necklaces
                  'website.ai_readiness.v1', 'timezone.time.v1', 'holiday.calendar.v1')                # 6 after
PRIORITY_PICKS = 4


TERMS_FILE = ROOT / 'agent_market/necklaces/member_terms.json'
TERMS_RANK = {'allowed': 0, 'silent': 1}     # PM 14:22: allowed or silent terms first, unknown after, prohibits never


def member_terms(path=TERMS_FILE):
    """{resource id: terms status} from the workflow team's terms table ({} when it cannot be read)."""
    try:
        members = json.loads(Path(path).read_text()).get('members') or {}
        return {int(k): str((v or {}).get('status')) for k, v in members.items() if str(k).isdigit()}
    except (OSError, ValueError, AttributeError):
        return {}


def new_queue(versions, candidates, seeds=(), limit=NEW_A_DAY, per_host=3, priority=PRIORITY_ROLES, terms=None):
    """Untested members, priority roles first (PRIORITY_PICKS a round each), then roles with the fewest successes,
    one per registrable domain in a role, 3 per host."""
    # A stored skip for our own reason (before R08 such skips were saved) never counts as tested.
    tested = {(v['resource_id'], v['tool']) for v in versions if not our_side_skip(v)}
    successes = Counter(v['role'] for v in versions if v['outcome'] == 'succeeded')
    taken_domains = defaultdict(set)
    for v in versions:
        taken_domains[v['role']].add(v['registrable_domain'])
    pools = defaultdict(list)
    for seed in seeds:
        pools[canonical(seed['role'])].append((seed['id'], seed['tool'], seed.get('host')))
    for role, rid, tool, host in candidates:
        pools[role].append((rid, tool, host))
    terms = member_terms() if terms is None else terms
    for role in pools:      # stable: seeds stay ahead of catalog members with the same terms status
        pools[role] = sorted((m for m in pools[role] if terms.get(m[0]) != 'prohibits'),
                             key=lambda m: TERMS_RANK.get(terms.get(m[0]), 2))
    hosts, out = Counter(), []
    order = {role: i for i, role in enumerate(priority)}
    roles = sorted(pools, key=lambda role: (order.get(role, len(order)), successes[role], role))
    while len(out) < limit and any(pools.values()):
        for role in [r for r in roles for _ in range(PRIORITY_PICKS if r in priority else 1)]:
            while pools[role]:
                rid, tool, host = pools[role].pop(0)
                domain = registrable(host) if host else None
                if (rid, tool) in tested or (domain and domain in taken_domains[role]) or (host and hosts[host] >= per_host):
                    continue
                tested.add((rid, tool))
                if domain:
                    taken_domains[role].add(domain)
                if host:
                    hosts[host] += 1
                out.append({'role': role, 'id': rid, 'tool': tool, 'kind': 'new'})
                break
            if len(out) >= limit:
                break
    return out


def build_queue(seed_file=ROOT / 'reports/pearls-2026-11-14/role_candidates_1115.json'):
    versions = latest_versions()
    try:
        seeds = json.loads(Path(seed_file).read_text())
    except (OSError, ValueError):
        seeds = []
    terms = member_terms()
    retests = [x for x in retest_queue(versions) if terms.get(x['id']) != 'prohibits']   # never call a member whose terms forbid it
    return retests + new_queue(versions, catalog_candidates(), seeds, terms=terms)


def run(queue):
    """Role tests for QUEUE within today's limits: 80 new + 40 retests, 120 in all, 60 after refusals pass 5%.
    Returns today's own errors: tests our code could not run and results it could not store (R15)."""
    import httpx
    import pearl_batch as PB
    from role_tool_test import resources, test_one
    pacer = PB.Pacer(state_dir=PB.STATE_DIR, system='role_tests')
    for key in ('role_tests', 'refusals', 'new_tests', 'retests'):
        pacer.state.setdefault(key, 0)
    found = resources({c['id'] for c in queue})
    errors = {'our_errors': 0, 'save_errors': 0}
    with httpx.Client(follow_redirects=False) as http:
        for candidate in queue:
            tests = pacer.state['role_tests']
            limit = FALLBACK_LIMIT if tests >= 20 and pacer.state['refusals'] * 100 > 5 * tests else ROLE_DAILY_LIMIT
            if tests >= limit:
                break
            kind = 'retests' if candidate.get('kind') == 'retest' else 'new_tests'
            if pacer.state[kind] >= (RETEST_A_DAY if kind == 'retests' else NEW_A_DAY):
                continue
            while not quiet_now():
                time.sleep(30)
            candidate = {**candidate, 'role': short(canonical(candidate['role'])) if canonical(candidate['role']) in SHORT else
                         canonical(candidate['role']), 'case': case_for(candidate['role'])}
            try:
                result = test_one(http, candidate, found.get(candidate['id'], {}), pacer)
            except Exception as error:          # our own bug never stops the day's run (11-14 09:12 RecursionError)
                print(f"role test skipped, our error: {candidate['id']} {candidate['role']} {type(error).__name__}",
                      file=sys.stderr)
                pacer.state['our_errors'] = int(pacer.state.get('our_errors', 0)) + 1
                errors['our_errors'] += 1
                pacer.save()
                continue                        # not the provider's failure: no version is stored
            if not (result.get('outcome') == 'skipped' and 'limit' in str(result.get('reason'))):
                pacer.state['role_tests'] += 1
                pacer.state[kind] += 1
            if result.get('http') in (403, 429) or str(result.get('reason', '')).endswith(('HTTP 429', 'HTTP 403')):
                pacer.state['refusals'] += 1
            pacer.save()
            if our_side_skip(result):
                continue                        # R08: not stored; the candidate stays in tomorrow's queue
            if not save_once_more(result):      # R15: one candidate's storage error never stops the day's run
                errors['save_errors'] += 1
                pacer.state['save_errors'] = int(pacer.state.get('save_errors', 0)) + 1
                pacer.save()
    return errors


def save_once_more(result, wait=1.0):
    """save_version with one retry (it is idempotent by attempt_id); False, logged, when both fail (R15)."""
    for attempt in (1, 2):
        try:
            save_version(result)
            return True
        except Exception as error:
            print(f"role test not stored ({attempt}/2): {result.get('id')} {result.get('role')} {type(error).__name__}",
                  file=sys.stderr)
            if attempt == 1:
                time.sleep(wait)
    return False


def main(argv=None):
    argv = argv or sys.argv[1:]
    if argv[0] == 'import':
        for result in json.loads(Path(argv[1]).read_text()).get('results', []):
            if result.get('outcome') in ('succeeded', 'failed', 'skipped'):
                save_version(result)
    elif argv[0] == 'import-fallbacks':
        import_fallbacks()
    elif argv[0] == 'rescore':
        rescore()
    elif argv[0] == 'queue':
        Path(argv[1]).write_text(json.dumps(build_queue(), indent=1))
    elif argv[0] == 'run':
        run(json.loads(Path(argv[1]).read_text()))
    print(publish(board='--no-board' not in argv))


if __name__ == '__main__':
    main()

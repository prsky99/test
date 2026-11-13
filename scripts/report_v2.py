"""Test report v2: role task test with a content check, every outcome kept, a quality score, and the final pearl
ranking (PM pearl audit 11-14, design reports/report-v2-2026-11-14/README.md).

Stage 1 writes files only (exports/pearls, not in git); no database is written. A stacked version table in the
database is stage 2, after a rehearsal and approval.

    .venv/bin/python -m scripts.report_v2 import reports/pearls-2026-11-14/role_tests.json   # reuse calls already made
    .venv/bin/python -m scripts.report_v2 run reports/pearls-2026-11-14/role_candidates_1115.json
    .venv/bin/python -m scripts.report_v2 rank                                                 # ranking, role_groups, board
"""
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
METHODOLOGY_VERSION = 'v1'
BOARD = ROOT / 'logs/ops/status-board.md'
RULES = 'v2-2026-11-14'
from agent_market.necklaces import gate_rules  # noqa: E402  (운영·SRE 897baf3a: one source for the gate numbers)
PASS_MARK = gate_rules.REPORT_SCORE
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
    return cases[day % len(cases)]

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
        import httpx
        resp = httpx.get(url, timeout=10, headers={'User-Agent': 'AgentConcierge-Verification/1.0'})
        if resp.status_code == 200:
            if 'coinbase' in url:
                value = float(resp.json()['data']['amount'])
            elif 'finance/chart' in url:   # last regular-market price (Stooq's CSV page answered 'does not exist', 11-14)
                value = float(resp.json()['chart']['result'][0]['meta']['regularMarketPrice'])
    except Exception:
        value = None
    _REFERENCE[url] = (time.time(), value)
    return value


def within_reference(text, reference, tolerance):
    numbers = [float(n.replace(',', '')) for n in re.findall(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?', text or '')]
    return any(abs(n - reference) <= tolerance * reference for n in numbers if n > 0)


def judge(role, text, args):
    checks = []
    rules = CHECKS.get(role) or [(name, lambda t, a, _p=pattern: _has(_p, t))
                                 for name, pattern in role_catalog.default_checks(canonical(role))]
    for name, rule in rules:
        try:
            passed = bool(rule(text or '', args or {}))
        except (ValueError, TypeError):
            passed = False
        checks.append({'check': name, 'passed': passed})
    live = role_catalog.live_spec(canonical(role))
    not_live = []
    if live:
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
    if r['outcome'] != 'succeeded':
        r['data_quality'] = {}
        return
    issues = DQ.clean_issues(text)
    live = role_catalog.live_spec(r['role'])
    from agent_market.necklaces import role_tasks
    acc_points, source, reasons = DQ.accuracy(case, text, structured, live=live,
                                              live_value=reference_value(live['reference']) if live and live.get('terms_ok') is not False else None,
                                              role_tasks=role_tasks)
    fresh_points, rule, newest = DQ.freshness(r['role'], text)
    comp_points, blanks, fields = DQ.completeness(text, structured)
    r['data_quality'] = {'accuracy': {'points': acc_points, 'source': source, 'reasons': reasons},
                         'freshness': {'points': fresh_points, 'rule': rule, 'newest': newest},
                         'completeness': {'points': comp_points, 'blanks': blanks, 'fields': fields},
                         'clean': {'points': 0 if issues else DQ.WEIGHTS['clean'], 'issues': issues}}
    r['data_quality']['consistency'] = {'points': consistency_points(r, time.time())}
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


def success_days(rid, role, tool, now, extra=None):
    days = set()
    for path in sorted(version_dir(rid, role).glob('*.json')) if version_dir(rid, role).exists() else []:
        try:
            v = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if v.get('tool') == tool and v.get('outcome') == 'succeeded' and now - float(v.get('tested', 0)) <= 7 * DAY:
            days.add(time.strftime('%Y-%m-%d', time.localtime(float(v['tested']))))
    if extra:
        days.add(time.strftime('%Y-%m-%d', time.localtime(extra)))
    return len(days)


def save_version(result, now=None):
    """One more version for (resource, role); earlier versions stay."""
    now = time.time() if now is None else now
    tested = float(result.get('started') or now)
    r = {'resource_id': result['id'], 'role': canonical(result['role']), 'domain': domain_of(result['role']),
         'tool': result['tool'], 'arguments': result.get('arguments'), 'outcome': result['outcome'],
         'reason': result.get('reason'), 'latency_ms': result.get('latency_ms'), 'http': result.get('http'),
         'excerpt': (result.get('excerpt') or '')[:1000], 'host': result.get('host'),
         'endpoint': result.get('endpoint'), 'tool_fingerprint': result.get('tool_fingerprint'),
         'fingerprint_version': result.get('fingerprint_version'),
         'registrable_domain': registrable(result.get('host')), 'source': result.get('source', 'role tool call'),
         'tested': tested}
    case = result.get('case')
    text = result.get('full_text') or r['excerpt']
    r['judgement'] = judge(short(r['role']), text, r['arguments']) if r['outcome'] == 'succeeded' else \
        {'rules': RULES, 'checks': [], 'passed': 0, 'total': 0}
    if case:
        r['case_id'] = case['case_id']
    assess(r, text, result.get('structured'), case)
    acc = (r.get('data_quality') or {}).get('accuracy', {})
    r['content_verdict'] = ('not run' if r['outcome'] != 'succeeded' else
                            'accurate' if acc.get('points') else 'no answer source' if acc.get('source', '').startswith('none')
                            else 'not accurate')
    folder = version_dir(r['resource_id'], r['role'])
    folder.mkdir(parents=True, exist_ok=True)
    r['version'] = len(list(folder.glob('*.json'))) + 1
    days = success_days(r['resource_id'], r['role'], r['tool'], now, extra=tested if r['outcome'] == 'succeeded' else None)
    r['quality'] = quality(r, days)
    stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(tested))
    name = f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]', '_', r['tool'])[:60]}"
    r['signed_report'] = sign_version(r, case, name)
    (folder / f'{name}.json').write_text(json.dumps(r, indent=1, ensure_ascii=False))
    return r


def signing_key(now=None):
    """The private key of the newest key valid now whose PEM file exists (11-17 운영 키); None when there is none."""
    from datetime import datetime, timezone
    from agent_market import evidence_signing as ES
    try:
        doc = json.loads((SIGNING / 'agentvalcon-keys.json').read_text())
    except (OSError, ValueError):
        return None
    when = datetime.fromtimestamp(now or time.time(), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    revoked = {r.get('keyid') for r in doc.get('revoked', [])}
    for key in sorted(doc.get('keys', []), key=lambda k: k.get('not_before', ''), reverse=True):
        path = SIGNING / f"{key.get('keyid')}.pem"
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
    days = success_days(r['resource_id'], r['role'], r['tool'], time.time(), extra=r['tested'])
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
    folder = SIGNING / 'envelopes' / 'test_report' / str(r['resource_id']) / r['role']
    folder.mkdir(parents=True, exist_ok=True)
    earlier = sorted((p for p in folder.glob('*.json') if p.stem.isdigit()), key=lambda p: int(p.stem))
    previous = json.loads(earlier[-1].read_text()) if earlier else None
    envelope = ES.sign_chained(evidence_for(r, case), key, previous=previous)
    path = folder / f"{r.get('version')}.json"
    path.write_text(json.dumps(envelope, indent=1))
    return str(path.relative_to(ROOT))


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


def rescore():
    """Score every stored version again with the current rules (PM 11-14 data quality), from the stored excerpt."""
    for path in (OUT / 'reports').glob('*/*/*.json') if (OUT / 'reports').exists() else []:
        v = json.loads(path.read_text())
        if v.get('outcome') == 'failed' and str(v.get('reason', '')).startswith('unclean answer'):
            v['outcome'], v['reason'] = 'succeeded', None       # judged again below
        case = None
        if v.get('case_id'):
            try:
                from agent_market.necklaces import role_tasks
                every = role_tasks.load() + (role_tasks.load(RAG_TASKS) if RAG_TASKS.exists() else [])
                case = next((c for c in every if c['case_id'] == v['case_id']), None)
            except Exception:
                case = None
        assess(v, v.get('excerpt') or '', None, case)
        acc = (v.get('data_quality') or {}).get('accuracy', {})
        v['content_verdict'] = ('not run' if v['outcome'] != 'succeeded' else 'accurate' if acc.get('points')
                                else 'no answer source' if acc.get('source', '').startswith('none') else 'not accurate')
        days = success_days(v['resource_id'], v['role'], v['tool'], time.time())
        v['quality'] = quality(v, days)
        v['rescored'] = time.strftime('%Y-%m-%d %H:%M') + ' (judged on the stored excerpt)'
        path.write_text(json.dumps(v, indent=1, ensure_ascii=False))


def latest_versions():
    latest = {}
    for path in (OUT / 'reports').glob('*/*/*.json') if (OUT / 'reports').exists() else []:
        try:
            v = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        v['role'] = canonical(v['role'])
        key = (v['resource_id'], v['role'], v['tool'])
        if key not in latest or v['tested'] > latest[key]['tested']:
            latest[key] = v
    return list(latest.values())


def rank(versions):
    """Per role: by quality score; one place per registrable domain; #1 at 85+ is the final pearl, #2-#3 fall back."""
    roles = defaultdict(list)
    for v in versions:
        if not is_own_fallback(v['resource_id']):          # own fallbacks never compete with external pearls
            roles[v['role']].append(v)
    out = {}
    for role, members in roles.items():
        # Ties (e.g. no answer source yet, accuracy 0 for all) go to the answer that passed more field checks for the
        # role, so a billing envelope (130453) does not lead a role over real advisories (47161).
        fit = lambda v: (v.get('judgement') or {}).get('passed', 0) / max(1, (v.get('judgement') or {}).get('total', 0))
        members.sort(key=lambda v: (-v['quality']['score'], -fit(v), v.get('latency_ms') or 10 ** 9))
        seen, ranked = set(), []
        for v in members:
            entry = {k: v.get(k) for k in ('resource_id', 'tool', 'outcome', 'reason', 'latency_ms', 'host',
                                           'registrable_domain', 'arguments', 'content_verdict', 'version')}
            # PM 11-14: a version with no accuracy comparison (0 points) never appears on a pearl candidate screen.
            entry['pearl_screen'] = bool(((v.get('data_quality') or {}).get('accuracy') or {}).get('points'))
            entry.update(score=v['quality']['score'], domain=v['domain'], tested=time.strftime('%Y-%m-%d %H:%M', time.localtime(v['tested'])),
                         success_days=success_days(v['resource_id'], role, v['tool'], time.time()))
            usable = v['outcome'] == 'succeeded' and v['registrable_domain'] not in seen
            entry['rank'] = len([e for e in ranked if e['rank']]) + 1 if usable else None
            if usable:
                seen.add(v['registrable_domain'])
            ranked.append(entry)
        top = next((e for e in ranked if e['rank'] == 1), None)
        good = bool(top and top['score'] >= PASS_MARK)
        out[role] = {'domain': domain_of(role), 'members': ranked,
                     'final_pearl': top['resource_id'] if good and top['success_days'] >= CONFIRM_DAYS else None,
                     'provisional_pearl': top['resource_id'] if good and top['success_days'] < CONFIRM_DAYS else None,
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


def funnel(versions, ranked, candidates_a=None):
    own = [v for v in versions if is_own_fallback(v['resource_id'])]
    versions = [v for v in versions if not is_own_fallback(v['resource_id'])]
    ok = sum(v['outcome'] == 'succeeded' for v in versions)
    high = sum(v['quality']['score'] >= PASS_MARK for v in versions)
    best = max((v['quality']['score'] for v in versions), default=0)
    own_high = len({v['resource_id'] for v in own if v['quality']['score'] >= PASS_MARK})
    finals = sum(1 for r in ranked.values() if r['final_pearl'])
    provisional = sum(1 for r in ranked.values() if r.get('provisional_pearl'))
    thin = sorted(role for role, r in ranked.items() if r['needs_agentcon_fallback'])
    return (f"{time.strftime('%m-%d %H:%M')} 진주 깔때기(검색과 RAG, report_v2): 후보 A {candidates_a if candidates_a is not None else '?'} → "
            f"v2 보고서 {len(versions)}(성공 {ok}·실패 {len(versions) - ok}, 외부 최고 {best:g}점) → 85점 이상 {high} → "
            f"최종 진주 확정 {finals}·잠정 {provisional}(역할 {finals + provisional}/{len(ranked)}, 확정은 서로 다른 날 2회 성공) · "
            f"검증 확정 {verified(versions)} / 목표 {TARGETS['verified']}, 최종 진주 역할 {finals} / 목표 {TARGETS['roles']} · "
            f"외부 대체 1개 이하(AgentValCon 대체 필요): {', '.join(thin) or '없음'}"
            + (f" · 자체 대체 {own_high}개 85점 이상(순위·깔때기 제외)" if own else ''))


def verified(versions):
    """Verified pearls (charter 0): latest version at 85+ with successes on two different days, any rank."""
    now = time.time()
    return sum(1 for v in versions if v['quality']['score'] >= PASS_MARK
               and success_days(v['resource_id'], v['role'], v['tool'], now) >= CONFIRM_DAYS)


def candidates_a():
    try:
        import psycopg
        dsn = (ROOT / 'gateway-data/postgres18/application.dsn').read_text().strip()
        with psycopg.connect(dsn, autocommit=True, options='-c default_transaction_read_only=on -c statement_timeout=20000') as c:
            return c.execute("""SELECT count(*) FROM public.resources WHERE active=1 AND eval_grade='A' AND health_status='healthy'
                AND COALESCE(eval_security,'') NOT IN ('quarantine','review')""").fetchone()[0]
    except Exception:
        return None


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
                                  'rank_rule': 'quality score (evidence 60 + writing 40), one place per registrable domain; '
                                               '#1 at 85+ is the final pearl, #2-#3 are external fallbacks',
                                  'roles': ranked}, indent=1, ensure_ascii=False))
    line = funnel(versions, ranked, candidates_a()) + refusal_note()
    if board:
        write_board(line)
    return line


def retest_queue(versions, day=None, limit=RETEST_A_DAY):
    """Top members of each role again: ranks 1-2 every day, 3-5 every other day (PM 11-14: 40 a day)."""
    day = int(time.strftime('%j')) if day is None else day
    out = []
    for role, entry in sorted(rank(versions).items()):
        for m in entry['members']:
            if m['rank'] and (m['rank'] <= 2 or (m['rank'] <= 5 and _parity(m['resource_id'], day) == 0)):
                out.append({'role': role, 'id': m['resource_id'], 'tool': m['tool'], 'kind': 'retest', 'rank': m['rank']})
    out.sort(key=lambda c: c['rank'])
    return out[:limit]


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


def new_queue(versions, candidates, seeds=(), limit=NEW_A_DAY, per_host=3):
    """Untested members, roles with the fewest successes first, one per registrable domain in a role, 3 per host."""
    tested = {(v['resource_id'], v['tool']) for v in versions}
    successes = Counter(v['role'] for v in versions if v['outcome'] == 'succeeded')
    taken_domains = defaultdict(set)
    for v in versions:
        taken_domains[v['role']].add(v['registrable_domain'])
    pools = defaultdict(list)
    for seed in seeds:
        pools[canonical(seed['role'])].append((seed['id'], seed['tool'], seed.get('host')))
    for role, rid, tool, host in candidates:
        pools[role].append((rid, tool, host))
    hosts, out = Counter(), []
    roles = sorted(pools, key=lambda role: (successes[role], role))
    while len(out) < limit and any(pools.values()):
        for role in roles:
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
    return retest_queue(versions) + new_queue(versions, catalog_candidates(), seeds)


def run(queue):
    """Role tests for QUEUE within today's limits: 80 new + 40 retests, 120 in all, 60 after refusals pass 5%."""
    import httpx
    import pearl_batch as PB
    from role_tool_test import resources, test_one
    pacer = PB.Pacer(state_dir=PB.STATE_DIR, system='role_tests')
    for key in ('role_tests', 'refusals', 'new_tests', 'retests'):
        pacer.state.setdefault(key, 0)
    found = resources({c['id'] for c in queue})
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
            result = test_one(http, candidate, found.get(candidate['id'], {}), pacer)
            if not (result.get('outcome') == 'skipped' and 'limit' in str(result.get('reason'))):
                pacer.state['role_tests'] += 1
                pacer.state[kind] += 1
            if result.get('http') in (403, 429) or str(result.get('reason', '')).endswith(('HTTP 429', 'HTTP 403')):
                pacer.state['refusals'] += 1
            pacer.save()
            save_version(result)


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

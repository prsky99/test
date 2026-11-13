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
BOARD = ROOT / 'logs/ops/status-board.md'
RULES = 'v2-2026-11-14'
PASS_MARK = 85
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
# Roles RAG judges with its default field/word checks until an answer set exists (PM 11-14: 30 roles by 11-21).
RAG_ROLES = {role for role, spec in role_catalog.ROLES.items() if spec.get('checks')}
ROLE_DOMAIN_V1 = {'domain.lookup.v1': 'internet', 'place.search.v1': 'travel', 'book.search.v1': 'reference',
                  'crypto.price.v1': 'finance', 'stock.quote.v1': 'finance', 'geocode.address.v1': 'maps',
                  'ip.lookup.v1': 'internet', 'timezone.time.v1': 'reference', 'dictionary.define.v1': 'reference',
                  'translate.text.v1': 'language', 'github.repo.v1': 'developer', 'holiday.calendar.v1': 'reference',
                  'sec.filings.v1': 'business', 'airport.lookup.v1': 'travel', 'unit.convert.v1': 'reference',
                  'earthquake.feed.v1': 'science', 'cve.record.v1': 'security', 'software.incident.v1': 'security',
                  'website.ai_readiness.v1': 'internet', 'web.grounding.v1': 'reference'}


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


def case_for(role, day=None):
    """One role task for ROLE, rotating by day so every case is used over the week; None when the role has none."""
    try:
        from agent_market.necklaces import role_tasks
        cases = role_tasks.by_role().get(canonical(role), [])
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
    return {'rules': RULES, 'checks': checks, 'passed': sum(c['passed'] for c in checks), 'total': len(checks)}


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
    """The English report body: what was sent, what came back, what was checked, and what was not."""
    verdict = r['judgement']
    lines = [f"Role task test for {r['role']}: tool `{r['tool']}` was called once, read-only, "
             f"with arguments {json.dumps(r.get('arguments') or {}, ensure_ascii=False)}."]
    if r['outcome'] == 'succeeded':
        lines.append(f"It answered in {r.get('latency_ms')} ms. Content checks passed: {verdict['passed']} of {verdict['total']} "
                     f"({', '.join(c['check'] + (' ok' if c['passed'] else ' failed') for c in verdict['checks'])}).")
    else:
        lines.append(f"Outcome: {r['outcome']} ({r.get('reason') or 'no reason given'}).")
    lines.append('Limits: one call with one input; the checks look for expected fields and words in the reply, '
                 'not for factual accuracy against an independent source.')
    return ' '.join(lines)


def writing_points(r, text):
    """40 points for the AQEF failures seen in the 11-10 audit: limits stated, claims tied to measured facts."""
    points = 0
    points += 10 if 'Limits:' in text else 0                                   # limitations stated
    points += 10 if r.get('arguments') is not None and 'arguments' in text else 0  # input disclosed
    points += 10 if (r['outcome'] != 'succeeded' or (r.get('excerpt') and r.get('latency_ms') is not None)) else 0  # claims backed
    points += 10 if r['judgement']['total'] else 0                              # what was checked is named
    return points


def quality(r, success_days):
    args = r.get('arguments')
    arg_points = 0 if not args else (7.5 if r.get('source') == 'collector message' else 15)
    verdict = r['judgement']
    if r['outcome'] != 'succeeded':
        evidence = {'arguments': arg_points, 'content': 0, 'repeat': 0, 'latency': 0}
    else:
        evidence = {'arguments': arg_points,
                    'content': round(20 * verdict['passed'] / verdict['total'], 1) if verdict['total'] else 0,
                    'repeat': min(15, 3 * success_days), 'latency': latency_points(r.get('latency_ms'))}
    text = report_text(r)
    write = writing_points(r, text)
    return {'score': round(sum(evidence.values()) + write, 1), 'evidence': evidence, 'writing': write, 'text': text}


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
         'registrable_domain': registrable(result.get('host')), 'source': result.get('source', 'role tool call'),
         'tested': tested}
    case = result.get('case')
    if case and r['outcome'] == 'succeeded':
        from agent_market.necklaces import role_tasks
        passed, reasons = role_tasks.score(case, result.get('full_text') or r['excerpt'], result.get('structured'))
        live = [k for k in ('published_within_days', 'dynamic') if k in (case.get('expect') or {})]
        r['judgement'] = {'rules': 'role-tasks-v1 ' + case['case_id'], 'checks': [{'check': case['case_id'], 'passed': passed}],
                          'passed': int(passed), 'total': 1, 'reasons': reasons, 'not_checked_live': live}
    elif r['outcome'] == 'succeeded':
        r['judgement'] = judge(short(r['role']), result.get('full_text') or r['excerpt'], r['arguments'])
    else:
        r['judgement'] = {'rules': RULES, 'checks': [], 'passed': 0, 'total': len(CHECKS.get(short(r['role']), [])) or 1}
    if case:
        r['case_id'] = case['case_id']
    if r['outcome'] == 'succeeded' and r['judgement']['total'] and r['judgement']['passed'] < r['judgement']['total']:
        r['content_verdict'] = 'partial' if r['judgement']['passed'] else 'failed'
    else:
        r['content_verdict'] = 'passed' if r['outcome'] == 'succeeded' else 'not run'
    folder = version_dir(r['resource_id'], r['role'])
    folder.mkdir(parents=True, exist_ok=True)
    r['version'] = len(list(folder.glob('*.json'))) + 1
    days = success_days(r['resource_id'], r['role'], r['tool'], now, extra=tested if r['outcome'] == 'succeeded' else None)
    r['quality'] = quality(r, days)
    stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(tested))
    (folder / f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]', '_', r['tool'])[:60]}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    return r


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
        roles[v['role']].append(v)
    out = {}
    for role, members in roles.items():
        members.sort(key=lambda v: (-v['quality']['score'], v.get('latency_ms') or 10 ** 9))
        seen, ranked = set(), []
        for v in members:
            entry = {k: v.get(k) for k in ('resource_id', 'tool', 'outcome', 'reason', 'latency_ms', 'host',
                                           'registrable_domain', 'arguments', 'content_verdict', 'version')}
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
    ok = sum(v['outcome'] == 'succeeded' for v in versions)
    high = sum(v['quality']['score'] >= PASS_MARK for v in versions)
    finals = sum(1 for r in ranked.values() if r['final_pearl'])
    provisional = sum(1 for r in ranked.values() if r.get('provisional_pearl'))
    thin = sorted(role for role, r in ranked.items() if r['needs_agentcon_fallback'])
    return (f"{time.strftime('%m-%d %H:%M')} 진주 깔때기(검색과 RAG, report_v2): 후보 A {candidates_a if candidates_a is not None else '?'} → "
            f"v2 보고서 {len(versions)}(성공 {ok}·실패 {len(versions) - ok}) → 85점 이상 {high} → "
            f"최종 진주 확정 {finals}·잠정 {provisional}(역할 {finals + provisional}/{len(ranked)}, 확정은 서로 다른 날 2회 성공) · "
            f"검증 확정 {verified(versions)} / 목표 {TARGETS['verified']}, 최종 진주 역할 {finals} / 목표 {TARGETS['roles']} · "
            f"외부 대체 1개 이하(AgentValCon 대체 필요): {', '.join(thin) or '없음'}")


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
            if m['rank'] and (m['rank'] <= 2 or (m['rank'] <= 5 and (day + m['resource_id']) % 2 == 0)):
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
    pacer = PB.Pacer(state_dir=PB.STATE_DIR)
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
    elif argv[0] == 'queue':
        Path(argv[1]).write_text(json.dumps(build_queue(), indent=1))
    elif argv[0] == 'run':
        run(json.loads(Path(argv[1]).read_text()))
    print(publish(board='--no-board' not in argv))


if __name__ == '__main__':
    main()

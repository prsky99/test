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
DAY = 86400

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
    for name, rule in CHECKS.get(role, []):
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
    return OUT / 'reports' / str(rid) / role.replace('/', '_')


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
    r = {'resource_id': result['id'], 'role': result['role'], 'domain': ROLE_DOMAIN.get(result['role'], 'other'),
         'tool': result['tool'], 'arguments': result.get('arguments'), 'outcome': result['outcome'],
         'reason': result.get('reason'), 'latency_ms': result.get('latency_ms'), 'http': result.get('http'),
         'excerpt': (result.get('excerpt') or '')[:1000], 'host': result.get('host'),
         'registrable_domain': registrable(result.get('host')), 'source': result.get('source', 'role tool call'),
         'tested': tested}
    r['judgement'] = judge(r['role'], r['excerpt'], r['arguments']) if r['outcome'] == 'succeeded' else \
        {'rules': RULES, 'checks': [], 'passed': 0, 'total': len(CHECKS.get(r['role'], []))}
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
            entry.update(score=v['quality']['score'], domain=v['domain'], tested=time.strftime('%Y-%m-%d %H:%M', time.localtime(v['tested'])))
            usable = v['outcome'] == 'succeeded' and v['registrable_domain'] not in seen
            entry['rank'] = len([e for e in ranked if e['rank']]) + 1 if usable else None
            if usable:
                seen.add(v['registrable_domain'])
            ranked.append(entry)
        top = next((e for e in ranked if e['rank'] == 1), None)
        out[role] = {'domain': ROLE_DOMAIN.get(role, 'other'), 'members': ranked,
                     'final_pearl': top['resource_id'] if top and top['score'] >= PASS_MARK else None,
                     'fallbacks': [e['resource_id'] for e in ranked if e['rank'] in (2, 3)],
                     'needs_agentcon_fallback': len([e for e in ranked if e['rank'] and e['rank'] >= 2]) <= 1}
    return out


def funnel(versions, ranked, candidates_a=None):
    ok = sum(v['outcome'] == 'succeeded' for v in versions)
    high = sum(v['quality']['score'] >= PASS_MARK for v in versions)
    finals = sum(1 for r in ranked.values() if r['final_pearl'])
    return (f"{time.strftime('%m-%d %H:%M')} 진주 깔때기(검색과 RAG, report_v2): 후보 A {candidates_a if candidates_a is not None else '?'} → "
            f"v2 보고서 {len(versions)}(성공 {ok}·실패 {len(versions) - ok}) → 85점 이상 {high} → 최종 진주 {finals}(역할 {finals}/{len(ranked)})")


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


def publish(board=True):
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
    line = funnel(versions, ranked, candidates_a())
    if board:
        write_board(line)
    return line


def main(argv=None):
    argv = argv or sys.argv[1:]
    if argv[0] == 'import':
        for result in json.loads(Path(argv[1]).read_text()).get('results', []):
            if result.get('outcome') in ('succeeded', 'failed', 'skipped'):
                save_version(result)
    elif argv[0] == 'run':
        import httpx
        import pearl_batch as PB
        from role_tool_test import resources, test_one
        candidates = json.loads(Path(argv[1]).read_text())
        pacer = PB.Pacer(state_dir=PB.STATE_DIR)
        found = resources({c['id'] for c in candidates})
        with httpx.Client(follow_redirects=False) as http:
            for candidate in candidates[:PB.DAILY_LIMIT]:
                save_version(test_one(http, candidate, found.get(candidate['id'], {}), pacer))
    print(publish(board='--no-board' not in argv))


if __name__ == '__main__':
    main()

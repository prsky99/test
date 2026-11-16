"""Ops launch gate for self-made substitute agents (deploy/NECKLACE_GATE.md section 10), run by 운영·SRE.

    .venv/bin/python -m scripts.substitute_gate nvd-cve cisa-kev package-registry depsdev-package --split holdout-r1

PM 11-14: the substitutes run inside the executor process (path A, FallbackAgents.execute), so the gate runs that same
call. For every held-out case it saves the whole answer first (raw), then judges:
- accuracy: the agent team's per-agent rules (gold_check.judge), truth from the workflow team's gold set;
- data quality (PM 11-14, required): sources with license, freshness with data_as_of and age within max_age,
  and a clean answer (no demo or placeholder words, error or payment text, broken encoding);
- the fixed role tasks and the contract test inputs.
Calls are reserved first in the shared outside-call ledger (agent_market.provider_budget, system 'gate').
Pass: answer set at least 29 of 30, every data-quality check on every answer, role tasks and contract inputs all.
Nothing is written to any database; results go under logs/ops/necklace-gate/substitutes/.
"""
import argparse
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'logs/ops/necklace-gate/substitutes'
CONTRACT_INPUTS = ROOT / 'reports/fallback-agents-2026-11-14/contract-test-inputs.json'
from agent_market.necklaces.gate_rules import SUBSTITUTE_CASES, SUBSTITUTE_PASS  # noqa: E402 - one source of the numbers
NEED = SUBSTITUTE_PASS
UNCLEAN = re.compile(r'lorem|ipsum|\bplaceholder\b|\bmock\b|\bdummy\b|\bexample\.(com|org)\b|\bsample data\b|'
                     r'traceback|internal server error|payment required|\bx402\b|insufficient (funds|credit)|�', re.I)
# Upper bounds of calls a run may make per source domain, reserved before the run (over-reserving is safe).
DOMAINS = {'nvd-cve': ['https://services.nvd.nist.gov/'], 'cisa-kev': ['https://www.cisa.gov/', 'https://api.first.org/'],
           'package-registry': ['https://registry.npmjs.org/', 'https://pypi.org/'], 'depsdev-package': ['https://api.deps.dev/'],
           'cve-org': ['https://cveawg.mitre.org/'], 'github-advisory': ['https://api.github.com/'],
           'gleif-lei': ['https://api.gleif.org/', 'https://query.wikidata.org/'], 'sec-edgar': ['https://data.sec.gov/'],
           'sec-company-profile': ['https://data.sec.gov/'],
           'wikipedia-summary': ['https://en.wikipedia.org/'],
           # The other 20 (R30, agent team 11-15): one URL per registrable domain, since the ledger counts by domain
           # (www.sec.gov and data.sec.gov are both sec.gov). [] = no outside call (local data or computed).
           'sec-filings': ['https://data.sec.gov/'], 'software-incident': ['https://api.github.com/'],
           'scorecard': ['https://api.scorecard.dev/'], 'arxiv-search': ['https://export.arxiv.org/'],
           'wiki-grounding': ['https://en.wikipedia.org/'], 'wiktionary-define': ['https://en.wiktionary.org/'],
           'wikidata-place': ['https://query.wikidata.org/'], 'wikidata-book': ['https://query.wikidata.org/'],
           'gdelt-news': ['https://api.gdeltproject.org/'],
           'census-geocode': ['https://geocoding.geo.census.gov/'],
           'mcp-registry': ['https://registry.modelcontextprotocol.io/'],
           'github-releases': ['https://api.github.com/'],
           'package-releases': ['https://registry.npmjs.org/'],
           'worldbank-indicator': ['https://api.worldbank.org/'], 'met-weather': ['https://api.met.no/'],
           'ecb-fx': ['https://www.ecb.europa.eu/'], 'usgs-quakes': ['https://earthquake.usgs.gov/'],
           'github-repo': ['https://api.github.com/'],
           # RDAP: the IANA bootstrap (cached a day) plus the registry's own RDAP server, which depends on the domain
           # asked, so it is reserved per call by the ledger, not here.
           'rdap-domain': ['https://data.iana.org/'],
           # Each case reads the site it is asked about; those sites are reserved per call, not here.
           'site-readiness': [],
           'tls-certificate': [],   # the case's own site (a handshake, reserved per site in the agent)
           'site-reachability': [],   # the case's own site (one GET, reserved per site by net.get)
           'tz-time': [], 'airport-lookup': [], 'unit-convert': [], 'public-holidays': [], 'holiday-calendar': [],
           'sun-times': []}
# Calls per case when an agent may call a source more than once (11-15 agent team, eefdb282: GLEIF search plus one
# direct read of the top-level entity; Wikidata at most once). Reserved as CASES x this + EXTRA_CALLS.
CALLS_PER_CASE = {'https://api.gleif.org/': 2}
EXTRA_CALLS = 4   # contract inputs and role tasks


def quality(envelope):
    """Data-quality reasons the answer fails (empty when clean)."""
    reasons = []
    sources = envelope.get('sources') or []
    if not sources or not all(isinstance(s, dict) and s.get('url') and s.get('license') for s in sources):
        reasons.append('sources_without_license')
    fresh = envelope.get('freshness') or (envelope.get('result') or {}).get('freshness')
    if not isinstance(fresh, dict) or not fresh.get('data_as_of') or fresh.get('age_seconds') is None:
        reasons.append('no_data_time')
    elif fresh.get('max_age_seconds') is not None and fresh['age_seconds'] > fresh['max_age_seconds']:
        reasons.append('stale')
    if UNCLEAN.search(json.dumps(envelope.get('result'), ensure_ascii=False)):
        reasons.append('unclean_text')
    return reasons


def calls_needed(agent_ids, cases=None):
    cases = SUBSTITUTE_CASES if cases is None else cases
    return {url: CALLS_PER_CASE.get(url, 1) * cases + EXTRA_CALLS for a in agent_ids for url in DOMAINS.get(a, [])}


def reserve_calls(agent_ids, cases=None):
    from agent_market.provider_budget import DAILY_TOTAL, reserve
    needed = calls_needed(agent_ids, cases)
    over = {url: n for url, n in needed.items() if n > DAILY_TOTAL}
    if over:  # cannot fit one day's domain total whatever else ran today: reserve nothing
        return {url: f'needs {n} > daily total {DAILY_TOTAL}' for url, n in over.items()}
    refused = {}
    for url, n in needed.items():
        ok, why = reserve(url, 'gate', n=n)
        if not ok:
            refused[url] = why
    return refused


def used_cases(paths):
    """(agent, case_id) pairs already run in earlier gate raw files: a rerun takes cases nobody has seen."""
    used = set()
    for path in paths or []:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('agent') and row.get('case_id'):
                used.add((row['agent'], row['case_id']))
    return used


def held_out(agent_id, split, fill_from=None, exclude=frozenset()):
    """The held-out cases the source can answer (gold_check.applies), SUBSTITUTE_CASES of them: the split first, then
    the fill split (11-14: GLEIF and SEC only answer cases with an LEI or a CIK). Cases a source cannot answer are
    never called."""
    from agent_market.fallback_agents.gold_check import SLUG, applies
    cases = []
    # 11-15 PM 14:34: a re-judgement after a fix skips the cases already seen, so it may need two fill rounds
    # ('holdout-r2,holdout-r3'); fill_from is one split name or several separated by commas, used in that order.
    fills = [f for f in (fill_from or '').split(',') if f]
    for name in [split] + fills:
        path = ROOT / 'gateway-data/necklaces/gold' / SLUG[agent_id] / f'{name}.jsonl'
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        cases += [dict(c, split=name) for c in rows if applies(agent_id, c) and (agent_id, c['case_id']) not in exclude]
    return cases[:SUBSTITUTE_CASES]


def remaining(agent_id, split, fill_from=None, exclude=frozenset(), prior=()):
    """Held-out cases still to run: the case window minus the rows an earlier part already judged."""
    done = {r['case_id'] for r in prior}
    return [c for c in held_out(agent_id, split, fill_from, exclude) if c['case_id'] not in done]


# A floor between cases for agents that call one shared allowance several times a case (ops 11-15: github-releases
# makes two calls a case inside GitHub's unauthenticated 60 an hour, so cases are kept 2 s apart).
PACE_SECONDS = {'github-releases': 2.0}


CALLS_A_CASE = 2   # the most reads one case makes on one host (wiki-grounding: title lookup + extract, 78caa6e4)


def window_wait(limiter, need=CALLS_A_CASE):
    """Seconds until LIMITER's request window has room for NEED more requests (0 when it has no window)."""
    count, window = getattr(limiter, 'count', None), getattr(limiter, 'window', None)
    if not window or not count:
        return 0.0
    if getattr(limiter, 'shared', None) is not None:
        try:
            sent = [float(t) for t in json.loads(limiter.shared.read_text() or '{}').get('sent') or []]
        except (OSError, ValueError):
            sent = []
        now = limiter.wall()
    else:
        sent, now = list(limiter.sent), limiter.clock()
    sent = sorted(t for t in sent if now - t < window)
    over = len(sent) + need - count
    if over <= 0:
        return 0.0
    return max(0.0, sent[min(over, len(sent)) - 1] + window - now) + 0.1


def pace(agents, agent_id, sleep=time.sleep, longest=120.0):
    """Wait OUTSIDE the call budget until the agent's slow hosts may be called again (agent team 11-15: arXiv's 3 s
    spacing used up most of the 3.3 s call budget when cases ran back to back, so 4 timed out, and after a 503 the
    next cases met a resting host). Only hosts spaced 1 s or more; a rest after 429/503 is waited for, at most LONGEST."""
    from urllib.parse import urlsplit
    waits = [PACE_SECONDS.get(agent_id, 0.0)]
    for url in DOMAINS.get(agent_id) or []:
        limiter = (getattr(agents, 'limiters', None) or {}).get(urlsplit(url).hostname)
        if limiter is None:
            continue
        # 11-16 06:48 holdout-r4-wiki: wiki-grounding's two reads a case met Wikipedia's own 40-a-minute window
        # (spacing 0.2 s, so it was skipped here) and 10 of 30 cases ended rate_limited in 0 ms without a call.
        waits.append(window_wait(limiter))
        if limiter.spacing < 1.0:
            continue
        waits.append(max(limiter.spacing + 0.2, limiter.resting()))
    if max(waits) > 0:
        sleep(min(longest, max(waits)))


def run(agent_ids, split, raw_path, agents=None, fill_from=None, exclude=frozenset(), limit=None, previous=None,
        sleep=time.sleep):
    """With limit, one part of a verdict split over days (11-15 PM: GLEIF 15 cases a day, 2 calls each); with
    previous (the rows of the earlier parts per agent) the verdict is judged on every part's rows together."""
    from agent_market.fallback_agents.agents import FallbackAgents, FallbackUnavailable
    from agent_market.fallback_agents.gold_check import case_arguments, judge, role_task_check
    agents = agents or FallbackAgents()
    report = {'split': split, 'agents': {}}
    with open(raw_path, 'a', encoding='utf-8') as raw:
        for agent_id in agent_ids:
            prior = list((previous or {}).get(agent_id) or [])
            cases = remaining(agent_id, split, fill_from, exclude, prior)
            if limit:
                cases = cases[:limit]
            rows = []
            for case in cases:
                pace(agents, agent_id, sleep)
                started, envelope, code = time.monotonic(), None, None
                try:
                    # The same mapping as the tuning runs (11-15: cutting to the contract fields dropped 'topic',
                    # so all 30 Wikipedia cases ran without a title)
                    envelope = agents.execute(agent_id, case_arguments(agent_id, case))
                except FallbackUnavailable as exc:
                    code = exc.code
                raw.write(json.dumps({'agent': agent_id, 'case_id': case['case_id'], 'error': code, 'envelope': envelope},
                                     ensure_ascii=False) + '\n')
                raw.flush()
                verdict = judge(agent_id, case, (envelope or {}).get('result'), code)
                # not_found where the truth says there is nothing to find is an answer, not a missing one (11-16)
                dq = quality(envelope) if envelope else ([] if verdict.get('expected_absence') and verdict.get('pass')
                                                         else ['no_answer'])
                rows.append({'case_id': case['case_id'], 'pass': bool(verdict.get('pass')), 'data_quality': dq,
                             'error': code, 'ms': int((time.monotonic() - started) * 1000)})
            contract_rows = []
            inputs = json.loads(CONTRACT_INPUTS.read_text()).get(agent_id) or []
            for arguments, expect, *_ in inputs:
                pace(agents, agent_id, sleep)
                try:
                    agents.execute(agent_id, arguments)
                    contract_rows.append(expect == 'ok')
                except FallbackUnavailable as exc:
                    contract_rows.append(expect == exc.code)
            roles = role_task_check([agent_id], agents, before_call=lambda a: pace(agents, a, sleep))[agent_id]
            part_rows, rows = rows, prior + rows
            passed = sum(r['pass'] for r in rows)
            dirty = [r['case_id'] for r in rows if r['data_quality']]
            report['agents'][agent_id] = {
                'answer_set': f'{passed}/{len(rows)}', 'data_quality_failures': dirty,
                'part': {'earlier_rows': len(prior), 'this_part': len(part_rows),
                         'complete': len(rows) >= SUBSTITUTE_CASES},
                'contract_inputs': f'{sum(contract_rows)}/{len(contract_rows)}', 'role_tasks': f"{roles['passed']}/{roles['cases']}",
                'pass': (passed >= NEED and len(rows) >= SUBSTITUTE_CASES and not dirty and bool(contract_rows)
                         and all(contract_rows) and roles['passed'] == roles['cases']),
                'missing': [m for m, bad in (('held_out_cases', len(rows) < SUBSTITUTE_CASES),
                                             ('contract_inputs', not contract_rows)) if bad],
                'rows': rows,
                # each role task's case_id, pass and why (agent team 11-16: arxiv 2/3 had no record of which failed)
                'role_task_rows': roles.get('rows') or []}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('agents', nargs='+')
    parser.add_argument('--split', default='holdout-r1')
    parser.add_argument('--fill-from', default=None, help='take more answerable cases from this split, or several comma-separated in order (e.g. holdout-r2,holdout-r3)')
    parser.add_argument('--exclude-raw', nargs='*', default=[], help='skip cases already run in these gate raw files')
    parser.add_argument('--limit', type=int, default=None, help='run at most this many cases now (a part of a verdict)')
    parser.add_argument('--continue-from', default=None, help='an earlier part verdict: judge its rows and these together')
    args = parser.parse_args(argv)
    exclude = used_cases(args.exclude_raw)
    previous = {}
    if args.continue_from:
        earlier = json.loads(Path(args.continue_from).read_text(encoding='utf-8'))
        previous = {a: r.get('rows') or [] for a, r in earlier['agents'].items() if a in args.agents}
    local = time.localtime()
    hm = local.tm_hour * 100 + local.tm_min
    if local.tm_min >= 55 or local.tm_min < 10 or 350 <= hm <= 510:  # never inside the measurement windows
        print(json.dumps({'ok': False, 'reason': 'measurement_window'}))
        return 75
    stamp = time.strftime('%Y%m%d-%H%M')
    OUT.mkdir(parents=True, exist_ok=True)
    # Two gates started in the same minute shared both names, and the second verdict replaced the first
    # (11-16 06:33 wiki-grounding, then arxiv-search). A taken stamp gets the next free suffix for both files.
    n = 1
    while (OUT / f'raw-{args.split}-{stamp}.jsonl').exists() or (OUT / f'verdict-{args.split}-{stamp}.json').exists():
        n += 1
        stamp = time.strftime('%Y%m%d-%H%M') + f'-{n}'
    want = {a: SUBSTITUTE_CASES - len(previous.get(a, [])) for a in args.agents}
    if args.limit:
        want = {a: min(n, args.limit) for a, n in want.items()}
    short = {a: len(remaining(a, args.split, args.fill_from, exclude, previous.get(a, []))) for a in args.agents}
    short = {a: n for a, n in short.items() if n < want[a]}
    if short:  # no calls when a source cannot reach the case count (an answer set to extend, not a verdict)
        print(json.dumps({'ok': False, 'reason': 'held_out_cases', 'answerable': short, 'need': want}))
        return 76
    refused = reserve_calls(args.agents, cases=max(want.values()))
    if refused:
        print(json.dumps({'ok': False, 'reason': 'budget', 'refused': refused}))
        return 75
    raw = OUT / f'raw-{args.split}-{stamp}.jsonl'
    report = run(args.agents, args.split, raw, fill_from=args.fill_from, exclude=exclude, limit=args.limit,
                 previous=previous)
    report.update(at=stamp, raw=str(raw.relative_to(ROOT)))
    out = OUT / f'verdict-{args.split}-{stamp}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({a: {k: v for k, v in r.items() if k != 'rows'} for a, r in report['agents'].items()}, ensure_ascii=False))
    print(out.relative_to(ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

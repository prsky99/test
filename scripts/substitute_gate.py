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
           'cve-org': ['https://cveawg.mitre.org/'], 'github-advisory': ['https://api.github.com/']}


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


def reserve_calls(agent_ids, n):
    from agent_market.provider_budget import reserve
    refused = {}
    for agent_id in agent_ids:
        for url in DOMAINS.get(agent_id, []):
            ok, why = reserve(url, 'gate', n=n)
            if not ok:
                refused[url] = why
    return refused


def run(agent_ids, split, raw_path, agents=None):
    from agent_market.fallback_agents.agents import FallbackAgents, FallbackUnavailable
    from agent_market.fallback_agents.catalog import SPECS, contract
    from agent_market.fallback_agents.gold_check import SLUG, judge, role_task_check
    agents = agents or FallbackAgents()
    report = {'split': split, 'agents': {}}
    with open(raw_path, 'a', encoding='utf-8') as raw:
        for agent_id in agent_ids:
            path = ROOT / 'gateway-data/necklaces/gold' / SLUG[agent_id] / f'{split}.jsonl'
            cases = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
            allowed = contract(SPECS[agent_id]['contract'])['input_schema']['properties']
            rows = []
            for case in cases:
                started, envelope, code = time.monotonic(), None, None
                try:
                    envelope = agents.execute(agent_id, {k: v for k, v in case['input'].items() if k in allowed})
                except FallbackUnavailable as exc:
                    code = exc.code
                raw.write(json.dumps({'agent': agent_id, 'case_id': case['case_id'], 'error': code, 'envelope': envelope},
                                     ensure_ascii=False) + '\n')
                raw.flush()
                verdict = judge(agent_id, case, (envelope or {}).get('result'))
                dq = quality(envelope) if envelope else ['no_answer']
                rows.append({'case_id': case['case_id'], 'pass': bool(verdict.get('pass')), 'data_quality': dq,
                             'error': code, 'ms': int((time.monotonic() - started) * 1000)})
            contract_rows = []
            for arguments, expect, *_ in (json.loads(CONTRACT_INPUTS.read_text()).get(agent_id) or []):
                try:
                    agents.execute(agent_id, arguments)
                    contract_rows.append(expect == 'ok')
                except FallbackUnavailable as exc:
                    contract_rows.append(expect == exc.code)
            roles = role_task_check([agent_id], agents)[agent_id]
            passed = sum(r['pass'] for r in rows)
            dirty = [r['case_id'] for r in rows if r['data_quality']]
            report['agents'][agent_id] = {
                'answer_set': f'{passed}/{len(rows)}', 'data_quality_failures': dirty,
                'contract_inputs': f'{sum(contract_rows)}/{len(contract_rows)}', 'role_tasks': f"{roles['passed']}/{roles['cases']}",
                'pass': (passed >= NEED and len(rows) >= SUBSTITUTE_CASES and not dirty and all(contract_rows)
                         and roles['passed'] == roles['cases']),
                'rows': rows}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('agents', nargs='+')
    parser.add_argument('--split', default='holdout-r1')
    args = parser.parse_args(argv)
    stamp = time.strftime('%Y%m%d-%H%M')
    OUT.mkdir(parents=True, exist_ok=True)
    refused = reserve_calls(args.agents, 34)
    if refused:
        print(json.dumps({'ok': False, 'reason': 'budget', 'refused': refused}))
        return 75
    raw = OUT / f'raw-{args.split}-{stamp}.jsonl'
    report = run(args.agents, args.split, raw)
    report.update(at=stamp, raw=str(raw.relative_to(ROOT)))
    out = OUT / f'verdict-{args.split}-{stamp}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({a: {k: v for k, v in r.items() if k != 'rows'} for a, r in report['agents'].items()}, ensure_ascii=False))
    print(out.relative_to(ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

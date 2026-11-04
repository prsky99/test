"""Run scripts/evaluate_chat_answer_quality.py in parallel shards and merge the result (2026-11-04).

usage: python -m scripts.evaluate_chat_parallel RELEASE CASES.json:part OUT.json [--workers 8]

Each shard is its own process with one read-only database connection and one model slot, so
WORKERS shards send at most WORKERS model requests at a time. A guard stops every shard when
the database holds GUARD_CONNECTIONS or more connections (memory: prod-db-connection-budget).
The merged summary uses the same formulas as the single-process evaluator.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD_CONNECTIONS = 40
PSQL = '/opt/homebrew/opt/postgresql@18/bin/psql'


def connections():
    dsn = f"host={ROOT}/gateway-data/postgres18/run port=55432 dbname=agentcon_cutover_20261020_191757"
    env = {**os.environ, 'PGOPTIONS': '-c default_transaction_read_only=on'}
    try:
        out = subprocess.run([PSQL, dsn, '-Atc', 'select count(*) from pg_stat_activity'], env=env,
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return int(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def summary(results, cases):
    lines = []
    n = len(results); p = sum(r['ok'] for r in results)
    lines.append(f'TOTAL {p}/{n} = {p/max(1, n)*100:.1f}%  max {max((r["ms"] for r in results), default=0)}ms')
    match = [r for r in results if cases[r['id']]['expect']['type'] == 'match']
    answered = [r for r in match if r.get('answered')]
    if match:
        right = sum(r['ok'] for r in answered)
        lines.append(f'PRECISION {right}/{len(answered)} = {right/max(1, len(answered))*100:.1f}%  '
                     f'COVERAGE {len(answered)}/{len(match)} = {len(answered)/len(match)*100:.1f}%')
    ms = sorted(r['ms'] for r in results)
    if ms:
        lines.append(f'LATENCY p50 {ms[len(ms)//2]}ms  p95 {ms[int(len(ms)*0.95)]}ms')
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('release'); parser.add_argument('cases'); parser.add_argument('out')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args(argv)
    workers = max(1, min(8, args.workers))
    path, part = args.cases.rsplit(':', 1)
    cases = {c['id']: c for c in json.load(open(path, encoding='utf-8'))[part]}
    before = connections()
    if before is not None and before + workers >= GUARD_CONNECTIONS:
        raise SystemExit(f'refused: {before} database connections; {workers} more would reach {GUARD_CONNECTIONS}')
    stopped = threading.Event()
    with tempfile.TemporaryDirectory(prefix='chat-eval-') as scratch:
        procs = []
        for index in range(workers):
            env = {**os.environ, 'EVAL_SHARD': f'{index}/{workers}', 'EVAL_LLM_CONCURRENCY': '1'}
            out = Path(scratch) / f'shard{index}.json'
            log = open(Path(scratch) / f'shard{index}.log', 'w')
            procs.append((subprocess.Popen(['nice', '-n', '10', str(ROOT / '.venv' / 'bin' / 'python'), '-B',
                                            'scripts/evaluate_chat_answer_quality.py', args.release, args.cases, str(out)],
                                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT), out, log))

        def guard():
            while not stopped.wait(10):
                count = connections()
                if count is not None and count >= GUARD_CONNECTIONS:
                    print(f'guard: {count} database connections; stopping every shard', file=sys.stderr)
                    for proc, _, _ in procs:
                        proc.terminate()
                    return
        threading.Thread(target=guard, daemon=True).start()
        started = time.time()
        codes = [proc.wait() for proc, _, _ in procs]
        stopped.set()
        for _, _, log in procs:
            log.close()
        if any(codes):
            for index, (_, _, log) in enumerate(procs):
                if codes[index]:
                    print(f'shard {index} failed:\n' + Path(log.name).read_text()[-2000:], file=sys.stderr)
            raise SystemExit(1)
        results = [row for _, out, _ in procs for row in json.load(open(out, encoding='utf-8'))]
    order = list(cases)
    results.sort(key=lambda row: order.index(row['id']) if row['id'] in cases else len(order))
    json.dump(results, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for line in summary(results, cases):
        print(line)
    print(f'WALL {time.time() - started:.0f}s with {workers} shards')


if __name__ == '__main__':
    main()

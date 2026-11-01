"""Bounded public-origin availability samples, without storing response bodies."""
import argparse
import json
from pathlib import Path
import time
import httpx


def observe(report, seconds):
    started = time.time()
    samples = []
    stable = 0
    state = Path('gateway-data/services/state.json')
    with httpx.Client(trust_env=False, timeout=5, headers={
            'Accept': 'text/html', 'User-Agent': 'AgentConcierge-Deployment-Verification/1.0'}) as client:
        while time.time() - started < seconds:
            before = time.time()
            try:
                response = client.get('http://127.0.0.1:8400/')
                status = response.status_code
            except httpx.HTTPError:
                status = 0
            samples.append({'at': round(before, 3), 'status': status, 'ms': round((time.time()-before)*1000, 2)})
            try:
                current = json.loads(state.read_text())
                ready = current.get('managed') and current.get('phase') in ('stable', 'retained')
            except (OSError, ValueError):
                ready = False
            stable = stable + 1 if ready and status == 200 else 0
            if stable >= 12:
                break
            # Keep ordinary checks below the public request limit. A 429 is
            # still recorded; the monitor never bypasses production protection.
            time.sleep(1.5)
    result = {'started': started, 'finished': time.time(), 'samples': len(samples),
              'non_200': sum(s['status'] != 200 for s in samples), 'stable_at_end': stable >= 12,
              'note': 'Initial legacy-to-proxy transition; later A/B deployments have separate measurements.',
              'observations': samples}
    Path(report).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'observations'}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True); parser.add_argument('--seconds', type=int, default=600)
    args=parser.parse_args()
    if not 1 <= args.seconds <= 900:
        parser.error('seconds must be between 1 and 900')
    observe(args.report, args.seconds)

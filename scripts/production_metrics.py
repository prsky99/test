"""One daily line of production figures (PM 11-18 19:13, production system v2, section 6).

    .venv/bin/python -m scripts.production_metrics [--root DIR] [--day YYYY-MM-DD] [--write]

Counts from files and code only, nothing is requested from the site:
  - open necklaces (live) and previews, from the judged snapshot (gateway-data/necklaces/necklaces.json) with the same
    offered() rule the public pages use,
  - pearls, final and verified (pearl_badge.counts(), the public list gateway-data/pearls/public-pearls.json),
  - the necklace line by stage, from the files: drafts (agent_market/necklaces/drafts/*.json) -> candidates (definitions with
    status candidate) -> previews (status preview) -> live (status live),
  - successful external necklace runs of one KST day (default: yesterday), by agent_market/necklaces/north_star.py (the same
    counting the board and the public figures use; cached answers, our own checks, crawlers and probes are not counted).
--write appends the same line as JSON to logs/ops/production-daily.jsonl (one line per day, replaced when run again).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))


def stage_counts(root):
    """{'draft', 'candidate', 'preview', 'live'} from the files: drafts are the draft files, the others count definitions by status."""
    base = Path(root) / 'agent_market/necklaces'
    out = {'draft': len(list((base / 'drafts').glob('*.json'))), 'candidate': 0, 'preview': 0, 'live': 0}
    for path in sorted((base / 'definitions').glob('*.json')):
        try:
            status = json.loads(path.read_text(encoding='utf-8')).get('status')
        except (OSError, ValueError):
            continue
        if status in out and status != 'draft':
            out[status] += 1
    return out


def collect(root, day=None, now=None):
    """The figures as a dict. The environment root is set first because the public readers find their files through it."""
    root = Path(root)
    os.environ['AGENTCON_PROJECT_ROOT'] = str(root)
    from agent_market.concierge import necklace_surface as ns
    from agent_market.concierge import pearl_badge
    from agent_market.necklaces import north_star
    now = now or datetime.now(timezone.utc)
    day = day or (now.astimezone(KST) - timedelta(days=1)).strftime('%Y-%m-%d')
    snapshot = ns.load(root / 'gateway-data/necklaces/necklaces.json')
    pearl_badge._cache.update(key=None, value={}, counts={'final': 0, 'verified': 0, 'jobs': 0, 'agents': 0})    # read the file now
    counts = pearl_badge.counts()
    runs = north_star.day_metric(root / 'gateway-data/necklaces', day)
    return {'at': now.astimezone(KST).strftime('%Y-%m-%d %H:%M KST'), 'necklaces_open': ns.live_count(snapshot, now),
            'necklaces_preview': ns.preview_count(snapshot, now), 'pearls_final': counts['final'], 'pearls_verified': counts['verified'],
            'pearl_jobs': counts['jobs'], 'pearl_agents': counts['agents'], 'stages': stage_counts(root),
            'external_runs_day': day, 'external_runs_succeeded': runs['succeeded'], 'external_runs': runs['external_runs']}


def line(m):
    s = m['stages']
    return ('%s | necklaces open %d, preview %d | pearls final %d, verified %d (%d jobs, %d agents) | stages draft %d > candidate %d > '
            'preview %d > live %d | external necklace runs %s: %d succeeded of %d'
            % (m['at'], m['necklaces_open'], m['necklaces_preview'], m['pearls_final'], m['pearls_verified'], m['pearl_jobs'],
               m['pearl_agents'], s['draft'], s['candidate'], s['preview'], s['live'], m['external_runs_day'],
               m['external_runs_succeeded'], m['external_runs']))


def write(root, m):
    """One line per KST day: a second run of the same day replaces its line."""
    path = Path(root) / 'logs/ops/production-daily.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    day = m['at'][:10]
    kept = []
    if path.exists():
        for old in path.read_text(encoding='utf-8').splitlines():
            try:
                if json.loads(old).get('at', '')[:10] != day:
                    kept.append(old)
            except ValueError:
                continue
    kept.append(json.dumps(m, separators=(',', ':'), sort_keys=True))
    path.write_text('\n'.join(kept) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description='One daily line of production figures (files and code only)')
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--day', default=None, help='KST day for the external runs (default: yesterday)')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    m = collect(args.root, args.day)
    print(line(m))
    if args.write:
        write(args.root, m)


if __name__ == '__main__':
    main()

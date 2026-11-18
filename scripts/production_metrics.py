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
Goals (PM 11-18 19:2x, user decision: at least 24 new pearls and 3 new public necklaces a day):
  - a new pearl is a (agent, role) pair that first shows in the public list at final or verified level in this run's day (pairs
    that need a direct connection, terms prohibits, are left out as the list rules say),
  - a new necklace is a necklace that first runs publicly (live or preview in the judged snapshot) in this run's day,
  - first sightings are kept in logs/ops/production-state.json; the first --write only sets the baseline (what already
    existed counts as zero new), until then the line says so. A shortfall carries to the next day's target.
--write appends the same line as JSON to logs/ops/production-daily.jsonl (one line per day, replaced when run again) and
records the day's goals in the state file.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
PEARL_TARGET, NECKLACE_TARGET = 24, 3


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


def pearl_pairs(pearl_badge):
    """Keys 'agent|role' of the public list at final or verified level, without the pairs that must be connected directly."""
    return {'%s|%s' % (agent, row['role']) for agent, found in pearl_badge.load().items() for row in found if not row.get('direct')}


def public_slugs(ns, snapshot, now):
    return {e['slug'] for e in snapshot.get('necklaces') or [] if isinstance(e, dict) and e.get('status') in ('live', 'preview')
            and ns.offered(e, now)}


def read_state(root):
    try:
        value = json.loads((Path(root) / 'logs/ops/production-state.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def goals(state, day, pairs, slugs):
    """(goal figures, state after the run). STATE None means no baseline yet: the figures are None and the new state is the baseline."""
    if state is None:
        return None, {'pearls': {k: 'baseline' for k in sorted(pairs)}, 'necklaces': {k: 'baseline' for k in sorted(slugs)}, 'days': {}}
    state = {'pearls': dict(state.get('pearls') or {}), 'necklaces': dict(state.get('necklaces') or {}), 'days': dict(state.get('days') or {})}
    for key in pairs:
        state['pearls'].setdefault(key, day)
    for key in slugs:
        state['necklaces'].setdefault(key, day)
    new_pearls = sum(1 for v in state['pearls'].values() if v == day)
    new_necklaces = sum(1 for v in state['necklaces'].values() if v == day)
    earlier = [d for d in state['days'] if d < day]
    last = state['days'][max(earlier)] if earlier else {}
    carry_pearls, carry_necklaces = int(last.get('pearl_carry_out', 0)), int(last.get('necklace_carry_out', 0))
    figures = {'new_pearls': new_pearls, 'pearl_target': PEARL_TARGET, 'pearl_shortfall': max(0, PEARL_TARGET - new_pearls),
               'pearl_carry_in': carry_pearls, 'pearl_carry_out': max(0, PEARL_TARGET + carry_pearls - new_pearls),
               'new_necklaces': new_necklaces, 'necklace_target': NECKLACE_TARGET,
               'necklace_shortfall': max(0, NECKLACE_TARGET - new_necklaces), 'necklace_carry_in': carry_necklaces,
               'necklace_carry_out': max(0, NECKLACE_TARGET + carry_necklaces - new_necklaces)}
    state['days'][day] = figures
    return figures, state


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
    figures, after = goals(read_state(root), day, pearl_pairs(pearl_badge), public_slugs(ns, snapshot, now))
    return {'at': now.astimezone(KST).strftime('%Y-%m-%d %H:%M KST'), 'necklaces_open': ns.live_count(snapshot, now),
            'necklaces_preview': ns.preview_count(snapshot, now), 'pearls_final': counts['final'], 'pearls_verified': counts['verified'],
            'pearl_jobs': counts['jobs'], 'pearl_agents': counts['agents'], 'stages': stage_counts(root),
            'external_runs_day': day, 'external_runs_succeeded': runs['succeeded'], 'external_runs': runs['external_runs'],
            'goals': figures, '_state_after': after}


def goal_text(m):
    g = m.get('goals')
    if not g:
        return 'goals: baseline not set yet (the first --write sets it)'
    return ('new pearls %d of %d (short %d, carried in %d, carried on %d) | new necklaces %d of %d (short %d, carried in %d, carried on %d)'
            % (g['new_pearls'], g['pearl_target'] + g['pearl_carry_in'], g['pearl_shortfall'], g['pearl_carry_in'], g['pearl_carry_out'],
               g['new_necklaces'], g['necklace_target'] + g['necklace_carry_in'], g['necklace_shortfall'], g['necklace_carry_in'],
               g['necklace_carry_out']))


def line(m):
    s = m['stages']
    return ('%s | necklaces open %d, preview %d | pearls final %d, verified %d (%d jobs, %d agents) | stages draft %d > candidate %d > '
            'preview %d > live %d | external necklace runs %s: %d succeeded of %d | %s'
            % (m['at'], m['necklaces_open'], m['necklaces_preview'], m['pearls_final'], m['pearls_verified'], m['pearl_jobs'],
               m['pearl_agents'], s['draft'], s['candidate'], s['preview'], s['live'], m['external_runs_day'],
               m['external_runs_succeeded'], m['external_runs'], goal_text(m)))


def write(root, m):
    """One line per KST day: a second run of the same day replaces its line."""
    path = Path(root) / 'logs/ops/production-daily.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    after = m.pop('_state_after', None)
    if after is not None:
        (Path(root) / 'logs/ops/production-state.json').write_text(json.dumps(after, separators=(',', ':'), sort_keys=True), encoding='utf-8')
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

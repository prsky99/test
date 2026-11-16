"""Server time of real public requests, read from logs/ops/request-timing/<day>.jsonl (PM 11-16, 운영·SRE side).

    .venv/bin/python -m scripts.request_timing_report hourly [--day 2026-11-17]   # median server_ms by hour and kind
    .venv/bin/python -m scripts.request_timing_report prune [--keep 14]          # remove days older than 14

The frontend (RequestTiming, search team, r11) appends one line per timed request after the answer is sent:
{"at": epoch seconds, "path": "mcp|a2a|chat|agents_best|api_explore|api_agents|api_feed|api_agent_v1_discover",
 "status": 200, "server_ms": 1234.5, "qa": false, "stages": {...}} - no query text, IP or user agent (11-10 user
decision). Lines from our own measurements and tests carry qa true and are left out of the medians here.

heavy_slot.server_guard reads recent() so the test-load guard judges real requests, not only the hourly sample.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / 'logs/ops/request-timing'
KEEP_DAYS = 14
KINDS = {'explore': ('api_explore',), 'recommend': ('mcp', 'a2a', 'chat', 'api_agent_v1_discover')}


def _median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def lines(start, end, directory=None):
    """Real (qa false) lines with start <= at < end, read from the day files that cover the span."""
    directory = Path(directory or DIR)
    day = datetime.fromtimestamp(start).date()
    last = datetime.fromtimestamp(end).date()
    out = []
    while day <= last:
        path = directory / f'{day.isoformat()}.jsonl'
        try:
            with path.open() as handle:
                for raw in handle:
                    try:
                        row = json.loads(raw)
                    except ValueError:
                        continue
                    at = row.get('at')
                    if (isinstance(at, (int, float)) and start <= at < end and not row.get('qa')
                            and isinstance(row.get('server_ms'), (int, float))):
                        out.append(row)
        except OSError:
            pass
        day += timedelta(days=1)
    return out


def kind_of(row):
    return next((kind for kind, paths in KINDS.items() if row.get('path') in paths), None)


def recent(now=None, minutes=20, directory=None):
    """{kind: (median server_ms, count)} of the last MINUTES of real requests."""
    now = time.time() if now is None else now
    found = {}
    for row in lines(now - minutes * 60, now, directory):
        kind = kind_of(row)
        if kind:
            found.setdefault(kind, []).append(row['server_ms'])
    return {kind: (_median(v), len(v)) for kind, v in found.items()}


def baseline(now=None, hours=24, skip_minutes=20, directory=None):
    """{kind: median of the hourly medians} over the HOURS before the recent window."""
    now = time.time() if now is None else now
    hourly = {}
    for row in lines(now - hours * 3600, now - skip_minutes * 60, directory):
        kind = kind_of(row)
        if kind:
            hour = int(row['at'] // 3600)
            hourly.setdefault(kind, {}).setdefault(hour, []).append(row['server_ms'])
    return {kind: _median([_median(v) for v in hours_.values()]) for kind, hours_ in hourly.items()}


def hourly_table(day, directory=None):
    start = datetime.fromisoformat(day).timestamp()
    table = {}
    for row in lines(start, start + 86400, directory):
        kind = kind_of(row) or row.get('path')
        hour = datetime.fromtimestamp(row['at']).strftime('%H')
        table.setdefault(hour, {}).setdefault(kind, []).append(row['server_ms'])
    return {h: {k: {'n': len(v), 'median_ms': round(_median(v), 1)} for k, v in kinds.items()}
            for h, kinds in sorted(table.items())}


def prune(keep=KEEP_DAYS, directory=None, today=None):
    """Remove day files older than KEEP days; returns the removed names."""
    directory = Path(directory or DIR)
    today = today or datetime.now().date()
    removed = []
    for path in sorted(directory.glob('????-??-??.jsonl')):
        try:
            day = datetime.strptime(path.stem, '%Y-%m-%d').date()
        except ValueError:
            continue
        if (today - day).days > keep:
            os.remove(path)
            removed.append(path.name)
    return removed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    h = sub.add_parser('hourly')
    h.add_argument('--day', default=datetime.now().date().isoformat())
    p = sub.add_parser('prune')
    p.add_argument('--keep', type=int, default=KEEP_DAYS)
    args = parser.parse_args(argv)
    if args.command == 'hourly':
        print(json.dumps(hourly_table(args.day), indent=1))
    else:
        print(json.dumps({'removed': prune(args.keep)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

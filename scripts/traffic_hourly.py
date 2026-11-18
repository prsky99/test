"""Visitor hours from the frontend's anonymous day files (PM 11-18, for deploy and maintenance times).

    .venv/bin/python -m scripts.traffic_hourly [--days 7] [--dir logs/service-frontend/traffic] [--end YYYY-MM-DD]

Reads the 'hourly' counters that agent_market/concierge/traffic.py writes (metric|HH, UTC hour, external requests only) from
the last DAYS day files, adds the processes of one day, and prints for each metric:
  1. the totals per UTC hour,
  2. the same totals in US Eastern, US Pacific, Central Europe (Berlin) and Korea time (each day converted with its own offset,
     so a daylight-saving change inside the window is handled),
  3. the quietest three-hour window of the day per time zone (the best time for a deploy or maintenance), by total count.
Files only: nothing is requested from the site and nothing is written. Days without an 'hourly' section (before the counters
were deployed) are listed and skipped, never read as zero.
"""
import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / 'logs/service-frontend/traffic'
ZONES = (('UTC', 'UTC'), ('US Eastern', 'America/New_York'), ('US Pacific', 'America/Los_Angeles'),
         ('Central Europe', 'Europe/Berlin'), ('Korea', 'Asia/Seoul'))
WINDOW = 3


def read_days(folder, days, end=None):
    """({day: {'metric|HH': n}}, [days skipped for having no hourly section], [days in the window]) for the last DAYS days."""
    folder = Path(folder)
    last = date.fromisoformat(end) if end else datetime.now(timezone.utc).date()
    wanted = [(last - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    have, skipped = {}, []
    for day in wanted:
        merged, seen = Counter(), False
        for path in sorted(folder.glob(day + '.*.json')):
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data.get('hourly'), dict):
                seen = True
                for key, value in data['hourly'].items():
                    if isinstance(value, int) and value >= 0:
                        merged[key] += value
        (have.__setitem__(day, dict(merged)) if seen else skipped.append(day))
    return have, skipped, wanted


def by_utc_hour(days):
    """{metric: [24 totals]} in UTC hours, added over the days."""
    out = defaultdict(lambda: [0] * 24)
    for counts in days.values():
        for key, value in counts.items():
            metric, _, hour = key.rpartition('|')
            if metric and hour.isdigit() and 0 <= int(hour) <= 23:
                out[metric][int(hour)] += value
    return dict(sorted(out.items()))


def by_local_hour(days, zone):
    """{metric: [24 totals]} in the zone's hours; every UTC hour of a day is moved by that day's own offset."""
    tz = ZoneInfo(zone)
    out = defaultdict(lambda: [0] * 24)
    for day, counts in days.items():
        for key, value in counts.items():
            metric, _, hour = key.rpartition('|')
            if metric and hour.isdigit() and 0 <= int(hour) <= 23:
                moment = datetime.fromisoformat(day).replace(hour=int(hour), tzinfo=timezone.utc).astimezone(tz)
                out[metric][moment.hour] += value
    return dict(sorted(out.items()))


def quietest_window(hours, width=WINDOW):
    """(start hour, total) of the lowest sum over WIDTH consecutive hours of the 24-hour circle; the earliest start wins a tie."""
    best = None
    for start in range(24):
        total = sum(hours[(start + i) % 24] for i in range(width))
        if best is None or total < best[1]:
            best = (start, total)
    return best


def render(days, skipped, wanted):
    lines = ['# Visitor hours (UTC counters from the frontend day files)', '',
             'Window: %s to %s (%d days). Days with counters: %d%s. Days before the counters existed are skipped, not counted as zero.'
             % (wanted[0], wanted[-1], len(wanted), len(days), ' (' + ', '.join(skipped) + ' skipped)' if skipped else ''), '']
    if not days:
        return '\n'.join(lines + ['No day in the window has hourly counters yet.'])
    for name, zone in ZONES:
        table = by_utc_hour(days) if zone == 'UTC' else by_local_hour(days, zone)
        lines += ['## %s (%s)' % (name, zone), '', '| metric | total | ' + ' | '.join(format(h, '02d') for h in range(24)) + ' | quietest 3 h |',
                  '|---|---|' + '---|' * 24 + '---|']
        for metric, hours in table.items():
            start, low = quietest_window(hours)
            lines.append('| %s | %d | %s | %02d:00-%02d:00 (%d) |' % (metric, sum(hours), ' | '.join(str(v) for v in hours), start,
                                                                       (start + WINDOW) % 24, low))
        lines.append('')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Visitor hours from the frontend day files (files only)')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--dir', default=str(DEFAULT_DIR))
    parser.add_argument('--end', default=None, help='last day, UTC (default: today)')
    args = parser.parse_args(argv)
    days, skipped, wanted = read_days(args.dir, max(1, min(args.days, 60)), args.end)
    print(render(days, skipped, wanted))


if __name__ == '__main__':
    main()

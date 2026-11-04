"""Field Core Web Vitals (11-04, five-point plan step 3): LCP, INP and CLS from real page loads.

The page sends one small beacon when it is hidden. Nothing identifies the visitor: no cookie, no
IP address, no user agent and no URL beyond a short page name are stored. Visitors with Global
Privacy Control or Do Not Track never send it. Each record is one JSON line in a daily file under
LOG_DIR/rum, and `python -m agent_market.concierge.rum [dir] [days]` prints the p75 figures.
"""
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_BODY = 512
PAGE = re.compile(r'[a-z][a-z-]{0,23}')
DEVICES = ('phone', 'desktop')
LIMITS = {'lcp': 60_000, 'inp': 20_000, 'cls': 10}
GOOD = {'lcp': 2500, 'inp': 200, 'cls': 0.1}  # web.dev thresholds at p75


class RumError(ValueError):
    pass


def directory():
    return Path(os.environ.get('LOG_DIR') or 'logs/service-frontend') / 'rum'


def parse(raw):
    """One beacon body to a record, or RumError. Unknown fields are dropped, numbers are bounded."""
    if len(raw) > MAX_BODY:
        raise RumError('too large')
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise RumError('not json') from None
    if not isinstance(body, dict):
        raise RumError('not an object')
    page = body.get('page')
    record = {'page': page if isinstance(page, str) and PAGE.fullmatch(page) else 'other',
              'device': body.get('device') if body.get('device') in DEVICES else 'desktop'}
    for name, limit in LIMITS.items():
        value = body.get(name)
        if value is None:
            record[name] = None
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= limit:
            raise RumError(name)
        record[name] = round(float(value), 3) if name == 'cls' else int(value)
    if record['lcp'] is None:
        raise RumError('lcp')
    return record


def record(raw, now=None, root=None):
    entry = parse(raw)
    now = now or datetime.now(timezone.utc)
    entry['hour'] = now.strftime('%Y-%m-%dT%H')
    target = (root or directory())
    target.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, separators=(',', ':')) + '\n').encode()
    fd = os.open(target / (now.strftime('%Y-%m-%d') + '.jsonl'), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)  # one short O_APPEND write, so the two frontend slots never interleave a line
    finally:
        os.close(fd)
    return entry


def p75(values):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, math.ceil(0.75 * len(values)) - 1)]


def summary(root=None, days=7, today=None):
    """p75 per metric for all loads and per page/device, over the last DAYS daily files."""
    root = root or directory()
    today = today or datetime.now(timezone.utc).date()
    rows = []
    for offset in range(days):
        path = root / ((today - timedelta(days=offset)).isoformat() + '.jsonl')
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue

    def figures(group):
        out = {'loads': len(group)}
        for name in LIMITS:
            value = p75([row[name] for row in group if row.get(name) is not None])
            out[name] = value
            out[name + '_good'] = None if value is None else value <= GOOD[name]
        return out

    groups = {}
    for row in rows:
        groups.setdefault(row.get('page', 'other') + '/' + row.get('device', 'desktop'), []).append(row)
    return {'days': days, 'all': figures(rows), 'groups': {key: figures(group) for key, group in sorted(groups.items())}}


if __name__ == '__main__':
    args = sys.argv[1:]
    print(json.dumps(summary(Path(args[0]) if args else None, int(args[1]) if len(args) > 1 else 7), indent=2))

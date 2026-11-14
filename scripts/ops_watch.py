#!/usr/bin/env python3
"""Ten-minute work-status check (11-10 user request). Cheap, read-only, no Claude needed.

Prints one JSON line and appends it to logs/ops/watch.jsonl. "anomalies" lists only what needs action:
- site: public pages that do not answer 200 within 8 s on two fresh connections
  (one failed try that the retry answers is kept under "site_path" with the net-path line, not alerted)
- deploy_lock: the status board deploy lock held for more than 40 minutes
- long_tests: pytest or release_gate processes running for more than 60 minutes
- deploy_stuck: service_deploy processes running for more than 30 minutes
- memory: system memory free below 15 percent
- swap: swap 90 percent used, or growing by 1 GB or more in the last hour (11-14 PM; every run records swap use,
  its hourly trend and the five processes with the most resident memory)
- disk: data volume 85 percent used or less than 60 GB free
- stale_handoffs: status board hand-offs still "대기" (waiting) for more than 6 hours (by board mtime)
Exit code 0 always; the caller reads "anomalies".
"""
import json
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'logs/ops/status-board.md'
OUT = ROOT / 'logs/ops/watch.jsonl'
NET_PATH = ROOT / 'logs/ops/net-path.jsonl'
URLS = ('https://agentconcierge.biz/', 'https://agentconcierge.biz/llms.txt',
        'https://agentconcierge.biz/api/explore?q=weather')


def etime_seconds(text):
    """ps etime [[dd-]hh:]mm:ss -> seconds."""
    days, _, rest = text.strip().rpartition('-')
    parts = [int(p) for p in rest.split(':')]
    while len(parts) < 3:
        parts.insert(0, 0)
    return int(days or 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def processes():
    rows = subprocess.run(['ps', '-eo', 'pid,etime,args'], capture_output=True, text=True).stdout.splitlines()[1:]
    for row in rows:
        pid, etime, args = row.strip().split(None, 2)
        yield int(pid), etime_seconds(etime), args


def fetch(url):
    """One GET on a fresh connection: (status or error name, seconds)."""
    started = time.time()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'agentcon-ops-watch/1 (site owner QA)'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            code = resp.status
    except Exception as error:  # noqa: BLE001 - any failure is the signal
        code = getattr(error, 'code', None) or type(error).__name__
    return code, round(time.time() - started, 2)


def nearest_path_record(at=None, window=150):
    """The logs/ops/net-path.jsonl line closest to now (within window s), for the measuring side's line."""
    at = at or time.time()
    best = None
    try:
        lines = NET_PATH.read_text().splitlines()[-30:]
    except OSError:
        return None
    for line in lines:
        try:
            row = json.loads(line)
            gap = abs(datetime.strptime(row['at'], '%Y-%m-%d %H:%M:%S').timestamp() - at)
        except (ValueError, KeyError, TypeError):
            continue
        if gap <= window and (best is None or gap < best[0]):
            best = (gap, {k: row.get(k) for k in ('at', 'gateway_ms', 'internet_ms', 'edge', 'public')})
    return best[1] if best else None


def check_site(retry_wait=2.0):
    """Returns (bad, path). A failure that a second fresh connection answers with 200 within 8 s goes to path:
    the site answered, the stall was one connection from this Mac (11-12 16:12: llms.txt 8.5 s while the
    net-path probe saw TLS 1.4 s and a 5 s TCP stall to Cloudflare LAX, gateway and origin clean).
    Both tries are kept; only a failure on both counts as a site anomaly."""
    bad, path = [], []
    for url in URLS:
        code, took = fetch(url)
        if code == 200 and took <= 8:
            continue
        first = {'url': url, 'status': code, 'seconds': took}
        if code in (403, 429):  # our own security answer: a real signal, retrying would only add a violation
            bad.append(first)
            continue
        time.sleep(retry_wait)
        code2, took2 = fetch(url)
        first['retry'] = {'status': code2, 'seconds': took2}
        if code2 == 200 and took2 <= 8:
            first['net_path'] = nearest_path_record()
            path.append(first)
        else:
            bad.append(first)
    return bad, path


def check_board():
    found = {}
    if not BOARD.is_file():
        return found
    text = BOARD.read_text()
    lock = text.split('## 배포 잠금', 1)[-1].split('##', 1)[0]
    stamp = re.search(r'(\d{2})-(\d{2}) (\d{2}):(\d{2})', lock)
    if stamp and '비어 있음' not in lock:
        now = datetime.now()
        held = datetime(now.year, int(stamp[1]), int(stamp[2]), int(stamp[3]), int(stamp[4]))
        minutes = (now - held).total_seconds() / 60
        if minutes > 40:
            found['deploy_lock'] = {'held_minutes': round(minutes), 'line': lock.strip().splitlines()[0][:120]}
    handoffs = text.split('## 넘기는 일', 1)[-1].split('##', 1)[0]
    waiting = [line.strip()[:120] for line in handoffs.splitlines() if line.startswith('|') and '대기' in line]
    age_hours = (time.time() - BOARD.stat().st_mtime) / 3600
    if waiting and age_hours > 6:
        found['stale_handoffs'] = waiting
    return found


def check_memory():
    out = subprocess.run(['memory_pressure'], capture_output=True, text=True).stdout
    match = re.search(r'free percentage: (\d+)%', out)
    return int(match[1]) if match else None


SWAP_FULL, SWAP_GROWTH_MB = 0.90, 1024


def check_swap(text=None):
    """vm.swapusage as used/total MB, or None."""
    if text is None:
        text = subprocess.run(['sysctl', '-n', 'vm.swapusage'], capture_output=True, text=True).stdout
    total, used = re.search(r'total = ([\d.]+)M', text or ''), re.search(r'used = ([\d.]+)M', text or '')
    return {'used_mb': round(float(used[1])), 'total_mb': round(float(total[1]))} if total and used else None


def swap_trend(now_used, records, minutes=60):
    """MB per hour from the record about MINUTES ago (watch.jsonl rows have 'at' and 'swap'), or None."""
    target = datetime.now().timestamp() - minutes * 60
    best = None
    for row in records:
        try:
            at = datetime.strptime(row['at'], '%Y-%m-%d %H:%M').timestamp()
            used = row['swap']['used_mb']
        except (KeyError, TypeError, ValueError):
            continue
        if abs(at - target) <= 15 * 60 and (best is None or abs(at - target) < abs(best[0] - target)):
            best = (at, used)
    if best is None or now_used is None:
        return None
    hours = (datetime.now().timestamp() - best[0]) / 3600
    return round((now_used - best[1]) / hours) if hours > 0 else None


def top_memory(n=5, text=None):
    """The N processes with the most resident memory: [[name#pid, MB], ...]."""
    if text is None:
        text = subprocess.run(['ps', '-Ao', 'pid=,rss=,comm='], capture_output=True, text=True).stdout
    rows = []
    for line in (text or '').splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[1]), f"{parts[2].rsplit('/', 1)[-1][:40]}#{parts[0]}"))
    return [[name, round(rss / 1024)] for rss, name in sorted(rows, reverse=True)[:n]]


def recent_records(path, lines=12):
    try:
        tail = path.read_text().splitlines()[-lines:]
    except OSError:
        return []
    out = []
    for line in tail:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def check_disk():
    import shutil
    try:
        usage = shutil.disk_usage('/System/Volumes/Data')
    except OSError:
        return None
    return {'used_percent': round(usage.used * 100 / usage.total), 'free_gb': round(usage.free / 1e9)}


def main():
    anomalies = {}
    site, site_path = check_site()
    if site:
        anomalies['site'] = site
    long_tests, stuck = [], []
    for pid, seconds, args in processes():
        if ('pytest' in args or 'release_gate' in args) and 'grep' not in args and seconds > 3600:
            long_tests.append({'pid': pid, 'minutes': seconds // 60, 'cmd': args[:100]})
        if 'scripts.service_deploy' in args and seconds > 1800:
            stuck.append({'pid': pid, 'minutes': seconds // 60, 'cmd': args[:100]})
    if long_tests:
        anomalies['long_tests'] = long_tests
    if stuck:
        anomalies['deploy_stuck'] = stuck
    free = check_memory()
    if free is not None and free < 15:
        anomalies['memory'] = {'free_percent': free}
    swap = check_swap()
    if swap:
        swap['trend_mb_per_h'] = swap_trend(swap['used_mb'], recent_records(OUT))
        if (swap['total_mb'] and swap['used_mb'] >= SWAP_FULL * swap['total_mb']) or (swap['trend_mb_per_h'] or 0) >= SWAP_GROWTH_MB:
            anomalies['swap'] = dict(swap)
    disk = check_disk()
    if disk and (disk['used_percent'] >= 85 or disk['free_gb'] < 60):
        anomalies['disk'] = disk
    anomalies.update(check_board())
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M'), 'memory_free_percent': free,
              'swap': swap, 'top_memory': top_memory(), 'anomalies': anomalies}
    if site_path:  # recorded, not alerted: the second fresh connection got 200 (see check_site)
        record['site_path'] = site_path
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('a') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

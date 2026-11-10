#!/usr/bin/env python3
"""Ten-minute work-status check (11-10 user request). Cheap, read-only, no Claude needed.

Prints one JSON line and appends it to logs/ops/watch.jsonl. "anomalies" lists only what needs action:
- site: public pages that do not answer 200 within 8 s
- deploy_lock: the status board deploy lock held for more than 40 minutes
- long_tests: pytest or release_gate processes running for more than 60 minutes
- deploy_stuck: service_deploy processes running for more than 30 minutes
- memory: system memory free below 15 percent
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


def check_site():
    bad = []
    for url in URLS:
        started = time.time()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'agentcon-ops-watch/1 (site owner QA)'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                code = resp.status
        except Exception as error:  # noqa: BLE001 - any failure is the signal
            code = getattr(error, 'code', None) or type(error).__name__
        took = round(time.time() - started, 2)
        if code != 200 or took > 8:
            bad.append({'url': url, 'status': code, 'seconds': took})
    return bad


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


def check_disk():
    import shutil
    try:
        usage = shutil.disk_usage('/System/Volumes/Data')
    except OSError:
        return None
    return {'used_percent': round(usage.used * 100 / usage.total), 'free_gb': round(usage.free / 1e9)}


def main():
    anomalies = {}
    site = check_site()
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
    disk = check_disk()
    if disk and (disk['used_percent'] >= 85 or disk['free_gb'] < 60):
        anomalies['disk'] = disk
    anomalies.update(check_board())
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M'), 'memory_free_percent': free,
              'anomalies': anomalies}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('a') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

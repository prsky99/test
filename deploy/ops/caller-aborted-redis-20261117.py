"""Take back the 4 timeout counts the Edge Worker c2702834 left in the 7-day task outcome counts (11-17 PM decision 2).

Between 08:41 and 10:48 the origin counted four calls our own runner cut at 3.5 s as provider timeouts
(concierge.task_outcomes.count): 147960 once, 241601 three times. This script subtracts exactly those from the
top-level "timeout" of each listing's task-outcome key (never below 0), keeps the key's remaining TTL (SET KEEPTTL),
and writes the values before the change to gateway-data/ops/caller-aborted-1117/redis-before.json.

  .venv/bin/python deploy/ops/caller-aborted-redis-20261117.py            # dry run: prints keys and the change
  .venv/bin/python deploy/ops/caller-aborted-redis-20261117.py --apply    # PM runs this
  .venv/bin/python deploy/ops/caller-aborted-redis-20261117.py --restore  # puts the saved values back (KEEPTTL)

The Redis address is read from gateway-data/agentcon.env inside this process only (REDIS_URL or REDIS_HOST/PORT/DB),
like the other ops tools; nothing is exported to the shell. Refuses to run under pytest.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / 'gateway-data/ops/caller-aborted-1117/redis-before.json'
TAKE_BACK = {147960: 1, 241601: 3}
KEY = 'task-outcome:v1:'


def settings():
    env = {}
    for line in (ROOT / 'gateway-data/agentcon.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def client():
    import redis
    env = settings()
    if env.get('REDIS_URL'):
        return redis.Redis.from_url(env['REDIS_URL'], decode_responses=True)
    return redis.Redis(host=env.get('REDIS_HOST', '127.0.0.1'), port=int(env.get('REDIS_PORT', '6379')),
                       db=int(env.get('REDIS_DB', '0')), password=env.get('REDIS_PASSWORD') or None, decode_responses=True)


def keys(r, rid):
    return sorted(set(r.scan_iter(match=f'*{KEY}{rid}', count=1000)))


def main(argv):
    if 'PYTEST_CURRENT_TEST' in os.environ:
        print('refused under pytest'); return 2
    r = client()
    if '--restore' in argv:
        saved = json.loads(BACKUP.read_text())
        for key, raw in saved.items():
            r.set(key, raw, keepttl=True)
            print('restored', key)
        return 0
    plan, before = [], {}
    for rid, n in TAKE_BACK.items():
        found = keys(r, rid)
        if not found:
            print(f'{rid}: no task-outcome key (expired or never written); nothing to take back')
        for key in found:
            raw = r.get(key)
            value = json.loads(raw) if raw else {}
            old = int(value.get('timeout') or 0)
            new = max(0, old - n)
            print(f'{key}: timeout {old} -> {new} (ttl {r.ttl(key)} s)')
            if new != old:
                before[key] = raw
                value['timeout'] = new
                plan.append((key, json.dumps(value)))
    if '--apply' not in argv:
        print('dry run; add --apply to write'); return 0
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_text(json.dumps(before, ensure_ascii=False, indent=1))
    os.chmod(BACKUP, 0o600)
    for key, raw in plan:
        r.set(key, raw, keepttl=True)
    print(f'applied {len(plan)} keys; before values in {BACKUP}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

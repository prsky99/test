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
- adcoin_daemon: the AD Coin worker daemon is not running, its LaunchAgents plist is gone (launchd would not start it
  after a reboot), or its code (the daemon script and agent_market/ad_coin .py/.json) differs from the active
  frontend release, so it needs a reinstall (11-14 PM). Every run records its state and release.
Every run also records production database connections per role (11-15 PM, no database session: the client side
of each Unix socket is matched to a backend of the production postmaster with lsof), to learn the daytime peak.
Precision review R53 (11-15) adds, every run:
- launchd_jobs: biz.agentconcierge.* launchd jobs (not the driveragent project) whose last exit status is not 0
- backup: the newest complete daily snapshot older than 26 hours, or the last backup run's offsite copy not ok
- core_down: PostgreSQL, Redis, OpenSearch, cloudflared, jobs or execution not running
- site checks run first and stop after SITE_BUDGET seconds (the rest is recorded as not checked)
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


SITE_BUDGET = 45   # seconds for all site checks together (R53: a hung check must not hold the whole watch)


def check_site(retry_wait=2.0, budget=SITE_BUDGET, clock=time.monotonic):
    """Returns (bad, path). A failure that a second fresh connection answers with 200 within 8 s goes to path:
    the site answered, the stall was one connection from this Mac (11-12 16:12: llms.txt 8.5 s while the
    net-path probe saw TLS 1.4 s and a 5 s TCP stall to Cloudflare LAX, gateway and origin clean).
    Both tries are kept; only a failure on both counts as a site anomaly."""
    bad, path = [], []
    deadline = clock() + budget
    for url in URLS:
        if clock() >= deadline:
            bad.append({'url': url, 'status': 'not_checked', 'reason': 'site_budget_exceeded'})
            continue
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


DAEMON = 'biz.agentconcierge.498590e0b3.adcoin-worker'
RELEASES = ROOT / 'gateway-data/services/releases'
SERVICE_STATE = ROOT / 'gateway-data/services/state.json'


def _daemon_code(release_dir):
    """sha256 over the files the worker daemon runs (its script and agent_market/ad_coin .py/.json), or None."""
    import hashlib
    files = [release_dir / 'scripts/ad_coin_worker_daemon.py']
    files += sorted(f for f in (release_dir / 'agent_market/ad_coin').rglob('*') if f.suffix in ('.py', '.json'))
    digest = hashlib.sha256()
    try:
        for f in files:
            digest.update(str(f.relative_to(release_dir)).encode() + b'\0' + f.read_bytes())
    except (OSError, ValueError):
        return None
    return digest.hexdigest()


def check_adcoin_daemon(printed=None, plist_dir=None, releases=None, state_file=None):
    """State of the AD Coin worker daemon and the problems to act on ('not_running', 'plist_missing',
    'reinstall_needed'). 11-14: it ran from adv-frontend-20261114-r1 with no plist on disk."""
    import os
    if printed is None:
        try:
            printed = subprocess.run(['launchctl', 'print', 'gui/%d/%s' % (os.getuid(), DAEMON)],
                                     capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            printed = ''
    releases = Path(releases or RELEASES)
    state = {'running': 'state = running' in printed,
             'release': next((line.split('/releases/', 1)[1].split('/', 1)[0] for line in printed.splitlines()
                              if line.strip().startswith('working directory') and '/releases/' in line), None),
             'plist_on_disk': (Path(plist_dir or Path.home() / 'Library/LaunchAgents') / (DAEMON + '.plist')).exists()}
    try:
        fe = json.loads(Path(state_file or SERVICE_STATE).read_text())['services']['frontend']
        state['active_frontend'] = fe['slots'][fe['active']]
    except (OSError, ValueError, KeyError):
        state['active_frontend'] = None
    problems = []
    if not state['running']:
        problems.append('not_running')
    if not state['plist_on_disk']:
        problems.append('plist_missing')
    if state['running'] and state['release'] and state['active_frontend'] and state['release'] != state['active_frontend']:
        ran, active = _daemon_code(releases / state['release']), _daemon_code(releases / state['active_frontend'])
        state['code_same_as_active'] = bool(ran and active and ran == active)
        if ran and active and ran != active:
            problems.append('reinstall_needed')
    state['problems'] = problems
    return state


PG_PID_FILE = ROOT / 'gateway-data/postgres18/data/postmaster.pid'
ROLES = ('frontend', 'jobs', 'admin', 'execution')


def _unix_sockets(args):
    out = subprocess.run(['lsof', '-a', '-U', '-F', 'pdn'] + args, capture_output=True, text=True, timeout=20).stdout
    rows, pid, dev = [], None, None
    for line in out.splitlines():
        if line[:1] == 'p':
            pid = int(line[1:])
        elif line[:1] == 'd':
            dev = line[1:]
        elif line[:1] == 'n':
            rows.append((pid, dev, line[1:]))
    return rows


def _service_role(args):
    if 'ad_coin_worker_daemon' in args:
        return 'adcoin_daemon'
    release = args.split('/releases/', 1)[1].split('/', 1)[0] if '/releases/' in args else ''
    return next((role for role in ROLES if '-%s-' % role in '-%s-' % release), None)


def db_connections(ps_text=None, sockets=None, postmaster=None):
    """Connections to the production database per role, by matching sockets; None when it cannot tell."""
    try:
        postmaster = postmaster or int(PG_PID_FILE.read_text().split()[0])
        ps_text = ps_text if ps_text is not None else subprocess.run(['ps', '-Ao', 'pid=,ppid=,args='], capture_output=True,
                                                                     text=True, timeout=10).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    backends, services = set(), {}
    for line in ps_text.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        pid, ppid, args = int(parts[0]), int(parts[1]), parts[2]
        if ppid == postmaster:
            backends.add(pid)
        elif '/releases/' in args.split(' ', 1)[0] and '/bin/python' in args.split(' ', 1)[0]:   # not shells quoting it
            role = _service_role(args)
            if role:
                services[pid] = role
    try:
        given = sockets is not None   # tests pass every socket; live runs ask lsof per service process
        sockets = sockets if given else _unix_sockets(['-c', 'postgres'])
        server = {dev for pid, dev, _ in sockets if pid in backends}
        roles, processes = {}, {}
        for pid, role in services.items():
            mine = [row for row in sockets if row[0] == pid] if given else _unix_sockets(['-p', str(pid)])
            roles[role] = roles.get(role, 0) + sum(1 for _, _, name in mine if name.startswith('->') and name[2:] in server)
            processes[role] = processes.get(role, 0) + 1
    except (OSError, subprocess.SubprocessError):
        return None
    total = len(server)
    return {'total': total, 'roles': roles, 'processes': processes, 'other': total - sum(roles.values())}


LAUNCHD_PREFIX = 'biz.agentconcierge.'
BACKUPS = ROOT / 'gateway-data/backups/daily'
BACKUP_LOG = ROOT / 'logs/services/biz.agentconcierge.backup.log'
BACKUP_MAX_HOURS = 26


def check_launchd(text=None):
    """(jobs, bad): every biz.agentconcierge.* launchd job with its PID and last exit status (driveragent excluded)."""
    if text is None:
        try:
            text = subprocess.run(['launchctl', 'list'], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return {}, []
    jobs = {}
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) != 3 or not parts[2].startswith(LAUNCHD_PREFIX) or '.driveragent.' in parts[2]:
            continue
        pid, status, label = parts
        try:
            status = int(status)
        except ValueError:
            continue
        jobs[label] = {'pid': int(pid) if pid.isdigit() else None, 'status': status}
    bad = [{'label': label, **job} for label, job in sorted(jobs.items()) if job['status'] != 0]
    return jobs, bad


FINGERPRINTS = ROOT / 'gateway-data/fingerprints/pearls.json'
FINGERPRINT_MAX_HOURS = 12   # PM 11-15 11:5x: the members' file is refreshed every 6 hours; 12 hours old is a fault


def check_fingerprints(path=None, now=None):
    """Age of the pearl/necklace-member fingerprint file (its 'generated' time). On 11-15 it was found unchanged since
    11-14 04:21, so the necklace watch and the gate read two-day-old definitions without anyone noticing."""
    path, now = Path(path or FINGERPRINTS), now or time.time()
    try:
        generated = json.loads(path.read_text()).get('generated')
        at = datetime.strptime(generated, '%Y-%m-%dT%H:%M:%S%z').timestamp()
    except (OSError, ValueError, TypeError, AttributeError):
        return {'generated': None, 'age_hours': None, 'problems': ['fingerprint_file_unreadable']}
    age = round((now - at) / 3600, 1)
    problems = ['fingerprints_older_than_%dh' % FINGERPRINT_MAX_HOURS] if age > FINGERPRINT_MAX_HOURS else []
    return {'generated': generated, 'age_hours': age, 'problems': problems}


def check_verify_snapshot(path=None, now=None, official=None):
    """The pearl snapshot the necklace judge trusts (PM 11-15 16:17): on 11-15 it lacked evaluator_version from 10:22
    until 16:16, so the judge counted no pearl and no provisional member and nobody was told. The judge's own rule
    (agent_market.necklaces.judge.snapshot_problem): older than its limit, or graded by another evaluator than the
    official one in scripts/report_v2.py."""
    from agent_market.necklaces.judge import snapshot_problem, verify_snapshot_path
    path = Path(path) if path else ROOT / verify_snapshot_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {'generated': None, 'evaluator_version': None, 'problems': ['verify_snapshot_unreadable']}
    problem = snapshot_problem(data, now, official) if official else snapshot_problem(data, now)
    return {'generated': data.get('generated'), 'evaluator_version': data.get('evaluator_version'),
            'problems': [problem] if problem else []}


REFERENCE_FAILURES = ROOT / 'logs/ops/reference-failures.jsonl'


def check_reference_failures(path=None, now=None, hours=24):
    """Answer-key references that did not answer 200 in the last day (PM 11-15 16:45): on 11-15 api.frankfurter.app
    had moved (301) and every FX answer scored accuracy 0 without anyone being told. Grouped by host and status."""
    path, now = Path(path or REFERENCE_FAILURES), now or time.time()
    seen = {}
    for row in _lines(path):
        try:
            if now - float(row.get('at') or 0) > hours * 3600:
                continue
        except (TypeError, ValueError):
            continue
        from urllib.parse import urlsplit
        key = f"{urlsplit(str(row.get('url') or '')).hostname} {row.get('status') or row.get('detail') or 'error'}"
        seen[key] = seen.get(key, 0) + 1
    return {'failures': seen, 'problems': sorted(seen)}


NECKLACE_LOGS = ROOT / 'logs/ops/necklace-watch'
NECKLACE_ROOT = ROOT / 'gateway-data/necklaces'
REGISTRY_LOG = ROOT / 'logs/ops/registry-job.jsonl'
DRILL_LOG = ROOT / 'logs/ops/necklace-watch/drills.jsonl'   # the workflow team's weekly fallback drill (when it exists)
LIVE_HOURS = tuple(range(6, 23))                             # agent_market.necklace_schedule.LIVE_HOURS


def _quiet(local):
    """The jobs steps skip :55-:10 and 03:50-05:10 (necklace_schedule), so an hour may hold no run then."""
    hhmm = local.hour * 100 + local.minute
    return 350 <= hhmm <= 530


def _lines(path):
    try:
        return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


def _at(row):
    try:
        return datetime.strptime(row['at'], '%Y-%m-%dT%H:%M:%S%z').timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def check_necklace_runs(now=None, logs=None, root=None, registry=None, drills=None):
    """PM 11-15 14:57 (user: "do not forget the checks"): a necklace check that was due and did not run. Not the
    checks' results: their absence. Each jobs step leaves a line even with nothing to do (necklace_schedule), so a
    missing line is a missing run:
    - hourly necklace watch (:20, outside the quiet windows): no line for 90 minutes
    - daily summary (from 05:20): no <day>.md by 06:30
    - trial retests (01:15-02:25): no trial line by 02:40
    - live retests: a live necklace not in retest/started-<day>.json after the end (:50) of its own hour
    - verified registry snapshot (hourly) and E6 lifecycle (daily), once their first line exists
    - the weekly fallback drill, once its log exists: no line for 8 days"""
    import zlib
    now = now or time.time()
    local = datetime.fromtimestamp(now)
    logs, root = Path(logs or NECKLACE_LOGS), Path(root or NECKLACE_ROOT)
    day = local.strftime('%Y%m%d')
    rows = _lines(logs / f'runs-{day}.jsonl') + _lines(logs / f"runs-{datetime.fromtimestamp(now - 86400):%Y%m%d}.jsonl")
    problems = []
    watch = [t for r in rows if 'step' not in r and (t := _at(r))]
    last_watch = max(watch) if watch else None
    if not _quiet(local) and (last_watch is None or now - last_watch > 90 * 60):
        problems.append('necklace_watch_missed')
    if local.hour * 100 + local.minute >= 630 and not (logs / f'{day}.md').is_file():
        problems.append('necklace_daily_summary_missed')
    today = [r for r in rows if r.get('at', '').startswith(local.strftime('%Y-%m-%d'))]
    if local.hour * 100 + local.minute >= 240 and not any(r.get('kind') == 'trial' for r in today):
        problems.append('necklace_trial_retest_missed')
    try:
        live = [n['slug'] for n in json.loads((root / 'necklaces.json').read_text()).get('necklaces') or []
                if n.get('status') == 'live' and n.get('slug')]
    except (OSError, ValueError, AttributeError):
        live = []
    try:
        started = json.loads((root / 'retest' / f'started-{day}.json').read_text())
    except (OSError, ValueError):
        started = {}
    for slug in live:
        hour = LIVE_HOURS[zlib.crc32(slug.encode('utf-8')) % len(LIVE_HOURS)]
        if (local.hour, local.minute) > (hour, 50) and slug not in started:
            problems.append(f'live_retest_missed:{slug}')
    reg = _lines(registry or REGISTRY_LOG)
    for step, hours in (('verified_registry', 2), ('tool_lifecycle', 26)):
        times = [t for r in reg if (r.get('step') or 'verified_registry') == step and (t := datetime.strptime(
            r['at'], '%Y-%m-%dT%H:%M:%S%z').timestamp() if r.get('at') else None)]
        if times and now - max(times) > hours * 3600:
            problems.append(f'{step}_missed')
    drill = _lines(drills or DRILL_LOG)
    times = [t for r in drill if (t := _at(r))]
    if times and now - max(times) > 8 * 86400:
        problems.append('fallback_drill_missed')
    return {'last_watch': datetime.fromtimestamp(last_watch).strftime('%m-%d %H:%M') if last_watch else None,
            'live': len(live), 'problems': problems}


def substitute_states(path=None):
    """Latest state of each AgentValCon substitute in approvals.json (PM 11-15 16:03): approved (formal: gate 30 and
    report v2 >= 85) and provisional (gate 30 only; may sit as a temporary member). Recorded, never alerted."""
    try:
        rows = json.loads(Path(path or NECKLACE_ROOT / 'approvals.json').read_text()).get('substitutes') or []
    except (OSError, ValueError, AttributeError):
        return None
    latest = {}
    for row in rows:
        if isinstance(row, dict) and row.get('agent_id'):
            key = (row['agent_id'], row.get('slot_role'))
            if key not in latest or str(row.get('at')) >= str(latest[key].get('at')):
                latest[key] = row
    out = {}
    for (agent, _), row in sorted(latest.items()):
        out.setdefault(row.get('state') or 'unknown', []).append(agent)
    return out


def check_backup(root=None, log=None, now=None):
    """The newest complete snapshot's age and the last backup run's offsite result; problems listed."""
    root, log, now = Path(root or BACKUPS), Path(log or BACKUP_LOG), now or time.time()
    newest = None
    for path in sorted(root.glob('snapshot-*')) if root.is_dir() else []:
        try:
            manifest = json.loads((path / 'manifest.json').read_text())
        except (OSError, ValueError):
            continue
        newest = {'snapshot': path.name, 'finished': manifest.get('finished')}
    last = None
    try:
        for line in log.read_text().splitlines()[-20:]:
            try:
                last = json.loads(line)
            except ValueError:
                continue
    except OSError:
        pass
    problems = []
    age = round((now - newest['finished']) / 3600, 1) if newest and newest.get('finished') else None
    if age is None or age > BACKUP_MAX_HOURS:
        problems.append('snapshot_older_than_%dh' % BACKUP_MAX_HOURS)
    offsite = ((last or {}).get('offsite') or {}).get('status')
    if last is not None and last.get('status') != 'ok':
        problems.append('last_run_' + str(last.get('status')))
    elif last is not None and offsite != 'ok':
        problems.append('offsite_' + str(offsite))
    return {'newest': (newest or {}).get('snapshot'), 'age_hours': age, 'last_run': (last or {}).get('started'),
            'offsite': offsite, 'problems': problems}


CORE = {'postgres': 'biz.agentconcierge.postgres18', 'opensearch': 'biz.agentconcierge.opensearch',
        'jobs': '.jobs.main', 'execution': '.execution.main'}
CORE_PROCESSES = {'redis': 'redis-server', 'cloudflared': 'cloudflared'}


def check_core(jobs, ps_text=None):
    """Core services that are not running: launchd jobs without a PID, processes not in the process list."""
    if ps_text is None:
        try:
            ps_text = subprocess.run(['ps', '-Ao', 'comm='], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            ps_text = ''
    down = []
    for name, label in CORE.items():
        found = [job for key, job in jobs.items() if key == label or key.endswith(label)]
        if not found or not any(job['pid'] for job in found):
            down.append(name)
    names = [line.strip().rsplit('/', 1)[-1] for line in ps_text.splitlines()]
    down += [name for name, command in CORE_PROCESSES.items() if not any(n.startswith(command) for n in names)]
    return down


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
    daemon = check_adcoin_daemon()
    if daemon['problems']:
        anomalies['adcoin_daemon'] = daemon
    jobs, failed_jobs = check_launchd()
    if failed_jobs:
        anomalies['launchd_jobs'] = failed_jobs
    backup = check_backup()
    if backup['problems']:
        anomalies['backup'] = backup
    fingerprints = check_fingerprints()
    if fingerprints['problems']:
        anomalies['fingerprints'] = fingerprints
    pearl_snapshot = check_verify_snapshot()
    if pearl_snapshot['problems']:
        anomalies['pearl_snapshot'] = pearl_snapshot
    references = check_reference_failures()
    if references['problems']:
        anomalies['reference_sources'] = references
    necklace_runs = check_necklace_runs()
    if necklace_runs['problems']:
        anomalies['necklace_checks'] = necklace_runs
    down = check_core(jobs) if jobs else []
    if down:
        anomalies['core_down'] = down
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M'), 'memory_free_percent': free,
              'swap': swap, 'top_memory': top_memory(), 'adcoin_daemon': daemon,
              'db_connections': db_connections(), 'launchd': jobs, 'backup': backup, 'fingerprints': fingerprints, 'pearl_snapshot': pearl_snapshot, 'necklace_runs': necklace_runs,
              'substitutes': substitute_states(),
              'anomalies': anomalies}
    if site_path:  # recorded, not alerted: the second fresh connection got 200 (see check_site)
        record['site_path'] = site_path
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('a') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

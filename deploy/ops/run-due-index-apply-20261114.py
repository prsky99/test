"""Apply the resources_health_due_host index (deploy/db/resources-health-due-host-20261113.sql) to production. Run by the user.

User approval 11-14 02:4x (via PM) after a full-data rehearsal. From the repository root:

    .venv/bin/python deploy/ops/run-due-index-apply-20261114.py            # checks, then applies
    .venv/bin/python deploy/ops/run-due-index-apply-20261114.py --dry-run  # checks only, changes nothing

It stops at the first failed step and writes one line under '## DB 변경 창' in the board:
 1. Rehearsal: logs/ops/db-rehearsal/due-index-full-20261114.json says passed, full data, the change applied, and
    every release (frontend, jobs, admin, execution) attached, wrote and searched before and after.
 2. Time and neighbours: minute :10-:54, not 03:50-05:10 (real_task_score) or 20:45-21:59 (relay deploys), the deploy
    lock empty, no copy rehearsal and no graph-cap migrate running.
 3. Check 0: the exact command passed a rehearsal within 24 h against the four releases active now. If a release
    changed since, a minimal-data rehearsal of the same command runs first (heavy_slot) and must pass.
 4. Before: the application attaches, public triggers are 5, the index does not exist yet.
 5. Apply: the rehearsed command, psql CREATE INDEX CONCURRENTLY (writes are not blocked; no lock timeout, it waits
    for older transactions by design). The checks around it use a 2 s lock timeout.
 6. After: the application attaches, public triggers 5, the index is valid, five public Explore samples with no error
    or empty answer. Any failure runs the rollback (DROP INDEX CONCURRENTLY, .rollback.sql) and stops.
Writes logs/ops/due-index-apply-20261114.json and .log. Changes no table, trigger or function.
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, '.venv', 'bin', 'python')
PSQL = '/opt/homebrew/opt/postgresql@18/bin/psql'
DSN = os.path.join(ROOT, 'gateway-data', 'postgres18', 'application.dsn')
KEY = os.path.join(ROOT, 'gateway-data', 'collector.sqlite3.updates-key')
SQL = 'deploy/db/resources-health-due-host-20261113.sql'
ROLLBACK_SQL = 'deploy/db/resources-health-due-host-20261113.rollback.sql'
REPORT = os.path.join(ROOT, 'logs', 'ops', 'db-rehearsal', 'due-index-full-20261114.json')
PASSED = os.path.join(ROOT, 'logs', 'ops', 'db-rehearsal', 'passed.json')
STATE = os.path.join(ROOT, 'gateway-data', 'services', 'state.json')
BOARD = os.path.join(ROOT, 'logs', 'ops', 'status-board.md')
OUT = os.path.join(ROOT, 'logs', 'ops', 'due-index-apply-20261114.json')
INDEX = 'resources_health_due_host'
# The exact text rehearsed (db_change_rehearsal keys its pass record by this text).
COMMAND = PSQL + ' -v ON_ERROR_STOP=1 -f ' + SQL
TASKS = ['weather forecast', 'pdf to text', 'github issues', 'currency exchange rate', 'image resize',
         'translate document', 'calendar booking', 'send email', 'crypto price', 'web search']
DRY = '--dry-run' in sys.argv[1:]
result = {'started': datetime.now().isoformat(timespec='seconds'), 'dry_run': DRY}


def save():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT if not DRY else OUT.replace('.json', '.dry-run.json'), 'w') as stream:
        stream.write(json.dumps(result, indent=1, default=str))


def log(message):
    line = datetime.now().strftime('%F %T ') + message
    print(line, flush=True)
    with open(OUT.replace('.json', '.dry-run.log' if DRY else '.log'), 'a') as stream:
        stream.write(line + '\n')


def board(text):
    if DRY:
        return log('(dry run) board line: ' + text)
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    from heavy_slot import board_lock
    try:
        with board_lock():
            with open(BOARD, encoding='utf-8') as stream:
                lines = stream.read().split('\n')
            at = next(i for i, l in enumerate(lines) if l.startswith('## DB 변경 창'))
            lines.insert(at + 1, '- {} 운영·SRE due_for_check 인덱스 운영 적용(사용자 실행): {}'.format(
                datetime.now().strftime('%m-%d %H:%M'), text))
            with open(BOARD, 'w', encoding='utf-8') as stream:
                stream.write('\n'.join(lines))
    except Exception as error:
        log('board write failed: {}'.format(error))


def stop(text):
    log('STOP: ' + text)
    result['stopped'] = text
    save()
    board('중지 — {}'.format(text[:500]))
    sys.exit(1)


def pg_env(lock_timeout=True):
    """libpq variables from the application DSN, so the rehearsed command text runs unchanged. The checks use a 2 s
    lock timeout; the CONCURRENTLY build does not (it waits for older transactions by design and blocks no writes)."""
    names = {'host': 'PGHOST', 'port': 'PGPORT', 'dbname': 'PGDATABASE', 'user': 'PGUSER', 'password': 'PGPASSWORD'}
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    for part in open(DSN).read().split():
        key, _, value = part.partition('=')
        if key in names:
            env[names[key]] = value
    if lock_timeout:
        env['PGOPTIONS'] = '-c lock_timeout=2s'
    return env


def sql(query):
    done = subprocess.run([PSQL, '-At', '-v', 'ON_ERROR_STOP=1', '-c', query], env=pg_env(), capture_output=True,
                          text=True, timeout=120)
    return done.stdout.strip() if done.returncode == 0 else 'ERROR ' + done.stderr.strip()[-200:]


def triggers():
    out = sql("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON "
              "n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal")
    return int(out) if out.isdigit() else out


def index_state():
    out = sql("SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
              "WHERE c.relname='{}'".format(INDEX))
    return {'': 'absent', 't': 'valid', 'f': 'invalid'}.get(out, out)


def active_four():
    with open(STATE) as stream:
        services = json.load(stream)['services']

    def release(entry):
        if 'slots' in entry:
            slot = entry['slots'][entry['active']]
            return slot['release'] if isinstance(slot, dict) else slot
        return entry['release']
    return [release(services[role]) for role in ('frontend', 'jobs', 'admin', 'execution')]


def rehearsal_reasons():
    try:
        with open(REPORT) as stream:
            r = json.load(stream)
    except Exception as error:
        return ['rehearsal report missing: {}'.format(error)]
    reasons = []
    if r.get('verdict') != 'passed':
        reasons.append('verdict {}'.format(r.get('verdict')))
    if r.get('data') != 'full':
        reasons.append('data {}'.format(r.get('data')))
    if not (r.get('apply') or {}).get('ok'):
        reasons.append('apply not ok')
    for phase in ('before', 'after'):
        checks = r.get(phase) or {}
        if len(checks) < 4 or not all(v.get('ok') for v in checks.values()):
            reasons.append('{} checks {}'.format(phase, {k: v.get('ok') for k, v in checks.items()}))
    return reasons


def passed_for(releases):
    """True when the exact command passed a rehearsal within 24 h against exactly these releases."""
    sys.path.insert(0, ROOT)
    from scripts.db_change_rehearsal import change_digest
    try:
        with open(PASSED) as stream:
            record = json.load(stream).get(change_digest(None, COMMAND))
    except Exception:
        record = None
    return bool(record and time.time() - record['at'] < 24 * 3600 and sorted(record['releases']) == sorted(releases))


def neighbours():
    reasons = []
    now = datetime.now()
    hm, minute = now.hour * 100 + now.minute, now.minute
    if not 10 <= minute < 55:
        reasons.append('hourly measurement window :55-:10')
    if 350 <= hm <= 510:
        reasons.append('03:50-05:10 real_task_score window')
    if 2045 <= hm <= 2159:
        reasons.append('20:45-21:59 relay deploy window')
    with open(BOARD, encoding='utf-8') as stream:
        text = stream.read()
    start = text.index('## 배포 잠금\n') + len('## 배포 잠금\n')
    lock = text[start:text.index('\n## ', start)].strip()
    if lock != '(비어 있음)':
        reasons.append('deploy lock held: {}'.format(lock[:120]))
    for pattern, what in (('^[^ ]*python[^ ]* -m scripts[.]db_change_rehearsal', 'a copy rehearsal'),
                          ('embeddings_graph_cap migrate', 'the graph-cap migrate')):
        if subprocess.run(['pgrep', '-f', pattern], capture_output=True).returncode == 0:
            reasons.append('{} is running'.format(what))
    return reasons


def explore(n=5):
    times, errors, empty = [], 0, 0
    for i in range(n):
        q = urllib.parse.quote('{} {}'.format(TASKS[(int(time.time()) + i) % len(TASKS)], int(time.time() * 1000) % 100000))
        started = time.perf_counter()
        try:
            request = urllib.request.Request('https://agentconcierge.biz/api/explore?q=' + q,
                                             headers={'Accept': 'application/json', 'User-Agent': 'agentconcierge-ops-check'})
            with urllib.request.urlopen(request, timeout=30) as response:
                empty += not json.loads(response.read()).get('items')
        except Exception:
            errors += 1
        times.append(round(time.perf_counter() - started, 2))
    return {'times': times, 'errors': errors, 'empty': empty}


def attach():
    code = ("import sys,psycopg;sys.path.insert(0,{root!r});from agent_market.storage_adapter import open_store;"
            "c=psycopg.connect(open({dsn!r}).read().strip(),autocommit=True);"
            "s=open_store('postgresql',connection=c,workflow_key=open({key!r},'rb').read(),"
            "required_capabilities=('full_application','service_runtime'))\n"
            "with s.tx(readonly=True): pass\nprint('attach ok')").format(root=ROOT, dsn=DSN, key=KEY)
    done = subprocess.run([PY, '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    return done.returncode == 0 and 'attach ok' in done.stdout, (done.stderr or done.stdout)[-300:]


def main():
    reasons = rehearsal_reasons()
    result['rehearsal'] = {'report': REPORT, 'reasons': reasons}
    save()
    if reasons:
        stop('리허설 조건 불충족: {}'.format('; '.join(reasons)))
    blocked = neighbours()
    result['neighbours'] = blocked
    if blocked:
        stop('지금은 실행하지 않음: {}'.format('; '.join(blocked)))
    releases = active_four()
    result['releases'] = releases
    if not passed_for(releases):
        if DRY:
            log('(dry run) releases changed since the rehearsal; a minimal-data rehearsal would run first: {}'.format(releases))
        else:
            log('releases changed since the rehearsal; minimal-data rehearsal against {}'.format(releases))
            done = subprocess.run([PY, '-m', 'scripts.heavy_slot', '--team', '운영·SRE', '--what',
                                   'rehearsal: due_for_check 인덱스 최소 데이터(운영 버전 넷)', '--minutes', '15', '--',
                                   PY, '-m', 'scripts.db_change_rehearsal', 'run', '--data', 'minimal',
                                   '--releases', ','.join(releases), '--command', COMMAND],
                                  cwd=ROOT, capture_output=True, text=True, timeout=3600)
            result['minimal_rehearsal'] = {'returncode': done.returncode, 'stdout': done.stdout[-1500:], 'stderr': done.stderr[-600:]}
            save()
            if done.returncode != 0 or not passed_for(active_four()):
                stop('최소 데이터 리허설 실패 또는 버전이 또 바뀜(rc {})'.format(done.returncode))
    attached, why = attach()
    result['before'] = {'attach': attached, 'attach_detail': why, 'triggers': triggers(), 'index': index_state(),
                        'explore': explore(3)}
    save()
    if not attached or result['before']['triggers'] != 5:
        stop('적용 전 상태 이상: attach {}, public 트리거 {}'.format(attached, result['before']['triggers']))
    if result['before']['index'] != 'absent':
        stop('인덱스가 이미 있음({}): 복구 SQL로 정리한 뒤 다시 실행'.format(result['before']['index']))
    if DRY:
        log('(dry run) all checks passed; would run: {}'.format(COMMAND))
        result['finished'] = datetime.now().isoformat(timespec='seconds')
        save()
        return
    board('시작(리허설 {})'.format(os.path.basename(REPORT)))
    began = time.monotonic()
    done = subprocess.run(COMMAND.split(), cwd=ROOT, env=pg_env(lock_timeout=False), capture_output=True, text=True,
                          timeout=3600)
    result['apply'] = {'returncode': done.returncode, 'seconds': round(time.monotonic() - began, 1),
                       'stdout': done.stdout[-800:], 'stderr': done.stderr[-800:]}
    attached, why = attach()
    result['after'] = {'attach': attached, 'attach_detail': why, 'triggers': triggers(), 'index': index_state(),
                       'explore': explore(5)}
    save()
    after = result['after']
    good = (done.returncode == 0 and attached and after['triggers'] == 5 and after['index'] == 'valid'
            and after['explore']['errors'] == 0 and after['explore']['empty'] == 0)
    if not good:
        back = subprocess.run([PSQL, '-v', 'ON_ERROR_STOP=1', '-f', ROLLBACK_SQL], cwd=ROOT, env=pg_env(),
                              capture_output=True, text=True, timeout=1800)
        result['rolled_back'] = {'returncode': back.returncode, 'stderr': back.stderr[-400:], 'attach': attach(),
                                 'triggers': triggers(), 'index': index_state()}
        save()
        stop('적용 뒤 확인 실패 → 복구함. apply rc {}, attach {}, 트리거 {}, 인덱스 {}, 탐색 {}, 복구 rc {}'.format(
            done.returncode, attached, after['triggers'], after['index'], after['explore'], back.returncode))
    log('applied in {} s'.format(result['apply']['seconds']))
    board('완료({:.0f}초): 새 연결 ok, public 트리거 5, 인덱스 valid, 공개 탐색 {}초 오류 0·0건 0. '
          '쿼리가 인덱스를 쓰는 코드는 다음 묶음부터'.format(result['apply']['seconds'], after['explore']['times']))
    result['finished'] = datetime.now().isoformat(timespec='seconds')
    save()


if __name__ == '__main__':
    main()

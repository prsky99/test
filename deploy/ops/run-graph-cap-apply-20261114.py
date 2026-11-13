"""Apply the per-host vector graph cap (scripts.embeddings_graph_cap) to production. Run by the user.

User approval 11-14 02시 (via PM 02:2x) after the 11-14 02:10 full rehearsal. Usage, from the repository root:

    .venv/bin/python deploy/ops/run-graph-cap-apply-20261114.py

What it does, stopping at the first failed step (each stop writes one line under '## DB 변경 창' in the board):
 1. Rehearsal conditions from reports/graph-cap-2026-11-13/rehearsal-summary.json: verdict passed, all release
    checks ok before and after, the frontend ok after the recovery, public triggers 5 before and after, apply ok,
    probe errors 0, new code attached with capped graphs a2a and x402, refresh changed 0 rows, recovery ok,
    a2a and mcp recall@10 not lower than before by more than 0.02.
 2. A start slot: 05:12, 06:12 or 07:12, the first one not yet past whose expected end (1.5 x the rehearsal's apply
    + 15 min) is before :55 of that hour. Avoids 03:50-05:10 (feed jobs deploy), 04-05 (real_task_score) and :55-:10.
 3. At the slot: the same change must have passed a rehearsal within 24 h against the four releases active now
    (frontend, jobs, admin, execution). If a release changed since 02:10 (e.g. the feed jobs deploy), a minimal-data
    rehearsal of the same command runs first against the releases now active (heavy_slot) and must pass.
 4. Apply: one connection, column with a 2 s lock timeout, partial HNSW indexes CONCURRENTLY.
 5. After: a new application connection, public triggers 5, public Explore 5 samples with no error or empty answer.
    Any failure runs the recovery (indexes, 330 s, column; graph-cap-rollback-20261114.sql) and stops.
Writes logs/ops/graph-cap-apply-20261114.json and .log. Never touches public-schema triggers.
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, '.venv', 'bin', 'python')
DSN = os.path.join(ROOT, 'gateway-data', 'postgres18', 'application.dsn')
KEY = os.path.join(ROOT, 'gateway-data', 'collector.sqlite3.updates-key')
SUMMARY = os.path.join(ROOT, 'reports', 'graph-cap-2026-11-13', 'rehearsal-summary.json')
PASSED = os.path.join(ROOT, 'logs', 'ops', 'db-rehearsal', 'passed.json')
STATE = os.path.join(ROOT, 'gateway-data', 'services', 'state.json')
OUT = os.path.join(ROOT, 'logs', 'ops', 'graph-cap-apply-20261114.json')
# The exact text rehearsed (db_change_rehearsal keys its pass record by this text).
COMMAND = '.venv/bin/python -m scripts.embeddings_graph_cap migrate --dsn-file {dsn_file} --i-have-approval'
ROLLBACK = [PY, '-m', 'scripts.embeddings_graph_cap', 'rollback', '--dsn-file', DSN, '--i-have-approval']
STATUS = [PY, '-m', 'scripts.embeddings_graph_cap', 'status', '--dsn-file', DSN]
SLOTS = ('05:12', '06:12', '07:12')
TASKS = ['weather forecast', 'pdf to text', 'github issues', 'currency exchange rate', 'image resize',
         'translate document', 'calendar booking', 'send email', 'crypto price', 'web search']
result = {'started': datetime.now().isoformat(timespec='seconds')}


def save():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as stream:
        stream.write(json.dumps(result, indent=1, default=str))


def log(message):
    line = datetime.now().strftime('%F %T ') + message
    print(line, flush=True)
    with open(OUT.replace('.json', '.log'), 'a') as stream:
        stream.write(line + '\n')


def board(text):
    path = os.path.join(ROOT, 'logs', 'ops', 'status-board.md')
    try:
        with open(path, encoding='utf-8') as stream:
            lines = stream.read().split('\n')
        at = lines.index('## DB 변경 창 (검색과 RAG, 잠금처럼 지킴)')
        lines.insert(at + 1, '- {} 검색과 RAG 그래프 상한 운영 적용: {}'.format(datetime.now().strftime('%m-%d %H:%M'), text))
        with open(path, 'w', encoding='utf-8') as stream:
            stream.write('\n'.join(lines))
    except Exception as error:
        log('board write failed: {}'.format(error))


def stop(text):
    log('STOP: ' + text)
    result['stopped'] = text
    save()
    board('중지 — {}'.format(text[:500]))
    sys.exit(1)


def active_four():
    with open(STATE) as stream:
        services = json.load(stream)['services']

    def release(entry):
        if 'slots' in entry:
            slot = entry['slots'][entry['active']]
            return slot['release'] if isinstance(slot, dict) else slot
        return entry['release']
    return [release(services[role]) for role in ('frontend', 'jobs', 'admin', 'execution')]


def rehearsal_conditions():
    reasons = []
    try:
        with open(SUMMARY) as stream:
            s = json.load(stream)
    except Exception as error:
        return ['rehearsal summary missing: {}'.format(error)], None
    if (s.get('verdict') or {}).get('verdict') != 'passed':
        reasons.append('verdict {}'.format((s.get('verdict') or {}).get('verdict')))
    checks = s.get('release_checks') or []
    if len(checks) < 8 or not all(c.get('ok') for c in checks):
        reasons.append('release checks {}'.format([(c.get('release'), c.get('ok'), c.get('error')) for c in checks]))
    if not (s.get('after_rollback_check') or {}).get('ok'):
        reasons.append('frontend after recovery not ok')
    if (s.get('before_state') or {}).get('public_triggers') != 5:
        reasons.append('public triggers before {}'.format((s.get('before_state') or {}).get('public_triggers')))
    after_status = ((s.get('after_state') or {}).get('status') or {}).get('status') or {}
    if after_status.get('public_triggers') != 5:
        reasons.append('public triggers after {}'.format(after_status.get('public_triggers')))
    apply = s.get('apply') or {}
    if not apply.get('ok'):
        reasons.append('apply not ok')
    if any((v or {}).get('errors') for v in (apply.get('probe') or {}).values()):
        reasons.append('probe errors {}'.format(apply.get('probe')))
    new = s.get('new_code') or {}
    if not new.get('ok') or new.get('capped') != ['a2a', 'x402']:
        reasons.append('new code ok={} capped={}'.format(new.get('ok'), new.get('capped')))
    refresh = s.get('refresh') or {}
    if refresh.get('returncode') != 0 or refresh.get('set_in') or refresh.get('set_out'):
        reasons.append('refresh {}'.format({k: refresh.get(k) for k in ('returncode', 'set_in', 'set_out')}))
    if (s.get('rollback') or {}).get('returncode') != 0:
        reasons.append('recovery rc {}'.format((s.get('rollback') or {}).get('returncode')))
    recall = s.get('recall') or {}
    for kind in ('a2a', 'mcp'):
        before = ((recall.get(kind) or {}).get('before') or {}).get('r10')
        after = ((recall.get(kind) or {}).get('after') or {}).get('r10')
        if before is None or after is None or after < before - 0.02:
            reasons.append('{} recall@10 {} -> {}'.format(kind, before, after))
    return reasons, apply.get('seconds')


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


def status():
    done = subprocess.run(STATUS, cwd=ROOT, capture_output=True, text=True, timeout=300)
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])['status']
    except Exception:
        return {'error': (done.stderr or done.stdout)[-300:]}


def main():
    reasons, measured = rehearsal_conditions()
    result['rehearsal'] = {'reasons': reasons, 'apply_seconds': measured}
    save()
    if reasons:
        stop('리허설 조건 불충족: {}'.format('; '.join(reasons)))
    expected = timedelta(seconds=1.5 * float(measured or 1200) + 900)
    now = datetime.now()
    slot = None
    for hhmm in SLOTS:
        start = datetime.combine(now.date(), datetime.strptime(hhmm, '%H:%M').time())
        if now <= start + timedelta(minutes=3) and start + expected <= start.replace(minute=55):
            slot = start
            break
    result['slot'], result['expected_minutes'] = (slot.strftime('%H:%M') if slot else None), round(expected.total_seconds() / 60, 1)
    save()
    if slot is None:
        stop('맞는 시작 칸 없음(05:12·06:12·07:12, 예상 {:.0f}분)'.format(expected.total_seconds() / 60))
    log('waiting for {} (expected {:.0f} min)'.format(result['slot'], expected.total_seconds() / 60))
    board('{} 시작 대기(예상 {:.0f}분)'.format(result['slot'], expected.total_seconds() / 60))
    while datetime.now() < slot:
        time.sleep(15)
    releases = active_four()
    result['releases'] = releases
    if not passed_for(releases):
        log('releases changed since the rehearsal; minimal-data rehearsal against {}'.format(releases))
        board('운영 버전이 리허설 뒤 바뀜 → 같은 명령으로 최소 데이터 리허설 {}'.format(','.join(releases)))
        done = subprocess.run([PY, '-m', 'scripts.heavy_slot', '--team', '검색과 RAG', '--what',
                               'rehearsal: 그래프 상한 최소 데이터(운영 버전 넷)', '--minutes', '20', '--',
                               PY, '-m', 'scripts.db_change_rehearsal', 'run', '--data', 'minimal',
                               '--releases', ','.join(releases), '--command', COMMAND],
                              cwd=ROOT, capture_output=True, text=True, timeout=3600)
        result['minimal_rehearsal'] = {'returncode': done.returncode, 'stdout': done.stdout[-1500:], 'stderr': done.stderr[-600:]}
        save()
        if done.returncode != 0 or not passed_for(active_four()):
            stop('최소 데이터 리허설 실패 또는 버전이 또 바뀜(rc {})'.format(done.returncode))
        if datetime.now() + expected - timedelta(minutes=10) > slot.replace(minute=55):
            stop('최소 데이터 리허설 뒤 남은 시간이 부족함')
    result['before'] = {'status': status(), 'explore': explore(5)}
    save()
    if result['before']['status'].get('public_triggers') != 5:
        stop('적용 전 public 트리거 {}'.format(result['before']['status'].get('public_triggers')))
    began = time.monotonic()
    done = subprocess.run(['nice', '-n', '10'] + COMMAND.replace('{dsn_file}', DSN).split(), cwd=ROOT,
                          capture_output=True, text=True, timeout=7200)
    result['apply'] = {'returncode': done.returncode, 'seconds': round(time.monotonic() - began, 1),
                       'stdout': done.stdout[-1500:], 'stderr': done.stderr[-800:]}
    attached, why = attach()
    after = status()
    result['after'] = {'attach': attached, 'attach_detail': why, 'status': after, 'explore': explore(5)}
    save()
    good = (done.returncode == 0 and attached and after.get('public_triggers') == 5
            and result['after']['explore']['errors'] == 0 and result['after']['explore']['empty'] == 0)
    if not good:
        back = subprocess.run(ROLLBACK, cwd=ROOT, capture_output=True, text=True, timeout=3600)
        result['rolled_back'] = {'returncode': back.returncode, 'stdout': back.stdout[-600:], 'attach': attach(), 'status': status()}
        save()
        stop('적용 뒤 확인 실패 → 복구함. apply rc {}, attach {}, 트리거 {}, 탐색 {}, 복구 rc {}'.format(
            done.returncode, attached, after.get('public_triggers'), result['after']['explore'], back.returncode))
    log('applied in {} s'.format(result['apply']['seconds']))
    sizes = {k: v for k, v in (after.get('indexes') or {}).items() if k.endswith('_cap')}
    board('완료({:.0f}초): 새 연결 ok, public 트리거 5, 공개 탐색 {}초 오류 0·0건 0, 표시 {}, 상한 색인 {}. 앱 사용은 65354d0d가 든 다음 배포부터'.format(
        result['apply']['seconds'], result['after']['explore']['times'], after.get('marks'), sizes))
    result['finished'] = datetime.now().isoformat(timespec='seconds')
    save()


if __name__ == '__main__':
    main()

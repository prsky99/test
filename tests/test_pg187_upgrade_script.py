"""deploy/ops/pg187-upgrade-20261117.sh with fake brew, agentcon, launchctl and PostgreSQL tools (운영·SRE 11-15).

Nothing here touches /opt/homebrew, launchd, the services or a database."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'deploy/ops/pg187-upgrade-20261117.sh'

TOOL = '''#!/bin/bash
# fake PostgreSQL tool: the version is the Cellar folder this copy lives in
me=$(cd "$(dirname "$0")/.." && basename "$(pwd -P)"); name=$(basename "$0"); S=$FAKE_STATE
case "$name" in
  pg_config) echo "PostgreSQL ${me%_*} (Homebrew)" ;;
  pg_ctl) rm -f "$PG_DATA/postmaster.pid"; echo stopped >> "$S/log" ;;
  pg_isready) [ -f "$PG_DATA/postmaster.pid" ] ;;
  psql) sql="${@: -1}"; v=$(cat "$S/version")
        case "$sql" in
          *server_version*) echo "$v" ;;
          *pg_extension*) echo "pg_stat_statements 1.12, plpgsql 1.0, unaccent 1.1, vector 0.8.2" ;;
          *pg_trigger*) echo "${FAKE_TRIGGERS:-5}" ;;
          *unaccent*) echo Creme ;;
          *vector*) echo 1 ;;
          *pg_stat_statements*) echo t ;;
          *PERFORM*) echo ok ;;
        esac ;;
esac
'''
BREW = '''#!/bin/bash
S=$FAKE_STATE; P=$PG_PREFIX
case "$1" in
  --cache) echo "$S/bottle.tar.gz" ;;
  list) echo pgvector ;;
  upgrade) echo "upgrade $*" >> "$S/log"; [ -n "${FAIL_BREW:-}" ] && exit 1
           ln -sfn ../Cellar/postgresql@18/18.7 "$P/opt/postgresql@18"
           ln -sfn ../../Cellar/postgresql@18/18.7/lib/postgresql/plpgsql.dylib "$P/lib/postgresql@18/plpgsql.dylib"
           echo 18.7 > "$S/version" ;;
esac
'''
AGENTCON = '''#!/bin/bash
S=$FAKE_STATE
case "$1" in
  stop) [ "$2 $3" = "--lock-owner PM" ] || exit 2; echo stopped > "$S/apps"; echo "agentcon stop" >> "$S/log" ;;
  start) echo running > "$S/apps"; echo "agentcon start" >> "$S/log" ;;
  status) if [ "$(cat "$S/apps")" = running ]; then pid=10; phase=stable; else pid=null; phase=stopped; fi
          echo "{\\"phase\\": \\"$phase\\", \\"proxy_pid\\": $pid, \\"services\\": {\\"frontend\\": {\\"active\\": \\"b\\", \\"slots\\": {\\"a\\": {\\"release\\": \\"x\\", \\"pid\\": null}, \\"b\\": {\\"release\\": \\"fe-r3\\", \\"pid\\": $pid}}}, \\"jobs\\": {\\"release\\": \\"jobs-r1\\", \\"pid\\": $pid}}}" ;;
esac
'''
LAUNCHCTL = '''#!/bin/bash
echo "launchctl $*" >> "$FAKE_STATE/log"; [ "$1" = kickstart ] && touch "$PG_DATA/postmaster.pid"; exit 0
'''
RUNNING = '''#!/bin/bash
[ -f "$PG_DATA/postmaster.pid" ] && echo "1350 postgres -D data"
[ -f "$FAKE_STATE/tms" ] && echo "1361 postgres -D pg"
exit 0
'''


def script(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def setup(tmp_path, board='## 배포 잠금\n- PM 11-17 05:15 PostgreSQL 18.7\n\n## 다음\n'):
    prefix, state = tmp_path / 'hb', tmp_path / 'state'
    state.mkdir(parents=True)
    for version in ('18.6_1', '18.7'):
        keg = prefix / 'Cellar/postgresql@18' / version
        for name in ('postgres', 'pg_ctl', 'pg_isready', 'psql', 'pg_config'):
            script(keg / 'bin' / name, TOOL)
        (keg / 'lib/postgresql').mkdir(parents=True)
        (keg / 'lib/postgresql/plpgsql.dylib').write_text(version)
    vector = prefix / 'Cellar/pgvector/0.8.2/lib/postgresql@18/vector.dylib'
    vector.parent.mkdir(parents=True)
    vector.write_text('v')
    (prefix / 'opt').mkdir()
    (prefix / 'lib/postgresql@18').mkdir(parents=True)
    os.symlink('../Cellar/postgresql@18/18.6_1', prefix / 'opt/postgresql@18')
    os.symlink('../../Cellar/postgresql@18/18.6_1/lib/postgresql/plpgsql.dylib', prefix / 'lib/postgresql@18/plpgsql.dylib')
    os.symlink('../../Cellar/pgvector/0.8.2/lib/postgresql@18/vector.dylib', prefix / 'lib/postgresql@18/vector.dylib')
    links = tmp_path / 'links.tsv'
    links.write_text(''.join(f'/opt/homebrew/x{i}\t../Cellar/postgresql@18/18.6_1/x{i}\n' for i in range(1950)))
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'postmaster.pid').write_text('1350')
    (state / 'version').write_text('18.6\n')
    (state / 'apps').write_text('running\n')
    (state / 'bottle.tar.gz').write_text('b')
    (state / 'log').write_text('')
    (tmp_path / 'token').write_text('t' * 185)
    (tmp_path / 'board.md').write_text(board)
    tools = tmp_path / 'tools'
    script(tools / 'brew', BREW)
    script(tools / 'agentcon', AGENTCON)
    script(tools / 'launchctl', LAUNCHCTL)
    script(tools / 'running', RUNNING)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'LANG': 'ko_KR.UTF-8', 'LC_ALL': 'ko_KR.UTF-8',
           'PG_PREFIX': str(prefix), 'BREW': str(tools / 'brew'), 'AGENTCON': str(tools / 'agentcon'),
           'LAUNCHCTL': str(tools / 'launchctl'), 'PG_RUNNING': str(tools / 'running'), 'INSTALL_NOW': '05:20',
           'BOARD': str(tmp_path / 'board.md'), 'PG_DATA': str(data), 'PG_SOCKET': str(tmp_path / 'run'),
           'TOKEN_FILE': str(tmp_path / 'token'), 'PG_LINKS': str(links), 'PG_RUN_LOG_DIR': str(tmp_path / 'logs'),
           'WAIT_SCALE': '0.01', 'FAKE_STATE': str(state), 'PG_BACKUP_RUNNING': 'false'}
    return prefix, state, env


def run(env, *args, **extra):
    return subprocess.run(['/bin/bash', str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True,
                          timeout=120)


def test_the_whole_run_in_order(tmp_path):
    prefix, state, env = setup(tmp_path)
    r = run(env)
    assert r.returncode == 0, r.stdout + r.stderr
    steps = [line for line in (state / 'log').read_text().splitlines() if line]
    assert steps[0] == 'agentcon stop' and steps[1] == 'stopped'
    assert steps[2].startswith('upgrade upgrade postgresql@18') and steps[3].startswith('launchctl kickstart')
    assert steps[4] == 'agentcon start'
    assert os.readlink(prefix / 'opt/postgresql@18') == '../Cellar/postgresql@18/18.7'
    assert 'public 트리거: 5' in r.stdout and '끝: PostgreSQL 18.7' in r.stdout and 'frontend: fe-r3' in r.stdout


def test_dry_run_changes_nothing_at_any_hour(tmp_path):
    prefix, state, env = setup(tmp_path, board='## 배포 잠금\n(비어 있음)\n')
    r = run(env, '--dry-run', INSTALL_NOW='12:53')
    assert r.returncode == 0 and '미리 보기 끝' in r.stdout and '실행 시간(05:10~05:50) 밖' in r.stdout
    assert (state / 'log').read_text() == ''
    assert os.readlink(prefix / 'opt/postgresql@18') == '../Cellar/postgresql@18/18.6_1'


def test_outside_the_window_or_without_the_pm_lock_nothing_starts(tmp_path):
    _, state, env = setup(tmp_path)
    assert run(env, INSTALL_NOW='04:59').returncode == 1
    _, state2, env2 = setup(tmp_path / 'b', board='## 배포 잠금\n- 검색과 RAG 배포 중\n')
    r = run(env2)
    assert r.returncode == 1 and 'PM 한 줄이 아님' in r.stdout
    assert (state / 'log').read_text() == '' and (state2 / 'log').read_text() == ''


def test_a_tms_server_still_running_stops_before_installing(tmp_path):
    prefix, state, env = setup(tmp_path)
    (state / 'tms').write_text('1')
    r = run(env)
    assert r.returncode == 1 and '세 서버가 모두 멈추지 않음(설치하지 않음)' in r.stdout
    assert 'launchctl kickstart gui/$(id -u)/biz.agentconcierge.postgres18' in r.stdout and './agentcon start' in r.stdout
    assert 'upgrade' not in (state / 'log').read_text()
    assert os.readlink(prefix / 'opt/postgresql@18') == '../Cellar/postgresql@18/18.6_1'


def test_a_failed_brew_upgrade_prints_the_link_restore_first(tmp_path):
    _, state, env = setup(tmp_path)
    r = run(env, FAIL_BREW='1')
    assert r.returncode == 1 and '멈춤: brew upgrade 실패' in r.stdout
    tail = r.stdout.split('되돌리기(순서대로):')[1]
    assert tail.index('pg187-restore-links.sh') < tail.index('kickstart') < tail.index('./agentcon start')
    assert 'agentcon start' not in (state / 'log').read_text()


def test_a_wrong_trigger_count_keeps_the_apps_stopped(tmp_path):
    _, state, env = setup(tmp_path)
    r = run(env, FAKE_TRIGGERS='4')
    assert r.returncode == 1 and '확인 SQL이 기대와 다름(앱은 아직 정지 상태)' in r.stdout
    assert 'agentcon start' not in (state / 'log').read_text()


def test_a_backup_still_running_stops_before_anything(tmp_path):
    _, state, env = setup(tmp_path)
    r = run(env, PG_BACKUP_RUNNING='true')
    assert r.returncode == 1 and '확인 실패: 04:30 백업이 끝남' in r.stdout
    assert (state / 'log').read_text() == ''

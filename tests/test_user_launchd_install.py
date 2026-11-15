"""deploy/ops/user-launchd-install-20261115.sh with a fake launchctl (운영·SRE 11-15): nothing touches real launchd."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'deploy/ops/user-launchd-install-20261115.sh'
LABELS = ['biz.agentconcierge.opsauto.ofac', 'biz.agentconcierge.opsauto.watchstale',
          'biz.agentconcierge.opsauto.housead', 'biz.agentconcierge.backup', 'biz.agentconcierge.opsauto.paidreconcile']
FAKE = '''#!/bin/bash
# fake launchctl: a loaded job is a file named after its label in $FAKE_STATE
cmd=$1; shift
case "$cmd" in
  print) l=${1##*/}; [ -f "$FAKE_STATE/$l" ] && { echo "    state = running"; echo "    path = $FAKE_STATE/$l"; exit 0; }; exit 113 ;;
  bootout) rm -f "$FAKE_STATE/${1##*/}"; exit 0 ;;
  bootstrap) l=$(basename "$2" .plist); echo "$l" >> "$FAKE_STATE/.bootstraps"
             [ "$l" = "${FAIL_BOOTSTRAP:-}" ] && exit 5; touch "$FAKE_STATE/$l"; exit 0 ;;
esac
exit 1
'''


def setup(tmp_path, old=('biz.agentconcierge.opsauto.housead', 'biz.agentconcierge.backup')):
    state, agents = tmp_path / 'state', tmp_path / 'agents'
    state.mkdir()
    agents.mkdir()
    fake = tmp_path / 'launchctl'
    fake.write_text(FAKE)
    fake.chmod(0o755)
    for label in old:   # the replace items: an older plist that is loaded
        (agents / (label + '.plist')).write_text('<plist>old</plist>')
        (state / label).touch()
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'LANG': 'ko_KR.UTF-8', 'LC_ALL': 'ko_KR.UTF-8',
           'LAUNCHCTL': str(fake), 'LAUNCH_AGENTS': str(agents), 'INSTALL_UID': '501', 'INSTALL_WAIT_SECONDS': '2',
           'INSTALL_BACKUP_DIR': str(tmp_path / 'backup'), 'FAKE_STATE': str(state), 'INSTALL_NOW': '10:20'}
    return env, state, agents


def run(env, *args, **extra):
    return subprocess.run(['/bin/bash', str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True)


def test_installs_all_five_and_keeps_the_replaced_plists(tmp_path):
    env, state, agents = setup(tmp_path)
    r = run(env)
    assert r.returncode == 0, r.stdout + r.stderr
    for label in LABELS:
        assert (state / label).exists()
        source = next(p for p in (ROOT / 'deploy/launchd/ops-pinned', ROOT / 'deploy/launchd/ops')
                      if (p / (label + '.plist')).exists())
        assert (agents / (label + '.plist')).read_bytes() == (source / (label + '.plist')).read_bytes()
    assert sorted(p.name for p in (tmp_path / 'backup').iterdir()) == [
        'biz.agentconcierge.backup.plist', 'biz.agentconcierge.opsauto.housead.plist']
    assert '모두 끝났습니다(5건 확인)' in r.stdout and 'agentconcierge-ofac-daily-refresh' in r.stdout
    again = run(env)
    assert again.returncode == 0 and again.stdout.count('건너뜀') == 5


def test_dry_run_changes_nothing_even_in_a_busy_minute(tmp_path):
    env, state, agents = setup(tmp_path)
    r = run(env, '--dry-run', INSTALL_NOW='09:57')
    assert r.returncode == 0 and '피하는 시간' in r.stdout and '미리 보기 끝' in r.stdout
    assert sorted(os.listdir(state)) == ['biz.agentconcierge.backup', 'biz.agentconcierge.opsauto.housead']
    assert len(os.listdir(agents)) == 2 and not (tmp_path / 'backup').exists()


def test_a_busy_time_refuses_to_install(tmp_path):
    env, state, _ = setup(tmp_path)
    for now in ('10:57', '11:05', '04:31', '09:15'):
        r = run(env, INSTALL_NOW=now)
        assert r.returncode == 3 and '피하는 시간' in r.stdout, now
    assert not (state / '.bootstraps').exists()


def test_a_failed_bootstrap_stops_there_and_prints_the_way_back(tmp_path):
    env, state, _ = setup(tmp_path)
    r = run(env, FAIL_BOOTSTRAP='biz.agentconcierge.opsauto.housead')
    assert r.returncode == 1 and '멈춤: 올리기(bootstrap) 실패' in r.stdout
    assert '되돌리기: launchctl bootout gui/$(id -u)/biz.agentconcierge.opsauto.housead; cp ' in r.stdout
    assert (state / 'biz.agentconcierge.opsauto.ofac').exists() and not (state / 'biz.agentconcierge.backup.plist').exists()
    assert 'biz.agentconcierge.opsauto.paidreconcile' not in (state / '.bootstraps').read_text()


def test_a_missing_replace_target_stops_before_changing_it(tmp_path):
    env, state, agents = setup(tmp_path, old=())
    r = run(env)
    assert r.returncode == 1 and '교체할 설치본이 없습니다' in r.stdout
    assert not (agents / 'biz.agentconcierge.opsauto.housead.plist').exists()

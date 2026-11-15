"""deploy/launchd/adcoin-worker-load.sh with a fake launchctl (PM 11-15 09:5x: the 09:49 reinstall left the daemon down
after a 30 s wait and said only "not installing")."""
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'deploy/launchd/adcoin-worker-load.sh'
LABEL = 'biz.example.adcoin-worker'
FAKE = r'''#!/bin/bash
# state files in $FAKE_DIR: loaded, unloading (list calls left), bootstrap_fail (failures left), never_runs
D=$FAKE_DIR; cmd=$1
count() { [ -f "$D/$1" ] && cat "$D/$1" || echo 0; }
case "$cmd" in
  list)
    if [ -f "$D/loaded" ]; then printf '123\t0\t%s\n' "$LABEL"; exit 0; fi
    n=$(count unloading); if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$D/unloading"; printf -- '-\t0\t%s\n' "$LABEL"; fi
    ;;
  bootout) [ -f "$D/loaded" ] && { rm "$D/loaded"; echo "${UNLOAD_POLLS:-0}" > "$D/unloading"; }; echo bootout >> "$D/calls" ;;
  bootstrap)
    echo bootstrap >> "$D/calls"
    n=$(count bootstrap_fail); if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$D/bootstrap_fail"; echo "Bootstrap failed: 5" >&2; exit 5; fi
    [ -f "$D/never_runs" ] || touch "$D/loaded" ;;
esac
'''


def run(tmp_path, *, unload_polls=0, bootstrap_fail=0, never_runs=False, wait=120, **extra):
    fake = tmp_path / 'launchctl'
    fake.write_text(FAKE)
    fake.chmod(0o755)
    (tmp_path / 'loaded').touch()                                    # the old daemon is loaded
    if bootstrap_fail:
        (tmp_path / 'bootstrap_fail').write_text(str(bootstrap_fail))
    if never_runs:
        (tmp_path / 'never_runs').touch()
    env = {**os.environ, 'LAUNCHCTL': str(fake), 'FAKE_DIR': str(tmp_path), 'LABEL': LABEL,
           'UNLOAD_POLLS': str(unload_polls), 'INSTALL_WAIT_SECONDS': str(wait), 'INSTALL_SETTLE_SECONDS': '0',
           'INSTALL_RETRY_SECONDS': '0', 'INSTALL_POLL_SECONDS': '0', 'INSTALL_REBOOTOUT_SECONDS': '0',
           'RERUN': 'bash install.sh r1', **extra}
    done = subprocess.run(['bash', str(SCRIPT), LABEL, str(tmp_path / 'job.plist')], env=env, capture_output=True,
                          text=True, timeout=60)
    return done.returncode, done.stdout + done.stderr, (tmp_path / 'calls').read_text().split()


def test_an_old_job_that_unloads_slowly_is_waited_for(tmp_path):
    code, out, calls = run(tmp_path, unload_polls=45)                  # longer than the old 30 s wait
    assert code == 0 and (tmp_path / 'loaded').exists() and calls.count('bootstrap') == 1
    assert 'bootout' in calls[1:]                                     # asked launchd again while waiting


def test_an_old_job_that_never_unloads_says_the_daemon_is_down(tmp_path):
    code, out, calls = run(tmp_path, unload_polls=10_000_000, wait=2)
    assert code == 3 and 'bootstrap' not in calls
    assert 'NOT running now' in out and 'bash install.sh r1' in out and '꺼져 있습니다' in out


def test_a_failing_bootstrap_is_retried_then_reported(tmp_path):
    code, _, calls = run(tmp_path, bootstrap_fail=2)
    assert code == 0 and calls.count('bootstrap') == 3
    again = tmp_path / 'again'
    again.mkdir()
    code, out, calls = run(again, bootstrap_fail=9)
    assert code == 4 and calls.count('bootstrap') == 3 and 'NOT running now' in out


def test_a_job_that_does_not_stay_up_is_reported(tmp_path):
    code, out, _ = run(tmp_path, never_runs=True)
    assert code == 5 and 'NOT running now' in out


def test_the_wait_is_wall_clock_time_even_when_sleep_returns_at_once(tmp_path):
    """PM 11-15 11:28: sleep returned at once in a session, so 120 polls took 3 s and the daemon was reported down."""
    started = time.monotonic()
    code, out, calls = run(tmp_path, unload_polls=10_000_000, wait=3, INSTALL_SLEEP='true', INSTALL_POLL_SECONDS='1',
                           INSTALL_REBOOTOUT_SECONDS='30')
    took = time.monotonic() - started
    assert code == 3 and took >= 2.9 and 'bootstrap' not in calls
    assert 'limit 3s' in out

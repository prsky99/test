"""Watching the watch (precision review R53, 11-15)."""
import json
import os
import subprocess
import time
from pathlib import Path

from scripts import ops_watch as w

ROOT = Path(__file__).resolve().parents[1]
LIST = '\n'.join(['PID\tStatus\tLabel', '1350\t0\tbiz.agentconcierge.postgres18', '19100\t0\tbiz.agentconcierge.opensearch',
                  '39026\t0\tbiz.agentconcierge.498590e0b3.jobs.main', '-\t0\tbiz.agentconcierge.498590e0b3.execution.main',
                  '-\t3\tbiz.agentconcierge.backup', '-\t-9\tbiz.agentconcierge.opsauto.housead',
                  '-\t1\tbiz.agentconcierge.driveragent.app', '77\t0\tcom.apple.x'])


def test_launchd_jobs_with_a_non_zero_exit_are_listed():
    jobs, bad = w.check_launchd(LIST)
    assert 'biz.agentconcierge.driveragent.app' not in jobs and 'com.apple.x' not in jobs
    assert [b['label'] for b in bad] == ['biz.agentconcierge.backup', 'biz.agentconcierge.opsauto.housead']
    assert jobs['biz.agentconcierge.postgres18'] == {'pid': 1350, 'status': 0}


def test_core_services_down_by_launchd_pid_and_process_list():
    jobs, _ = w.check_launchd(LIST)
    assert w.check_core(jobs, '/opt/homebrew/bin/cloudflared\n') == ['execution', 'redis']
    assert w.check_core(jobs, 'redis-server\ncloudflared\n') == ['execution']


def test_backup_age_and_offsite_result(tmp_path):
    snap = tmp_path / 'daily/snapshot-20261115-043005'
    snap.mkdir(parents=True)
    (snap / 'manifest.json').write_text(json.dumps({'finished': 1000.0}))
    (tmp_path / 'daily/snapshot-20261116-043005').mkdir()          # incomplete: no manifest
    log = tmp_path / 'backup.log'
    log.write_text('noise\n' + json.dumps({'started': 's', 'status': 'ok', 'offsite': {'status': 'ok'}}) + '\n')
    ok = w.check_backup(tmp_path / 'daily', log, now=1000.0 + 3600 * 5)
    assert ok['problems'] == [] and ok['age_hours'] == 5.0 and ok['newest'] == 'snapshot-20261115-043005'
    assert w.check_backup(tmp_path / 'daily', log, now=1000.0 + 3600 * 27)['problems'] == ['snapshot_older_than_26h']
    log.write_text(json.dumps({'status': 'ok', 'offsite': {'status': 'skipped'}}) + '\n')
    assert w.check_backup(tmp_path / 'daily', log, now=1000.0)['problems'] == ['offsite_skipped']
    assert w.check_backup(tmp_path / 'none', tmp_path / 'nolog', now=1.0)['problems'] == ['snapshot_older_than_26h']


def test_site_checks_stop_at_the_budget(monkeypatch):
    clock = iter([0, 10, 50, 60, 70]).__next__
    monkeypatch.setattr(w, 'fetch', lambda url: (200, 1.0))
    bad, path = w.check_site(budget=45, clock=clock)
    assert [b['status'] for b in bad] == ['not_checked'] * (len(w.URLS) - 1) and path == []


def test_an_alert_open_for_seven_runs_escalates_once(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    import ops_auto
    board = tmp_path / 'board.md'
    board.write_text('# b\n## 넘기는 일\n| a | b | c | d |\n')
    monkeypatch.setattr(ops_auto, 'BOARD', board)
    monkeypatch.setattr(ops_auto, 'DESKTOP', tmp_path / 'desktop.txt')
    monkeypatch.setattr(ops_auto, 'ESCALATIONS', tmp_path / 'esc.md')
    for _ in range(9):
        ops_auto.board_handoff('backup', 'snapshot older than 26 hours')
    assert '같은 경고 9회째' in board.read_text()
    assert len((tmp_path / 'esc.md').read_text().splitlines()) == 1
    assert '[격상 backup]' in (tmp_path / 'desktop.txt').read_text()


def test_watch_stale_check_alerts_once_an_hour(tmp_path):
    (tmp_path / 'deploy/ops').mkdir(parents=True)
    script = tmp_path / 'deploy/ops/watch-stale-check.sh'
    script.write_text((ROOT / 'deploy/ops/watch-stale-check.sh').read_text())
    (tmp_path / 'logs/ops').mkdir(parents=True)
    watch = tmp_path / 'logs/ops/watch.jsonl'
    watch.write_text('{}\n')
    env = {**os.environ, 'DESKTOP_FILE': str(tmp_path / 'desktop.txt')}
    run = lambda: subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True)
    assert run().stdout == '' and not (tmp_path / 'desktop.txt').exists()          # fresh
    old = time.time() - 40 * 60
    os.utime(watch, (old, old))
    assert '40분째 멈춤' in run().stdout
    assert run().stdout == ''                                                     # once an hour
    assert len((tmp_path / 'logs/ops/pm-escalations.md').read_text().splitlines()) == 1

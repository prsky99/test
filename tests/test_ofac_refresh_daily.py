"""OFAC refresh moved from a Claude scheduled task to launchd (precision review R06, 11-15)."""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tree(tmp_path, report, rc):
    (tmp_path / 'deploy/ops').mkdir(parents=True)
    (tmp_path / 'deploy/ops/ofac-refresh-daily.sh').write_text((ROOT / 'deploy/ops/ofac-refresh-daily.sh').read_text())
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/heavy_slot.py').write_text((ROOT / 'scripts/heavy_slot.py').read_text())
    (tmp_path / 'logs/ops').mkdir(parents=True)
    (tmp_path / 'logs/ops/status-board.md').write_text('# board\n## 넘기는 일\n- old\n')
    (tmp_path / 'gateway-data/ofac').mkdir(parents=True)
    bin_dir = tmp_path / '.venv/bin'
    bin_dir.mkdir(parents=True)
    fake = bin_dir / 'python'
    fake.write_text('#!/bin/bash\nif [ "$1" = "-m" ]; then echo \'%s\'; exit %d; fi\nexec %s "$@"\n' % (report, rc, sys.executable))
    fake.chmod(0o755)
    return tmp_path


def _run(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    env['OFAC_RETRY_SECONDS'] = '0'
    return subprocess.run(['bash', str(root / 'deploy/ops/ofac-refresh-daily.sh')], env=env, capture_output=True, text=True)


def test_a_good_refresh_appends_the_usual_line(tmp_path):
    root = _tree(tmp_path, '{"ok": true, "addresses": 94, "added": 0, "removed": 0}', 0)
    (root / 'gateway-data/ofac/eth_addresses.txt').write_text('0xabc\n')
    assert _run(root).returncode == 0
    line = (root / 'logs/ops/ofac-refresh.md').read_text().splitlines()[-1]
    assert line.endswith('ok 94 addresses (변동 없음: +0/-0)')
    assert '갱신 실패' not in (root / 'logs/ops/status-board.md').read_text()


def test_a_failure_with_a_week_old_list_goes_to_the_board(tmp_path):
    root = _tree(tmp_path, '{"ok": false, "problem": "too_few:3"}', 1)
    old = root / 'gateway-data/ofac/eth_addresses.txt'
    old.write_text('0xabc\n')
    week = time.time() - 7 * 86400
    os.utime(old, (week, week))
    assert _run(root).returncode == 1
    assert (root / 'logs/ops/ofac-refresh.md').read_text().splitlines()[-1].endswith('failed too_few:3')
    board = (root / 'logs/ops/status-board.md').read_text().splitlines()
    assert board[2].startswith('- ') and '제재 주소 목록이 7일째 갱신 실패' in board[2] and board[3] == '- old'


def test_a_failure_with_a_fresh_list_only_logs(tmp_path):
    root = _tree(tmp_path, '{"ok": false, "problem": "dropped:94->10"}', 1)
    (root / 'gateway-data/ofac/eth_addresses.txt').write_text('0xabc\n')
    assert _run(root).returncode == 1
    assert '갱신 실패' not in (root / 'logs/ops/status-board.md').read_text()


def test_the_launchd_job_runs_at_06_20():
    import plistlib
    spec = plistlib.loads((ROOT / 'deploy/launchd/ops/biz.agentconcierge.opsauto.ofac.plist').read_bytes())
    assert spec['StartCalendarInterval'] == {'Hour': 6, 'Minute': 20}
    assert spec['ProgramArguments'][-1].endswith('deploy/ops/ofac-refresh-daily.sh')

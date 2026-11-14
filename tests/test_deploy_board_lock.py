"""deploy and worker-deploy read the status-board lock section (11-11: deploys started under another team's lock)."""
import datetime as dt

import pytest

from scripts import service_deploy as sd

BOARD = """# 운영 현황판
## 운영 중인 버전
- frontend x
## 배포 잠금
{locks}
## 배포 대기
| 팀 | 내용 |
"""


def _root(tmp_path, locks):
    (tmp_path / 'logs/ops').mkdir(parents=True)
    (tmp_path / 'logs/ops/status-board.md').write_text(BOARD.format(locks=locks), encoding='utf-8')
    return tmp_path


def test_own_lock_line_allows_the_deploy(tmp_path):
    root = _root(tmp_path, '- 운영·SRE 11-11 11:30 jobs diskread-jobs-r1. 다른 배포 금지')
    assert sd.check_board_lock(root, '운영·SRE', now=dt.datetime(2026, 11, 11, 11, 35)) == [
        '운영·SRE 11-11 11:30 jobs diskread-jobs-r1. 다른 배포 금지']


def test_own_line_stamped_long_before_the_deploy_refuses(tmp_path):
    """11-14: the line said 13:18 (runner start) while the lock was taken at 18:10."""
    root = _root(tmp_path, '- 운영·SRE 11-14 13:18 pid=85836 frontend eve-frontend-20261114-r1')
    with pytest.raises(RuntimeError, match='deploy_lock_own_line_old'):
        sd.check_board_lock(root, '운영·SRE', now=dt.datetime(2026, 11, 14, 18, 10))
    assert sd.check_board_lock(root, '운영·SRE', now=dt.datetime(2026, 11, 14, 13, 20))


@pytest.mark.parametrize('locks', [
    '검색과 RAG 11-11 06:47 frontend p0read-frontend-20261111-r1 배포 중',
    '- 운영·SRE 11-11 11:30 jobs\n- 성장·유통 11-11 11:31 frontend',
    '- someone without a team name 07:00 frontend'])
def test_another_team_or_unknown_line_refuses(tmp_path, locks):
    root = _root(tmp_path, locks)
    with pytest.raises(RuntimeError, match='deploy_lock_held_by_another_team'):
        sd.check_board_lock(root, '운영·SRE', now=NOW, alive=lambda pid: True)


NOW = dt.datetime(2026, 11, 11, 7, 10)


@pytest.mark.parametrize('locks', ['(비어 있음)', ''])
def test_an_empty_lock_section_asks_for_your_line_first(tmp_path, locks):
    with pytest.raises(RuntimeError, match='deploy_lock_not_taken'):
        sd.check_board_lock(_root(tmp_path, locks), '검색과 RAG')


def test_unknown_owner_and_missing_board(tmp_path):
    with pytest.raises(RuntimeError, match='deploy_lock_owner_unknown'):
        sd.check_board_lock(tmp_path, 'nobody')
    assert sd.check_board_lock(tmp_path, '운영·SRE') is None   # no status board on this machine


def test_cli_requires_lock_owner_and_checks_before_anything_runs(tmp_path, monkeypatch):
    import sys
    root = _root(tmp_path, '검색과 RAG 11-11 06:47 frontend 배포 중')
    monkeypatch.setattr(sd, 'lock_staleness', lambda entry, now=None, alive=None: None)   # a live lock
    monkeypatch.setattr(sys, 'argv', ['service_deploy', '--root', str(root), 'deploy', 'frontend', 'r1'])
    with pytest.raises(SystemExit):
        sd.main()   # --lock-owner is required
    calls = []
    monkeypatch.setattr(sd.Deployment, 'check_base', lambda *a, **k: calls.append('base'), raising=False)
    monkeypatch.setattr(sd.Deployment, 'deploy_worker', lambda *a, **k: calls.append('deploy'), raising=False)
    for command in (['deploy', 'frontend', 'r1'], ['worker-deploy', 'jobs', 'r1']):
        monkeypatch.setattr(sys, 'argv', ['service_deploy', '--root', str(root), *command, '--lock-owner', '운영·SRE'])
        with pytest.raises(RuntimeError, match='deploy_lock_held_by_another_team'):
            sd.main()
    assert calls == []


@pytest.mark.parametrize('entry,alive,why', [
    ('검색과 RAG 11-11 06:47 pid=4242 frontend 배포 중', False, 'pid_gone'),
    ('검색과 RAG 11-11 06:00 pid=4242 frontend 배포 중', True, 'older_than_60m'),
    ('검색과 RAG 06:00 frontend', True, 'older_than_60m'),
    ('검색과 RAG 11-11 06:47 pid=4242 frontend', True, None),
    ('검색과 RAG frontend (no time, no pid)', True, None)])
def test_lock_staleness(entry, alive, why):
    assert sd.lock_staleness(entry, NOW, lambda pid: alive) == why


def test_a_stale_lock_needs_take_stale_lock_and_the_takeover_is_recorded(tmp_path, monkeypatch):
    # 11-11: a team's lock stayed 4.5 hours after its session ended.
    root = _root(tmp_path, '검색과 RAG 11-11 06:47 pid=4242 frontend p0read-frontend-20261111-r1 배포 중')
    with pytest.raises(RuntimeError, match='deploy_lock_stale'):
        sd.check_board_lock(root, '운영·SRE', now=NOW, alive=lambda pid: False)
    taken = sd.check_board_lock(root, '운영·SRE', take_stale=True, now=NOW, alive=lambda pid: False)
    assert taken and 'took over' in taken[0]
    board = (root / 'logs/ops/status-board.md').read_text(encoding='utf-8')
    assert '- 운영·SRE 11-11 07:10 pid=' in board and '넘겨받음(오래된 잠금): 검색과 RAG 11-11 06:47 pid=4242' in board
    assert '[pid_gone]' in board and board.count('## 배포 잠금') == 1 and '## 배포 대기' in board
    assert 'took over' in (root / 'logs/ops/deploy-lock-takeovers.md').read_text(encoding='utf-8')
    assert sd.check_board_lock(root, '운영·SRE', now=NOW, alive=lambda pid: True)   # now our own line


def test_a_live_lock_cannot_be_taken(tmp_path):
    root = _root(tmp_path, '- 성장·유통 11-11 07:05 pid=99 frontend')
    with pytest.raises(RuntimeError, match='deploy_lock_held_by_another_team'):
        sd.check_board_lock(root, '운영·SRE', take_stale=True, now=NOW, alive=lambda pid: True)

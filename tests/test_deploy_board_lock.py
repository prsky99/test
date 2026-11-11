"""deploy and worker-deploy read the status-board lock section (11-11: deploys started under another team's lock)."""
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
    assert sd.check_board_lock(root, '운영·SRE') == ['운영·SRE 11-11 11:30 jobs diskread-jobs-r1. 다른 배포 금지']


@pytest.mark.parametrize('locks', [
    '검색과 RAG 11-11 06:47 frontend p0read-frontend-20261111-r1 배포 중',
    '- 운영·SRE 11-11 11:30 jobs\n- 성장·유통 11-11 11:31 frontend',
    '- someone without a team name 11:00 frontend'])
def test_another_team_or_unknown_line_refuses(tmp_path, locks):
    root = _root(tmp_path, locks)
    with pytest.raises(RuntimeError, match='deploy_lock_held_by_another_team'):
        sd.check_board_lock(root, '운영·SRE')


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

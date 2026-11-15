"""Deploy runner board helpers in the repository (precision review R55, 11-15)."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = '# board\n## 배포 잠금\n\n(비어 있음)\n\n## 배포 대기\n- other\n## 넘기는 일\n'


def _run(tmp_path, script):
    board = tmp_path / 'board.md'
    if not board.exists():
        board.write_text(BOARD)
    env = {**os.environ, 'RL_BOARD': str(board)}
    return subprocess.run(['bash', '-c', '. %s/deploy/ops/runner-lock.sh; RL_KEY=r1; RL_WHAT="frontend r1"; %s'
                           % (ROOT, script)], env=env, capture_output=True, text=True), board


def test_reserve_take_release_and_unreserve(tmp_path):
    out, board = _run(tmp_path, 'rl_reserve; rl_reserve')
    assert out.returncode == 0 and board.read_text().count('[예약 r1]') == 1 and '- other' in board.read_text()
    out, board = _run(tmp_path, 'rl_take; echo rc=$?; rl_take; echo rc=$?; cp "$RL_BOARD" "$RL_BOARD.taken"; '
                                'rl_release; rl_unreserve')    # one shell, like a runner (lines carry its pid)
    assert 'rc=0' in out.stdout and 'rc=3' in out.stdout and 'lock held' in out.stdout
    lock = (tmp_path / 'board.md.taken').read_text().split('## 배포 잠금\n', 1)[1].split('\n## ', 1)[0]
    assert '운영·SRE' in lock and 'frontend r1' in lock and '(비어 있음)' not in lock
    text = board.read_text()
    assert '(비어 있음)' in text.split('## 배포 잠금\n', 1)[1].split('\n## ', 1)[0] and '[예약 r1]' not in text
    assert '- other' in text


def test_the_runner_template_is_valid_bash_and_stamps_the_lock_at_the_deploy_moment():
    text = (ROOT / 'deploy/ops/deploy-runner.sh').read_text()
    assert subprocess.run(['bash', '-n', str(ROOT / 'deploy/ops/deploy-runner.sh')]).returncode == 0
    assert text.index('rl_reserve') < text.index('./agentcon package') < text.index('scripts.release_gate') \
        < text.index('rl_take') < text.index('./agentcon $DEPLOY')
    assert '--base "$BASE"' in text and '--no-prune' in text
    assert '/Users/' not in (ROOT / 'deploy/ops/runner-lock.sh').read_text()

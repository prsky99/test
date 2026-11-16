"""package warns when the active release's commit is not in the packaged commit or not in the development branch
(11-16: the active bundle line eb28348f had never been merged back, so the branch tip would have dropped it)."""
import json
import subprocess

from tests.test_service_deploy import FakeDeployment


def git(root, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(root, name):
    (root / name).write_text(name)
    git(root, 'add', name)
    git(root, 'commit', '-q', '-m', name)
    return git(root, 'rev-parse', 'HEAD')


def release(manager, name, sha):
    path = manager.directory / 'releases' / name
    path.mkdir(parents=True, exist_ok=True)
    (path / 'release.json').write_text(json.dumps({'release': name, 'commit': sha}))


def test_lineage_warnings(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q')
    start = commit(root, 'a')
    git(root, 'checkout', '-q', '-b', 'dev')
    tip = commit(root, 'b')
    git(root, 'checkout', '-q', '-b', 'bundle', start)
    bundle = commit(root, 'c')
    manager = FakeDeployment(tmp_path)
    manager.root = root
    release(manager, 'active-bundle', bundle)
    release(manager, 'active-dev', start)
    # the dev tip packaged on a bundle that was never merged back: both warnings
    found = manager.lineage_warnings('active-bundle', tip, branch='dev')
    assert [w.split(':')[0] for w in found] == ['lineage_base_not_in_commit', 'lineage_active_not_on_branch']
    # a base inside both the commit and the branch: nothing to say
    assert manager.lineage_warnings('active-dev', tip, branch='dev') == []
    # after the bundle is merged into dev, packaging dev's tip is clean
    git(root, 'checkout', '-q', 'dev')
    git(root, 'merge', '-q', '--no-edit', 'bundle')
    merged = git(root, 'rev-parse', 'HEAD')
    assert manager.lineage_warnings('active-bundle', merged, branch='dev') == []
    # no base, or a base without a recorded commit: no warning, no error
    assert manager.lineage_warnings(None, merged, branch='dev') == []
    release(manager, 'old', None)
    assert manager.lineage_warnings('old', merged, branch='dev') == []


def test_a_release_only_overlay_kept_in_the_new_commit_is_not_a_lineage_break(tmp_path):
    """11-16 day bundles: each release is the branch tip plus one revert of a night-only commit, off the branch.
    The next bundle repeats the revert, so the overlay is kept; dropping it (the plain tip) still warns."""
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'checkout', '-q', '-b', 'dev')
    commit(root, 'a')
    (root / 'night').write_text('night-only')
    git(root, 'add', 'night')
    git(root, 'commit', '-q', '-m', 'night')
    tip1 = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-q', '--detach', tip1)
    git(root, 'rm', '-q', 'night')
    git(root, 'commit', '-q', '-m', 'revert night')
    r1 = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-q', 'dev')
    tip2 = commit(root, 'b')
    git(root, 'checkout', '-q', '--detach', tip2)
    git(root, 'rm', '-q', 'night')
    git(root, 'commit', '-q', '-m', 'revert night again')
    r2 = git(root, 'rev-parse', 'HEAD')
    manager = FakeDeployment(tmp_path)
    manager.root = root
    release(manager, 'day-r1', r1)
    assert manager.lineage_warnings('day-r1', r2, branch='dev') == []
    assert [w.split(':')[0] for w in manager.lineage_warnings('day-r1', tip2, branch='dev')] == [
        'lineage_base_not_in_commit', 'lineage_active_not_on_branch']

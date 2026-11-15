"""Code folder for the launchd operations jobs, built from a commit (precision review R05, 11-15).

The operations jobs (house ad ledger writes, backups first) ran the shared working copy, which several sessions edit.
They now run gateway-data/ops-code/current, a folder exported from one commit with `git archive`. Inside it, links
point at the project's data (gateway-data, logs, exports, .venv, .venv-tests), so every path a job uses (relative to
its working directory or to its own file) lands where it did before. Only the code comes from the commit.

    .venv/bin/python -m scripts.ops_code install <commit>     # export, check, then switch 'current' atomically
    .venv/bin/python -m scripts.ops_code status               # which commit 'current' runs, and the folders kept
    .venv/bin/python -m scripts.ops_code rollback             # 'current' back to the previous folder

Nothing restarts: launchd starts each job fresh at its next run. The plists that use this are in
deploy/launchd/ops-pinned/ (installation is a user step, deploy/ops/user-launchd-ops-code-20261115.md).
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
CODE = ('agent_market', 'scripts', 'deploy/ops')
DATA_LINKS = ('gateway-data', 'logs', 'exports', '.venv', '.venv-tests')
KEEP = 5


def folder(root=None):
    return Path(root or ROOT) / 'gateway-data/ops-code'


def install(commit, root=None, now=None):
    root = Path(root or ROOT)
    sha = subprocess.run(['git', 'rev-parse', '--verify', commit + '^{commit}'], cwd=root, capture_output=True,
                         text=True, check=True).stdout.strip()
    base = folder(root)
    base.mkdir(parents=True, exist_ok=True)
    name = '%s-%s' % (sha[:12], time.strftime('%Y%m%d-%H%M%S', time.localtime(now)))
    target = base / name
    staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=base))
    try:
        archive = subprocess.run(['git', 'archive', '--format=tar', sha, *CODE], cwd=root, capture_output=True)
        if archive.returncode:   # a path of CODE is not in that commit
            raise ValueError('missing_in_commit: ' + archive.stderr.decode(errors='replace').strip()[:200])
        with tarfile.open(fileobj=__import__('io').BytesIO(archive.stdout)) as tar:
            for member in tar.getmembers():
                if member.issym() or member.islnk() or member.name.startswith(('/', '..')) or '/../' in member.name:
                    raise ValueError('unsafe_archive_member: ' + member.name)
            tar.extractall(staging)
        for name_ in DATA_LINKS:
            os.symlink(root / name_, staging / name_)
        for required in ('scripts/scheduled_backup.py', 'deploy/ops/house-ad-daily.sh'):
            if not (staging / required).is_file():
                raise ValueError('missing_in_commit: ' + required)
        (staging / 'ops-code.json').write_text(json.dumps({'commit': sha, 'installed': time.time() if now is None else now}))
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    switch(base, name)
    prune(base)
    return status(root)


def switch(base, name):
    """Point 'current' at NAME atomically (a new link renamed over the old one); 'previous' keeps the old target."""
    current = base / 'current'
    if current.is_symlink():
        old = os.readlink(current)
        if old != name:
            _replace_link(base, 'previous', old)
    _replace_link(base, 'current', name)


def _replace_link(base, link, name):
    temporary = base / ('.%s-%d' % (link, os.getpid()))
    if temporary.is_symlink() or temporary.exists():
        temporary.unlink()
    os.symlink(name, temporary)
    os.replace(temporary, base / link)


def rollback(root=None):
    base = folder(root)
    previous = base / 'previous'
    if not previous.is_symlink() or not (base / os.readlink(previous)).is_dir():
        raise SystemExit('no_previous_ops_code')
    switch(base, os.readlink(previous))
    return status(root)


def prune(base, keep=KEEP):
    """Keep the newest KEEP folders and whatever 'current' and 'previous' point at."""
    pinned = {os.readlink(base / link) for link in ('current', 'previous') if (base / link).is_symlink()}
    folders = sorted((p for p in base.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith('.')),
                     key=lambda p: p.name.split('-', 1)[-1])
    for path in folders[:-keep]:
        if path.name not in pinned:
            shutil.rmtree(path)


def status(root=None):
    base = folder(root)
    out = {'current': None, 'previous': None, 'folders': []}
    for link in ('current', 'previous'):
        if (base / link).is_symlink():
            name = os.readlink(base / link)
            try:
                meta = json.loads((base / name / 'ops-code.json').read_text())
            except (OSError, ValueError):
                meta = {}
            out[link] = {'folder': name, 'commit': meta.get('commit')}
    if base.is_dir():
        out['folders'] = sorted(p.name for p in base.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith('.'))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('install').add_argument('commit')
    sub.add_parser('status')
    sub.add_parser('rollback')
    args = parser.parse_args(argv)
    result = install(args.commit) if args.command == 'install' else rollback() if args.command == 'rollback' else status()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

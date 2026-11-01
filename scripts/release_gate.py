"""Run the opening-path tests against a release copy before it is deployed.

Releases are built by overlaying files on the active release, so tests in the working copy do
not prove the release. 11-02 07:01: batch-reads r5 passed in the working copy but every customer
opening page failed in production (gzip inside batched reads); 11-02: a release built from the
repository would have lost typed_engine_for. This copies the release and the repository's tests
into a scratch directory and runs a short list of tests there, at low priority (CLAUDE.md).

    .venv-tests/bin/python -m scripts.release_gate batch-reads-frontend-20261102-r6
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES = ROOT / 'gateway-data' / 'services' / 'releases'
# Fast checks of what every customer and public page needs to open (about a minute).
TESTS = (
    'tests/test_customer_batch.py',
    'tests/test_typed_engine_for.py',
    'tests/test_workspace_read_only_paths.py',
    'tests/test_front_first_entry_browser.py',
    'tests/test_workspace_entry_progress_browser.py',
)


def copy_release(release, into):
    source = RELEASES / release
    if not (source / 'release.json').is_file():
        raise SystemExit(f'release not found: {release}')
    target = into / release
    # APFS clones (cp -c) make a full copy of a release almost free.
    subprocess.run(['cp', '-cR', str(source), str(target)], check=True)
    shutil.copytree(ROOT / 'tests', target / 'tests')
    for name in ('pytest.ini', 'conftest.py', 'pyproject.toml', 'setup.cfg'):
        if (ROOT / name).is_file() and not (target / name).exists():
            shutil.copy2(ROOT / name, target / name)
    return target


def run(release, tests, python):
    with tempfile.TemporaryDirectory(prefix='release-gate-') as scratch:
        copy = copy_release(release, Path(scratch).resolve())
        env = {**os.environ, 'PYTHONPATH': str(copy)}
        where = subprocess.run([python, '-c', 'import agent_market; print(agent_market.__file__)'],
                               cwd=copy, env=env, capture_output=True, text=True, check=True).stdout.strip()
        if not str(Path(where).resolve()).startswith(str(copy)):
            raise SystemExit(f'tests would import the wrong code: {where}')
        result = subprocess.run(['nice', '-n', '10', python, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *tests],
                                cwd=copy, env=env)
        return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('release')
    parser.add_argument('tests', nargs='*', default=list(TESTS))
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args(argv)
    code = run(args.release, args.tests, args.python)
    print(f'release gate {args.release}: ' + ('passed' if code == 0 else f'FAILED (pytest exit {code})'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())

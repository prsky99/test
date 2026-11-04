"""Run the opening-path tests against a release copy before it is deployed.

Releases are built by overlaying files on the active release, so tests in the working copy do
not prove the release. 11-02 07:01: batch-reads r5 passed in the working copy but every customer
opening page failed in production (gzip inside batched reads); 11-02: a release built from the
repository would have lost typed_engine_for. This copies the release and the repository's tests
into a scratch directory and runs a short list of tests there, at low priority (CLAUDE.md).

    .venv-tests/bin/python -m scripts.release_gate batch-reads-frontend-20261102-r6

When the release changes how Chat recommends (CHAT_FILES differ from the active frontend), it also
runs a fixed Chat evaluation sample on both releases against production, read-only, and refuses a
release that answers more of them wrongly (2nd review A-3, 2026-11-04). --skip-chat skips that.
"""
import argparse
import hashlib
import json
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


# Files whose change can move a Chat recommendation (the policy-hash files and the Chat path).
CHAT_FILES = (
    'agent_market/concierge/selection.py', 'agent_market/concierge/discovery.py',
    'agent_market/concierge/task_requirements.py', 'agent_market/concierge/explore_search.py',
    'agent_market/concierge/execution_policy.py', 'agent_market/capability_registry.py',
    'agent_market/collector/usage.py', 'agent_market/postgres_capability_text.py',
    'agent_market/concierge/fast_chat.py', 'agent_market/concierge/llm.py',
    'agent_market/concierge/chat_guidance.py', 'agent_market/concierge/chat_query_rewrite.py',
    'agent_market/concierge/chat_task_spec.py', 'agent_market/concierge/task_conditions.py',
    'agent_market/concierge/query_intent.py', 'agent_market/concierge/engine.py',
)
CASES_1K = ROOT / 'tests' / 'data' / 'chat_answer_quality_cases_1k.json'
CASES_REVIEW = ROOT / 'tests' / 'data' / 'chat_answer_quality_cases.json'
CHAT_SAMPLE = 100   # holdout cases, chosen by id hash so every gate reads the same ones
CHAT_MARGIN = 2     # refuse when new failures exceed new passes by this many


def active_frontend():
    state = json.loads((ROOT / 'gateway-data' / 'services' / 'state.json').read_text())['services']['frontend']
    return state['slots'][state['active']]


def chat_changed(release, active):
    """CHAT_FILES whose bytes differ between the two releases."""
    def read(name, path):
        target = RELEASES / name / path
        return target.read_bytes() if target.is_file() else None
    return [path for path in CHAT_FILES if read(release, path) != read(active, path)]


def chat_sample(size=CHAT_SAMPLE):
    holdout = json.loads(CASES_1K.read_text(encoding='utf-8'))['holdout']
    picked = sorted(holdout, key=lambda case: hashlib.sha1(case['id'].encode()).hexdigest())[:size]
    review = json.loads(CASES_REVIEW.read_text(encoding='utf-8')).get('review', [])
    return review + picked


def evaluate(release, cases_file, out, only=None):
    python = ROOT / '.venv' / 'bin' / 'python'
    env = {**os.environ, **({'EVAL_ONLY': ','.join(only)} if only else {})}
    env.pop('EVAL_REPEAT', None); env.pop('EVAL_SUBSET', None); env.pop('EVAL_RECALL', None)
    subprocess.run(['nice', '-n', '10', str(python), '-B', 'scripts/evaluate_chat_answer_quality.py',
                    str(RELEASES / release), f'{cases_file}:gate', str(out)],
                   cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {row['id']: bool(row['ok']) for row in json.loads(Path(out).read_text(encoding='utf-8'))}


def compare(before, after):
    """(new failures, new passes) between two {id: ok} verdicts on the same cases."""
    broken = sorted(i for i in before if before[i] and not after.get(i, False))
    fixed = sorted(i for i in before if not before[i] and after.get(i, False))
    return broken, fixed


def chat_check(release, active=None, *, evaluate=evaluate):
    """0 when the release answers the sample no worse than the active frontend, 1 otherwise."""
    active = active or active_frontend()
    changed = chat_changed(release, active)
    if not changed:
        print(f'chat check: skipped (no Chat file differs from {active})')
        return 0
    print(f'chat check: {len(changed)} Chat file(s) differ from {active}: ' + ', '.join(Path(p).name for p in changed))
    with tempfile.TemporaryDirectory(prefix='chat-gate-') as scratch:
        cases = Path(scratch) / 'cases.json'
        cases.write_text(json.dumps({'gate': chat_sample()}), encoding='utf-8')
        before = evaluate(active, cases, Path(scratch) / 'active.json')
        after = evaluate(release, cases, Path(scratch) / 'release.json')
        broken, fixed = compare(before, after)
        if broken:
            # A verdict that flips back on a second run is noise (live health, model load), not a regression.
            again = evaluate(release, cases, Path(scratch) / 'again.json', only=broken)
            broken = [i for i in broken if not again.get(i, False)]
    print(f'chat check: active {sum(before.values())}/{len(before)}, release {sum(after.values())}/{len(after)}; '
          f'new failures {len(broken)} {broken[:10]}, new passes {len(fixed)}')
    if len(broken) - len(fixed) >= CHAT_MARGIN:
        print('chat check: FAILED (more new failures than passes; see scripts/evaluate_chat_answer_quality.py)')
        return 1
    return 0


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
    parser.add_argument('--skip-chat', action='store_true', help='skip the Chat evaluation comparison')
    args = parser.parse_args(argv)
    code = run(args.release, args.tests, args.python)
    if code == 0 and not args.skip_chat:
        code = chat_check(args.release)
    print(f'release gate {args.release}: ' + ('passed' if code == 0 else f'FAILED (pytest exit {code})'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())

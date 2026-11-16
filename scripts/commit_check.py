"""Checks a commit range before it leaves this Mac (PM 11-16 source review 5.3, 운영·SRE).

    .venv/bin/python -m scripts.commit_check origin/claude/hopeful-darwin-i3qj6n..HEAD   # a range
    .venv/bin/python -m scripts.commit_check --staged                                    # the index (git commit)

Why: the static check (tests/test_pyflakes_undefined_names.py) only looked at agent_market, and nothing looked at a
commit before it was pushed from the shared working tree. Team sessions commit with a temporary index and
`git commit-tree`, which runs no git hook, so the check runs from the pre-push hook (every push, however the commit
was made) and from pre-commit (a plain `git commit`). Hooks live in .githooks/ (core.hooksPath).

What it checks, in the files a commit adds or changes:
- files that must never be committed: deploy/gateway.env, key and wallet files, gateway-data/, exports/, and the
  local-only review reports (the repository is public)
- a private key block or an Anthropic API key in any text file
- undefined names (pyflakes) in agent_market/ and scripts/ Python files
- Hangul in agent_market/concierge/*.py (agent-facing text is English; the frontend gate fails on it)
- policy-hash files (explore and selection rules): a note that the release goes out at night only

11-16: warnings only. From BLOCK_FROM (KST) a finding stops the push or commit; COMMIT_CHECK_SKIP="<reason>" lets one
through and the reason is logged in logs/ops/commit-check.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / 'logs/ops/commit-check.jsonl'
BLOCK_FROM = '20261117'   # PM 11-16 15:42: warn today, block from tomorrow
NEVER = (re.compile(r'(^|/)deploy/gateway\.env$'), re.compile(r'\.(pem|key|p12|keystore)$'),
         re.compile(r'(^|/)wallet[^/]*\.(json|txt)$'), re.compile(r'^gateway-data/'), re.compile(r'^exports/'),
         re.compile(r'^reports/precision-review-2026-11-15/README\.md$'),
         re.compile(r'^reports/source-review-2026-11-16/README\.md$'))
SECRET = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-ant-[A-Za-z0-9_-]{20,}')
HANGUL = re.compile('[가-힣ᄀ-ᇿ㄰-㆏]')
POLICY_FILES = ('agent_market/explore_documents.py', 'agent_market/concierge/selection.py',
                'agent_market/concierge/task_requirements.py', 'agent_market/concierge/explore_search.py',
                'agent_market/concierge/execution_policy.py', 'agent_market/capability_registry.py',
                'agent_market/collector/usage.py', 'agent_market/postgres_capability_text.py')


def git(*args, check=True):
    done = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    if check and done.returncode:
        raise RuntimeError(done.stderr.strip() or 'git ' + ' '.join(args))
    return done.stdout


def changed_files(spec):
    """(path, blob) for files added or changed: by a commit range, or in the index for 'staged'."""
    if spec == 'staged':
        out = git('diff', '--cached', '--name-only', '--diff-filter=AM', '-z')
        return [(p, ':' + p) for p in out.split('\0') if p]
    files = {}
    for sha in git('rev-list', '--no-merges', spec).split():
        out = git('diff-tree', '--no-commit-id', '-r', '--name-only', '--diff-filter=AM', '-z', sha)
        for p in out.split('\0'):
            if p and p not in files:
                files[p] = sha + ':' + p     # the newest commit that touched it (rev-list is newest first)
    return sorted(files.items())


def text_of(blob):
    done = subprocess.run(['git', 'show', blob], cwd=ROOT, capture_output=True)
    if done.returncode or b'\0' in done.stdout[:8000]:
        return None
    return done.stdout.decode('utf-8', 'replace')


def undefined_names(path, text):
    try:
        from pyflakes import api, messages, reporter
    except ImportError:
        return []
    found = []

    class Collect(reporter.Reporter):
        def __init__(self):
            super().__init__(None, None)

        def flake(self, message):
            if isinstance(message, messages.UndefinedName):
                found.append('%s:%s undefined name %r' % (path, message.lineno, message.message_args[0]))

        def syntaxError(self, filename, msg, lineno, offset, text):
            found.append('%s:%s syntax error: %s' % (path, lineno, msg))

        def unexpectedError(self, filename, msg):
            pass
    api.check(text, path, Collect())
    return found


def findings(files, read=None):
    """(problems, notes) for FILES [(path, blob)]; READ(blob) gives the text (git show by default)."""
    read = read or text_of
    problems, notes = [], []
    for path, blob in files:
        if any(rule.search(path) for rule in NEVER):
            problems.append(f'{path}: must not be committed (public repository)')
            continue
        text = read(blob)
        if text is None:
            continue
        if SECRET.search(text):
            problems.append(f'{path}: looks like a private key or an API key')
        if path.endswith('.py') and (path.startswith('agent_market/') or path.startswith('scripts/')):
            problems += undefined_names(path, text)
        if path.startswith('agent_market/concierge/') and path.endswith('.py') and HANGUL.search(text):
            problems.append(f'{path}: Hangul in agent-facing source (escape it or move it out)')
        if path in POLICY_FILES:
            notes.append(f'{path}: policy-hash file - its release goes out at night (00:30-01:30) only')
    return problems, notes


def blocking(now=None):
    return time.strftime('%Y%m%d', time.localtime(now)) >= BLOCK_FROM


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('range', nargs='?', help='commit range, e.g. origin/<branch>..HEAD')
    parser.add_argument('--staged', action='store_true', help='check the index (pre-commit)')
    args = parser.parse_args(argv)
    spec = 'staged' if args.staged else args.range
    if not spec:
        parser.error('give a range or --staged')
    problems, notes = findings(changed_files(spec))
    for note in notes:
        print('commit_check note: ' + note, file=sys.stderr)
    if not problems:
        return 0
    block = blocking()
    skip = os.environ.get('COMMIT_CHECK_SKIP', '').strip()
    for line in problems:
        print(('commit_check BLOCK: ' if block and not skip else 'commit_check WARNING: ') + line, file=sys.stderr)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a') as out:
        out.write(json.dumps({'at': time.strftime('%Y-%m-%d %H:%M'), 'spec': spec, 'problems': problems,
                              'blocked': bool(block and not skip), 'skip_reason': skip or None},
                             ensure_ascii=False) + '\n')
    if block and not skip:
        print('commit_check: fix the lines above, or set COMMIT_CHECK_SKIP="<reason>" (logged)', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

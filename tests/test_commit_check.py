"""scripts/commit_check.py: the push and commit check (PM 11-16 source review 5.3). No git calls here."""
import time

from scripts import commit_check as cc


def run(files):
    texts = dict(files)
    return cc.findings([(path, path) for path in texts], read=texts.get)


def test_never_committed_files_secrets_undefined_names_and_hangul():
    problems, notes = run([
        ('deploy/gateway.env', 'X=1'),
        ('reports/source-review-2026-11-16/README.md', '# local'),
        ('docs/note.md', '-----BEGIN OPENSSH ' + 'PRIVATE KEY-----\nabc'),   # split so this file is not a finding
        ('scripts/x.py', 'def f():\n    return missing_name\n'),
        ('agent_market/concierge/reply.py', 'TEXT = "' + '한글' + '"\n'),
        ('agent_market/concierge/selection.py', 'A = 1\n'),
        ('tests/test_y.py', 'def test():\n    assert undefined_here\n'),   # tests are not checked for names
    ])
    assert any('deploy/gateway.env' in p for p in problems)
    assert any('source-review' in p for p in problems)
    assert any('docs/note.md' in p and 'private key' in p for p in problems)
    assert any("scripts/x.py:2 undefined name 'missing_name'" == p for p in problems)
    assert any('reply.py' in p and 'Hangul' in p for p in problems)
    assert not any('tests/test_y.py' in p for p in problems)
    assert notes == ['agent_market/concierge/selection.py: policy-hash file - its release goes out at night (00:30-01:30) only']


def test_clean_files_pass():
    assert run([('agent_market/a.py', 'import os\nprint(os.sep)\n'), ('README.md', 'hello')]) == ([], [])


def test_warn_on_1116_block_from_1117():
    assert not cc.blocking(time.mktime((2026, 11, 16, 23, 59, 0, 0, 0, -1)))
    assert cc.blocking(time.mktime((2026, 11, 17, 0, 0, 0, 0, 0, -1)))

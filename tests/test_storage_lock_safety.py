"""Storage permission hardening must never release SQLite's POSIX locks."""
import os
import sqlite3
import stat
import subprocess
import sys

import pytest

from agent_market.storage_security import private_sqlite_file


@pytest.mark.skipif(os.name != 'posix', reason='POSIX advisory lock regression')
def test_permissions_preserve_an_active_transaction_lock(tmp_path):
    path = tmp_path / 'shared.sqlite3'
    db = sqlite3.connect(path)
    try:
        db.execute('CREATE TABLE example (value INTEGER)')
        db.commit()
        db.execute('BEGIN IMMEDIATE')
        private_sqlite_file(path)
        contender = subprocess.run([sys.executable, '-c', '''
import sqlite3,sys
c=sqlite3.connect(sys.argv[1],timeout=.05)
try:
    c.execute('BEGIN IMMEDIATE')
except sqlite3.OperationalError as error:
    if 'locked' not in str(error): raise
    sys.exit(0)
else:
    c.rollback()
    sys.exit(1)
''', str(path)], capture_output=True, text=True, timeout=5)
        assert contender.returncode == 0, contender.stderr or 'Permission change released the active writer lock'
    finally:
        db.rollback()
        db.close()


def test_permissions_do_not_open_existing_database_or_sidecars(tmp_path, monkeypatch):
    path = tmp_path / 'existing.sqlite3'
    for suffix in ('', '-wal', '-shm'):
        target = tmp_path / (path.name + suffix)
        target.write_bytes(b'preserve')
        target.chmod(0o644)
    def forbidden(*args, **kwargs):
        raise AssertionError('Existing SQLite files must not be opened outside SQLite')
    monkeypatch.setattr(os, 'open', forbidden)
    private_sqlite_file(path)
    for suffix in ('', '-wal', '-shm'):
        target = tmp_path / (path.name + suffix)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert target.read_bytes() == b'preserve'


@pytest.mark.parametrize('suffix', ['', '-wal', '-shm'])
def test_permission_hardening_refuses_symlinks(tmp_path, suffix):
    path = tmp_path / 'store.sqlite3'
    if suffix:
        path.write_bytes(b'original')
    target = tmp_path / 'other.txt'
    target.write_text('unchanged')
    target.chmod(0o644)
    (tmp_path / (path.name + suffix)).symlink_to(target)
    with pytest.raises(OSError):
        private_sqlite_file(path)
    assert target.read_text() == 'unchanged'
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_new_database_is_private_and_existing_content_is_preserved(tmp_path):
    path = tmp_path / 'new.sqlite3'
    private_sqlite_file(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE example (value INTEGER)')
        db.execute('INSERT INTO example VALUES (42)')
    private_sqlite_file(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT value FROM example').fetchone()[0] == 42

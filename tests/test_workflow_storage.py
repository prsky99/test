"""Storage observations cannot mutate execution, keys or maintenance state."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from agent_market import workflow_storage as storage


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'private-storage.sqlite3'
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE workflow_runs(id TEXT,status TEXT,execution_outcome TEXT);
        CREATE TABLE workflow_result_outbox(status TEXT);
        CREATE TABLE workflow_manual_deliveries(status TEXT);
        INSERT INTO workflow_runs VALUES('kept-secret-run','failed','unknown');
        INSERT INTO workflow_runs VALUES('queued-run','queued',NULL);
        INSERT INTO workflow_result_outbox VALUES('unknown');
        INSERT INTO workflow_manual_deliveries VALUES('accepted');''')
    db.close()
    return path


def test_read_only_snapshot_has_allocation_queues_without_private_values(database):
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    observed = storage.observe(database)
    assert observed['available'] and observed['coverage']['complete']
    assert observed['workflow_counts']['runs'] == {'states': {'failed': 1, 'queued': 1}, 'unknown_outcomes': 1}
    assert observed['workflow_counts']['result_outbox']['states'] == {'unknown': 1}
    assert observed['sqlite']['allocated_bytes'] > 0
    assert 0 <= observed['sqlite']['free_page_bytes'] <= observed['sqlite']['allocated_bytes']
    assert not observed['coverage']['lock_contention_measured']
    assert not observed['coverage']['file_sizes_are_transactional']
    assert not any(observed['actions'].values())
    assert not any(value in json.dumps(observed) for value in [str(database), database.name, 'kept-secret-run'])
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert not list(database.parent.glob('*.updates-key'))


def test_sqlite_handle_is_read_only_and_no_maintenance_statement_runs(database, monkeypatch):
    original = sqlite3.connect
    statements = []

    class Recording(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            statements.append(statement)
            return super().execute(statement, *args, **kwargs)

    def connect(target, *args, **kwargs):
        assert target.endswith('?mode=ro') and kwargs['uri'] is True
        return original(target, *args, factory=Recording, **kwargs)

    monkeypatch.setattr(storage.sqlite3, 'connect', connect)
    assert storage.observe(database)['available']
    assert all(statement.startswith(('SELECT', 'PRAGMA', 'BEGIN')) for statement in statements)
    assert not any(word in ' '.join(statements).lower() for word in ['vacuum', 'wal_checkpoint', 'insert ', 'delete ', 'update ', 'create '])


def test_wal_committed_rows_are_included_without_explicit_checkpoint(database):
    writer = sqlite3.connect(database)
    try:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO workflow_runs VALUES('wal-only-run','running',NULL)")
        writer.commit()
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        observed = storage.observe(database)
        assert observed['workflow_counts']['runs']['states']['running'] == 1
        assert observed['files']['wal']['present'] and observed['files']['wal']['bytes'] > 0
        assert observed['sqlite']['journal_mode'] == 'wal'
        assert hashlib.sha256(database.read_bytes()).hexdigest() == before
        assert not observed['actions']['wal_checkpoint']
    finally:
        writer.close()


@pytest.mark.parametrize('kind', ['missing', 'directory', 'invalid'])
def test_unavailable_database_is_safe_and_never_created(tmp_path, kind):
    path = tmp_path / 'not-a-database'
    if kind == 'directory':
        path.mkdir()
    if kind == 'invalid':
        path.write_text('private-secret-content')
    before = sorted(str(item) for item in tmp_path.iterdir())
    result = storage.observe(path)
    assert not result['available'] and not result['coverage']['complete']
    assert sorted(str(item) for item in tmp_path.iterdir()) == before
    assert not any(part in json.dumps(result) for part in [str(path), 'private-secret-content', 'Traceback'])


def test_exclusive_writer_returns_bounded_unavailable_without_touching_writer(database):
    writer = sqlite3.connect(database)
    try:
        writer.execute('BEGIN EXCLUSIVE')
        started = time.monotonic()
        result = storage.observe(database)
        assert time.monotonic() - started < 1
        assert not result['available'] and 'database' in result['coverage']['unavailable_sections']
        assert writer.in_transaction
    finally:
        writer.rollback()
        writer.close()


def test_budget_reports_partial_coverage_instead_of_fabricating_zero(database, monkeypatch):
    monkeypatch.setattr(storage, 'SECONDS', 0)
    result = storage.observe(database)
    assert not result['coverage']['complete']
    assert result['workflow_counts'] == {}
    assert result['coverage']['unavailable_sections']


def test_unknown_status_is_aggregated_without_rendering_stored_text(database):
    with sqlite3.connect(database) as db:
        db.execute('INSERT INTO workflow_runs VALUES(?,?,?)', ('other-run', '<script>private diagnostic</script>', 'unknown'))
    result = storage.observe(database)
    assert result['workflow_counts']['runs']['states']['other'] == 1
    assert result['workflow_counts']['runs']['unknown_outcomes'] == 2
    assert 'private diagnostic' not in json.dumps(result)


def test_storage_endpoint_requires_current_superadmin_and_never_caches(database):
    app = FastAPI()

    def require_sadmin(request: Request):
        if request.headers.get('x-test-role') != 'superadmin':
            raise HTTPException(403, 'Forbidden')

    app.include_router(storage.router_for(database, require_sadmin))
    with TestClient(app) as client:
        for headers in ({}, {'x-test-role': 'admin'}):
            rejected = client.get('/admin/api/workflows/storage', headers=headers)
            assert rejected.status_code == 403 and rejected.headers['cache-control'] == 'no-store'
        response = client.get('/admin/api/workflows/storage', headers={'x-test-role': 'superadmin'})
        assert response.status_code == 200 and response.json()['available']
        assert response.headers['cache-control'] == 'no-store'
        assert client.post('/admin/api/workflows/storage', headers={'x-test-role': 'superadmin'}).status_code == 405


def test_cli_inspection_keeps_existing_database_and_no_key_or_server(database):
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    command = [sys.executable, '-B', '-m', 'agent_market.workflow_storage', '--db', str(database)]
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=5)
    assert result.returncode == 0 and json.loads(result.stdout)['read_only'] is True
    assert not result.stderr and hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert {path.name for path in database.parent.iterdir()} == {database.name}

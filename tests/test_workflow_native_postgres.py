"""Explicit native worker/archive boundaries and actual private cluster contracts."""
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from agent_market.workflow_postgres import PostgresWorkflowWorker, NativeWorkflowUnavailable
from agent_market.workflow_postgres_archive import (
    NativeArchiveUnavailable, _environment, _json, _private, _read, _run, backup, restore,
)


class NoIo:
    @property
    def autocommit(self):
        pytest.fail('Invalid configuration inspected a database connection')


@pytest.mark.parametrize('key', [None, b'', b'k' * 31, b'k' * 33, 'k' * 32, bytearray(b'k' * 32)])
def test_native_worker_requires_exact_explicit_key_before_any_io(key):
    with pytest.raises(NativeWorkflowUnavailable, match='explicit_workflow_key_required'):
        PostgresWorkflowWorker(NoIo(), workflow_key=key)


@pytest.mark.parametrize('function', [backup, restore])
def test_archive_requires_explicit_key_before_database_or_filesystem_io(tmp_path, function):
    with pytest.raises(NativeArchiveUnavailable, match='explicit_workflow_key_required'):
        function(NoIo(), tmp_path / 'must-not-exist', workflow_key=None, cluster={}, tools={})
    assert not (tmp_path / 'must-not-exist').exists()


def test_worker_refuses_a_non_explicit_execution_transport_before_database_io():
    with pytest.raises(NativeWorkflowUnavailable, match='explicit_proxy_required'):
        PostgresWorkflowWorker(NoIo(), workflow_key=b'k' * 32, proxy=object())


def test_worker_initialization_failure_detaches_facade_without_closing_caller(monkeypatch):
    closed = []
    facade = SimpleNamespace(close=lambda: closed.append('facade'))
    monkeypatch.setattr('agent_market.storage_adapter.open_store', lambda *_args, **_kwargs: facade)
    def reject(*_args, **_kwargs): raise ValueError('Synthetic runtime attachment refusal')
    monkeypatch.setattr('agent_market.workflows.WorkflowRuntime', reject)
    with pytest.raises(ValueError, match='Synthetic runtime attachment refusal'):
        PostgresWorkflowWorker(NoIo(), workflow_key=b'k' * 32)
    assert closed == ['facade']


@pytest.mark.parametrize('cluster', [{}, {'root': '/private/tmp/operating', 'socket': '/private/tmp/operating/socket'},
    {'root': '/Users/operating', 'socket': '/Users/operating/socket'},
    {'root': '/private/tmp/a2a-adapter-pg-fixture', 'socket': '/private/tmp/elsewhere'}])
def test_archive_does_not_infer_or_attach_operating_connection(cluster):
    with pytest.raises(NativeArchiveUnavailable, match='owned_private_cluster_required'):
        _private(NoIo(), cluster)


def test_archive_tools_receive_fixed_argv_and_clean_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('PGPASSWORD', 'synthetic-private-password')
    monkeypatch.setenv('PGSERVICE', 'operating-service')
    monkeypatch.setenv('AGENT_PRIVATE_ARTIFACT_KEYRING', 'private-keyring')
    recorded = []
    def call(argv, **kwargs):
        recorded.append((argv, kwargs)); return SimpleNamespace(returncode=0)
    monkeypatch.setattr('agent_market.workflow_postgres_archive.subprocess.run', call)
    target = {'root': tmp_path, 'host': '/private/tmp/a2a-adapter-pg-fixture/socket', 'port': 55447,
              'database': 'postgres', 'user': 'postgres'}
    _run('/trusted/pg_dump', target, ['--format=custom', '--file=/private/tmp/synthetic.dump'])
    argv, kwargs = recorded[0]
    assert argv == ['/trusted/pg_dump', '--host=/private/tmp/a2a-adapter-pg-fixture/socket', '--port=55447',
        '--username=postgres', '--dbname=postgres', '--no-password', '--format=custom', '--file=/private/tmp/synthetic.dump']
    assert kwargs['env'] == _environment(tmp_path) and kwargs['timeout'] == 60
    assert not any(key in kwargs['env'] for key in ('PGPASSWORD', 'PGSERVICE', 'AGENT_PRIVATE_ARTIFACT_KEYRING'))
    assert 'shell' not in kwargs


def test_archive_tool_failure_exposes_only_safe_code(monkeypatch, tmp_path):
    monkeypatch.setattr('agent_market.workflow_postgres_archive.subprocess.run',
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr=b'synthetic-private-driver-details'))
    target = {'root': tmp_path, 'host': '/private/tmp/socket', 'port': 1, 'database': 'postgres', 'user': 'postgres'}
    with pytest.raises(NativeArchiveUnavailable) as caught:
        _run('/trusted/pg_restore', target, [])
    assert str(caught.value) == 'archive_tool_failed'
    assert 'synthetic-private' not in str(caught.value)


def test_artifact_read_refuses_symlink_world_readable_and_oversize_before_body(tmp_path):
    private = tmp_path / 'private'
    private.write_bytes(b'synthetic'); private.chmod(0o600)
    assert _read(private, 9) == b'synthetic'
    linked = tmp_path / 'linked'; linked.symlink_to(private)
    with pytest.raises(OSError): _read(linked, 9)
    private.chmod(0o644)
    with pytest.raises(NativeArchiveUnavailable): _read(private, 9)
    private.chmod(0o600)
    with pytest.raises(NativeArchiveUnavailable): _read(private, 8)


def test_encrypt_requires_explicit_key_configuration_before_new_archive_creation(monkeypatch, tmp_path):
    monkeypatch.delenv('AGENT_PRIVATE_ARTIFACT_KEYRING', raising=False)
    monkeypatch.setattr('agent_market.workflow_postgres_archive._private', lambda *_args: {})
    monkeypatch.setattr('agent_market.workflow_postgres_archive._tools', lambda *_args: {})
    with pytest.raises(NativeArchiveUnavailable, match='explicit_encryption_key_required'):
        backup(NoIo(), tmp_path / 'archive', workflow_key=b'k' * 32, cluster={}, tools={}, encrypt=True)
    assert not (tmp_path / 'archive').exists()


def test_authenticated_archive_with_old_schema_refuses_implicit_migration_before_tool(monkeypatch, tmp_path):
    import hashlib
    import hmac
    from agent_market.private_artifact_keys import ArtifactSigner
    from agent_market.workflow_postgres_archive import PROFILE
    monkeypatch.delenv('AGENT_PRIVATE_ARTIFACT_KEYRING', raising=False)
    monkeypatch.setattr('agent_market.workflow_postgres_archive._private', lambda *_args: {})
    monkeypatch.setattr('agent_market.workflow_postgres_archive._tools', lambda *_args: {})
    monkeypatch.setattr('agent_market.workflow_postgres_archive._query', lambda *_args: [(0,)])
    monkeypatch.setattr('agent_market.workflow_postgres_archive._run', lambda *_args: pytest.fail('Old schema reached pg_restore'))
    key = b'k' * 32
    manifest = {'profile': PROFILE, 'version': 1, 'encrypted': False, 'schema_sha256': '0' * 64}
    manifest['signature'] = ArtifactSigner(hmac.new(key, PROFILE.encode(), hashlib.sha256).digest(), PROFILE).sign(manifest)
    path = tmp_path / 'manifest.json'; path.write_text(json.dumps(manifest)); path.chmod(0o600)
    with pytest.raises(NativeArchiveUnavailable, match='archive_authentication_failed'):
        restore(NoIo(), tmp_path, workflow_key=key, cluster={}, tools={})


@pytest.mark.parametrize('value', [b'{"x":1,"x":2}', b'[]', b'{"x":NaN}', b'\xff', b'null'])
def test_manifest_parser_refuses_ambiguous_or_nonfinite_content(value):
    with pytest.raises(NativeArchiveUnavailable, match='invalid_archive_manifest'):
        _json(value)


def test_worker_wait_and_close_keep_live_execution_slot_and_caller_connection():
    from concurrent.futures import Future
    worker = PostgresWorkflowWorker.__new__(PostgresWorkflowWorker)
    running = Future(); closed = []
    worker._closed = False
    worker._lock = threading.RLock()
    worker.runtime = SimpleNamespace(futures={'run': running}, lock=threading.RLock())
    worker.store = SimpleNamespace(close=lambda: closed.append(True))
    with pytest.raises(NativeWorkflowUnavailable, match='worker_still_active'): worker.close()
    with pytest.raises(NativeWorkflowUnavailable, match='worker_still_active'): worker.wait(timeout=.001)
    assert not closed and not worker._closed
    running.set_result(None); worker.close(); worker.close()
    assert closed == [True] and worker._closed


def test_native_rehearsal_cli_refuses_any_operating_connection_argument(monkeypatch):
    from scripts import rehearse_workflow_native_postgres as runner
    monkeypatch.setattr(runner, 'rehearse', lambda: pytest.fail('Invalid arguments reached native harness'))
    with pytest.raises(SystemExit): runner.main([])
    with pytest.raises(SystemExit): runner.main(['--run', '--dsn', 'postgresql://private.invalid/operating'])


def test_actual_native_worker_crash_outbox_archive_restore_and_key_rotation(monkeypatch, request):
    from scripts.rehearse_workflow_native_postgres import rehearse
    for name, value in {'PGHOST': 'operating.invalid', 'PGSERVICE': 'synthetic-no-service',
        'PGPASSWORD': 'synthetic-unused-parent-password', 'AGENT_PRIVATE_ARTIFACT_KEYRING': '/private/absent-parent-keyring',
        'REDIS_HOST': 'operating.invalid', 'REDIS_PORT': '6379'}.items():
        monkeypatch.setenv(name, value)
    before = dict(os.environ)
    result = rehearse()
    request.node.user_properties.append(('native_contracts', json.dumps(result, sort_keys=True)))
    assert dict(os.environ) == before
    assert len(result['checks']) >= 20 and all(value is True for value in result['checks'].values())
    assert result['temporary_cluster_removed'] and result['synthetic']
    assert result['external_provider_calls'] == result['delivery_calls'] == result['production_actions'] == 0
    assert not result['operating_backup_ready']

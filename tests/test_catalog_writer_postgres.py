"""Required disposable PostgreSQL atomic-writer and outbox parity contracts."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import rehearse_catalog_writer_postgres as rehearsal
from scripts import rehearse_storage_adapter_postgres as pg


@pytest.mark.parametrize('arguments', [[], ['--db', '/private/catalog.sqlite'], ['--dsn', 'postgresql://private:secret@localhost/live'],
                                    ['--run', '--run'], ['--run', '--output', '/private/report'], ['--ru'], ['--seed', '1']])
def test_writer_cli_accepts_no_database_paths_or_connection_settings(arguments, monkeypatch, capsys):
    monkeypatch.setattr(rehearsal, 'rehearse', lambda: pytest.fail('No database for invalid arguments'))
    assert rehearsal.main(arguments) == 2
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {'ok': False, 'profile': rehearsal.PROFILE, 'error': 'invalid_arguments'}
    assert '/private/' not in captured.out and 'secret' not in captured.out


def test_import_and_missing_run_never_start_database_or_subprocess():
    root = Path(__file__).resolve().parents[1]
    code = '''import sys
sys.path.insert(0, sys.argv[1])
def guard(event, args):
    if event in ('sqlite3.connect', 'subprocess.Popen', 'socket.__new__', 'socket.connect'):
        raise AssertionError('No implicit database or process initialization')
sys.addaudithook(guard)
from scripts import rehearse_catalog_writer_postgres as module
raise SystemExit(module.main([]))
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, str(root)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and not result.stderr
    assert json.loads(result.stdout)['error'] == 'invalid_arguments'


def test_driver_refusal_precedes_tools_or_cluster(monkeypatch, capsys):
    def absent(): raise pg.RehearsalError('dependency_unavailable')
    monkeypatch.setattr(pg, '_driver', absent)
    monkeypatch.setattr(pg, '_tools', lambda: pytest.fail('No tools before driver'))
    assert rehearsal.main(['--run']) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'dependency_unavailable'


def test_tools_refusal_does_not_fall_back_to_operating_backend(monkeypatch, capsys):
    monkeypatch.setattr(pg, '_driver', lambda: object())
    def absent(): raise pg.RehearsalError('tools_unavailable')
    monkeypatch.setattr(pg, '_tools', absent)
    monkeypatch.setattr(pg, '_private_cluster', lambda *a: pytest.fail('No implicit fallback'))
    assert rehearsal.main(['--run']) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'tools_unavailable'


@pytest.mark.parametrize('fault', ['empty', 'missing', 'integer', 'false'])
def test_writer_proof_requires_exact_true_invariants(fault, monkeypatch):
    checks = {name: True for name in rehearsal.CHECKS}
    assert checks
    if fault == 'empty': checks = {}
    elif fault == 'missing': checks.pop(next(iter(checks)))
    else: checks[next(iter(checks))] = 1 if fault == 'integer' else False
    @contextmanager
    def cluster(_tools): yield {}
    monkeypatch.setattr(pg, '_driver', lambda: object())
    monkeypatch.setattr(pg, '_tools', lambda: {})
    monkeypatch.setattr(pg, '_private_cluster', cluster)
    monkeypatch.setattr(rehearsal, '_contract_child', lambda *a: {'checks': checks, 'versions': {}})
    with pytest.raises(rehearsal.RehearsalError, match='invariant_failed'):
        rehearsal.rehearse()


def test_child_uses_clean_environment_and_fixed_entry(tmp_path, monkeypatch):
    inherited = {'PGHOST': 'private-host.invalid', 'PGPASSWORD': 'synthetic-private-password', 'PGSERVICE': 'operating-service'}
    for key, value in inherited.items(): monkeypatch.setenv(key, value)
    descriptor = {'socket': str(tmp_path / 'socket'), 'environment': pg._environment(tmp_path)}
    def child(arguments, environment, **kwargs):
        assert not set(inherited) & set(environment)
        assert arguments[-1] == 'from scripts.rehearse_catalog_writer_postgres import _worker_main; raise SystemExit(_worker_main())'
        assert json.loads(kwargs['input']) == {'socket': descriptor['socket']}
        return SimpleNamespace(stdout=json.dumps({'checks': {name: True for name in rehearsal.CHECKS},
            'versions': {'postgresql_version_number': 140022, 'psycopg': '3.3.6'}}), stderr='')
    monkeypatch.setattr(pg, '_run', child)
    result = rehearsal._contract_child(descriptor, SimpleNamespace(__file__='/private/tmp/synthetic-driver/psycopg/__init__.py'))
    assert result['versions']['psycopg'] == '3.3.6'
    assert dict(os.environ).items() >= inherited.items()


def test_actual_sqlite_postgres_writer_and_outbox_contracts(monkeypatch):
    # Missing optional driver/tools is a failed integration, never a skipped
    # or fabricated success. The driver remains in a separate temporary target.
    inherited = {'PGHOST': 'private-host.invalid', 'PGPORT': '1', 'PGDATABASE': 'private-live-catalog',
                 'PGUSER': 'private-live-user', 'PGPASSWORD': 'synthetic-private-password', 'PGSERVICE': 'operating-service',
                 'PGSERVICEFILE': '/private/operating-service', 'PGPASSFILE': '/private/operating-passfile',
                 'PGOPTIONS': '-c invalid_operating_setting=1'}
    for key, value in inherited.items(): monkeypatch.setenv(key, value)
    before = dict(os.environ)
    result = rehearsal.rehearse()
    assert dict(os.environ) == before
    assert result['ok'] is True and result['profile'] == rehearsal.PROFILE
    assert set(result['checks']) == rehearsal.CHECKS and all(value is True for value in result['checks'].values())
    assert result['transport'] == 'private_unix_socket_only' and result['cluster_stopped_and_removed'] is True
    assert result['limits']['search_or_embedding_engine_executed'] is False and result['limits']['application_store_integrated'] is False
    assert result['limits']['production_db_writes'] == result['limits']['provider_calls'] == 0
    assert result['versions']['postgresql_version_number'] >= 140000 and result['elapsed_ms'] >= 0
    rendered = json.dumps(result)
    private_values = [value for key, value in inherited.items() if key != 'PGPORT']
    for marker in (*private_values, '/private/', 'postgresql://', 'Traceback'):
        assert marker not in rendered

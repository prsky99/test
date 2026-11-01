"""Required isolated PostgreSQL parity and catalog rehearsal CLI boundaries."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import rehearse_catalog_repository_postgres as rehearsal
from scripts import rehearse_storage_adapter_postgres as pg


@pytest.mark.parametrize('arguments', [[], ['--db', '/private/catalog.sqlite'], ['--dsn', 'postgresql://private:secret@localhost/live'],
                                    ['--run', '--run'], ['--run', '--output', '/private/report'], ['--ru'], ['--seed', '1']])
def test_catalog_cli_has_no_database_or_output_configuration(arguments, monkeypatch, capsys):
    monkeypatch.setattr(rehearsal, 'rehearse', lambda: pytest.fail('No database for invalid arguments'))
    assert rehearsal.main(arguments) == 2
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {'ok': False, 'profile': rehearsal.PROFILE, 'error': 'invalid_arguments'}
    assert '/private/' not in captured.out and 'secret' not in captured.out


def test_import_and_argument_refusal_do_not_initialize_database_or_subprocess():
    root = Path(__file__).resolve().parents[1]
    code = '''import sys
sys.path.insert(0, sys.argv[1])
def guard(event, args):
    if event in ('sqlite3.connect', 'subprocess.Popen', 'socket.__new__', 'socket.connect'):
        raise AssertionError('Database or process work before explicit execution')
sys.addaudithook(guard)
from scripts import rehearse_catalog_repository_postgres as module
raise SystemExit(module.main([]))
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, str(root)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and not result.stderr
    assert json.loads(result.stdout)['error'] == 'invalid_arguments'


def test_dependency_refusal_is_fixed_and_does_not_start_cluster(monkeypatch, capsys):
    def absent(): raise pg.RehearsalError('dependency_unavailable')
    monkeypatch.setattr(pg, '_driver', absent)
    monkeypatch.setattr(pg, '_tools', lambda: pytest.fail('No tools before driver'))
    assert rehearsal.main(['--run']) == 1
    captured = capsys.readouterr()
    assert not captured.err and json.loads(captured.out)['error'] == 'dependency_unavailable'


def test_tools_refusal_has_no_silent_backend_fallback(monkeypatch, capsys):
    monkeypatch.setattr(pg, '_driver', lambda: object())
    def absent(): raise pg.RehearsalError('tools_unavailable')
    monkeypatch.setattr(pg, '_tools', absent)
    monkeypatch.setattr(pg, '_private_cluster', lambda *a: pytest.fail('No fallback database'))
    assert rehearsal.main(['--run']) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'tools_unavailable'


@pytest.mark.parametrize('fault', ['empty', 'missing', 'integer', 'false'])
def test_catalog_proof_cannot_pass_when_missing_or_nonboolean(fault, monkeypatch):
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


def test_child_environment_contains_no_inherited_pg_credentials(tmp_path, monkeypatch):
    inherited = {'PGHOST': 'private-host.invalid', 'PGPASSWORD': 'synthetic-private-password', 'PGSERVICE': 'operating-service'}
    for key, value in inherited.items(): monkeypatch.setenv(key, value)
    descriptor = {'socket': str(tmp_path / 'socket'), 'environment': pg._environment(tmp_path)}
    observed = []
    def child(arguments, environment, **kwargs):
        observed.append(environment)
        assert arguments[-1] == 'from scripts.rehearse_catalog_repository_postgres import _worker_main; raise SystemExit(_worker_main())'
        assert json.loads(kwargs['input']) == {'socket': descriptor['socket']}
        return SimpleNamespace(stdout=json.dumps({'checks': {name: True for name in rehearsal.CHECKS},
            'versions': {'postgresql_version_number': 140022, 'psycopg': '3.3.6'}}), stderr='')
    monkeypatch.setattr(pg, '_run', child)
    result = rehearsal._contract_child(descriptor, SimpleNamespace(__file__='/private/tmp/synthetic-driver/psycopg/__init__.py'))
    assert result['versions']['psycopg'] == '3.3.6'
    assert observed and not set(inherited) & set(observed[0])
    assert dict(os.environ).items() >= inherited.items()


def test_actual_catalog_repository_contract_matches_sqlite_without_operating_credentials(monkeypatch):
    # Required actual integration; missing optional dependency is a failed
    # rehearsal, not skipped or represented by fake passing evidence.
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
    assert result['limits']['fts_search_parity_established'] is False and result['limits']['application_store_integrated'] is False
    assert result['limits']['production_db_writes'] == result['limits']['provider_calls'] == 0
    assert result['versions']['postgresql_version_number'] >= 140000 and result['elapsed_ms'] >= 0
    rendered = json.dumps(result)
    private_values = [value for key, value in inherited.items() if key != 'PGPORT']
    for marker in (*private_values, '/private/', 'postgresql://', 'Traceback'):
        assert marker not in rendered

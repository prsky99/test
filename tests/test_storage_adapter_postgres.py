"""Disposable PostgreSQL DB-API contracts and clean-environment harness safety."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import rehearse_storage_adapter_postgres as rehearsal


@pytest.mark.parametrize('arguments', [[], ['--db', '/private/credential.sqlite'], ['--dsn', 'postgresql://private:secret@localhost/live'],
                                    ['--run', '--run'], ['--run', '--output', '/private/report'], ['--ru'], ['--seed', '1']])
def test_cli_rejects_paths_connections_ambiguous_flags_and_missing_execution(arguments, monkeypatch, capsys):
    monkeypatch.setattr(rehearsal, 'rehearse', lambda: pytest.fail('No rehearsal for invalid arguments'))
    assert rehearsal.main(arguments) == 2
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == {'ok': False, 'profile': rehearsal.PROFILE, 'error': 'invalid_arguments'}
    assert 'secret' not in output.out and '/private/' not in output.out


def test_missing_driver_fails_without_tools_cluster_or_fallback(monkeypatch, capsys):
    def unavailable(_name):
        raise ImportError('private driver path')
    monkeypatch.setattr(rehearsal.importlib, 'import_module', unavailable)
    monkeypatch.setattr(rehearsal, '_tools', lambda: pytest.fail('No tools before dependency check'))
    assert rehearsal.main(['--run']) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)['error'] == 'dependency_unavailable'
    assert not captured.err and 'private driver path' not in captured.out


def test_missing_tools_fail_without_temporary_cluster(monkeypatch, capsys):
    monkeypatch.setattr(rehearsal, '_driver', lambda: object())
    monkeypatch.setattr(rehearsal.shutil, 'which', lambda *a, **k: None)
    monkeypatch.setattr(rehearsal.tempfile, 'TemporaryDirectory', lambda *a, **k: pytest.fail('No temporary cluster without tools'))
    assert rehearsal.main(['--run']) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'tools_unavailable'


@pytest.mark.parametrize('installation', ['/usr/lib/postgresql/18/bin', '/opt/homebrew/opt/postgresql@18/bin'])
def test_tools_prefer_postgresql18_without_inherited_path(monkeypatch, installation):
    monkeypatch.setenv('PATH', '/private/synthetic-untrusted-tools')
    def which(name, *, path):
        assert '/private/synthetic-untrusted-tools' not in path
        if path in (installation, '/opt/homebrew/bin'):
            return path+'/'+name
    monkeypatch.setattr(rehearsal.shutil, 'which', which)
    assert rehearsal._tools() == {name:installation+'/'+name for name in ('initdb','pg_ctl')}


def test_tools_never_mix_partial_postgresql_installations(monkeypatch):
    def which(name, *, path):
        if path=='/usr/lib/postgresql/18/bin' and name=='initdb':
            return path+'/'+name
        if path=='/usr/lib/postgresql/16/bin':
            return path+'/'+name
    monkeypatch.setattr(rehearsal.shutil,'which',which)
    assert rehearsal._tools() == {name:'/usr/lib/postgresql/16/bin/'+name for name in ('initdb','pg_ctl')}


def test_postgres_environment_never_inherits_operating_connection_or_home_values(tmp_path, monkeypatch):
    inherited = {'HOME': '/private/operating-home', 'PGPASSWORD': 'private-operating-password',
                 'PGSERVICE': 'production', 'PGHOST': 'production.example', 'PGOPTIONS': '-c log_statement=all',
                 'SSL_CERT_FILE': '/private/operating-ca', 'DYLD_LIBRARY_PATH': '/private/libraries'}
    for key, value in inherited.items():
        monkeypatch.setenv(key, value)
    environment = rehearsal._environment(tmp_path)
    assert environment['HOME'] == str(tmp_path / 'home')
    assert set(environment) == {'PATH', 'HOME', 'TMPDIR', 'LC_ALL', 'LANG', 'PGPASSFILE', 'PGSERVICEFILE', 'PGSYSCONFDIR'}
    assert not any(value in environment.values() for value in inherited.values())
    assert dict(os.environ).items() >= inherited.items()
    assert (tmp_path / 'home').stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('start_fails', [False, True])
def test_private_cluster_cleans_after_contract_or_start_failure(monkeypatch, start_fails):
    events = []
    roots = []
    def fake_run(arguments, environment, **kwargs):
        data = Path(arguments[arguments.index('-D') + 1])
        roots.append(data.parent)
        if arguments[0] == 'fixed-initdb':
            assert '--username=postgres' in arguments and '--auth-host=reject' in arguments
            data.mkdir(mode=0o700)
        elif arguments[-1] == 'start':
            assert "listen_addresses=''" in arguments[arguments.index('-o') + 1]
            (data / 'postmaster.pid').write_text('synthetic-private-pid')
            events.append('start')
            if start_fails:
                raise rehearsal.RehearsalError()
        elif arguments[-1] == 'stop':
            (data / 'postmaster.pid').unlink()
            events.append('stop')
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    monkeypatch.setattr(rehearsal, '_run', fake_run)
    with pytest.raises((RuntimeError, rehearsal.RehearsalError)):
        with rehearsal._private_cluster({'initdb': 'fixed-initdb', 'pg_ctl': 'fixed-pgctl'}) as descriptor:
            assert Path(descriptor['socket']).stat().st_mode & 0o077 == 0
            raise RuntimeError('Synthetic failure must clean the cluster')
    assert events == ['start', 'stop']
    assert roots and not any(root.exists() for root in roots)


def test_unconfirmed_postmaster_stop_preserves_private_fixture_until_owned_cleanup(monkeypatch):
    roots = []
    stops = []
    def fake_run(arguments, environment, **kwargs):
        data = Path(arguments[arguments.index('-D') + 1])
        roots.append(data.parent)
        if arguments[0] == 'fixed-initdb':
            data.mkdir(mode=0o700)
            (data / 'synthetic-marker').write_text('Do not delete an unconfirmed cluster')
        elif arguments[-1] == 'start':
            (data / 'postmaster.pid').write_text('synthetic-private-pid')
        elif arguments[-1] == 'stop':
            stops.append(arguments[arguments.index('-m') + 1])
            raise rehearsal.RehearsalError()
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    monkeypatch.setattr(rehearsal, '_run', fake_run)
    try:
        with pytest.raises(rehearsal.RehearsalError, match='rehearsal_failed'):
            with rehearsal._private_cluster({'initdb': 'fixed-initdb', 'pg_ctl': 'fixed-pgctl'}):
                pass
        assert stops == ['fast', 'immediate']
        root = roots[0]
        assert root.is_dir() and root.stat().st_mode & 0o077 == 0
        assert (root / 'data' / 'postmaster.pid').is_file()
        assert (root / 'data' / 'synthetic-marker').read_text() == 'Do not delete an unconfirmed cluster'
    finally:
        # This fake pid never represents a process. Only this test removes the
        # fixture after confirming the preservation contract.
        for root in set(roots):
            rehearsal.shutil.rmtree(root, ignore_errors=True)


def test_fixed_child_receives_only_explicit_clean_environment_and_private_socket(tmp_path, monkeypatch):
    environment = rehearsal._environment(tmp_path)
    descriptor = {'root': str(tmp_path), 'socket': str(tmp_path / 'socket'), 'environment': environment}
    observed = []
    def child(arguments, child_env, **kwargs):
        observed.append((arguments, child_env, kwargs))
        assert '-B' in arguments and arguments[-1].endswith('raise SystemExit(_worker_main())')
        assert set(child_env) == set(environment) | {'PYTHONPATH'}
        assert json.loads(kwargs['input']) == {'socket': descriptor['socket']}
        assert kwargs['timeout'] == 30
        return SimpleNamespace(stdout=json.dumps({'checks': {name: True for name in rehearsal.CHECKS},
                                                  'versions': {'postgresql_version_number': 140022, 'psycopg': '3.3.6'}}), stderr='')
    monkeypatch.setattr(rehearsal, '_run', child)
    result = rehearsal._contract_child(descriptor, SimpleNamespace(__file__='/private/tmp/synthetic-driver/psycopg/__init__.py'))
    assert result['versions']['psycopg'] == '3.3.6' and observed
    assert 'PGPASSWORD' not in observed[0][1] and 'PGSERVICE' not in observed[0][1]


@pytest.mark.parametrize('fault', ['empty', 'missing', 'integer', 'false'])
def test_incomplete_or_nonboolean_contract_cannot_pass(fault, monkeypatch):
    checks = {name: True for name in rehearsal.CHECKS}
    if fault == 'empty': checks = {}
    elif fault == 'missing': checks.pop(next(iter(checks)))
    else: checks[next(iter(checks))] = 1 if fault == 'integer' else False
    @contextmanager
    def cluster(_tools):
        yield {}
    monkeypatch.setattr(rehearsal, '_driver', lambda: object())
    monkeypatch.setattr(rehearsal, '_tools', lambda: {})
    monkeypatch.setattr(rehearsal, '_private_cluster', cluster)
    monkeypatch.setattr(rehearsal, '_contract_child', lambda *a: {'checks': checks, 'versions': {}})
    with pytest.raises(rehearsal.RehearsalError, match='invariant_failed'):
        rehearsal.rehearse()


def test_actual_postgres_adapter_contract_uses_no_operating_credentials(monkeypatch):
    # This is an actual required integration test, not skip-on-missing evidence.
    # Install optional psycopg in a separate temporary target and provide it in
    # PYTHONPATH; the project environment and operating requirements stay intact.
    poisoned = {'PGHOST': 'production.invalid', 'PGPORT': '1', 'PGUSER': 'private-user', 'PGDATABASE': 'private-database',
                'PGPASSWORD': 'synthetic-poison-password', 'PGSERVICE': 'missing-operating-service',
                'PGSERVICEFILE': '/private/absent-operating-service', 'PGPASSFILE': '/private/absent-operating-password',
                'PGOPTIONS': '-c invalid_operating_setting=1'}
    for key, value in poisoned.items():
        monkeypatch.setenv(key, value)
    before = dict(os.environ)
    result = rehearsal.rehearse()
    assert dict(os.environ) == before
    assert result['ok'] is True and result['profile'] == rehearsal.PROFILE
    assert set(result['checks']) == rehearsal.CHECKS and all(value is True for value in result['checks'].values())
    assert result['cluster_stopped_and_removed'] is True and result['transport'] == 'private_unix_socket_only'
    assert result['versions']['postgresql_version_number'] >= 140000
    assert result['limits']['application_store_integrated'] is False and result['limits']['production_cutover'] is False
    assert result['limits']['production_db_writes'] == result['limits']['provider_calls'] == 0
    assert result['elapsed_ms'] >= 0
    serialized = json.dumps(result)
    # The port sentinel "1" is ordinary aggregate/version text, not a private
    # string marker. Only meaningful inherited values can prove disclosure.
    private_values = [value for key, value in poisoned.items() if key != 'PGPORT']
    for marker in (*private_values, '/private/', 'password=', 'postgresql://', 'Traceback', 'adapter_items'):
        assert marker not in serialized

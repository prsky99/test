"""Safety boundaries for the portable synthetic PostgreSQL acceptance command."""
import json
import os

import pytest

from scripts.validate_postgres_acceptance import configuration, private_json, tool_environment


def connection_file(tmp_path, **changes):
    path = tmp_path / 'test-connection.json'
    path.write_text(json.dumps({'host': 'db.example.invalid', 'port': 5432,
                               'user': 'acceptance', 'dbname': 'postgres',
                               'sslmode': 'verify-full', **changes}))
    path.chmod(0o600)
    return path


@pytest.mark.parametrize('mode', [0o644, 0o640, 0o604])
def test_shared_connection_files_are_refused_before_connect(tmp_path, mode):
    path = connection_file(tmp_path)
    path.chmod(mode)
    with pytest.raises(AssertionError):
        configuration(path)


@pytest.mark.parametrize('mode', ['disable', 'allow', 'prefer', 'require', 'verify-ca'])
def test_remote_test_database_requires_hostname_verified_tls(tmp_path, mode):
    with pytest.raises(AssertionError):
        configuration(connection_file(tmp_path, sslmode=mode))


@pytest.mark.parametrize('change', [{'port': True}, {'port': 0}, {'port': 65536},
                                   {'options': '-c search_path=public'}, {'host': ''},
                                   {'password': ['not-a-string']}, {'target_database': 'operating'}])
def test_no_arbitrary_connection_options_or_existing_write_target(tmp_path, change):
    with pytest.raises(AssertionError):
        configuration(connection_file(tmp_path, **change))


def test_owner_file_symlink_is_refused_and_private_result_cannot_overwrite(tmp_path):
    path = connection_file(tmp_path)
    linked = tmp_path / 'linked.json'
    linked.symlink_to(path)
    with pytest.raises(OSError):
        configuration(linked)
    result = tmp_path / 'result.json'
    private_json(result, {'synthetic': True})
    assert result.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        private_json(result, {'synthetic': False})
    assert json.loads(result.read_text()) == {'synthetic': True}


def test_subprocess_uses_exact_test_target_without_inherited_libpq_options(tmp_path, monkeypatch):
    monkeypatch.setenv('PGHOST', 'operating.invalid')
    monkeypatch.setenv('PGOPTIONS', '-c search_path=operating')
    monkeypatch.setenv('PGSERVICE', 'operating')
    monkeypatch.setenv('PGPASSWORD', 'must-not-leak')
    config = configuration(connection_file(tmp_path))
    env = tool_environment(config, 'ac_validation_synthetic')
    assert env['PGHOST'] == 'db.example.invalid'
    assert env['PGDATABASE'] == 'ac_validation_synthetic'
    assert env['PGSSLMODE'] == 'verify-full'
    assert env['PGPASSFILE'] == os.devnull
    assert not any(key in env for key in ('PGOPTIONS', 'PGSERVICE', 'PGPASSWORD'))

"""Private configuration checks never execute values or mutate a database."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts.agentcon_config import ConfigError, ReadonlyStore, read_settings, read_edge_gateway_settings

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/agentcon_config.py'


def private_file(tmp_path, content, mode=0o600):
    path = tmp_path / 'settings.env'
    path.write_text(content)
    path.chmod(mode)
    return path


def run_check(path=None, *, action='--check', overrides=None, cwd=None):
    # Only a clean, synthetic process environment reaches the validator.
    env = {'PATH': os.environ.get('PATH', ''), 'DEPLOYMENT_MODE': 'test',
           'GATEWAY_DB': ':memory:', 'SCHEDULER': '0', 'CONCIERGE_LLM': 'off'}
    for key, value in (overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    args = [sys.executable, str(SCRIPT), action]
    if path is not None:
        args.extend(['--env-file', str(path)])
    return subprocess.run(args, env=env, cwd=cwd, capture_output=True, text=True, timeout=15)


def production_environment(db):
    return {'DEPLOYMENT_MODE': 'production', 'GATEWAY_DB': str(db),
            'ADMIN_TOKEN': 'synthetic-token-placeholder-' + 'a' * 40,
            'ADMIN_BOOTSTRAP_PASSWORD': 'synthetic-bootstrap-placeholder',
            'AGENT_FRONT_URL': 'https://public.example.invalid',
            'PUBLIC_TLS_TERMINATION': 'proxy', 'SSL_ENABLED': '0',
            'ALLOW_PRIVATE_AGENT_URLS': '0', 'FORWARDED_ALLOW_IPS': '127.0.0.1'}


def existing_database(path, password='synthetic-changed-password'):
    from agent_market.gateway.admin_auth import hash_password
    hashed, salt = hash_password(password)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE admin_users(username TEXT,password_hash TEXT,salt TEXT,active INTEGER)')
        db.execute('INSERT INTO admin_users VALUES (?,?,?,1)', ('sadmin', hashed, salt))
    return path


def test_literal_export_preserves_values_and_inherited_environment_wins(tmp_path):
    path = private_file(tmp_path, '# private settings\nHOST=127.0.0.1\nADMIN_TOKEN=literal$VALUE#suffix\nPORT=8300\n')
    result = run_check(path, action='--export', overrides={'PORT': '8401'})
    assert result.returncode == 0 and result.stderr == ''
    assert result.stdout.splitlines() == ['HOST=127.0.0.1', 'ADMIN_TOKEN=literal$VALUE#suffix']
    inherited_empty = run_check(path, action='--export', overrides={'ADMIN_TOKEN': ''})
    assert 'ADMIN_TOKEN=' not in inherited_empty.stdout


@pytest.mark.parametrize('mode', [0o400, 0o600])
def test_private_owner_modes_are_supported(tmp_path, mode):
    assert read_settings(private_file(tmp_path, 'PORT=8300\n', mode)) == {'PORT': '8300'}


def test_edge_delivery_settings_are_literal_private_file_references(tmp_path):
    values = {'AGENT_EDGE_GATEWAY_CONFIG': '/private/config/edge.json',
              'AGENT_EDGE_CLOUDFLARE_ACCOUNT': 'a' * 32,
              'AGENT_EDGE_CLOUDFLARE_TOKEN_FILE': '/private/config/analytics.token'}
    path = private_file(tmp_path, ''.join(key + '=' + value + '\n' for key, value in values.items()))
    assert read_settings(path) == values
    assert read_edge_gateway_settings(path) == values
    with pytest.raises(ConfigError):
        read_edge_gateway_settings(private_file(tmp_path, 'ADMIN_TOKEN=not-an-edge-setting\n'))


def test_identity_settings_are_supported_without_database_or_secret_output(tmp_path):
    values = {
        'GOOGLE_OIDC_CLIENT_ID': 'synthetic-client.apps.googleusercontent.com',
        'GOOGLE_OIDC_CLIENT_SECRET': 'synthetic-google-private',
        'GOOGLE_OIDC_REDIRECT_URI': 'https://customer.example.invalid/api/customer-auth/callback',
        'GITHUB_OAUTH_CLIENT_ID': 'synthetic-github-client',
        'GITHUB_OAUTH_CLIENT_SECRET': 'synthetic-github-private',
        'GITHUB_OAUTH_REDIRECT_URI': 'https://customer.example.invalid/api/customer-auth/github/callback',
    }
    path = private_file(tmp_path, ''.join(key + '=' + value + '\n' for key, value in values.items()))
    result = run_check(path, action='--identity-check', cwd=tmp_path,
                       overrides={'GATEWAY_DB': '/unavailable/never-open.sqlite'})
    assert result.returncode == 0
    assert json.loads(result.stdout) == {'google_configured': True, 'github_configured': True}
    assert all(value not in result.stdout + result.stderr for value in values.values())
    assert sorted(item.name for item in tmp_path.iterdir()) == ['settings.env']


@pytest.mark.parametrize('content', [
    'GOOGLE_OIDC_CLIENT_ID=synthetic-client.apps.googleusercontent.com\n',
    'GITHUB_OAUTH_CLIENT_ID=synthetic-client\nGITHUB_OAUTH_CLIENT_SECRET=private-placeholder\nGITHUB_OAUTH_REDIRECT_URI=http://127.0.0.1/callback\n',
])
def test_partial_or_unsafe_identity_settings_fail_closed_without_values(tmp_path, content):
    result = run_check(private_file(tmp_path, content), action='--identity-check')
    assert result.returncode == 1 and result.stdout == ''
    assert 'private-placeholder' not in result.stderr and 'synthetic-client' not in result.stderr


def test_file_owner_must_match_current_user(tmp_path, monkeypatch):
    path = private_file(tmp_path, 'PORT=8300\n')
    uid = os.getuid()
    monkeypatch.setattr('scripts.agentcon_config.os.getuid', lambda: uid + 1)
    with pytest.raises(ConfigError):
        read_settings(path)


@pytest.mark.parametrize('mode', [0o644, 0o640, 0o660, 0o700, 0o000])
def test_nonprivate_or_unsupported_owner_modes_fail_without_values(tmp_path, mode):
    result = run_check(private_file(tmp_path, 'ADMIN_TOKEN=private-review-placeholder\n', mode), action='--export')
    assert result.returncode == 1 and not result.stdout
    assert 'private-review-placeholder' not in result.stderr


def test_symlink_and_nonregular_settings_are_rejected(tmp_path):
    target = private_file(tmp_path, 'PORT=8300\n')
    link = tmp_path / 'linked.env'
    link.symlink_to(target)
    with pytest.raises(ConfigError):
        read_settings(link)
    with pytest.raises(ConfigError):
        read_settings(tmp_path)
    fifo = tmp_path / 'fifo.env'
    os.mkfifo(fifo, 0o600)
    result = run_check(fifo, action='--export')
    assert result.returncode == 1


@pytest.mark.parametrize('content', [
    'UNKNOWN=private-review-placeholder\n',
    'ADMIN_TOKEN=private-review-placeholder\nADMIN_TOKEN=duplicate\n',
    'ADMIN_TOKEN private-review-placeholder\n',
    'ADMIN_TOKEN=private-review-placeholder\x00\n',
    'ADMIN_TOKEN="private-review-placeholder"\n',
    'ADMIN_TOKEN=private-review-placeholder\t\n',
    'ADMIN_TOKEN=private-review-placeholder\u202e\n',
])
def test_invalid_file_fails_atomically_without_secret_output(tmp_path, content):
    result = run_check(private_file(tmp_path, content), action='--export')
    assert result.returncode == 1 and result.stdout == ''
    assert 'private-review-placeholder' not in result.stderr


def test_literal_command_substitution_is_never_executed(tmp_path):
    marker = tmp_path / 'must-not-exist'
    value = f'$(touch {marker})`touch {marker}`'
    path = private_file(tmp_path, f'ADMIN_TOKEN={value}\n')
    result = run_check(path, action='--export')
    assert result.returncode == 0 and result.stdout == f'ADMIN_TOKEN={value}\n'
    assert not marker.exists()
    # Validation also uses the literal data rather than executing it.
    checked = run_check(path)
    assert checked.returncode == 0 and not marker.exists()
    assert value not in checked.stdout + checked.stderr


@pytest.mark.parametrize('path_kind', ['omitted', 'empty', 'missing'])
def test_optional_missing_file_checks_environment_only(tmp_path, path_kind):
    path = None if path_kind == 'omitted' else '' if path_kind == 'empty' else tmp_path / 'missing.env'
    result = run_check(path, cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)['database'] == 'new'
    assert not (tmp_path / 'missing.env').exists()


def test_successful_existing_production_check_is_readonly_and_sanitized(tmp_path):
    db = existing_database(tmp_path / 'existing.sqlite3')
    before = (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns, sorted(p.name for p in tmp_path.iterdir()))
    result = run_check(overrides=production_environment(db), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {'ok': True, 'database': 'existing', 'production_guards_checked': True,
                    'private_destinations_disabled': True, 'proxy_tls': True}
    after = (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns, sorted(p.name for p in tmp_path.iterdir()))
    assert before == after
    assert 'synthetic-' not in result.stdout + result.stderr
    assert str(db) not in result.stdout + result.stderr


def test_check_uses_file_defaults_but_inherited_values_take_precedence(tmp_path):
    settings = production_environment(tmp_path / 'new.sqlite3')
    settings['PORT'] = '0'
    path = private_file(tmp_path, ''.join(f'{key}={value}\n' for key, value in settings.items()))
    result = run_check(path, overrides={'DEPLOYMENT_MODE': None, 'GATEWAY_DB': None, 'PORT': '8345'})
    assert result.returncode == 0
    assert json.loads(result.stdout)['production_guards_checked'] is True
    rejected = run_check(path, overrides={'DEPLOYMENT_MODE': None, 'GATEWAY_DB': None})
    assert rejected.returncode == 1 and rejected.stdout == ''
    assert 'synthetic-' not in rejected.stderr


def test_readonly_facade_rejects_writes(tmp_path):
    db = existing_database(tmp_path / 'existing.sqlite3')
    facade = ReadonlyStore(db)
    try:
        assert facade.query('PRAGMA query_only')[0][0] == 1
        with pytest.raises(sqlite3.OperationalError):
            facade.query('DELETE FROM admin_users')
    finally:
        facade.close()


def test_new_production_check_never_creates_database_or_parent(tmp_path):
    db = tmp_path / 'uncreated-parent' / 'new.sqlite3'
    result = run_check(overrides=production_environment(db))
    assert result.returncode == 0 and json.loads(result.stdout)['database'] == 'new'
    assert not db.parent.exists()
    result = run_check(overrides={**production_environment(db), 'ADMIN_BOOTSTRAP_PASSWORD': ''})
    assert result.returncode == 1 and not db.parent.exists()


def test_existing_default_password_is_rejected_without_changing_it(tmp_path):
    db = existing_database(tmp_path / 'existing.sqlite3', password='sadmin')
    before = db.read_bytes()
    result = run_check(overrides=production_environment(db))
    assert result.returncode == 1 and result.stdout == ''
    assert 'Default administrator credentials' in result.stderr
    assert db.read_bytes() == before
    assert 'synthetic-' not in result.stderr


def test_existing_database_without_default_account_requires_bootstrap_without_creating_it(tmp_path):
    db = existing_database(tmp_path / 'existing.sqlite3')
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE admin_users SET username='other-administrator'")
    before = db.read_bytes()
    result = run_check(overrides={**production_environment(db), 'ADMIN_BOOTSTRAP_PASSWORD': ''})
    assert result.returncode == 1 and result.stdout == ''
    assert 'bootstrap password' in result.stderr and db.read_bytes() == before
    result = run_check(overrides=production_environment(db))
    assert result.returncode == 0 and db.read_bytes() == before
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM admin_users WHERE username='sadmin'").fetchone()[0] == 0


def test_invalid_development_proxy_configuration_is_also_rejected():
    result = run_check(overrides={'DEPLOYMENT_MODE': 'development', 'FORWARDED_ALLOW_IPS': '*'})
    assert result.returncode == 1 and result.stdout == ''
    assert 'Trusted ingress configuration is invalid' in result.stderr
    assert '*' not in result.stderr


@pytest.mark.parametrize('override', [
    {'ADMIN_TOKEN': 'short-private-placeholder'}, {'AGENT_FRONT_URL': 'http://invalid.example'},
    {'ALLOW_PRIVATE_AGENT_URLS': '1'}, {'SSL_ENABLED': '1'},
    {'FORWARDED_ALLOW_IPS': '*'}, {'DEPLOYMENT_MODE': 'production-typo'},
    {'PORT': '0'}, {'PORT': '65536'}, {'PORT': 'private-review-placeholder'},
    {'AGENT_FRONT_PORT': '-1'}, {'AGENT_FRONT_PORT': '65536'},
])
def test_invalid_production_settings_fail_without_values(tmp_path, override):
    result = run_check(overrides={**production_environment(tmp_path / 'new.sqlite3'), **override})
    assert result.returncode == 1 and result.stdout == ''
    assert 'private-placeholder' not in result.stderr and 'private-review-placeholder' not in result.stderr
    assert not (tmp_path / 'new.sqlite3').exists()


def test_export_does_not_run_production_guards(tmp_path):
    path = private_file(tmp_path, 'DEPLOYMENT_MODE=production\nADMIN_TOKEN=short\n')
    result = run_check(path, action='--export', overrides={'DEPLOYMENT_MODE': 'production'})
    assert result.returncode == 0 and result.stdout == 'ADMIN_TOKEN=short\n'


def test_cli_modes_are_exclusive_and_errors_do_not_echo_arguments():
    result = subprocess.run([sys.executable, str(SCRIPT), '--export', '--check', 'private-review-placeholder'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1 and not result.stdout
    assert 'private-review-placeholder' not in result.stderr

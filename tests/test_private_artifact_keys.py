"""Synthetic key rotation and backup authentication; no operating key material."""
import base64
import copy
import json
import os
import sqlite3
import time

import pytest

from agent_market.private_artifact_keys import ArtifactKeys, ArtifactSigner, ArtifactCipher, ArtifactKeyError, ENV, PROFILE
from agent_market.workflow_backup import backup, restore


def config(active='new', *, revoked=(), legacy=False):
    return {'profile': PROFILE, 'active_signing': active, 'active_encryption': active, 'allow_legacy': legacy,
            'keys': [{'id': identity, 'key': base64.b64encode(bytes([index]) * 32).decode(),
                      'verify_until': time.time() + 3600, 'revoked': identity in revoked}
                     for index, identity in enumerate(('old', 'new'), 1)]}


def configure(tmp_path, monkeypatch, value=None):
    path = tmp_path / 'private-keyring.json'
    path.write_text(json.dumps(value or config()))
    path.chmod(0o600)
    monkeypatch.setenv(ENV, str(path))
    return path


def test_versioned_signatures_previous_key_window_revocation_and_purpose():
    value = {'resource': 17, 'revision': 2}
    old = ArtifactSigner(b'l' * 32, 'test-purpose', ArtifactKeys(config('old'))).sign(value)
    assert old.startswith('ak1.old.')
    current = ArtifactSigner(b'l' * 32, 'test-purpose', ArtifactKeys(config()))
    assert current.verify(value, old) and current.sign(value).startswith('ak1.new.')
    assert not current.verify({**value, 'revision': 3}, old)
    assert not ArtifactSigner(b'l' * 32, 'other-purpose', current.keys).verify(value, old)
    revoked = ArtifactSigner(b'l' * 32, 'test-purpose', ArtifactKeys(config(revoked=('old',))))
    assert not revoked.verify(value, old)
    expired = config(); expired['keys'][0]['verify_until'] = 1
    assert not ArtifactSigner(b'l' * 32, 'test-purpose', ArtifactKeys(expired)).verify(value, old)


def test_legacy_signature_requires_explicit_migration_permission(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    signature = ArtifactSigner(b'l' * 32, 'purpose').sign({'a': 1})
    assert len(signature) == 64
    assert not ArtifactSigner(b'l' * 32, 'purpose', ArtifactKeys(config())).verify({'a': 1}, signature)
    assert ArtifactSigner(b'l' * 32, 'purpose', ArtifactKeys(config(legacy=True))).verify({'a': 1}, signature)


def test_cipher_authenticates_identity_context_and_previous_key():
    context = {'workspace_id': 'synthetic', 'run_id': 'run-1'}
    old = ArtifactCipher('retained-output', ArtifactKeys(config('old')))
    encoded = old.seal(b'private retained output', context)
    assert b'private retained output' not in encoded
    current = ArtifactCipher('retained-output', ArtifactKeys(config()))
    assert current.open(encoded, context) == b'private retained output'
    assert old.seal(b'private retained output', context) != encoded
    for cipher, aad in ((current, {**context, 'run_id': 'run-2'}),
                        (ArtifactCipher('other-purpose', current.keys), context),
                        (ArtifactCipher('retained-output', ArtifactKeys(config(revoked=('old',)))), context)):
        with pytest.raises(ArtifactKeyError): cipher.open(encoded, aad)
    changed = json.loads(encoded); changed['ciphertext'] = changed['ciphertext'][:-4] + 'AAAA'
    with pytest.raises(ArtifactKeyError): current.open(json.dumps(changed).encode(), context)


@pytest.mark.parametrize('fault', ['duplicate_id', 'short_key', 'revoked_active', 'expired_active', 'nan', 'extra', 'missing'])
def test_invalid_config_denies_instead_of_plaintext_fallback(fault):
    value = config()
    if fault == 'duplicate_id': value['keys'][0]['id'] = 'new'
    elif fault == 'short_key': value['keys'][0]['key'] = base64.b64encode(b'short').decode()
    elif fault == 'revoked_active': value['keys'][1]['revoked'] = True
    elif fault == 'expired_active': value['keys'][1]['verify_until'] = 1
    elif fault == 'nan': value['keys'][1]['verify_until'] = float('nan')
    elif fault == 'extra': value['debug'] = True
    else: value.pop('allow_legacy')
    with pytest.raises(ArtifactKeyError): ArtifactKeys(value)


def test_keyring_file_permissions_symlink_and_duplicate_json_fail_closed(tmp_path, monkeypatch):
    path = configure(tmp_path, monkeypatch)
    assert ArtifactKeys().summary()['authenticated_encryption']
    path.chmod(0o644)
    with pytest.raises(ArtifactKeyError): ArtifactKeys()
    path.chmod(0o600)
    link = tmp_path / 'symlink'; link.symlink_to(path); monkeypatch.setenv(ENV, str(link))
    with pytest.raises(OSError): ArtifactKeys()
    monkeypatch.setenv(ENV, str(path)); path.write_text('{"profile":1,"profile":2}')
    with pytest.raises(ArtifactKeyError): ArtifactKeys()


def test_encryption_is_explicit_and_missing_key_denies(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    with pytest.raises(ArtifactKeyError): ArtifactCipher('purpose').seal(b'private', {'id': 1})
    source = tmp_path / 'source.db'
    with sqlite3.connect(source) as db: db.execute('CREATE TABLE marker(value TEXT)')
    destination = tmp_path / 'backup'
    with pytest.raises(ArtifactKeyError): backup(source, destination, encrypt=True)
    assert not destination.exists()


def test_encrypted_backup_authentication_restore_quarantine_and_key_rotation(tmp_path, monkeypatch):
    path = configure(tmp_path, monkeypatch, config('old'))
    source = tmp_path / 'source.db'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE marker(value TEXT)'); db.execute('INSERT INTO marker VALUES(?)', ('private output marker',))
        db.execute('CREATE TABLE execution_controls(id INTEGER PRIMARY KEY,invoke_enabled INTEGER,workflow_enabled INTEGER,delivery_enabled INTEGER,revision INTEGER,updated REAL)')
        db.execute('INSERT INTO execution_controls VALUES(1,1,1,1,1,0)')
    source.with_name(source.name + '.updates-key').write_bytes(b's' * 32)
    directory = tmp_path / 'backup'; manifest = backup(source, directory, encrypt=True, retention_days=14)
    assert manifest['encrypted'] and manifest['retention_days'] == 14 and not manifest['automatic_deletion']
    assert not (directory / 'catalog.sqlite3').exists() and not (directory / 'updates-key').exists()
    assert b'private output marker' not in (directory / 'catalog.sqlite3.sealed').read_bytes()
    assert all(item.stat().st_mode & 0o777 == 0o600 for item in directory.iterdir())
    path.write_text(json.dumps(config()))
    target = tmp_path / 'restored.db'; result = restore(directory, target)
    assert result['authenticated_encryption'] and result['manifest_authenticated']
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT value FROM marker').fetchone()[0] == 'private output marker'
        assert db.execute('SELECT invoke_enabled FROM execution_controls').fetchone()[0] == 0
    path.write_text(json.dumps(config(revoked=('old',))))
    with pytest.raises(ValueError): restore(directory, tmp_path / 'revoked.db')
    assert not (tmp_path / 'revoked.db').exists()


def test_backup_manifest_or_ciphertext_tamper_creates_no_restore_artifact(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    source = tmp_path / 'source.db'
    with sqlite3.connect(source) as db: db.execute('CREATE TABLE marker(value TEXT)')
    directory = tmp_path / 'backup'; backup(source, directory, encrypt=True)
    manifest_path = directory / 'manifest.json'; original = manifest_path.read_bytes()
    changed = json.loads(original); changed['retention_days'] = 365
    manifest_path.write_text(json.dumps(changed))
    target = tmp_path / 'refused.db'
    with pytest.raises(ValueError): restore(directory, target)
    assert not target.exists()
    manifest_path.write_bytes(original)
    (directory / 'catalog.sqlite3.sealed').write_bytes(b'tampered')
    with pytest.raises(ValueError): restore(directory, target)
    assert not target.exists()


def test_encrypted_snapshot_failure_removes_only_new_partial_artifacts(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    import agent_market.workflow_backup as module
    source = tmp_path / 'source.db'
    with sqlite3.connect(source) as db: db.execute('CREATE TABLE marker(value TEXT)')
    def fail(*args): raise ValueError('Synthetic snapshot failure')
    monkeypatch.setattr(module, 'copy_database', fail)
    destination = tmp_path / 'new-backup'
    with pytest.raises(ValueError): backup(source, destination, encrypt=True)
    assert not destination.exists()
    existing = tmp_path / 'existing'; existing.mkdir(); (existing / 'keep').write_text('operator file')
    with pytest.raises(FileExistsError): backup(source, existing, encrypt=True)
    assert (existing / 'keep').read_text() == 'operator file'

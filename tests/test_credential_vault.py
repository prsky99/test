"""Storage encryption, safe migration and fail-closed key handling."""
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_market.credential_vault import CredentialVault, PREFIX
from agent_market.gateway.store import Store


def test_credentials_encrypted_and_reopen_compatible(tmp_path):
    path=str(tmp_path/'credentials.db');store=Store(path)
    store.set_credential('WORKFLOW_KEY','abc-secret-value-1234','test')
    raw=store.query('SELECT key_value FROM platform_credentials')[0]['key_value']
    assert raw.startswith(PREFIX) and 'abc-secret' not in raw
    assert store.get_credential('WORKFLOW_KEY')=='abc-secret-value-1234'
    entry=store.list_credentials()[0]
    assert entry['masked_value']=='abc...1234' and entry['has_value']
    assert 'secret-value' not in str(entry)
    assert os.stat(path+'.credentials-key').st_mode & 0o777==0o600
    store._db.close()
    reopened=Store(path)
    assert reopened.get_credential('WORKFLOW_KEY')=='abc-secret-value-1234'
    reopened._db.close()


def test_existing_plaintext_migrates_without_changing_metadata(tmp_path):
    path=str(tmp_path/'legacy.db');store=Store(path)
    with store.tx() as db:db.execute('INSERT INTO platform_credentials(key_name,key_value,provider,description,updated_at) VALUES (?,?,?,?,?)',('LEGACY_KEY','legacy-private-value','legacy','Keep metadata',123))
    store._db.close();reopened=Store(path)
    assert reopened.get_credential('LEGACY_KEY')=='legacy-private-value'
    row=reopened.query('SELECT * FROM platform_credentials')[0]
    assert row['key_value'].startswith(PREFIX) and row['description']=='Keep metadata' and row['updated_at']==123
    reopened._db.close()


def test_ciphertext_tamper_and_key_name_swap_fail_closed(tmp_path):
    vault=CredentialVault(str(tmp_path/'vault.db'))
    value=vault.seal('FIRST','secret')
    with pytest.raises(ValueError):vault.open('SECOND',value)
    altered=value[:-4]+'AAAA'
    with pytest.raises(ValueError):vault.open('FIRST',altered)
    with pytest.raises(ValueError):vault.open('FIRST','plaintext')


def test_atomic_key_creation_is_shared_between_workers(tmp_path):
    path=str(tmp_path/'shared.db')
    with ThreadPoolExecutor(max_workers=4) as pool:keys=list(pool.map(lambda _:CredentialVault(path).key,range(12)))
    assert len(set(keys))==1
    assert not list(tmp_path.glob('.credential-key-*'))


def test_invalid_key_permissions_and_symlinks_are_rejected(tmp_path):
    path=str(tmp_path/'private.db');key=tmp_path/'private.db.credentials-key'
    key.write_bytes(b'x'*32);key.chmod(0o644)
    with pytest.raises(ValueError):CredentialVault(path)
    key.unlink();target=tmp_path/'other';target.write_bytes(b'x'*32);target.chmod(0o600);key.symlink_to(target)
    with pytest.raises(OSError):CredentialVault(path)


def test_lost_key_does_not_overwrite_ciphertext(tmp_path):
    path=str(tmp_path/'lost.db');store=Store(path);store.set_credential('KEY','sensitive','test')
    before=store.query('SELECT key_value FROM platform_credentials')[0]['key_value'];store._db.close()
    (tmp_path/'lost.db.credentials-key').write_bytes(b'wrong-key-contents'.ljust(32,b'_'))
    with pytest.raises(ValueError):Store(path)
    with sqlite3.connect(path) as db:assert db.execute('SELECT key_value FROM platform_credentials').fetchone()[0]==before

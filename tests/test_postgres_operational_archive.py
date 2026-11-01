"""Credential, ownership and reapproval boundaries without operating access."""
from dataclasses import replace
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from agent_market.postgres_archive_provider import (
    ArchiveProviderDenied, ArchiveCredential, DatabaseIdentity,
    ExplicitArchiveCredentialProvider, tool_environment, verify_connection,
)
from agent_market.postgres_restore_guard import RestoreOwnerAuthority, RestoreGateDenied


def identity():
    return DatabaseIdentity('/private/tmp/synthetic-owned-socket', 55447, 'postgres', 'postgres', '123456789', 1)


@pytest.mark.parametrize('changes', [dict(host='postgresql://private.invalid/database'), dict(port=True),
    dict(database='postgres;DROP DATABASE'), dict(user='user\npassword'), dict(system_identifier='not-a-cluster'),
    dict(database_oid=0), dict(host='db.example', host_address=None), dict(host='/private/socket', host_address='127.0.0.1')])
def test_invalid_explicit_identity_cannot_become_a_tool_destination(changes):
    with pytest.raises(ArchiveProviderDenied): replace(identity(), **changes).validate()


@pytest.mark.parametrize('purpose,expiry', [('other', 100), ('backup', -1), ('restore', 1000)])
def test_explicit_credential_purpose_and_expiry_are_bounded(purpose, expiry):
    lease = ArchiveCredential(identity(), purpose, time.time() + expiry, 'synthetic-private-password')
    with pytest.raises(ArchiveProviderDenied): lease.consume(identity(), purpose)
    assert 'synthetic-private-password' not in repr(lease)


def test_credential_provider_refuses_reuse_wrong_identity_and_hidden_factory_failure():
    current = identity(); lease = ArchiveCredential(current, 'backup', time.time() + 60)
    provider = ExplicitArchiveCredentialProvider(lambda *_: lease)
    assert provider.obtain(current, 'backup') is lease
    with pytest.raises(ArchiveProviderDenied): provider.obtain(current, 'backup')
    with pytest.raises(ArchiveProviderDenied): ArchiveCredential(current, 'backup', time.time()+60).consume(replace(current, database='other'), 'backup')
    def unavailable(*_): raise RuntimeError('synthetic-private-password')
    with pytest.raises(ArchiveProviderDenied) as caught: ExplicitArchiveCredentialProvider(unavailable).obtain(current, 'backup')
    assert 'synthetic-private-password' not in str(caught.value)


def test_tool_credentials_are_owner_only_temporary_bound_and_scrubbed(monkeypatch):
    monkeypatch.setenv('PGPASSWORD', 'parent-secret')
    monkeypatch.setenv('PGSERVICE', 'operating-service')
    lease = ArchiveCredential(identity(), 'backup', time.time() + 60, 'synthetic:password\\value').consume(identity(), 'backup')
    with tool_environment(lease) as (environment, root):
        password_file = Path(environment['PGPASSFILE'])
        assert root.stat().st_mode & 0o777 == 0o700
        assert password_file.stat().st_mode & 0o777 == 0o600
        assert 'synthetic\\:password\\\\value' in password_file.read_text()
        assert environment['PGSSLMODE'] == 'disable'
        assert not any(name in environment for name in ('PGPASSWORD','PGSERVICE','AGENT_PRIVATE_ARTIFACT_KEYRING'))
        assert all('synthetic' not in value for value in environment.values())
    assert not root.exists() and lease.password is None


def test_existing_connection_identity_mismatch_refuses_before_query():
    class NoCursor:
        autocommit = True
        info = SimpleNamespace(transaction_status=0, host='/different/socket', port=55447, dbname='postgres', user='postgres')
        def cursor(self, **_): pytest.fail('Wrong identity queried server')
    with pytest.raises(ArchiveProviderDenied, match='identity_mismatch'): verify_connection(NoCursor(), identity())


@pytest.mark.parametrize('change',[None,'sslmode','certificate','transport','address'])
def test_tcp_connection_requires_pinned_address_and_verify_full_policy(tmp_path, change):
    certificate=tmp_path/'fixture-ca.pem'; certificate.write_text('Synthetic public root certificate')
    current=DatabaseIdentity('db.example',5432,'postgres','postgres','123456789',42,'192.0.2.10',str(certificate))
    parameters={'sslmode':'verify-full','sslrootcert':str(certificate)}
    if change=='sslmode': parameters['sslmode']='require'
    if change=='certificate': parameters['sslrootcert']='/different/ca.pem'
    class Cursor:
        def __enter__(self): return self
        def __exit__(self,*_args): pass
        def execute(self,*_args): pass
        def fetchone(self): return ('123456789',42,'postgres','postgres','192.0.2.10',5432)
    connection=SimpleNamespace(autocommit=True,
        info=SimpleNamespace(transaction_status=0,host='db.example',port=5432,dbname='postgres',user='postgres',
            hostaddr='192.0.2.11' if change=='address' else '192.0.2.10',get_parameters=lambda:parameters),
        pgconn=SimpleNamespace(ssl_in_use=change!='transport'),cursor=lambda **_:Cursor())
    if change is None: assert verify_connection(connection,current)==current.fingerprint()
    else:
        with pytest.raises(ArchiveProviderDenied,match='identity_mismatch'): verify_connection(connection,current)


def test_current_owner_authority_requires_fresh_live_independent_proof():
    live = {'active': True}
    authority = RestoreOwnerAuthority(b'o'*32, verifier=lambda review, proof: 'current-external-owner' if live['active'] and proof == 'synthetic-proof' else None)
    review = {'generation':'pgr_synthetic','revision':2,'challenge':'new-random-value'}
    receipt = authority.issue(review, 'synthetic-proof')
    assert authority.verify(review, receipt, 'synthetic-proof')
    with pytest.raises(RestoreGateDenied): authority.verify({**review,'revision':3}, receipt, 'synthetic-proof')
    with pytest.raises(RestoreGateDenied): authority.verify(review, receipt, 'old-restore-session')
    live['active'] = False
    with pytest.raises(RestoreGateDenied): authority.verify(review, receipt, 'synthetic-proof')


def test_external_owner_verifier_failure_does_not_expose_private_details():
    def fail(*_args): raise RuntimeError('synthetic-private-owner-token')
    authority = RestoreOwnerAuthority(b'o'*32, verifier=fail)
    with pytest.raises(RestoreGateDenied) as caught: authority.issue({'challenge':'new'}, 'private-proof')
    assert str(caught.value) == 'current_owner_proof_required'


def test_owner_receipt_expiring_during_external_recheck_cannot_be_approved(monkeypatch):
    now=time.time(); clock=[now]
    authority=RestoreOwnerAuthority(b'o'*32,verifier=lambda *_:'current-owner')
    review={'generation':'fresh','challenge':'one-use'}
    receipt=authority.issue(review,'proof')
    def verifier(*_): clock[0]=now+301; return 'current-owner'
    authority.verifier=verifier
    monkeypatch.setattr('agent_market.postgres_restore_guard.time.time',lambda:clock[0])
    with pytest.raises(RestoreGateDenied,match='current_owner_proof_required'):
        authority.verify(review,receipt,'proof')


def test_single_use_credential_lease_cannot_be_dispatched_twice():
    current=identity(); lease=ArchiveCredential(current,'backup',time.time()+60).consume(current,'backup')
    with tool_environment(lease): pass
    with pytest.raises(ArchiveProviderDenied,match='archive_credential_replayed'):
        with tool_environment(lease): pytest.fail('Replayed tool credential was opened')


def test_general_archive_cli_or_implicit_provider_is_not_inferred(monkeypatch, tmp_path):
    from agent_market.postgres_operational_archive import _credential, OperationalArchiveDenied
    with pytest.raises(OperationalArchiveDenied, match='explicit_archive_credentials_required'):
        _credential(object(), identity(), None, 'backup')


def test_restore_owner_signing_key_cannot_reuse_the_workflow_key():
    from agent_market.postgres_operational_archive import approve_deployment, OperationalArchiveDenied
    authority=RestoreOwnerAuthority(b'k'*32,verifier=lambda *_:'owner')
    with pytest.raises(OperationalArchiveDenied,match='independent_owner_authority_required'):
        approve_deployment(object(),identity=None,credentials=None,workflow_key=b'k'*32,authority=authority,receipt={},proof=None)


def test_actual_general_archive_credentials_ownership_failure_and_reapproval(monkeypatch, request):
    from scripts.rehearse_postgres_operational_archive import rehearse
    monkeypatch.setenv('PGPASSWORD', 'synthetic-unused-parent-password')
    monkeypatch.setenv('PGHOST', 'operating.invalid')
    monkeypatch.setenv('AGENT_PRIVATE_ARTIFACT_KEYRING', '/private/absent-parent-keyring')
    before = dict(os.environ); result = rehearse()
    assert dict(os.environ) == before
    assert all(value is True for value in result['checks'].values()) and len(result['checks']) >= 20
    assert not result['operating_backup_ready'] and result['operating_actions'] == result['external_calls'] == 0
    assert result['temporary_cluster_removed']
    import json
    request.node.user_properties.append(('operational_archive_contracts', json.dumps(result,sort_keys=True)))

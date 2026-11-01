"""Typed transfer, explicit proof and native isolation contracts."""
import json
import math
import hashlib
import hmac
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_market.application_store_migration import (
    MigrationDenied, PreparationAuthority, _cell, _canonical, _stores,
)


@pytest.mark.parametrize('value,kind', [('1','INTEGER'), (True,'INTEGER'), (2**63,'INTEGER'),
    ('1','REAL'), (math.inf,'REAL'), (math.nan,'REAL'), (1,'TEXT'), ('nul\0','TEXT'),
    ('\ud800','TEXT'), ('blob','BLOB'), (memoryview(b'byte'),'UNKNOWN')])
def test_affinity_failure_exposes_only_safe_code(value, kind):
    with pytest.raises(MigrationDenied, match='unsupported_source_affinity'):
        _cell(value, kind, 'synthetic', 'field')


def test_mixed_private_principal_preserves_customer_or_staff_identity():
    assert _cell(42,'TEXT','workspace_drafts','created_by') == '42'
    assert _cell('cu_'+'1'*32,'TEXT','workspace_private_runs','actor_user_id') == 'cu_'+'1'*32
    assert _cell(None,'INTEGER','resources','id') is None
    assert _cell(42,'REAL','resources','eval_score') == 42.0
    assert _canonical((b'synthetic-private',))[0]['blob_length'] == 17
    assert 'synthetic-private' not in json.dumps(_canonical((b'synthetic-private',)))


@pytest.mark.parametrize('key,verifier', [(b'short',lambda *_:None), ('x'*32,lambda *_:None), (b'a'*32,None)])
def test_independent_proof_requires_explicit_key_and_verifier(key, verifier):
    with pytest.raises(MigrationDenied): PreparationAuthority(key, verifier=verifier)


def test_claimed_boolean_or_missing_current_owner_evidence_is_not_approval():
    authority=PreparationAuthority(b'a'*32,verifier=lambda *_:True)
    with pytest.raises(MigrationDenied,match='independent_current_owner_proof_required'):
        authority.issue({'phase':'cutover'},True)


def approval_fixture():
    names=('owner_ref','ingress_stop_ref','workers_stop_ref','external_reconciliation_ref','compatibility_ref','rollback_point_ref')
    challenge={'operation_id':'apm_'+'1'*32,'revision':1,'phase':'cutover'}
    authority=PreparationAuthority(b'a'*32,verifier=lambda *_:{name:'synthetic:'+name for name in names})
    return authority,challenge,authority.issue(challenge,None)


def test_proof_is_exact_challenge_and_expiry_bound_and_contains_only_hashes():
    authority,challenge,approval=approval_fixture()
    assert authority.verify(approval,challenge)['challenge'] == challenge
    with pytest.raises(MigrationDenied): authority.verify(approval,challenge|{'phase':'rollback'})
    approval['payload']['expires']=time.time()-1
    with pytest.raises(MigrationDenied): authority.verify(approval,challenge)
    assert 'synthetic:owner_ref' not in json.dumps(approval)


def test_signature_tampering_and_unscoped_store_objects_are_refused():
    authority,challenge,approval=approval_fixture()
    approval['signature']='0'*64
    with pytest.raises(MigrationDenied): authority.verify(approval,challenge)
    with pytest.raises(MigrationDenied,match='idle_owned_stores_required'):
        _stores(SimpleNamespace(),SimpleNamespace(),b'm'*32)


@pytest.mark.parametrize('copy', [False, True])
def test_transfer_consumer_failure_closes_row_cursors_before_database_shutdown(monkeypatch, copy):
    import agent_market.application_store_migration as migration
    closed=[]
    class Cursor(sqlite3.Cursor):
        def close(self):
            closed.append(True)
            return super().close()
    class Connection(sqlite3.Connection):
        def execute(self, statement, values=()):
            return self.cursor(factory=Cursor).execute(statement, values)
    db=sqlite3.connect(':memory:',factory=Connection)
    try:
        db.execute('CREATE TABLE sample(value TEXT)').close()
        db.execute("INSERT INTO sample VALUES('ok')").close()
        db.execute('CREATE TABLE native_sample(value TEXT)').close()
        db.execute('INSERT INTO native_sample VALUES(?)',('x'*40,)).close()
        closed.clear()
        monkeypatch.setattr(migration,'_columns',lambda:{'sample':[('value','TEXT')]})
        monkeypatch.setattr(migration,'MAX_BYTES',20)
        def fail_copy(*_args):
            raise MigrationDenied('synthetic_copy_refused')
        target=SimpleNamespace(_execute=fail_copy,
            _native=lambda _sql:db.execute('SELECT value FROM native_sample'))
        expected='synthetic_copy_refused' if copy else 'migration_byte_limit'
        with pytest.raises(MigrationDenied,match=expected):
            migration._measure(SimpleNamespace(_db=db),target,{'sample'},b'm'*32,copy=copy)
        assert len(closed)==(1 if copy else 2)
        assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0]==1
    finally:
        db.close()


def test_actual_application_transfer_native_database_and_quarantine(monkeypatch):
    from scripts.rehearse_application_migration_postgres import rehearse
    monkeypatch.setenv('PGHOSTADDR','127.0.0.1')
    monkeypatch.setenv('PGSERVICE','synthetic-nonexistent-service')
    monkeypatch.setenv('PGOPTIONS','-c synthetic_invalid_setting=1')
    result=rehearse()
    assert len(result['checks']) >= 21 and all(result['checks'].values())
    assert result['operating_database_writes'] == result['external_provider_calls'] == 0
    assert result['target_quarantined'] and not result['cutover_authorized'] and not result['full_application_ready']
    assert result['temporary_cluster_removed'] and result['source_unchanged']
    folder=Path('reports/advancement-batch7-2026-10-19/pg');folder.mkdir(parents=True,exist_ok=True)
    (folder/'migration-native.json').write_text(json.dumps(result,indent=2)+'\n')


def test_owner_revocation_after_issue_is_rechecked_before_preparation():
    authority,challenge,approval=approval_fixture()
    authority.verifier=lambda *_:None
    with pytest.raises(MigrationDenied,match='independent_current_owner_proof_required'):
        authority.verify(approval,challenge)


def test_receipt_expiring_during_independent_verifier_is_refused(monkeypatch):
    import agent_market.application_store_migration as migration
    authority,challenge,approval=approval_fixture()
    current=[approval['payload']['expires']-.01]
    monkeypatch.setattr(migration.time,'time',lambda:current[0])
    original=authority.verifier
    def slow(*args):
        value=original(*args);current[0]+=.02;return value
    authority.verifier=slow
    with pytest.raises(MigrationDenied,match='independent_current_owner_proof_required'):
        authority.verify(approval,challenge)


EFFECTS = (
    ('workspace_remote_tasks','private-a2a03-task-poll-v1','status','completed',
        ('submitted','working','input-required','auth-required','dispatched','unknown'),
        {'logical_id':'logical','expires':9999999999.0}),
    ('reliability_eval_jobs','bounded-continuous-evaluation-v1','state','completed',
        ('reserved','prepared','dispatched','unknown'),
        {'logical_key':'logical','host_key':'host','window_start':1.0,'expires':9999999999.0}),
    ('workspace_machine_update_events','workspace-machine-evidence-updates-v1','state','accepted',
        ('prepared','dispatched','unknown'),
        {'subscription_id':'subscription','dedupe_hash':'dedupe','created':1.0}),
    ('stripe_sandbox_commands','stripe-connect-test-usd-gross-v1',None,'accepted',
        ('dispatched','unknown'),{'order_id':'order'}),
)


@pytest.fixture
def signed_effect_target(monkeypatch):
    from agent_market.private_artifact_keys import ENV, ArtifactSigner
    from agent_market.workspace_access import PROFILE
    from agent_market.workspace_remote_a2a import SCHEMA as REMOTE
    from agent_market.reliability_evaluation import SCHEMA as EVALUATION
    from agent_market.workspace_machine_updates import SCHEMA as UPDATES
    from agent_market.stripe_sandbox import SCHEMA as STRIPE
    monkeypatch.delenv(ENV,raising=False)
    db=sqlite3.connect(':memory:')
    for statement in (*REMOTE,*EVALUATION,*UPDATES,*STRIPE):
        db.execute(statement)
    root=b'k'*32
    key=hmac.new(hmac.new(root,b'workflow-results-v1',hashlib.sha256).digest(),
        PROFILE.encode('ascii'),hashlib.sha256).digest()
    target=SimpleNamespace(workflow_key=root,
        _native=lambda statement:db.execute(statement.replace('public.','')),
        _execute=lambda _statement:SimpleNamespace(fetchone=lambda:(0,)))
    def insert(spec,state,*,locator=None,invalid_signature=False):
        table,profile,state_column,_terminal,_active,extras=spec
        value={'id':'effect','workspace_id':'workspace','state':state,**extras}
        signer=ArtifactSigner(hmac.new(key,profile.encode(),hashlib.sha256).digest(),profile)
        row={**value,'payload':json.dumps(value),'signature':signer.sign(value)}
        if invalid_signature:
            row['signature']='0'*64
        if state_column:
            row[state_column]=state if locator is None else locator
        if state_column!='state':
            del row['state']
        columns=','.join(row)
        db.execute('INSERT INTO '+table+'('+columns+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
    try:
        yield db,target,insert
    finally:
        db.close()


@pytest.mark.parametrize('spec',EFFECTS,ids=[s[0] for s in EFFECTS])
def test_handoff_accepts_only_verified_terminal_new_effects(signed_effect_target,spec):
    from agent_market.application_store_migration import _quiescent
    db,target,insert=signed_effect_target
    insert(spec,spec[3])
    before=list(db.iterdump())
    assert _quiescent(target)
    assert list(db.iterdump())==before


@pytest.mark.parametrize('spec,state',[(s,state) for s in EFFECTS for state in s[4]],
    ids=[s[0]+':'+state for s in EFFECTS for state in s[4]])
def test_handoff_blocks_active_or_uncertain_new_effects(signed_effect_target,spec,state):
    from agent_market.application_store_migration import _quiescent
    db,target,insert=signed_effect_target
    insert(spec,state)
    before=list(db.iterdump())
    assert not _quiescent(target)
    assert list(db.iterdump())==before


@pytest.mark.parametrize('spec',EFFECTS,ids=[s[0] for s in EFFECTS])
def test_handoff_does_not_trust_forged_terminal_effect_locators(signed_effect_target,spec):
    from agent_market.application_store_migration import _quiescent
    db,target,insert=signed_effect_target
    insert(spec,spec[3],invalid_signature=True)
    assert not _quiescent(target)
    db.execute('DELETE FROM '+spec[0])
    if spec[2]:
        insert(spec,'unknown',locator=spec[3])
        assert not _quiescent(target)
        db.execute('DELETE FROM '+spec[0])
    insert(spec,spec[3])
    db.execute('UPDATE '+spec[0]+" SET workspace_id='tampered-locator'")
    assert not _quiescent(target)


def test_handoff_limits_fail_closed_instead_of_truncating_signed_effect_review(signed_effect_target,monkeypatch):
    import agent_market.application_store_migration as migration
    _db,target,insert=signed_effect_target
    insert(EFFECTS[0],'completed')
    monkeypatch.setattr(migration,'MAX_TABLE_ROWS',0)
    assert not migration._quiescent(target)


def test_blob_transfer_quota_counts_raw_bytes_before_hash_canonicalization(monkeypatch):
    import agent_market.application_store_migration as migration
    monkeypatch.setattr(migration,'MAX_BYTES',1024)
    monkeypatch.setattr(migration,'_columns',lambda:{'vec_resources':[('rowid','INTEGER'),('embedding','BLOB')]})
    monkeypatch.setattr(migration,'_rows',lambda *_args,**_kwargs:(row for row in ((1,b'x'*3072),)))
    with pytest.raises(MigrationDenied,match='migration_byte_limit'):
        migration._measure(SimpleNamespace(),SimpleNamespace(),{'vec_resources'},b'k'*32)


def test_session_lock_acknowledgement_uncertainty_poisoned_target_and_releases_source(monkeypatch):
    import sqlite3
    import threading
    import agent_market.application_store_migration as migration
    connection=sqlite3.connect(':memory:')
    source=SimpleNamespace(_db=connection,_lock=threading.RLock())
    target=SimpleNamespace(_connection=object(),_lock=threading.RLock(),_broken=False)
    monkeypatch.setattr(migration,'_stores',lambda *_:b'k'*32)
    def uncertain(*_args,**_kwargs):raise RuntimeError('Synthetic lost lock response')
    monkeypatch.setattr(migration,'_sql',uncertain)
    try:
        with pytest.raises(MigrationDenied,match='target_ownership_unknown'):
            with migration._fence(source,target,'apm_'+'1'*32,b'k'*32):pytest.fail('uncertain owner admitted')
        assert target._broken and not connection.in_transaction
        assert connection.execute('PRAGMA busy_timeout').fetchone()[0]==5000
    finally:connection.close()

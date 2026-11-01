"""No-replay custody keeps uncertain history while rejecting live effects."""
import hashlib
import hmac
import sqlite3
import time
from types import SimpleNamespace

import pytest

from agent_market.migration_terminal_custody import PROFILE, inspect, quiescent
from agent_market.private_artifact_keys import ArtifactSigner
from agent_market.workspace_access import PROFILE as ACCESS_PROFILE, _canonical, _hash
from agent_market.workspace_typed_flows import PROFILE as TYPED_PROFILE


@pytest.fixture
def fixture_store():
    db = sqlite3.connect(':memory:')
    db.executescript('''
        CREATE TABLE workflow_runs(id TEXT,status TEXT,execution_outcome TEXT,finished REAL,lease_until REAL);
        CREATE TABLE workflow_execution_attempts(run_id TEXT,status TEXT,dispatched REAL);
        CREATE TABLE workflow_result_outbox(status TEXT);
        CREATE TABLE workspace_private_runs(status TEXT);
        CREATE TABLE workspace_meter_operations(status TEXT);
        CREATE TABLE clearing_ledger(status TEXT);
        CREATE TABLE workflow_manual_deliveries(status TEXT);
        CREATE TABLE agent_task_events(id TEXT,watch_id TEXT,status TEXT,attempts INTEGER);
        CREATE TABLE agent_task_watches(id TEXT,channel TEXT);
        CREATE TABLE workspace_typed_flow_runs(id TEXT,ticket_id TEXT,workspace_id TEXT,flow_id TEXT,
            status TEXT,created REAL,deadline REAL,payload TEXT,signature TEXT);
        CREATE TABLE workspace_typed_flow_tickets(id TEXT,workspace_id TEXT,flow_id TEXT,version_id TEXT,
            expires REAL,payload TEXT,signature TEXT,run_id TEXT);
        CREATE TABLE workspace_typed_flow_steps(run_id TEXT,node_id TEXT,status TEXT,payload TEXT,signature TEXT);
        CREATE TABLE workspace_remote_tasks(id TEXT,workspace_id TEXT,logical_id TEXT,expires REAL,status TEXT,payload TEXT,signature TEXT);
        CREATE TABLE reliability_eval_jobs(id TEXT,workspace_id TEXT,logical_key TEXT,state TEXT,host_key TEXT,
            window_start REAL,expires REAL,payload TEXT,signature TEXT);
        CREATE TABLE workspace_machine_update_events(id TEXT,workspace_id TEXT,subscription_id TEXT,
            dedupe_hash TEXT,state TEXT,created REAL,payload TEXT,signature TEXT);
        CREATE TABLE stripe_sandbox_commands(id TEXT,workspace_id TEXT,order_id TEXT,payload TEXT,signature TEXT);
        INSERT INTO workflow_runs VALUES('old','failed','unknown',1,0);
        INSERT INTO workflow_execution_attempts VALUES('old','unknown',1);
        INSERT INTO workflow_execution_attempts VALUES('old','prepared',NULL);
        INSERT INTO agent_task_watches VALUES('manual','poll');
        INSERT INTO agent_task_events VALUES('event','manual','ready',0);
    ''')
    def execute(statement):
        return db.execute(statement.replace('public.', ''))
    store = SimpleNamespace(_execute=execute, _native=execute, workflow_key=b'm' * 32, db=db)
    yield store
    db.close()


def add_typed(store):
    runtime_key = hmac.new(store.workflow_key, b'workflow-results-v1', hashlib.sha256).digest()
    access_key = hmac.new(runtime_key, ACCESS_PROFILE.encode(), hashlib.sha256).digest()
    signer = ArtifactSigner(hmac.new(access_key, TYPED_PROFILE.encode(), hashlib.sha256).digest(), TYPED_PROFILE)
    ticket = {'profile': TYPED_PROFILE, 'id': 'ticket', 'workspace_id': 'workspace', 'flow_id': 'flow',
              'version_id': 'version', 'expires': 3}
    run = {'profile': TYPED_PROFILE, 'id': 'typed', 'ticket_id': 'ticket', 'workspace_id': 'workspace',
           'flow_id': 'flow', 'status': 'unknown', 'created': 1, 'deadline': 2, 'finished': 2,
           'ticket_hash': _hash(ticket)}
    step = {'profile': TYPED_PROFILE, 'run_id': 'typed', 'node_id': 'node', 'status': 'dispatched',
            'version_id': 'version'}
    store.db.execute('INSERT INTO workspace_typed_flow_tickets VALUES(?,?,?,?,?,?,?,?)',
                     ('ticket', 'workspace', 'flow', 'version', 3, _canonical(ticket), signer.sign(ticket), 'typed'))
    store.db.execute('INSERT INTO workspace_typed_flow_runs VALUES(?,?,?,?,?,?,?,?,?)',
                     ('typed', 'ticket', 'workspace', 'flow', 'unknown', 1, 2, _canonical(run), signer.sign(run)))
    store.db.execute('INSERT INTO workspace_typed_flow_steps VALUES(?,?,?,?,?)',
                     ('typed', 'node', 'dispatched', _canonical(step), signer.sign(step)))
    return signer, run, step


def test_explicit_custody_preserves_rows_and_original_unknown_outcomes(fixture_store):
    add_typed(fixture_store)
    before = list(fixture_store.db.iterdump())
    result = inspect(fixture_store)
    assert result['unknown_workflow_runs'] == result['unknown_typed_runs'] == result['manual_poll_events'] == 1
    assert result['terminal_execution_attempts'] == 2
    assert not result['outcomes_rewritten'] and not result['automatic_replay_enabled']
    assert quiescent(fixture_store, PROFILE)
    assert not quiescent(fixture_store, None) and not quiescent(fixture_store, 'unknown-policy')
    assert before == list(fixture_store.db.iterdump())


@pytest.mark.parametrize('mutation', [
    "UPDATE workflow_runs SET status='queued'",
    "UPDATE workflow_runs SET status='running'",
    "UPDATE workflow_runs SET finished=NULL",
    "UPDATE workflow_runs SET lease_until=1",
    "UPDATE workflow_runs SET status='succeeded'",
    "UPDATE workflow_execution_attempts SET status='dispatched'",
    "UPDATE workflow_execution_attempts SET run_id='orphan'",
    "UPDATE workflow_execution_attempts SET dispatched=1 WHERE status='prepared'",
    "UPDATE agent_task_watches SET channel='browser'",
    "UPDATE agent_task_events SET watch_id='orphan'",
    "UPDATE agent_task_events SET attempts=1",
    "UPDATE agent_task_events SET status='pending'",
    "UPDATE agent_task_events SET status='sending'",
    "INSERT INTO workflow_result_outbox VALUES('unknown')",
    "INSERT INTO workspace_private_runs VALUES('unknown')",
    "INSERT INTO workspace_meter_operations VALUES('admitted')",
    "INSERT INTO clearing_ledger VALUES('held')",
    "INSERT INTO workflow_manual_deliveries VALUES('pending')",
])
def test_live_or_outbound_or_resumable_effects_are_not_custody(fixture_store, mutation):
    fixture_store.db.execute(mutation)
    assert not quiescent(fixture_store, PROFILE)


@pytest.mark.parametrize('mutation', [
    "UPDATE workspace_typed_flow_runs SET signature='forged'",
    "UPDATE workspace_typed_flow_runs SET workspace_id='other'",
    "UPDATE workspace_typed_flow_tickets SET run_id=NULL",
    "UPDATE workspace_typed_flow_tickets SET signature='forged'",
    "UPDATE workspace_typed_flow_steps SET signature='forged'",
    "UPDATE workspace_typed_flow_steps SET status='completed'",
    "DELETE FROM workspace_typed_flow_tickets",
])
def test_typed_custody_requires_authentic_unchanged_consumed_ticket(fixture_store, mutation):
    add_typed(fixture_store)
    fixture_store.db.execute(mutation)
    assert not quiescent(fixture_store, PROFILE)


@pytest.mark.parametrize('change', ['future', 'unfinished', 'wrong-ticket-hash', 'wrong-version'])
def test_even_signed_nonterminal_or_rebound_typed_history_is_refused(fixture_store, change):
    signer, run, step = add_typed(fixture_store)
    if change == 'wrong-version':
        step['version_id'] = 'other'
        fixture_store.db.execute('UPDATE workspace_typed_flow_steps SET payload=?,signature=?',
                                 (_canonical(step), signer.sign(step)))
    else:
        if change == 'future':
            run['deadline'] = time.time() + 600
            fixture_store.db.execute('UPDATE workspace_typed_flow_runs SET deadline=?', (run['deadline'],))
        elif change == 'unfinished':
            run['finished'] = None
        else:
            run['ticket_hash'] = 'wrong'
        fixture_store.db.execute('UPDATE workspace_typed_flow_runs SET payload=?,signature=?',
                                 (_canonical(run), signer.sign(run)))
    assert not quiescent(fixture_store, PROFILE)


def test_custody_is_part_of_independent_approval_not_an_ambient_runtime_setting():
    from agent_market.application_store_migration import _challenge, PreparationAuthority, MigrationDenied
    value = {'operation_id': 'apm_' + '1' * 32, 'revision': 1, 'summary': {},
             'schema_profile': 'fixture', 'target_anchor': 'fixture'}
    strict = _challenge(value, 'cutover')
    custody = _challenge(value, 'cutover', PROFILE)
    names = ('owner_ref', 'ingress_stop_ref', 'workers_stop_ref', 'external_reconciliation_ref',
             'compatibility_ref', 'rollback_point_ref')
    authority = PreparationAuthority(b'a' * 32, verifier=lambda *_: {name: 'fixture:' + name for name in names})
    approval = authority.issue(strict, None)
    with pytest.raises(MigrationDenied):
        authority.verify(approval, custody)
    with pytest.raises(MigrationDenied):
        _challenge(value, 'cutover', 'unreviewed')


def test_actual_native_copy_activation_and_rollback_preserve_unknown_without_dispatch():
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, _tools, PORT
    from agent_market.storage_adapter import open_store
    from agent_market.application_store_postgres import _CATALOG, ApplicationStoreError
    from agent_market.gateway.store import Store
    from agent_market.credential_vault import CredentialVault
    from agent_market.application_store_migration import (copy_application, preparation_challenge,
        prepare_transition, activate_application, rollback_activation, PreparationAuthority,
        review_application, MigrationDenied, _quiescent)
    with _private_cluster(_tools()) as cluster:
        conn = psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        target = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'm' * 32)
        source = Store(':memory:')
        vault = CredentialVault.from_key(b's' * 32)
        for table in ('workflow_runs', 'workflow_execution_attempts', 'workflow_manual_deliveries'):
            if not source._db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
                source._db.execute(_CATALOG['sqlite_tables'][table])
        source._db.execute('''INSERT INTO workflow_runs(id,workflow_id,digest,snapshot,actor,source,status,
            created,finished,execution_outcome,lease_until) VALUES('retained',1,'fixture','{}','fixture',
            'fixture','failed',1,2,'unknown',0)''')
        source._db.execute("INSERT INTO workflow_execution_attempts VALUES('retained','node',1,'fixture','unknown',1,1,2)")
        source._db.commit()
        operation = 'apm_' + 'e' * 32
        try:
            copy_application(source, target, operation_id=operation, source_workflow_key=b'm' * 32, source_vault=vault)
            with review_application(conn, workflow_key=b'm' * 32, operation_id=operation) as reviewed:
                with reviewed.tx(readonly=True):
                    assert not _quiescent(reviewed)
                    assert inspect(reviewed)['unknown_workflow_runs'] == 1
            names = ('owner_ref', 'ingress_stop_ref', 'workers_stop_ref', 'external_reconciliation_ref',
                     'compatibility_ref', 'rollback_point_ref')
            allowed = [None]
            authority = PreparationAuthority(b'a' * 32, verifier=lambda c, p:
                {name: 'fixture:' + name for name in names} if c == allowed[0] and p == 'owner' else None)
            def approval(phase, policy=None):
                allowed[0] = preparation_challenge(target, operation_id=operation, phase=phase, history_policy=policy)
                return authority.issue(allowed[0], 'owner')
            arguments = dict(operation_id=operation, source_workflow_key=b'm' * 32, authority=authority,
                             proof='owner', source_vault=vault)
            with pytest.raises(MigrationDenied, match='external_outcome_reconciliation_required'):
                prepare_transition(source, target, phase='cutover', approval=approval('cutover'), **arguments)
            prepared = prepare_transition(source, target, phase='cutover', history_policy=PROFILE,
                                          approval=approval('cutover', PROFILE), **arguments)
            assert prepared['receipt']['preserved_terminal_history']['unknown_workflow_runs'] == 1
            active = activate_application(source, target, approval=approval('activation'), **arguments)
            assert active['receipt']['operating_enabled'] and active['receipt']['history_policy'] == PROFILE
            with pytest.raises(sqlite3.DatabaseError):
                source.set_meta('old-writer', 'forbidden')
            with target.tx(readonly=True):
                assert target._execute("SELECT execution_outcome FROM workflow_runs WHERE id='retained'").fetchone()[0] == 'unknown'
            target.set_meta('new-writer', 'verified')
            fresh = open_store('postgresql', connection=conn, workflow_key=b'm' * 32)
            fresh.close()
            rolled = rollback_activation(source, target, approval=approval('rollback_activation'), capture_changes=True, **arguments)
            assert not rolled['receipt']['operating_enabled']
            assert source.get_meta('new-writer') == 'verified'
            with pytest.raises(ApplicationStoreError):
                target.set_meta('after-rollback', 'forbidden')
        finally:
            target.close()
            conn.close()
            source._db.close()

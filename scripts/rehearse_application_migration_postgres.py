"""Full known-table transfer on an owned disposable Unix-socket fixture only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster

PROFILE = 'application-migration-native-contracts-v1'


def _contracts(connect):
    from agent_market.gateway import store as store_module
    from agent_market.gateway.admin_auth import ADMIN_SCHEMA
    from agent_market.storage_adapter import open_store
    from agent_market.application_store_postgres import ApplicationStoreError, _CATALOG
    from agent_market.application_store_migration import (copy_application, reconcile_application,
        preparation_challenge, prepare_transition, PreparationAuthority, MigrationDenied, _fence)
    from agent_market.credential_vault import CredentialVault
    from agent_market.gateway.notification_preferences import NotificationPreferences
    from agent_market.workspace_access import WorkspaceAccess, SessionActor
    from agent_market.gateway import admin_auth
    from agent_market.legacy_vector_index import ModelDescriptor
    from agent_market.application_store_migration import review_application, _quiescent
    pg = connect()
    target = open_store('postgresql', connection=pg, initialize=True, workflow_key=b'm' * 32)
    old = store_module.init_admin_auth_db
    store_module.init_admin_auth_db = lambda db: db.executescript(ADMIN_SCHEMA)
    try: source = store_module.Store(str(Path(pg.info.host).parent/'application-source.sqlite'))
    finally: store_module.init_admin_auth_db = old
    source._credential_vault = CredentialVault.from_key(b's' * 32)
    checks = {}
    operation = 'apm_' + '1' * 32
    def denied(fn, code):
        try: fn()
        except (MigrationDenied, ApplicationStoreError) as error:
            if error.code != code: raise
            return True
        raise AssertionError(code)
    try:
        source.upsert_resource({'key': 'synthetic:transfer', 'source': 'fixture', 'kind': 'mcp',
            'url': 'https://synthetic.example/mcp', 'name': 'Atomic transfer', 'description': 'Synthetic public corpus',
            'category': 'research', 'networks': [], 'details': {}}, now=10)
        subject = source.resource(1)
        report = {'title': 'Synthetic transfer report', 'resource_id': subject['id'],
            'agent_name': subject['name'], 'kind': subject['kind'], 'agent_url': subject['url'],
            # Metadata solely exercises identity high-water transfer. It is not
            # a measured execution report or an operating quality assertion.
            'is_success': 0, 'evidence_scope': 'synthetic-fixture',
            'input_wire': 'Synthetic test', 'output_wire': 'Synthetic result'}
        try: source.create_test_report(report | {'agent_name': 'Different fixture subject'})
        except ValueError:
            checks['mismatched_report_subject_refused_before_insertion'] = not source.query('SELECT id FROM agent_test_reports')
        else: raise AssertionError('mismatched migration report subject admitted')
        source.create_test_report(report)
        source.create_workflow({'name': 'Synthetic workflow', 'nodes': [], 'edges': [], 'author': 'Fixture', 'is_template': 1})
        source.set_credential('synthetic-key', 'synthetic-vault-value-42', 'fixture', 'Synthetic only')
        with source.tx() as db:
            staff_user = admin_auth.create_admin_user(db, 'migration-owner', 'Synthetic-migration-password-42', 'Fixture owner', 'superadmin')
            staff_token = admin_auth.create_session(db, staff_user['id'], staff_user['username'], staff_user['role'], staff_user['name'])
        staff = SessionActor(staff_user['id'], admin_auth.session_reference(staff_token))
        source_access = WorkspaceAccess(source, b'm' * 32)
        workspace = source_access.provision({'name': 'Migration private team', 'owner_id': staff_user['id']}, staff)
        private_draft = source_access.save_draft(workspace['id'], {'name': 'Private transfer draft',
            'description': '', 'definition': {'nodes': [], 'edges': []}}, staff)
        private_snapshot = source_access.create_snapshot(workspace['id'], private_draft['id'], {'draft_revision': 1}, staff)
        descriptor = ModelDescriptor('synthetic-transfer-model', revision='fixture-v1')
        source._vector_index.ensure_jobs(descriptor, limit=1, resource_ids=(1,))
        vector_claim = source._vector_index.claim_batch(descriptor, limit=1, resource_ids=(1,))[0]
        if source._vector_index.publish(vector_claim, [1.0]+[0.0]*767, descriptor) != 'indexed':
            raise AssertionError('native transfer vector fixture')
        # Remove both sides of this fixture-only report before testing deleted
        # identity high water. Retain the actual source reference constraint.
        with source.tx() as db:
            db.execute('DELETE FROM test_report_subject_claims')
            db.execute('DELETE FROM agent_test_reports')
        # High-water ID remains consumed even after its row is deleted.
        deleted_high_water = source._db.execute("SELECT seq FROM sqlite_sequence WHERE name='agent_test_reports'").fetchone()[0]
        source._db.execute('CREATE TABLE synthetic_unknown(id INTEGER)'); source._db.commit()
        checks['unknown_source_schema_refused_before_commit'] = denied(lambda: copy_application(source, target,
            operation_id=operation, source_workflow_key=b'm' * 32, source_vault=source._credential_vault), 'unknown_source_schema')
        source._db.execute('DROP TABLE synthetic_unknown'); source._db.commit()
        checks['wrong_signing_key_refused'] = denied(lambda: copy_application(source, target,
            operation_id=operation, source_workflow_key=b'x' * 32), 'workflow_key_custody_mismatch')
        checks['credential_copy_requires_explicit_source_vault'] = denied(lambda: copy_application(source, target,
            operation_id=operation, source_workflow_key=b'm' * 32), 'source_vault_required')
        # A late refusal rolls all prior table inserts back, including triggers.
        checks['failed_transfer_has_no_committed_target_rows'] = target.resource(1) is None
        with target.tx(): target._validate_native_invariants()
        with source.tx() as db: db.execute("UPDATE resources SET eval_score='invalid affinity' WHERE id=1")
        checks['invalid_affinity_refused_atomically'] = denied(lambda: copy_application(source, target,
            operation_id=operation, source_workflow_key=b'm' * 32, source_vault=source._credential_vault), 'unsupported_source_affinity')
        with source.tx() as db: db.execute('UPDATE resources SET eval_score=NULL WHERE id=1')
        # Native adapter receives an actual current notification view, including
        # all filter builders, alias ordering and escaped bound hostile text.
        for q in ('', "x%' OR 1=1 --"):
            for state in ('all', 'active'):
                for channel in ('all', 'webhook'):
                    left = NotificationPreferences(source).list(q, state, channel)
                    right = NotificationPreferences(target).list(q, state, channel)
                    if left != right: raise AssertionError('notification preference dialect parity')
        checks['notification_admin_finite_queries_bound_parity'] = True
        if source._vector_index.current_ids([1], descriptor) != {1}:
            source._vector_index.ensure_jobs(descriptor, limit=1, resource_ids=(1,))
            vector_claim = source._vector_index.claim_batch(descriptor, limit=1, resource_ids=(1,))[0]
            if source._vector_index.publish(vector_claim, [1.0]+[0.0]*767, descriptor) != 'indexed':
                raise AssertionError('current vector source fixture')
        from concurrent.futures import ThreadPoolExecutor
        import sqlite3
        competitor_connection = connect()
        competitor = open_store('postgresql',connection=competitor_connection,workflow_key=b'm'*32)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with _fence(source,target,operation,b'm'*32):
                writer = sqlite3.connect(str(Path(pg.info.host).parent/'application-source.sqlite'),timeout=.1)
                try:
                    try:writer.execute("INSERT INTO meta VALUES('external-writer','blocked')")
                    except sqlite3.OperationalError:checks['sqlite_writer_fence_blocks_separate_connections']=True
                    else:raise AssertionError('source writer was admitted')
                finally:writer.close()
                def competing_write():
                    try:competitor.set_meta('external-writer','blocked')
                    except ApplicationStoreError:return True
                    return False
                checks['native_writer_fence_blocks_separate_store']=pool.submit(competing_write).result(timeout=3)
        competitor.close();competitor_connection.close()
        # A late error after sequence preparation must roll back both identity
        # RESTART and application inserts, rather than leaking nextval changes.
        import agent_market.application_store_migration as migration_module
        receipt_writer = migration_module._receipt
        def refuse_receipt(*_args,**_kwargs):raise MigrationDenied('synthetic_receipt_failure')
        migration_module._receipt=refuse_receipt
        try:
            checks['late_transfer_failure_rolls_back_rows_and_sequences']=denied(lambda:copy_application(source,target,
                operation_id=operation,source_workflow_key=b'm'*32,source_vault=source._credential_vault),'synthetic_receipt_failure')
        finally:migration_module._receipt=receipt_writer
        with target.tx():
            checks['late_failure_retains_fresh_identity_counter']=target._execute('SELECT last_value,is_called FROM agent_test_reports_id_seq').fetchone()[0]==1
        checks['late_failure_retains_empty_target']=target.resource(1) is None
        record = copy_application(source, target, operation_id=operation, source_workflow_key=b'm' * 32,
            source_vault=source._credential_vault)
        checks['all_known_present_tables_atomic_transfer_equal'] = record['receipt']['summary']['equal']
        checks['optional_absent_source_tables_explicitly_empty'] = bool(record['receipt']['summary']['schema_absent_empty'])
        checks['target_stays_quarantined_for_existing_store'] = denied(lambda: target.resource(1), 'migration_target_quarantined')
        checks['target_stays_quarantined_for_fresh_attach'] = denied(lambda: open_store('postgresql', connection=pg,
            workflow_key=b'm' * 32), 'migration_target_quarantined')
        same = reconcile_application(source, target, operation_id=operation, source_workflow_key=b'm' * 32,
            source_vault=source._credential_vault)
        checks['typed_whole_application_reconciliation_equal'] = same['summary']['equal'] and same['matches_staged_baseline']
        with _fence(source, target, operation, b'm' * 32):
            checks['credential_cipher_resealed_with_same_plaintext'] = target.get_credential('synthetic-key') == 'synthetic-vault-value-42'
            checks['identity_high_water_preserved_after_deletion'] = target._execute(
                "SELECT last_value,is_called FROM agent_test_reports_id_seq").fetchone()[0] == deleted_high_water + 1
            checks['workflow_catalog_public_consumer_parity'] = target.list_workflows(is_template=True) == source.list_workflows(is_template=True)
            checks['empty_effect_queues_can_be_prepared'] = _quiescent(target)
        with review_application(pg, workflow_key=b'm'*32, operation_id=operation) as reviewed:
            native_access = WorkspaceAccess(reviewed, b'm' * 32)
            checks['signed_private_snapshot_and_staff_authority_preserved'] = (
                native_access.workspace(workspace['id'], staff)['name'] == workspace['name']
                and native_access.version(workspace['id'], private_draft['id'], private_snapshot['id'], staff)['snapshot'] == private_snapshot['snapshot'])
            checks['vector_bytes_provenance_and_current_generation_preserved'] = reviewed._vector_index.current_ids([1], descriptor) == {1}
            checks['reconnected_explicit_review_only_not_activated'] = reviewed.resource(1)['name'] == 'Atomic transfer'
        checks['review_scope_store_closed_after_exit'] = reviewed._closed

        try:
            with _fence(source,target,operation,b'm'*32):
                for status in ('prepared','dispatched','unknown'):
                    target._execute('INSERT INTO workspace_private_runs VALUES(%s,%s,%s,%s,%s,%s,%s,1,2,NULL,NULL,%s,%s)',
                        ('synthetic-run','synthetic-ticket',workspace['id'],private_draft['id'],private_snapshot['id'],'0',status,'{}','synthetic'))
                    if _quiescent(target):raise AssertionError('ambiguous private run admitted')
                    target._execute('DELETE FROM workspace_private_runs WHERE id=%s',('synthetic-run',))
                for status in ('running','unknown'):
                    target._execute('INSERT INTO workspace_typed_flow_runs VALUES(%s,%s,%s,%s,%s,1,2,%s,%s)',
                        ('synthetic-typed','synthetic-ticket',workspace['id'],'synthetic-flow',status,'{}','synthetic'))
                    if _quiescent(target):raise AssertionError('ambiguous typed run admitted')
                    target._execute('DELETE FROM workspace_typed_flow_runs WHERE id=%s',('synthetic-typed',))
                checks['private_prepared_dispatched_unknown_and_typed_running_unknown_block_preparation']=True
                raise MigrationDenied('synthetic_quiescence_rollback')
        except MigrationDenied as error:
            if error.code!='synthetic_quiescence_rollback':raise
        challenge = preparation_challenge(target, operation_id=operation, phase='cutover')
        fields = ('owner_ref', 'ingress_stop_ref', 'workers_stop_ref', 'external_reconciliation_ref', 'compatibility_ref', 'rollback_point_ref')
        authority = PreparationAuthority(b'a' * 32, verifier=lambda expected, proof:
            {name: 'synthetic:' + name for name in fields} if proof == 'fixture-owner-proof' and expected == challenge else None)
        approval = authority.issue(challenge, 'fixture-owner-proof')
        source.set_meta('synthetic-source-change', 'changed')
        checks['source_divergence_blocks_cutover_preparation'] = denied(lambda: prepare_transition(source, target,
            operation_id=operation, source_workflow_key=b'm' * 32, phase='cutover', authority=authority,
            approval=approval, proof='fixture-owner-proof', source_vault=source._credential_vault), 'application_baseline_diverged')
        with source.tx() as db: db.execute('DELETE FROM meta WHERE key=?', ('synthetic-source-change',))
        prepared = prepare_transition(source, target, operation_id=operation, source_workflow_key=b'm' * 32,
            phase='cutover', authority=authority, approval=approval, proof='fixture-owner-proof', source_vault=source._credential_vault)
        checks['independent_cutover_preparation_never_activates'] = prepared['receipt']['state'] == 'cutover_prepared' and not prepared['receipt']['cutover_authorized']
        checks['old_approval_cannot_replay_after_revision'] = denied(lambda: prepare_transition(source, target,
            operation_id=operation, source_workflow_key=b'm' * 32, phase='cutover', authority=authority,
            approval=approval, proof='fixture-owner-proof', source_vault=source._credential_vault), 'independent_current_owner_proof_required')
        rollback = preparation_challenge(target, operation_id=operation, phase='rollback')
        authority.verifier = lambda expected, proof: {name: 'synthetic:' + name for name in fields} if expected == rollback and proof == 'fixture-owner-proof' else None
        rollback_approval = authority.issue(rollback, 'fixture-owner-proof')
        rolled = prepare_transition(source, target, operation_id=operation, source_workflow_key=b'm' * 32,
            phase='rollback', authority=authority, approval=rollback_approval, proof='fixture-owner-proof', source_vault=source._credential_vault)
        checks['rollback_is_signed_preparation_without_reverse_copy'] = rolled['receipt']['state'] == 'rollback_prepared' and not rolled['receipt']['operating_enabled']
        checks['prepared_target_still_refuses_normal_operations'] = denied(lambda: target.resource(1), 'migration_target_quarantined')
        checks['source_unchanged_by_transfer_or_preparation'] = source.resource(1)['name'] == 'Atomic transfer'
        if not all(checks.values()): raise AssertionError('native migration contract')
        return {'checks': checks, 'known_tables': len(_CATALOG['tables']), 'copied_rows': record['receipt']['summary']['rows'],
            'target_quarantined': True, 'cutover_authorized': False, 'full_application_ready': False}
    finally:
        target.close(); pg.close(); source._db.close()


def _worker():
    from scripts import rehearse_application_store_postgres as base
    base._contracts = _contracts
    base._worker()


def rehearse():
    driver = _driver()
    files = [Path(__file__), Path('agent_market/application_store_migration.py'), Path('agent_market/application_store_postgres.py'),
        Path('agent_market/application_store_sql.json'), Path('agent_market/gateway/notification_preferences.py')]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment'])
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(driver.__file__).resolve().parent.parent)
        result = subprocess.run([sys.executable, '-B', '-c',
            'from scripts.rehearse_application_migration_postgres import _worker; _worker()'],
            env=environment, input=json.dumps({'socket': cluster['socket'], 'root': cluster['root']}),
            text=True, capture_output=True, timeout=180)
        if result.returncode: raise RuntimeError('Synthetic migration contract failed: ' + result.stderr[-5000:])
        result = json.loads(result.stdout)
    if before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}: raise AssertionError('source changed')
    return {'profile': PROFILE, **result, 'source_hashes': before, 'source_unchanged': True,
        'temporary_cluster_removed': True, 'operating_database_writes': 0, 'external_provider_calls': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', action='store_true', required=True)
    parser.parse_args(argv)
    print(json.dumps(rehearse(), sort_keys=True, allow_nan=False))


if __name__ == '__main__': main()

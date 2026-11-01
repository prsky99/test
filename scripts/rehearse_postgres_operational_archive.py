"""Run the general archive API only against a fresh Unix PostgreSQL fixture.

The same explicit identity/credential/gate API intended for operator wiring is
used. No operating DSN, path, key, service or provider can be supplied by CLI.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from unittest.mock import patch

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster, PORT

PROFILE = 'general-postgres-archive-synthetic-contracts-v1'
KEY = b'synthetic-native-workflow-key-32'
PASSWORD = 'synthetic-native-archive-pass-42'


def require(value, label):
    if value is not True: raise AssertionError(label)


def _guard(cluster):
    original = socket.socket.connect
    def connect(current, address):
        if current.family != socket.AF_UNIX or not str(address).startswith(cluster['socket'] + '/'):
            raise AssertionError('Unexpected archive fixture socket destination')
        return original(current, address)
    socket.socket.connect = connect
    socket.getaddrinfo = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('Unexpected name resolution'))


def _connect(cluster, database='postgres'):
    return _driver().connect(host=cluster['socket'], hostaddr='', port=PORT, dbname=database,
        user='postgres', password=PASSWORD, connect_timeout=3, autocommit=True,
        passfile=str(Path(cluster['root']) / 'absent-passfile'), sslmode='disable', gssencmode='disable')


def _identity(connection):
    from agent_market.postgres_archive_provider import DatabaseIdentity
    with connection.cursor() as cursor:
        cursor.execute('SELECT system_identifier::text FROM pg_catalog.pg_control_system()'); system = cursor.fetchone()[0]
        cursor.execute('SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=current_database()'); oid = cursor.fetchone()[0]
    return DatabaseIdentity(connection.info.host, connection.info.port, connection.info.dbname, connection.info.user, system, oid)


def _contracts(cluster, tools):
    from dataclasses import replace
    from agent_market.storage_adapter import open_store
    from agent_market.postgres_archive_provider import ArchiveCredential, ExplicitArchiveCredentialProvider, ArchiveProviderDenied
    from agent_market.postgres_restore_guard import RestoreOwnerAuthority, RestoreGateDenied, WRITER_LOCK, exclusive
    from agent_market import postgres_operational_archive as api
    from agent_market.application_store_postgres import ApplicationStoreError
    from agent_market.workflows import WorkflowRuntime
    connection = _connect(cluster); checks = {}; root = Path(cluster['root'])
    def sql(current, statement, parameters=()):
        with current.cursor() as cursor:
            cursor.execute(statement, parameters)
            return cursor.fetchall() if cursor.description else []
    def rejected(action, exceptions=(ValueError,), code=None):
        try: action()
        except exceptions as error: return code is None or getattr(error, 'code', None) == code
        return False
    def provider(password=PASSWORD, *, seconds=120):
        return ExplicitArchiveCredentialProvider(lambda identity, purpose: ArchiveCredential(identity, purpose, time.time()+seconds, password))
    def target(database):
        # Database names are fixed fixture constants, never caller input.
        if database not in ('archive_success','archive_conflict','archive_failed','archive_expired','archive_corrupt','archive_copy'):
            raise AssertionError('Unreviewed fixture database')
        sql(connection, 'CREATE DATABASE ' + database)
        current = _connect(cluster, database)
        return current, _identity(current)
    ring = root / 'artifact-keys.json'
    ring.write_text(json.dumps({'profile':'private-artifact-keys-v1','active_signing':'fixture-a','active_encryption':'fixture-a','allow_legacy':True,
        'keys':[{'id':'fixture-a','key':base64.b64encode(b'a'*32).decode(),'verify_until':time.time()+3600,'revoked':False}]})); ring.chmod(0o600)
    os.environ['AGENT_PRIVATE_ARTIFACT_KEYRING'] = str(ring)
    store = open_store('postgresql', connection=connection, initialize=True, workflow_key=KEY)
    runtime = WorkflowRuntime(store)
    definition_id = store.create_workflow({'name':'Synthetic archived workflow','nodes':[{'id':'start','type':'trigger','name':'Start','data':{}}],'edges':[]})
    runtime.launch = lambda _: None
    pending = runtime.submit(store.get_workflow(definition_id))
    sql(connection, "INSERT INTO workflow_result_outbox(id,run_id,destination_id,status,created) VALUES('archive-pending-outbox',%s,'fixture-destination','pending',%s)", (pending['run_id'],time.time()))
    store.set_credential('SYNTHETIC_GENERAL_ARCHIVE','synthetic-private-value','fixture')
    ciphertext = sql(connection, 'SELECT key_value FROM platform_credentials WHERE key_name=%s', ('SYNTHETIC_GENERAL_ARCHIVE',))[0][0]
    require(sql(connection,"SELECT to_regclass('public.workspace_sandbox_payment_intents') IS NOT NULL")==[(True,)],'current sandbox schema fixture')
    require(sql(connection,"SELECT to_regclass('public.evidence_rollup_withdrawals') IS NOT NULL")==[(True,)],'current evidence schema fixture')
    sql(connection,"INSERT INTO workspace_sandbox_payment_intents VALUES('wspi_synthetic_archive','synthetic-workspace','synthetic-event',1,'{}','synthetic-unchanged')")
    sql(connection,"INSERT INTO evidence_rollup_withdrawals VALUES('synthetic-workspace','workspace','synthetic-source',1,'{}','synthetic-unchanged')")
    # Require real tool authentication in this owned fixture. The caller's
    # already authenticated connection stays open; pg_dump must use its lease.
    sql(connection, "ALTER ROLE postgres PASSWORD 'synthetic-native-archive-pass-42'")
    hba = root/'data'/'pg_hba.conf'; hba.write_text('local all all scram-sha-256\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n'); hba.chmod(0o600)
    sql(connection, 'SELECT pg_reload_conf()')
    time.sleep(.1)
    source_identity = _identity(connection)
    try:
        checks['general_api_wrong_identity_refused_before_archive'] = rejected(lambda: api.backup(connection,root/'wrong-identity',identity=replace(source_identity,database_oid=1),credentials=provider(),workflow_key=KEY,tools=tools), (ArchiveProviderDenied,))
        checks['expired_credential_refused_without_archive'] = rejected(lambda: api.backup(connection,root/'expired',identity=source_identity,credentials=provider(seconds=-1),workflow_key=KEY,tools=tools), (ArchiveProviderDenied,)) and not (root/'expired').exists()
        checks['real_wrong_tool_password_fails_without_artifact'] = rejected(lambda: api.backup(connection,root/'wrong-password',identity=source_identity,credentials=provider('synthetic-wrong-password'),workflow_key=KEY,tools=tools), (api.OperationalArchiveDenied,), 'archive_tool_failed') and not (root/'wrong-password').exists()
        archive = root/'general-archive'
        manifest = api.backup(connection,archive,identity=source_identity,credentials=provider(),workflow_key=KEY,tools=tools)
        checks['general_api_explicit_authenticated_backup_succeeds'] = (manifest['encrypted'] is True and not manifest['operating_backup_ready']
            and manifest['source_identity']==source_identity.fingerprint() and {p.name for p in archive.iterdir()}=={'application.dump.sealed','manifest.json'})
        checks['backup_does_not_export_keys_or_passwords'] = (not manifest['workflow_key_included'] and not manifest['artifact_keys_included']
            and all(PASSWORD.encode() not in path.read_bytes() and KEY not in path.read_bytes() for path in archive.iterdir()))
        checks['backup_retains_caller_connection_and_source_controls'] = not connection.closed and sql(connection,'SELECT invoke_enabled+workflow_enabled+delivery_enabled FROM execution_controls')[0][0]==3
        conflict, conflict_identity = target('archive_conflict')
        try:
            sql(connection, 'SELECT pg_advisory_lock(%s)',(WRITER_LOCK,))
            # Advisory locks are database-scoped. Hold the target's writer lock
            # on another connection instead of relying on a source lock.
            competitor = _connect(cluster, 'archive_conflict')
            try:
                sql(competitor,'SELECT pg_advisory_lock(%s)',(WRITER_LOCK,))
                checks['exclusive_restore_conflict_refused'] = rejected(lambda: api.restore(conflict,archive,identity=conflict_identity,credentials=provider(),workflow_key=KEY,tools=tools), (RestoreGateDenied,), 'restore_ownership_conflict')
            finally:
                sql(competitor,'SELECT pg_advisory_unlock(%s)',(WRITER_LOCK,)); competitor.close()
                sql(connection,'SELECT pg_advisory_unlock(%s)',(WRITER_LOCK,))
            checks['conflict_does_not_create_control_or_application_tables'] = sql(conflict,"SELECT to_regnamespace('agent_restore_control') IS NULL")==[(True,)]
        finally: conflict.close()
        corrupt, corrupt_identity = target('archive_corrupt')
        try:
            bad = root/'corrupt-archive'; shutil.copytree(archive,bad)
            encoded=bad/'application.dump.sealed'; data=encoded.read_bytes(); encoded.write_bytes(data[:-1]+bytes([data[-1]^1]))
            checks['corrupt_archive_refused_before_target_claim'] = rejected(lambda: api.restore(corrupt,bad,identity=corrupt_identity,credentials=provider(),workflow_key=KEY,tools=tools), (api.OperationalArchiveDenied,), 'archive_authentication_failed')
            checks['corrupt_archive_leaves_target_unclaimed'] = sql(corrupt,"SELECT to_regnamespace('agent_restore_control') IS NULL")==[(True,)]
        finally: corrupt.close()
        restored, restored_identity = target('archive_success')
        try:
            original_quarantine = api.quarantine
            def inspect_during_quarantine(current):
                other = _connect(cluster,'archive_success')
                try:
                    checks['pending_gate_denies_unrelated_store_attach'] = rejected(lambda: open_store('postgresql',connection=other,workflow_key=KEY), (ApplicationStoreError,RestoreGateDenied))
                    checks['pending_gate_denies_initialize_bypass'] = rejected(lambda: open_store('postgresql',connection=other,initialize=True,workflow_key=KEY), (ApplicationStoreError,RestoreGateDenied))
                    checks['internal_restore_scope_cannot_cross_connections'] = checks['pending_gate_denies_unrelated_store_attach']
                    checks['live_restore_owner_excludes_competitor'] = rejected(lambda: _claim_other(other), (RestoreGateDenied,), 'restore_ownership_conflict')
                finally: other.close()
                return original_quarantine(current)
            def _claim_other(other):
                with exclusive(other): pass
            api.quarantine = inspect_during_quarantine
            try: result=api.restore(restored,archive,identity=restored_identity,credentials=provider(),workflow_key=KEY,tools=tools)
            finally: api.quarantine=original_quarantine
            checks['restore_unknown_execution_and_outbox_never_replay'] = (sql(restored,'SELECT execution_outcome FROM workflow_runs WHERE id=%s',(pending['run_id'],))==[('unknown',)]
                and sql(restored,'SELECT status FROM workflow_result_outbox')==[('unknown',)] and result['automatic_replay'] is False)
            checks['restored_target_remains_quarantined_until_independent_review'] = (result['deployment_state']=='quarantined'
                and rejected(lambda: open_store('postgresql',connection=restored,workflow_key=KEY),(ApplicationStoreError,RestoreGateDenied)))
            checks['vault_ciphertext_preserved_without_decrypt_or_sweep'] = sql(restored,'SELECT key_value FROM platform_credentials WHERE key_name=%s',('SYNTHETIC_GENERAL_ARCHIVE',))==[(ciphertext,)]
            checks['restored_sandbox_intents_permanently_blocked'] = sql(restored,'SELECT id FROM workspace_sandbox_payment_restore_blocks')==[('wspi_synthetic_archive',)]
            checks['evidence_withdrawal_tombstones_preserved_unchanged'] = sql(restored,'SELECT payload,signature FROM evidence_rollup_withdrawals')==[('{}','synthetic-unchanged')]
            checks['same_target_cannot_be_overwritten'] = rejected(lambda: api.restore(restored,archive,identity=restored_identity,credentials=provider(),workflow_key=KEY,tools=tools),(api.OperationalArchiveDenied,), 'new_empty_target_required')
            owner={'active':True}
            authority=RestoreOwnerAuthority(b'o'*32,verifier=lambda review,proof: 'external-current-owner' if owner['active'] and proof=='fresh-owner-proof' else None)
            review=api.review(restored,identity=restored_identity,credentials=provider(),workflow_key=KEY)
            receipt=authority.issue(review,'fresh-owner-proof')
            owner['active']=False
            checks['withdrawn_current_owner_proof_denies_reapproval'] = rejected(lambda: api.approve_deployment(restored,identity=restored_identity,credentials=provider(),workflow_key=KEY,authority=authority,receipt=receipt,proof='fresh-owner-proof'),(RestoreGateDenied,), 'current_owner_proof_required')
            owner['active']=True
            wrong=authority.issue({**review,'challenge':'old-backup-challenge'},'fresh-owner-proof')
            checks['old_or_wrong_restore_challenge_cannot_reapprove'] = rejected(lambda: api.approve_deployment(restored,identity=restored_identity,credentials=provider(),workflow_key=KEY,authority=authority,receipt=wrong,proof='fresh-owner-proof'),(RestoreGateDenied,), 'current_owner_proof_required')
            now=time.time()
            with patch('agent_market.postgres_restore_guard.time.time',return_value=now+301):
                checks['expired_owner_receipt_denies_reapproval'] = rejected(lambda: api.approve_deployment(restored,identity=restored_identity,credentials=provider(),workflow_key=KEY,authority=authority,receipt=receipt,proof='fresh-owner-proof'),(RestoreGateDenied,), 'current_owner_proof_required')
            leases=[]
            expiring_provider=ExplicitArchiveCredentialProvider(lambda identity,purpose: _capture_lease(identity,purpose))
            def _capture_lease(identity,purpose):
                lease=ArchiveCredential(identity,purpose,time.time()+120,PASSWORD); leases.append(lease); return lease
            original_verifier=authority.verifier
            def expires_during_review(current_review,proof):
                leases[-1].expires=time.time()-1
                return original_verifier(current_review,proof)
            authority.verifier=expires_during_review
            try:
                checks['approval_lease_expiry_during_live_proof_keeps_gate_closed'] = rejected(lambda: api.approve_deployment(restored,identity=restored_identity,credentials=expiring_provider,workflow_key=KEY,authority=authority,receipt=receipt,proof='fresh-owner-proof'),(ArchiveProviderDenied,), 'archive_credential_expired')
            finally: authority.verifier=original_verifier
            approved=api.approve_deployment(restored,identity=restored_identity,credentials=provider(),workflow_key=KEY,authority=authority,receipt=receipt,proof='fresh-owner-proof')
            checks['wrong_workflow_key_cannot_use_shared_artifact_signature'] = rejected(lambda: open_store('postgresql',connection=restored,workflow_key=b'x'*32),(ApplicationStoreError,RestoreGateDenied))
            attached=open_store('postgresql',connection=restored,workflow_key=KEY)
            try:
                checks['fresh_live_owner_approval_allows_inspection_only'] = approved['deployment_state']=='approved' and sql(restored,'SELECT invoke_enabled+workflow_enabled+delivery_enabled FROM execution_controls')==[(0,)]
                checks['owner_approval_does_not_revive_old_run_or_delivery'] = sql(restored,'SELECT execution_outcome FROM workflow_runs WHERE id=%s',(pending['run_id'],))==[('unknown',)] and sql(restored,'SELECT status FROM workflow_result_outbox')==[('unknown',)]
            finally: attached.close()
            checks['approval_is_cas_bound_and_not_replayable'] = rejected(lambda: api.approve_deployment(restored,identity=restored_identity,credentials=provider(),workflow_key=KEY,authority=authority,receipt=receipt,proof='fresh-owner-proof'),(RestoreGateDenied,))
            checks['restore_and_approval_keep_signed_audit_history'] = sql(restored,'SELECT COUNT(*) FROM agent_restore_control.events')==[(3,)]
            approved_row=sql(restored,'SELECT state,generation,revision,payload,signature FROM agent_restore_control.gate WHERE id=1')[0]
        finally: restored.close()
        copied,copied_identity=target('archive_copy')
        try:
            from agent_market.postgres_restore_guard import CONTROL_DDL
            for statement in CONTROL_DDL: sql(copied,statement)
            sql(copied,'INSERT INTO agent_restore_control.gate VALUES(1,%s,%s,%s,%s,%s)',approved_row)
            checks['copied_approved_gate_cannot_admit_another_database'] = rejected(lambda: open_store('postgresql',connection=copied,initialize=True,workflow_key=KEY),(ApplicationStoreError,RestoreGateDenied),'restore_identity_mismatch')
        finally: copied.close()
        failed,failed_identity=target('archive_failed')
        try:
            original_quarantine=api.quarantine
            def fail_after_write(current):
                current._execute('UPDATE execution_controls SET invoke_enabled=0').close()
                raise RuntimeError('Synthetic quarantine rollback')
            api.quarantine=fail_after_write
            try:
                checks['quarantine_failure_is_not_reported_as_success'] = rejected(lambda: api.restore(failed,archive,identity=failed_identity,credentials=provider(),workflow_key=KEY,tools=tools),(RuntimeError,))
            finally: api.quarantine=original_quarantine
            checks['quarantine_transaction_failure_rolls_back_its_writes'] = sql(failed,'SELECT invoke_enabled FROM execution_controls')==[(1,)]
            checks['failed_quarantine_keeps_durable_attach_gate_closed'] = sql(failed,'SELECT state FROM agent_restore_control.gate')==[('failed',)] and rejected(lambda: open_store('postgresql',connection=failed,workflow_key=KEY),(ApplicationStoreError,RestoreGateDenied))
        finally: failed.close()
        expired,expired_identity=target('archive_expired')
        try:
            original_run=api._run
            def expire_after_tool(tool,credential,args):
                original_run(tool,credential,args); credential.expires=time.time()-1
            api._run=expire_after_tool
            try:
                checks['expired_inflight_credential_never_returns_ready_target'] = rejected(lambda: api.restore(expired,archive,identity=expired_identity,credentials=provider(),workflow_key=KEY,tools=tools),(ArchiveProviderDenied,), 'archive_credential_expired')
            finally: api._run=original_run
            checks['expired_restore_retains_closed_gate_after_tool_commit'] = sql(expired,'SELECT state FROM agent_restore_control.gate')==[('failed',)] and rejected(lambda: open_store('postgresql',connection=expired,initialize=True,workflow_key=KEY),(ApplicationStoreError,RestoreGateDenied))
        finally: expired.close()
        require(all(value is True for value in checks.values()),'general archive contracts: '+json.dumps(checks,sort_keys=True))
        return checks
    finally:
        store.close(); connection.close()


def _worker():
    config=json.loads(sys.stdin.read(8192)); cluster=config['cluster']; root=Path(cluster['root'])
    require(root.parent==Path('/private/tmp') and root.name.startswith('a2a-adapter-pg-') and cluster['socket']==str(root/'socket'),'owned fixture')
    _guard(cluster)
    print(json.dumps({'checks':_contracts(cluster,config['tools'])},sort_keys=True,allow_nan=False))


def rehearse():
    driver=_driver(); commands=_tools()
    tools={name:str(Path(commands['pg_ctl']).parent/name) for name in ('pg_dump','pg_restore')}
    with _private_cluster(commands) as fixture:
        cluster={key:fixture[key] for key in ('root','socket')}; environment=dict(fixture['environment'])
        environment.update(PYTHONDONTWRITEBYTECODE='1',REDIS_HOST='127.0.0.1',REDIS_PORT='9')
        environment['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        result=subprocess.run([sys.executable,'-B','-c','from scripts.rehearse_postgres_operational_archive import _worker; _worker()'],
            env=environment,input=json.dumps({'cluster':cluster,'tools':tools}),text=True,capture_output=True,timeout=150)
        if result.returncode: raise RuntimeError('Synthetic general archive contract failed: '+result.stderr[-6000:])
        value=json.loads(result.stdout)
    return {'profile':PROFILE,**value,'operating_backup_ready':False,'operating_actions':0,'external_calls':0,'temporary_cluster_removed':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False); parser.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if not args.run: parser.error('--run is required')
    print(json.dumps(rehearse(),sort_keys=True,allow_nan=False)); return 0


if __name__=='__main__': raise SystemExit(main())

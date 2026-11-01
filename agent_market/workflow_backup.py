"""Explicit online snapshots and fail-closed restoration to a new SQLite path."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import tempfile
from contextlib import closing

from .private_artifact_keys import ArtifactKeys, ArtifactSigner, ArtifactCipher, ArtifactKeyError


def digest(path):
    with open(path,'rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def exclusive(path,data=b''):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as target:target.write(data)


def read_key(path):
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    with os.fdopen(fd,'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):raise ValueError('Invalid key file.')
        key=source.read(33)
        if len(key)!=32:raise ValueError('Invalid key file.')
        return key


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=5)


def copy_database(source,target):
    deadline=time.monotonic()+30
    def progress(*_):
        if time.monotonic()>deadline:raise TimeoutError('Snapshot time limit reached.')
    source.backup(target,pages=256,progress=progress,sleep=.01)
    if target.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('Snapshot integrity check failed.')


def backup(source_path,directory,*,encrypt=False,retention_days=30):
    if type(encrypt) is not bool or type(retention_days) is not int or not 1<=retention_days<=365:raise ValueError('Invalid backup policy.')
    keys=ArtifactKeys();cipher=ArtifactCipher('workflow-backup-v2',keys)
    if encrypt and not cipher.configured:raise ArtifactKeyError('An explicit authenticated encryption key is required.')
    directory=Path(directory);directory.mkdir(mode=0o700,exist_ok=False)
    try:
        return _write_backup(source_path,directory,encrypt,retention_days,keys,cipher)
    except Exception:
        # This directory was created exclusively by this invocation; never
        # traverse or recursively delete an existing operator-owned directory.
        for name in ('catalog.sqlite3','catalog.sqlite3-journal','catalog.sqlite3-wal','catalog.sqlite3-shm','updates-key','catalog.sqlite3.sealed','updates-key.sealed','manifest.json'):
            (directory/name).unlink(missing_ok=True)
        directory.rmdir()
        raise


def _write_backup(source_path,directory,encrypt,retention_days,keys,cipher):
    destination=directory/'catalog.sqlite3';exclusive(destination)
    with closing(readonly(source_path)) as source,closing(sqlite3.connect(destination)) as target:copy_database(source,target)
    manifest={'version':2 if encrypt else 1,'database_sha256':digest(destination),'key_included':False,'execution_restore':'quarantine_all_unfinished_and_pause_controls',
              'created':time.time(),'retention_days':retention_days,'automatic_deletion':False,'encrypted':encrypt,
              'artifact_key_policy':keys.summary()}
    manifest['review_delete_after']=manifest['created']+retention_days*86400
    key_path=Path(str(source_path)+'.updates-key')
    if key_path.exists() and not os.environ.get('AGENT_UPDATES_KEY'):
        exclusive(directory/'updates-key',read_key(key_path));manifest['key_included']=True;manifest['key_sha256']=digest(directory/'updates-key')
    if encrypt:
        for name in ('catalog.sqlite3','updates-key'):
            path=directory/name
            if not path.exists():continue
            if path.stat().st_size>134217728:raise ValueError('Encrypted backup artifact exceeds the bounded size limit.')
            encoded=cipher.seal(path.read_bytes(),{'profile':'workflow-backup-v2','artifact':name,'created':manifest['created']})
            sealed=directory/(name+'.sealed');exclusive(sealed,encoded);path.unlink()
            manifest['database_sha256' if name=='catalog.sqlite3' else 'key_sha256']=digest(sealed)
    if keys.config is not None:
        manifest['manifest_signature']=ArtifactSigner(b'\0'*32,'workflow-backup-manifest-v2',keys).sign(manifest)
    exclusive(directory/'manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
    return manifest


def quarantine(db):
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    now=time.time()
    if 'workspace_admin_commands' in tables:
        db.execute("UPDATE workspace_admin_commands SET status='restore_review_required',revision=revision+1 WHERE status='pending'")
        db.execute("UPDATE workspace_admin_outbox SET status='quarantined',fence=fence+1,lease_until=0")
        db.execute('UPDATE workspace_admin_disclosures SET revoked=?,revision=revision+1 WHERE revoked IS NULL',(now,))
    if 'admin_reviewed_commands' in tables:
        db.execute("UPDATE admin_reviewed_commands SET status='restore_review_required',revision=revision+1 WHERE status IN ('pending','approved')")
    if 'workflow_runs' in tables:
        columns={r[1] for r in db.execute('PRAGMA table_info(workflow_runs)')}
        for name,declaration in (('execution_outcome','TEXT'),('owner','TEXT'),('fence','INTEGER NOT NULL DEFAULT 0'),('lease_until','REAL NOT NULL DEFAULT 0')):
            if name not in columns:db.execute(f'ALTER TABLE workflow_runs ADD COLUMN {name} {declaration}')
        db.execute("UPDATE workflow_runs SET status='failed',execution_outcome='unknown',error='Restored execution requires review; automatic replay is disabled.',result=NULL,finished=?,owner=NULL,fence=fence+1,lease_until=0 WHERE status IN ('queued','running')",(now,))
    if 'customer_credit_accounts' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS customer_credit_restore_blocks(customer_id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO customer_credit_restore_blocks SELECT customer_id FROM customer_credit_accounts')
    if 'workflow_result_outbox' in tables:
        db.execute("UPDATE workflow_result_outbox SET status='unknown',owner=NULL,fence=fence+1,lease_until=0,finished=? WHERE status IN ('pending','claimed','dispatched')",(now,))
        for row in db.execute("SELECT run_id FROM workflow_result_outbox WHERE status='unknown'").fetchall():
            from .workflow_persistence import DurableRuns
            DurableRuns.distribution(db,row[0],{'status':'UNKNOWN'})
    if 'workflow_manual_deliveries' in tables:
        db.execute("UPDATE workflow_manual_deliveries SET status='unknown',owner=NULL,fence=fence+1,lease_until=0,finished=? WHERE status IN ('pending','claimed','dispatched')",(now,))
    if 'workflow_deliveries' in tables:db.execute("UPDATE workflow_deliveries SET status='uncertain',finished=?,error='Restored delivery requires review.' WHERE status IN ('sending','prepared')",(now,))
    if 'workflow_schedules' in tables:db.execute('UPDATE workflow_schedules SET enabled=0,next_run=NULL,event_hash=NULL,event_sealed=NULL')
    if 'workflow_delivery_grants' in tables:db.execute('UPDATE workflow_delivery_grants SET revoked=? WHERE revoked IS NULL',(now,))
    if 'workflow_destinations' in tables:db.execute("UPDATE workflow_destinations SET state='revoked',sealed=NULL,code_hash=NULL WHERE state IN ('verified','pending')")
    if 'workflow_apps' in tables:db.execute('UPDATE workflow_apps SET active=0')
    if 'workflow_deployment_grants' in tables:
        db.execute('UPDATE workflow_deployment_grants SET active=0,revision=revision+1,revoked=?',(now,))
    if 'workflow_publication_grants' in tables:
        db.execute('UPDATE workflow_publication_grants SET active=0,revision=revision+1,revoked=?',(now,))
    if 'workflow_connection_deployments' in tables:
        db.execute('UPDATE workflow_connection_deployments SET active=0,revision=revision+1,revoked=?',(now,))
    if 'workflow_connection_automation' in tables:
        db.execute('UPDATE workflow_connection_automation SET active=0,revision=revision+1,revoked=?,next_run=NULL',(now,))
    if 'workflow_fallback_control' in tables:db.execute('UPDATE workflow_fallback_control SET enabled=0,revision=revision+1,updated=?',(now,))
    # Signed policy rows cannot be edited on restore; removing policies/proofs
    # requires fresh approval, shadow verification and explicit canary admission.
    if 'workflow_fallback_policies' in tables:db.execute('DELETE FROM workflow_fallback_policies')
    if 'workflow_fallback_shadow' in tables:db.execute('DELETE FROM workflow_fallback_shadow')
    if 'workflow_product_templates' in tables:db.execute('UPDATE workflow_product_templates SET revoked=? WHERE revoked IS NULL',(now,))
    if 'workflow_io_profiles' in tables:db.execute('UPDATE workflow_io_profiles SET revoked=? WHERE revoked IS NULL',(now,))
    if 'execution_controls' in tables:
        db.execute('UPDATE execution_controls SET invoke_enabled=0,workflow_enabled=0,delivery_enabled=0,revision=revision+1,updated=?',(now,))
        if 'execution_control_events' in tables:db.execute('INSERT INTO execution_control_events SELECT revision,0,0,0,0,? FROM execution_controls WHERE id=1',(now,))
    if 'agent_task_watches' in tables:db.execute("UPDATE agent_task_watches SET state='expired',sealed=NULL,verified_at=NULL,revoked_at=?,task='' WHERE state IN ('active','pending_verification','paused')",(now,))
    if 'agent_task_events' in tables:db.execute("UPDATE agent_task_events SET status='failed',payload='{}',error='restore_review_required' WHERE status IN ('pending','sending')")
    if 'admin_sessions' in tables:db.execute('DELETE FROM admin_sessions')
    # A restored membership may predate withdrawal. Pause private workspaces and
    # tombstone membership revisions; a new login never revives old access.
    if 'organization_workspaces' in tables:
        db.execute('UPDATE organization_workspaces SET active=0,revision=revision+1,updated=?',(now,))
    if 'workspace_memberships' in tables:
        db.execute('UPDATE workspace_memberships SET active=0,revision=revision+1,updated=?',(now,))
    # Private run tickets never survive a snapshot restore. Signed run payloads
    # remain intact; private reads project unfinished revoked tickets as unknown.
    if 'workspace_private_tickets' in tables:
        db.execute('UPDATE workspace_private_tickets SET revoked=? WHERE revoked IS NULL',(now,))
    if 'customer_oidc_flows' in tables:
        db.execute('UPDATE customer_oidc_flows SET consumed=? WHERE consumed IS NULL',(now,))
    if 'customer_sessions' in tables:
        db.execute('UPDATE customer_sessions SET revoked=? WHERE revoked IS NULL',(now,))
    if 'customer_bff_tokens' in tables:
        db.execute('UPDATE customer_bff_tokens SET revoked=? WHERE revoked IS NULL',(now,))
    if 'customer_workspace_links' in tables:
        db.execute('UPDATE customer_workspace_links SET active=0,revision=revision+1,updated=?',(now,))
    # These are disposable capabilities, not execution or reconciliation records.
    for table in ('workspace_app_codes','workspace_app_tokens'):
        if table in tables:db.execute('DELETE FROM '+table)
    if 'workspace_executable_releases' in tables or 'workspace_release_deployments' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_release_restore_blocks(authority_id TEXT PRIMARY KEY)')
        if 'workspace_executable_releases' in tables:
            db.execute('INSERT OR IGNORE INTO workspace_release_restore_blocks SELECT id FROM workspace_executable_releases')
        if 'workspace_release_deployments' in tables:
            db.execute('INSERT OR IGNORE INTO workspace_release_restore_blocks SELECT app_id FROM workspace_release_deployments')
    if 'workspace_restore_reviews' in tables:
        db.execute('UPDATE workspace_restore_reviews SET consumed=? WHERE consumed IS NULL',(now,))
    if 'customer_organizations' in tables:
        db.execute('UPDATE customer_organizations SET active=0,revision=revision+1,archived=?',(now,))
    if 'customer_organization_invitations' in tables:
        db.execute("UPDATE customer_organization_invitations SET status='revoked',revision=revision+1,resolved=? WHERE status='pending'",(now,))
    if 'customer_recovery_policies' in tables or 'customer_recovery_requests' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS customer_recovery_blocks(id TEXT PRIMARY KEY)')
        if 'customer_recovery_policies' in tables:
            db.execute("INSERT OR IGNORE INTO customer_recovery_blocks SELECT workspace_id||':'||revision FROM customer_recovery_policies")
        if 'customer_recovery_requests' in tables:
            db.execute('INSERT OR IGNORE INTO customer_recovery_blocks SELECT id FROM customer_recovery_requests')
    if 'stripe_sandbox_orders' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS stripe_sandbox_restore_blocks(order_id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO stripe_sandbox_restore_blocks SELECT id FROM stripe_sandbox_orders')
    if 'workspace_meter_policies' in tables:
        # Signed authorization cannot be edited into a new valid policy during
        # restore. Historical operation/attempt/entry receipts remain intact.
        db.execute('DELETE FROM workspace_meter_policies')
    if 'workspace_typed_flows' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_typed_flow_restore_blocks(id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO workspace_typed_flow_restore_blocks SELECT id FROM workspace_typed_flows')
    if 'workspace_provider_agreements' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_agreement_restore_blocks(id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO workspace_agreement_restore_blocks SELECT id FROM workspace_provider_agreements')
    if 'workspace_sandbox_payment_intents' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_sandbox_payment_restore_blocks(id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO workspace_sandbox_payment_restore_blocks SELECT id FROM workspace_sandbox_payment_intents')
    if 'provider_claim_transfers' in tables:
        # Signed offers are retained unchanged, but a permanent block prevents
        # pre-restore invitations from becoming a new endpoint-control challenge.
        db.execute('CREATE TABLE IF NOT EXISTS provider_claim_transfer_restore_blocks(id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO provider_claim_transfer_restore_blocks SELECT id FROM provider_claim_transfers')
    if 'provider_control_claims' in tables:
        db.execute('UPDATE provider_control_claims SET revoked=? WHERE revoked IS NULL',(now,))
    # Preserve signed history while permanently retiring pre-restore authority.
    # Encrypted evidence bodies are erased; old consent cannot re-ingest them.
    if 'reliability_consents' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS reliability_restore_blocks(authority_id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO reliability_restore_blocks SELECT id FROM reliability_consents')
    if 'reliability_operating_qualifications' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS reliability_restore_blocks(authority_id TEXT PRIMARY KEY)')
        db.execute("INSERT OR IGNORE INTO reliability_restore_blocks SELECT 'operating:'||workspace_id||':'||resource_id||':'||revision FROM reliability_operating_qualifications")
    if 'workspace_remote_tasks' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_remote_task_restore_blocks(id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO workspace_remote_task_restore_blocks SELECT id FROM workspace_remote_tasks')
    if 'reliability_sources' in tables:
        db.execute('DELETE FROM reliability_sources')
    if any(table in tables for table in ('reliability_eval_controls','reliability_eval_plans','reliability_eval_jobs','reliability_route_policies')):
        db.execute('CREATE TABLE IF NOT EXISTS reliability_controls_restore_blocks(authority_id TEXT PRIMARY KEY)')
        if 'reliability_eval_controls' in tables:
            db.execute("INSERT OR IGNORE INTO reliability_controls_restore_blocks SELECT 'eval_control:'||workspace_id||':'||json_extract(payload,'$.revision') FROM reliability_eval_controls")
        if 'reliability_eval_plans' in tables:
            db.execute("INSERT OR IGNORE INTO reliability_controls_restore_blocks SELECT 'eval_plan:'||workspace_id||':'||revision FROM reliability_eval_plans")
        if 'reliability_eval_jobs' in tables:
            db.execute("INSERT OR IGNORE INTO reliability_controls_restore_blocks SELECT 'eval_job:'||id FROM reliability_eval_jobs")
        if 'reliability_route_policies' in tables:
            db.execute("INSERT OR IGNORE INTO reliability_controls_restore_blocks SELECT 'routing_policy:'||workspace_id||':'||revision FROM reliability_route_policies")
    if 'workspace_factory_reviews' in tables or 'workspace_sdk_policies' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_expansion_restore_blocks(authority_id TEXT PRIMARY KEY)')
        if 'workspace_factory_reviews' in tables:
            db.execute('INSERT OR IGNORE INTO workspace_expansion_restore_blocks SELECT id FROM workspace_factory_reviews')
        if 'workspace_sdk_policies' in tables:
            db.execute("INSERT OR IGNORE INTO workspace_expansion_restore_blocks SELECT json_extract(payload,'$.id')||':'||revision FROM workspace_sdk_policies")
    if 'workspace_support_cases' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_support_restore_blocks(authority_id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO workspace_support_restore_blocks SELECT id FROM workspace_support_cases')
    if 'workspace_machine_subscriptions' in tables or 'workspace_machine_update_events' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_machine_update_restore_blocks(id TEXT PRIMARY KEY)')
        if 'workspace_machine_subscriptions' in tables:
            db.execute('INSERT OR IGNORE INTO workspace_machine_update_restore_blocks SELECT id FROM workspace_machine_subscriptions')
        if 'workspace_machine_update_events' in tables:
            db.execute('INSERT OR IGNORE INTO workspace_machine_update_restore_blocks SELECT id FROM workspace_machine_update_events')
    if 'workspace_machine_receivers' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_machine_receiver_restore_blocks(id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO workspace_machine_receiver_restore_blocks SELECT id FROM workspace_machine_receivers')
    if 'reliability_research_manifests' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS reliability_research_restore_blocks(manifest_id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO reliability_research_restore_blocks SELECT id FROM reliability_research_manifests')
    if 'reliability_admission_policies' in tables or 'reliability_admissions' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS reliability_admission_restore_blocks(authority_id TEXT PRIMARY KEY)')
        if 'reliability_admission_policies' in tables:
            db.execute("INSERT OR IGNORE INTO reliability_admission_restore_blocks SELECT workspace_id||':'||revision FROM reliability_admission_policies")
        if 'reliability_admissions' in tables:
            db.execute('INSERT OR IGNORE INTO reliability_admission_restore_blocks SELECT id FROM reliability_admissions')
    if 'workspace_protocol_reports' in tables:
        db.execute('CREATE TABLE IF NOT EXISTS workspace_protocol_restore_blocks(id TEXT PRIMARY KEY)')
        db.execute('INSERT OR IGNORE INTO workspace_protocol_restore_blocks SELECT id FROM workspace_protocol_reports')
    if 'reliability_circuit_states' in tables:
        from .reliability_circuit import quarantine_circuits
        quarantine_circuits(db)


def restore(directory,target_path):
    directory=Path(directory);target_path=Path(target_path)
    raw=(directory/'manifest.json').read_bytes()
    if len(raw)>32768:raise ValueError('Invalid backup manifest.')
    def exact(pairs):
        value={}
        for name,item in pairs:
            if name in value:raise ValueError('Invalid backup manifest.')
            value[name]=item
        return value
    manifest=json.loads(raw,object_pairs_hook=exact)
    keys=ArtifactKeys();signature=manifest.pop('manifest_signature',None)
    if signature is not None:
        if not ArtifactSigner(b'\0'*32,'workflow-backup-manifest-v2',keys).verify(manifest,signature):raise ValueError('Backup manifest authentication failed.')
    elif manifest.get('version')==2 or keys.config and not keys.config['allow_legacy']:
        raise ValueError('An authenticated backup manifest is required.')
    encrypted=manifest.get('version')==2
    if manifest.get('version') not in (1,2) or encrypted != manifest.get('encrypted',False):raise ValueError('Invalid backup profile.')
    database=directory/('catalog.sqlite3.sealed' if encrypted else 'catalog.sqlite3')
    if digest(database)!=manifest['database_sha256']:raise ValueError('Backup checksum mismatch.')
    cipher=ArtifactCipher('workflow-backup-v2',keys)
    def content(name):
        path=directory/(name+'.sealed' if encrypted else name)
        if path.stat().st_size>(180000000 if encrypted else 134217728):raise ValueError('Backup artifact exceeds the bounded size limit.')
        value=path.read_bytes()
        return cipher.open(value,{'profile':'workflow-backup-v2','artifact':name,'created':manifest['created']}) if encrypted else value
    key=None
    if manifest['key_included']:
        path=directory/('updates-key.sealed' if encrypted else 'updates-key')
        if digest(path)!=manifest['key_sha256']:raise ValueError('Backup key checksum mismatch.')
        key=content('updates-key') if encrypted else read_key(path)
        if len(key)!=32:raise ValueError('Invalid backup key.')
    decrypted=content('catalog.sqlite3') if encrypted else None
    inventory_path=Path(str(target_path)+'.restored-inventory.json')
    if target_path.exists() or Path(str(target_path)+'.updates-key').exists() or inventory_path.exists():raise ValueError('Restore requires new database, key and inventory paths.')
    exclusive(target_path)
    if key:exclusive(str(target_path)+'.updates-key',key)
    with tempfile.TemporaryDirectory(prefix='workflow-restore-') as temporary:
        source_path=database
        if encrypted:
            source_path=Path(temporary)/'authenticated.sqlite3';exclusive(source_path,decrypted)
        with closing(readonly(source_path)) as source,closing(sqlite3.connect(target_path)) as target:
            copy_database(source,target)
            inventory=restored_inventory(target)
            with target:quarantine(target)
            if target.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('Restored integrity check failed.')
    exclusive(inventory_path,(json.dumps(inventory,indent=2)+'\n').encode())
    return {'integrity':'ok','unfinished_execution':'quarantined','runtime_controls':'paused','key_included':bool(key),'inventory_file':inventory_path.name,'authenticated_encryption':encrypted,'manifest_authenticated':signature is not None}


def restored_inventory(db):
    """Private IDs/states only; no old key, endpoint, principal or input export."""
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    specs={
        'workflow_apps':('id,workflow_id,active','active=1','Reissue a deployment key and review origins.'),
        'workflow_deployment_grants':('id,app_id,workflow_id,revision,active','active=1','Reissue the deployment and independently approve its grant and per-run sharing.'),
        'workflow_publication_grants':('id,workflow_id,revision,active','active=1','Review a new canonical test and independently approve publication and each public run.'),
        'workflow_connection_deployments':('id,grant_id,release_id,revision,active','active=1','Review publication, reissue the connected deployment key and independently authorize its grant and each run.'),
        'workflow_connection_automation':('id,release_id,revision,active,used','active=1','Review a fresh independent automation and future-title sharing grant; unresolved runs are never replayed.'),
        'workflow_schedules':('workflow_id,mode,enabled','enabled=1','Review scheduling, rotate event keys and approve delivery again.'),
        'workflow_destinations':('id,workflow_id,channel,state',"state IN ('pending','verified')",'Register and verify the destination again.'),
        'workflow_delivery_grants':('id,workflow_id,source','revoked IS NULL','Issue a new purpose-bound result delivery grant.'),
        'workflow_fallback_policies':('workflow_id,revision','1=1','Review connections and build new shadow evidence before canary.'),
        'workflow_product_templates':('workflow_id,stage,expires','revoked IS NULL','Build new normal and independent outage proof before republishing.'),
        'workflow_io_profiles':('id,created,expires','revoked IS NULL','Retest current native schemas and mappings; restored profiles stay revoked.'),
        'workflow_manual_deliveries':('id,run_id,status',"status IN ('pending','claimed','dispatched')",'Inspect the external outcome; automatic replay is disabled.')}
    specs['organization_workspaces']=('id,revision,active','active=1',
        'Private workspace access remains paused. Establish current ownership and membership through a separately reviewed recovery process; old memberships are not automatically restored.')
    specs['workspace_private_tickets']=('id,workspace_id,draft_id,snapshot_id,run_id','revoked IS NULL',
        'Private run tickets are revoked. Inspect unresolved outcomes; do not replay restored inputs. Any future manual execution needs a fresh current session, reviewed snapshot and independent one-run authorization.')
    specs['workspace_executable_releases']=('id,workspace_id,draft_id,snapshot_id,revision','active=1',
        'Old executable releases remain blocked. Review a current snapshot and new test before issuing a new release.')
    specs['workspace_release_deployments']=('app_id,release_id,workspace_id,revision','active=1',
        'Old deployments remain blocked. Issue a new origin-bound grant and customer authorization.')
    specs['provider_control_claims']=('id,workspace_id,resource_id,revision,status',"revoked IS NULL",
        'Verify endpoint control with a fresh challenge; restored proof never reactivates ownership.')
    specs['provider_claim_transfers']=('id,source_workspace_id,target_workspace_id,revision,status',"status='pending'",
        'Old transfer offers remain permanently blocked. Establish current owners and start a new transfer and HTTPS challenge.')
    specs['customer_organizations']=('workspace_id,active,revision','active=1',
        'Customer organization access remains paused; old owner and invitation rows cannot independently establish current authority.')
    specs['customer_organization_invitations']=('id,workspace_id,role,status,revision',"status='pending'",
        'Pending invitations are revoked. A separately established current owner must issue a fresh recipient-bound invitation.')
    specs['customer_recovery_policies']=('workspace_id,revision','1=1',
        'Recovery policies remain blocked. Establish current ownership before enrolling new independent recovery keys.')
    specs['customer_recovery_requests']=('id,workspace_id,target_id,status',"status IN ('challenge','pending')",
        'Old recovery requests remain blocked. Confirm current offline ownership and independent review with a new request.')
    specs['stripe_sandbox_orders']=('id,workspace_id','1=1',
        'Reconcile the original test-provider records. Restored orders and financial replay tombstones cannot start a new charge, refund or payout.')
    specs['reliability_research_manifests']=('id,workspace_id,corpus_id','1=1',
        'Retain research history only. A current owner must approve a new manifest and corpus; old evaluation jobs are never replayed.')
    specs['reliability_admission_policies']=('workspace_id,revision','1=1',
        'Old pilot policies remain blocked. Review current evidence and issue a new policy with separate one-run authorization.')
    specs['reliability_admissions']=('id,workspace_id,snapshot_id,ticket_id','1=1',
        'Inspect the original execution outcome. Restored admissions cannot dispatch or become SDK releases; unresolved calls are never replayed.')
    specs['workspace_protocol_reports']=('id,workspace_id','1=1',
        'Keep reports as history only. Reconcile the original sandbox events independently; a report never authorizes a new capture or refund.')
    specs['reliability_circuit_states']=('workspace_id,resource_id,revision,generation','1=1',
        'Review current evidence and configure a new circuit generation. Old state and probe outcomes cannot reopen restored execution authority.')
    specs['reliability_circuit_claims']=('workspace_id,source_ref,resource_id','1=1',
        'Preserve consumed observations as history; old evaluation jobs cannot become fresh probes or be replayed.')
    result={'version':1,'created':time.time(),'automatic_reactivation':False,'items':{}}
    for table,(columns,where,action) in specs.items():
        if table not in tables:continue
        cursor=db.execute('SELECT '+columns+' FROM '+table+' WHERE '+where+' LIMIT 1001')
        names=[c[0] for c in cursor.description];rows=cursor.fetchall()
        result['items'][table]={'count':db.execute('SELECT COUNT(*) FROM '+table+' WHERE '+where).fetchone()[0],
                              'truncated':len(rows)>1000,'records':[dict(zip(names,r)) for r in rows[:1000]],'review_action':action}
    if 'execution_controls' in tables:
        row=db.execute('SELECT invoke_enabled,workflow_enabled,delivery_enabled FROM execution_controls WHERE id=1').fetchone()
        result['previous_runtime_controls']=dict(zip(('invoke_enabled','workflow_enabled','delivery_enabled'),row)) if row else {}
    if 'workflow_fallback_control' in tables:
        row=db.execute('SELECT enabled FROM workflow_fallback_control WHERE id=1').fetchone();result['previous_fallback_enabled']=bool(row and row[0])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    save=sub.add_parser('backup');save.add_argument('--db',required=True);save.add_argument('--directory',required=True)
    save.add_argument('--encrypt',action='store_true');save.add_argument('--retention-days',type=int,default=30)
    load=sub.add_parser('restore');load.add_argument('--directory',required=True);load.add_argument('--target',required=True)
    args=parser.parse_args()
    result=backup(args.db,args.directory,encrypt=args.encrypt,retention_days=args.retention_days) if args.action=='backup' else restore(args.directory,args.target)
    print(json.dumps(result))


if __name__=='__main__':main()

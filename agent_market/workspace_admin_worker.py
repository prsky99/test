"""Host-owned bounded projection worker and explicit maintenance operations."""
import logging
import hashlib
import hmac
import json
import threading
import time

from .workspace_admin_events import drain, execute, register, rows, transaction, emit,source_present

log = logging.getLogger(__name__)
register({
    'backfill_credits': 'SELECT id,customer_id,created,event_key,delta,balance,payload,signature FROM customer_credit_events WHERE id>? ORDER BY id LIMIT ?',
    'backfill_orgs': 'SELECT id,workspace_id,actor_ref,action,object_ref,revision,created,payload,signature FROM customer_organization_audit WHERE id>? ORDER BY id LIMIT ?',
    'backfill_runtime': 'SELECT id,workspace_id,customer_id,action,object_id,created FROM customer_workspace_audit WHERE id>? ORDER BY id LIMIT ?',
    'deleted_customers': '''SELECT d.customer_id FROM customer_account_deletions d
        JOIN customer_identities i ON i.id=d.customer_id WHERE i.active=0 AND requested<?
        AND NOT EXISTS(SELECT 1 FROM workspace_admin_state s WHERE s.id='deleted:' || d.customer_id)
        ORDER BY requested LIMIT ?''',
    'delete_events': 'DELETE FROM workspace_admin_events WHERE customer_id=?',
    'delete_outbox': 'DELETE FROM workspace_admin_outbox WHERE customer_id=?',
    'delete_messages': 'DELETE FROM workspace_admin_messages WHERE case_id IN (SELECT id FROM workspace_admin_cases WHERE customer_id=?)',
    'delete_cases': 'DELETE FROM workspace_admin_cases WHERE customer_id=?',
    'delete_commands': 'DELETE FROM workspace_admin_commands WHERE customer_id=?',
    'delete_disclosures': 'DELETE FROM workspace_admin_disclosures WHERE customer_id=?',
    'delete_case_links': 'DELETE FROM workspace_admin_case_links WHERE case_id IN (SELECT id FROM workspace_admin_cases WHERE customer_id=?)',
    'delete_operation_links': 'DELETE FROM workspace_admin_operation_links WHERE customer_id=?',
    'quarantine_commands': "UPDATE workspace_admin_commands SET status='restore_review_required',revision=revision+1 WHERE status='pending'",
    'quarantine_outbox': "UPDATE workspace_admin_outbox SET status='quarantined',fence=fence+1,lease_until=0",
    'quarantine_disclosures': 'UPDATE workspace_admin_disclosures SET revoked=?,revision=revision+1 WHERE revoked IS NULL',
    'closed_cases': '''SELECT id,updated FROM workspace_admin_cases c WHERE status='closed' AND updated<?
        AND NOT EXISTS(SELECT 1 FROM workspace_admin_state s WHERE s.id='case_pruned:' || c.id
            AND CAST(s.value AS DOUBLE PRECISION)>=c.updated) ORDER BY updated,id LIMIT ?''',
    'prune_case_messages': 'DELETE FROM workspace_admin_messages WHERE case_id=?',
    'prune_case_subject': "UPDATE workspace_admin_cases SET subject='Archived support request' WHERE id=?",
})


def backfill(store, limit=100):
    """Only factual retained audit sources, with per-source cursors and provenance."""
    count=0
    from .private_artifact_keys import ArtifactSigner
    from .customer_organizations import PROFILE as ORG_PROFILE
    identity_key=store._workspace_admin_identity_key
    credit_signer=ArtifactSigner(identity_key,'customer-workspace-credits-v1')
    org_signer=ArtifactSigner(hmac.new(identity_key,ORG_PROFILE.encode(),hashlib.sha256).digest(),ORG_PROFILE)
    with transaction(store) as db:
        for source in ('credits','orgs','runtime'):
            table={'credits':'customer_credit_events','orgs':'customer_organization_audit','runtime':'customer_workspace_audit'}[source]
            if not source_present(db,table):
                execute(db,'put_state',('source:'+source,'not_provisioned'))
                continue
            execute(db,'put_state',('source:'+source,'available'))
            state=rows(db,'state',('backfill:'+source,))
            cursor=int(state[0]['value']) if state else 0
            batch=rows(db,'backfill_'+source,(cursor,limit))
            for row in batch:
                customer=row.get('customer_id',row.get('actor_ref'))
                # Deleted accounts cannot be rediscovered by a later backfill.
                from .workspace_admin_control import rows as control_rows
                account = control_rows(db,'customer',(customer,))
                if account and account[0]['active']:
                    valid=True
                    if source in ('credits','orgs'):
                        try:
                            value=json.loads(row['payload'])
                            signer=credit_signer if source=='credits' else org_signer
                            fields=('customer_id','created','event_key','delta','balance') if source=='credits' else (
                                'workspace_id','actor_ref','action','object_ref','revision','created')
                            valid=signer.verify(value,row['signature']) and all(value.get(field)==row[field] for field in fields)
                        except (ValueError,TypeError,KeyError):valid=False
                    if not valid:
                        emit(store,db,'integrity.failed',outcome='denied',error_code='SOURCE_SIGNATURE_REJECTED',
                            event_key='source-integrity:'+source+':'+str(row['id']))
                        execute(db,'put_state',('source_integrity:'+source,'review_required'))
                        cursor=row['id'];count+=1
                        continue
                    emit(store,db,'historical.'+(row.get('action') or 'credit.recorded'),
                        customer=customer,workspace=row.get('workspace_id'),object_id=row.get('object_ref',row.get('object_id')),
                        occurred=row['created'],event_key='backfill:'+source+':'+str(row['id']))
                cursor=row['id']; count+=1
            execute(db,'put_state',('backfill:'+source,str(cursor)))
            execute(db,'put_state',('backfill_complete:'+source,'true' if len(batch)<limit else 'false'))
    return {'source_rows_reviewed':count}


def prune(store, limit=100):
    now=time.time()
    with transaction(store) as db:
        changed=execute(db,'event_prune',(now-30*86400,limit)).rowcount
        anonymous=execute(db,'event_prune_auth',(now-7*86400,limit)).rowcount
        removed=0
        for row in rows(db,'deleted_customers',(now-90*86400,limit)):
            for name in ('delete_events','delete_outbox','delete_messages','delete_case_links','delete_operation_links','delete_cases','delete_commands','delete_disclosures'):
                execute(db,name,(row['customer_id'],))
            execute(db,'put_state',('deleted:'+row['customer_id'],str(now)))
            removed+=1
        closed=rows(db,'closed_cases',(now-90*86400,limit))
        for case in closed:
            execute(db,'prune_case_messages',(case['id'],))
            execute(db,'prune_case_subject',(case['id'],))
            execute(db,'put_state',('case_pruned:'+case['id'],str(case['updated'])))
        execute(db,'put_state',('last_prune',str(now)))
    return {'expired_events_removed':changed,'anonymous_auth_events_removed':anonymous,
            'deleted_accounts_reviewed':removed,'closed_cases_pruned':len(closed)}


def quarantine(store):
    with transaction(store) as db:
        execute(db,'quarantine_commands'); execute(db,'quarantine_outbox')
        execute(db,'quarantine_disclosures',(time.time(),))
        execute(db,'put_state',('restore_quarantine',str(time.time())))


class OperationsWorker:
    def __init__(self, core):
        self.core=core; self.enabled=core.enabled
        self._stop=threading.Event(); self._thread=None; self.last_success=None; self.failure_count=0
        self.consecutive_failures=0
        self.last_storage_attempt=0; self.storage_failure_count=0

    def start(self):
        if not self.enabled: return True
        if self._thread and self._thread.is_alive(): return True
        self._thread=threading.Thread(target=self._loop,name='workspace-admin-projection',daemon=True)
        self._thread.start()
        return True

    def _loop(self):
        last_maintenance=0
        while not self._stop.is_set():
            try:
                drain(self.core.store,100)
                if time.monotonic()-last_maintenance>=60:
                    backfill(self.core.store,100)
                    prune(self.core.store,100)
                    if not self.last_storage_attempt or time.monotonic()-self.last_storage_attempt>=3600:
                        self.last_storage_attempt=time.monotonic()
                        try:
                            from .admin_completion import sample_storage
                            sample_storage(self.core.store)
                        except Exception:
                            self.storage_failure_count+=1
                            if self.storage_failure_count==1 or self.storage_failure_count%30==0:
                                log.warning('Administrator storage sampling unavailable; prior samples are retained.')
                    last_maintenance=time.monotonic()
                self.last_success=time.time()
                self.consecutive_failures=0
            except Exception:
                self.failure_count+=1
                self.consecutive_failures+=1
                if self.failure_count==1 or self.failure_count%30==0:
                    log.warning('Workspace administration projection unavailable; inspect ingestion health.')
            self._stop.wait(2 if not self.consecutive_failures else min(30,2+self.consecutive_failures))

    def close(self):
        self._stop.set()
        if self._thread: self._thread.join(5)
        return not self._thread or not self._thread.is_alive()

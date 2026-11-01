"""Individual-staff workspace operations; private content is never a read model."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import re
import secrets
import time

from . import admin_risk
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _identity
from .workspace_admin_events import (
    VERSION, activate, audit, canonical, emit, execute, register, rows, signature, transaction, source_present,
)

register({
    'customers': '''SELECT id,issuer,active,revision,created,last_login FROM customer_identities
        WHERE id>? AND id LIKE ? ESCAPE '!' ORDER BY id LIMIT ?''',
    'customer': 'SELECT id,issuer,active,revision,created,last_login FROM customer_identities WHERE id=?',
    'customer_count': 'SELECT COUNT(*) AS n FROM customer_identities',
    'organization_count': 'SELECT COUNT(*) AS n FROM customer_organizations WHERE active=1',
    'organizations': '''SELECT w.id,w.name,w.active,w.revision,w.created,w.updated,o.created_by AS customer_id
        FROM organization_workspaces w JOIN customer_organizations o ON o.workspace_id=w.id WHERE w.id>? ORDER BY w.id LIMIT ?''',
    'customer_links': 'SELECT workspace_id,role,active,revision FROM customer_workspace_links WHERE customer_id=? ORDER BY workspace_id LIMIT 100',
    'session_count': 'SELECT COUNT(*) AS n FROM customer_sessions WHERE customer_id=? AND revoked IS NULL AND expires>?',
    'event_customer': '''SELECT * FROM workspace_admin_events
        WHERE customer_id=? AND (occurred<? OR (occurred=? AND id<?)) ORDER BY occurred DESC,id DESC LIMIT ?''',
    'event_list': '''SELECT * FROM workspace_admin_events
        WHERE occurred>=? AND (occurred<? OR (occurred=? AND id<?)) ORDER BY occurred DESC,id DESC LIMIT ?''',
    'event_overview': '''SELECT event_type,outcome,COUNT(*) AS n FROM workspace_admin_events WHERE occurred>=? AND occurred<=? GROUP BY event_type,outcome''',
    'credits_accounts': 'SELECT customer_id FROM customer_credit_accounts WHERE customer_id>? ORDER BY customer_id LIMIT ?',
    'credit_events': 'SELECT payload,signature FROM customer_credit_events WHERE customer_id=? ORDER BY id LIMIT 2000',
    'case_operator_list': 'SELECT id,status,priority,assigned_to,revision,updated FROM workspace_admin_cases WHERE id>? ORDER BY id LIMIT ?',
    'case_list': 'SELECT * FROM workspace_admin_cases WHERE id>? ORDER BY id LIMIT ?',
    'case_customer': 'SELECT * FROM workspace_admin_cases WHERE customer_id=? AND id>? ORDER BY id LIMIT ?',
    'case_get': 'SELECT * FROM workspace_admin_cases WHERE id=?',
    'case_insert': 'INSERT INTO workspace_admin_cases VALUES(?,?,?,?,?,NULL,1,?,?,?,?)',
    'case_update': '''UPDATE workspace_admin_cases SET status=?,priority=?,assigned_to=?,revision=revision+1,updated=? WHERE id=? AND revision=?''',
    'case_messages': 'SELECT id,author,visibility,body,created FROM workspace_admin_messages WHERE case_id=? ORDER BY created DESC,id DESC LIMIT 201',
    'case_public_messages': "SELECT id,author,body,created FROM workspace_admin_messages WHERE case_id=? AND visibility='customer' ORDER BY created DESC,id DESC LIMIT 201",
    'message_insert': 'INSERT INTO workspace_admin_messages VALUES(?,?,?,?,?,?,?,?)',
    'message_replay': 'SELECT * FROM workspace_admin_messages WHERE request_id=?',
    'command_insert': "INSERT INTO workspace_admin_commands VALUES(?,?,?,1,'pending',?,NULL,?,?,?,?)",
    'command_list': 'SELECT id,customer_id,kind,revision,status,requested_by,approved_by,created,updated FROM workspace_admin_commands ORDER BY created DESC,id DESC LIMIT 100',
    'command_get': 'SELECT * FROM workspace_admin_commands WHERE id=?',
    'command_applied': "UPDATE workspace_admin_commands SET status='applied',revision=revision+1,approved_by=?,updated=? WHERE id=? AND revision=? AND status='pending'",
    'sessions_revoke': 'UPDATE customer_sessions SET revoked=? WHERE customer_id=? AND revoked IS NULL',
    'bff_revoke': 'UPDATE customer_bff_tokens SET revoked=? WHERE customer_id=? AND revoked IS NULL',
    'restrict': 'UPDATE customer_identities SET active=0,revision=revision+1 WHERE id=? AND revision=?',
    'case_count': "SELECT COUNT(*) AS n FROM workspace_admin_cases WHERE status NOT IN ('resolved','closed')",
    'private_runs': 'SELECT id,draft_id,snapshot_id,status,created,dispatched,finished FROM workspace_private_runs WHERE workspace_id=? ORDER BY created DESC LIMIT 100',
    'typed_runs': '''SELECT r.id,r.flow_id,t.version_id,r.status,r.created,r.deadline
        FROM workspace_typed_flow_runs r JOIN workspace_typed_flow_tickets t ON t.id=r.ticket_id
        WHERE r.workspace_id=? ORDER BY r.created DESC LIMIT 100''',
    'draft_metadata': 'SELECT id,name,revision,active,created,updated FROM workspace_drafts WHERE workspace_id=? ORDER BY updated DESC LIMIT 100',
    'typed_metadata': 'SELECT id,revision,active,version_id FROM workspace_typed_flows WHERE workspace_id=? ORDER BY id LIMIT 100',
    'releases_metadata': 'SELECT id,draft_id,snapshot_id,revision,active,created,expires FROM workspace_executable_releases WHERE workspace_id=? ORDER BY created DESC LIMIT 100',
    'deployments_metadata': 'SELECT app_id,release_id,revision,active,created,expires FROM workspace_release_deployments WHERE workspace_id=? ORDER BY created DESC LIMIT 100',
    'organization_exists': 'SELECT workspace_id FROM customer_organizations WHERE workspace_id=?',
    'incident_list': 'SELECT * FROM workspace_admin_incidents ORDER BY updated DESC,id DESC LIMIT 100',
    'incident_get': 'SELECT * FROM workspace_admin_incidents WHERE id=?',
    'incident_insert': 'INSERT INTO workspace_admin_incidents VALUES(?,?,1,?,?,?,?,?)',
    'incident_update': 'UPDATE workspace_admin_incidents SET status=?,revision=revision+1,assigned_to=?,updated=?,reason=? WHERE id=? AND revision=?',
    'audit_list': 'SELECT * FROM workspace_admin_audit ORDER BY created DESC,id DESC LIMIT 100',
    'disclosure_insert': 'INSERT INTO workspace_admin_disclosures VALUES(?,?,?,?,?,?,NULL,?,1,?,?)',
    'disclosure_get': 'SELECT * FROM workspace_admin_disclosures WHERE id=?',
    'disclosure_revoke': 'UPDATE workspace_admin_disclosures SET revoked=?,revision=revision+1 WHERE id=? AND revision=? AND revoked IS NULL',
    'disclosure_list': 'SELECT id,case_id,workspace_id,object_id,expires,revoked,revision FROM workspace_admin_disclosures WHERE customer_id=? ORDER BY created DESC LIMIT 100',
    'customer_link': '''SELECT l.workspace_id FROM customer_workspace_links l
        JOIN customer_identities c ON c.id=l.customer_id JOIN organization_workspaces w ON w.id=l.workspace_id
        WHERE l.customer_id=? AND l.workspace_id=? AND l.active=1 AND c.active=1 AND w.active=1''',
    'operation_events': 'SELECT * FROM workspace_admin_events WHERE object_id=? ORDER BY occurred,id LIMIT 100',
    'single_operation': 'SELECT id,workspace_id,draft_id,snapshot_id,status,created,deadline,dispatched,finished FROM workspace_private_runs WHERE id=?',
    'typed_operation': 'SELECT id,workspace_id,flow_id,status,created,deadline FROM workspace_typed_flow_runs WHERE id=?',
    'step_metadata': 'SELECT node_id,status FROM workspace_typed_flow_steps WHERE run_id=? ORDER BY node_id LIMIT 100',
    'error_groups': '''SELECT event_type,outcome,COUNT(*) AS operations,COUNT(DISTINCT customer_id) AS affected_customers,
        MIN(occurred) AS first_seen,MAX(occurred) AS last_seen FROM workspace_admin_events
        WHERE occurred>=? AND occurred<=? AND outcome IN ('failed','unknown','denied') GROUP BY event_type,outcome ORDER BY operations DESC LIMIT 50''',
    'staff_session_age': 'SELECT created_at FROM admin_sessions WHERE token=? AND user_id=?',
    'active_customers': '''SELECT COUNT(DISTINCT customer_id) AS n FROM workspace_admin_events
        WHERE occurred>=? AND occurred<=? AND event_type NOT LIKE 'auth.%' AND event_type NOT LIKE 'session.%' ''',
    'new_customers': 'SELECT COUNT(*) AS n FROM customer_identities WHERE created>=? AND created<=?',
    'case_links': 'SELECT source_kind,source_ref,created FROM workspace_admin_case_links WHERE case_id=? ORDER BY created',
    'source_inquiry': 'SELECT inquiry_id AS reference,status,created_at FROM customer_inquiries WHERE inquiry_id=?',
    'source_privacy': 'SELECT request_id AS reference,status,created_at FROM privacy_requests WHERE request_id=?',
    'source_cancellation': 'SELECT request_id AS reference,status,created_at FROM cancellation_requests WHERE request_id=?',
    'source_link': 'SELECT case_id FROM workspace_admin_case_links WHERE source_kind=? AND source_ref=?',
    'case_link_insert': 'INSERT INTO workspace_admin_case_links VALUES(?,?,?,?,?,?)',
    'staff_exists': 'SELECT id FROM admin_users WHERE id=? AND active=1',
    'risk_superadmins': admin_risk.QUERIES['risk_superadmins'],
    'operation_links': 'SELECT operation_id FROM workspace_admin_operation_links WHERE object_id=? ORDER BY created LIMIT 100',
    'observation_metadata': 'SELECT id,kind,source,protocol,status,error_code,created,finished,elapsed_ms FROM platform_operations WHERE id=?',
    'command_cancel': "UPDATE workspace_admin_commands SET status='cancelled',revision=revision+1,updated=? WHERE id=? AND revision=? AND status='pending'",
    'support_workspaces': '''SELECT w.id,w.name,l.role FROM customer_workspace_links l
        JOIN organization_workspaces w ON w.id=l.workspace_id WHERE l.customer_id=? AND l.active=1 AND w.active=1 ORDER BY w.name,w.id LIMIT 100''',
    'source_coverage': '''SELECT id,value FROM workspace_admin_state WHERE id IN
        ('source:credits','source:orgs','source:runtime','backfill:credits','backfill:orgs','backfill:runtime',
         'backfill_complete:credits','backfill_complete:orgs','backfill_complete:runtime') ORDER BY id''',
    'source_integrity': "SELECT id,value FROM workspace_admin_state WHERE id IN ('source_integrity:credits','source_integrity:orgs') ORDER BY id",
})


def text(value, maximum=1000, minimum=1):
    if (type(value) is not str or not minimum <= len(value.strip()) <= maximum
            or any(ord(c) < 32 and c not in '\n\t' for c in value)):
        raise WorkspaceInvalid()
    return value.strip()


def exact(body, fields):
    if type(body) is not dict or set(body) != set(fields):
        raise WorkspaceInvalid()


def request_id(value):
    if type(value) is not str or not re.fullmatch('[a-f0-9]{32}', value):
        raise WorkspaceInvalid()
    return value


def revision(value):
    if type(value) is not int or not 1 <= value < 2**31:
        raise WorkspaceInvalid()
    return value


def page(value, maximum=100):
    if type(value) is not int or not 1 <= value <= maximum:
        raise WorkspaceInvalid()
    return value


class WorkspaceAdminControl:
    def __init__(self, identity, access):
        self.identity, self.access, self.store = identity, access, identity.store
        if self.store is not access.store:
            raise WorkspaceInvalid()
        activate(self.store, identity.key)
        from .customer_credits import CustomerCredits
        self.credits = CustomerCredits(identity)

    @property
    def enabled(self):
        return bool(getattr(self.store, '_workspace_admin_events_enabled', False))

    @contextmanager
    def tx(self, actor, write=False, highest=False):
        if not self.enabled:
            raise WorkspaceConflict()
        with transaction(self.store, readonly=not write) as db:
            user = self.access._actor(actor, write=write, highest=highest)
            yield db, user
            self.access._actor(actor, write=write, highest=highest)

    def options(self, actor):
        with transaction(self.store, True):
            user = self.access._actor(actor)
        return {'profile': VERSION, 'migration_required': not self.enabled, 'role': user['role'], 'staff_id': actor.user_id,
                'can_support': user['role'] != 'operator', 'can_approve': user['role'] == 'superadmin', 'review_ttl': admin_risk.REVIEW_TTL,
                'private_content_access': False, 'payments': 'coming_soon', 'subscriptions': 'coming_soon'}

    def overview(self, actor, hours=24):
        page(hours, 168)
        journal=getattr(self.store,'_observation_journal',None)
        observations=journal.health() if journal is not None else {'available':False,'complete':False}
        with self.tx(actor) as (db, _):
            now = time.time()
            events = rows(db, 'event_overview', (now-hours*3600,now))
            pending = rows(db, 'pending_count')
            state = rows(db, 'state', ('last_projection',))
            coverage=rows(db,'source_coverage');coverage_map={item['id']:item['value'] for item in coverage}
            integrity=rows(db,'source_integrity')
            history_complete=all(coverage_map.get('backfill_complete:'+source)=='true'
                or coverage_map.get('source:'+source)=='not_provisioned' for source in ('credits','orgs','runtime'))
            watermark=float(state[0]['value']) if state else None
            errors=rows(db,'error_groups',(now-hours*3600,now))
            alerts=[]
            if watermark is None or now-watermark>30: alerts.append('projection_stale')
            if any(item['status']=='quarantined' for item in pending): alerts.append('event_integrity_review_required')
            if any(item['oldest'] is not None and now-item['oldest']>30 for item in pending): alerts.append('projection_backlog')
            if any(item['outcome']=='unknown' for item in errors): alerts.append('unknown_outcomes_require_review')
            if not observations.get('complete'): alerts.append('operational_observations_incomplete')
            if not history_complete:alerts.append('historical_backfill_incomplete')
            if integrity:alerts.append('historical_source_integrity_review_required')
            return {'captured_at': now, 'window_start': now-hours*3600, 'window_end': now,
                'customers': rows(db, 'customer_count')[0]['n'],
                'new_customers':rows(db,'new_customers',(now-hours*3600,now))[0]['n'],
                'active_customers':rows(db,'active_customers',(now-hours*3600,now))[0]['n'],
                'active_organizations': rows(db, 'organization_count')[0]['n'] if source_present(db,'customer_organizations') else None,
                'open_cases': rows(db, 'case_count')[0]['n'], 'events': events,'error_groups':errors,'alerts':alerts,
                'operational_observations':observations,
                'ingestion': {'outbox': pending, 'last_projection':watermark,
                    'complete': not pending and watermark is not None and now-watermark<=30 and history_complete and not integrity,
                    'live_projection_complete':not pending and watermark is not None and now-watermark<=30,
                    'historical_backfill_complete':history_complete,'source_coverage':coverage,'source_integrity':integrity,
                    'history': 'Only recorded events; no inferred historical logins.'},
                'commerce': {'payments': 'coming_soon', 'subscriptions': 'coming_soon', 'actual_revenue': None}}

    def customers(self, actor, cursor='', q='', limit=50):
        text(q, 80, 0); text(cursor, 120, 0); page(limit)
        # Escape SQL wildcard characters; customer IDs are exact opaque identifiers.
        if q and not re.fullmatch('[A-Za-z0-9_-]+', q):
            raise WorkspaceInvalid()
        with self.tx(actor) as (db, _):
            values = rows(db, 'customers', (cursor, '%'+q.replace('_','!_')+'%', limit+1))
            return {'customers': values[:limit], 'next_cursor': values[limit-1]['id'] if len(values)>limit else None}

    def customer(self, actor, customer):
        _identity(customer, 'cu')
        with self.tx(actor) as (db, _):
            found = rows(db, 'customer', (customer,))
            if len(found) != 1:
                raise WorkspaceDenied()
            value = self.credits._account(db, customer)
            return {'customer': found[0], 'links': rows(db, 'customer_links', (customer,)),
                'active_sessions': rows(db, 'session_count', (customer, time.time()))[0]['n'],
                'credits': value, 'private_content_access': False}

    def events(self, actor, customer=None, before=None, cursor='~', hours=24, limit=50):
        page(limit); page(hours, 168)
        if before is not None and (type(before) not in (float,int) or not 0 <= before <= time.time()+60):
            raise WorkspaceInvalid()
        text(cursor, 120)
        bound = before if before is not None else time.time()+1
        with self.tx(actor) as (db, _):
            if customer:
                _identity(customer, 'cu')
                result = rows(db, 'event_customer', (customer, bound, bound, cursor, limit+1))
            else:
                result = rows(db, 'event_list', (time.time()-hours*3600,bound,bound,cursor,limit+1))
            next_value = {'before': result[limit-1]['occurred'], 'cursor': result[limit-1]['id']} if len(result)>limit else None
            return {'events': [self._event(item) for item in result[:limit]], 'next_cursor': next_value, 'captured_at': time.time()}

    def _event(self,item):
        value=json.loads(item['payload'])
        expected=signature(self.store._workspace_admin_event_key,value)
        if (not hmac.compare_digest(expected,item['signature']) or value['id']!=item['id']
                or value['type']!=item['event_type'] or value['customer_id']!=item['customer_id']
                or value['workspace_id']!=item['workspace_id'] or value['object_id']!=item['object_id']
                or value['outcome']!=item['outcome'] or value['occurred_at']!=item['occurred']):
            raise WorkspaceConflict()
        return {key:val for key,val in item.items() if key not in ('payload','signature','event_key')} | {
            'safe_error_code':value.get('safe_error_code'),'provider':value.get('provider')}

    def operation(self,actor,identity):
        if type(identity) is not str or not re.fullmatch('[A-Za-z0-9_.:-]{1,120}',identity): raise WorkspaceInvalid()
        with self.tx(actor) as (db,_):
            events=[self._event(item) for item in rows(db,'operation_events',(identity,))]
            source=rows(db,'single_operation',(identity,)) or rows(db,'typed_operation',(identity,))
            if not events and not source: raise WorkspaceDenied()
            meta=source[0] if source else None
            return {'operation_id':identity,'events':events,'authoritative_state':meta,
                'attempts':rows(db,'step_metadata',(identity,)),
                'observations':[item for link in rows(db,'operation_links',(identity,)) for item in rows(db,'observation_metadata',(link['operation_id'],))],
                'observed_elapsed_ms':round((events[-1]['occurred']-events[0]['occurred'])*1000,3) if len(events)>1 else None,
                'observation_stale':bool(meta and meta['status'] in ('prepared','running','dispatched') and meta['deadline']<time.time()
                    or not meta and events and events[-1]['event_type']=='generation.requested' and time.time()-events[-1]['occurred']>120)}

    def organizations(self, actor, cursor='', limit=50):
        text(cursor,120,0); page(limit)
        with self.tx(actor) as (db, _):
            if not source_present(db,'customer_organizations'):
                return {'organizations':[],'next_cursor':None,'available':False}
            values = rows(db, 'organizations', (cursor,limit+1))
            return {'organizations': values[:limit], 'next_cursor': values[limit-1]['id'] if len(values)>limit else None}

    def operations(self, actor, workspace):
        _identity(workspace, 'ws')
        with self.tx(actor) as (db, _):
            if not rows(db, 'organization_exists', (workspace,)):
                raise WorkspaceDenied()
            return {key: rows(db, name, (workspace,)) for key,name in (
                ('drafts','draft_metadata'),('typed_flows','typed_metadata'),('executions','private_runs'),
                ('typed_executions','typed_runs'),('releases','releases_metadata'),('deployments','deployments_metadata'))}

    def reconciliation(self, actor, cursor='', limit=25):
        text(cursor,120,0); page(limit,50)
        with self.tx(actor) as (db, _):
            accounts = rows(db, 'credits_accounts', (cursor,limit+1))
            results=[]
            for item in accounts[:limit]:
                customer=item['customer_id']
                try:
                    account=self.credits._account(db, customer)
                    history=rows(db, 'credit_events', (customer,))
                    total=0
                    for record in history:
                        event=json.loads(record['payload'])
                        if not self.credits.signer.verify(event,record['signature']): raise WorkspaceConflict()
                        total+=event['command']['delta']
                        if event['balance'] != total: raise WorkspaceConflict()
                    results.append({'customer_id':customer,'balance':account['balance'],
                        'status':'incomplete' if len(history)==2000 else 'matched' if total==account['balance'] else 'mismatch',
                        'account_status':account['status'], 'event_count':len(history)})
                except (WorkspaceConflict,ValueError,KeyError,TypeError):
                    results.append({'customer_id':customer,'status':'integrity_review_required'})
            return {'accounts':results, 'next_cursor':accounts[limit-1]['customer_id'] if len(accounts)>limit else None,
                    'captured_at':time.time(), 'actual_money':False}

    def _case(self, db, identity, customer=None):
        _identity(identity,'wac')
        found=rows(db,'case_get',(identity,))
        if len(found)!=1 or customer is not None and found[0]['customer_id']!=customer:
            raise WorkspaceDenied()
        return found[0]

    def cases(self, actor, customer=None, cursor='', limit=50):
        page(limit); text(cursor,120,0)
        with self.tx(actor) as (db,user):
            if user['role']=='operator':
                if customer is not None:raise WorkspaceDenied()
                result=rows(db,'case_operator_list',(cursor,limit+1))
            else:
                result=rows(db,'case_customer',(customer,cursor,limit+1)) if customer else rows(db,'case_list',(cursor,limit+1))
            return {'cases':result[:limit],'next_cursor':result[limit-1]['id'] if len(result)>limit else None}

    def case(self, actor, identity):
        with self.tx(actor,True) as (db,_):
            value=self._case(db,identity)
            audit(db,actor.user_id,'case.read',identity,'Customer service case inspection')
            messages=rows(db,'case_messages',(identity,))
            return {'case':value,'messages':messages[:200][::-1],'messages_truncated':len(messages)>200,
                    'source_links':rows(db,'case_links',(identity,))}

    def link_case(self,actor,identity,body):
        exact(body,('revision','source_kind','source_ref','reason','confirmed_customer_relation'))
        revision(body['revision']); reason=text(body['reason'],500,20)
        if body['source_kind'] not in ('inquiry','privacy','cancellation') or body['confirmed_customer_relation'] is not True:
            raise WorkspaceInvalid()
        if type(body['source_ref']) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,120}',body['source_ref']): raise WorkspaceInvalid()
        with self.tx(actor,True) as (db,_):
            case=self._case(db,identity)
            old=rows(db,'source_link',(body['source_kind'],body['source_ref']))
            if old:
                if old[0]['case_id']!=identity: raise WorkspaceConflict()
                return {'linked':True,'replayed':True}
            if case['revision']!=body['revision']: raise WorkspaceConflict()
            if not rows(db,'source_'+body['source_kind'],(body['source_ref'],)): raise WorkspaceDenied()
            execute(db,'case_link_insert',(identity,body['source_kind'],body['source_ref'],actor.user_id,time.time(),reason))
            execute(db,'case_update',(case['status'],case['priority'],case['assigned_to'],time.time(),identity,case['revision']))
            audit(db,actor.user_id,'case.link.'+body['source_kind'],identity,reason)
            return {'linked':True,'replayed':False,'original_request_state_unchanged':True}

    def create_case_db(self,db,customer,body,author):
        exact(body,('subject','message','workspace_id','source_ref','request_id'))
        _identity(customer,'cu'); rid=request_id(body['request_id'])
        replay=rows(db,'message_replay',(rid,))
        if replay:
            case=self._case(db,replay[0]['case_id'],customer)
            if (replay[0]['request_digest']!=hashlib.sha256(canonical(body).encode()).hexdigest()
                    or replay[0]['author']!=author):
                raise WorkspaceConflict()
            return case
        if not rows(db,'customer',(customer,)): raise WorkspaceDenied()
        ws=body['workspace_id']
        if ws is not None:
            _identity(ws,'ws')
            if not rows(db,'customer_link',(customer,ws)): raise WorkspaceDenied()
        ref=body['source_ref']
        if ref is not None and not re.fullmatch('[A-Za-z0-9_:-]{1,120}',ref): raise WorkspaceInvalid()
        subject=text(body['subject'],160); message=text(body['message'],4000)
        now=time.time(); identity='wac_'+secrets.token_hex(16)
        execute(db,'case_insert',(identity,customer,ws,'new','normal',now,now,ref,subject))
        execute(db,'message_insert',('wam_'+secrets.token_hex(16),identity,author,'customer',message,now,rid,hashlib.sha256(canonical(body).encode()).hexdigest()))
        emit(self.store,db,'case.opened',customer=customer,workspace=ws,object_id=identity)
        audit(db,author,'case.open',identity,'Customer service request')
        return self._case(db,identity)

    def create_case(self,actor,customer,body):
        with self.tx(actor,True) as (db,_):
            return {'case':self.create_case_db(db,customer,body,'staff:'+str(actor.user_id))}

    def case_action(self,actor,identity,body):
        exact(body,('revision','status','priority','assigned_to','message','visibility','request_id'))
        revision(body['revision']); request_id(body['request_id'])
        if (body['status'] not in ('new','triaged','in_progress','waiting_customer','waiting_internal','resolved','closed')
                or body['priority'] not in ('normal','high','urgent') or body['visibility'] not in ('internal','customer')
                or body['assigned_to'] is not None and (type(body['assigned_to']) is not int or body['assigned_to']<1)):
            raise WorkspaceInvalid()
        message=text(body['message'],4000)
        with self.tx(actor,True) as (db,_):
            old=self._case(db,identity)
            if body['assigned_to'] is not None and not rows(db,'staff_exists',(body['assigned_to'],)):
                raise WorkspaceInvalid()
            previous=rows(db,'message_replay',(body['request_id'],))
            if previous:
                if (previous[0]['case_id']!=identity or previous[0]['body']!=message
                        or previous[0]['author']!='staff:'+str(actor.user_id)
                        or previous[0]['request_digest']!=hashlib.sha256(canonical(body).encode()).hexdigest()): raise WorkspaceConflict()
                return {'case':old,'replayed':True}
            if old['revision']!=body['revision']: raise WorkspaceConflict()
            execute(db,'case_update',(body['status'],body['priority'],body['assigned_to'],time.time(),identity,body['revision']))
            execute(db,'message_insert',('wam_'+secrets.token_hex(16),identity,'staff:'+str(actor.user_id),body['visibility'],message,time.time(),body['request_id'],hashlib.sha256(canonical(body).encode()).hexdigest()))
            emit(self.store,db,'case.updated',customer=old['customer_id'],workspace=old['workspace_id'],object_id=identity)
            audit(db,actor.user_id,'case.'+body['status'],identity,'Service response' if body['visibility']=='customer' else 'Internal service note')
            return {'case':self._case(db,identity)}

    def commands(self,actor):
        with self.tx(actor) as (db,_):
            return {'commands':[admin_risk.project(item) for item in rows(db,'command_list')],'review_ttl':admin_risk.REVIEW_TTL}

    def cancel_command(self,actor,identity,body):
        exact(body,('revision','reason')); revision(body['revision']); reason=text(body['reason'],300,5)
        with self.tx(actor,True) as (db,user):
            found=rows(db,'command_get',(identity,))
            if not found:raise WorkspaceDenied()
            record=found[0];self._command_value(record)
            if record['requested_by']!=actor.user_id and user['role']!='superadmin':raise WorkspaceDenied()
            if execute(db,'command_cancel',(time.time(),identity,body['revision'])).rowcount!=1:raise WorkspaceConflict()
            audit(db,actor.user_id,'command.cancel',identity,reason)
            emit(self.store,db,'command.cancelled',customer=record['customer_id'],object_id=identity)
            return {'status':'cancelled'}

    def command_detail(self,actor,identity):
        with self.tx(actor) as (db,_):
            found=rows(db,'command_get',(identity,))
            if not found: raise WorkspaceDenied()
            record=found[0];body=self._command_value(record)
            return {'command':admin_risk.project({k:v for k,v in record.items() if k not in ('payload','signature')}),'review':body}

    def _command_value(self,record):
        body=json.loads(record['payload'])
        envelope={'body':body,'id':record['id'],'requested_by':record['requested_by'],'created':record['created']}
        if (record['customer_id']!=body['customer_id'] or record['kind']!=body['kind']
                or not hmac.compare_digest(signature(self.store._workspace_admin_event_key,envelope),record['signature'])):
            raise WorkspaceConflict()
        return body

    def command(self,actor,body):
        exact(body,('customer_id','kind','target_revision','delta','credit_status','reason','request_id'))
        _identity(body['customer_id'],'cu'); revision(body['target_revision']); request_id(body['request_id'])
        if (body['kind'] not in ('sessions_revoke','account_restrict','credit_adjust')
                or type(body['delta']) is not int or not -1000000<=body['delta']<=1000000
                or body['credit_status'] not in ('active','suspended','closed')): raise WorkspaceInvalid()
        reason=text(body['reason'],300,5)
        with self.tx(actor,True) as (db,_):
            if not rows(db,'customer',(body['customer_id'],)): raise WorkspaceDenied()
            identity='wcmd_'+body['request_id']
            old=rows(db,'command_get',(identity,))
            if old:
                self._command_value(old[0])
                if old[0]['payload']!=canonical(body) or old[0]['requested_by']!=actor.user_id: raise WorkspaceConflict()
                return {'command_id':identity,'status':old[0]['status'],'replayed':True}
            now=time.time()
            envelope={'body':body,'id':identity,'requested_by':actor.user_id,'created':now}
            execute(db,'command_insert',(identity,body['customer_id'],body['kind'],actor.user_id,now,now,canonical(body),signature(self.store._workspace_admin_event_key,envelope)))
            audit(db,actor.user_id,'command.request',identity,reason)
            return {'command_id':identity,'status':'pending','revision':1}

    def approve(self,actor,identity,body):
        if type(body) is not dict or set(body) not in ({'revision','reason','confirm'},{'revision','reason','confirm','allow_self_review'}):
            raise WorkspaceInvalid()
        if 'allow_self_review' in body and type(body['allow_self_review']) is not bool: raise WorkspaceInvalid()
        revision(body['revision']); reason=text(body['reason'],300,5)
        if body['confirm']!='APPLY': raise WorkspaceInvalid()
        with self.tx(actor,True,True) as (db,_):
            found=rows(db,'command_get',(identity,))
            if not found: raise WorkspaceDenied()
            old=found[0]; command=self._command_value(old)
            if old['status']=='applied': return {'status':'applied','replayed':True}
            if old['status']!='pending' or old['revision']!=body['revision']: raise WorkspaceConflict()
            single=old['requested_by']==actor.user_id
            session=rows(db,'staff_session_age',(actor.session_ref,actor.user_id)) if single else []
            try:
                admin_risk.check_reviewer(requested_by=old['requested_by'],reviewer_id=actor.user_id,created=old['created'],
                    acknowledged=body.get('allow_self_review'),superadmins=rows(db,'risk_superadmins')[0]['n'] if single else None,
                    session_created=session[0]['created_at'] if session else None)
            except admin_risk.ReviewExpired: raise WorkspaceConflict() from None
            except admin_risk.ReviewDenied: raise WorkspaceDenied() from None
            customer=command['customer_id']; current=rows(db,'customer',(customer,))
            if not current or not current[0]['active']: raise WorkspaceDenied()
            if command['kind']=='credit_adjust':
                self.credits.admin_change_in_transaction(db,customer,{
                    'revision':command['target_revision'],'delta':command['delta'],'status':command['credit_status'],
                    'reason':command['reason'],'request_id':command['request_id']},actor)
            else:
                if current[0]['revision']!=command['target_revision']: raise WorkspaceConflict()
                execute(db,'sessions_revoke',(time.time(),customer)); execute(db,'bff_revoke',(time.time(),customer))
                if command['kind']=='account_restrict': execute(db,'restrict',(customer,command['target_revision']))
            execute(db,'command_applied',(actor.user_id,time.time(),identity,body['revision']))
            audit(db,actor.user_id,'command.apply.single_approver' if single else 'command.apply',identity,reason)
            emit(self.store,db,'command.applied',customer=customer,object_id=identity)
            return {'status':'applied','replayed':False,'same_person_review':single}

    def incidents(self,actor):
        with self.tx(actor) as (db,_): return {'incidents':rows(db,'incident_list')}

    def incident(self,actor,body,identity=None):
        exact(body,('revision','status','category','reason','assigned_to'))
        if type(body['revision']) is not int or not 0<=body['revision']<2**31: raise WorkspaceInvalid()
        if body['status'] not in ('open','mitigated','resolved') or body['category'] not in ('auth','ai','execution','credit','storage','ingestion','support'):
            raise WorkspaceInvalid()
        reason=text(body['reason'],500,5)
        if body['assigned_to'] is not None and (type(body['assigned_to']) is not int or body['assigned_to']<1): raise WorkspaceInvalid()
        with self.tx(actor,True) as (db,_):
            now=time.time()
            if body['assigned_to'] is not None and not rows(db,'staff_exists',(body['assigned_to'],)):
                raise WorkspaceInvalid()
            if identity is None:
                if body['revision']!=0: raise WorkspaceConflict()
                identity='wai_'+secrets.token_hex(16)
                execute(db,'incident_insert',(identity,body['status'],body['assigned_to'],now,now,body['category'],reason))
            else:
                revision(body['revision'])
                if execute(db,'incident_update',(body['status'],body['assigned_to'],now,reason,identity,body['revision'])).rowcount!=1: raise WorkspaceConflict()
            audit(db,actor.user_id,'incident.'+body['status'],identity,reason)
            return {'incident':rows(db,'incident_get',(identity,))[0]}

    def audits(self,actor):
        with self.tx(actor,highest=True) as (db,_): return {'audit':rows(db,'audit_list')}

    def disclosure(self,current,case_id,body):
        exact(body,('workspace_id','draft_id','ttl_seconds','confirm'))
        if type(body['ttl_seconds']) is not int or not 60<=body['ttl_seconds']<=3600 or body['confirm']!='SHARE':
            raise WorkspaceInvalid()
        with self.identity.tx() as db:
            self.identity._session(db,current.session_ref,current.customer_id)
            case=self._case(db,case_id,current.customer_id)
            ws=body['workspace_id']
            if case['workspace_id']!=ws: raise WorkspaceDenied()
            self.identity.authorize(db,current,ws,'manage')
            draft=self.access._open_draft(self.access._draft_row(ws,body['draft_id']))
            identity='wad_'+secrets.token_hex(16); expires=time.time()+body['ttl_seconds']
            binding=signature(self.store._workspace_admin_event_key,[current.customer_id,case_id,ws,body['draft_id'],draft['revision'],expires])
            execute(db,'disclosure_insert',(identity,current.customer_id,case_id,ws,body['draft_id'],expires,time.time(),draft['revision'],binding))
            audit(db,current.customer_id,'disclosure.grant',identity,'Customer shared one current draft revision for support')
            return {'disclosure_id':identity,'expires':expires,'revision':1}

    def disclosures(self,actor,customer):
        _identity(customer,'cu')
        with self.tx(actor) as (db,_): return {'disclosures':rows(db,'disclosure_list',(customer,))}

    def disclosure_read(self,actor,identity):
        with self.tx(actor,True,True) as (db,_):
            found=rows(db,'disclosure_get',(identity,))
            if not found: raise WorkspaceDenied()
            value=found[0]
            expected=signature(self.store._workspace_admin_event_key,[value['customer_id'],value['case_id'],value['workspace_id'],value['object_id'],value['object_revision'],value['expires']])
            if (value['revoked'] is not None or value['expires']<=time.time()
                    or not hmac.compare_digest(expected,value['binding'])
                    or not rows(db,'customer_link',(value['customer_id'],value['workspace_id']))): raise WorkspaceDenied()
            draft=self.access._open_draft(self.access._draft_row(value['workspace_id'],value['object_id']))
            if draft['revision']!=value['object_revision']: raise WorkspaceConflict()
            audit(db,actor.user_id,'disclosure.read',identity,'Customer-authorized support draft inspection')
            return {'draft':draft,'expires':value['expires']}

    def disclosure_revoke(self,current,identity,body):
        exact(body,('revision',)); revision(body['revision'])
        with self.identity.tx() as db:
            self.identity._session(db,current.session_ref,current.customer_id)
            found=rows(db,'disclosure_get',(identity,))
            if not found or found[0]['customer_id']!=current.customer_id: raise WorkspaceDenied()
            if execute(db,'disclosure_revoke',(time.time(),identity,body['revision'])).rowcount!=1: raise WorkspaceConflict()
            audit(db,current.customer_id,'disclosure.revoke',identity,'Customer withdrew support access')
            return {'revoked':True}

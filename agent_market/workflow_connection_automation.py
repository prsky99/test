"""Independent bounded automation for an already tested public connection.

The canonical graph stays manual. This grant authorizes only the separate
scheduler or an authenticated owner event, including its future-title rule.
"""
import copy
import hmac
import json
import re
import secrets
import sqlite3
import time

from .capability_registry import canonical, digest
from . import workflow_public_flow as flow

PROFILE = 'published-connection-automation-v1'
SHARE_NOTICE = 'workflow-connection-automation-share-v1'
GRANT_NOTICE = 'workflow-connection-automation-trigger-v1'
EVENT_NOTICE = 'workflow-connection-automation-event-v1'
PLAN = 'workflow-connection-automation-plan-v1'
TICKET = 'workflow-connection-automation-run-v1'
DEFAULTS = {'trigger': 'scheduled', 'interval_seconds': 300, 'max_runs': 10, 'ttl_seconds': 86400}
SCHEMA = '''CREATE TABLE IF NOT EXISTS workflow_connection_automation (
 id TEXT PRIMARY KEY,release_id TEXT NOT NULL,proposal_nonce TEXT NOT NULL UNIQUE,
 revision INTEGER NOT NULL,active INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
 created REAL NOT NULL,expires REAL NOT NULL,revoked REAL,used INTEGER NOT NULL DEFAULT 0,
 next_run REAL,last_admitted REAL);
CREATE TABLE IF NOT EXISTS workflow_connection_automation_admissions (
 grant_id TEXT NOT NULL,slot TEXT NOT NULL,run_id TEXT NOT NULL UNIQUE,created REAL NOT NULL,
 trigger TEXT NOT NULL,PRIMARY KEY(grant_id,slot));
'''
PLAN_FIELDS = {'audience','profile','owner','release_id','publication_revision','definition_hash','rule_hash','proof_hash',
               'created','expires','grant_expires','nonce','trigger','interval_seconds','max_runs'}
TICKET_FIELDS = {'audience','profile','grant_id','revision','release_id','publication_revision','definition_hash',
                 'rule_hash','grant_hash','nonce','trigger','due_at','created','expires','reviewed_at'}


class ConnectionAutomation:
    def __init__(self, runtime):
        self.runtime, self.store, self.publication = runtime, runtime.store, runtime.publication
        with self.store._lock: self.store._db.executescript(SCHEMA)

    def _owner(self, actor): return self.publication._owner(actor)

    @staticmethod
    def notices(): return {'share': SHARE_NOTICE, 'grant': GRANT_NOTICE, 'event': EVENT_NOTICE}

    @staticmethod
    def _limits(trigger, interval, maximum):
        if (trigger not in ('scheduled','event') or type(interval) is not int
                or (trigger == 'scheduled' and not 300 <= interval <= 86400)
                or (trigger == 'event' and interval != 0) or type(maximum) is not int or not 1 <= maximum <= 100):
            raise ValueError('Use a bounded schedule or an authenticated administrator event.')

    def options(self, release_id, actor):
        self._owner(actor)
        try: self.publication.current(release_id); available = True
        except (ValueError,KeyError,TypeError,IndexError): available = False
        return {'ok': True,'profile': PROFILE,'release_id': release_id,'available': available,'defaults': dict(DEFAULTS),
                'notices': self.notices(),'grants': self.history(release_id,actor)['grants']}

    def prepare(self, release_id, body, actor):
        owner = self._owner(actor)
        if not isinstance(body,dict) or set(body) != {'trigger','interval_seconds','max_runs','ttl_seconds'}: raise ValueError('Review the exact automation configuration.')
        self._limits(body['trigger'],body['interval_seconds'],body['max_runs'])
        if type(body['ttl_seconds']) is not int or not 300 <= body['ttl_seconds'] <= 86400: raise ValueError('Use a bounded automation duration.')
        publication, workflow = self.publication.current(release_id); created = flow.stamp(time.time())
        expires = flow.stamp(min(created + body['ttl_seconds'],publication['expires'],publication['proof']['valid_until']))
        if expires-created < 300 or body['trigger']=='scheduled' and created+body['interval_seconds'] >= expires: raise ValueError('The reviewed schedule must fit within the original publication validity.')
        p = {'audience': PLAN,'profile': PROFILE,'owner': owner,'release_id': release_id,'publication_revision': publication['revision'],
             'definition_hash': publication['definition_hash'],'rule_hash': digest(workflow['nodes'][2]['data']['composition']['payload']['connection']),
             'proof_hash': digest(publication['proof']),'created': created,'expires': flow.stamp(min(created+900,expires)),
             'grant_expires': expires,'nonce': secrets.token_hex(16),'trigger': body['trigger'],
             'interval_seconds': body['interval_seconds'],'max_runs': body['max_runs']}
        return {'ok': True,'profile': PROFILE,**self.publication._envelope(p),'executed': False,'notices': self.notices(),
                'preview': {**self.publication._preview(workflow,expires),'trigger': p['trigger'],'interval_seconds': p['interval_seconds'],
                            'max_runs': p['max_runs'],'fixed_window': True,'event_min_interval_seconds': 60}}

    def issue(self, release_id, body, actor):
        owner = self._owner(actor)
        if (not isinstance(body,dict) or set(body) != {'proposal','signature','sharing_authority','sharing_notice','trigger_authority','trigger_notice'}
                or body['sharing_authority'] is not True or body['sharing_notice'] != SHARE_NOTICE
                or body['trigger_authority'] is not True or body['trigger_notice'] != GRANT_NOTICE): raise ValueError('Separate automation and future-title sharing approvals are required.')
        p = self.publication._unpack(body,PLAN,PLAN_FIELDS); self._limits(p['trigger'],p['interval_seconds'],p['max_runs'])
        if (p['profile'] != PROFILE or p['owner'] != owner or p['release_id'] != release_id
                or not isinstance(p['nonce'],str) or not re.fullmatch(r'[a-f0-9]{32}',p['nonce'])
                or not 300 <= flow.timestamp(p['grant_expires'])-p['created'] <= 86400
                or p['expires'] != min(p['created']+900,p['grant_expires'])): raise ValueError('The reviewed automation changed.')
        publication, workflow = self.publication.current(release_id)
        if (type(p['publication_revision']) is not int or p['publication_revision'] != publication['revision']
                or p['definition_hash'] != publication['definition_hash'] or p['proof_hash'] != digest(publication['proof'])
                or p['rule_hash'] != digest(workflow['nodes'][2]['data']['composition']['payload']['connection'])
                or p['grant_expires'] > min(publication['expires'],publication['proof']['valid_until'])): raise ValueError('The tested publication changed.')
        self.publication._epoch(p['created']); created = time.time(); identity = 'aut_'+secrets.token_hex(16)
        payload = {**p,'audience': GRANT_NOTICE,'id': identity,'revision': 1,'reviewed_at': p['created'],
                   'proposal_nonce': p['nonce'],'created': created,'expires': p['grant_expires'],
                   'sharing_notice': SHARE_NOTICE,'trigger_notice': GRANT_NOTICE}
        next_run = created+p['interval_seconds'] if p['trigger']=='scheduled' else None
        if next_run is not None and next_run >= payload['expires']: raise ValueError('The reviewed schedule expired before activation.')
        with self.store._lock:
            if self.store._db.in_transaction: raise ValueError('Automation issuance is temporarily unavailable.')
            with self.store.tx() as db:
                db.execute('BEGIN IMMEDIATE'); self.publication._epoch(p['created']); self._owner(owner)
                current = db.execute('SELECT revision,active FROM workflow_publication_grants WHERE id=?',(release_id,)).fetchone()
                if not current or not current['active'] or current['revision'] != p['publication_revision']: raise ValueError('The publication changed before activation.')
                if db.execute('SELECT 1 FROM workflow_connection_automation WHERE proposal_nonce=?',(p['nonce'],)).fetchone(): raise ValueError('This automation review was already consumed.')
                if db.execute("SELECT COUNT(*) FROM workflow_connection_automation WHERE created>? AND json_extract(payload,'$.owner')=?",(created-3600,owner)).fetchone()[0] >= 20: raise ValueError('The automation grant limit has been reached.')
                db.execute('INSERT INTO workflow_connection_automation VALUES (?,?,?,1,1,?,?,?,?,NULL,0,?,NULL)',
                           (identity,release_id,p['nonce'],canonical(payload),self.runtime.authority.signature(payload),created,payload['expires'],next_run))
        return {'ok': True,'profile': PROFILE,'grant': self._view(dict(self.store.query('SELECT * FROM workflow_connection_automation WHERE id=?',(identity,))[0]),payload)}

    @staticmethod
    def _view(row,p):
        return {**{key:row[key] for key in ('id','revision','used','next_run','created','expires','revoked')},
                'active': bool(row['active']),'trigger':p['trigger'],'interval_seconds':p['interval_seconds'],'max_runs':p['max_runs']}

    def metadata(self, identity, *, active=True):
        if not isinstance(identity,str) or not re.fullmatch(r'aut_[a-f0-9]{32}',identity): raise ValueError('The automation grant is unavailable.')
        rows = self.store.query('SELECT * FROM workflow_connection_automation WHERE id=?',(identity,))
        if len(rows)!=1 or len(rows[0]['payload'])>16000: raise ValueError('The automation grant is unavailable.')
        row = dict(rows[0]); p = json.loads(row['payload'])
        if (not hmac.compare_digest(row['signature'],self.runtime.authority.signature(p)) or p.get('audience')!=GRANT_NOTICE
                or p.get('profile')!=PROFILE or p.get('sharing_notice')!=SHARE_NOTICE or p.get('trigger_notice')!=GRANT_NOTICE
                or p.get('id')!=identity or p.get('release_id')!=row['release_id'] or p.get('proposal_nonce')!=row['proposal_nonce']
                or p.get('created')!=row['created'] or p.get('expires')!=row['expires'] or p.get('revision')!=1
                or not flow.timestamp(p['created']) < flow.timestamp(p['expires']) <= p['created']+86400
                or flow.timestamp(p['reviewed_at'])>p['created']+5): raise ValueError('The signed automation grant changed.')
        self._limits(p['trigger'],p['interval_seconds'],p['max_runs'])
        if active:
            state=self.store.query('SELECT COUNT(*) AS n,MAX(created) AS last FROM workflow_connection_automation_admissions WHERE grant_id=?',(identity,))[0]
            expected_next=(state['last'] if state['n'] else p['created'])+p['interval_seconds'] if p['trigger']=='scheduled' else None
            if (type(row['used']) is not int or row['used']!=state['n'] or row['last_admitted']!=state['last']
                    or row['next_run']!=expected_next):raise ValueError('The durable automation counters changed.')
        if active and (row['active']!=1 or row['revision']!=p['revision'] or row['revoked'] is not None or not time.time()<p['expires']): raise ValueError('Automation was revoked or expired.')
        return row,p

    def current(self, identity):
        row,p = self.metadata(identity); self._owner(p['owner']); self.publication._epoch(p['reviewed_at'])
        publication,workflow = self.publication.current(p['release_id'])
        if (p['publication_revision']!=publication['revision'] or p['definition_hash']!=publication['definition_hash']
                or p['proof_hash']!=digest(publication['proof']) or p['rule_hash']!=digest(workflow['nodes'][2]['data']['composition']['payload']['connection'])
                or p['expires']>min(publication['expires'],publication['proof']['valid_until'])): raise ValueError('The automation publication or original proof changed.')
        return row,p,workflow

    def history(self, release_id, actor):
        self._owner(actor); grants=[]
        for row in self.store.query('SELECT * FROM workflow_connection_automation WHERE release_id=? ORDER BY created DESC LIMIT 50',(release_id,)):
            try:
                raw,p=self.metadata(row['id'],active=False); grants.append(self._view(raw,p))
            except (ValueError,KeyError,TypeError): continue
        runs=[{'grant_id':r['grant_id'],'event_id':r['slot'].removeprefix('event:') if r['trigger']=='event' else None,
               'run_id':r['run_id'],'status':r['status'],'outcome':r['execution_outcome'],'created':r['created']}
              for r in self.store.query('''SELECT a.*,r.status,r.execution_outcome FROM workflow_connection_automation_admissions a
                 JOIN workflow_connection_automation g ON g.id=a.grant_id JOIN workflow_runs r ON r.id=a.run_id
                 WHERE g.release_id=? ORDER BY a.created DESC LIMIT 100''',(release_id,))]
        return {'ok':True,'profile':PROFILE,'grants':grants,'runs':runs}

    def revoke(self, release_id, identity, revision, actor):
        self._owner(actor)
        if type(revision) is not int: raise ValueError('Use the current automation revision.')
        with self.store.tx() as db:
            if db.execute('UPDATE workflow_connection_automation SET active=0,revision=revision+1,revoked=?,next_run=NULL WHERE id=? AND release_id=? AND revision=? AND active=1',
                          (time.time(),identity,release_id,revision)).rowcount!=1: raise ValueError('The automation revision changed.')
        self.cancel(identity)
        return {'ok':True,'id':identity,'active':False,'revision':revision+1}

    def cancel(self, identity):
        for row in self.store.query("SELECT id FROM workflow_runs WHERE actor=? AND status IN ('queued','running')",('automation:'+identity,)): self.runtime.cancel(row['id'])

    def _ticket(self, identity, slot, trigger, due_at=None):
        row,p,workflow=self.current(identity); created=flow.stamp(time.time())
        if p['trigger']!=trigger: raise ValueError('The trigger does not match this automation grant.')
        ticket={'audience':TICKET,'profile':PROFILE,'grant_id':identity,'revision':row['revision'],'release_id':p['release_id'],
                'publication_revision':p['publication_revision'],'definition_hash':p['definition_hash'],'rule_hash':p['rule_hash'],
                'grant_hash':digest(p),'nonce':slot,'trigger':trigger,'due_at':due_at,'created':created,
                'expires':flow.stamp(min(created+300,p['expires'])),'reviewed_at':p['reviewed_at']}
        return {'ticket':ticket,'signature':self.runtime.authority.signature(ticket)},workflow,p

    def _validate_ticket(self, context, *, admitted=None, current=True):
        if not isinstance(context,dict) or set(context)!={'ticket','signature'}: raise ValueError('An independent automation run purpose is required.')
        t=context['ticket']
        if (not isinstance(t,dict) or set(t)!=TICKET_FIELDS or t['audience']!=TICKET or t['profile']!=PROFILE
                or not isinstance(context['signature'],str) or not hmac.compare_digest(context['signature'],self.runtime.authority.signature(t))
                or t['trigger'] not in ('event','scheduled') or not isinstance(t['nonce'],str)
                or not re.fullmatch(r'event:[a-f0-9]{32}|schedule:[0-9]+\.[0-9]{6}',t['nonce'])
                or not flow.timestamp(t['created']) <= (time.time() if admitted is None else flow.timestamp(admitted)) < flow.timestamp(t['expires']) <= t['created']+300): raise ValueError('The automation run purpose changed or expired.')
        if current: row,p,workflow=self.current(t['grant_id'])
        else: row,p=self.metadata(t['grant_id'],active=False); workflow=None
        if (type(t['revision']) is not int or t['revision']!=p['revision'] or t['grant_hash']!=digest(p)
                or any(t[key]!=p[key] for key in ('release_id','publication_revision','definition_hash','rule_hash','reviewed_at','trigger'))
                or t['expires']>p['expires'] or (t['trigger']=='event' and (t['due_at'] is not None or not t['nonce'].startswith('event:')))
                or (t['trigger']=='scheduled' and (t['nonce']!='schedule:'+format(flow.timestamp(t['due_at']),'.6f') or t['due_at']>t['created']))): raise ValueError('The automation grant or trigger changed.')
        return t,p,workflow

    def _existing(self, identity, slot):
        rows=self.store.query('''SELECT r.* FROM workflow_connection_automation_admissions a JOIN workflow_runs r ON r.id=a.run_id
                                 WHERE a.grant_id=? AND a.slot=?''',(identity,slot))
        if not rows:return None
        row=dict(rows[0]); records=self.store.query('SELECT payload FROM workflow_run_authority WHERE run_id=?',(row['id'],))
        if len(records)!=1:raise ValueError('The retained automation purpose is unavailable.')
        scope=json.loads(records[0]['payload'])['principal']['payload']['connection_automation']; self.replay_scope(row,scope)
        return {'ok':True,'profile':PROFILE,'event_id':slot.removeprefix('event:') if slot.startswith('event:') else None,
                'run_id':row['id'],'status':row['status'],'replayed':True}

    def trigger(self, release_id, identity, body, actor):
        owner=self._owner(actor)
        if (not isinstance(body,dict) or set(body)!={'event_id','authority','notice'} or body['authority'] is not True or body['notice']!=EVENT_NOTICE
                or not isinstance(body['event_id'],str) or not re.fullmatch(r'[a-f0-9]{32}',body['event_id'])): raise ValueError('Explicit authenticated event authority and a stable event identifier are required.')
        _,p=self.metadata(identity,active=False)
        if p['owner']!=owner or p['release_id']!=release_id or p['trigger']!='event':raise ValueError('The event owner or automation changed.')
        slot='event:'+body['event_id']; old=self._existing(identity,slot)
        if old:return old
        context,workflow,p=self._ticket(identity,slot,'event')
        return self._submit(context,workflow,p)

    def _submit(self, context, workflow, grant):
        t=context['ticket']; principal=self.runtime.principal('admin',grant['owner'],workflow['id'],role='superadmin')
        args={'actor':'automation:'+t['grant_id'],'source':'admin','idempotency':t['nonce'],'principal':principal,'connection_automation':context}
        try:job=self.runtime.submit(workflow,**args)
        except (sqlite3.IntegrityError,ValueError):
            old=self._existing(t['grant_id'],t['nonce'])
            if old:return old
            raise ValueError('Automation admission changed; inspect its history.') from None
        return {'ok':True,'profile':PROFILE,'event_id':t['nonce'].removeprefix('event:') if t['trigger']=='event' else None,**job}

    def admit(self, workflow, claims, context, *, source, profile, fallback, public):
        if context is None:return None
        if (not flow.is_flow(workflow) or source!='admin' or claims.get('kind')!='admin' or claims.get('role')!='superadmin'
                or public or profile!='standard' or fallback):raise ValueError('Use only this independently approved standard automation purpose.')
        t,p,current=self._validate_ticket(context)
        if claims['subject']!=p['owner'] or flow.graph_value(workflow)!=flow.graph_value(current):raise ValueError('The automation owner or canonical graph changed.')
        return copy.deepcopy(context)

    def commit(self, db, run_id, scope):
        """Reserve the slot and quota in the same writer transaction as the run."""
        t=scope['ticket']; row,p=self.metadata(t['grant_id']); self._owner(p['owner']); self.publication._epoch(p['reviewed_at'])
        control=db.execute('SELECT invoke_enabled,workflow_enabled FROM execution_controls WHERE id=1').fetchone()
        pub=db.execute('SELECT revision,active FROM workflow_publication_grants WHERE id=?',(p['release_id'],)).fetchone()
        count=db.execute('SELECT COUNT(*) FROM workflow_connection_automation_admissions WHERE grant_id=?',(row['id'],)).fetchone()[0]
        if (not control or not control['invoke_enabled'] or not control['workflow_enabled'] or not pub or not pub['active'] or pub['revision']!=p['publication_revision']
                or count!=row['used'] or count>=p['max_runs'] or not t['created']<=time.time()<t['expires']
                or db.execute('SELECT 1 FROM workflow_connection_automation_admissions a JOIN workflow_runs r ON r.id=a.run_id WHERE a.grant_id=? AND (r.status IN (\'queued\',\'running\') OR r.execution_outcome=\'unknown\')',(row['id'],)).fetchone()):raise ValueError('Automation is full, unresolved or unavailable.')
        if t['trigger']=='scheduled':
            if row['next_run']!=t['due_at'] or not row['next_run']<=time.time():raise ValueError('The scheduled slot changed or is not due.')
        elif row['last_admitted'] is not None and time.time()-row['last_admitted']<60:raise ValueError('The event admission interval has not elapsed.')
        created=time.time(); next_run=created+p['interval_seconds'] if p['trigger']=='scheduled' else None
        if db.execute('UPDATE workflow_connection_automation SET used=used+1,last_admitted=?,next_run=? WHERE id=? AND active=1 AND revision=? AND used=?',
                      (created,next_run,row['id'],t['revision'],count)).rowcount!=1:raise ValueError('The automation admission changed.')
        db.execute('INSERT INTO workflow_connection_automation_admissions VALUES (?,?,?,?,?)',(row['id'],t['nonce'],run_id,created,t['trigger']))

    def run_scope(self, row, workflow, authority):
        p=authority['principal']['payload']; scope=p.get('connection_automation'); t,grant,current=self._validate_ticket(scope)
        if (row['source']!='admin' or p.get('kind')!='admin' or p.get('role')!='superadmin' or p.get('subject')!=grant['owner']
                or any(p.get(key) is not None for key in ('public_connection','connection_deployment','controlled_pair','deployment_consent'))
                or authority.get('grant_id') is not None or digest(workflow)!=row['digest'] or flow.graph_value(workflow)!=flow.graph_value(current)
                or row['actor']!='automation:'+t['grant_id'] or row['idempotency_key']!=t['nonce']
                or self.runtime.budgets.get(row)['profile']!='standard'):raise ValueError('The accepted automation purpose changed.')
        receipt=self.store.query('SELECT run_id FROM workflow_connection_automation_admissions WHERE grant_id=? AND slot=?',(t['grant_id'],t['nonce']))
        if len(receipt)!=1 or receipt[0]['run_id']!=row['id']:raise ValueError('The durable automation admission changed.')

    def replay_scope(self, row, scope):
        t,grant,_=self._validate_ticket(scope,admitted=row['created'],current=False)
        rows=self.store.query('SELECT substr(payload,1,16385) AS payload,signature FROM workflow_run_authority WHERE run_id=?',(row['id'],))
        if len(rows)!=1 or len(rows[0]['payload'])>16384:raise ValueError('The retained automation purpose is unavailable.')
        a=json.loads(rows[0]['payload']); e=a['principal']; p=e['payload']
        if (not hmac.compare_digest(rows[0]['signature'],self.runtime.authority.signature(a)) or not hmac.compare_digest(e['signature'],self.runtime.authority.signature(p))
                or any(a.get(key)!=row[key] for key in ('workflow_id','digest','source')) or a.get('run_id')!=row['id'] or a.get('grant_id') is not None
                or p.get('connection_automation')!=scope or p.get('kind')!='admin' or p.get('role')!='superadmin' or p.get('subject')!=grant['owner']
                or p.get('workflow_id')!=row['workflow_id'] or p.get('audience')!='workflow-runtime-v1' or not row['created']<flow.timestamp(p.get('expires'))<=t['expires']
                or row['source']!='admin' or row['actor']!='automation:'+t['grant_id'] or row['idempotency_key']!=t['nonce']):raise ValueError('The retained automation nonce scope changed.')
        receipt=self.store.query('SELECT run_id FROM workflow_connection_automation_admissions WHERE grant_id=? AND slot=?',(t['grant_id'],t['nonce']))
        if len(receipt)!=1 or receipt[0]['run_id']!=row['id']:raise ValueError('The retained automation receipt changed.')

    def _due_rows(self, now, cursor):
        due,identity=cursor if cursor else (None,None)
        return self.store.query("""SELECT g.id,g.next_run FROM workflow_connection_automation g
            WHERE g.active=1 AND g.next_run<=? AND g.expires>? AND g.used<json_extract(g.payload,'$.max_runs')
            AND EXISTS (SELECT 1 FROM workflow_publication_grants p WHERE p.id=g.release_id AND p.active=1 AND p.expires>?)
            AND NOT EXISTS (SELECT 1 FROM workflow_connection_automation_admissions a JOIN workflow_runs r ON r.id=a.run_id
                WHERE a.grant_id=g.id AND (r.status IN ('queued','running') OR r.execution_outcome='unknown'))
            AND (? IS NULL OR g.next_run>? OR (g.next_run=? AND g.id>?))
            ORDER BY g.next_run,g.id LIMIT 32""",(now,now,now,due,due,due,identity))

    def run_due(self, now=None):
        now=time.time() if now is None else flow.timestamp(now); checked=0
        cursor=getattr(self,'_due_cursor',None)
        rows=self._due_rows(now,cursor)
        if not rows and cursor:
            self._due_cursor=None
            rows=self._due_rows(now,None)
        for row in rows:
            self._due_cursor=(row['next_run'],row['id'])
            try:
                context,workflow,p=self._ticket(row['id'],'schedule:'+format(row['next_run'],'.6f'),'scheduled',row['next_run'])
                self._submit(context,workflow,p); checked+=1
            except (ValueError,KeyError,TypeError):continue
            if checked>=4:break
        return {'checked':checked}

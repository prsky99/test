"""Server-issued workflow authority, explicit result grants and runtime controls."""
import hashlib
import hmac
import json
import secrets
import time

SCHEMA='''
CREATE TABLE IF NOT EXISTS execution_controls (
 id INTEGER PRIMARY KEY CHECK(id=1),invoke_enabled INTEGER NOT NULL,
 workflow_enabled INTEGER NOT NULL,delivery_enabled INTEGER NOT NULL,
 revision INTEGER NOT NULL,updated REAL NOT NULL);
INSERT OR IGNORE INTO execution_controls VALUES (1,1,1,1,0,0);
CREATE TABLE IF NOT EXISTS execution_control_events (
 revision INTEGER PRIMARY KEY,invoke_enabled INTEGER NOT NULL,workflow_enabled INTEGER NOT NULL,
 delivery_enabled INTEGER NOT NULL,admin_id INTEGER NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_delivery_grants (
 id TEXT PRIMARY KEY,workflow_id INTEGER NOT NULL,digest TEXT NOT NULL,destination_id TEXT NOT NULL,
 destination_hash TEXT NOT NULL,source TEXT NOT NULL,actor_key TEXT NOT NULL,
 created REAL NOT NULL,expires REAL NOT NULL,revoked REAL);
CREATE INDEX IF NOT EXISTS workflow_grants_lookup ON workflow_delivery_grants(workflow_id,source,actor_key);
CREATE TABLE IF NOT EXISTS workflow_run_authority (
 run_id TEXT PRIMARY KEY,payload TEXT NOT NULL,signature TEXT NOT NULL);
'''
CONTROL_KEYS=('invoke_enabled','workflow_enabled','delivery_enabled')
SOURCES=('admin','public','schedule','event','webapp','verification')
NOTICE='workflow-result-grant-v1'


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def controls(store):
    rows=store.query('SELECT * FROM execution_controls WHERE id=1')
    if not rows:raise ValueError('Execution policy is unavailable.')
    row=dict(rows[0]);return {**row,**{k:bool(row[k]) for k in CONTROL_KEYS}}


def require_enabled(store,kind='invoke'):
    from .concierge.execution_policy import ExecutionDenied
    try:enabled=controls(store)[kind+'_enabled']
    except Exception:raise ExecutionDenied('Execution is temporarily unavailable.',error_code='POLICY_DENIED') from None
    if not enabled:raise ExecutionDenied('Execution is temporarily paused.',error_code='POLICY_DENIED')


def set_controls(store,body,admin_id):
    if not isinstance(body,dict) or set(body)!={*CONTROL_KEYS,'revision'} or any(type(body[k]) is not bool for k in CONTROL_KEYS) or type(body['revision']) is not int:
        raise ValueError('Provide all control flags and their current revision.')
    with store.tx() as db:
        changed=db.execute('UPDATE execution_controls SET invoke_enabled=?,workflow_enabled=?,delivery_enabled=?,revision=revision+1,updated=? WHERE id=1 AND revision=?',
            (*[int(body[k]) for k in CONTROL_KEYS],time.time(),body['revision'])).rowcount
        if not changed:raise ValueError('Control revision changed. Reload before saving.')
        db.execute('INSERT INTO execution_control_events VALUES (?,?,?,?,?,?)',
            (body['revision']+1,*[int(body[k]) for k in CONTROL_KEYS],admin_id,time.time()))
    return controls(store)


class Authority:
    def __init__(self,store,key):self.store,self.key=store,hmac.new(key,b'workflow-authority-v1',hashlib.sha256).digest()

    def signature(self,payload):return hmac.new(self.key,canonical(payload).encode(),hashlib.sha256).hexdigest()

    def principal(self,kind,subject,workflow_id,*,role='operator'):
        if kind not in ('admin','public','deployment','schedule','event','verification'):raise ValueError('Unsupported execution principal.')
        payload={'kind':kind,'subject':str(subject),'workflow_id':workflow_id,'role':role if kind=='admin' else 'operator',
                 'audience':'workflow-runtime-v1','expires':time.time()+3600}
        if kind in ('schedule','event'):payload['automation_hash']=self.automation_hash(workflow_id)
        return {'payload':payload,'signature':self.signature(payload)}

    def automation_hash(self,workflow_id):
        rows=self.store.query('SELECT mode,enabled,preset,timezone,event_hash FROM workflow_schedules WHERE workflow_id=?',(workflow_id,))
        return hashlib.sha256(canonical(dict(rows[0]) if rows else {}).encode()).hexdigest()

    def validate(self,envelope,workflow_id,source):
        if not isinstance(envelope,dict) or not isinstance(envelope.get('payload'),dict) or not isinstance(envelope.get('signature'),str):raise ValueError('Execution authority is required.')
        p=envelope['payload']
        if not hmac.compare_digest(envelope['signature'],self.signature(p)):raise ValueError('Invalid execution authority.')
        kind={'webapp':'deployment'}.get(source,source)
        if source not in SOURCES or p.get('kind')!=kind or p.get('workflow_id')!=workflow_id or p.get('audience')!='workflow-runtime-v1' or p.get('expires',0)<=time.time():raise ValueError('Execution authority does not match this workflow.')
        if kind=='deployment':
            row=self.store.query('SELECT workflow_id,active FROM workflow_apps WHERE id=?',(p['subject'],))
            if not row or not row[0]['active'] or row[0]['workflow_id']!=workflow_id:raise ValueError('Deployment authorization was revoked.')
        if kind=='admin' and p['subject'].isdecimal():
            row=self.store.query('SELECT role,active FROM admin_users WHERE id=?',(int(p['subject']),))
            if not row or not row[0]['active'] or row[0]['role']!=p['role']:raise ValueError('Administrator execution authority changed.')
        if kind in ('schedule','event'):
            rows=self.store.query('SELECT mode,enabled FROM workflow_schedules WHERE workflow_id=?',(workflow_id,))
            if not rows or not rows[0]['enabled'] or rows[0]['mode']!=('scheduled' if kind=='schedule' else 'event_driven') or p.get('automation_hash')!=self.automation_hash(workflow_id):raise ValueError('Automatic execution authorization changed.')
        return p

    def actor_key(self,p):return hmac.new(self.key,(p['kind']+':'+p['subject']).encode(),hashlib.sha256).hexdigest()

    @staticmethod
    def destination_hash(destination):return hashlib.sha256((destination.get('sealed') or '').encode()).hexdigest()

    def issue(self,workflow_id,digest,destination,sources,principal):
        if principal['kind']!='admin' or not sources or set(sources)-{'admin','schedule','event'}:raise ValueError('Only explicit administrator result delivery can be granted.')
        now=time.time();items=[]
        with self.store.tx() as db:
            db.execute('UPDATE workflow_delivery_grants SET revoked=? WHERE workflow_id=? AND revoked IS NULL',(now,workflow_id))
            for source in sources:
                p=principal if source=='admin' else self.principal(source,str(workflow_id),workflow_id)['payload']
                identity='dg_'+secrets.token_hex(16)
                db.execute('INSERT INTO workflow_delivery_grants VALUES (?,?,?,?,?,?,?,?,?,NULL)',
                    (identity,workflow_id,digest,destination['id'],self.destination_hash(destination),source,self.actor_key(p),now,now+30*86400))
                items.append(identity)
        return items

    def choose(self,workflow_id,digest,source,principal):
        if source not in ('admin','schedule','event'):return None
        rows=self.store.query('SELECT id FROM workflow_delivery_grants WHERE workflow_id=? AND digest=? AND source=? AND actor_key=? AND revoked IS NULL AND expires>? ORDER BY created DESC LIMIT 1',
            (workflow_id,digest,source,self.actor_key(principal),time.time()))
        return rows[0][0] if rows else None

    def save_run(self,db,run_id,workflow_id,digest,source,envelope,grant):
        payload={'principal':envelope,'workflow_id':workflow_id,'digest':digest,'source':source,'grant_id':grant,'run_id':run_id}
        db.execute('INSERT INTO workflow_run_authority VALUES (?,?,?)',(run_id,canonical(payload),self.signature(payload)))

    def run(self,run_id,workflow_id,digest,source):
        rows=self.store.query('SELECT * FROM workflow_run_authority WHERE run_id=?',(run_id,))
        if not rows:return None
        row=rows[0];payload=json.loads(row['payload'])
        if not hmac.compare_digest(row['signature'],self.signature(payload)) or any(payload.get(k)!=v for k,v in {'run_id':run_id,'workflow_id':workflow_id,'digest':digest,'source':source}.items()):raise ValueError('Stored execution authority changed.')
        self.validate(payload['principal'],workflow_id,source)
        return payload

    def delivery(self,run, destination):
        if not run or not run.get('grant_id'):return False
        try:p=self.validate(run['principal'],run['workflow_id'],run['source'])
        except ValueError:return False
        if run['source'] not in ('admin','schedule','event'):return False
        current=self.store.query("SELECT * FROM workflow_destinations WHERE id=? AND workflow_id=? AND state='verified'",(destination['id'],run['workflow_id']))
        if not current or self.destination_hash(dict(current[0]))!=self.destination_hash(destination):return False
        rows=self.store.query('SELECT * FROM workflow_delivery_grants WHERE id=? AND workflow_id=? AND digest=? AND source=? AND actor_key=? AND destination_id=? AND destination_hash=? AND revoked IS NULL AND expires>?',
            (run['grant_id'],run['workflow_id'],run['digest'],run['source'],self.actor_key(p),destination['id'],self.destination_hash(destination),time.time()))
        return bool(rows and destination['state']=='verified')

    def grants(self,workflow_id):
        return [dict(r) for r in self.store.query('SELECT id,source,created,expires,revoked FROM workflow_delivery_grants WHERE workflow_id=? ORDER BY created DESC LIMIT 30',(workflow_id,))]

    def revoke(self,workflow_id,identity=None):
        with self.store.tx() as db:
            if identity:db.execute('UPDATE workflow_delivery_grants SET revoked=? WHERE workflow_id=? AND id=? AND revoked IS NULL',(time.time(),workflow_id,identity))
            else:db.execute('UPDATE workflow_delivery_grants SET revoked=? WHERE workflow_id=? AND revoked IS NULL',(time.time(),workflow_id))

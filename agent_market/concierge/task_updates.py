"""Purpose-scoped task watches, private destinations, and bounded delivery."""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import stat
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

# PyCryptodome >=3.20 supplies this namespace; the deprecated PyCrypto package is not used.
from Crypto.Cipher import AES  # nosec B413

from .browser_push import BrowserPush, validate_subscription
from .protocols import PROTOCOLS
from .selection import search_terms
from .security import check_malicious_text
from ..observability import journal_for, stable_reference, attempt_scope, provider_dispatch

NOTICE_VERSION = 'task-updates-2026-10-17-v1'
DESTINATION_NOTICE = 'destination-confirmation-2026-10-17-v1'
MARKETING_NOTICE = 'optional-marketing-2026-10-17-v1'
WATCH_TTL = 90 * 86400
CODE_TTL = 3600
CADENCE = 86400
_OUTBOUND_SLOTS = threading.BoundedSemaphore(4)
_UNREVIEWED = object()


class UpdateError(ValueError):
    pass


class TaskUpdates:
    """No visitor tier or marketing flags can authorize this sender."""

    def __init__(self, store, rec, courier):
        self.store, self.rec, self.courier = store, rec, courier
        self.lock = threading.RLock()
        self.key = self._load_key()
        self.journal=journal_for(store)
        self.push = BrowserPush(self.key)
        self.outbound_enabled = os.environ.get('AGENT_TASK_UPDATES_OUTBOUND','1') == '1'

    def _load_key(self):
        if getattr(self.store, 'backend', 'sqlite') == 'postgresql':
            key = getattr(self.store, 'workflow_key', None)
            if type(key) is not bytes or len(key) != 32:
                raise ValueError('PostgreSQL requires an explicit persistent workflow key.')
            return key
        configured = os.environ.get('AGENT_UPDATES_KEY')
        if configured:
            key = base64.urlsafe_b64decode(configured)
            if len(key) != 32:
                raise ValueError('Invalid task update encryption key')
            return key
        path = self.store.query('PRAGMA database_list')[0]['file']
        if not path:
            return secrets.token_bytes(32)
        key_path = Path(path + '.updates-key')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os,'O_NONBLOCK',0)
        try:
            fd = os.open(key_path, flags)
        except FileNotFoundError:
            try:
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            except FileExistsError:
                fd = os.open(key_path, flags)
            else:
                with os.fdopen(fd, 'wb') as out:
                    out.write(secrets.token_bytes(32))
                    out.flush()
                    os.fsync(out.fileno())
                fd = os.open(key_path, flags)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or hasattr(os,'geteuid') and info.st_uid!=os.geteuid():
                raise ValueError('Task update encryption key requires private permissions')
            key = source.read(33)
        if len(key) != 32:
            raise ValueError('Invalid task update encryption key')
        return key

    def _seal(self, value, watch_id):
        cipher = AES.new(self.key, AES.MODE_GCM)
        cipher.update(watch_id.encode())
        raw, tag = cipher.encrypt_and_digest(json.dumps(value).encode())
        return base64.urlsafe_b64encode(cipher.nonce + tag + raw).decode()

    def _open(self, sealed, watch_id):
        raw = base64.urlsafe_b64decode(sealed)
        cipher = AES.new(self.key, AES.MODE_GCM, nonce=raw[:16])
        cipher.update(watch_id.encode())
        return json.loads(cipher.decrypt_and_verify(raw[32:], raw[16:32]))

    def _get(self, watch_id, visitor_id=None):
        rows = self.store.query('SELECT * FROM agent_task_watches WHERE id=?', (watch_id,))
        if not rows or visitor_id is not None and rows[0]['visitor_id'] != visitor_id:
            raise UpdateError('Task updates not found.')
        return dict(rows[0])

    def _permission(self, db, row, action):
        db.execute('INSERT INTO agent_task_permissions (watch_id,visitor_id,action,purpose,notice_version,at) VALUES (?,?,?,?,?,?)',
                   (row['id'],row['visitor_id'],action,'task_updates',NOTICE_VERSION,time.time()))

    def capability(self,watch_id):
        return watch_id+'.'+hmac.new(self.key,('stop:'+watch_id).encode(),hashlib.sha256).hexdigest()

    def stop_capability(self,capability):
        if not isinstance(capability,str) or not re.fullmatch(r'tw_[0-9a-f]{32}\.[0-9a-f]{64}',capability):
            raise UpdateError('This stop link is unavailable.')
        watch_id=capability.split('.')[0]
        if not hmac.compare_digest(capability,self.capability(watch_id)):
            raise UpdateError('This stop link is unavailable.')
        try:
            row=self._get(watch_id)
            self.action(row['visitor_id'],watch_id,'stop')
        except UpdateError:
            pass

    def _evidence(self, task, protocol):
        if not (type(task) is str and task.strip()):
            return 'null', None
        try:
            items = self.rec.search(task.strip(), kind=protocol)
        except Exception:
            return 'null', None
        item = items[0] if items else None
        # Public gateway URLs remain stable when a private provider binding changes.
        # Keep binding evidence private and bind approval/queued delivery to it.
        resource = self.store.resource(item['id']) if item else None
        binding = {key:resource.get(key) for key in (
            'id','kind','url','usage_tools_hash','usage_full_hash',
            'active','health_status','auth_observed','auth_declared')} if resource else None
        if resource:
            for field, keys in (
                ('usage_guide',('binding','endpoint','agent_card','methods')),
                ('details',('spec_version','protocolVersion','protocol_version')),
            ):
                value=resource.get(field) or {}
                if isinstance(value,str):
                    try:value=json.loads(value)
                    except ValueError:value={}
                binding[field]={key:value.get(key) for key in keys} if isinstance(value,dict) else None
        digest = hmac.new(self.key, ('task-binding-v1:' + json.dumps(
            binding, sort_keys=True, separators=(',',':'))).encode(), hashlib.sha256).hexdigest()
        snapshot = [item['id'], item.get('grade'), (item.get('test_report') or {}).get('id'), digest] if item else None
        return json.dumps(snapshot), item

    def _queued_evidence(self, evidence):
        return hmac.new(self.key, ('task-queue-v1:' + evidence).encode(), hashlib.sha256).hexdigest()

    def create(self, visitor_id, data):
        if data.get('authority') is not True or data.get('task_updates') is not True or data.get('notice_version') != NOTICE_VERSION:
            raise UpdateError('Confirm authorization and the task update notice.')
        task = data.get('task')
        if not isinstance(task, str) or not 1 <= len(task.strip()) <= 160 or not search_terms(task):
            raise UpdateError('Use a short task label without personal information.')
        bad, _ = check_malicious_text(task)
        if bad or re.search(r'https?://|\bvt_|[\w.+-]+@[\w.-]+|[\x00-\x1f]',task,re.I):
            raise UpdateError('Use a short task label without personal information.')
        protocol = data.get('protocol') or None
        if protocol is not None and (not isinstance(protocol,str) or protocol not in PROTOCOLS):
            raise UpdateError('Choose a supported protocol.')
        channel = data.get('channel')
        if channel not in ('poll','browser','webhook','a2a'):
            raise UpdateError('Choose a supported delivery method.')
        if channel!='poll' and not self.outbound_enabled:
            raise UpdateError('Notification delivery is unavailable. Choose manual checks.')
        if channel!='poll' and (data.get('destination_confirmed') is not True or data.get('destination_notice_version')!=DESTINATION_NOTICE):
            raise UpdateError('Confirm the selected notification destination.')
        if type(data.get('marketing',False)) is not bool:
            raise UpdateError('Choose marketing updates separately.')
        if data.get('marketing') and (channel=='poll' or data.get('marketing_notice_version')!=MARKETING_NOTICE):
            raise UpdateError('Review the separate marketing notice for a verified destination.')
        self.maintain()
        now = time.time()
        watch_id = 'tw_' + secrets.token_hex(16)
        baseline, _ = self._evidence(task.strip(), protocol)
        sealed = code_hash = None
        destination_hash=None
        if channel != 'poll':
            if channel=='browser':
                try:
                    subscription=validate_subscription(data.get('subscription'))
                except (ValueError,TypeError) as exc:
                    raise UpdateError('Use a valid browser-generated push subscription.') from exc
                url=subscription['endpoint']
                code=secrets.token_urlsafe(32)
                secret={'url':url,'subscription':subscription,'code':code}
            else:
                url=data.get('url')
                self.validate_destination(url)
                code=f'{secrets.randbelow(10**6):06d}'
                secret={'url':url,'code':code,'secret':secrets.token_urlsafe(32)}
            code_hash=hashlib.sha256((watch_id+code).encode()).hexdigest()
            sealed=self._seal(secret,watch_id)
            destination_hash=hmac.new(self.key,(channel+':'+url).encode(),hashlib.sha256).hexdigest()
        # Preserve abuse limits after a declined pending request is physically removed.
        if not self._budget(visitor_id,'registration',5,3600) or not self._budget('all','registration',500,3600):
            raise UpdateError('Please wait before requesting more task updates.')
        with self.lock, self.store.tx() as db:
            if destination_hash and db.execute("SELECT 1 FROM agent_task_watches w JOIN agent_task_destination_checks c ON c.watch_id=w.id WHERE w.visitor_id=? AND c.destination_hash=? AND LOWER(TRIM(w.task))=? AND COALESCE(w.protocol,'')=? AND w.state IN ('active','paused','pending_verification') AND w.expires>?",(visitor_id,destination_hash,task.strip().lower(),protocol or '',now)).fetchone():
                raise UpdateError('This task already has a request for that destination. Manage the existing request.')
            if db.execute('SELECT COUNT(*) FROM agent_task_watches WHERE visitor_id=? AND created>?', (visitor_id,now-3600)).fetchone()[0] >= 5:
                raise UpdateError('Please wait before requesting more task updates.')
            if db.execute('SELECT COUNT(*) FROM agent_task_watches WHERE created>?',(now-3600,)).fetchone()[0] >= 500:
                raise UpdateError('Task updates are busy. Please try again later.')
            if db.execute("SELECT COUNT(*) FROM agent_task_watches WHERE state IN ('active','paused','pending_verification')").fetchone()[0] >= 1000:
                raise UpdateError('Task updates are busy. Please try again later.')
            if db.execute("SELECT COUNT(*) FROM agent_task_watches WHERE visitor_id=? AND state IN ('active','paused','pending_verification')",(visitor_id,)).fetchone()[0] >= 10:
                raise UpdateError('Stop an existing task update before adding another.')
            db.execute('''INSERT INTO agent_task_watches
                (id,visitor_id,task,protocol,channel,state,sealed,code_hash,code_expires,created,expires,baseline,notice_version,authority)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)''',
                (watch_id,visitor_id,task.strip(),protocol,channel,'active' if channel=='poll' else 'pending_verification',
                 sealed,code_hash,now+CODE_TTL if sealed else None,now,now+WATCH_TTL,baseline,NOTICE_VERSION))
            if destination_hash:
                db.execute('INSERT INTO agent_task_destination_checks VALUES (?,?,?,?,?)',(watch_id,DESTINATION_NOTICE,now,None,destination_hash))
            if data.get('marketing'):
                db.execute('INSERT INTO agent_marketing_permissions VALUES (?,?,?,?,?,?,?)',(watch_id,visitor_id,MARKETING_NOTICE,now,None,None,now+WATCH_TTL))
                db.execute('INSERT INTO agent_task_permissions (watch_id,visitor_id,action,purpose,notice_version,at) VALUES (?,?,?,?,?,?)',(watch_id,visitor_id,'requested','marketing',MARKETING_NOTICE,now))
            self._permission(db,{'id':watch_id,'visitor_id':visitor_id},'requested')
        return self.public(self._get(watch_id))

    @staticmethod
    def validate_destination(url):
        try:
            if not isinstance(url,str) or len(url)>500 or re.search(r'[\s\\\x00-\x1f]',url):
                raise ValueError()
            p = urlsplit(url)
            if p.scheme!='https' or not p.hostname or p.username is not None or p.password is not None or p.fragment or p.query or p.port not in (None,443):
                raise ValueError()
            if p.hostname=='localhost' or p.hostname.endswith(('.localhost','.local','.internal')) or '%' in p.hostname:
                raise ValueError()
            try:
                address=ipaddress.ip_address(p.hostname)
            except ValueError:
                address=None
            if address is not None and not address.is_global:
                raise ValueError()
            if p.hostname in ('hooks.slack.com','discord.com','discordapp.com') or any(x in p.path.lower() for x in ('/webhooks/','/trigger/','/workflows/')):
                raise ValueError()
        except ValueError:
            raise UpdateError('Use a dedicated HTTPS notification inbox without credentials or query parameters.')

    def _budget(self,destination,kind,maximum,window):
        key=hmac.new(self.key,(kind+':'+destination).encode(),hashlib.sha256).hexdigest()
        now=time.time()
        with self.store.tx() as db:
            row=db.execute('SELECT * FROM agent_task_budgets WHERE key=?',(key,)).fetchone()
            if row and now-row['started']<window and row['n']>=maximum:
                return False
            count=row['n']+1 if row and now-row['started']<window else 1
            start=row['started'] if count>1 else now
            db.execute('INSERT OR REPLACE INTO agent_task_budgets VALUES (?,?,?)',(key,start,count))
        return True

    def send_challenge(self, watch_id):
        """A fixed verification payload is the only outbound message before activation."""
        if not _OUTBOUND_SLOTS.acquire(blocking=False):
            return
        try:
            return self._send_challenge(watch_id)
        finally:
            _OUTBOUND_SLOTS.release()

    def _send_challenge(self,watch_id):
        if not self.outbound_enabled:
            return
        with self.lock:
            rows=self.store.query('SELECT * FROM agent_task_watches WHERE id=?',(watch_id,))
            if not rows:
                return
            row=dict(rows[0])
            if row['state']!='pending_verification' or row['verification_sent'] or row['code_expires']<time.time():
                return
            secret = self._open(row['sealed'],watch_id)
            host = urlsplit(secret['url']).hostname
            if not self._budget(secret['url'] if row['channel']=='browser' else host,'verification',3 if row['channel']=='browser' else 10,3600):
                self._fail_verification(row)
                return
            with self.store.tx() as db:
                db.execute('UPDATE agent_task_watches SET verification_sent=1 WHERE id=?',(watch_id,))
        try:
            if row['channel']=='browser':
                ok,_=self.push.send(secret['subscription'],{'type':'browser_verification','watch_id':watch_id,'challenge':secret['code'],'expires_at':row['code_expires']},ttl=300)
                if not ok:
                    self._fail_verification(row)
                return
            target = self.courier.resolve(row['channel'],secret['url'])
            self.validate_destination(target['url'])
            if row['channel']=='a2a':
                source,destination=urlsplit(secret['url']),urlsplit(target['url'])
                if (source.scheme,source.hostname,source.port or 443)!=(destination.scheme,destination.hostname,destination.port or 443):
                    raise UpdateError('Use the actual A2A inbox URL when the agent card points to a different origin.')
            contact = {'type':row['channel'],'url':secret['url'],'endpoint':json.dumps(target)}
            ok,_ = self.courier.send(contact,'task_verification','Confirm this requested task update destination.',
                                    {'watch_id':watch_id,'verification_code':secret['code'],'signing_secret':secret['secret'],'expires_in':CODE_TTL,
                                     'key_id':hashlib.sha256(secret['secret'].encode()).hexdigest()[:16],
                                     'stop_url':'https://agentconcierge.biz/#stop-updates='+self.capability(watch_id)})
            with self.lock, self.store.tx() as db:
                current_rows=self.store.query('SELECT * FROM agent_task_watches WHERE id=?',(watch_id,))
                if not current_rows:
                    return
                current = dict(current_rows[0])
                if current['state']!='pending_verification':
                    return
                if not ok:
                    self._fail_verification(current)
                    return
                secret.pop('code',None)
                secret['target']=target
                db.execute('UPDATE agent_task_watches SET sealed=? WHERE id=?',(self._seal(secret,watch_id),watch_id))
        except Exception:
            with self.lock:
                current_rows=self.store.query('SELECT * FROM agent_task_watches WHERE id=?',(watch_id,))
                if current_rows:
                    self._fail_verification(dict(current_rows[0]))

    def _fail_verification(self,row):
        with self.store.tx() as db:
            db.execute("UPDATE agent_task_watches SET state='failed',sealed=NULL,code_hash=NULL,task='',revoked_at=? WHERE id=?",(time.time(),row['id']))

    def verify(self,visitor_id,watch_id,code):
        with self.lock, self.store.tx() as db:
            row = self._get(watch_id,visitor_id)
            if row['channel']=='browser' or row['state']!='pending_verification' or not row['verification_sent'] or not row['code_hash'] or row['code_expires']<time.time():
                raise UpdateError('Verification is unavailable or expired.')
            actual = hashlib.sha256((watch_id+str(code)).encode()).hexdigest()
            if not re.fullmatch(r'\d{6}',str(code)) or not hmac.compare_digest(actual,row['code_hash']):
                db.execute('UPDATE agent_task_watches SET verify_failures=verify_failures+1 WHERE id=?',(watch_id,))
                if row['verify_failures']>=4:
                    self._fail_verification(row)
                # Raise after the transaction commits the failed-attempt counter.
                valid = False
            else:
                secret = self._open(row['sealed'],watch_id)
                if 'target' not in secret:
                    raise UpdateError('Verification is not ready. Please try again.')
                db.execute("UPDATE agent_task_watches SET state='active',code_hash=NULL,verified_at=? WHERE id=?",(time.time(),watch_id))
                self._confirm_destination(db,row)
                self._permission(db,row,'confirmed')
                valid = True
        if not valid:
            raise UpdateError('Verification could not be confirmed.')
        return self.public(self._get(watch_id))

    def _confirm_destination(self,db,row):
        now=time.time()
        db.execute('UPDATE agent_task_destination_checks SET verified_at=? WHERE watch_id=?',(now,row['id']))
        changed=db.execute('UPDATE agent_marketing_permissions SET verified_at=? WHERE watch_id=? AND withdrawn_at IS NULL AND verified_at IS NULL',(now,row['id'])).rowcount
        if changed:
            db.execute('INSERT INTO agent_task_permissions (watch_id,visitor_id,action,purpose,notice_version,at) VALUES (?,?,?,?,?,?)',(row['id'],row['visitor_id'],'destination_verified','marketing',MARKETING_NOTICE,now))

    def destination_facts(self,row):
        checks=self.store.query('SELECT confirmed_at,verified_at,notice_version FROM agent_task_destination_checks WHERE watch_id=?',(row['id'],))
        marketing=self.store.query('SELECT * FROM agent_marketing_permissions WHERE watch_id=?',(row['id'],))
        grant=dict(marketing[0]) if marketing else None
        verified=bool(row['channel']!='poll' and row['verified_at'] and row['sealed'] and row['authority'] and row['notice_version']==NOTICE_VERSION and row['state'] in ('active','paused') and row['expires']>time.time())
        return {'destination_confirmed_at':checks[0]['confirmed_at'] if checks else None,
                'destination_verified':verified,'marketing_requested':bool(grant and not grant['withdrawn_at'] and grant['expires']>time.time()),
                'marketing_status':'not_requested' if not grant else 'withdrawn' if grant['withdrawn_at'] else 'expired' if grant['expires']<=time.time() else 'confirmed' if verified and grant['verified_at'] else 'pending_verification',
                'marketing_eligible':bool(verified and row['state']=='active' and grant and grant['verified_at'] and not grant['withdrawn_at'] and grant['expires']>time.time() and grant['notice_version']==MARKETING_NOTICE),
                'marketing_notice_version':grant['notice_version'] if grant else None}

    def decline(self,visitor_id,watch_id):
        with self.lock,self.store.tx() as db:
            rows=db.execute('SELECT * FROM agent_task_watches WHERE id=?',(watch_id,)).fetchall()
            if rows:
                row=dict(rows[0])
                if row['visitor_id']!=visitor_id:
                    raise UpdateError('Task updates not found.')
                if row['verified_at']:
                    self._permission(db,row,'declined')
                    self._withdraw_marketing(db,row)
                else:
                    db.execute('DELETE FROM agent_task_permissions WHERE watch_id=?',(watch_id,))
                    db.execute('DELETE FROM agent_marketing_permissions WHERE watch_id=?',(watch_id,))
                db.execute('DELETE FROM agent_task_events WHERE watch_id=?',(watch_id,))
                db.execute('DELETE FROM agent_task_destination_checks WHERE watch_id=?',(watch_id,))
                db.execute('DELETE FROM agent_task_watches WHERE id=?',(watch_id,))
        return {'id':watch_id,'state':'deleted'}

    def _withdraw_marketing(self,db,row):
        changed=db.execute('UPDATE agent_marketing_permissions SET withdrawn_at=? WHERE watch_id=? AND withdrawn_at IS NULL',(time.time(),row['id'])).rowcount
        if changed:
            db.execute('INSERT INTO agent_task_permissions (watch_id,visitor_id,action,purpose,notice_version,at) VALUES (?,?,?,?,?,?)',(row['id'],row['visitor_id'],'withdrawn','marketing',MARKETING_NOTICE,time.time()))

    def withdraw_marketing(self,visitor_id,watch_id):
        with self.lock,self.store.tx() as db:
            row=self._get(watch_id,visitor_id)
            self._withdraw_marketing(db,row)
        return self.public(self._get(watch_id,visitor_id))

    def confirm_browser(self,watch_id,challenge,decision):
        if not isinstance(watch_id,str) or not re.fullmatch(r'tw_[0-9a-f]{32}',watch_id):
            raise UpdateError('Browser verification is unavailable.')
        if decision not in ('confirm','decline') or not isinstance(challenge,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',challenge):
            raise UpdateError('Browser verification is unavailable.')
        with self.lock,self.store.tx() as db:
            row=self._get(watch_id)
            if row['channel']!='browser' or row['state']!='pending_verification' or not row['verification_sent'] or not row['code_hash'] or row['code_expires']<time.time():
                raise UpdateError('Browser verification is unavailable.')
            actual=hashlib.sha256((watch_id+challenge).encode()).hexdigest()
            if not hmac.compare_digest(actual,row['code_hash']):
                raise UpdateError('Browser verification is unavailable.')
            if decision=='decline':
                return self.decline(row['visitor_id'],watch_id)
            db.execute("UPDATE agent_task_watches SET state='active',code_hash=NULL,verified_at=? WHERE id=?",(time.time(),watch_id))
            secret=self._open(row['sealed'],watch_id);secret.pop('code',None)
            db.execute('UPDATE agent_task_watches SET sealed=? WHERE id=?',(self._seal(secret,watch_id),watch_id))
            self._confirm_destination(db,row)
            self._permission(db,row,'confirmed')
        return {'id':watch_id,'state':'active'}

    def public(self,row):
        return {**{k:row[k] for k in ('id','task','protocol','channel','state','created','expires','notice_version')},**self.destination_facts(row)}

    def list(self,visitor_id):
        self.maintain()
        return [self.public(dict(row)) for row in self.store.query('SELECT * FROM agent_task_watches WHERE visitor_id=? ORDER BY created DESC LIMIT 20',(visitor_id,))]

    def action(self,visitor_id,watch_id,action):
        if action=='check':
            with self.lock:
                row=self._get(watch_id,visitor_id)
                if row['state']!='active' or row['expires']<=time.time():
                    raise UpdateError('Only active task updates can be checked.')
                items=self.events(visitor_id,watch_id)
                with self.store.tx() as db:
                    self._permission(db,row,'checked')
                return {'items':items}
        if action=='decline':
            return self.decline(visitor_id,watch_id)
        if action=='withdraw_marketing':
            return self.withdraw_marketing(visitor_id,watch_id)
        if action not in ('pause','resume','stop','delete','renew'):
            raise UpdateError('Choose a supported action.')
        with self.lock, self.store.tx() as db:
            row = self._get(watch_id,visitor_id)
            active = row['state'] in ('active','paused') and row['expires']>time.time()
            if action in ('resume','renew') and not active:
                raise UpdateError('Request and verify task updates again.')
            if action in ('resume','renew') and row['notice_version']!=NOTICE_VERSION:
                raise UpdateError('Review the current task update notice before requesting updates again.')
            if action=='pause' and row['state']!='active':
                raise UpdateError('Only active task updates can be paused.')
            state = {'pause':'paused','resume':'active','stop':'revoked','delete':'revoked','renew':row['state']}[action]
            db.execute('UPDATE agent_task_watches SET state=?,expires=? WHERE id=?',
                       (state,time.time()+WATCH_TTL if action=='renew' else row['expires'],watch_id))
            if action in ('stop','delete'):
                self._withdraw_marketing(db,row)
                db.execute('UPDATE agent_task_watches SET sealed=NULL,code_hash=NULL,task=\'\',protocol=NULL,baseline=NULL,revoked_at=? WHERE id=?',(time.time(),watch_id))
                if row['state'] in ('active','paused','pending_verification'):
                    # Commit minimal customer-request evidence with the withdrawal.
                    # Do not retain destinations, task text, tokens or stop capabilities.
                    db.execute("""INSERT INTO cancellation_requests
                        (request_id,created_at,visitor_id,source,reason,status)
                        VALUES (?,?,?,'task_updates',?,'cancelled')""",
                        ('cnl_'+secrets.token_hex(16),time.time(),visitor_id,
                         'Notification data deleted' if action=='delete' else 'Task updates stopped'))
            if action in ('pause','stop','delete'):
                db.execute("UPDATE agent_task_events SET status='cancelled',payload='{}' WHERE watch_id=? AND status IN ('pending','ready')",(watch_id,))
            if action=='delete':
                db.execute('DELETE FROM agent_task_events WHERE watch_id=?',(watch_id,))
            if action=='delete':
                db.execute('DELETE FROM agent_task_destination_checks WHERE watch_id=?',(watch_id,))
            self._permission(db,row,action)
        return self.public(self._get(watch_id))

    def stop_all(self,visitor_id):
        for row in self.list(visitor_id):
            if row['state'] in ('active','paused','pending_verification'):
                self.action(visitor_id,row['id'],'stop')

    def maintain(self):
        now = time.time()
        with self.lock, self.store.tx() as db:
            db.execute("UPDATE agent_task_watches SET state='expired',sealed=NULL,code_hash=NULL,task='',protocol=NULL,baseline=NULL,revoked_at=? WHERE (expires<? AND state IN ('active','paused')) OR (code_expires<? AND state='pending_verification')",(now,now,now))
            db.execute("UPDATE agent_task_events SET status='cancelled',payload='{}' WHERE status IN ('pending','ready') AND watch_id IN (SELECT id FROM agent_task_watches WHERE state IN ('revoked','expired','failed'))")
            db.execute('DELETE FROM agent_task_events WHERE created<?',(now-30*86400,))
            db.execute('DELETE FROM agent_task_permissions WHERE at<?',(now-730*86400,))
            db.execute("UPDATE agent_marketing_permissions SET withdrawn_at=COALESCE(withdrawn_at,?) WHERE watch_id IN (SELECT id FROM agent_task_watches WHERE state='revoked')",(now,))
            db.execute('DELETE FROM agent_marketing_permissions WHERE requested_at<?',(now-730*86400,))
            db.execute('DELETE FROM agent_task_budgets WHERE started<?',(now-86400,))
            db.execute("UPDATE agent_task_events SET status='unknown' WHERE status='sending' AND evidence LIKE 'dependency:%' AND next_attempt<?",(now,))
            db.execute("UPDATE agent_task_events SET status='pending' WHERE status='sending' AND evidence NOT LIKE 'dependency:%' AND next_attempt<?",(now,))
            stale="SELECT id FROM agent_task_watches WHERE state IN ('pending_verification','failed','expired','revoked') AND channel!='poll' AND verified_at IS NULL AND created<?"
            stale_ids=[(r[0],) for r in db.execute(stale,(now-86400,))]
            db.executemany('DELETE FROM agent_task_permissions WHERE watch_id=?',stale_ids)
            db.executemany('DELETE FROM agent_task_events WHERE watch_id=?',stale_ids)
            db.executemany('DELETE FROM agent_task_destination_checks WHERE watch_id=?',stale_ids)
            db.executemany('DELETE FROM agent_marketing_permissions WHERE watch_id=?',stale_ids)
            db.executemany('DELETE FROM agent_task_watches WHERE id=?',stale_ids)
            db.execute("DELETE FROM agent_task_watches WHERE state IN ('revoked','expired','failed') AND revoked_at<?",(now-730*86400,))
            db.execute('DELETE FROM agent_task_destination_checks WHERE watch_id NOT IN (SELECT id FROM agent_task_watches)')

    def refresh(self,visitor_id=None,watch_id=None,reviewed=_UNREVIEWED):
        self.maintain()
        rows = self.store.query("SELECT * FROM agent_task_watches WHERE state='active' AND (? IS NULL OR visitor_id=?) AND (? IS NULL OR id=?) ORDER BY last_checked,created LIMIT 200",(visitor_id,visitor_id,watch_id,watch_id))
        for raw in rows:
            row = dict(raw)
            if not self.admin_summary(row)['permission_current']:
                continue
            with self.store.tx() as db:
                db.execute('UPDATE agent_task_watches SET last_checked=? WHERE id=?',(time.time(),row['id']))
            evidence,item = self._evidence(row['task'],row['protocol'])
            if reviewed is not _UNREVIEWED and self.delivery_recommendation(item)!=reviewed:
                continue
            if evidence==row['baseline'] or row['last_event'] and row['last_event']>time.time()-CADENCE:
                continue
            # Send only essential public connection/evidence facts, never saved prompts or visitor IDs.
            public_item = {k:item.get(k) for k in ('id','name','kind','url','usage_endpoint','grade','test_report','active_checked_at')} if item else None
            payload = {'type':'task_update','purpose':'task_updates','schema_version':1,'untrusted_listing_data':True,'recommendation':public_item,'message':'Verification evidence changed.' if item else 'No currently active, relevant agent found.','return_url':'https://agentconcierge.biz/#chat','preferences_url':'https://agentconcierge.biz/#cancellation','stop_url':'https://agentconcierge.biz/#stop-updates='+self.capability(row['id'])}
            with self.lock,self.store.tx() as db:
                remaining=self.store.query('SELECT * FROM agent_task_watches WHERE id=?',(row['id'],))
                if not remaining:
                    continue
                fresh=dict(remaining[0])
                if not self.admin_summary(fresh)['permission_current'] or fresh['baseline']!=row['baseline']:
                    continue
                event_key=hashlib.sha256((str(row['baseline'])+'>'+evidence+':'+str(int(time.time()/CADENCE))).encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO agent_task_events (id,watch_id,created,payload,status,next_attempt,evidence) VALUES (?,?,?,?,?,?,?)',
                           ('te_'+secrets.token_hex(16),row['id'],time.time(),json.dumps(payload),'ready' if row['channel']=='poll' else 'pending',time.time(),event_key+':'+self._queued_evidence(evidence)))
                db.execute('UPDATE agent_task_watches SET baseline=?,last_event=? WHERE id=?',(evidence,time.time(),row['id']))

    def events(self,visitor_id,watch_id):
        row=self._get(watch_id,visitor_id)
        if row['state']!='active' or row['expires']<=time.time():
            return []
        self.refresh(visitor_id)
        return [{'id':r['id'],'created':r['created'],**json.loads(r['payload'])} for r in self.store.query("SELECT * FROM agent_task_events WHERE watch_id=? AND status IN ('ready','sent') ORDER BY created DESC LIMIT 10",(watch_id,))]

    def run_due(self,force_visitor=None):
        deadline=time.monotonic()+30
        front=getattr(self,'_front',None)
        if front is not None:
            from ..agent_access.service import for_front
            from ..agent_access.storage import ready
            if ready(self.store):for_front(front).events.tick()
        self.refresh(force_visitor)
        if not self.outbound_enabled:
            return {'checked':0,'sent':0,'nothing_new':0,'failed':0}
        for row in self.store.query("SELECT id FROM agent_task_watches WHERE state='pending_verification' AND verification_sent=0 AND (? IS NULL OR visitor_id=?) LIMIT 10",(force_visitor,force_visitor)):
            if time.monotonic()>deadline:
                break
            self.send_challenge(row['id'])
        stats={'checked':0,'sent':0,'nothing_new':0,'failed':0}
        sql="SELECT e.* FROM agent_task_events e JOIN agent_task_watches w ON w.id=e.watch_id WHERE e.status='pending' AND e.next_attempt<=?"
        args=[time.time()]
        if force_visitor:
            sql+=' AND w.visitor_id=?';args.append(force_visitor)
        for raw in self.store.query(sql+' ORDER BY e.created LIMIT 20',args):
            if time.monotonic()>deadline:
                break
            result=self._attempt(dict(raw))
            if result:
                stats['checked']+=1
                stats[result]+=1
        return stats

    def _attempt(self,event,reviewed=_UNREVIEWED):
        if not self.outbound_enabled:
            return None
        from ..execution_authority import require_enabled
        from .execution_policy import ExecutionDenied
        try:require_enabled(self.store,'delivery')
        except ExecutionDenied:return None
        if not _OUTBOUND_SLOTS.acquire(blocking=False):
            return None
        try:
            with self.lock,self.store.tx() as db:
                remaining=self.store.query('SELECT * FROM agent_task_watches WHERE id=?',(event['watch_id'],))
                if not remaining:
                    return None
                row=dict(remaining[0])
                if not self.admin_summary(row)['permission_current'] or not row['sealed']:
                    return None
                payload=json.loads(event['payload'])
                dependency=payload.get('type')=='dependency_update'
                dependency_valid=False
                if not dependency:
                    evidence,item=self._evidence(row['task'],row['protocol'])
                    current=self.delivery_recommendation(item)
                    queue_seal = str(event.get('evidence') or '').partition(':')[2]
                if dependency and getattr(self,'_front',None)is not None:
                    from ..agent_access.service import for_front
                    dependency_valid=for_front(self._front).events.delivery_valid(row,event,payload) and reviewed is _UNREVIEWED
                if ((dependency and not dependency_valid)or(not dependency and (not hmac.compare_digest(queue_seal,self._queued_evidence(evidence))
                        or payload.get('recommendation')!=current
                        or (reviewed is not _UNREVIEWED and reviewed!=current)))):
                    db.execute("UPDATE agent_task_events SET status='cancelled',payload='{}',error='evidence_changed' WHERE id=?",(event['id'],))
                    return None
                secret=self._open(row['sealed'],row['id'])
                if not self._budget(secret['url'] if row['channel']=='browser' else secret['target']['url'],'delivery',10,86400):
                    db.execute('UPDATE agent_task_events SET next_attempt=? WHERE id=?',(time.time()+3600,event['id']))
                    return None
                claimed=db.execute("UPDATE agent_task_events SET status='sending',attempts=attempts+1,next_attempt=? WHERE id=? AND status='pending'",(time.time()+600,event['id'])).rowcount
                if not claimed:
                    return None
            observation=self.journal.begin('delivery','task_delivery',identity=stable_reference('task-delivery',event['id']))
            attempt=observation.attempt()
            try:
                with attempt_scope(attempt):
                    provider_dispatch()
                    if row['channel']=='browser':
                        ok,error=self.push.send(secret['subscription'],{'type':'task_update','event_id':event['id']})
                    else:
                        ok,error=self.courier.send_update(row['channel'],secret,json.loads(event['payload']),event['id'])
                    attempt.finish('accepted' if ok else 'failed',None if ok else 'UPSTREAM_NETWORK')
            except Exception:
                ok,error=False,'delivery_failed'
            attempts=event['attempts']+1
            with self.lock,self.store.tx() as db:
                current_rows=self.store.query('SELECT * FROM agent_task_watches WHERE id=?',(row['id'],))
                if not current_rows:
                    observation.finish('accepted' if ok else 'unknown',None if ok else 'UPSTREAM_NETWORK')
                    return 'sent' if ok else 'failed'
                fresh=dict(current_rows[0])
                retry=not dependency and not ok and error!='gone' and attempts<5 and event['created']>time.time()-86400 and fresh['state']=='active'
                db.execute('UPDATE agent_task_events SET status=?,next_attempt=?,error=? WHERE id=?',('sent' if ok else 'pending' if retry else 'failed',time.time()+min(3600,60*2**attempts)+secrets.randbelow(30),None if ok else 'delivery_failed',event['id']))
                if dependency and not ok and error!='gone':
                    db.execute("UPDATE agent_task_events SET status='unknown' WHERE id=?",(event['id'],))
                if not ok and error=='gone':
                    self.action(row['visitor_id'],row['id'],'stop')
                elif not ok and not retry and fresh['state']=='active':
                    db.execute("UPDATE agent_task_watches SET state='paused' WHERE id=?",(row['id'],))
            observation.finish('accepted' if ok else 'pending' if retry else 'failed',None if ok else 'UPSTREAM_NETWORK')
            return 'sent' if ok else 'failed'
        finally:
            _OUTBOUND_SLOTS.release()

    def dispatch_campaign(self,vid,campaign):
        return {'status':'permission_denied','error':'Review a specific task before processing.'}

    def determine_campaign(self,vid):
        return 'task_update'

    def run_nurture_pipeline(self,force_visitor=None):
        return {'checked':0,'sent':0,'failed':0,'status':'selection_required'}

    def admin_summary(self,row):
        data=self.public(row)
        data.update(verified_at=row['verified_at'],last_event=row['last_event'],last_checked=row['last_checked'],
                    authority=bool(row['authority']),destination='Not retained',purpose='task_updates')
        grants=self.store.query('SELECT requested_at,verified_at,withdrawn_at,expires FROM agent_marketing_permissions WHERE watch_id=?',(row['id'],))
        if grants:
            data.update({'marketing_'+key:grants[0][key] for key in ('requested_at','verified_at','withdrawn_at','expires')})
        destination_ready=row['channel']=='poll'
        if row['channel']=='poll':
            data['destination']='Authenticated polling'
        elif row['channel']=='browser' and row['sealed']:
            try:
                secret=self._open(row['sealed'],row['id'])
                validate_subscription(secret['subscription'])
                data['destination']='Verified browser subscription' if row['verified_at'] else 'Browser confirmation pending'
                destination_ready=True
            except (ValueError,KeyError,TypeError):
                data['destination']='Unavailable'
        elif row['sealed']:
            try:
                secret=self._open(row['sealed'],row['id'])
                # Show the host only; paths may contain private routing secrets.
                host=urlsplit(secret['url']).hostname
                data['destination']='https://'+('['+host+']' if ':' in host else host)+'/…'
                destination_ready=bool(secret.get('target',{}).get('url') and secret.get('secret'))
            except (ValueError,KeyError,TypeError):
                data['destination']='Unavailable'
        data['permission_current']=bool(row['state']=='active' and row['expires']>time.time() and row['authority'] and row['notice_version']==NOTICE_VERSION and destination_ready and (row['channel']=='poll' or row['verified_at'] and row['sealed']))
        data['marketing_eligible']=bool(data['marketing_eligible'] and data['permission_current'])
        return data

    @staticmethod
    def delivery_recommendation(item):
        return {key:item.get(key) for key in ('id','name','kind','url','usage_endpoint','grade','test_report','active_checked_at')} if item else None

    @staticmethod
    def payload_evidence(payload):
        item=payload.get('recommendation')
        return json.dumps([item['id'],item.get('grade'),(item.get('test_report') or {}).get('id')] if item else None)

    def preview(self,visitor_id,watch_id,actor):
        row=self._get(watch_id,visitor_id)
        evidence,item=self._evidence(row['task'],row['protocol']) if row['task'] else ('null',None)
        recommendation=self.delivery_recommendation(item)
        pending=self.store.query("SELECT * FROM agent_task_events WHERE watch_id=? AND status='pending' ORDER BY created DESC LIMIT 1",(watch_id,))
        queued=dict(pending[0]) if pending else None
        eligible=self.admin_summary(row)['permission_current']
        reason='ready'
        if not eligible:
            reason='permission_unavailable'
        elif row['channel']!='poll' and not self.outbound_enabled:
            reason='delivery_disabled'
        elif queued and (json.loads(queued['payload']).get('recommendation')!=recommendation
                or not hmac.compare_digest(str(queued.get('evidence') or '').partition(':')[2],self._queued_evidence(evidence))):
            reason='queued_evidence_changed'
        elif queued and queued['next_attempt']>time.time():
            reason='retry_scheduled'
        elif evidence==row['baseline'] and not queued:
            reason='no_change'
        elif not queued and row['last_event'] and row['last_event']>time.time()-CADENCE:
            reason='cadence_limit'
        # Bind processing to the exact reviewed state and evidence, not editable message text.
        fingerprint=hashlib.sha256(json.dumps([row['state'],row['expires'],row['notice_version'],row['baseline'],row['last_event'],row['task'],row['protocol'],row['channel'],row['authority'],row['verified_at'],hashlib.sha256((row['sealed'] or '').encode()).hexdigest(),
            evidence,recommendation,queued['payload'] if queued else None,queued['id'] if queued else None,queued['attempts'] if queued else None,queued['next_attempt'] if queued else None,reason],sort_keys=True).encode()).hexdigest()
        claims={'visitor':visitor_id,'watch':watch_id,'actor':actor,'fingerprint':fingerprint,'expires':time.time()+300}
        raw=base64.urlsafe_b64encode(json.dumps(claims,separators=(',',':')).encode()).decode()
        token=raw+'.'+hmac.new(self.key,('admin-preview:'+raw).encode(),hashlib.sha256).hexdigest()
        return {'watch':self.admin_summary(row),'recommendation':recommendation,'reason':reason,'can_process':reason=='ready',
                'delivery':'poll' if row['channel']=='poll' else 'inbox','preview_token':token,'fingerprint':fingerprint,
                'pending_event_id':queued['id'] if queued else None,'expires_at':claims['expires']}

    def process_preview(self,visitor_id,watch_id,actor,token):
        try:
            if not isinstance(token,str) or len(token)>3000:
                raise ValueError()
            raw,signature=token.rsplit('.',1)
            expected=hmac.new(self.key,('admin-preview:'+raw).encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected,signature):
                raise ValueError()
            claims=json.loads(base64.urlsafe_b64decode(raw))
            if claims['visitor']!=visitor_id or claims['watch']!=watch_id or claims['actor']!=actor or claims['expires']<time.time():
                raise ValueError()
        except (ValueError,KeyError,TypeError):
            raise UpdateError('Review this task again before processing.')
        current=self.preview(visitor_id,watch_id,actor)
        if not current['can_process'] or claims['fingerprint']!=current['fingerprint']:
            raise UpdateError('The permission or evidence changed. Review this task again.')
        self.refresh(visitor_id,watch_id,reviewed=current['recommendation'])
        row=self._get(watch_id,visitor_id)
        if not self.admin_summary(row)['permission_current']:
            raise UpdateError('The permission changed. Review this task again.')
        if row['channel']=='poll':
            events=self.store.query("SELECT payload FROM agent_task_events WHERE watch_id=? AND status='ready' ORDER BY created DESC LIMIT 1",(watch_id,))
            if not events or json.loads(events[0]['payload']).get('recommendation')!=current['recommendation']:
                raise UpdateError('The evidence changed. Review this task again.')
            return {'status':'ready','watch_id':watch_id,'sent':0}
        events=self.store.query("SELECT * FROM agent_task_events WHERE watch_id=? AND status='pending' AND next_attempt<=? ORDER BY created DESC LIMIT 1",(watch_id,time.time()))
        if not events:
            raise UpdateError('No eligible task update is ready.')
        event=dict(events[0])
        result=self._attempt(event,reviewed=current['recommendation'])
        return {'status':result or 'deferred','watch_id':watch_id,'event_id':event['id'],'sent':int(result=='sent')}

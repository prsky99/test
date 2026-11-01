"""Explicit private A2A 0.3 JSON-RPC task polling; no automatic resubmission.

The synchronous public gateway is unchanged. Trusted bindings select a recorded
agent version and transport. Source: https://a2a-protocol.org/v0.3.0/specification/
"""
from dataclasses import dataclass
import json
import re
import secrets
import time
import threading
from urllib.parse import urlsplit

from .capability_registry import digest, version_parts
from .concierge.http_security import bounded_client
from .execution_authority import require_enabled
from .private_artifact_keys import ArtifactCipher
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _rows

PROFILE = 'private-a2a03-task-poll-v1'
SESSION_PROFILE = 'private-a2a03-session-stream-v1'
NOTICE = 'private-a2a-task-input-sharing-v1'
STATES = frozenset(('submitted', 'working', 'input-required', 'auth-required', 'completed', 'canceled', 'failed', 'rejected'))
TERMINAL = frozenset(('completed', 'canceled', 'failed', 'rejected', 'unknown'))
_control_slots = threading.BoundedSemaphore(2)
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_remote_tasks (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,logical_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,status TEXT NOT NULL,expires REAL NOT NULL,
       UNIQUE(workspace_id,logical_id))''',
    'CREATE INDEX IF NOT EXISTS workspace_remote_tasks_active ON workspace_remote_tasks(status,expires)',
    'CREATE TABLE IF NOT EXISTS workspace_remote_task_restore_blocks(id TEXT PRIMARY KEY)',
)


class TaskProtocolError(ValueError):
    pass


class TaskClient:
    """Fixed HTTPS endpoint and bounded response; no arbitrary file fetching."""
    def __init__(self, endpoint, *, http=None, streaming=False):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            raise WorkspaceInvalid()
        if type(streaming) is not bool:
            raise WorkspaceInvalid()
        self.endpoint, self.http, self.streaming = endpoint, http, streaming

    def call(self, method, params, *, before_dispatch=None, on_event=None, cursor=None):
        if method in ('message/stream', 'tasks/resubscribe'):
            if not self.streaming or on_event is None:
                raise WorkspaceInvalid()
            return self._stream(method, params, before_dispatch, on_event, cursor)
        if method not in ('message/send', 'tasks/get', 'tasks/cancel'):
            raise WorkspaceInvalid()
        identity = secrets.token_hex(16)
        owned = self.http is None
        client = self.http or bounded_client(allow_private=False, limit=65536, timeout=10)
        try:
            if before_dispatch is not None:
                before_dispatch()
            with client.stream('POST', self.endpoint, json={'jsonrpc':'2.0', 'id':identity,
                    'method':method, 'params':params}, headers={'Accept':'application/json',
                    'Accept-Encoding':'identity'}, follow_redirects=False) as response:
                if not 200 <= response.status_code < 300 or response.headers.get('content-encoding','identity') != 'identity':
                    raise TaskProtocolError()
                raw = bytearray()
                for part in response.iter_bytes(chunk_size=4096):
                    raw.extend(part)
                    if len(raw) > 65536:
                        raise TaskProtocolError()
            def pairs(items):
                value = {}
                for key, item in items:
                    if key in value:
                        raise TaskProtocolError()
                    value[key] = item
                return value
            value = json.loads(raw, object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(TaskProtocolError()))
            if (type(value) is not dict or value.get('jsonrpc') != '2.0'
                    or value.get('id') != identity or ('result' in value) == ('error' in value)):
                raise TaskProtocolError()
            if 'error' in value:
                raise TaskProtocolError()
            return value['result']
        finally:
            if owned:
                client.close()

    def _stream(self, method, params, before_dispatch, on_event, cursor):
        """One bounded SSE connection. Reconnection is an explicit read action.

        A2A 0.3 defines resubscribe, not an exactly-once event cursor extension.
        SSE ids, when supplied, are retained and sent as Last-Event-ID; providers
        without ids may only return full snapshots, never ambiguous append data.
        """
        identity, started = secrets.token_hex(16), time.monotonic()
        owned = self.http is None
        client = self.http or bounded_client(allow_private=False, limit=262144, timeout=45)
        headers = {'Accept': 'text/event-stream', 'Accept-Encoding': 'identity'}
        if cursor:
            if type(cursor) is not str or len(cursor) > 200 or any(ord(c) < 32 for c in cursor):
                raise TaskProtocolError()
            headers['Last-Event-ID'] = cursor
        try:
            if before_dispatch is not None:
                before_dispatch()
            with client.stream('POST', self.endpoint, json={'jsonrpc': '2.0', 'id': identity,
                    'method': method, 'params': params}, headers=headers, follow_redirects=False) as response:
                if (response.status_code != 200 or response.headers.get('content-type', '').split(';')[0].strip() != 'text/event-stream'
                        or response.headers.get('content-encoding', 'identity') != 'identity'):
                    raise TaskProtocolError()
                data, event_id, total, count, last = [], None, 0, 0, None
                for line in response.iter_lines():
                    total += len(line.encode('utf-8')) + 1
                    if total > 262144 or time.monotonic() - started > 45 or len(line) > 65536:
                        raise TaskProtocolError()
                    if line == '':
                        if data:
                            from .workspace_ai_support import strict_json
                            event = strict_json('\n'.join(data))
                            if (type(event) is not dict or event.get('jsonrpc') != '2.0' or event.get('id') != identity
                                    or 'error' in event or 'result' not in event):
                                raise TaskProtocolError()
                            count += 1
                            if count > 128:
                                raise TaskProtocolError()
                            last = on_event(event['result'], event_id)
                            if last.get('status', {}).get('state') in TERMINAL - {'unknown'} or event['result'].get('final') is True:
                                return last
                        data, event_id = [], None
                    elif line.startswith('data:'):
                        data.append(line[5:].lstrip(' '))
                    elif line.startswith('id:'):
                        event_id = line[3:].lstrip(' ')
                        if not event_id or len(event_id) > 200 or any(ord(c) < 32 for c in event_id):
                            raise TaskProtocolError()
                    elif line.startswith(':') or line.startswith(('event:', 'retry:')):
                        continue
                    else:
                        raise TaskProtocolError()
                # A clean end without a final event is an interruption, not success.
                raise TaskProtocolError()
        finally:
            if owned:
                client.close()


@dataclass(frozen=True, repr=False)
class TaskBinding:
    resource_id: int
    version_id: str
    client: TaskClient

    def __post_init__(self):
        if (type(self.resource_id) is not int or self.resource_id < 1
                or not isinstance(self.version_id, str) or not re.fullmatch('cv_[0-9a-f]{32}', self.version_id)
                or type(self.client) is not TaskClient):
            raise WorkspaceInvalid()


class RemoteTasks(SignedWorkspaceModule):
    def __init__(self, access, *, bindings=(), cipher=None):
        if type(bindings) is not tuple or len(bindings) > 20 or any(type(b) is not TaskBinding for b in bindings):
            raise WorkspaceInvalid()
        if len({b.resource_id for b in bindings}) != len(bindings):
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.bindings = {b.resource_id:b for b in bindings}
        self.cipher = cipher or ArtifactCipher(PROFILE)

    def options(self,ws,actor):
        with self.access._tx(actor) as (db,_):
            self.scope(ws,actor)
        return {'profile':PROFILE,'notice':NOTICE,'bindings':[
            {'resource_id':b.resource_id,'version_id':b.version_id,'streaming':b.client.streaming}
            for b in self.bindings.values()], 'encryption_configured':self.cipher.configured,
            'automatic_retry':False,'streaming':any(b.client.streaming for b in self.bindings.values()),
            'task_seconds':900,'stream_connection_seconds':45,'relation_to_typed_flows':'separate_async_task_history'}

    def _owner(self, ws, actor):
        member, user = self.scope(ws, actor, write=True)
        return {'actor':actor.user_id, 'session':actor.session_ref,
                'member':member['member_revision'], 'workspace':member['revision'], 'role':user['role']}

    def _pin(self, rid, version):
        if type(rid) is not int or type(version) is not str:
            raise WorkspaceInvalid()
        binding = self.bindings.get(rid)
        resource = self.store.resource(rid)
        if not binding or binding.version_id != version or not resource or resource['kind'] != 'a2a':
            raise WorkspaceDenied()
        parts = version_parts(resource)
        current = 'cv_'+digest([rid, *parts[:3]])[:32]
        if (current != version or resource['url'] != binding.client.endpoint or resource.get('active') != 1
                or resource.get('health_status') not in ('healthy', 'reachable')
                or resource.get('eval_security') == 'quarantine' or resource.get('auth_observed')):
            raise WorkspaceDenied()
        from .concierge.execution_policy import admit, ExecutionDenied
        try:
            admit(resource, 'a2a', public=True, authorize_charge=False)
        except ExecutionDenied:
            raise WorkspaceDenied() from None
        require_enabled(self.store, 'invoke')
        return binding

    def _load(self, db, ws, identity):
        rows = _rows(db, 'SELECT * FROM workspace_remote_tasks WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if value['id'] != identity or value['workspace_id'] != ws or value['logical_id'] != rows[0]['logical_id']:
            raise WorkspaceConflict()
        if value['state'] != rows[0]['status'] or value['expires'] != rows[0]['expires']:
            raise WorkspaceConflict()
        if db.execute('SELECT 1 FROM workspace_remote_task_restore_blocks WHERE id=?', (identity,)).fetchone():
            raise WorkspaceDenied()
        return value

    def _save(self, db, value):
        db.execute('''INSERT INTO workspace_remote_tasks VALUES(?,?,?,?,?,?,?) ON CONFLICT(id)
            DO UPDATE SET payload=excluded.payload,signature=excluded.signature,
            status=excluded.status,expires=excluded.expires''',
            (value['id'], value['workspace_id'], value['logical_id'], _canonical(value), self.sign(value),
             value['state'], value['expires']))

    def _private(self, value):
        sealed = value['sealed']
        if type(sealed) is list:
            if not 1 <= len(sealed) <= 24 or any(type(x) is not str or len(x)>12000 for x in sealed):
                raise WorkspaceConflict()
            sealed = ''.join(sealed)
        return json.loads(self.cipher.open(sealed.encode('ascii'),
            {'profile':PROFILE,'id':value['id'],'workspace_id':value['workspace_id']}))

    def _seal(self, value, private):
        raw = _canonical(private).encode('ascii')
        if len(raw)>40000:
            raise WorkspaceInvalid()
        sealed = self.cipher.seal(raw,
            {'profile':PROFILE,'id':value['id'],'workspace_id':value['workspace_id']}).decode('ascii')
        # Keep each authenticated envelope fragment inside the shared bounded
        # JSON tree contract, including non-ASCII text encoded as JSON escapes.
        value['sealed'] = [sealed[i:i+12000] for i in range(0,len(sealed),12000)]

    @staticmethod
    def dto(value):
        return {k:value[k] for k in ('id','resource_id','version_id','state','revision','created','expires')} | {
            'profile':value.get('task_profile', PROFILE), 'automatic_retry':False,
            'streaming':value.get('task_profile') == SESSION_PROFILE,
            'session_turn':value.get('turn', 1), 'retained_events':value.get('event_count', 0),
            'resume_available':(value.get('resumable', False) or value.get('remote_task_retained',False)
                and value['state']=='dispatched' and value.get('operation_expires',value['expires'])<=clock()) and value['expires'] > clock(),
            'cancel_available':value.get('task_profile')==SESSION_PROFILE and value.get('remote_task_retained',False)
                and value['state'] not in ('completed','canceled','failed','rejected') and value['expires']>clock(),
            'remote_output_retained':value.get('has_output',False),
            'output_truncated':value.get('output_truncated',False),
            'execution_outcome':'unknown' if value['state'] in ('dispatched','unknown') else value['state']}

    def status(self, ws, identity, actor):
        with self.access._tx(actor) as (db,_):
            self.scope(ws,actor)
            value = self._load(db,ws,identity)
            return self.dto(value) | {'output_preview':self._private(value).get('output') or ''}

    def listing(self, ws, actor):
        with self.access._tx(actor) as (db,_):
            self.scope(ws,actor)
            rows = _rows(db, 'SELECT id FROM workspace_remote_tasks WHERE workspace_id=? LIMIT 100', (ws,))
            tasks = [self.dto(self._load(db,ws,row['id'])) for row in rows]
            return sorted(tasks,key=lambda value:value['created'],reverse=True)

    @staticmethod
    def _admit(db, excluding=None):
        # Durable cross-process admission is separate from the in-process shared
        # pool. Interrupted dispatched rows retain their slot until expiry.
        if db.execute("SELECT COUNT(*) FROM workspace_remote_tasks WHERE status='dispatched' AND expires>? AND id<>?",
                (clock(),excluding or '')).fetchone()[0] >= 4:
            raise WorkspaceConflict()

    def send(self, ws, body, actor):
        from .workspace_execution import _slots
        if not _slots.acquire(blocking=False):
            raise WorkspaceConflict()
        try:
            return self._send(ws,body,actor)
        finally:
            _slots.release()

    def _send(self, ws, body, actor):
        exact(body, ('logical_id','resource_id','version_id','text','authorized','notice'))
        if (body['authorized'] is not True or body['notice'] != NOTICE
                or type(body['logical_id']) is not str or not re.fullmatch('rat_[0-9a-f]{32}',body['logical_id'])
                or type(body['text']) is not str or not 1 <= len(body['text'].encode('utf-8')) <= 4000
                or not self.cipher.configured):
            raise WorkspaceInvalid()
        binding = self._pin(body['resource_id'], body['version_id'])
        with self.access._tx(actor,write=True) as (db,_):
            owner = self._owner(ws,actor)
            rows = _rows(db,'SELECT * FROM workspace_remote_tasks WHERE workspace_id=? AND logical_id=?',(ws,body['logical_id']))
            fingerprint = _hash(body)
            if rows:
                value = self._load(db,ws,rows[0]['id'])
                if value['input_hash'] != fingerprint or value['owner'] != owner:
                    raise WorkspaceConflict()
                return self.dto(value) | {'replayed':True}
            if db.execute('SELECT COUNT(*) FROM workspace_remote_tasks WHERE workspace_id=?',(ws,)).fetchone()[0] >= 100:
                raise WorkspaceConflict()
            self._admit(db)
            value = {'id':'rtk_'+secrets.token_hex(16),'workspace_id':ws,'logical_id':body['logical_id'],
                'resource_id':body['resource_id'],'version_id':body['version_id'],'owner':owner,'input_hash':fingerprint,
                'revision':1,'state':'dispatched','created':clock(),'expires':clock()+900,'has_output':False}
            if binding.client.streaming:
                value.update(task_profile=SESSION_PROFILE, turn=1, event_count=0, operation_expires=clock()+45)
            private = {'text':body['text'],'messageId':secrets.token_hex(16),'remote_id':None,'output':None,
                       'context_id':None, 'cursor':None, 'event_hashes':[], 'artifacts':{}}
            self._seal(value, private)
            self._pin(value['resource_id'],value['version_id'])
            self._save(db,value)
        return self._perform(ws,value,binding,'message/stream' if binding.client.streaming else 'message/send',{'message':{'kind':'message','role':'user',
            'messageId':private['messageId'],'parts':[{'kind':'text','text':body['text']}]},
            'configuration':{'blocking':False}},actor)

    def command(self, ws, identity, body, actor, *, _guard=None):
        from .workspace_execution import _slots
        # A bounded control lane remains available while all business streams
        # occupy the execution pool. It cannot create or resend a message.
        slots = _control_slots if type(body) is dict and body.get('action')=='cancel' else _slots
        if not slots.acquire(blocking=False):
            raise WorkspaceConflict()
        try:
            return self._command(ws,identity,body,actor,_guard=_guard)
        finally:
            slots.release()

    def _command(self, ws, identity, body, actor, *, _guard=None):
        exact(body,('revision','action','authorized','notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE or body['action'] not in ('poll','cancel','resume'):
            raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):
            value = self._load(db,ws,identity)
            recovering = (body['action'] == 'resume' and value.get('task_profile') == SESSION_PROFILE
                and (value.get('resumable') or value['state'] == 'dispatched'
                     and value.get('operation_expires', value['expires']) <= clock()))
            canceling = (body['action']=='cancel' and value.get('task_profile')==SESSION_PROFILE
                         and value.get('remote_task_retained',False))
            if (type(body['revision']) is not int or body['revision'] != value['revision']
                    or value['state'] in TERMINAL and not (recovering or canceling and value['state']=='unknown')
                    or value['state'] == 'dispatched' and not (recovering or canceling)
                    or value['expires'] <= clock() or self._owner(ws,actor) != value['owner']):
                raise WorkspaceConflict()
            private = self._private(value)
            if not private['remote_id']:
                raise WorkspaceConflict()
            binding = self._pin(value['resource_id'],value['version_id'])
            if body['action'] == 'resume' and not recovering:
                raise WorkspaceConflict()
            self._admit(db,identity)
            value.update(state='dispatched',revision=value['revision']+1)
            if value.get('task_profile') == SESSION_PROFILE:
                value['operation_expires'] = min(value['expires'], clock()+45)
            self._save(db,value)
        method = {'poll':'tasks/get','cancel':'tasks/cancel','resume':'tasks/resubscribe'}[body['action']]
        params = {'id':private['remote_id']}
        if body['action']=='poll':params['historyLength']=0
        return self._perform(ws,value,binding,method,params,actor,_guard=_guard)

    def continue_session(self, ws, identity, body, actor):
        """A new, reviewed message for the same input-required task/context.

        This is not a retry of a prior submission. A durable logical turn key
        returns the retained outcome even if the caller lost the response.
        """
        from .workspace_execution import _slots
        exact(body, ('revision','logical_id','text','authorized','notice'))
        if (body['authorized'] is not True or body['notice'] != NOTICE or type(body['revision']) is not int
                or type(body['logical_id']) is not str or not re.fullmatch('rat_[0-9a-f]{32}',body['logical_id'])
                or type(body['text']) is not str or not 1 <= len(body['text'].encode('utf-8')) <= 4000):
            raise WorkspaceInvalid()
        if not _slots.acquire(blocking=False):
            raise WorkspaceConflict()
        try:
            with self.access._tx(actor,write=True) as (db,_):
                value = self._load(db,ws,identity)
                if (value.get('task_profile') != SESSION_PROFILE or value['owner'] != self._owner(ws,actor)
                        or value['expires'] <= clock()):
                    raise WorkspaceDenied()
                private = self._private(value)
                turns = private.setdefault('turns', {})
                fingerprint = _hash(body)
                if body['logical_id'] in turns:
                    if turns[body['logical_id']] != fingerprint:
                        raise WorkspaceConflict()
                    return self.dto(value) | {'replayed': True}
                if (body['revision'] != value['revision'] or value['state'] != 'input-required'
                        or not private.get('remote_id') or not private.get('context_id') or value['turn'] >= 16):
                    raise WorkspaceConflict()
                binding = self._pin(value['resource_id'],value['version_id'])
                self._admit(db)
                turns[body['logical_id']] = fingerprint
                private['messageId'] = secrets.token_hex(16)
                private['text'] = body['text']
                private['cursor'], private['event_hashes'] = None, []
                value.update(state='dispatched',revision=value['revision']+1,turn=value['turn']+1,
                             operation_expires=min(value['expires'], clock()+45),resumable=False)
                self._seal(value,private)
                self._save(db,value)
            return self._perform(ws,value,binding,'message/stream',{'message':{'kind':'message','role':'user',
                'messageId':private['messageId'],'taskId':private['remote_id'],'contextId':private['context_id'],
                'parts':[{'kind':'text','text':body['text']}]},'configuration':{'blocking':False}},actor)
        finally:
            _slots.release()

    def _event(self, ws, value, event, cursor, actor):
        """Fence and persist each accepted event before consuming another one."""
        if type(event) is not dict:
            raise TaskProtocolError()
        kind = event.get('kind')
        if kind not in ('task','status-update','artifact-update'):
            raise TaskProtocolError()
        remote = event.get('id' if kind == 'task' else 'taskId')
        context = event.get('contextId')
        if (type(remote) is not str or not 1 <= len(remote) <= 200
                or type(context) is not str or not 1 <= len(context) <= 200):
            raise TaskProtocolError()
        with self.access._tx(actor,write=True) as (db,_):
            current = self._load(db,ws,value['id'])
            if (current['revision'] != value['revision'] or current['state'] != 'dispatched'
                    or self._owner(ws,actor) != value['owner'] or current['expires'] <= clock()
                    or current['operation_expires'] <= clock()):
                raise WorkspaceDenied()
            self._pin(value['resource_id'],value['version_id'])
            private = self._private(current)
            if private.get('remote_id') not in (None,remote) or private.get('context_id') not in (None,context):
                raise TaskProtocolError()
            private.update(remote_id=remote,context_id=context)
            seen = private.setdefault('event_hashes', [])
            fingerprint = _hash(event)
            previous = [entry for entry in seen if cursor is not None and entry[0] == cursor]
            if previous:
                if previous[0][1] != fingerprint:
                    raise TaskProtocolError()
                return private['task_snapshot']
            if len(seen) >= 128:
                raise TaskProtocolError()
            artifacts = private.setdefault('artifacts', {})
            snapshot = private.get('task_snapshot', {'kind':'task','id':remote,'contextId':context,
                                                     'status':{'state':'working'}})
            if kind in ('task','status-update'):
                status = event.get('status')
                if type(status) is not dict or status.get('state') not in STATES:
                    raise TaskProtocolError()
                snapshot['status'] = {'state':status['state']}
            incoming = event.get('artifacts',[]) if kind == 'task' else [event['artifact']] if kind == 'artifact-update' else []
            if type(incoming) is not list or len(incoming) > 20:
                raise TaskProtocolError()
            for artifact in incoming:
                if type(artifact) is not dict or type(artifact.get('artifactId')) is not str or not 1 <= len(artifact['artifactId']) <= 200:
                    raise TaskProtocolError()
                parts = artifact.get('parts')
                if type(parts) is not list or len(parts) > 20:
                    raise TaskProtocolError()
                text = '\n'.join(p['text'] for p in parts if type(p) is dict and p.get('kind') == 'text' and type(p.get('text')) is str)
                key = artifact['artifactId']
                if event.get('append') is True:
                    if not cursor or key not in artifacts:
                        raise TaskProtocolError()
                    text = artifacts[key] + text
                artifacts[key] = text
                if len(artifacts) > 20 or sum(len(v.encode('utf-8')) for v in artifacts.values()) > 12000:
                    raise TaskProtocolError()
            snapshot['artifacts'] = [{'artifactId':key,'parts':[{'kind':'text','text':text}]} for key,text in artifacts.items()]
            private['task_snapshot'] = snapshot
            seen.append([cursor,fingerprint])
            if cursor is not None:
                private['cursor'] = cursor
            value['event_count'] = value.get('event_count',0)+1
            value['remote_task_retained'] = True
            self._seal(value,private)
            self._save(db,value)
            return snapshot

    def _perform(self, ws, value, binding, method, params, actor, *, _guard=None):
        state, output, remote = 'unknown', None, None
        try:
            # A post-commit authority change cancels transmission rather than
            # adopting the old decision. Dispatched remains a no-replay barrier.
            def guard():
                if _guard is not None:
                    _guard()
                with self.access._tx(actor,write=True) as (db,_):
                    current = self._load(db,ws,value['id'])
                    if (self._owner(ws,actor) != value['owner'] or current['revision'] != value['revision']
                            or current['state'] != 'dispatched' or current['expires'] <= clock()):
                        raise WorkspaceDenied()
                    self._pin(value['resource_id'],value['version_id'])
            if method in ('message/stream', 'tasks/resubscribe'):
                result = binding.client.call(method,params,before_dispatch=guard,
                    on_event=lambda event,cursor:self._event(ws,value,event,cursor,actor),
                    cursor=self._private(value).get('cursor'))
            else:
                result = binding.client.call(method,params,before_dispatch=guard)
            if _guard is not None:
                _guard()
            if (type(result) is not dict or result.get('kind') != 'task'
                    or type(result.get('id')) is not str or not 1 <= len(result['id']) <= 200
                    or type(result.get('status')) is not dict or result['status'].get('state') not in STATES):
                raise TaskProtocolError()
            remote, state = result['id'], result['status']['state']
            private = self._private(value)
            if private['remote_id'] is not None and remote != private['remote_id']:
                raise TaskProtocolError()
            context = result.get('contextId')
            if context is not None:
                if (type(context) is not str or not 1 <= len(context) <= 200
                        or private.get('context_id') not in (None, context)):
                    raise TaskProtocolError()
                private['context_id'] = context
                self._seal(value,private)
            # Keep only bounded text; ignore provider file URLs and private wire.
            artifacts = result.get('artifacts',[])
            if type(artifacts) is not list or len(artifacts)>20:
                raise TaskProtocolError()
            output = '\n'.join(p['text'] for a in artifacts if type(a) is dict
                for p in a.get('parts',[]) if type(p) is dict and p.get('kind')=='text' and type(p.get('text')) is str)
            if len(output)>16000:
                raise TaskProtocolError()
        except Exception:
            state, output, remote = 'unknown', None, None
        with self.access._tx(actor,write=True) as (db,_):
            current = self._load(db,ws,value['id'])
            if current['revision'] != value['revision'] or self._owner(ws,actor) != value['owner']:
                raise WorkspaceConflict()
            if current['expires'] <= clock():
                state, output = 'unknown', None
            if value.get('operation_expires', clock()+1) <= clock():
                state, output = 'unknown', None
            private = self._private(value)
            if remote is not None:private['remote_id']=remote
            private['output'] = output.encode('utf-8')[:2000].decode('utf-8','ignore') if output else None
            private['output_hash'] = _hash(output) if output is not None else None
            value.update(state=state,revision=value['revision']+1,has_output=bool(output),
                output_truncated=bool(output and private['output'] != output))
            if value.get('task_profile') == SESSION_PROFILE:
                value['resumable'] = state == 'unknown' and bool(private['remote_id']) and value['expires'] > clock()
            self._seal(value,private)
            self._save(db,value)
            return self.dto(value)

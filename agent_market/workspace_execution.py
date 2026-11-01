"""One explicitly authorized private MCP call under a current named session.

Private run rows never enter the legacy workflow queue. Tickets contain private
authority and remain server-side; public DTOs contain neither signatures nor
session references. Interrupted dispatched calls are never automatically retried.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager, nullcontext
import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import threading
import time

from .workspace_access import (
    SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid,
    _canonical, _hash, _identity, _revision, _rows, _tree,
)

PROFILE = 'workspace-private-mcp-run-v1'
NOTICE = 'workspace-private-run-v1'
LIMITS = {'seconds': 12, 'ticket_seconds': 300, 'max_calls': 1, 'history': 30,
          'pending_tickets': 20, 'tickets_per_workspace': 1000, 'runs_per_day': 100,
          'active_runs': 4, 'output_bytes': 65536}
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_private_tickets (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,draft_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,
       actor_user_id INTEGER NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,run_id TEXT UNIQUE,revoked REAL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_private_runs (
       id TEXT PRIMARY KEY,ticket_id TEXT NOT NULL UNIQUE,workspace_id TEXT NOT NULL,draft_id TEXT NOT NULL,
       snapshot_id TEXT NOT NULL,actor_user_id INTEGER NOT NULL,status TEXT NOT NULL,
       created REAL NOT NULL,deadline REAL NOT NULL,dispatched REAL,finished REAL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS workspace_private_runs_scope ON workspace_private_runs(workspace_id,draft_id,snapshot_id,created)',
    'CREATE INDEX IF NOT EXISTS workspace_private_tickets_actor ON workspace_private_tickets(actor_user_id,expires)',
)
STATES = ('prepared', 'dispatched', 'succeeded', 'failed', 'unknown', 'denied')
ERRORS = ('POLICY_DENIED', 'UPSTREAM_TIMEOUT', 'UPSTREAM_NETWORK', 'UPSTREAM_PROTOCOL',
          'UPSTREAM_TOOL_ERROR', 'EXECUTION_FAILED', 'OUTPUT_REJECTED', 'INTERRUPTED')
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='workspace-private')
_slots = threading.BoundedSemaphore(4)


class OutputContractRejected(WorkspaceInvalid):
    """A completed response failed its purpose-specific output contract."""


def _now():
    value = time.time()
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise WorkspaceConflict()
    return value


class WorkspaceExecution:
    def __init__(self, access, proxy, *, authority_guard=None, meter=None):
        self.access, self.store, self.proxy = access, access.store, proxy
        if authority_guard is not None and not callable(authority_guard):
            raise WorkspaceInvalid()
        self.authority_guard = authority_guard
        self.purpose_guards = ()
        self.output_guards = ()
        self.meter = meter
        self.key = hmac.new(access.key, PROFILE.encode('ascii'), hashlib.sha256).digest()
        from .private_artifact_keys import ArtifactCipher, ArtifactSigner
        self._artifact_signer = ArtifactSigner(self.key, PROFILE)
        self._output_cipher = ArtifactCipher('workspace-private-output-v1')
        with self._internal() as db:
            for statement in SCHEMA:
                db.execute(statement)

    @contextmanager
    def _internal(self):
        """Short native transactions; never wrap provider I/O in this context."""
        with self.store._lock:
            db = self.store._db
            if db.in_transaction:
                raise WorkspaceConflict()
            try:
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except BaseException as error:
                try:
                    db.rollback()
                except sqlite3.Error:
                    pass
                if isinstance(error, sqlite3.Error):
                    raise WorkspaceConflict() from None
                raise

    def _signature(self, value):
        return self._artifact_signer.sign(value)

    def _scope(self, ws, draft_id, snapshot_id, actor, *, write=False):
        membership, user = self.access._access(ws, actor, write=write)
        self.access._open_draft(self.access._draft_row(ws, draft_id))
        row = self.access._version_row(ws, draft_id, snapshot_id)
        snapshot = self.access._open_version(row)
        if not row['active']:
            raise WorkspaceDenied()
        return membership, user, row, snapshot

    def _control(self, db):
        try:
            rows = _rows(db, 'SELECT * FROM execution_controls WHERE id=1')
            if len(rows) != 1:
                raise WorkspaceDenied()
            row = rows[0]
            if (row['invoke_enabled'] != 1 or row['workflow_enabled'] != 1
                    or not _revision(row['revision'], zero=True)
                    or type(row['updated']) not in (int, float)
                    or not math.isfinite(row['updated']) or row['updated'] < 0):
                raise WorkspaceDenied()
            return {'revision': row['revision'], 'updated': row['updated']}
        except sqlite3.Error:
            raise WorkspaceDenied() from None

    def _node(self, snapshot):
        definition = snapshot['snapshot']['definition']
        nodes, edges = definition['nodes'], definition['edges']
        if len(nodes) != 2 or len(edges) != 1:
            raise WorkspaceInvalid()
        triggers = [node for node in nodes if node['type'] == 'trigger']
        agents = [node for node in nodes if node['type'] == 'agent']
        if (len(triggers) != 1 or len(agents) != 1 or agents[0]['kind'] != 'mcp'
                or edges != [{'source': triggers[0]['id'], 'target': agents[0]['id']}]
                or set(agents[0]['data']) != {'tool', 'input'}):
            raise WorkspaceInvalid()
        return agents[0]

    def _resource(self, db, node):
        """Pure current-row checks: no registry refresh or nested Store writes."""
        from .capability_registry import version_parts
        from .concierge.execution_policy import admit, admit_tool
        rows = _rows(db, 'SELECT * FROM resources WHERE id=?', (node['resource_id'],))
        if len(rows) != 1:
            raise WorkspaceDenied()
        resource = rows[0]
        try:
            admit(resource, 'mcp', public=True)
            spec = admit_tool(resource, node['data']['tool'], node['data']['input'])
            annotations = spec.get('annotations') or {}
            if (annotations.get('readOnlyHint') is not True
                    or annotations.get('destructiveHint') is not False
                    or annotations.get('idempotentHint') is not True
                    or not resource.get('usage_tools_hash')
                    or any(resource.get(key) not in (None, 0, False, '', '{}')
                           for key in ('auth_required', 'auth_observed', 'auth_declared', 'auth_info'))):
                raise WorkspaceDenied()
            generation = _rows(db, 'SELECT generation FROM resource_observation_generations WHERE resource_id=?',
                               (resource['id'],))
            if len(generation) != 1 or not _revision(generation[0]['generation']):
                raise WorkspaceDenied()
            pin = _hash({'version_parts': version_parts(resource), 'tool': spec,
                         'tools_hash': resource['usage_tools_hash'], 'full_hash': resource.get('usage_full_hash'),
                         'health_status': resource.get('health_status'), 'eval_security': resource.get('eval_security'),
                         'price_usdc': resource.get('price_usdc'), 'generation': generation[0]['generation']})
            return resource, pin
        except (ValueError, TypeError, KeyError, sqlite3.Error):
            raise WorkspaceDenied() from None

    def _binding(self, db, ws, draft_id, snapshot_id, actor):
        membership, user, row, snapshot = self._scope(ws, draft_id, snapshot_id, actor, write=True)
        node = self._node(snapshot)
        resource, pin = self._resource(db, node)
        control = self._control(db)
        bound = {'workspace_id': ws, 'draft_id': draft_id, 'snapshot_id': snapshot_id,
                 'actor_user_id': actor.user_id, 'session_ref': actor.session_ref,
                 'workspace_revision': membership['revision'], 'member_revision': membership['member_revision'],
                 'member_role': membership['member_role'], 'user_role': user['role'],
                 'snapshot_revision': row['revision'], 'snapshot_hash': row['payload_hash'],
                 'definition_hash': snapshot['definition_hash'], 'resource_id': resource['id'],
                 'binding_hash': pin, 'controls': control}
        if getattr(actor, 'principal_kind', 'admin') == 'customer':
            bound.update(actor_kind='customer', token_ref=actor.token_ref)
        return bound, node, resource

    def _actor_from_claims(self, claims):
        factory = getattr(self.access, 'actor_from_claims', None)
        if factory is not None:
            return factory(claims)
        if claims.get('actor_kind', 'admin') != 'admin':
            raise WorkspaceDenied()
        return SessionActor(claims['actor_user_id'], claims['session_ref'])

    def _purpose(self, db, ticket, claims):
        if self.authority_guard is not None and self.authority_guard(db, ticket, claims) is not True:
            raise WorkspaceDenied()
        for guard in self.purpose_guards:
            if guard(db, ticket, claims) is not True:
                raise WorkspaceDenied()

    def _active_runs(self, db, now):
        count = db.execute("SELECT COUNT(*) FROM workspace_private_runs WHERE status IN ('prepared','dispatched') AND deadline>?", (now,)).fetchone()[0]
        related = getattr(self, 'related_active_count', None)
        if related is not None:
            extra = related(db, now)
            if type(extra) is not int or extra < 0:
                raise WorkspaceConflict()
            count += extra
        return count

    def options(self, ws, draft_id, snapshot_id, actor):
        with self.access._tx(actor) as (db, user):
            membership, _, _, snapshot = self._scope(ws, draft_id, snapshot_id, actor)
            try:
                node = self._node(snapshot)
                self._resource(db, node)
                self._control(db)
                supported, reason = True, None
            except WorkspaceInvalid:
                supported, reason = False, 'unsupported_snapshot'
            except WorkspaceDenied:
                supported, reason = False, 'agent_unavailable'
            return {'supported': supported,
                    'can_run': supported and user['role'] != 'operator' and membership['member_role'] in ('owner', 'editor'),
                    'limits': dict(LIMITS), 'notice': NOTICE, 'unsupported_reason': reason}

    def prepare(self, ws, draft_id, snapshot_id, body, actor):
        if type(body) is not dict or set(body) != {'snapshot_revision'} or not _revision(body['snapshot_revision']):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            bound, node, _ = self._binding(db, ws, draft_id, snapshot_id, actor)
            if body['snapshot_revision'] != bound['snapshot_revision']:
                raise WorkspaceConflict()
            now = _now()
            if (db.execute('''SELECT COUNT(*) FROM workspace_private_tickets WHERE workspace_id=?
                    AND revoked IS NULL AND run_id IS NULL AND expires>?''', (ws, now)).fetchone()[0]
                    >= LIMITS['tickets_per_workspace']
                    or db.execute('''SELECT COUNT(*) FROM workspace_private_tickets WHERE actor_user_id=?
                         AND revoked IS NULL AND run_id IS NULL AND expires>?''', (actor.user_id, now)).fetchone()[0]
                    >= LIMITS['pending_tickets']):
                raise WorkspaceConflict()
            identity = 'wpt_' + secrets.token_hex(16)
            payload = {'profile': PROFILE, 'id': identity, **bound, 'created': now,
                       'expires': now + LIMITS['ticket_seconds'], 'notice': NOTICE}
            db.execute('INSERT INTO workspace_private_tickets VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)',
                       (identity, ws, draft_id, snapshot_id, actor.user_id, now, payload['expires'],
                        _canonical(payload), self._signature(payload)))
            preview = {key: bound[key] for key in ('workspace_id', 'draft_id', 'snapshot_id', 'snapshot_revision', 'resource_id')}
            preview.update(tool=node['data']['tool'], input=node['data']['input'], seconds=LIMITS['seconds'], max_calls=1)
            self.access._audit(db, actor, ws, 'execution.prepare', identity, bound['snapshot_revision'])
            return {'ticket_id': identity, 'expires': payload['expires'], 'preview': preview, 'notice': NOTICE}

    def _ticket(self, db, identity, ws, draft_id, snapshot_id):
        _identity(identity, 'wpt')
        rows = _rows(db, 'SELECT * FROM workspace_private_tickets WHERE id=? AND workspace_id=? AND draft_id=? AND snapshot_id=?',
                     (identity, ws, draft_id, snapshot_id))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row = rows[0]
        try:
            payload = json.loads(row['payload'])
            _tree(payload)
            if (not self._artifact_signer.verify(payload, row['signature'])
                    or payload['profile'] != PROFILE or payload['notice'] != NOTICE
                    or any(payload[key] != row[key] for key in ('id', 'workspace_id', 'draft_id', 'snapshot_id',
                                                               'actor_user_id', 'created', 'expires'))
                    or payload['expires'] != payload['created'] + LIMITS['ticket_seconds']):
                raise WorkspaceConflict()
            return row, payload
        except (KeyError, TypeError, ValueError):
            raise WorkspaceConflict() from None

    def _open_run(self, row, ticket, ticket_payload, *, decrypt_output=True):
        try:
            if type(row['payload']) is not str or len(row['payload'].encode('utf-8')) > LIMITS['output_bytes']*2+32768:
                raise WorkspaceConflict()
            payload = json.loads(row['payload'])
            if type(payload) is not dict:
                raise WorkspaceConflict()
            _tree({key: value for key, value in payload.items() if key != 'encrypted_output'})
            if (not self._artifact_signer.verify(payload, row['signature'])
                    or payload.get('profile') != PROFILE or payload.get('ticket_hash') != _hash(ticket_payload)
                    or row['status'] not in STATES or ticket['run_id'] != row['id']
                    or row['ticket_id'] != ticket['id']
                    or any(row[key] != ticket[key] for key in ('workspace_id', 'draft_id', 'snapshot_id', 'actor_user_id'))
                    or any(payload[key] != row[key] for key in ('id', 'ticket_id', 'workspace_id', 'draft_id',
                         'snapshot_id', 'actor_user_id', 'status', 'created', 'deadline', 'dispatched', 'finished'))
                    or payload['error_code'] is not None and payload['error_code'] not in ERRORS
                    or row['deadline'] != row['created'] + LIMITS['seconds']):
                raise WorkspaceConflict()
            if type(decrypt_output) is not bool:
                raise WorkspaceConflict()
            if not decrypt_output:
                payload['output'] = None
                payload.pop('encrypted_output', None)
                return payload
            if 'encrypted_output' in payload:
                if payload.get('output') is not None:
                    raise WorkspaceConflict()
                raw = self._output_cipher.open(_canonical(payload['encrypted_output']).encode('ascii'),
                    self._output_context(payload))
                payload['output'] = json.loads(raw)
                _tree(payload['output'])
                del payload['encrypted_output']
            return payload
        except (KeyError, TypeError, ValueError):
            raise WorkspaceConflict() from None

    def _store_run(self, db, payload, *, insert=False):
        stored = dict(payload)
        if self._output_cipher.configured and stored.get('output') is not None:
            stored['encrypted_output'] = json.loads(self._output_cipher.seal(
                _canonical(stored['output']).encode('ascii'), self._output_context(stored)))
            stored['output'] = None
        values = tuple(payload[key] for key in ('id', 'ticket_id', 'workspace_id', 'draft_id', 'snapshot_id',
                       'actor_user_id', 'status', 'created', 'deadline', 'dispatched', 'finished'))
        if insert:
            db.execute('INSERT INTO workspace_private_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (*values, _canonical(stored), self._signature(stored)))
        else:
            db.execute('''UPDATE workspace_private_runs SET status=?,dispatched=?,finished=?,payload=?,signature=? WHERE id=?''',
                       (payload['status'], payload['dispatched'], payload['finished'], _canonical(stored), self._signature(stored), payload['id']))

    @staticmethod
    def _output_context(payload):
        return {name: payload[name] for name in ('profile', 'id', 'workspace_id', 'draft_id', 'snapshot_id', 'ticket_id')}

    def _load_run(self, db, identity, ws, draft_id, snapshot_id, *, decrypt_output=True):
        _identity(identity, 'wpr')
        rows = _rows(db, 'SELECT * FROM workspace_private_runs WHERE id=? AND workspace_id=? AND draft_id=? AND snapshot_id=?',
                     (identity, ws, draft_id, snapshot_id))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row = rows[0]
        ticket, payload = self._ticket(db, row['ticket_id'], ws, draft_id, snapshot_id)
        return row, ticket, payload, self._open_run(row, ticket, payload, decrypt_output=decrypt_output)

    @staticmethod
    def _dto(payload, ticket, *, output=True):
        result = {key: payload[key] for key in ('id', 'status', 'created', 'deadline', 'dispatched', 'finished', 'error_code')}
        if result['status'] in ('prepared', 'dispatched') and (ticket['revoked'] is not None or _now() >= result['deadline']):
            result.update(status='unknown', error_code='INTERRUPTED', finished=None)
        if output:
            result['output'] = payload['output'] if result['status'] == 'succeeded' else None
            if payload.get('output_archived') is True:
                result['output_archived'] = True
        return result

    def _guard(self, run_id, stopped):
        from .concierge.execution_policy import ExecutionDenied
        try:
            with self._internal() as db:
                rows = _rows(db, 'SELECT * FROM workspace_private_runs WHERE id=?', (run_id,))
                if len(rows) != 1:
                    raise WorkspaceDenied()
                row = rows[0]
                _, ticket, claims, payload = self._load_run(db, run_id, row['workspace_id'], row['draft_id'], row['snapshot_id'])
                actor = self._actor_from_claims(claims)
                current, _, _ = self._binding(db, row['workspace_id'], row['draft_id'], row['snapshot_id'], actor)
                if (stopped.is_set() or ticket['revoked'] is not None or row['status'] != 'prepared'
                        or _now() >= row['deadline'] or any(claims[key] != value for key, value in current.items())):
                    raise WorkspaceDenied()
                self._purpose(db, ticket, claims)
                if self.meter is not None:
                    self.meter.dispatch(db, claims, payload)
                payload.update(status='dispatched', dispatched=_now())
                self._store_run(db, payload)
        except (WorkspaceInvalid, WorkspaceDenied, WorkspaceConflict):
            raise ExecutionDenied('Private execution authority is no longer current.', error_code='POLICY_DENIED') from None

    def _finish(self, identity, ws, draft_id, snapshot_id, status, code=None, output=None):
        with self._internal() as db:
            row, ticket, claims, payload = self._load_run(db, identity, ws, draft_id, snapshot_id)
            if row['status'] not in ('prepared', 'dispatched'):
                return self._dto(payload, ticket)
            if ticket['revoked'] is not None or _now() >= row['deadline']:
                status, code, output = 'unknown' if row['dispatched'] is not None else 'denied', 'UPSTREAM_TIMEOUT', None
            elif status == 'succeeded':
                try:
                    actor = self._actor_from_claims(claims)
                    current, _, _ = self._binding(db, ws, draft_id, snapshot_id, actor)
                    if any(claims[key] != value for key, value in current.items()):
                        raise WorkspaceDenied()
                    self._purpose(db, ticket, claims)
                    for guard in self.output_guards:
                        if guard(db, ticket, claims, output) is not True:
                            raise OutputContractRejected()
                except OutputContractRejected:
                    status, code, output = 'failed', 'OUTPUT_REJECTED', None
                except (WorkspaceInvalid, WorkspaceDenied, WorkspaceConflict):
                    status, code, output = 'unknown', 'POLICY_DENIED', None
                if row['dispatched'] is None:
                    status, code, output = 'denied', 'POLICY_DENIED', None
            if row['dispatched'] is None and status == 'unknown':
                status = 'denied' if code == 'POLICY_DENIED' else 'failed'
            payload.update(status=status, error_code=code, output=output if status == 'succeeded' else None, finished=_now())
            self._store_run(db, payload)
            from .workspace_admin_events import emit
            customer = claims.get('actor_user_id')
            emit(self.store, db, 'execution.' + status,
                 customer=customer if isinstance(customer, str) and customer.startswith('cu_') else None,
                 workspace=ws, object_id=identity, outcome=status,
                 event_key='execution:' + identity + ':' + status, error_code=code)
            if self.meter is not None:
                self.meter.finish(db, payload)
            return self._dto(payload, ticket)

    def _output(self, value, resource):
        from .concierge.connections import bindings, gateway_agent_url, project
        from .concierge.recommendation_security import public_data
        from .concierge.security import public_metadata
        _tree(value)
        output = project(public_metadata(public_data(value)), gateway_agent_url(resource['id'], 'mcp'), bindings(resource))
        _tree(output)
        if len(_canonical(output).encode('ascii')) > LIMITS['output_bytes']:
            raise WorkspaceInvalid()
        return output

    def execute(self, ws, draft_id, snapshot_id, body, actor):
        if (type(body) is not dict or set(body) != {'ticket_id', 'authorized', 'notice'}
                or body['authorized'] is not True or body['notice'] != NOTICE):
            raise WorkspaceInvalid()
        control = getattr(self.store, '_service_control', None)
        remote = getattr(self.store, '_service_role', 'legacy') in ('frontend', 'admin')
        if remote and (control is None or not control.status('execution').get('available')):
            raise WorkspaceConflict()
        if not _slots.acquire(blocking=False):
            raise WorkspaceConflict()
        submitted = False
        try:
            with self.access._tx(actor, write=True) as (db, _):
                self._scope(ws, draft_id, snapshot_id, actor, write=True)
                ticket, claims = self._ticket(db, body['ticket_id'], ws, draft_id, snapshot_id)
                if claims['actor_user_id'] != actor.user_id or claims['session_ref'] != actor.session_ref:
                    raise WorkspaceDenied()
                self._purpose(db, ticket, claims)
                if ticket['run_id']:
                    _, _, _, payload = self._load_run(db, ticket['run_id'], ws, draft_id, snapshot_id)
                    return {**self._dto(payload, ticket), 'replayed': True}
                current, node, resource = self._binding(db, ws, draft_id, snapshot_id, actor)
                now = _now()
                if ticket['revoked'] is not None or claims['expires'] <= now or any(claims[key] != value for key, value in current.items()):
                    raise WorkspaceDenied()
                if (self._active_runs(db, now) >= LIMITS['active_runs']
                        or db.execute('SELECT COUNT(*) FROM workspace_private_runs WHERE workspace_id=? AND created>?',
                                      (ws, now - 86400)).fetchone()[0] >= LIMITS['runs_per_day']):
                    raise WorkspaceConflict()
                identity = 'wpr_' + secrets.token_hex(16)
                payload = {'profile': PROFILE, 'id': identity, 'ticket_id': ticket['id'], 'ticket_hash': _hash(claims),
                           **{key: current[key] for key in ('workspace_id', 'draft_id', 'snapshot_id', 'actor_user_id')},
                           'status': 'prepared', 'created': now, 'deadline': now + LIMITS['seconds'],
                           'dispatched': None, 'finished': None, 'error_code': None, 'output': None}
                if remote:
                    payload['worker_execution'] = True
                self._store_run(db, payload, insert=True)
                if self.meter is not None:
                    self.meter.admit(db, claims, payload)
                if db.execute('UPDATE workspace_private_tickets SET run_id=? WHERE id=? AND run_id IS NULL AND revoked IS NULL',
                              (identity, ticket['id'])).rowcount != 1:
                    raise WorkspaceConflict()
                self.access._audit(db, actor, ws, 'execution.admit', identity, claims['snapshot_revision'])
            if remote:
                while _now() < payload['deadline']:
                    result = self.run(ws, draft_id, snapshot_id, identity, actor)
                    if result['status'] not in ('prepared', 'dispatched'):
                        return result
                    time.sleep(.2)
                return self.run(ws, draft_id, snapshot_id, identity, actor)
            submitted = True
            return self._perform_admitted(payload, node, resource, actor)
        finally:
            if not submitted:
                _slots.release()

    def _perform_admitted(self, payload, node, resource, actor):
        ws, draft_id, snapshot_id, identity = (payload[k] for k in
            ('workspace_id', 'draft_id', 'snapshot_id', 'id'))
        submitted = False
        try:
            stopped = threading.Event()
            operation = self.proxy.journal.begin('execution', 'legacy', resource_id=resource['id'], proto='mcp') if getattr(self.proxy, 'journal', None) else None
            attempt = operation.attempt(resource['id'], 'mcp') if operation else None
            from .workspace_admin_events import link_observation
            if getattr(self.store, '_workspace_admin_events_enabled', False):
                with self._internal() as db:
                    link_observation(self.store, db, operation, identity, ws,
                                     actor.user_id if isinstance(actor.user_id, str) else None)

            def work():
                from .concierge.http_security import outbound_operation
                from .observability import attempt_scope
                from .workflow_persistence import dispatch_scope
                from .edge_gateway.result_transport import parent_scope
                with parent_scope(identity,node['id']), (attempt_scope(attempt, finish_errors=False) if attempt else nullcontext()), outbound_operation(LIMITS['seconds']), dispatch_scope(lambda: self._guard(identity, stopped)):
                    from .edge_gateway.native import execute as edge_execute
                    result = edge_execute(self.store, resource,
                        {'tool': node['data']['tool'], 'arguments': node['data']['input']}, scope=identity)
                    if result is not None:
                        return result
                    return self.proxy.execute(resource['id'], node['data']['tool'], node['data']['input'], public=True)

            future = _pool.submit(work)
            submitted = True
            future.add_done_callback(lambda done: _slots.release())
            try:
                result = future.result(timeout=LIMITS['seconds'])
                if type(result) is not dict:
                    status, code, output = 'failed', 'UPSTREAM_PROTOCOL', None
                elif result.get('ok') is True:
                    try:
                        output = self._output(result.get('result', result.get('output', result.get('data'))), resource)
                        status, code = 'succeeded', None
                    except WorkspaceInvalid:
                        status, code, output = 'failed', 'OUTPUT_REJECTED', None
                else:
                    code = result.get('error_code') if result.get('error_code') in ERRORS else 'EXECUTION_FAILED'
                    status, output = 'unknown' if code in ('UPSTREAM_TIMEOUT', 'UPSTREAM_NETWORK', 'UPSTREAM_PROTOCOL') else 'failed', None
                with self._internal() as db:
                    state, _, _, _ = self._load_run(db, identity, ws, draft_id, snapshot_id)
                if state['dispatched'] is None:
                    status, code, output = 'denied', 'POLICY_DENIED', None
                value = self._finish(identity, ws, draft_id, snapshot_id, status, code, output)
            except FutureTimeout:
                stopped.set()
                value = self._finish(identity, ws, draft_id, snapshot_id, 'unknown', 'UPSTREAM_TIMEOUT')
            except Exception as error:
                stopped.set()
                code = getattr(error, 'error_code', None)
                value = self._finish(identity, ws, draft_id, snapshot_id, 'unknown', code if code in ERRORS else 'EXECUTION_FAILED')
            finally:
                stopped.set()
                if operation:
                    attempt.finish(value['status'] if 'value' in locals() else 'unknown', value.get('error_code') if 'value' in locals() else 'EXECUTION_FAILED')
                    operation.finish(value['status'] if 'value' in locals() else 'unknown', value.get('error_code') if 'value' in locals() else 'EXECUTION_FAILED')
                    operation.detach_attempts()
            return value
        finally:
            if not submitted:
                _slots.release()

    def execute_admitted(self, identity, ws, draft_id, snapshot_id):
        """Execute a once-claimed, signed run outside the web process."""
        if not _slots.acquire(blocking=False):
            raise WorkspaceConflict()
        try:
            with self._internal() as db:
                _, _, claims, payload = self._load_run(db, identity, ws, draft_id, snapshot_id)
                if payload.get('worker_execution') is not True or payload['status'] != 'prepared':
                    raise WorkspaceDenied()
                actor = self._actor_from_claims(claims)
                _, node, resource = self._binding(db, ws, draft_id, snapshot_id, actor)
        except BaseException:
            _slots.release()
            raise
        return self._perform_admitted(payload, node, resource, actor)

    def runs(self, ws, draft_id, snapshot_id, actor):
        with self.access._tx(actor) as (db, _):
            self._scope(ws, draft_id, snapshot_id, actor)
            rows = _rows(db, '''SELECT * FROM workspace_private_runs WHERE workspace_id=? AND draft_id=? AND snapshot_id=?
                         ORDER BY created DESC,id DESC LIMIT 30''', (ws, draft_id, snapshot_id))
            result = []
            for row in rows:
                ticket, claims = self._ticket(db, row['ticket_id'], ws, draft_id, snapshot_id)
                result.append(self._dto(self._open_run(row, ticket, claims), ticket, output=False))
            return result

    def run(self, ws, draft_id, snapshot_id, identity, actor):
        with self.access._tx(actor) as (db, _):
            self._scope(ws, draft_id, snapshot_id, actor)
            _, ticket, _, payload = self._load_run(db, identity, ws, draft_id, snapshot_id)
            return self._dto(payload, ticket)

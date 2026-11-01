"""Bounded evidence-change consumer using purpose grants, never staff sessions.

Only the existing metadata notice path is used. Unknown events are not resent.
Grant actors have no authority outside this private adapter and are never
accepted by the ordinary WorkspaceAccess or by business execution endpoints.
"""
from contextlib import contextmanager
import copy
from dataclasses import dataclass
import threading

from .shadow_ledger import clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _rows
from .workspace_machine_updates import (MachineUpdates, PREPARE_NOTICE, DISPATCH_NOTICE)

NOTICE = 'workspace-evidence-change-delivery-grant-v1'


@dataclass(frozen=True, repr=False)
class GrantActor:
    user_id: int
    session_ref: str
    workspace_id: str
    subscription_id: str


class GrantAccess:
    def __init__(self, automation):
        self.automation = automation
        self.store, self.key = automation.core.store, automation.core.access.key

    @contextmanager
    def _tx(self, actor, write=False, highest=False):
        if highest or type(actor) is not GrantActor:
            raise WorkspaceDenied()
        with self.store._lock:
            db = self.store._db
            if db.in_transaction:
                raise WorkspaceConflict()
            try:
                db.execute('BEGIN IMMEDIATE')
                _, user = self._access(actor.workspace_id, actor)
                yield db, user
                self._access(actor.workspace_id, actor)
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _access(self, ws, actor, write=False, owner=False):
        if type(actor) is not GrantActor or actor.workspace_id != ws:
            raise WorkspaceDenied()
        value = self.automation.current(self.store._db, ws, actor.subscription_id)
        if actor.user_id != value['owner']['actor_user_id'] or actor.session_ref != value['owner']['session_ref']:
            raise WorkspaceDenied()
        rows = _rows(self.store._db, 'SELECT * FROM organization_workspaces WHERE id=? AND active=1', (ws,))
        return {**rows[0], 'member_revision': value['owner']['member_revision'], 'member_role': 'owner'}, {
            'role': value['owner']['user_role'], 'user_id': actor.user_id}

    def _audit(self, db, actor, ws, action, identity=None, revision=None):
        self._access(ws, actor, write=True, owner=True)
        value = self.automation.current(db, ws, actor.subscription_id)
        if action == 'machine_updates.prepare':
            count = db.execute('SELECT COUNT(*) FROM workspace_machine_update_events WHERE workspace_id=? AND subscription_id=?',
                               (ws, actor.subscription_id)).fetchone()[0]
            if count > value['automation']['max_events']:
                raise WorkspaceDenied()
        db.execute('''INSERT INTO workspace_access_audit
            (workspace_id,actor_user_id,action,object_id,revision,created) VALUES(?,?,?,?,?,?)''',
            (ws, actor.user_id, 'purpose_grant.' + action, identity, revision, clock()))


class MachineUpdateAutomation:
    def __init__(self, core, *, enabled=False):
        if type(core) is not MachineUpdates or type(enabled) is not bool:
            raise WorkspaceInvalid()
        self.core, self.enabled = core, enabled
        self._stop, self._thread, self._tick = threading.Event(), None, threading.Lock()
        self._cursor = ''
        self.failed_ticks = 0
        self.access = GrantAccess(self)
        source = getattr(core.evidence_source, '__self__', None)
        if (source is None or source.access is not core.access
                or not callable(getattr(source, 'current_projection_in_transaction', None))):
            raise WorkspaceInvalid()
        # Reuse the same signed plane and algorithms under a metadata-only grant
        # adapter. No public or ordinary staff authority is broadened.
        plane = copy.copy(source)
        plane.access = self.access
        self.machine = copy.copy(core)
        self.machine.access = self.access
        def current_projection(ws, rid, actor):
            with self.access._tx(actor) as (db, _):
                return plane.current_projection_in_transaction(db, ws, rid, actor)
        self.machine.evidence_source = current_projection
        verifier = core.destination_verifier
        if getattr(verifier, 'access', None) is core.access:
            verifier = copy.copy(verifier)
            verifier.access = self.access
        self.machine.destination_verifier = verifier
        core.automation = self

    def current(self, db, ws, subscription_id):
        value, _ = self.core._subscription(db, ws, subscription_id)
        grant = value.get('automation')
        if (type(grant) is not dict or set(grant) != {'notice', 'expires', 'max_events'}
                or grant['notice'] != NOTICE or type(grant['expires']) not in (int, float)
                or not clock() < grant['expires'] <= value['created'] + 86400
                or type(grant['max_events']) is not int or not 1 <= grant['max_events'] <= 20):
            raise WorkspaceDenied()
        owner = value['owner']
        rows = _rows(db, '''SELECT w.revision AS workspace_revision,m.revision AS member_revision,u.role AS user_role
            FROM organization_workspaces w JOIN workspace_memberships m ON m.workspace_id=w.id
            JOIN admin_users u ON u.id=m.user_id
            WHERE w.id=? AND w.active=1 AND m.user_id=? AND m.active=1 AND m.role='owner' AND u.active=1''',
            (ws, owner['actor_user_id']))
        if len(rows) != 1 or rows[0]['user_role'] == 'operator' or any(rows[0][key] != owner[key]
                for key in ('workspace_revision', 'member_revision', 'user_role')):
            raise WorkspaceDenied()
        return value

    def authorize(self, ws, body, actor):
        exact(body, ('subscription_id', 'ttl_seconds', 'max_events', 'authorized', 'notice'))
        if (body['authorized'] is not True or body['notice'] != NOTICE
                or type(body['ttl_seconds']) is not int or not 60 <= body['ttl_seconds'] <= 86400
                or type(body['max_events']) is not int or not 1 <= body['max_events'] <= 20):
            raise WorkspaceInvalid()
        with self.core.access._tx(actor, write=True) as (db, _):
            owner = self.core._owner(ws, actor)
            value, _ = self.core._subscription(db, ws, body['subscription_id'])
            if value.get('automation') is not None or value['owner'] != owner:
                raise WorkspaceDenied()
            if db.execute('SELECT 1 FROM workspace_machine_update_events WHERE workspace_id=? AND subscription_id=? LIMIT 1',
                          (ws, value['id'])).fetchone():
                raise WorkspaceDenied()
            now = clock()
            expires = min(now + body['ttl_seconds'], value['created'] + 86400)
            if expires <= now:
                raise WorkspaceDenied()
            value['owner'] = {**owner, 'session_ref': 'purpose:' + value['id']}
            value['automation'] = {'notice': NOTICE, 'expires': expires, 'max_events': body['max_events']}
            db.execute('UPDATE workspace_machine_subscriptions SET payload=?,signature=? WHERE id=? AND workspace_id=?',
                       (_canonical(value), self.core.sign(value), value['id'], ws))
            self.core.access._audit(db, actor, ws, 'machine_updates.automatic_grant', value['id'], 1)
            return {'subscription_id': value['id'], 'expires': expires, 'max_events': body['max_events'],
                    'worker_configured': self.enabled, 'advertising_enabled': False}

    def tick(self):
        if not self.enabled or not self._tick.acquire(blocking=False):
            return {'checked': 0, 'accepted': 0, 'blocked': 0}
        result = {'checked': 0, 'accepted': 0, 'blocked': 0}
        try:
            with self.core.store._lock:
                rows = _rows(self.core.store._db, 'SELECT id,workspace_id FROM workspace_machine_subscriptions WHERE id>? ORDER BY id LIMIT 50', (self._cursor,))
            if not rows:
                self._cursor = ''
                return result
            self._cursor = rows[-1]['id'] if len(rows) == 50 else ''
            for row in rows:
                result['checked'] += 1
                try:
                    with self.core.store._lock:
                        value = self.current(self.core.store._db, row['workspace_id'], row['id'])
                        count = self.core.store._db.execute('SELECT COUNT(*) FROM workspace_machine_update_events WHERE workspace_id=? AND subscription_id=?',
                            (row['workspace_id'], row['id'])).fetchone()[0]
                        if count >= value['automation']['max_events']:
                            raise WorkspaceDenied()
                    actor = GrantActor(value['owner']['actor_user_id'], value['owner']['session_ref'], row['workspace_id'], row['id'])
                    event = self.machine.prepare(row['workspace_id'], {'subscription_id': row['id'],
                        'authorized': True, 'notice': PREPARE_NOTICE}, actor)
                    outcome = self.machine.dispatch(row['workspace_id'], {'event_id': event['id'],
                        'authorized': True, 'notice': DISPATCH_NOTICE}, actor)
                    result['accepted'] += outcome['state'] == 'accepted'
                except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                    result['blocked'] += 1
            return result
        finally:
            self._tick.release()

    def start(self):
        if not self.enabled:
            return True
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop.clear()
        def loop():
            while not self._stop.wait(15):
                try:
                    self.tick()
                except Exception:
                    # A failure never causes an uncertain notice to be retried.
                    self.failed_ticks = min(self.failed_ticks + 1, 1000000)
        self._thread = threading.Thread(target=loop, name='machine-evidence-changes', daemon=True)
        self._thread.start()
        return True

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        return self._thread is None or not self._thread.is_alive()

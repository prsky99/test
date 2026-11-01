"""Current customer read/execute authority, never an administrator conversion.

Customers may inspect explicitly linked workspaces and use the bounded private
runner. This adapter supplies no provisioning, membership mutation or draft-write
API. Its opaque customer identity is retained in private execution attribution.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import sqlite3

from .customer_identity import CustomerActor
from .workspace_access import WorkspaceDenied, WorkspaceConflict, _rows

SCHEMA='''CREATE TABLE IF NOT EXISTS customer_workspace_audit (
 id INTEGER PRIMARY KEY,workspace_id TEXT NOT NULL,customer_id TEXT NOT NULL,
 action TEXT NOT NULL,object_id TEXT,revision INTEGER,created REAL NOT NULL)'''


@dataclass(frozen=True, repr=False)
class CustomerRuntimeActor:
    customer_id: str
    session_ref: str
    workspace_id: str
    token_ref: str | None = None
    principal_kind = 'customer'

    @property
    def user_id(self):
        # Opaque cu_ identifiers cannot collide with integer staff identities.
        return self.customer_id

    def __repr__(self):
        return '<CustomerRuntime private>'


class CustomerWorkspaceAccess:
    def __init__(self, access, identity):
        if identity.store is not access.store:
            raise WorkspaceDenied()
        self.base, self.identity = access, identity
        self.store, self.key = access.store, access.key
        with identity.tx() as db:
            db.execute(SCHEMA)

    def from_scope(self, scope):
        if type(scope) is not dict or scope.get('purpose') not in ('read', 'execute'):
            raise WorkspaceDenied()
        return CustomerRuntimeActor(scope['customer_id'], scope['session_ref'],
                                    scope['workspace_id'], scope.get('token_ref'))

    def actor_from_claims(self, claims):
        if claims.get('actor_kind') != 'customer':
            raise WorkspaceDenied()
        return CustomerRuntimeActor(claims['actor_user_id'], claims['session_ref'],
                                    claims['workspace_id'], claims.get('token_ref'))

    def _authorize(self, actor, write=False):
        if type(actor) is not CustomerRuntimeActor:
            raise WorkspaceDenied()
        return self.identity.authorize(self.store._db,
            CustomerActor(actor.customer_id, actor.session_ref, actor.token_ref),
            actor.workspace_id, 'execute' if write else 'read')

    def _actor(self, actor, write=False, highest=False):
        if highest:
            raise WorkspaceDenied()
        scope = self._authorize(actor, write)
        return {'user_id': scope['customer_id'], 'role': 'customer',
                'expires_at': scope['session_expires']}

    @contextmanager
    def _tx(self, actor, write=False, highest=False, readonly=False):
        # readonly: customer pages that only read skip the global writer lock on PostgreSQL (11-01).
        if readonly and getattr(self.store, 'backend', '') == 'postgresql':
            try:
                with self.store.tx(readonly=True) as db:
                    user = self._actor(actor, write, highest)
                    yield db, user
                    self._actor(actor, write, highest)
            except sqlite3.Error:
                raise WorkspaceConflict() from None
            return
        with self.store._lock:
            db = self.store._db
            if db.in_transaction:
                raise WorkspaceConflict()
            try:
                db.execute('BEGIN IMMEDIATE')
                user = self._actor(actor, write, highest)
                yield db, user
                self._actor(actor, write, highest)
                db.commit()
            except BaseException as error:
                try: db.rollback()
                except sqlite3.Error: pass
                if isinstance(error, sqlite3.Error):
                    raise WorkspaceConflict() from None
                raise

    def _access(self, ws, actor, write=False, owner=False):
        if type(actor) is not CustomerRuntimeActor or actor.workspace_id != ws:
            raise WorkspaceDenied()
        scope = self._authorize(actor, write)
        if owner and (scope['role'] != 'owner' or actor.token_ref is not None):
            raise WorkspaceDenied()
        rows = _rows(self.store._db, 'SELECT * FROM organization_workspaces WHERE id=? AND active=1', (ws,))
        if len(rows) != 1:
            raise WorkspaceDenied()
        member = {**rows[0], 'member_revision': scope['link_revision'],
                  'member_role': 'editor' if scope['role'] == 'runner' else scope['role']}
        return member, {'user_id': actor.customer_id, 'role': 'customer'}

    def _audit(self, db, actor, ws, action, identity=None, revision=None):
        from .workspace_execution import _now
        self._access(ws, actor, write=True)
        db.execute('''INSERT INTO customer_workspace_audit
            (workspace_id,customer_id,action,object_id,revision,created) VALUES(?,?,?,?,?,?)''',
            (ws, actor.customer_id, action, identity, revision, _now()))
        from .workspace_admin_events import emit
        emit(self.store, db, action, customer=actor.customer_id, workspace=ws, object_id=identity)
        db.execute('''DELETE FROM customer_workspace_audit WHERE id IN
            (SELECT id FROM customer_workspace_audit WHERE workspace_id=? ORDER BY id DESC LIMIT 100 OFFSET 5000)''', (ws,))

    def _draft_row(self, *args, **kwargs):
        return self.base._draft_row(*args, **kwargs)

    def _open_draft(self, *args):
        return self.base._open_draft(*args)

    def _version_row(self, *args):
        return self.base._version_row(*args)

    def _open_version(self, *args):
        return self.base._open_version(*args)

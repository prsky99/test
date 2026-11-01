"""Customer-owned private organizations with exact-identity invitations.

Customer authority stays separate from staff memberships. Invitations do not
carry bearer authority, and archived or restored organizations cannot be revived
through these methods. Safety evidence is retained after account withdrawal.
"""
from contextlib import contextmanager
import hashlib
import hmac
import secrets

from .customer_identity import CustomerActor, _time
from .customer_workspace_runtime import CustomerRuntimeActor, CustomerWorkspaceAccess
from .workspace_access import (WorkspaceAccess, WorkspaceConflict, WorkspaceDenied,
                               WorkspaceInvalid, _canonical, _identity, _revision,
                               _rows, _safe_text, _tree)

PROFILE = 'customer-organizations-v1'
ROLES = ('owner', 'editor', 'viewer', 'runner')
LIMITS = {'owned_workspaces': 10, 'members': 100, 'pending_invitations': 50,
          'invitation_seconds': 604800, 'invitations': 500, 'audit_read': 100}
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS customer_organizations (
       workspace_id TEXT PRIMARY KEY,active INTEGER NOT NULL,revision INTEGER NOT NULL,
       created_by TEXT NOT NULL,created REAL NOT NULL,archived REAL)''',
    '''CREATE TABLE IF NOT EXISTS customer_organization_invitations (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,recipient_customer_id TEXT NOT NULL,
       recipient_revision INTEGER NOT NULL,role TEXT NOT NULL,status TEXT NOT NULL,
       revision INTEGER NOT NULL,created_by TEXT NOT NULL,creator_link_revision INTEGER NOT NULL,
       created REAL NOT NULL,expires REAL NOT NULL,resolved REAL)''',
    '''CREATE TABLE IF NOT EXISTS customer_organization_audit (
       id INTEGER PRIMARY KEY,workspace_id TEXT,actor_ref TEXT NOT NULL,action TEXT NOT NULL,
       object_ref TEXT,revision INTEGER,created REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS customer_account_deletions (
       customer_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,requested REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS customer_organization_invitation_recipient ON customer_organization_invitations(recipient_customer_id,status,expires)',
    'CREATE INDEX IF NOT EXISTS customer_organization_audit_scope ON customer_organization_audit(workspace_id,id)',
)


class CustomerDraftAccess(CustomerWorkspaceAccess, WorkspaceAccess):
    """Reuse signed draft storage under customer edit, never runner, authority."""
    def _authorize(self, actor, write=False):
        if type(actor) is not CustomerRuntimeActor or actor.token_ref is not None:
            raise WorkspaceDenied()
        return self.identity.authorize(self.store._db,
            CustomerActor(actor.customer_id, actor.session_ref), actor.workspace_id,
            'edit' if write else 'read')

    def _save_draft_in_transaction(self, db, ws, body, actor):
        result = super()._save_draft_in_transaction(db,ws,body,actor)
        if getattr(self,'credits',None) is not None:
            self.credits.saved(db,ws,result['id'],result['revision'],actor,parent=body.get('id'))
        return result

    def _sign(self, value):
        return self.base._sign(value)

    def _verify(self, value, signature):
        return self.base._verify(value, signature)

    def _audit(self, db, actor, ws, action, identity=None, revision=None):
        # This separate attribution table never impersonates an administrator.
        self._access(ws, actor, write=True)
        db.execute('''INSERT INTO customer_workspace_audit
            (workspace_id,customer_id,action,object_id,revision,created) VALUES(?,?,?,?,?,?)''',
            (ws, actor.customer_id, action, identity, revision, _time()))
        from .workspace_admin_events import emit
        emit(self.store, db, action, customer=actor.customer_id, workspace=ws, object_id=identity)

    def _workspace(self, row, user):
        role = row['member_role']
        return {'id': row['id'], 'name': row['name'], 'active': bool(row['active']),
                'revision': row['revision'], 'role': role,
                'can_manage': role == 'owner', 'can_edit': role in ('owner', 'editor'),
                'can_run': role in ('owner', 'editor', 'runner')}


class CustomerOrganizations:
    def __init__(self, identity, access):
        if identity.store is not access.store:
            raise WorkspaceInvalid()
        self.identity, self.access, self.store = identity, access, identity.store
        self.key = hmac.new(identity.key, PROFILE.encode(), hashlib.sha256).digest()
        from .private_artifact_keys import ArtifactSigner
        self.signer = ArtifactSigner(self.key, PROFILE)
        with identity.tx() as db:
            for statement in SCHEMA:
                db.execute(statement)
        self.drafts = CustomerDraftAccess(access, identity)

    def _signature(self, value):
        return self.signer.sign(value)

    def _actor(self, db, actor):
        if type(actor) is not CustomerActor or actor.token_ref is not None:
            raise WorkspaceDenied()
        _identity(actor.customer_id, 'cu')
        self.identity._session(db, actor.session_ref, actor.customer_id)
        return actor

    @contextmanager
    def _tx(self, actor):
        with self.identity.tx() as db:
            self._actor(db, actor)
            yield db
            self._actor(db, actor)

    @contextmanager
    def _read(self, actor):
        # Pages that only read skip the global writer lock (11-01 support lock timeouts).
        with self.identity.read_tx() as db:
            self._actor(db, actor)
            yield db

    def _audit(self, db, actor, ws, action, object_ref=None, revision=None):
        value = {'workspace_id': ws, 'actor_ref': actor.customer_id, 'action': action,
                 'object_ref': object_ref, 'revision': revision, 'created': _time()}
        db.execute('''INSERT INTO customer_organization_audit
            (workspace_id,actor_ref,action,object_ref,revision,created,payload,signature)
            VALUES(?,?,?,?,?,?,?,?)''',
            (ws, actor.customer_id, action, object_ref, revision, value['created'],
             _canonical(value), self._signature(value)))
        from .workspace_admin_events import emit
        emit(self.store, db, action, customer=actor.customer_id, workspace=ws, object_id=object_ref)

    def _scope(self, db, ws, actor, purpose='read'):
        _identity(ws, 'ws')
        scope = self.identity.authorize(db, actor, ws, purpose)
        org = _rows(db, 'SELECT * FROM customer_organizations WHERE workspace_id=? AND active=1', (ws,))
        if len(org) != 1:
            raise WorkspaceDenied()
        return scope, org[0]

    def _workspace(self, db, ws, actor):
        scope, org = self._scope(db, ws, actor)
        row = _rows(db, 'SELECT name,revision FROM organization_workspaces WHERE id=? AND active=1', (ws,))[0]
        return {'id': ws, 'name': row['name'], 'revision': row['revision'],
                'organization_revision': org['revision'], 'role': scope['role'],
                'link_revision': scope['link_revision'], 'can_manage': scope['role'] == 'owner',
                'can_edit': scope['role'] in ('owner', 'editor'),
                'can_run': scope['role'] in ('owner', 'editor', 'runner')}

    def _bump(self, db, ws):
        now = _time()
        db.execute('UPDATE customer_organizations SET revision=revision+1 WHERE workspace_id=? AND active=1', (ws,))
        db.execute('UPDATE organization_workspaces SET revision=revision+1,updated=? WHERE id=? AND active=1', (now, ws))
        db.execute('UPDATE customer_bff_tokens SET revoked=? WHERE workspace_id=? AND revoked IS NULL', (now, ws))

    def _owners(self, db, ws, excluding=None):
        owners = _rows(db, '''SELECT l.customer_id,i.issuer FROM customer_workspace_links l
            JOIN customer_identities i ON i.id=l.customer_id
            WHERE l.workspace_id=? AND l.role='owner' AND l.active=1 AND i.active=1
            AND (? IS NULL OR l.customer_id!=?)''', (ws, excluding, excluding))
        current = []
        for owner in owners:
            try:
                self.identity._issuer_configuration(owner['issuer'])
            except WorkspaceDenied:
                continue
            current.append({'customer_id': owner['customer_id']})
        return current

    def _expire(self, db, ws=None):
        # Fixed predicates and bounded per-organization pending capacity.
        if ws is None:
            db.execute("UPDATE customer_organization_invitations SET status='expired',revision=revision+1,resolved=? WHERE status='pending' AND expires<=?", (_time(), _time()))
        else:
            db.execute("UPDATE customer_organization_invitations SET status='expired',revision=revision+1,resolved=? WHERE workspace_id=? AND status='pending' AND expires<=?", (_time(), ws, _time()))

    def list(self, actor):
        with self._read(actor) as db:
            rows = _rows(db, '''SELECT o.workspace_id FROM customer_organizations o
                JOIN organization_workspaces w ON w.id=o.workspace_id
                JOIN customer_workspace_links l ON l.workspace_id=o.workspace_id
                WHERE o.active=1 AND w.active=1 AND l.customer_id=? AND l.active=1
                ORDER BY w.updated DESC,o.workspace_id LIMIT 101''', (actor.customer_id,))
            if len(rows) > 100:
                raise WorkspaceConflict()
            account = _rows(db, 'SELECT revision FROM customer_identities WHERE id=?', (actor.customer_id,))[0]
            return {'customer_id': actor.customer_id, 'account_revision': account['revision'],
                    'organizations': [self._workspace(db, row['workspace_id'], actor) for row in rows]}

    def create(self, body, actor):
        if type(body) is not dict or set(body) != {'name'}:
            raise WorkspaceInvalid()
        _safe_text(body['name'], 120)
        with self._tx(actor) as db:
            count = db.execute('''SELECT COUNT(*) FROM customer_organizations o
                JOIN customer_workspace_links l ON l.workspace_id=o.workspace_id
                WHERE o.active=1 AND l.customer_id=? AND l.active=1 AND l.role='owner' ''', (actor.customer_id,)).fetchone()[0]
            if count >= LIMITS['owned_workspaces'] or db.execute('SELECT COUNT(*) FROM organization_workspaces').fetchone()[0] >= 10000:
                raise WorkspaceConflict()
            ws, now = 'ws_' + secrets.token_hex(16), _time()
            # Zero is a non-staff sentinel. The exact customer creator is kept
            # solely in the customer organization and signed audit namespaces.
            db.execute('INSERT INTO organization_workspaces VALUES(?,?,1,1,0,?,?)', (ws, body['name'], now, now))
            db.execute('INSERT INTO customer_organizations VALUES(?,1,1,?,?,NULL)', (ws, actor.customer_id, now))
            db.execute("INSERT INTO customer_workspace_links VALUES(?,?,'owner',1,1,?)", (ws, actor.customer_id, now))
            self._audit(db, actor, ws, 'organization.create', ws, 1)
            return self._workspace(db, ws, actor)

    def detail(self, ws, actor):
        with self._read(actor) as db:
            return self._workspace(db, ws, actor)

    def rename(self, ws, body, actor):
        if type(body) is not dict or set(body) != {'name', 'revision'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        _safe_text(body['name'], 120)
        with self._tx(actor) as db:
            self._scope(db, ws, actor, 'manage')
            changed = db.execute('UPDATE organization_workspaces SET name=? WHERE id=? AND revision=? AND active=1', (body['name'], ws, body['revision'])).rowcount
            if changed != 1:
                raise WorkspaceConflict()
            self._bump(db, ws)
            self._audit(db, actor, ws, 'organization.rename', ws, body['revision'] + 1)
            return self._workspace(db, ws, actor)

    def members(self, ws, actor):
        with self._read(actor) as db:
            self._scope(db, ws, actor, 'manage')
            return _rows(db, '''SELECT l.customer_id,l.role,l.active,l.revision FROM customer_workspace_links l
                JOIN customer_identities i ON i.id=l.customer_id WHERE l.workspace_id=? AND i.active=1
                ORDER BY l.customer_id LIMIT 100''', (ws,))

    def set_member(self, ws, body, actor):
        if (type(body) is not dict or set(body) != {'customer_id', 'role', 'active', 'revision'}
                or body['role'] not in ROLES or type(body['active']) is not bool or not _revision(body['revision'])):
            raise WorkspaceInvalid()
        _identity(body['customer_id'], 'cu')
        with self._tx(actor) as db:
            self._scope(db, ws, actor, 'manage')
            rows = _rows(db, 'SELECT * FROM customer_workspace_links WHERE workspace_id=? AND customer_id=? AND active=1', (ws, body['customer_id']))
            if len(rows) != 1:
                raise WorkspaceDenied()
            old = rows[0]
            if old['revision'] != body['revision']:
                raise WorkspaceConflict()
            if old['role'] == 'owner' and (body['role'] != 'owner' or not body['active']) and not self._owners(db, ws, body['customer_id']):
                raise WorkspaceConflict()
            # Promoting a member to owner also requires their accepted invitation
            # or the explicit transfer operation, rather than silent elevation.
            if old['role'] != 'owner' and body['role'] == 'owner':
                raise WorkspaceInvalid()
            revision = old['revision'] + 1
            db.execute('UPDATE customer_workspace_links SET role=?,active=?,revision=?,updated=? WHERE workspace_id=? AND customer_id=? AND revision=?',
                       (body['role'], int(body['active']), revision, _time(), ws, body['customer_id'], old['revision']))
            self._bump(db, ws)
            self._audit(db, actor, ws, 'member.update', body['customer_id'], revision)
            return {**body, 'revision': revision}

    def invite(self, ws, body, actor):
        if (type(body) is not dict or set(body) != {'customer_id', 'role', 'revision'}
                or body['role'] not in ROLES or not _revision(body['revision'])):
            raise WorkspaceInvalid()
        _identity(body['customer_id'], 'cu')
        with self._tx(actor) as db:
            scope, org = self._scope(db, ws, actor, 'manage')
            if org['revision'] != body['revision']:
                raise WorkspaceConflict()
            self._expire(db, ws)
            db.execute("DELETE FROM customer_organization_invitations WHERE id IN (SELECT id FROM customer_organization_invitations WHERE workspace_id=? AND status!='pending' AND resolved<? ORDER BY resolved LIMIT 50)", (ws, _time() - 90 * 86400))
            target = _rows(db, 'SELECT revision FROM customer_identities WHERE id=? AND active=1', (body['customer_id'],))
            current = _rows(db, 'SELECT active FROM customer_workspace_links WHERE workspace_id=? AND customer_id=?', (ws, body['customer_id']))
            if len(target) != 1 or body['customer_id'] == actor.customer_id or current and current[0]['active']:
                raise WorkspaceDenied()
            if (db.execute("SELECT COUNT(*) FROM customer_organization_invitations WHERE workspace_id=? AND status='pending'", (ws,)).fetchone()[0] >= LIMITS['pending_invitations']
                    or db.execute('SELECT COUNT(*) FROM customer_organization_invitations WHERE workspace_id=?', (ws,)).fetchone()[0] >= LIMITS['invitations']
                    or not current and db.execute('SELECT COUNT(*) FROM customer_workspace_links WHERE workspace_id=?', (ws,)).fetchone()[0] >= LIMITS['members']):
                raise WorkspaceConflict()
            if db.execute("SELECT 1 FROM customer_organization_invitations WHERE workspace_id=? AND recipient_customer_id=? AND status='pending'", (ws, body['customer_id'])).fetchone():
                raise WorkspaceConflict()
            identity, now = 'coi_' + secrets.token_hex(16), _time()
            db.execute("INSERT INTO customer_organization_invitations VALUES(?,?,?,?,?,'pending',1,?,?,?,?,NULL)",
                       (identity, ws, body['customer_id'], target[0]['revision'], body['role'], actor.customer_id,
                        scope['link_revision'], now, now + LIMITS['invitation_seconds']))
            self._audit(db, actor, ws, 'invitation.create', identity, 1)
            return {'id': identity, 'role': body['role'], 'status': 'pending', 'revision': 1, 'expires': now + LIMITS['invitation_seconds']}

    def invitations(self, actor, ws=None):
        with self._tx(actor) as db:
            if ws is not None:
                self._scope(db, ws, actor, 'manage')
                self._expire(db, ws)
                return _rows(db, '''SELECT id,recipient_customer_id,role,status,revision,expires
                    FROM customer_organization_invitations WHERE workspace_id=? ORDER BY created DESC LIMIT 100''', (ws,))
            db.execute("UPDATE customer_organization_invitations SET status='expired',revision=revision+1,resolved=? WHERE recipient_customer_id=? AND status='pending' AND expires<=?", (_time(), actor.customer_id, _time()))
            return _rows(db, '''SELECT i.id,i.workspace_id,w.name,i.role,i.status,i.revision,i.expires
                FROM customer_organization_invitations i JOIN customer_organizations o ON o.workspace_id=i.workspace_id
                JOIN organization_workspaces w ON w.id=i.workspace_id WHERE i.recipient_customer_id=?
                AND o.active=1 AND w.active=1 ORDER BY i.created DESC LIMIT 100''', (actor.customer_id,))

    def resolve_invitation(self, invitation, body, actor):
        _identity(invitation, 'coi')
        if type(body) is not dict or set(body) != {'decision', 'revision'} or body['decision'] not in ('accept', 'decline', 'revoke') or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self._tx(actor) as db:
            rows = _rows(db, 'SELECT * FROM customer_organization_invitations WHERE id=?', (invitation,))
            if len(rows) != 1:
                raise WorkspaceDenied()
            row = rows[0]
            if body['decision'] == 'revoke':
                self._scope(db, row['workspace_id'], actor, 'manage')
            elif actor.customer_id != row['recipient_customer_id']:
                raise WorkspaceDenied()
            if row['revision'] != body['revision'] or row['status'] != 'pending' or row['expires'] <= _time():
                raise WorkspaceConflict()
            if body['decision'] == 'accept':
                current = _rows(db, 'SELECT revision FROM customer_identities WHERE id=? AND active=1', (actor.customer_id,))
                issuer = _rows(db, "SELECT revision FROM customer_workspace_links WHERE workspace_id=? AND customer_id=? AND active=1 AND role='owner'", (row['workspace_id'], row['created_by']))
                workspace = _rows(db, '''SELECT 1 FROM customer_organizations o JOIN organization_workspaces w ON w.id=o.workspace_id
                    WHERE o.workspace_id=? AND o.active=1 AND w.active=1''', (row['workspace_id'],))
                if (len(current) != 1 or current[0]['revision'] != row['recipient_revision'] or len(issuer) != 1
                        or issuer[0]['revision'] != row['creator_link_revision'] or len(workspace) != 1):
                    raise WorkspaceDenied()
                old = _rows(db, 'SELECT revision,active FROM customer_workspace_links WHERE workspace_id=? AND customer_id=?', (row['workspace_id'], actor.customer_id))
                if old and old[0]['active']:
                    raise WorkspaceConflict()
                if row['role'] == 'owner' and db.execute('''SELECT COUNT(*) FROM customer_organizations o JOIN customer_workspace_links l ON l.workspace_id=o.workspace_id
                    WHERE o.active=1 AND l.customer_id=? AND l.active=1 AND l.role='owner' ''', (actor.customer_id,)).fetchone()[0] >= LIMITS['owned_workspaces']:
                    raise WorkspaceConflict()
                if not old and db.execute('SELECT COUNT(*) FROM customer_workspace_links WHERE workspace_id=?', (row['workspace_id'],)).fetchone()[0] >= LIMITS['members']:
                    raise WorkspaceConflict()
                revision = (old[0]['revision'] if old else 0) + 1
                db.execute('''INSERT INTO customer_workspace_links VALUES(?,?,?,1,?,?) ON CONFLICT(workspace_id,customer_id)
                    DO UPDATE SET role=excluded.role,active=1,revision=excluded.revision,updated=excluded.updated''',
                    (row['workspace_id'], actor.customer_id, row['role'], revision, _time()))
                self._bump(db, row['workspace_id'])
            status = {'accept': 'accepted', 'decline': 'declined', 'revoke': 'revoked'}[body['decision']]
            db.execute('UPDATE customer_organization_invitations SET status=?,revision=revision+1,resolved=? WHERE id=? AND revision=? AND status=\'pending\'', (status, _time(), invitation, body['revision']))
            self._audit(db, actor, row['workspace_id'], 'invitation.' + status, invitation, body['revision'] + 1)
            return {'id': invitation, 'status': status, 'revision': body['revision'] + 1}

    def transfer(self, ws, body, actor):
        if type(body) is not dict or set(body) != {'customer_id', 'revision', 'target_revision'} or not _revision(body['revision']) or not _revision(body['target_revision']):
            raise WorkspaceInvalid()
        _identity(body['customer_id'], 'cu')
        with self._tx(actor) as db:
            scope, org = self._scope(db, ws, actor, 'manage')
            if org['revision'] != body['revision']:
                raise WorkspaceConflict()
            target = _rows(db, '''SELECT l.* FROM customer_workspace_links l JOIN customer_identities i ON i.id=l.customer_id
                WHERE l.workspace_id=? AND l.customer_id=? AND l.active=1 AND i.active=1''', (ws, body['customer_id']))
            # The recipient must first accept an owner invitation. This avoids
            # imposing ownership responsibilities through a role mutation.
            if len(target) != 1 or target[0]['role'] != 'owner' or body['customer_id'] == actor.customer_id:
                raise WorkspaceDenied()
            if target[0]['revision'] != body['target_revision']:
                raise WorkspaceConflict()
            db.execute("UPDATE customer_workspace_links SET role='editor',revision=revision+1,updated=? WHERE workspace_id=? AND customer_id=? AND revision=?", (_time(), ws, actor.customer_id, scope['link_revision']))
            self._bump(db, ws)
            self._audit(db, actor, ws, 'ownership.transfer', body['customer_id'], org['revision'] + 1)
            return self._workspace(db, ws, actor)

    def leave(self, ws, body, actor):
        if type(body) is not dict or set(body) != {'revision'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self._tx(actor) as db:
            scope, _ = self._scope(db, ws, actor)
            if scope['link_revision'] != body['revision']:
                raise WorkspaceConflict()
            if scope['role'] == 'owner' and not self._owners(db, ws, actor.customer_id):
                raise WorkspaceConflict()
            db.execute('UPDATE customer_workspace_links SET active=0,revision=revision+1,updated=? WHERE workspace_id=? AND customer_id=? AND revision=?', (_time(), ws, actor.customer_id, body['revision']))
            self._bump(db, ws)
            self._audit(db, actor, ws, 'member.leave', actor.customer_id, body['revision'] + 1)
            return {'left': True}

    def _archive(self, db, ws, actor):
        now = _time()
        self._bump(db, ws)
        db.execute('UPDATE customer_organizations SET active=0,archived=? WHERE workspace_id=?', (now, ws))
        db.execute('UPDATE organization_workspaces SET active=0 WHERE id=?', (ws,))
        db.execute('UPDATE customer_workspace_links SET active=0,revision=revision+1,updated=? WHERE workspace_id=?', (now, ws))
        db.execute("UPDATE customer_organization_invitations SET status='revoked',revision=revision+1,resolved=? WHERE workspace_id=? AND status='pending'", (now, ws))
        self._audit(db, actor, ws, 'organization.archive', ws)

    def archive(self, ws, body, actor):
        if type(body) is not dict or set(body) != {'revision', 'confirm'} or body['confirm'] != 'ARCHIVE' or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self._tx(actor) as db:
            _, org = self._scope(db, ws, actor, 'manage')
            if org['revision'] != body['revision']:
                raise WorkspaceConflict()
            self._archive(db, ws, actor)
            return {'archived': True}

    def audit(self, ws, actor):
        with self._read(actor) as db:
            self._scope(db, ws, actor, 'manage')
            rows = _rows(db, 'SELECT action,object_ref,revision,created,payload,signature FROM customer_organization_audit WHERE workspace_id=? ORDER BY id DESC LIMIT 100', (ws,))
            import json
            for row in rows:
                payload = json.loads(row['payload'])
                if (not self.signer.verify(payload, row['signature']) or payload.get('workspace_id') != ws
                        or any(payload.get(key) != row[key] for key in ('action', 'object_ref', 'revision', 'created'))):
                    raise WorkspaceConflict()
            return [{key: row[key] for key in ('action', 'object_ref', 'revision', 'created')} for row in rows]

    def runtime_actor(self, ws, actor):
        with self._read(actor) as db:
            self._scope(db, ws, actor)
        return CustomerRuntimeActor(actor.customer_id, actor.session_ref, ws)

    def delete_account(self, body, actor):
        if (type(body) is not dict or set(body) != {'revision', 'confirm', 'archive_owned'}
                or body['confirm'] != 'DELETE' or type(body['archive_owned']) is not bool or not _revision(body['revision'])):
            raise WorkspaceInvalid()
        # The final current-session check precedes the deliberate revocation.
        with self.identity.tx() as db:
            self._actor(db, actor)
            account = _rows(db, 'SELECT revision FROM customer_identities WHERE id=? AND active=1', (actor.customer_id,))
            if len(account) != 1 or account[0]['revision'] != body['revision']:
                raise WorkspaceConflict()
            owned = _rows(db, '''SELECT o.workspace_id FROM customer_organizations o JOIN organization_workspaces w ON w.id=o.workspace_id
                JOIN customer_workspace_links l ON l.workspace_id=o.workspace_id
                WHERE o.active=1 AND w.active=1 AND l.customer_id=? AND l.active=1 AND l.role='owner' ''', (actor.customer_id,))
            sole = [row['workspace_id'] for row in owned if not self._owners(db, row['workspace_id'], actor.customer_id)]
            if sole and not body['archive_owned']:
                raise WorkspaceConflict()
            for ws in sole:
                self._archive(db, ws, actor)
            now = _time()
            links = _rows(db, 'SELECT workspace_id FROM customer_workspace_links WHERE customer_id=? AND active=1', (actor.customer_id,))
            for row in links:
                self._bump(db, row['workspace_id'])
                self._audit(db, actor, row['workspace_id'], 'account.withdrawal', actor.customer_id)
            db.execute('UPDATE customer_workspace_links SET active=0,revision=revision+1,updated=? WHERE customer_id=? AND active=1', (now, actor.customer_id))
            db.execute('UPDATE customer_sessions SET revoked=? WHERE customer_id=? AND revoked IS NULL', (now, actor.customer_id))
            db.execute('UPDATE customer_bff_tokens SET revoked=? WHERE customer_id=? AND revoked IS NULL', (now, actor.customer_id))
            db.execute("UPDATE customer_organization_invitations SET status='revoked',revision=revision+1,resolved=? WHERE (recipient_customer_id=? OR created_by=?) AND status='pending'", (now, actor.customer_id, actor.customer_id))
            db.execute('UPDATE customer_identities SET active=0,revision=revision+1,last_login=0 WHERE id=? AND revision=?', (actor.customer_id, body['revision']))
            # The keyed subject tombstone prevents the same withdrawn identity
            # silently recovering old access on its next sign-in. No email,
            # provider token, or display name was collected in this namespace.
            receipt = {'customer_id': actor.customer_id, 'revision': body['revision'] + 1,
                       'requested': now, 'archived_organizations': len(sole),
                       'access_revoked': True, 'safety_evidence_retained': True,
                       'backup_erasure_confirmed': False}
            db.execute('INSERT INTO customer_account_deletions VALUES(?,?,?,?,?)',
                       (actor.customer_id, receipt['revision'], now, _canonical(receipt), self._signature(receipt)))
            self._audit(db, actor, None, 'account.delete', actor.customer_id, receipt['revision'])
            return {'account_deleted': True, 'archived_organizations': len(sole),
                    'access_revoked': True, 'safety_evidence_retained': True}

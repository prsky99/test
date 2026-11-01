"""Named-session workspace membership and non-executable private saved drafts.

No legacy workflow, execution, deployment, publication, provider ownership or
visitor authority is created here. The caller supplies the Store and key.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import html
import json
import math
import re
import secrets
import sqlite3
import time
from urllib.parse import unquote

from .concierge.recommendation_security import public_data, secret_name

PROFILE = 'workspace-private-snapshots-v1'
ROLES = ('owner', 'editor', 'viewer')
LIMITS = {'workspaces': 100, 'members': 100, 'drafts': 100, 'versions': 50,
          'nodes': 6, 'edges': 12, 'body_bytes': 65536, 'depth': 12,
          'tree_nodes': 2000, 'name': 120, 'description': 1000, 'audit': 100}
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS organization_workspaces (
       id TEXT PRIMARY KEY,name TEXT NOT NULL,active INTEGER NOT NULL,
       revision INTEGER NOT NULL,created_by INTEGER NOT NULL,created REAL NOT NULL,updated REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_memberships (
       workspace_id TEXT NOT NULL,user_id INTEGER NOT NULL,role TEXT NOT NULL,
       active INTEGER NOT NULL,revision INTEGER NOT NULL,updated REAL NOT NULL,
       PRIMARY KEY(workspace_id,user_id))''',
    '''CREATE TABLE IF NOT EXISTS workspace_drafts (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,name TEXT NOT NULL,description TEXT NOT NULL,
       definition TEXT NOT NULL,revision INTEGER NOT NULL,active INTEGER NOT NULL,
       created_by INTEGER NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
       payload_hash TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_versions (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,draft_id TEXT NOT NULL,
       ordinal INTEGER NOT NULL,draft_revision INTEGER NOT NULL,revision INTEGER NOT NULL,
       active INTEGER NOT NULL,created_by INTEGER NOT NULL,created REAL NOT NULL,revoked REAL,
       payload TEXT NOT NULL,payload_hash TEXT NOT NULL,signature TEXT NOT NULL,state_signature TEXT NOT NULL,
       UNIQUE(workspace_id,draft_id,ordinal))''',
    '''CREATE TABLE IF NOT EXISTS workspace_access_audit (
       id INTEGER PRIMARY KEY,workspace_id TEXT NOT NULL,actor_user_id INTEGER NOT NULL,
       action TEXT NOT NULL,object_id TEXT,revision INTEGER,created REAL NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS workspace_drafts_scope ON workspace_drafts(workspace_id,created,id)',
    'CREATE INDEX IF NOT EXISTS workspace_versions_scope ON workspace_versions(workspace_id,draft_id,ordinal)',
    'CREATE INDEX IF NOT EXISTS workspace_audit_scope ON workspace_access_audit(workspace_id,id)',
)
_URI = re.compile(r'(?i)\b[a-z][a-z0-9+.-]{1,30}://|(?:^|\s)www\.|(?:\{\{|\}\}|\$node|\$prev)')
_PATH = re.compile(r'(?i)(?:/Users/|/home/|/private/|/var/|/etc/|/tmp/|[A-Z]:\\)')
_QUOTED = re.compile(r'''["'](?P<name>[A-Za-z][A-Za-z _-]{0,47})["']\s*:\s*''')


class WorkspaceError(ValueError):
    code = 'workspace_invalid'


class WorkspaceDenied(WorkspaceError):
    code = 'workspace_unavailable'

    def __init__(self):
        super().__init__('The workspace object or current session is unavailable.')


class WorkspaceConflict(WorkspaceError):
    code = 'workspace_conflict'

    def __init__(self):
        super().__init__('Workspace state changed or could not be confirmed. Reload before saving.')


class WorkspaceLimit(WorkspaceConflict):
    """A bounded count was reached; unlike a conflict, retrying unchanged cannot succeed."""
    code = 'workspace_limit'

    def __init__(self, message='This workspace has reached a saved-item limit.'):
        WorkspaceError.__init__(self, message)


class WorkspaceInvalid(WorkspaceError):
    def __init__(self):
        super().__init__('Provide a supported bounded private workspace snapshot.')


@dataclass(frozen=True, repr=False)
class SessionActor:
    user_id: int
    session_ref: str

    def __repr__(self):
        return '<WorkspaceSession private>'


def _now():
    return time.time()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode('ascii')).hexdigest()


def _positive(value):
    return type(value) is int and 0 < value < 2**63


def _revision(value, zero=False):
    return type(value) is int and (0 if zero else 1) <= value < 2**63


def _identity(value, prefix):
    if type(value) is not str or not re.fullmatch(prefix + r'_[0-9a-f]{32}', value):
        raise WorkspaceDenied()
    return value


def _utf8(value):
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise WorkspaceInvalid() from None


def _rows(db, statement, values=()):
    cursor = db.execute(statement, values)
    names = tuple(item[0] for item in cursor.description) if cursor.description else ()
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _tree(value):
    total = 0

    def walk(item, depth):
        nonlocal total
        total += 1
        if total > LIMITS['tree_nodes'] or depth > LIMITS['depth']:
            raise WorkspaceInvalid()
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise WorkspaceInvalid()
            for key, child in item.items():
                if len(key) > 120 or '\0' in key:
                    raise WorkspaceInvalid()
                _utf8(key)
                walk(child, depth + 1)
        elif type(item) is list:
            for child in item:
                walk(child, depth + 1)
        elif type(item) is str:
            if len(item) > 16000 or '\0' in item:
                raise WorkspaceInvalid()
            _utf8(item)
        elif item is not None and type(item) not in (int, float, bool):
            raise WorkspaceInvalid()
        elif type(item) is float and not math.isfinite(item):
            raise WorkspaceInvalid()
        elif type(item) is int and not -(2**63) <= item < 2**63:
            raise WorkspaceInvalid()

    try:
        walk(value, 0)
        if len(_canonical(value).encode('ascii')) > LIMITS['body_bytes']:
            raise WorkspaceInvalid()
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise WorkspaceInvalid() from None


def _safe_text(value, maximum, empty=False):
    if (type(value) is not str or len(value) > maximum or not empty and not value.strip()
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)):
        raise WorkspaceInvalid()
    _utf8(value)
    decoded = value
    for _ in range(3):
        decoded = html.unescape(unquote(decoded)).replace('\\/', '/')
    if (_URI.search(decoded) or _PATH.search(decoded) or public_data(decoded) != decoded
            or any(secret_name(match['name']) for match in _QUOTED.finditer(decoded))):
        raise WorkspaceInvalid()
    return value


def _literals(value):
    if type(value) is dict:
        for key, child in value.items():
            if secret_name(key) or key in ('credential_refs', 'headers', 'composition', 'endpoint', 'url',
                                           'delivery', 'schedule', 'subscription', 'signing_secret'):
                raise WorkspaceInvalid()
            _literals(child)
    elif type(value) is list:
        for child in value:
            _literals(child)
    elif type(value) is str:
        _safe_text(value, 16000, empty=True)


class WorkspaceAccess:
    def __init__(self, store, key):
        if type(key) is not bytes or len(key) < 32:
            raise WorkspaceInvalid()
        self.store = store
        self.key = hmac.new(key, PROFILE.encode('ascii'), hashlib.sha256).digest()
        from .private_artifact_keys import ArtifactSigner
        self._artifact_signer = ArtifactSigner(self.key, PROFILE)
        with store._lock:
            if store._db.in_transaction:
                raise WorkspaceConflict()
            try:
                store._db.execute('BEGIN IMMEDIATE')
                for statement in SCHEMA:
                    store._db.execute(statement)
                store._db.commit()
            except sqlite3.Error:
                store._db.rollback()
                raise WorkspaceConflict() from None

    def _sign(self, value):
        return self._artifact_signer.sign(value)

    def _verify(self, value, signature):
        return self._artifact_signer.verify(value, signature)

    def _actor(self, actor, write=False, highest=False):
        if (type(actor) is not SessionActor or not _positive(actor.user_id)
                or type(actor.session_ref) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', actor.session_ref)):
            raise WorkspaceDenied()
        now = _now()
        if type(now) not in (float, int) or not math.isfinite(now) or now < 0:
            raise WorkspaceDenied()
        rows = _rows(self.store._db, '''SELECT u.id AS user_id,u.role,s.expires_at,u.password_hash,u.salt FROM admin_sessions s
            JOIN admin_users u ON u.id=s.user_id WHERE s.token=? AND s.user_id=? AND u.active=1 AND s.expires_at>?''',
            (actor.session_ref, actor.user_id, now))
        if (len(rows) != 1 or rows[0]['role'] not in ('superadmin', 'admin', 'operator')
                or type(rows[0]['expires_at']) not in (int, float)
                or not math.isfinite(rows[0]['expires_at'])
                or highest and rows[0]['role'] != 'superadmin'
                or write and rows[0]['role'] == 'operator'):
            raise WorkspaceDenied()
        from .gateway.admin_auth import password_change_required
        if password_change_required(rows[0].pop('password_hash'), rows[0].pop('salt')):
            raise WorkspaceDenied()
        return rows[0]

    @contextmanager
    def _tx(self, actor, write=False, highest=False):
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
            except BaseException as exc:
                try:
                    db.rollback()
                except sqlite3.Error:
                    pass
                if isinstance(exc, (WorkspaceError, KeyboardInterrupt, SystemExit)):
                    raise
                if isinstance(exc, sqlite3.Error):
                    raise WorkspaceConflict() from None
                raise

    def _access(self, ws, actor, write=False, owner=False):
        _identity(ws, 'ws')
        user = self._actor(actor, write)
        rows = _rows(self.store._db, '''SELECT w.*,m.role AS member_role,m.revision AS member_revision
            FROM organization_workspaces w JOIN workspace_memberships m ON m.workspace_id=w.id
            WHERE w.id=? AND w.active=1 AND m.user_id=? AND m.active=1''', (ws, actor.user_id))
        if (len(rows) != 1 or rows[0]['member_role'] not in ROLES
                or owner and rows[0]['member_role'] != 'owner'
                or write and rows[0]['member_role'] == 'viewer'):
            raise WorkspaceDenied()
        return rows[0], user

    @staticmethod
    def _workspace(row, user):
        role = row.get('member_role')
        edit = role in ('owner', 'editor') and user['role'] != 'operator'
        return {key: row[key] for key in ('id', 'name', 'revision')} | {
            'active': bool(row['active']), 'role': role, 'can_edit': edit,
            'can_manage': role == 'owner' and user['role'] != 'operator'}

    def _audit(self, db, actor, ws, action, identity=None, revision=None):
        db.execute('''INSERT INTO workspace_access_audit
            (workspace_id,actor_user_id,action,object_id,revision,created) VALUES(?,?,?,?,?,?)''',
            (ws, actor.user_id, action, identity, revision, _now()))
        from .workspace_admin_events import emit
        emit(self.store, db, action, workspace=ws, object_id=identity)
        # Authorization tombstones are separate and never pruned with display history.
        db.execute('''DELETE FROM workspace_access_audit WHERE id IN
            (SELECT id FROM workspace_access_audit WHERE workspace_id=? ORDER BY id DESC LIMIT 100 OFFSET 5000)''', (ws,))

    def options(self, actor):
        with self._tx(actor) as (_, user):
            return {'profile': PROFILE, 'user': {'user_id': actor.user_id, 'role': user['role']},
                    'can_provision': user['role'] == 'superadmin', 'roles': list(ROLES),
                    'limits': dict(LIMITS), 'private_snapshots_only': True}

    def workspaces(self, actor):
        with self._tx(actor) as (db, user):
            rows = _rows(db, '''SELECT w.*,m.role AS member_role FROM organization_workspaces w
                JOIN workspace_memberships m ON m.workspace_id=w.id WHERE w.active=1 AND m.active=1
                AND m.user_id=? ORDER BY w.created,w.id LIMIT 101''', (actor.user_id,))
            if len(rows) > LIMITS['workspaces']:
                raise WorkspaceConflict()
            return [self._workspace(row, user) for row in rows]

    def provision(self, body, actor):
        _tree(body)
        if type(body) is not dict or set(body) != {'name', 'owner_id'} or not _positive(body['owner_id']):
            raise WorkspaceInvalid()
        name = _safe_text(body['name'], LIMITS['name'])
        with self._tx(actor, write=True, highest=True) as (db, user):
            owner = _rows(db, 'SELECT role FROM admin_users WHERE id=? AND active=1', (body['owner_id'],))
            if len(owner) != 1 or owner[0]['role'] not in ('admin', 'superadmin'):
                raise WorkspaceInvalid()
            if db.execute('SELECT COUNT(*) FROM organization_workspaces').fetchone()[0] >= LIMITS['workspaces']:
                raise WorkspaceConflict()
            identity, now = 'ws_' + secrets.token_hex(16), _now()
            db.execute('INSERT INTO organization_workspaces VALUES(?,?,1,1,?,?,?)',
                       (identity, name, actor.user_id, now, now))
            db.execute('INSERT INTO workspace_memberships VALUES(?,?,?,1,1,?)',
                       (identity, body['owner_id'], 'owner', now))
            self._audit(db, actor, identity, 'workspace.provision', identity, 1)
            return self._workspace({'id': identity, 'name': name, 'active': 1, 'revision': 1,
                                    'member_role': 'owner' if body['owner_id'] == actor.user_id else None}, user)

    def workspace(self, ws, actor):
        with self._tx(actor) as (_, user):
            row, _ = self._access(ws, actor)
            return self._workspace(row, user)

    def members(self, ws, actor):
        with self._tx(actor) as (db, _):
            self._access(ws, actor, owner=True)
            return _rows(db, '''SELECT user_id,role,active,revision FROM workspace_memberships
                WHERE workspace_id=? ORDER BY user_id LIMIT 100''', (ws,))

    def set_member(self, ws, body, actor):
        _tree(body)
        if (type(body) is not dict or set(body) != {'user_id', 'role', 'active', 'revision'}
                or not _positive(body['user_id']) or body['role'] not in ROLES
                or type(body['active']) is not bool or not _revision(body['revision'], zero=True)):
            raise WorkspaceInvalid()
        with self._tx(actor, write=True) as (db, _):
            self._access(ws, actor, write=True, owner=True)
            target = _rows(db, 'SELECT role,active FROM admin_users WHERE id=?', (body['user_id'],))
            if len(target) != 1 or body['active'] and (not target[0]['active']
                    or target[0]['role'] not in ('admin', 'superadmin', 'operator')
                    or body['role'] == 'owner' and target[0]['role'] == 'operator'):
                raise WorkspaceInvalid()
            old = _rows(db, 'SELECT * FROM workspace_memberships WHERE workspace_id=? AND user_id=?', (ws, body['user_id']))
            if (old and old[0]['revision'] != body['revision']) or not old and body['revision'] != 0:
                raise WorkspaceConflict()
            if old and old[0]['active'] and old[0]['role'] == 'owner' and (not body['active'] or body['role'] != 'owner'):
                others = db.execute('''SELECT COUNT(*) FROM workspace_memberships m JOIN admin_users u ON u.id=m.user_id
                    WHERE m.workspace_id=? AND m.active=1 AND m.role='owner' AND m.user_id!=?
                    AND u.active=1 AND u.role IN ('admin','superadmin')''', (ws, body['user_id'])).fetchone()[0]
                if not others:
                    raise WorkspaceConflict()
            if not old and db.execute('SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=?', (ws,)).fetchone()[0] >= LIMITS['members']:
                raise WorkspaceConflict()
            revision, now = body['revision'] + 1, _now()
            db.execute('''INSERT INTO workspace_memberships VALUES(?,?,?,?,?,?) ON CONFLICT(workspace_id,user_id)
                DO UPDATE SET role=excluded.role,active=excluded.active,revision=excluded.revision,updated=excluded.updated''',
                (ws, body['user_id'], body['role'], int(body['active']), revision, now))
            db.execute('UPDATE organization_workspaces SET revision=revision+1,updated=? WHERE id=?', (now, ws))
            self._audit(db, actor, ws, 'member.update', 'user:' + str(body['user_id']), revision)
            return {'user_id': body['user_id'], 'role': body['role'], 'active': body['active'], 'revision': revision}

    def set_active(self, ws, body, actor):
        if type(body) is not dict or set(body) != {'active', 'revision'} or body['active'] is not False or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self._tx(actor, write=True) as (db, _):
            row, _ = self._access(ws, actor, write=True, owner=True)
            if row['revision'] != body['revision']:
                raise WorkspaceConflict()
            db.execute('UPDATE organization_workspaces SET active=0,revision=revision+1,updated=? WHERE id=?', (_now(), ws))
            db.execute('UPDATE workspace_memberships SET active=0,revision=revision+1,updated=? WHERE workspace_id=?', (_now(), ws))
            self._audit(db, actor, ws, 'workspace.archive', ws, body['revision'] + 1)
            return {'id': ws, 'active': False, 'revision': body['revision'] + 1}

    def _definition(self, value, db=None):
        _tree(value)
        if type(value) is not dict or set(value) != {'nodes', 'edges'} or type(value['nodes']) is not list or type(value['edges']) is not list:
            raise WorkspaceInvalid()
        if not value['nodes']:
            if value['edges']:
                raise WorkspaceInvalid()
            return
        if len(value['nodes']) > LIMITS['nodes'] or len(value['edges']) > LIMITS['edges']:
            raise WorkspaceInvalid()
        _literals(value)
        from .workflows import graph, sensitive
        from .concierge.execution_policy import admit_tool
        if sensitive(value):
            raise WorkspaceInvalid()
        triggers = []
        try:
            for node in value['nodes']:
                if (type(node) is not dict or not {'id', 'name', 'type', 'kind', 'data'} <= set(node)
                        or set(node) - {'id', 'name', 'type', 'kind', 'data', 'resource_id', 'position'}
                        or type(node['id']) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', node['id'])):
                    raise WorkspaceInvalid()
                _safe_text(node['name'], 120)
                if 'position' in node:
                    pos = node['position']
                    if type(pos) is not dict or set(pos) != {'x', 'y'} or any(type(n) not in (int, float) or not math.isfinite(n) or abs(n) > 10000 for n in pos.values()):
                        raise WorkspaceInvalid()
                if node['type'] == 'trigger':
                    if node['kind'] != 'trigger' or node['data'] != {} or 'resource_id' in node:
                        raise WorkspaceInvalid()
                    triggers.append(node['id'])
                    continue
                if node['type'] != 'agent' or node['kind'] not in ('mcp', 'a2a', 'x402') or not _positive(node.get('resource_id')):
                    raise WorkspaceInvalid()
                data = node['data']
                if type(data) is not dict:
                    raise WorkspaceInvalid()
                resource = None
                if db is not None:
                    resources = _rows(db, 'SELECT * FROM resources WHERE id=?', (node['resource_id'],))
                    if len(resources) != 1 or not resources[0].get('active') or resources[0].get('kind') != node['kind']:
                        raise WorkspaceInvalid()
                    resource = resources[0]
                if node['kind'] == 'mcp':
                    if set(data) != {'tool', 'input'} or type(data['tool']) is not str or type(data['input']) is not dict:
                        raise WorkspaceInvalid()
                    if resource is not None:
                        admit_tool(resource, data['tool'], data['input'])
                elif node['kind'] == 'a2a':
                    if set(data) != {'message'}:
                        raise WorkspaceInvalid()
                    _safe_text(data['message'], 2000)
                elif data != {'action': 'probe'}:
                    raise WorkspaceInvalid()
            if len(triggers) != 1 or any(type(e) is not dict or set(e) != {'source', 'target'} for e in value['edges']):
                raise WorkspaceInvalid()
            by_id, incoming, order = graph(value)
            if order[0] != triggers[0] or any(not incoming[nid] for nid in by_id if nid != triggers[0]):
                raise WorkspaceInvalid()
        except (ValueError, TypeError, KeyError, OverflowError):
            raise WorkspaceInvalid() from None

    @staticmethod
    def _draft_payload(row):
        return {key: row[key] for key in ('id', 'workspace_id', 'name', 'description', 'definition',
                                         'revision', 'active', 'created_by', 'created', 'updated')}

    def _open_draft(self, row):
        try:
            value = {**row, 'definition': json.loads(row['definition'])}
            payload = self._draft_payload(value)
            if row['payload_hash'] != _hash(payload) or not self._verify(payload, row['signature']):
                raise WorkspaceConflict()
            self._definition(value['definition'])
            return {key: value[key] for key in ('id', 'workspace_id', 'name', 'description', 'definition', 'revision', 'created', 'updated')} | {'active': bool(row['active'])}
        except (ValueError, TypeError, KeyError):
            raise WorkspaceConflict() from None

    def _draft_row(self, ws, identity, active=True):
        _identity(identity, 'wd')
        rows = _rows(self.store._db, 'SELECT * FROM workspace_drafts WHERE workspace_id=? AND id=?', (ws, identity))
        if len(rows) != 1 or active and not rows[0]['active']:
            raise WorkspaceDenied()
        return rows[0]

    def drafts(self, ws, actor):
        with self._tx(actor) as (db, _):
            self._access(ws, actor)
            rows = _rows(db, 'SELECT * FROM workspace_drafts WHERE workspace_id=? AND active=1 ORDER BY created,id LIMIT 101', (ws,))
            if len(rows) > LIMITS['drafts']:
                raise WorkspaceConflict()
            return [self._open_draft(row) for row in rows]

    def save_draft(self, ws, body, actor):
        with self._tx(actor, write=True) as (db, _):
            return self._save_draft_in_transaction(db, ws, body, actor)

    def _save_draft_in_transaction(self, db, ws, body, actor):
        if db is not self.store._db or not db.in_transaction:
            raise WorkspaceConflict()
        _tree(body)
        fields = {'name', 'description', 'definition'}
        if type(body) is not dict or set(body) not in (fields, fields | {'id', 'revision'}):
            raise WorkspaceInvalid()
        _safe_text(body['name'], LIMITS['name'])
        _safe_text(body['description'], LIMITS['description'], empty=True)
        self._access(ws, actor, write=True)
        self._definition(body['definition'], db)
        now = _now()
        if 'id' in body:
            old = self._draft_row(ws, body['id'])
            self._open_draft(old)
            if not _revision(body['revision']) or old['revision'] != body['revision']:
                raise WorkspaceConflict()
            identity, revision, created_by, created = old['id'], old['revision'] + 1, old['created_by'], old['created']
        else:
            if db.execute('SELECT COUNT(*) FROM workspace_drafts WHERE workspace_id=?', (ws,)).fetchone()[0] >= LIMITS['drafts']:
                raise WorkspaceConflict()
            identity, revision, created_by, created = 'wd_' + secrets.token_hex(16), 1, actor.user_id, now
        value = {'id': identity, 'workspace_id': ws, 'name': body['name'], 'description': body['description'],
                 'definition': body['definition'], 'revision': revision, 'active': 1,
                 'created_by': created_by, 'created': created, 'updated': now}
        payload = self._draft_payload(value)
        if 'id' in body:
            changed = db.execute('''UPDATE workspace_drafts SET name=?,description=?,definition=?,revision=?,
                updated=?,payload_hash=?,signature=? WHERE workspace_id=? AND id=? AND revision=? AND active=1''',
                (value['name'], value['description'], _canonical(value['definition']), revision,
                 now, _hash(payload), self._sign(payload), ws, identity, body['revision'])).rowcount
            if changed != 1:
                raise WorkspaceConflict()
        else:
            db.execute('INSERT INTO workspace_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity, ws, value['name'], value['description'], _canonical(value['definition']), revision, 1,
                 created_by, created, now, _hash(payload), self._sign(payload)))
        self._audit(db, actor, ws, 'draft.save', identity, revision)
        return self._open_draft(self._draft_row(ws, identity))

    def draft(self, ws, identity, actor):
        with self._tx(actor):
            self._access(ws, actor)
            return self._open_draft(self._draft_row(ws, identity))

    def revoke_draft(self, ws, identity, body, actor):
        if type(body) is not dict or set(body) != {'revision'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self._tx(actor, write=True) as (db, _):
            self._access(ws, actor, write=True, owner=True)
            row = self._draft_row(ws, identity)
            self._open_draft(row)
            if row['revision'] != body['revision']:
                raise WorkspaceConflict()
            payload = self._draft_payload({**row, 'definition': json.loads(row['definition']),
                                           'active': 0, 'revision': row['revision'] + 1, 'updated': _now()})
            db.execute('UPDATE workspace_drafts SET active=0,revision=?,updated=?,payload_hash=?,signature=? WHERE id=? AND workspace_id=?',
                       (payload['revision'], payload['updated'], _hash(payload), self._sign(payload), identity, ws))
            self._audit(db, actor, ws, 'draft.archive', identity, payload['revision'])
            return {'id': identity, 'active': False, 'revision': payload['revision']}

    @staticmethod
    def _version_state(row):
        return {key: row[key] for key in ('id', 'workspace_id', 'draft_id', 'revision', 'active', 'revoked', 'payload_hash')}

    def _open_version(self, row):
        try:
            payload = json.loads(row['payload'])
            if (set(payload) != {'profile', 'workspace_id', 'draft_id', 'id', 'ordinal', 'draft_revision', 'created_by', 'created', 'snapshot'}
                    or payload['profile'] != PROFILE or any(payload[k] != row[k] for k in ('workspace_id', 'draft_id', 'id', 'ordinal', 'draft_revision', 'created_by', 'created'))
                    or row['payload_hash'] != _hash(payload) or not self._verify(payload, row['signature'])
                    or not self._verify(self._version_state(row), row['state_signature'])):
                raise WorkspaceConflict()
            self._definition(payload['snapshot']['definition'])
            return {key: row[key] for key in ('id', 'workspace_id', 'draft_id', 'revision', 'ordinal', 'draft_revision', 'created')} | {
                'active': bool(row['active']), 'definition_hash': _hash(payload['snapshot']['definition']),
                'snapshot': payload['snapshot'], 'saved_snapshot': True, 'executable': False, 'deployable': False, 'published': False}
        except (ValueError, TypeError, KeyError):
            raise WorkspaceConflict() from None

    def _version_row(self, ws, identity, version):
        _identity(version, 'wv')
        rows = _rows(self.store._db, 'SELECT * FROM workspace_versions WHERE workspace_id=? AND draft_id=? AND id=?', (ws, identity, version))
        if len(rows) != 1:
            raise WorkspaceDenied()
        return rows[0]

    def create_snapshot(self, ws, identity, body, actor):
        with self._tx(actor, write=True) as (db, _):
            return self._create_snapshot_in_transaction(db, ws, identity, body, actor)

    def _create_snapshot_in_transaction(self, db, ws, identity, body, actor):
        if db is not self.store._db or not db.in_transaction:
            raise WorkspaceConflict()
        if type(body) is not dict or set(body) != {'draft_revision'} or not _revision(body['draft_revision']):
            raise WorkspaceInvalid()
        self._access(ws, actor, write=True)
        row = self._draft_row(ws, identity)
        draft = self._open_draft(row)
        if row['revision'] != body['draft_revision']:
            raise WorkspaceConflict()
        count = db.execute('SELECT COUNT(*) FROM workspace_versions WHERE workspace_id=? AND draft_id=?', (ws, identity)).fetchone()[0]
        if count >= LIMITS['versions']:
            raise WorkspaceConflict()
        vid, now = 'wv_' + secrets.token_hex(16), _now()
        payload = {'profile': PROFILE, 'workspace_id': ws, 'draft_id': identity, 'id': vid,
                   'ordinal': count + 1, 'draft_revision': row['revision'], 'created_by': actor.user_id,
                   'created': now, 'snapshot': {key: draft[key] for key in ('name', 'description', 'definition')}}
        state = {'id': vid, 'workspace_id': ws, 'draft_id': identity, 'revision': 1,
                 'active': 1, 'revoked': None, 'payload_hash': _hash(payload)}
        db.execute('INSERT INTO workspace_versions VALUES(?,?,?,?,?,1,1,?,?,NULL,?,?,?,?)',
                   (vid, ws, identity, count + 1, row['revision'], actor.user_id, now,
                    _canonical(payload), state['payload_hash'], self._sign(payload), self._sign(state)))
        self._audit(db, actor, ws, 'snapshot.create', vid, 1)
        return self._open_version(self._version_row(ws, identity, vid))

    def versions(self, ws, identity, actor):
        with self._tx(actor) as (db, _):
            self._access(ws, actor)
            self._open_draft(self._draft_row(ws, identity, active=False))
            rows = _rows(db, 'SELECT * FROM workspace_versions WHERE workspace_id=? AND draft_id=? ORDER BY ordinal LIMIT 51', (ws, identity))
            if len(rows) > LIMITS['versions']:
                raise WorkspaceConflict()
            # Revoked content cannot be recovered through the history route.
            # Active payloads also require their individually scoped read.
            return [{key: value for key, value in self._open_version(row).items() if key != 'snapshot'} for row in rows]

    def version(self, ws, identity, version, actor):
        with self._tx(actor):
            self._access(ws, actor)
            self._open_draft(self._draft_row(ws, identity))
            row = self._version_row(ws, identity, version)
            result = self._open_version(row)
            if not row['active']:
                raise WorkspaceDenied()
            return result

    def revoke_version(self, ws, identity, version, body, actor):
        if type(body) is not dict or set(body) != {'revision'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self._tx(actor, write=True) as (db, _):
            self._access(ws, actor, write=True, owner=True)
            self._open_draft(self._draft_row(ws, identity, active=False))
            row = self._version_row(ws, identity, version)
            self._open_version(row)
            if not row['active'] or row['revision'] != body['revision']:
                raise WorkspaceConflict()
            state = self._version_state({**row, 'active': 0, 'revision': row['revision'] + 1, 'revoked': _now()})
            db.execute('UPDATE workspace_versions SET active=0,revision=?,revoked=?,state_signature=? WHERE workspace_id=? AND draft_id=? AND id=?',
                       (state['revision'], state['revoked'], self._sign(state), ws, identity, version))
            self._audit(db, actor, ws, 'snapshot.revoke', version, state['revision'])
            return {'id': version, 'active': False, 'revision': state['revision']}

    def audit(self, ws, actor):
        with self._tx(actor) as (db, _):
            self._access(ws, actor, owner=True)
            return _rows(db, '''SELECT id,actor_user_id,action,object_id,revision,created
                FROM workspace_access_audit WHERE workspace_id=? ORDER BY id DESC LIMIT 100''', (ws,))

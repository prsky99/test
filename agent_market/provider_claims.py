"""Purpose-bound HTTPS endpoint-control challenges, independent of quality."""
import hashlib
import hmac
import json
import secrets
from urllib.parse import urlsplit

from .customer_identity import _object, _time
from .private_artifact_keys import ArtifactSigner
from .workspace_access import (WorkspaceAccess, WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid,
                               _canonical, _hash, _identity, _revision, _rows)

PROFILE = 'provider-https-control-v1'
NOTICE = 'provider-https-control-v1'
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS provider_control_claims(
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,resource_id INTEGER NOT NULL,
       revision INTEGER NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,
       verified REAL,valid_until REAL,revoked REAL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS provider_claim_scope ON provider_control_claims(workspace_id,resource_id,created)',
    '''CREATE TABLE IF NOT EXISTS provider_claim_transfers(id TEXT PRIMARY KEY,source_workspace_id TEXT NOT NULL,
       target_workspace_id TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,expires REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE TABLE IF NOT EXISTS provider_claim_transfer_restore_blocks(id TEXT PRIMARY KEY)',
)


class ProviderClaims:
    def __init__(self, store, key, http=None):
        self.store, self.http, self.access = store, http, WorkspaceAccess(store, key)
        self.key = hmac.new(key, PROFILE.encode(), hashlib.sha256).digest()
        self.signer = ArtifactSigner(self.key, PROFILE)
        with store._lock:
            if store._db.in_transaction:
                raise WorkspaceConflict()
            try:
                store._db.execute('BEGIN IMMEDIATE')
                for statement in SCHEMA:
                    store._db.execute(statement)
                store._db.commit()
            except Exception:
                store._db.rollback()
                raise WorkspaceConflict() from None

    def _sign(self, payload):
        return self.signer.sign(payload)

    def _resource(self, db, identity):
        from .capability_registry import version_parts
        from .concierge.recommendation_security import usable_endpoint
        if type(identity) is not int or not 0 < identity < 2**31:
            raise WorkspaceInvalid()
        rows = _rows(db, 'SELECT * FROM resources WHERE id=? AND active=1', (identity,))
        if len(rows) != 1:
            raise WorkspaceDenied()
        resource = rows[0]
        if not usable_endpoint(resource.get('url')) or urlsplit(resource['url']).scheme != 'https':
            raise WorkspaceDenied()
        generations = _rows(db, 'SELECT generation FROM resource_observation_generations WHERE resource_id=?', (identity,))
        if len(generations) != 1 or not _revision(generations[0]['generation']):
            raise WorkspaceDenied()
        parsed = urlsplit(resource['url'])
        origin = 'https://' + parsed.netloc.lower()
        return {'resource_id': identity, 'binding_hash': _hash(version_parts(resource)),
                'generation': generations[0]['generation'], 'origin': origin,
                'challenge_url': origin + '/.well-known/agent-concierge-claim.json'}

    def _authority(self, db, ws, actor):
        membership, user = self.access._access(ws, actor, write=True, owner=True)
        return {'workspace_id': ws, 'actor_user_id': actor.user_id, 'session_ref': actor.session_ref,
                'workspace_revision': membership['revision'], 'member_revision': membership['member_revision'],
                'user_role': user['role']}

    def _open(self, row):
        payload = _object(row['payload'])
        if (payload.get('profile') != PROFILE or not self.signer.verify(payload, row['signature'])
                or any(payload.get(key) != row[key] for key in ('id', 'workspace_id', 'resource_id', 'revision',
                         'status', 'created', 'expires', 'verified', 'valid_until'))):
            raise WorkspaceConflict()
        return payload

    @staticmethod
    def _dto(row):
        return {key: row[key] for key in ('id', 'resource_id', 'revision', 'status', 'created', 'expires', 'verified', 'valid_until')} | {
            'revoked': row['revoked'], 'endpoint_control_only': True, 'quality_certified': False}

    def options(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.access._access(ws, actor, owner=True)
            return {'profile': PROFILE, 'notice': NOTICE, 'challenge_seconds': 600, 'verified_seconds': 30 * 86400,
                    'path': '/.well-known/agent-concierge-claim.json', 'endpoint_control_only': True,
                    'quality_or_execution_approval': False}

    def claims(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.access._access(ws, actor, owner=True)
            rows = _rows(db, 'SELECT * FROM provider_control_claims WHERE workspace_id=? ORDER BY created DESC,id LIMIT 100', (ws,))
            for row in rows:
                self._open(row)
            return [self._dto(row) for row in rows]

    def prepare(self, ws, body, actor):
        if type(body) is not dict or set(body) != {'resource_id'}:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            return self._prepare(db, ws, body['resource_id'], actor)

    def _prepare(self, db, ws, resource_id, actor, *, predecessor=None):
        now, nonce, identity = _time(), secrets.token_urlsafe(32), 'pc_' + secrets.token_hex(16)
        authority = self._authority(db, ws, actor)
        resource = self._resource(db, resource_id)
        if db.execute('SELECT COUNT(*) FROM provider_control_claims WHERE workspace_id=?', (ws,)).fetchone()[0] >= 1000:
            raise WorkspaceConflict()
        payload = {'profile': PROFILE, 'id': identity, **authority, **resource, 'revision': 1, 'status': 'pending',
                   'created': now, 'expires': now + 600, 'verified': None, 'valid_until': None,
                   'nonce_hash': hashlib.sha256(nonce.encode('ascii')).hexdigest()}
        if predecessor:
            payload['predecessor'] = predecessor
        db.execute('INSERT INTO provider_control_claims VALUES(?,?,?,1,?,?,?,?,NULL,NULL,?,?)',
            (identity, ws, resource['resource_id'], 'pending', now, now + 600, None, _canonical(payload), self._sign(payload)))
        self.access._audit(db, actor, ws, 'provider.prepare', identity, 1)
        return {'claim': {'id': identity, 'revision': 1, 'expires': now + 600,
                          'challenge_url': resource['challenge_url']},
                'challenge': {'profile': PROFILE, 'claim_id': identity, 'nonce': nonce}, 'notice': NOTICE}

    def rechallenge(self, ws, identity, body, actor):
        """Retire the previous proof atomically; a new nonce must be hosted again."""
        if type(body) is not dict or set(body) != {'revision'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._authority(db, ws, actor)
            row, payload = self._row(db, ws, identity)
            if row['revision'] != body['revision']:
                raise WorkspaceConflict()
            if row['revoked'] is None:
                payload.update(status='superseded', revision=row['revision'] + 1)
                self._write(db, payload, _time())
            value = self._prepare(db, ws, row['resource_id'], actor, predecessor=identity)
            self.access._audit(db, actor, ws, 'provider.rechallenge', identity, payload['revision'])
            return value

    def transfer(self, ws, identity, body, actor):
        """Retire a current proof and offer only a fresh challenge to another owner."""
        if type(body) is not dict or set(body) != {'revision', 'target_workspace_id'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        target = _identity(body['target_workspace_id'], 'ws')
        if target == ws:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._authority(db, ws, actor)
            row, payload = self._row(db, ws, identity)
            current = self.current(db, ws, row['resource_id'])
            targets = _rows(db, 'SELECT revision FROM organization_workspaces WHERE id=? AND active=1', (target,))
            if len(targets) != 1 or current['id'] != identity or row['revision'] != body['revision']:
                raise WorkspaceConflict()
            value = {'profile': 'provider-transfer-v1', 'id': 'pt_' + secrets.token_hex(16),
                     'source_workspace_id': ws, 'target_workspace_id': target, 'resource_id': row['resource_id'],
                     'target_revision': targets[0]['revision'], 'predecessor': identity,
                     'binding': self._resource(db, row['resource_id']), 'revision': 1, 'status': 'pending',
                     'expires': _time() + 600}
            payload.update(status='transferred', revision=row['revision'] + 1)
            self._write(db, payload, _time())
            db.execute('INSERT INTO provider_claim_transfers VALUES(?,?,?,1,?,?,?,?)',
                       (value['id'], ws, target, value['status'], value['expires'], _canonical(value), self._sign(value)))
            self.access._audit(db, actor, ws, 'provider.transfer_offer', identity, payload['revision'])
            return {'transfer_id': value['id'], 'revision': 1, 'expires': value['expires'], 'fresh_challenge_required': True}

    def accept_transfer(self, ws, identity, body, actor):
        if type(body) is not dict or set(body) != {'revision'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        _identity(identity, 'pt')
        with self.access._tx(actor, write=True) as (db, _):
            authority = self._authority(db, ws, actor)
            rows = _rows(db, 'SELECT * FROM provider_claim_transfers WHERE id=? AND target_workspace_id=?', (identity, ws))
            if len(rows) != 1:
                raise WorkspaceDenied()
            if db.execute('SELECT 1 FROM provider_claim_transfer_restore_blocks WHERE id=?', (identity,)).fetchone():
                raise WorkspaceDenied()
            row = rows[0]
            value = _object(row['payload'])
            if (not self.signer.verify(value, row['signature']) or value.get('profile') != 'provider-transfer-v1'
                    or any(value.get(key) != row[key] for key in ('id', 'source_workspace_id', 'target_workspace_id', 'revision', 'status', 'expires'))
                    or row['revision'] != body['revision'] or row['status'] != 'pending' or row['expires'] <= _time()
                    or value['target_revision'] != authority['workspace_revision']
                    or value['binding'] != self._resource(db, value['resource_id'])):
                raise WorkspaceDenied()
            result = self._prepare(db, ws, value['resource_id'], actor, predecessor=value['predecessor'])
            value.update(status='consumed', revision=row['revision'] + 1)
            changed = db.execute("UPDATE provider_claim_transfers SET status='consumed',revision=?,payload=?,signature=? WHERE id=? AND revision=? AND status='pending'",
                                 (value['revision'], _canonical(value), self._sign(value), identity, row['revision'])).rowcount
            if changed != 1:
                raise WorkspaceConflict()
            self.access._audit(db, actor, ws, 'provider.transfer_accept', identity, value['revision'])
            return result

    def expire(self, ws, body, actor):
        if type(body) is not dict or set(body) != {'limit'} or type(body['limit']) is not int or not 1 <= body['limit'] <= 50:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._authority(db, ws, actor)
            rows = _rows(db, "SELECT * FROM provider_control_claims WHERE workspace_id=? AND revoked IS NULL AND ((status IN ('pending','checking') AND expires<=?) OR (status='verified' AND valid_until<=?)) ORDER BY created LIMIT ?", (ws, _time(), _time(), body['limit']))
            for row in rows:
                value = self._open(row)
                value.update(status='expired', revision=row['revision'] + 1)
                self._write(db, value, _time())
                self.access._audit(db, actor, ws, 'provider.expire', row['id'], value['revision'])
            return {'expired': len(rows), 'automatic_calls': 0, 'quality_certified': False}

    def _row(self, db, ws, identity):
        _identity(identity, 'pc')
        rows = _rows(db, 'SELECT * FROM provider_control_claims WHERE workspace_id=? AND id=?', (ws, identity))
        if len(rows) != 1:
            raise WorkspaceDenied()
        return rows[0], self._open(rows[0])

    def _write(self, db, payload, revoked=None):
        db.execute('''UPDATE provider_control_claims SET revision=?,status=?,verified=?,valid_until=?,revoked=?,payload=?,signature=? WHERE id=?''',
                   (payload['revision'], payload['status'], payload['verified'], payload['valid_until'], revoked,
                    _canonical(payload), self._sign(payload), payload['id']))

    def verify(self, ws, body, actor):
        if (type(body) is not dict or set(body) != {'claim_id', 'revision', 'authorized', 'notice'}
                or body['authorized'] is not True or body['notice'] != NOTICE or not _revision(body['revision'])):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            authority = self._authority(db, ws, actor)
            row, payload = self._row(db, ws, body['claim_id'])
            current = self._resource(db, row['resource_id'])
            if (row['revision'] != body['revision'] or row['status'] != 'pending' or row['revoked'] is not None
                    or row['expires'] <= _time() or any(payload.get(key) != value for key, value in (authority | current).items())):
                raise WorkspaceDenied()
            payload.update(status='checking', revision=row['revision'] + 1)
            self._write(db, payload)
        # At most one explicit GET per challenge. Failure requires a new nonce.
        valid = False
        try:
            from .concierge.http_security import bounded_client, outbound_operation
            with outbound_operation(8):
                client = bounded_client(self.http, limit=4096, timeout=8)
                try:
                    response = client.get(payload['challenge_url'])
                    proof = _object(response.content)
                    valid = (response.status_code == 200 and set(proof) == {'profile', 'claim_id', 'nonce'}
                        and proof['profile'] == PROFILE and proof['claim_id'] == payload['id']
                        and type(proof['nonce']) is str and len(proof['nonce']) == 43
                        and hmac.compare_digest(hashlib.sha256(proof['nonce'].encode('ascii')).hexdigest(), payload['nonce_hash']))
                finally:
                    client.close()
        except Exception:
            valid = False
        with self.access._tx(actor, write=True) as (db, _):
            authority = self._authority(db, ws, actor)
            row, payload = self._row(db, ws, body['claim_id'])
            current = self._resource(db, row['resource_id'])
            if (row['revision'] != body['revision'] + 1 or row['status'] != 'checking' or row['revoked'] is not None
                    or row['expires'] <= _time() or any(payload.get(key) != value for key, value in (authority | current).items())):
                raise WorkspaceDenied()
            now = _time()
            payload.update(status='verified' if valid else 'failed', revision=row['revision'] + 1,
                           verified=now if valid else None, valid_until=now + 30 * 86400 if valid else None)
            self._write(db, payload)
            self.access._audit(db, actor, ws, 'provider.verify' if valid else 'provider.failed', payload['id'], payload['revision'])
            return self._dto(_rows(db, 'SELECT * FROM provider_control_claims WHERE id=?', (payload['id'],))[0])

    def revoke(self, ws, identity, body, actor):
        if type(body) is not dict or set(body) != {'revision'} or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._authority(db, ws, actor)
            row, payload = self._row(db, ws, identity)
            if row['revision'] != body['revision'] or row['revoked'] is not None:
                raise WorkspaceConflict()
            payload.update(status='revoked', revision=row['revision'] + 1)
            self._write(db, payload, _time())
            self.access._audit(db, actor, ws, 'provider.revoke', identity, payload['revision'])
            return {'id': identity, 'revision': payload['revision'], 'status': 'revoked'}

    def current(self, db, ws, resource_id):
        """Internal caller-owned transaction check, never an execution approval."""
        if db is not self.store._db or not db.in_transaction:
            raise WorkspaceDenied()
        workspace = _rows(db, 'SELECT revision FROM organization_workspaces WHERE id=? AND active=1', (ws,))
        if len(workspace) != 1:
            raise WorkspaceDenied()
        current = self._resource(db, resource_id)
        rows = _rows(db, '''SELECT * FROM provider_control_claims WHERE workspace_id=? AND resource_id=?
            AND status='verified' AND revoked IS NULL AND valid_until>? ORDER BY verified DESC LIMIT 100''', (ws, resource_id, _time()))
        for row in rows:
            payload = self._open(row)
            if (payload.get('workspace_revision') == workspace[0]['revision']
                    and all(payload.get(key) == value for key, value in current.items())):
                return self._dto(row)
        raise WorkspaceDenied()

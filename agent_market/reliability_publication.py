"""Concrete, revocable local authority for a separately mounted trust app.

Signing keys are injected by the host and never serialized into this registry.
An explicit named owner approves each fixed projection and each public key.
"""
import hashlib

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .capability_registry import digest
from .reliability_evaluation import bounded_int, finite, revision_authority
from .reliability_portable_receipt import SigningConfig, ReceiptInvalid, _canonical as receipt_json, _projection
from .reliability_public_receipt import DisclosureApproval, KeyPublicationApproval, create_trust_app
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _identity, _rows

PROFILE = 'explicit-local-trust-publication-v1'
NOTICE = 'publish-fixed-evidence-metadata-v1'
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS reliability_publication_grants (
       public_ref TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_publication_keys (
       issuer TEXT NOT NULL,key_id TEXT NOT NULL,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,
       signature TEXT NOT NULL,PRIMARY KEY(issuer,key_id))''',
)


class ReliabilityPublication(SignedWorkspaceModule):
    def __init__(self, access, trust, *, configs=(), enabled=False):
        if (trust.access is not access or type(enabled) is not bool or type(configs) is not tuple
                or len(configs) > 5 or any(type(c) is not SigningConfig for c in configs)
                or len({(c.issuer, c.key_id) for c in configs}) != len(configs)):
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.trust, self.configs, self.enabled = trust, configs, enabled

    @staticmethod
    def _authorize(body, fields):
        exact(body, (*fields, 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        bounded_int(body['revision'], 0, 2**31-1)

    @staticmethod
    def _expires(value):
        if not finite(value) or not clock() < value <= clock()+3600:
            raise WorkspaceInvalid()

    def _config(self, issuer, key_id):
        if not self.enabled:
            raise WorkspaceDenied()
        for config in self.configs:
            if config.issuer == issuer and config.key_id == key_id:
                return config
        raise WorkspaceDenied()

    def _read_grant(self, db, ref):
        rows = _rows(db, 'SELECT * FROM reliability_publication_grants WHERE public_ref=?', (ref,))
        if not rows:
            return None
        value = self.opened(rows[0])
        if value.get('public_ref') != ref or value.get('workspace_id') != rows[0]['workspace_id']:
            raise WorkspaceConflict()
        return value

    def _read_key(self, db, issuer, key_id):
        rows = _rows(db, 'SELECT * FROM reliability_publication_keys WHERE issuer=? AND key_id=?', (issuer, key_id))
        if not rows:
            return None
        value = self.opened(rows[0])
        if any(value.get(k) != rows[0][k] for k in ('issuer', 'key_id', 'workspace_id')):
            raise WorkspaceConflict()
        return value

    @staticmethod
    def _actor(value):
        return SessionActor(value['actor_user_id'], value['session_ref'])

    def _authority(self, db, value, actor):
        member, user = self.scope(value['workspace_id'], actor, write=True, owner=True)
        if (not self.enabled or value['expires'] <= clock()
                or any(value.get(k) != v for k, v in revision_authority(member, user, actor).items())):
            raise WorkspaceDenied()

    def publish_key(self, ws, body, actor):
        self._authorize(body, ('revision', 'issuer', 'key_id', 'revoked', 'expires'))
        if type(body['revoked']) is not bool:
            raise WorkspaceInvalid()
        self._expires(body['expires'])
        config = self._config(body['issuer'], body['key_id'])
        raw = config.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            old = self._read_key(db, config.issuer, config.key_id)
            if body['revision'] != (old['revision'] if old else 0) or old and old['workspace_id'] != ws:
                raise WorkspaceConflict()
            # A revoked key ID is a permanent tombstone; rotation needs a new ID.
            if old and old['revoked'] and not body['revoked']:
                raise WorkspaceConflict()
            value = {k: body[k] for k in ('issuer', 'key_id', 'revoked', 'expires')} | {
                'workspace_id': ws, 'revision': body['revision']+1, 'public_key_sha256': hashlib.sha256(raw).hexdigest(),
                **revision_authority(member, user, actor)}
            db.execute('''INSERT INTO reliability_publication_keys VALUES(?,?,?,?,?) ON CONFLICT(issuer,key_id)
                DO UPDATE SET payload=excluded.payload,signature=excluded.signature''',
                (config.issuer, config.key_id, ws, _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'reliability.publication.key', config.key_id, value['revision'])
            return {k: value[k] for k in ('key_id', 'revision', 'revoked', 'expires')}

    def _project(self, ws, rid, ref, actor):
        value, _ = self.trust.projection(ws, rid, actor)
        if value['state'] != 'last_verified':
            raise WorkspaceConflict()
        return _projection({'subject_ref': ref, 'contract_id': value['contract_id'],
            'version_digest': digest([value['agent_version'], value['schema_hash']]),
            'evidence_digest': digest([value['source_revision'], value['contract_revision'], value['logical_samples']]),
            'verdict': 'qualified', 'observed_at': int(value['last_verified_at']),
            'expires_at': int(value['expires_at'])}, clock())

    def disclose(self, ws, body, actor):
        self._authorize(body, ('revision', 'resource_id', 'public_ref', 'audiences', 'expires', 'withdrawn'))
        _identity(body['public_ref'], 'public'); bounded_int(body['resource_id'], 1, 2**31-1)
        self._expires(body['expires'])
        audiences = body['audiences']
        if (type(body['withdrawn']) is not bool or type(audiences) is not list or not 1 <= len(audiences) <= 20
                or any(type(a) is not str for a in audiences) or len(set(audiences)) != len(audiences)
                or not self.enabled or not all(any(a in c.audiences for c in self.configs) for a in audiences)):
            raise WorkspaceInvalid()
        projection = None if body['withdrawn'] else self._project(ws, body['resource_id'], body['public_ref'], actor)
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            old = self._read_grant(db, body['public_ref'])
            if body['revision'] != (old['revision'] if old else 0) or old and old['workspace_id'] != ws:
                raise WorkspaceConflict()
            if old and (old['resource_id'] != body['resource_id'] or old['withdrawn'] and not body['withdrawn']):
                raise WorkspaceConflict()
            if db.execute('SELECT COUNT(*) FROM reliability_publication_grants WHERE workspace_id=?', (ws,)).fetchone()[0] >= 100 and old is None:
                raise WorkspaceConflict()
            value = {k: body[k] for k in ('resource_id', 'public_ref', 'audiences', 'expires', 'withdrawn')} | {
                'workspace_id': ws, 'revision': body['revision']+1,
                'projection_sha256': hashlib.sha256(receipt_json(projection)).hexdigest() if projection else None,
                **revision_authority(member, user, actor)}
            db.execute('''INSERT INTO reliability_publication_grants VALUES(?,?,?,?) ON CONFLICT(public_ref)
                DO UPDATE SET payload=excluded.payload,signature=excluded.signature''',
                (value['public_ref'], ws, _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'reliability.publication.disclose', value['public_ref'], value['revision'])
            return {k: value[k] for k in ('public_ref', 'revision', 'withdrawn', 'expires')}

    def projection_source(self, ref):
        # A public request can only recover the explicitly recorded approving
        # principal; it never creates authority or accepts a caller principal.
        with self.store._lock:
            value = self._read_grant(self.store._db, ref)
        if value is None or value['withdrawn']:
            raise WorkspaceDenied()
        actor = self._actor(value)
        with self.access._tx(actor) as (db, _):
            self._authority(db, value, actor)
            if self._read_grant(db, ref) != value:
                raise WorkspaceConflict()
        projection = self._project(value['workspace_id'], value['resource_id'], ref, actor)
        if hashlib.sha256(receipt_json(projection)).hexdigest() != value['projection_sha256']:
            raise WorkspaceConflict()
        return projection

    def disclosure_authorizer(self, ref, audience, projection_hash):
        with self.store._lock:
            value = self._read_grant(self.store._db, ref)
        if value is None:
            raise WorkspaceDenied()
        actor = self._actor(value)
        with self.access._tx(actor) as (db, _):
            self._authority(db, value, actor)
            if (self._read_grant(db, ref) != value or value['withdrawn'] or audience not in value['audiences']
                    or projection_hash != value['projection_sha256']):
                raise WorkspaceDenied()
            return DisclosureApproval(ref, audience, projection_hash, int(min(clock()//60*60+240, value['expires'])),
                                      value['workspace_revision'], value['revision'], value['revision'], True)

    def key_status_source(self, issuer, key_id, public_hash):
        self._config(issuer, key_id)
        with self.store._lock:
            value = self._read_key(self.store._db, issuer, key_id)
        if value is None:
            raise WorkspaceDenied()
        actor = self._actor(value)
        with self.access._tx(actor) as (db, _):
            self._authority(db, value, actor)
            if self._read_key(db, issuer, key_id) != value or value['public_key_sha256'] != public_hash:
                raise WorkspaceDenied()
            return KeyPublicationApproval(issuer, key_id, public_hash, int(min(clock()//60*60+240, value['expires'])),
                                          value['revision'], value['revoked'])

    def create_app(self, issuer, key_id, *, allowed_hosts):
        return create_trust_app(self._config(issuer, key_id), projection_source=self.projection_source,
            disclosure_authorizer=self.disclosure_authorizer, key_status_source=self.key_status_source,
            allowed_hosts=allowed_hosts)

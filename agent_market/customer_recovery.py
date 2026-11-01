"""Pre-enrolled, dual-signature sole-owner recovery with a dispute window.

The recovery key is held offline by the customer. A separate configured review
authority must sign the same exact claim. Neither staff identity nor email is a
recovery proof. No key is generated, discovered or exported by this module.
"""
from dataclasses import dataclass
import hashlib
import re
import secrets

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .customer_identity import _b64, _decode, _time
from .shadow_ledger import exact
from .workspace_access import (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid,
                               _canonical, _identity, _rows, _revision)

PROFILE = 'customer-sole-owner-recovery-v1'
NOTICE = 'customer-recovery-enroll-v1'
WAIT_SECONDS = 86400
CLAIM_SECONDS = 7 * 86400
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS customer_recovery_policies (
       workspace_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS customer_recovery_requests (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,target_id TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE TABLE IF NOT EXISTS customer_recovery_blocks(id TEXT PRIMARY KEY)',
    'CREATE INDEX IF NOT EXISTS customer_recovery_pending ON customer_recovery_requests(workspace_id,status)',
)


def _public(value):
    try:
        raw = _decode(value, 64)
        if len(raw) != 32:
            raise ValueError()
        return Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, WorkspaceDenied):
        raise WorkspaceInvalid() from None


def _verify(key, value, signature):
    try:
        key.verify(_decode(signature, 128), _canonical(value).encode())
    except (ValueError, InvalidSignature, WorkspaceDenied):
        raise WorkspaceDenied() from None


@dataclass(frozen=True)
class RecoveryAuthority:
    id: str
    public_key: str

    def __post_init__(self):
        if type(self.id) is not str or not re.fullmatch('[a-z][a-z0-9_-]{2,63}', self.id):
            raise WorkspaceInvalid()
        _public(self.public_key)


class CustomerRecovery:
    def __init__(self, organizations, authorities=()):
        if (type(authorities) is not tuple or len(authorities) > 10
                or any(type(authority) is not RecoveryAuthority for authority in authorities)
                or len({authority.id for authority in authorities}) != len(authorities)):
            raise WorkspaceInvalid()
        self.organizations = organizations
        self.identity, self.store = organizations.identity, organizations.store
        self.authorities = {authority.id: authority for authority in authorities}
        from .private_artifact_keys import ArtifactSigner
        self.signer = ArtifactSigner(hashlib.sha256(organizations.key + PROFILE.encode()).digest(), PROFILE)
        with self.identity.tx() as db:
            for sql in SCHEMA:
                db.execute(sql)

    def _open(self, row):
        from .customer_identity import _object
        value = _object(row['payload'])
        if not self.signer.verify(value, row['signature']):
            raise WorkspaceConflict()
        return value

    def _owner(self, db, ws, actor):
        scope, organization = self.organizations._scope(db, ws, actor, 'manage')
        owners = self.organizations._owners(db, ws)
        if owners != [{'customer_id': actor.customer_id}]:
            raise WorkspaceDenied()
        return scope, organization

    def _policy(self, db, ws):
        _identity(ws, 'ws')
        rows = _rows(db, 'SELECT * FROM customer_recovery_policies WHERE workspace_id=?', (ws,))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self._open(rows[0])
        if value['workspace_id'] != ws or value['revision'] != rows[0]['revision']:
            raise WorkspaceConflict()
        if not value['active'] or db.execute('SELECT 1 FROM customer_recovery_blocks WHERE id=?',
                (ws + ':' + str(value['revision']),)).fetchone():
            raise WorkspaceDenied()
        authority = self.authorities.get(value['authority_id'])
        if authority is None or authority.public_key != value['authority_key']:
            raise WorkspaceDenied()
        organizations = _rows(db, 'SELECT * FROM customer_organizations WHERE workspace_id=? AND active=1', (ws,))
        workspaces = _rows(db, 'SELECT revision FROM organization_workspaces WHERE id=? AND active=1', (ws,))
        links = _rows(db, "SELECT * FROM customer_workspace_links WHERE workspace_id=? AND customer_id=? AND active=1 AND role='owner'",
                      (ws, value['owner_id']))
        accounts = _rows(db, 'SELECT revision FROM customer_identities WHERE id=? AND active=1', (value['owner_id'],))
        if (len(organizations) != 1 or len(workspaces) != 1 or len(links) != 1 or len(accounts) != 1
                or organizations[0]['revision'] != value['organization_revision']
                or workspaces[0]['revision'] != value['workspace_revision']
                or links[0]['revision'] != value['owner_revision']
                or accounts[0]['revision'] != value['identity_revision']
                or self.organizations._owners(db, ws) != [{'customer_id': value['owner_id']}]):
            raise WorkspaceDenied()
        return value

    def enroll(self, ws, body, actor):
        exact(body, ('public_key', 'authority_id', 'revision', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE or not _revision(body['revision'], zero=True):
            raise WorkspaceInvalid()
        _public(body['public_key'])
        authority = self.authorities.get(body['authority_id'])
        if authority is None or authority.public_key == body['public_key']:
            raise WorkspaceDenied()
        with self.organizations._tx(actor) as db:
            scope, organization = self._owner(db, ws, actor)
            old = _rows(db, 'SELECT revision FROM customer_recovery_policies WHERE workspace_id=?', (ws,))
            revision = old[0]['revision'] if old else 0
            if revision != body['revision']:
                raise WorkspaceConflict()
            account = _rows(db, 'SELECT revision FROM customer_identities WHERE id=? AND active=1', (actor.customer_id,))[0]
            value = {'profile': PROFILE, 'workspace_id': ws, 'revision': revision + 1, 'active': True,
                     'owner_id': actor.customer_id, 'owner_revision': scope['link_revision'],
                     'identity_revision': account['revision'], 'organization_revision': organization['revision'],
                     'workspace_revision': scope['workspace_revision'], 'public_key': body['public_key'],
                     'authority_id': authority.id, 'authority_key': authority.public_key, 'created': _time()}
            if old:
                db.execute('UPDATE customer_recovery_policies SET revision=?,payload=?,signature=? WHERE workspace_id=? AND revision=?',
                           (value['revision'], _canonical(value), self.signer.sign(value), ws, revision))
            else:
                db.execute('INSERT INTO customer_recovery_policies VALUES(?,?,?,?)',
                           (ws, value['revision'], _canonical(value), self.signer.sign(value)))
            self.organizations._audit(db, actor, ws, 'recovery.enroll', ws, value['revision'])
            return {'enrolled': True, 'revision': value['revision'], 'dispute_seconds': WAIT_SECONDS}

    def challenge(self, ws, body, actor):
        exact(body, ('evidence_sha256',))
        if type(body['evidence_sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', body['evidence_sha256']):
            raise WorkspaceInvalid()
        with self.organizations._tx(actor) as db:
            policy = self._policy(db, ws)
            if actor.customer_id == policy['owner_id']:
                raise WorkspaceDenied()
            if db.execute("SELECT COUNT(*) FROM customer_recovery_requests WHERE workspace_id=? AND target_id=? AND status='challenge' AND created>?",
                          (ws, actor.customer_id, _time() - 3600)).fetchone()[0] >= 5:
                raise WorkspaceConflict()
            account = _rows(db, 'SELECT revision FROM customer_identities WHERE id=? AND active=1', (actor.customer_id,))[0]
            now = _time()
            claim = {'profile': PROFILE, 'id': 'crr_' + secrets.token_hex(16), 'workspace_id': ws,
                     'policy_revision': policy['revision'], 'target_id': actor.customer_id,
                     'target_revision': account['revision'], 'evidence_sha256': body['evidence_sha256'],
                     'proof_submission_expires': now + 3600,
                     'created': now, 'expires': now + CLAIM_SECONDS, 'policy_sha256': hashlib.sha256(_canonical(policy).encode()).hexdigest()}
            value = {'claim': claim, 'owner_signature': None, 'authority_signature': None,
                     'eligible_after': None, 'resolution': None, 'status': 'challenge', 'challenge_expires': claim['proof_submission_expires']}
            db.execute('INSERT INTO customer_recovery_requests VALUES(?,?,?,?,?,?,?)',
                       (claim['id'], ws, actor.customer_id, 'challenge', now, _canonical(value), self.signer.sign(value)))
            self.organizations._audit(db, actor, ws, 'recovery.challenge', claim['id'], policy['revision'])
            return {'claim': claim, 'dispute_seconds': WAIT_SECONDS}

    def review(self, ws, actor):
        """The current owner can see and contest pending recovery requests."""
        with self.organizations._tx(actor) as db:
            self.organizations._scope(db, ws, actor, 'manage')
            policies = _rows(db, 'SELECT * FROM customer_recovery_policies WHERE workspace_id=?', (ws,))
            policy = self._open(policies[0]) if policies else None
            try:
                current = self._policy(db, ws)
            except WorkspaceDenied:
                current = None
            pending = []
            for row in _rows(db, "SELECT * FROM customer_recovery_requests WHERE workspace_id=? AND status IN ('challenge','pending') ORDER BY created DESC LIMIT 100", (ws,)):
                _, value = self._request(db, ws, row['id'])
                if value['claim']['expires'] > _time() and (row['status'] == 'pending' or value['challenge_expires'] > _time()):
                    pending.append({'id': row['id'], 'status': row['status'], 'created': row['created'],
                                    'eligible_after': value['eligible_after'], 'expires': value['claim']['expires']})
            return {'revision': policy['revision'] if policy else 0,
                    'enrolled': current is not None, 'reenrollment_required': policy is not None and current is None,
                    'authorities': sorted(self.authorities),
                    'pending': pending, 'dispute_seconds': WAIT_SECONDS}

    def revoke(self, ws, body, actor):
        exact(body, ('revision',))
        with self.organizations._tx(actor) as db:
            self.organizations._scope(db, ws, actor, 'manage')
            policy = self._policy(db, ws)
            if policy['revision'] != body['revision'] or not _revision(body['revision']):
                raise WorkspaceConflict()
            db.execute('INSERT INTO customer_recovery_blocks VALUES(?)', (ws + ':' + str(policy['revision']),))
            policy['active'] = False
            db.execute('UPDATE customer_recovery_policies SET payload=?,signature=? WHERE workspace_id=? AND revision=?',
                       (_canonical(policy), self.signer.sign(policy), ws, policy['revision']))
            self.organizations._audit(db, actor, ws, 'recovery.revoke', ws, policy['revision'])
            return {'enrolled': False, 'revision': policy['revision']}

    def _request(self, db, ws, identity):
        _identity(identity, 'crr')
        rows = _rows(db, 'SELECT * FROM customer_recovery_requests WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row, value = rows[0], self._open(rows[0])
        claim = value['claim']
        if (claim['id'] != identity or claim['workspace_id'] != ws or claim['created'] != row['created']
                or claim['target_id'] != row['target_id'] or value['status'] != row['status']):
            raise WorkspaceConflict()
        if value['challenge_expires'] != claim['proof_submission_expires']:
            raise WorkspaceConflict()
        if db.execute('SELECT 1 FROM customer_recovery_blocks WHERE id=?', (identity,)).fetchone():
            raise WorkspaceDenied()
        return row, value

    def _current(self, db, ws, value, actor):
        policy, claim = self._policy(db, ws), value['claim']
        accounts = _rows(db, 'SELECT revision FROM customer_identities WHERE id=? AND active=1', (actor.customer_id,))
        if (actor.customer_id != claim['target_id'] or len(accounts) != 1
                or accounts[0]['revision'] != claim['target_revision']
                or claim['policy_revision'] != policy['revision'] or _time() >= claim['expires']
                or claim['policy_sha256'] != hashlib.sha256(_canonical(policy).encode()).hexdigest()):
            raise WorkspaceDenied()
        return policy

    def _save(self, db, row, value, status):
        value['status'] = status
        changed = db.execute('UPDATE customer_recovery_requests SET status=?,payload=?,signature=? WHERE id=? AND status=?',
                             (status, _canonical(value), self.signer.sign(value), row['id'], row['status'])).rowcount
        if changed != 1:
            raise WorkspaceConflict()

    def submit(self, ws, identity, body, actor):
        exact(body, ('owner_signature', 'authority_signature'))
        with self.organizations._tx(actor) as db:
            row, value = self._request(db, ws, identity)
            if row['status'] != 'challenge':
                raise WorkspaceConflict()
            policy = self._current(db, ws, value, actor)
            if _time() >= value['challenge_expires']:
                raise WorkspaceDenied()
            _verify(_public(policy['public_key']), value['claim'], body['owner_signature'])
            _verify(_public(policy['authority_key']), value['claim'], body['authority_signature'])
            if db.execute("SELECT COUNT(*) FROM customer_recovery_requests WHERE workspace_id=? AND status='pending' AND created>?",
                          (ws, _time() - CLAIM_SECONDS)).fetchone()[0] >= 5:
                raise WorkspaceConflict()
            value.update(body)
            value['eligible_after'] = _time() + WAIT_SECONDS
            if value['eligible_after'] >= value['claim']['expires']:
                raise WorkspaceConflict()
            self._save(db, row, value, 'pending')
            self.organizations._audit(db, actor, ws, 'recovery.review_approved', identity, policy['revision'])
            return {'id': identity, 'status': 'pending', 'eligible_after': value['eligible_after'], 'access_granted': False}

    def status(self, ws, identity, actor):
        with self.organizations._tx(actor) as db:
            row, value = self._request(db, ws, identity)
            if actor.customer_id != value['claim']['target_id']:
                self.organizations._scope(db, ws, actor, 'manage')
            return {'id': identity, 'status': row['status'], 'eligible_after': value['eligible_after'],
                    'expires': value['claim']['expires'], 'access_granted': row['status'] == 'completed'}

    def contest(self, ws, identity, actor):
        with self.organizations._tx(actor) as db:
            self.organizations._scope(db, ws, actor, 'manage')
            row, value = self._request(db, ws, identity)
            if row['status'] not in ('challenge', 'pending'):
                raise WorkspaceConflict()
            value['resolution'] = {'at': _time(), 'reason': 'owner_contested'}
            self._save(db, row, value, 'contested')
            self.organizations._audit(db, actor, ws, 'recovery.contest', identity)
            return {'status': 'contested', 'access_granted': False}

    def withdraw(self, ws, identity, actor):
        with self.organizations._tx(actor) as db:
            row, value = self._request(db, ws, identity)
            if actor.customer_id != value['claim']['target_id'] or row['status'] not in ('challenge', 'pending'):
                raise WorkspaceDenied()
            value['resolution'] = {'at': _time(), 'reason': 'requester_withdrew'}
            self._save(db, row, value, 'withdrawn')
            self.organizations._audit(db, actor, ws, 'recovery.withdraw', identity)
            return {'status': 'withdrawn', 'access_granted': False}

    def finalize(self, ws, identity, actor):
        # The requesting customer's session remains checked on transaction exit.
        # Revocation below applies to the previous owner's separate identity.
        with self.organizations._tx(actor) as db:
            row, value = self._request(db, ws, identity)
            if row['status'] != 'pending' or _time() < value['eligible_after']:
                raise WorkspaceDenied()
            policy = self._current(db, ws, value, actor)
            for key, signature in (('public_key', 'owner_signature'), ('authority_key', 'authority_signature')):
                _verify(_public(policy[key]), value['claim'], value[signature])
            now = _time()
            db.execute('UPDATE customer_workspace_links SET active=0,revision=revision+1,updated=? WHERE workspace_id=? AND customer_id=?',
                       (now, ws, policy['owner_id']))
            old = _rows(db, 'SELECT revision FROM customer_workspace_links WHERE workspace_id=? AND customer_id=?', (ws, actor.customer_id))
            if old:
                db.execute("UPDATE customer_workspace_links SET role='owner',active=1,revision=revision+1,updated=? WHERE workspace_id=? AND customer_id=?",
                           (now, ws, actor.customer_id))
            else:
                db.execute('INSERT INTO customer_workspace_links VALUES(?,?,?,?,?,?)', (ws, actor.customer_id, 'owner', 1, 1, now))
            db.execute('UPDATE customer_sessions SET revoked=? WHERE customer_id=? AND revoked IS NULL', (now, policy['owner_id']))
            db.execute('UPDATE customer_bff_tokens SET revoked=? WHERE customer_id=? AND revoked IS NULL', (now, policy['owner_id']))
            db.execute("UPDATE customer_organization_invitations SET status='revoked',revision=revision+1,resolved=? WHERE workspace_id=? AND status='pending'", (now, ws))
            self.organizations._bump(db, ws)
            db.execute('INSERT INTO customer_recovery_blocks VALUES(?)', (ws + ':' + str(policy['revision']),))
            value['resolution'] = {'at': now, 'reason': 'dual_proof_after_dispute_window'}
            self._save(db, row, value, 'completed')
            self.organizations._audit(db, actor, ws, 'recovery.complete', identity, policy['revision'])
            return {'status': 'completed', 'access_granted': True, 'old_sessions_revoked': True,
                    'new_recovery_enrollment_required': True}

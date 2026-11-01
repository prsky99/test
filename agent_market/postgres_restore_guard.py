"""Durable deployment gate for explicitly owned native PostgreSQL restoration.

The gate lives outside the archived application schema. A failed restore cannot
erase it, and an old backup cannot supply its fresh independent approval.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import hmac
import json
import secrets
import time

from .private_artifact_keys import ArtifactKeys, ArtifactSigner

PROFILE = 'postgres-restore-deployment-gate-v1'
WRITER_LOCK = 71498241526018
_owner = ContextVar('explicit_postgres_restore_owner', default=None)
CONTROL_DDL = (
    'CREATE SCHEMA agent_restore_control',
    '''CREATE TABLE agent_restore_control.gate(id INTEGER PRIMARY KEY CHECK(id=1),
       state TEXT NOT NULL,generation TEXT NOT NULL,revision BIGINT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE agent_restore_control.events(generation TEXT NOT NULL,revision BIGINT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(generation,revision))''',
    'GRANT USAGE ON SCHEMA agent_restore_control TO PUBLIC',
    'GRANT SELECT ON agent_restore_control.gate TO PUBLIC',
)


class RestoreGateDenied(ValueError):
    def __init__(self, code='restore_reapproval_required'):
        self.code = code
        super().__init__(code)


def _key(key):
    if type(key) is not bytes or len(key) != 32:
        raise RestoreGateDenied('explicit_workflow_key_required')
    return key


def _signer(key):
    return ArtifactSigner(hmac.new(_key(key), PROFILE.encode(), hashlib.sha256).digest(), PROFILE, ArtifactKeys())


def _custody(key):
    return hmac.new(_key(key), (PROFILE + ':workflow-key-custody').encode(), hashlib.sha256).hexdigest()


def _sql(connection, sql, params=(), *, rows=True):
    with connection.cursor(row_factory=lambda _: tuple) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if rows else None


def _json(raw):
    def exact(pairs):
        result = {}
        for name, value in pairs:
            if name in result: raise ValueError()
            result[name] = value
        return result
    try:
        if type(raw) is not str or len(raw.encode()) > 16384: raise ValueError()
        value = json.loads(raw, object_pairs_hook=exact, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if type(value) is not dict: raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise RestoreGateDenied() from None


def _load(connection, key):
    exists = _sql(connection, "SELECT pg_catalog.to_regnamespace('agent_restore_control') IS NOT NULL")[0][0]
    if not exists: return None
    if _sql(connection, "SELECT pg_catalog.to_regclass('agent_restore_control.gate') IS NOT NULL") != [(True,)]:
        raise RestoreGateDenied()
    rows = _sql(connection, 'SELECT state,generation,revision,payload,signature FROM agent_restore_control.gate WHERE id=1')
    if len(rows) != 1: raise RestoreGateDenied()
    state, generation, revision, raw, signature = rows[0]
    payload = _json(raw)
    if (payload.get('profile') != PROFILE or payload.get('state') != state or payload.get('generation') != generation
            or payload.get('revision') != revision or not _signer(key).verify(payload, signature)
            or not hmac.compare_digest(str(payload.get('key_custody', '')), _custody(key))):
        raise RestoreGateDenied()
    return payload


def _owns(connection):
    return _sql(connection, '''SELECT COUNT(*) FROM pg_catalog.pg_locks WHERE pid=pg_catalog.pg_backend_pid()
        AND locktype='advisory' AND granted AND mode='ExclusiveLock' AND classid=%s AND objid=%s AND objsubid=1''',
        (WRITER_LOCK >> 32, WRITER_LOCK & 0xffffffff)) == [(1,)]


def assert_attach_allowed(store):
    """Called after native transaction/writer admission, before application SQL."""
    connection = store._connection
    try:
        value = _load(connection, getattr(store, 'workflow_key', None))
        if value is None: return
        actual = _sql(connection, '''SELECT (SELECT system_identifier::text FROM pg_catalog.pg_control_system()),
            (SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=pg_catalog.current_database())''')
        if actual != [(value['anchor']['system_identifier'], value['anchor']['database_oid'])]:
            raise RestoreGateDenied('restore_identity_mismatch')
        internal = _owner.get()
        if (internal and internal['connection'] is connection and internal['generation'] == value['generation']
                and value['state'] == 'restoring' and value.get('owner_hash') == hashlib.sha256(internal['token'].encode()).hexdigest()
                and value.get('expires', 0) > time.time() and _owns(connection)):
            return
        if value['state'] != 'approved': raise RestoreGateDenied()
    except RestoreGateDenied:
        raise
    except Exception:
        raise RestoreGateDenied() from None


@contextmanager
def exclusive(connection):
    if connection.autocommit is not True or int(connection.info.transaction_status) != 0:
        raise RestoreGateDenied('connection_busy')
    if _sql(connection, 'SELECT pg_catalog.pg_try_advisory_lock(%s)', (WRITER_LOCK,)) != [(True,)]:
        raise RestoreGateDenied('restore_ownership_conflict')
    try: yield
    finally:
        try: _sql(connection, 'SELECT pg_catalog.pg_advisory_unlock(%s)', (WRITER_LOCK,))
        except Exception: pass  # Connection loss releases server session locks.


def _write(connection, key, value, *, previous=None, action, actor_ref=None):
    signer = _signer(key)
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    signature = signer.sign(value)
    event = {'profile': PROFILE, 'generation': value['generation'], 'revision': value['revision'],
             'action': action, 'state': value['state'], 'created': time.time(), 'actor_ref': actor_ref,
             'previous': hashlib.sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest() if previous else None}
    _sql(connection, 'BEGIN', rows=False)
    try:
        if previous is None:
            _sql(connection, 'INSERT INTO agent_restore_control.gate VALUES(1,%s,%s,%s,%s,%s)',
                (value['state'], value['generation'], value['revision'], raw, signature), rows=False)
        else:
            with connection.cursor() as cursor:
                cursor.execute('''UPDATE agent_restore_control.gate SET state=%s,revision=%s,payload=%s,signature=%s
                    WHERE id=1 AND generation=%s AND revision=%s''',
                    (value['state'], value['revision'], raw, signature, previous['generation'], previous['revision']))
                if cursor.rowcount != 1: raise RestoreGateDenied('restore_revision_conflict')
        _sql(connection, 'INSERT INTO agent_restore_control.events VALUES(%s,%s,%s,%s)',
             (value['generation'], value['revision'], json.dumps(event, sort_keys=True), signer.sign(event)), rows=False)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return value


def claim(connection, key, *, identity, anchor, archive_hash, expires):
    if not _owns(connection): raise RestoreGateDenied('restore_ownership_required')
    if _sql(connection, "SELECT pg_catalog.to_regnamespace('agent_restore_control') IS NOT NULL") != [(False,)]:
        raise RestoreGateDenied('restore_target_already_claimed')
    for sql in CONTROL_DDL: _sql(connection, sql, rows=False)
    token = secrets.token_urlsafe(32)
    value = {'profile': PROFILE, 'state': 'restoring', 'generation': 'pgr_' + secrets.token_hex(16),
        'revision': 1, 'identity': identity, 'anchor': anchor, 'key_custody': _custody(key), 'archive_hash': archive_hash, 'created': time.time(),
        'expires': expires, 'owner_hash': hashlib.sha256(token.encode()).hexdigest()}
    _write(connection, key, value, action='restore.claimed')
    return value, token


@contextmanager
def restore_scope(connection, key, token):
    value = _load(connection, key)
    if (not value or value['state'] != 'restoring' or not _owns(connection)
            or value.get('owner_hash') != hashlib.sha256(token.encode()).hexdigest() or value.get('expires', 0) <= time.time()):
        raise RestoreGateDenied('restore_ownership_required')
    marker = _owner.set({'connection': connection, 'generation': value['generation'], 'token': token})
    try: yield value
    finally: _owner.reset(marker)


def finish(connection, key, token, *, success, inventory=None):
    value = _load(connection, key)
    if (not value or value['state'] != 'restoring' or not _owns(connection)
            or value.get('owner_hash') != hashlib.sha256(token.encode()).hexdigest()):
        raise RestoreGateDenied('restore_ownership_required')
    updated = {**value, 'state': 'quarantined' if success else 'failed', 'revision': value['revision'] + 1,
               'finished': time.time(), 'inventory': inventory if success else None,
               'challenge': secrets.token_urlsafe(32) if success else None}
    updated.pop('owner_hash', None); updated.pop('expires', None)
    return _write(connection, key, updated, previous=value, action='restore.quarantined' if success else 'restore.failed')


def challenge(connection, key):
    value = _load(connection, key)
    if not value or value['state'] != 'quarantined': raise RestoreGateDenied()
    return {name: value[name] for name in ('profile', 'generation', 'revision', 'identity', 'archive_hash', 'challenge')}


class RestoreOwnerAuthority:
    """Explicit external current-owner verifier; never derived from restored rows."""
    def __init__(self, key, *, verifier):
        self.key = _key(key)
        if not callable(verifier): raise RestoreGateDenied('current_owner_verifier_required')
        self.verifier = verifier

    def _current_owner(self, review, proof):
        try:
            started = time.monotonic()
            owner = self.verifier(review, proof)
            if type(owner) is not str or not 1 <= len(owner.encode()) <= 256 or time.monotonic()-started > 10: raise ValueError()
            return owner
        except Exception:
            raise RestoreGateDenied('current_owner_proof_required') from None

    def issue(self, review, proof):
        owner = self._current_owner(review, proof)
        now = time.time()
        payload = {'profile': PROFILE, 'review': review, 'owner_ref': hashlib.sha256(owner.encode()).hexdigest(),
                   'created': now, 'expires': now + 300}
        signature = hmac.new(self.key, json.dumps(payload, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
        return {'payload': payload, 'signature': signature}

    def verify(self, review, receipt, proof):
        try:
            if type(receipt) is not dict or set(receipt) != {'payload', 'signature'}: raise ValueError()
            payload = receipt['payload']
            signature = hmac.new(self.key, json.dumps(payload, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
            if (not hmac.compare_digest(signature, receipt['signature']) or payload['profile'] != PROFILE or payload['review'] != review
                    or not time.time() - 300 <= payload['created'] <= time.time() or not time.time() < payload['expires'] <= payload['created'] + 300):
                raise ValueError()
            owner = self._current_owner(review, proof)
            if hashlib.sha256(owner.encode()).hexdigest() != payload['owner_ref'] or payload['expires'] <= time.time():
                raise ValueError()
            return payload['owner_ref']
        except (TypeError, ValueError, KeyError, RecursionError):
            raise RestoreGateDenied('current_owner_proof_required') from None


def approve(connection, key, *, identity, authority, receipt, proof, current_check):
    if not isinstance(authority, RestoreOwnerAuthority): raise RestoreGateDenied('current_owner_verifier_required')
    if not callable(current_check): raise RestoreGateDenied('current_approval_guard_required')
    with exclusive(connection):
        value = _load(connection, key)
        review = challenge(connection, key)
        if value['identity'] != identity: raise RestoreGateDenied('restore_identity_mismatch')
        actor = authority.verify(review, receipt, proof)
        current_check()
        if not _owns(connection): raise RestoreGateDenied('restore_ownership_required')
        # Approval makes the restored deployment inspectable only. Old runtime
        # controls and authority must remain paused/revoked until fresh grants.
        if _sql(connection, 'SELECT invoke_enabled+workflow_enabled+delivery_enabled FROM public.execution_controls WHERE id=1') != [(0,)]:
            raise RestoreGateDenied('restored_controls_not_paused')
        updated = {**value, 'state': 'approved', 'revision': value['revision'] + 1,
                   'approved': time.time(), 'owner_ref': actor}
        updated.pop('challenge', None)
        return _write(connection, key, updated, previous=value, action='restore.approved', actor_ref=actor)

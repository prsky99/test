"""Explicit credential-backed PostgreSQL archives and gated deployment recovery.

This is a source API, not an operating connection discovery or activation path.
Operating acceptance remains separate even after isolated contracts pass.
"""
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import tempfile
import time

from .private_artifact_keys import ArtifactKeys, ArtifactSigner, ArtifactCipher
from .workflow_backup import exclusive, digest
from .workflow_postgres_archive import _read, _json, _key, _schema_hash, _objects, _tools, _query, quarantine, MAX_ARCHIVE_BYTES
from .postgres_archive_provider import ExplicitArchiveCredentialProvider, verify_connection, tool_environment
from . import postgres_restore_guard as gate

PROFILE = 'explicit-postgres-operational-archive-v1'


class OperationalArchiveDenied(ValueError):
    def __init__(self, code='operational_archive_unavailable'):
        self.code = code
        super().__init__(code)


def _custody(key):
    return hmac.new(key, (PROFILE + ':workflow-key-custody').encode(), hashlib.sha256).hexdigest()


def _signer(key, keys):
    return ArtifactSigner(hmac.new(key, PROFILE.encode(), hashlib.sha256).digest(), PROFILE, keys)


def _credential(connection, identity, provider, purpose):
    if type(provider) is not ExplicitArchiveCredentialProvider:
        raise OperationalArchiveDenied('explicit_archive_credentials_required')
    fingerprint = verify_connection(connection, identity)
    return fingerprint, provider.obtain(identity, purpose)


def _run(tool, credential, arguments):
    identity = credential.identity
    argv = [tool, '--host=' + identity.host, '--port=' + str(identity.port), '--username=' + identity.user,
            '--dbname=' + identity.database, '--no-password', *arguments]
    with tool_environment(credential) as (environment, directory):
        environment['PGOPTIONS'] = '-c statement_timeout=60000 -c lock_timeout=1000'
        try:
            result = subprocess.run(argv, cwd=directory, env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=65)  # nosec B603
        except (OSError, subprocess.TimeoutExpired):
            raise OperationalArchiveDenied('archive_tool_failed') from None
        if result.returncode:
            raise OperationalArchiveDenied('archive_tool_failed')


def _validate_source(connection, key):
    from .storage_adapter import open_store
    store = open_store('postgresql', connection=connection, initialize=False, workflow_key=key)
    store.close()
    _objects(connection)


def backup(connection, directory, *, identity, credentials, workflow_key, tools, retention_days=30):
    key, commands, keys = _key(workflow_key), _tools(tools), ArtifactKeys()
    cipher = ArtifactCipher(PROFILE, keys)
    if not cipher.configured: raise OperationalArchiveDenied('explicit_encryption_key_required')
    if type(retention_days) is not int or not 1 <= retention_days <= 365:
        raise OperationalArchiveDenied('invalid_archive_policy')
    source_identity, credential = _credential(connection, identity, credentials, 'backup')
    directory = Path(directory)
    # Session ownership drains the current application writer and excludes new
    # application writers while source schema and dump snapshot are attested.
    with gate.exclusive(connection):
        credential.current(); _validate_source(connection, key)
        directory.mkdir(mode=0o700, exist_ok=False)
        try:
            path = directory / 'application.dump'
            _run(commands['pg_dump'], credential, ['--format=custom', '--schema=public', '--strict-names',
                '--no-owner', '--no-privileges', '--file=' + str(path.resolve())])
            path.chmod(0o600)
            if path.stat().st_size > MAX_ARCHIVE_BYTES: raise OperationalArchiveDenied('archive_size_limit')
            now = time.time()
            manifest = {'profile': PROFILE, 'version': 1, 'created': now, 'source_identity': source_identity,
                'schema_sha256': _schema_hash(), 'workflow_key_custody': _custody(key), 'encrypted': True,
                'retention_days': retention_days, 'review_delete_after': now + retention_days * 86400,
                'automatic_deletion': False, 'workflow_key_included': False, 'artifact_keys_included': False,
                'key_policy': keys.summary(), 'restore_requires_fresh_target': True, 'current_owner_reapproval_required': True}
            encrypted = cipher.seal(path.read_bytes(), {'profile': PROFILE, 'created': now, 'schema_sha256': manifest['schema_sha256']})
            sealed = directory / 'application.dump.sealed'; exclusive(sealed, encrypted); path.unlink()
            manifest['archive_sha256'] = digest(sealed); manifest['signature'] = _signer(key, keys).sign(manifest)
            exclusive(directory / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
            return {**manifest, 'operating_backup_ready': False}
        except BaseException:
            for name in ('application.dump', 'application.dump.sealed', 'manifest.json'):
                (directory / name).unlink(missing_ok=True)
            directory.rmdir()
            raise


def _authenticated(directory, key):
    directory = Path(directory); keys = ArtifactKeys()
    manifest = _json(_read(directory / 'manifest.json', 32768)); signature = manifest.pop('signature', None)
    if (not _signer(key, keys).verify(manifest, signature) or manifest.get('profile') != PROFILE
            or manifest.get('version') != 1 or manifest.get('encrypted') is not True
            or manifest.get('schema_sha256') != _schema_hash()
            or not hmac.compare_digest(str(manifest.get('workflow_key_custody', '')), _custody(key))):
        raise OperationalArchiveDenied('archive_authentication_failed')
    encoded = _read(directory / 'application.dump.sealed', 180000000)
    if hashlib.sha256(encoded).hexdigest() != manifest.get('archive_sha256'):
        raise OperationalArchiveDenied('archive_authentication_failed')
    content = ArtifactCipher(PROFILE, keys).open(encoded,
        {'profile': PROFILE, 'created': manifest['created'], 'schema_sha256': manifest['schema_sha256']})
    return manifest, content


def _empty(connection):
    if (_query(connection, "SELECT COUNT(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='public'") != [(0,)]
            or _query(connection, "SELECT COUNT(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON p.pronamespace=n.oid WHERE n.nspname='public'") != [(0,)]):
        raise OperationalArchiveDenied('new_empty_target_required')


def restore(connection, directory, *, identity, credentials, workflow_key, tools):
    key, commands = _key(workflow_key), _tools(tools)
    manifest, content = _authenticated(directory, key)
    target_identity, credential = _credential(connection, identity, credentials, 'restore')
    if target_identity == manifest['source_identity']: raise OperationalArchiveDenied('restore_source_target_conflict')
    with gate.exclusive(connection):
        credential.current(); _empty(connection)
        claimed, owner_token = gate.claim(connection, key, identity=target_identity,
            anchor={'system_identifier': identity.system_identifier, 'database_oid': identity.database_oid},
            archive_hash=manifest['archive_sha256'], expires=min(credential.expires, time.time() + 120))
        try:
            with tempfile.TemporaryDirectory(prefix='a2a-authenticated-restore-') as temporary:
                artifact = Path(temporary) / 'authenticated.dump'; exclusive(artifact, content)
                credential.current()
                with connection.cursor() as cursor: cursor.execute('DROP SCHEMA IF EXISTS public')
                _run(commands['pg_restore'], credential, ['--single-transaction', '--exit-on-error',
                    '--no-owner', '--no-privileges', str(artifact.resolve())])
            credential.current(); verify_connection(connection, identity)
            from .storage_adapter import open_store
            with gate.restore_scope(connection, key, owner_token):
                store = open_store('postgresql', connection=connection, initialize=False, workflow_key=key)
                try:
                    _objects(connection)
                    with store.tx():
                        result = quarantine(store)
                finally: store.close()
            value = gate.finish(connection, key, owner_token, success=True, inventory=result['review_inventory'])
            return {**result, 'profile': PROFILE, 'deployment_state': value['state'], 'generation': value['generation'],
                'revision': value['revision'], 'operating_backup_ready': False, 'current_owner_reapproval_required': True}
        except BaseException:
            # A failed quarantine never returns an attachable target. The gate
            # was committed outside the archived schema before tool dispatch.
            try:
                if int(connection.info.transaction_status): connection.rollback()
                gate.finish(connection, key, owner_token, success=False)
            except Exception:
                pass  # The already durable restoring gate still denies access.
            raise


def review(connection, *, identity, credentials, workflow_key):
    key = _key(workflow_key)
    fingerprint, credential = _credential(connection, identity, credentials, 'approve')
    credential.current(); value = gate.challenge(connection, key)
    if value['identity'] != fingerprint: raise OperationalArchiveDenied('restore_identity_mismatch')
    return value


def approve_deployment(connection, *, identity, credentials, workflow_key, authority, receipt, proof):
    key = _key(workflow_key)
    if not isinstance(authority, gate.RestoreOwnerAuthority) or hmac.compare_digest(authority.key, key):
        raise OperationalArchiveDenied('independent_owner_authority_required')
    fingerprint, credential = _credential(connection, identity, credentials, 'approve')
    credential.current()
    def current():
        credential.current()
        if verify_connection(connection, identity) != fingerprint:
            raise OperationalArchiveDenied('restore_identity_mismatch')
    try:
        value = gate.approve(connection, key, identity=fingerprint, authority=authority, receipt=receipt, proof=proof, current_check=current)
    finally:
        credential.password = None
    return {'deployment_state': value['state'], 'generation': value['generation'], 'revision': value['revision'],
        'runtime_controls': 'paused', 'old_authority_reactivated': False, 'operating_backup_ready': False}

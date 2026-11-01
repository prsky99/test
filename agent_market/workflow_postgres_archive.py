"""Bounded private Unix-cluster archive rehearsal with fail-closed restoration.

This is an offline native kernel, not an operating backup scheduler or credential
provider. Only an explicitly owned disposable cluster and new empty target are
accepted. The workflow key and optional artifact keyring stay outside archives.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time

from .private_artifact_keys import ArtifactKeys, ArtifactSigner, ArtifactCipher
from .workflow_backup import exclusive, digest

PROFILE = 'postgres-private-workflow-archive-v1'
MAX_ARCHIVE_BYTES = 134217728


class NativeArchiveUnavailable(ValueError):
    def __init__(self, code='native_archive_unavailable'):
        self.code = code
        super().__init__(code)


def _key(value):
    if type(value) is not bytes or len(value) != 32:
        raise NativeArchiveUnavailable('explicit_workflow_key_required')
    return value


def _custody(key):
    return hmac.new(key, (PROFILE + ':workflow-key-custody').encode(), hashlib.sha256).hexdigest()


def _read(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or info.st_size > maximum):
            raise NativeArchiveUnavailable('private_archive_file_required')
        value = source.read(maximum + 1)
    if len(value) > maximum:
        raise NativeArchiveUnavailable('archive_size_limit')
    return value


def _json(raw):
    def exact(pairs):
        value = {}
        for name, item in pairs:
            if name in value:
                raise ValueError()
            value[name] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=exact, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if type(value) is not dict:
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise NativeArchiveUnavailable('invalid_archive_manifest') from None


def _schema_hash():
    from .application_store_postgres import _CATALOG
    return hashlib.sha256(json.dumps({'profile': _CATALOG['profile'], 'schema': _CATALOG['schema']},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _objects(connection):
    # An application profile attests known objects; an archive must additionally
    # refuse unrelated tables, views and functions rather than export them.
    from .application_store_postgres import _CATALOG
    expected = set(_CATALOG['tables']) | {'resources_fts', 'vec_resources', 'application_store_state'}
    rows = _query(connection, "SELECT c.relname,c.relkind FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')")
    if {row[0] for row in rows} != expected or any(row[1] != 'r' for row in rows):
        raise NativeArchiveUnavailable('archive_schema_scope_mismatch')
    rows = _query(connection, "SELECT p.proname FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON p.pronamespace=n.oid WHERE n.nspname='public'")
    from .application_store_postgres import _invariant_ddl
    expected_functions = {re.match(r'CREATE FUNCTION ([a-z_]+)\(', sql)[1]
        for sql in _invariant_ddl() if sql.startswith('CREATE FUNCTION ')}
    if {row[0] for row in rows} != expected_functions or len(rows) != len(expected_functions):
        raise NativeArchiveUnavailable('archive_schema_scope_mismatch')
    if _query(connection, "SELECT COUNT(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='public' AND c.relkind='S' AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_class t ON t.oid=d.refobjid JOIN pg_catalog.pg_namespace tn ON tn.oid=t.relnamespace WHERE d.objid=c.oid AND d.deptype IN ('a','i') AND tn.nspname='public' AND t.relname=ANY(%s))", (sorted(expected),)) != [(0,)]:
        raise NativeArchiveUnavailable('archive_schema_scope_mismatch')


def _query(connection, sql, parameters=()):
    with connection.cursor(row_factory=lambda cursor: tuple) as cursor:
        cursor.execute(sql, parameters)
        return cursor.fetchall()


def _private(connection, cluster):
    if type(cluster) is not dict or set(cluster) != {'root', 'socket'}:
        raise NativeArchiveUnavailable('owned_private_cluster_required')
    root, socket = Path(cluster['root']), Path(cluster['socket'])
    if (not root.is_absolute() or root.is_symlink() or root.parent != Path('/private/tmp')
            or not re.fullmatch('a2a-adapter-pg-[A-Za-z0-9_-]+', root.name)
            or socket != root / 'socket' or socket.is_symlink()):
        raise NativeArchiveUnavailable('owned_private_cluster_required')
    for directory in (root, socket):
        info = directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise NativeArchiveUnavailable('owned_private_cluster_required')
    try:
        if connection.autocommit is not True or int(connection.info.transaction_status) != 0:
            raise NativeArchiveUnavailable('connection_busy')
        host, port, database, user = connection.info.host, connection.info.port, connection.info.dbname, connection.info.user
        if host != str(socket) or type(port) is not int or not 1 <= port <= 65535:
            raise NativeArchiveUnavailable('private_unix_connection_required')
        if any(type(value) is not str or not re.fullmatch('[a-z_][a-z0-9_]{0,62}', value) for value in (database, user)):
            raise NativeArchiveUnavailable('private_database_name_required')
        actual = _query(connection, "SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr(),current_setting('data_directory')")
        if actual != [('', None, None, str(root / 'data'))]:
            raise NativeArchiveUnavailable('private_unix_connection_required')
        return {'root': root, 'host': host, 'port': port, 'database': database, 'user': user}
    except NativeArchiveUnavailable:
        raise
    except Exception:
        raise NativeArchiveUnavailable('private_unix_connection_required') from None


def _tools(tools):
    if type(tools) is not dict or set(tools) != {'pg_dump', 'pg_restore'}:
        raise NativeArchiveUnavailable('explicit_archive_tools_required')
    result = {}
    for name, value in tools.items():
        path = Path(value)
        if not path.is_absolute() or path.name != name or not path.is_file() or not os.access(path, os.X_OK):
            raise NativeArchiveUnavailable('explicit_archive_tools_required')
        result[name] = str(path)
    return result


def _environment(root):
    return {'PATH': '/usr/bin:/bin', 'HOME': str(root), 'TMPDIR': str(root), 'LC_ALL': 'C', 'LANG': 'C',
            'PGPASSFILE': str(root / 'no-password-file'), 'PGSERVICEFILE': str(root / 'no-service-file'),
            'PGSYSCONFDIR': str(root)}


def _run(tool, target, arguments):
    argv = [tool, '--host=' + target['host'], '--port=' + str(target['port']), '--username=' + target['user'],
            '--dbname=' + target['database'], '--no-password', *arguments]
    try:
        result = subprocess.run(argv, env=_environment(target['root']), cwd=target['root'],
            capture_output=True, timeout=60)  # nosec B603
        if result.returncode:
            raise NativeArchiveUnavailable('archive_tool_failed')
    except (OSError, subprocess.TimeoutExpired):
        raise NativeArchiveUnavailable('archive_tool_failed') from None


def backup(connection, directory, *, workflow_key, cluster, tools, encrypt=False, retention_days=30):
    key = _key(workflow_key)
    if type(encrypt) is not bool or type(retention_days) is not int or not 1 <= retention_days <= 365:
        raise NativeArchiveUnavailable('invalid_archive_policy')
    target, commands, keys = _private(connection, cluster), _tools(tools), ArtifactKeys()
    cipher = ArtifactCipher(PROFILE, keys)
    if encrypt and not cipher.configured:
        raise NativeArchiveUnavailable('explicit_encryption_key_required')
    from .storage_adapter import open_store
    source = open_store('postgresql', connection=connection, initialize=False, workflow_key=key)
    source.close()
    _objects(connection)
    directory = Path(directory); directory.mkdir(mode=0o700, exist_ok=False)
    try:
        path = directory / 'application.dump'
        _run(commands['pg_dump'], target, ['--format=custom', '--schema=public', '--strict-names',
            '--no-owner', '--no-privileges', '--file=' + str(path.resolve())])
        path.chmod(0o600)
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise NativeArchiveUnavailable('archive_size_limit')
        now = time.time()
        manifest = {'profile': PROFILE, 'version': 1, 'created': now, 'schema_sha256': _schema_hash(),
            'encrypted': encrypt, 'retention_days': retention_days, 'review_delete_after': now + retention_days * 86400,
            'automatic_deletion': False, 'workflow_key_included': False, 'artifact_keys_included': False,
            'workflow_key_custody': _custody(key), 'restore_requires_empty_target': True, 'restore_quarantine_required': True,
            'key_policy': keys.summary()}
        if encrypt:
            raw = cipher.seal(path.read_bytes(), {'profile': PROFILE, 'created': now, 'schema_sha256': manifest['schema_sha256']})
            exclusive(directory / 'application.dump.sealed', raw); path.unlink(); path = directory / 'application.dump.sealed'
        manifest['archive_sha256'] = digest(path)
        signer = ArtifactSigner(hmac.new(key, PROFILE.encode(), hashlib.sha256).digest(), PROFILE, keys)
        manifest['signature'] = signer.sign(manifest)
        exclusive(directory / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
        return manifest
    except BaseException:
        for name in ('application.dump', 'application.dump.sealed', 'manifest.json'):
            (directory / name).unlink(missing_ok=True)
        directory.rmdir()
        raise


def quarantine(store):
    """Current native schema only; one writer transaction, no arbitrary SQL."""
    now = time.time()
    statements = (
        ("UPDATE workflow_runs SET status='failed',execution_outcome='unknown',error='Restored execution requires review; automatic replay is disabled.',result=NULL,finished=%s,owner=NULL,fence=fence+1,lease_until=0 WHERE status IN ('queued','running')", (now,)),
        ("UPDATE workflow_result_outbox SET status='unknown',owner=NULL,fence=fence+1,lease_until=0,finished=%s WHERE status IN ('pending','claimed','dispatched')", (now,)),
        ("UPDATE workflow_manual_deliveries SET status='unknown',owner=NULL,fence=fence+1,lease_until=0,finished=%s WHERE status IN ('pending','claimed','dispatched')", (now,)),
        ("UPDATE workflow_deliveries SET status='uncertain',finished=%s,error='Restored delivery requires review.' WHERE status IN ('sending','prepared')", (now,)),
        ('UPDATE workflow_schedules SET enabled=0,next_run=NULL,event_hash=NULL,event_sealed=NULL', ()),
        ('UPDATE workflow_delivery_grants SET revoked=%s WHERE revoked IS NULL', (now,)),
        ("UPDATE workflow_destinations SET state='revoked',sealed=NULL,code_hash=NULL WHERE state IN ('verified','pending')", ()),
        ('UPDATE workflow_apps SET active=0', ()),
        ('UPDATE workflow_deployment_grants SET active=0,revision=revision+1,revoked=%s', (now,)),
        ('UPDATE workflow_publication_grants SET active=0,revision=revision+1,revoked=%s', (now,)),
        ('UPDATE workflow_connection_deployments SET active=0,revision=revision+1,revoked=%s', (now,)),
        ('UPDATE workflow_connection_automation SET active=0,revision=revision+1,revoked=%s,next_run=NULL', (now,)),
        ('UPDATE workflow_fallback_control SET enabled=0,revision=revision+1,updated=%s', (now,)),
        ('DELETE FROM workflow_fallback_policies', ()), ('DELETE FROM workflow_fallback_shadow', ()),
        ('UPDATE execution_controls SET invoke_enabled=0,workflow_enabled=0,delivery_enabled=0,revision=revision+1,updated=%s', (now,)),
        ('INSERT INTO execution_control_events SELECT revision,0,0,0,0,%s FROM execution_controls WHERE id=1', (now,)),
        ("UPDATE agent_task_watches SET state='expired',sealed=NULL,verified_at=NULL,revoked_at=%s,task='' WHERE state IN ('active','pending_verification','paused')", (now,)),
        ("UPDATE agent_task_events SET status='failed',payload='{}',error='restore_review_required' WHERE status IN ('pending','sending')", ()),
        ('DELETE FROM admin_sessions', ()),
        ('UPDATE organization_workspaces SET active=0,revision=revision+1,updated=%s', (now,)),
        ('UPDATE workspace_memberships SET active=0,revision=revision+1,updated=%s', (now,)),
        ('UPDATE workspace_private_tickets SET revoked=%s WHERE revoked IS NULL', (now,)),
        ('UPDATE customer_oidc_flows SET consumed=%s WHERE consumed IS NULL', (now,)),
        ('UPDATE customer_sessions SET revoked=%s WHERE revoked IS NULL', (now,)),
        ('UPDATE customer_bff_tokens SET revoked=%s WHERE revoked IS NULL', (now,)),
        ('UPDATE customer_workspace_links SET active=0,revision=revision+1,updated=%s', (now,)),
        ('DELETE FROM workspace_app_codes', ()), ('DELETE FROM workspace_app_tokens', ()),
        ('INSERT INTO workspace_release_restore_blocks SELECT id FROM workspace_executable_releases ON CONFLICT DO NOTHING', ()),
        ('INSERT INTO workspace_release_restore_blocks SELECT app_id FROM workspace_release_deployments ON CONFLICT DO NOTHING', ()),
        ('UPDATE workspace_restore_reviews SET consumed=%s WHERE consumed IS NULL', (now,)),
        ('UPDATE customer_organizations SET active=0,revision=revision+1,archived=%s', (now,)),
        ("UPDATE customer_organization_invitations SET status='revoked',revision=revision+1,resolved=%s WHERE status='pending'", (now,)),
        ("INSERT INTO customer_recovery_blocks SELECT workspace_id||':'||CAST(revision AS TEXT) FROM customer_recovery_policies ON CONFLICT DO NOTHING", ()),
        ('INSERT INTO customer_recovery_blocks SELECT id FROM customer_recovery_requests ON CONFLICT DO NOTHING', ()),
        ('INSERT INTO stripe_sandbox_restore_blocks SELECT id FROM stripe_sandbox_orders ON CONFLICT DO NOTHING', ()),
        ('DELETE FROM workspace_meter_policies', ()),
        ('INSERT INTO workspace_typed_flow_restore_blocks SELECT id FROM workspace_typed_flows ON CONFLICT DO NOTHING', ()),
        ('INSERT INTO workspace_agreement_restore_blocks SELECT id FROM workspace_provider_agreements ON CONFLICT DO NOTHING', ()),
        ('INSERT INTO provider_claim_transfer_restore_blocks SELECT id FROM provider_claim_transfers ON CONFLICT DO NOTHING', ()),
        ('UPDATE provider_control_claims SET revoked=%s WHERE revoked IS NULL', (now,)),
        ('INSERT INTO reliability_restore_blocks SELECT id FROM reliability_consents ON CONFLICT DO NOTHING', ()),
        ("INSERT INTO reliability_restore_blocks SELECT 'operating:'||workspace_id||':'||CAST(resource_id AS TEXT)||':'||CAST(revision AS TEXT) FROM reliability_operating_qualifications ON CONFLICT DO NOTHING", ()),
        ('INSERT INTO workspace_remote_task_restore_blocks SELECT id FROM workspace_remote_tasks ON CONFLICT DO NOTHING', ()),
        ('DELETE FROM reliability_sources', ()),
        ("INSERT INTO reliability_controls_restore_blocks SELECT 'eval_control:'||workspace_id||':'||(payload::jsonb->>'revision') FROM reliability_eval_controls ON CONFLICT DO NOTHING", ()),
        ("INSERT INTO reliability_controls_restore_blocks SELECT 'eval_plan:'||workspace_id||':'||revision FROM reliability_eval_plans ON CONFLICT DO NOTHING", ()),
        ("INSERT INTO reliability_controls_restore_blocks SELECT 'eval_job:'||id FROM reliability_eval_jobs ON CONFLICT DO NOTHING", ()),
        ("INSERT INTO reliability_controls_restore_blocks SELECT 'routing_policy:'||workspace_id||':'||revision FROM reliability_route_policies ON CONFLICT DO NOTHING", ()),
        ('INSERT INTO workspace_expansion_restore_blocks SELECT id FROM workspace_factory_reviews ON CONFLICT DO NOTHING', ()),
        ("INSERT INTO workspace_expansion_restore_blocks SELECT (payload::jsonb->>'id')||':'||revision FROM workspace_sdk_policies ON CONFLICT DO NOTHING", ()),
        ('INSERT INTO workspace_support_restore_blocks SELECT id FROM workspace_support_cases ON CONFLICT DO NOTHING', ()),
        ('INSERT INTO workspace_machine_update_restore_blocks SELECT id FROM workspace_machine_subscriptions ON CONFLICT DO NOTHING', ()),
        ('INSERT INTO workspace_machine_update_restore_blocks SELECT id FROM workspace_machine_update_events ON CONFLICT DO NOTHING', ()),
        ('INSERT INTO workspace_machine_receiver_restore_blocks SELECT id FROM workspace_machine_receivers ON CONFLICT DO NOTHING', ()),
        ('INSERT INTO reliability_research_restore_blocks SELECT id FROM reliability_research_manifests ON CONFLICT DO NOTHING', ()),
        ("INSERT INTO reliability_admission_restore_blocks SELECT workspace_id||':'||revision FROM reliability_admission_policies ON CONFLICT DO NOTHING", ()),
        ('INSERT INTO reliability_admission_restore_blocks SELECT id FROM reliability_admissions ON CONFLICT DO NOTHING', ()),
        ('INSERT INTO workspace_protocol_restore_blocks SELECT id FROM workspace_protocol_reports ON CONFLICT DO NOTHING', ()),
        ("INSERT INTO reliability_circuit_restore_blocks SELECT 'circuit:'||workspace_id||':'||CAST(resource_id AS TEXT)||':'||CAST(generation AS TEXT) FROM reliability_circuit_states ON CONFLICT DO NOTHING", ()),
        ("INSERT INTO reliability_circuit_restore_blocks SELECT 'source:'||workspace_id||':'||source_ref FROM reliability_circuit_claims ON CONFLICT DO NOTHING", ()),
    )
    with store.tx():
        inventory = {
            'unfinished_executions': store._execute("SELECT COUNT(*) FROM workflow_runs WHERE status IN ('queued','running')").fetchone()[0],
            'unfinished_deliveries': store._execute("SELECT COUNT(*) FROM workflow_result_outbox WHERE status IN ('pending','claimed','dispatched')").fetchone()[0],
            'verified_destinations': store._execute("SELECT COUNT(*) FROM workflow_destinations WHERE state='verified'").fetchone()[0],
            'active_workspaces': store._execute('SELECT COUNT(*) FROM organization_workspaces WHERE active=1').fetchone()[0],
            'active_customer_organizations': store._execute('SELECT COUNT(*) FROM customer_organizations WHERE active=1').fetchone()[0],
            'unrevoked_delivery_grants': store._execute('SELECT COUNT(*) FROM workflow_delivery_grants WHERE revoked IS NULL').fetchone()[0],
            'research_manifests': store._execute('SELECT COUNT(*) FROM reliability_research_manifests').fetchone()[0],
            'single_admission_policies': store._execute('SELECT COUNT(*) FROM reliability_admission_policies').fetchone()[0],
            'single_admissions': store._execute('SELECT COUNT(*) FROM reliability_admissions').fetchone()[0],
            'protocol_reports': store._execute('SELECT COUNT(*) FROM workspace_protocol_reports').fetchone()[0],
            'configured_circuits': store._execute('SELECT COUNT(*) FROM reliability_circuit_states').fetchone()[0],
            'consumed_circuit_observations': store._execute('SELECT COUNT(*) FROM reliability_circuit_claims').fetchone()[0],
        }
        for sql, parameters in statements:
            store._execute(sql, parameters).close()
        if store._execute("SELECT to_regclass('public.workspace_sandbox_payment_intents') IS NOT NULL").fetchone()[0]:
            store._execute('''INSERT INTO workspace_sandbox_payment_restore_blocks
                SELECT id FROM workspace_sandbox_payment_intents ON CONFLICT DO NOTHING''').close()
        # Distribution is private terminal metadata, never a resend instruction.
        rows = store._execute("SELECT id,result FROM workflow_runs WHERE id IN (SELECT run_id FROM workflow_result_outbox WHERE status='unknown')").fetchall()
        for identity, raw in rows:
            if raw:
                value = json.loads(raw); value['final_deliverable']['distribution'] = {'status': 'UNKNOWN'}
                store._execute('UPDATE workflow_runs SET result=%s WHERE id=%s', (json.dumps(value, separators=(',', ':')), identity)).close()
    return {'runtime_controls': 'paused', 'unfinished_execution': 'unknown', 'old_authority_reactivated': False,
            'automatic_replay': False, 'provider_calls': 0, 'delivery_calls': 0,
            'review_inventory': inventory, 'reapproval': 'Establish current owners independently; issue new grants, proofs, releases and one-run consent. Never replay unresolved outcomes.'}


def restore(connection, directory, *, workflow_key, cluster, tools):
    key = _key(workflow_key); target, commands = _private(connection, cluster), _tools(tools)
    if (_query(connection, "SELECT COUNT(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='public'")[0][0] != 0
            or _query(connection, "SELECT COUNT(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON p.pronamespace=n.oid WHERE n.nspname='public'")[0][0] != 0):
        raise NativeArchiveUnavailable('new_empty_target_required')
    directory = Path(directory)
    raw = _read(directory / 'manifest.json', 32768)
    manifest = _json(raw); signature = manifest.pop('signature', None)
    keys = ArtifactKeys(); signer = ArtifactSigner(hmac.new(key, PROFILE.encode(), hashlib.sha256).digest(), PROFILE, keys)
    if (not signer.verify(manifest, signature) or manifest.get('profile') != PROFILE or manifest.get('version') != 1
            or type(manifest.get('encrypted')) is not bool or manifest.get('schema_sha256') != _schema_hash()
            or not hmac.compare_digest(str(manifest.get('workflow_key_custody', '')), _custody(key))):
        raise NativeArchiveUnavailable('archive_authentication_failed')
    source = directory / ('application.dump.sealed' if manifest['encrypted'] else 'application.dump')
    content = _read(source, 180000000 if manifest['encrypted'] else MAX_ARCHIVE_BYTES)
    if hashlib.sha256(content).hexdigest() != manifest['archive_sha256']:
        raise NativeArchiveUnavailable('archive_authentication_failed')
    # The target is caller-owned, empty, private and unpublished. Return no Store
    # until the restore and native quarantine have both completed successfully.
    with tempfile.TemporaryDirectory(prefix='archive-restore-', dir=target['root']) as temporary:
        artifact = Path(temporary) / 'authenticated.dump'
        if manifest['encrypted']:
            content = ArtifactCipher(PROFILE, keys).open(content,
                {'profile': PROFILE, 'created': manifest['created'], 'schema_sha256': manifest['schema_sha256']})
        # Always restore the already authenticated bytes, preventing an artifact
        # path replacement between checksum validation and pg_restore opening.
        exclusive(artifact, content)
        # A freshly created PostgreSQL database already contains an empty public
        # schema. The authenticated dump creates it itself. Never use CASCADE or
        # --clean: any unexpected concurrently created object aborts this step.
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA IF EXISTS public')
        _run(commands['pg_restore'], target, ['--single-transaction', '--exit-on-error', '--no-owner', '--no-privileges', str(artifact.resolve())])
        from .storage_adapter import open_store
        store = open_store('postgresql', connection=connection, initialize=False, workflow_key=key)
        try:
            _objects(connection)
            result = quarantine(store)
        finally:
            store.close()
    return {**result, 'profile': PROFILE, 'encrypted': manifest['encrypted'], 'workflow_key_included': False,
            'operating_backup_ready': False}

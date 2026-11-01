"""Restore a private backup only into a disposable PostgreSQL cluster."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def rehearse(backup):
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, _tools, PORT
    from agent_market.storage_adapter import open_store
    from agent_market.service_runtime import ServiceControl
    backup = Path(backup).resolve()
    manifest = json.loads((backup / 'manifest.json').read_text())
    digest = hashlib.sha256()
    with (backup / 'database.dump').open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != manifest['files']['database.dump']['sha256']:
        raise ValueError('backup_digest_mismatch')
    began = time.monotonic()
    tools = {name: '/opt/homebrew/opt/postgresql@18/bin/' + name for name in ('initdb', 'pg_ctl')}
    with _private_cluster(tools) as cluster:
        environment = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
        result = subprocess.run(['/opt/homebrew/opt/postgresql@18/bin/pg_restore',
            '--exit-on-error', '--no-owner', '--no-acl', '--jobs=2',
            '--host', cluster['socket'], '--port', str(PORT), '--username', 'postgres', '--dbname', 'postgres',
            str(backup / 'database.dump')], env=environment, capture_output=True, timeout=900)
        if result.returncode:
            diagnostic = backup / 'restore-error.private.log'
            descriptor = os.open(diagnostic, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(result.stderr)
            raise RuntimeError('isolated_restore_failed')
        connection = psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        key = (backup / 'workflow.key').read_bytes()
        store = None
        control_connection = psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        control = ServiceControl(control_connection, key)
        try:
            control.install()
            counts = {table: connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                      for table in ('resources', 'agent_test_reports', 'workflow_runs', 'workspace_typed_flow_runs')}
            assert counts['resources'] > 0 and control.ready()
            # A copied migration gate is intentionally tied to the original DB
            # identity. Validate that restoration does not silently authorize a
            # second writer. App rollback uses the original, unchanged database.
            from agent_market.application_store_postgres import ApplicationStoreError, PROFILE
            profile = connection.execute('SELECT profile FROM application_store_state WHERE id=1').fetchone()[0]
            assert profile == PROFILE
            quarantined = False
            try:
                store = open_store('postgresql', connection=connection, workflow_key=key,
                                   required_capabilities=('full_application', 'service_runtime'))
            except ApplicationStoreError as error:
                if str(error) != 'migration_target_quarantined':
                    raise
                quarantined = True
            result = {'restore_rehearsed': True, 'isolated_cluster': True, 'production_modified': False,
                      'completed': time.time(), 'backup_sha256': digest.hexdigest(),
                      'schema_profile_marker_verified': True, 'control_schema_installed': True,
                      'copied_writer_gate_preserved': quarantined,
                      'restored_database_activated': False,
                      'counts': counts, 'seconds': round(time.monotonic() - began, 3)}
        finally:
            control.close()
            if store is not None:
                store.close()
            connection.close()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    result = rehearse(args.backup)
    Path(args.report).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))

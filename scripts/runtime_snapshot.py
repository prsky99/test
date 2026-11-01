"""Create a private, consistent database and source rollback snapshot.

Never prints credentials or connection strings. This command does not stop a
service, migrate a schema, or restore data. Run from the project directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

from scripts.agentcon_config import read_settings
from agent_market.application_runtime import _private_bytes, _connect


def snapshot(destination, settings_file, resume=False):
    destination = Path(destination).resolve()
    destination.mkdir(mode=0o700, parents=True, exist_ok=resume)
    if destination.is_symlink() or destination.stat().st_mode & 0o077:
        raise ValueError('private_snapshot_directory_required')
    settings = read_settings(settings_file)
    if settings.get('APPLICATION_STORE_BACKEND') != 'postgresql':
        raise ValueError('postgres_profile_required')
    dsn = _private_bytes(settings['APPLICATION_POSTGRES_DSN_FILE'], 16384).decode().strip()
    from psycopg.conninfo import conninfo_to_dict
    options = conninfo_to_dict(dsn)
    tools_path = '/opt/homebrew/opt/postgresql@18/bin:' + os.environ.get('PATH', '')
    dump = shutil.which('pg_dump', path=tools_path)
    restore = shutil.which('pg_restore', path=tools_path)
    if not dump or not restore:
        raise ValueError('postgres_backup_tools_required')
    environment = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    environment.update(PGPASSFILE=os.devnull, PGSERVICEFILE=os.devnull,
                       PGSSLMODE='verify-full', PGGSSENCMODE='disable', PGCONNECT_TIMEOUT='5')
    for name, value in options.items():
        environment['PG' + ('DATABASE' if name == 'dbname' else name.upper())] = value
    began = time.time()
    with _connect(dsn) as connection:
        connection.execute('BEGIN READ ONLY')
        db = connection.execute("SELECT current_setting('server_version'), pg_database_size(current_database())").fetchone()
        resources = connection.execute('SELECT count(*) FROM resources').fetchone()[0]
        connection.rollback()
    target = destination / 'database.dump'
    if not (resume and target.is_file() and not target.is_symlink()):
        with target.open('xb') as stream:
            os.chmod(target, 0o600)
            result = subprocess.run([dump, '--format=custom', '--no-owner', '--no-acl'],
                                    env=environment, stdout=stream, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError('database_dump_failed')
    result = subprocess.run([restore, '--list', str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode or b'TOC Entries' not in result.stdout:
        raise RuntimeError('database_dump_catalog_invalid')
    root = Path.cwd()
    archive = destination / 'source.tar.gz'
    source_paths = ['agent_market', 'scripts', 'deploy', 'new', 'agentcon', 'AGENTS.md',
                    'extracted_html.txt', 'pyproject.toml', 'requirements.txt', 'requirements-dev.txt']
    def accept(info):
        parts = Path(info.name).parts
        if any(p in {'__pycache__', '.DS_Store', 'node_modules', '.pytest_cache'} for p in parts):
            return None
        if info.issym() or info.islnk():
            raise ValueError('source_snapshot_symlink_refused')
        return info
    with tarfile.open(archive, 'w:gz', dereference=True) as tar:
        os.chmod(archive, 0o600)
        for name in source_paths:
            if (root / name).exists():
                tar.add(root / name, arcname=name, filter=accept)
    # Recovery needs the original encryption key and runtime profile as well.
    for name, path in [('runtime.env', settings_file), ('workflow.key', settings['APPLICATION_WORKFLOW_KEY_FILE']),
                       ('postgres.dsn', settings['APPLICATION_POSTGRES_DSN_FILE'])]:
        data = _private_bytes(str(path), 65536)
        out = destination / name
        descriptor = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
    files = {}
    for item in (target, archive):
        digest = hashlib.sha256()
        with item.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        files[item.name] = {'bytes': item.stat().st_size, 'sha256': digest.hexdigest()}
    manifest = {'created': began, 'finished': time.time(), 'postgres_version': db[0],
                'database_bytes': db[1], 'catalog_resources_at_baseline': resources,
                'dump_catalog_checked': True, 'restore_rehearsed': False, 'files': files}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--settings', default='gateway-data/agentcon.env')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(snapshot(args.destination, args.settings, args.resume), indent=2))
    except Exception as error:
        import traceback
        where = traceback.extract_tb(error.__traceback__)[-1]
        raise SystemExit(f'Snapshot incomplete: {type(error).__name__} at {where.name}:{where.lineno}. Preserve private files.') from None

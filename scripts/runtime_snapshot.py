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
from agent_market.application_runtime import _ABSENT_PASSFILE, _private_bytes, _connect


# Precision review R51 (11-15): state that lives outside the database and the source tree. Relative to the project
# root; a missing path is listed, never an error (some appear later, such as the signing folder from 11-17).
STATE_PATHS = ('gateway-data/necklaces', 'gateway-data/fingerprints', 'exports/pearls', 'gateway-data/ofac',
               'gateway-data/web-bot-auth', 'gateway-data/web-bot-signer.env', 'gateway-data/sponsored.env',
               'gateway-data/house-ad.env', 'gateway-data/edge-gateway.env', 'gateway-data/edge-gateway.json',
               'gateway-data/edge-gateway.worker-secrets.json', 'gateway-data/services/state.json',
               'gateway-data/services/pinned-releases.txt', 'gateway-data/signing', 'logs/ops/status-board.md',
               'logs/ops/user-slo.jsonl', 'logs/ops/error-ledger-known.json', 'logs/ops/error-ledger-windows.json',
               'logs/ops/necklace-gate')


def copy_state(root, destination, paths=STATE_PATHS):
    """Archive the state files into destination/state.tar.gz (owner-only) and return each file's sha256.
    Symbolic links are skipped and listed; an unreadable file fails the snapshot (exit non-zero)."""
    root = Path(root)
    archive = destination / 'state.tar.gz'
    files, missing, skipped = {}, [], []
    with tarfile.open(archive, 'w:gz') as tar:
        os.chmod(archive, 0o600)
        for name in paths:
            path = root / name
            if not path.exists() and not path.is_symlink():
                missing.append(name)
                continue
            items = [path] if not path.is_dir() or path.is_symlink() else sorted(
                p for p in path.rglob('*') if p.is_file() or p.is_symlink())
            for item in items:
                relative = str(item.relative_to(root))
                if item.is_symlink():
                    skipped.append(relative)
                    continue
                data = item.read_bytes()
                files[relative] = hashlib.sha256(data).hexdigest()
                info = tarfile.TarInfo(relative)
                info.size, info.mtime, info.mode = len(data), int(item.stat().st_mtime), 0o600
                import io
                tar.addfile(info, io.BytesIO(data))
    return {'files': files, 'missing': missing, 'skipped_symlinks': skipped}


def copy_key_directory(source, target):
    """Copy every regular file of a private key directory (owner-only, 0600) and return their digests.
    No directory configured means nothing to copy; a key that cannot be read privately fails the snapshot."""
    if not source:
        return {}
    source = Path(source)
    if not source.is_dir() or source.is_symlink():
        raise ValueError('ad_coin_key_directory_missing')
    target.mkdir(mode=0o700, exist_ok=True)
    digests = {}
    for item in sorted(source.iterdir()):
        if item.name.startswith('.') or item.is_dir():
            continue
        data = _private_bytes(str(item), 65536)
        out = target / item.name
        if out.exists():
            out.unlink()
        descriptor = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        digests[item.name] = hashlib.sha256(data).hexdigest()
    return digests


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
    environment.update(PGPASSFILE=_ABSENT_PASSFILE, PGSERVICEFILE=os.devnull,
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
    # The project root, also when the backup job runs from gateway-data/ops-code/current (R05): that folder links
    # gateway-data to the project's, and holds only agent_market, scripts and deploy/ops of one commit.
    root = Path(os.path.realpath(Path.cwd() / 'gateway-data')).parent
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
    # 11-10: AI AD Coin v2 keys (owner link, ledger signing). Losing owner-link.key would show every site
    # user as a new v2 account with no balance; they are as critical as workflow.key.
    keys = copy_key_directory(settings.get('AD_COIN_V2_KEY_DIR'), destination / 'ad_coin_v2_keys')
    state = copy_state(root, destination)
    files = {}
    for item in (target, archive, destination / 'state.tar.gz'):
        digest = hashlib.sha256()
        with item.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        files[item.name] = {'bytes': item.stat().st_size, 'sha256': digest.hexdigest()}
    manifest = {'created': began, 'finished': time.time(), 'postgres_version': db[0],
                'database_bytes': db[1], 'catalog_resources_at_baseline': resources,
                'dump_catalog_checked': True, 'restore_rehearsed': False, 'files': files,
                'ad_coin_v2_keys': keys, 'state_files': state['files'], 'state_missing': state['missing'],
                'state_skipped_symlinks': state['skipped_symlinks']}
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

"""Take one private runtime snapshot and keep only the newest few.

Meant for the daily launchd job biz.agentconcierge.backup. It wraps
scripts.runtime_snapshot, so each snapshot holds the database dump, the source
archive and the keys needed to restore. It waits while the application holds
many connections, so the dump never takes the last free slot. Never prints
credentials or connection strings. Run from the project directory:
    .venv/bin/python -m scripts.scheduled_backup
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import time

from scripts.agentcon_config import read_settings
from scripts.runtime_snapshot import snapshot
from agent_market.application_runtime import _private_bytes, _connect

PREFIX = 'snapshot-'


def app_connections(settings_file):
    settings = read_settings(settings_file)
    dsn = _private_bytes(settings['APPLICATION_POSTGRES_DSN_FILE'], 16384).decode().strip()
    with _connect(dsn) as connection:
        count = connection.execute(
            'SELECT count(*) FROM pg_stat_activity WHERE usename = current_user').fetchone()[0]
        connection.rollback()
    # Our own check connection is not part of the application's load.
    return count - 1


def prune(root, keep):
    """Remove completed snapshots beyond the newest `keep`, and failed leftovers."""
    entries = sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and p.name.startswith(PREFIX))
    complete = [p for p in entries if (p / 'manifest.json').is_file()]
    removed = []
    for path in complete[:-keep] if keep else complete:
        shutil.rmtree(path)
        removed.append(path.name)
    newest = complete[-1].name if complete else None
    for path in entries:
        if path not in complete and newest and path.name < newest:
            shutil.rmtree(path)
            removed.append(path.name)
    return removed


def copy_offsite(source, target_root, keep, mounted=os.path.ismount):
    """Copy one completed snapshot to another machine's mounted share.

    The share root (the parent of target_root) must be a mount point, so an
    unmounted share never fills a stray local folder under /Volumes.
    """
    target_root = Path(target_root)
    if not mounted(str(target_root.parent)):
        return {'status': 'skipped', 'reason': 'share_not_mounted'}
    target_root.mkdir(mode=0o700, exist_ok=True)
    final = target_root / source.name
    if (final / 'manifest.json').is_file():
        return {'status': 'ok', 'snapshot': final.name, 'removed': [], 'already': True}
    partial = target_root / ('.partial-' + source.name)
    if partial.exists():
        shutil.rmtree(partial)
    shutil.copytree(source, partial, copy_function=shutil.copyfile)
    manifest = json.loads((source / 'manifest.json').read_text())
    for name, info in manifest['files'].items():
        if (partial / name).stat().st_size != info['bytes']:
            shutil.rmtree(partial)
            raise RuntimeError('offsite_copy_size_mismatch')
    # AI AD Coin v2 keys must arrive byte for byte (11-10).
    import hashlib
    for name, digest in (manifest.get('ad_coin_v2_keys') or {}).items():
        copied = partial / 'ad_coin_v2_keys' / name
        if not copied.is_file() or hashlib.sha256(copied.read_bytes()).hexdigest() != digest:
            shutil.rmtree(partial)
            raise RuntimeError('offsite_key_copy_mismatch')
    partial.rename(final)
    return {'status': 'ok', 'snapshot': final.name, 'removed': prune(target_root, keep)}


def latest(root):
    complete = sorted(p for p in Path(root).iterdir() if p.name.startswith(PREFIX) and (p / 'manifest.json').is_file())
    if not complete:
        raise ValueError('no_complete_snapshot')
    return complete[-1]


def run(root, settings_file, keep=7, limit=19, attempts=6, wait=300, copy_to=None,
        count=app_connections, take=snapshot, sleep=time.sleep, now=time.localtime, copy=copy_offsite):
    root = Path(root).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise ValueError('private_backup_directory_required')
    for attempt in range(attempts):
        busy = count(settings_file)
        if busy <= limit:
            break
        if attempt + 1 < attempts:
            sleep(wait)
    else:
        return {'status': 'skipped', 'reason': 'connections_busy', 'app_connections': busy}
    destination = root / (PREFIX + time.strftime('%Y%m%d-%H%M%S', now()))
    manifest = take(destination, settings_file)
    result = {'status': 'ok', 'snapshot': destination.name, 'app_connections': busy,
              'seconds': round(manifest['finished'] - manifest['created']),
              'database_dump_bytes': manifest['files']['database.dump']['bytes'],
              'removed': prune(root, keep)}
    if copy_to:
        # A failed copy keeps the local snapshot; the next day copies again.
        try:
            result['offsite'] = copy(destination, copy_to, keep)
        except Exception as error:
            result['offsite'] = {'status': 'failed', 'error': type(error).__name__}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='gateway-data/backups/daily')
    parser.add_argument('--settings', default='gateway-data/agentcon.env')
    parser.add_argument('--keep', type=int, default=7)
    parser.add_argument('--max-app-connections', type=int, default=19)
    parser.add_argument('--copy-to', help='folder on a mounted share, e.g. /Volumes/<share>/agentconcierge-backups')
    parser.add_argument('--copy-only', action='store_true', help='copy the newest local snapshot without taking one')
    args = parser.parse_args()
    started = time.strftime('%Y-%m-%dT%H:%M:%S')
    try:
        if args.copy_only:
            result = {'offsite': copy_offsite(latest(Path(args.root).resolve()), args.copy_to, args.keep)}
            result['status'] = result['offsite']['status']
        else:
            result = run(args.root, args.settings, args.keep, args.max_app_connections, copy_to=args.copy_to)
    except Exception as error:
        import traceback
        where = traceback.extract_tb(error.__traceback__)[-1]
        print(json.dumps({'started': started, 'status': 'failed',
                          'error': f'{type(error).__name__} at {where.name}:{where.lineno}'}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps({'started': started, **result}), flush=True)
    if result['status'] != 'ok':
        raise SystemExit(2)

"""Re-admit only the reviewed October 20 registry-loss cohort for local checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from agent_market.application_writer_fence import assert_sqlite_writer_allowed
from agent_market.managed_catalog import ensure_schema

# Last-seen window of the independently reconciled 20,863-row incident cohort.
START, END = 1792249200, 1792335600  # 2026-10-18 00:00 to 10-19 00:00 Asia/Seoul.
FIELDS = 'id,key,active,health_status,next_check_at,last_seen,last_check_at,eval_security'


def begin_write(db):
    deadline = time.monotonic() + 20
    while True:
        try:
            db.execute('BEGIN IMMEDIATE')
            return
        except sqlite3.OperationalError as error:
            if 'locked' not in str(error).lower() or time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def candidates(db):
    return [dict(row) for row in db.execute(f'''SELECT {FIELDS} FROM resources r
        WHERE source='x402-bazaar' AND active=0 AND last_seen>=? AND last_seen<?
        AND COALESCE(eval_security,'')!='quarantine'
        AND NOT EXISTS(SELECT 1 FROM admin_audit_logs a WHERE a.action='AGENT_DEACTIVATE'
          AND a.status='SUCCESS' AND a.target='agent:'||r.id)
        ORDER BY id''', (START, END))]


def recover(path, *, expected_count, apply=False, backup_dir=None):
    supplied = Path(path)
    if supplied.is_symlink() or not supplied.is_file() or supplied.stat().st_uid != os.getuid():
        raise ValueError('owned_regular_database_required')
    if type(expected_count) is not int or not 0 <= expected_count <= 20863:
        raise ValueError('reviewed_cohort_size_required')
    path = supplied.resolve()
    db = sqlite3.connect(path.as_uri() + ('?mode=rw' if apply else '?mode=ro'), uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    if apply:
        from agent_market.gateway.rag import load_sqlite_vec
        load_sqlite_vec(db)
    if not apply:
        db.execute('PRAGMA query_only=ON')
    try:
        rows = candidates(db)
        if len(rows) != expected_count:
            raise ValueError('reviewed_cohort_changed')
        result = {'eligible': len(rows), 'previously_checked': sum(row['last_check_at'] is not None for row in rows),
                  'applied': 0, 'health_evidence_created': 0,
                  'provider_requests': 0, 'backup_created': False}
        if not apply or not rows:
            return result
        if not backup_dir:
            raise ValueError('private_backup_directory_required')
        directory = Path(backup_dir)
        if directory.is_symlink():
            raise ValueError('private_backup_directory_required')
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
            raise ValueError('private_backup_directory_required')
        document = json.dumps({'profile': 'registry-loss-local-management-v1', 'at': time.time(),
                               'rows': rows}, sort_keys=True).encode()
        backup = directory / ('registry-loss-' + hashlib.sha256(document).hexdigest() + '.json')
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        result['backup_created'] = True
        with db:
            begin_write(db)
            assert_sqlite_writer_allowed(db)
            ensure_schema(db)
        for start in range(0, len(rows), 250):
            with db:
                begin_write(db)
                assert_sqlite_writer_allowed(db)
                for row in rows[start:start + 250]:
                    fresh = db.execute(f'SELECT {FIELDS},inactive_reason FROM resources WHERE id=?', (row['id'],)).fetchone()
                    if fresh is None or any(fresh[key] != value for key, value in row.items()) or fresh['inactive_reason']:
                        raise ValueError('cohort_row_changed')
                    # Preserve failure duration/counters; do not claim stale healthy states as fresh.
                    db.execute('''UPDATE resources SET active=1,
                        health_status=CASE WHEN health_status IN ('healthy','reachable') THEN 'unknown' ELSE health_status END,
                        next_check_at=NULL,registry_missing_since=?,managed_at=COALESCE(managed_at,last_check_at)
                        WHERE id=?''', (time.time(), row['id']))
                    db.execute("INSERT OR REPLACE INTO vec_outbox(resource_id,enqueued_at,reason) VALUES(?,?,'local-management-recovery')", (row['id'], time.time()))
            result['applied'] += len(rows[start:start + 250])
            journal = backup.with_suffix('.progress.jsonl')
            descriptor = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(descriptor, 'a') as stream:
                stream.write(json.dumps({'at': time.time(), 'applied': result['applied'],
                    'ids': [row['id'] for row in rows[start:start + 250]]}) + '\n')
            time.sleep(0.02)  # Let independent operational writers acquire the lock between batches.
        result['backup_sha256'] = hashlib.sha256(document).hexdigest()
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--expected-count', type=int, required=True)
    parser.add_argument('--backup-dir')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(recover(args.db, expected_count=args.expected_count, apply=args.apply,
                             backup_dir=args.backup_dir), sort_keys=True))


if __name__ == '__main__':
    main()

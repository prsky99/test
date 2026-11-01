"""Keep the newest report per proven subject; dry run unless --apply is given.

Gateway addresses contain historical database-local IDs. They require the same
normalized report name as well, rather than borrowing today's resource binding.
No service, catalog resource, execution evidence or report content is created.
"""
import argparse
import collections
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import sys
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_market.concierge.report_evidence import canonical_endpoint, _name
from scripts.repair_report_bindings import _packed


class CleanupError(ValueError):
    """Bounded operational errors without exposing report contents."""


def _timestamp(value):
    if type(value) in (int, float):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value)
        except ValueError:
            try:
                parsed = datetime.datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
                # Historical SQLite CURRENT_TIMESTAMP values are UTC.
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                result = parsed.timestamp()
            except (ValueError, OverflowError):
                raise CleanupError('unorderable_report_timestamp') from None
    else:
        raise CleanupError('unorderable_report_timestamp')
    if not math.isfinite(result) or result <= 0:
        raise CleanupError('unorderable_report_timestamp')
    return result


def _subject(row):
    endpoint = canonical_endpoint(row['agent_url'])
    if row['kind'] not in ('a2a', 'mcp', 'x402') or endpoint is None:
        return None
    if endpoint[1] == 'agentconcierge.biz' and endpoint[3].startswith('/api/gateway/'):
        name = _name(row['agent_name'])
        return ('gateway', row['kind'], endpoint, name) if name else None
    return ('provider', row['kind'], endpoint)


def plan(rows):
    groups = collections.defaultdict(list)
    unresolved = 0
    for row in rows:
        subject = _subject(row)
        if subject is None:
            unresolved += 1
        else:
            groups[subject].append(row)
    changes = []
    unorderable = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        try:
            ordered = sorted(group, key=lambda row: (_timestamp(row['created_at']), row['id']), reverse=True)
        except CleanupError:
            unorderable += 1
            continue
        keys = {row['creation_subject_key'] for row in ordered if row['creation_subject_key']}
        if len(keys) > 1:
            raise CleanupError('inconsistent_subject_reservations')
        changes.append({'keep': ordered[0], 'delete': ordered[1:],
                        'creation_subject_key': next(iter(keys), None)})
    return {'changes': changes, 'total': len(rows), 'unresolved': unresolved,
            'unorderable_groups': unorderable}


def _rows(db):
    return [dict(row) for row in db.execute('SELECT * FROM agent_test_reports ORDER BY id')]


def _signature(rows):
    return hashlib.sha256(_packed(rows)).hexdigest()


def _references(db):
    for table in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall():
        if (table['sql'] or '').upper().startswith('CREATE VIRTUAL TABLE'):
            continue
        quoted = '"' + table['name'].replace('"', '""') + '"'
        for reference in db.execute('PRAGMA foreign_key_list(' + quoted + ')'):
            if reference['table'] == 'agent_test_reports' and (
                    table['name'], reference['from'], reference['to']) != (
                    'test_report_subject_claims', 'report_id', 'id'):
                raise CleanupError('unsupported_report_reference')


def _backup(directory, rows, claims, changes):
    return _private_backup(directory, 'report-deduplication-', {
        'format': 'report-deduplication-backup-v1',
        'created_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'reports': rows, 'claims': claims,
        'keep_delete_mapping': [{'keep_id': change['keep']['id'],
            'delete_ids': [row['id'] for row in change['delete']]} for change in changes]})


def _private_backup(directory, prefix, document):
    """Durably save a full operational snapshot before opening deletion paths."""
    directory = Path(directory).absolute()
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise CleanupError('backup_directory_not_private')
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(directory_fd)
        if ((opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                or opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) != 0o700):
            raise CleanupError('backup_directory_changed')
        filename = prefix + uuid.uuid4().hex + '.json'
        payload = _packed(document)
        fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0),
                     0o600, dir_fd=directory_fd)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory_fd)
        return str(directory / filename)
    finally:
        os.close(directory_fd)


def cleanup(path, *, apply=False, backup_dir=None):
    supplied = Path(path)
    if supplied.is_symlink():
        raise CleanupError('regular_owned_database_required')
    path = supplied.resolve(strict=True)
    if not path.is_file() or path.stat().st_uid != os.getuid():
        raise CleanupError('regular_owned_database_required')
    if apply and not backup_dir:
        raise CleanupError('private_backup_directory_required')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    try:
        before = _rows(db)
        _references(db)
        planned = plan(before)
    finally:
        db.close()
    backup = None
    deleted = sum(len(change['delete']) for change in planned['changes'])
    if apply and deleted:
        db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            from agent_market.application_writer_fence import assert_sqlite_writer_allowed
            assert_sqlite_writer_allowed(db)
            fresh = _rows(db)
            if _signature(before) != _signature(fresh):
                raise CleanupError('reports_changed_since_preflight')
            _references(db)
            claims = [dict(row) for row in db.execute('SELECT * FROM test_report_subject_claims')]
            backup = _backup(backup_dir, fresh, claims, planned['changes'])
            expected_rows = {row['id']: dict(row) for row in before}
            for change in planned['changes']:
                keep = change['keep']
                for old in change['delete']:
                    db.execute('UPDATE test_report_subject_claims SET report_id=? WHERE report_id=?',
                               (keep['id'], old['id']))
                    if db.execute('DELETE FROM agent_test_reports WHERE id=?', (old['id'],)).rowcount != 1:
                        raise CleanupError('unexpected_delete_result')
                    del expected_rows[old['id']]
                expected = dict(keep)
                key = change['creation_subject_key']
                if key and not keep['creation_subject_key']:
                    db.execute('UPDATE agent_test_reports SET creation_subject_key=? WHERE id=?', (key, keep['id']))
                    expected['creation_subject_key'] = key
                expected_rows[keep['id']] = expected
                actual = db.execute('SELECT * FROM agent_test_reports WHERE id=?', (keep['id'],)).fetchone()
                if actual is None or dict(actual) != expected:
                    raise CleanupError('retained_report_changed')
            remaining = _rows(db)
            if len(remaining) != len(before) - deleted:
                raise CleanupError('unexpected_remaining_count')
            if remaining != sorted(expected_rows.values(), key=lambda row: row['id']):
                raise CleanupError('unexpected_surviving_report_change')
            if db.execute('''SELECT 1 FROM test_report_subject_claims c
                LEFT JOIN agent_test_reports r ON r.id=c.report_id
                WHERE c.report_id IS NOT NULL AND r.id IS NULL LIMIT 1''').fetchone():
                raise CleanupError('dangling_report_reservation')
            db.commit()
        finally:
            db.close()
    return {'mode': 'apply' if apply else 'dry_run', 'reports_before': len(before),
            'duplicate_groups': len(planned['changes']), 'eligible_deletions': deleted,
            'deleted': deleted if apply else 0, 'reports_after': len(before) - deleted if apply else len(before),
            'unresolved_subjects': planned['unresolved'], 'unorderable_groups': planned['unorderable_groups'],
            'backup_file': backup}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--db', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir')
    args = parser.parse_args(argv)
    try:
        result = cleanup(args.db, apply=args.apply, backup_dir=args.backup_dir)
    except (CleanupError, OSError, sqlite3.Error, ValueError, TypeError) as error:
        code = str(error) if isinstance(error, CleanupError) else 'database_or_backup_error'
        print(json.dumps({'ok': False, 'error': code}))
        return 1
    print(json.dumps({'ok': True, **result}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

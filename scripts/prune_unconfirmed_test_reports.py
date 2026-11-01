"""Retain the explicitly reviewed public report subjects; default to dry run.

Uses Explore's shared subject predicate, including historical agents. Expected
counts pin the authorized scope. No report content, resources, execution evidence,
subject reservations, or creation guards are rewritten.
"""
import argparse
import collections
import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_market.application_writer_fence import assert_sqlite_writer_allowed
from agent_market.concierge.connections import gateway_agent_url
from agent_market.concierge.report_evidence import canonical_endpoint, report_subject_matches
from scripts.deduplicate_test_reports import CleanupError, _private_backup, _references, _rows, _signature


def plan(db, rows):
    kept, deleted, resources = [], [], {}
    for report in rows:
        rid = report.get('resource_id')
        if rid not in resources:
            row = db.execute('''SELECT id,kind,name,url,active,health_status,eval_security
                                FROM resources WHERE id=?''', (rid,)).fetchone()
            resources[rid] = dict(row) if row is not None else None
        resource = resources[rid]
        matches = False
        if (resource and resource['kind'] in ('a2a', 'mcp', 'x402')
                and resource.get('eval_security') != 'quarantine'
                and resource.get('health_status') != 'quarantined'):
            gateway = canonical_endpoint(gateway_agent_url(resource['id'], resource['kind']))
            if canonical_endpoint(report.get('agent_url')) == gateway:
                # Gateway IDs alone are insufficient. Hash a complete version only
                # when the report actually provides a version to compare against.
                if report.get('connection_version_id'):
                    full = dict(db.execute('SELECT * FROM resources WHERE id=?', (rid,)).fetchone())
                    matches = report_subject_matches(report, full)
            else:
                matches = report_subject_matches(report, resource)
        (kept if matches else deleted).append(report)
    return {'keep_ids': [row['id'] for row in kept],
            'delete_ids': [row['id'] for row in deleted],
            'kept_agents': len({row['resource_id'] for row in kept}),
            'kept_by_kind': dict(collections.Counter(row['kind'] for row in kept))}


def _check_references(db, planned):
    _references(db)
    removed = set(planned['delete_ids'])
    claims = [dict(row) for row in db.execute('SELECT * FROM test_report_subject_claims ORDER BY subject_key')]
    if any(row['report_id'] in removed for row in claims):
        raise CleanupError('unconfirmed_report_has_subject_reservation')
    for row in db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='agent_test_reports'"):
        if re.search(r'\bDELETE\b', (row['sql'] or '').split('BEGIN', 1)[0], re.I):
            raise CleanupError('unreviewed_report_delete_trigger')
    return claims


def cleanup(path, *, expected_kept, expected_deleted, expected_kept_sha256=None,
            apply=False, backup_dir=None):
    supplied = Path(path)
    if supplied.is_symlink():
        raise CleanupError('regular_owned_database_required')
    path = supplied.resolve(strict=True)
    if not path.is_file() or path.stat().st_uid != os.getuid():
        raise CleanupError('regular_owned_database_required')
    if (type(expected_kept) is not int or expected_kept <= 0
            or type(expected_deleted) is not int or expected_deleted < 0):
        raise CleanupError('explicit_reviewed_counts_required')
    if apply and not backup_dir:
        raise CleanupError('private_backup_directory_required')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        before = _rows(db)
        planned = plan(db, before)
        claims = _check_references(db, planned)
        if (len(planned['keep_ids']) != expected_kept
                or len(planned['delete_ids']) != expected_deleted):
            raise CleanupError('reviewed_counts_changed')
        if expected_kept_sha256 is not None and _signature(planned['keep_ids']) != expected_kept_sha256:
            raise CleanupError('reviewed_retained_ids_changed')
    finally:
        db.close()
    backup = None
    if apply and planned['delete_ids']:
        db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            assert_sqlite_writer_allowed(db)
            fresh = _rows(db)
            if _signature(before) != _signature(fresh):
                raise CleanupError('reports_changed_since_preflight')
            if plan(db, fresh) != planned:
                raise CleanupError('report_subjects_changed_since_preflight')
            if _check_references(db, planned) != claims:
                raise CleanupError('report_reservations_changed_since_preflight')
            schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
            backup = _private_backup(backup_dir, 'report-subject-pruning-', {
                'format': 'report-subject-pruning-backup-v1',
                'created_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'reports': fresh, 'claims': claims, 'plan': planned,
                'reports_sha256': _signature(fresh)})
            for report_id in planned['delete_ids']:
                if db.execute('DELETE FROM agent_test_reports WHERE id=?', (report_id,)).rowcount != 1:
                    raise CleanupError('unexpected_delete_result')
            retained = set(planned['keep_ids'])
            expected = [row for row in before if row['id'] in retained]
            if _rows(db) != expected:
                raise CleanupError('unexpected_surviving_report_change')
            if _check_references(db, planned) != claims:
                raise CleanupError('unexpected_report_reservation_change')
            if db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall() != schema:
                raise CleanupError('unexpected_schema_change')
            if db.execute('''SELECT 1 FROM test_report_subject_claims c
                LEFT JOIN agent_test_reports r ON r.id=c.report_id
                WHERE c.report_id IS NOT NULL AND r.id IS NULL LIMIT 1''').fetchone():
                raise CleanupError('dangling_report_reservation')
            db.commit()
        finally:
            db.close()
    return {'mode': 'apply' if apply else 'dry_run', 'reports_before': len(before),
            'kept': len(planned['keep_ids']), 'eligible_deletions': len(planned['delete_ids']),
            'deleted': len(planned['delete_ids']) if apply else 0,
            'reports_after': len(planned['keep_ids']) if apply else len(before),
            'kept_agents': planned['kept_agents'], 'kept_by_kind': planned['kept_by_kind'],
            'kept_ids_sha256': _signature(planned['keep_ids']), 'backup_file': backup}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--db', required=True)
    parser.add_argument('--expected-kept', required=True, type=int)
    parser.add_argument('--expected-deleted', required=True, type=int)
    parser.add_argument('--expected-kept-sha256')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir')
    args = parser.parse_args(argv)
    try:
        result = cleanup(args.db, expected_kept=args.expected_kept,
                         expected_deleted=args.expected_deleted,
                         expected_kept_sha256=args.expected_kept_sha256,
                         apply=args.apply, backup_dir=args.backup_dir)
    except (CleanupError, OSError, sqlite3.Error, ValueError, TypeError) as error:
        code = str(error) if isinstance(error, CleanupError) else 'database_or_backup_error'
        print(json.dumps({'ok': False, 'error': code}))
        return 1
    print(json.dumps({'ok': True, **result}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Restore independently identified historical reports without creating execution evidence.

Read original direct endpoints from an older report database and literal authoring
metadata, never execute retired seed scripts. Preserve newest-per-provider rules,
creation reservations, identity triggers and original private backups.
"""
import argparse
import ast
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_market.application_writer_fence import assert_sqlite_writer_allowed
from agent_market.concierge.report_evidence import canonical_endpoint, _name, report_subject_matches
from agent_market.report_creation import reserve, finish
from scripts.deduplicate_test_reports import (
    _private_backup, _references, _rows, _signature, _timestamp,
)
from scripts.repair_report_bindings import _packed

FIELDS = ('slug', 'title', 'kind', 'agent_name', 'agent_url')
EXECUTION = ('executed_at', 'execution_finished_at', 'connection_version_id')
RESOURCE_FIELDS = 'id,key,kind,name,url,active,health_status,eval_security'
NOTICE = (
    '> Historical report restored from a retained backup. The subject connection '
    'has been repaired using the original provider endpoint. Retired gateway '
    'references are omitted; use the current connection details. Original '
    'outcomes and grades are historical records, not a new execution or a '
    'guarantee of current availability.\n\n'
)
GATEWAY_REFERENCE = re.compile(r'https://agentconcierge\.biz/api/gateway/(?:a2a|mcp|x402)/[0-9]+(?=$|[^0-9A-Za-z_/-])')
SUBJECT_ENDPOINT = re.compile(r'^\s*\|\s*\*\*(?:Primary )?Endpoint URL\*\*\s*\|\s*`(https?://[^`\s]+)`\s*\|\s*$', re.I)


class RestoreError(ValueError):
    """Bounded errors do not include private report or source content."""


def _open(path, readonly=True):
    supplied = Path(path)
    if supplied.is_symlink():
        raise RestoreError('regular_owned_file_required')
    supplied = supplied.resolve(strict=True)
    if not supplied.is_file() or supplied.stat().st_uid != os.getuid():
        raise RestoreError('regular_owned_file_required')
    db = sqlite3.connect(supplied.as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    if readonly:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
    return db


def _provider(url):
    endpoint = canonical_endpoint(url)
    if not endpoint or endpoint[1] == 'agentconcierge.biz' and endpoint[3].startswith('/api/gateway/'):
        return None
    return endpoint


def _legacy(row):
    return row.get('evidence_scope') in (None, 'legacy') and all(row.get(k) is None for k in EXECUTION)


def _matches_original(source, report):
    return (all(isinstance(source.get(k), str) for k in FIELDS)
            and all(source[k] == report[k] for k in ('slug', 'title', 'kind'))
            and _name(source['agent_name']) == _name(report['agent_name'])
            and _provider(source['agent_url']) is not None)


def load_backup(path, expected_deleted):
    supplied = Path(path)
    if supplied.is_symlink() or not supplied.is_file():
        raise RestoreError('regular_backup_required')
    document = json.loads(supplied.read_text())
    if document.get('format') != 'report-subject-pruning-backup-v1':
        raise RestoreError('unsupported_backup_format')
    reports = document['reports']
    if _signature(reports) != document.get('reports_sha256'):
        raise RestoreError('backup_integrity_mismatch')
    ids = document['plan']['delete_ids']
    kept = document['plan']['keep_ids']
    if (type(expected_deleted) is not int or expected_deleted <= 0
            or len(ids) != expected_deleted or len(set(ids)) != len(ids)
            or set(ids) & set(kept)
            or set(ids) | set(kept) != {row['id'] for row in reports}
            or len({row['id'] for row in reports}) != len(reports)
            or len({row['slug'] for row in reports}) != len(reports)):
        raise RestoreError('reviewed_backup_scope_mismatch')
    return [row for row in reports if row['id'] in set(ids)]


def provenance(reports, source_db, scripts_dir):
    """Retain complete endpoint identity; mentions of unrelated URLs are not proof."""
    by_slug = {row['slug']: row for row in reports}
    proofs = collections.defaultdict(list)
    sources = {}
    source = _open(source_db)
    try:
        for record in source.execute('SELECT * FROM agent_test_reports'):
            record = dict(record)
            report = by_slug.get(record.get('slug'))
            if report and _legacy(record) and _matches_original(record, report):
                proofs[report['id']].append({'endpoint': _provider(record['agent_url']),
                    'source': 'historical_database', 'digest': _signature(record)})
    finally:
        source.close()
    directory = Path(scripts_dir).resolve(strict=True)
    # The finite authoring formats are read with AST literal_eval, never imported.
    paths = sorted({*directory.glob('seed_*reports.py'), *directory.glob('insert_batch*.py'),
                    *directory.glob('generate_batches_*.py'), *directory.glob('build_batches_*.py')})
    for path in paths:
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise RestoreError('unsupported_authoring_source')
        raw = path.read_bytes()
        tree = ast.parse(raw)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            fields = {key.value: value for key, value in zip(node.keys, node.values)
                      if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            if not set(FIELDS).issubset(fields):
                continue
            try:
                record = {key: ast.literal_eval(fields[key]) for key in FIELDS}
            except (ValueError, TypeError):
                continue
            report = by_slug.get(record.get('slug')) if isinstance(record.get('slug'), str) else None
            if report and _matches_original(record, report):
                fingerprint = hashlib.sha256(raw).hexdigest()
                sources[path.name] = fingerprint
                proofs[report['id']].append({'endpoint': _provider(record['agent_url']),
                    'source': 'literal_authoring_metadata', 'file': path.name,
                    'source_sha256': fingerprint, 'digest': _signature(record)})
    # An explicit endpoint field in a subject's retained report is different
    # from an arbitrary citation. Require the current subject name as well.
    for report in reports:
        if proofs[report['id']]:
            continue
        endpoints = {_provider(match[1]) for line in report['content_md'].splitlines()
                     if (match := SUBJECT_ENDPOINT.fullmatch(line))}
        endpoints.discard(None)
        if len(endpoints) == 1:
            proofs[report['id']].append({'endpoint': next(iter(endpoints)),
                'source': 'explicit_report_subject_endpoint', 'require_same_name': True,
                'digest': _signature(report['content_md'])})
    return proofs, sources


def subject_key(kind, endpoint):
    return 'trs_' + hashlib.sha256(json.dumps([kind, endpoint], separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def restored_row(original, target):
    row = {**original, 'resource_id': target['id'], 'agent_name': target['name'],
           'agent_url': target['url'], 'evidence_scope': 'legacy',
           'creation_subject_key': subject_key(target['kind'], _provider(target['url']))}
    # Do not replay or rewrite old requests as newly executed requests. Remove
    # retired numerical gateway links so they cannot open an unrelated service.
    for key in ('content_md', 'input_wire', 'output_wire', 'summary', 'workflow_recommendation', 'pros', 'cons', 'tags'):
        if isinstance(row.get(key), str):
            row[key] = GATEWAY_REFERENCE.sub('[Retired gateway reference]', row[key])
    row['content_md'] = NOTICE + row['content_md']
    return row


def plan(db, reports, proofs):
    current = _rows(db)
    by_id = {row['id']: row for row in current}
    by_slug = {row['slug']: row for row in current}
    resources = collections.defaultdict(list)
    for row in db.execute('SELECT ' + RESOURCE_FIELDS + ' FROM resources'):
        row = dict(row)
        endpoint = _provider(row['url'])
        if endpoint:
            resources[(row['kind'], endpoint)].append(row)
    existing = collections.defaultdict(list)
    for row in current:
        endpoint = _provider(row['agent_url'])
        if endpoint:
            existing[(row['kind'], endpoint)].append(row)
    reasons, groups = collections.Counter(), collections.defaultdict(list)
    for report in reports:
        if not _legacy(report):
            reasons['not_unexecuted_historical'] += 1
            continue
        evidence = proofs[report['id']]
        endpoints = {tuple(item['endpoint']) for item in evidence}
        if len(endpoints) != 1:
            reasons['no_independent_original_endpoint' if not endpoints else 'conflicting_original_endpoints'] += 1
            continue
        endpoint = next(iter(endpoints))
        candidates = resources[(report['kind'], endpoint)]
        if len(candidates) != 1:
            reasons['provider_not_in_current_catalog' if not candidates else 'ambiguous_catalog_endpoint'] += 1
            continue
        target = candidates[0]
        if any(item.get('require_same_name') for item in evidence) and _name(target['name']) != _name(report['agent_name']):
            reasons['explicit_subject_name_changed'] += 1
            continue
        if target['eval_security'] == 'quarantine' or target['health_status'] == 'quarantined':
            reasons['quarantined_subject'] += 1
            continue
        proposed = restored_row(report, target)
        if report['id'] in by_id or report['slug'] in by_slug:
            present = by_id.get(report['id'])
            if present == proposed:
                reasons['already_restored'] += 1
                continue
            raise RestoreError('report_identity_collision')
        if not report_subject_matches(proposed, target):
            raise RestoreError('restored_subject_mismatch')
        groups[(report['kind'], endpoint)].append({'original': report, 'restored': proposed,
                                                  'target': target, 'provenance': evidence})
    changes = []
    for subject, group in groups.items():
        ordered = sorted(group, key=lambda item: (_timestamp(item['original']['created_at']), item['original']['id']), reverse=True)
        chosen = ordered[0]
        reasons['older_backup_duplicate'] += len(ordered) - 1
        previous = existing[subject]
        if len(previous) > 1:
            raise RestoreError('existing_provider_duplicates_require_review')
        if previous:
            old = previous[0]
            if (_timestamp(old['created_at']), old['id']) >= (_timestamp(chosen['original']['created_at']), chosen['original']['id']):
                reasons['newer_report_already_present'] += 1
                continue
            chosen['replaces'] = old
        changes.append(chosen)
    return {'current': current, 'changes': sorted(changes, key=lambda item: item['original']['id']),
            'reasons': dict(reasons)}


def restore(backup, source_db, db_path, scripts_dir, *, expected_deleted, apply=False, backup_dir=None):
    if os.path.samefile(source_db, db_path):
        raise RestoreError('separate_provenance_database_required')
    if apply and not backup_dir:
        raise RestoreError('private_backup_required')
    reports = load_backup(backup, expected_deleted)
    proofs, sources = provenance(reports, source_db, scripts_dir)
    db = _open(db_path)
    try:
        _references(db)
        planned = plan(db, reports, proofs)
    finally:
        db.close()
    saved = None
    if apply and planned['changes']:
        db = _open(db_path, readonly=False)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            assert_sqlite_writer_allowed(db)
            _references(db)
            fresh = plan(db, reports, proofs)
            if _signature(fresh) != _signature(planned):
                raise RestoreError('reports_or_subjects_changed_since_preflight')
            schema = [tuple(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
            claims = [dict(row) for row in db.execute('SELECT * FROM test_report_subject_claims ORDER BY subject_key')]
            saved = _private_backup(backup_dir, 'report-restoration-', {
                'format': 'historical-report-restoration-backup-v1',
                'created_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'reports': fresh['current'], 'claims': claims, 'changes': fresh['changes'],
                'source_fingerprints': sources, 'source_backup_sha256': hashlib.sha256(Path(backup).read_bytes()).hexdigest()})
            expected = {row['id']: row for row in fresh['current']}
            columns = [row['name'] for row in db.execute('PRAGMA table_info(agent_test_reports)')]
            if set(columns) != set(reports[0]) or any(not re.fullmatch('[a-z_][a-z0-9_]*', key) for key in columns):
                raise RestoreError('unsupported_report_schema')
            for change in fresh['changes']:
                row, previous = change['restored'], change.get('replaces')
                key = row['creation_subject_key']
                claim = db.execute('SELECT report_id FROM test_report_subject_claims WHERE subject_key=?', (key,)).fetchone()
                if claim:
                    if not previous or claim['report_id'] != previous['id']:
                        raise RestoreError('subject_reservation_conflict')
                    db.execute('UPDATE test_report_subject_claims SET report_id=NULL WHERE subject_key=?', (key,))
                else:
                    reserve(db, key)
                db.execute('INSERT INTO agent_test_reports (' + ','.join('"'+key+'"' for key in columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', [row[key] for key in columns])
                finish(db, key, row['id'])
                if previous:
                    db.execute('UPDATE test_report_subject_claims SET report_id=? WHERE report_id=?', (row['id'], previous['id']))
                    if db.execute('DELETE FROM agent_test_reports WHERE id=?', (previous['id'],)).rowcount != 1:
                        raise RestoreError('replacement_failed')
                    del expected[previous['id']]
                expected[row['id']] = row
            if _rows(db) != sorted(expected.values(), key=lambda row: row['id']):
                raise RestoreError('unexpected_report_change')
            if [tuple(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')] != schema:
                raise RestoreError('unexpected_schema_change')
            if db.execute('''SELECT 1 FROM test_report_subject_claims c LEFT JOIN agent_test_reports r ON r.id=c.report_id
                WHERE c.report_id IS NULL OR r.id IS NULL LIMIT 1''').fetchone():
                raise RestoreError('unresolved_report_reservation')
            db.commit()
        finally:
            db.close()
    changed = len(planned['changes'])
    replaced = sum('replaces' in item for item in planned['changes'])
    return {'mode': 'apply' if apply else 'dry_run', 'reviewed_deleted_reports': len(reports),
            'reports_before': len(planned['current']), 'eligible_restorations': changed,
            'eligible_replacements': replaced, 'restored': changed if apply else 0,
            'replaced_older_reports': replaced if apply else 0,
            'reports_after': len(planned['current']) + (changed - replaced if apply else 0),
            'skipped': planned['reasons'], 'by_protocol': dict(collections.Counter(item['target']['kind'] for item in planned['changes'])),
            'backup_created': saved is not None, 'provider_calls': 0, 'new_execution_evidence': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for flag in ['backup', 'source-db', 'db', 'scripts-dir']:
        parser.add_argument('--'+flag, required=True)
    parser.add_argument('--expected-deleted', required=True, type=int)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir')
    args = parser.parse_args(argv)
    try:
        result = restore(args.backup, args.source_db, args.db, args.scripts_dir,
                         expected_deleted=args.expected_deleted, apply=args.apply, backup_dir=args.backup_dir)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, SyntaxError):
        print(json.dumps({'ok': False, 'error': 'report_restoration_preflight_or_transaction_failed'}))
        return 1
    print(json.dumps({'ok': True, **result}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Repair only independently matched legacy report subjects; default to dry run.

The source remains a read-only snapshot. Apply requires a private row backup and
never creates execution/version evidence. Output contains aggregate counts only.
"""
import argparse
import base64
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_market.concierge.report_evidence import canonical_endpoint, _name

IDENTITY = ('id', 'resource_id', 'title', 'slug', 'kind', 'agent_name', 'agent_url')
EVIDENCE = ('evidence_scope', 'executed_at', 'execution_finished_at', 'connection_version_id')
RESOURCE = ('id', 'key', 'kind', 'name', 'url')
EVIDENCE_SQL = {
    'evidence_scope': 'SELECT id,evidence_scope FROM agent_test_reports',
    'executed_at': 'SELECT id,executed_at FROM agent_test_reports',
    'execution_finished_at': 'SELECT id,execution_finished_at FROM agent_test_reports',
    'connection_version_id': 'SELECT id,connection_version_id FROM agent_test_reports',
}


class RepairError(ValueError):
    """A fixed error code that does not disclose database content."""


def _packed(value):
    def blob(item):
        if isinstance(item, bytes):
            return {'sqlite_blob_base64': base64.b64encode(item).decode('ascii')}
        raise TypeError('unsupported_sqlite_value')
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False, default=blob).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_packed(value)).hexdigest()


def _open(path, *, readonly):
    con = sqlite3.connect(Path(path).resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw'),
                          uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=2000')
    if readonly:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
    return con


def _columns(con, table):
    # Table names are fixed program constants, never command-line input.
    return {row['name'] for row in con.execute('PRAGMA table_info('+table+')')}


def _reports(con, *, destination):
    columns = _columns(con, 'agent_test_reports')
    if not set(IDENTITY).issubset(columns) or (destination and not set(EVIDENCE).issubset(columns)):
        raise RepairError('unsupported_report_schema')
    rows = [dict(row) for row in con.execute(
        'SELECT id,resource_id,title,slug,kind,agent_name,agent_url FROM agent_test_reports')]
    by_id = {row['id']: row for row in rows}
    for column, sql in EVIDENCE_SQL.items():
        if column in columns:
            for row in con.execute(sql):
                by_id[row['id']][column] = row[column]
    return rows


def _legacy(report):
    return (report.get('evidence_scope') in (None, 'legacy') and
            all(report.get(key) is None for key in EVIDENCE[1:]))


def _gateway(report):
    return canonical_endpoint('https://agentconcierge.biz/api/gateway/'+
                              str(report['kind'])+'/'+str(report['resource_id']))


def _managed_endpoint(endpoint):
    return bool(endpoint and endpoint[1] == 'agentconcierge.biz' and
                endpoint[3].startswith('/api/gateway/'))


def plan_repairs(source, destination):
    """Plan with cheap report metadata and one current-catalog metadata scan."""
    for con in (source, destination):
        if not set(RESOURCE).issubset(_columns(con, 'resources')):
            raise RepairError('unsupported_resource_schema')
    sources = _reports(source, destination=False)
    reports = _reports(destination, destination=True)
    source_slugs, dest_slugs = collections.defaultdict(list), collections.Counter()
    for row in sources:
        source_slugs[row['slug']].append(row)
    for row in reports:
        dest_slugs[row['slug']] += 1
    reasons, pending = collections.Counter(), []
    for report in reports:
        if not _legacy(report):
            reasons['not_legacy_unexecuted'] += 1
            continue
        slug = report['slug']
        if not slug or dest_slugs[slug] != 1 or len(source_slugs[slug]) != 1:
            reasons['missing_or_ambiguous_slug'] += 1
            continue
        original = source_slugs[slug][0]
        if (not _legacy(original) or original['title'] != report['title'] or
                original['kind'] != report['kind'] or not _name(report['agent_name']) or
                _name(original['agent_name']) != _name(report['agent_name'])):
            reasons['source_report_mismatch'] += 1
            continue
        if canonical_endpoint(original['agent_url']) != _gateway(original):
            reasons['source_gateway_mismatch'] += 1
            continue
        old = source.execute('SELECT id,key,kind,name,url FROM resources WHERE id=?',
                             (original['resource_id'],)).fetchone()
        if old is None or old['kind'] != original['kind'] or _name(old['name']) != _name(original['agent_name']):
            reasons['source_resource_mismatch'] += 1
            continue
        old = dict(old)
        endpoint = canonical_endpoint(old['url'])
        if not old['key'] or endpoint is None or _managed_endpoint(endpoint):
            reasons['source_endpoint_invalid'] += 1
            continue
        resources = destination.execute('SELECT id,key,kind,name,url FROM resources WHERE key=?',
                                        (old['key'],)).fetchall()
        if len(resources) != 1:
            reasons['destination_key_missing_or_ambiguous'] += 1
            continue
        target = dict(resources[0])
        if (target['kind'] != old['kind'] or _name(target['name']) != _name(old['name']) or
                canonical_endpoint(target['url']) != endpoint):
            reasons['destination_subject_changed'] += 1
            continue
        if (report['resource_id'] == target['id'] and report['agent_name'] == target['name'] and
                report['agent_url'] == target['url']):
            reasons['already_bound'] += 1
            continue
        # A different direct URL is not an unbound legacy gateway record.
        if canonical_endpoint(report['agent_url']) != _gateway(report):
            reasons['destination_gateway_mismatch'] += 1
            continue
        pending.append((report, original, old, target, endpoint))
    needed = {(target['kind'], _name(target['name']), endpoint)
              for _, _, _, target, endpoint in pending}
    subjects = collections.Counter()
    needed_names = {(kind, name) for kind, name, _ in needed}
    if needed:
        for resource in destination.execute('SELECT id,kind,name,url FROM resources'):
            name = _name(resource['name'])
            # Canonicalize only possible subjects, without broadening endpoints.
            if (resource['kind'], name) in needed_names:
                subject = (resource['kind'], name, canonical_endpoint(resource['url']))
                if subject in needed:
                    subjects[subject] += 1
    changes = []
    for report, original, old, target, endpoint in pending:
        if subjects[(target['kind'], _name(target['name']), endpoint)] != 1:
            reasons['destination_subject_ambiguous'] += 1
            continue
        before = dict(destination.execute('SELECT * FROM agent_test_reports WHERE id=?', (report['id'],)).fetchone())
        original_row = dict(source.execute('SELECT * FROM agent_test_reports WHERE id=?', (original['id'],)).fetchone())
        changes.append({'before': before, 'target': target, 'source_resource': old,
                        'source_report_id': original['id'], 'source_report_digest': _digest(original_row),
                        'destination_report_digest': _digest(before),
                        'source_resource_identity_digest': _digest(old),
                        'destination_resource_identity_digest': _digest(target)})
    return {'total': len(reports), 'changes': changes, 'reasons': dict(reasons)}


def _signature(plan):
    return _digest(sorted(plan['changes'], key=lambda item: item['before']['id']))


def _backup(plan, path):
    """Persist private original rows and provenance before the first SQL update."""
    directory = Path(path).absolute()
    descriptor = None
    filename = 'report-bindings-'+uuid.uuid4().hex+'.json'
    created = False
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
                stat.S_IMODE(info.st_mode) != 0o700):
            raise RepairError('backup_directory_not_private')
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))
        opened = os.fstat(descriptor)
        if ((opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or
                opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) != 0o700):
            raise RepairError('backup_directory_changed')
        payload = _packed({'format': 'legacy-report-binding-backup-v1',
                           'created_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           'rows': plan['changes']})
        fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0),
                     0o600, dir_fd=descriptor)
        created = True
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(descriptor)
    except Exception:
        if created and descriptor is not None:
            try:
                os.unlink(filename, dir_fd=descriptor)
            except OSError:
                pass
        raise RepairError('backup_failed') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def repair(source_db, db, *, apply=False, backup_dir=None):
    """Return aggregate results. This function never starts application services."""
    source_path, destination_path = Path(source_db), Path(db)
    if not source_path.is_file() or not destination_path.is_file():
        raise RepairError('existing_database_files_required')
    if os.path.samefile(source_path, destination_path):
        raise RepairError('source_and_destination_must_differ')
    if apply and not backup_dir:
        raise RepairError('private_backup_directory_required')
    source = _open(source_path, readonly=True)
    destination = None
    try:
        destination = _open(destination_path, readonly=True)
        plan = plan_repairs(source, destination)
        destination.close()
        destination = None
        backup_created = False
        if apply and plan['changes']:
            destination = _open(destination_path, readonly=False)
            destination.execute('BEGIN IMMEDIATE')
            fresh = plan_repairs(source, destination)
            if _signature(plan) != _signature(fresh):
                raise RepairError('destination_changed_since_preflight')
            _backup(fresh, backup_dir)
            backup_created = True
            for change in fresh['changes']:
                before, target = change['before'], change['target']
                result = destination.execute("UPDATE agent_test_reports SET resource_id=?,agent_name=?,agent_url=?,evidence_scope='legacy' WHERE id=?",
                    (target['id'], target['name'], target['url'], before['id']))
                expected = {**before, 'resource_id': target['id'], 'agent_name': target['name'],
                            'agent_url': target['url'], 'evidence_scope': 'legacy'}
                actual = destination.execute('SELECT * FROM agent_test_reports WHERE id=?', (before['id'],)).fetchone()
                if result.rowcount != 1 or actual is None or dict(actual) != expected:
                    raise RepairError('unexpected_update_result')
            destination.commit()
        protocols = collections.Counter(change['target']['kind'] for change in plan['changes'])
        return {'mode': 'apply' if apply else 'dry_run', 'reports_checked': plan['total'],
                'eligible': len(plan['changes']), 'changed': len(plan['changes']) if apply else 0,
                'protocols': dict(protocols), 'skipped': plan['reasons'], 'backup_created': backup_created}
    finally:
        if destination is not None:
            destination.close()  # Roll back every uncommitted write on failure.
        source.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir')
    args = parser.parse_args(argv)
    try:
        result = repair(args.source_db, args.db, apply=args.apply, backup_dir=args.backup_dir)
    except RepairError as exc:
        print('Report binding repair refused: '+str(exc), file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error, ValueError, TypeError):
        print('Report binding repair refused: database_or_backup_error', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

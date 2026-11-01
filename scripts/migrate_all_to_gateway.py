#!/usr/bin/env python3
"""Read-only stored-report inventory; historical migration behavior is retired.

Use explicit --db paths. This tool never transforms stored reports, canonical
provider bindings, citation URLs or wire evidence. Raw private evidence is not
itself proof of a public leak; public API projection needs separate regression
checks. Output contains only fixed reason codes and aggregate counts.
"""
import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit


FIELDS = ('content_md', 'summary', 'input_wire', 'output_wire', 'pros', 'cons',
          'workflow_recommendation')
REQUIRED_REPORT_COLUMNS = {'id', 'resource_id', 'kind', 'agent_url'}
COUNTERS = ('reports_scanned', 'matched_resource_and_protocol', 'missing_resource',
            'protocol_mismatch', 'unsupported_protocol', 'missing_report_agent_url',
            'report_agent_url_matches_canonical', 'report_agent_url_is_managed',
            'unbound_report_agent_url', 'reports_with_managed_catalog_binding',
            'stored_raw_binding_mentions', 'stored_upstream_labels',
            'stored_sensitive_pattern_candidates', 'bounded_field_overflow_candidates')
PRIVATE_PATTERN = re.compile(
    r'(?i)\b(?:Bearer|Basic)\s+\S+|\bvt_[A-Za-z0-9_-]+|/Users/|/home/|'
    r'(?:api[_-]?key|access_token|password|signing_secret)[\"\x27]?\s*[:=]')
KINDS = ('mcp', 'a2a', 'x402')


class AuditError(ValueError):
    """A fixed, non-sensitive failure code suitable for CLI output."""


def managed_identity(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname != 'agentconcierge.biz'
                or parsed.port not in (None, 443) or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            return None
        match = re.fullmatch(r'/api/gateway/(mcp|a2a|x402)/([1-9][0-9]{0,9})', parsed.path)
        if match and int(match[2]) < 2**31:
            return match[1], int(match[2])
    except (ValueError, TypeError):
        pass
    return None


def audit_database(database, *, max_reports=50000):
    """Read one existing DB in a consistent read transaction; never initialize it."""
    if type(max_reports) is not int or not 1 <= max_reports <= 200000:
        raise AuditError('invalid_report_limit')
    try:
        path = Path(database).expanduser().resolve(strict=True)
    except (OSError, ValueError, TypeError, RuntimeError):
        raise AuditError('database_unavailable') from None
    if not path.is_file():
        raise AuditError('database_unavailable')
    counts = Counter({name: 0 for name in COUNTERS})
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.25)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            report_columns = {row['name'] for row in db.execute('PRAGMA table_info(agent_test_reports)')}
            resource_columns = {row['name'] for row in db.execute('PRAGMA table_info(resources)')}
            if (not REQUIRED_REPORT_COLUMNS <= report_columns
                    or not {'id', 'kind', 'url'} <= resource_columns):
                raise AuditError('required_schema_unavailable')
            # All interpolated identifiers come from this fixed source allowlist.
            selected = ','.join('substr(t.' + field + ',1,262145) AS ' + field
                                for field in FIELDS if field in report_columns)
            fields_sql = ',' + selected if selected else ''
            rows = db.execute(
                'SELECT t.id,t.resource_id,t.kind,substr(t.agent_url,1,8193) AS agent_url,r.id AS catalog_id,'
                'r.kind AS catalog_kind,substr(r.url,1,8193) AS catalog_url' + fields_sql +
                ' FROM agent_test_reports t LEFT JOIN resources r ON r.id=t.resource_id'
                ' ORDER BY t.id LIMIT ?', (max_reports + 1,))
            truncated = False
            for index, row in enumerate(rows):
                if index == max_reports:
                    truncated = True
                    break
                counts['reports_scanned'] += 1
                if (len(row['agent_url'] or '') > 8192 or len(row['catalog_url'] or '') > 8192
                        or any(len(row[field] or '') > 262144 for field in FIELDS if field in row.keys())):
                    counts['bounded_field_overflow_candidates'] += 1
                if row['catalog_id'] is None:
                    counts['missing_resource'] += 1
                elif row['kind'] != row['catalog_kind']:
                    counts['protocol_mismatch'] += 1
                else:
                    counts['matched_resource_and_protocol'] += 1
                if row['kind'] not in KINDS:
                    counts['unsupported_protocol'] += 1
                agent_url = row['agent_url'] or ''
                canonical = row['catalog_url'] or ''
                if not agent_url:
                    counts['missing_report_agent_url'] += 1
                elif agent_url == canonical:
                    counts['report_agent_url_matches_canonical'] += 1
                elif managed_identity(agent_url) == (row['kind'], row['resource_id']):
                    counts['report_agent_url_is_managed'] += 1
                else:
                    counts['unbound_report_agent_url'] += 1
                if managed_identity(canonical):
                    counts['reports_with_managed_catalog_binding'] += 1
                corpus = '\n'.join(str(row[field] or '') for field in FIELDS if field in row.keys())
                if canonical and (canonical in corpus or canonical.replace('/', '\\/') in corpus):
                    counts['stored_raw_binding_mentions'] += 1
                if re.search(r'(?i)upstream\s+(?:provider\s+target|agent\s+card|target\s*/?\s*binding)', corpus):
                    counts['stored_upstream_labels'] += 1
                if PRIVATE_PATTERN.search(corpus):
                    counts['stored_sensitive_pattern_candidates'] += 1
            db.rollback()
    except AuditError:
        raise
    except (sqlite3.Error, OSError, ValueError):
        raise AuditError('database_read_failed') from None
    return {'status': 'partial' if truncated or counts['bounded_field_overflow_candidates'] else 'complete',
            'truncated': truncated, 'content_truncated': bool(counts['bounded_field_overflow_candidates']),
            'counts': dict(counts)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', action='append', required=True, metavar='EXISTING_DB',
                        help='An existing SQLite file, opened read-only. Repeat for another database.')
    parser.add_argument('--max-reports', type=int, default=50000,
                        help='Maximum reports per database, 1 to 200000 (default: 50000).')
    args = parser.parse_args(argv)
    results = []
    for index, database in enumerate(args.db, 1):
        try:
            result = audit_database(database, max_reports=args.max_reports)
        except AuditError as exc:
            result = {'status': 'unavailable', 'error_code': str(exc)}
        results.append({'database_index': index, **result})
    result = {'mode': 'read-only-stored-report-inventory', 'database_writes': 0,
              'provider_calls': 0, 'projection_claim': 'not_a_public_leak_or_live_invocation_certification',
              'databases': results, 'limits': [
                  'No stored report, canonical upstream, citation or wire evidence is changed.',
                  'Stored raw bindings can be correct private evidence; counts are not public leak findings.',
                  'Public endpoint projection and actual registered-agent execution need separate tests.',
                  'No raw paths, URLs, credentials, report bodies or report identities are printed.',
                  'The inventory is bounded by the explicit per-database report limit.',
                  'Report bodies are limited to 262144 characters per field; oversized fields make coverage partial.',
              ]}
    print(json.dumps(result, indent=2))
    return 0 if all(row['status'] == 'complete' for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())

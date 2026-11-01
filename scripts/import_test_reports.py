#!/usr/bin/env python3
"""Preflight historical reports against an explicitly selected canonical catalog."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_market.concierge.report_evidence import report_subject_matches


def resolve_reports(db, reports):
    """Resolve a stable catalog key per destination, never copy another DB's ID."""
    result = []
    if not isinstance(reports, list) or not 0 < len(reports) <= 1000:
        raise ValueError('Provide between one and 1000 historical reports.')
    for original in reports:
        if not isinstance(original, dict) or not isinstance(original.get('subject_key'), str):
            raise ValueError('Every imported report requires a canonical subject_key.')
        if (original.get('evidence_scope') not in (None, 'legacy')
                or any(original.get(key) is not None for key in
                       ('executed_at', 'execution_finished_at', 'connection_version_id'))):
            raise ValueError('Imported documents cannot assert measured execution evidence.')
        rows = db.execute('SELECT * FROM resources WHERE key=?', (original['subject_key'],)).fetchall()
        if len(rows) != 1:
            raise ValueError('The canonical subject is unavailable in this catalog.')
        resource = dict(rows[0])
        report = {**original, 'resource_id': resource['id'], 'evidence_scope': 'legacy'}
        if not report_subject_matches(report, resource):
            raise ValueError('The report name, protocol and endpoint must match the canonical subject.')
        result.append(report)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Save reviewed historical reports after preflight.')
    args = parser.parse_args()
    try:
        reports = json.loads(args.reports.read_text())
        with sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            resolved = resolve_reports(db, reports)
        if args.apply:
            from agent_market.gateway.store import Store
            store = Store(str(args.db))
            try:
                # Re-resolve against the selected destination before writing.
                resolved = resolve_reports(store._db, reports)
                for report in resolved:
                    store.create_test_report(report)
            finally:
                store._db.close()
        print(json.dumps({'reports': len(resolved), 'applied': args.apply,
                          'scope': 'historical', 'provider_calls': 0}))
        return 0
    except (ValueError, KeyError, OSError, sqlite3.Error):
        print(json.dumps({'error': 'report_import_preflight_failed', 'provider_calls': 0}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

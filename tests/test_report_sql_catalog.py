"""Reviewed report/frontend SQL stays finite and native clock buckets stay exact."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_market.application_store_postgres import (
    ApplicationStoreError, PostgresApplicationStore, _LegacyConnection, _STATEMENTS, _normalized,
)
from agent_market.concierge.front import CARD_COLS, LIVE_COND, REPORT_HISTORY_COND, REPORT_SUBJECT_COND, VERIFIED_EXECUTION_COND
from scripts.build_application_store_postgres_catalog import source_constant


def expression(text):
    return ast.parse(text, mode='eval').body


def test_source_constant_supports_only_reviewed_literal_name_interpolation():
    environment = {'PREDICATE': 'r.active=1'}
    assert source_constant(expression('f"WHERE {PREDICATE}"'), environment) == 'WHERE r.active=1'
    assert source_constant(expression('{"x": [("a", PREDICATE)]}'), environment) == {
        'x': [('a', 'r.active=1')]}
    assert source_constant(expression('"prefix " + PREDICATE'), environment) == 'prefix r.active=1'


@pytest.mark.parametrize('text', [
    '__import__("os").system("not-executed")', 'f"{unreviewed}"',
    'f"{PREDICATE!r}"', 'f"{PREDICATE:>10}"', 'f"{PREDICATE.upper()}"',
    '{**unreviewed}', '"prefix" + unreviewed', 'PREDICATE.__class__',
])
def test_source_constant_refuses_calls_attributes_runtime_names_and_formatting(text):
    with pytest.raises(ValueError):
        source_constant(expression(text), {'PREDICATE': 'r.active=1'})


def test_current_report_card_and_filter_queries_are_registered_exactly():
    for verified in (False, True):
        for has_report in (False, True):
            predicates = [REPORT_HISTORY_COND if has_report and not verified else LIVE_COND]
            if verified:
                predicates.append(VERIFIED_EXECUTION_COND)
            if has_report:
                predicates.append('r.id IN (SELECT resource_id FROM agent_test_reports WHERE resource_id IS NOT NULL)')
                predicates.append(f'EXISTS (SELECT 1 FROM agent_test_reports tr WHERE {REPORT_SUBJECT_COND})')
            where = ' AND '.join(predicates)
            sql = 'SELECT ' + CARD_COLS + ' FROM resources r WHERE ' + where + \
                  ' ORDER BY COALESCE(r.first_seen, 0) DESC, r.id DESC LIMIT ?'
            entry = _STATEMENTS[_normalized(sql)]
            assert entry['readonly'] is True
            assert 'NULL AS report_grade' in entry['postgres']
            assert 'strftime' not in entry['postgres']
            if has_report:
                assert 'r.id IN (SELECT resource_id FROM agent_test_reports WHERE resource_id IS NOT NULL)' in entry['postgres']
                assert f'EXISTS (SELECT 1 FROM agent_test_reports tr WHERE {REPORT_SUBJECT_COND})' in entry['postgres']
            if verified:
                assert 'EXTRACT(EPOCH FROM clock_timestamp())' in entry['postgres']


def test_report_helper_and_public_rollup_fixed_queries_are_registered():
    for filename in ('agent_market/concierge/report_evidence.py',
                     'agent_market/concierge/verification_summary.py'):
        tree = ast.parse(Path(filename).read_text())
        queries = [node.value for node in ast.walk(tree)
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and node.value.lstrip().startswith('SELECT')]
        assert queries
        for sql in queries:
            assert _normalized(sql) in _STATEMENTS
    hourly = next(item for item in _STATEMENTS.values()
                  if 'SELECT MIN(23,CAST((finished-?)/3600 AS INTEGER)) bucket' in item['sqlite'])
    assert 'LEAST(23,TRUNC((finished-%s)/3600)::integer)' in hourly['postgres']


def test_catalog_registration_does_not_accept_other_runtime_sql():
    store = SimpleNamespace(_depth=1, _failed=False)
    with pytest.raises(ApplicationStoreError, match='unsupported_application_sql'):
        _LegacyConnection(store).execute('SELECT id FROM agent_test_reports WHERE resource_id=7 OR 1=1')
    assert store._failed


def test_native_report_schema_requires_finish_time_and_refuses_old_attachment():
    native = PostgresApplicationStore.__new__(PostgresApplicationStore)
    native._depth = 1
    expected = native._expected_columns('agent_test_reports')
    assert ('execution_finished_at', 'double precision', 'YES') in expected
    queries = []
    def execute(sql, params):
        queries.append(sql)
        assert params == ('agent_test_reports',)
        return SimpleNamespace(fetchall=lambda: [row for row in expected if row[0] != 'execution_finished_at'])
    native._execute = execute
    with pytest.raises(ApplicationStoreError, match='schema_profile_mismatch'):
        native._validate_native_table('agent_test_reports')
    assert len(queries) == 1 and queries[0].startswith('SELECT column_name,')
    assert 'ALTER' not in queries[0], 'Attaching an old native schema must not silently migrate it.'

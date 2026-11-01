"""Source inventory is bounded and does not turn dynamic strings into SQL."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_market.application_store_coverage import _Coverage
from agent_market.application_store_postgres import _normalized


def test_registered_literals_and_unknown_dynamic_statements_are_distinct():
    code="def work(store,text):\n store.query('SELECT id FROM resources WHERE id=?',(1,))\n store.query(text)\n"
    parsed=ast.parse(code)
    analyzer=_Coverage(parsed,'agent_market/_synthetic.py', {_normalized('SELECT id FROM resources WHERE id=?')},set())
    analyzer.visit(parsed)
    assert [row['status'] for row in analyzer.rows]==['registered_dialect_pair','dynamic_requires_review']
    encoded=json.dumps(analyzer.rows)
    assert 'SELECT id' not in encoded and all(row['line'] in (2,3) for row in analyzer.rows)


def test_bound_native_source_and_non_sql_managed_execution_are_not_false_missing_sql():
    code="def _execute_bounded():\n def work():\n  executor._execute(resource)\n"
    analyzer=_Coverage(ast.parse(code),'agent_market/concierge/managed_gateway.py',set(),set())
    analyzer.visit(ast.parse(code))
    assert len(analyzer.rows)==1 and analyzer.rows[0]['status']=='non_sql_execution_sink'


@pytest.fixture(scope='module')
def candidate_vector_catalog():
    """Build an in-memory candidate; never encode/write the checked-in JSON."""
    from agent_market.gateway import store as store_module
    from agent_market.gateway.admin_auth import ADMIN_SCHEMA
    from agent_market.infra.redis_hub import RedisHub
    from scripts.build_application_store_postgres_catalog import build_catalog
    cache = RedisHub(); cache._closed = True
    with patch.object(store_module, 'init_admin_auth_db', lambda db: db.executescript(ADMIN_SCHEMA)), \
         patch.object(RedisHub, 'get_instance', staticmethod(lambda: cache)):
        return build_catalog()


def test_registered_native_json_paths_use_reviewed_postgres_types(candidate_vector_catalog):
    entries = candidate_vector_catalog['statements']
    assert not any('json_extract(' in row['postgres'] for row in entries)
    reset = next(row for row in entries if "json_extract(m.value, '$.\"' || o.resource_id" in row['sqlite'])
    assert "m.value::jsonb -> o.resource_id::text ->> 'reset_at'" in reset['postgres']
    scheduled = next(row for row in entries if "g.used<json_extract(g.payload,'$.max_runs')" in row['sqlite'])
    assert "((g.payload::jsonb)->>'max_runs')::bigint" in scheduled['postgres']
    owners = [row for row in entries if "json_extract(payload,'$.owner')" in row['sqlite']]
    assert owners and all("((payload::jsonb)->>'owner')::text" in row['postgres'] for row in owners)


def _actual_claim_expression(prefix):
    from scripts.build_application_store_postgres_catalog import source_constant
    tree = ast.parse(Path('agent_market/legacy_vector_index.py').read_text())
    claim = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'claim_batch')
    expressions = []
    for node in ast.walk(claim):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'execute' and node.args:
            expression = node.args[0]
        elif isinstance(node.func, ast.Name) and node.func.id == '_rows' and len(node.args) >= 2:
            expression = node.args[1]
        else:
            continue
        if not isinstance(expression, ast.BinOp):
            continue
        sql = source_constant(expression, {'clause': ''})
        if sql.lstrip().startswith(prefix):
            expressions.append(expression)
    assert len(expressions) == 1
    return expressions[0]


@pytest.mark.parametrize('family,prefix,readonly', [
    ('vector.supersede_stale_heads.', "UPDATE legacy_vector_jobs SET status='superseded'", False),
    ('vector.claim.', 'SELECT j.* FROM legacy_vector_jobs j JOIN legacy_vector_heads', True),
])
def test_finite_claim_cleanup_and_current_select_match_every_actual_source_filter(candidate_vector_catalog, family, prefix, readonly):
    from agent_market.legacy_vector_index import MAX_BATCH, VectorIndex, VectorError
    from scripts.build_application_store_postgres_catalog import source_constant
    assert MAX_BATCH == 50
    rows = {row['name']: row for row in candidate_vector_catalog['statements'] if row['name'].startswith(family)}
    assert set(rows) == {family+str(count) for count in range(MAX_BATCH+1)}
    expression = _actual_claim_expression(prefix)
    for count in range(MAX_BATCH+1):
        clause = '' if count == 0 else ' AND j.resource_id IN ('+','.join('?' for _ in range(count))+')'
        actual = source_constant(expression, {'clause': clause})
        entry = rows[family+str(count)]
        assert _normalized(entry['sqlite']) == _normalized(actual)
        assert entry['readonly'] is readonly and entry['generated_id'] is None
        assert entry['sqlite'].count('?') == entry['postgres'].count('%s') == count+3
        assert 'legacy_vector_generations' in entry['postgres'] and 'resources r' in entry['postgres']
    # Both optional filters have the same hard bound. No empty IN() or 51-ID
    # dynamic form may be admitted by the source or by the candidate catalog.
    vector = VectorIndex.__new__(VectorIndex)
    assert vector._request(1, list(range(1, 51)), None)[0] == tuple(range(1, 51))
    for resource_ids in ([], list(range(1, 52))):
        with pytest.raises(VectorError):
            vector._request(1, resource_ids, None)
    with pytest.raises(VectorError):
        vector._request(1, None, [{'id': index, 'name': 'Synthetic', 'description': '', 'category': 'other'} for index in range(1, 52)])


@pytest.mark.parametrize('family,prefix', [
    ('vector.supersede_stale_heads.', "UPDATE legacy_vector_jobs SET status='superseded'"),
    ('vector.claim.', 'SELECT j.* FROM legacy_vector_jobs j JOIN legacy_vector_heads'),
])
def test_mutated_predicate_filter_limit_and_statement_never_gain_native_authority(candidate_vector_catalog, monkeypatch, family, prefix):
    import agent_market.application_store_postgres as native
    from scripts.build_application_store_postgres_catalog import source_constant
    by_sql = {_normalized(entry['sqlite']): entry for entry in candidate_vector_catalog['statements']}
    monkeypatch.setattr(native, '_STATEMENTS', by_sql)
    expression = _actual_claim_expression(prefix)
    original = next(row['sqlite'] for row in candidate_vector_catalog['statements'] if row['name'] == family+'1')
    mutations = [original+'; DELETE FROM resources', original.replace('LIMIT ?', 'LIMIT 5000'),
        original.replace('j.resource_id IN (?)', 'j.resource_id IN (1)'),
        source_constant(expression, {'clause': ' AND j.resource_id IN ('+','.join('?' for _ in range(51))+')'})]
    if family == 'vector.claim.':
        mutations.append(original.replace('AND g.generation=j.generation', ''))
        mutations.append(original.replace("AND COALESCE(r.eval_security,'')!='quarantine'", ''))
    else:
        mutations.append(original.replace("OR r.eval_security='quarantine'", ''))
    for sql in mutations:
        assert _normalized(sql) not in by_sql
        store = SimpleNamespace(_depth=1, _failed=False)
        with pytest.raises(native.ApplicationStoreError, match='unsupported_application_sql'):
            native._LegacyConnection(store).execute(sql)
        assert store._failed

"""Native collector scheduling keeps SQL values, work limits and fences explicit."""
import math
from types import SimpleNamespace

import pytest

from agent_market.application_store_collector import PostgresCollectorMixin
from agent_market.application_store_postgres import ApplicationStoreError, PostgresApplicationStore, _LegacyConnection


class CapturingCollector(PostgresCollectorMixin):
    def _collector_rows(self, sql, params=()):
        self.statement, self.parameters = sql, params
        return []


@pytest.mark.parametrize('options', [dict(limit=0), dict(limit=5001), dict(limit=True),
    dict(limit=1, per_host=0), dict(limit=1, per_host=5001), dict(limit=1, kind=['mcp'] * 17),
    dict(limit=1, kind=['mcp', {}]), dict(limit=1, kind='nul\0kind')])
def test_invalid_collector_selector_fails_before_native_io(options):
    collector = CapturingCollector()
    with pytest.raises(ApplicationStoreError): collector.due_for_check(100, **options)
    assert not hasattr(collector, 'statement')


@pytest.mark.parametrize('value', [-1, math.nan, math.inf, True, '100', 10**1000])
def test_invalid_collector_time_is_refused_without_query(value):
    collector = CapturingCollector()
    with pytest.raises(ApplicationStoreError): collector.due_for_capability(value, 100, 10)
    assert not hasattr(collector, 'statement')


def test_selector_and_host_caps_are_bound_not_interpolated():
    collector = CapturingCollector()
    text = "mcp' OR 1=1 --"
    collector.due_for_check(100, 10, per_host=2, kind=[text, 'a2a'])
    assert text not in collector.statement and collector.parameters == [text, 'a2a', 100, 2, 10]
    assert 'ROW_NUMBER()' in collector.statement


def test_invalid_postpone_cannot_enter_transaction_or_commit_a_prefix():
    collector = CapturingCollector()
    collector.tx = lambda: pytest.fail('Invalid batch opened a transaction')
    with pytest.raises(ApplicationStoreError): collector.postpone([1, 'invalid'], 200)


def test_unsupported_store_query_poisons_an_existing_transaction():
    store = PostgresApplicationStore.__new__(PostgresApplicationStore)
    store._depth, store._failed = 1, False
    with pytest.raises(ApplicationStoreError): store.query('SELECT synthetic_unregistered')
    assert store._failed


def test_caught_batch_iteration_failure_poisons_preceding_registered_updates():
    store = SimpleNamespace(_depth=1, _failed=False)
    database = _LegacyConnection(store)
    applied = []
    database.execute = lambda *_args: applied.append(True) or SimpleNamespace(rowcount=1)
    def parameters():
        yield (1,)
        raise RuntimeError('Synthetic batch iterator failed')
    with pytest.raises(RuntimeError): database.executemany('synthetic-owned-statement', parameters())
    assert applied == [True] and store._failed


def test_noop_batch_rows_cannot_bypass_iteration_limit():
    store = SimpleNamespace(_depth=1, _failed=False)
    database = _LegacyConnection(store)
    database.execute = lambda *_args: SimpleNamespace(rowcount=0)
    with pytest.raises(ApplicationStoreError, match='result_limit'):
        database.executemany('synthetic-owned-statement', (() for _ in range(5001)))
    assert store._failed


def test_public_fts_query_families_are_named_exact_projections_not_runtime_rewrites():
    from agent_market.application_store_postgres import _STATEMENTS
    families = [item for item in _STATEMENTS.values() if item.get('adapter') == 'explore-fts5-v1']
    assert len([item for item in families if item['name']=='front.explore.fts']) == 16
    assert len([item for item in families if item['name']=='admin.explore.fts']) == 8
    assert {item['parameter_count'] for item in families} == {3, 4}
    for item in families:
        assert item['readonly'] is True and 'resources_fts MATCH ?' in item['sqlite']
        assert 'json_array_elements(%s::json)' in item['postgres']
        assert 'CASE WHEN r.trial_ok=1 THEN 0.5 ELSE 0 END' in item['postgres']


def test_actual_native_current_collector_parity_and_concurrent_observation_ownership():
    from scripts.rehearse_application_collector_postgres import rehearse
    result = rehearse()
    assert len(result['checks']) >= 14 and all(value is True for value in result['checks'].values())
    assert result['temporary_cluster_removed'] and result['provider_calls'] == result['production_actions'] == 0
    assert not result['full_application_ready']

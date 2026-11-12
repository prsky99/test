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
    # The ranking asks for a whole batch (CHECK_BATCH, 18db93cf), not the caller's limit.
    assert text not in collector.statement and collector.parameters == [text, 'a2a', 100, 2, 1000]
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


class RankingCollector(PostgresCollectorMixin):
    """Ranking returns 1,000 due ids; whole-row reads must bind at most 256 values each."""
    def __init__(self):
        self.bound = []

    def _collector_rows(self, sql, params=()):
        if 'ROW_NUMBER()' in sql:
            return [{'id': rid} for rid in range(1, 1001)]
        assert len(params) <= 256, len(params)  # _values refuses more (invalid_parameters)
        self.bound.append(len(params))
        return [{'id': rid, 'active': 1, 'health_status': 'healthy', 'next_check_at': None, 'kind': 'x402'}
                for rid in params]


def test_a_large_health_batch_reads_rows_in_bounded_statements():
    """11-12 10:54~: the x402 health loop asked for 2 x its batch (over 256 ids) in one IN list and every
    round failed with invalid_parameters; rows are now read 200 ids at a time."""
    collector = RankingCollector()
    rows = collector.due_for_check(100, 600, per_host=2, kind='x402')
    assert len(rows) == 600 and [row['id'] for row in rows] == list(range(1, 601))
    assert collector.bound == [200, 200, 200]


class GroupingCollector(PostgresCollectorMixin):
    def __init__(self):
        self.statements = []

    def _collector_rows(self, sql, params=()):
        self.statements.append((sql, params))
        if 'GROUP BY kind' in sql and 'host' not in sql.split('FROM')[0]:
            return [{'kind': 'a2a', 'n': 100}]
        return [{'host': 'big.example', 'kind': 'a2a', 'n': 97, 'ok': None}]


def test_host_kind_shares_binds_its_threshold_and_reads_two_groupings():
    collector = GroupingCollector()
    assert collector.host_kind_shares(1000) == {'kinds': {'a2a': 100}, 'hosts': [('big.example', 'a2a', 97, 0)]}
    assert collector.statements[1][1] == (1000,) and 'HAVING COUNT(*) >= %s' in collector.statements[1][0]
    import pytest
    with pytest.raises(ApplicationStoreError):
        collector.host_kind_shares(0)

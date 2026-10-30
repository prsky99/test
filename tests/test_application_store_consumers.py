"""Named current admin consumer limits precede any native SQL."""
import pytest
import json
from contextlib import nullcontext
from types import SimpleNamespace
from agent_market.application_store_consumers import PostgresConsumerMixin
from agent_market.application_store_postgres import ApplicationStoreError, _values


@pytest.mark.parametrize('kwargs',[{'q':'bad\0text'},{'q':'x'*4097},{'offset':-1},{'offset':True},{'limit':0},{'limit':1001},{'contact':None}])
def test_visiting_agent_query_refuses_bad_values_before_any_transaction(kwargs):
    # This object has no database. Reaching one would fail the contract.
    with pytest.raises(ApplicationStoreError,match='invalid_parameters'):
        PostgresConsumerMixin().visitor_desk_list(**kwargs)


def test_circuit_duplicate_ids_obey_production_scalar_parameter_contract():
    """Unit guard for the real invalid_parameters failure; native IO is separate."""
    class BoundProbe(PostgresConsumerMixin):
        def tx(self, **kwargs):
            return nullcontext()

        def get_meta(self, key, default=None):
            return default

        def _execute(self, statement, params=()):
            _values(params)
            if 'jsonb_array_elements_text' in statement:
                assert params == ('[1]',)
                assert json.loads(params[0]) == [1]
                rows = ([{'id': 1, 'kind': 'mcp', 'name': 'Probe'}] if 'SELECT id,kind,name' in statement
                        else [{'resource_id': 2}])
            else:
                rows = [{'resource_id': 1}]
            return SimpleNamespace(fetchall=lambda: rows)

    assert BoundProbe().global_failing_resources() == {1, 2}


def test_circuit_duplicates_use_name_index_only_for_ascii_names():
    """translate() lowers ASCII only; other names keep the full LOWER() match."""
    statements = []
    class Probe(PostgresConsumerMixin):
        def tx(self, **kwargs):
            return nullcontext()

        def get_meta(self, key, default=None):
            return default

        def _execute(self, statement, params=()):
            _values(params)
            statements.append((statement, params))
            if 'SELECT id,kind,name' in statement:
                rows = [{'id': 1, 'kind': 'mcp', 'name': 'Weather'}, {'id': 3, 'kind': 'mcp', 'name': 'Météo'}]
            elif 'jsonb_array_elements_text' in statement:
                rows = [{'resource_id': 4 if 'translate' in statement else 5}]
            else:
                rows = [{'resource_id': 1}, {'resource_id': 3}]
            return SimpleNamespace(fetchall=lambda: rows)

    assert Probe().global_failing_resources() == {1, 3, 4, 5}
    duplicate_queries = [(s, p) for s, p in statements if 'JOIN resources r2' in s]
    assert [(('translate' in s), json.loads(p[0])) for s, p in duplicate_queries] == [(True, [1]), (False, [3])]

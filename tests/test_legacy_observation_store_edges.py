"""Caught child faults must not commit a prefix of a guarded Store bundle."""
import sqlite3

import pytest

from tests.test_legacy_observation_guards_review import full_store
from tests.test_catalog_writer_review import logical_state


class AcceptedChildFault(sqlite3.Connection):
    fail_prefix = None
    injected = 0

    def execute(self, sql, parameters=()):
        result = super().execute(sql, parameters)
        if self.fail_prefix and sql.lstrip().startswith(self.fail_prefix):
            self.fail_prefix = None
            self.injected += 1
            raise RuntimeError('Synthetic accepted child observation fault')
        return result


@pytest.fixture
def edge_store(full_store):
    from agent_market.gateway.rag import ensure_vec_table
    store, rid = full_store
    store._db.close()
    connection = sqlite3.connect(store._path, check_same_thread=False, factory=AcceptedChildFault)
    connection.row_factory = sqlite3.Row
    assert ensure_vec_table(connection)
    store._db = connection
    return store, rid, connection


def capability(store, rid):
    store.record_capability(rid, {'languages': ['en'], 'regions': [], 'currencies': [],
        'tool_count': 1, 'tool_names': ['syntheticchildtool']})


def usage(store, rid):
    tools = [{'name': 'syntheticchildtool', 'description': 'Synthetic child tool'}]
    full = [tools[0] | {'inputSchema': {'type': 'object', 'properties': {}}}]
    store.record_usage(rid, tools, '6' * 64, {}, None, None, full_tools=full)


def test_swallowed_accepted_usage_write_fault_rolls_back_prior_capability_and_consumption(edge_store):
    store, rid, connection = edge_store
    token = store.observation_guard(rid, 'survey', expected_resource=store.resource(rid))
    before = logical_state(connection)
    caught_child = []
    with pytest.raises(sqlite3.DatabaseError):
        with store.observation_transaction(token):
            capability(store, rid)
            connection.fail_prefix = 'UPDATE resources SET usage_tools='
            try:
                usage(store, rid)
            except RuntimeError:
                # This mirrors the prior collector's optional record-error catch.
                caught_child.append(True)
    assert caught_child == [True] and connection.injected == 1
    assert logical_state(connection) == before
    assert not connection.in_transaction and store._observation_context is None
    assert store.resource(rid)['cap_checked_at'] is None
    assert store.query('SELECT applied_sequence FROM resource_observation_owners')[0][0] == 0


def test_accepted_release_then_caught_error_cannot_commit_the_child_or_bundle_prefix(edge_store):
    store, rid, connection = edge_store
    token = store.observation_guard(rid, 'survey', expected_resource=store.resource(rid))
    before = logical_state(connection)
    caught_child = []
    with pytest.raises(sqlite3.DatabaseError):
        with store.observation_transaction(token):
            capability(store, rid)
            connection.fail_prefix = 'RELEASE SAVEPOINT '
            try:
                usage(store, rid)
            except (RuntimeError, sqlite3.DatabaseError):
                # The release actually succeeded; rollback-to that name can fail.
                caught_child.append(True)
    assert caught_child == [True] and connection.injected == 1
    assert logical_state(connection) == before
    assert not connection.in_transaction and store._observation_context is None
    assert not store.query("SELECT rowid FROM resources_fts WHERE resources_fts MATCH 'syntheticchildtool'")
    assert store.query('SELECT applied_sequence FROM resource_observation_owners')[0][0] == 0

"""Independent full-Store stale-result and atomic observation regressions."""
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import Event

import pytest

from tests.test_catalog_writer_review import add_history, logical_state


def registration(**changes):
    return {
        'key': 'synthetic:legacy-guard:reader', 'source': 'synthetic-review', 'kind': 'mcp',
        'url': 'https://legacy-review.example/agent/a', 'name': 'Synthetic reader',
        'description': 'Weather climate documentation', 'category': 'research',
        'networks': [], 'details': {},
    } | changes


@pytest.fixture
def full_store(tmp_path):
    from agent_market.gateway.admin_auth import ADMIN_SCHEMA, create_admin_user
    from agent_market.gateway.store import Store
    path = tmp_path / 'synthetic-full-store.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(ADMIN_SCHEMA)
        create_admin_user(db, 'sadmin', 'Synthetic-guard-review-password-42', 'Synthetic reviewer', 'superadmin')
    store = Store(str(path))
    rid = store.upsert_resource(registration(), now=10)
    try:
        assert len(store.query('PRAGMA table_info(resources)')) >= 67
        yield store, rid
    finally:
        store._db.close()


@pytest.mark.parametrize('aba', [False, True])
def test_tracked_health_result_cannot_overwrite_a_changed_or_aba_endpoint(full_store, monkeypatch, aba):
    from agent_market.collector.health import HealthChecker, CheckResult
    store, rid = full_store
    initial = store.resource(rid)
    checker = HealthChecker(store)

    def delayed_result(resource):
        assert resource['url'] == initial['url']
        store.upsert_resource(registration(url='https://legacy-review.example/agent/b'), now=20)
        if aba:
            store.upsert_resource(registration(), now=30)
            assert store.resource(rid)['content_hash'] == initial['content_hash']
        return CheckResult('healthy', status_code=200, latency_ms=12)

    monkeypatch.setattr(checker, 'check', delayed_result)
    checker.check_and_record(initial)
    current = store.resource(rid)
    assert current['health_status'] == 'unknown'
    assert current['last_check_at'] is None
    assert not store.health_history(rid)


def test_removing_last_tool_removes_its_fts_terms_without_removing_registry_text(full_store):
    store, rid = full_store
    tools = [{'name': 'syntheticobsolete', 'description': 'Previous tool entry'}]
    complete = [tools[0] | {'inputSchema': {'type': 'object', 'properties': {}}}]
    store.record_usage(rid, tools, '1' * 64, {}, None, None, full_tools=complete)
    assert store.query("SELECT rowid FROM resources_fts WHERE resources_fts MATCH 'syntheticobsolete'")
    store.record_usage(rid, [], '2' * 64, {}, {'removed': ['syntheticobsolete']}, None, full_tools=[])
    assert not store.query("SELECT rowid FROM resources_fts WHERE resources_fts MATCH 'syntheticobsolete'")
    assert store.query("SELECT rowid FROM resources_fts WHERE resources_fts MATCH 'weather'")[0][0] == rid


def record_guarded_health(store, rid, token, *, outcome='healthy'):
    with store.observation_transaction(token):
        return store.record_health(rid, outcome, 200 if outcome != 'fail' else 500, 12, None,
                                   next_check_at=time.time() + 600)


def test_two_store_handles_reject_a_changed_back_binding_generation(full_store):
    from agent_market.gateway.store import Store
    from agent_market.observation_guards import GuardError
    store, rid = full_store
    initial = store.resource(rid)
    token = store.observation_guard(rid, 'health', expected_resource=initial)
    other = Store(store._path)
    try:
        other.upsert_resource(registration(url='https://legacy-review.example/agent/b'), now=20)
        other.upsert_resource(registration(), now=30)
        assert store.resource(rid)['content_hash'] == initial['content_hash']
        before = logical_state(store._db)
        with pytest.raises(GuardError) as captured:
            record_guarded_health(store, rid, token)
        assert captured.value.code == 'stale_generation'
        assert logical_state(store._db) == before
        assert not store._db.in_transaction
    finally:
        other._db.close()


def test_latest_owner_reservation_wins_across_store_handles_before_any_result(full_store):
    from agent_market.gateway.store import Store
    from agent_market.observation_guards import GuardError
    store, rid = full_store
    first = store.observation_guard(rid, 'health', expected_resource=store.resource(rid))
    other = Store(store._path)
    try:
        second = other.observation_guard(rid, 'health', expected_resource=other.resource(rid))
        before = logical_state(store._db)
        with pytest.raises(GuardError) as captured:
            record_guarded_health(store, rid, first)
        assert captured.value.code == 'stale_sequence'
        assert logical_state(store._db) == before
        record_guarded_health(other, rid, second, outcome='reachable')
        assert store.resource(rid)['health_status'] == 'reachable'
        assert len(store.health_history(rid)) == 1
    finally:
        other._db.close()


def test_foreign_store_cannot_apply_or_consume_an_issued_token(full_store):
    from agent_market.gateway.store import Store
    from agent_market.observation_guards import GuardError
    store, rid = full_store
    token = store.observation_guard(rid, 'health', expected_resource=store.resource(rid))
    other = Store(store._path)
    try:
        before = logical_state(store._db)
        with pytest.raises(GuardError) as captured:
            record_guarded_health(other, rid, token)
        assert captured.value.code == 'invalid_token'
        assert logical_state(store._db) == before
        record_guarded_health(store, rid, token)
        assert len(store.health_history(rid)) == 1
    finally:
        other._db.close()


def test_guarded_health_never_synthesizes_execution_evidence_or_approval(full_store):
    store, rid = full_store
    add_history(store._db, rid)
    before = logical_state(store._db)
    retained = {table: before[table] for table in ('connection_agents', 'connection_versions',
        'capability_evidence', 'capability_approvals')}
    token = store.observation_guard(rid, 'health', expected_resource=store.resource(rid))
    record_guarded_health(store, rid, token)
    after = logical_state(store._db)
    assert {table: after[table] for table in retained} == retained
    assert store.query('SELECT COUNT(*) FROM capability_eligibility')[0][0] == 0
    assert store.resource(rid)['trial_ok'] is None


def test_plain_compatible_write_invalidates_an_older_tracked_owner_token(full_store):
    from agent_market.observation_guards import GuardError
    store, rid = full_store
    store.record_health(rid, 'reachable', 200, 4, None, next_check_at=time.time() + 600)
    token = store.observation_guard(rid, 'health', expected_resource=store.resource(rid))
    store.record_health(rid, 'reachable', 200, 4, None, next_check_at=time.time() + 600)
    before = logical_state(store._db)
    with pytest.raises(GuardError) as captured:
        record_guarded_health(store, rid, token)
    assert captured.value.code == 'stale_sequence'
    assert logical_state(store._db) == before
    assert store.resource(rid)['health_status'] == 'reachable'


def test_independent_health_owner_does_not_discard_current_evaluation(full_store):
    store, rid = full_store
    store.record_health(rid, 'healthy', 200, 4, None, next_check_at=time.time() + 600)
    health = store.observation_guard(rid, 'health', expected_resource=store.resource(rid))
    evaluation = store.observation_guard(rid, 'evaluation', expected_resource=store.resource(rid))
    record_guarded_health(store, rid, health)
    with store.observation_transaction(evaluation):
        store.record_evaluation(rid, {'score': 87, 'grade': 'B', 'security': 'review', 'coverage': 'definitions'})
    assert store.resource(rid)['eval_grade'] == 'B'
    assert store.resource(rid)['health_status'] == 'healthy'


@pytest.mark.parametrize('binding_field,value', [
    ('auth_info', '{"method":"synthetic-changed-auth"}'),
    ('usage_full_hash', 'f' * 64),
])
def test_changed_auth_or_schema_blocks_older_guard_even_when_endpoint_is_same(full_store, binding_field, value):
    from agent_market.observation_guards import GuardError
    store, rid = full_store
    token = store.observation_guard(rid, 'evaluation', expected_resource=store.resource(rid))
    with store.tx() as db:
        db.execute('UPDATE resources SET ' + binding_field + '=? WHERE id=?', (value, rid))
    before = logical_state(store._db)
    with pytest.raises(GuardError) as captured:
        with store.observation_transaction(token):
            store.record_evaluation(rid, {'score': 99, 'grade': 'A', 'security': 'ok'})
    assert captured.value.code == 'stale_generation'
    assert logical_state(store._db) == before


@pytest.mark.parametrize('prefix', [
    'UPDATE resources SET cap_languages=', 'UPDATE resources SET usage_tools=',
    'DELETE FROM resources_fts ', 'INSERT INTO resources_fts',
    'INSERT OR REPLACE INTO vec_outbox',
])
def test_accepted_survey_sql_failure_rolls_back_the_entire_guarded_bundle(full_store, prefix):
    from agent_market.gateway.rag import ensure_vec_table
    store, rid = full_store

    class AcceptedFault(sqlite3.Connection):
        fail_prefix = None
        failures = 0
        def execute(self, sql, parameters=()):
            result = super().execute(sql, parameters)
            if self.fail_prefix and sql.lstrip().startswith(self.fail_prefix):
                self.failures += 1
                raise RuntimeError('synthetic-private-accepted-observation-failure')
            return result

    store._db.close()
    db = sqlite3.connect(store._path, check_same_thread=False, factory=AcceptedFault)
    db.row_factory = sqlite3.Row
    assert ensure_vec_table(db)
    store._db = db
    add_history(db, rid)
    token = store.observation_guard(rid, 'survey', expected_resource=store.resource(rid))
    before = logical_state(db)
    db.fail_prefix = prefix
    with pytest.raises(RuntimeError, match='synthetic-private-accepted-observation-failure'):
        with store.observation_transaction(token):
            store.record_capability(rid, {'languages': ['en'], 'regions': [], 'currencies': [],
                                         'tool_count': 1, 'tool_names': ['syntheticreference']})
            tools = [{'name': 'syntheticreference', 'description': 'Synthetic reference description'}]
            full = [tools[0] | {'inputSchema': {'type': 'object', 'properties': {}}}]
            store.record_usage(rid, tools, '3' * 64, {}, None, None, full_tools=full)
    db.fail_prefix = None
    assert db.failures == 1, 'The intended statement must execute before its simulated failure.'
    assert logical_state(db) == before
    assert not db.in_transaction


def test_outer_survey_exception_cannot_commit_nested_observation_writes(full_store):
    store, rid = full_store
    token = store.observation_guard(rid, 'survey', expected_resource=store.resource(rid))
    before = logical_state(store._db)
    with pytest.raises(RuntimeError, match='synthetic-bundle-failure'):
        with store.observation_transaction(token):
            store.record_capability(rid, {'languages': ['en'], 'regions': [], 'currencies': [],
                                         'tool_count': 0, 'tool_names': []})
            store.record_usage(rid, [], '4' * 64, {}, None, None, full_tools=[])
            raise RuntimeError('synthetic-bundle-failure')
    assert logical_state(store._db) == before
    assert not store._db.in_transaction


def test_guarded_bundle_cannot_mutate_another_resource(full_store):
    from agent_market.observation_guards import GuardError
    store, rid = full_store
    other = store.upsert_resource(registration(key='synthetic:other-reader',
        url='https://legacy-review.example/agent/other'), now=10)
    token = store.observation_guard(rid, 'health', expected_resource=store.resource(rid))
    before = logical_state(store._db)
    with pytest.raises(GuardError) as captured:
        with store.observation_transaction(token):
            store.record_health(other, 'healthy', 200, 5, None, next_check_at=time.time() + 600)
    assert captured.value.code == 'invalid_token'
    assert logical_state(store._db) == before
    assert not store.health_history(other)


def test_failed_survey_invalidates_an_older_evaluation_without_erasing_recorded_grade(full_store):
    from agent_market.observation_guards import GuardError
    store, rid = full_store
    store.record_evaluation(rid, {'score': 87, 'grade': 'B', 'security': 'review', 'coverage': 'definitions'})
    token = store.observation_guard(rid, 'evaluation', expected_resource=store.resource(rid))
    store.record_capability(rid, None, 'synthetic survey failure')
    assert store.resource(rid)['eval_at'] is None
    assert store.resource(rid)['eval_grade'] == 'B'
    before = logical_state(store._db)
    with pytest.raises(GuardError) as captured:
        with store.observation_transaction(token):
            store.record_evaluation(rid, {'score': 99, 'grade': 'A', 'security': 'ok'})
    assert captured.value.code == 'stale_generation'
    assert logical_state(store._db) == before


def test_commit_after_accept_poisons_handle_and_reopen_never_replays_old_token(full_store):
    from agent_market.gateway.rag import ensure_vec_table
    from agent_market.gateway.store import Store
    from agent_market.observation_guards import GuardError
    store, rid = full_store

    class CommitLost(sqlite3.Connection):
        armed = False
        attempts = 0
        def commit(self):
            super().commit()
            if self.armed:
                self.attempts += 1
                raise RuntimeError('synthetic-private-observation-commit-acknowledgement-lost')

    store._db.close()
    db = sqlite3.connect(store._path, check_same_thread=False, factory=CommitLost)
    db.row_factory = sqlite3.Row
    assert ensure_vec_table(db)
    store._db = db
    token = store.observation_guard(rid, 'health', expected_resource=store.resource(rid))
    db.armed = True
    with pytest.raises(RuntimeError, match='synthetic-private-observation-commit-acknowledgement-lost'):
        record_guarded_health(store, rid, token)
    assert db.attempts == 1 and store._observation_broken is True
    assert len(store.health_history(rid)) == 1
    with pytest.raises(GuardError) as captured:
        store.observation_guard(rid, 'health', expected_resource=store.resource(rid))
    assert captured.value.code == 'invalid_token'
    fresh = Store(store._path)
    try:
        assert fresh.resource(rid)['health_status'] == 'healthy'
        assert len(fresh.health_history(rid)) == 1
        before = logical_state(fresh._db)
        with pytest.raises(GuardError) as captured:
            record_guarded_health(fresh, rid, token)
        assert captured.value.code == 'invalid_token'
        assert logical_state(fresh._db) == before
    finally:
        fresh._db.close()


def test_other_thread_cannot_borrow_a_foreign_active_observation_context(full_store):
    from agent_market.observation_guards import GuardError
    store, rid = full_store
    payload = {'score': 84, 'grade': 'B', 'security': 'review', 'at': time.time() - 10}
    store.record_evaluation(rid, payload)
    token = store.observation_guard(rid, 'health', expected_resource=store.resource(rid))
    entered = Event()

    def ordinary_caller():
        entered.set()
        store.record_evaluation(rid, payload)

    foreign_error = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.observation_transaction(token):
            result = pool.submit(ordinary_caller)
            assert entered.wait(timeout=2)
            try:
                result.result(timeout=0.05)
            except FutureTimeout:
                pass
            except GuardError as exc:
                foreign_error = exc.code
        if foreign_error is None:
            result.result(timeout=2)
    assert foreign_error is None, 'An ordinary caller saw a different thread\'s private observation context.'


def test_successful_mcp_handshakes_preserve_tool_auth_and_none_discovery_cannot_clear_it(full_store):
    import json
    import httpx
    from agent_market.collector.health import HealthChecker
    store, rid = full_store
    methods = []

    def transport(request):
        method = json.loads(request.content)['method']
        methods.append(method)
        if method == 'server/discover':
            return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 1,
                'error': {'code': -32601, 'message': 'Method not found'}})
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 1, 'result': {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'serverInfo': {'name': 'Synthetic reader', 'version': '1'}}})

    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        checker = HealthChecker(store, http=http, allow_private=True)
        assert checker.check_and_record(store.resource(rid))['accepted'] is True
        assert store.resource(rid)['auth_observed'] == 0
        store.mark_tool_level_auth(rid)
        assert store.resource(rid)['auth_observed'] == 1
        assert checker.check_and_record(store.resource(rid))['accepted'] is True
    current = store.resource(rid)
    assert current['health_status'] == 'healthy'
    assert current['auth_observed'] == 1 and current['auth_scope'] == 'tool'
    assert methods.count('initialize') == 2 and len(store.health_history(rid)) == 2
    # A synthetic no-auth discovery result still describes only connection access.
    guard = store.observation_guard(rid, 'auth', expected_resource=current)
    with store.observation_transaction(guard):
        store.record_auth(rid, {'method': 'none', 'autonomy': 'none_needed', 'info': {'synthetic': True}})
    assert store.resource(rid)['auth_observed'] == 1 and store.resource(rid)['auth_scope'] == 'tool'

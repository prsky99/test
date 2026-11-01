"""Independent observation ownership, atomicity, and recovery boundaries."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.test_catalog_index_review import components
from tests.test_catalog_writer_review import FaultConnection, add_history, command, logical_state, operation


def observation_operation(number):
    return 'ob_' + format(number, '032x')


def observation_system(db):
    from agent_market.catalog_observations import OBSERVATION_SCHEMA, CatalogObservations
    system = components(db)
    with system.adapter.transaction() as session:
        for statement in OBSERVATION_SCHEMA:
            session.execute(statement)
    system.observations = CatalogObservations(system.adapter)
    written = system.writer.upsert(command(name='Weather reader', description='Weather climate reference'),
        operation_id=operation(1), expected_revision=0, observed_at=10)
    system.rid = written.resource_id
    # This is retained synthetic initial state, not an observation from a provider.
    db.execute("UPDATE resources SET health_status='healthy',eval_security='ok' WHERE id=?", (system.rid,))
    db.commit()
    add_history(db, system.rid)
    return system


@pytest.fixture
def observed():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    try:
        yield observation_system(db)
    finally:
        db.close()


def resource(system):
    return dict(system.db.execute('SELECT * FROM resources WHERE id=?', (system.rid,)).fetchone())


def revision(system):
    return dict(system.db.execute('SELECT * FROM catalog_resource_revisions WHERE resource_id=?', (system.rid,)).fetchone())


def immutable_history(system):
    snapshot = logical_state(system.db)
    return {name: snapshot[name] for name in ('connection_agents', 'connection_versions',
        'capability_approvals', 'capability_evidence')}


def record(system, payload, *, number=1, expected_revision=1, observed_at=20):
    return system.observations.record(system.rid, payload, operation_id=observation_operation(number),
        expected_revision=expected_revision, observed_at=observed_at)


def successful_survey(*, full=True):
    from agent_market.catalog_observations import SurveyObservation
    tools = [{'name': 'synthetic_tool_label', 'description': 'Synthetic private tool phrase'}]
    complete = [tools[0] | {'inputSchema': {'type': 'object', 'properties': {}}}]
    return SurveyObservation(tools_json=json.dumps(tools),
        guide_json='{"endpoint":"https://provider.example/project/tools","token":"synthetic-private-survey"}',
        full_tools_json=json.dumps(complete) if full else None)


def test_health_preserves_registry_hashes_model_and_immutable_evidence(observed):
    from agent_market.catalog_observations import HealthObservation
    before = resource(observed)
    before_revision = revision(observed)
    history = immutable_history(observed)
    result = record(observed, HealthObservation('healthy', next_check_at=50))
    after = resource(observed)
    after_revision = revision(observed)
    assert (result.status, result.owner, result.revision, result.replayed) == ('committed', 'health', 2, False)
    for name in ('id', 'key', 'source', 'kind', 'url', 'name', 'description', 'category', 'details',
                 'networks', 'price_usdc', 'pay_to', 'method', 'first_seen', 'last_seen', 'active',
                 'content_hash', 'calls_30d', 'payers_30d', 'auth_declared', 'auth_observed', 'auth_info'):
        assert after[name] == before[name], name
    for name in ('content_hash', 'hash_profile', 'corpus_hash', 'model_hash', 'updated_at'):
        assert after_revision[name] == before_revision[name], name
    assert immutable_history(observed) == history
    assert observed.db.execute('SELECT COUNT(*) FROM capability_eligibility').fetchone()[0] == 0
    assert observed.db.execute('SELECT revision FROM catalog_index_heads').fetchone()[0] == 2
    assert observed.db.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone()[0] == 2
    assert after['last_check_at'] == 20 and after['last_ok_at'] == 20 and after['next_check_at'] == 50


def test_equal_health_payload_advances_once_but_operation_replay_does_not(observed):
    from agent_market.catalog_observations import HealthObservation
    payload = HealthObservation('reachable')
    first = record(observed, payload)
    second = record(observed, payload, number=2, expected_revision=2, observed_at=21)
    assert first.revision == 2 and second.revision == 3
    before = logical_state(observed.db)
    replay = record(observed, payload, number=2, expected_revision=2, observed_at=21)
    assert replay.status == 'committed' and replay.revision == 3 and replay.replayed is True
    assert logical_state(observed.db) == before


def test_stale_registry_generation_conflicts_without_overwriting_new_endpoint(observed):
    from agent_market.catalog_observations import HealthObservation
    changed = observed.writer.upsert(command(name='New endpoint reader', url='https://other.example/agent'),
        operation_id=operation(2), expected_revision=1, observed_at=30)
    before = resource(observed)
    history = immutable_history(observed)
    stale = record(observed, HealthObservation('healthy'), expected_revision=1, observed_at=40)
    assert stale.status == 'conflict' and stale.revision == changed.revision
    assert resource(observed) == before
    assert immutable_history(observed) == history
    assert observed.observations.current(observed.rid, owner='health') is None
    replay_before = logical_state(observed.db)
    replay = record(observed, HealthObservation('healthy'), expected_revision=1, observed_at=40)
    assert replay.status == 'conflict' and replay.replayed is True
    assert logical_state(observed.db) == replay_before


def test_owner_clocks_are_independent_and_old_owner_result_cannot_overwrite(observed):
    from agent_market.catalog_observations import HealthObservation, EvaluationObservation
    record(observed, HealthObservation('healthy'), observed_at=100)
    survey = record(observed, successful_survey(), number=2, expected_revision=2, observed_at=50)
    evaluation = record(observed, EvaluationObservation(91, 'A', 'ok'), number=3, expected_revision=3, observed_at=60)
    assert survey.status == evaluation.status == 'committed'
    assert observed.observations.current(observed.rid, owner='health').observed_at == 100
    assert observed.observations.current(observed.rid, owner='survey').observed_at == 50
    assert observed.observations.current(observed.rid, owner='evaluation').observed_at == 60
    before = logical_state(observed.db)
    with pytest.raises(ValueError) as captured:
        record(observed, HealthObservation('fail'), number=4, expected_revision=4, observed_at=99)
    assert captured.value.code == 'stale_observation'
    assert logical_state(observed.db) == before


def test_survey_missing_full_schema_clears_retained_full_schema_even_with_equal_compact_tools(observed):
    record(observed, successful_survey())
    complete = resource(observed)
    assert complete['usage_full_tools'] is not None and complete['usage_full_hash'] is not None
    result = record(observed, successful_survey(full=False), number=2, expected_revision=2, observed_at=21)
    latest = resource(observed)
    assert result.status == 'committed'
    assert latest['usage_tools_hash'] == complete['usage_tools_hash']
    assert latest['usage_full_tools'] is None and latest['usage_full_hash'] is None


def test_failed_survey_preserves_previous_payload_without_claiming_fresh_success(observed):
    from agent_market.catalog_observations import SurveyObservation
    record(observed, successful_survey())
    before = resource(observed)
    history = immutable_history(observed)
    result = record(observed, SurveyObservation(error_code='survey_failed'), number=2, expected_revision=2, observed_at=21)
    after = resource(observed)
    assert result.status == 'committed' and result.revision == 3
    for name in ('usage_tools', 'usage_tools_hash', 'usage_full_tools', 'usage_full_hash', 'usage_guide'):
        assert after[name] == before[name], name
    assert after['cap_checked_at'] is None
    assert observed.observations.current(observed.rid, owner='survey').outcome == 'failed'
    assert immutable_history(observed) == history


def test_accepting_observation_invalidates_prepared_index_work_then_rebuilds_same_corpus(observed):
    from agent_market.catalog_observations import HealthObservation
    claim = observed.outbox.claim('old-index-worker', now=11, lease_seconds=60)
    artifact = observed.index.build(claim)
    record(observed, HealthObservation('healthy'))
    before = logical_state(observed.db)
    assert observed.index.publish(claim, artifact, now=21) in ('stale_claim', 'superseded')
    assert logical_state(observed.db) == before
    current = observed.outbox.claim('current-index-worker', now=22)
    assert current.revision == 2 and current.corpus_hash == claim.corpus_hash and current.model_hash == claim.model_hash
    latest = observed.index.build(current)
    assert latest.terms == artifact.terms
    assert observed.index.publish(current, latest, now=23) == 'indexed'
    assert observed.index.search('weather climate')[0].revision == 2


def test_observation_payloads_do_not_enter_lexical_corpus_or_synthesize_callability(observed, monkeypatch):
    import socket
    import httpx
    from agent_market.capability_registry import Registry
    from agent_market.catalog_observations import EvaluationObservation
    def forbidden(*_args, **_kwargs):
        raise AssertionError('No provider, network or registry activity is permitted here.')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(Registry, 'current', forbidden)
    history = immutable_history(observed)
    record(observed, successful_survey())
    record(observed, EvaluationObservation(100, 'A', 'ok'), number=2, expected_revision=2, observed_at=21)
    current = observed.outbox.claim('private-index-worker', now=22)
    artifact = observed.index.build(current)
    assert 'synthetic' not in artifact.terms and 'phrase' not in artifact.terms and 'survey' not in artifact.terms
    assert observed.index.publish(current, artifact, now=23) == 'indexed'
    assert observed.index.search('weather climate')
    assert immutable_history(observed) == history
    assert observed.db.execute('SELECT COUNT(*) FROM capability_eligibility').fetchone()[0] == 0


@pytest.mark.parametrize('prefix', [
    'UPDATE resources SET health_status=',
    'UPDATE catalog_resource_revisions SET revision=',
    'DELETE FROM capability_eligibility',
    'UPDATE catalog_index_heads SET revision=',
    'INSERT INTO catalog_index_jobs ',
    'INSERT INTO catalog_observation_heads ',
    'INSERT INTO catalog_observation_operations ',
])
def test_accepted_sql_failure_rolls_back_every_observation_effect(prefix):
    from agent_market.catalog_observations import HealthObservation
    from agent_market.storage_adapter import StorageError
    db = sqlite3.connect(':memory:', factory=FaultConnection)
    db.row_factory = sqlite3.Row
    try:
        system = observation_system(db)
        claim = system.outbox.claim('retained-index-worker', now=11)
        artifact = system.index.build(claim)
        assert system.index.publish(claim, artifact, now=12) == 'indexed'
        before = logical_state(db)
        db.fail_prefix = prefix
        with pytest.raises(StorageError) as captured:
            record(system, HealthObservation('fail'), observed_at=20)
        assert captured.value.code == 'statement_failed'
        assert str(captured.value) == 'statement_failed'
        assert db.failures == 1, 'The intended SQL must have executed before its simulated failure.'
        db.fail_prefix = None
        assert logical_state(db) == before
        assert system.observations.reconcile(observation_operation(1)) is None
        assert system.observations.current(system.rid, owner='health') is None
        assert system.index.artifact(system.rid) == artifact
        assert system.index.search('weather climate')[0].revision == 1
    finally:
        db.close()


def test_commit_after_accept_is_resolved_by_fresh_connection_without_second_observation(tmp_path):
    from agent_market.catalog_observations import CatalogObservations, HealthObservation
    from agent_market.storage_adapter import SQLiteAdapter, StorageError

    class CommitLost(sqlite3.Connection):
        armed = False
        attempts = 0
        def commit(self):
            super().commit()
            if self.armed:
                self.attempts += 1
                raise RuntimeError('synthetic-private-commit-acknowledgement-lost')

    path = tmp_path / 'synthetic-observations.sqlite3'
    db = sqlite3.connect(path, factory=CommitLost)
    db.row_factory = sqlite3.Row
    try:
        system = observation_system(db)
        identity = system.rid
        immutable = immutable_history(system)
        payload = HealthObservation('reachable', next_check_at=30)
        db.armed = True
        with pytest.raises(StorageError) as captured:
            record(system, payload)
        assert captured.value.code == 'commit_unknown'
        assert db.attempts == 1
    finally:
        db.close()
    fresh = sqlite3.connect(path)
    fresh.row_factory = sqlite3.Row
    try:
        observations = CatalogObservations(SQLiteAdapter(fresh))
        receipt = observations.reconcile(observation_operation(1))
        assert (receipt.status, receipt.owner, receipt.resource_id, receipt.revision) == ('committed', 'health', identity, 2)
        head = observations.current(identity, owner='health')
        assert (head.observed_at, head.revision, head.outcome) == (20, 2, 'reachable')
        row = fresh.execute('SELECT health_status,last_check_at,last_ok_at,next_check_at FROM resources').fetchone()
        assert tuple(row) == ('reachable', 20, 20, 30)
        assert fresh.execute('SELECT COUNT(*) FROM capability_eligibility').fetchone()[0] == 0
        assert fresh.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone()[0] == 2
        assert {name: logical_state(fresh)[name] for name in immutable} == immutable
        before = logical_state(fresh)
        replay = observations.record(identity, payload, operation_id=observation_operation(1), expected_revision=1, observed_at=20)
        assert replay.replayed is True and replay.revision == 2
        assert logical_state(fresh) == before
    finally:
        fresh.close()


def test_two_native_connections_cannot_apply_the_same_resource_generation_twice(tmp_path):
    from agent_market.catalog_observations import CatalogObservations, HealthObservation
    from agent_market.storage_adapter import SQLiteAdapter
    path = tmp_path / 'synthetic-cas.sqlite3'
    initial = sqlite3.connect(path)
    initial.row_factory = sqlite3.Row
    try:
        initial.execute('PRAGMA journal_mode=WAL')
        system = observation_system(initial)
        identity = system.rid
        history = immutable_history(system)
    finally:
        initial.close()
    ready = Barrier(2)

    def work(number, outcome):
        db = sqlite3.connect(path, timeout=3)
        try:
            observer = CatalogObservations(SQLiteAdapter(db))
            ready.wait(timeout=3)
            return observer.record(identity, HealthObservation(outcome), operation_id=observation_operation(number),
                expected_revision=1, observed_at=20 + number)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [future.result(timeout=5) for future in (
            executor.submit(work, 1, 'healthy'), executor.submit(work, 2, 'reachable'))]
    assert sorted(item.status for item in results) == ['committed', 'conflict']
    assert all(item.revision == 2 for item in results)
    check = sqlite3.connect(path)
    try:
        assert check.execute('SELECT revision FROM catalog_resource_revisions').fetchone()[0] == 2
        assert check.execute('SELECT COUNT(*) FROM catalog_observation_heads').fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM catalog_observation_operations WHERE status='committed'").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM catalog_observation_operations WHERE status='conflict'").fetchone()[0] == 1
        assert check.execute('SELECT health_n_24h FROM resources').fetchone()[0] == 1
        assert check.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone()[0] == 2
        assert {name: logical_state(check)[name] for name in history} == history
    finally:
        check.close()


def test_reconcile_and_current_remain_read_only_when_write_control_is_paused(observed):
    from agent_market.catalog_observations import HealthObservation, ObservationError
    record(observed, HealthObservation('healthy'))
    observed.db.execute('UPDATE catalog_write_controls SET enabled=0,revision=2 WHERE id=1')
    observed.db.commit()
    before = logical_state(observed.db)
    assert observed.observations.reconcile(observation_operation(1)).revision == 2
    assert observed.observations.current(observed.rid, owner='health').observed_at == 20
    with pytest.raises(ObservationError) as captured:
        record(observed, HealthObservation('healthy'))
    assert captured.value.code == 'write_disabled'
    assert logical_state(observed.db) == before


@pytest.mark.parametrize('failed', [False, True])
def test_survey_invalidates_evaluation_freshness_without_erasing_its_recorded_state(observed, failed):
    from agent_market.catalog_observations import EvaluationObservation, SurveyObservation
    record(observed, EvaluationObservation(92, 'A', 'review'), observed_at=20)
    head = observed.observations.current(observed.rid, owner='evaluation')
    before = resource(observed)
    survey = SurveyObservation(error_code='survey_failed') if failed else successful_survey()
    record(observed, survey, number=2, expected_revision=2, observed_at=30)
    after = resource(observed)
    assert after['eval_at'] is None, 'Survey changes must not advertise a retained assessment as current.'
    assert after['eval_score'] == before['eval_score']
    assert after['eval_grade'] == before['eval_grade']
    assert after['eval_security'] == before['eval_security']
    assert observed.observations.current(observed.rid, owner='evaluation') == head


@pytest.mark.parametrize('failed', [False, True])
def test_old_evaluation_time_cannot_revalidate_a_newer_survey_generation(observed, failed):
    from agent_market.catalog_observations import EvaluationObservation, ObservationError, SurveyObservation
    record(observed, EvaluationObservation(92, 'A', 'review'), observed_at=20)
    survey = SurveyObservation(error_code='survey_failed') if failed else successful_survey()
    record(observed, survey, number=2, expected_revision=2, observed_at=30)
    before = logical_state(observed.db)
    with pytest.raises(ObservationError) as captured:
        record(observed, EvaluationObservation(99, 'A', 'ok'), number=3, expected_revision=3, observed_at=25)
    assert captured.value.code == 'stale_observation'
    assert logical_state(observed.db) == before
    assert resource(observed)['eval_at'] is None
    fresh = record(observed, EvaluationObservation(94, 'A', 'review'), number=4, expected_revision=3, observed_at=31)
    assert fresh.status == 'committed' and fresh.revision == 4
    assert resource(observed)['eval_at'] == 31

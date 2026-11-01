"""Fail-closed application PostgreSQL boundaries, without opening a database."""
import math
import threading
from types import SimpleNamespace

import pytest

from agent_market.application_store_postgres import (
    ApplicationStoreError, PostgresApplicationStore, _LegacyConnection,
    _Cursor, _normalized, _values, _STATEMENTS,
)
from agent_market.storage_adapter import Row, open_store


@pytest.mark.parametrize('values', [(math.nan,), (math.inf,), ({'private': 'value'},),
    ('nul\0value',), (2**63,), (-2**63 - 1,), [object()], tuple(range(257))])
def test_invalid_bound_parameters_are_rejected_before_native_driver(values):
    with pytest.raises(ApplicationStoreError, match='invalid_parameters'):
        _values(values)


def test_parameter_bytes_are_bounded_without_rendering_private_values():
    with pytest.raises(ApplicationStoreError) as caught:
        _values(('synthetic-private' * 600000,))
    assert caught.value.code == 'parameter_limit'
    assert 'synthetic-private' not in str(caught.value)


def test_current_store_boolean_bindings_have_sqlite_integer_semantics():
    assert _values((True, False, 1)) == (1, 0, 1)


def test_sql_format_normalization_preserves_literal_identifier_and_comment_bytes():
    assert _normalized(" SELECT  id\n FROM resources WHERE name='two  spaces' ") == "SELECT id FROM resources WHERE name='two  spaces'"
    assert _normalized("SELECT 'O''Reilly  text'") != _normalized("SELECT 'O''Reilly text'")
    assert _normalized('SELECT "two  spaces"') != _normalized('SELECT "two spaces"')
    assert _normalized('SELECT 1 -- comment\n') == 'SELECT 1 -- comment'
    assert _normalized('SELECT 1; DELETE FROM resources') not in _STATEMENTS


@pytest.mark.parametrize('sql', ['DROP TABLE resources', 'SELECT synthetic_not_registered',
    "SELECT * FROM resources WHERE id=1 OR 'private'='private'", 'SELECT 1; DELETE FROM admin_sessions'])
def test_unregistered_sql_is_refused_and_caught_error_poisoned_transaction(sql):
    store = SimpleNamespace(_depth=1, _failed=False)
    db = _LegacyConnection(store)
    with pytest.raises(ApplicationStoreError) as caught: db.execute(sql)
    assert caught.value.code == 'unsupported_application_sql'
    assert store._failed is True
    assert sql not in str(caught.value)


def direct_store(connection, *, failed=False):
    store = PostgresApplicationStore.__new__(PostgresApplicationStore)
    store._connection = connection
    store._owner, store._depth, store._direct = threading.get_ident(), 1, True
    store._broken, store._closed, store._failed = False, False, failed
    store._lock = threading.RLock()
    return store


@pytest.mark.parametrize('failed,commit', [(False, False), (True, True)])
def test_direct_rollback_failure_permanently_poisoned_connection(failed, commit):
    def fail(): raise RuntimeError('Synthetic rollback acknowledgement failure')
    store = direct_store(SimpleNamespace(rollback=fail), failed=failed)
    with pytest.raises(ApplicationStoreError, match='rollback_unknown'):
        store._finish_direct(commit)
    assert store._broken and store._depth == 0 and not store._direct
    with pytest.raises(ApplicationStoreError, match='connection_unusable'):
        with store.tx(): pytest.fail('Poisoned connection was reused')


def test_direct_commit_acknowledgement_failure_never_becomes_known_rollback():
    calls = []
    def commit(): calls.append('commit'); raise RuntimeError('Synthetic lost commit acknowledgement')
    store = direct_store(SimpleNamespace(commit=commit, rollback=lambda: calls.append('rollback')))
    with pytest.raises(ApplicationStoreError, match='commit_unknown'): store._finish_direct(True)
    assert store._broken and calls == ['commit'] and store._depth == 0


def test_cursor_close_uncertainty_cannot_commit_preceding_writes():
    store = direct_store(SimpleNamespace())
    def fail(): raise RuntimeError('Synthetic cursor cleanup failure')
    store._native = lambda *_args: SimpleNamespace(rowcount=1, description=None, close=fail)
    with pytest.raises(ApplicationStoreError, match='connection_unusable'): store._execute('synthetic')
    assert store._broken and store._failed


def test_execute_then_cursor_close_failure_permanently_poisoned_connection():
    store = direct_store(SimpleNamespace())
    def execute(*_args): raise RuntimeError('Synthetic statement failure')
    def close(): raise RuntimeError('Synthetic cursor cleanup failure')
    store._connection = SimpleNamespace(cursor=lambda **_kwargs: SimpleNamespace(execute=execute, close=close))
    with pytest.raises(ApplicationStoreError, match='connection_unusable'): store._execute('synthetic')
    assert store._broken and store._failed
    store._depth = 0
    with pytest.raises(ApplicationStoreError, match='connection_unusable'):
        with store.tx(): pytest.fail('Uncertain driver handle reused')


def test_advisory_begin_failure_with_failed_cleanup_poisoned_connection():
    def rollback(): raise RuntimeError('Synthetic rollback failed')
    store = direct_store(SimpleNamespace(info=SimpleNamespace(transaction_status=0), rollback=rollback))
    store._depth, store._direct = 0, False
    store._native = lambda *a: _Cursor()
    def control(): raise ApplicationStoreError('statement_failed')
    store._transaction_controls = control
    with pytest.raises(ApplicationStoreError): store._begin_direct()
    assert store._broken


def test_dbapi_result_snapshot_retains_description_named_and_positional_access():
    result = _Cursor((Row(('id', 'text'), (7, 'Synthetic text')),), rowcount=1)
    assert tuple(item[0] for item in result.description) == ('id', 'text')
    row = result.fetchone()
    assert row[0] == row['id'] == 7 and dict(row) == {'id': 7, 'text': 'Synthetic text'}
    assert result.fetchone() is None and result.fetchall() == []


def test_factory_full_application_requires_explicit_key_before_any_connection_io():
    class NoIo:
        @property
        def autocommit(self): pytest.fail('Unsupported capability inspected connection')
    with pytest.raises(ApplicationStoreError, match='explicit_workflow_key_required'):
        open_store('postgresql', connection=NoIo(), initialize=True, required_capabilities=('full_application',))
    with pytest.raises(ApplicationStoreError, match='unsupported_application_capability'):
        open_store('postgresql', connection=NoIo(), initialize=True, required_capabilities=('unreviewed_future_application',))


def test_only_bounded_vector_claim_query_variants_are_registered():
    eligible = "active=1 AND COALESCE(health_status,'unknown')!='retired' AND COALESCE(eval_security,'')!='quarantine'"
    def sql(count):
        return 'SELECT id FROM resources WHERE ' + eligible + ' AND id IN (' + ','.join('?' for _ in range(count)) + ') ORDER BY id LIMIT ?'
    assert _normalized(sql(1)) in _STATEMENTS
    assert _normalized(sql(50)) in _STATEMENTS
    assert _normalized(sql(51)) not in _STATEMENTS


def test_rehearsal_cli_runs_only_after_explicit_run_and_never_accepts_dsn(monkeypatch):
    from scripts import rehearse_application_store_postgres as runner
    monkeypatch.setattr(runner, 'rehearse', lambda: pytest.fail('Invalid arguments reached native harness'))
    with pytest.raises(SystemExit): runner.main([])
    with pytest.raises(SystemExit): runner.main(['--run', '--dsn', 'postgresql://private.invalid/operating'])


def test_actual_application_postgres_contracts_ignore_parent_connection_and_key_configuration(monkeypatch):
    import os
    from scripts.rehearse_application_store_postgres import rehearse
    poisoned = {'PGHOSTADDR': '127.0.0.1', 'PGSERVICE': 'synthetic-no-such-service',
        'PGOPTIONS': '-c invalid_synthetic_setting=1', 'AGENT_ADMIN_BOOTSTRAP_PASSWORD_FILE': '/private/absent-synthetic-key',
        'AGENT_PRIVATE_ARTIFACT_KEYRING': '/private/absent-synthetic-keyring'}
    for key, value in poisoned.items(): monkeypatch.setenv(key, value)
    before = dict(os.environ)
    result = rehearse()
    assert dict(os.environ) == before
    assert len(result['checks']) >= 30 and all(value is True for value in result['checks'].values())
    assert result['temporary_cluster_removed'] and result['synthetic']
    assert result['production_actions'] == result['external_provider_calls'] == 0
    assert not result['production_cutover'] and not result['coverage']['full_application_ready']
    required = {'native_factory_atomic_idempotent_private_save',
                'native_sdk_source_version_owner_policy_and_catalog',
                'native_support_retained_logical_run_dedupe_withdrawal_unassessed',
                'machine_signed_receipt_confirms_delivery_only_native',
                'native_evaluation_concrete_mcp_worker_once_and_unassessed_quality',
                'native_machine_receiver_atomic_receipt_and_reopen_replay_blocked',
                'native_machine_receiver_restore_retains_claim_and_retires_authority',
                'native_machine_concrete_verified_proof_secure_a2a_http_roundtrip'}
    required.update({
        'native_typed_evidence_existing_authority_and_no_new_source_schema',
        'native_typed_evidence_per_node_consent_projection_and_capture_dedupe',
        'native_typed_evidence_sanitized_metadata_etag_and_current_lineage',
        'native_typed_evidence_existing_agent_report_no_synthetic_quality_promotion',
        'native_typed_evidence_transaction_guard_erasure_and_hash_only_neutral',
        'native_rnd_research_manifest_existing_corpus_immutable_and_missing_coverage',
        'native_rnd_research_concrete_worker_goal_oracle_pairs_no_quality_promotion',
        'native_rnd_research_manifest_withdrawal_current_scope',
        'native_rnd_research_restore_tombstone_preserves_original_signature',
        'native_rnd_intent_and_reviewed_new_draft_preserve_original',
        'native_rnd_single_admission_reuses_private_dispatch_and_replay_zero_replacements',
        'native_rnd_admission_restore_block_preserves_retained_run',
        'native_rnd_protocol_existing_ledger_partial_refund_and_report_only_dedupe',
        'native_rnd_protocol_restore_never_revives_financial_authority',
        'native_circuit_explicit_configuration_cas_and_sticky_open',
        'native_circuit_existing_signed_mcp_probe_proof_closes_once',
        'native_circuit_restore_tombstone_and_reapproval_require_fresh_probe'})
    assert required <= set(result['checks'])
    from pathlib import Path
    import json
    destination = Path('reports/advancement-completion-2026-10-19/native')
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'application-contracts.json').write_text(json.dumps(result, indent=2)+'\n')

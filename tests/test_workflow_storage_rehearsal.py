"""Disposable storage scenario measurements, boundaries and cleanup tests."""
from pathlib import Path
from types import SimpleNamespace
import json
import math
import sqlite3

import pytest

from agent_market import workflow_storage_rehearsal as rehearsal


@pytest.fixture(autouse=True)
def isolated_key_environment(monkeypatch):
    monkeypatch.delenv('AGENT_UPDATES_KEY',raising=False)


@pytest.mark.parametrize('kwargs',[{'iterations':0},{'iterations':51},{'iterations':True},{'readers':0},{'readers':5},
                                   {'readers':1.5},{'writers':0},{'writers':5},{'writers':False}])
def test_direct_configuration_is_bounded_before_any_fixture_creation(kwargs,monkeypatch):
    monkeypatch.setattr(rehearsal,'_build_fixture',lambda *a:pytest.fail('No fixture for invalid configuration'))
    with pytest.raises(rehearsal.RehearsalError,match='invalid_configuration'):rehearsal.run_rehearsal(**kwargs)


def test_configured_key_environment_is_refused_without_loading_a_fixture(monkeypatch):
    monkeypatch.setenv('AGENT_UPDATES_KEY','synthetic-refusal-not-an-operating-key')
    monkeypatch.setattr(rehearsal,'_build_fixture',lambda *a:pytest.fail('No fixture when key environment is configured'))
    with pytest.raises(rehearsal.RehearsalError,match='configured_key_environment'):rehearsal.run_rehearsal()
    assert 'AGENT_UPDATES_KEY' in rehearsal.os.environ


@pytest.mark.parametrize('error',[RuntimeError('private path /private/tmp/credential'),TimeoutError('private-secret-value')])
def test_fixture_failure_cleans_workspace_without_returning_exception_details(error,monkeypatch):
    workspaces=[]
    def fail(directory):
        workspaces.append(directory.parent)
        assert directory.parent.exists();raise error
    monkeypatch.setattr(rehearsal,'_build_fixture',fail)
    with pytest.raises(rehearsal.RehearsalError) as captured:rehearsal.run_rehearsal()
    assert str(captured.value)=='rehearsal_failed' and workspaces and not workspaces[0].exists()


@pytest.fixture
def sql_fixture(tmp_path):
    from agent_market.gateway.store import Store
    store=Store(str(tmp_path/'sql-fixture.sqlite3'))
    try:yield SimpleNamespace(store=store)
    finally:store._db.close()


@pytest.mark.parametrize('iterations,readers,writers',[(1,1,1),(12,2,2),(50,4,4)])
def test_actual_separate_sql_connections_have_accounted_commits_refusals_and_snapshots(sql_fixture,iterations,readers,writers):
    result=rehearsal._load(sql_fixture,iterations,readers,writers)
    assert result['scope']=='sql_fixture_contention_only' and result['deterministic_busy_refusals']==1
    assert result['attempted_writes']==iterations*writers
    assert result['committed_writes']+result['busy_writes']+result['budget_skipped_writes']==iterations*writers
    assert result['reader_snapshots']+result['busy_reads']+result['budget_skipped_reads']==iterations*readers
    assert result['accounted_writes'] is True and result['consistent_reads'] is True
    assert result['committed_writes']>=1 and result['reader_snapshots']>=1
    for name in ('elapsed_ms','write_p50_ms','write_p95_ms','read_p50_ms','read_p95_ms'):
        assert result[name] is None or type(result[name]) in (int,float) and math.isfinite(result[name]) and result[name]>=0
    assert sql_fixture.store.query('SELECT SUM(n) FROM storage_rehearsal_counters')[0][0]==result['committed_writes']


def test_complete_scenario_has_real_safe_measurements_and_no_operating_scope():
    result=rehearsal.run_rehearsal(iterations=2,readers=1,writers=1)
    assert result['ok'] is True and result['profile']==rehearsal.PROFILE
    assert set(result['invariants'])==rehearsal.CHECKS and all(v is True for v in result['invariants'].values())
    assert result['limits']['workflow_throughput_measured'] is False and result['limits']['establishes_sla'] is False
    assert result['limits']['production_actions']==result['limits']['external_provider_calls']==0
    assert result['limits']['global_hard_deadline'] is False
    assert result['limits']['max_idle_batches']==2 and result['limits']['body_batch_limit']==20
    assert result['limits']['metadata_batch_limit']==1 and result['limits']['retention_clock_days_after_fixture']==91
    phases=result['phases'];assert phases['fixture']['synthetic'] is True
    assert phases['fixture']['fixture_effects']['provider_network_calls']==0
    assert phases['durable']['scope']=='claim_fence_recovery_only' and phases['durable']['fixture_agent_calls']==0
    assert set(phases['durable']['invariants'])==rehearsal.DURABLE_CHECKS
    assert set(phases['maintenance']['invariants'])==rehearsal.RETENTION_CHECKS
    assert set(phases['backup_restore']['invariants'])==rehearsal.RESTORE_CHECKS
    assert phases['maintenance']['busy_apply']['busy'] and not phases['maintenance']['busy_apply']['bodies_compacted']
    assert 1<=phases['maintenance']['idle_apply']['bodies_compacted']<=20
    assert phases['maintenance']['metadata_preview']['metadata_candidates']==1
    assert phases['maintenance']['metadata_apply']['metadata_pruned']==1
    assert phases['maintenance']['remaining_preview']['dry_run'] is True
    assert phases['maintenance']['remaining_preview_limit']==20
    assert phases['maintenance']['all_aged_metadata_cleared'] is False
    assert phases['backup_restore']['synthetic_restore_boundary']=={'synthetic_queued':1,'synthetic_prepared':1,'fixture_agent_calls':0}
    assert phases['physical_compaction']['performed'] and phases['physical_compaction']['controls_paused']
    assert phases['physical_compaction']['critical_workflow_state_unchanged'] is True
    for phase in ('load','physical_compaction'):
        for sample in ('before','after'):
            observed=phases[phase][sample]
            assert observed['available'] and observed['coverage']['queue_counts_at_one_read_snapshot']
            assert observed['sqlite']['page_size_bytes']>0
    serialized=json.dumps(result)
    for forbidden in ('wr_','capp_','pub_','cpk_','wap_','/private/','/Users/','Traceback','synthetic-sealed-value'):
        assert forbidden not in serialized


def test_late_load_failure_closes_fixture_database_and_cleans_workspace(monkeypatch):
    fixtures=[];original=rehearsal._build_fixture
    def build(directory):
        fixture=original(directory);fixtures.append((fixture,directory.parent,fixture.store._db));return fixture
    monkeypatch.setattr(rehearsal,'_build_fixture',build)
    monkeypatch.setattr(rehearsal,'_load',lambda *a,**k:(_ for _ in ()).throw(TimeoutError('private timeout diagnostic')))
    with pytest.raises(rehearsal.RehearsalError,match='rehearsal_failed'):rehearsal.run_rehearsal(iterations=1,readers=1,writers=1)
    assert fixtures and not fixtures[0][1].exists()
    assert fixtures[0][0].store is None and fixtures[0][0].client is None
    with pytest.raises(sqlite3.ProgrammingError):fixtures[0][2].execute('SELECT 1')


def test_physical_compaction_refuses_active_authorities_before_any_vacuum(tmp_path):
    from agent_market.workflow_storage_fixtures import synthetic_fixture
    fixture=synthetic_fixture(tmp_path/'active',completed=2)
    try:
        before=rehearsal._logical_state(fixture.store._path)
        with pytest.raises(rehearsal.RehearsalError,match='invariant_failed'):rehearsal._physical_compaction(fixture.store._path)
        assert rehearsal._logical_state(fixture.store._path)==before
    finally:fixture.close()


def test_physical_state_fingerprint_includes_controls_and_event_tombstones(tmp_path):
    from agent_market.workflow_storage_fixtures import synthetic_fixture
    fixture=synthetic_fixture(tmp_path/'state',completed=2)
    try:
        initial=rehearsal._logical_state(fixture.store._path)
        with fixture.store.tx() as db:db.execute('UPDATE execution_controls SET revision=revision+1 WHERE id=1')
        controls_changed=rehearsal._logical_state(fixture.store._path)
        assert controls_changed!=initial
        workflow=fixture.refs['literal_workflow']['id']
        with fixture.store.tx() as db:db.execute('INSERT INTO workflow_event_receipts VALUES (?,?,?)',(workflow,'synthetic-extra-receipt',0))
        assert rehearsal._logical_state(fixture.store._path)!=controls_changed
    finally:fixture.close()

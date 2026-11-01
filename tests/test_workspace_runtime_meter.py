"""Actual private-run transactions drive simulation; no payment/provider network."""
import sqlite3

import pytest

from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied
from agent_market.workspace_metering import WorkspaceMetering, NOTICE
from tests.test_workspace_execution import execution_world, call


@pytest.fixture
def metered():
    world = execution_world()
    store, access, actors, execution, proxy, ws, wd, wv = world
    meter = WorkspaceMetering(access)
    execution.meter = meter
    yield world, meter
    store._db.close()


def configure(world, meter, **values):
    return meter.configure(world[5], {'revision': 0, 'enabled': True,
        'units_per_success': 7, 'max_runs': 2, 'ttl_seconds': 3600,
        'authorized': True, 'notice': NOTICE, **values}, world[2][1])


def test_default_does_not_meter_or_change_execution(metered):
    world, meter = metered
    assert call(world)['status'] == 'succeeded'
    summary = meter.summary(world[5], world[2][1])
    assert summary['operations'] == 0 and summary['policy'] is None


def test_authorized_runtime_records_one_logical_run_attempt_and_balanced_entries(metered):
    world, meter = metered
    configure(world, meter)
    result = call(world)
    assert result['status'] == 'succeeded'
    value = meter.summary(world[5], world[2][1])
    assert value['operations'] == value['attempts'] == 1
    assert value['simulated_units'] == 7 and value['outcomes'] == {'succeeded': 1}
    assert value['balanced'] and not value['actual_money'] and not value['automatic_payment']
    with world[3]._internal() as db:
        _, _, _, run = world[3]._load_run(db, result['id'], *world[5:])
        meter.finish(db, run)
    assert meter.summary(world[5], world[2][1])['simulated_units'] == 7


def test_policy_budget_is_enforced_before_another_provider_attempt(metered):
    world, meter = metered
    configure(world, meter, max_runs=1)
    assert call(world)['status'] == 'succeeded'
    with pytest.raises(WorkspaceConflict):
        call(world)
    assert meter.summary(world[5], world[2][1])['operations'] == 1


def test_policy_requires_current_owner_and_cas(metered):
    world, meter = metered
    configure(world, meter)
    with pytest.raises(WorkspaceConflict):
        configure(world, meter)
    with world[0]._db as db:
        db.execute('UPDATE workspace_memberships SET revision=revision+2 WHERE workspace_id=? AND user_id=1', (world[5],))
    with pytest.raises(WorkspaceDenied):
        call(world)
    assert meter.summary(world[5], world[2][1])['operations'] == 0


def test_unknown_dispatch_never_becomes_simulated_success(metered, monkeypatch):
    world, meter = metered
    configure(world, meter)
    def reject(value, resource):
        raise sqlite3.OperationalError('Synthetic loss after dispatch')
    monkeypatch.setattr(world[3], '_output', reject)
    result = call(world)
    assert result['status'] == 'unknown'
    value = meter.summary(world[5], world[2][1])
    assert value['attempts'] == 1 and value['simulated_units'] == 0
    assert value['outcomes'] == {'unknown': 1}


def test_terminal_commit_fault_rolls_back_meter_with_run_and_does_not_recall(metered, monkeypatch):
    world, meter = metered
    configure(world, meter)
    original = meter.finish
    calls = []
    def once(db, run):
        original(db, run)
        if not calls:
            calls.append(True)
            raise sqlite3.OperationalError('Synthetic accepted meter commit failure')
    monkeypatch.setattr(meter, 'finish', once)
    result = call(world)
    assert result['status'] == 'unknown'
    summary = meter.summary(world[5], world[2][1])
    assert summary['operations'] == summary['attempts'] == 1 and summary['simulated_units'] == 0
    assert world[0]._db.execute('SELECT COUNT(*) FROM workspace_meter_entries').fetchone()[0] == 0


def test_tampered_or_orphan_attempt_is_not_accepted_as_usage(metered):
    world, meter = metered
    configure(world, meter)
    call(world)
    with world[0]._db as db:
        db.execute("UPDATE workspace_meter_attempts SET payload='{}'")
    with pytest.raises(WorkspaceConflict):
        meter.summary(world[5], world[2][1])

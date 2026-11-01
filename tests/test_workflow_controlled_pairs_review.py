"""Independent checks of shared context, dispatch races and historical reads."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

import pytest

from agent_market.capability_registry import Registry
from agent_market.workflow_comparison import ComparisonError
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_controlled_pairs import controlled_routing, prepared, authorized, completed_pair
from tests.test_workflow_resolved_evidence import alter_checkpoint
from tests.test_workflow_runtime import wait


def source_context_change(value):
    """Keep the forwarded query identical while changing its full source."""
    output = copy.deepcopy(value['record']['data'])
    normalized = output.get('structuredContent', output)
    normalized['partial'] = not normalized['partial']
    value['record']['data'] = output
    value['flow_output'] = copy.deepcopy(output)


def test_same_query_does_not_make_a_changed_full_source_context_equivalent(controlled_routing):
    rt, _, _, calls, *_ = controlled_routing
    service, _, run = completed_pair(controlled_routing)
    before = service.inspect({'run_id': run['run_id']})['resolved_input']
    alter_checkpoint(rt, run['run_id'], 'search-1', source_context_change)
    source = json.loads(rt.store.query('SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id=?',
                                      (run['run_id'], 'search-1'))[0][0])
    assert source['record']['data']['structuredContent']['items'][0]['title'] == before['query']
    with pytest.raises(ComparisonError):
        service.inspect({'run_id': run['run_id']})
    assert len(calls) == 3


def test_signed_b_observation_cannot_precede_a_completion(controlled_routing):
    rt, _, _, calls, *_ = controlled_routing
    service, _, run = completed_pair(controlled_routing)
    a = json.loads(rt.store.query('SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id=?',
                                 (run['run_id'], 'search-2'))[0][0])['record']
    assert a['latency_ms'] > 0
    alter_checkpoint(rt, run['run_id'], 'search-3', lambda value: value['record'].update(started=a['started']))
    with pytest.raises(ComparisonError):
        service.inspect({'run_id': run['run_id']})
    assert len(calls) == 3


@pytest.mark.parametrize('attack', ['a_signature', 'a_certainty', 'full_source_context'])
def test_b_rechecks_predecessor_and_full_context_after_preparation_before_dispatch(controlled_routing, monkeypatch, attack):
    rt, _, _, calls, *_ = controlled_routing
    service, proposal = prepared(rt)
    original = rt.persistence.prepare
    changed = []

    def prepare(run_id, owner, fence, node_id, input_hash):
        result = original(run_id, owner, fence, node_id, input_hash)
        if node_id == 'search-3' and not changed:
            changed.append(run_id)
            if attack == 'a_signature':
                with rt.store.tx() as db:
                    db.execute("UPDATE workflow_checkpoints SET signature='invalid' WHERE run_id=? AND node_id='search-2'", (run_id,))
            elif attack == 'a_certainty':
                with rt.store.tx() as db:
                    db.execute("UPDATE workflow_execution_attempts SET status='unknown' WHERE run_id=? AND node_id='search-2'", (run_id,))
            else:
                alter_checkpoint(rt, run_id, 'search-1', source_context_change)
        return result

    monkeypatch.setattr(rt.persistence, 'prepare', prepare)
    job = service.execute(authorized(proposal), 1)
    result = wait(rt, job)
    assert changed == [job['run_id']]
    assert result['status'] == 'failed'
    assert len(calls) == 2 and calls[0] == 'primary.example'
    b = rt.store.query('SELECT status,dispatched FROM workflow_execution_attempts WHERE run_id=? AND node_id=?',
                       (job['run_id'], 'search-3'))
    assert len(b) == 1 and b[0]['dispatched'] is None and b[0]['status'] == 'failed'
    assert not rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?', (job['run_id'],))


def test_historical_read_uses_no_live_pin_or_registry_writer_after_time_and_producer_role_change(controlled_routing):
    rt, _, _, calls, *_ = controlled_routing
    service, _, run = completed_pair(controlled_routing)
    with rt.store.tx() as db:
        db.execute("UPDATE admin_users SET role='operator' WHERE id=1")
        db.execute('UPDATE resources SET active=0')
    future = time.time() + 7200
    before = rt.store._db.total_changes
    with patch.object(rt.fallback, 'pin', side_effect=AssertionError('Historical reads must not refresh live pins')), \
            patch.object(Registry, 'current', side_effect=AssertionError('Historical reads must not create versions')), \
            patch('time.time', return_value=future):
        result = service.inspect({'run_id': run['run_id']})
    assert result['comparison_status'] == 'complete' and result['shared_input_verified']
    assert all(not target['current']['eligible_now'] for target in result['targets'])
    assert not result['publication_readiness']['ready']
    assert rt.store._db.total_changes == before and len(calls) == 3
    assert result['effects'] == {'provider_calls': 0, 'model_calls': 0, 'evidence_writes': 0, 'publication': False}


def test_one_read_snapshot_does_not_mix_a_concurrent_checkpoint_change(controlled_routing, monkeypatch):
    rt, _, _, calls, *_ = controlled_routing
    rt.store._db.execute('PRAGMA journal_mode=WAL')
    service, _, run = completed_pair(controlled_routing)
    original = service.node_result
    changed = []

    def node_result(store, row, node, *args, **kwargs):
        result = original(store, row, node, *args, **kwargs)
        if node['id'] == 'search-1' and not changed:
            changed.append(True)

            def write():
                with rt.store.tx() as db:
                    db.execute("UPDATE workflow_checkpoints SET signature='invalid' WHERE run_id=? AND node_id='search-2'", (run['run_id'],))

            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(write).result(timeout=3)
        return result

    monkeypatch.setattr(service, 'node_result', node_result)
    result = service.inspect({'run_id': run['run_id']})
    assert changed and result['comparison_status'] == 'complete'
    with pytest.raises(ComparisonError):
        service.inspect({'run_id': run['run_id']})
    assert len(calls) == 3


def test_pair_scope_shared_source_and_attempts_round_trip_existing_postgres_state_boundary(controlled_routing, monkeypatch):
    from scripts.rehearse_workflow_postgres import rehearse,TABLES

    rt, _, _, calls, *_ = controlled_routing
    _, _, run = completed_pair(controlled_routing)
    monkeypatch.setenv('PATH', '/opt/homebrew/opt/postgresql@14/bin:' + os.environ.get('PATH', ''))
    result = rehearse(rt.store._path)
    assert result['round_trip_equal'] and set(result['tables']) == set(TABLES)
    assert result['tables']['workflow_checkpoints'] >= 4
    assert result['tables']['workflow_run_authority'] >= 1
    assert result['tables']['workflow_execution_attempts'] >= 3
    assert len(calls) == 3
    Path('reports/advancement-r07-controlled-pairs-2026-10-18/postgres-pair.json').write_text(
        json.dumps(result, indent=2) + '\n')


def test_control_change_after_proposal_check_cannot_revive_old_pair_at_dispatch(controlled_routing, monkeypatch):
    from agent_market.execution_authority import controls, set_controls

    rt, _, _, calls, *_ = controlled_routing
    service, proposal = prepared(rt)
    reserve = service._reserve

    def reserve_then_pause_and_resume(value):
        workflow = reserve(value)
        current = controls(rt.store)
        paused = set_controls(rt.store, {'invoke_enabled': True, 'workflow_enabled': False,
                                        'delivery_enabled': True, 'revision': current['revision']}, 1)
        set_controls(rt.store, {'invoke_enabled': True, 'workflow_enabled': True,
                                'delivery_enabled': True, 'revision': paused['revision']}, 1)
        return workflow

    monkeypatch.setattr(service, '_reserve', reserve_then_pause_and_resume)
    try:
        job = service.execute(authorized(proposal), 1)
    except (ComparisonError, ValueError):
        pass
    else:
        result = wait(rt, job)
        assert result['status'] != 'succeeded'
    assert not calls

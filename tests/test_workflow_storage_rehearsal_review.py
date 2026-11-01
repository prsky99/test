"""Independent negative coverage and process-isolation review of rehearsal."""
import os
import sqlite3

import httpx
import pytest

from agent_market import workflow_storage_rehearsal as rehearsal
from agent_market.concierge.proxy import McpProxy
from agent_market.workflows import WorkflowRuntime


@pytest.mark.parametrize('method', ['exercise_durable', 'verify_compaction', 'verify_restore'])
@pytest.mark.parametrize('fault', ['empty', 'missing', 'integer_true'])
def test_lost_or_nonboolean_verification_cannot_be_reported_as_success(monkeypatch, method, fault):
    original = rehearsal._build_fixture

    def build(directory):
        fixture = original(directory)
        verify = getattr(fixture, method)

        def damaged(*args, **kwargs):
            result = verify(*args, **kwargs)
            checks = result['invariants'] if method == 'exercise_durable' else result
            assert checks and all(value is True for value in checks.values())
            if fault == 'empty':
                checks.clear()
            elif fault == 'missing':
                checks.pop(next(iter(checks)))
            else:
                checks[next(iter(checks))] = 1
            return result

        setattr(fixture, method, damaged)
        return fixture

    monkeypatch.setattr(rehearsal, '_build_fixture', build)
    with pytest.raises(rehearsal.RehearsalError, match='invariant_failed'):
        rehearsal.run_rehearsal(iterations=1, readers=1, writers=1)


def test_maximum_sql_fixture_load_preserves_process_environment_and_transport_classes():
    before_environment = dict(os.environ)
    before_functions = (sqlite3.connect, httpx.Client.send, McpProxy.execute,
                        WorkflowRuntime.launch, WorkflowRuntime._execute_bounded)
    report = rehearsal.run_rehearsal(iterations=50, readers=4, writers=4)
    assert dict(os.environ) == before_environment
    assert before_functions == (sqlite3.connect, httpx.Client.send, McpProxy.execute,
                                WorkflowRuntime.launch, WorkflowRuntime._execute_bounded)
    assert report['ok'] is True and all(value is True for value in report['invariants'].values())
    load = report['phases']['load']
    assert load['attempted_writes'] == 200
    assert load['committed_writes'] + load['busy_writes'] + load['budget_skipped_writes'] == 200
    assert load['reader_snapshots'] + load['busy_reads'] + load['budget_skipped_reads'] == 200
    assert report['limits']['workflow_throughput_measured'] is False
    assert report['limits']['external_provider_calls'] == report['limits']['production_actions'] == 0
    assert report['phases']['fixture']['fixture_effects']['mcp_calls'] > 0
    assert report['invariants']['temporary_workspace_removed'] is True

"""Caller-owned worker composition; no operating configuration is inferred."""
import math
import threading
from types import SimpleNamespace

import pytest

from agent_market.workflow_worker import compose_worker, run_worker
from agent_market.workflows import WorkflowRuntime


def runtime_fixture():
    runtime = WorkflowRuntime.__new__(WorkflowRuntime)
    calls = []
    runtime.proxy = None
    runtime.persistence = SimpleNamespace(recover=lambda: calls.append('recover'))
    runtime.operations = SimpleNamespace(recover=lambda: calls.append('operations'))
    runtime.run_due = lambda: calls.append('dispatch')
    return runtime, calls


def test_worker_default_only_recovers_and_keeps_caller_objects():
    runtime, calls = runtime_fixture()
    value = run_worker(runtime, stop=threading.Event(), once=True)
    assert calls == ['recover', 'operations']
    assert value['ticks'] == 1 and not value['execution_requested']
    assert not value['caller_store_closed_by_worker'] and not value['automatic_backend_selection']
    assert not value['operating_acceptance']


def test_worker_dispatch_requires_explicit_transport_before_queue_access():
    runtime, calls = runtime_fixture()
    with pytest.raises(ValueError, match='explicit_proxy_required'):
        run_worker(runtime, stop=threading.Event(), once=True, execute=True)
    assert calls == []
    runtime.proxy = SimpleNamespace(execute=lambda *_: None)
    run_worker(runtime, stop=threading.Event(), once=True, execute=True)
    assert calls == ['dispatch']


@pytest.mark.parametrize('interval', [True, None, 0, .01, 31, math.nan, math.inf])
def test_invalid_loop_configuration_does_not_access_runtime(interval):
    runtime, calls = runtime_fixture()
    with pytest.raises(ValueError, match='invalid_worker_configuration'):
        run_worker(runtime, stop=threading.Event(), once=True, interval=interval)
    assert calls == []


def test_stopped_worker_performs_no_storage_or_provider_work():
    runtime, calls = runtime_fixture()
    stop = threading.Event(); stop.set()
    assert run_worker(runtime, stop=stop, once=True)['ticks'] == 0
    assert calls == []


def test_composition_rejects_implicit_or_unscoped_store():
    with pytest.raises(ValueError, match='explicit_application_store_required'):
        compose_worker(SimpleNamespace())


def test_postgres_missing_key_or_busy_store_is_refused_before_runtime(monkeypatch):
    from agent_market.application_store_postgres import PostgresApplicationStore
    store = PostgresApplicationStore.__new__(PostgresApplicationStore)
    store.workflow_key = None
    monkeypatch.setattr('agent_market.workflow_worker.WorkflowRuntime', lambda *_args, **_kwargs: pytest.fail('Unqualified Store reached runtime'))
    with pytest.raises(ValueError, match='explicit_workflow_key_required'):
        compose_worker(store)
    store.workflow_key = b'k' * 32
    store._closed, store._broken, store._depth = False, False, 1
    with pytest.raises(ValueError, match='idle_application_store_required'):
        compose_worker(store)


def test_caller_owned_store_is_used_directly_without_closing_or_opening_connection(tmp_path, monkeypatch):
    from agent_market.gateway.store import Store
    store = Store(str(tmp_path/'worker.sqlite3'))
    seen = []
    try:
        monkeypatch.setattr('agent_market.workflow_worker.WorkflowRuntime', lambda current, **transport: seen.append((current,transport)) or current)
        assert compose_worker(store) is store
        assert seen == [(store,{'proxy':None,'courier':None})]
        assert store._db.execute('SELECT 1').fetchone()[0] == 1
        with store.tx():
            store._db.execute('BEGIN IMMEDIATE')
            with pytest.raises(ValueError, match='idle_application_store_required'):
                compose_worker(store)
    finally:
        store._db.close()


def test_actual_native_caller_worker_and_fenced_application_binding(request):
    import json
    from scripts.rehearse_worker_binding_postgres import rehearse
    result = rehearse()
    assert all(result['checks'].values()) and len(result['checks']) >= 15
    assert result['temporary_cluster_removed']
    assert result['operating_database_writes'] == result['external_provider_calls'] == 0
    assert not result['full_application_ready'] and not result['operating_cutover']
    request.node.user_properties.append(('storage_worker_binding_native',json.dumps(result,sort_keys=True)))

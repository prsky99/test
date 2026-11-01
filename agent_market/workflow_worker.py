"""Run only the persisted workflow queue; does not launch an HTTP server or collector."""
import argparse
import math
import signal
import threading
import time
from concurrent.futures import wait
from .gateway.store import Store
from .workflows import WorkflowRuntime
from .concierge.proxy import McpProxy
from .concierge.notify import Courier


def compose_worker(store, *, proxy=None, courier=None):
    """Attach the existing runtime to a caller-owned, explicitly selected Store.

    No connection, transport, server or scheduler is inferred. In particular a
    PostgreSQL caller supplies the already attached Store and persistent key;
    the worker does not reinterpret its absent SQLite path as an in-memory DB.
    """
    from .application_store_postgres import PostgresApplicationStore
    if type(store) not in (Store, PostgresApplicationStore):
        raise ValueError('explicit_application_store_required')
    if proxy is not None and not callable(getattr(proxy, 'execute', None)):
        raise ValueError('explicit_proxy_required')
    if courier is not None and not callable(getattr(courier, 'send_update', None)):
        raise ValueError('explicit_courier_required')
    if type(store) is PostgresApplicationStore:
        if type(store.workflow_key) is not bytes or len(store.workflow_key) != 32:
            raise ValueError('explicit_workflow_key_required')
        store.require_capabilities(('durable_workflow_runtime',))
        if store._closed or store._broken or store._depth:
            raise ValueError('idle_application_store_required')
    elif store._db.in_transaction:
        raise ValueError('idle_application_store_required')
    return WorkflowRuntime(store, proxy=proxy, courier=courier)


def run_worker(runtime, *, stop, once=False, execute=False, interval=2):
    """Run the existing durable loop without taking ownership of caller objects.

    Storage-only recovery is the default. Execution explicitly includes saved
    schedules/automation and an explicitly supplied courier may drain delivery.
    Existing runtime principals, grants, kill switches and fencing still apply.
    The caller must wait for in-flight futures before detaching its Store.
    """
    if (type(runtime) is not WorkflowRuntime or type(stop) is not threading.Event
            or type(once) is not bool or type(execute) is not bool
            or type(interval) not in (int, float) or not math.isfinite(interval)
            or not .05 <= interval <= 30):
        raise ValueError('invalid_worker_configuration')
    if execute and not callable(getattr(runtime.proxy, 'execute', None)):
        raise ValueError('explicit_proxy_required')
    ticks = 0
    while not stop.is_set():
        if execute:
            runtime.run_due()
        else:
            runtime.persistence.recover()
            runtime.operations.recover()
        ticks += 1
        if once:
            break
        stop.wait(interval)
    return {'ticks': ticks, 'execution_requested': execute,
            'caller_store_closed_by_worker': False, 'automatic_backend_selection': False,
            'operating_acceptance': False}


def drain_worker(runtime, timeout=30):
    """Wait for admitted work without replaying, cancelling or closing its Store."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 300:
        raise ValueError('invalid_worker_shutdown_timeout')
    deadline = time.monotonic() + timeout
    while True:
        with runtime.lock:
            futures = tuple(runtime.futures.values())
        if not futures:
            return True
        _, pending = wait(futures, timeout=max(0, deadline-time.monotonic()))
        if pending:
            return False
        # Completed failures remain durable outcomes, not cleanup exceptions.
        with runtime.lock:
            if all(future.done() for future in runtime.futures.values()):
                return True
        if time.monotonic() >= deadline:
            return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db');parser.add_argument('--once',action='store_true')
    args=parser.parse_args();stop=threading.Event()
    import os
    if not args.db and os.environ.get('APPLICATION_STORE_BACKEND', 'sqlite') == 'sqlite':
        parser.error('--db is required for the SQLite backend.')
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    from .application_runtime import open_runtime_storage
    storage=open_runtime_storage(args.db);store=storage.store
    runtime=compose_worker(store,proxy=McpProxy(store),courier=Courier())
    try:
        run_worker(runtime,stop=stop,once=args.once,execute=True)
    finally:
        # Leave persisted ownership to expire if the process is forcibly killed.
        if drain_worker(runtime):
            storage.close()


if __name__=='__main__':main()

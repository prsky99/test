"""Explicit native PostgreSQL workflow worker attachment and queue recovery.

This module never reads a DSN, starts a server, enables controls or creates an
HTTP client. The caller owns the native connection and workflow signing key.
"""
import threading
import time


class NativeWorkflowUnavailable(ValueError):
    def __init__(self, code='native_workflow_unavailable'):
        self.code = code
        super().__init__(code)


class PostgresWorkflowWorker:
    def __init__(self, connection, *, workflow_key, proxy=None):
        if type(workflow_key) is not bytes or len(workflow_key) != 32:
            raise NativeWorkflowUnavailable('explicit_workflow_key_required')
        if proxy is not None and not callable(getattr(proxy, 'execute', None)):
            raise NativeWorkflowUnavailable('explicit_proxy_required')
        from .storage_adapter import open_store
        from .workflows import WorkflowRuntime
        self.store = open_store('postgresql', connection=connection, initialize=False, workflow_key=workflow_key)
        try:
            self.runtime = WorkflowRuntime(self.store, proxy=proxy, courier=None)
        except BaseException:
            self.store.close()
            raise
        self._lock = threading.RLock()
        self._closed = False

    def tick(self, *, execute=False):
        with self._lock:
            if type(execute) is not bool or self._closed:
                raise NativeWorkflowUnavailable()
            if execute and self.runtime.proxy is None:
                raise NativeWorkflowUnavailable('explicit_proxy_required')
            # Recovery is storage-only. In particular this does not drain result
            # delivery, create scheduled runs, activate automation, or enable a gate.
            recovered = self.runtime.persistence.recover()
            self.runtime.operations.recover()
            wakeups = 0
            if execute:
                for row in self.store.query("SELECT id FROM workflow_runs WHERE status='queued' ORDER BY created LIMIT 12"):
                    self.runtime.launch(row['id']); wakeups += 1
        return {'recovered': recovered, 'queue_wakeups': wakeups, 'external_attempts': None,
                'delivery_enabled_by_worker': False, 'schedule_creation': False,
                'automatic_unknown_retry': False}

    def wait(self, *, timeout=65):
        if type(timeout) not in (int, float) or not 0 < timeout <= 130 or self._closed:
            raise NativeWorkflowUnavailable()
        deadline = time.monotonic() + timeout
        with self.runtime.lock:
            futures = list(self.runtime.futures.values())
        for future in futures:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeWorkflowUnavailable('worker_still_active')
            try:
                future.result(timeout=remaining)
            except TimeoutError:
                raise NativeWorkflowUnavailable('worker_still_active') from None

    def close(self):
        with self._lock, self.runtime.lock:
            if self._closed:
                return
            if any(not future.done() for future in self.runtime.futures.values()):
                raise NativeWorkflowUnavailable('worker_still_active')
            self.store.close()
            self._closed = True
        # The caller's native connection is deliberately not closed.

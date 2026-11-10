"""Isolated role, authority, admission and real PostgreSQL ownership checks."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import time

import pytest
from fastapi.testclient import TestClient

from agent_market.config import GatewayConfig
from agent_market.gateway.store import Store
from agent_market.service_host import create_service_app, probe_token
from agent_market.service_runtime import ServiceControl, ServiceUnavailable
from tests.test_market import NET
from tests.test_workspace_execution import execution_world, prepared, request
from tests.test_workspace_typed_flows import typed_world, save, run
from tests.test_workflow_fallback import routing


class Control:
    key = b'k' * 32
    available = True

    def ready(self):
        return True

    def status(self, role):
        return {'available': self.available}


@pytest.mark.parametrize('role', ['frontend', 'admin'])
def test_web_roles_do_not_start_jobs_and_readiness_is_private(role, monkeypatch):
    import agent_market.workspace_platform as platform
    from agent_market.gateway.server import Scheduler
    def forbidden(*args, **kwargs):
        raise AssertionError('Web must not start a background service')
    monkeypatch.setattr(platform, 'start_for', forbidden)
    monkeypatch.setattr(Scheduler, 'start', forbidden)
    config = GatewayConfig(NET, None, ':memory:', 'test-secret', 1, 3600, 900, True, False,
                           concierge_llm='off', customer_workspace_access=True)
    store = Store()
    try:
        app = create_service_app(config, role, store=store, control=Control(), warm=False, release='synthetic-v1')
        with TestClient(app) as client:
            assert client.get('/internal/service/ready').status_code == 404
            reply = client.get('/internal/service/ready', headers={'x-service-probe': probe_token(Control.key)})
            assert reply.status_code == 200
            assert reply.json() == {'ready': True, 'role': role, 'release': 'synthetic-v1', 'active_requests': 0,
                                    'embedding_warmup': None, 'generation_warmup': None, 'report_snapshot': None}
            paths = {getattr(r, 'path', '') for r in app.routes}
            if role == 'frontend':
                assert '/needs' in paths and not any(p.startswith('/admin') for p in paths)
                assert client.get('/admin/ui').status_code == 404
                assert client.post('/needs', json={'task': 'Synthetic request'}).status_code == 401
            else:
                assert client.get('/admin/ui').status_code in (200, 302, 303, 307)
                assert '/needs' not in paths
                assert client.get('/customer/organizations').status_code == 404
        assert app.state.ready is False
    finally:
        store._db.close()


def test_private_run_executes_only_on_worker_and_reuses_existing_admission():
    fixture = execution_world()
    store, access, actors, core, proxy, ws, draft, snapshot = fixture
    control = Control()
    store._service_role, store._service_control = 'frontend', control
    ticket = prepared(fixture)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(core.execute, ws, draft, snapshot, request(ticket), actors[1])
            deadline = time.monotonic() + 3
            identity = None
            while time.monotonic() < deadline:
                with store._lock:
                    row = store._db.execute('SELECT id FROM workspace_private_runs').fetchone()
                if row:
                    identity = row[0]
                    break
                time.sleep(.01)
            assert identity and proxy.calls == 0
            value = core.execute_admitted(identity, ws, draft, snapshot)
            assert value['status'] == 'succeeded'
            assert response.result(timeout=3)['status'] == 'succeeded'
            replay = core.execute(ws, draft, snapshot, request(ticket), actors[1])
            assert replay['replayed'] and proxy.calls == 1
    finally:
        store._db.close()


def test_typed_run_is_durable_before_worker_io(typed_world):
    w = typed_world
    w.store._service_role, w.store._service_control = 'frontend', Control()
    flow = save(w)
    ticket = w.core.prepare(w.ws, flow['id'], {'revision': 1}, w.actor)
    with ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(run, w, flow, ticket)
        deadline = time.monotonic() + 3
        identity = None
        while time.monotonic() < deadline:
            with w.store._lock:
                row = w.store._db.execute('SELECT id FROM workspace_typed_flow_runs').fetchone()
            if row:
                identity = row[0]
                break
            time.sleep(.01)
        assert identity and not w.calls
        w.core.execute_admitted(identity, w.ws, flow['id'])
        result, _ = response.result(timeout=3)
        assert result['run']['status'] == 'succeeded'
        assert len(w.calls) == 2
        replay, _ = run(w, flow, ticket)
        assert replay['replayed'] and len(w.calls) == 2


def test_real_postgres_claim_signature_and_owner_recovery():
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, _tools, PORT
    tools = {name: '/opt/homebrew/opt/postgresql@18/bin/' + name for name in ('initdb', 'pg_ctl')}
    with _private_cluster(tools) as cluster:
        def connect():
            return psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        a, b = ServiceControl(connect(), b'k' * 32), ServiceControl(connect(), b'k' * 32)
        try:
            a.install()
            assert a.ready()
            a.acquire_owner('jobs')
            with pytest.raises(ServiceUnavailable):
                b.acquire_owner('jobs')
            a.heartbeat('jobs', {'paused': False})
            assert b.status()['available'] is True
            first = a.enqueue('crawl', {'force_full': False})
            assert b.enqueue('crawl', {'force_full': False})['command_id'] == first['command_id']
            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(lambda c: c.claim(), [a, b]))
            assert sum(item is not None for item in claims) == 1
            owner = a if claims[0] else b
            other = b if claims[0] else a
            assert not other.finish(first['command_id'], True)
            assert owner.finish(first['command_id'], True)
            bad = a.enqueue('pause')
            with b.tx() as db:
                db.execute("UPDATE service_runtime.commands SET payload='{} ',signature='bad' WHERE id=%s", (bad['command_id'],))
            assert b.claim() is None
            assert b.actions()['pause']['state'] == 'failed'
            item = a.enqueue('rescan')
            assert a.claim()['id'] == item['command_id']
            a.close()
            b.acquire_owner('jobs')
            assert b.actions()['rescan']['state'] == 'unknown'
            assert b.claim() is None
            b.heartbeat('execution', {'running': False})
            assert not b.status('execution')['available']
        finally:
            a.close()
            b.close()

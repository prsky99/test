"""Disposable verification only; no operating database path is accepted."""
from contextlib import contextmanager
import json
from pathlib import Path
import time
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from ..collector import usage
from ..concierge.proxy import McpProxy
from ..gateway.store import Store
from ..workflows import WorkflowRuntime
from .catalog import SPECS, tool_spec
from .engine import DataAgents
from .service import create_app, PREFIX
from .staging import definitions

ORIGIN = 'https://owned-data-agents.example'


@contextmanager
def isolated_world(directory, *, engine=None):
    root = Path(directory)
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    engine = engine or DataAgents()
    store = Store(str(root / 'isolated.sqlite3'))
    service = TestClient(create_app(enabled=True, engine=engine), base_url=ORIGIN)
    requests = []
    def bridge(request):
        if request.url.host != 'owned-data-agents.example':
            raise AssertionError('Only this isolated protocol origin is allowed.')
        body = json.loads(request.content)
        requests.append({'path': request.url.path, 'method': body.get('method'),
                         'params': body.get('params', {})})
        response = service.post(request.url.path, content=request.content,
                                headers={'Content-Type': 'application/json'})
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content)
    http = httpx.Client(transport=httpx.MockTransport(bridge), trust_env=False)
    runtime = None
    try:
        resources = {}
        for identity, spec in SPECS.items():
            tools = [tool_spec(identity)]
            endpoint = ORIGIN + PREFIX + '/' + identity + '/mcp'
            # Survey the real staged protocol handler before storing the schema.
            response = service.post(endpoint, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            if response.status_code != 200 or response.json()['result']['tools'] != tools:
                raise AssertionError('The isolated capability survey failed.')
            rid = store.upsert_resource({'key': 'staged:' + identity, 'source': 'isolated-owned-verification',
                'kind': 'mcp', 'url': endpoint, 'name': spec['name'], 'description': spec['description'],
                'category': 'data_utility', 'price_usdc': 0, 'details': {}})
            compact = usage.compact_tools(tools)
            store.record_usage(rid, compact, usage.tools_hash(compact), {}, None, {'ok': True}, full_tools=tools)
            store.record_health(rid, 'healthy', 200, 1, None, time.time() + 3600)
            resources[identity] = rid
        runtime = WorkflowRuntime(store, McpProxy(store, allow_private=True, http=http))
        workflows = []
        for recipe in definitions(ORIGIN):
            # The existing seed may already contain this staged recipe when a
            # test intentionally substitutes definitions before Store creation.
            found = store.query('SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?', (recipe['seed_key'],))
            wid = found[0][0] if found else store.create_workflow(recipe)
            workflows.append(store.get_workflow(wid))
        yield SimpleNamespace(root=root, engine=engine, store=store, service=service,
                              http=http, runtime=runtime, resources=resources,
                              workflows=workflows, requests=requests)
    finally:
        if runtime:
            for future in list(runtime.futures.values()):
                future.result(timeout=30)
        http.close()
        service.close()
        store._db.close()


def wait(runtime, submitted):
    until = time.monotonic() + 65
    while time.monotonic() < until:
        run = runtime.get(submitted['run_id'])
        if run['status'] in ('succeeded', 'failed', 'cancelled'):
            future = runtime.futures.get(submitted['run_id'])
            if future:
                future.result(timeout=3)
            return runtime.get(submitted['run_id'])
        time.sleep(.02)
    raise TimeoutError('The isolated workflow did not finish.')

"""Staff Testbench uses the same live first-party bindings as the public UI."""
# ruff: noqa: F401,F811
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.gateway.dashboard import dashboard_router
from tests.test_owned_data_agents import engine
from tests.test_owned_data_agents_activation import operating
from tests.conftest import staff_headers

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

HEADERS = {'X-Dashboard': '1', 'Authorization': 'Bearer synthetic-current-admin'}


@pytest.mark.parametrize('example_index', range(4))
def test_staff_recipe_executes_local_agent_with_real_adapter_output(operating, monkeypatch, example_index):
    front, public, _, calls, _ = operating
    app = FastAPI()
    app.include_router(dashboard_router(front.store, front.store._path, 'synthetic-current-admin', None,
                                      front=front, ssl_manager=Mock(get_status=lambda: {})))
    def no_remote_agent(*args, **kwargs):
        raise AssertionError('The local agent must not use its public HTTP endpoint.')
    monkeypatch.setattr('agent_market.gateway.dashboard.public_async_client', no_remote_agent)
    with TestClient(app) as admin:
        monkeypatch.setitem(HEADERS, 'Authorization', staff_headers(admin)['Authorization'])
        examples = admin.get('/admin/api/test/examples', headers=HEADERS).json()['examples']
        assert examples == public.get('/api/test/presets').json()['live_examples']
        if example_index == 0:
            templates = admin.get('/admin/api/workflows?is_template=1', headers=HEADERS).json()['workflows']
            public_templates = public.get('/api/workflows/templates').json()['templates']
            assert len(templates) == len(public_templates) == 3
            assert {row['id'] for row in templates} == {row['id'] for row in public_templates}
        example = examples[example_index]
        rid = example['resource_id']
        assert example['available'] and rid > 0 and not example['simulated']
        arguments = dict(example['args'])
        if 'query' in arguments:
            arguments['query'] = 'administrator verification public research'
        elif 'country_code' in arguments:
            arguments['country_code'] = 'CA'
        elif 'package' in arguments:
            arguments['package'] = 'lodash'
        spec = admin.get(f'/admin/api/test/agents/{rid}/spec?refresh=true', headers=HEADERS)
        assert spec.status_code == 200
        before = len(calls)
        result = admin.post('/admin/api/test/execute', headers=HEADERS,
            json={'resource_id': rid, 'tool': example['tool'], 'arguments': arguments})
        assert result.status_code == 200
        data = result.json()
        assert data['ok'] and data['execution_succeeded'] and not data['simulated']
        assert data['request_wire']['execution'] == 'local'
        assert data['response_wire']['structuredContent']['agent']
        assert len(calls) > before
        # Existing execution control remains authoritative for the local path.
        with front.store.tx() as db:
            db.execute('UPDATE execution_controls SET invoke_enabled=0')
        before = len(calls)
        denied = admin.post('/admin/api/test/execute', headers=HEADERS,
            json={'resource_id': rid, 'tool': example['tool'], 'arguments': arguments}).json()
        assert not denied['ok'] and not denied['execution_succeeded']
        assert len(calls) == before

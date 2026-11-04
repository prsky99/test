"""MCP tasks for published workflow runs: same admission as the public REST run, task id = run id + run key."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge import mcp_tasks

HASH = 'a' * 64
RUN_ID, RUN_KEY = 'wr_' + '0' * 32, 'k' * 43


class Runs:
    def __init__(self):
        self.status, self.submitted, self.cancelled = 'queued', [], []

    def submit(self, workflow, **kwargs):
        self.submitted.append((workflow, kwargs))
        return {'run_id': RUN_ID, 'status': 'queued', 'run_key': RUN_KEY}

    def authorized(self, run_id, key):
        return run_id == RUN_ID and key == RUN_KEY

    def get(self, run_id):
        return {'run_id': run_id, 'workflow_id': 5, 'workflow_name': 'Weather brief', 'status': self.status,
                'created_at': 1793750000.0, 'error': 'node 2 timed out' if self.status == 'failed' else None,
                'node_results': [{'node_id': 'n1', 'status': 'succeeded', 'output': 'ok', 'input': 'secret input'}]}

    def cancel(self, run_id):
        self.cancelled.append(run_id)
        self.status = 'cancelled'
        return self.get(run_id)


@pytest.fixture
def front(monkeypatch):
    import agent_market.workflows as workflows
    monkeypatch.setattr(workflows, 'public_template',
                        lambda workflow, runtime: {'definition_hash': HASH, 'id': workflow['id']} if workflow else None)
    return SimpleNamespace(store=SimpleNamespace(get_workflow=lambda wid: {'id': wid} if wid == 5 else None), workflows=Runs())


def test_start_applies_the_public_rest_checks(front):
    with pytest.raises(mcp_tasks.TaskError, match='definition_hash'):
        mcp_tasks.start(front, {'template_id': 5})
    with pytest.raises(mcp_tasks.TaskError, match='changed'):
        mcp_tasks.start(front, {'template_id': 5, 'definition_hash': 'b' * 64})
    with pytest.raises(mcp_tasks.TaskError, match='available published'):
        mcp_tasks.start(front, {'template_id': 6, 'definition_hash': HASH})
    with pytest.raises(mcp_tasks.TaskError, match='declare input'):
        mcp_tasks.start(front, {'template_id': 5, 'definition_hash': HASH, 'input': {'city': 'Seoul'}})
    with pytest.raises(mcp_tasks.TaskError):
        mcp_tasks.start(front, {'template_id': 5, 'definition_hash': HASH, 'nodes': []})
    run = mcp_tasks.start(front, {'template_id': 5, 'definition_hash': HASH})
    workflow, kwargs = front.workflows.submitted[0]
    assert kwargs['actor'] == 'public' and kwargs['source'] == 'public' and kwargs['public'] is True
    assert mcp_tasks.task_id(run) == RUN_ID + '.' + RUN_KEY


def test_task_lifecycle_follows_the_run(front):
    value = RUN_ID + '.' + RUN_KEY
    task = mcp_tasks.get(front, {'taskId': value})
    assert task['status'] == 'working' and task['pollInterval'] == mcp_tasks.POLL_MS and task['createdAt'].endswith('Z')
    with pytest.raises(mcp_tasks.TaskError, match='still working'):
        mcp_tasks.result(front, {'taskId': value}, wait=0, sleep=lambda s: None)
    front.workflows.status = 'succeeded'
    done = mcp_tasks.result(front, {'taskId': value}, wait=0)
    assert done['isError'] is False and done['_meta']['io.modelcontextprotocol/related-task'] == {'taskId': value}
    assert 'input' not in done['structuredContent']['node_results'][0]  # public_outcome scrubs inputs
    with pytest.raises(mcp_tasks.TaskError, match='already completed'):
        mcp_tasks.cancel(front, {'taskId': value})


def test_cancel_and_failure(front):
    value = RUN_ID + '.' + RUN_KEY
    assert mcp_tasks.cancel(front, {'taskId': value})['status'] == 'cancelled' and front.workflows.cancelled == [RUN_ID]
    front.workflows.status = 'failed'
    task = mcp_tasks.get(front, {'taskId': value})
    assert task['status'] == 'failed' and task['statusMessage'] == 'node 2 timed out' and 'pollInterval' not in task
    assert mcp_tasks.result(front, {'taskId': value}, wait=0)['isError'] is True


@pytest.mark.parametrize('value', [None, 'nope', RUN_ID + '.' + 'x' * 43, RUN_ID, RUN_ID + '.' + RUN_KEY + '!'])
def test_unknown_or_wrong_key_is_not_found(front, value):
    with pytest.raises(mcp_tasks.TaskError, match='Task not found'):
        mcp_tasks.get(front, {'taskId': value})


def test_endpoint_advertises_tasks_and_refuses_unreviewed_runs():
    from agent_market.concierge.front import create_front_app
    from tests.test_gateway import populated
    client = TestClient(create_front_app(populated().app.state.front))
    call = lambda method, params: client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).json()
    init = call('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 't'}})['result']
    assert init['capabilities']['tasks'] == {'cancel': {}, 'requests': {'tools': {'call': {}}}}
    tools = {tool['name']: tool for tool in call('tools/list', {})['result']['tools']}
    assert tools['run_workflow']['execution'] == {'taskSupport': 'optional'}
    assert tools['run_workflow']['annotations']['readOnlyHint'] is False
    assert all('execution' not in tool for name, tool in tools.items() if name != 'run_workflow')
    refused = call('tools/call', {'name': 'run_workflow', 'arguments': {'template_id': 1}, 'task': {'ttl': 60000}})
    assert refused['result']['isError'] is True and 'definition_hash' in refused['result']['structuredContent']['error']
    missing = call('tasks/get', {'taskId': RUN_ID + '.' + RUN_KEY})
    assert missing['error'] == {'code': -32602, 'message': 'Task not found.'}
    assert call('tasks/list', {})['error']['code'] == -32601  # listing is not offered without caller identity


def test_endpoint_answers_a_task_request_at_once(monkeypatch):
    from agent_market.concierge.front import create_front_app
    from tests.test_gateway import populated
    front = populated().app.state.front
    runs = Runs()
    for name in ('get', 'authorized', 'cancel'):
        monkeypatch.setattr(front.workflows, name, getattr(runs, name))
    monkeypatch.setattr(mcp_tasks, 'start', lambda front, args: runs.submit({'id': 5}))
    client = TestClient(create_front_app(front))
    call = lambda method, params: client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).json()
    created = call('tools/call', {'name': 'run_workflow', 'arguments': {'template_id': 5, 'definition_hash': HASH},
                                  'task': {'ttl': 60000}})['result']
    value = RUN_ID + '.' + RUN_KEY
    assert created['task']['taskId'] == value and created['task']['status'] == 'working'
    plain = call('tools/call', {'name': 'run_workflow', 'arguments': {'template_id': 5, 'definition_hash': HASH}})['result']
    assert plain['structuredContent']['taskId'] == value and plain['isError'] is False
    runs.status = 'succeeded'
    assert call('tasks/get', {'taskId': value})['result']['status'] == 'completed'
    assert call('tasks/result', {'taskId': value})['result']['structuredContent']['workflow_name'] == 'Weather brief'

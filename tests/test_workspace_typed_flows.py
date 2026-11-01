"""Whole-graph execution uses real MCP transport against synthetic responders."""
import copy
import json
import threading
import time
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway import admin_auth
from agent_market.workspace_access import WorkspaceAccess, SessionActor, WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid
from agent_market.workspace_execution import WorkspaceExecution
from agent_market.workspace_typed_flows import TypedFlows, NOTICE
from agent_market.workspace_typed_flow_service import router_for
from agent_market.workflow_backup import quarantine
from tests.test_workflow_fallback import routing


@pytest.fixture
def typed_world(routing):
    rt, _, ids, calls, modes, hooks, remote = routing
    with rt.store.tx() as db:
        db.executescript(admin_auth.ADMIN_SCHEMA)
        user = admin_auth.create_admin_user(db, 'typed-owner', 'Synthetic-typed-password42', 'Synthetic owner', 'superadmin')
        raw = admin_auth.create_session(db, user['id'], user['username'], user['role'], user['name'])
    actor = SessionActor(user['id'], admin_auth.session_reference(raw))
    access = WorkspaceAccess(rt.store, rt.key)
    ws = access.provision({'name': 'Private typed graphs', 'owner_id': user['id']}, actor)['id']
    execution = WorkspaceExecution(access, rt.proxy); core = TypedFlows(execution)
    yield SimpleNamespace(rt=rt, store=rt.store, access=access, execution=execution, core=core, actor=actor, ws=ws,
                          ids=ids, calls=calls, modes=modes, hooks=hooks, remote=remote, raw=raw)


def node(identity, resource, *, parent=None, condition=None):
    return {'id': identity, 'resource_id': resource, 'contract_id': 'docs.search.v1',
            'input': {'query': 'Current documentation', 'language': 'en', 'limit': 2} if not parent else {'language': 'en', 'limit': 2},
            'bindings': {} if not parent else {'query': {'node_id': parent, 'path': ['items', 0, 'title']}},
            'after': [] if not parent else [parent], 'when': condition}


def graph(w):
    return {'nodes': [node('first', w.ids[0]), node('followup', w.ids[1], parent='first',
        condition={'node_id': 'first', 'path': ['partial'], 'equals': False})]}


def save(w, definition=None):
    return w.core.save(w.ws, {'flow_id': None, 'revision': 0, 'name': 'Private evidence workflow', 'definition': definition or graph(w)}, w.actor)


def test_library_counts_current_version_steps_including_reused_agents_and_retired_flows(typed_world):
    w = typed_world; flow = save(w)
    assert w.core.listing(w.ws, w.actor)[0]['step_count'] == 2
    definition = {'nodes': [node('step_' + str(i), w.ids[0],
        parent='step_' + str(i - 1) if i else None) for i in range(10)]}
    updated = w.core.save(w.ws, {'flow_id': flow['id'], 'revision': flow['revision'],
        'name': 'Ten configured agent steps', 'definition': definition}, w.actor)
    item = w.core.listing(w.ws, w.actor)[0]
    assert item['step_count'] == 10 and 'definition' not in item and 'pins' not in item
    w.core.disable(w.ws, flow['id'], {'revision': updated['revision']}, w.actor)
    item = w.core.listing(w.ws, w.actor)[0]
    assert item['step_count'] == 10 and not item['active']


def run(w, flow, ticket=None):
    ticket = ticket or w.core.prepare(w.ws, flow['id'], {'revision': flow['revision']}, w.actor)
    return w.core.execute(w.ws, flow['id'], {'ticket_id': ticket['ticket_id'], 'authorized': True, 'notice': NOTICE}, w.actor), ticket


def test_actual_two_step_projection_explicit_graph_review_and_replay(typed_world):
    w = typed_world; flow = save(w)
    arguments = []
    w.hooks['alternate.example'] = lambda request: arguments.append(json.loads(request.content)['params']['arguments'])
    assert not w.calls
    ticket = w.core.prepare(w.ws, flow['id'], {'revision': 1}, w.actor)
    assert not w.calls and ticket['review']['prior_output_sharing'] and ticket['review']['max_calls'] == 2
    assert ticket['review']['nodes'][1]['bindings']['query']['path'] == ['items', 0, 'title']
    result, _ = run(w, flow, ticket)
    assert result['run']['status'] == 'succeeded', result
    assert w.calls == ['primary.example', 'alternate.example']
    assert all(item['status'] == 'succeeded' for item in result['run']['steps'])
    assert arguments[0]['query'] == 'Current documentation'
    replay, _ = run(w, flow, ticket)
    assert replay['replayed'] and replay['run']['id'] == result['run']['id'] and len(w.calls) == 2
    assert w.store.query('SELECT COUNT(*) FROM workspace_private_runs')[0][0] == 0
    assert w.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == 0


def test_boolean_branch_skip_calls_only_selected_path(typed_world):
    w = typed_world; definition = graph(w); definition['nodes'][1]['when']['equals'] = True
    flow = save(w, definition); result, _ = run(w, flow)
    assert result['run']['status'] == 'succeeded' and w.calls == ['primary.example']
    assert [item['status'] for item in result['run']['steps']] == ['succeeded', 'skipped']


@pytest.mark.parametrize('fault', ['cycle', 'self', 'missing_parent', 'unknown_field', 'object_projection', 'dynamic_path',
    'string_condition', 'expression', 'overlap', 'too_many', 'unknown_contract', 'credential', 'unhashable_after'])
def test_unsupported_or_ambiguous_graph_is_rejected_without_calls(typed_world, fault):
    w = typed_world; definition = graph(w)
    if fault == 'cycle': definition['nodes'][0]['after'] = ['followup']
    elif fault == 'self': definition['nodes'][0]['after'] = ['first']
    elif fault == 'missing_parent': definition['nodes'][1]['after'] = []
    elif fault == 'unknown_field': definition['nodes'][1]['bindings']['query']['path'] = ['items', 0, 'private_token']
    elif fault == 'object_projection': definition['nodes'][1]['bindings']['query']['path'] = ['items', 0]
    elif fault == 'dynamic_path': definition['nodes'][1]['bindings']['query']['path'] = ['items', '${index}', 'title']
    elif fault == 'string_condition': definition['nodes'][1]['when'] = {'node_id': 'first', 'path': ['items', 0, 'title'], 'equals': 'Any title'}
    elif fault == 'expression': definition['nodes'][1]['when']['eval'] = 'True'
    elif fault == 'overlap': definition['nodes'][1]['input']['query'] = 'hidden overlap'
    elif fault == 'too_many': definition['nodes'] = [node('step' + str(index), w.ids[0]) for index in range(11)]
    elif fault == 'unknown_contract': definition['nodes'][0]['contract_id'] = 'shell.execute.v1'
    elif fault == 'credential': definition['nodes'][0]['input']['token'] = 'synthetic-secret'
    else: definition['nodes'][0]['after'] = [{}]
    with pytest.raises((WorkspaceInvalid, ValueError)): save(w, definition)
    assert not w.calls and not w.core.listing(w.ws, w.actor)


def test_consent_wrong_session_and_withdrawn_approval_are_denied_before_first_call(typed_world):
    w = typed_world; flow = save(w); ticket = w.core.prepare(w.ws, flow['id'], {'revision': 1}, w.actor)
    with pytest.raises(WorkspaceInvalid): w.core.execute(w.ws, flow['id'], {'ticket_id': ticket['ticket_id'], 'authorized': False, 'notice': NOTICE}, w.actor)
    with w.store.tx() as db: db.execute('DELETE FROM capability_approvals WHERE version_id IN (SELECT id FROM connection_versions WHERE resource_id=?)', (w.ids[1],))
    with pytest.raises(WorkspaceDenied): run(w, flow, ticket)
    assert not w.calls


def test_authority_withdrawal_after_first_response_prevents_followup(typed_world):
    w = typed_world; flow = save(w)
    def withdraw(_):
        with w.store.tx() as db: db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?', (w.ws,))
    w.hooks['primary.example'] = withdraw
    result, _ = run(w, flow)
    assert result['run']['status'] == 'unknown' and w.calls == ['primary.example']
    assert all(item['output'] is None for item in result['run']['steps'])


def test_dispatched_timeout_is_unknown_and_never_retries_or_falls_back(typed_world):
    w = typed_world; flow = save(w); w.modes['primary.example'] = 'unknown'
    result, ticket = run(w, flow)
    assert result['run']['status'] == 'unknown' and w.calls == ['primary.example']
    again, _ = run(w, flow, ticket)
    assert again['replayed'] and again['run']['status'] == 'unknown' and w.calls == ['primary.example']


def test_definitive_contract_failure_stops_followup_and_hides_output(typed_world):
    w = typed_world; flow = save(w); w.modes['primary.example'] = 'invalid'
    result, _ = run(w, flow)
    assert result['run']['status'] == 'failed' and result['run']['error_code'] == 'CONTRACT_REJECTED'
    assert w.calls == ['primary.example'] and all(item['output'] is None for item in result['run']['steps'])


def test_new_graph_revision_rejects_old_review_and_stale_save_cas(typed_world):
    w = typed_world; flow = save(w); ticket = w.core.prepare(w.ws, flow['id'], {'revision': 1}, w.actor)
    body = {'flow_id': flow['id'], 'revision': 1, 'name': 'Changed name', 'definition': graph(w)}
    changed = w.core.save(w.ws, body, w.actor)
    assert changed['revision'] == 2
    with pytest.raises(WorkspaceConflict): w.core.save(w.ws, body, w.actor)
    with pytest.raises(WorkspaceDenied): run(w, flow, ticket)
    assert not w.calls


def test_signed_graph_tampering_and_atomic_version_failure(typed_world):
    w = typed_world; flow = save(w)
    with w.store.tx() as db: db.execute("UPDATE workspace_typed_flow_versions SET payload='{}' WHERE id=?", (flow['version_id'],))
    with pytest.raises(WorkspaceConflict): w.core.prepare(w.ws, flow['id'], {'revision': 1}, w.actor)
    assert not w.calls


def test_restore_blocks_graphs_and_old_review_without_rewriting_signed_history(typed_world):
    w = typed_world; flow = save(w); ticket = w.core.prepare(w.ws, flow['id'], {'revision': 1}, w.actor)
    before = w.store.query('SELECT payload,signature FROM workspace_typed_flow_versions')[0][:]
    with w.store.tx() as db:
        db.execute('INSERT INTO workspace_typed_flow_restore_blocks VALUES(?)', (flow['id'],))
    with pytest.raises(WorkspaceDenied): run(w, flow, ticket)
    assert before == w.store.query('SELECT payload,signature FROM workspace_typed_flow_versions')[0][:]
    assert not w.calls


def test_strict_api_staff_namespace_csrf_and_safe_projection(typed_world):
    w = typed_world; app = FastAPI(); app.include_router(router_for(w.core))
    base = '/admin/api/workflow-workspaces/' + w.ws + '/typed-flows'
    headers = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + w.raw}
    with TestClient(app, base_url='https://admin.test') as client:
        assert client.get(base).status_code == 401
        assert client.get(base, headers=headers).status_code == 200
        response = client.post(base, headers=headers, json={'flow_id': None, 'revision': 0, 'name': 'Typed graph', 'definition': graph(w)})
        assert response.status_code == 200, response.text
        assert 'no-store' in response.headers['cache-control']
        assert 'session_ref' not in response.text and 'signature' not in response.text
        bad = client.post(base, headers={**headers, 'Origin': 'https://other.test'}, json={})
        assert bad.status_code in (401, 403)
        assert not w.calls


def test_concurrent_replay_cannot_dispatch_same_graph_twice(typed_world):
    w = typed_world; flow = save(w); ticket = w.core.prepare(w.ws, flow['id'], {'revision': 1}, w.actor)
    entered, release = threading.Event(), threading.Event()
    w.hooks['primary.example'] = lambda _: (entered.set(), release.wait(4))
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(run, w, flow, ticket)
        assert entered.wait(3)
        try:
            second, _ = run(w, flow, ticket)
            assert second['replayed'] and second['run']['status'] == 'running'
            assert w.calls == ['primary.example']
        finally:
            release.set()
        completed, _ = first.result(timeout=5)
    assert completed['run']['status'] == 'succeeded' and len(w.calls) == 2
    assert w.store.query('SELECT COUNT(*) FROM workspace_typed_flow_runs')[0][0] == 1


def test_late_response_cannot_replace_unknown_timeout_or_start_followup(typed_world, monkeypatch):
    w = typed_world; flow = save(w)
    import agent_market.workspace_typed_flows as module
    monkeypatch.setitem(module.LIMITS, 'seconds', 0.12)
    futures = []; submit = module._pool.submit
    def capture(*args, **kwargs):
        future = submit(*args, **kwargs); futures.append(future); return future
    monkeypatch.setattr(module._pool, 'submit', capture)
    entered, release = threading.Event(), threading.Event()
    w.hooks['primary.example'] = lambda _: (entered.set(), release.wait(3))
    try:
        result, _ = run(w, flow)
        assert entered.is_set() and result['run']['status'] == 'unknown'
        assert w.calls == ['primary.example']
    finally:
        release.set()
    futures[0].result(timeout=3)
    assert w.core.get(w.ws, flow['id'], result['run']['id'], w.actor)['status'] == 'unknown'
    assert w.calls == ['primary.example']


def test_disable_is_cas_bound_and_stops_reviewed_graph_before_dispatch(typed_world):
    w = typed_world; flow = save(w); ticket = w.core.prepare(w.ws, flow['id'], {'revision': 1}, w.actor)
    value = w.core.disable(w.ws, flow['id'], {'revision': 1}, w.actor)
    assert value['revision'] == 2 and value['active'] is False
    with pytest.raises(WorkspaceDenied): run(w, flow, ticket)
    assert not w.calls


def test_native_transaction_rolls_back_partial_version_on_flow_failure(typed_world):
    w = typed_world
    with w.store.tx() as db:
        db.execute("CREATE TRIGGER deny_flow BEFORE INSERT ON workspace_typed_flows BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(WorkspaceConflict): save(w)
    assert w.store.query('SELECT COUNT(*) FROM workspace_typed_flow_versions')[0][0] == 0
    assert not w.calls


def test_restore_keeps_signed_graph_but_blocks_it_after_manual_workspace_reactivation(typed_world):
    w = typed_world; flow = save(w)
    before = w.store.query('SELECT payload,signature FROM workspace_typed_flow_versions')[0][:]
    with w.store.tx() as db:
        quarantine(db)
        assert db.execute('SELECT 1 FROM workspace_typed_flow_restore_blocks WHERE id=?', (flow['id'],)).fetchone()
        db.execute('UPDATE organization_workspaces SET active=1 WHERE id=?', (w.ws,))
        db.execute('UPDATE workspace_memberships SET active=1 WHERE workspace_id=?', (w.ws,))
        user = db.execute('SELECT username,role,name FROM admin_users WHERE id=?', (w.actor.user_id,)).fetchone()
        raw = admin_auth.create_session(db, w.actor.user_id, user['username'], user['role'], user['name'])
    current = SessionActor(w.actor.user_id, admin_auth.session_reference(raw))
    with pytest.raises(WorkspaceDenied): w.core.prepare(w.ws, flow['id'], {'revision': 1}, current)
    assert before == w.store.query('SELECT payload,signature FROM workspace_typed_flow_versions')[0][:]
    assert not w.calls


def test_authorized_simulation_meter_counts_one_run_and_each_actual_node_dispatch(typed_world):
    w = typed_world
    from agent_market.workspace_metering import WorkspaceMetering, NOTICE as METER_NOTICE
    meter = WorkspaceMetering(w.access); w.execution.meter = meter
    meter.configure(w.ws, {'revision': 0, 'enabled': True, 'units_per_success': 7, 'max_runs': 5,
        'ttl_seconds': 3600, 'authorized': True, 'notice': METER_NOTICE}, w.actor)
    flow = save(w); result, ticket = run(w, flow)
    assert result['run']['status'] == 'succeeded'
    summary = meter.summary(w.ws, w.actor)
    assert summary['operations'] == 1 and summary['attempts'] == 2
    assert summary['simulated_units'] == 7 and summary['actual_money'] is False
    replay, _ = run(w, flow, ticket)
    assert replay['replayed'] and meter.summary(w.ws, w.actor)['attempts'] == 2


def test_optional_step_encryption_rotates_and_rejects_resigned_cross_node_swap(typed_world, tmp_path, monkeypatch):
    w = typed_world
    from tests.test_private_artifact_keys import configure, config
    path = configure(tmp_path, monkeypatch, config('old', legacy=True))
    w.core = TypedFlows(w.execution); flow = save(w); result, _ = run(w, flow)
    assert result['run']['status'] == 'succeeded'
    rows = w.store.query('SELECT * FROM workspace_typed_flow_steps ORDER BY node_id')
    first, second = [json.loads(row['payload']) for row in rows]
    assert first['output'] is second['output'] is None and first['encrypted_output'] != second['encrypted_output']
    path.write_text(json.dumps(config(legacy=True))); current = TypedFlows(w.execution)
    assert current.get(w.ws, flow['id'], result['run']['id'], w.actor)['steps'][0]['output']
    first['encrypted_output'] = second['encrypted_output']
    with w.store.tx() as db:
        db.execute('UPDATE workspace_typed_flow_steps SET payload=?,signature=? WHERE run_id=? AND node_id=?',
                   (json.dumps(first), current.signer.sign(first), first['run_id'], first['node_id']))
    with pytest.raises(WorkspaceConflict): current.get(w.ws, flow['id'], result['run']['id'], w.actor)


def test_consecutive_calls_to_one_agent_are_spaced(typed_world, monkeypatch):
    # 2026-10-21: a provider rejected the sixth call made within about four seconds.
    import agent_market.workspace_typed_flows as module
    monkeypatch.setattr(module, 'AGENT_INTERVAL_SECONDS', 0.3)
    w = typed_world; stamps = []
    w.hooks['primary.example'] = lambda _: stamps.append(time.monotonic())
    flow = save(w, {'nodes': [node('one', w.ids[0]), node('two', w.ids[0], parent='one'), node('three', w.ids[0], parent='two')]})
    result, _ = run(w, flow)
    assert result['run']['status'] == 'succeeded' and len(stamps) == 3
    assert all(later - earlier >= 0.28 for earlier, later in zip(stamps, stamps[1:]))


def test_workspaces_have_no_workflow_cap(typed_world):
    """11-01: the 50 active-workflow cap is gone; the 51st and later saves succeed and stay active."""
    from agent_market import workspace_typed_flows as module
    w = typed_world
    assert 'flows' not in module.LIMITS
    saved = [save(w) for _ in range(55)]
    listed = {item['id']: item for item in w.core.listing(w.ws, w.actor)}
    assert len(saved) == len(listed) == 55 and all(listed[flow['id']]['active'] for flow in saved)


def test_workflow_queries_are_registered_for_postgresql():
    """QA 18: an unregistered query failed on PostgreSQL and every new save became a generic 409."""
    import ast, inspect, json, textwrap
    from pathlib import Path
    from agent_market import workspace_typed_flows as module
    from agent_market.application_store_postgres import _normalized
    blob = json.loads((Path(module.__file__).parent / 'application_store_sql.json').read_text())
    registered = {_normalized(item['sqlite']) for item in blob['statements']}
    statements = list(module.SCHEMA)
    for method in (module.TypedFlows._save_in_transaction, module.TypedFlows.listing):
        tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
        statements += [item.value for item in ast.walk(tree) if isinstance(item, ast.Constant) and type(item.value) is str
                       and item.value.lstrip().startswith(('SELECT', 'INSERT', 'UPDATE', 'CREATE'))]
    assert len(statements) >= len(module.SCHEMA) + 4
    for statement in statements:
        assert _normalized(statement) in registered, statement


def test_listing_keeps_more_than_fifty_workflows(typed_world):
    """QA 19: the listing stopped at 50 rows, so retired workflows past that could not be found again."""
    w = typed_world
    saved = {save(w)['id'] for _ in range(55)}
    listed = w.core.listing(w.ws, w.actor)
    assert len(listed) == 55 and {item['id'] for item in listed} == saved


def test_listing_queries_are_registered_for_postgresql():
    import inspect, re
    from agent_market import application_store_postgres as postgres, workspace_typed_flows as module
    source = inspect.getsource(module.TypedFlows.listing)
    found = re.findall(r"_rows\(db, (?:'''(.+?)'''|'(.+?)')", source, re.S)
    assert len(found) == 2
    for triple, single in found:
        assert postgres._normalized(triple or single) in postgres._STATEMENTS


def test_listing_pages_past_five_hundred_workflows(typed_world):
    """Without a cap the listing reads 500 rows at a time by id; nothing past the first page is lost."""
    w = typed_world
    saved = {save(w)['id'] for _ in range(1003)}
    listed = w.core.listing(w.ws, w.actor)
    assert len(listed) == 1003 and {item['id'] for item in listed} == saved
    assert all(item['step_count'] >= 1 for item in listed)
    assert [item['updated'] for item in listed] == sorted((item['updated'] for item in listed), reverse=True)

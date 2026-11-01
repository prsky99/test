"""Independent private-run withdrawal, concurrency and namespace checks.

All provider traffic uses the shared isolated McpProxy/MockTransport fixture.
These checks make no live-provider or operating-workspace claims.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from threading import Barrier

import pytest

from agent_market.execution_authority import controls, set_controls
from agent_market.gateway import admin_auth
from agent_market.workspace_service import BASE
from agent_market.workspace_execution import WorkspaceExecution
from tests.test_workspace_execution_api import authorized, execute, prepare, private_api


def _post(w, ticket, person='owner', *, headers=None, path=None):
    return w.client.post((path or w.path) + '/runs',
        headers=headers or w.headers[person], json=authorized(ticket))


def _resource_generation(w):
    return w.store.query('SELECT generation FROM resource_observation_generations WHERE resource_id=?',
                         (w.rid,))[0][0]


@pytest.mark.parametrize('change', ['url_aba', 'schema_aba', 'membership_aba', 'controls_aba'])
def test_handshake_withdrawal_then_restoration_cannot_revive_an_old_ticket(private_api, change):
    w = private_api
    ticket = prepare(w)
    generation = _resource_generation(w)
    def withdraw_then_restore():
        if change in ('url_aba', 'schema_aba'):
            column = 'url' if change == 'url_aba' else 'usage_tools_hash'
            original = w.store.resource(w.rid)[column]
            changed = 'https://changed-provider.example/mcp' if column == 'url' else 'a' * 64
            with w.store.tx() as db:
                db.execute('UPDATE resources SET ' + column + '=? WHERE id=?', (changed, w.rid))
                db.execute('UPDATE resources SET ' + column + '=? WHERE id=?', (original, w.rid))
            assert _resource_generation(w) > generation
        elif change == 'membership_aba':
            with w.store.tx() as db:
                db.execute('''UPDATE workspace_memberships SET active=0,revision=revision+1
                    WHERE workspace_id=? AND user_id=?''', (w.ws['id'], w.users['owner']))
                db.execute('''UPDATE workspace_memberships SET active=1,revision=revision+1
                    WHERE workspace_id=? AND user_id=?''', (w.ws['id'], w.users['owner']))
        else:
            state = controls(w.store)
            paused = set_controls(w.store, {key: state[key] for key in
                ('invoke_enabled', 'workflow_enabled', 'delivery_enabled')} |
                {'invoke_enabled': False, 'revision': state['revision']}, w.users['owner'])
            set_controls(w.store, {key: paused[key] for key in
                ('invoke_enabled', 'workflow_enabled', 'delivery_enabled')} |
                {'invoke_enabled': True, 'revision': paused['revision']}, w.users['owner'])
    w.control['during_list'] = withdraw_then_restore
    response = _post(w, ticket)
    assert response.status_code in (200, 404, 409), response.text
    if response.status_code == 200:
        assert response.json()['run']['status'] in ('denied', 'failed')
    assert w.calls.count('tools/list') == 1
    assert w.calls.count('tools/call') == 0


def test_two_simultaneous_uses_of_one_ticket_have_one_run_and_at_most_one_dispatch(private_api):
    w = private_api
    ticket = prepare(w)
    gate = Barrier(2)
    def start_once():
        gate.wait(timeout=5)
        return _post(w, ticket)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start_once) for _ in range(2)]
        responses = [future.result(timeout=15) for future in futures]
    assert all(response.status_code in (200, 409) for response in responses), [r.text for r in responses]
    accepted = [response.json()['run'] for response in responses if response.status_code == 200]
    assert accepted and len({run['id'] for run in accepted}) == 1
    assert w.calls.count('tools/call') == 1
    history = w.client.get(w.path + '/runs', headers=w.headers['owner']).json()['runs']
    assert [run['id'] for run in history] == [accepted[0]['id']]


def test_accepted_unknown_is_readable_after_new_login_but_old_ticket_is_not_reauthorized(private_api):
    w = private_api
    w.control['mode'] = 'timeout'
    job, ticket = execute(w)
    assert job['status'] == 'unknown'
    old_token = w.headers['owner']['Authorization'][7:]
    with w.store.tx() as db:
        db.execute('DELETE FROM admin_sessions WHERE token=?', (admin_auth.session_reference(old_token),))
        row = db.execute('SELECT * FROM admin_users WHERE id=?', (w.users['owner'],)).fetchone()
        token = admin_auth.create_session(db, row['id'], row['username'], row['role'], row['name'])
    new_headers = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + token}
    result = w.client.get(w.path + '/runs/' + job['id'], headers=new_headers)
    assert result.status_code == 200 and result.json()['run']['status'] == 'unknown', result.text
    replay = _post(w, ticket, headers=new_headers)
    assert replay.status_code in (404, 409)
    assert w.calls.count('tools/call') == 1


def test_run_cannot_be_rebound_to_another_snapshot_of_the_same_draft(private_api):
    w = private_api
    job, ticket = execute(w)
    response = w.client.post(f'{BASE}/{w.ws["id"]}/drafts/{w.draft["id"]}/snapshots',
        headers=w.headers['owner'], json={'draft_revision': w.draft['revision']})
    assert response.status_code == 200, response.text
    second = response.json()['snapshot']['id']
    second_path = w.path.replace(w.snapshot['id'], second)
    result = w.client.get(second_path + '/runs/' + job['id'], headers=w.headers['owner'])
    assert result.status_code == 404 and 'Private research result' not in result.text
    assert _post(w, ticket, path=second_path).status_code in (404, 409)
    assert w.calls.count('tools/call') == 1


@pytest.mark.parametrize('change', ['member_removed', 'snapshot_revoked', 'draft_archived', 'workspace_archived'])
def test_accepted_private_results_obey_current_content_withdrawal(private_api, change):
    w = private_api
    job, _ = execute(w)
    if change == 'member_removed':
        with w.store.tx() as db:
            db.execute('UPDATE workspace_memberships SET active=0,revision=revision+1 WHERE workspace_id=? AND user_id=?',
                       (w.ws['id'], w.users['viewer']))
    elif change == 'snapshot_revoked':
        response = w.client.post(w.path.removesuffix('/execution') + '/revoke', headers=w.headers['owner'],
                                 json={'revision': w.snapshot['revision']})
        assert response.status_code == 200, response.text
    elif change == 'draft_archived':
        response = w.client.post(f'{BASE}/{w.ws["id"]}/drafts/{w.draft["id"]}/archive', headers=w.headers['owner'],
                                 json={'revision': w.draft['revision']})
        assert response.status_code == 200, response.text
    else:
        current = w.client.get(f'{BASE}/{w.ws["id"]}', headers=w.headers['owner'])
        assert current.status_code == 200, current.text
        response = w.client.post(f'{BASE}/{w.ws["id"]}/archive', headers=w.headers['owner'],
                                 json={'active': False, 'revision': current.json()['workspace']['revision']})
        assert response.status_code == 200, response.text
    result = w.client.get(w.path + '/runs/' + job['id'], headers=w.headers['viewer'])
    assert result.status_code == 404 and 'Private research result' not in result.text
    assert w.calls.count('tools/call') == 1


def test_private_inputs_and_results_never_enter_the_global_observation_journal(private_api):
    w = private_api
    job, _ = execute(w)
    assert job['status'] == 'succeeded'
    for table in ('platform_operations', 'platform_attempts', 'platform_observation_events',
                  'capability_evidence', 'workflow_runs', 'workflow_versions', 'workflow_node_runs',
                  'workflow_run_authority', 'workflow_result_outbox'):
        rows = [dict(row) for row in w.store.query('SELECT * FROM ' + table)]
        serialized = json.dumps(rows)
        assert 'Synthetic semiconductor research' not in serialized
        assert 'Private research result' not in serialized
        assert w.ws['id'] not in serialized
        assert w.draft['id'] not in serialized
        assert w.snapshot['id'] not in serialized


def test_an_independent_writer_can_withdraw_the_session_during_discovery(private_api):
    w = private_api
    ticket = prepare(w)
    changed = []
    def revoke_from_another_connection():
        with sqlite3.connect(w.store._path, timeout=.1) as writer:
            writer.execute('DELETE FROM admin_sessions WHERE token=?',
                (admin_auth.session_reference(w.headers['owner']['Authorization'][7:]),))
        changed.append(True)
    w.control['during_list'] = revoke_from_another_connection
    response = _post(w, ticket)
    assert changed == [True]
    assert response.status_code == 200, response.text
    assert response.json()['run']['status'] == 'denied'
    assert w.calls.count('tools/call') == 0


def test_session_loss_after_real_dispatch_preserves_unknown_without_private_output(private_api, monkeypatch):
    w = private_api
    ticket = prepare(w)
    original = w.remote.handle_request
    def provider_accepted_then_session_withdrawn(request):
        response = original(request)
        if json.loads(request.content or b'{}').get('method') == 'tools/call':
            with w.store.tx() as db:
                db.execute('DELETE FROM admin_sessions WHERE token=?',
                    (admin_auth.session_reference(w.headers['owner']['Authorization'][7:]),))
        return response
    monkeypatch.setattr(w.remote, 'handle_request', provider_accepted_then_session_withdrawn)
    response = _post(w, ticket)
    assert response.status_code == 200, response.text
    result = response.json()['run']
    assert result['status'] == 'unknown' and result['output'] is None
    assert w.calls.count('tools/call') == 1
    assert 'Private research result' not in response.text
    detail = w.client.get(w.path + '/runs/' + result['id'], headers=w.headers['viewer'])
    assert detail.status_code == 200 and detail.json()['run']['status'] == 'unknown'


def test_accepted_run_insert_failure_rolls_back_ticket_consumption_before_any_provider_call(private_api, monkeypatch):
    w = private_api
    ticket = prepare(w)
    original = WorkspaceExecution._store_run
    accepted = []
    def accepted_then_failed(self, db, payload, *, insert=False):
        original(self, db, payload, insert=insert)
        if insert:
            assert db.execute('SELECT id FROM workspace_private_runs WHERE id=?', (payload['id'],)).fetchone()
            accepted.append(payload['id'])
            raise sqlite3.OperationalError('Synthetic accepted SQL failure')
    with monkeypatch.context() as patch:
        patch.setattr(WorkspaceExecution, '_store_run', accepted_then_failed)
        failed = _post(w, ticket)
    assert failed.status_code == 409 and len(accepted) == 1, failed.text
    assert not w.calls
    assert w.store.query('SELECT COUNT(*) FROM workspace_private_runs')[0][0] == 0
    assert w.store.query('SELECT run_id FROM workspace_private_tickets WHERE id=?', (ticket['ticket_id'],))[0][0] is None
    retry = _post(w, ticket)
    assert retry.status_code == 200 and retry.json()['run']['status'] == 'succeeded', retry.text
    assert w.calls.count('tools/call') == 1

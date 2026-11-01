"""Private execution uses synthetic registered rows and a no-network proxy."""
import copy
import json
import sqlite3
import threading
import time

import pytest

import agent_market.workspace_execution as module
from agent_market.collector import usage
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from agent_market.workspace_execution import LIMITS, NOTICE, PROFILE, WorkspaceExecution
from tests.test_workspace_access import definition, draft_body, member, provision, workspace_world


class FixtureProxy:
    def __init__(self):
        self.before = None
        self.after = None
        self.calls = 0
        self.requests = 0
        self.result = {'ok': True, 'result': {'content': [{'type': 'text', 'text': 'Synthetic private result'}]}}

    def execute(self, resource_id, tool, arguments, *, public=False):
        assert public is True and resource_id == 1 and tool == 'search_news'
        self.requests += 1
        if self.before:
            self.before()
        from agent_market.observability import provider_dispatch
        provider_dispatch()
        self.calls += 1
        if self.after:
            self.after()
        return copy.deepcopy(self.result)


def execution_world(path=':memory:'):
    store, access, actors = workspace_world(path)
    db = store._db
    for name, declaration in (('health_status', 'TEXT'), ('eval_security', 'TEXT'),
                              ('price_usdc', 'INTEGER'), ('usage_tools_hash', 'TEXT'),
                              ('auth_required', 'INTEGER'), ('auth_observed', 'INTEGER'),
                              ('auth_declared', 'INTEGER'), ('auth_info', 'TEXT')):
        db.execute('ALTER TABLE resources ADD COLUMN ' + name + ' ' + declaration)
    specs = json.loads(db.execute('SELECT usage_tools FROM resources WHERE id=1').fetchone()[0])
    db.execute("UPDATE resources SET health_status='healthy',price_usdc=0,usage_tools_hash=? WHERE id=1",
               (usage.tools_hash(usage.compact_tools(specs)),))
    db.execute('CREATE TABLE resource_observation_generations(resource_id INTEGER PRIMARY KEY,generation INTEGER NOT NULL)')
    db.execute('INSERT INTO resource_observation_generations VALUES(1,1)')
    db.execute('''CREATE TABLE execution_controls(id INTEGER PRIMARY KEY,invoke_enabled INTEGER,workflow_enabled INTEGER,
        delivery_enabled INTEGER,revision INTEGER,updated REAL)''')
    db.execute('INSERT INTO execution_controls VALUES(1,1,1,1,0,0)')
    db.commit()
    proxy = FixtureProxy()
    core = WorkspaceExecution(access, proxy)
    ws = provision((store, access, actors))['id']
    draft = access.save_draft(ws, draft_body(definition()), actors[1])
    snapshot = access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actors[1])
    return store, access, actors, core, proxy, ws, draft['id'], snapshot['id']


@pytest.fixture
def private():
    value = execution_world()
    try:
        yield value
    finally:
        value[0]._db.close()


def prepared(private):
    _, _, actors, core, _, ws, draft, version = private
    return core.prepare(ws, draft, version, {'snapshot_revision': 1}, actors[1])


def request(ticket):
    return {'ticket_id': ticket['ticket_id'], 'authorized': True, 'notice': NOTICE}


def call(private, ticket=None):
    _, _, actors, core, _, ws, draft, version = private
    return core.execute(ws, draft, version, request(ticket or prepared(private)), actors[1])


def test_offline_prepare_has_exact_safe_preview_and_no_legacy_rows(private):
    store, _, actors, core, proxy, ws, draft, version = private
    options = core.options(ws, draft, version, actors[1])
    assert options['can_run'] and options['supported'] and options['notice'] == NOTICE
    ticket = prepared(private)
    assert ticket['ticket_id'].startswith('wpt_') and ticket['preview']['input'] == {'query': 'Storage research'}
    assert ticket['preview']['seconds'] == 12 and ticket['preview']['max_calls'] == 1
    assert proxy.calls == proxy.requests == 0
    raw = json.dumps(ticket)
    assert all(value not in raw for value in ('session_ref', 'signature', 'https://', 'binding_hash', 'sha256:'))
    assert store._db.execute('SELECT COUNT(*) FROM workspace_private_runs').fetchone()[0] == 0
    assert not store._db.execute("SELECT name FROM sqlite_schema WHERE name IN ('agent_workflows','workflow_runs')").fetchall()


def test_single_call_exact_replay_and_metadata_only_history(private):
    _, _, actors, core, proxy, ws, draft, version = private
    ticket = prepared(private)
    result = call(private, ticket)
    assert result['status'] == 'succeeded' and result['id'].startswith('wpr_')
    assert result['output']['content'][0]['text'] == 'Synthetic private result'
    assert result['dispatched'] <= result['finished'] and proxy.calls == 1
    replay = call(private, ticket)
    assert replay['replayed'] and replay['id'] == result['id'] and proxy.calls == 1
    assert 'output' not in core.runs(ws, draft, version, actors[1])[0]
    assert core.run(ws, draft, version, result['id'], actors[1])['output'] == result['output']


@pytest.mark.parametrize('body', [{}, {'snapshot_revision': True}, {'snapshot_revision': 0},
    {'snapshot_revision': 1, 'input': {}}, {'snapshot_revision': '1'}])
def test_prepare_body_exact(private, body):
    _, _, actors, core, proxy, ws, draft, version = private
    with pytest.raises(WorkspaceInvalid):
        core.prepare(ws, draft, version, body, actors[1])
    assert proxy.calls == 0


@pytest.mark.parametrize('change', [{'authorized': False}, {'authorized': 1}, {'notice': 'legacy'}, {'input': {}}])
def test_explicit_live_authority_exact_and_not_inherited(private, change):
    _, _, actors, core, proxy, ws, draft, version = private
    body = request(prepared(private)) | change
    with pytest.raises(WorkspaceInvalid):
        core.execute(ws, draft, version, body, actors[1])
    assert proxy.requests == 0


def test_viewer_and_operator_can_read_but_not_prepare_or_execute(private):
    store, access, actors, core, proxy, ws, draft, version = private
    for uid, role in ((2, 'viewer'), (3, 'editor')):
        member((store, access, actors), ws, uid, role)
        assert not core.options(ws, draft, version, actors[uid])['can_run']
        with pytest.raises(WorkspaceDenied):
            core.prepare(ws, draft, version, {'snapshot_revision': 1}, actors[uid])
    result = call(private)
    assert core.run(ws, draft, version, result['id'], actors[2])['status'] == 'succeeded'
    assert proxy.calls == 1


@pytest.mark.parametrize('field,value', [('health_status', 'down'), ('eval_security', 'review'),
    ('price_usdc', 1), ('auth_observed', 1), ('auth_required', 1), ('auth_declared', 1),
    ('auth_info', '{"token":"synthetic"}'), ('active', 0), ('usage_tools_hash', None)])
def test_ineligible_agents_cannot_prepare(private, field, value):
    store, _, actors, core, proxy, ws, draft, version = private
    with store._db:
        store._db.execute('UPDATE resources SET ' + field + '=? WHERE id=1', (value,))
    assert not core.options(ws, draft, version, actors[1])['can_run']
    with pytest.raises(WorkspaceDenied):
        prepared(private)
    assert proxy.requests == 0


@pytest.mark.parametrize('annotation,value', [('readOnlyHint', False), ('destructiveHint', True), ('idempotentHint', False)])
def test_all_three_explicit_tool_annotations_are_required(private, annotation, value):
    store, _, _, _, proxy, _, _, _ = private
    tools = json.loads(store._db.execute('SELECT usage_tools FROM resources WHERE id=1').fetchone()[0])
    tools[0]['annotations'][annotation] = value
    with store._db:
        store._db.execute('UPDATE resources SET usage_tools=? WHERE id=1', (json.dumps(tools),))
    with pytest.raises(WorkspaceDenied):
        prepared(private)
    assert proxy.requests == 0


def test_other_saved_profiles_are_non_executable(private):
    _, access, actors, core, proxy, ws, _, _ = private
    for graph in ({'nodes': [], 'edges': []}, definition('a2a'), definition('x402')):
        draft = access.save_draft(ws, draft_body(graph), actors[1])
        version = access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actors[1])
        assert core.options(ws, draft['id'], version['id'], actors[1])['unsupported_reason'] == 'unsupported_snapshot'
        with pytest.raises(WorkspaceInvalid):
            core.prepare(ws, draft['id'], version['id'], {'snapshot_revision': 1}, actors[1])
    assert proxy.requests == 0


@pytest.mark.parametrize('fault', ['logout', 'demote', 'deactivate', 'member_revision', 'snapshot_revoke',
                                  'draft_archive', 'control', 'binding', 'schema', 'generation'])
def test_current_authority_rechecked_at_business_dispatch(private, fault):
    store, access, actors, _, proxy, ws, draft, version = private
    ticket = prepared(private)

    def withdraw():
        assert not store._db.in_transaction
        with store._lock, store._db:
            if fault == 'logout':
                store._db.execute('DELETE FROM admin_sessions WHERE user_id=1')
            elif fault == 'demote':
                store._db.execute("UPDATE admin_users SET role='operator' WHERE id=1")
            elif fault == 'deactivate':
                store._db.execute('UPDATE admin_users SET active=0 WHERE id=1')
            elif fault == 'member_revision':
                store._db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?', (ws,))
            elif fault == 'control':
                store._db.execute('UPDATE execution_controls SET revision=revision+1,updated=? WHERE id=1', (time.time(),))
            elif fault == 'binding':
                store._db.execute("UPDATE resources SET url='https://changed.invalid/mcp' WHERE id=1")
            elif fault == 'schema':
                store._db.execute("UPDATE resources SET usage_tools_hash='changed' WHERE id=1")
            elif fault == 'generation':
                store._db.execute('UPDATE resource_observation_generations SET generation=generation+1 WHERE resource_id=1')
        if fault == 'snapshot_revoke':
            access.revoke_version(ws, draft, version, {'revision': 1}, actors[1])
        elif fault == 'draft_archive':
            access.revoke_draft(ws, draft, {'revision': 1}, actors[1])

    proxy.before = withdraw
    result = call(private, ticket)
    assert result['status'] in ('denied', 'failed') and result['output'] is None and proxy.calls == 0


@pytest.mark.parametrize('code', ['UPSTREAM_NETWORK', 'UPSTREAM_TIMEOUT', 'UPSTREAM_PROTOCOL'])
def test_ambiguous_dispatched_outcome_is_retained_unknown_no_retry(private, code):
    _, _, actors, core, proxy, ws, draft, version = private
    proxy.result = {'ok': False, 'error_code': code, 'error': '/private/synthetic/token=never-export'}
    ticket = prepared(private)
    result = call(private, ticket)
    assert result['status'] == 'unknown' and result['error_code'] == code and result['output'] is None
    assert call(private, ticket)['id'] == result['id'] and proxy.calls == 1
    assert 'never-export' not in json.dumps(core.run(ws, draft, version, result['id'], actors[1]))


def test_output_projection_masks_credentials_and_known_invocation_binding_but_preserves_citations(private):
    _, _, _, _, proxy, _, _, _ = private
    proxy.result['result'] = {'token': 'synthetic-private-secret', 'endpoint': 'https://synthetic.invalid/mcp',
                              'citation': 'https://public.example/article',
                              'content': [{'type': 'text', 'text': 'Documentation password=synthetic-private-secret'}]}
    result = call(private)
    encoded = json.dumps(result)
    assert 'synthetic-private-secret' not in encoded and 'https://synthetic.invalid/mcp' not in encoded
    assert 'https://public.example/article' in encoded and '[REDACTED]' in encoded


@pytest.mark.parametrize('value', ['x' * 17000, {'bad': float('nan')}, {'bad': '\ud800'}])
def test_malformed_or_oversized_completed_output_never_persisted(private, value):
    _, _, _, _, proxy, _, _, _ = private
    proxy.result['result'] = value
    result = call(private)
    assert result['status'] == 'failed' and result['error_code'] == 'OUTPUT_REJECTED' and result['output'] is None


def test_restore_revocation_and_deadline_reads_are_projection_only_no_dispatch(private):
    store, _, actors, core, proxy, ws, draft, version = private
    ticket = prepared(private)
    block, release = threading.Event(), threading.Event()
    proxy.before = lambda: (block.set(), release.wait(2))
    result = []
    thread = threading.Thread(target=lambda: result.append(call(private, ticket)))
    thread.start()
    assert block.wait(1)
    with store._lock, store._db:
        row = store._db.execute('SELECT id FROM workspace_private_runs').fetchone()
        store._db.execute('UPDATE workspace_private_tickets SET revoked=? WHERE id=?', (time.time(), ticket['ticket_id']))
    before = store._db.total_changes
    assert core.run(ws, draft, version, row[0], actors[1])['status'] == 'unknown'
    assert store._db.total_changes == before
    release.set()
    thread.join(2)
    assert not thread.is_alive() and proxy.calls == 0 and result[0]['output'] is None


@pytest.mark.parametrize('table,column', [('workspace_private_tickets', 'payload'), ('workspace_private_tickets', 'signature'),
                                         ('workspace_private_runs', 'payload'), ('workspace_private_runs', 'signature'),
                                         ('workspace_private_runs', 'status')])
def test_private_ticket_and_run_tampering_is_refused(private, table, column):
    store, _, actors, core, _, ws, draft, version = private
    result = call(private)
    with store._db:
        store._db.execute('UPDATE ' + table + ' SET ' + column + '=?', ('tampered',))
    with pytest.raises(WorkspaceConflict):
        core.run(ws, draft, version, result['id'], actors[1])


def test_expired_unused_ticket_does_not_reserve_or_call(private, monkeypatch):
    store, _, _, _, proxy, _, _, _ = private
    ticket = prepared(private)
    monkeypatch.setattr(module, '_now', lambda: ticket['expires'] + 1)
    with pytest.raises(WorkspaceDenied):
        call(private, ticket)
    assert store._db.execute('SELECT COUNT(*) FROM workspace_private_runs').fetchone()[0] == 0
    assert proxy.calls == 0


def test_pending_ticket_quota_is_bounded_without_execution(private):
    for _ in range(LIMITS['pending_tickets']):
        prepared(private)
    with pytest.raises(WorkspaceConflict):
        prepared(private)
    assert private[4].requests == 0


def test_accepted_admission_commit_response_loss_is_never_reexecuted(tmp_path, monkeypatch):
    class UncertainConnection(sqlite3.Connection):
        armed = False

        def commit(self):
            super().commit()
            if self.armed and self.execute('SELECT COUNT(*) FROM workspace_private_runs').fetchone()[0]:
                self.armed = False
                raise sqlite3.OperationalError('Synthetic accepted commit response loss')

    value = execution_world(str(tmp_path / 'owned.sqlite3'))
    store, _, actors, core, proxy, ws, draft, version = value
    try:
        ticket = prepared(value)
        store._db.close()
        store._db = sqlite3.connect(str(tmp_path / 'owned.sqlite3'), check_same_thread=False, factory=UncertainConnection)
        store._db.row_factory = sqlite3.Row
        store._db.armed = True
        with pytest.raises(WorkspaceConflict):
            call(value, ticket)
        assert proxy.requests == 0
        replay = call(value, ticket)
        assert replay['replayed'] and replay['status'] == 'prepared' and proxy.requests == 0
        assert store._db.execute('SELECT COUNT(*) FROM workspace_private_runs').fetchone()[0] == 1
        monkeypatch.setattr(module, '_now', lambda: replay['deadline'] + 1)
        assert core.run(ws, draft, version, replay['id'], actors[1])['status'] == 'unknown'
        assert proxy.requests == 0
    finally:
        store._db.close()


def test_late_dispatched_success_cannot_overwrite_timeout(private, monkeypatch):
    _, _, actors, core, proxy, ws, draft, version = private
    # Shorten only the synthetic clock budget; production remains fixed12seconds.
    monkeypatch.setitem(module.LIMITS, 'seconds', 0.05)
    release, finished = threading.Event(), threading.Event()
    proxy.after = lambda: (release.wait(2), finished.set())
    result = call(private)
    assert result['status'] == 'unknown' and result['error_code'] == 'UPSTREAM_TIMEOUT'
    assert proxy.calls == 1
    release.set()
    assert finished.wait(1)
    time.sleep(0.02)
    retained = core.run(ws, draft, version, result['id'], actors[1])
    assert retained['status'] == 'unknown' and retained['output'] is None
    assert call(private, {'ticket_id': private[0]._db.execute('SELECT id FROM workspace_private_tickets').fetchone()[0]})['replayed']
    assert proxy.calls == 1

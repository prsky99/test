"""Isolated canonical public connection purposes and certainty boundaries."""
import copy
from datetime import datetime, timezone
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from agent_market.gateway.admin_auth import ADMIN_SCHEMA, create_admin_user
from agent_market.workflow_publication import PROFILE, TEST_SHARE_NOTICE, TEST_RUN_NOTICE, PUBLISH_NOTICE, SHARE_NOTICE, RUN_NOTICE
from agent_market.workflow_public_flow import public_title
from agent_market.workflows import WorkflowError, public_template
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_runtime import wait


@pytest.fixture
def publication(typed_routing):
    rt = typed_routing[0]
    with rt.store._lock: rt.store._db.executescript(ADMIN_SCHEMA)
    with rt.store.tx() as db:
        owner = create_admin_user(db, 'publication-reviewer', 'isolated-long-password', 'Publication reviewer', 'superadmin')
    if isinstance(owner, dict): owner = owner['id']
    return rt, owner, typed_routing


def candidate(rt, owner):
    options = rt.publication.options(owner)
    return rt.publication.candidate({'source_id': options['news'][0]['id'], 'target_id': options['docs'][0]['id'],
                                     'query': 'Python asynchronous documentation', 'limit': 3,
                                     'from_utc': datetime.fromtimestamp(time.time() - 86400, timezone.utc).isoformat().replace('+00:00', 'Z')}, owner)


def declaration(prepared, *, test=False):
    return {'proposal': copy.deepcopy(prepared['proposal']), 'signature': prepared['signature'], 'sharing_authority': True,
            'sharing_notice': TEST_SHARE_NOTICE if test else SHARE_NOTICE, 'run_authority': True,
            'run_notice': TEST_RUN_NOTICE if test else RUN_NOTICE}


def published(rt, owner):
    draft = candidate(rt, owner); tested = wait(rt, rt.publication.test(declaration(draft, test=True), owner))
    assert tested['status'] == 'succeeded', tested
    plan = rt.publication.publication_candidate({'run_id': tested['run_id'], 'ttl_seconds': 3600}, owner)
    release = rt.publication.publish({'proposal': plan['proposal'], 'signature': plan['signature'],
                                     'publication_authority': True, 'publication_notice': PUBLISH_NOTICE}, owner)
    return release, tested, draft, plan


def test_canonical_test_then_separate_publication_and_public_run(publication):
    rt, owner, routing = publication
    release, tested, draft, _ = published(rt, owner)
    assert routing[3] == ['primary.example', routing[3][1]] and len(routing[3]) == 2
    workflow = rt.store.get_workflow(tested['workflow_id'])
    assert public_template(workflow | {'is_template': 1}) is None
    assert rt.publication.public_list()['releases'][0]['id'] == release['id']
    routing[3].clear(); rt.typed_test_controls['seen'].clear()
    prepared = rt.publication.prepare_run(release['id'])
    assert prepared['preview']['source']['input']['from_utc'] == draft['preview']['source']['input']['from_utc']
    assert prepared['preview']['target']['settings'] == {'language': 'en', 'limit': 3}
    result = wait(rt, rt.publication.execute_run(release['id'], declaration(prepared)))
    assert result['status'] == 'succeeded', result
    assert len(routing[3]) == 2
    assert rt.typed_test_controls['seen'][1]['query'] == rt.typed_test_controls['title']
    key = rt.publication.execute_run(release['id'], declaration(prepared))['run_key']
    assert rt.publication.read_run(release['id'], result['run_id'], key)['status'] == 'succeeded'
    assert len(routing[3]) == 2
    assert not rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?', (result['run_id'],))


@pytest.mark.parametrize('title', ['/private/tmp/internal.txt', '/var/run/agent.sock', 'token=sample',
                                   'https://example.org', 'person@example.org', '<b>Title</b>', '{{call()}}',
                                   '', 'a' * 501, '[REDACTED]', 'Python\nprivate', ' Python title'])
def test_unsafe_future_title_never_calls_docs(publication, title):
    rt, owner, routing = publication; release, *_ = published(rt, owner)
    routing[3].clear(); rt.typed_test_controls['title'] = title
    result = wait(rt, rt.publication.execute_run(release['id'], declaration(rt.publication.prepare_run(release['id']))))
    assert result['status'] == 'failed' and routing[3] == ['primary.example']
    assert not rt.store.query("SELECT 1 FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-2'", (result['run_id'],))


@pytest.mark.parametrize('field,value', [('sharing_authority', False), ('sharing_authority', 1), ('run_authority', False),
                                       ('sharing_notice', TEST_SHARE_NOTICE), ('run_notice', TEST_RUN_NOTICE)])
def test_fresh_public_purpose_is_separate_from_private_test(publication, field, value):
    rt, owner, routing = publication; release, *_ = published(rt, owner); routing[3].clear()
    body = declaration(rt.publication.prepare_run(release['id'])); body[field] = value
    with pytest.raises(ValueError): rt.publication.execute_run(release['id'], body)
    assert not routing[3]


def test_unscoped_public_admin_and_legacy_deployment_cannot_execute_new_audience(publication):
    rt, owner, routing = publication; release, test, *_ = published(rt, owner); routing[3].clear()
    workflow = rt.store.get_workflow(test['workflow_id'])
    for args in ({'public': True}, {}, {'source': 'webapp'}):
        with pytest.raises(WorkflowError): rt.submit(workflow, **args)
    assert not routing[3]


def test_public_projection_has_no_graph_pin_owner_or_proof(publication):
    rt, owner, _ = publication; release, *_ = published(rt, owner)
    objects = [rt.publication.public_list(), rt.publication.public_projection(release['id']), rt.publication.prepare_run(release['id'])]
    for value in objects:
        encoded = json.dumps(value)
        for forbidden in ('primary.example', 'alternate.example', 'third.example', 'resource_id', 'version_id', 'owner', 'composition', 'workflow_id', 'test_run_id', 'checkpoint'):
            assert forbidden not in encoded


@pytest.mark.parametrize('change', ['revoked', 'controls', 'role', 'source_certainty', 'source_hash'])
def test_live_source_boundary_change_stops_documentation_dispatch(publication, change):
    from agent_market.execution_authority import controls, set_controls
    rt, owner, routing = publication; release, *_ = published(rt, owner); routing[3].clear()
    def mutate(_):
        if change == 'revoked': rt.publication.revoke(release['id'], release['revision'], owner)
        elif change == 'controls':
            for enabled in (False, True):
                current = controls(rt.store)
                set_controls(rt.store, {'invoke_enabled': enabled, 'workflow_enabled': True, 'delivery_enabled': current['delivery_enabled'], 'revision': current['revision']}, owner)
        elif change == 'role':
            with rt.store.tx() as db: db.execute("UPDATE admin_users SET role='operator' WHERE id=?", (owner,))
        else:
            original = rt.persistence.checkpoint
            def checkpoint(*args, **kwargs):
                result = original(*args, **kwargs)
                if args[3] == 'search-1':
                    with rt.store.tx() as db:
                        if change == 'source_certainty': db.execute("UPDATE workflow_execution_attempts SET status='unknown' WHERE run_id=? AND node_id='search-1'", (args[0],))
                        else: db.execute("UPDATE workflow_checkpoints SET signature='wrong' WHERE run_id=? AND node_id='search-1'", (args[0],))
                return result
            rt.persistence.checkpoint = checkpoint
    prepared = rt.publication.prepare_run(release['id']); routing[5]['primary.example'] = mutate
    result = wait(rt, rt.publication.execute_run(release['id'], declaration(prepared)))
    assert result['status'] != 'succeeded' and routing[3] == ['primary.example']


@pytest.mark.parametrize('change', ['attempt', 'authority', 'provenance', 'pruned'])
def test_original_certain_canonical_test_is_required_for_publication(publication, change):
    rt, owner, _ = publication; draft = candidate(rt, owner); tested = wait(rt, rt.publication.test(declaration(draft, test=True), owner))
    with rt.store.tx() as db:
        if change == 'attempt': db.execute("UPDATE workflow_execution_attempts SET status='unknown' WHERE run_id=? AND node_id='search-2'", (tested['run_id'],))
        elif change == 'authority': db.execute('DELETE FROM workflow_run_authority WHERE run_id=?', (tested['run_id'],))
        elif change == 'pruned': db.execute("DELETE FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'", (tested['run_id'],))
        else:
            record = json.loads(db.execute("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-2'", (tested['run_id'],)).fetchone()[0])
            record['typed_input']['source_checkpoint_hash'] = '0' * 64
            db.execute("UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=? AND node_id='search-2'", (json.dumps(record), rt.authority.signature(record), tested['run_id']))
    with pytest.raises(ValueError): rt.publication.publication_candidate({'run_id': tested['run_id'], 'ttl_seconds': 3600}, owner)


def test_expired_provider_evidence_or_pruned_proof_does_not_hide_accepted_outcome(publication):
    rt, owner, routing = publication; release, proof, *_ = published(rt, owner)
    prepared = rt.publication.prepare_run(release['id']); job = rt.publication.execute_run(release['id'], declaration(prepared)); wait(rt, job)
    with rt.store.tx() as db:
        db.execute('DELETE FROM workflow_checkpoints WHERE run_id=?', (proof['run_id'],))
        db.execute('UPDATE capability_evidence SET expires=0')
    assert rt.publication.read_run(release['id'], job['run_id'], job['run_key'])['status'] == 'succeeded'
    with pytest.raises(ValueError): rt.publication.prepare_run(release['id'])


def test_public_nonce_replay_cannot_be_rebound(publication):
    rt, owner, routing = publication; release, *_ = published(rt, owner)
    first = declaration(rt.publication.prepare_run(release['id'])); wait(rt, rt.publication.execute_run(release['id'], first))
    count = len(routing[3]); second = declaration(rt.publication.prepare_run(release['id']))
    second['proposal']['nonce'] = first['proposal']['nonce']; second['signature'] = rt.authority.signature(second['proposal'])
    with pytest.raises((ValueError, WorkflowError)): rt.publication.execute_run(release['id'], second)
    assert len(routing[3]) == count


def test_metadata_read_still_checks_retained_ticket_purpose_integrity(publication):
    rt, owner, _ = publication; release, *_ = published(rt, owner)
    job = rt.publication.execute_run(release['id'], declaration(rt.publication.prepare_run(release['id']))); wait(rt, job)
    with rt.store.tx() as db:
        value = json.loads(db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?', (job['run_id'],)).fetchone()[0])
        principal = value['principal']['payload']; principal['public_connection']['signature'] = 'invalid-inner-ticket-signature'
        value['principal']['signature'] = rt.authority.signature(principal)
        db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?', (json.dumps(value), rt.authority.signature(value), job['run_id']))
    with pytest.raises(ValueError): rt.publication.read_run(release['id'], job['run_id'], job['run_key'])


def test_new_release_capability_has_no_legacy_runtime_access(publication):
    rt, owner, _ = publication; release, *_ = published(rt, owner)
    body = declaration(rt.publication.prepare_run(release['id'])); job = rt.publication.execute_run(release['id'], body)
    wait(rt, job)
    assert not rt.authorized(job['run_id'], job['run_key'])
    assert rt.store.query('SELECT access_hash FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0] is None
    assert rt.publication.read_run(release['id'], job['run_id'], job['run_key'])['status'] == 'succeeded'
    rt.publication.revoke(release['id'], release['revision'], owner)
    with pytest.raises(ValueError): rt.publication.read_run(release['id'], job['run_id'], job['run_key'])


def test_canonical_test_expiry_is_not_extended_while_queued(publication, monkeypatch):
    rt, owner, routing = publication; draft = candidate(rt, owner)
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    job = rt.publication.test(declaration(draft, test=True), owner)
    authority = json.loads(rt.store.query('SELECT payload FROM workflow_run_authority WHERE run_id=?', (job['run_id'],))[0][0])
    assert authority['principal']['payload']['expires'] <= draft['proposal']['expires']
    expires = authority['principal']['payload']['expires']
    monkeypatch.setattr('agent_market.workflow_publication.time.time', lambda: expires + 1)
    rt._execute(job['run_id'])
    assert rt.get(job['run_id'])['status'] == 'failed' and not routing[3]


def test_candidate_and_ticket_are_stable_across_browser_numeric_roundtrip(publication, monkeypatch):
    rt, owner, _ = publication
    original = time.time()
    with monkeypatch.context() as patch:
        patch.setattr('agent_market.workflow_publication.time.time', lambda: float(int(original) + 1))
        draft = candidate(rt, owner)
    body = json.loads(json.dumps(declaration(draft, test=True)), parse_float=lambda value: int(float(value)) if float(value).is_integer() else float(value))
    assert rt.authority.signature(body['proposal']) == body['signature']
    # The whole-second fixture was authored just ahead of the real clock.
    # Admission correctly refuses a not-yet-created review; wait for its time.
    time.sleep(max(0, draft['proposal']['created'] - time.time()) + .005)
    tested = wait(rt, rt.publication.test(body, owner))
    assert tested['status'] == 'succeeded', tested


@pytest.mark.parametrize('authorization', [{}, {'publication_authority': False, 'publication_notice': PUBLISH_NOTICE},
                                          {'publication_authority': 1, 'publication_notice': PUBLISH_NOTICE},
                                          {'publication_authority': True, 'publication_notice': TEST_SHARE_NOTICE},
                                          {'publication_authority': True}])
def test_publication_requires_its_own_explicit_purpose(publication, authorization):
    rt, owner, _ = publication; draft = candidate(rt, owner)
    tested = wait(rt, rt.publication.test(declaration(draft, test=True), owner))
    plan = rt.publication.publication_candidate({'run_id': tested['run_id'], 'ttl_seconds': 3600}, owner)
    with pytest.raises(ValueError): rt.publication.publish({'proposal': plan['proposal'], 'signature': plan['signature'], **authorization}, owner)
    assert not rt.store.query('SELECT 1 FROM workflow_publication_grants')


@pytest.mark.parametrize('field', ['signature', 'status', 'input', 'time'])
def test_trigger_checkpoint_is_also_verified_for_publication(publication, field):
    rt, owner, _ = publication; draft = candidate(rt, owner)
    job = rt.publication.test(declaration(draft, test=True), owner); wait(rt, job)
    with rt.store.tx() as db:
        cp = json.loads(db.execute("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='start'", (job['run_id'],)).fetchone()[0])
        if field == 'status': cp['record']['status'] = 'failed'
        elif field == 'input': cp['record']['input'] = {'extra': 'not-reviewed'}
        elif field == 'time': cp['record']['started'] = True
        db.execute("UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=? AND node_id='start'",
                   (json.dumps(cp), 'wrong' if field == 'signature' else rt.authority.signature(cp), job['run_id']))
    with pytest.raises(ValueError): rt.publication.publication_candidate({'run_id': job['run_id'], 'ttl_seconds': 3600}, owner)


CHILD = r'''
import json,os,signal,sys,httpx
from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
from agent_market.concierge.proxy import McpProxy
from tests.test_mcp_proxy import MockRemoteMcp
from tests.test_workflow_fallback import tool,output
path,run_id,audit,phase=sys.argv[1:]
remote=MockRemoteMcp([tool()],call_result=output());original=remote.handle_request
def die():os.kill(os.getpid(),signal.SIGKILL)
def handle(request):
 body=json.loads(request.content or '{}');news=request.url.host=='primary.example'
 remote.tools=[tool('news.search.v1') if news else tool()]
 if body.get('method')=='tools/call':
  with open(audit,'a') as out:out.write(request.url.host+'\n');out.flush();os.fsync(out.fileno())
  if phase=='docs-dispatched' and not news:die()
  remote.call_result=output('news.search.v1' if news else 'docs.search.v1')
 return original(request)
remote.handle_request=handle
store=Store(path);client=httpx.Client(transport=remote)
runtime=WorkflowRuntime(store,McpProxy(store,allow_private=True,http=client))
if phase=='source-checkpoint':
 checkpoint=runtime.persistence.checkpoint
 def saved(*args,**kwargs):
  result=checkpoint(*args,**kwargs)
  if args[3]=='search-1':die()
  return result
 runtime.persistence.checkpoint=saved
runtime._execute(run_id)
raise SystemExit('Expected crash boundary was not reached')
'''


@pytest.mark.parametrize('phase', ['source-checkpoint', 'docs-dispatched'])
def test_real_sigkill_public_scope_recovery_never_repeats_an_external_dispatch(publication, monkeypatch, tmp_path, phase):
    rt, owner, routing = publication; release, *_ = published(rt, owner); routing[3].clear()
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    body = declaration(rt.publication.prepare_run(release['id'])); job = rt.publication.execute_run(release['id'], body)
    audit = tmp_path / 'calls.txt'
    child = subprocess.run([sys.executable, '-B', '-c', CHILD, rt.store._path, job['run_id'], str(audit), phase], capture_output=True, timeout=15)
    assert child.returncode == -signal.SIGKILL, child.stderr.decode()[-1600:]
    before = audit.read_text().splitlines(); deadline = rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0]
    with rt.store.tx() as db: db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?', (job['run_id'],))
    rt.persistence.recover(); rt._execute(job['run_id']); result = rt.get(job['run_id'])
    if phase == 'source-checkpoint':
        assert before == ['primary.example'] and len(routing[3]) == 1 and routing[3][0] != 'primary.example'
        assert result['status'] == 'succeeded', result
    else:
        assert len(before) == 2 and not routing[3]
        assert result['status'] == 'failed' and result['execution_outcome'] == 'unknown'
        for _ in range(2): rt.persistence.recover(); rt._execute(job['run_id'])
        assert not routing[3]
    assert len(before) + len(routing[3]) == 2
    assert rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0] == deadline

"""Private controllers exercise actual mock-transport calls, never external I/O."""
import base64
from copy import deepcopy
import hashlib
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from agent_market.capability_registry import digest
from agent_market.reliability_automation import CircuitAutomation, NOTICE as AUTO_NOTICE
from agent_market.reliability_early_stop import ReliabilityEarlyStop, NOTICE as STOP_NOTICE, PAIR_NOTICE
from agent_market.reliability_judges import JudgeConfig, SignedIndependentJudge, PROFILE as JUDGE_PROFILE
from agent_market.reliability_portable_receipt import SigningConfig, verify
from agent_market.reliability_publication import ReliabilityPublication, NOTICE as PUBLIC_NOTICE
from agent_market.reliability_research import ReliabilityResearch
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical
from tests.test_reliability_controls import controls, private_api, setup_plan, plan, post
from tests.test_reliability_circuit import circuit, config as circuit_config
from tests.test_reliability_evaluation_worker import worker_world
from tests.test_reliability_research import configured, manifest
from tests.test_workspace_remote_a2a import remote, command as task_command
from tests.test_workspace_reliability import reliability, setup, sample, report


def stop_policy(x, **changes):
    return {'revision': 0, 'resource_id': x.w.remote_rid, 'version_id': x.version['id'], 'enabled': True,
            'max_elapsed_seconds': 60, 'max_polls': 1, 'expires': time.time()+600,
            'authorized': True, 'notice': STOP_NOTICE, **changes}


def stopping(x):
    core = ReliabilityEarlyStop(x.core.access, x.core, enabled=True)
    core.configure(x.w.ws['id'], stop_policy(x), x.actor)
    task = x.core.send(x.w.ws['id'], task_command(x), x.actor)
    watch = core.watch(x.w.ws['id'], {'task_id': task['id'], 'policy_revision': 1, 'opt_in': True,
                        'authorized': True, 'notice': STOP_NOTICE}, x.actor)
    return core, task, watch


def advance(x, core, watch):
    return core.advance(x.w.ws['id'], watch['id'], {'revision': watch['revision'],
                         'authorized': True, 'notice': STOP_NOTICE}, x.actor)


def test_early_stop_executes_real_cancel_after_bound_poll_and_never_replays(remote):
    x = remote; core, task, watch = stopping(x)
    watch = advance(x, core, watch)
    assert watch['state'] == 'watching' and watch['polls'] == 1 and watch['actual_interventions'] == 0
    x.control['state'] = 'canceled'
    stopped = advance(x, core, watch)
    assert stopped['state'] == 'stopped' and stopped['remote_cancel_confirmed']
    assert stopped['actual_interventions'] == 1 and stopped['reason'] == 'poll_limit'
    assert advance(x, core, stopped) == stopped
    assert [c['method'] for c in x.calls] == ['message/send', 'tasks/get', 'tasks/cancel']
    assert stopped['false_stop_rate'] is stopped['successful_outcome_loss'] is None
    assert not stopped['quality_promotion_eligible']


@pytest.mark.parametrize('outcome', ['completed', 'timeout'])
def test_late_completion_or_cancel_response_loss_never_claims_confirmed_stop(remote, outcome):
    x = remote; core, task, watch = stopping(x); watch = advance(x, core, watch)
    x.control['state'] = 'completed'; x.control['timeout'] = outcome == 'timeout'
    result = advance(x, core, watch)
    assert result['state'] == ('completed' if outcome == 'completed' else 'unknown')
    assert result['late_result'] == (outcome == 'completed')
    assert not result['remote_cancel_confirmed']
    assert advance(x, core, result) == result and len(x.calls) == 3


def test_opt_in_default_off_and_policy_withdrawal_block_packet(remote):
    x = remote; disabled = ReliabilityEarlyStop(x.core.access, x.core)
    with pytest.raises(WorkspaceConflict):
        disabled.configure(x.w.ws['id'], stop_policy(x), x.actor)
    core, task, watch = stopping(x)
    with pytest.raises(WorkspaceInvalid):
        core.watch(x.w.ws['id'], {'task_id': task['id'], 'policy_revision': 1, 'opt_in': False,
                   'authorized': True, 'notice': STOP_NOTICE}, x.actor)
    original = x.core.command
    def withdraw(*args, **kwargs):
        core.configure(x.w.ws['id'], stop_policy(x, revision=1, enabled=False), x.actor)
        return original(*args, **kwargs)
    x.core.command = withdraw
    result = advance(x, core, watch)
    assert result['state'] == 'unknown' and len(x.calls) == 1


def test_durable_dispatch_barrier_survives_controller_restart(remote):
    x = remote; core, task, watch = stopping(x)
    with x.w.store.tx() as db:
        value = core._load(db, x.w.ws['id'], watch['id']); value['state'] = 'dispatched'; core._save(db, value)
    rebuilt = ReliabilityEarlyStop(x.core.access, x.core, enabled=True)
    result = advance(x, rebuilt, watch)
    assert result['reconciliation_required'] and len(x.calls) == 1


def test_early_stop_worker_drives_real_poll_cancel_and_restart_requires_fresh_watch(remote):
    x = remote; core, task, watch = stopping(x)
    replacement = ReliabilityEarlyStop(x.core.access, x.core, enabled=True)
    assert replacement.tick() == {'advanced': 0} and len(x.calls) == 1
    assert core.tick() == {'advanced': 1}
    x.control['state'] = 'canceled'
    assert core.tick() == {'advanced': 1}
    assert core.status(x.w.ws['id'], x.actor)['runs'][0]['remote_cancel_confirmed']
    assert core.tick() == {'advanced': 0} and len(x.calls) == 3
    assert core.close() and replacement.close()


def auto(w, monkeypatch):
    monkeypatch.setattr('agent_market.reliability_automation.clock', lambda: w.now)
    w.circuit.configure(w.ws['id'], circuit_config(w), w.actor)
    setup_plan(w)
    automation = CircuitAutomation(w.circuit, enabled=True)
    automation.activate(w.ws['id'], {'plan_revision': 1, 'max_probes': 1, 'expires': w.now+1800,
                        'authorized': True, 'notice': AUTO_NOTICE}, w.actor)
    w.worker.circuit_automation = automation
    w.worker.activate(w.ws['id'], w.actor, 1)
    return automation


def test_worker_automatically_ingests_failures_and_binds_separately_approved_probe(circuit, monkeypatch):
    w = circuit; automation = auto(w, monkeypatch)
    w.eval_control['mode'] = 'tool_error'; w.worker.tick()
    assert w.circuit.status(w.ws['id'], w.rids[0], w.actor)['circuit']['state'] == 'open'
    w.now = (int(w.now//600)+1)*600+1; w.eval_control['mode'] = 'ok'
    w.worker.tick()
    current = w.circuit.status(w.ws['id'], w.rids[0], w.actor)['circuit']
    assert current['state'] == 'closed' and current['reason'] == 'verified_probe_response'
    assert automation.status(w.ws['id'], w.actor)['remaining_probes'] == 0
    assert w.eval_calls.count('tools/call') == 2
    w.worker.tick(); assert w.eval_calls.count('tools/call') == 2


def test_automatic_activation_has_no_implicit_restart_or_budget_increase(circuit, monkeypatch):
    w = circuit; automation = auto(w, monkeypatch)
    assert CircuitAutomation(w.circuit, enabled=True).status(w.ws['id'], w.actor)['active'] is False
    with pytest.raises(WorkspaceInvalid):
        automation.activate(w.ws['id'], {'plan_revision': 1, 'max_probes': 11, 'expires': w.now+100,
                            'authorized': True, 'notice': AUTO_NOTICE}, w.actor)
    w.worker.deactivate(w.ws['id'])
    assert not automation.status(w.ws['id'], w.actor)['active'] and not w.eval_calls


def test_adaptive_resource_priority_rotates_shared_host_without_changing_budget(worker_world, monkeypatch):
    w = worker_world
    monkeypatch.setattr('agent_market.reliability_research.clock', lambda: w.now)
    w.research = ReliabilityResearch(w.access, w.evaluation)
    # Register via the core; existing corpus/host limits remain authoritative.
    approved = w.research.register_manifest(w.ws['id'], manifest(w, adaptive_priority=True), w.actor)
    w.evaluation.configure_plan(w.ws['id'], plan(w, corpus_id=approved['corpus_id'],
                               resource_ids=[w.rids[0], w.rids[2]], per_host_budget=1), w.actor)
    from agent_market.reliability_evaluation import NOTICE
    w.evaluation.set_control(w.ws['id'], {'revision': 0, 'enabled': True, 'authorized': True, 'notice': NOTICE}, w.actor)
    w.worker.activate(w.ws['id'], w.actor, 1); w.worker.tick()
    first = w.evaluation.status(w.ws['id'], w.actor)['jobs'][0]
    w.now = (int(w.now//600)+1)*600+1
    w.worker.tick()
    jobs = w.evaluation.status(w.ws['id'], w.actor)['jobs']
    second = next(j for j in jobs if j['window_start'] > first['window_start'])
    assert first['resource_id'] != second['resource_id']
    assert len(jobs) == 2 and w.eval_calls.count('tools/call') == 2


def publication(w):
    key = Ed25519PrivateKey.generate()
    config = SigningConfig('https://trust.test', 'first', key, ('agent-client',))
    w.sources[w.rids[0]]['environment'] = 'approved_external'
    registry = ReliabilityPublication(w.access, w.trust, configs=(config,), enabled=True)
    registry.publish_key(w.ws['id'], {'revision': 0, 'issuer': config.issuer, 'key_id': 'first',
            'revoked': False, 'expires': time.time()+600, 'authorized': True, 'notice': PUBLIC_NOTICE}, w.actor)
    body = {'revision': 0, 'resource_id': w.rids[0], 'public_ref': 'public_'+'d'*32,
            'audiences': ['agent-client'], 'expires': time.time()+600, 'withdrawn': False,
            'authorized': True, 'notice': PUBLIC_NOTICE}
    registry.disclose(w.ws['id'], body, w.actor)
    return registry, config, body


def test_concrete_publication_serves_verifiable_receipt_and_withdrawal_is_immediate(controls):
    w = controls; registry, config, body = publication(w)
    with TestClient(registry.create_app(config.issuer, config.key_id, allowed_hosts=('trust.test',)),
                    base_url='https://trust.test') as client:
        response = client.get('/v1/receipts/'+body['public_ref']+'?audience=agent-client')
        assert response.status_code == 200, response.text
        value = response.json()
        result = verify(_canonical(value['receipt']).encode('ascii'), value['signature'],
            trusted_keys={'first': config.private_key.public_key()}, issuer=config.issuer, audience='agent-client')
        assert result['signature_verified'] and not result['business_completion_verified']
        assert client.get('/.well-known/jwks.json').json()['keys'][0]['kid'] == 'first'
        registry.disclose(w.ws['id'], body | {'revision': 1, 'withdrawn': True}, w.actor)
        assert client.get('/v1/receipts/'+body['public_ref']+'?audience=agent-client').status_code == 404
        with pytest.raises(WorkspaceConflict):
            registry.disclose(w.ws['id'], body | {'revision': 2}, w.actor)
        assert 'PRIVATE' not in response.text and 'session_ref' not in response.text


@pytest.mark.parametrize('change', ['source', 'membership', 'key'])
def test_concrete_publication_rechecks_live_source_authority_and_revocation(controls, change):
    w = controls; registry, config, body = publication(w)
    if change == 'source': w.sources[w.rids[0]]['source_revision'] = 'f'*64
    elif change == 'membership':
        with w.store.tx() as db: db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?', (w.ws['id'],))
    else:
        registry.publish_key(w.ws['id'], {'revision': 1, 'issuer': config.issuer, 'key_id': 'first',
            'revoked': True, 'expires': time.time()+600, 'authorized': True, 'notice': PUBLIC_NOTICE}, w.actor)
    with TestClient(registry.create_app(config.issuer, config.key_id, allowed_hosts=('trust.test',)), base_url='https://trust.test') as client:
        response = client.get('/v1/receipts/'+body['public_ref']+'?audience=agent-client')
        assert response.status_code == 404
        if change == 'key': assert client.get('/.well-known/jwks.json').json()['keys'] == []


@pytest.mark.parametrize('bad', ['signature', 'nonce', 'binding', 'independence', 'expiry', 'extra'])
def test_signed_judge_rejects_unbound_or_forged_remote_result(controls, bad):
    w = controls; secret = Ed25519PrivateKey.generate()
    config = JudgeConfig('https://judge.test/assess', 'judge-key', secret.public_key(), 'judge-v1',
                         'independent-read-evaluation', 'a'*64)
    bundle = {'input': {'query': 'Public documentation'}, 'output': {'items': []}}
    binding = {'evaluator_version': 'judge-v1', 'bundle_hash': digest(bundle), 'environment': 'approved_external'}
    def transport(request):
        value = json.loads(request.content); now = time.time()
        payload = {'profile': JUDGE_PROFILE, 'purpose': config.purpose, 'key_id': config.key_id,
            'nonce': value['nonce'], 'binding_hash': digest(value['binding']), 'independence_hash': config.independence_hash,
            'qualification_hash': 'b'*64, 'issued_at': now, 'expires': now+120, 'evaluator_id': config.evaluator_id,
            'quality': 'passed', 'source_fidelity': 'verified', 'reviewer_count': 1, 'reviewer_agreement': None}
        if bad == 'nonce': payload['nonce'] = '0'*64
        elif bad == 'binding': payload['binding_hash'] = '0'*64
        elif bad == 'independence': payload['independence_hash'] = '0'*64
        elif bad == 'expiry': payload['expires'] = now-1
        elif bad == 'extra': payload['email'] = 'not-permitted@example.test'
        signer = Ed25519PrivateKey.generate() if bad == 'signature' else secret
        signature = base64.urlsafe_b64encode(signer.sign(_canonical(payload).encode('ascii'))).rstrip(b'=').decode('ascii')
        return httpx.Response(200, json={'payload': payload, 'signature': signature})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = SignedIndependentJudge(w.store, config, http=client)
        with pytest.raises(WorkspaceDenied): adapter(binding, bundle)


def test_signed_judge_real_protocol_roundtrip_and_transaction_fence(controls):
    w = controls; key = Ed25519PrivateKey.generate(); calls = []
    config = JudgeConfig('https://judge.test/qualify', 'judge-key', key.public_key(), 'judge-v1',
                         'operating-read-routing', 'a'*64)
    binding = {'source_environment': 'approved_external', 'source_hash': 'c'*64}
    def transport(request):
        value = json.loads(request.content); calls.append(value); now = time.time()
        payload = {'profile': JUDGE_PROFILE, 'purpose': config.purpose, 'key_id': config.key_id, 'nonce': value['nonce'],
            'binding_hash': digest(value['binding']), 'independence_hash': config.independence_hash, 'qualification_hash': 'b'*64,
            'issued_at': now, 'expires': now+120, 'evaluator_id': config.evaluator_id, 'approved': True, 'approval_hash': 'd'*64}
        signature = base64.urlsafe_b64encode(key.sign(_canonical(payload).encode('ascii'))).rstrip(b'=').decode('ascii')
        return httpx.Response(200, json={'payload': payload, 'signature': signature})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = SignedIndependentJudge(w.store, config, http=client)
        result = adapter(binding)
        assert result.binding_hash == digest(binding) and len(calls) == 1
        with w.access._tx(w.actor, write=True):
            with pytest.raises(WorkspaceConflict): adapter(binding)
        assert len(calls) == 1


def test_signed_independent_evaluator_connects_real_retained_sources_to_current_report(reliability):
    w = setup(reliability, environment='approved_external'); sample(w); sample(w)
    key = Ed25519PrivateKey.generate(); calls = []
    config = JudgeConfig('https://judge.test/evaluate', 'judge-key', key.public_key(), 'trusted-evaluator-v1',
                         'independent-read-evaluation', '5'*64)
    def transport(request):
        value = json.loads(request.content); calls.append(value); now = time.time()
        assert not w.store._db.in_transaction
        assert digest(value['bundle']) == value['binding']['bundle_hash']
        payload = {'profile': JUDGE_PROFILE, 'purpose': config.purpose, 'key_id': config.key_id,
            'nonce': value['nonce'], 'binding_hash': digest(value['binding']), 'independence_hash': config.independence_hash,
            'qualification_hash': '4'*64, 'issued_at': now, 'expires': now+120, 'evaluator_id': config.evaluator_id,
            'quality': 'passed', 'source_fidelity': 'verified', 'reviewer_count': 1, 'reviewer_agreement': None}
        signature = base64.urlsafe_b64encode(key.sign(_canonical(payload).encode('ascii'))).rstrip(b'=').decode('ascii')
        return httpx.Response(200, json={'payload': payload, 'signature': signature})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        w.plane.evaluator = SignedIndependentJudge(w.store, config, http=client)
        result = report(w)
        assert result.status_code == 200 and len(calls) == 2
        assert w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)['independent_qualified']
        assert len(calls) == 2  # Transaction-time projection uses the local cache.


@pytest.fixture
def paired_stop(remote):
    x = remote; calls = []; states = {}; count = [0]; quality = {'baseline': 'passed', 'intervention': 'failed'}
    config = JudgeConfig('https://judge.test/pair', 'pair-key', Ed25519PrivateKey.generate().public_key(),
                         'pair-judge-v1', 'independent-read-evaluation', 'e'*64)
    signing = Ed25519PrivateKey.generate()
    config = JudgeConfig(config.endpoint, config.key_id, signing.public_key(), config.evaluator_id, config.purpose, config.independence_hash)
    control = {'cancel_artifact': False, 'withdraw': None}
    def transport(request):
        body = json.loads(request.content)
        if request.url.host == 'judge.test':
            assert not x.w.store._db.in_transaction
            calls.append('judge:'+body['binding']['arm']); now = time.time()
            payload = {'profile': JUDGE_PROFILE, 'purpose': config.purpose, 'key_id': config.key_id,
                'nonce': body['nonce'], 'binding_hash': digest(body['binding']), 'independence_hash': config.independence_hash,
                'qualification_hash': 'f'*64, 'issued_at': now, 'expires': now+120, 'evaluator_id': config.evaluator_id,
                'quality': quality[body['binding']['arm']], 'source_fidelity': 'verified',
                'reviewer_count': 1, 'reviewer_agreement': None}
            if control['withdraw']: control['withdraw']()
            signature = base64.urlsafe_b64encode(signing.sign(_canonical(payload).encode())).rstrip(b'=').decode()
            return httpx.Response(200, json={'payload': payload, 'signature': signature})
        method = body['method']; calls.append(method)
        if method == 'message/send':
            count[0] += 1; identity = 'independent-fixture-'+str(count[0]); states[identity] = 'working'
        else:
            identity = body['params']['id']
            if method == 'tasks/cancel': states[identity] = 'canceled'
        task = {'kind': 'task', 'id': identity, 'status': {'state': states[identity]}}
        if task['status']['state'] == 'completed' or task['status']['state'] == 'canceled' and control['cancel_artifact']:
            task['artifacts'] = [{'artifactId': 'bounded', 'parts': [{'kind': 'text', 'text': 'Actual bounded fixture output'}]}]
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': task})
    original = x.core.bindings[x.w.remote_rid].client.http
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        x.core.bindings[x.w.remote_rid].client.http = http
        core = ReliabilityEarlyStop(x.core.access, x.core, enabled=True,
            comparator=SignedIndependentJudge(x.w.store, config, http=http), environment='approved_external', minimum_pairs=1)
        core.configure(x.w.ws['id'], stop_policy(x), x.actor)
        intervention = x.core.send(x.w.ws['id'], task_command(x), x.actor)
        baseline = x.core.send(x.w.ws['id'], task_command(x) | {'logical_id': 'rat_'+'b'*32}, x.actor)
        watch = core.watch(x.w.ws['id'], {'task_id': intervention['id'], 'policy_revision': 1,
            'opt_in': True, 'authorized': True, 'notice': STOP_NOTICE}, x.actor)
        yield x, core, baseline, watch, calls, states, quality, control
        core.close(); x.core.bindings[x.w.remote_rid].client.http = original


def pair(x, core, baseline, watch):
    return core.pair(x.w.ws['id'], watch['id'], {'revision': watch['revision'], 'baseline_task_id': baseline['id'],
                'authorized': True, 'notice': PAIR_NOTICE}, x.actor)


def finish_pair(x, core, baseline, watch, states):
    states['independent-fixture-2'] = 'completed'
    from agent_market.workspace_remote_a2a import NOTICE
    x.core.command(x.w.ws['id'], baseline['id'], {'revision': baseline['revision'], 'action': 'poll',
                      'authorized': True, 'notice': NOTICE}, x.actor)
    watch = advance(x, core, watch); return advance(x, core, watch)


def test_precommitted_comparison_keeps_missing_canceled_output_unassessed_and_blocks_promotion(paired_stop):
    x, core, baseline, watch, calls, states, quality, control = paired_stop
    watch = pair(x, core, baseline, watch)
    assert core.comparison_report(x.w.ws['id'], x.actor)['unknown_or_unassessed_pairs'] == 1
    watch = finish_pair(x, core, baseline, watch, states)
    result = core.assess_pair(x.w.ws['id'], watch['id'], {'revision': watch['revision'],
                      'authorized': True, 'notice': PAIR_NOTICE}, x.actor)
    assert result['outcomes'] == ['passed', 'canceled_unassessed'] and not result['assessed']
    report = core.comparison_report(x.w.ws['id'], x.actor)
    assert report['false_stop_rate'] is report['successful_outcome_loss'] is None
    assert report['confirmed_stop_baseline_pass_fraction'] == 1 and not report['quality_promotion_eligible']
    assert calls.count('judge:baseline') == 1 and 'judge:intervention' not in calls
    assert calls.count('message/send') == 2


def test_independently_assessed_full_artifacts_bind_quality_metrics_and_current_promotion_guard(paired_stop):
    x, core, baseline, watch, calls, states, quality, control = paired_stop
    control['cancel_artifact'] = True; quality.update(baseline='failed', intervention='failed')
    watch = pair(x, core, baseline, watch); watch = finish_pair(x, core, baseline, watch, states)
    result = core.assess_pair(x.w.ws['id'], watch['id'], {'revision': watch['revision'],
                      'authorized': True, 'notice': PAIR_NOTICE}, x.actor)
    assert result['assessed'] and result['outcomes'] == ['failed', 'failed']
    report = core.comparison_report(x.w.ws['id'], x.actor)
    assert report['assessed_pairs'] == 1 and report['false_stop_rate'] == report['successful_outcome_loss'] == 0
    assert report['quality_promotion_eligible'] and not report['public_activation']
    core.comparator = None
    assert not core.comparison_report(x.w.ws['id'], x.actor)['quality_promotion_eligible']


def test_pairing_after_intervention_or_with_wrong_purpose_is_rejected(paired_stop):
    x, core, baseline, watch, calls, states, quality, control = paired_stop
    with pytest.raises(WorkspaceInvalid):
        core.pair(x.w.ws['id'], watch['id'], {'revision': watch['revision'], 'baseline_task_id': baseline['id'],
                   'authorized': True, 'notice': STOP_NOTICE}, x.actor)
    watch = advance(x, core, watch)
    with pytest.raises(WorkspaceConflict): pair(x, core, baseline, watch)
    assert not any(c.startswith('judge:') for c in calls)


def test_late_independent_assessment_cannot_commit_withdrawn_policy(paired_stop):
    x, core, baseline, watch, calls, states, quality, control = paired_stop
    watch = pair(x, core, baseline, watch); watch = finish_pair(x, core, baseline, watch, states)
    control['withdraw'] = lambda: core.configure(x.w.ws['id'], stop_policy(x, revision=1, enabled=False), x.actor)
    with pytest.raises(WorkspaceConflict):
        core.assess_pair(x.w.ws['id'], watch['id'], {'revision': watch['revision'],
                           'authorized': True, 'notice': PAIR_NOTICE}, x.actor)
    with x.w.store.tx() as db:
        assert core._load(db, x.w.ws['id'], watch['id'])['assessment'] is None

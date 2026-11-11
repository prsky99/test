"""Isolated dispatch, quota, privacy and fallback security contracts."""
import base64
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import secrets
import time
from types import SimpleNamespace

import httpx
import pytest

from agent_market.capability_registry import Registry
from agent_market.edge_gateway.auth import canonical, derived, service_mac, verify_ticket
from agent_market.edge_gateway.config import Config, EdgeError, PROFILE, load
from agent_market.edge_gateway.monitor import Monitor
from agent_market.edge_gateway.service import Service, day_at
from agent_market.edge_gateway.state import execute, host_control, migrate, ready, rows, transaction
from tests.test_fast_single_recommendation import catalog

ORIGIN = 'https://agentconcierge.biz'


@pytest.fixture
def edge(catalog, monkeypatch):
    store, front, client, add, now = catalog
    resource_id = add('Stream Agent', kind='a2a')
    endpoint = store.resource(resource_id)['url']
    version = Registry(store).current(resource_id)['id']
    config = Config.from_dict({'profile': PROFILE, 'public_origin': ORIGIN, 'shared_secret': base64.b64encode(b'e' * 32).decode(),
        'worker_ready': True, 'providers': [{'resource_id': resource_id, 'version_id': version, 'endpoint': endpoint,
            'privacy_reviewed': True, 'origin_compatible': True, 'free_cpu_verified': True}]})
    front.courier.resolve = lambda *_args, **_kw: {'url': endpoint, 'v1': False}
    checks, calls = [], []
    monkeypatch.setattr('agent_market.edge_gateway.service.validate_public_url', lambda url: checks.append(url))
    front.security.allow_probe = lambda *_args, **_kw: True
    def provider(method, url, limit, **kwargs):
        calls.append((method, url, kwargs))
        return 200, json.dumps({'jsonrpc': '2.0', 'id': kwargs['json']['id'], 'result': {
            'kind': 'message', 'parts': [{'kind': 'text', 'text': 'Endpoint ' + endpoint + '; source https://news.example/article'}]}}).encode()
    front.courier._request = provider
    migrate(store)
    clock = [time.time()]
    service = Service(front, config, clock=lambda: clock[0])
    service.observe(0, clock[0], healthy=True)
    front.edge_gateway = service
    store._edge_gateway_service = service
    visitor = client.post('/chat', json={'message': 'find an A2A weather agent'}).json()['visitor']['token']
    principal = service.principal(visitor)
    return SimpleNamespace(store=store, front=front, client=client, service=service, config=config,
                           rid=resource_id, endpoint=endpoint, clock=clock, token=visitor,
                           principal=principal, calls=calls, checks=checks)


def proposal(edge, key=None):
    return {'resource_id': edge.rid, 'input': {'message': 'What is the weather in Tokyo?'},
            'idempotency_key': key or secrets.token_hex(12), 'run_authority': True, 'sharing_authority': True}


def prepare(edge, value=None):
    response = edge.client.post('/api/gateway-execution/v1/runs', json=value or proposal(edge),
                               headers={'Origin': ORIGIN, 'X-Visitor-Token': edge.token})
    assert response.status_code == 200, response.text
    return response.json()


def service_request(edge, operation, value, nonce=None):
    raw = canonical(value).encode()
    path = '/api/edge-gateway-internal/v1/' + operation
    timestamp, identity = str(int(edge.clock[0])), nonce or secrets.token_hex(16)
    return edge.client.post(path, content=raw, headers={'Content-Type': 'application/json', 'X-Edge-Time': timestamp,
        'X-Edge-Nonce': identity, 'X-Edge-Signature': service_mac(edge.config.key, 'POST', path, timestamp, identity, raw)})


def claim(edge, grant, value, backend='worker'):
    return edge.service.claim(grant['access_token'], ORIGIN, grant['run_id'], value['input'], backend)


def test_prepare_pins_input_and_hides_every_private_binding(edge):
    value = proposal(edge)
    grant = prepare(edge, value)
    assert grant['stream_path'].startswith('/api/edge-gateway/')
    public = json.dumps(grant)
    assert edge.endpoint not in public and edge.token not in public and base64.b64encode(edge.config.key).decode() not in public
    token = verify_ticket(edge.config.key, grant['access_token'], ORIGIN, now=edge.clock[0])
    assert set(token) == {'aud', 'run', 'origin', 'exp'} and token['run'] == grant['run_id']
    again = prepare(edge, value)
    assert again['run_id'] == grant['run_id'] and not edge.calls


def set_request_mode(edge, mode):
    edge.service.config = replace(edge.config, providers=(replace(edge.config.providers[0], request_mode=mode),))


def test_json_mode_selects_blocking_send_and_pins_method_before_dispatch(edge):
    set_request_mode(edge, 'json')
    value = proposal(edge); grant = prepare(edge, value)
    binding = claim(edge, grant, value)
    assert binding['request_mode'] == 'json'
    assert binding['request']['method'] == 'message/send'
    assert binding['request']['params']['configuration'] == {'blocking': True}
    assert binding['request']['id'] == binding['attempt_id']
    assert not edge.calls


def test_method_change_after_prepare_requires_new_authorization(edge):
    value = proposal(edge); grant = prepare(edge, value)
    set_request_mode(edge, 'json')
    with pytest.raises(EdgeError) as changed: claim(edge, grant, value)
    assert changed.value.code == 'INPUT_CHANGED'
    with pytest.raises(EdgeError) as reused: edge.service.prepare(edge.principal, ORIGIN, value)
    assert reused.value.code == 'IDEMPOTENCY_CONFLICT'
    assert edge.service.status(edge.principal, grant['run_id'])['state'] == 'prepared'
    assert not edge.calls


def test_canary_admits_only_the_operator_principal_and_denies_old_unscoped_tickets(edge):
    value = proposal(edge); old = prepare(edge, value)
    edge.service.config = replace(edge.config, canary_principal='a' * 64)
    with pytest.raises(EdgeError): edge.service.prepare(edge.principal, ORIGIN, proposal(edge))
    with pytest.raises(EdgeError): claim(edge, old, value)
    grant = edge.service.prepare('a' * 64, ORIGIN, proposal(edge))
    binding = edge.service.claim(grant['access_token'], ORIGIN, grant['run_id'], value['input'], 'worker')
    assert binding['attempt_id'] and not edge.calls


def test_signed_public_bridge_prepares_approved_requests_and_preserves_origin_for_other_resources(edge):
    body = {'resource_id': edge.rid, 'input': {'message': 'What is the weather in Tokyo?'},
            'origin': ORIGIN, 'idempotency_key': 'public-bridge-01'}
    assert edge.client.post('/api/edge-gateway-internal/v1/public-prepare', json=body).status_code == 401
    accepted = service_request(edge, 'public-prepare', body)
    assert accepted.status_code == 200 and accepted.json()['backend'] == 'worker'
    assert 'endpoint' not in accepted.json()
    assert accepted.json()['binding']['endpoint'] == edge.endpoint
    with transaction(edge.store, readonly=True) as db:
        assert rows(db, 'run', (accepted.json()['run_id'],))[0]['state'] == 'dispatch_reserved'
    other = service_request(edge, 'public-prepare', {**body, 'resource_id': edge.rid + 1})
    assert other.json() == {'backend': 'origin'}
    edge.service.config = replace(edge.config, canary_principal='a' * 64)
    assert service_request(edge, 'public-prepare', body).json() == {'backend': 'origin'}
    assert not edge.calls


def test_safe_diagnostic_receipts_are_persisted_but_arbitrary_text_is_rejected(edge):
    value = proposal(edge); grant = prepare(edge, value); binding = claim(edge, grant, value)
    done = {'run_id': grant['run_id'], 'attempt_id': binding['attempt_id'], 'outcome': 'failed',
            'outcome_code': 'PROVIDER_METHOD_UNSUPPORTED'}
    assert service_request(edge, 'complete', {**done, 'outcome_code': edge.endpoint}).status_code == 400
    assert service_request(edge, 'complete', {**done, 'outcome': 'succeeded'}).status_code == 400
    assert service_request(edge, 'complete', done).status_code == 200
    assert service_request(edge, 'complete', done).status_code == 200
    assert service_request(edge, 'complete', {**done, 'outcome_code': 'EXECUTION_FAILED'}).status_code == 409
    status = edge.service.status(edge.principal, grant['run_id'])
    assert status['error_code'] == done['outcome_code'] and 'stream_path' not in status


@pytest.mark.parametrize('change', ['run-authority', 'sharing-authority', 'pii', 'action', 'extra-field', 'resource', 'protocol-version'])
def test_admission_fails_before_any_provider_dispatch(edge, change):
    value = proposal(edge)
    if change == 'run-authority': value['run_authority'] = False
    if change == 'sharing-authority': value['sharing_authority'] = False
    if change == 'pii': value['input']['message'] = 'Look up personal@example.com'
    if change == 'action': value['input']['message'] = 'delete the account'
    if change == 'extra-field': value['endpoint'] = 'http://127.0.0.1/private'
    if change == 'resource': value['resource_id'] = True
    if change == 'protocol-version':
        with edge.store.tx() as db: db.execute('UPDATE resources SET active=0 WHERE id=?', (edge.rid,))
    response = edge.client.post('/api/gateway-execution/v1/runs', json=value,
                               headers={'Origin': ORIGIN, 'X-Visitor-Token': edge.token})
    assert response.status_code in (400, 403, 409)
    assert not edge.calls and edge.endpoint not in response.text


def test_missing_session_and_cross_origin_prepare_are_denied(edge):
    value = proposal(edge)
    assert edge.client.post('/api/gateway-execution/v1/runs', json=value).status_code == 401
    assert edge.client.post('/api/gateway-execution/v1/runs', json=value,
        headers={'Origin': 'https://evil.example', 'X-Visitor-Token': edge.token}).status_code == 403


def test_soft_switch_routes_new_runs_outside_worker_prefix(edge):
    edge.service.observe(90000, edge.clock[0], healthy=True)
    grant = prepare(edge)
    assert grant['stream_path'].startswith('/api/origin-gateway/')
    assert edge.service.summary()['reason'] == 'daily_reserve'


@pytest.mark.parametrize('alias', ['edge', 'origin'])
def test_authenticated_origin_bypass_executes_once_and_preserves_projection(edge, alias):
    value = proposal(edge)
    grant = prepare(edge, value)
    edge.service.observe(100000, edge.clock[0], healthy=False)
    path = f'/api/{alias}-gateway/v1/runs/{grant["run_id"]}/stream'
    headers = {'Origin': ORIGIN, 'Authorization': 'Bearer ' + grant['access_token']}
    response = edge.client.post(path, json=value['input'], headers=headers)
    assert response.status_code == 200 and response.headers['content-type'].startswith('text/event-stream')
    assert '"state":"succeeded"' in response.text
    assert edge.endpoint not in response.text and 'https://news.example/article' in response.text
    assert len(edge.calls) == 1
    assert edge.client.post(path, json=value['input'], headers=headers).status_code == 409
    assert len(edge.calls) == 1


def test_two_backends_cannot_claim_the_same_run(edge):
    value = proposal(edge); grant = prepare(edge, value)
    def attempt(backend):
        try: return claim(edge, grant, value, backend)['attempt_id']
        except EdgeError as error: return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ('worker', 'origin')))
    assert sum(str(item).startswith('ea_') for item in outcomes) == 1
    assert 'ALREADY_CLAIMED' in outcomes
    assert not edge.calls


def test_changed_input_and_changed_binding_never_dispatch(edge):
    value = proposal(edge); grant = prepare(edge, value)
    altered = {'message': 'What is the weather in London?'}
    with pytest.raises(EdgeError, match='approved') as error:
        edge.service.claim(grant['access_token'], ORIGIN, grant['run_id'], altered, 'origin')
    assert error.value.code == 'INPUT_CHANGED'
    with edge.store.tx() as db: db.execute('UPDATE resources SET url=? WHERE id=?', ('https://replacement.example/api', edge.rid))
    with pytest.raises(EdgeError) as changed: claim(edge, grant, value)
    assert changed.value.code == 'SCHEMA_CHANGED'
    assert not edge.calls


def test_service_hmac_and_nonce_replay_protect_private_claim(edge):
    value = proposal(edge); grant = prepare(edge, value)
    body = {'run_id': grant['run_id'], 'access_token': grant['access_token'], 'origin': ORIGIN, 'input': value['input']}
    path = '/api/edge-gateway-internal/v1/claim'
    assert edge.client.post(path, json=body).status_code == 401
    identity = secrets.token_hex(16)
    accepted = service_request(edge, 'claim', body, identity)
    assert accepted.status_code == 200 and accepted.json()['endpoint'] == edge.endpoint
    replay = service_request(edge, 'claim', body, identity)
    assert replay.status_code == 401
    assert edge.endpoint not in replay.text


def test_worker_failure_after_claim_never_returns_an_origin_restart_grant(edge):
    value = proposal(edge); grant = prepare(edge, value)
    binding = claim(edge, grant, value)
    state = edge.service.status(edge.principal, grant['run_id'])
    assert state['state'] == 'dispatch_reserved' and 'stream_path' not in state
    edge.service.finish(grant['run_id'], binding['attempt_id'], 'outcome_unknown')
    assert edge.service.status(edge.principal, grant['run_id'])['state'] == 'outcome_unknown'
    with pytest.raises(EdgeError): claim(edge, grant, value, 'origin')


def test_receipts_are_metadata_only_idempotent_and_conflict_closed(edge):
    value = proposal(edge); grant = prepare(edge, value); binding = claim(edge, grant, value)
    done = {'run_id': grant['run_id'], 'attempt_id': binding['attempt_id'], 'outcome': 'succeeded'}
    assert service_request(edge, 'complete', done).status_code == 200
    assert service_request(edge, 'complete', done).status_code == 200
    assert service_request(edge, 'complete', {**done, 'outcome': 'failed'}).status_code == 409
    assert service_request(edge, 'complete', {**done, 'output': edge.endpoint}).status_code == 400
    with transaction(edge.store, readonly=True) as db:
        saved = rows(db, 'run', (grant['run_id'],))[0]
        count = db.execute('SELECT COUNT(*) FROM edge_gateway_events').fetchone()[0]
    assert count == 1 and 'output' not in saved and edge.endpoint not in canonical(saved)


def test_owner_only_status_and_expired_ticket_are_enforced(edge):
    value = proposal(edge); grant = prepare(edge, value)
    with pytest.raises(EdgeError) as wrong: edge.service.status('b' * 64, grant['run_id'])
    assert wrong.value.status == 404
    edge.clock[0] += 121
    with pytest.raises(EdgeError) as expired: claim(edge, grant, value, 'origin')
    assert expired.value.status == 401


def test_daily_reset_requires_fresh_health_and_keeps_cpu_block(edge):
    edge.service.observe(100000, edge.clock[0], healthy=True)
    assert edge.service.summary()['preferred_backend'] == 'origin'
    edge.clock[0] = (int(edge.clock[0]) // 86400 + 1) * 86400 + 1
    assert edge.service.summary()['preferred_backend'] == 'origin'
    edge.service.observe(0, edge.clock[0], healthy=True)
    assert edge.service.summary()['preferred_backend'] == 'worker'
    with transaction(edge.store) as db: execute(db, 'block_cpu')
    edge.clock[0] += 86400
    edge.service.observe(0, edge.clock[0], healthy=True)
    assert edge.service.summary()['reason'] == 'cpu_blocked'


def test_stale_metrics_and_cumulative_reservations_switch_conservatively(edge):
    edge.clock[0] += 301
    assert edge.service.summary()['preferred_backend'] == 'origin'
    edge.service.observe(89999, edge.clock[0], healthy=True)
    assert prepare(edge)['stream_path'].startswith('/api/edge-gateway/')
    assert prepare(edge)['stream_path'].startswith('/api/origin-gateway/')


def test_origin_never_impersonates_a_worker_health_proof(edge):
    path = '/api/edge-gateway/v1/health'; raw = b'{}'; identity = secrets.token_hex(16); ts = str(int(edge.clock[0]))
    reply = edge.client.post(path, content=raw, headers={'Content-Type': 'application/json', 'X-Edge-Time': ts,
        'X-Edge-Nonce': identity, 'X-Edge-Signature': service_mac(edge.config.key, 'POST', path, ts, identity, raw)})
    assert reply.status_code == 200 and reply.json() == {'backend': 'origin'}
    assert 'x-edge-health-signature' not in reply.headers


def test_readonly_monitor_observes_account_total_and_signed_health(edge):
    def respond(request):
        if request.url.host == 'api.cloudflare.com':
            query = json.loads(request.content)
            assert 'mutation' not in query['query']
            return httpx.Response(200, json={'data': {'viewer': {'accounts': [{'usage': [{'sum': {'requests': 123}}], 'worker': []}]}}})
        result = {'backend': 'worker', 'nonce': request.headers['x-edge-nonce'], 'utc_day': day_at(edge.clock[0])}
        raw = json.dumps(result, separators=(',', ':')).encode()
        signature = hmac.new(derived(edge.config.key, 'edge-health-v1'), raw, hashlib.sha256).hexdigest()
        return httpx.Response(200, content=raw, headers={'x-edge-health-signature': signature})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        answer = Monitor(edge.service, 'a' * 32, 'synthetic-token', client=client).refresh()
    assert answer['healthy'] and edge.service.summary()['account_requests_reported'] == 123



def test_monitor_retries_one_transient_failure_before_withdrawing_readiness(edge, monkeypatch):
    import agent_market.edge_gateway.monitor as monitor_module
    monkeypatch.setattr(monitor_module, 'RETRY_SECONDS', 0)
    edge.service.observe(10, edge.clock[0], healthy=True)
    for outcomes, expected in (([EdgeError('OBSERVATION_UNAVAILABLE'), None], True),
                            ([EdgeError('OBSERVATION_UNAVAILABLE'), EdgeError('OBSERVATION_UNAVAILABLE')], False)):
        watcher = Monitor(edge.service, 'a' * 32, 'synthetic-token', client=object())
        calls = []
        def refresh(pending=list(outcomes)):
            calls.append(1); outcome = pending.pop(0)
            if outcome: raise outcome
            watcher.stop.set()
        watcher.refresh = refresh
        watcher.stop.wait = lambda seconds, real=watcher.stop.wait: (watcher.stop.set() if len(calls) >= 2 and seconds == 60 else None) or real(0)
        watcher.loop()
        assert len(calls) == 2
        assert (edge.service.summary()['preferred_backend'] == 'worker') is expected

def test_config_is_owner_only_rejects_private_urls_and_requires_review(edge, tmp_path, monkeypatch):
    value = {'profile': PROFILE, 'public_origin': ORIGIN, 'shared_secret': base64.b64encode(b'e' * 32).decode(),
             'worker_ready': True, 'providers': [{'resource_id': edge.rid, 'version_id': edge.config.providers[0].version_id,
                 'endpoint': edge.endpoint, 'privacy_reviewed': True, 'origin_compatible': True, 'free_cpu_verified': True}]}
    path = tmp_path / 'edge.json'; path.write_text(json.dumps(value)); path.chmod(0o600)
    monkeypatch.setenv('AGENT_EDGE_GATEWAY_CONFIG', str(path))
    assert load().origin == ORIGIN
    value['providers'][0]['request_mode'] = 'json'
    assert Config.from_dict(value).providers[0].request_mode == 'json'
    value['providers'][0]['request_mode'] = 'auto'
    with pytest.raises(EdgeError): Config.from_dict(value)
    value['providers'][0]['request_mode'] = 'stream'
    path.chmod(0o644)
    with pytest.raises(EdgeError): load()
    value['providers'][0]['endpoint'] = 'https://127.0.0.1/private'
    with pytest.raises(EdgeError): Config.from_dict(value)
    value['providers'][0]['endpoint'] = edge.endpoint
    value['providers'][0]['free_cpu_verified'] = False
    with pytest.raises(EdgeError): Config.from_dict(value)


def test_missing_migration_stays_disabled_and_migration_preserves_state(edge):
    before = edge.service.summary()
    migrate(edge.store)
    assert ready(edge.store) and edge.service.summary()['revision'] == before['revision']


def test_host_controls_use_revision_fences_and_do_not_clear_cpu_on_daily_reset(edge):
    revision = edge.service.summary()['revision']
    host_control(edge.store, 'origin', revision, 'Controlled Origin fallback')
    assert edge.service.summary()['reason'] == 'operator_origin'
    with pytest.raises(EdgeError) as stale:
        host_control(edge.store, 'auto', revision, 'Stale operator change')
    assert stale.value.code == 'REVISION_CHANGED'
    revision = edge.service.summary()['revision']
    host_control(edge.store, 'auto', revision, 'Validated free delivery')
    with transaction(edge.store) as db: execute(db, 'block_cpu')
    revision = edge.service.summary()['revision']
    host_control(edge.store, 'clear-runtime-block', revision, 'Corrected profile validated')
    assert edge.service.summary()['reason'] == 'health_unconfirmed'
    edge.service.observe(0, edge.clock[0], healthy=True)
    assert edge.service.summary()['preferred_backend'] == 'worker'


def test_origin_body_counter_is_metadata_only(edge):
    value = proposal(edge); grant = prepare(edge, value)
    response = edge.client.post(f'/api/origin-gateway/v1/runs/{grant["run_id"]}/stream', json=value['input'],
        headers={'Origin': ORIGIN, 'Authorization': 'Bearer ' + grant['access_token']})
    assert response.status_code == 200
    totals = edge.service.summary()['counts']
    assert totals == [{'backend': 'origin', 'state': 'succeeded', 'n': 1, 'body_bytes': len(response.content)}]


def test_operator_migration_never_initializes_unrelated_application_schema(tmp_path, monkeypatch):
    import sqlite3
    from agent_market.edge_gateway.operator_store import open_operator_store
    monkeypatch.setenv('APPLICATION_STORE_BACKEND', 'sqlite')
    path = tmp_path / 'existing.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE renewal_fixture (id INTEGER PRIMARY KEY, layout TEXT NOT NULL)')
        db.execute("INSERT INTO renewal_fixture VALUES(1,'unchanged')")
    with open_operator_store(path) as store:
        migrate(store)
        migrate(store)
        assert ready(store)
        host_control(store, 'origin', 0, 'Operator fallback test')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM renewal_fixture').fetchall() == [(1, 'unchanged')]
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {name for name in names if not name.startswith('edge_gateway_')} == {'renewal_fixture'}
    with pytest.raises(EdgeError):
        with open_operator_store(tmp_path / 'absent.db'):
            pytest.fail('A new application database must not be created.')
    assert not (tmp_path / 'absent.db').exists()


def test_dormant_provisioning_accepts_no_provider_but_cannot_enable_worker(edge):
    value = {'profile': PROFILE, 'public_origin': ORIGIN,
             'shared_secret': base64.b64encode(b'e' * 32).decode(), 'worker_ready': False, 'providers': []}
    config = Config.from_dict(value)
    assert not config.worker_ready and config.providers == ()
    with pytest.raises(EdgeError): config.provider(edge.rid)
    with pytest.raises(EdgeError): Config.from_dict({**value, 'worker_ready': True})


def test_public_prepare_over_the_rate_gate_hands_the_call_to_the_origin_gateway(edge):
    """11-11: the Worker turned this 429 into "The execution is unavailable." with no code for 7 of 30
    real tasks. Over the gate the bridge answers backend=origin, so the Origin gateway returns its own
    HTTP 429 with Retry-After; nothing is prepared or executed."""
    body = {'resource_id': edge.rid, 'input': {'message': 'What is the weather in Tokyo?'},
            'origin': ORIGIN, 'idempotency_key': 'public-bridge-over-limit'}
    edge.front.security.allow_probe = lambda *_args, **_kw: False
    over = service_request(edge, 'public-prepare', body)
    assert over.status_code == 200 and over.json() == {'backend': 'origin'}
    with transaction(edge.store, readonly=True) as db:
        assert db.execute("SELECT count(*) FROM edge_gateway_runs").fetchone()[0] == 0   # nothing prepared
    assert not edge.calls
    edge.front.security.allow_probe = lambda *_args, **_kw: True
    assert service_request(edge, 'public-prepare', {**body, 'idempotency_key': 'public-bridge-under'}).json()['backend'] == 'worker'


def _observe(edge, errors, invoked):
    def respond(request):
        if request.url.host == 'api.cloudflare.com':
            variables = json.loads(request.content)['variables']
            assert variables['window'] < variables['end']   # the worker rows read only the recent window
            return httpx.Response(200, json={'data': {'viewer': {'accounts': [{'usage': [{'sum': {'requests': 500}}],
                'worker': [{'dimensions': {'status': 'success'}, 'sum': {'requests': invoked - errors, 'errors': 0}},
                           {'dimensions': {'status': 'scriptThrewException'}, 'sum': {'requests': errors, 'errors': errors}}]}]}}})
        result = {'backend': 'worker', 'nonce': request.headers['x-edge-nonce'], 'utc_day': day_at(edge.clock[0])}
        raw = json.dumps(result, separators=(',', ':')).encode()
        signature = hmac.new(derived(edge.config.key, 'edge-health-v1'), raw, hashlib.sha256).hexdigest()
        return httpx.Response(200, content=raw, headers={'x-edge-health-signature': signature})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        return Monitor(edge.service, 'a' * 32, 'synthetic-token', client=client).refresh()


def _audit(edge):
    with transaction(edge.store, readonly=True) as db:
        return [(r['action'], 'edge-monitor') for r in rows(db, 'audit_monitor_last')]   # the query keeps only edge-monitor rows


def test_runtime_block_trips_on_rate_then_half_opens_and_clears_on_a_clean_window(edge):
    """11-11 PM decision: one Worker error a day blocked Worker execution from 10-31 with no way back."""
    from agent_market.edge_gateway import monitor as m
    edge.service.random = lambda: 0.05            # inside the half-open share
    assert _observe(edge, 3, 1000)['transition'] is None and edge.service.summary()['preferred_backend'] == 'worker'
    assert _observe(edge, 10, 100)['transition'] == 'auto-block'
    assert edge.service.summary()['reason'] == 'cpu_blocked' and _audit(edge) == [('auto-block', 'edge-monitor')]
    edge.clock[0] += m.HALF_OPEN_AFTER - 60
    assert edge.service.summary()['reason'] == 'cpu_blocked'
    edge.clock[0] += 61
    _observe(edge, 0, 10)                          # keeps health fresh; too few invocations to clear
    assert edge.service.summary()['reason'] == 'half_open'
    edge.service.random = lambda: 0.5              # outside the share: Origin
    assert edge.service.summary()['reason'] == 'cpu_blocked'
    edge.clock[0] += m.WINDOW_SECONDS
    assert _observe(edge, 0, 50)['transition'] == 'auto-clear'
    assert _audit(edge) == [('auto-clear', 'edge-monitor')]
    _observe(edge, 0, 50)
    assert edge.service.summary()['preferred_backend'] == 'worker'


def test_a_failed_half_open_probe_blocks_again_and_restarts_the_timer(edge):
    from agent_market.edge_gateway import monitor as m
    assert _observe(edge, 20, 100)['transition'] == 'auto-block'
    edge.clock[0] += 60
    assert _observe(edge, 20, 100)['transition'] is None          # still inside the first half-open wait
    edge.clock[0] += m.HALF_OPEN_AFTER
    assert _observe(edge, 20, 100)['transition'] == 'auto-block'  # the probe window failed
    edge.service.random = lambda: 0.0
    assert edge.service.summary()['reason'] == 'cpu_blocked'


def test_a_block_without_a_monitor_audit_row_waits_for_an_operator(edge):
    edge.service.random = lambda: 0.0
    with transaction(edge.store) as db: execute(db, 'block_cpu')
    edge.clock[0] += 7200
    assert _observe(edge, 0, 500)['transition'] is None
    assert edge.service.summary()['reason'] == 'cpu_blocked'

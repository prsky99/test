"""Fixed Stripe test protocol over a mock transport and disposable signed runs."""
import hashlib
import hmac
import json
import secrets
import time
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway import admin_auth
from agent_market.stripe_sandbox import (StripeTestConfig, StripeTestClient, StripeSandbox, NOTICE,
                                         API_VERSION, allocate, refund_targets)
from agent_market.stripe_sandbox_service import router_for, create_webhook_app
from agent_market.workspace_access import WorkspaceAccess, SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from agent_market.workspace_execution import WorkspaceExecution
from agent_market.workflows import runtime_for
from tests.test_workspace_execution_api import private_api, execute as execute_run


@pytest.fixture
def stripe(private_api):
    w = private_api; one, _ = execute_run(w); two, _ = execute_run(w)
    runtime = runtime_for(w.store)
    access = WorkspaceAccess(w.store, runtime.key)
    execution = WorkspaceExecution(access, w.app.state.front.proxy) if hasattr(w.app.state, 'front') else WorkspaceExecution(access, None)
    actor = SessionActor(w.users['owner'], admin_auth.session_reference(w.headers['owner']['Authorization'][7:]))
    config = StripeTestConfig('sk_test_'+'s'*32, 'whsec_'+'w'*32, ((w.rid, 'acct_Synthetic'),))
    calls, objects = [], {}; control = {'lost': False, 'invalid': False, 'refund_failed': False}
    def transport(request):
        fields = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        path = request.url.path
        calls.append({'method': request.method, 'path': path, 'data': fields,
                      'key': request.headers.get('Idempotency-Key')})
        assert request.url.host == 'api.stripe.com' and request.headers['Stripe-Version'] == API_VERSION
        assert request.headers['Authorization'].startswith('Bearer sk_test_')
        if request.method == 'GET':
            if path.startswith('/v1/charges/'):
                pi = objects['/v1/payment_intents/pi_Synthetic']
                return httpx.Response(200, json={'id': pi['latest_charge'], 'object': 'charge', 'livemode': False,
                    'payment_intent': pi['id'], 'amount': pi['amount'], 'amount_refunded': 0, 'currency': 'usd', 'paid': True,
                    'balance_transaction': {'id': 'txn_Synthetic', 'object': 'balance_transaction', 'source': pi['latest_charge'],
                        'currency': 'usd', 'amount': pi['amount'], 'fee': 59, 'net': pi['amount']-59}})
            return httpx.Response(200, json=objects[path])
        if path == '/v1/payment_intents':
            result = {'id': 'pi_Synthetic', 'object': 'payment_intent', 'livemode': False, 'amount': int(fields['amount']),
                'amount_received': 0, 'currency': 'usd', 'capture_method': 'manual', 'status': 'requires_payment_method',
                'metadata': {'order_id': fields['metadata[order_id]']}, 'latest_charge': None,
                'client_secret': 'NEVER_STORE_THIS_CLIENT_SECRET'}
        elif path.endswith(('/confirm', '/capture', '/cancel')):
            if path.endswith('/confirm'): assert set(fields) == {'payment_method'}
            if path.endswith('/cancel'): assert fields == {}
            result = dict(objects['/v1/payment_intents/pi_Synthetic'])
            result['status'] = 'requires_capture' if path.endswith('/confirm') else 'succeeded' if path.endswith('/capture') else 'canceled'
            if result['status'] == 'succeeded': result.update(amount_received=result['amount'], latest_charge='ch_Synthetic')
        elif path == '/v1/transfers':
            result = {'id': 'tr_'+str(len(objects)), 'object': 'transfer', 'livemode': False,
                'amount': int(fields['amount']), 'currency': 'usd', 'destination': fields['destination'],
                'source_transaction': fields['source_transaction'], 'metadata': {'order_id': fields['metadata[order_id]']}}
        elif path == '/v1/refunds':
            result = {'id': 're_'+str(len(objects)), 'object': 'refund', 'amount': int(fields['amount']),
                'status': 'failed' if control['refund_failed'] else 'succeeded',
                'currency': 'usd', 'payment_intent': fields['payment_intent'], 'metadata': {
                    'order_id': fields['metadata[order_id]'], 'command_id': fields['metadata[command_id]']}}
        elif path.endswith('/reversals'):
            result = {'id': 'trr_'+str(len(objects)), 'object': 'transfer_reversal', 'amount': int(fields['amount']),
                'transfer': path.split('/')[3], 'metadata': {'order_id': fields['metadata[order_id]']}}
        else:
            raise AssertionError(path)
        location = ('/v1/payment_intents/'+result['id'] if result['object']=='payment_intent' else
            '/v1/transfers/'+result['id'] if result['object']=='transfer' else
            '/v1/refunds/'+result['id'] if result['object']=='refund' else path+'/'+result['id'])
        objects[location] = result
        if control['lost']:
            control['lost'] = False
            raise httpx.ReadTimeout('Synthetic response loss')
        if control['invalid']:
            result = dict(result, livemode=True)
        return httpx.Response(200, json=result)
    http = httpx.Client(transport=httpx.MockTransport(transport))
    core = StripeSandbox(access, execution, client=StripeTestClient(config, http=http))
    order = core.quote(w.ws['id'], {'amount': 1000, 'attempts': [{'run_id': one['id'], 'weight': 1},
        {'run_id': two['id'], 'weight': 3}], 'authorized': True, 'notice': NOTICE}, actor)
    app = FastAPI(); app.include_router(router_for(core))
    with TestClient(app, base_url='https://admin.test') as client:
        yield SimpleNamespace(w=w, core=core, actor=actor, order=order, config=config, calls=calls,
                              objects=objects, control=control, client=client,
                              base='/admin/api/workflow-workspaces/'+w.ws['id']+'/stripe-sandbox')
    http.close()


def act(x, action, **fields):
    current = x.core.status(x.w.ws['id'], x.order['id'], x.actor)
    body = {'command_id': 'spc_'+secrets.token_hex(16), 'action': action, 'revision': current['revision'],
            'authorized': True, 'notice': NOTICE, **fields}
    result = x.core.execute(x.w.ws['id'], x.order['id'], body, x.actor)
    return result, body


def capture(x):
    for action in ('create', 'confirm', 'capture'):
        result, _ = act(x, action); assert result['state'] == 'accepted'


def settle(x):
    capture(x)
    for i in range(2):
        result, _ = act(x, 'transfer', index=i); assert result['state'] == 'accepted'


def signed_event(x, command, obj, *, event_id='evt_Synthetic'):
    value = {'id': event_id, 'object': 'event', 'livemode': False, 'api_version': API_VERSION,
             'request': {'idempotency_key': command['key']}, 'data': {'object': obj}}
    raw = json.dumps(value).encode(); stamp = str(int(time.time()))
    signature = hmac.new(x.config.webhook_secret.encode(), stamp.encode()+b'.'+raw, hashlib.sha256).hexdigest()
    return raw, 't='+stamp+',v1='+signature


def test_test_only_configuration_and_exact_integer_allocation():
    with pytest.raises(WorkspaceInvalid): StripeTestConfig('sk_live_'+'a'*32, 'whsec_'+'b'*32, ((1, 'acct_Test'),))
    for amount in range(1, 101):
        result = allocate(amount, [1, 3, 7]); assert sum(result) == amount and min(result) >= 0
    order = {'amount': 1000, 'contributors': [{'allocation': 175}, {'allocation': 525}], 'platform_allocation': 300}
    previous = [0, 0, 0]
    for refunded in range(1001):
        current = refund_targets(order, refunded)
        assert sum(current) == refunded and all(current[i] >= previous[i] for i in range(2))
        previous = current


def test_manual_capture_weighted_transfers_partial_refund_and_explicit_reversals(stripe):
    x = stripe; settle(x)
    status = x.core.status(x.w.ws['id'], x.order['id'], x.actor)
    assert status['captured'] == 1000 and status['platform_allocation'] == 300
    assert sorted(c['allocation'] for c in status['provider_allocations']) == [175, 525]
    assert all(c['allocation'] == c['transferred'] for c in status['provider_allocations'])
    refund, _ = act(x, 'refund', amount=333); assert refund['state'] == 'accepted'
    assert sum(c['reversed'] for c in x.core.status(x.w.ws['id'], x.order['id'], x.actor)['provider_allocations']) == 0
    for i in range(2):
        reverse, _ = act(x, 'reverse', index=i); assert reverse['state'] == 'accepted'
    result = x.core.status(x.w.ws['id'], x.order['id'], x.actor)
    assert result['refunded'] == 333 and result['ledger_conserved']
    assert sum(c['reversed'] for c in result['provider_allocations']) == sum(c['allocation']*333//1000 for c in result['provider_allocations'])
    assert not result['processor_balance_reconciled']
    persisted = '\n'.join(r[0] for r in x.w.store.query('SELECT payload FROM stripe_sandbox_orders'))
    assert 'NEVER_STORE_THIS_CLIENT_SECRET' not in persisted and x.config.secret_key not in persisted


def test_unknown_create_waits_for_signed_original_id_and_never_posts_twice(stripe):
    x = stripe; x.control['lost'] = True
    result, body = act(x, 'create'); assert result['state'] == 'unknown'
    assert x.core.execute(x.w.ws['id'], x.order['id'], body, x.actor) == result and len(x.calls) == 1
    with pytest.raises(WorkspaceConflict): act(x, 'create')
    reconcile = {'command_id': body['command_id'], 'authorized': True, 'notice': NOTICE}
    assert x.core.reconcile(x.w.ws['id'], x.order['id'], reconcile, x.actor)['original_id_required']
    command = x.core._command(x.w.store._db, x.w.ws['id'], body['command_id'])
    raw, signature = signed_event(x, command, x.objects['/v1/payment_intents/pi_Synthetic'])
    assert x.core.webhook(raw, signature)['accepted']
    assert x.core.webhook(raw, signature)['replayed']
    accepted = x.core.reconcile(x.w.ws['id'], x.order['id'], reconcile, x.actor)
    assert accepted['state'] == 'accepted'
    assert [c['method'] for c in x.calls] == ['POST', 'GET']
    assert x.calls[-1]['path'] == '/v1/payment_intents/pi_Synthetic'


def test_duplicate_transfer_and_refund_commands_do_not_duplicate_accounting(stripe):
    x = stripe; capture(x)
    first, body = act(x, 'transfer', index=0)
    assert x.core.execute(x.w.ws['id'], x.order['id'], body, x.actor) == first
    with pytest.raises(WorkspaceConflict): act(x, 'transfer', index=0)
    act(x, 'transfer', index=1)
    first, body = act(x, 'refund', amount=500)
    assert x.core.execute(x.w.ws['id'], x.order['id'], body, x.actor) == first
    assert x.core.status(x.w.ws['id'], x.order['id'], x.actor)['refunded'] == 500
    assert len([c for c in x.calls if c['path'] == '/v1/refunds']) == 1


def test_live_response_restore_and_other_roles_fail_closed(stripe):
    x = stripe; x.control['invalid'] = True
    result, _ = act(x, 'create'); assert result['state'] == 'unknown'
    base = x.base+'/orders/'+x.order['id']
    assert x.client.get(base).status_code == 401
    assert x.client.post(base+'/execute', headers=x.w.headers['viewer'], json={}).status_code == 400
    assert x.client.get(base, headers=x.w.headers['outsider']).status_code == 404
    with x.w.store.tx() as db: db.execute('INSERT INTO stripe_sandbox_restore_blocks VALUES(?)', (x.order['id'],))
    with pytest.raises(WorkspaceConflict): act(x, 'create')


def test_webhook_requires_raw_signature_expiry_test_mode_and_exact_host(stripe):
    x = stripe; x.control['lost'] = True; _, body = act(x, 'create')
    command = x.core._command(x.w.store._db, x.w.ws['id'], body['command_id'])
    raw, signature = signed_event(x, command, x.objects['/v1/payment_intents/pi_Synthetic'])
    with TestClient(create_webhook_app(x.core, allowed_host='receiver.test'), base_url='https://receiver.test') as client:
        assert client.post('/stripe/test/events', content=raw).status_code == 400
        assert client.post('/stripe/test/events', content=raw, headers={'Stripe-Signature': signature, 'Host': 'evil.test'}).status_code == 404
        assert client.post('/stripe/test/events', content=raw, headers={'Stripe-Signature': signature}).status_code == 200
        assert client.post('/stripe/test/events', content=raw+b' ', headers={'Stripe-Signature': signature}).status_code == 400


def test_same_immutable_successful_attempts_cannot_fund_new_economic_order(stripe):
    x = stripe
    order = x.core._load(x.w.store._db, x.w.ws['id'], x.order['id'])
    body = {'amount': 1000, 'attempts': [{'run_id': c['run_id'], 'weight': c['weight']} for c in order['contributors']],
            'authorized': True, 'notice': NOTICE}
    with pytest.raises(WorkspaceConflict): x.core.quote(x.w.ws['id'], body, x.actor)
    with x.w.store.tx() as db: db.execute('DELETE FROM stripe_sandbox_reservations')
    with pytest.raises(WorkspaceConflict): x.core.quote(x.w.ws['id'], body, x.actor)
    assert not x.calls


def test_original_charge_fee_and_net_reconcile_once_without_capture_or_transfer(stripe):
    x = stripe; capture(x); before = len(x.calls)
    body = {'authorized': True, 'notice': NOTICE}
    result = x.core.reconcile_balance(x.w.ws['id'], x.order['id'], body, x.actor)
    assert result['processor_fee'] == 59 and result['processor_balance_reconciled'] and result['ledger_conserved']
    again = x.core.reconcile_balance(x.w.ws['id'], x.order['id'], body, x.actor)
    assert again == result and all(c['method'] == 'GET' for c in x.calls[before:])
    stored = x.core._load(x.w.store._db, x.w.ws['id'], x.order['id'])
    assert sum(e['units'] for e in stored['entries'] if e['account'] == 'processor_fee_expense') == 59


@pytest.mark.parametrize('revision', [True, 1.0, '1'])
def test_revision_types_and_valid_viewer_payload_cannot_dispatch(stripe, revision):
    x = stripe
    body = {'command_id': 'spc_'+secrets.token_hex(16), 'action': 'create', 'revision': revision,
            'authorized': True, 'notice': NOTICE}
    with pytest.raises(WorkspaceInvalid): x.core.execute(x.w.ws['id'], x.order['id'], body, x.actor)
    body['revision'] = 1
    response = x.client.post(x.base+'/orders/'+x.order['id']+'/execute', headers=x.w.headers['viewer'], json=body)
    assert response.status_code == 404 and not x.calls


def test_verified_async_refund_failure_reconciles_original_and_never_books_refund(stripe):
    x = stripe; settle(x); x.control.update(lost=True, refund_failed=True)
    result, body = act(x, 'refund', amount=100); assert result['state'] == 'unknown'
    command = x.core._command(x.w.store._db, x.w.ws['id'], body['command_id'])
    refund = next(v for k, v in x.objects.items() if k.startswith('/v1/refunds/'))
    raw, signature = signed_event(x, command, refund)
    event = json.loads(raw); event['request'] = None
    raw = json.dumps(event).encode(); stamp = str(int(time.time()))
    signature = 't='+stamp+',v1='+hmac.new(x.config.webhook_secret.encode(), stamp.encode()+b'.'+raw, hashlib.sha256).hexdigest()
    assert x.core.webhook(raw, signature)['reconciliation_required']
    result = x.core.reconcile(x.w.ws['id'], x.order['id'], {'command_id': body['command_id'],
                              'authorized': True, 'notice': NOTICE}, x.actor)
    assert result['state'] == 'failed'
    status = x.core.status(x.w.ws['id'], x.order['id'], x.actor)
    assert status['refunded'] == 0 and status['ledger_conserved']
    assert len([c for c in x.calls if c['method'] == 'POST' and c['path'] == '/v1/refunds']) == 1


@pytest.mark.parametrize('action,prefix', [('create', 'pi'), ('confirm', 'pi'), ('capture', 'pi'), ('cancel', 'pi'),
                                        ('transfer', 'tr'), ('refund', 're'), ('reverse', 'trr')])
def test_every_financial_branch_preserves_authenticated_original_id_before_accounting(stripe, action, prefix):
    x = stripe
    order = x.core._load(x.w.store._db, x.w.ws['id'], x.order['id']); previous = deepcopy(order)
    command = {'id': 'spc_'+'a'*32, 'action': action, 'data': {}, 'provider_id': prefix+'_Original'}
    with pytest.raises(WorkspaceConflict):
        x.core._apply(order, command, {'id': prefix+'_Different', 'amount': 1000, 'livemode': False})
    assert order == previous


@pytest.mark.parametrize('raw', [b'{"livemode":true,"livemode":false}', b'{"livemode":false,"amount":NaN}',
                               b'{"livemode":false,"amount":1e999}', b'[]'])
def test_stripe_response_json_rejects_duplicates_nonfinite_and_nonobject(raw):
    config = StripeTestConfig('sk_test_'+'s'*32, 'whsec_'+'w'*32, ((1, 'acct_Synthetic'),))
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw))) as http:
        client = StripeTestClient(config, http=http)
        with pytest.raises((WorkspaceInvalid, WorkspaceConflict, ValueError)):
            client.request('GET', '/v1/payment_intents/pi_Original')


def test_capture_response_loss_reads_already_pinned_original_without_reposting_or_webhook(stripe):
    x = stripe; act(x, 'create'); act(x, 'confirm'); x.control['lost'] = True
    result, body = act(x, 'capture'); assert result['state'] == 'unknown'
    result = x.core.reconcile(x.w.ws['id'], x.order['id'], {'command_id': body['command_id'],
                'authorized': True, 'notice': NOTICE}, x.actor)
    assert result['state'] == 'accepted'
    assert x.core.status(x.w.ws['id'], x.order['id'], x.actor)['captured'] == 1000
    assert len([c for c in x.calls if c['path'].endswith('/capture')]) == 1 and x.calls[-1]['method'] == 'GET'


def test_uncaptured_authorization_can_cancel_original_without_metadata_parameter(stripe):
    x = stripe; act(x, 'create'); act(x, 'confirm')
    result, _ = act(x, 'cancel'); assert result['state'] == 'accepted'
    status = x.core.status(x.w.ws['id'], x.order['id'], x.actor)
    assert status['state'] == 'canceled' and status['captured'] == 0 and status['ledger_conserved']

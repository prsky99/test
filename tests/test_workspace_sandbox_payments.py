"""Actual signed sandbox ingress and conserved existing TEST_UNIT ledger."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import time

import pytest

from agent_market.workspace_sandbox_payments import (SandboxPayments, PREPARE_NOTICE,
    EXECUTE_NOTICE, WITHDRAW_NOTICE)
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from tests.test_workspace_agreements import agreement
from tests.test_provider_claims import provider


@pytest.fixture
def sandbox(agreement):
    w = agreement
    w.payments = SandboxPayments(w.access, w.agreements)
    return w


def prepare(w, action='capture', target=None, amount=101, revision=1, reference='sim_transport_capture'):
    return w.payments.prepare(w.ws, {'action': action, 'target_id': target or w.agreement['id'],
        'units': amount, 'revision': revision, 'event_reference': reference,
        'authorized': True, 'notice': PREPARE_NOTICE}, w.staff[1])


def dispatch(w, value):
    return w.payments.dispatch(w.ws, {'intent_id': value['id'], 'authorized': True,
        'notice': EXECUTE_NOTICE}, w.staff[1])


def wire(w, value):
    with w.access._tx(w.staff[1]) as (db, _):
        current = w.payments._current(db, w.ws, value['id'], w.staff[1])
        raw = w.payments._wire(current)
    return raw, w.payments._signature(raw)


def test_real_ingress_capture_refund_replay_uses_existing_balanced_ledger(sandbox):
    w = sandbox; before = len(w.provider_calls)
    intent = prepare(w)
    assert sum(item['event_count'] for item in w.agreements.summary(w.ws, w.staff[1])['settlements']) == 0
    result = dispatch(w, intent)
    assert result['receipt_recorded'] and not result['actual_money']
    replay = dispatch(w, intent)
    assert replay['result']['replayed'] and replay['result']['id'] == result['result']['id']
    refund = prepare(w, 'refund', result['result']['id'], 33, result['result']['revision'], 'sim_transport_refund')
    refunded = dispatch(w, refund)
    assert refunded['result']['refunded_units'] == 33
    assert dispatch(w, intent)['result']['refunded_units'] == 0
    assert dispatch(w, refund)['result']['replayed']
    summary = w.agreements.summary(w.ws, w.staff[1])
    assert sum(item['event_count'] for item in summary['settlements']) == 2 and summary['balanced']
    assert len(w.provider_calls) == before
    assert all(item['state'] == 'recorded' for item in w.payments.status(w.ws, w.staff[1])['intents'])
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_receipts').fetchone()[0] == 2


@pytest.mark.parametrize('change', ['signature', 'body', 'environment', 'duplicate_json', 'expired', 'wrong_workspace'])
def test_transport_authentication_and_bounds_reject_before_ledger(sandbox, change):
    w = sandbox; value = prepare(w); raw, signature = wire(w, value)
    if change == 'signature': signature = 'v1.' + '0' * 64
    elif change == 'body': raw = raw.replace(b'101', b'102')
    else:
        parsed = json.loads(raw)
        if change == 'environment': parsed['environment'] = 'operating'
        elif change == 'expired': parsed['expires'] = time.time() - 1
        elif change == 'wrong_workspace': parsed['workspace_id'] = 'ws_' + 'b' * 32
        raw = json.dumps(parsed, sort_keys=True, separators=(',', ':')).encode()
        if change == 'duplicate_json': raw = b'{"profile":"duplicate",' + raw[1:]
        signature = w.payments._signature(raw)
    with pytest.raises((WorkspaceDenied, WorkspaceInvalid)):
        w.payments.ingest(raw, signature, w.staff[1])
    assert sum(item['event_count'] for item in w.agreements.summary(w.ws, w.staff[1])['settlements']) == 0


@pytest.mark.parametrize('change', ['session', 'membership', 'resource', 'claim', 'withdraw', 'restore'])
def test_current_authority_rechecked_at_dispatch(sandbox, change):
    w = sandbox; value = prepare(w)
    if change == 'withdraw':
        w.payments.withdraw(w.ws, {'intent_id': value['id'], 'authorized': True, 'notice': WITHDRAW_NOTICE}, w.staff[1])
    else:
        with w.store._db as db:
            if change == 'session': db.execute('UPDATE admin_sessions SET expires_at=0 WHERE user_id=1')
            elif change == 'membership': db.execute('UPDATE workspace_memberships SET revision=revision+2 WHERE workspace_id=? AND user_id=1', (w.ws,))
            elif change == 'resource': db.execute('UPDATE resources SET active=0 WHERE id=1')
            elif change == 'claim': db.execute('UPDATE provider_control_claims SET revoked=?', (time.time(),))
            elif change == 'restore': db.execute('INSERT INTO workspace_sandbox_payment_restore_blocks VALUES(?)', (value['id'],))
    with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
        dispatch(w, value)
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 0


def test_receipt_failure_rolls_back_accepted_capture_entries(sandbox, monkeypatch):
    w = sandbox; intent = prepare(w); original = w.access._audit
    def fail(db, actor, ws, action, *args):
        original(db, actor, ws, action, *args)
        if action == 'sandbox_payment.receive':
            assert db.execute('SELECT COUNT(*) FROM workspace_agreement_entries').fetchone()[0] == 5
            assert db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_receipts').fetchone()[0] == 1
            raise WorkspaceConflict()
    with monkeypatch.context() as context:
        context.setattr(w.access, '_audit', fail)
        with pytest.raises(WorkspaceConflict): dispatch(w, intent)
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 0
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_receipts').fetchone()[0] == 0
    assert dispatch(w, intent)['receipt_recorded']


def test_concurrent_identical_transport_events_commit_one_receipt_and_capture(sandbox):
    w = sandbox; intent = prepare(w)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: dispatch(w, intent), range(4)))
    assert sum(not item['result']['replayed'] for item in results) == 1
    assert sum(item['event_count'] for item in w.agreements.summary(w.ws, w.staff[1])['settlements']) == 1
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_receipts').fetchone()[0] == 1


@pytest.mark.parametrize('table', ['workspace_sandbox_payment_intents', 'workspace_sandbox_payment_receipts', 'workspace_sandbox_payment_withdrawals'])
def test_history_tamper_fails_closed(sandbox, table):
    w = sandbox; intent = prepare(w)
    if table.endswith('receipts'): dispatch(w, intent)
    if table.endswith('withdrawals'):
        w.payments.withdraw(w.ws, {'intent_id': intent['id'], 'authorized': True, 'notice': WITHDRAW_NOTICE}, w.staff[1])
    with w.store._db as db: db.execute('UPDATE ' + table + " SET payload='{}'")
    with pytest.raises((WorkspaceConflict, WorkspaceInvalid, WorkspaceDenied)):
        w.payments.status(w.ws, w.staff[1])


@pytest.mark.parametrize('body', [True,{}, {'action':'payout'}, {'actual_money':True}, {'notice':PREPARE_NOTICE}])
def test_malformed_or_operating_commands_do_not_create_intents(sandbox, body):
    with pytest.raises(WorkspaceInvalid): sandbox.payments.prepare(sandbox.ws, body, sandbox.staff[1])
    assert sandbox.store._db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_intents').fetchone()[0] == 0

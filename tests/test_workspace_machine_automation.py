"""Purpose grants drive existing notice events without a human session replay."""
import json
import copy

import pytest

from agent_market.workspace_access import WorkspaceDenied
from agent_market.workspace_machine_automation import MachineUpdateAutomation, GrantActor, NOTICE
from agent_market.workspace_machine_updates import WITHDRAW_NOTICE
from tests.test_provider_claims import provider  # noqa: F401
from tests.test_workspace_machine_updates import machine, subscribe, Evidence  # noqa: F401


class CurrentEvidence(Evidence):
    def current_projection_in_transaction(source, db, ws, rid, actor):
        assert db.in_transaction
        source.access._access(ws, actor)
        return copy.deepcopy(source.value)


def source_for(w):
    source = CurrentEvidence(w.access)
    source.value = w.evidence_source.value
    w.evidence_source = source
    w.machine.evidence_source = source.get_agent_projection


def grant(w, maximum=3):
    subscription = subscribe(w)
    source_for(w)
    automation = MachineUpdateAutomation(w.machine, enabled=True)
    automation.authorize(w.ws, {'subscription_id': subscription['id'], 'ttl_seconds': 600,
        'max_events': maximum, 'authorized': True, 'notice': NOTICE}, w.staff[1])
    return automation, subscription


def test_granted_changed_evidence_delivers_once_after_original_session_expires(machine):
    w = machine; auto, sub = grant(w)
    with w.store._db:
        w.store._db.execute('DELETE FROM admin_sessions WHERE user_id=1')
    assert auto.tick()['accepted'] == 1
    assert auto.tick()['accepted'] == 0 and len(w.receiver.calls) == 1
    w.evidence_source.value['source_revision'] = '4'*64
    # The source object is copied, with the same immutable/current backing data.
    assert auto.tick()['accepted'] == 1 and len(w.receiver.calls) == 2
    events = w.store._db.execute('SELECT state FROM workspace_machine_update_events').fetchall()
    assert all(row['state'] == 'accepted' for row in events)
    principal = GrantActor(1, 'purpose:' + sub['id'], w.ws, sub['id'])
    with pytest.raises(WorkspaceDenied):
        w.access._access(w.ws, principal, write=True)
    assert all('task_completed' not in json.loads(raw) or not json.loads(raw)['task_completed'] for raw, _ in w.receiver.calls)


@pytest.mark.parametrize('change', ['withdraw', 'member', 'workspace', 'provider', 'restore', 'tamper'])
def test_current_revocation_or_tamper_prevents_automatic_dispatch(machine, change):
    w = machine; auto, sub = grant(w)
    if change == 'withdraw':
        w.machine.withdraw(w.ws, {'subscription_id': sub['id'], 'authorized': True, 'notice': WITHDRAW_NOTICE}, w.staff[1])
    else:
        with w.store._db:
            if change == 'member': w.store._db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=? AND user_id=1', (w.ws,))
            elif change == 'workspace': w.store._db.execute('UPDATE organization_workspaces SET active=0 WHERE id=?', (w.ws,))
            elif change == 'provider': w.store._db.execute("UPDATE provider_control_claims SET status='revoked' WHERE workspace_id=?", (w.ws,))
            elif change == 'restore': w.store._db.execute('INSERT INTO workspace_machine_update_restore_blocks VALUES(?)', (sub['id'],))
            else: w.store._db.execute("UPDATE workspace_machine_subscriptions SET payload='{}' WHERE id=?", (sub['id'],))
    assert auto.tick()['accepted'] == 0 and not w.receiver.calls


def test_unknown_is_not_resent_and_budget_does_not_expand_with_new_evidence(machine):
    w = machine; auto, _ = grant(w, maximum=2)
    w.receiver.fault = 'exception'
    assert auto.tick()['accepted'] == 0 and len(w.receiver.calls) == 1
    w.receiver.fault = None
    assert auto.tick()['accepted'] == 0 and len(w.receiver.calls) == 1
    w.evidence_source.value['source_revision'] = '4'*64
    assert auto.tick()['accepted'] == 1 and len(w.receiver.calls) == 2
    w.evidence_source.value['source_revision'] = '5'*64
    assert auto.tick()['accepted'] == 0 and len(w.receiver.calls) == 2


def test_default_worker_is_inert_and_start_close_do_not_issue_authority(machine):
    w = machine; source_for(w); auto = MachineUpdateAutomation(w.machine)
    assert auto.start() and auto.tick() == {'checked': 0, 'accepted': 0, 'blocked': 0} and auto.close()
    assert not w.receiver.calls
    with pytest.raises(WorkspaceDenied):
        with auto.access._tx(None):
            raise AssertionError('An invalid actor must never enter the grant transaction.')


def test_explicit_worker_lifecycle_starts_one_consumer_and_stops_without_implicit_notice(machine):
    w = machine; automation, _ = grant(w)
    try:
        assert automation.start()
        thread = automation._thread
        assert thread.is_alive() and automation.start() and automation._thread is thread
        assert not w.receiver.calls
    finally:
        assert automation.close()
    assert not thread.is_alive()

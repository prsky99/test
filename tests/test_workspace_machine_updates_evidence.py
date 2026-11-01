"""Actual current reliability projection stays neutral through signed delivery."""

import copy
from dataclasses import replace
import json
import time

import httpx
import pytest

from agent_market.provider_claims import ProviderClaims, NOTICE
from agent_market.workspace_access import WorkspaceDenied
from agent_market.workspace_machine_updates import (MachineUpdates, ConfiguredSender, VerifiedDestination,
    PURPOSE, SUBSCRIBE_NOTICE, PREPARE_NOTICE, DISPATCH_NOTICE, verify_envelope, _signature)
from agent_market.workspace_access import _canonical
from tests.test_workspace_execution_api import private_api  # noqa: F401
from tests.test_workspace_reliability import reliability, setup, sample, trusted  # noqa: F401
from tests.test_workspace_machine_updates import Receiver


def test_actual_neutral_reliability_and_current_provider_proof_can_deliver_metadata_only(reliability):
    w = reliability
    ws = w.ws['id']
    proof = {}

    def controlled(request):
        assert request.method == 'GET' and request.url.path == '/.well-known/agent-concierge-claim.json'
        return httpx.Response(200, json=copy.deepcopy(proof))

    http = httpx.Client(transport=httpx.MockTransport(controlled))
    claims = ProviderClaims(w.store, b'c'*32, http)
    try:
        prepared = claims.prepare(ws, {'resource_id': w.rid}, w.actor)
        proof.update(prepared['challenge'])
        verified = claims.verify(ws, {'claim_id': prepared['claim']['id'], 'revision': prepared['claim']['revision'],
                                     'authorized': True, 'notice': NOTICE}, w.actor)
        now = time.time()
        destination = VerifiedDestination(ws, 'configured_inbox', 'audience_fixture', 'a2a_inbox', PURPOSE,
                                          1, now, now+300, b'r'*32, 'isolated')
        machine = MachineUpdates(w.plane.access, w.plane.get_agent_projection,
                                 destination_verifier=lambda *_: destination, provider_claims=claims)
        receiver = Receiver(machine)
        machine.sender = ConfiguredSender(receiver.send)
        before = len(w.calls)
        sub = machine.subscribe(ws, {'resource_id': w.rid, 'destination_ref': destination.destination_ref,
            'audience': destination.audience, 'protocol': destination.protocol,
            'authorized': True, 'notice': SUBSCRIBE_NOTICE}, w.actor)
        event = machine.prepare(ws, {'subscription_id': sub['id'], 'authorized': True, 'notice': PREPARE_NOTICE}, w.actor)
        result = machine.dispatch(ws, {'event_id': event['id'], 'authorized': True, 'notice': DISPATCH_NOTICE}, w.actor)
        assert result['state'] == 'accepted' and result['quality_status'] == 'unassessed'
        assert result['reason'] == 'evidence_unassessed' and result['delivery_receipt_only']
        assert len(w.calls) == before and len(receiver.calls) == 1
        claim_state = claims.revoke(ws, verified['id'], {'revision': verified['revision']}, w.actor)
        assert claim_state['status'] == 'revoked'
        with pytest.raises(WorkspaceDenied):
            machine.subscribe(ws, {'resource_id': w.rid, 'destination_ref': destination.destination_ref,
                'audience': destination.audience, 'protocol': destination.protocol,
                'authorized': True, 'notice': SUBSCRIBE_NOTICE}, w.actor)
    finally:
        http.close()


def test_actual_qualification_loss_and_same_authorized_contract_regain_emit_truthful_notices(reliability):
    w = setup(reliability); sample(w); sample(w)
    ws, challenge = w.ws['id'], {}
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=copy.deepcopy(challenge))))
    claims = ProviderClaims(w.store, b'c'*32, http)
    try:
        prepared = claims.prepare(ws, {'resource_id': w.rid}, w.actor)
        challenge.update(prepared['challenge'])
        claims.verify(ws, {'claim_id': prepared['claim']['id'], 'revision': prepared['claim']['revision'],
                          'authorized': True, 'notice': NOTICE}, w.actor)
        now, evidence_expires = time.time(), time.time()+120
        destination = VerifiedDestination(ws, 'configured_inbox', 'audience_fixture', 'a2a_inbox', PURPOSE,
                                          1, now, now+300, b'r'*32, 'isolated')
        core = MachineUpdates(w.plane.access, w.plane, destination_verifier=lambda *_: destination, provider_claims=claims)
        receiver = Receiver(core); core.sender = ConfiguredSender(receiver.send)
        def subscribe():
            return core.subscribe(ws, {'resource_id': w.rid, 'destination_ref': destination.destination_ref,
                'audience': destination.audience, 'protocol': destination.protocol,
                'authorized': True, 'notice': SUBSCRIBE_NOTICE}, w.actor)
        def prepare(sub):
            return core.prepare(ws, {'subscription_id': sub['id'], 'authorized': True, 'notice': PREPARE_NOTICE}, w.actor)
        def dispatch(event):
            return core.dispatch(ws, {'event_id': event['id'], 'authorized': True, 'notice': DISPATCH_NOTICE}, w.actor)
        neutral_subscription = subscribe()
        fixed_evaluator = lambda binding,bundle: replace(trusted(binding,bundle), expires=evidence_expires)
        w.plane.evaluator = fixed_evaluator
        w.plane.current_report(ws, w.rid, w.actor)
        projection = w.plane.get_agent_projection(ws, w.rid, w.actor)
        assert projection['independent_qualified'] and projection['contract_id'] == 'news.search.v1'
        with pytest.raises(WorkspaceDenied): prepare(neutral_subscription)
        subscription = subscribe()
        old_positive = prepare(subscription)
        w.plane.evaluator = None
        loss = prepare(subscription)
        assert dispatch(loss)['state'] == 'accepted'
        loss_wire = json.loads(receiver.calls[-1][0])
        assert loss_wire['subject']['contract_ref'] is loss_wire['subject']['contract_revision'] is loss_wire['subject']['contract_hash'] is None
        assert loss_wire['reason'] == 'evidence_unassessed' and not loss_wire['evidence']['independent_qualified']
        with pytest.raises(WorkspaceDenied): dispatch(old_positive)
        w.plane.evaluator = fixed_evaluator
        w.plane.current_report(ws, w.rid, w.actor)
        gain = prepare(subscription)
        assert dispatch(gain)['state'] == 'accepted'
        raw, signature = receiver.calls[-1]
        gain_wire = json.loads(raw)
        assert gain_wire['subject']['contract_ref'] == 'news.search.v1' and gain_wire['evidence']['quality_status'] == 'assessed'
        assert gain_wire['expires_at'] <= evidence_expires
        with pytest.raises(WorkspaceDenied):
            verify_envelope(raw, signature, key=core.envelope_key(destination), audience=destination.audience,
                protocol=destination.protocol, seen_events=set(), seen_nonces=set(), seen_dedupes=set(), now=evidence_expires+1)
        extended = copy.deepcopy(gain_wire)
        extended['expires_at'] = extended['issued_at']+300
        extended_raw = _canonical(extended).encode('ascii')
        with pytest.raises(WorkspaceDenied):
            verify_envelope(extended_raw, _signature(core.envelope_key(destination), extended_raw), key=core.envelope_key(destination),
                audience=destination.audience, protocol=destination.protocol,
                seen_events=set(), seen_nonces=set(), seen_dedupes=set(), now=evidence_expires+1)
        history = core.status(ws, w.actor)
        assert next(event for event in history['events'] if event['id'] == old_positive['id'])['state'] == 'superseded'
        assert len(receiver.calls) == 2
    finally:
        http.close()

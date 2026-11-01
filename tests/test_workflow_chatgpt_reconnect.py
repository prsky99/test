"""Local reauthorization preserves the issued client and verified account."""
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from agent_market.workflow_chatgpt import LoginAttempt, ChatGPTGraphProposer, private_write
from agent_market.workflow_chatgpt_login import login_attempt
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied
from tests.test_workflow_ai_providers import record, signing
from tests.test_workflow_model_ollama import growth, typed_world, routing, graph
from tests.test_workspace_model_proposal import request


HOST = 'urn:uuid:00000000-0000-4000-8000-000000000000'
CALLBACK = 'http://127.0.0.1:14555/auth/callback'
EMAIL = 'owner@example.test'


def stored(tmp_path, **changes):
    value = record() | {'email': EMAIL, **changes}
    private_write(tmp_path / 'credentials.json', value)
    return value


def test_first_connection_registers_but_reconnect_reuses_issued_client(tmp_path):
    first = login_attempt(tmp_path, CALLBACK, HOST, EMAIL)
    assert first.client_id == 'dynamic_agent_client'
    stored(tmp_path)
    second = login_attempt(tmp_path, CALLBACK, HOST, EMAIL.upper())
    args = parse_qs(urlsplit(second.authorization_url()).query)
    assert args['client_id'] == ['oaiapp_synthetic']
    assert 'agent_name_hint' not in args
    assert second.expected_subject == 'synthetic-subject'
    assert first.state != second.state and first.verifier != second.verifier


@pytest.mark.parametrize('changes', [
    {'profile': 'other'}, {'issuer': 'https://foreign.test'},
    {'client_id': 'dynamic_agent_client'}, {'client_id': 1},
    {'email': 'other@example.test'}, {'email': None},
    {'ext_agent_host_id': 'different-host'}, {'subject': ''},
    {'scopes': []}, {'scopes': [{}]},
])
def test_reconnect_refuses_wrong_account_host_or_untrusted_client(tmp_path, changes):
    stored(tmp_path, **changes)
    before = (tmp_path / 'credentials.json').read_bytes()
    with pytest.raises(WorkspaceDenied):
        login_attempt(tmp_path, CALLBACK, HOST, EMAIL)
    assert (tmp_path / 'credentials.json').read_bytes() == before


def test_reconnect_refuses_insecure_credentials_instead_of_registering_again(tmp_path):
    stored(tmp_path)
    path = tmp_path / 'credentials.json'
    path.chmod(0o644)
    with pytest.raises(WorkspaceDenied):
        login_attempt(tmp_path, CALLBACK, HOST, EMAIL)


@pytest.mark.parametrize('client_id', ['', 'other', 1, 'https://foreign.test'])
def test_authorization_rejects_unregistered_client_shapes(client_id):
    with pytest.raises(WorkspaceDenied):
        LoginAttempt(CALLBACK, HOST, client_id=client_id).authorization_url()


def test_reauthorization_cannot_switch_subject_under_same_email(tmp_path, signing):
    token, jwk = signing
    stored(tmp_path)
    flow = login_attempt(tmp_path, CALLBACK, HOST, EMAIL)

    def respond(request):
        if request.url.path.endswith('jwks.json'):
            return httpx.Response(200, json={'keys': [jwk]})
        original = record()
        return httpx.Response(200, json={'token_type': 'Bearer',
            'scope': ' '.join(original['scopes']), 'expires_in': 3600,
            'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh',
            'id_token': token(nonce=flow.nonce, sub='different-subject', email=EMAIL)})

    before = (tmp_path / 'credentials.json').read_bytes()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(WorkspaceDenied):
            flow.complete(client, {'state': flow.state, 'code': 'synthetic-code'})
    assert flow.consumed
    assert (tmp_path / 'credentials.json').read_bytes() == before


@pytest.mark.parametrize('withdraw', [False, True])
def test_explicit_local_chatgpt_adapter_gets_current_authority_guard(growth, monkeypatch, withdraw):
    g = growth
    seen = []

    def propose(self, envelope, *, _guard=None):
        assert _guard is not None
        if withdraw:
            with g.w.store.tx() as db:
                db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?', (g.w.ws,))
        _guard()
        seen.append(envelope)
        return graph(g.w)

    monkeypatch.setattr(ChatGPTGraphProposer, 'propose', propose)
    g.factory.model_proposer = ChatGPTGraphProposer('not-read-in-synthetic-test')
    if withdraw:
        with pytest.raises((WorkspaceConflict, WorkspaceDenied)):
            g.factory.prepare_model_proposal(g.w.ws, request(), g.w.actor)
        assert not seen
    else:
        review = g.factory.prepare_model_proposal(g.w.ws, request(), g.w.actor)
        assert len(seen) == 1 and review['definition'] == graph(g.w)
    assert not g.w.calls

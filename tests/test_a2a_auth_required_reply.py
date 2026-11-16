"""PM 11-17 02:2x: an A2A agent whose message answer asks for the provider's own authorization is recorded as
needing authorization, so keyless recommendation and connection candidates leave it (not one listing by id).

Before, only "an API key is required" phrases counted; a 401/403, a JSON-RPC error saying "Unauthorized", or the
A2A task state auth-required left the agent recorded as open.
"""
import json

import httpx
import pytest

from agent_market.collector.a2a import AgentProber, card_hash, normalize_card
from agent_market.collector.auth_discovery import asks_for_auth
from agent_market.gateway.store import Store
from tests.test_a2a_key_required import CARD, CARD_URL


@pytest.mark.parametrize("text", [
    "Unauthorized",
    '{"code": -32000, "message": "Not authorized: sign in first"}',
    "Authentication required. Connect your workspace at https://example.com/connect",
    "This connection requires separate provider authorization.",
    "This action requires an account. Sign up at https://example.com",
    "Provide an API key via Authorization: Bearer <key>",          # asks_for_key still counts
])
def test_replies_that_ask_for_authorization(text):
    assert asks_for_auth(text)


@pytest.mark.parametrize("text", [
    "No authentication required: send A2A requests directly.",
    "Crypto.com Market Data. Access: No account or API key required; public market data only.",
    "The swap requires a token address and an amount.",
    "Meeting overlap for New York and Seoul: 08:00-09:00 KST.",
    "Save the access token now, then use the returned endpoint.",
    None,
])
def test_replies_that_do_not(text):
    assert not asks_for_auth(text)


def transport(answer):
    class Agent(httpx.BaseTransport):
        def handle_request(self, request):
            if request.method == "GET":
                if str(request.url) == CARD_URL:
                    return httpx.Response(200, json=CARD, headers={"content-type": "application/json"})
                return httpx.Response(404)
            body = json.loads(request.content)
            if body["method"] != "message/send":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            return answer()
    return Agent()


def survey(answer, trial_info=None):
    store = Store()
    rid = store.upsert_resource({"key": f"a2a:{CARD_URL}", "source": "well-known", "kind": "a2a", "url": CARD_URL,
                                 "name": "agent", "description": "an agent", "category": "productivity", "networks": [],
                                 "price_usdc": 0, "details": {"agent_card": CARD_URL}})
    if trial_info is not None:
        with store.tx() as db:
            db.execute("UPDATE resources SET trial_info=?, usage_tools_hash=? WHERE id=?",
                       (json.dumps(trial_info), card_hash(normalize_card(CARD, CARD_URL)), rid))
    http = httpx.Client(transport=transport(answer))
    return AgentProber(store, http=http, allow_private=True, per_host_delay=0).survey(store.resource(rid), http)


def task(state, text):
    return lambda: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
        "id": "t-1", "contextId": "c-1", "status": {"state": state},
        "artifacts": [{"name": "a", "parts": [{"kind": "text", "text": text}]}]}})


@pytest.mark.parametrize("answer", [
    lambda: httpx.Response(401, json={"error": "unauthorized"}),
    lambda: httpx.Response(403, text="forbidden"),
    lambda: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "Unauthorized"}}),
    task("auth-required", "Connect your account first."),
    task("completed", "Authentication required. Connect your workspace at https://example.com/connect"),
])
def test_an_answer_that_asks_for_authorization_marks_the_agent_as_needing_it(answer):
    s = survey(answer)
    assert s["trial"]["ok"] is False and s["trial"]["key_required"] is True
    assert s["auth_required"] is True and s["auth"]["method"] == "api_key" and s["auth"]["autonomy"] == "human_once"
    assert s["auth"]["info"]["observed_in"] == "agent_reply"


def test_a_recorded_auth_required_state_counts_without_messaging_again():
    sent = []

    def answer():
        sent.append(1)
        return task("completed", "fine")()
    recorded = {"ok": False, "state": "auth-required", "at": 9e18, "error": "Task is not completed: auth-required."}
    s = survey(answer, recorded)
    assert sent == [] and s["trial"] is None and s["auth_required"] is True


def test_a_working_answer_stays_open():
    s = survey(task("completed", "Brand intelligence: Nike is expanding its running line this quarter."))
    assert s["auth_required"] is False and s["auth"]["method"] == "none"

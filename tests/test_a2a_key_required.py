"""An agent whose own answer asks for an API key is not recorded as open (PM 11-13 20:3x, a07 Fodda).

Fodda's card declares no security scheme, so auth_method was 'none' and its trial counted as working, while the
answer itself said "Provide an API key via Authorization: Bearer <key>". The phrase list is narrow (see
auth_discovery.asks_for_key) and a negation just before it does not count.
"""
import json

import httpx
import pytest

from agent_market.collector.a2a import AgentProber
from agent_market.collector.auth_discovery import asks_for_key
from agent_market.gateway.store import Store

CARD = {
    "name": "Trend Agent", "description": "Brand and trend intelligence for agents about consumer brands.",
    "url": "https://trend.example/a2a", "preferredTransport": "JSONRPC", "protocolVersion": "0.3.0", "version": "1.0.0",
    "capabilities": {}, "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
    "skills": [{"id": "brand", "name": "Brand intelligence", "description": "What a brand is doing now.",
                "tags": ["brand"], "examples": ["What is Nike doing?"]}],
}
CARD_URL = "https://trend.example/.well-known/agent-card.json"
FODDA = ("Fodda A2A endpoint is operational. Provide an API key via Authorization: Bearer <key> for full access "
         "to trend intelligence. Get a key at https://app.fodda.ai")


@pytest.mark.parametrize("text", [
    FODDA,
    '{"error": "Missing API key. Provide X-Nefesh-Key header or Authorization: Bearer token."}',
    'API Error: Status 403 (Forbidden). Response: {"message":"API Key is required"}',
    "This tool requires an API key to identify your org context.",
    '{"authentication":"tenant-scoped x-api-key required for customer data"}',
])
def test_replies_that_ask_for_a_key(text):
    assert asks_for_key(text)


@pytest.mark.parametrize("text", [
    "Crypto.com Market Data. Access: No account or API key required; public market data only.",
    "Frontera Signal sells data per call over x402: USDC on Base, no account and no API key",
    "Without an API key, add a data part {\"contactEmail\": \"...\"} for the business.",
    "5 providers: Vercel Sandbox, E2B. Send your API key to see saved keys.",
    "3 of 3 free ID photos left today. For more, get an API key at https://idphoto.example",
    "Clean: no live secrets found. Did I leak an API key in this code?",
    "Save the access token now, then use the returned endpoint.",
    None,
])
def test_replies_that_do_not(text):
    assert not asks_for_key(text)


class Agent(httpx.BaseTransport):
    def handle_request(self, request):
        if request.method == "GET":
            if str(request.url) == CARD_URL:
                return httpx.Response(200, json=CARD, headers={"content-type": "application/json"})
            return httpx.Response(404)
        body = json.loads(request.content)
        if body["method"] == "tasks/get":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "Task not found"}})
        # A Task without "kind", as Fodda answers.
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
            "id": "task-1", "contextId": "ctx-1", "status": {"state": "completed"},
            "artifacts": [{"name": "health_check", "parts": [{"kind": "text", "text": FODDA}]}]}})


def survey(trial_info=None):
    store = Store()
    rid = store.upsert_resource({"key": f"a2a:{CARD_URL}", "source": "well-known", "kind": "a2a", "url": CARD_URL,
                                 "name": "agent", "description": "an agent", "category": "productivity", "networks": [],
                                 "price_usdc": 0, "details": {"agent_card": CARD_URL}})
    if trial_info is not None:   # a recent trial of the same card: no new message is sent
        from agent_market.collector.a2a import card_hash, normalize_card
        with store.tx() as db:
            db.execute("UPDATE resources SET trial_info=?, usage_tools_hash=? WHERE id=?",
                       (json.dumps(trial_info), card_hash(normalize_card(CARD, CARD_URL)), rid))
    http = httpx.Client(transport=Agent())
    prober = AgentProber(store, http=http, allow_private=True, per_host_delay=0)
    return prober.survey(store.resource(rid), http)


def test_a_fresh_trial_that_is_asked_for_a_key_marks_the_agent_keyed():
    s = survey()
    assert s["trial"]["ok"] is False and s["trial"]["key_required"] is True
    assert s["auth"]["method"] == "api_key" and s["auth"]["autonomy"] == "human_once" and s["auth_required"] is True
    assert s["auth"]["info"]["observed_in"] == "agent_reply"


def test_a_recorded_trial_that_asked_for_a_key_counts_without_messaging_again():
    import time
    s = survey({"skill": "brand", "message": "What is Nike doing?", "at": time.time(), "state": "completed", "ok": True,
                "sample_output": FODDA})
    assert s["trial"] is None
    assert s["auth"]["method"] == "api_key" and s["auth_required"] is True

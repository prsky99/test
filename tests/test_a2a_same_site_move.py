"""A card that its own server moves between example.com and www.example.com stays reachable (PM 11-13 20:3x, a02).

www.agentreeve.com/.well-known/agent-card.json answers 301/308 to agentreeve.com; the gateway never follows redirects,
so the agent was unreachable while the apex answered SendMessage in 0.48 s. The collector now follows that one
same-site move and records the final card, and the origin checks count www and the apex as one site. Any other
redirect is still not followed.
"""
import json

import httpx
import pytest

from agent_market.collector.a2a import AgentProber
from agent_market.concierge.execution_policy import ExecutionDenied, resolve_a2a
from agent_market.concierge.recommendation_security import same_site_origin
from agent_market.gateway.store import Store

CARD = {
    "name": "Crypto Agent", "description": "Crypto market data for agents: prices and funding across exchanges.",
    "supportedInterfaces": [{"url": "https://agentreeve.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
    "version": "1.0.0", "capabilities": {"streaming": False}, "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [{"id": "free_preview", "name": "Free preview", "description": "BTC spot and futures preview.", "tags": ["btc"]}],
}
WWW = "https://www.agentreeve.example/.well-known/agent-card.json"
APEX = "https://agentreeve.example/.well-known/agent-card.json"


class Moves(httpx.BaseTransport):
    def __init__(self, status=308, location=APEX):
        self.status, self.location, self.gets = status, location, []

    def handle_request(self, request):
        url = str(request.url)
        if request.method == "GET":
            self.gets.append(url)
            if url == WWW:
                return httpx.Response(self.status, headers={"location": self.location})
            if url in (APEX, "https://other.example/.well-known/agent-card.json"):
                return httpx.Response(200, json=CARD, headers={"content-type": "application/json"})
            return httpx.Response(404)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "Task not found"}})


def card_for(transport):
    store = Store()
    rid = store.upsert_resource({"key": f"a2a:{WWW}", "source": "well-known", "kind": "a2a", "url": WWW, "name": "agent",
                                 "description": "an agent", "category": "finance", "networks": [], "price_usdc": 0,
                                 "details": {"agent_card": WWW}})
    http = httpx.Client(transport=transport)
    prober = AgentProber(store, http=http, allow_private=True, per_host_delay=0)
    return prober.fetch_card(http, store.resource(rid))


def test_same_site_origin_ignores_one_leading_www_only():
    assert same_site_origin("https://agentreeve.com/a2a", "https://www.agentreeve.com/.well-known/agent-card.json")
    assert same_site_origin("https://www.agentreeve.com/a2a", "https://agentreeve.com/x")
    assert same_site_origin("https://a.example/a2a", "https://a.example/card.json")
    assert not same_site_origin("https://evil.com/a2a", "https://www.agentreeve.com/card.json")
    assert not same_site_origin("https://api.agentreeve.com/a2a", "https://www.agentreeve.com/card.json")
    assert not same_site_origin("http://agentreeve.com/a2a", "https://www.agentreeve.com/card.json")
    assert not same_site_origin("https://agentreeve.com:8443/a2a", "https://www.agentreeve.com/card.json")
    assert not same_site_origin("https://com/a2a", "https://www.com/card.json")      # no bare public suffix
    assert not same_site_origin("https://agentreeve.com/a2a", None)


@pytest.mark.parametrize("status", [301, 308])
def test_a_permanent_move_to_the_apex_is_followed_once_and_recorded(status):
    transport = Moves(status)
    card, meta, err = card_for(transport)
    assert err is None and card["card_url"] == APEX
    assert meta["moved"] == {"from": WWW, "to": APEX, "status": status}
    assert transport.gets.count(APEX) == 1


@pytest.mark.parametrize("status,location", [
    (302, APEX),                                                   # temporary moves are not followed
    (307, APEX),
    (308, "https://other.example/.well-known/agent-card.json"),    # another site
    (308, "https://agentreeve.example/agent-card.json"),           # another path
    (308, "https://agentreeve.example/.well-known/agent-card.json?x=1"),
])
def test_any_other_redirect_is_not_followed(status, location):
    transport = Moves(status, location)
    card, meta, err = card_for(transport)
    assert card is None and "moved" not in meta
    assert "https://other.example/.well-known/agent-card.json" not in transport.gets


class Courier:
    def resolve(self, ctype, url, public_only=False):
        return {"url": url, "v1": True}


def resource(endpoint):
    return {"url": WWW, "details": json.dumps({"agent_card": WWW}),
            "usage_guide": json.dumps({"endpoint": endpoint, "binding": "JSONRPC", "spec_version": "1.0",
                                       "methods": {"send": "SendMessage"}})}


def test_execution_accepts_the_apex_endpoint_of_a_www_registration_and_nothing_wider():
    assert resolve_a2a(resource("https://agentreeve.example/a2a"), Courier(), public=True)["url"] == "https://agentreeve.example/a2a"
    with pytest.raises(ExecutionDenied):
        resolve_a2a(resource("https://other.example/a2a"), Courier(), public=True)
    with pytest.raises(ExecutionDenied):
        resolve_a2a(resource("https://api.agentreeve.example/a2a"), Courier(), public=True)

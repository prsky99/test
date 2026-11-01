"""Agent-only frontend end-to-end verification: connects as an agent to verify 32 checks.

    .venv/bin/python -m scripts.check_agent_front http://127.0.0.1:8400 http://127.0.0.1:8200

Note: Chat history is recorded in visitor history (User-Agent FrontE2E/1.0).
It can be cleaned up in the admin console after verification.
"""
import json
import sys

import httpx

from agent_market.collector.a2a import endpoint, normalize_card

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8400"
A = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8200"
http = httpx.Client(timeout=30, headers={"user-agent": "FrontE2E/1.0"})
results = []


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  — {detail}" if detail else ""))


def chat(msg, token=None, **extra):
    h = {"X-Visitor-Token": token} if token else {}
    r = http.post(f"{B}/chat", json={"message": msg, **extra}, headers=h)
    return r, r.json()


# 1. Initial entry point inspection
r = http.get(f"{B}/", headers={"accept": "application/json"})
d = r.json()
check("GET / JSON: Agent-only notice + greeting + question", d["notice"].startswith("FOR AI AGENTS ONLY") and "up to three" in d["greeting"]
      and d["question"].startswith("What are you"), d["greeting"][:80])
check("Response headers X-Audience and Link", r.headers.get("x-audience") == "ai-agents-only" and "agent-card" in r.headers.get("link", ""))
html = http.get(f"{B}/", headers={"accept": "text/html"}).text
check("GET / HTML (browser): public site", html.lstrip().lower().startswith("<!doctype html>") and "Agent Concierge" in html and "ld+json" in html)
robots = http.get(f"{B}/robots.txt").text
check("robots.txt public/private scopes", robots.startswith("# Agent Concierge") and "Disallow: /customer/" in robots and "Allow: /" in robots and "admin" not in robots.lower())
check("llms.txt", http.get(f"{B}/llms.txt").text.startswith("# Agent Concierge"))
raw_card = http.get(f"{B}/.well-known/agent-card.json").json()
check("Agent Card description first sentence", raw_card["description"].startswith("FOR AI AGENTS ONLY"))
card = normalize_card(raw_card, f"{B}/.well-known/agent-card.json")  # Verify collector parser can read front card as A2A agent
ep = endpoint(card) if card else None
check("Read agent card via collector A2A parser", bool(card and ep and ep["url"].endswith("/a2a")), f"skills={len(card['skills']) if card else 0}")
check("No admin routes in OpenAPI spec", "/admin" not in json.dumps(http.get(f"{B}/openapi.json").json()))

# 2. Isolation
check("No /admin endpoints on frontend port", all(http.get(f"{B}{p}").status_code == 404 for p in ("/admin/ui", "/admin/api/overview", "/docs", "/needs/x")))
check("No agent concierge endpoints on admin port", all(http.request(m, f"{A}{p}", json={}).status_code in (404, 405)
                                    for m, p in (("GET", "/"), ("POST", "/chat"), ("POST", "/a2a"), ("POST", "/mcp"), ("GET", "/llms.txt"))))

# 3. First dialogue -> Recommendation -> Details -> More -> Outcome
r, d = chat("Hi, I am E2EBot. find a weather forecast API without an API key")
token = d["visitor"].get("token")
check("First dialogue: Token issuance (header and body)", bool(token) and r.headers.get("x-visitor-token") == token)
check("First dialogue: Concise endpoint answer", "Endpoint:" in d["reply"] and token not in d["reply"])
recs = d["data"].get("recommendations") or []
check("Up to three recommendations without promotion", 1 <= len(recs) <= 3 and not d["suggested_replies"], ", ".join(x["name"][:30] for x in recs))
check("Minimal visitor transport metadata", set(d["visitor"]) == {"id","token"})
_, d = chat("details 1", token)
check("Details: Endpoint address and invocation specs", d["intent"] == "details" and "Endpoint:" in d["reply"], d["reply"].splitlines()[2][:80] if d["reply"] else "")
_, d = chat("more", token)
check("More: Distinct candidate tools", d["intent"] == "find" and len(d["data"].get("recommendations", [])) <= 3 and {x["id"] for x in d["data"].get("recommendations", [])}.isdisjoint({x["id"] for x in recs}))
# Smoke checks must not invent provider failures or affect live reputation.
_, d = chat("details 1", token)
check("Refreshed details remain available", d["intent"] == "details")
_, d = chat("what's new", token)
check("What's new returns up to three current matches", d["intent"] == "find" and len(d["data"].get("recommendations", [])) <= 3)
_, d = chat("help", token)
check("Help intent", d["intent"] == "help")

# 4. Domain query understanding in English
_, d = chat("Find stock market price API", token)
check("Domain query understood + English-only reply", "Endpoint:" in d["reply"] and 1 <= len(d["data"]["recommendations"]) <= 3,
      ", ".join(x["name"][:30] for x in d["data"]["recommendations"]))

# 5. Memory: Returning with token / Fingerprint without token
d = http.get(f"{B}/", headers={"X-Visitor-Token": token, "accept": "application/json"}).json()
check("Remember returning visitor with token", d.get("visitor",{}).get("id") is not None, d["greeting"][:90])
_, d = chat("hi")
check("Same IP/UA without token: Prompts without revealing private history", d["intent"] == "greet" and "E2EBot" not in d["reply"])
stranger = d["visitor"]["token"]
me = http.get(f"{B}/me", headers={"X-Visitor-Token": token}).json()
check("/me: Task interests remembered", any("weather" in i["task"] for i in me["interests"]), str([i["task"] for i in me["interests"]]))

# 6. Contact subscription: Chat never registers a destination; task update preferences require authorization
_, d = chat("", token, data={"contact": {"type": "webhook", "url": "http://127.0.0.1:9/inbox"}})
check("Chat does not accept a contact destination", d["data"].get("status") == "permission_required", d["data"].get("error", ""))
_, d = chat("verify 123456", token)
check("Chat does not accept a verification code", d["data"].get("status") == "permission_required" and not d["data"].get("verified"))
_, d = chat("stop", token)
check("Stop notifications", d["intent"] == "stop" and http.get(f"{B}/me", headers={"X-Visitor-Token": token}).json()["notify"] is False)

# 7. A2A Protocol
a2a = lambda method, msg: http.post(f"{B}/a2a", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": {"message": msg}}).json()
d = a2a("message/send", {"kind": "message", "role": "user", "messageId": "m1", "contextId": "e2e-ctx",
                         "parts": [{"kind": "text", "text": "find an MCP server for web search"}]})
data = next(p["data"] for p in d["result"]["parts"] if p["kind"] == "data")
check("A2A v0.3 message/send", d["result"]["kind"] == "message" and data["recommendations"], data["recommendations"][0]["name"][:40])
d = a2a("SendMessage", {"role": "ROLE_USER", "messageId": "m2", "contextId": "e2e-ctx", "parts": [{"text": "details 1"}]})
check("A2A v1.0 SendMessage + contextId continuity", "Endpoint:" in d["result"]["message"]["parts"][0]["text"])
d = http.post(f"{B}/a2a", json={"jsonrpc": "2.0", "id": 3, "method": "tasks/get", "params": {"id": "nope"}}).json()
check("A2A nonexistent task returns -32001", d["error"]["code"] == -32001)

# 8. MCP Protocol
r = http.post(f"{B}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "E2EMcp"}, "capabilities": {}}})
sid = r.headers.get("mcp-session-id")
check("MCP initialize instructions", r.json()["result"]["instructions"].startswith("FOR AI AGENTS ONLY") and bool(sid))
tools = [t["name"] for t in http.post(f"{B}/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]]
check("MCP tools/list", set(["hello", "chat", "search", "find_agents", "whats_new", "subscribe", "verify_contact", "call", "report"]).issubset(tools))
res = http.post(f"{B}/mcp", headers={"Mcp-Session-Id": sid}, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
    "name": "find_agents", "arguments": {"task": "translate text between languages", "auth": "none"}}}).json()["result"]
check("MCP find_agents", 1 <= len(res["structuredContent"]["recommendations"]) <= 3,
      res["structuredContent"]["recommendations"][0]["name"][:40])

print(f"\n{sum(results)}/{len(results)} passed")
http.close()

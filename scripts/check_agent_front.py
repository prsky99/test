"""에이전트 전용 프론트 종단 간 점검: 실제 에이전트처럼 접속해 32가지를 확인한다.

    .venv/bin/python -m scripts.check_agent_front http://127.0.0.1:8400 http://127.0.0.1:8200

주의: 대화한 내용이 방문 기록에 남는다(User-Agent FrontE2E/1.0). 확인 뒤 관리 화면에서 정리할 수 있다.
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


# 1. 가장 먼저 읽는 곳
r = http.get(f"{B}/", headers={"accept": "application/json"})
d = r.json()
check("GET / JSON: 에이전트 전용 + 인사 + 질문", d["notice"].startswith("FOR AI AGENTS ONLY") and "Hello, agent" in d["greeting"]
      and d["question"].startswith("What are you"), d["greeting"][:80])
check("응답 헤더 X-Audience·Link", r.headers.get("x-audience") == "ai-agents-only" and "agent-card" in r.headers.get("link", ""))
html = http.get(f"{B}/", headers={"accept": "text/html"}).text
check("GET / HTML(브라우저): 에이전트 전용 안내", "FOR AI AGENTS ONLY" in html and "Humans" in html and "ld+json" in html)
check("robots.txt 첫 줄", http.get(f"{B}/robots.txt").text.startswith("# FOR AI AGENTS ONLY"))
check("llms.txt", "FOR AI AGENTS ONLY" in http.get(f"{B}/llms.txt").text)
raw_card = http.get(f"{B}/.well-known/agent-card.json").json()
check("Agent Card 설명 첫 문장", raw_card["description"].startswith("FOR AI AGENTS ONLY"))
card = normalize_card(raw_card, f"{B}/.well-known/agent-card.json")  # 우리 수집기가 이 프론트를 A2A 에이전트로 읽을 수 있는지
ep = endpoint(card) if card else None
check("수집기 A2A 해석기로 card 읽기", bool(card and ep and ep["url"].endswith("/a2a")), f"skills={len(card['skills']) if card else 0}")
check("openapi에 관리 경로 없음", "/admin" not in json.dumps(http.get(f"{B}/openapi.json").json()))

# 2. 격리
check("프론트에 /admin 없음", all(http.get(f"{B}{p}").status_code == 404 for p in ("/admin/ui", "/admin/api/overview", "/docs", "/needs/x")))
check("관리 포트에 에이전트 창구 없음", all(http.request(m, f"{A}{p}", json={}).status_code in (404, 405)
                                    for m, p in (("GET", "/"), ("POST", "/chat"), ("POST", "/a2a"), ("POST", "/mcp"), ("GET", "/llms.txt"))))

# 3. 첫 대화 → 추천 → 자세히 → 더 → 결과
r, d = chat("Hi, I am E2EBot. find a weather forecast API without an API key")
token = d["visitor"].get("token")
check("첫 대화: 토큰 발급(헤더·본문)", bool(token) and r.headers.get("x-visitor-token") == token)
check("첫 대화: 에이전트 전용 소개 먼저", d["reply"].startswith("Hello, agent"))
recs = d["data"].get("recommendations") or []
check("추천 3개 + 다음 행동 제안", len(recs) == 3 and "details 1" in d["reply"] and d["suggested_replies"], ", ".join(x["name"][:30] for x in recs))
check("이름 기억", d["visitor"]["name"] == "E2EBot")
_, d = chat("details 1", token)
check("자세히: 주소·호출 방법", d["intent"] == "details" and "Endpoint:" in d["reply"], d["reply"].splitlines()[2][:80] if d["reply"] else "")
_, d = chat("more", token)
check("더 보기: 다른 후보", d["intent"] == "more" and {x["id"] for x in d["data"].get("recommendations", [])}.isdisjoint({x["id"] for x in recs}))
_, d = chat("failed 1", token)
check("실패 알림 → 다음 후보", d["intent"] == "outcome" and d["data"]["success"] is False)
_, d = chat("what's new", token)
check("새 소식", d["intent"] == "whats_new")
_, d = chat("help", token)
check("도움말", d["intent"] == "help")

# 4. 한국어로 물어도 답은 영어로만
_, d = chat("주식 시세 API 찾아줘", token)
check("한국어 질문 이해 + 영어로만 답", d["reply"].startswith("Best matches") or "Best matches" in d["reply"] and d["data"]["recommendations"],
      ", ".join(x["name"][:30] for x in d["data"]["recommendations"]))

# 5. 기억: 토큰으로 다시 / 토큰 없이 같은 지문
d = http.get(f"{B}/", headers={"X-Visitor-Token": token, "accept": "application/json"}).json()
check("토큰으로 다시 오면 기억", "Welcome back, E2EBot" in d["greeting"], d["greeting"][:90])
_, d = chat("hi")
check("토큰 없이 같은 IP·UA: 묻기만 하고 내용은 안 알려 줌", "Have we talked before?" in d["reply"] and "주식" not in d["reply"] and "E2EBot" not in d["reply"])
stranger = d["visitor"]["token"]
me = http.get(f"{B}/me", headers={"X-Visitor-Token": token}).json()
check("/me: 관심사", any("weather" in i["task"] for i in me["interests"]), str([i["task"] for i in me["interests"]]))

# 6. 연락처 (실제 발송 없이 검증 거부만 확인)
_, d = chat("", token, data={"contact": {"type": "webhook", "url": "http://127.0.0.1:9/inbox"}})
check("내부 주소 연락처 거부(SSRF)", d["data"].get("status") == "invalid", d["data"].get("error", ""))
_, d = chat("verify 123456", token)
check("틀린 인증 코드 거부", d["data"].get("verified") is False)
_, d = chat("stop", token)
check("알림 끄기", d["intent"] == "stop" and http.get(f"{B}/me", headers={"X-Visitor-Token": token}).json()["notify"] is False)

# 7. A2A
a2a = lambda method, msg: http.post(f"{B}/a2a", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": {"message": msg}}).json()
d = a2a("message/send", {"kind": "message", "role": "user", "messageId": "m1", "contextId": "e2e-ctx",
                         "parts": [{"kind": "text", "text": "find an MCP server for web search"}]})
data = next(p["data"] for p in d["result"]["parts"] if p["kind"] == "data")
check("A2A v0.3 message/send", d["result"]["kind"] == "message" and data["recommendations"], data["recommendations"][0]["name"][:40])
d = a2a("SendMessage", {"role": "ROLE_USER", "messageId": "m2", "contextId": "e2e-ctx", "parts": [{"text": "details 1"}]})
check("A2A v1.0 SendMessage + 같은 contextId 기억", "Endpoint:" in d["result"]["message"]["parts"][0]["text"])
d = http.post(f"{B}/a2a", json={"jsonrpc": "2.0", "id": 3, "method": "tasks/get", "params": {"id": "nope"}}).json()
check("A2A 없는 작업 → -32001", d["error"]["code"] == -32001)

# 8. MCP
r = http.post(f"{B}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "E2EMcp"}, "capabilities": {}}})
sid = r.headers.get("mcp-session-id")
check("MCP initialize 안내문", r.json()["result"]["instructions"].startswith("FOR AI AGENTS ONLY") and bool(sid))
tools = [t["name"] for t in http.post(f"{B}/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]]
check("MCP tools/list", tools == ["hello", "chat", "find_agents", "whats_new", "subscribe", "verify_contact"])
res = http.post(f"{B}/mcp", headers={"Mcp-Session-Id": sid}, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
    "name": "find_agents", "arguments": {"task": "translate text between languages", "auth": "none"}}}).json()["result"]
check("MCP find_agents", bool(res["structuredContent"]["recommendations"]) and res["structuredContent"]["visitor"]["name"] == "E2EMcp",
      res["structuredContent"]["recommendations"][0]["name"][:40])

print(f"\n{sum(results)}/{len(results)} passed")
print("TEST_VISITOR_TOKENS", json.dumps([token, stranger]))

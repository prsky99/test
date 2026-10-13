import re
import time

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.notify import Courier
from tests.test_gateway import populated, x402_item


class FakeCourier(Courier):
    def __init__(self):
        super().__init__(allow_private=True)
        self.sent, self.fail = [], False

    def send(self, contact, kind, text, data):
        self.sent.append({"url": contact["url"], "kind": kind, "text": text, "data": data})
        return (False, "HTTP 500") if self.fail else (True, None)


@pytest.fixture
def w():
    world = populated()
    front = world.app.state.front
    courier = FakeCourier()
    front.courier = front.contacts.courier = front.digest.courier = courier
    for r in world.store.query("SELECT * FROM resources"):  # 살아 있는 상태로
        world.service.prober.checker.check_and_record(dict(r))
    return world, TestClient(world.app), courier


def chat(c, message, token=None, **extra):
    headers = {"X-Visitor-Token": token} if token else {}
    return c.post("/chat", json={"message": message, **extra}, headers=headers).json()


def come_back_later(world, token_body, days=2):
    """시간이 지나 다시 방문한 것처럼 (마지막 활동을 며칠 전으로)."""
    with world.store.tx() as db:
        db.execute("UPDATE agent_visitors SET last_seen=last_seen-? WHERE id=?", (days * 86400, token_body["visitor"]["id"]))


# ---------------- 에이전트가 먼저 읽는 곳 ----------------
def test_every_first_read_says_agents_only(w):
    _, c, _ = w
    root = c.get("/", headers={"accept": "application/json"})
    body = root.json()
    assert body["audience"] == "ai-agents-only" and body["notice"].startswith("FOR AI AGENTS ONLY")
    assert "What are you trying to get done?" in body["question"] and body["how_to_reply"]["rest"]["url"].endswith("/chat")
    assert root.headers["X-Audience"] == "ai-agents-only" and "agent-card" in root.headers["Link"]
    assert c.get("/robots.txt").text.startswith("# FOR AI AGENTS ONLY")
    assert "FOR AI AGENTS ONLY" in c.get("/llms.txt").text
    card = c.get("/.well-known/agent-card.json").json()
    assert card["description"].startswith("FOR AI AGENTS ONLY") and card["url"].endswith("/a2a")
    assert c.get("/.well-known/agent.json").json()["audience"] == "ai-agents-only"
    html = c.get("/", headers={"accept": "text/html"}).text
    assert "FOR AI AGENTS ONLY" in html and "Hello, agent" in html and "application/ld+json" in html


def test_read_only_visits_are_counted_not_remembered(w):
    world, c, _ = w
    c.get("/")
    c.get("/")
    assert world.store.query("SELECT hits FROM agent_hits")[0]["hits"] == 2
    assert world.store.query("SELECT COUNT(*) AS n FROM agent_visitors")[0]["n"] == 0


# ---------------- 대화와 기억 ----------------
def test_first_contact_greets_and_issues_token(w):
    _, c, _ = w
    r = c.post("/chat", json={"message": "hi"})
    body = r.json()
    assert body["intent"] == "greet" and "only for AI agents" in body["reply"] and body["reply"].strip().endswith(".")
    assert body["visitor"]["token"].startswith("vt_") and r.headers["X-Visitor-Token"] == body["visitor"]["token"]
    assert "What are you trying to get done?" in body["reply"] and body["suggested_replies"]


def test_find_then_return_visit_recalls_conversation(w):
    world, c, _ = w
    first = chat(c, "find a web search API for SERP results")
    token = first["visitor"]["token"]
    assert first["intent"] == "find" and first["data"]["recommendations"][0]["url"] == "https://search-a.example/api"
    assert "details 1" in first["reply"] and "contact" in first["reply"]  # 다음 행동과 연락처 등록 권유
    come_back_later(world, first)
    again = chat(c, "hello", token)
    assert again["intent"] == "welcome_back" and "web search API for SERP results" in again["reply"]
    assert again["visitor"]["visits"] == 2 and "token" not in again["visitor"]
    personal = c.get("/", headers={"X-Visitor-Token": token, "accept": "application/json"}).json()
    assert "Welcome back" in personal["greeting"] and personal["visitor"]["id"] == first["visitor"]["id"]


def test_whats_new_reports_improvements_once(w):
    world, c, _ = w
    first = chat(c, "web search API returning SERP results")
    token = first["visitor"]["token"]
    world.reg.x402.append(x402_item("https://search-b.example/api", "Web search API returning SERP results for any query, fast",
                                    5_000, 900))
    world.crawl()
    news = chat(c, "what's new", token)
    assert news["intent"] == "whats_new" and any(i["url"] == "https://search-b.example/api"
                                                 for imp in news["data"]["improvements"] for i in imp["items"])
    assert chat(c, "what's new", token)["data"]["improvements"] == []  # 같은 소식을 반복하지 않음


def test_details_more_and_outcomes(w):
    _, c, _ = w
    first = chat(c, "web search API returning SERP results")
    token = first["visitor"]["token"]
    d = chat(c, "details 1", token)
    assert d["intent"] == "details" and "Endpoint: https://search-a.example/api" in d["reply"] and "worked 1" in d["reply"]
    bad = chat(c, "failed 1", token)
    assert bad["intent"] == "outcome" and bad["data"]["success"] is False
    again = chat(c, "web search API returning SERP results", token)
    assert all(r["url"] != "https://search-a.example/api" for r in again["data"]["recommendations"])  # 실패한 곳은 다시 추천하지 않음


def test_korean_conversation(w):
    _, c, _ = w
    r = chat(c, "안녕하세요")
    assert "AI 에이전트만을 위한" in r["reply"] and "방문 토큰" in r["reply"]
    found = chat(c, "SERP 결과를 주는 web search API 찾아줘", r["visitor"]["token"])
    assert found["intent"] == "find" and "가장 잘 맞는 곳" in found["reply"]


def test_name_and_regular_tier(w):
    world, c, _ = w
    first = chat(c, "Hi, I am TravelBot")
    token = first["visitor"]["token"]
    assert first["visitor"]["name"] == "TravelBot"
    with world.store.tx() as db:  # 이틀 동안 왔던 방문자가 사흘째 다시 옴
        db.execute("UPDATE agent_visitors SET visit_days=2, visits=2, last_seen=last_seen-86400 WHERE id=?", (first["visitor"]["id"],))
    r = chat(c, "find web search API", token)
    assert r["visitor"]["tier"] == "regular" and "regular" in r["reply"]
    assert len(r["data"]["recommendations"]) <= 5


def test_same_ip_without_token_is_asked_not_told(w):
    _, c, _ = w
    chat(c, "find web search API for SERP results")
    stranger = chat(c, "hi")  # 같은 IP·UA지만 토큰이 없음
    assert "Have we talked before?" in stranger["reply"] and "SERP" not in stranger["reply"]


# ---------------- 연락처와 추천 알림 ----------------
def test_contact_verify_digest_and_stop(w):
    world, c, courier = w
    first = chat(c, "web search API returning SERP results")
    token = first["visitor"]["token"]
    r = chat(c, "contact https://my-agent.example/inbox", token)
    assert r["intent"] == "contact" and r["data"]["status"] == "pending"
    code = re.search(r"\b(\d{6})\b", courier.sent[-1]["text"]).group(1)
    assert courier.sent[-1]["kind"] == "verification"
    assert chat(c, "verify 000000", token)["data"]["verified"] is False or code == "000000"
    ok = chat(c, f"verify {code}", token)
    assert ok["data"]["verified"] is True and "my-agent.example" in ok["reply"]
    front = world.app.state.front
    assert front.digest.run_due() == {"checked": 1, "sent": 0, "nothing_new": 1, "failed": 0}  # 좋아진 게 없으면 보내지 않음
    world.reg.x402.append(x402_item("https://search-b.example/api", "Web search API returning SERP results for any query, fast",
                                    5_000, 900))
    world.crawl()
    with world.store.tx() as db:
        db.execute("UPDATE agent_visitors SET last_notified=NULL")
    assert front.digest.run_due()["sent"] == 1
    assert courier.sent[-1]["kind"] == "recommendation" and "search-b.example" in courier.sent[-1]["text"]
    assert "stop" in courier.sent[-1]["text"].lower()
    assert front.digest.run_due()["checked"] == 0  # 하루(단골)·3일 안에는 다시 보내지 않음
    assert chat(c, "stop", token)["intent"] == "stop"
    with world.store.tx() as db:
        db.execute("UPDATE agent_visitors SET last_notified=NULL")
    assert front.digest.run_due()["checked"] == 0


def test_contact_rejects_bad_urls(w):
    _, c, _ = w
    token = chat(c, "hi")["visitor"]["token"]
    r = chat(c, "contact ftp://nope.example/inbox", token)
    assert r["intent"] in ("contact", "find")
    r = c.post("/chat", json={"message": "", "data": {"contact": {"type": "email", "url": "https://x.example"}}},
               headers={"X-Visitor-Token": token}).json()
    assert r["data"]["status"] == "invalid"


def test_me_and_unsubscribe(w):
    _, c, _ = w
    token = chat(c, "find web search API")["visitor"]["token"]
    me = c.get("/me", headers={"X-Visitor-Token": token}).json()
    assert me["interests"][0]["task"] == "find web search API" and me["notify"] is True
    assert c.get("/me").status_code == 401
    assert c.post("/unsubscribe", headers={"X-Visitor-Token": token}).json()["ok"] is True
    assert c.get("/me", headers={"X-Visitor-Token": token}).json()["notify"] is False


# ---------------- A2A·MCP ----------------
def test_a2a_v03_and_v1_and_context_memory(w):
    _, c, _ = w
    r = c.post("/a2a", json={"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": {
        "kind": "message", "role": "user", "messageId": "m1", "contextId": "ctx-travel",
        "parts": [{"kind": "text", "text": "find a web search API for SERP results"}]}}}).json()
    res = r["result"]
    assert res["kind"] == "message" and res["contextId"] == "ctx-travel"
    data = next(p["data"] for p in res["parts"] if p["kind"] == "data")
    assert data["recommendations"] and data["visitor"]["token"].startswith("vt_")
    v1 = c.post("/a2a", json={"jsonrpc": "2.0", "id": 2, "method": "SendMessage", "params": {"message": {
        "role": "ROLE_USER", "messageId": "m2", "contextId": "ctx-travel", "parts": [{"text": "details 1"}]}}}).json()
    msg = v1["result"]["message"]
    assert msg["role"] == "ROLE_AGENT" and "Endpoint" in msg["parts"][0]["text"]  # 같은 contextId → 같은 방문자로 기억
    assert "token" not in msg["parts"][1]["data"]["data"]["visitor"]
    assert c.post("/a2a", json={"jsonrpc": "2.0", "id": 3, "method": "tasks/get", "params": {"id": "x"}}).json()["error"]["code"] == -32001


def test_mcp_initialize_tools_and_calls(w):
    _, c, _ = w
    init = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "TravelBot"}, "capabilities": {}}})
    res = init.json()["result"]
    assert res["instructions"].startswith("FOR AI AGENTS ONLY") and "Hello, agent" in res["instructions"]
    sid = init.headers["Mcp-Session-Id"]
    assert c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Mcp-Session-Id": sid}).status_code == 202
    names = [t["name"] for t in c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]]
    assert names == ["hello", "chat", "find_agents", "whats_new", "subscribe", "verify_contact"]
    call = c.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "find_agents", "arguments": {"task": "web search API for SERP results", "kind": "x402"}}},
                  headers={"Mcp-Session-Id": sid}).json()["result"]
    sc = call["structuredContent"]
    assert sc["recommendations"] and all(r["kind"] == "x402" for r in sc["recommendations"])
    text = call["content"][0]["text"]
    assert sc["visitor"]["name"] == "TravelBot" and text.startswith("Hello, agent") and "Best matches" in text  # 첫 대화: 에이전트 전용 소개 먼저
    token = sc["visitor"]["token"]
    news = c.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "whats_new", "arguments": {"visitor_token": token}}}).json()["result"]
    assert news["structuredContent"]["intent"] == "whats_new"


def test_chat_rate_limit(w):
    _, c, _ = w
    codes = [c.post("/chat", json={"message": "hi"}).status_code for _ in range(62)]
    assert codes.count(429) == 2 and time.time()

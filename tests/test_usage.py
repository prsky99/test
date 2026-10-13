import json

import httpx
import pytest

from agent_market.collector import usage
from agent_market.collector.capabilities import CapabilityProber
from agent_market.gateway.store import Store
from tests.test_constraints import mcp_resource
from tests.test_gateway import GW_World

WEATHER = {"name": "get_weather", "description": "Current weather for a city",
           "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}
DELETE = {"name": "delete_all", "description": "Delete everything", "annotations": {"destructiveHint": True},
          "inputSchema": {"type": "object", "properties": {}}}
SEND = {"name": "send_message", "description": "Send a message",
        "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]}}
BY_ID = {"name": "get_order", "description": "Get an order",
         "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}


class FakeToolServer(httpx.BaseTransport):
    def __init__(self, tools, tool_result=None):
        self.tools, self.calls = tools, []
        self.tool_result = tool_result or {"content": [{"type": "text", "text": "Seoul: 18C, clear"}]}

    def handle_request(self, request):
        if request.method == "DELETE":
            return httpx.Response(204)
        body = json.loads(request.content or b"{}")
        self.calls.append(body.get("method"))
        if body.get("method") == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "s1"}, json={"jsonrpc": "2.0", "id": 1, "result": {
                "protocolVersion": "2025-06-18", "serverInfo": {"name": "weather", "version": "1.2"}, "instructions": "Use get_weather."}})
        if body.get("method") == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": {"tools": self.tools}})
        if body.get("method") == "tools/call":
            self.calls.append(("call", body["params"]["name"], body["params"]["arguments"]))
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 3, "result": self.tool_result})
        return httpx.Response(202)


def setup(tools, **kw):
    store = Store()
    rid = mcp_resource(store, "https://w.example/mcp", "Weather for any city")
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy', category='travel_maps_weather' WHERE id=?", (rid,))
    server = FakeToolServer(tools, **kw)
    prober = CapabilityProber(store, http=httpx.Client(transport=server), allow_private=True, per_host_delay=0)
    return store, rid, server, prober


def calls(server):
    return [c for c in server.calls if isinstance(c, tuple)]


# ---------------- 안전 규칙 ----------------

def test_safety_rules():
    tools = {t["name"]: t for t in usage.compact_tools([WEATHER, DELETE, SEND, BY_ID,
        {"name": "lookup_user", "inputSchema": {"properties": {"email": {"type": "string"}}, "required": ["email"]}},
        {"name": "post_tweet", "annotations": {"readOnlyHint": True}, "inputSchema": {"properties": {}}}])}
    assert usage.is_safe_tool(tools["get_weather"])
    assert not usage.is_safe_tool(tools["delete_all"])  # 파괴적 표시
    assert not usage.is_safe_tool(tools["send_message"])  # 전송 성격
    assert not usage.is_safe_tool(tools["lookup_user"])  # 개인정보 입력
    assert usage.is_safe_tool(tools["post_tweet"])  # 서버가 읽기 전용이라고 명시하면 따름
    assert usage.example_arguments(tools["get_order"]) is None  # id는 지어내지 않음
    assert usage.example_arguments(tools["get_weather"], "travel_maps_weather") == {"city": "Seoul"}


def test_hash_and_diff():
    a = usage.compact_tools([WEATHER, SEND])
    b = usage.compact_tools([{**WEATHER, "description": "Weather v2"}, BY_ID])
    assert usage.tools_hash(a) != usage.tools_hash(b)
    assert usage.diff_tools(a, b) == {"added": ["get_order"], "removed": ["send_message"], "changed": ["get_weather"]}


# ---------------- 실제 호출과 안내 ----------------

def test_trial_runs_safe_tool_and_builds_verified_guide():
    store, rid, server, prober = setup([DELETE, SEND, WEATHER])
    stats = prober.run_due()
    assert stats["trial_ok"] == 1
    assert calls(server) == [("call", "get_weather", {"city": "Seoul"})]  # 위험한 도구는 호출하지 않음
    r = store.resource(rid)
    guide = json.loads(r["usage_guide"])
    assert r["trial_ok"] == 1 and guide["server"] == {"name": "weather", "version": "1.2"}
    assert guide["verified_example"]["name"] == "get_weather"
    assert guide["verified_example"]["verified"]["sample_output"] == "Seoul: 18C, clear"
    assert guide["verified_example"]["example_request"]["params"] == {"name": "get_weather", "arguments": {"city": "Seoul"}}
    assert any("initialize" in step for step in guide["how_to_connect"]) and guide["tool_count"] == 3
    send = next(t for t in guide["tools"] if t["name"] == "send_message")
    assert send["example_request"]["params"]["arguments"] == {"to": "<string>"} and send["verified"] is None


def test_no_safe_tool_means_guide_without_trial():
    store, rid, server, prober = setup([SEND, BY_ID])
    stats = prober.run_due()
    assert calls(server) == [] and "trial_ok" not in stats
    r = store.resource(rid)
    assert r["usage_guide"] and r["trial_ok"] is None and json.loads(r["usage_guide"])["verified_example"] is None


def test_tool_error_marks_trial_failed():
    store, rid, server, prober = setup([WEATHER], tool_result={"isError": True, "content": [{"type": "text", "text": "city not found"}]})
    assert prober.run_due()["trial_failed"] == 1
    trial = json.loads(store.resource(rid)["trial_info"])
    assert trial["ok"] is False and trial["error"] == "city not found"


def test_unchanged_tools_do_not_rerun_trial_but_changes_do(monkeypatch):
    store, rid, server, prober = setup([WEATHER])
    prober.run_due()
    first_updated = store.resource(rid)["usage_updated_at"]
    with store.tx() as db:
        db.execute("UPDATE resources SET cap_checked_at=0 WHERE id=?", (rid,))
    prober.run_due()
    assert len(calls(server)) == 1  # 도구 목록 그대로 → 다시 호출하지 않음
    assert store.resource(rid)["usage_updated_at"] == first_updated and store.resource(rid)["usage_changes"] is None

    server.tools = [{**WEATHER, "description": "Weather with forecast"}, BY_ID]  # 사용법 변경
    with store.tx() as db:
        db.execute("UPDATE resources SET cap_checked_at=0 WHERE id=?", (rid,))
    stats = prober.run_due()
    r = store.resource(rid)
    assert stats["usage_changed"] == 1 and len(calls(server)) == 2  # 바뀌면 다시 시험
    assert json.loads(r["usage_changes"]) == {"added": ["get_order"], "removed": [], "changed": ["get_weather"]}
    assert r["usage_updated_at"] > first_updated
    assert json.loads(r["usage_guide"])["changes"]["added"] == ["get_order"]


def test_trials_can_be_disabled():
    store, rid, server, prober = setup([WEATHER])
    prober.trials = False
    prober.run_due()
    assert calls(server) == [] and store.resource(rid)["usage_guide"]


# ---------------- 게이트웨이 ----------------

@pytest.fixture
def world():
    w = GW_World()
    w.reg.mcp = [{"server": {"name": "io.ex/weather", "title": "Weather", "description": "Weather forecast for any city",
                             "remotes": [{"type": "streamable-http", "url": "https://w.example/mcp"}]}, "_meta": {}}]
    w.crawl()
    return w


def give_guide(w, tools):
    rid = w.store.query("SELECT id FROM resources WHERE url='https://w.example/mcp'")[0]["id"]
    with w.store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy', cap_checked_at=NULL WHERE id=?", (rid,))
    prober = CapabilityProber(w.store, http=httpx.Client(transport=FakeToolServer(tools)), allow_private=True, per_host_delay=0)
    prober.run_due()
    return rid


def test_intro_includes_usage_guide_and_verified_flag(world):
    give_guide(world, [WEATHER])
    agent = world.client().create_need("weather forecast for Seoul", kinds=["mcp"])["agent"]
    assert agent["verified_working"] is True and agent["usage"]["verified_example"]["name"] == "get_weather"


def test_client_notified_when_current_agent_usage_changes(world):
    sent = []
    world.service.notifier = lambda url, payload: sent.append(payload)
    rid = give_guide(world, [WEATHER])
    need = world.client().create_need("weather forecast for Seoul", kinds=["mcp"], webhook="https://client.example/hook")
    assert world.service.rescan()["usage_updates"] == 0  # 소개 이후 바뀐 게 없음

    with world.store.tx() as db:  # 다음 날 다시 조사 (정상 상태)
        db.execute("UPDATE resources SET cap_checked_at=NULL, health_status='healthy' WHERE id=?", (rid,))
    prober = CapabilityProber(world.store, http=httpx.Client(transport=FakeToolServer([WEATHER, BY_ID])), allow_private=True, per_host_delay=0)
    prober.run_due()
    assert world.service.rescan()["usage_updates"] == 1
    event = next(p for p in sent if p["event"] == "usage_updated")
    assert event["need_id"] == need["need_id"] and event["changes"]["added"] == ["get_order"] and event["usage"]["tool_count"] == 2
    assert world.service.rescan()["usage_updates"] == 0  # 한 번만 알림



@pytest.mark.parametrize("bad_response", [
    {"jsonrpc": "2.0", "id": 3, "error": "rate limited"},  # error가 문자열
    {"jsonrpc": "2.0", "id": 3, "result": ["not", "a", "dict"]},  # result가 객체가 아님
])
def test_non_standard_tool_responses_do_not_break_batch(bad_response):
    class Odd(FakeToolServer):
        def handle_request(self, request):
            body = json.loads(request.content or b"{}") if request.method != "DELETE" else {}
            if body.get("method") == "tools/call":
                return httpx.Response(200, json=bad_response)
            return super().handle_request(request)
    store = Store()
    rid = mcp_resource(store, "https://odd.example/mcp")
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))
    prober = CapabilityProber(store, http=httpx.Client(transport=Odd([WEATHER])), allow_private=True, per_host_delay=0)
    stats = prober.run_due()
    assert stats["checked"] == 1 and stats["trial_failed"] == 1 and store.resource(rid)["usage_guide"]

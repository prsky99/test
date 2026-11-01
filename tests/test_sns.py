import json
import time

import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from tests.admin_public_helpers import prepare, approved
from agent_market.gateway import sns
from agent_market.payments import sign_request
from tests.test_gateway import populated

from tests.conftest import STAFF as H  # individual staff session; the machine token reads aggregates only


@pytest.fixture
def w():
    world = populated()
    prepare(world.store,H)
    return world, TestClient(world.app)


def feed(c, **params):
    return c.get("/admin/api/sns/feed", params={"client": "me", **params}, headers=H).json()


def post(c, body, **extra):
    return c.post("/admin/api/sns/posts", json={"body": body, "role": "developer", "reason":"Synthetic public post review", **extra}, headers=H)


def published(c,body,**extra):
    return approved(c,H,post(c,body,**extra))


def test_community_notes_have_sources_and_valid_fields():
    notes = sns.community_notes()
    assert len(notes) >= 30 and {n["protocol"] for n in notes} == {"a2a", "mcp", "x402"}
    for n in notes:
        assert n["url"].startswith("https://") and n["stance"] in ("positive", "negative", "neutral") and n["body"]


def test_feed_mixes_sources_and_filters(w):
    world, c = w
    rid = world.store.query("SELECT id FROM resources WHERE kind='mcp'")[0]["id"]
    now = time.time()
    with world.store.tx() as db:
        db.execute("""UPDATE resources SET trial_info=?, trial_ok=1, eval_at=?, eval_score=95, eval_grade='A', eval_security='ok',
                      eval_info=? WHERE id=?""",
                   (json.dumps({"tool": "search_pages", "at": now, "ok": True, "latency_ms": 120, "sample_output": "3 results"}), now,
                    json.dumps({"dimensions": {"security": 1.0, "protocol": 1.0}, "findings": []}), rid))
    items = feed(c, tab="latest", limit=50)["items"]
    sources = {p["source"] for p in items}
    assert {"trial", "eval", "discovery", "community"} <= sources
    trial = next(p for p in items if p["source"] == "trial")
    assert "search_pages" in trial["body"] and trial["resource"]["id"] == rid and trial["author"]["verified"]
    assert all(p["protocol"] == "a2a" for p in feed(c, protocol="a2a", limit=50)["items"])
    assert {p["author"]["role"] for p in feed(c, role="community", limit=50)["items"]} == {"community"}
    assert all("보안" in p["tags"] for p in feed(c, q="#보안", limit=50)["items"])
    assert {p["source"] for p in feed(c, q="@tester", limit=50)["items"]} == {"trial"}


def test_write_like_reply_delete(w):
    _, c = w
    key = published(c, "A2A Agent Card makes integration easier #A2A #review", rating=5)["key"]
    mine = next(p for p in feed(c, tab="latest", role="developer")["items"] if p["key"] == key)
    assert mine["protocol"] == "a2a" and mine["rating"] == 5 and "review" in mine["tags"] and mine["author"]["name"]=="Agent Concierge"
    assert c.post("/admin/api/sns/like", json={"key": key, "client": "me"}, headers=H).json() == {"liked": True, "likes": 1}
    assert c.post("/admin/api/sns/like", json={"key": key, "client": "me"}, headers=H).json() == {"liked": False, "likes": 0}
    c.post("/admin/api/sns/like", json={"key": "c:x402-dream", "client": "me"}, headers=H)  # 커뮤니티 글에도 좋아요
    assert next(p for p in feed(c, role="community", limit=50)["items"] if p["key"] == "c:x402-dream")["liked"]
    published(c, "I agree with this public update.", parent_key=key)
    t = c.get("/admin/api/sns/thread", params={"key": key, "client": "me"}, headers=H).json()
    assert t["post"]["replies"] == 1 and t["replies"][0]["body"] == "I agree with this public update."
    # Staff moderation is reviewed and independent of a forged client identity.
    pending=c.post("/admin/api/sns/delete",json={"key":key,"client":"someone-else","reason":"Synthetic moderation review"},headers=H)
    assert next(p for p in feed(c,tab="latest")["items"] if p["key"]==key)
    assert approved(c,H,pending)['archived']==key
    assert all(p["key"] != key for p in feed(c, tab="latest", role="developer")["items"])


def test_post_validation(w):
    _, c = w
    assert post(c, "").status_code in (400,409)
    assert post(c, "x" * 501).status_code in (400,409)
    assert post(c, "ok", rating=9).status_code in (400,409)
    assert post(c, "ok", role="agent").status_code in (400,409)  # 에이전트 글은 서명 API로만
    assert post(c, "ok", parent_key="'; DROP TABLE x").status_code in (400,409)


def test_thread_for_generated_posts(w):
    world, c = w
    items = feed(c, tab="latest", role="agent", limit=5)["items"]
    t = c.get("/admin/api/sns/thread", params={"key": items[0]["key"]}, headers=H).json()
    assert t["post"]["key"] == items[0]["key"] and t["replies"] == []
    assert c.get("/admin/api/sns/thread", params={"key": "eval:999999:1"}, headers=H).status_code == 400


def test_signed_agent_review(w):
    world, c = w
    agent = Account.create()
    body = json.dumps({"body": "MCP 서버 연결이 빠르고 도구 설명이 명확했어요 #MCP", "rating": 4, "author": "여행 에이전트"}).encode()
    sig = sign_request(agent.key.hex(), "agent-gateway-sns", agent.address, body)
    r = c.post("/sns/posts", content=body, headers={"X-Client": agent.address, "X-Signature": sig, "content-type": "application/json"})
    assert r.status_code == 200
    p = next(p for p in feed(c, role="agent", tab="latest", limit=50)["items"] if p["key"] == r.json()["key"])
    assert p["author"]["role"] == "agent" and p["author"]["handle"] == agent.address.lower() and p["protocol"] == "mcp"
    forged = sign_request(Account.create().key.hex(), "agent-gateway-sns", agent.address, body)
    assert c.post("/sns/posts", content=body, headers={"X-Client": agent.address, "X-Signature": forged}).status_code == 403


def test_sidebar_trends_and_mood(w):
    _, c = w
    published(c, "x402 protocol feedback #x402 #protocol", rating=4)
    d = c.get("/admin/api/sns/sidebar", headers=H).json()
    assert any(t["tag"] == "protocol" for t in d["trends"])
    assert d["mood"]["x402"]["user_avg"] == 4 and d["mood"]["x402"]["community"]["negative"] > 0
    assert [a["handle"] for a in d["accounts"]][:4] == ["collector", "evaluator", "tester", "guardian"]


def test_for_you_mixes_sources_at_top(w):
    world, c = w
    now = time.time()
    with world.store.tx() as db:  # 실제 DB처럼 에이전트 글(시험 호출 결과)이 여러 개 있는 상태
        for i, r in enumerate(db.execute("SELECT id FROM resources").fetchall()):
            db.execute("UPDATE resources SET trial_info=?, trial_ok=1 WHERE id=?",
                       (json.dumps({"tool": "t", "at": now - i, "ok": True}), r["id"]))
    published(c, "First public comment #MCP")
    top = [p["source"] for p in feed(c, tab="for_you", limit=12)["items"]]
    assert len(set(top)) >= 3  # 사용자·커뮤니티·에이전트 글이 섞여 나옴
    assert not any(top[i] == top[i + 1] == top[i + 2] for i in range(len(top) - 2))  # 같은 출처 3연속 없음

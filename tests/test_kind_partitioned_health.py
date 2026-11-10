from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from agent_market.collector.agent import CollectorAgent
from agent_market.collector.health import HealthChecker, Schedule
from agent_market.config import GatewayConfig
from agent_market.gateway.crawler import Crawler
from agent_market.gateway.store import Store


@pytest.fixture
def temp_store(tmp_path: Path) -> Store:
    db_path = tmp_path / "test_health_partition.db"
    store = Store(db_path)
    return store


def add_resource(store: Store, url: str, kind: str = "x402") -> int:
    return store.upsert_resource({
        "key": f"{kind}:{url}",
        "source": "test-source",
        "kind": kind,
        "url": url,
        "name": url,
        "description": f"Test {kind} agent",
        "category": "search",
        "networks": ["eip155:8453"],
        "price_usdc": 1000,
        "pay_to": "0x" + "aa" * 20,
        "method": "GET",
        "details": {},
    })


def test_health_interval_default_is_six_hours(temp_store: Store, monkeypatch):
    monkeypatch.delenv("HEALTH_INTERVAL_MINUTES", raising=False)
    cfg = GatewayConfig.from_env()
    assert cfg.health_interval == 21600.0

    schedule = Schedule()
    assert schedule.interval == 21600.0

    checker = HealthChecker(temp_store, schedule=schedule)
    now = time.time()
    # Normal and down agents use six hours with the existing jitter.
    next_check = checker.next_check_at(state_failures=0, in_use=False, now=now, host_size=1)
    assert 21600 * 0.9 <= (next_check - now) <= 21600 * 1.1
    down = checker.next_check_at(state_failures=3, in_use=False, now=now, host_size=1)
    assert 21600 * 0.9 <= down - now <= 21600 * 1.1
    for failures, in_use in [(0, True), (1, False)]:
        urgent = checker.next_check_at(failures, in_use, now, host_size=1)
        assert 900 * 0.9 <= urgent - now <= 900 * 1.1


def test_store_due_for_check_partitions_by_kind(temp_store: Store):
    now = time.time()

    # Register sample agents of different kinds
    id_a2a = add_resource(temp_store, "https://a2a.example.com/.well-known/agent.json", kind="a2a")
    id_mcp = add_resource(temp_store, "https://mcp.example.com/sse", kind="mcp")
    id_x402 = add_resource(temp_store, "https://x402.example.com/api/agent", kind="x402")
    id_other = add_resource(temp_store, "https://other.example.com/api", kind="custom")

    # Set next_check_at in the past so they are due
    with temp_store._lock:
        temp_store._db.execute("UPDATE resources SET next_check_at = ?", (now - 10,))
        temp_store._db.commit()

    # Query A2A only
    due_a2a = temp_store.due_for_check(now=now, limit=100, kind="a2a")
    assert len(due_a2a) == 1
    assert due_a2a[0]["id"] == id_a2a
    assert due_a2a[0]["kind"] == "a2a"

    # Query MCP only
    due_mcp = temp_store.due_for_check(now=now, limit=100, kind="mcp")
    assert len(due_mcp) == 1
    assert due_mcp[0]["id"] == id_mcp
    assert due_mcp[0]["kind"] == "mcp"

    # Query x402: should pick up x402 AND custom/unclassified kind fallback
    due_x402 = temp_store.due_for_check(now=now, limit=100, kind="x402")
    x402_ids = {r["id"] for r in due_x402}
    assert id_x402 in x402_ids
    assert id_other in x402_ids
    assert id_a2a not in x402_ids
    assert id_mcp not in x402_ids

    # Query multiple kinds: ["a2a", "mcp"]
    due_both = temp_store.due_for_check(now=now, limit=100, kind=["a2a", "mcp"])
    both_ids = {r["id"] for r in due_both}
    assert id_a2a in both_ids
    assert id_mcp in both_ids
    assert id_x402 not in both_ids
    assert id_other not in both_ids

    # Query kind=None (legacy/all mode)
    due_all = temp_store.due_for_check(now=now, limit=100, kind=None)
    assert len(due_all) == 4


def test_collector_health_loop_threads_configuration(temp_store: Store):
    dummy_http = httpx.Client()
    crawler = Crawler(temp_store, http=dummy_http, page_delay=0)
    checker = HealthChecker(temp_store, http=dummy_http)

    # health_lanes = 1 (single thread round robin)
    agent_1 = CollectorAgent(temp_store, crawler, checker, health_lanes=1)
    loops_1 = agent_1._build_health_loops()
    assert len(loops_1) == 1
    assert loops_1[0][0] == "collector-health"

    # health_lanes = 2 (lane 1: a2a+mcp, lane 2: x402)
    agent_2 = CollectorAgent(temp_store, crawler, checker, health_lanes=2)
    loops_2 = agent_2._build_health_loops()
    assert len(loops_2) == 2
    names_2 = [loop[0] for loop in loops_2]
    assert "collector-health-a2a-mcp" in names_2
    assert "collector-health-x402" in names_2

    # health_lanes = 3 (dedicated lanes for a2a, mcp, x402)
    agent_3 = CollectorAgent(temp_store, crawler, checker, health_lanes=3)
    loops_3 = agent_3._build_health_loops()
    assert len(loops_3) == 3
    names_3 = [loop[0] for loop in loops_3]
    assert names_3 == ["collector-health-a2a", "collector-health-mcp", "collector-health-x402"]

    # health_lanes = 5 (a2a, mcp, and 3 workers for x402)
    agent_5 = CollectorAgent(temp_store, crawler, checker, health_lanes=5)
    loops_5 = agent_5._build_health_loops()
    assert len(loops_5) == 5
    names_5 = [loop[0] for loop in loops_5]
    assert names_5 == [
        "collector-health-a2a",
        "collector-health-mcp",
        "collector-health-x402",
        "collector-health-x402-2",
        "collector-health-x402-3",
    ]

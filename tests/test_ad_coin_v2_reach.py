"""Operator screen "예산별 예상 노출" (PM 11-18 19:4x: not on the public /advertise page): measured figures only, zeros
stay 0, no table from a stale snapshot."""
import json
import time

from fastapi import FastAPI
from starlette.testclient import TestClient

from agent_market.ad_coin.v2 import admin_page, reach

SQL_OUTPUT = ["booked|placement_days|26", "served|explore|11", "served|mcp|2", "served|a2a|1", "noise line", ""]


def snapshot(**shown):
    base = {"explore": 0, "chat": 0, "mcp": 0, "a2a": 0}
    base.update(shown)
    return reach.build_snapshot(26, base, shown.get("necklace", 0), measured_at=time.time(), through_day="2026-11-17")


def test_counts_from_the_read_only_query_and_the_necklace_log():
    booked, shown = reach.parse_counts(SQL_OUTPUT)
    assert booked == 26 and shown == {"explore": 11, "mcp": 2, "a2a": 1}
    snap = reach.build_snapshot(booked, shown, 0, measured_at=1, through_day="2026-11-17")
    assert snap["shown"] == {"explore": 11, "chat": 0, "agent_answers": 3, "necklace": 0}
    assert snap["booked_placement_days"] == 26 and snap["window_days"] == 7


def test_budget_rows_are_placements_times_shown_per_booked_placement_day():
    snap = snapshot(explore=11)
    rows = {budget: reach.expected(snap, budget, 5) for budget in reach.BUDGETS_USDC}
    assert rows[10] == (2, {"explore": 1, "chat": 0, "agent_answers": 0, "necklace": 0})   # 2 * 11 / 26 = 0.85
    assert rows[25][1]["explore"] == 2 and rows[50][1]["explore"] == 4 and rows[100][1]["explore"] == 8
    assert reach.expected(reach.build_snapshot(0, {}, 0, measured_at=1, through_day="x"), 100, 5)[1]["explore"] == 0


def test_the_card_states_the_measurement_and_writes_zero_as_zero():
    card = reach.table_html(snapshot(explore=11), 5)
    assert "예산별 예상 노출" in card and "<td>0</td>" in card
    assert "끝난 예약 칸-일 26개" in card and "Explore 11회" in card and "목걸이 답변 0회" in card
    assert "공개 화면에는 아직 싣지 않습니다" in card and "자체 광고주" in card
    assert reach.table_html(None, 5) == ""


def test_stale_missing_or_broken_snapshots_show_no_table(tmp_path):
    path = tmp_path / "reach-7d.json"
    assert reach.read_snapshot(path) is None
    reach.write_snapshot(path, snapshot(explore=11))
    assert reach.read_snapshot(path)["shown"]["explore"] == 11
    assert reach.read_snapshot(path, now=time.time() + (reach.STALE_DAYS + 1) * 86400) is None
    path.write_text(json.dumps({"booked_placement_days": 26, "measured_at": time.time()}))
    assert reach.read_snapshot(path) is None


def test_only_the_operator_screen_shows_the_table_and_only_with_a_fresh_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "reach-7d.json"
    monkeypatch.setattr(reach, "SNAPSHOT", str(path))
    app = FastAPI()
    app.include_router(admin_page.router_for())
    client = TestClient(app)
    page = client.get(admin_page.PATH).text
    assert "@@" not in page and "예산별 예상 노출" not in page
    reach.write_snapshot(path, snapshot(explore=11))
    page = client.get(admin_page.PATH).text
    assert "예산별 예상 노출" in page and 'href="#reach"' in page
    assert page.index('id="paid"') < page.index('id="reach"') < page.index('id="one"')
    public = client.get("/ad-coin/v2/advertise").text
    assert "@@" not in public and 'id="reach' not in public and "Expected reach" not in public   # not public yet

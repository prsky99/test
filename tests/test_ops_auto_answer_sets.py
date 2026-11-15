"""ops_auto answer_set_expiry (PM 12:27, 11-15): a board line 14 days before a necklace answer set expires."""
import json
from datetime import datetime

from scripts import ops_auto


def manifest(gold, slug, until):
    folder = gold / slug
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"valid_until": until} if until else {}))


def test_expiring_sets_open_one_line_a_day_and_none_closes_it(tmp_path, monkeypatch):
    opened, closed = [], []
    monkeypatch.setattr(ops_auto, "board_handoff", lambda kind, text: opened.append((kind, text)))
    monkeypatch.setattr(ops_auto, "board_close", lambda kind, note: closed.append(kind) or True)
    gold, state = tmp_path / "gold", tmp_path / "state.json"
    manifest(gold, "cve-incident-brief", "2026-12-13")
    manifest(gold, "book-author-brief", "2027-02-23")
    clock = lambda: datetime(2026, 11, 30, 9, 0).timestamp()
    assert ops_auto.answer_set_expiry(clock, gold, state) == ["cve-incident-brief 2026-12-13 만료"]
    assert opened[0][0] == "answer_sets" and "cve-incident-brief" in opened[0][1]
    assert ops_auto.answer_set_expiry(clock, gold, state) is None                  # once a day
    assert ops_auto.TEAM["answer_sets"] == "워크플로우"
    later = lambda: datetime(2026, 12, 14, 9, 0).timestamp()
    manifest(gold, "topic-evidence-brief", None)
    found = ops_auto.answer_set_expiry(later, gold, state)
    assert "cve-incident-brief 2026-12-13 만료됨" in found and "topic-evidence-brief 유효기간 없음" in found
    calm = tmp_path / "calm"
    manifest(calm, "book-author-brief", "2027-02-23")
    assert ops_auto.answer_set_expiry(lambda: datetime(2026, 12, 15, 9, 0).timestamp(), calm, state) == []
    assert closed == ["answer_sets"]


def test_holiday_truth_runs_once_a_day_logs_a_line_and_stops_when_written(tmp_path):
    """PM 11-15: the daily Nager.Date round lives in the ops watch, not in a session's background job."""
    runs = []

    def build(root):
        runs.append(root)
        return {"countries_kept": 20, "countries": 53, "cases": 61, "stopped": "provider budget: system_share"}
    gold, state, log = tmp_path / "gold", tmp_path / "state.json", tmp_path / "log.jsonl"
    gold.mkdir()
    morning = lambda: datetime(2026, 11, 16, 9, 30).timestamp()
    assert ops_auto.holiday_truth(morning, build, state, log, gold) is None and runs == []      # before 10:00
    day = lambda: datetime(2026, 11, 16, 10, 20).timestamp()
    line = ops_auto.holiday_truth(day, build, state, log, gold)
    assert line["cases"] == 61 and line["written"] is False and len(runs) == 1
    assert ops_auto.holiday_truth(day, build, state, log, gold) is None and len(runs) == 1    # once a day
    assert json.loads(log.read_text().splitlines()[0])["countries_kept"] == 20
    (gold / "holidays-at-address").mkdir()
    (gold / "holidays-at-address" / "manifest.json").write_text("{}")
    later = lambda: datetime(2026, 11, 17, 10, 20).timestamp()
    assert ops_auto.holiday_truth(later, build, state, log, gold) == "done" and len(runs) == 1

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


def test_holiday_truth_runs_in_the_app_python_retries_errors_and_stops_when_written(tmp_path, monkeypatch):
    """PM 11-15 / ops review: the daily Nager.Date round runs as a subprocess of the app's Python (the watch's own
    lacks the app's packages), outside :55-:10; the day is done only on a result, an error is tried 3 times a day."""
    import subprocess
    monkeypatch.setattr(ops_auto, "ACTIONS", tmp_path / "actions.md")
    outputs = []

    def run():
        out = outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out
    ok = subprocess.CompletedProcess([], 0, json.dumps({"countries_kept": 20, "countries": 53, "cases": 61,
                                                         "stopped": "provider budget: system_share"}), "")
    broken = subprocess.CompletedProcess([], 1, "", "ModuleNotFoundError: No module named 'jsonschema'")
    gold, state, log = tmp_path / "gold", tmp_path / "state.json", tmp_path / "log.jsonl"
    gold.mkdir()
    at = lambda h, m: (lambda: datetime(2026, 11, 16, h, m).timestamp())
    assert ops_auto.holiday_truth(at(9, 30), run, state, log, gold) is None                 # before 10:00
    assert ops_auto.holiday_truth(at(10, 5), run, state, log, gold) is None                 # measurement window
    outputs[:] = [broken, subprocess.TimeoutExpired("x", 180), ok]
    first = ops_auto.holiday_truth(at(10, 20), run, state, log, gold)
    assert first["ok"] is False and "ModuleNotFoundError" in first["error"]
    assert ops_auto.holiday_truth(at(10, 30), run, state, log, gold)["error"] == "TimeoutExpired"
    third = ops_auto.holiday_truth(at(10, 40), run, state, log, gold)
    assert third["ok"] is True and third["cases"] == 61 and third["try"] == 3
    assert ops_auto.holiday_truth(at(11, 20), run, state, log, gold) is None                # done for the day
    assert len(log.read_text().splitlines()) == 3 and "실패(1/3)" in (tmp_path / "actions.md").read_text()
    outputs[:] = [broken] * 4                                   # next day: three errors, then it waits a day
    for minute in (20, 30, 40, 50):
        ops_auto.holiday_truth(lambda m=minute: datetime(2026, 11, 17, 11, m).timestamp(), run, state, log, gold)
    assert len(outputs) == 1
    (gold / "holidays-at-address").mkdir()
    (gold / "holidays-at-address" / "manifest.json").write_text("{}")
    assert ops_auto.holiday_truth(lambda: datetime(2026, 11, 18, 10, 20).timestamp(), run, state, log, gold) == "done"

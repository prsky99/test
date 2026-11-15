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

"""scripts.answered_by: who answered each slot in a gate round (PM 11-16), on a small fixed round."""
import json

from scripts import answered_by


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_counts_external_ours_none_and_cases_without_slots(tmp_path):
    write(tmp_path / "retest" / "20270101.jsonl", [
        {"slug": "s", "set": "holdout-r1", "type": "case", "case_id": "a"},
        {"slug": "s", "set": "holdout-r1", "type": "case", "case_id": "b"},
        {"slug": "s", "set": "holdout-r1", "type": "excluded", "case_id": "c"},
        {"slug": "s", "set": "holdout-r1-rerun", "type": "case", "case_id": "c"},
        {"slug": "s", "set": "holdout-r1", "type": "excluded", "case_id": "d"},
        {"slug": "s", "set": "other", "type": "case", "case_id": "e"},          # another round: not counted
    ])
    ext = lambda rid, rank: {"resource_id": rid, "tool": "t", "kind": "external", "rank": rank, "ok": True}
    own = lambda tool, rank: {"resource_id": None, "tool": tool, "kind": "agentcon", "rank": rank, "ok": True}
    write(tmp_path / "results" / "s" / "selftest-20270101.jsonl", [
        {"case_id": "a", "slots": {"papers": {"status": "answered", "kind": "external", "rank": 1}},
         "attempts": {"papers": [ext(39577, 1)]}},
        {"case_id": "b", "slots": {"papers": {"status": "answered", "kind": "agentcon", "rank": 3}},
         "attempts": {"papers": [dict(ext(39577, 1), ok=False), dict(ext(47151, 2), ok=False), own("search_research_papers", 3)]}},
        {"case_id": "c", "slots": {}, "attempts": {}},                                 # first measurement: excluded
        {"case_id": "c", "slots": {"papers": {"status": "failed", "kind": None, "rank": None}}, "attempts": {"papers": []}},
        {"case_id": "d", "slots": {}, "attempts": {}},                                 # excluded, no slot ran
        {"case_id": "e", "slots": {"papers": {"status": "answered", "kind": "external", "rank": 1}},
         "attempts": {"papers": [ext(1, 1)]}},
    ])
    out = answered_by.count(tmp_path, "s", "holdout-r1", "20270101")
    assert out["cases_in_round"] == 4 and out["cases"] == 4 and out["cases_without_slots"] == 1
    assert out["slots"]["papers"] == {"external": 1, "agentcon": 1, "none": 1,
                                      "by_member": {"39577": 1, "search_research_papers": 1}}

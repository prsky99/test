"""scripts/necklace_value_report (PM 11-17): the four numbers from a round's own lines, public lines only after a pass."""
import json

from scripts import necklace_value_report as nvr


def lines(n_pass=29):
    out = []
    for i in range(30):
        ok = i < n_pass
        out.append({"type": "case", "slug": "s", "version": 2, "set": "h", "case_id": f"c{i}", "ok": ok,
                    "latency_ms": 1000 + i * 10,
                    "slots": {"a": {"rank": 2 if i == 0 else 1, "status": "answered"}},
                    "value": {"necklace": {"tokens": 100, "calls": 1, "ms": 1, "correct": ok},
                              "direct": {"tokens": 80, "calls": 3, "ms": 1, "correct": ok},
                              "direct_full": {"tokens": 900, "calls": 6, "ms": 1, "correct": ok,
                                              "estimated": ["find_agents"]}}})
        out.append({"type": "single", "slug": "s", "resource_id": 7, "case_id": f"c{i}", "ok": i < 20})
    out.append({"type": "excluded", "slug": "s", "set": "h", "case_id": "x", "why": "reference_unavailable"})
    out.append({"type": "case", "slug": "other", "set": "h", "case_id": "c0", "ok": False})
    return out


def test_four_numbers_come_from_the_round_lines():
    m = nvr.measure(lines(), "s", "h")
    assert m["accuracy"]["necklace"] == {"correct": 29, "of": 30, "rate": 0.967}
    assert m["accuracy"]["best_single"]["correct"] == 20 and m["accuracy"]["delta_points"] == 30.0
    assert m["time_ms"]["p50"] == 1145 and m["excluded"] == 1
    assert m["tokens"]["ratio_full_to_necklace"] == 9.0 and m["tokens"]["ratio_member_answers_to_necklace"] == 0.8
    assert m["fallbacks"]["cases"] == 1 and m["fallbacks"]["by_slot"] == {"a": 1}


def test_public_lines_only_after_a_passing_round(tmp_path):
    m = nvr.measure(lines(), "s", "h")
    assert "공개 금지" in nvr.readme(m, None)
    assert "공개 금지" in nvr.readme(m, {"runner_result": {"passed": 27, "of": 30}})
    text = nvr.readme(m, {"runner_result": {"passed": 29, "of": 30}, "path": "engine"})
    assert "Correct on 29 of 30" in text and "about 9 times as many tokens" in text and "원서버 경로" in text
    assert "relay 경로" in nvr.readme(m, {"runner_result": {"passed": 29, "of": 30}, "path": "relay (x)"})


def test_cli_writes_readme_and_json(tmp_path):
    root = tmp_path / "root"
    (root / "retest").mkdir(parents=True)
    (root / "retest" / "20261118.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines()))
    assert nvr.main(["s", "h", "20261118", "--root", str(root), "--logs", str(tmp_path / "logs"),
                     "--out", str(tmp_path / "out")]) == 0
    folder = tmp_path / "out" / "necklace-value-s-20261118"
    assert (folder / "README.md").exists() and json.loads((folder / "value.json").read_text())["graded"] == 30

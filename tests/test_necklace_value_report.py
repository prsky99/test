"""scripts/necklace_value_report (PM 11-17): measured numbers from the rounds' own lines; public lines only when both
rounds passed and the delta is above 0, with no token estimate and no engine-path time in them."""
import json

from scripts import necklace_value_report as nvr


def lines(split="h", n_pass=29):
    out = []
    for i in range(30):
        ok = i < n_pass
        out.append({"type": "case", "slug": "s", "version": 2, "set": split, "case_id": f"c{i}", "ok": ok,
                    "latency_ms": 1000 + i * 10,
                    "slots": {"a": {"rank": 2 if i == 0 else 1, "status": "answered"}},
                    "value": {"necklace": {"tokens": 100, "calls": 1, "ms": 1, "correct": ok},
                              "direct": {"tokens": 80, "calls": 3, "ms": 1, "correct": ok},
                              "direct_full": {"tokens": 900, "calls": 6, "ms": 1, "correct": ok,
                                              "estimated": ["find_agents"]}}})
        out.append({"type": "single", "slug": "s", "resource_id": 7, "case_id": f"c{i}", "ok": i < 20})
    out.append({"type": "excluded", "slug": "s", "set": split, "case_id": "x", "why": "reference_unavailable"})
    out.append({"type": "case", "slug": "other", "set": split, "case_id": "c0", "ok": False})
    return out


def write_day(root, day, rows):
    (root / "retest").mkdir(parents=True, exist_ok=True)
    with (root / "retest" / f"{day}.jsonl").open("a") as fh:
        fh.write("".join(json.dumps(l) + "\n" for l in rows))


def test_four_numbers_come_from_the_round_lines():
    m = nvr.measure(lines(), "s", "h")
    assert m["accuracy"]["necklace"] == {"correct": 29, "of": 30, "rate": 0.967}
    assert m["accuracy"]["best_single"]["correct"] == 20 and m["accuracy"]["delta_points"] == 30.0
    assert m["time_ms"]["p50"] == 1145 and m["excluded"] == 1
    assert m["tokens"]["ratio_full_to_necklace"] == 9.0
    assert m["fallbacks"]["cases"] == 1 and m["fallbacks"]["by_slot"] == {"a": 1}


def test_two_rounds_merge_and_one_round_is_never_public(tmp_path):
    root = tmp_path / "root"
    write_day(root, "20261118", lines("r5") + lines("r6", 28))
    m = nvr.measure_rounds(root, "s", [("r5", "20261118"), ("r6", "20261118")])
    assert m["accuracy"]["necklace"]["correct"] == 57 and m["accuracy"]["necklace"]["of"] == 60
    assert m["accuracy"]["best_single"]["cases"] == 60
    one = nvr.readme(m, [{"verdict": "pass"}], [("r5", "20261118")], "s")
    assert "공개 금지: 1회차 중간 결과" in one


def test_public_lines_need_both_rounds_and_carry_no_token_estimate_or_engine_time():
    m = nvr.measure(lines(), "s", "h")
    engine = [{"verdict": "pass", "path": "engine"}, {"verdict": "pass", "path": "engine"}]
    text = nvr.readme(m, engine, [("a", "1"), ("b", "2")], "s")
    public = text.split("## 5.")[1]
    assert "Correct on 29 of 30" in public and "+30 points" in public
    assert "token" not in public.lower() and " s (median)" not in public
    assert "내부 수치" in text
    assert "공개 금지" in nvr.readme(m, [{"verdict": "pass"}, {"verdict": "fail (27/30)"}], [("a", "1"), ("b", "2")], "s")
    relay = [{"verdict": "pass", "path": "relay"}, {"verdict": "pass", "path": "relay"}]
    assert "s (median) on our public address" in nvr.readme(m, relay, [("a", "1"), ("b", "2")], "s")


def test_cli_writes_readme_and_json(tmp_path):
    root = tmp_path / "root"
    write_day(root, "20261118", lines("r5"))
    assert nvr.main(["s", "r5@20261118", "--root", str(root), "--logs", str(tmp_path / "logs"),
                     "--out", str(tmp_path / "out")]) == 0
    body = json.loads((tmp_path / "out" / "necklace-value-s-20261118" / "value.json").read_text())
    assert body["graded"] == 30 and body["public"] is False


def test_tokens_counted_by_a_tokenizer_where_the_text_is_whole_and_estimated_where_cut(tmp_path):
    root = tmp_path / "root"
    write_day(root, "20261118", lines("r5"))
    folder = root / "results" / "s"
    folder.mkdir(parents=True)
    rows = [{"case_id": f"c{i}", "output": {"a": "x" * 40},
             "attempts": {"a": [{"raw": "y" * 100, "chars_out": 100}, {"raw": "z" * 2000, "chars_out": 9000}]}}
            for i in range(30)]
    (folder / "selftest-20261118.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    seen = []
    counted = nvr.measured_tokens(root, "s", [("r5", "20261118")], counter=lambda texts: seen.extend(texts) or [7] * len(texts))
    assert counted["counted_by"] == "Anthropic count_tokens" and counted["necklace_answer"]["median"] == 7
    assert counted["member_answers"]["median"] == 7 + 2250 and counted["member_answers_cut_estimated"] == 30
    assert len(seen) == 60                                    # 30 answers + 30 whole member texts, the cut ones not sent
    fallback = nvr.measured_tokens(root, "s", [("r5", "20261118")], counter=lambda texts: None)
    assert fallback["counted_by"].startswith("characters / 4")


def test_texts_the_tokenizer_could_not_count_are_estimated_and_counted(tmp_path):
    root = tmp_path / "root"
    write_day(root, "20261118", lines("r5"))
    folder = root / "results" / "s"
    folder.mkdir(parents=True)
    rows = [{"case_id": f"c{i}", "output": {"a": "x" * 40}, "attempts": {"a": [{"raw": "y" * 100, "chars_out": 100}]}}
            for i in range(30)]
    (folder / "selftest-20261118.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    half = lambda texts: [5] * 10 + [None] * (len(texts) - 10)          # a 429 after ten texts
    counted = nvr.measured_tokens(root, "s", [("r5", "20261118")], counter=half)
    assert counted["texts_estimated_after_rate_limit_or_cap"] == 50

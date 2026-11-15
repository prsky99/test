"""Value proof (plan 3.1, PM 11-15): one necklace call against calling the members directly, on the same case."""
from agent_market.necklaces import judge, model, runner, value


def run_book(lead_fails=False):
    def caller(member, args, timeout_s):
        if member["tool"] == "search_books":
            if lead_fails:
                raise RuntimeError("down")
            return {"docs": [{"author_name": ["George Orwell"], "first_publish_year": 1949, "title": "1984"}] * 3}
        if member.get("agent_id") == "wikidata-book":
            return {"answer": "1984 — novel; author George Orwell; published 1949"}
        return [{"title": "George Orwell", "description": "English novelist (1903–1950)", "excerpt": "x" * 400}]
    defn = model.load("agent_market/necklaces/definitions/book-author-brief.json")
    state = {"substitutes": [["wikidata-book", "book.search.v1"]]}
    return defn, runner.Runner(caller, watch_state=state).run(defn, {"title": "Nineteen Eighty-Four"})


def test_both_paths_are_measured_from_the_same_run():
    defn, result = run_book()
    v = value.measure(defn, {"title": "Nineteen Eighty-Four"}, result, True)
    assert v["necklace"]["calls"] == 1 and v["direct"]["calls"] == 2           # one call against two member calls
    assert v["direct"]["tokens"] > 0 and v["necklace"]["tokens"] > 0
    attempts = [a for slot in result["attempts"].values() for a in slot]
    assert all(a["chars_out"] > 0 and a["chars_in"] > 0 for a in attempts)
    assert v["direct"]["correct"] is True


def test_a_slot_rescued_by_a_fallback_is_wrong_on_the_direct_path():
    defn, result = run_book(lead_fails=True)
    v = value.measure(defn, {"title": "x"}, result, True)
    assert v["necklace"]["correct"] is True and v["direct"]["correct"] is False
    assert v["direct"]["calls"] == 3                                            # the failed lead counts as a call


def test_summary_medians_and_publication_only_after_the_gate():
    rows = [{"necklace": {"calls": 1, "tokens": 300, "ms": 2000, "correct": True},
             "direct": {"calls": 2, "tokens": 900, "ms": 3000, "correct": c}} for c in (True, False, True)]
    s = value.summarize(rows + [{"necklace": {"calls": 1, "tokens": 1, "ms": 1, "correct": None}, "direct": {}}])
    assert s["cases"] == 3 and s["direct"]["tokens"] == 900 and s["direct"]["correct_rate"] == 0.667
    assert s["necklace"]["correct_rate"] == 1.0 and value.summarize([]) is None
    defn = dict(model.load("agent_market/necklaces/definitions/book-author-brief.json"), status="live")
    state = {"updated": judge._iso(0)}
    assert judge.build_entry(defn, None, {"value": s}, 0, state, set())["value"] is None       # no gate yet
    approval = {"state": "approved", "version": defn["version"], "definition_digest": model.digest(defn),
                "at": "2026-11-17T06:00:00Z"}
    assert judge.build_entry(defn, approval, {"value": s}, 0, state, set())["value"] == s


def test_comparison_is_the_form_growth_shows():
    from agent_market.necklaces.value import comparison
    assert comparison(None) is None
    out = comparison({"cases": 12, "since": "2026-11-17T02:31:00+0900", "until": "2026-11-20T02:40:00+0900",
                      "necklace": {"calls": 1, "tokens": 300, "ms": 2340, "correct_rate": 0.917},
                      "direct": {"calls": 3, "tokens": 1210.5, "ms": 1980, "correct_rate": 0.75}, "method": "m"})
    assert out["measured_at"] == "2026-11-20" and out["cases"] == 12
    assert out["with"] == {"calls": 1, "tokens": 300, "seconds": 2.3, "accuracy": 0.917}
    assert out["without"]["calls"] == 3 and out["without"]["accuracy"] == 0.75


def test_growth_surface_accepts_the_comparison():
    import pytest
    from agent_market.concierge import necklace_surface
    from agent_market.necklaces.value import comparison
    if not hasattr(necklace_surface, "comparison_line"):
        pytest.skip("growth's comparison line not in this tree yet")
    entry = {"comparison": comparison({"cases": 5, "until": "2026-11-20T02:40:00+0900",
                                       "necklace": {"calls": 1, "tokens": 300, "ms": 2340, "correct_rate": 1.0},
                                       "direct": {"calls": 3, "tokens": 1210, "ms": 1980, "correct_rate": 0.8}})}
    line = necklace_surface.comparison_line(entry)
    assert line and "5 cases (2026-11-20)" in line and "80% \u2192 100%" in line


def test_full_value_adds_finding_and_merging_and_marks_estimates():
    """PM 15:11: the conservative value leaves finding and merging out; the full value adds find_agents per slot,
    tools/list per member server called and one merge pass over the answers received, with estimates named."""
    from agent_market.necklaces import value
    defn = {"slots": [{"slot": "a"}, {"slot": "b", "depends_on": ["a"]}]}
    result = {"output": {"x": "y" * 40}, "latency_ms": 900,
              "slots": {"a": {"rank": 1}, "b": {"rank": 1}},
              "attempts": {"a": [{"resource_id": 1, "ms": 300, "chars_in": 40, "chars_out": 400}],
                           "b": [{"resource_id": 2, "ms": 500, "chars_in": 40, "chars_out": 800, "error_class": "timeout"},
                                 {"resource_id": 3, "ms": 400, "chars_in": 40, "chars_out": 400},
                                 {"resource_id": 4, "ms": 0, "error_class": "deadline"}]}}
    out = value.measure(defn, {"q": "z"}, result, True)
    direct, full = out["direct"], out["direct_full"]
    assert direct["calls"] == 3 and full["calls"] == 3 + 2 + 3          # 2 find_agents, 3 servers' tools/list
    assert full["tokens"] > direct["tokens"] + full["parts"]["find_tokens"] - 1
    assert full["parts"]["merge_tokens"] >= (400 + 800 + 400) // 4
    assert full["ms"] == direct["ms"] + 2 * (value.FIND_AGENTS["ms"] + value.TOOLS_LIST["ms"])
    assert full["correct"] == direct["correct"] and set(full["estimated"]) == {"find_agents", "tools_list"}
    summary = value.summarize([out, out])
    shown = value.comparison(dict(summary, until="2026-11-20T00:00:00Z"))
    assert shown["without_full"]["tokens"] > shown["without"]["tokens"] and shown["without_full"]["estimated"]

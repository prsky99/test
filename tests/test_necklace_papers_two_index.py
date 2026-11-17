"""PM 11-17: topic papers key "papers-two-index-v1" (G = OA top 10 ∩ CR top 50 ∪ CR top 10 ∩ OA top 50) and the
same-source rule not applied to it."""
import json
from urllib.parse import unquote

from agent_market.necklaces import gold_topics_two_index as two
from agent_market.necklaces import retest
from agent_market.necklaces.gold_repos import Budget


def oa_body(dois):
    return {"results": [{"doi": "https://doi.org/" + d, "title": "Paper " + d} for d in dois]}


def cr_body(dois):
    return {"message": {"items": [{"DOI": d.upper(), "title": ["Paper " + d]} for d in dois]}}


def test_g_takes_papers_both_indexes_rank_high_by_doi():
    oa = two.openalex_list(oa_body([f"10.1/oa{i}" for i in range(10)] + ["10.1/both-wide"] + [f"10.1/x{i}" for i in range(39)]))
    cr = two.crossref_list(cr_body(["10.1/both-wide", "10.1/oa3"] + [f"10.1/cr{i}" for i in range(8)] + ["10.1/oa7"]))
    g = [p["doi"] for p in two.two_index(oa, cr)]
    # oa3: OA top 10 and CR top 50; oa7: OA top 10 and CR top 50 (11th in CR); both-wide: CR top 10 and OA top 50
    assert g == ["10.1/oa3", "10.1/oa7", "10.1/both-wide"]
    assert two.two_index(oa, two.crossref_list(cr_body(["10.9/other"]))) == []


def fake_get(calls, openalex, crossref, wiki_titles=None):
    def get(url):
        calls.append(url)
        if "wikipedia" in url:
            return 200, {"query": {"pages": [{"title": t, "description": "d", "fullurl": "https://en.wikipedia.org/wiki/" + t}
                                             for t in wiki_titles]}}
        phrase = unquote(url.split("title.search:")[-1] if "openalex" in url else url.split("query.title=")[1].split("&")[0])
        if "openalex" in url:
            return 200, oa_body(openalex(phrase))
        return 200, cr_body(crossref(phrase))
    return get


def test_r6_set_takes_the_first_30_topics_with_a_non_empty_g_and_records_the_rule(tmp_path):
    from agent_market.necklaces.gold_topics_r6 import TOPICS
    folder = tmp_path / "gold" / "topic-evidence-brief"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"files": {}}))
    empty = {TOPICS[1][1], TOPICS[4][1]}                           # two topics where the indexes never agree
    calls = []
    get = fake_get(calls, lambda p: [f"10.1/{p}-{i}" for i in range(50)],
                   lambda p: [f"10.9/{p}"] if p in empty else [f"10.1/{p}-{i}" for i in range(50)],
                   [t for t, _, _ in TOPICS])
    out = two.step(tmp_path, "holdout-r6-2i", get)
    assert out["written"] == {"cases": 30, "dropped": 2}
    cases = [json.loads(x) for x in (folder / "holdout-r6-2i.jsonl").read_text().splitlines()]
    assert [c["case_id"] for c in cases] == ["topic:" + t for t, p, _ in TOPICS if p not in empty][:30]
    assert all(c["truth"]["papers_rule"] == "papers-two-index-v1" and c["truth"]["papers"] for c in cases)
    entry = json.loads((folder / "manifest.json").read_text())["files"]["holdout-r6-2i"]
    assert entry["grading_rule"]["name"] == "papers-two-index-v1" and entry["grading_rule"]["top"] == 10
    assert entry["dropped_count"] == 2
    assert sum("wikipedia" in u for u in calls) == 1 and sum("openalex" in u for u in calls) == 32
    assert all("per-page=50" in u for u in calls if "openalex" in u) and all("rows=50" in u for u in calls if "crossref" in u)


def test_r5_set_reuses_its_topics_and_wikipedia_facts_and_resumes_after_a_budget_stop(tmp_path):
    folder = tmp_path / "gold" / "topic-evidence-brief"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"files": {}}))
    r5 = [{"case_id": f"topic:T{i}", "stratum": "stem", "input": {"topic": f"T{i}"},
           "truth": {"wiki": {"title": f"T{i}"}, "papers": [], "paper_phrase": f"t{i}"}} for i in range(3)]
    (folder / "holdout-r5.jsonl").write_text("".join(json.dumps(c) + "\n" for c in r5))
    calls, budget = [], {"left": 3}

    def get(url):
        if budget["left"] == 0:
            raise Budget("system_share")
        budget["left"] -= 1
        return fake_get(calls, lambda p: [f"10.1/{p}"], lambda p: [f"10.1/{p}"])(url)
    first = two.step(tmp_path, "holdout-r5-2i", get)
    assert first["stopped"] == "system_share" and "written" not in first
    budget["left"] = 10
    second = two.step(tmp_path, "holdout-r5-2i", get)
    assert second["written"] == {"cases": 3, "dropped": 0}
    assert not any("wikipedia" in u for u in calls) and len(calls) == 6      # nothing asked twice


def member_answer_case(rule):
    defn = {"slug": "topic-evidence-brief", "slots": [{"slot": "papers", "chain": [
        {"resource_id": 47151, "tool": "openalex_search_entities", "upstream": ["openalex"]}]}]}
    case = {"truth": {"papers_rule": rule} if rule else {},
            "truth_sources": [{"name": "OpenAlex (title search, most cited, top 50)"},
                              {"name": "Crossref (title search, most referenced, top 50)"}]}
    result = {"attempts": {"papers": [{"ok": True, "resource_id": 47151}]}}
    return defn, case, result


def test_same_source_is_not_applied_to_the_two_index_key_only():
    assert retest.same_source(*member_answer_case("papers-two-index-v1")) == []
    assert retest.same_source(*member_answer_case(None)) == ["papers"]


def test_grade_papers_v2_matches_like_before():
    case = {"truth": {"papers": [{"doi": "10.1/a", "title": "A study of things"}], "papers_rule": "papers-two-index-v1"}}
    assert retest.grade_papers_v2(case, {"items": [{"doi": "10.1/A"}]}) is True
    assert retest.grade_papers_v2(case, {"items": [{"title": "something else"}]}) is False
    assert retest.GRADERS["papers"] is retest.grade_papers_v2

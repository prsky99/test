"""topic-evidence-brief holdout-r3: one Wikipedia batch, OpenAlex per topic, resumable under the ledger."""
import json

from agent_market.necklaces import gold_repos, gold_topics_r3 as r3


def setup(tmp_path):
    folder = tmp_path / "gold" / "topic-evidence-brief"
    folder.mkdir(parents=True)
    (folder / "holdout-r1.jsonl").write_text(json.dumps({"case_id": "topic:CRISPR"}) + "\n")
    (folder / "manifest.json").write_text(json.dumps({"files": {}}))
    return folder


def fake(limit=999, papers=3):
    calls = []

    def get(url):
        if len(calls) >= limit:
            raise gold_repos.Budget("system_share")
        calls.append(url)
        if "wikipedia.org" in url:
            pages = [{"title": t, "description": "a topic", "fullurl": "https://en.wikipedia.org/wiki/x"}
                     for t, _, _ in r3.TOPICS if t not in ("CRISPR", "Metamaterial")]
            pages.append({"title": "Metamaterial", "missing": True})
            return 200, {"query": {"pages": pages}}
        return 200, {"results": [{"doi": f"https://doi.org/10.1/{i}", "title": f"Paper {i}"} for i in range(papers)]}
    return get, calls


def test_r3_skips_seen_topics_resumes_and_writes_once_done(tmp_path):
    folder = setup(tmp_path)
    get, calls = fake(limit=3)
    out = r3.step(tmp_path, get)
    assert out["stopped"] == "system_share" and out["done"] == 2 and "written" not in out
    assert sum("wikipedia.org" in c for c in calls) == 1                 # one batch call for every title
    get, calls = fake()
    out = r3.step(tmp_path, get)
    assert not any("wikipedia.org" in c for c in calls)                  # kept from the first run
    assert out["dropped"] == {"Metamaterial": "no standard Wikipedia page"}
    total = len(r3.TOPICS) - 2                                           # CRISPR was seen, Metamaterial dropped
    assert out["written"]["cases"] == total
    cases = [json.loads(l) for l in (folder / "holdout-r3.jsonl").read_text().splitlines()]
    assert not any(c["case_id"] == "topic:CRISPR" for c in cases)
    assert all(c["truth"]["paper_phrase"] and len(c["truth"]["papers"]) == 3 and c["truth"]["wiki"]["title"] for c in cases)
    assert json.loads((folder / "manifest.json").read_text())["files"]["holdout-r3"]["cases"] == total


def test_a_topic_with_too_few_papers_is_left_out(tmp_path):
    setup(tmp_path)
    get, _ = fake(papers=2)
    out = r3.step(tmp_path, get)
    assert out["written"]["cases"] == 0 and len(out["dropped"]) == len(r3.TOPICS) - 1

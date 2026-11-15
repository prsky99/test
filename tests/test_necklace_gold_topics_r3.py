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


def test_r4_is_a_fresh_unfiltered_sample_with_its_own_progress(tmp_path):
    """PM 11-16 06:5x: holdout-r4 shares no topic with r1-r3 and is not filtered by a source's coverage."""
    from agent_market.necklaces import gold, gold_topics_r4 as r4
    old = {t for t, _, _ in gold.TOPICS} | {t for t, _, _ in r3.TOPICS}
    assert len(r4.TOPICS) >= 35 and not old & {t for t, _, _ in r4.TOPICS}
    folder = setup(tmp_path)
    (folder / "holdout-r3.jsonl").write_text(json.dumps({"case_id": "topic:" + r4.TOPICS[0][0]}) + "\n")
    calls = []

    def get(url):
        calls.append(url)
        if "wikipedia.org" in url:
            return 200, {"query": {"pages": [{"title": t, "description": "d", "fullurl": "https://en.wikipedia.org/wiki/x"}
                                             for t, _, _ in r4.TOPICS]}}
        return 200, {"results": [{"doi": f"10.1/{i}", "title": f"P {i}"} for i in range(3)]}
    out = r4.step(tmp_path, get=get)
    assert out["written"]["cases"] == len(r4.TOPICS) - 1                  # the topic r3 already holds is left out
    entry = json.loads((folder / "manifest.json").read_text())["files"]["holdout-r4"]
    assert "not filtered" in entry["selection"] and entry["truth_sources"]
    assert (folder / "r4-progress.json").exists() and not (folder / "r3-progress.json").exists()


def test_the_wikipedia_part_of_r4_is_written_from_the_batch_alone(tmp_path):
    """PM 11-16 07:0x: holdout-r4-wiki (truth: Wikipedia only) is written as soon as the batch is in; the OpenAlex
    part keeps going afterwards and does not count r4-wiki's topics as seen."""
    from agent_market.necklaces import gold_repos, gold_topics_r4 as r4
    folder = setup(tmp_path)
    calls = []

    def get(url):
        calls.append(url)
        if "wikipedia.org" in url:
            return 200, {"query": {"pages": [{"title": t, "description": "d", "fullurl": "https://en.wikipedia.org/wiki/x"}
                                             for t, _, _ in r4.TOPICS]}}
        raise gold_repos.Budget("system_share")                         # no OpenAlex today
    r4.step(tmp_path, get=get)
    out = r4.wiki_split(tmp_path)
    assert out["cases"] == len(r4.TOPICS)
    case = json.loads((folder / "holdout-r4-wiki.jsonl").read_text().splitlines()[0])
    assert case["truth"]["wiki"]["title"] and case["truth"]["paper_phrase"] and "papers" not in case["truth"]
    entry = json.loads((folder / "manifest.json").read_text())["files"]["holdout-r4-wiki"]
    assert entry["same_topics_as"] == "holdout-r4" and "Wikipedia only" in entry["selection"]

    def openalex(url):
        return 200, {"results": [{"doi": f"10.1/{i}", "title": f"P {i}"} for i in range(3)]}
    later = r4.step(tmp_path, get=openalex)
    assert later["written"]["cases"] == len(r4.TOPICS)                 # r4-wiki's topics were not treated as seen


def test_r5_shares_no_topic_with_any_earlier_set():
    from agent_market.necklaces import gold, gold_topics_r4 as r4, gold_topics_r5 as r5
    old = {t for t, _, _ in gold.TOPICS} | {t for t, _, _ in r3.TOPICS} | {t for t, _, _ in r4.TOPICS}
    assert len(r5.TOPICS) >= 35 and not old & {t for t, _, _ in r5.TOPICS}

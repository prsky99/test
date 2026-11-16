"""topic-evidence-brief holdout-r6 and r7 (PM 11-16 18:3x): fresh topics, 30 cases each within the day's OpenAlex share."""
import json

from agent_market.necklaces import gold_topics_r3 as r3, gold_topics_r4 as r4, gold_topics_r5 as r5
from agent_market.necklaces import gold_topics_r6 as r6, gold_topics_r7 as r7


def titles(mod):
    return [t for t, _, _ in mod.TOPICS]


def test_lists_are_fresh_and_leave_room_for_drops():
    earlier = set(titles(r3)) | set(titles(r4)) | set(titles(r5))
    assert not (set(titles(r6)) | set(titles(r7))) & earlier
    assert not set(titles(r6)) & set(titles(r7))
    assert len(set(titles(r6))) == len(titles(r6)) and len(set(titles(r7))) == len(titles(r7))
    assert r6.ROUND_CASES == r7.ROUND_CASES == 30
    assert 30 < len(r6.TOPICS) <= 38 + 8 and 30 < len(r7.TOPICS) <= 40 + 8   # one Wikipedia batch (50 titles at most)


def test_r6_builds_the_first_30_topics_with_papers_and_asks_no_more(tmp_path):
    folder = tmp_path / "gold" / "topic-evidence-brief"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"files": {}}))
    calls = []

    def get(url):
        calls.append(url)
        if "wikipedia.org" in url:
            pages = [{"title": t, "description": "a topic", "fullurl": "https://en.wikipedia.org/wiki/x"} for t in titles(r6)]
            return 200, {"query": {"pages": pages}}
        return 200, {"results": [{"doi": f"https://doi.org/10.1/{i}", "title": f"Paper {i}"} for i in range(3)]}
    out = r6.step(tmp_path, get=get)
    assert out["written"]["cases"] == 30 and len([c for c in calls if "wikipedia.org" not in c]) == 30
    cases = [json.loads(l)["case_id"] for l in (folder / "holdout-r6.jsonl").read_text().splitlines()]
    assert cases == ["topic:" + t for t in titles(r6)[:30]]

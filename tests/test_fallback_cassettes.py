"""Record-and-replay for the agents.py split (PM 11-16): replay is deterministic, a changed answer is caught."""
import base64
import json

from scripts import fallback_cassettes as fc


def cassette(home, agent_id, title, extract):
    body = json.dumps({"query": {"pages": [{"title": title, "extract": extract, "touched": "2026-11-01T00:00:00Z",
                                            "fullurl": "https://en.wikipedia.org/wiki/" + title}]}}).encode()
    key = ("GET https://en.wikipedia.org/w/api.php?action=query&exintro=1&explaintext=1&format=json&formatversion=2"
           "&inprop=url&maxlag=5&ppprop=disambiguation&prop=extracts%7Cinfo%7Cpageprops&redirects=1&titles=" + title)
    (home / "data").mkdir(parents=True, exist_ok=True)
    (home / f"{agent_id}.jsonl").write_text(json.dumps({"case": "gate:x", "args": {"title": title}, "exchanges": [
        {"key": key, "status": 200, "headers": {"content-type": "application/json"},
         "body": base64.b64encode(body).decode()}]}) + "\n")


def test_baseline_then_check_is_the_same_and_a_changed_answer_is_caught(tmp_path):
    cassette(tmp_path, "wikipedia-summary", "Photosynthesis", "Photosynthesis is how plants make sugar.")
    base = fc.baseline(["wikipedia-summary"], tmp_path)
    assert base["wikipedia-summary"]["cases"] == 1 + len(fc.ERROR_PATHS)
    first = json.loads((tmp_path / "wikipedia-summary.baseline.jsonl").read_text().splitlines()[0])
    assert first["output"]["envelope"]["result"]["title"] == "Photosynthesis" and first["unrecorded"] == []
    assert fc.check(["wikipedia-summary"], tmp_path)["wikipedia-summary"]["same"] is True
    cassette(tmp_path, "wikipedia-summary", "Photosynthesis", "Photosynthesis is something else now.")
    report = fc.check(["wikipedia-summary"], tmp_path)["wikipedia-summary"]
    assert report["same"] is False and report["different"] == ["gate:x"]


def test_error_paths_are_replayed_from_fakes(tmp_path):
    cassette(tmp_path, "wikipedia-summary", "Photosynthesis", "Photosynthesis is how plants make sugar.")
    rows = fc.replay(["wikipedia-summary"], tmp_path)["wikipedia-summary"]
    errors = {r["case"]: r["output"].get("error") for r in rows if r["case"].startswith("error:")}
    assert set(errors) == {"error:" + k for k in fc.ERROR_PATHS} and all(errors.values())

"""E5 tool-definition change feed: listing events and operations' definition changes as JSON Feed 1.1."""
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market import tool_change_feed as F
from agent_market import verified_registry as R
from agent_market import verified_registry_service as S

NOW = 1_800_000_000.0
DAY = time.strftime("%Y%m%d", time.localtime(NOW))


def local(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def change(rid, *, at=NOW - 600, classification="general", prev="aa", cur="bb", added=(), removed=(), changed=(),
           source="survey", risk=()):
    return {"at": local(at), "resource_id": rid, "source": source, "server_fp": cur * 32,
            "prev_server_fp": prev * 32 if prev else None, "normalized_same": False, "added": list(added),
            "removed": list(removed), "changed": list(changed), "risk": list(risk), "classification": classification}


def setup(tmp_path, changes, events=(), members=()):
    reg, fp = tmp_path / "registry", tmp_path / "fp"
    reg.mkdir()
    fp.mkdir()
    (fp / f"changes-{DAY}.jsonl").write_text("\n".join(json.dumps(c) for c in changes))
    if events:
        (reg / f"events-{DAY}.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    (fp / "pearls.json").write_text(json.dumps({"resources": {str(m): {"current": "cc" * 32} for m in members}}))
    snapshot = {"servers": [
        {"server": {"name": "io.github.example/weather"}, "_meta": {R.META_KEY: {"listed": True}}, "_id": 1},
        {"server": {"name": "io.github.example/gone"}, "_meta": {R.META_KEY: {"listed": False}}, "_id": 2}]}
    return snapshot, reg, fp


def test_only_meaningful_changes_in_scope_are_published(tmp_path):
    snapshot, reg, fp = setup(tmp_path, [
        change(1, added=["new_tool"], changed=[{"name": "get", "fields": ["description", "annotations"]}]),
        change(1, at=NOW - 500, classification="dynamic", cur="dd"),                  # numbers in descriptions only
        change(1, at=NOW - 400, prev=None, cur="ee"),                                  # first measurement
        change(1, at=NOW - 300, cur="ff", changed=[{"name": "get", "fields": ["outputSchema"]}]),   # not ours to tell
        change(2, at=NOW - 200, removed=["old"], prev="11", cur="22"),                 # dropped from the registry: kept
        change(9, at=NOW - 100, added=["x"], prev="33", cur="44"),                     # not listed, not a member
        change(7, at=NOW - 50, prev="55", cur="66", classification="risk", risk=["hint_flipped"],
               changed=[{"name": "run", "fields": []}], source="health"),              # member, risk
    ], members=[7])
    feed = F.build_feed(snapshot, reg, fp, NOW)
    assert feed["version"] == "https://jsonfeed.org/version/1.1"
    items = feed["items"]
    assert [i["_agentvalcon"].get("resource_id") for i in items] == [7, 2, 1]          # newest first
    weather = items[2]["_agentvalcon"]
    assert weather["server_name"] == "io.github.example/weather" and weather["added"] == ["new_tool"]
    assert weather["changed"] == [{"tool": "get", "fields": ["description"]}]
    assert items[2]["title"] == "Tool definitions changed: io.github.example/weather"
    risky = items[0]
    assert risky["_agentvalcon"]["kind"] == "definition_changed" and risky["title"] == "Tool definitions changed: agent 7"
    text = json.dumps(feed)
    assert "risk" not in text and "hint_flipped" not in text                            # never the risk detail


def test_listing_events_and_duplicates_from_two_sources(tmp_path):
    events = [{"at": R._iso(NOW - 3600), "event": "delisted", "name": "io.github.example/gone", "version": "1.0.0",
               "reason": "no_recent_success"},
              {"at": R._iso(NOW - 7200), "event": "listed", "name": "io.github.example/weather", "version": "1.2.0"},
              {"at": R._iso(NOW - 40 * 86400), "event": "listed", "name": "io.github.example/old", "version": "1"}]
    same = dict(added=["new_tool"])
    snapshot, reg, fp = setup(tmp_path, [change(1, **same), change(1, at=NOW - 590, source="health", **same)],
                              events=events)
    items = F.build_feed(snapshot, reg, fp, NOW)["items"]
    assert [i["_agentvalcon"]["kind"] for i in items] == ["definition_changed", "delisted", "listed"]
    gone = items[1]
    assert gone["title"] == "Delisted: io.github.example/gone" and gone["_agentvalcon"]["reason"] == "no_recent_success"
    assert gone["url"].endswith("/servers/io.github.example%2Fgone/versions/latest")


def test_route_pages_with_cursor_etag_and_cors(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "PAGE", 2)
    monkeypatch.setattr(F.page, "__defaults__", (None, 2))
    snapshot, reg, fp = setup(tmp_path, [change(1, at=NOW - i * 60, prev=f"{i:02d}", cur=f"{i + 50:02d}",
                                                added=[f"t{i}"]) for i in range(5)])
    F.refresh(snapshot, reg, NOW, fp)
    app = FastAPI()
    app.include_router(S.router_for(R.SnapshotIndex(reg), F.FeedIndex(reg)))
    client = TestClient(app)
    first = client.get(F.FEED_PATH)
    assert first.status_code == 200 and first.headers["content-type"].startswith("application/feed+json")
    assert first.headers["access-control-allow-origin"] == "*" and "max-age" in first.headers["cache-control"]
    body = first.json()
    assert len(body["items"]) == 2 and body["next_url"].startswith(F.SITE + F.FEED_PATH + "?cursor=")
    seen = [i["id"] for i in body["items"]]
    url = body["next_url"]
    while url:
        page = client.get(url.replace(F.SITE, "")).json()
        seen += [i["id"] for i in page["items"]]
        url = page.get("next_url")
    assert len(seen) == len(set(seen)) == 5
    assert client.get(F.FEED_PATH, headers={"if-none-match": first.headers["etag"]}).status_code == 304
    assert client.get(F.FEED_PATH + "?cursor=bm9wZQ").status_code == 400
    assert client.options(F.FEED_PATH).status_code == 204


def test_preparing_and_job_writes_the_feed(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(S.router_for(R.SnapshotIndex(tmp_path / "none"), F.FeedIndex(tmp_path / "none")))
    answer = TestClient(app).get(F.FEED_PATH)
    assert answer.status_code == 503 and answer.headers["retry-after"] == "300"
    monkeypatch.setenv("FINGERPRINT_DATA", str(tmp_path / "fp"))

    class Store:
        def query(self, sql, params):
            return []
    noon = time.mktime((2026, 11, 15, 12, 30, 0, 0, 0, -1))
    assert R.run_job(Store(), now=noon, folder=tmp_path)["changes"] == 0
    feed = json.loads((tmp_path / F.FILE).read_text())
    assert feed["items"] == [] and feed["feed_url"] == F.SITE + F.FEED_PATH
    stamp = (tmp_path / F.FILE).read_bytes()
    R.run_job(Store(), now=noon + 3600, folder=tmp_path)
    assert (tmp_path / F.FILE).read_bytes() == stamp      # an unchanged feed keeps its bytes and so its ETag

"""AgentValCon Verified Registry (docs/VERIFIED_REGISTRY.md, E7): listing rules, v0.1 shapes, cursor, CORS, deltas."""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market import verified_registry as R
from agent_market import verified_registry_service as S

NOW = 1_800_000_000.0


def row(rid, name, *, at=NOW - 3600, description="Weather forecasts for any city.", version="1.2.0",
        remotes=None, website="https://example.com", tool="get_forecast"):
    details = {"registry_name": name, "version": version, "website": website,
               "repository": {"url": "https://github.com/example/weather", "source": "github"},
               "remotes": remotes if remotes is not None else [{"type": "streamable-http", "url": f"https://{rid}.example.com/mcp"}]}
    return {"id": rid, "name": name.split("/")[-1], "description": description, "url": f"https://{rid}.example.com/mcp",
            "details": json.dumps(details), "trial_info": json.dumps({"tool": tool, "at": at, "ok": True, "arguments": {"q": "x"}}),
            "eval_grade": "A"}


def snapshot_dir(tmp_path, rows, previous=None, now=NOW, **kw):
    snap = R.build_snapshot(rows, now, previous, **kw)
    R.write_snapshot(snap, tmp_path)
    return snap


def test_listing_rules_and_entry_shape(tmp_path):
    rows = [row(1, "io.github.example/weather"),
            row(2, "io.github.example/stale", at=NOW - 8 * 86400),                       # no success in 7 days
            row(3, "bad name with spaces"),
            row(4, "io.github.example/long", description="x" * 101),
            row(5, "io.github.example/keyed", remotes=[{"type": "streamable-http", "url": "https://k.example.com/mcp",
                                                        "headers": [{"name": "Authorization", "isRequired": True}]}]),
            row(9, "io.github.example/optional", remotes=[{"type": "streamable-http", "url": "https://o.example.com/mcp",
                                                           "headers": [{"name": "Authorization", "isSecret": True,
                                                                        "description": "Optional key", "x": 1}]}]),
            row(6, "io.github.example/private", remotes=[{"type": "streamable-http", "url": "https://127.0.0.1/mcp"}]),
            row(7, "io.github.example/risky"),
            row(8, "io.github.example/by-name")]
    snap = R.build_snapshot(rows, NOW, risky={"io.github.example/risky"},
                            fingerprints={1: {"server_fp": "ab" * 32, "version": "fingerprint-v1",
                                              "unchanged_since": "2026-11-10T00:00:00Z"}})
    assert snap["listed"] == 2
    assert [s["server"]["name"] for s in snap["servers"]] == ["io.github.example/optional", "io.github.example/weather"]
    assert snap["servers"][0]["server"]["remotes"][0]["headers"] == [
        {"name": "Authorization", "description": "Optional key", "isSecret": True}]   # optional header kept as written
    item = snap["servers"][1]
    assert item["server"] == {"$schema": R.SCHEMA_URL, "name": "io.github.example/weather",
                              "description": "Weather forecasts for any city.", "version": "1.2.0",
                              "remotes": [{"type": "streamable-http", "url": "https://1.example.com/mcp"}],
                              "repository": {"url": "https://github.com/example/weather", "source": "github"},
                              "websiteUrl": "https://example.com"}
    meta = item["_meta"][R.META_KEY]
    assert meta["listed"] and meta["checked_tool"] == "get_forecast" and meta["grade"] == "A" and meta["checked_without_headers"]
    assert meta["tools_fingerprint"] == "sha256:" + "ab" * 32 and "arguments" not in json.dumps(meta)
    assert meta["evidence"] == "https://agentconcierge.biz/agent/1" and "Not affiliated" in meta["notice"]
    assert "io.modelcontextprotocol.registry/official" not in item["_meta"]   # never invented


def test_routes_follow_the_v01_shape_with_cors_and_cursor(tmp_path):
    names = [f"io.github.example/s{i:02d}" for i in range(5)]
    snapshot_dir(tmp_path, [row(i + 1, n) for i, n in enumerate(names)])
    app = FastAPI()
    app.include_router(S.router_for(R.SnapshotIndex(tmp_path)))
    client = TestClient(app)
    first = client.get(S.BASE + "/servers", params={"limit": 2, "version": "latest"})
    assert first.status_code == 200 and first.headers["access-control-allow-origin"] == "*"
    assert first.headers["access-control-allow-methods"] == "GET, OPTIONS"
    body = first.json()
    assert [s["server"]["name"] for s in body["servers"]] == names[:2] and body["metadata"]["count"] == 2
    second = client.get(S.BASE + "/servers", params={"limit": 2, "cursor": body["metadata"]["nextCursor"]}).json()
    assert [s["server"]["name"] for s in second["servers"]] == names[2:4]
    last = client.get(S.BASE + "/servers", params={"limit": 2, "cursor": second["metadata"]["nextCursor"]}).json()
    assert [s["server"]["name"] for s in last["servers"]] == names[4:] and last["metadata"]["nextCursor"] is None
    bad = client.get(S.BASE + "/servers", params={"cursor": "%%%"})
    assert bad.status_code == 400 and bad.json()["detail"] == "Invalid cursor parameter"
    assert [s["server"]["name"] for s in client.get(S.BASE + "/servers", params={"search": "S03"}).json()["servers"]] == [names[3]]
    latest = client.get(S.BASE + "/servers/io.github.example%2Fs01/versions/latest")
    assert latest.status_code == 200 and latest.json()["server"]["name"] == names[1]
    assert client.get(S.BASE + "/servers/io.github.example%2Fs01/versions/1.2.0").json()["server"]["version"] == "1.2.0"
    assert client.get(S.BASE + "/servers/io.github.example%2Fs01/versions/9.9.9").status_code == 404
    listed = client.get(S.BASE + "/servers/io.github.example%2Fs01/versions").json()
    assert listed["metadata"]["count"] == 1
    assert client.get(S.BASE + "/servers/io.github.example%2Fnope/versions/latest").status_code == 404
    pre = client.options(S.BASE + "/servers")
    assert pre.status_code == 204 and pre.headers["access-control-allow-headers"] == "Authorization, Content-Type"
    cached = client.get(S.BASE + "/servers", headers={"if-none-match": first.headers["etag"]})
    assert cached.status_code == 304


def test_servers_that_drop_out_stay_30_days_only_in_updated_since(tmp_path):
    first = snapshot_dir(tmp_path, [row(1, "io.github.example/a"), row(2, "io.github.example/b")], now=NOW)
    later = NOW + 3 * 86400
    second = snapshot_dir(tmp_path, [row(1, "io.github.example/a", at=later - 60)], previous=first, now=later)
    gone = [s for s in second["servers"] if s["server"]["name"] == "io.github.example/b"][0]
    assert gone["_meta"][R.META_KEY]["listed"] is False and gone["_meta"][R.META_KEY]["reason"]
    index = R.SnapshotIndex(tmp_path)
    assert [s["server"]["name"] for s in R.list_page(index.current())["servers"]] == ["io.github.example/a"]
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW + 86400))
    delta = R.list_page(index.current(), updated_since=since)
    # Only entries whose registry data changed (or that dropped out) count as updated; a fresher success time alone
    # does not make clients fetch the entry again.
    assert {s["server"]["name"] for s in delta["servers"]} == {"io.github.example/b"}
    assert R.version(index.current(), "io.github.example/b", "latest") is None
    much_later = NOW + 40 * 86400
    third = R.build_snapshot([row(1, "io.github.example/a", at=much_later - 60)], much_later, second)
    assert [s["server"]["name"] for s in third["servers"]] == ["io.github.example/a"]


def test_unchanged_entries_keep_their_updated_at(tmp_path):
    first = R.build_snapshot([row(1, "io.github.example/a", at=NOW - 10)], NOW)
    second = R.build_snapshot([row(1, "io.github.example/a", at=NOW - 10)], NOW + 3600, first)
    meta = lambda s: s["servers"][0]["_meta"][R.META_KEY]   # noqa: E731
    assert meta(second)["updated_at"] == meta(first)["updated_at"]
    third = R.build_snapshot([row(1, "io.github.example/a", at=NOW - 10, version="1.3.0")], NOW + 7200, second)
    assert meta(third)["updated_at"] != meta(first)["updated_at"]


def test_job_reads_in_id_pages_and_skips_measurement_windows(tmp_path):
    class Store:
        def __init__(self):
            self.calls = []

        def query(self, sql, params):
            assert sql == R.SELECT_PAGE
            self.calls.append(params[0])
            after = params[0]
            rows = [row(i, f"io.github.example/s{i:04d}") for i in range(after + 1, min(after + 1000, 2500) + 1)]
            return rows
    store = Store()
    assert len(R.read_rows(store)) == 2500 and store.calls == [0, 1000, 2000]
    quiet = time.mktime((2026, 11, 15, 10, 57, 0, 0, 0, -1))
    assert R.run_job(store, now=quiet, folder=tmp_path) == {"skipped": "measurement_window"}


def test_preparing_before_the_first_snapshot(tmp_path):
    app = FastAPI()
    app.include_router(S.router_for(R.SnapshotIndex(tmp_path / "none")))
    response = TestClient(app).get(S.BASE + "/servers")
    assert response.status_code == 503 and response.headers["retry-after"] == "300"
    assert response.headers["access-control-allow-origin"] == "*"


@pytest.mark.parametrize("cursor", ["", None])
def test_empty_cursor_starts_at_the_top(tmp_path, cursor):
    snapshot_dir(tmp_path, [row(1, "io.github.example/a")])
    assert R.list_page(R.SnapshotIndex(tmp_path).current(), cursor=cursor)["metadata"]["count"] == 1


def test_entries_validate_against_the_official_server_schema():
    """tests/data/mcp-server.schema-2025-12-11.json is a copy of
    https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json (modelcontextprotocol/registry)."""
    from pathlib import Path
    import jsonschema
    schema = json.loads((Path(__file__).parent / "data" / "mcp-server.schema-2025-12-11.json").read_text())
    rows = [row(1, "io.github.example/weather"),
            row(2, "io.github.example/optional", remotes=[{"type": "sse", "url": "https://o.example.com/sse",
                                                           "headers": [{"name": "X-Key", "isSecret": True,
                                                                        "description": "Optional key"}]}])]
    validator = jsonschema.validators.validator_for(schema)(schema)
    for item in R.build_snapshot(rows, NOW)["servers"]:
        assert not list(validator.iter_errors(item["server"])), item["server"]["name"]


def test_mounted_in_the_public_front_with_its_own_headers(tmp_path, monkeypatch):
    """The full public app serves the registry; the shared-cache middleware passes its CORS and cache headers through."""
    from agent_market.concierge.front import Front, clear_front_caches, create_front_app
    from agent_market.gateway.store import Store
    snapshot_dir(tmp_path / "registry", [row(1, "io.github.example/weather")])
    monkeypatch.setenv("VERIFIED_REGISTRY_DATA", str(tmp_path / "registry"))
    store = Store(str(tmp_path / "front.db"))
    clear_front_caches()
    front = Front(store)
    client = TestClient(create_front_app(front, manage_book_lifecycle=False))
    try:
        listed = client.get("/registry/verified/v0.1/servers?version=latest&limit=10")
        assert listed.status_code == 200 and listed.json()["servers"][0]["server"]["name"] == "io.github.example/weather"
        assert listed.headers["access-control-allow-origin"] == "*"
        assert listed.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=300"
        assert client.get("/registry/verified/v0.1/servers/io.github.example%2Fweather/versions/latest").status_code == 200
        assert client.options("/registry/verified/v0.1/servers").status_code == 204
    finally:
        client.close()
        front.book.close()
        store._db.close()

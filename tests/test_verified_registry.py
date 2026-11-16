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
        remotes=None, website="https://example.com", tool="get_forecast", url=None):
    details = {"registry_name": name, "version": version, "website": website,
               "repository": {"url": "https://github.com/example/weather", "source": "github"},
               "remotes": remotes if remotes is not None else [{"type": "streamable-http", "url": f"https://{rid}.example.com/mcp"}]}
    # the endpoint the collector called (C09): the first declared remote unless a test says otherwise
    url = url or (remotes[0].get("url") if remotes else None) or f"https://{rid}.example.com/mcp"
    return {"id": rid, "name": name.split("/")[-1], "description": description, "url": url,
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
    snap = R.build_snapshot(rows, NOW, risky={7}, risk_checked=True,
                            fingerprints={1: {"server_fp": "ab" * 32, "version": "fingerprint-v1",
                                              "as_of": "2026-11-14T04:21:40+0900"}})
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
    assert meta["definition_risk_check"] == "clear"
    unchecked = R.build_snapshot([row(1, "io.github.example/weather")], NOW)["servers"][0]["_meta"][R.META_KEY]
    assert unchecked["definition_risk_check"] == "not_checked_yet" and "tools_fingerprint" not in unchecked
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
    assert [s["server"]["name"] for s in last["servers"]] == names[4:] and "nextCursor" not in last["metadata"]
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
    monkeypatch.setattr(R, "_DEFAULT", None)   # the process-wide index reads the folder set above
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
        line = client.get("/status.json").json()["verified_registry"]
        assert line["listed"] == 1 and line["url"].endswith("/registry/verified") and line["snapshot"]
    finally:
        client.close()
        front.book.close()
        store._db.close()


def test_fingerprint_records_by_resource_id_and_risk_check_availability(tmp_path, monkeypatch):
    monkeypatch.setenv("FINGERPRINT_DATA", str(tmp_path))
    (tmp_path / "pearls.json").write_text(json.dumps({"version": "fingerprint-v1", "generated": "2026-11-14T04:21:40+0900",
                                                      "pearls": {"33328": {"server_fp": "aa" * 32, "tools": {}}}}))
    fps, risky, available = R.load_fingerprints(NOW)
    assert fps[33328]["server_fp"] == "aa" * 32 and risky == frozenset() and available is False   # no change log yet
    today = time.strftime("%Y%m%d", time.localtime(NOW))
    local = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(NOW - 600))   # how operations write 'at' (+0900)
    (tmp_path / f"changes-{today}.jsonl").write_text("\n".join(json.dumps(r) for r in (
        {"at": local, "source": "health", "resource_id": 5, "server_fp": "bb" * 32, "classification": "risk"},
        {"at": R._iso(NOW - 300), "source": "health", "resource_id": 6, "server_fp": "cc" * 32,
         "classification": "dynamic"})))
    fps, risky, available = R.load_fingerprints(NOW)
    assert risky == frozenset({5}) and fps[6]["server_fp"] == "cc" * 32
    assert available is False          # member checks alone do not cover the catalog
    with (tmp_path / f"changes-{today}.jsonl").open("a") as fh:
        fh.write("\n" + json.dumps({"at": local, "source": "survey", "resource_id": 7, "server_fp": "dd" * 32,
                                    "classification": "general"}))
    assert R.load_fingerprints(NOW)[2] is True


def test_members_measured_recently_are_risk_checked_before_the_survey_log(tmp_path, monkeypatch):
    """Operations' member file (resources[rid], every 6 hours) covers members only, so only they say 'clear'."""
    monkeypatch.setenv("FINGERPRINT_DATA", str(tmp_path))
    measured = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(NOW - 3600))
    (tmp_path / "pearls.json").write_text(json.dumps({"version": "fingerprint-v1", "resources": {
        "1": {"current": "ee" * 32, "measured_at": measured, "classification": "same", "risk": []},
        "3": {"current": "ff" * 32, "measured_at": measured, "classification": "risk", "risk": ["hint_flipped"]}}}))
    fps, risky, available = R.load_fingerprints(NOW)
    assert fps[1]["checked"] and risky == frozenset({3}) and available is False
    snap = R.build_snapshot([row(1, "io.github.example/member"), row(2, "io.github.example/other"),
                             row(3, "io.github.example/risky")], NOW, None, fps, risky, available)
    meta = {s["server"]["name"]: s["_meta"][R.META_KEY] for s in snap["servers"]}
    assert meta["io.github.example/member"]["definition_risk_check"] == "clear"
    assert meta["io.github.example/member"]["tools_fingerprint"] == "sha256:" + "ee" * 32
    assert meta["io.github.example/other"]["definition_risk_check"] == "not_checked_yet"
    assert "io.github.example/risky" not in meta


def test_a_server_that_falls_below_the_rules_leaves_the_next_snapshot_and_the_change_log_says_why(tmp_path):
    """PM 11-15: 'delisted' is the most useful signal for an organization's allowlist."""
    rows = [row(1, "io.github.example/stays"), row(2, "io.github.example/stale"), row(3, "io.github.example/risky"),
            row(4, "io.github.example/gone")]
    first = R.build_snapshot(rows, NOW)
    assert first["listed"] == 4 and first["events"] == []          # the first snapshot is not news
    later = NOW + 8 * 86400
    rows2 = [row(1, "io.github.example/stays", at=later - 60), row(2, "io.github.example/stale"),   # 8 days old now
             row(3, "io.github.example/risky", at=later - 60), row(5, "io.github.example/new", at=later - 60)]
    second = R.build_snapshot(rows2, later, first, risky={3}, risk_checked=True)
    listed = [s["server"]["name"] for s in second["servers"] if s["_meta"][R.META_KEY]["listed"]]
    assert listed == ["io.github.example/new", "io.github.example/stays"]
    events = {e["name"]: e for e in second["events"]}
    assert events["io.github.example/stale"]["reason"] == "no_recent_success"
    assert events["io.github.example/risky"]["reason"] == "definition_risk"
    assert events["io.github.example/gone"]["reason"] == "left_catalog_criteria"   # no longer returned by the query
    assert events["io.github.example/new"]["event"] == "listed"
    assert {e["event"] for n, e in events.items() if n != "io.github.example/new"} == {"delisted"}
    gone = {s["server"]["name"]: s["_meta"][R.META_KEY] for s in second["servers"] if not s["_meta"][R.META_KEY]["listed"]}
    assert gone["io.github.example/risky"]["reason"] == "definition_risk"
    third = R.build_snapshot(rows2, later + 3600, second, risky={3}, risk_checked=True)
    assert third["events"] == []                                     # each change is logged once


def test_job_writes_listing_events_beside_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("FINGERPRINT_DATA", str(tmp_path / "fp"))

    class Store:
        def __init__(self, rows):
            self.rows = rows

        def query(self, sql, params):
            return [r for r in self.rows if r["id"] > params[0]][:1000]
    noon = time.mktime((2026, 11, 15, 12, 30, 0, 0, 0, -1))
    assert R.run_job(Store([row(1, "io.github.example/a", at=noon - 60), row(2, "io.github.example/b", at=noon - 60)]),
                     now=noon, folder=tmp_path)["listed"] == 2
    later = noon + 3600
    R.run_job(Store([row(1, "io.github.example/a", at=later - 60)]), now=later, folder=tmp_path)
    lines = [json.loads(x) for x in (tmp_path / ("events-" + time.strftime("%Y%m%d", time.localtime(later)) + ".jsonl"))
             .read_text().splitlines()]
    assert lines == [{"at": R._iso(later), "event": "delisted", "name": "io.github.example/b", "version": "1.2.0",
                      "reason": "left_catalog_criteria"}]
    assert "events" not in json.loads((tmp_path / "verified.json").read_text())


def _openapi():
    """tests/data/mcp-registry-openapi-2025-12-01.json: docs/reference/api/openapi.yaml of modelcontextprotocol/registry
    (OpenAPI 3.1, info.version 2025-12-01), converted to JSON without changes."""
    from pathlib import Path
    return json.loads((Path(__file__).parent / "data" / "mcp-registry-openapi-2025-12-01.json").read_text())


def _validator(doc, schema):
    import jsonschema
    root = {**schema, "components": doc["components"]}
    return jsonschema.Draft202012Validator(root)


def test_responses_validate_against_the_official_openapi_document(tmp_path):
    doc = _openapi()
    names = [f"io.github.example/s{i:02d}" for i in range(3)]
    snapshot_dir(tmp_path, [row(i + 1, n) for i, n in enumerate(names)] + [
        row(9, "io.github.example/optional", remotes=[{"type": "sse", "url": "https://o.example.com/sse",
                                                       "headers": [{"name": "X-Key", "isSecret": True, "description": "Optional"}]}])])
    app = FastAPI()
    app.include_router(S.router_for(R.SnapshotIndex(tmp_path)))
    client = TestClient(app)
    paths = doc["paths"]

    def check(path_key, status, response):
        schema = paths[path_key]["get"]["responses"][str(status)]["content"]["application/json"]["schema"]
        errors = list(_validator(doc, schema).iter_errors(response.json()))
        assert not errors, [e.message for e in errors][:3]

    page = client.get(S.BASE + "/servers", params={"limit": 2, "version": "latest"})
    check("/v0.1/servers", 200, page)
    check("/v0.1/servers", 200, client.get(S.BASE + "/servers", params={"cursor": page.json()["metadata"]["nextCursor"]}))
    check("/v0.1/servers", 200, client.get(S.BASE + "/servers", params={"search": "s01"}))
    check("/v0.1/servers/{serverName}/versions", 200, client.get(S.BASE + "/servers/io.github.example%2Fs01/versions"))
    check("/v0.1/servers/{serverName}/versions/{version}", 200,
          client.get(S.BASE + "/servers/io.github.example%2Foptional/versions/latest"))
    check("/v0.1/servers/{serverName}/versions", 404, client.get(S.BASE + "/servers/io.github.example%2Fnone/versions"))
    check("/v0.1/servers/{serverName}/versions/{version}", 404,
          client.get(S.BASE + "/servers/io.github.example%2Fnone/versions/latest"))
    bad = client.get(S.BASE + "/servers", params={"cursor": "!!"})
    assert bad.status_code == 400 and bad.json()["error"] == "Invalid cursor parameter"


def test_repository_kept_as_a_url_becomes_the_official_object():
    """11-15 comparison with the official registry: our collector keeps repository as its URL; the entry must carry
    {url, source} like the official one (6 of 7 compared servers lacked it before this fix)."""
    r = row(1, "io.github.example/weather")
    details = json.loads(r["details"])
    details["repository"] = "https://github.com/example/weather"
    r["details"] = json.dumps(details)
    assert R.entry(r, NOW)["server"]["repository"] == {"url": "https://github.com/example/weather", "source": "github"}
    details["repository"] = "https://git.example.org/x/y"            # unknown forge: no source, so left out
    r["details"] = json.dumps(details)
    assert "repository" not in R.entry(r, NOW)["server"]


def test_contract_with_the_member_fingerprint_writer(tmp_path, monkeypatch):
    """Operations review 11-15: the member step's latest reading (resources[rid]) wins over the 11-14 baseline,
    with its own measure time, and a change line it writes in the same run does not override it."""
    from datetime import datetime
    from agent_market import member_fingerprints as mf
    from agent_market.tool_fingerprint import server_fp
    weather = {"name": "get_weather", "description": "Forecast", "inputSchema": {"type": "object"}}
    old_tools, new_tools = [weather], [{**weather, "description": "Hourly forecast and alerts"}]
    (tmp_path / "pearls.json").write_text(json.dumps({"generated": "2026-11-14T04:21:40+0900", "pearls": {
        "1": {"server_fp": server_fp(old_tools), "baseline_at": "2026-11-14T04:21:40+0900", "tools": {}}}}))
    state = {"tools": old_tools}
    rows = {1: {"id": 1, "kind": "mcp", "url": "https://1.example.com/mcp"}}

    def run(ts):
        mf.refresh(rows.get, lambda url: state["tools"], data=tmp_path, now=ts, ids=[1], reserve=lambda u: (True, "ok"),
                   note=lambda u, s: None, sleep=lambda s: None)
    first, second = datetime(2026, 11, 16, 10, 15).timestamp(), datetime(2026, 11, 16, 16, 15).timestamp()
    run(first)
    state["tools"] = new_tools
    run(second)
    monkeypatch.setenv("FINGERPRINT_DATA", str(tmp_path))
    fps, risky, available = R.load_fingerprints(second + 60)
    assert fps[1]["server_fp"] == server_fp(new_tools) and fps[1]["as_of"].startswith("2026-11-16T16:15")
    assert fps[1]["checked"] and risky == frozenset() and available is False
    snap = R.build_snapshot([row(1, "io.github.example/member", at=second)], second + 60, None, fps, risky, available)
    meta = snap["servers"][0]["_meta"][R.META_KEY]
    assert meta["tools_fingerprint"] == "sha256:" + server_fp(new_tools)
    assert meta["tools_unchanged_since"].startswith("2026-11-16T16:15") and meta["definition_risk_check"] == "clear"


def test_snapshot_write_uses_a_unique_temp_file_and_cleans_up(tmp_path, monkeypatch):
    R.write_snapshot({"servers": [], "listed": 0}, tmp_path)
    before = (tmp_path / "verified.json").read_bytes()
    (tmp_path / ".verified.json.tmp").write_text("someone else's")       # an old fixed name is never touched

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(R.os, "replace", boom)
    with pytest.raises(OSError):
        R.write_snapshot({"servers": [], "listed": 1}, tmp_path)
    assert (tmp_path / "verified.json").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [".verified.json.tmp", "verified.json"]
    assert (tmp_path / ".verified.json.tmp").read_text() == "someone else's"


def test_rate_limit_ignores_a_client_sent_ip_header(tmp_path):
    snapshot_dir(tmp_path, [row(1, "io.github.example/a")])
    app = FastAPI()
    app.include_router(S.router_for(R.SnapshotIndex(tmp_path)))
    client = TestClient(app)
    codes = [client.get(S.BASE + "/servers", headers={"cf-connecting-ip": f"203.0.113.{i}"}).status_code
             for i in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429       # a new header value per request is the same client
    seen = []
    app2 = FastAPI()
    app2.include_router(S.router_for(R.SnapshotIndex(tmp_path), resolve_ip=lambda request: seen.append(1) or "198.51.100.7"))
    assert TestClient(app2).get(S.BASE + "/servers").status_code == 200 and seen == [1]


# ---------------------------------------------------------------- source review C09 / C10 (11-16)
def test_only_the_endpoint_we_called_is_a_verified_remote():
    """A called; the publisher adds B on another domain: B is never under server.remotes, only named as unverified."""
    a = {"type": "streamable-http", "url": "https://a.example.com/mcp"}
    b = {"type": "streamable-http", "url": "https://other-domain.example.net/mcp"}
    item = R.entry(row(1, "io.github.example/weather", remotes=[b, a], url="https://A.example.com/mcp/"), NOW)
    assert item["server"]["remotes"] == [a]
    meta = item["_meta"][R.META_KEY]
    assert meta["checked_endpoint"] == {"url": a["url"], "type": "streamable-http"}
    assert meta["unverified_remotes"] == [b] and meta["verified_scope"] == "checked_endpoint_and_tool"
    assert meta["checked_tool"] == "get_forecast" and meta["observed_at"] == meta["last_success_at"]


def test_a_changed_endpoint_is_not_listed_and_says_why():
    r = row(1, "io.github.example/weather", remotes=[{"type": "streamable-http", "url": "https://new.example.com/mcp"}],
            url="https://old.example.com/mcp")
    assert R.entry(r, NOW) is None
    assert R.exclusion_reason(r, NOW) == "endpoint_not_checked"


@pytest.mark.parametrize("at", [float("nan"), float("inf"), NOW + 3600, "soon", None, 0])
def test_broken_or_future_trial_times_are_never_a_success(at):
    r = row(1, "io.github.example/weather", at=at)
    assert R.entry(r, NOW) is None and R.exclusion_reason(r, NOW) == "no_recent_success"


def test_canonical_endpoint_ignores_case_default_port_and_trailing_slash_only():
    assert R.canonical_endpoint("https://A.Example.com:443/mcp/") == R.canonical_endpoint("https://a.example.com/mcp")
    assert R.canonical_endpoint("https://a.example.com/mcp?x=1") != R.canonical_endpoint("https://a.example.com/mcp")
    assert R.canonical_endpoint("https://a.example.com:8443/mcp") != R.canonical_endpoint("https://a.example.com/mcp")
    assert R.canonical_endpoint("http://a.example.com/mcp") is None


def test_a_fingerprint_change_alone_moves_updated_at_and_a_plain_rebuild_does_not():
    rows = [row(1, "io.github.example/weather")]
    first = R.build_snapshot(rows, NOW, None, {1: {"server_fp": "aa", "version": "v1", "as_of": "x"}})
    again = R.build_snapshot(rows, NOW + 600, first, {1: {"server_fp": "aa", "version": "v1", "as_of": "x"}})
    assert again["servers"][0]["_meta"][R.META_KEY]["updated_at"] == R._iso(NOW)       # nothing changed
    changed = R.build_snapshot(rows, NOW + 1200, again, {1: {"server_fp": "bb", "version": "v1", "as_of": "x"}})
    assert changed["servers"][0]["_meta"][R.META_KEY]["updated_at"] == R._iso(NOW + 1200)
    assert R.content_hash(again["servers"][0]) != R.content_hash(changed["servers"][0])


def test_trial_fingerprint_against_the_latest_one():
    """PM 11-16: the fingerprint at trial time vs the latest; a change after our call means recheck_pending."""
    def with_fp(server_fp):
        r = row(1, "io.github.example/weather")
        trial = json.loads(r["trial_info"])
        if server_fp:
            trial.update(server_fp=server_fp, fp_version="fingerprint-v1")
        return {**r, "trial_info": json.dumps(trial)}
    latest = {1: {"server_fp": "aa", "version": "fingerprint-v1", "as_of": "x"}}
    meta = R.entry(with_fp("aa"), NOW, latest)["_meta"][R.META_KEY]
    assert meta["fingerprint_match"] == "match" and meta["verification_state"] == "verified"
    assert meta["trial_fingerprint"] == "sha256:aa"
    meta = R.entry(with_fp("bb"), NOW, latest)["_meta"][R.META_KEY]
    assert meta["fingerprint_match"] == "mismatch" and meta["verification_state"] == "recheck_pending"
    meta = R.entry(with_fp(None), NOW, latest)["_meta"][R.META_KEY]       # older trials: no field, nothing made up
    assert meta["fingerprint_match"] == "not_comparable" and "trial_fingerprint" not in meta
    meta = R.entry(with_fp("aa"), NOW, {})["_meta"][R.META_KEY]            # no latest fingerprint
    assert meta["fingerprint_match"] == "not_comparable"

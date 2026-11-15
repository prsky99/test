"""E6 lifecycle signals: unresponsive servers, domains near expiry (RDAP), similar names."""
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market import tool_lifecycle as L
from agent_market import verified_registry as R
from agent_market import verified_registry_service as S

NOW = 1_800_000_000.0
DAY = 86400


def row(rid, name, *, status="healthy", failing_since=None, owner="example", host=None):
    details = {"registry_name": name, "repository": {"url": f"https://github.com/{owner}/x", "source": "github"},
               "remotes": [{"type": "streamable-http", "url": f"https://{host or f'{rid}.example{rid}.com'}/mcp"}]}
    return {"id": rid, "details": json.dumps(details), "url": f"https://{host or f'{rid}.example{rid}.com'}/mcp",
            "health_status": status, "failing_since": failing_since}


def listed(*names_hosts):
    return {"servers": [{"server": {"name": n, "remotes": [{"type": "streamable-http", "url": f"https://{h}/mcp"}]},
                         "_meta": {R.META_KEY: {"listed": True}}, "_id": i} for i, (n, h) in enumerate(names_hosts)]}


def test_unresponsive_needs_retired_or_more_than_seven_days_of_failure():
    rows = [row(1, "io.github.a/retired", status="retired"),
            row(2, "io.github.a/down8", status="down", failing_since=NOW - 8 * DAY),
            row(3, "io.github.a/down2", status="down", failing_since=NOW - 2 * DAY),      # not yet
            row(4, "io.github.a/healthy", failing_since=NOW - 9 * DAY),                    # recovered
            row(5, "io.github.a/retired", status="retired")]                                # same name once
    out = L.unresponsive(rows, NOW)
    assert [(i["name"], i["state"]) for i in out] == [("io.github.a/down8", "failing_over_7_days"),
                                                      ("io.github.a/retired", "retired")]
    assert out[0]["failing_since"] == R._iso(NOW - 8 * DAY) and out[0]["hosts"] == ["2.example2.com"]


def test_similar_names_need_a_different_owner_and_domain():
    rows = [row(1, "io.github.modelcontext/weather", owner="modelcontext", host="mc.dev"),
            row(2, "io.github.modelc0ntext/weather", owner="modelc0ntext", host="evil.dev"),   # look-alike
            row(3, "io.github.modelcontext/weathers", owner="modelcontext", host="mc.dev"),    # same owner
            row(4, "io.github.modelcontext/weatherx", owner="someone", host="mc.dev"),         # same domain
            row(5, "io.github.modelcontexts/weather", owner="other", host="other.io"),         # one edit
            row(6, "io.github.unrelated/thing", owner="u", host="u.io"),
            row(7, "de.dinilu/mcp", owner="d1", host="mcp.dinilu.de"),
            row(8, "dk.dinilu/mcp", owner="d2", host="mcp.dinilu.dk")]                    # one brand, two countries
    out = L.similar_names(rows, {"io.github.modelcontext/weather", "de.dinilu/mcp"})
    assert [(i["name"], i["kind"]) for i in out] == [("io.github.modelc0ntext/weather", "lookalike_characters"),
                                                     ("io.github.modelcontexts/weather", "one_edit")]
    assert all(i["resembles"] == "io.github.modelcontext/weather" and not i["name_is_verified"] for i in out)


class Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.content = json.dumps(body).encode()

    def json(self):
        return self._body


class Http:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def get(self, url, headers=None):
        self.calls.append(url)
        if url == L.BOOTSTRAP_URL:
            services = [[["com", "net"], ["https://rdap.verisign.com/com/v1/"]], [["io"], ["https://rdap.nic.io/"]]]
            services += [[[f"t{i}"], [f"https://rdap.t{i}.example/"]] for i in range(120)]
            return Response(200, {"services": services})
        status, body = self.answers.get(url, (404, {}))
        return Response(status, body)


def expiry(days):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW + days * DAY))
    return {"events": [{"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"},
                       {"eventAction": "expiration", "eventDate": stamp}],
            "entities": [{"roles": ["registrant"], "vcardArray": ["vcard", [["fn", {}, "text", "Private Person"]]]}]}


def test_rdap_reads_by_server_budget_cache_and_only_the_expiry_date():
    snapshot = listed(("io.github.a/one", "api.one.com"), ("io.github.a/two", "two.com"), ("io.github.a/three", "x.three.io"),
                      ("io.github.a/tenant", "me.vercel.app"))
    domains = L.registrable_domains(snapshot)
    assert set(domains) == {"one.com", "two.com", "three.io"}                 # a hosting tenant is not read
    http = Http({"https://rdap.verisign.com/com/v1/domain/one.com": (200, expiry(20)),
                 "https://rdap.verisign.com/com/v1/domain/two.com": (200, expiry(400)),
                 "https://rdap.nic.io/domain/three.io": (429, {})})
    budget = {"verisign.com": 2, "nic.io": 5, "iana.org": 1}
    reserved, notes = [], []

    def reserve(url):
        from agent_market.provider_budget import domain
        reserved.append(url)
        left = budget.get(domain(url), 0)
        budget[domain(url)] = left - 1
        return (left > 0, "ok" if left > 0 else "share")
    state = {}
    counts = L.read_expiry(domains, state, NOW, http=http, reserve=reserve,
                           note=lambda url, status, evidence=None: notes.append((url, status, evidence)), sleep=lambda s: None,
                           check_public_url=lambda url: None)
    assert counts == {"read": 3, "refused": 0, "failed": 1} and notes[0][1] == 429
    cache = state["domains"]
    assert cache["one.com"]["expires"].startswith(time.strftime("%Y-%m-%d", time.gmtime(NOW + 20 * DAY)))
    assert "three.io" not in cache                                            # 429: try another day
    assert "Private" not in json.dumps(state)                                 # no registrant data kept
    out = L.expiring(domains, cache, NOW)
    assert [i["domain"] for i in out] == ["one.com"] and out[0]["servers"] == ["io.github.a/one"]
    # the next day: bootstrap from the cache, near-expiry domains wait 7 days, far ones 90
    http.calls.clear()
    assert L.due(cache, domains, NOW + DAY) == ["three.io"]
    assert set(L.due(cache, domains, NOW + 8 * DAY)) == {"three.io", "one.com"}
    budget["verisign.com"] = 0
    counts = L.read_expiry(domains, state, NOW + 8 * DAY, http=http, reserve=reserve, note=lambda *a, **k: None,
                           sleep=lambda s: None, check_public_url=lambda url: None)
    assert L.BOOTSTRAP_URL not in http.calls and counts["refused"] == 1        # Verisign's share is used up


def test_job_writes_the_file_and_the_route_serves_it(tmp_path):
    R.write_snapshot(listed(("io.github.a/one", "api.one.com")), tmp_path)

    class Store:
        def query(self, sql, params):
            assert sql == R.SELECT_OFFICIAL
            rows = [row(1, "io.github.a/one", owner="a", host="api.one.com"),
                    row(2, "io.github.a/0ne", owner="b", host="zero.dev"),
                    row(3, "io.github.b/gone", status="retired")]
            return [r for r in rows if r["id"] > params[0]]
    http = Http({"https://rdap.verisign.com/com/v1/domain/one.com": (200, expiry(10))})
    noon = time.mktime((2026, 11, 15, 12, 30, 0, 0, 0, -1))
    out = L.run_job(Store(), now=noon, folder=tmp_path, http=http, reserve=lambda url: (True, "ok"),
                    note=lambda *a, **k: None, sleep=lambda s: None, check_public_url=lambda url: None)
    assert out["unresponsive"] == 1 and out["similar_name"] == 1 and out["domains_checked"] == 1
    data = json.loads((tmp_path / L.FILE).read_text())
    assert set(data["rules"]) == {"unresponsive", "domain_expiring", "similar_name"}
    assert data["similar_name"][0]["name"] == "io.github.a/0ne"
    app = FastAPI()
    app.include_router(S.router_for(R.SnapshotIndex(tmp_path), lifecycle_index=L.LifecycleIndex(tmp_path)))
    client = TestClient(app)
    answer = client.get(L.PATH)
    assert answer.status_code == 200 and answer.headers["access-control-allow-origin"] == "*"
    assert answer.json()["coverage"]["verified_servers"] == 1
    assert client.get(L.PATH, headers={"if-none-match": answer.headers["etag"]}).status_code == 304
    quiet = time.mktime((2026, 11, 15, 4, 0, 0, 0, 0, -1))
    assert L.run_job(Store(), now=quiet, folder=tmp_path, http=http) == {"skipped": "measurement_window"}
    empty = FastAPI()
    empty.include_router(S.router_for(R.SnapshotIndex(tmp_path / "none"), lifecycle_index=L.LifecycleIndex(tmp_path / "none")))
    assert TestClient(empty).get(L.PATH).status_code == 503


def test_members_first_and_far_dates_are_not_read_again():
    """PM 11-15 12:3x: members' and pearls' domains first, then recent or failing ones; a read date waits for 60 days."""
    snapshot = listed(("io.github.a/plain", "plain.com"), ("io.github.a/member", "member.com"),
                      ("io.github.a/failing", "failing.com"))
    for item in snapshot["servers"]:
        item["_meta"][R.META_KEY]["updated_at"] = R._iso(NOW - 90 * DAY)
    rows = [row(9, "io.github.b/other", status="down", failing_since=NOW - DAY, host="api.failing.com")]
    rank = L.priorities(snapshot, rows, [1], NOW)
    assert rank == {"member.com": 0, "failing.com": 1, "plain.com": 2}
    assert L.due({}, rank, NOW, rank) == ["member.com", "failing.com", "plain.com"]
    far = {"checked_at": NOW, "expires": R._iso(NOW + 400 * DAY), "status": "ok"}
    blank = {"checked_at": NOW, "expires": None, "status": "not_found"}
    cache = {"member.com": far, "failing.com": blank}
    assert L.due(cache, rank, NOW + 200 * DAY, rank) == ["plain.com", "failing.com"]   # 400-day date waits
    assert "member.com" in L.due(cache, rank, NOW + 345 * DAY, rank)                  # within 60 days of expiry

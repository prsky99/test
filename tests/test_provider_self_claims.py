"""Provider self-service claims (docs/PROVIDER_SELF_CLAIM.md, PM decisions 11-15): SQLite and mocked HTTP only."""
import json

import httpx
import pytest

from agent_market import provider_self_claims as P

RESOURCES = {
    1: {"id": 1, "active": 1, "kind": "a2a", "url": "https://agents.example.com/a2a/alpha", "health_status": "healthy",
        "trial_info": json.dumps({"tool": "message/send", "at": 1.0, "ok": True, "arguments": {"secret": "x"}})},
    2: {"id": 2, "active": 1, "kind": "a2a", "url": "https://agents.example.com/a2a/beta"},
    3: {"id": 3, "active": 1, "kind": "mcp", "url": "https://mcp.example.org/mcp"},
    4: {"id": 4, "active": 1, "kind": "mcp", "url": "https://server.smithery.ai/@someone/tool/mcp"},
    5: {"id": 5, "active": 1, "kind": "x402", "url": "https://pay.example.net/api"},
    6: {"id": 6, "active": 0, "kind": "mcp", "url": "https://gone.example.org/mcp"},
}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def service(tmp_path, handler=None, reserve=None, resources=None, clock=None):
    calls = []

    def respond(request):
        calls.append((request.method, str(request.url)))
        return handler(request) if handler else httpx.Response(404)
    http = httpx.Client(transport=httpx.MockTransport(respond))
    reserved = []
    svc = P.ProviderSelfClaims(P.SqliteClaimDB(tmp_path / "claims.sqlite3"), (resources or RESOURCES).get, http=http,
                               clock=clock or Clock(), reserve=reserve or (lambda url, n: reserved.append(url) or True),
                               reports_dir=tmp_path / "reports", retest_file=tmp_path / "retest-queue.json",
                               public_check=lambda url: True)
    return svc, calls, reserved


def well_known(svc_holder):
    def handler(request):
        claim = svc_holder["claim"]
        return httpx.Response(200, json={"profile": P.PROFILE, "claim": claim["claim_id"], "nonce": claim["nonce"]})
    return handler


def test_prepare_makes_no_outside_call_and_shows_the_value_once(tmp_path):
    svc, calls, _ = service(tmp_path)
    out = svc.prepare("cust-1", 1, "well_known")
    assert calls == [] and out["origin"] == "https://agents.example.com"
    assert out["instructions"]["publish_at"] == "https://agents.example.com/.well-known/agentvalcon-claim.json"
    assert out["instructions"]["content"] == {"profile": P.PROFILE, "claim": out["claim_id"], "nonce": out["nonce"]}
    listed = svc.claims("cust-1")["items"]
    assert len(listed) == 1 and "nonce" not in json.dumps(listed) and out["nonce"] not in json.dumps(listed)


def test_prepare_rules(tmp_path):
    svc, _, _ = service(tmp_path)
    for rid, method, code in ((4, "well_known", "shared_host_use_protocol"), (5, "protocol", "protocol_needs_mcp_or_a2a"),
                              (6, "well_known", "resource_not_found"), (1, "dns_txt", "invalid_method")):
        with pytest.raises(P.ClaimError) as err:
            svc.prepare("cust-1", rid, method)
        assert err.value.code == code
    assert svc.prepare("cust-1", 4, "protocol")["instructions"]["text"].startswith("agentvalcon-claim=")
    first = svc.prepare("cust-1", 1, "well_known")
    second = svc.prepare("cust-1", 2, "well_known")   # same origin: the unused value is replaced
    statuses = {c["id"]: c["status"] for c in svc.claims("cust-1")["items"]}
    assert statuses[first["claim_id"]] == "expired" and statuses[second["claim_id"]] == "pending"


def test_well_known_check_verifies_and_covers_every_resource_on_the_origin(tmp_path):
    holder = {}
    svc, calls, reserved = service(tmp_path, well_known(holder))
    holder["claim"] = svc.prepare("cust-1", 1, "well_known")
    assert svc.verify("cust-1", holder["claim"]["claim_id"]) == {"claim_id": holder["claim"]["claim_id"],
                                                                 "status": "verified", "outcome": "verified"}
    assert calls == [("GET", "https://agents.example.com/.well-known/agentvalcon-claim.json")]
    assert reserved == ["https://agents.example.com/.well-known/agentvalcon-claim.json"]
    for rid in (1, 2):   # both resources on the origin
        assert svc.benefits("cust-1", rid)["resource_id"] == rid
    with pytest.raises(P.ClaimError) as err:
        svc.benefits("cust-2", 1)                     # another account proves nothing
    assert err.value.code == "not_verified_for_resource"


@pytest.mark.parametrize("response,outcome", [
    (httpx.Response(200, content=b'{"profile":"agentvalcon-provider-claim-v1","claim":"x","claim":"y","nonce":"n"}'),
     "invalid_body"),
    (httpx.Response(200, json={"profile": P.PROFILE, "claim": "CLAIM", "nonce": "wrong-value-wrong-value-x"}),
     "value_mismatch"),
    (httpx.Response(302, headers={"location": "https://elsewhere.example/claim.json"}), "http_status"),
    (httpx.Response(200, content=b"x" * 5000), "response_too_large"),
])
def test_failed_checks_leave_the_claim_pending(tmp_path, response, outcome):
    holder = {}

    def handler(request):
        if b'"CLAIM"' in response.content:
            return httpx.Response(200, json={"profile": P.PROFILE, "claim": holder["claim"]["claim_id"],
                                             "nonce": "wrong-value-wrong-value-x"})
        return response
    clock = Clock()
    svc, _, _ = service(tmp_path, handler, clock=clock)
    holder["claim"] = svc.prepare("cust-1", 1, "well_known")
    out = svc.verify("cust-1", holder["claim"]["claim_id"])
    assert out["status"] == "pending" and out["outcome"] == outcome
    [row] = svc.claims("cust-1")["items"]
    assert row["status"] == "pending" and row["last_error"] == outcome


def test_budget_refusal_and_private_address_make_no_request(tmp_path):
    svc, calls, _ = service(tmp_path, reserve=lambda url, n: False)
    claim = svc.prepare("cust-1", 1, "well_known")
    assert svc.verify("cust-1", claim["claim_id"])["outcome"] == "call_budget_refused" and calls == []
    (tmp_path / "b").mkdir()
    svc2, calls2, _ = service(tmp_path / "b")
    svc2._public_check = lambda url: False
    claim = svc2.prepare("cust-1", 1, "well_known")
    assert svc2.verify("cust-1", claim["claim_id"])["outcome"] == "not_public_address" and calls2 == []


def test_check_limits_per_origin_and_per_day(tmp_path):
    clock = Clock()
    svc, _, _ = service(tmp_path, lambda r: httpx.Response(404), clock=clock)
    claim = svc.prepare("cust-1", 1, "well_known")
    svc.verify("cust-1", claim["claim_id"])
    with pytest.raises(P.ClaimError) as err:
        svc.verify("cust-1", claim["claim_id"])
    assert err.value.code == "origin_checked_recently"
    for _ in range(P.MAX_CHECKS_A_DAY - 1):
        clock.t += 61
        svc.verify("cust-1", claim["claim_id"])
    clock.t += 61
    with pytest.raises(P.ClaimError) as err:
        svc.verify("cust-1", claim["claim_id"])
    assert err.value.code == "too_many_checks"


def test_mcp_marker_in_initialize_instructions_or_meta_only(tmp_path):
    holder = {}

    def handler(request):
        body = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "x"},
                                                      **holder["result"]}}
        return httpx.Response(200, text="event: message\ndata: " + json.dumps(body) + "\n\n",
                              headers={"content-type": "text/event-stream"})
    svc, calls, _ = service(tmp_path, handler)
    claim = svc.prepare("cust-1", 3, "protocol")
    holder["result"] = {"capabilities": {"tools": {"description": "agentvalcon-claim=" + claim["nonce"]}}}
    assert svc.verify("cust-1", claim["claim_id"])["outcome"] == "value_mismatch"   # not instructions or _meta
    svc.clock.t += 61
    holder["result"] = {"instructions": "Hello. agentvalcon-claim=" + claim["nonce"]}
    assert svc.verify("cust-1", claim["claim_id"])["status"] == "verified"
    assert calls[-1][0] == "POST" and calls[-1][1] == "https://mcp.example.org/mcp"
    with pytest.raises(P.ClaimError):
        svc.benefits("cust-1", 1)            # a protocol claim covers its own resource only
    assert svc.benefits("cust-1", 3)["resource_id"] == 3


def test_a2a_card_extension(tmp_path):
    holder = {}

    def handler(request):
        return httpx.Response(200, json={"name": "Alpha", "capabilities": {"extensions": [
            {"uri": P.A2A_EXTENSION, "params": {"nonce": holder["claim"]["nonce"]}}]}})
    svc, calls, _ = service(tmp_path, handler)
    holder["claim"] = svc.prepare("cust-1", 1, "protocol")
    assert svc.verify("cust-1", holder["claim"]["claim_id"])["status"] == "verified"
    assert calls == [("GET", "https://agents.example.com/.well-known/agent-card.json")]


def test_benefits_are_read_only_and_drop_a_moved_resource(tmp_path):
    holder = {}
    resources = {k: dict(v) for k, v in RESOURCES.items()}
    svc, _, _ = service(tmp_path, well_known(holder), resources=resources)
    holder["claim"] = svc.prepare("cust-1", 1, "well_known")
    svc.verify("cust-1", holder["claim"]["claim_id"])
    report = tmp_path / "reports" / "1" / "news.search.v1" / "20261115-010101-search.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"outcome": "failed", "reason": "timeout", "quality": {"score": 40.0},
                                  "evaluator_version": "dq-2026-11-14b"}))
    (tmp_path / "retest-queue.json").write_text(json.dumps({"generated": "2026-11-15 09:00",
                                                            "items": [{"id": 9}, {"id": 1}, {"id": 7}]}))
    out = svc.benefits("cust-1", 1)
    assert out["test_reports"][0]["reason"] == "timeout" and out["test_reports"][0]["score"] == 40.0
    assert out["retest_queue"] == {"available": True, "as_of": "2026-11-15 09:00", "queued": True, "position": 2, "of": 3}
    assert out["last_trial"] == {"tool": "message/send", "at": 1.0, "ok": True}   # arguments are never shown
    assert "never changed" in out["note"]
    resources[1]["url"] = "https://new-home.example.net/a2a/alpha"
    with pytest.raises(P.ClaimError):
        svc.benefits("cust-1", 1)


def test_corrections_are_queued_never_applied(tmp_path):
    holder = {}
    svc, _, _ = service(tmp_path, well_known(holder))
    holder["claim"] = svc.prepare("cust-1", 1, "well_known")
    with pytest.raises(P.ClaimError):
        svc.request_correction("cust-1", 1, "description", "Better text")   # not verified yet
    svc.verify("cust-1", holder["claim"]["claim_id"])
    req = svc.request_correction("cust-1", 1, "description", "  Answers  questions about weather. ",
                                 "https://agents.example.com/docs")
    assert req["status"] == "open"
    for bad in (("grade", "A", None), ("name", "", None), ("name", "x" * 1001, None), ("name", "ok", "ftp://x")):
        with pytest.raises(P.ClaimError):
            svc.request_correction("cust-1", 1, *bad)
    [waiting] = svc.waiting_corrections()
    assert waiting["proposed"] == "Answers questions about weather." and waiting["status"] == "open"
    assert svc.decide_correction(req["request_id"], "held", "agent team", "need the doc page")
    assert svc.decide_correction(req["request_id"], "applied", "agent team")
    assert not svc.decide_correction(req["request_id"], "declined", "agent team")   # decided already
    assert RESOURCES[1].get("description") is None                                  # nothing applied by code


def test_recheck_extends_or_lapses_after_two_failures(tmp_path):
    holder = {"ok": True}
    clock = Clock()

    def handler(request):
        if not holder["ok"]:
            return httpx.Response(404)
        return httpx.Response(200, json={"profile": P.PROFILE, "claim": holder["claim"]["claim_id"],
                                         "nonce": holder["claim"]["nonce"]})
    svc, _, _ = service(tmp_path, handler, clock=clock)
    holder["claim"] = svc.prepare("cust-1", 1, "well_known")
    svc.verify("cust-1", holder["claim"]["claim_id"])
    assert svc.recheck_due() == {"available": True, "verified": 0, "retry": 0, "lapsed": 0}   # not due yet
    clock.t += P.VALID_S - P.RECHECK_BEFORE_S + 1
    assert svc.recheck_due()["verified"] == 1
    holder["ok"] = False
    clock.t += P.VALID_S - P.RECHECK_BEFORE_S + 1
    assert svc.recheck_due()["retry"] == 1
    clock.t += P.RETRY_S + 1
    assert svc.recheck_due()["lapsed"] == 1
    assert svc.claims("cust-1")["items"][0]["status"] == "lapsed"
    with pytest.raises(P.ClaimError):
        svc.benefits("cust-1", 1)


def test_withdraw_and_limits(tmp_path):
    svc, _, _ = service(tmp_path)
    claim = svc.prepare("cust-1", 1, "well_known")
    assert svc.withdraw("cust-1", claim["claim_id"])["status"] == "withdrawn"
    with pytest.raises(P.ClaimError):
        svc.withdraw("cust-2", claim["claim_id"])


class Off:
    backend = "postgres"

    def ready(self):
        return False


def test_feature_is_off_until_the_tables_exist(tmp_path):
    svc = P.ProviderSelfClaims(Off(), RESOURCES.get, public_check=lambda url: True)
    assert svc.claims("cust-1") == {"available": False, "items": []}
    assert svc.recheck_due() == {"available": False}
    with pytest.raises(P.ClaimError) as err:
        svc.prepare("cust-1", 1, "well_known")
    assert (err.value.code, err.value.status) == ("provider_claims_not_available", 409)


def test_postgres_change_stays_in_its_own_schema():
    ddl = P.postgres_schema_statements()
    assert ddl[0] == "CREATE SCHEMA IF NOT EXISTS provider_claims" and ddl[1] == "SET LOCAL search_path TO provider_claims"
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "deploy" / "db-changes"
    script = (root / "provider-claims-v1.sql").read_text()
    assert ";\n".join(ddl) + ";" in script and script.rstrip().endswith("COMMIT;")   # the checked-in file is this DDL
    assert "DROP SCHEMA IF EXISTS provider_claims CASCADE;" in (root / "provider-claims-v1-rollback.sql").read_text()
    text = " ".join(ddl).upper()
    assert "TRIGGER" not in text and "FUNCTION" not in text and "PUBLIC." not in text and " REAL" not in text
    assert P.postgres_rollback_statements() == ["DROP SCHEMA IF EXISTS provider_claims CASCADE"]
    assert all("%" not in sql for sql in P.SQL.values())   # '?' becomes '%s' on PostgreSQL


def test_routes_need_the_customer_and_map_errors(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from agent_market import provider_self_claims_service as S
    holder = {}
    svc, _, _ = service(tmp_path, well_known(holder))

    def actor(request, identity, csrf=False):
        if request.headers.get("x-test-customer") is None:
            raise HTTPException(401, "Sign in to continue.")
        return SimpleNamespace(customer_id=request.headers["x-test-customer"])
    monkeypatch.setattr(S, "customer_actor", actor)
    app = FastAPI()
    app.include_router(S.router_for(identity=None, service=svc))
    client = TestClient(app)
    me = {"x-test-customer": "cust-1"}
    assert client.get(S.BASE).status_code == 401
    assert client.get(S.BASE, headers={**me, "authorization": "Bearer x"}).status_code == 403
    made = client.post(S.BASE, headers=me, json={"resource_id": 1, "method": "well_known"})
    assert made.status_code == 201 and made.json()["instructions"]["content"]["profile"] == P.PROFILE
    holder["claim"] = made.json()
    assert client.post(S.BASE, headers=me, json={"resource_id": 1}).status_code == 400
    assert client.post(S.BASE, headers=me, json={"resource_id": 1, "method": "well_known", "x": 1}).status_code == 400
    assert client.post(S.BASE + "/" + holder["claim"]["claim_id"] + "/verify", headers=me).json()["status"] == "verified"
    assert client.get(S.BASE + "/resources/1", headers=me).json()["resource_id"] == 1
    denied = client.get(S.BASE + "/resources/1", headers={"x-test-customer": "cust-2"})
    assert denied.status_code == 403 and denied.json()["detail"] == {"code": "not_verified_for_resource"}
    fix = client.post(S.BASE + "/resources/1/corrections", headers=me, json={"field": "name", "proposed": "Alpha Agent"})
    assert fix.status_code == 201 and fix.json()["status"] == "open"


def test_routes_are_off_on_a_store_without_the_claims_schema(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market import provider_self_claims_service as S
    monkeypatch.setattr(S, "customer_actor", lambda request, identity, csrf=False: SimpleNamespace(customer_id="c"))
    store = SimpleNamespace(backend="sqlite", resource=RESOURCES.get)
    app = FastAPI()
    app.include_router(S.router_for(identity=None, store=store))
    client = TestClient(app)
    assert client.get(S.BASE).json() == {"ok": True, "available": False, "items": []}
    off = client.post(S.BASE, json={"resource_id": 1, "method": "well_known"})
    assert off.status_code == 409 and off.json()["detail"] == {"code": "provider_claims_not_available"}


def test_recheck_job_stays_out_of_measurement_windows():
    from types import SimpleNamespace
    from agent_market import provider_self_claims_service as S
    store = SimpleNamespace(backend="sqlite", resource=RESOURCES.get)
    import time
    quiet = time.mktime((2026, 11, 15, 10, 57, 0, 0, 0, -1))
    open_ = time.mktime((2026, 11, 15, 10, 30, 0, 0, 0, -1))
    assert S.recheck_job(store, now=quiet) == {"skipped": "measurement_window"}
    assert S.recheck_job(store, now=open_) == {"available": False}


def test_postgres_db_opens_short_connections_sends_registered_sql_and_stays_off_while_missing(monkeypatch):
    from contextlib import contextmanager
    sent, opened, closed = [], [], []

    class Cursor:
        def __init__(self, rows):
            self.rows, self.rowcount = rows, len(rows)

        def execute(self, sql, args):
            sent.append((sql, args))
            if "provider_claim_schema" in sql and state["missing"]:
                raise RuntimeError('relation "provider_claim_schema" does not exist')

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Connection:
        autocommit = False

        def __init__(self):
            opened.append(self)

        def execute(self, sql, args=()):
            sent.append((sql, args))

        def cursor(self, row_factory=None):
            return Cursor([{"version": 1}])

        @contextmanager
        def transaction(self):
            yield self

        def close(self):
            closed.append(self)

    state = {"missing": True}
    clock = Clock()
    db = P.PostgresClaimDB(Connection, clock=clock)
    assert db.ready() is False
    assert ("SET search_path TO provider_claims", ()) in sent and ("SET statement_timeout = 2000", ()) in sent
    assert len(opened) == len(closed) == 1          # no standing connection, even while off
    state["missing"] = False
    assert db.ready() is False and len(opened) == 1  # checked again only after RETRY_S, without a connection
    clock.t += P.PostgresClaimDB.RETRY_S + 1
    assert db.ready() is True
    sent.clear()
    with db.tx():
        db.run("claims_expire_pending", (5.0,))
        db.one("claims_live_count", ("c",))
    assert len(opened) == len(closed) == 3           # one connection for the whole transaction, closed after
    assert [q for q, _ in sent if not q.startswith("SET")] == [
        P.SQL["claims_expire_pending"].replace("?", "%s"), P.SQL["claims_live_count"].replace("?", "%s")]
    monkeypatch.setitem(P.SQL, "claims_live_count", "SELECT 1")   # code changed without updating the registry
    with pytest.raises(RuntimeError, match="unregistered_sql"):
        db.one("claims_live_count", ("c",))
    db2 = P.PostgresClaimDB(Connection, clock=clock)
    assert db2.ready() is False                       # a registry that does not match the code keeps it off


def test_sql_registry_matches_the_code():
    """After changing SQL: python -m agent_market.provider_self_claims --write-sql-registry (reviewed in git)."""
    assert P.registered_digests() == P.sql_digests() and len(P.sql_digests()) == len(P.SQL)

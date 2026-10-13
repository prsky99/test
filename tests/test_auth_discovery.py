import json

import httpx
import pytest

from agent_market.collector.auth_discovery import AuthDiscoverer, parse_www_authenticate
from agent_market.gateway.store import Store
from tests.test_constraints import mcp_resource
from tests.test_gateway import GW_World

AS_META = {
    "issuer": "https://auth.example", "authorization_endpoint": "https://auth.example/authorize",
    "token_endpoint": "https://auth.example/token", "registration_endpoint": "https://auth.example/register",
    "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
}


class FakeAuthWeb(httpx.BaseTransport):
    def __init__(self):
        self.routes, self.calls = {}, []

    def handle_request(self, request):
        url = str(request.url)
        self.calls.append((request.method, url, request.headers.get("authorization")))
        fn = self.routes.get((request.method, url)) or self.routes.get(("*", url))
        return fn(request) if fn else httpx.Response(404)


def oauth_server(web, url, as_meta=AS_META, prm_via_header=True):
    prm_url = url.replace("/mcp", "") + "/.well-known/oauth-protected-resource/mcp"
    www = f'Bearer resource_metadata="{prm_url}", scope="read"' if prm_via_header else "Bearer"
    web.routes[("POST", url)] = lambda r: httpx.Response(401, headers={"www-authenticate": www}, json={"error": "unauthorized"})
    web.routes[("GET", prm_url)] = lambda r: httpx.Response(200, json={
        "resource": url, "authorization_servers": [as_meta["issuer"]], "scopes_supported": ["read"]})
    web.routes[("GET", as_meta["issuer"] + "/.well-known/oauth-authorization-server")] = lambda r: httpx.Response(200, json=as_meta)


@pytest.fixture
def env():
    store, web = Store(), FakeAuthWeb()
    disc = AuthDiscoverer(store, http=httpx.Client(transport=web), allow_private=True, per_host_delay=0)
    return store, web, disc


def mark_auth_required(store, rid):
    with store.tx() as db:
        db.execute("UPDATE resources SET auth_observed=1 WHERE id=?", (rid,))


def test_parse_www_authenticate():
    p = parse_www_authenticate('Bearer resource_metadata="https://x/.well-known/oauth-protected-resource", scope="a b", error=invalid_token')
    assert p == {"scheme": "Bearer", "resource_metadata": "https://x/.well-known/oauth-protected-resource", "scope": "a b", "error": "invalid_token"}
    assert parse_www_authenticate(None) == {}


def test_oauth_with_dynamic_registration_needs_human_once(env):
    store, web, disc = env
    oauth_server(web, "https://o.example/mcp")
    found = disc.discover(store.resource(mcp_resource(store, "https://o.example/mcp")), disc._fixed_http)
    assert found["method"] == "oauth2" and found["autonomy"] == "human_once"
    o = found["info"]["oauth"]
    assert o["registration_endpoint"] == "https://auth.example/register" and o["scopes"] == ["read"]
    assert o["resource"] == "https://o.example/mcp"
    text = " ".join(found["info"]["instructions"])
    assert "Dynamic Client Registration" in text and "PKCE" in text and "Authorization: Bearer" in text
    assert all(auth is None for _, _, auth in web.calls)  # 자격 증명은 절대 보내지 않음


def test_client_credentials_with_registration_is_agent_autonomous(env):
    store, web, disc = env
    oauth_server(web, "https://m2m.example/mcp", as_meta={**AS_META, "grant_types_supported": ["client_credentials"]})
    found = disc.discover(store.resource(mcp_resource(store, "https://m2m.example/mcp")), disc._fixed_http)
    assert found["autonomy"] == "agent_autonomous"
    assert any("without a human" in s for s in found["info"]["instructions"])


def test_metadata_found_by_well_known_path_without_header(env):
    store, web, disc = env
    oauth_server(web, "https://wk.example/mcp", prm_via_header=False)
    found = disc.discover(store.resource(mcp_resource(store, "https://wk.example/mcp")), disc._fixed_http)
    assert found["method"] == "oauth2" and found["info"]["oauth"]["protected_resource_metadata"].endswith("/oauth-protected-resource/mcp")


def test_api_key_with_signup_link(env):
    store, web, disc = env
    url = "https://k.example/mcp"
    web.routes[("POST", url)] = lambda r: httpx.Response(401, json={"error": "API key required. Get one at https://k.example/signup."})
    rid = mcp_resource(store, url, remotes=[{"url": url, "headers": [
        {"name": "X-API-Key", "description": "Your key from the dashboard", "isRequired": True, "isSecret": True}]}])
    found = disc.discover(store.resource(rid), disc._fixed_http)
    assert found["method"] == "api_key" and found["autonomy"] == "human_once"
    assert found["info"]["api_key"]["header"] == "X-API-Key" and found["info"]["api_key"]["where_to_get"] == ["https://k.example/signup"]
    assert "X-API-Key: <key>" in " ".join(found["info"]["instructions"])


def test_actually_open_server_is_reset_to_no_auth(env):
    store, web, disc = env
    url = "https://open.example/mcp"
    web.routes[("POST", url)] = lambda r: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}})
    rid = mcp_resource(store, url)
    mark_auth_required(store, rid)
    stats = disc.run_due()
    assert stats["none"] == 1 and store.resource(rid)["auth_observed"] == 0 and store.resource(rid)["auth_method"] == "none"


def test_run_due_only_auth_required_and_shares_as_metadata(env):
    store, web, disc = env
    for host in ("a", "b"):
        oauth_server(web, f"https://{host}.example/mcp")
        mark_auth_required(store, mcp_resource(store, f"https://{host}.example/mcp"))
    mcp_resource(store, "https://free.example/mcp")  # 인증 불필요(모름)는 조사하지 않음
    stats = disc.run_due()
    assert stats["checked"] == 2 and stats["oauth2"] == 2
    as_calls = [c for c in web.calls if c[1].endswith("/.well-known/oauth-authorization-server")]
    assert len(as_calls) == 1  # 같은 인증 서버 메타데이터는 한 번만 받음
    assert disc.run_due()["checked"] == 0  # 일주일 안에는 다시 조사하지 않음


def test_private_metadata_urls_are_not_fetched():
    store = Store()
    disc = AuthDiscoverer(store, http=httpx.Client(transport=FakeAuthWeb()), allow_private=False)
    assert disc._json(disc._fixed_http, "http://127.0.0.1/.well-known/oauth-protected-resource") is None


# ---------------- 게이트웨이 ----------------

def test_gateway_auth_agent_option_and_instructions():
    w = GW_World()
    w.reg.mcp = [
        {"server": {"name": f"io.ex/{n}", "title": f"{n} news", "description": "Company news search",
                    "remotes": [{"type": "streamable-http", "url": f"https://{n}.example/mcp"}]}, "_meta": {}}
        for n in ("human", "robot")
    ]
    w.crawl()
    ids = {r["url"]: r["id"] for r in w.store.query("SELECT id, url FROM resources")}
    for name, autonomy in (("human", "human_once"), ("robot", "agent_autonomous")):
        rid = ids[f"https://{name}.example/mcp"]
        mark_auth_required(w.store, rid)
        w.store.record_auth(rid, {"method": "oauth2", "autonomy": autonomy,
                                  "info": {"instructions": [f"steps for {name}"], "oauth": {"token_endpoint": "https://auth/token"}}})
    out = w.client().create_need("company news search", kinds=["mcp"], auth="agent")
    auth = out["agent"]["constraints"]["auth"]
    assert out["agent"]["url"] == "https://robot.example/mcp"
    assert auth["method"] == "oauth2" and auth["autonomy"] == "agent_autonomous" and auth["instructions"] == ["steps for robot"]
    assert w.client().create_need("company news search", kinds=["mcp"], auth="none")["status"] == "watching"


def test_x402_agents_explain_payment_instead_of_login():
    w = GW_World()
    from tests.test_gateway import x402_item
    w.reg.x402 = [x402_item("https://pay.example/api", "Company news search API", 5_000, 100)]
    w.crawl()
    auth = w.client().create_need("company news search", kinds=["x402"], auth="agent")["agent"]["constraints"]["auth"]
    assert auth["method"] == "x402_payment" and auth["required"] is False
    assert json.dumps(auth).count("USDC") == 1



def test_huge_metadata_is_compacted_not_truncated(env):
    store, web, disc = env
    big = {**AS_META, "scopes_supported": [f"scope:{i}:" + "x" * 50 for i in range(500)]}
    oauth_server(web, "https://big.example/mcp", as_meta=big)
    rid = mcp_resource(store, "https://big.example/mcp")
    mark_auth_required(store, rid)
    disc.run_due()
    info = json.loads(store.resource(rid)["auth_info"])  # 깨지지 않은 JSON
    assert len(info["oauth"]["scopes_supported"]) == 20

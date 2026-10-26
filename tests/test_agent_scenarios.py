import base64
import json

import httpx

from scripts.agent_scenarios import Runner, decode_x402, readiness_scanner, run, text_of


def test_text_of_drops_scripts_and_tags():
    assert text_of("<p>Hi <b>there</b></p><script>var x='hidden'</script>") == "Hi there"


def test_decode_x402_header():
    raw = base64.b64encode(json.dumps({"x402Version": 2, "accepts": [{"scheme": "exact"}]}).encode()).decode().rstrip("=")
    assert decode_x402(raw)["accepts"][0]["scheme"] == "exact"
    assert decode_x402("not base64!!") is None


def _site(request):
    p = request.url.path
    if request.method == "HEAD":
        return httpx.Response(405)
    if p == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
    if p in ("/llms.txt",):
        return httpx.Response(200, text="# x", headers={"content-type": "text/markdown"})
    if p.endswith(".json"):
        return httpx.Response(200, json={}, headers={"content-type": "application/json"})
    if p == "/sitemap.xml":
        return httpx.Response(200, text="<urlset/>", headers={"content-type": "application/xml"})
    return httpx.Response(404, json={"detail": "Not Found"})


def test_readiness_flags_head_405():
    R = Runner("https://example.test", httpx.Client(transport=httpx.MockTransport(_site)))
    readiness_scanner(R)
    head = [r for r in R.results if r["name"].startswith("HEAD")]
    assert head and all(r["status"] == "FAIL" for r in head)
    ct = [r for r in R.results if r["name"] == "발견 파일의 Content-Type"][0]
    assert ct["status"] == "PASS"


def test_run_survives_broken_kind():
    def boom(request):
        raise httpx.ConnectError("down")
    results = run("https://example.test", httpx.Client(transport=httpx.MockTransport(boom)), {"crawler", "readiness"})
    assert {r["kind"] for r in results} == {"crawler", "readiness"}
    assert all(r["status"] == "FAIL" for r in results)

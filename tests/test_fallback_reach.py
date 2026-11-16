"""site.reachability (agent team 11-16): one GET, redirects followed hop by hop through net.get, our refusals raised."""
import httpx
import pytest

from agent_market.fallback_agents.limits import HostLimiter, SourceBusy
from agent_market.fallback_agents.reach import reach


def client(routes):
    def handler(request):
        return routes[str(request.url)]
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_follows_redirects_to_the_final_page():
    http = client({"https://example.com/": httpx.Response(301, headers={"location": "https://www.example.com/"}),
                   "https://www.example.com/": httpx.Response(200, text="ok")})
    out = reach("https://example.com/", limiters={}, http=http)
    assert out | {"elapsed_ms": 0} == {"reachable": True, "status": 200, "final_url": "https://www.example.com/",
                                       "https": True, "redirects": 1, "elapsed_ms": 0, "note": None}


def test_a_redirect_to_plain_http_is_not_followed():
    http = client({"https://example.com/": httpx.Response(302, headers={"location": "http://example.com/"})})
    out = reach("https://example.com/", limiters={}, http=http)
    assert not out["reachable"] and out["https"] is False and out["note"] == "redirects to a non-https address"


def test_the_sites_own_503_is_an_answer_about_the_site():
    out = reach("https://example.com/", limiters={}, http=client({"https://example.com/": httpx.Response(503)}))
    assert out["reachable"] is False and out["status"] == 503 and out["note"] == "HTTP 503"


def test_too_many_redirects_and_404():
    loop = {f"https://example.com/{i}": httpx.Response(302, headers={"location": f"https://example.com/{i + 1}"})
            for i in range(10)}
    out = reach("https://example.com/0", limiters={}, http=client(loop), seconds=10)
    assert not out["reachable"] and out["redirects"] == 5 and "more than 5 redirects" in out["note"]
    out = reach("https://example.com/", limiters={}, http=client({"https://example.com/": httpx.Response(404)}))
    assert out["reachable"] is False and out["status"] == 404


def test_our_own_spacing_refusal_is_raised_not_reported_as_down():
    lim = HostLimiter(1.0)
    lim.rest_until = lim.clock() + 600
    with pytest.raises(SourceBusy):
        reach("https://example.com/", limiters={"example.com": lim}, http=client({}))


def test_only_https_urls():
    with pytest.raises(ValueError):
        reach("http://example.com/", limiters={})

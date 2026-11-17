"""AgentValCon fallback agents (agent team 11-14): contracts, pacing, snapshot, sources.

All network traffic here is an in-process httpx.MockTransport; no public source is called.
"""
import gzip
import hashlib
import io
import json
from pathlib import Path

import httpx
import jsonschema
import pytest

from agent_market.fallback_agents import SPECS, FallbackAgents, FallbackUnavailable, slot_output, tool_spec
from agent_market.fallback_agents import net
from agent_market.fallback_agents.catalog import contract
from agent_market.fallback_agents.limits import HostLimiter, SourceBusy, limiters
from agent_market.fallback_agents.nvd_store import Snapshot, iter_feed, record

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def nvd_cve(cve_id="CVE-2021-44228", modified="2026-01-01T00:00:00.000", status="Analyzed", **extra):
    cve = {"id": cve_id, "published": "2021-12-10T10:15:09.143", "lastModified": modified, "vulnStatus": status,
           "descriptions": [{"lang": "es", "value": "x"}, {"lang": "en", "value": "Apache  Log4j2\nJNDI features"}],
           "metrics": {"cvssMetricV31": [
               {"type": "Secondary", "cvssData": {"version": "3.1", "baseScore": 9.8, "vectorString": "CVSS:3.1/AV:N/S"}},
               {"type": "Primary", "cvssData": {"version": "3.1", "baseScore": 10.0, "vectorString": "CVSS:3.1/AV:N/P"}}],
               "cvssMetricV2": [{"type": "Primary", "cvssData": {"version": "2.0", "baseScore": 9.3}}]},
           "references": [{"url": "http://insecure.example/a"}, {"url": "https://logging.apache.org/log4j/2.x/security.html"},
                          {"url": "https://logging.apache.org/log4j/2.x/security.html"}]}
    cve.update(extra)
    return {"cve": cve}


def feed_bytes(items):
    text = json.dumps({"resultsPerPage": len(items), "format": "NVD_CVE", "version": "2.0",
                       "vulnerabilities": items}).encode()
    return gzip.compress(text), hashlib.sha256(text).hexdigest()


def client(routes, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        for prefix, answer in routes.items():
            if str(request.url).startswith(prefix):
                return answer(request) if callable(answer) else answer
        return httpx.Response(404, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


def agents(tmp_path, routes, calls=None, clock=None, snapshot=None):
    clock = clock or Clock()
    return FallbackAgents(http=client(routes, calls), data_dir=tmp_path, clock=clock, wall=lambda: 1.8e9 + clock.t,
                          limiters=limiters(clock=clock, sleep=clock.sleep), snapshot=snapshot), clock


# ------------------------------------------------------------------ catalog and contracts
def test_tools_are_read_only_and_use_the_slot_contracts():
    assert set(SPECS) == {"nvd-cve", "cve-org", "cisa-kev", "github-advisory", "package-registry", "depsdev-package", "gleif-lei", "sec-edgar", "wikipedia-summary", "arxiv-search", "worldbank-indicator", "met-weather", "public-holidays", "holiday-calendar", "sec-filings", "software-incident", "scorecard", "site-readiness", "wiki-grounding", "ecb-fx", "usgs-quakes", "tz-time", "airport-lookup", "wiktionary-define", "github-repo", "rdap-domain", "unit-convert", "wikidata-place", "wikidata-book", "gdelt-news", "census-geocode", "mcp-registry", "github-releases", "package-releases", "tls-certificate", "sec-company-profile", "sun-times", "site-reachability", "dns-spf-dmarc"}
    for agent_id, spec in SPECS.items():
        tool = tool_spec(agent_id)
        c = contract(spec["contract"])
        assert tool["inputSchema"] == c["input_schema"] and tool["outputSchema"] == c["output_schema"]
        assert tool["annotations"] == {"readOnlyHint": True, "destructiveHint": False,
                                       "idempotentHint": True, "openWorldHint": True}
        assert tool["description"].isascii() and "Agentcon " not in spec["name"]
        assert spec["name"].startswith("AgentValCon ")
        for source in spec["sources"]:
            assert source["url"].startswith("https://") and source["license"] and source["notice"]


def test_necklace_definition_names_match_the_agents():
    defn = json.loads((ROOT / "agent_market/necklaces/definitions/cve-incident-brief.json").read_text())
    links = [(slot["contract"], link) for slot in defn["slots"] for link in slot["chain"] if link["kind"] == "agentcon"]
    assert links, "cve-incident-brief has AgentValCon links"
    for contract_id, link in links:
        assert link["agent_id"] in SPECS
        assert SPECS[link["agent_id"]]["tool"] == link["tool"]
        assert SPECS[link["agent_id"]]["contract"] == contract_id


def test_nvd_notice_and_user_agent_carry_the_public_contact():
    from agent_market.fallback_agents.catalog import NVD, USER_AGENT
    assert "not endorsed or certified by the NVD" in NVD["notice"]
    assert "contact@agentconcierge.biz" in USER_AGENT and USER_AGENT.startswith("AgentValCon")


# ------------------------------------------------------------------ NVD record and feed parsing
def test_nvd_record_prefers_newest_version_primary_and_https_references():
    out = record(nvd_cve()["cve"])
    assert out["cvss_score"] == 10.0 and out["cvss_version"] == "3.1" and out["cvss_vector"].endswith("/P")
    assert out["description"] == "Apache Log4j2 JNDI features"
    assert out["references"] == ["https://logging.apache.org/log4j/2.x/security.html"]
    jsonschema.validate(out, contract("cve.record.v1")["output_schema"])
    bare = record({"id": "CVE-2026-0001"})
    assert bare == {"cve_id": "CVE-2026-0001", "source": "NVD"}


def test_iter_feed_streams_items_across_tiny_chunks():
    items = [nvd_cve("CVE-2020-0001"), {"cve": {"id": "CVE-2020-0002", "descriptions": [{"lang": "en", "value": "a ] b , [ c } {"}]}}]
    text = json.dumps({"x": [1, 2], "vulnerabilities": items, "tail": True})
    got = list(iter_feed(io.StringIO(text), chunk=7))
    assert [i["cve"]["id"] for i in got] == ["CVE-2020-0001", "CVE-2020-0002"]
    with pytest.raises(ValueError):
        list(iter_feed(io.StringIO('{"vulnerabilities": [{"cve": {"id": "CVE-2020-0001"}}'), chunk=5))


def feed_routes(feeds):
    routes = {}
    for name, (blob, sha) in feeds.items():
        meta = f"lastModifiedDate:2026-11-13T14:00:06-05:00\nsize:1\ngzSize:{len(blob)}\nsha256:{sha.upper()}\n"
        routes[f"https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{name}.meta"] = httpx.Response(200, text=meta)
        routes[f"https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{name}.json.gz"] = httpx.Response(
            200, content=blob, headers={"content-type": "application/x-gzip"})
    return routes


def test_snapshot_update_checks_sha_keeps_newer_rows_and_skips_unchanged(tmp_path):
    clock = Clock()
    snap = Snapshot(tmp_path / "nvd.sqlite3")
    db = snap._open(snap.path)
    with db:
        snap.ingest(db, [nvd_cve("CVE-2021-44228", modified="2026-06-01T00:00:00.000")])
        db.execute("INSERT INTO meta VALUES ('synced_at', ?)", (repr(1.8e9),))
    db.close()
    older = nvd_cve("CVE-2021-44228", modified="2025-01-01T00:00:00.000", descriptions=[{"lang": "en", "value": "old"}])
    new = nvd_cve("CVE-2026-1234")
    feeds = {"modified": feed_bytes([older, new])}
    calls = []
    report = snap.sync("update", http=client(feed_routes(feeds), calls), limiters=limiters(clock, clock.sleep),
                       now=lambda: 1.8e9 + 3600, log=lambda *_: None)
    assert report["feeds"]["modified"]["rows"] == 2 and report["rows_total"] == 2
    kept, status, synced = snap.lookup("CVE-2021-44228")
    assert kept["description"] == "Apache Log4j2 JNDI features" and status == "Analyzed"
    assert snap.lookup("CVE-2026-1234")[0]["cve_id"] == "CVE-2026-1234"
    assert synced == 1.8e9 + 3600
    again = snap.sync("update", http=client(feed_routes(feeds)), limiters=limiters(clock, clock.sleep),
                      now=lambda: 1.8e9 + 7200, log=lambda *_: None)
    assert again["feeds"]["modified"] == {"skipped": "unchanged"}
    assert clock.t > 1000.0, "feed requests to one host are spaced"


def test_snapshot_rejects_a_feed_whose_hash_does_not_match(tmp_path):
    clock = Clock()
    snap = Snapshot(tmp_path / "nvd.sqlite3")
    db = snap._open(snap.path)
    with db:
        db.execute("INSERT INTO meta VALUES ('synced_at', ?)", (repr(1.8e9),))
    db.close()
    blob, _ = feed_bytes([nvd_cve("CVE-2026-9999")])
    with pytest.raises(RuntimeError, match="SHA-256"):
        snap.sync("update", http=client(feed_routes({"modified": (blob, "0" * 64)})),
                  limiters=limiters(clock, clock.sleep), now=lambda: 1.8e9 + 60, log=lambda *_: None)
    assert snap.lookup("CVE-2026-9999")[0] is None


def test_update_refuses_a_snapshot_older_than_the_modified_window(tmp_path):
    snap = Snapshot(tmp_path / "nvd.sqlite3")
    db = snap._open(snap.path)
    with db:
        db.execute("INSERT INTO meta VALUES ('synced_at', ?)", (repr(1.8e9),))
    db.close()
    clock = Clock()
    with pytest.raises(RuntimeError, match="--full"):
        snap.sync("update", http=client({}), limiters=limiters(clock, clock.sleep), now=lambda: 1.8e9 + 8 * 86400)


# ------------------------------------------------------------------ nvd-cve agent
def seeded_snapshot(tmp_path, *items):
    snap = Snapshot(tmp_path / "nvd.sqlite3")
    db = snap._open(snap.path)
    with db:
        snap.ingest(db, items)
        db.execute("INSERT INTO meta VALUES ('synced_at', ?)", (repr(1.8e9 + 1000.0 - 600),))
    db.close()
    return snap


def test_nvd_agent_answers_from_the_snapshot_without_network(tmp_path):
    calls = []
    a, _ = agents(tmp_path, {}, calls, snapshot=seeded_snapshot(tmp_path, nvd_cve()))
    env = a.execute("nvd-cve", {"cve_id": "CVE-2021-44228"})
    assert calls == []
    assert env["cache"] == {"status": "snapshot", "age_seconds": 600}
    assert slot_output(env)["cvss_score"] == 10.0 and env["sources"][0]["name"].startswith("NVD")
    assert env["tool"] == "get_cve_record" and env["partial"] is False


def test_nvd_agent_rejected_cve_is_not_found(tmp_path):
    a, _ = agents(tmp_path, {}, snapshot=seeded_snapshot(tmp_path, nvd_cve("CVE-2020-1111", status="Rejected")))
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("nvd-cve", {"cve_id": "CVE-2020-1111"})
    assert err.value.code == "not_found"


def test_nvd_agent_snapshot_miss_uses_one_paced_api_call(tmp_path):
    calls = []
    api = {"https://services.nvd.nist.gov/rest/json/cves/2.0": httpx.Response(
        200, json={"vulnerabilities": [nvd_cve("CVE-2026-5555")]})}
    a, _ = agents(tmp_path, api, calls, snapshot=seeded_snapshot(tmp_path, nvd_cve()))
    env = a.execute("nvd-cve", {"cve_id": "CVE-2026-5555"})
    assert env["cache"]["status"] == "live" and calls == ["https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2026-5555"]
    assert a.execute("nvd-cve", {"cve_id": "CVE-2026-5555"})["cache"]["status"] == "fresh_cache"
    assert len(calls) == 1


def test_nvd_agent_api_429_rests_the_host_and_reports_rate_limited(tmp_path):
    calls = []
    api = {"https://services.nvd.nist.gov/": httpx.Response(429, headers={"retry-after": "120"})}
    a, clock = agents(tmp_path, api, calls, snapshot=seeded_snapshot(tmp_path, nvd_cve()))
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("nvd-cve", {"cve_id": "CVE-2026-0002"})
    assert err.value.code == "rate_limited"
    assert a.limiters["services.nvd.nist.gov"].resting() == pytest.approx(120, abs=1)
    with pytest.raises(FallbackUnavailable):
        a.execute("nvd-cve", {"cve_id": "CVE-2026-0003"})
    assert len(calls) == 1, "no request while the host rests"


def test_invalid_input_never_reaches_a_source(tmp_path):
    calls = []
    a, _ = agents(tmp_path, {}, calls)
    for bad in ({"cve_id": "CVE-21-1"}, {"cve_id": "CVE-2021-44228", "x": 1}, {}):
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("cve-org", bad)
        assert err.value.code == "invalid_input"
    with pytest.raises(FallbackUnavailable):
        a.execute("unknown", {"cve_id": "CVE-2021-44228"})
    assert calls == []


# ------------------------------------------------------------------ cve-org agent
def cve5(cve_id="CVE-2024-3094", state="PUBLISHED"):
    return {"cveMetadata": {"cveId": cve_id, "state": state, "datePublished": "2024-03-29T15:51:12.001Z"},
            "containers": {"cna": {"providerMetadata": {"shortName": "redhat"},
                                   "descriptions": [{"lang": "en", "value": "Malicious code in xz"}],
                                   "references": [{"url": "https://access.redhat.com/security/cve/CVE-2024-3094"}],
                                   "metrics": [{"other": {}}, {"cvssV3_1": {"version": "3.1", "baseScore": 10,
                                                                            "vectorString": "CVSS:3.1/AV:N"}}]},
                           "adp": [{"metrics": [{"cvssV3_1": {"version": "3.1", "baseScore": 9.0}}]}]}}


def test_cve_org_agent_reads_the_cna_score_first(tmp_path):
    a, _ = agents(tmp_path, {"https://cveawg.mitre.org/api/cve/CVE-2024-3094": httpx.Response(200, json=cve5())})
    out = slot_output(a.execute("cve-org", {"cve_id": "CVE-2024-3094"}))
    assert out == {"cve_id": "CVE-2024-3094", "source": "CVE Program (score from CNA redhat)", "cvss_score": 10.0, "cvss_version": "3.1",
                   "cvss_vector": "CVSS:3.1/AV:N", "description": "Malicious code in xz",
                   "published": "2024-03-29T15:51:12.001Z",
                   "references": ["https://access.redhat.com/security/cve/CVE-2024-3094"]}


def test_cve_org_agent_prefers_the_newest_cvss_version_in_a_block(tmp_path):
    record_ = cve5()
    record_["containers"]["cna"]["metrics"].append({"cvssV4_0": {"version": "4.0", "baseScore": 2.3}})
    a, _ = agents(tmp_path, {"https://cveawg.mitre.org/": httpx.Response(200, json=record_)})
    out = slot_output(a.execute("cve-org", {"cve_id": "CVE-2024-3094"}))
    assert (out["cvss_score"], out["cvss_version"]) == (2.3, "4.0")


def test_cve_org_agent_uses_adp_score_when_the_cna_has_none(tmp_path):
    record_ = cve5()
    record_["containers"]["cna"]["metrics"] = []
    a, _ = agents(tmp_path, {"https://cveawg.mitre.org/": httpx.Response(200, json=record_)})
    assert slot_output(a.execute("cve-org", {"cve_id": "CVE-2024-3094"}))["cvss_score"] == 9.0


def test_cve_org_agent_rejected_or_missing_is_not_found(tmp_path):
    a, _ = agents(tmp_path, {"https://cveawg.mitre.org/api/cve/CVE-2024-0001": httpx.Response(
        200, json=cve5("CVE-2024-0001", "REJECTED"))})
    for cve_id in ("CVE-2024-0001", "CVE-2024-0002"):
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("cve-org", {"cve_id": cve_id})
        assert err.value.code == "not_found"


def test_stale_cache_serves_when_the_source_fails_later(tmp_path):
    state = {"ok": True}

    def answer(request):
        return httpx.Response(200, json=cve5()) if state["ok"] else httpx.Response(500)
    a, clock = agents(tmp_path, {"https://cveawg.mitre.org/": answer})
    a.execute("cve-org", {"cve_id": "CVE-2024-3094"})
    state["ok"] = False
    clock.t += 7 * 3600
    env = a.execute("cve-org", {"cve_id": "CVE-2024-3094"})
    assert env["cache"] == {"status": "stale_cache", "age_seconds": 7 * 3600}
    clock.t += 8 * 86400
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("cve-org", {"cve_id": "CVE-2024-3094"})
    assert err.value.code == "source_unavailable"


# ------------------------------------------------------------------ cisa-kev agent
KEV_BODY = {"catalogVersion": "2026.11.13", "vulnerabilities": [{"cveID": "CVE-2021-44228", "dateAdded": "2021-12-10"}]
            + [{"cveID": f"CVE-2020-{i:05d}", "dateAdded": "2022-01-01"} for i in range(200)]}


def kev_routes(epss=True):
    routes = {"https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json":
              httpx.Response(200, json=KEV_BODY)}
    routes["https://api.first.org/data/v1/epss"] = (
        (lambda r: httpx.Response(200, json={"data": [{"cve": r.url.params["cve"], "epss": "0.94358"}]}))
        if epss else httpx.Response(500))
    return routes


def test_kev_agent_reports_listing_date_and_epss(tmp_path):
    calls = []
    a, _ = agents(tmp_path, kev_routes(), calls)
    out = slot_output(a.execute("cisa-kev", {"cve_id": "CVE-2021-44228"}))
    assert out == {"cve_id": "CVE-2021-44228", "kev": True, "kev_date_added": "2021-12-10", "epss": 0.94358,
                   "source": "CISA KEV; FIRST EPSS"}
    out = slot_output(a.execute("cisa-kev", {"cve_id": "CVE-2019-0001"}))
    assert out["kev"] is False and "kev_date_added" not in out
    assert sum("cisa.gov" in c for c in calls) == 1, "catalog downloaded once per hour"
    assert (tmp_path / "kev-catalog.json").exists()


def test_kev_agent_without_epss_is_partial_not_failed(tmp_path):
    a, _ = agents(tmp_path, kev_routes(epss=False))
    env = a.execute("cisa-kev", {"cve_id": "CVE-2021-44228"})
    assert env["partial"] is True and "epss" not in env["result"] and env["result"]["source"] == "CISA KEV"


def test_kev_agent_uses_the_saved_catalog_when_cisa_fails(tmp_path):
    a, clock = agents(tmp_path, kev_routes())
    a.execute("cisa-kev", {"cve_id": "CVE-2021-44228"})
    failing = kev_routes()
    failing["https://www.cisa.gov/"] = httpx.Response(500)
    del failing["https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"]
    clock2 = Clock()
    clock2.t = clock.t + 2 * 3600
    b = FallbackAgents(http=client(failing), data_dir=tmp_path, clock=clock2, wall=lambda: 1.8e9 + clock2.t,
                       limiters=limiters(clock2, clock2.sleep))
    env = b.execute("cisa-kev", {"cve_id": "CVE-2021-44228"})
    assert env["cache"]["status"] == "stale_cache" and env["result"]["kev"] is True
    (tmp_path / "kev-catalog.json").unlink()
    c = FallbackAgents(http=client(failing), data_dir=tmp_path / "empty", clock=clock2,
                       limiters=limiters(clock2, clock2.sleep))
    with pytest.raises(FallbackUnavailable) as err:
        c.execute("cisa-kev", {"cve_id": "CVE-2021-44228"})
    assert err.value.code == "source_unavailable"


# ------------------------------------------------------------------ github-advisory agent
GH_ROW = {"ghsa_id": "GHSA-35jh-r3h4-6jhm", "summary": "Command Injection in lodash", "severity": "high",
          "html_url": "https://github.com/advisories/GHSA-35jh-r3h4-6jhm",
          "identifiers": [{"type": "GHSA", "value": "GHSA-35jh-r3h4-6jhm"}, {"type": "CVE", "value": "CVE-2021-23337"}],
          "vulnerabilities": [{"package": {"ecosystem": "npm", "name": "lodash"}, "vulnerable_version_range": "< 4.17.21"},
                              {"package": {"ecosystem": "npm", "name": "lodash.template"}, "vulnerable_version_range": "< 9"}]}


def test_github_agent_lists_reviewed_advisories_with_aliases(tmp_path):
    calls = []
    a, _ = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(200, json=[GH_ROW, dict(GH_ROW)])}, calls)
    env = a.execute("github-advisory", {"package": "lodash", "ecosystem": "npm", "version": "4.17.20"})
    assert env["result"] == {"items": [{"id": "GHSA-35jh-r3h4-6jhm", "aliases": ["CVE-2021-23337"],
                                        "summary": "Command Injection in lodash", "severity": "high",
                                        "affected": "< 4.17.21", "url": "https://github.com/advisories/GHSA-35jh-r3h4-6jhm"}],
                             "partial": False, "source": "GitHub Advisory Database"}
    assert "affects=lodash&" in calls[0] and "ecosystem=npm" in calls[0] and "type=reviewed" in calls[0]
    assert env["sources"][0]["license"].startswith("CC BY 4.0")


def test_github_agent_maps_pypi_to_pip_and_empty_is_valid(tmp_path):
    calls = []
    a, _ = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(200, json=[])}, calls)
    env = a.execute("github-advisory", {"package": "requests", "ecosystem": "PyPI"})
    assert env["result"]["items"] == [] and "ecosystem=pip" in calls[0] and "affects=requests&" in calls[0] + "&"


def test_github_agent_stops_at_the_hourly_allowance(tmp_path):
    calls = []
    a, clock = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(200, json=[])}, calls)
    for i in range(50):
        a.execute("github-advisory", {"package": f"pkg{i}", "ecosystem": "npm"})
        clock.t += 1.5
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("github-advisory", {"package": "one-more", "ecosystem": "npm"})
    assert err.value.code == "rate_limited" and len(calls) == 50


def test_github_remaining_zero_rests_until_reset(tmp_path):
    import time as _time
    reset = str(int(_time.time()) + 900)
    a, _ = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(
        200, json=[], headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset})})
    a.execute("github-advisory", {"package": "a", "ecosystem": "npm"})
    assert 800 < a.limiters["api.github.com"].resting() <= 900


# ------------------------------------------------------------------ limits, network guard, output guard, usage
def test_limiter_rest_rules():
    clock = Clock()
    lim = HostLimiter(1.0, clock=clock, sleep=clock.sleep)
    lim.observed(429, {})
    assert lim.resting() == 300
    lim = HostLimiter(1.0, clock=clock, sleep=clock.sleep)
    lim.observed(429, {"retry-after": "5"})
    assert lim.resting() == 30
    lim = HostLimiter(1.0, clock=clock, sleep=clock.sleep)
    lim.observed(429, {"retry-after": "99999"})
    assert lim.resting() == 3600
    lim = HostLimiter(10.0, clock=clock, sleep=clock.sleep)
    with lim.slot(5):
        pass
    with pytest.raises(SourceBusy):
        with lim.slot(5):
            pass


def test_network_guard_refuses_other_hosts_and_private_preflight(monkeypatch):
    clock = Clock()
    lims = limiters(clock, clock.sleep)
    for url in ("http://cveawg.mitre.org/api/cve/x", "https://example.com/", "https://user:pw@api.github.com/",
                "https://api.github.com:8443/"):
        with pytest.raises(net.SourceError):
            net.get(url, limiters=lims, seconds=2, limit=10)

    def private(url):
        raise net.validate_public_url.__globals__["DiscoveryError"]("Private or internal destinations are prohibited")
    monkeypatch.setattr(net, "validate_public_url", private)
    with pytest.raises(net.SourceError, match="public destination"):
        net.get("https://cveawg.mitre.org/api/cve/CVE-2024-3094", limiters=lims, seconds=2, limit=10)


def test_output_that_breaks_the_contract_is_an_error(tmp_path, monkeypatch):
    a, _ = agents(tmp_path, {"https://cveawg.mitre.org/": httpx.Response(200, json=cve5())})
    monkeypatch.setattr(a, "_cve_org", lambda args, rem: ({"cve_id": args["cve_id"], "source": "x", "cvss_score": 11},
                                                         {"status": "live", "age_seconds": 0}, False, {}))
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("cve-org", {"cve_id": "CVE-2024-3094"})
    assert err.value.code == "invalid_output"
    monkeypatch.setattr(a, "_cve_org", lambda args, rem: ({"cve_id": "CVE-2000-0001", "source": "x"},
                                                         {"status": "live", "age_seconds": 0}, False, {}))
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("cve-org", {"cve_id": "CVE-2024-3094"})
    assert err.value.code == "invalid_output"


def test_usage_log_records_outcomes_without_inputs(tmp_path):
    a, _ = agents(tmp_path, kev_routes())
    a.execute("cisa-kev", {"cve_id": "CVE-2021-44228"})
    with pytest.raises(FallbackUnavailable):
        a.execute("cve-org", {"cve_id": "CVE-2024-0009"})
    lines = [json.loads(x) for f in (tmp_path / "usage").glob("*.jsonl") for x in f.read_text().splitlines()]
    assert [(x["agent"], x["ok"], x["code"]) for x in lines] == [("cisa-kev", True, None), ("cve-org", False, "not_found")]
    assert "CVE-" not in json.dumps(lines)


def test_github_agent_checks_ranges_itself_for_casing_and_pre_releases(tmp_path):
    rows = [{"ghsa_id": "GHSA-23j4-mw76-5v7h", "identifiers": [], "html_url": "https://github.com/advisories/GHSA-23j4-mw76-5v7h",
             "vulnerabilities": [{"package": {"ecosystem": "pip", "name": "Scrapy"}, "vulnerable_version_range": "< 2.11.2"}]},
            {"ghsa_id": "GHSA-7j7m-v7m3-jqm7", "identifiers": [],
             "vulnerabilities": [{"package": {"ecosystem": "pip", "name": "scrapy"}, "vulnerable_version_range": ">= 2.0.0, < 2.11.1"}]},
            {"ghsa_id": "GHSA-cjvr-mfj7-j4j8", "identifiers": [],
             "vulnerabilities": [{"package": {"ecosystem": "pip", "name": "scrapy"}, "vulnerable_version_range": "< 1.8.2"},
                                 {"package": {"ecosystem": "pip", "name": "scrapy"}, "vulnerable_version_range": ">= 2.0.0, < 2.6.0"}]},
            {"ghsa_id": "GHSA-2222-3333-4444", "identifiers": [],
             "vulnerabilities": [{"package": {"ecosystem": "pip", "name": "scrapy"}, "vulnerable_version_range": "~> weird"}]},
            {"ghsa_id": "GHSA-5555-6666-7777", "identifiers": [],
             "vulnerabilities": [{"package": {"ecosystem": "pip", "name": "scrapy-splash"}, "vulnerable_version_range": "< 9"}]}]
    a, _ = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(200, json=rows)})
    env = a.execute("github-advisory", {"package": "scrapy", "ecosystem": "PyPI", "version": "1.1.1rc1"})
    assert [i["id"] for i in env["result"]["items"]] == ["GHSA-23j4-mw76-5v7h", "GHSA-cjvr-mfj7-j4j8", "GHSA-2222-3333-4444"]
    assert env["partial"] is True, "an unreadable range is kept and flagged, never dropped as safe"
    every = a.execute("github-advisory", {"package": "scrapy", "ecosystem": "PyPI"})
    assert len(every["result"]["items"]) == 4 and every["cache"]["status"] == "fresh_cache"


@pytest.mark.parametrize("a,b", [("1.0", "1.0.0"), ("1.0rc1", "1.0"), ("1.0.dev1", "1.0a1"), ("1.0a2", "1.0b1"),
                                 ("1.0", "1.0.post1"), ("0.8.0b2", "0.8.0"), ("18.7.0rc1", "18.7.0"), ("1!0.1", "2.0"),
                                 ("2.0.0", "10.0.0"), ("1.0.post1.dev1", "1.0.post1")])
def test_pep440_order_matches_packaging(a, b):
    from packaging.version import Version
    from agent_market.fallback_agents.versions import pep440_key
    assert (pep440_key(a) < pep440_key(b)) == (Version(a) < Version(b))
    assert (pep440_key(a) == pep440_key(b)) == (Version(a) == Version(b))


def test_semver_order_and_ranges():
    from agent_market.fallback_agents.versions import in_range, semver_key
    chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
             "1.0.0-rc.1", "1.0.0", "4.17.20", "4.17.21"]
    assert sorted(chain, key=semver_key) == chain
    assert in_range("4.17.20", "< 4.17.21", "npm") is True
    assert in_range("4.17.21", ">= 4.0.0, < 4.17.21", "npm") is False
    assert in_range("1.2.5", "= 1.2.5", "npm") is True
    assert in_range("not-a-version", "< 2", "npm") is None


def test_tools_pass_the_relay_safety_check_without_the_read_only_hint():
    from agent_market.collector.usage import _DENY, is_relay_safe_tool
    for agent_id in SPECS:
        tool = tool_spec(agent_id)
        compact = {"name": tool["name"], "description": tool["description"], "annotations": tool["annotations"],
                   "required": tool["inputSchema"].get("required", [])}
        assert is_relay_safe_tool(compact)
        assert not _DENY.search(tool["name"]) and not _DENY.search(tool["description"][:200])


def test_gold_check_rules():
    from agent_market.fallback_agents.gold_check import judge
    case = {"truth": {"cvss": {"score": 9.8, "version": "3.1", "source": "NVD"}, "kev": True,
                      "kev_date_added": "2023-06-13", "epss": 0.6}}
    assert judge("nvd-cve", case, {"cvss_score": 9.8, "cvss_version": "3.1"})["pass"]
    assert not judge("cve-org", case, {"cvss_score": 9.2, "cvss_version": "3.1"})["pass"]
    assert not judge("nvd-cve", case, {"cvss_score": 9.8, "cvss_version": "4.0"})["pass"]
    assert not judge("nvd-cve", case, None)["pass"]
    kev = judge("cisa-kev", case, {"kev": True, "kev_date_added": "2023-06-13", "epss": 0.4})
    assert kev["pass"] and kev["epss_band_same"] is False
    pkg = {"truth": {"advisories": [{"id": "GHSA-a", "ids": ["GHSA-a", "PYSEC-1"]}, {"id": "PYSEC-1", "ids": ["GHSA-a", "PYSEC-1"]},
                                    {"id": "PYSEC-2", "ids": ["PYSEC-2"]}]}}
    got = judge("github-advisory", pkg, {"items": [{"id": "GHSA-a", "aliases": []}]})
    assert got["pass"] and got["recall_ghsa"] == 1.0 and got["recall_all"] == 0.5
    assert not judge("github-advisory", {"truth": {"advisories": []}}, {"items": [{"id": "GHSA-b"}]})["pass"]
    assert not judge("github-advisory", pkg, {"items": []})["pass"]


# ------------------------------------------------------------------ data age (PM 11-14)
def test_every_answer_states_source_time_and_age(tmp_path):
    snap = seeded_snapshot(tmp_path, nvd_cve())
    db = snap._open(snap.path)
    with db:
        db.execute("INSERT OR REPLACE INTO meta VALUES ('source_updated_at', '2026-11-13T14:00:06-05:00')")
    db.close()
    a, _ = agents(tmp_path, kev_routes(), snapshot=snap)
    env = a.execute("nvd-cve", {"cve_id": "CVE-2021-44228"})
    assert env["freshness"] == {"data_as_of": {"NVD": "2026-11-13T14:00:06-05:00"}, "age_seconds": 600,
                                "max_age_seconds": 21600}
    body = dict(KEV_BODY, dateReleased="2026-11-13T17:49:24.9532Z")
    a2, _ = agents(tmp_path / "k", {**kev_routes(), "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json":
                                    httpx.Response(200, json=body),
                                    "https://api.first.org/data/v1/epss": httpx.Response(200, json={"data": [
                                        {"cve": "CVE-2021-44228", "epss": "0.9", "date": "2026-11-13"}]})})
    env = a2.execute("cisa-kev", {"cve_id": "CVE-2021-44228"})
    assert env["freshness"]["data_as_of"] == {"CISA KEV": "2026-11-13T17:49:24.9532Z", "FIRST EPSS": "2026-11-13"}


def test_a_snapshot_over_six_hours_old_is_stale_not_an_answer(tmp_path):
    snap = Snapshot(tmp_path / "nvd.sqlite3")
    db = snap._open(snap.path)
    with db:
        snap.ingest(db, [nvd_cve()])
        db.execute("INSERT INTO meta VALUES ('synced_at', ?)", (repr(1.8e9 + 1000.0 - 6 * 3600 - 1),))
    db.close()
    a, _ = agents(tmp_path, {}, snapshot=snap)
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("nvd-cve", {"cve_id": "CVE-2021-44228"})
    assert err.value.code == "stale"


def test_kev_catalog_older_than_a_day_is_stale(tmp_path):
    a, clock = agents(tmp_path, kev_routes())
    a.execute("cisa-kev", {"cve_id": "CVE-2021-44228"})
    failing = {"https://www.cisa.gov/": httpx.Response(500)}
    c2 = Clock()
    c2.t = clock.t + 25 * 3600
    b = FallbackAgents(http=client(failing), data_dir=tmp_path, clock=c2, wall=lambda: 1.8e9 + c2.t,
                       limiters=limiters(c2, c2.sleep))
    with pytest.raises(FallbackUnavailable) as err:
        b.execute("cisa-kev", {"cve_id": "CVE-2021-44228"})
    assert err.value.code == "source_unavailable"


def test_sync_records_the_modified_feed_time(tmp_path):
    clock = Clock()
    snap = Snapshot(tmp_path / "nvd.sqlite3")
    db = snap._open(snap.path)
    with db:
        db.execute("INSERT INTO meta VALUES ('synced_at', ?)", (repr(1.8e9),))
    db.close()
    snap.sync("update", http=client(feed_routes({"modified": feed_bytes([nvd_cve()])})),
              limiters=limiters(clock, clock.sleep), now=lambda: 1.8e9 + 60, log=lambda *_: None)
    assert snap.meta("source_updated_at") == "2026-11-13T14:00:06-05:00"


# ------------------------------------------------------------------ package.health agents
def test_package_registry_npm_reads_latest_only(tmp_path):
    calls = []
    a, _ = agents(tmp_path, {"https://registry.npmjs.org/request/latest": httpx.Response(200, json={
        "name": "request", "version": "2.88.2", "deprecated": "request has been deprecated",
        "repository": {"type": "git", "url": "git+https://github.com/request/request.git"},
        "maintainers": [{"email": "x@y.z"}], "scripts": {"postinstall": "evil"}})}, calls)
    env = a.execute("package-registry", {"package": "request", "ecosystem": "npm"})
    assert env["result"] == {"latest_version": "2.88.2", "deprecated": True, "source": "npm public registry",
                             "repository": "https://github.com/request/request"}
    assert calls == ["https://registry.npmjs.org/request/latest"]
    assert "npm public registry" in env["freshness"]["data_as_of"] and env["freshness"]["max_age_seconds"] == 21600


def test_package_registry_scoped_npm_name_is_encoded(tmp_path):
    calls = []
    a, _ = agents(tmp_path, {"https://registry.npmjs.org/@types%2Fnode/latest": httpx.Response(
        200, json={"name": "@types/node", "version": "26.6.6", "repository": "github:DefinitelyTyped/DefinitelyTyped"})}, calls)
    out = a.execute("package-registry", {"package": "@types/node", "ecosystem": "npm"})["result"]
    assert out["repository"] == "https://github.com/DefinitelyTyped/DefinitelyTyped" and out["deprecated"] is False


def test_package_registry_pypi_release_time_yank_and_repository(tmp_path):
    body = {"info": {"name": "Django", "version": "6.1.3", "yanked": False, "classifiers": [],
                     "home_page": "https://www.djangoproject.com/",
                     "project_urls": {"Documentation": "https://docs.djangoproject.com/", "Source": "https://github.com/django/django"}},
            "urls": [{"upload_time_iso_8601": "2026-11-03T15:21:22Z", "yanked": False},
                     {"upload_time_iso_8601": "2026-11-03T15:21:19Z", "yanked": False}]}
    a, _ = agents(tmp_path, {"https://pypi.org/pypi/django/json": httpx.Response(200, json=body)})
    out = a.execute("package-registry", {"package": "django", "ecosystem": "PyPI"})["result"]
    assert out == {"latest_version": "6.1.3", "source": "PyPI JSON API", "released_at": "2026-11-03T15:21:19Z",
                   "repository": "https://github.com/django/django"}
    body["info"]["classifiers"] = ["Development Status :: 7 - Inactive"]
    b, _ = agents(tmp_path / "b", {"https://pypi.org/pypi/django/json": httpx.Response(200, json=body)})
    assert b.execute("package-registry", {"package": "django", "ecosystem": "PyPI"})["result"]["deprecated"] is True


def test_package_registry_missing_package_is_not_found(tmp_path):
    a, _ = agents(tmp_path, {})
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("package-registry", {"package": "no-such-pkg-x", "ecosystem": "npm"})
    assert err.value.code == "not_found"


def depsdev_routes(scorecard=True):
    routes = {
        "https://api.deps.dev/v3/systems/npm/packages/lodash/versions/4.18.1": httpx.Response(200, json={
            "relatedProjects": [{"projectKey": {"id": "github.com/lodash/lodash"}, "relationType": "ISSUE_TRACKER"},
                                {"projectKey": {"id": "github.com/lodash/lodash"}, "relationType": "SOURCE_REPO"}]}),
        "https://api.deps.dev/v3/systems/npm/packages/lodash": httpx.Response(200, json={"versions": [
            {"versionKey": {"version": "4.17.21"}, "isDefault": False},
            {"versionKey": {"version": "4.18.1"}, "isDefault": True, "isDeprecated": False, "publishedAt": "2026-04-01T21:01:20Z"}]}),
        "https://api.scorecard.dev/projects/github.com/lodash/lodash": httpx.Response(200, json={
            "date": "2026-11-09", "score": 7.5} if scorecard else {}),
    }
    return routes


def test_depsdev_agent_reports_default_version_repo_and_scorecard(tmp_path):
    a, _ = agents(tmp_path, depsdev_routes())
    env = a.execute("depsdev-package", {"package": "lodash", "ecosystem": "npm"})
    assert env["result"] == {"latest_version": "4.18.1", "repository": "https://github.com/lodash/lodash", "scorecard": 7.5,
                             "source": "latest_version: deps.dev default version (CC BY 4.0); repository: deps.dev "
                                       "source-repository association (CC BY 4.0); scorecard: OpenSSF Scorecard API "
                                       "(CDLA-Permissive-2.0)"}
    assert env["field_sources"]["scorecard"].startswith("OpenSSF Scorecard API")
    assert env["freshness"]["data_as_of"]["OpenSSF Scorecard"] == "2026-11-09"
    assert [s["name"].split(" ")[0] for s in env["sources"]] == ["Open", "OpenSSF"]
    assert "released_at" not in env["result"] and "deprecated" not in env["result"], "registry facts are not taken from deps.dev"


def test_depsdev_agent_without_scorecard_keeps_version_facts(tmp_path):
    routes = depsdev_routes(scorecard=False)
    a, _ = agents(tmp_path, routes)
    out = a.execute("depsdev-package", {"package": "lodash", "ecosystem": "npm"})["result"]
    assert "scorecard" not in out and "OpenSSF" not in out["source"] and out["latest_version"] == "4.18.1"
    del routes["https://api.scorecard.dev/projects/github.com/lodash/lodash"]
    routes["https://api.scorecard.dev/"] = httpx.Response(500)
    b, _ = agents(tmp_path / "b", routes)
    env = b.execute("depsdev-package", {"package": "lodash", "ecosystem": "npm"})
    assert env["partial"] is True and env["result"]["latest_version"] == "4.18.1"


def test_repository_url_normalization():
    from agent_market.fallback_agents.agents import repository_url
    assert repository_url("git+https://github.com/a/b.git") == "https://github.com/a/b"
    assert repository_url("git://github.com/a/b.git") == "https://github.com/a/b"
    assert repository_url("git@github.com:a/b.git") == "https://github.com/a/b"
    assert repository_url("https://github.com/a/b/tree/main/pkg") == "https://github.com/a/b"
    assert repository_url("a/b") == "https://github.com/a/b"
    assert repository_url("https://docs.example.org/", hosted_only=True) is None
    assert repository_url("http://insecure.example/") is None


def test_cve_org_gold_rule_uses_the_named_source():
    from agent_market.fallback_agents.gold_check import judge
    case = {"truth": {"cvss": {"score": 8.0, "version": "3.1", "source": "NVD"},
                      "cvss_record": {"from": "cna", "provider": "cisco", "score": 10.0, "version": "3.1"}}}
    assert judge("cve-org", case, {"cvss_score": 10.0, "cvss_version": "3.1", "source": "CVE Program (score from CNA cisco)"})["pass"]
    assert not judge("cve-org", case, {"cvss_score": 10.0, "cvss_version": "3.1", "source": "CVE Program"})["pass"]
    none = {"truth": {"cvss": {"score": 6.4, "version": "2.0"}, "cvss_record": None}}
    assert judge("cve-org", none, {"source": "CVE Program"})["pass"]
    assert not judge("cve-org", none, {"cvss_score": 6.4, "cvss_version": "2.0", "source": "CVE Program"})["pass"]


# ------------------------------------------------------------------ company.registry agents
def gleif_row(lei, legal, city, reg="ISSUED", others=()):
    return {"attributes": {"lei": lei, "entity": {"legalName": {"name": legal}, "otherNames": [{"name": o} for o in others],
                                                  "status": "ACTIVE", "registeredAs": "806592", "registeredAt": {"id": "RA000598"},
                                                  "legalAddress": {"city": city}},
                           "registration": {"status": reg, "lastUpdateDate": "2026-03-03T16:34:33Z"}}}


def test_gleif_agent_exact_name_only_and_core_name_search(tmp_path):
    calls = []
    rows = [gleif_row("HWUPKR0MPOU8FGXBT394", "Apple Inc.", "Glendale"),
            gleif_row("254900KZR24L5GN8TE52", "Apple Ford, Inc.", "Wilmington", "LAPSED")]
    a, _ = agents(tmp_path, {"https://api.gleif.org/api/v1/lei-records": httpx.Response(200, json={"data": rows})}, calls)
    env = a.execute("gleif-lei", {"name": "Apple Incorporated", "country": "US"})
    assert env["result"] == {"legal_name": "Apple Inc.", "identifiers": {"LEI": "HWUPKR0MPOU8FGXBT394", "company number": "806592",
                                                                         "registration authority (GLEIF RA code)": "RA000598"},
                             "status": "ACTIVE (LEI ISSUED)", "url": "https://search.gleif.org/#/record/HWUPKR0MPOU8FGXBT394",
                             "source": "GLEIF", "address_city": "Glendale"}
    assert "filter%5Bentity.names%5D=Apple&" in calls[0] and "country%5D=US" in calls[0]
    assert env["freshness"]["data_as_of"] == {"GLEIF": "2026-03-03T16:34:33Z"}
    assert env["sources"][0]["license"].startswith("CC0")
    # A short name matches at the core tier (legal form dropped) when exactly one record does.
    assert a.execute("gleif-lei", {"name": "Apple"})["result"]["identifiers"]["LEI"] == "HWUPKR0MPOU8FGXBT394"


def test_company_name_tiers_exact_first_then_core_then_loose(tmp_path):
    from agent_market.fallback_agents.agents import name_keys
    assert name_keys("Nestlé S.A.") == ("nestle sa", "nestle", "nestle")
    assert name_keys("ASML Holding N.V.") == ("asml holding nv", "asml holding", "asml")
    assert name_keys("The Coca-Cola Company")[1] == "coca cola"
    rows = [gleif_row("AAAAAAAAAAAAAAAAAA01", "Allianz SE", "Munich"),
            gleif_row("AAAAAAAAAAAAAAAAAA02", "Allianz Ltd", "London"),
            gleif_row("AAAAAAAAAAAAAAAAAA03", "ASML Holding N.V.", "Veldhoven")]
    a, _ = agents(tmp_path, {"https://api.gleif.org/": httpx.Response(200, json={"data": rows})})
    assert a.execute("gleif-lei", {"name": "Allianz SE"})["result"]["identifiers"]["LEI"].endswith("01")  # exact wins
    with pytest.raises(FallbackUnavailable, match="Several"):  # two records at the core tier: never a guess
        a.execute("gleif-lei", {"name": "Allianz"})
    assert a.execute("gleif-lei", {"name": "ASML"})["result"]["identifiers"]["LEI"].endswith("03")  # loose tier


def test_gleif_short_name_resolved_by_wikidata_lei_link_within_gleif_records(tmp_path):
    def row(lei, legal):
        r = gleif_row(lei, legal, "London")
        r["attributes"]["entity"]["legalAddress"]["country"] = "GB"
        return r
    rows = [row("AAAAAAAAAAAAAAAAAA01", "HSBC HOLDINGS B.V."), row("MLU0ZO3ML4LN2LL2TL39", "HSBC Holdings plc"),
            row("AAAAAAAAAAAAAAAAAA03", "HSBC Bank plc")]
    gleif = {"https://api.gleif.org/api/v1/lei-records": httpx.Response(200, json={"data": rows})}

    def wikidata(*leis):
        return {"https://query.wikidata.org/sparql": httpx.Response(200, json={"results": {"bindings": [
            {"lei": {"value": lei}, "ord": {"value": str(i)}} for i, lei in enumerate(leis)]}})}

    calls = []
    a, _ = agents(tmp_path / "a", {**gleif, **wikidata("MLU0ZO3ML4LN2LL2TL39")}, calls)
    env = a.execute("gleif-lei", {"name": "HSBC", "country": "GB"})
    assert env["result"]["identifiers"]["LEI"] == "MLU0ZO3ML4LN2LL2TL39"  # the parent, not the same-name B.V.
    assert any("query.wikidata.org" in c for c in calls)
    assert [s["name"] for s in env["sources"]][1].startswith("Wikidata")
    # Wikidata never supplies a record: a linked LEI whose GLEIF name lacks a word of the input is ignored,
    # and the name rules then report the tie instead of guessing.
    b, _ = agents(tmp_path / "b", {**gleif, **wikidata("AAAAAAAAAAAAAAAAAA03")})
    with pytest.raises(FallbackUnavailable, match="Several"):
        b.execute("gleif-lei", {"name": "HSBC Holdings", "country": "GB"})
    # Wikidata down: the same honest tie.
    c, _ = agents(tmp_path / "c", {**gleif, "https://query.wikidata.org/sparql": httpx.Response(503)})
    with pytest.raises(FallbackUnavailable, match="Several"):
        c.execute("gleif-lei", {"name": "HSBC", "country": "GB"})
    # An exact legal name never asks Wikidata.
    calls.clear()
    d, _ = agents(tmp_path / "d", {**gleif, **wikidata("AAAAAAAAAAAAAAAAAA01")}, calls)
    assert d.execute("gleif-lei", {"name": "HSBC Bank PLC", "country": "GB"})["result"]["identifiers"]["LEI"].endswith("03")
    assert not any("query.wikidata.org" in c for c in calls)


def test_gleif_short_name_reads_the_linked_parent_outside_the_first_page(tmp_path):
    bv = gleif_row("AAAAAAAAAAAAAAAAAA01", "ING Bank N.V.", "Amsterdam")
    parent = gleif_row("549300NYKK9MWM7GGW15", "ING Groep N.V.", "Amsterdam")
    for r in (bv, parent):
        r["attributes"]["entity"]["legalAddress"]["country"] = "NL"
    calls = []
    a, _ = agents(tmp_path, {
        "https://api.gleif.org/api/v1/lei-records/549300NYKK9MWM7GGW15": httpx.Response(200, json={"data": parent}),
        "https://api.gleif.org/api/v1/lei-records": httpx.Response(200, json={"data": [bv]}),
        "https://query.wikidata.org/sparql": httpx.Response(200, json={"results": {"bindings": [
            {"lei": {"value": "549300NYKK9MWM7GGW15"}, "ord": {"value": "0"}}]}})}, calls)
    out = a.execute("gleif-lei", {"name": "ING", "country": "NL"})["result"]
    assert out["legal_name"] == "ING Groep N.V." and out["identifiers"]["LEI"] == "549300NYKK9MWM7GGW15"
    assert sum("/lei-records/549300NYKK9MWM7GGW15" in c for c in calls) == 1  # one direct record read


def test_gleif_makes_at_most_two_gleif_calls_a_request(tmp_path):
    # A legal-form name that matches nothing: core search, one linked record read (which fails the word check),
    # and no third call (the full-name search is skipped once a record was read).
    other = gleif_row("549300NYKK9MWM7GGW15", "Somebody Else N.V.", "Amsterdam")
    other["attributes"]["entity"]["legalAddress"]["country"] = "NL"
    calls = []
    a, _ = agents(tmp_path, {
        "https://api.gleif.org/api/v1/lei-records/549300NYKK9MWM7GGW15": httpx.Response(200, json={"data": other}),
        "https://api.gleif.org/api/v1/lei-records": httpx.Response(200, json={"data": []}),
        "https://query.wikidata.org/sparql": httpx.Response(200, json={"results": {"bindings": [
            {"lei": {"value": "549300NYKK9MWM7GGW15"}, "ord": {"value": "0"}}]}})}, calls)
    with pytest.raises(FallbackUnavailable):
        a.execute("gleif-lei", {"name": "Nowhere Trading B.V.", "country": "NL"})
    assert sum("api.gleif.org" in c for c in calls) == 2


def test_company_names_with_two_part_legal_forms():
    from agent_market.fallback_agents.agents import name_keys
    assert name_keys("Novo Nordisk A/S")[1] == "novo nordisk"
    assert name_keys("Accenture public limited company")[:2] == ("accenture plc", "accenture")
    assert name_keys("Henkel AG & Co. KGaA")[1] == "henkel"
    assert name_keys("Philips International B.V.")[2] == "philips international"  # a subsidiary keeps its word


def test_gleif_agent_matches_other_names_and_refuses_ambiguity(tmp_path):
    rows = [gleif_row("5493006W3QUS5LMH6R84", "トヨタ自動車株式会社", "Toyota", others=["Toyota Motor Corporation"])]
    a, _ = agents(tmp_path, {"https://api.gleif.org/": httpx.Response(200, json={"data": rows})})
    out = a.execute("gleif-lei", {"name": "Toyota Motor Corp", "country": "JP"})["result"]
    assert out["legal_name"] == "トヨタ自動車株式会社 (Toyota Motor Corporation)"
    two = [gleif_row("AAAAAAAAAAAAAAAAAA01", "Acme Corp", "X"), gleif_row("AAAAAAAAAAAAAAAAAA02", "ACME CORPORATION", "Y")]
    b, _ = agents(tmp_path / "b", {"https://api.gleif.org/": httpx.Response(200, json={"data": two})})
    with pytest.raises(FallbackUnavailable, match="Several"):
        b.execute("gleif-lei", {"name": "Acme Corporation"})


def sec_routes():
    tickers = {str(i): {"cik_str": 100000 + i, "ticker": f"T{i}", "title": f"Company {i} Inc"} for i in range(1200)}
    tickers["a"] = {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
    tickers["b"] = {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"}
    tickers["c"] = {"cik_str": 804328, "ticker": "QCOM", "title": "QUALCOMM INC/DE"}
    return {"https://www.sec.gov/files/company_tickers.json": httpx.Response(200, json=tickers),
            "https://data.sec.gov/submissions/CIK0000789019.json": httpx.Response(200, json={
                "cik": "0000789019", "name": "MICROSOFT CORP", "tickers": ["MSFT"], "exchanges": ["Nasdaq"], "lei": None,
                "ein": "911144442", "phone": "425-882-8080", "category": "Large accelerated filer",
                "addresses": {"business": {"city": "REDMOND"}}}),
            "https://data.sec.gov/submissions/CIK0000804328.json": httpx.Response(200, json={
                "cik": "0000804328", "name": "QUALCOMM INC/DE", "tickers": ["QCOM"]})}


def test_sec_agent_maps_name_to_cik_and_omits_contact_fields(tmp_path):
    calls = []
    a, _ = agents(tmp_path, sec_routes(), calls)
    env = a.execute("sec-edgar", {"name": "Microsoft Corporation", "country": "US"})
    assert env["result"] == {"legal_name": "MICROSOFT CORP", "identifiers": {"SEC CIK": "789019", "ticker": "MSFT", "exchange": "Nasdaq"},
                             "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000789019",
                             "source": "SEC EDGAR", "status": "Large accelerated filer", "address_city": "REDMOND"}
    assert "425" not in json.dumps(env) and "911144442" not in json.dumps(env)
    a.execute("sec-edgar", {"name": "MICROSOFT CORP"})
    assert sum("company_tickers" in c for c in calls) == 1, "ticker list is cached"
    assert a.execute("sec-edgar", {"name": "QUALCOMM Incorporated"})["result"]["identifiers"]["SEC CIK"] == "804328"
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("sec-edgar", {"name": "Unknown Holdings"})
    assert err.value.code == "not_found"
    assert a.execute("sec-edgar", {"name": "Microsoft"})["result"]["identifiers"]["SEC CIK"] == "789019"  # core tier


def test_sec_user_agent_names_the_public_contact():
    from agent_market.fallback_agents.catalog import SEC, USER_AGENT
    assert "contact@agentconcierge.biz" in USER_AGENT and "10 requests per second" in SEC["license"]
    lim = limiters()
    assert lim["data.sec.gov"].spacing >= 0.1 and lim["www.sec.gov"].spacing >= 0.1


def test_company_key_treats_suffix_spellings_alike():
    from agent_market.fallback_agents.agents import company_key, core_name
    assert company_key("Apple Inc.") == company_key("APPLE INCORPORATED") == "apple inc"
    assert company_key("Siemens Aktiengesellschaft") == company_key("Siemens AG")
    assert core_name("NVIDIA Corp.") == "NVIDIA" and core_name("Corp") == "Corp"
    assert core_name("Amazon.com, Inc.") == "Amazon.com"


# ------------------------------------------------------------------ encyclopedia and papers agents
def test_wikipedia_agent_follows_redirects_and_credits_cc_by_sa(tmp_path):
    calls = []
    page = {"title": "Python (programming language)", "fullurl": "https://en.wikipedia.org/wiki/Python_(programming_language)",
            "touched": "2026-11-13T07:06:55Z", "extract": "Python is a high-level language.\nGuido van Rossum began work on it."}
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": httpx.Response(200, json={"query": {"pages": [page]}})}, calls)
    env = a.execute("wikipedia-summary", {"title": "Python programming language"})
    assert env["result"] == {"title": "Python (programming language)",
                             "summary": "Python is a high-level language. Guido van Rossum began work on it.",
                             "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
                             "source": "Wikipedia (CC BY-SA 4.0, Wikipedia contributors)"}
    assert "redirects=1" in calls[0] and "maxlag=5" in calls[0]
    assert env["sources"][0]["license"].startswith("CC BY-SA 4.0")
    assert env["freshness"]["data_as_of"] == {"Wikipedia": "2026-11-13T07:06:55Z"}


def test_wikipedia_agent_refuses_missing_and_disambiguation(tmp_path):
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": lambda r: httpx.Response(200, json={"query": {"pages": [
        ] if "gpssearch" in r.url.params else [                      # the title search finds nothing either (11-16)
        {"title": r.url.params["titles"], "missing": True} if r.url.params["titles"] == "Nope" else
        {"title": "Mercury", "pageprops": {"disambiguation": ""}, "extract": "Mercury may refer to:"}]}})})
    for title in ("Nope", "Mercury"):
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("wikipedia-summary", {"title": title})
        assert err.value.code == "not_found"


def test_lead_cuts_at_a_sentence():
    from agent_market.fallback_agents.agents import lead
    assert lead("One. Two three. Four five six.", 20) == "One. Two three."
    assert len(lead("word " * 1000, 100)) <= 104


ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2304.06446v2</id><published>2023-04-13T00:00:00Z</published>
<title>SpectFormer: Frequency and Attention is what you need in a Vision Transformer</title></entry>
<entry><id>http://arxiv.org/abs/1706.03762v7</id><published>2017-06-12T17:57:34Z</published>
<title>Attention Is All You
  Need</title></entry>
<entry><id>http://arxiv.org/abs/1706.03762v6</id><published>2017-06-12T17:57:34Z</published>
<title>Attention Is All You Need</title></entry>
</feed>"""


def test_arxiv_agent_ranks_title_matches_and_keeps_ids(tmp_path):
    calls = []
    a, _ = agents(tmp_path, {"https://export.arxiv.org/api/query": httpx.Response(
        200, content=ATOM, headers={"content-type": "application/atom+xml"})}, calls)
    env = a.execute("arxiv-search", {"query": "attention is all you need", "limit": 5})
    assert env["result"]["items"][0] == {"title": "Attention Is All You Need", "id": "arXiv:1706.03762",
                                         "url": "https://arxiv.org/abs/1706.03762", "year": 2017}
    assert len(env["result"]["items"]) == 2, "duplicate titles are folded"
    assert "search_query=ti%3A%22attention+is+all+you+need%22+OR+%28ti%3Aattention+AND+ti%3Aneed%29" in calls[0]
    assert "Thank you to arXiv" in env["sources"][0]["notice"]


def test_arxiv_agent_puts_the_topic_phrase_in_titles_first(tmp_path):
    """holdout-r3 11-16 (28/30): papers that only mention both words came first; one request now also asks for
    titles carrying the phrase, and those rank first (plural s and two-word order aside)."""
    feed = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2311.00001v1</id><published>2023-11-01T00:00:00Z</published>
<title>Causal Models of Human Migration due to Climate Change</title></entry>
<entry><id>http://arxiv.org/abs/2401.00002v1</id><published>2024-01-01T00:00:00Z</published>
<title>Forecasting climate migrations in South Asia</title></entry>
<entry><id>http://arxiv.org/abs/2402.00003v1</id><published>2024-02-01T00:00:00Z</published>
<title>Migration climate corridors and trees</title></entry></feed>"""
    calls = []
    a, _ = agents(tmp_path, {"https://export.arxiv.org/api/query": httpx.Response(
        200, content=feed, headers={"content-type": "application/atom+xml"})}, calls)
    items = a.execute("arxiv-search", {"query": "Climate migration", "limit": 3})["result"]["items"]
    assert {i["id"] for i in items[:2]} == {"arXiv:2401.00002", "arXiv:2402.00003"}   # phrase titles before the rest
    assert "ti%3A%22climate+migration%22+OR+%28all%3Aclimate+AND+all%3Amigration%29" in calls[0]


def test_arxiv_agent_finds_a_pasted_title_with_a_keyword_after_it(tmp_path):
    """Role task papers-attention 11-16 (2/3): "attention is all you need transformer" matched so many abstracts that
    the paper fell outside the 50 results. PM decision a: more than four words are searched in titles only (the first
    five words as a phrase, or every keyword in the title); two to four words keep the phrase OR all-fields search."""
    feed = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2105.00001v1</id><published>2021-05-01T00:00:00Z</published>
<title>Need for attention in transformer models</title></entry>
<entry><id>http://arxiv.org/abs/1706.03762v7</id><published>2017-06-12T17:57:34Z</published>
<title>Attention Is All You Need</title></entry></feed>"""
    calls = []
    a, _ = agents(tmp_path, {"https://export.arxiv.org/api/query": httpx.Response(
        200, content=feed, headers={"content-type": "application/atom+xml"})}, calls)
    items = a.execute("arxiv-search", {"query": "attention is all you need transformer", "limit": 2})["result"]["items"]
    assert items[0]["id"] == "arXiv:1706.03762"
    assert calls[0].endswith("search_query=ti%3A%22attention+is+all+you+need%22+OR+%28ti%3Aattention+AND+ti%3Aneed"
                             "+AND+ti%3Atransformer%29&start=0&max_results=50")   # titles only, no all-fields part


def test_arxiv_feed_with_a_dtd_is_refused(tmp_path):
    from agent_market.fallback_agents.agents import arxiv_entries
    with pytest.raises(ValueError):
        arxiv_entries(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><feed/>')


def test_arxiv_requests_are_three_seconds_apart():
    assert limiters()["export.arxiv.org"].spacing >= 3.0


# ------------------------------------------------------------------ country.indicator agent
def wb_routes():
    return {
        "https://api.worldbank.org/v2/country/KOR/indicator/SP.POP.TOTL": httpx.Response(200, json=[
            {"page": 1, "lastupdated": "2026-11-11"},
            [{"indicator": {"id": "SP.POP.TOTL", "value": "Population, total"}, "country": {"id": "KR", "value": "Korea, Rep."},
              "countryiso3code": "KOR", "date": "2023", "value": 51712619}]]),
        "https://api.worldbank.org/v2/country/JPN": httpx.Response(200, json=[{"page": 1}, [
            {"id": "JPN", "name": "Japan", "capitalCity": "Tokyo"}]]),
        "https://api.worldbank.org/v2/country/XXX/indicator/": httpx.Response(200, json=[
            {"message": [{"id": "120", "value": "Invalid value"}]}]),
    }


def test_worldbank_agent_maps_names_and_states_year_and_unit(tmp_path):
    calls = []
    a, _ = agents(tmp_path, wb_routes(), calls)
    env = a.execute("worldbank-indicator", {"country": "kor", "indicator": "Population", "year": 2023})
    assert env["result"] == {"country": "Korea, Rep. (KOR)", "indicator": "Population, total (SP.POP.TOTL)", "year": 2023,
                             "value": 51712619, "source": "World Bank WDI (CC BY 4.0)", "unit": "people"}
    assert "date=" not in calls[0] and "mrnev" not in calls[0] and env["freshness"]["data_as_of"] == {"World Bank": "2026-11-11"}
    assert env["sources"][0]["license"].startswith("CC BY 4.0")
    cap = a.execute("worldbank-indicator", {"country": "JPN", "indicator": "capital"})["result"]
    assert cap["value"] == "Tokyo" and "year" not in cap


def test_worldbank_agent_unknown_inputs(tmp_path):
    calls = []
    a, _ = agents(tmp_path, wb_routes(), calls)
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("worldbank-indicator", {"country": "KOR", "indicator": "happiness"})
    assert err.value.code == "invalid_input" and calls == []
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("worldbank-indicator", {"country": "XXX", "indicator": "gdp"})
    assert err.value.code == "not_found"
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("worldbank-indicator", {"country": "KOR", "indicator": "gdp", "year": 1900})
    assert err.value.code == "invalid_input"


def test_worldbank_agent_asks_once_more_in_the_other_form_after_a_stall(tmp_path):
    calls = []

    def answer(request):
        if "mrnev" not in str(request.url):
            raise httpx.ReadTimeout("stalled", request=request)
        return httpx.Response(200, json=[{"lastupdated": "2026-11-11"}, [
            {"indicator": {"id": "SP.POP.TOTL", "value": "Population, total"}, "country": {"value": "South Africa"},
             "countryiso3code": "ZAF", "date": "2025", "value": 64000000}]])
    a, _ = agents(tmp_path, {"https://api.worldbank.org/": answer}, calls)
    out = a.execute("worldbank-indicator", {"country": "ZAF", "indicator": "population"})["result"]
    assert out["year"] == 2025 and len(calls) == 2 and "mrnev=1" in calls[1]


def test_worldbank_agent_does_not_ask_again_after_a_refusal(tmp_path):
    calls = []
    a, _ = agents(tmp_path, {"https://api.worldbank.org/": httpx.Response(429, headers={"retry-after": "60"})}, calls)
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("worldbank-indicator", {"country": "ZAF", "indicator": "population"})
    assert err.value.code == "rate_limited" and len(calls) == 1


# ------------------------------------------------------------------ weather agent
def met_body(temp=9.7):
    return {"properties": {"meta": {"updated_at": "2026-11-13T19:20:28Z"}, "timeseries": [
        {"time": "2026-11-13T19:00:00Z", "data": {"instant": {"details": {"air_temperature": 9.0}}}},
        {"time": "2026-11-13T20:00:00Z", "data": {
            "instant": {"details": {"air_temperature": temp, "wind_speed": 2.1, "relative_humidity": 98.3}},
            "next_1_hours": {"summary": {"symbol_code": "lightrainshowers_day"}},
            "next_6_hours": {"summary": {"symbol_code": "rain"}, "details": {"precipitation_amount": 5.4}}}}]}}


def test_met_agent_rounds_coordinates_credits_met_and_waits_for_expires(tmp_path):
    from datetime import datetime, timezone
    calls = []
    clock = Clock()
    wall = lambda: 1794600000.0 + clock.t  # noqa: E731
    expires = "Fri, 13 Nov 2026 20:25:59 GMT"

    def answer(request):
        calls.append(dict(request.headers))
        if request.headers.get("if-modified-since"):
            return httpx.Response(304, headers={"expires": expires})
        return httpx.Response(200, json=met_body(), headers={"expires": expires, "last-modified": "Fri, 13 Nov 2026 19:54:21 GMT"})
    a = FallbackAgents(http=client({"https://api.met.no/": answer}), data_dir=tmp_path, clock=clock, wall=wall,
                       utc_now=lambda: datetime(2026, 11, 13, 20, 5, tzinfo=timezone.utc), limiters=limiters(clock, clock.sleep))
    env = a.execute("met-weather", {"city": "Seoul", "latitude": 37.56654, "longitude": 126.97796})
    assert env["result"] == {"temperature_c": 9.7, "time": "2026-11-13T20:00:00Z", "source": "Based on data from MET Norway (CC BY 4.0, https://api.met.no/doc/License)",
                             "forecast": "Temperature 9.7 °C; next hour: light rain showers; next 6 hours: rain, 5.4 mm "
                                         "precipitation; wind 2.1 m/s; humidity 98.3%"}
    assert env["freshness"]["data_as_of"] == {"MET Norway": "2026-11-13T19:20:28Z"}
    assert env["sources"][0]["license"].startswith("CC BY 4.0 and NLOD 2.0")
    a.execute("met-weather", {"latitude": 37.5701, "longitude": 126.9801})
    assert len(calls) == 1, "same 0.01-degree cell before Expires: no new request"
    clock.t += 3600
    again = a.execute("met-weather", {"latitude": 37.57, "longitude": 126.98})
    assert len(calls) == 2 and calls[1]["if-modified-since"] == "Fri, 13 Nov 2026 19:54:21 GMT"
    assert again["result"]["temperature_c"] == 9.7 and again["cache"]["status"] == "live"


def test_met_agent_rejects_bad_coordinates_and_fails_closed(tmp_path):
    a, _ = agents(tmp_path, {"https://api.met.no/": httpx.Response(500)})
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("met-weather", {"latitude": 91, "longitude": 0})
    assert err.value.code == "invalid_input"
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("met-weather", {"latitude": 10, "longitude": 10})
    assert err.value.code == "source_unavailable"


def test_symbol_text_and_expires():
    from agent_market.fallback_agents.agents import expires_in, symbol_text
    assert symbol_text("partlycloudy_night") == "partly cloudy" and symbol_text("heavysnowshowersandthunder") == "heavy snow showers and thunder"
    assert expires_in("Fri, 13 Nov 2026 20:25:59 GMT", 1794600000.0 + 0) > 0
    assert expires_in(None, 0) == 600.0


# ------------------------------------------------------------------ public holidays (events.search, PM 11-14: national holidays only)
def test_public_holidays_lists_national_holidays_with_scope_and_version(tmp_path):
    pytest.importorskip("holidays")
    calls = []
    a, _ = agents(tmp_path, {}, calls)
    env = a.execute("public-holidays", {"query": "Diwali", "place": "India", "year": 2026})
    assert env["result"] == {"items": [{"title": "Diwali (national public holiday)", "date": "2026-11-08", "place": "India (IN)"}],
                             "source": "holidays 0.108 (MIT): national public holidays only"}
    assert calls == [], "no network"
    assert env["freshness"]["data_as_of"] == {"holidays 0.108": "2026-11-02"} and env["cache"]["status"] == "snapshot"
    assert "Festivals, concerts and other events are not covered" in env["sources"][0]["notice"]
    kr = a.execute("public-holidays", {"place": "KOR", "year": 2026, "month": 10})["result"]["items"]
    assert [i["title"] for i in kr][:1] == ["National Foundation Day (national public holiday)"]
    assert all(i["title"].isascii() for i in kr)
    tr = a.execute("public-holidays", {"query": "Ataturk youth", "place": "Turkey", "year": 2026})["result"]["items"]
    assert tr[0]["title"].startswith("Commemoration of Atatürk"), "English names keep their accents unlabeled"


def test_public_holidays_states_its_coverage_when_asked_for_events(tmp_path):
    pytest.importorskip("holidays")
    a, _ = agents(tmp_path, {})
    for args, words in (({"query": "concert", "place": "San Francisco"}, "not a supported country"),
                        ({"query": "festival", "year": 2026, "month": 11}, "give a country"),
                        ({"query": "concert", "place": "United States", "year": 2026}, "concerts")):
        with pytest.raises(FallbackUnavailable, match=words) as err:
            a.execute("public-holidays", args)
        assert err.value.code == "not_found"


def test_public_holidays_without_the_library_fails_closed(tmp_path, monkeypatch):
    import builtins
    real = builtins.__import__

    def no_holidays(name, *args, **kwargs):
        if name == "holidays" or name.startswith("holidays."):
            raise ImportError("not installed")
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_holidays)
    a, _ = agents(tmp_path, {})
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("public-holidays", {"place": "Japan"})
    assert err.value.code == "source_unavailable"


# ------------------------------------------------------------------ test report v2 input (PM 11-14: avc: namespace)
def test_report_input_rows_use_the_avc_namespace_and_whole_envelope(tmp_path):
    from agent_market.fallback_agents.report_input import results
    a, _ = agents(tmp_path, kev_routes())
    cases = {"cve.exploited.v1": [{"case_id": "kev-log4shell", "input": {"cve_id": "CVE-2021-44228"}, "expect": {"kev": True}},
                                  {"case_id": "kev-bad", "input": {"cve_id": "nope"}, "expect": {}}]}
    rows = results(["cisa-kev"], agents=a, cases_for=lambda: cases, clock=lambda: 1.8e9)
    ok, bad = rows
    assert ok["id"] == "avc:cisa-kev" and ok["role"] == "cve.exploited.v1" and ok["tool"] == "check_kev"
    assert ok["outcome"] == "succeeded" and ok["structured"]["kev"] is True and ok["case"]["case_id"] == "kev-log4shell"
    assert '"freshness"' in ok["full_text"] and '"license"' in ok["full_text"] and ok["started"] == 1.8e9
    assert ok["endpoint"].startswith("in-process:") and ok["host"] == "www.cisa.gov"
    assert bad["outcome"] == "failed" and bad["reason"].startswith("invalid_input")


# ------------------------------------------------------------------ shared daily test budget (ops 11-14)
def test_test_runs_count_calls_in_the_shared_ledger_and_stop_at_the_share(tmp_path, monkeypatch):
    from agent_market import provider_budget
    from agent_market.fallback_agents.net import budget
    monkeypatch.setattr(provider_budget, "DIR", tmp_path / "ledger")
    calls = []
    a, clock = agents(tmp_path, {"https://cveawg.mitre.org/": lambda r: httpx.Response(200, json=cve5(r.url.path.rsplit("/", 1)[1]))}, calls)
    with budget("substitute_tests"):
        for i in range(provider_budget.SHARE["substitute_tests"]):
            a.execute("cve-org", {"cve_id": f"CVE-2024-{3000 + i}"})
            clock.t += 2
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("cve-org", {"cve_id": "CVE-2024-3999"})
    assert err.value.code == "rate_limited" and len(calls) == provider_budget.SHARE["substitute_tests"]
    clock.t += 2
    a.execute("cve-org", {"cve_id": "CVE-2024-3998"})  # a live necklace call outside the block is not counted
    assert len(calls) == provider_budget.SHARE["substitute_tests"] + 1


def test_a_429_in_a_test_run_pauses_the_domain_for_everyone(tmp_path, monkeypatch):
    from agent_market import provider_budget
    from agent_market.fallback_agents.net import budget
    monkeypatch.setattr(provider_budget, "DIR", tmp_path / "ledger")
    a, _ = agents(tmp_path, {"https://cveawg.mitre.org/": httpx.Response(429)})
    with budget("gate"):
        with pytest.raises(FallbackUnavailable):
            a.execute("cve-org", {"cve_id": "CVE-2024-3094"})
    assert provider_budget.reserve("https://cveawg.mitre.org/x", "gate") == (False, "paused_429")


def test_case_arguments_map_the_necklace_topic_to_the_contract_title():
    from agent_market.fallback_agents.gold_check import case_arguments
    case = {"input": {"topic": "Dark matter"}}
    assert case_arguments("wikipedia-summary", case) == {"title": "Dark matter"}
    assert case_arguments("gleif-lei", {"input": {"name": "ASML", "country": "NL", "extra": 1}}) == {"name": "ASML", "country": "NL"}


def test_gold_check_uses_gate_for_holdout_rounds():
    from agent_market.fallback_agents.gold_check import budget_system
    assert budget_system("holdout-r1") == "gate" and budget_system("tuning") == "substitute_tests"


def test_gold_check_company_cases_skip_without_truth_and_respect_limit(tmp_path):
    from agent_market.fallback_agents.gold_check import check
    folder = tmp_path / "gold" / "company-due-diligence"
    folder.mkdir(parents=True)
    cases = [{"case_id": "c1", "input": {"name": "Allianz", "country": "DE"}, "truth": {"lei": "L1", "cik": None}},
             {"case_id": "c2", "input": {"name": "Balchem Corp"}, "truth": {"lei": None, "cik": "9326"}},
             {"case_id": "c3", "input": {"name": "ASML"}, "truth": {"lei": "L3", "cik": None}}]
    (folder / "tuning.jsonl").write_text("\n".join(json.dumps(c) for c in cases))
    seen = []

    class Fake:
        def execute(self, agent_id, args):
            seen.append(args["name"])
            return {"result": {"identifiers": {"LEI": "L1"}}, "cache": {"status": "live"}}

    out = check(["gleif-lei"], tmp_path, agents=Fake(), limit=1)["agents"]["gleif-lei"]["summary"]
    assert seen == ["Allianz"]  # no call for the CIK-only case, none past the limit
    assert (out["cases"], out["passed"], out["not_applicable"], out["not_run"]) == (1, 1, 1, 1)
    seen.clear()
    stopped = check(["gleif-lei"], tmp_path, agents=Fake(), quiet=lambda ts: True)
    assert seen == [] and stopped["stopped"] == "quiet_window"
    assert stopped["agents"]["gleif-lei"]["summary"]["not_run"] == 2


def test_holiday_calendar_answers_the_holiday_contract(tmp_path):
    pytest.importorskip("holidays")
    a, _ = agents(tmp_path, {})
    env = a.execute("holiday-calendar", {"country": "US", "country_code": "US", "countryCode": "US", "year": 2026})
    answer = env["result"]["answer"]
    assert answer.startswith("National public holidays in United States (US), 2026 (national public holidays only;")
    assert "2026-11-26 Thanksgiving Day" in answer and "2026-07-03 Independence Day (observed)" in answer
    assert env["result"]["source"] == "holidays 0.108 (MIT): national public holidays only"
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("holiday-calendar", {"country": "Atlantis"})
    assert err.value.code == "not_found"


# ------------------------------------------------------------------ sec.filings, software.incident, package.risk
def test_sec_filings_resolves_ticker_and_lists_periodic_reports(tmp_path):
    routes = sec_routes()
    routes["https://data.sec.gov/submissions/CIK0000789019.json"] = httpx.Response(200, json={
        "cik": "0000789019", "name": "MICROSOFT CORP", "filings": {"recent": {
            "form": ["4", "8-K", "10-Q", "10-K"], "filingDate": ["2026-11-12", "2026-10-29", "2026-10-29", "2026-07-30"],
            "accessionNumber": ["a1", "a2", "a3", "a4"], "primaryDocument": ["f4.xml", "8k.htm", "10q.htm", "10k.htm"]}}})
    a, _ = agents(tmp_path, routes)
    env = a.execute("sec-filings", {"ticker": "msft"})
    answer = env["result"]["answer"]
    assert answer.startswith("Matched SEC filer: MICROSOFT CORP (SEC CIK 789019), by ticker MSFT. Recent EDGAR filings: "
                             "2026-11-12 4; 2026-10-29 8-K")
    assert "2026-07-30 10-K (accession a4)" in answer and env["freshness"]["data_as_of"] == {"SEC EDGAR (latest filing date)": "2026-11-12"}
    assert a.execute("sec-filings", {"cik": "CIK0000789019"})["result"]["answer"] == answer.replace("by ticker MSFT", "by CIK")
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("sec-filings", {"cik": "12ab"})
    assert err.value.code == "invalid_input"


def test_sec_filings_adds_the_latest_annual_report_facts(tmp_path):
    """PM 11-15 12:46: the filings seat answers company lookup -> recent filings -> the annual report's facts."""
    from agent_market.fallback_agents.agents import annual_facts
    routes = sec_routes()
    routes["https://data.sec.gov/submissions/CIK0000789019.json"] = httpx.Response(200, json={
        "cik": "0000789019", "name": "MICROSOFT CORP", "filings": {"recent": {
            "form": ["10-K"], "filingDate": ["2026-07-30"], "accessionNumber": ["a4"], "primaryDocument": ["10k.htm"]}}})

    def fy(val, end, start="2025-07-01", form="10-K", filed="2026-07-30"):
        return {"val": val, "end": end, "start": start, "form": form, "fp": "FY", "filed": filed}
    routes["https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"] = httpx.Response(200, json={"facts": {
        "us-gaap": {
            "Revenues": {"units": {"USD": [fy(93_580_000_000, "2015-06-30", "2014-07-01", filed="2015-07-31")]}},  # stopped
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                fy(245_122_000_000, "2025-06-30", "2024-07-01", filed="2025-07-30"), fy(281_724_000_000, "2026-06-30"),
                {**fy(70_000_000_000, "2026-03-31", "2026-01-01"), "fp": "Q3", "form": "10-Q"}]}},
            "NetIncomeLoss": {"units": {"USD": [fy(101_832_000_000, "2026-06-30")]}},
            "Assets": {"units": {"USD": [{**fy(619_003_000_000, "2026-06-30"), "start": None}]}}}}})
    a, _ = agents(tmp_path, routes)
    env = a.execute("sec-filings", {"ticker": "MSFT"})
    answer = env["result"]["answer"]
    assert ("Latest annual report facts from EDGAR XBRL company facts "
            "(https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json): 10-K for the fiscal year ended 2026-06-30, "
            "filed 2026-07-30; revenue USD 281.7 billion (US GAAP RevenueFromContractWithCustomerExcludingAssessedTax); "
            "net income USD 101.8 billion (US GAAP NetIncomeLoss); total assets USD 619.0 billion (US GAAP Assets).") in answer
    assert env["result"]["source"] == "SEC EDGAR (submissions and XBRL company facts)"
    ifrs = {"facts": {"ifrs-full": {"Revenue": {"units": {"EUR": [fy(28_262_000_000, "2025-12-31", "2025-01-01", "20-F")]}},
                                    "ProfitLoss": {"units": {"EUR": [fy(7_571_000_000, "2025-12-31", "2025-01-01", "20-F")]}}}}}
    assert annual_facts(ifrs).endswith("revenue EUR 28.3 billion (IFRS Revenue); net income EUR 7.6 billion "
                                       "(IFRS ProfitLoss); total assets not reported for that year.")   # never made up
    assert annual_facts({"facts": {}}) is None and annual_facts({}) is None


def test_sec_filings_identifiers_first_exact_names_only_and_no_registration_is_an_answer(tmp_path):
    """PM 11-15 12:55: CIK, then ticker, then an exact name; a near name is not guessed; no SEC registration is a
    normal answer (a non-U.S. company), not an error."""
    routes = sec_routes()
    routes["https://data.sec.gov/submissions/CIK0000789019.json"] = httpx.Response(200, json={
        "cik": "0000789019", "name": "MICROSOFT CORP", "filings": {"recent": {
            "form": ["8-K"], "filingDate": ["2026-10-29"], "accessionNumber": ["a2"], "primaryDocument": ["8k.htm"]}}})
    a, _ = agents(tmp_path, routes)
    by_both = a.execute("sec-filings", {"ticker": "MSFT", "company": "Apple Inc."})["result"]["answer"]
    assert "MICROSOFT CORP (SEC CIK 789019), by ticker MSFT" in by_both                    # identifier wins
    assert "by exact company name" in a.execute("sec-filings", {"company": "Microsoft Corporation"})["result"]["answer"]
    assert "by company name without its legal form" in a.execute("sec-filings", {"company": "Microsoft"})["result"]["answer"]
    none = a.execute("sec-filings", {"company": "Microsoft Holdings"})["result"]               # near name: not guessed
    assert none["answer"].startswith("No SEC EDGAR registration matches (company Microsoft Holdings)")
    abroad = a.execute("sec-filings", {"ticker": "ZZZZ", "company": "Allianz SE"})["result"]
    assert abroad["answer"].startswith("No SEC EDGAR registration matches (ticker ZZZZ, company Allianz SE)")
    assert abroad["url"] == "https://www.sec.gov/edgar/search/"


def test_annual_facts_follow_every_concept_change():
    """PM 11-15 13:46: a filer that stopped using a concept for each of the three values (MSFT's revenue moved from
    Revenues to RevenueFromContract...; here net income and total assets move too, the assets with a switch from US
    GAAP to IFRS) still gets all three for its newest year, each named by the concept it now uses."""
    from agent_market.fallback_agents.agents import annual_facts

    def fy(val, end, start=None, form="20-F", filed=None):
        return {"val": val, "end": end, "start": start or end[:4] + "-01-01", "form": form, "fp": "FY",
                "filed": filed or str(int(end[:4]) + 1) + "-03-01"}
    raw = {"facts": {
        "us-gaap": {"Revenues": {"units": {"USD": [fy(10e9, "2017-12-31", form="10-K")]}},
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [fy(14e9, "2025-12-31")]}},
                    "NetIncomeLoss": {"units": {"USD": [fy(1e9, "2018-12-31", form="10-K")]}},
                    "ProfitLoss": {"units": {"USD": [fy(2e9, "2025-12-31")]}},
                    "Assets": {"units": {"USD": [{**fy(30e9, "2019-12-31", form="10-K"), "start": None}]}}},
        "ifrs-full": {"Assets": {"units": {"USD": [{**fy(41e9, "2025-12-31"), "start": None}]}}}}}
    text = annual_facts(raw)
    assert "20-F for the fiscal year ended 2025-12-31" in text
    assert text.endswith("revenue USD 14.0 billion (US GAAP RevenueFromContractWithCustomerExcludingAssessedTax); "
                         "net income USD 2.0 billion (US GAAP ProfitLoss); total assets USD 41.0 billion (IFRS Assets).")
    assert "not reported" not in text


def test_sec_filings_without_xbrl_facts_still_lists_filings(tmp_path):
    routes = sec_routes()
    routes["https://data.sec.gov/submissions/CIK0000789019.json"] = httpx.Response(200, json={
        "cik": "0000789019", "name": "MICROSOFT CORP", "filings": {"recent": {
            "form": ["8-K"], "filingDate": ["2026-10-29"], "accessionNumber": ["a2"], "primaryDocument": ["8k.htm"]}}})
    routes["https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"] = httpx.Response(404, json={})
    a, _ = agents(tmp_path, routes)
    env = a.execute("sec-filings", {"cik": "789019"})
    assert "Latest annual report facts" not in env["result"]["answer"] and env["result"]["source"] == "SEC EDGAR (submissions)"


def test_software_incident_by_cve_shows_fixed_versions_as_data(tmp_path):
    calls = []
    row = dict(GH_ROW, published_at="2021-02-15T17:20:12Z",
               vulnerabilities=[{"package": {"ecosystem": "npm", "name": "lodash"}, "first_patched_version": "4.17.21"}])
    a, _ = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(200, json=[row])}, calls)
    out = a.execute("software-incident", {"query": "cve-2021-23337"})["result"]
    assert out["items"][0] == {"title": "GHSA-35jh-r3h4-6jhm: Command Injection in lodash (patched in lodash@4.17.21)",
                               "fixed_version": "4.17.21", "url": "https://github.com/advisories/GHSA-35jh-r3h4-6jhm",
                               "published": "2021-02-15T17:20:12Z"}
    assert "cve_id=CVE-2021-23337" in calls[0]
    assert a.execute("software-incident", {"query": "CVE-2021-23337"})["result"]["packages"] == [
        {"ecosystem": "npm", "name": "lodash", "first_patched_version": "4.17.21"}]          # structured (workflow 11-15)


def test_software_incident_falls_back_to_the_nvd_record_and_states_its_coverage(tmp_path):
    a, _ = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(200, json=[])},
                  snapshot=seeded_snapshot(tmp_path, nvd_cve("CVE-2021-44228")))
    out = a.execute("software-incident", {"query": "CVE-2021-44228"})["result"]
    assert out["source"].startswith("NVD") and out["items"][0]["url"] == "https://logging.apache.org/log4j/2.x/security.html"
    with pytest.raises(FallbackUnavailable, match="use a CVE id, an exact package name or the program's product name"):
        a.execute("software-incident", {"query": "xz-utils"})


def test_software_incident_maps_a_program_name_to_nvd_cpe_products(tmp_path):
    xz = nvd_cve("CVE-2024-3094", published="2024-03-29T17:15:21.150",
                 descriptions=[{"lang": "en", "value": "Malicious code was discovered in the upstream tarballs of xz."}],
                 configurations=[{"nodes": [{"cpeMatch": [
                     {"vulnerable": True, "criteria": "cpe:2.3:a:tukaani:xz:5.6.0:*:*:*:*:*:*:*"},
                     {"vulnerable": True, "criteria": "cpe:2.3:a:tukaani:xz:*:*:*:*:*:*:*:*", "versionEndExcluding": "5.6.2"},
                     {"vulnerable": False, "criteria": "cpe:2.3:o:linux:linux_kernel:-:*:*:*:*:*:*:*"}]}]}])
    old = nvd_cve("CVE-2022-1271", published="2022-08-31T16:15:09.347",
                  configurations=[{"nodes": [{"cpeMatch": [{"vulnerable": True, "criteria": "cpe:2.3:a:tukaani:xz:*:*:*:*:*:*:*:*",
                                                            "versionEndExcluding": "5.2.5"}]}]}])
    snap = seeded_snapshot(tmp_path, xz, old)
    a, _ = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(200, json=[])}, snapshot=snap)
    out = a.execute("software-incident", {"query": "xz-utils"})["result"]
    assert [i["title"][:28] for i in out["items"]] == ["CVE-2024-3094 (tukaani:xz): ", "CVE-2022-1271 (tukaani:xz): "]
    assert out["items"][0]["fixed_version"] == "5.6.2" and out["source"].startswith("NVD (CPE product match")
    from agent_market.fallback_agents.nvd_store import product_variants
    assert product_variants("xz-utils") == ["xz-utils", "xz_utils", "xz"] and product_variants("Log4j") == ["log4j"]


def test_scorecard_reads_the_repository_or_the_package_repository(tmp_path):
    calls = []
    body = {"date": "2026-11-09", "score": 7.3, "checks": [{"name": "Fuzzing", "score": 0}, {"name": "Maintained", "score": 10},
                                                          {"name": "SAST", "score": 0}, {"name": "Unknown", "score": -1}]}
    routes = {"https://api.scorecard.dev/projects/github.com/facebook/react": httpx.Response(200, json=body),
              "https://registry.npmjs.org/react/latest": httpx.Response(200, json={
                  "name": "react", "version": "19.0.0", "repository": {"url": "git+https://github.com/facebook/react.git"}})}
    a, _ = agents(tmp_path, routes, calls)
    env = a.execute("scorecard", {"repo": "github.com/facebook/react"})
    assert env["result"]["answer"] == ("OpenSSF Scorecard for github.com/facebook/react: aggregate score 7.3/10 (scored "
                                       "2026-11-09). Lowest checks: Fuzzing 0, SAST 0, Maintained 10.")
    assert env["sources"][0]["license"].startswith("CDLA-Permissive-2.0")
    b, _ = agents(tmp_path / "b", routes)
    assert "7.3/10" in b.execute("scorecard", {"package": "react", "ecosystem": "npm"})["result"]["answer"]
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("scorecard", {"repo": "example.com/x"})
    assert err.value.code == "invalid_input"


# ------------------------------------------------------------------ website readiness (public files only)
ROBOTS = "User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n\nUser-agent: AgentValCon-FallbackAgents\nDisallow: /sitemap.xml\n\nSitemap: https://www.example.org/sitemap.xml\n"


def test_site_readiness_reads_files_respects_robots_and_scores(tmp_path):
    calls = []
    routes = {"https://example.org/robots.txt": httpx.Response(301, headers={"location": "https://www.example.org/robots.txt"}),
              "https://www.example.org/robots.txt": httpx.Response(200, text=ROBOTS),
              "https://example.org/llms.txt": httpx.Response(200, text="# Example\n\n- [Docs](https://example.org/docs)\n"),
              "https://example.org/sitemap.xml": httpx.Response(200, text="<urlset><url><loc>x</loc></url></urlset>")}
    a, _ = agents(tmp_path, routes, calls)
    env = a.execute("site-readiness", {"domain": "https://Example.org/"})
    out = env["result"]
    assert out["domain"] == "example.org" and out["signals"]["robots_txt"] == {"present": True, "sitemaps_declared": 1}
    assert out["signals"]["ai_crawlers"]["GPTBot"] == "blocked" and out["signals"]["ai_crawlers"]["ClaudeBot"] == "allowed (by the * rule)"
    assert out["signals"]["llms_txt"] == {"present": True, "bytes": 46, "title": "Example", "links": 1}
    assert out["signals"]["sitemap_xml"]["present"] is None, "robots.txt disallows it for our user agent: not read"
    assert not any("sitemap.xml" in c for c in calls)
    assert out["score"] == round(20 + 30 * 5 / 6 + 30, 1)


def test_site_readiness_refuses_off_site_redirects_and_non_public_names(tmp_path):
    routes = {"https://example.org/robots.txt": httpx.Response(302, headers={"location": "https://evil.example.net/robots.txt"}),
              "https://example.org/llms.txt": httpx.Response(406),
              "https://example.org/sitemap.xml": httpx.Response(404)}
    calls = []
    a, _ = agents(tmp_path, routes, calls)
    out = a.execute("site-readiness", {"domain": "example.org"})["result"]
    assert out["signals"]["robots_txt"] == {"present": False, "note": "redirects off the site"}
    assert out["signals"]["llms_txt"] == {"present": None, "note": "not read: HTTP 406"}   # unknown, not absent (ops 11-15)
    assert out["signals"]["sitemap_xml"] == {"present": False, "note": "HTTP 404"}
    assert not any("evil" in c for c in calls)
    for bad in ("localhost", "10.0.0.1", "intranet", "printer.local", "example.org:8443"):
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("site-readiness", {"domain": bad})
        assert err.value.code == "invalid_input"


def test_site_requests_pass_the_public_address_preflight(monkeypatch):
    clock = Clock()
    seen = []
    monkeypatch.setattr(net, "validate_public_url", lambda url: seen.append(url) or (_ for _ in ()).throw(
        net.validate_public_url.__globals__.get("DiscoveryError", ValueError)("private")))
    with pytest.raises(net.SourceError, match="public destination"):
        net.get("https://rebinding.example.com/robots.txt", limiters=limiters(clock, clock.sleep), seconds=2, limit=10,
                any_site=True)
    assert seen == ["https://rebinding.example.com/robots.txt"]
    with pytest.raises(net.SourceError, match="not allowed"):
        net.get("https://127.0.0.1/robots.txt", limiters=limiters(clock, clock.sleep), seconds=2, limit=10, any_site=True)


# ------------------------------------------------------------------ web.grounding (Wikipedia, extractive)
def test_wiki_grounding_quotes_the_best_sentences_with_links(tmp_path):
    calls = []
    pages = [{"index": 1, "title": "Python (programming language)", "fullurl": "https://en.wikipedia.org/wiki/Python_(programming_language)",
              "touched": "2026-11-13T07:06:55Z",
              "extract": "Python is a high-level, general-purpose programming language. Guido van Rossum began working on "
                         "Python in the late 1980s. It is widely used."},
             {"index": 2, "title": "Monty Python", "fullurl": "https://en.wikipedia.org/wiki/Monty_Python",
              "extract": "Monty Python were a British comedy troupe."}]
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": httpx.Response(200, json={"query": {"pages": pages}})}, calls)
    env = a.execute("wiki-grounding", {"question": "Who created the Python programming language?"})
    out = env["result"]
    assert out["answer"].startswith("From Wikipedia (quoted, not generated): ")
    assert "Guido van Rossum began working on Python in the late 1980s." in out["answer"]
    assert out["sources"][0] == "https://en.wikipedia.org/wiki/Python_(programming_language)"
    from agent_market.fallback_agents.agents import search_terms
    assert search_terms("What is the capital city of South Korea?") == "South Korea"
    assert out["source"].startswith("Wikipedia (CC BY-SA 4.0")
    assert "gsrsearch=Who+created+the+Python+programming+language" in calls[0] and "maxlag=5" in calls[0]
    assert len(calls) == 1                     # a question that is not "what is X" has no title to try first


def test_wiki_grounding_quotes_the_subjects_own_article_first(tmp_path):
    """holdout-r3 11-16 (28/30): search ranked "Intrusion detection system" above "Anomaly detection"; the article
    titled as the subject (redirects followed, never a disambiguation page) is quoted first."""
    from agent_market.fallback_agents.agents import subject_title
    calls = []
    side = [{"index": 1, "pageid": 1, "title": "Intrusion detection system", "fullurl": "https://en.wikipedia.org/wiki/Intrusion_detection_system",
             "extract": "Anomaly-based detection finds deviations; anomaly detection of traffic relies on models of anomaly detection."},
            {"index": 2, "pageid": 2, "title": "Anomaly detection", "fullurl": "https://en.wikipedia.org/wiki/Anomaly_detection",
             "extract": "In data analysis, anomaly detection is the identification of rare items."}]
    own = [{"pageid": 2, "title": "Anomaly detection", "fullurl": "https://en.wikipedia.org/wiki/Anomaly_detection",
            "extract": "In data analysis, anomaly detection is the identification of rare items."}]

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"query": {"pages": own if "titles=" in str(request.url) else side}})
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": handler})
    out = a.execute("wiki-grounding", {"question": "What is anomaly detection?"})["result"]
    assert out["sources"][0] == "https://en.wikipedia.org/wiki/Anomaly_detection"
    assert "titles=Anomaly+detection" in calls[0] and "redirects=1" in calls[0]
    assert subject_title("Optogenetics") == "Optogenetics" and subject_title("Who was Ada Lovelace?") == "Ada Lovelace"
    assert subject_title("Who created the Python programming language?") is None
    # a disambiguation page is never the subject's article: then search order and sentence scores decide as before
    own[0] = dict(own[0], pageprops={"disambiguation": ""})
    del side[1]                                  # search alone found only the side article (the real gate case)
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": handler})
    out = a.execute("wiki-grounding", {"question": "What is anomaly detection?"})["result"]
    assert out["sources"][0] == "https://en.wikipedia.org/wiki/Intrusion_detection_system"


def test_wiki_grounding_without_a_match_is_not_found(tmp_path):
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": httpx.Response(200, json={"query": {"pages": []}})})
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("wiki-grounding", {"question": "What is the qwzx of plorb?"})
    assert err.value.code == "not_found"
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("wiki-grounding", {"question": "who is the what?"})
    assert err.value.code == "invalid_input"


# ------------------------------------------------------------------ fx.rate (ECB reference rates)
ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time='2026-11-13'>""" + b"".join(f"<Cube currency='{c}' rate='{r}'/>".encode() for c, r in [
    ("USD", "1.1052"), ("JPY", "176.83"), ("KRW", "1477.80"), ("GBP", "0.8412"), ("CHF", "0.9301"), ("CAD", "1.5300"),
    ("AUD", "1.6900"), ("CNY", "7.9100"), ("SEK", "11.20"), ("NOK", "11.70")]) + b"</Cube></Cube></gesmes:Envelope>"


def test_ecb_fx_states_the_rate_date_and_crosses_through_the_euro(tmp_path):
    from datetime import datetime, timezone
    calls = []
    clock = Clock()
    a = FallbackAgents(http=client({"https://www.ecb.europa.eu/": httpx.Response(200, content=ECB_XML)}, calls), data_dir=tmp_path,
                       clock=clock, wall=lambda: 1.8e9 + clock.t, utc_now=lambda: datetime(2026, 11, 14, 6, 0, tzinfo=timezone.utc),
                       limiters=limiters(clock, clock.sleep))
    usd_eur = a.execute("ecb-fx", {"from": "USD", "to": "EUR", "amount": 100})
    assert usd_eur["result"] == {"from": "USD", "to": "EUR", "rate": 0.904814, "date": "2026-11-13",
                                 "source": "ECB euro foreign exchange reference rates; for information only, not for transactions"}
    usd_jpy = a.execute("ecb-fx", {"from": "USD", "to": "JPY"})["result"]
    assert usd_jpy["rate"] == round(176.83 / 1.1052, 3) and "(crossed through EUR by AgentValCon); for information only" in usd_jpy["source"]
    assert len(calls) == 1 and usd_eur["freshness"]["data_as_of"] == {"ECB": "2026-11-13"}
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("ecb-fx", {"from": "USD", "to": "XYZ"})
    assert err.value.code == "not_found"


def test_ecb_fx_refuses_old_rates_and_dtd_feeds(tmp_path):
    from datetime import datetime, timezone
    from agent_market.fallback_agents.agents import ecb_rates
    clock = Clock()
    a = FallbackAgents(http=client({"https://www.ecb.europa.eu/": httpx.Response(200, content=ECB_XML)}), data_dir=tmp_path,
                       clock=clock, utc_now=lambda: datetime(2026, 11, 25, tzinfo=timezone.utc), limiters=limiters(clock, clock.sleep))
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("ecb-fx", {"from": "USD", "to": "EUR"})
    assert err.value.code == "stale"
    with pytest.raises(ValueError):
        ecb_rates(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')


# ------------------------------------------------------------------ earthquake.feed (USGS)
def quake(mag, t, place, tsunami=0):
    return {"properties": {"mag": mag, "time": t, "place": place, "tsunami": tsunami, "url": "https://earthquake.usgs.gov/x"}}


def test_usgs_quakes_filters_by_magnitude_and_widens_to_the_month(tmp_path):
    week = {"metadata": {"generated": 1794604050000}, "features": [quake(4.8, 1794599361768, "A"), quake(5.3, 1794590000000, "B", 1)]}
    month = {"metadata": {"generated": 1794604050000}, "features": [quake(7.0, 1792680000000, "C")]}
    calls = []
    a, _ = agents(tmp_path, {"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson": httpx.Response(200, json=week),
                             "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson": httpx.Response(200, json=month)}, calls)
    out = a.execute("usgs-quakes", {"min_magnitude": 5})["result"]
    assert out["answer"].startswith("1 earthquake of magnitude 5 or more in the past 7 days") and "M5.3" in out["answer"]
    assert "(tsunami flag)" in out["answer"] and out["source"].startswith("USGS")
    big = a.execute("usgs-quakes", {"magnitude": 7})["result"]["answer"]
    assert "past 30 days" in big and "M7.0" in big and len(calls) == 2
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("usgs-quakes", {"magnitude": 11})
    assert err.value.code == "invalid_input"


# ------------------------------------------------------------------ timezone.time (IANA tz, offline)
def test_tz_time_answers_from_zone_or_city_without_network(tmp_path):
    from datetime import datetime, timezone
    calls = []
    clock = Clock()
    a = FallbackAgents(http=client({}, calls), data_dir=tmp_path, clock=clock,
                       utc_now=lambda: datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc), limiters=limiters(clock, clock.sleep))
    ny = a.execute("tz-time", {"city": "New York", "timezone": "America/New_York"})["result"]
    assert ny["answer"].startswith("Local time in America/New_York: 2026-11-13 16:00:00 EST (UTC-05:00).")
    assert a.execute("tz-time", {"city": "seoul"})["result"]["answer"].startswith("Local time in Asia/Seoul: 2026-11-14 06:00:00 KST")
    assert ny["source"].startswith("IANA Time Zone Database") and calls == []
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("tz-time", {"city": "Atlantis"})
    assert err.value.code == "not_found"


# ------------------------------------------------------------------ airport.lookup (OurAirports index)
AIRPORT_CSV = ('"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent","iso_country","iso_region",'
               '"municipality","scheduled_service","icao_code","iata_code","gps_code","local_code","home_link","wikipedia_link","keywords"\n'
               '1,"RKSI","large_airport","Incheon International Airport",37.469101,126.450996,23,"AS","KR","KR-28","Seoul","yes","RKSI","ICN","RKSI",,,,\n'
               '2,"XX00","closed","Old Field",1,1,1,"NA","US","US-CA","Nowhere","no",,"OLD",,,,,\n'
               + "".join(f'{i},"K{i:03d}","small_airport","Field {i}",1,1,1,"NA","US","US-TX","Town","no","K{i:03d}",,,,,,\n' for i in range(3, 5100)))


def test_airport_index_keeps_coded_open_airports_and_answers_offline(tmp_path):
    from agent_market.fallback_agents.airports import build_index, sync
    index = build_index(AIRPORT_CSV)
    assert "ICN" in index and "RKSI" in index and "OLD" not in index
    calls = []
    sync(tmp_path / "airports.json", http=client({"https://davidmegginson.github.io/": httpx.Response(
        200, text=AIRPORT_CSV, headers={"last-modified": "Fri, 13 Nov 2026 02:53:52 GMT"})}, calls), now=lambda: 1.8e9)
    a, _ = agents(tmp_path, {}, calls)
    env = a.execute("airport-lookup", {"code": "icn"})
    assert env["result"]["answer"].startswith("Incheon International Airport (IATA ICN, ICAO RKSI): Seoul, country code KR "
                                              "(KR-28), large airport")
    assert "time zone" not in env["result"]["answer"]          # no grid on this server: the lookup still answers
    assert env["result"]["url"] == "https://ourairports.com/airports/RKSI/" and len(calls) == 1
    assert env["freshness"]["data_as_of"] == {"OurAirports": "Fri, 13 Nov 2026 02:53:52 GMT"}
    assert "Incheon" in a.execute("airport-lookup", {"query": "incheon"})["result"]["answer"]
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("airport-lookup", {"code": "ZZZ"})
    assert err.value.code == "not_found"


def test_gdelt_news_lists_titles_outlets_dates_and_links_only(tmp_path):
    """PM 11-15 13:52: topic -> article list from GDELT (title, outlet, date, URL), cited, no article text."""
    calls = []
    art = lambda i, url: {"url": url, "title": f"Story {i}", "seendate": f"202611{14 - i:02d}T080000Z",
                          "domain": f"news{i}.example", "language": "English", "socialimage": "x"}
    routes = {"https://api.gdeltproject.org/api/v2/doc/doc": httpx.Response(200, json={"articles": [
        art(1, "https://news1.example/a"), art(2, "http://insecure.example/b"), art(3, "https://news3.example/c")]})}
    a, _ = agents(tmp_path, routes, calls)
    env = a.execute("gdelt-news", {"query": "solar storm", "limit": 5})
    items = env["result"]["items"]
    assert items == [{"title": "Story 1 (news1.example)", "url": "https://news1.example/a", "published": "2026-11-13T08:00:00Z"},
                     {"title": "Story 3 (news3.example)", "url": "https://news3.example/c", "published": "2026-11-11T08:00:00Z"}]
    assert "GDELT Project (https://www.gdeltproject.org/)" in env["result"]["source"]
    assert "mode=artlist" in str(calls[0]) and "timespan=7d" in str(calls[0])
    a.execute("gdelt-news", {"query": "Solar  storm"})                  # same topic: from the cache
    assert len(calls) == 1
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("gdelt-news", {"query": "x"})
    assert err.value.code == "invalid_input"


def test_gdelt_news_plain_text_answers_are_not_news(tmp_path):
    routes = {"https://api.gdeltproject.org/api/v2/doc/doc": httpx.Response(200, text="The specified phrase is too short.")}
    a, _ = agents(tmp_path, routes)
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("gdelt-news", {"query": "ai chips"})
    assert err.value.code == "invalid_input"
    empty = {"https://api.gdeltproject.org/api/v2/doc/doc": httpx.Response(200, json={})}
    a, _ = agents(tmp_path / "e", empty)
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("gdelt-news", {"query": "nothing here today"})
    assert err.value.code == "not_found"


def write_tz_grid(path, step=10.0):
    """A tiny grid in the reader's format: Asia/Seoul at 30-40N 120-130E, a Europe/Zurich|Europe/Berlin boundary
    cell at 40-50N 0-10E, Etc/GMT elsewhere."""
    import json as _json
    import struct
    import zlib
    from array import array
    rows, cols = round(180 / step), round(360 / step)
    zones = ["Etc/GMT", "Asia/Seoul", "Europe/Zurich", "Europe/Berlin"]
    sets = [["Europe/Berlin", "Europe/Zurich"]]
    body = bytearray()
    for r in range(rows):
        runs = [(0, 0)]
        if r == 4:          # row r spans 90-10r .. 90-10(r+1): 50..40N
            runs = [(0, 0), (18, 32768), (19, 0)]
        if r == 5:          # 40..30N
            runs = [(0, 0), (30, 1), (31, 0)]
        body += struct.pack("<I", len(runs)) + array("H", [c for c, _ in runs]).tobytes() + array("H", [v for _, v in runs]).tobytes()
    header = {"format": "avc-tz-grid-1", "step": step, "rows": rows, "cols": cols, "zones": zones, "sets": sets,
              "countries": {"Asia/Seoul": ["KR"], "Europe/Zurich": ["CH", "DE", "LI"], "Europe/Berlin": ["DE", "DK", "NO", "SE", "SJ"],
                            "Etc/GMT": []}, "boundary_data": "test"}
    raw = _json.dumps(header).encode()
    path.write_bytes(b"AVCTZ1\n" + struct.pack("<I", len(raw)) + raw + zlib.compress(bytes(body)))


def test_tz_time_takes_a_point_and_lists_candidates_near_a_boundary(tmp_path):
    """PM 11-15 13:52: lat,lon in; one zone where the grid is sure, the candidates near a boundary, a country code
    narrows them; no network call."""
    from datetime import datetime, timezone
    write_tz_grid(tmp_path / "tz-grid.bin")
    calls = []
    clock = Clock()
    a = FallbackAgents(http=client({}, calls), data_dir=tmp_path, clock=clock,
                       utc_now=lambda: datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc), limiters=limiters(clock, clock.sleep))
    seoul = a.execute("tz-time", {"location": "37.5665,126.9780"})["result"]
    assert seoul["answer"].startswith("Time zone at 37.5665,126.9780: Asia/Seoul. Local time in Asia/Seoul: "
                                      "2026-11-14 06:00:00 KST (UTC+09:00)")
    assert "ODbL" in seoul["source"] and calls == []
    near = a.execute("tz-time", {"location": "47.5,7.6"})["result"]["answer"]
    assert near.startswith("The point 47.5000,7.6000 is near a time zone boundary (within about 2 km); candidate zones: "
                           "Europe/Berlin: ") and "Europe/Zurich: " in near
    swiss = a.execute("tz-time", {"location": "47.5,7.6,CH"})["result"]["answer"]
    assert swiss.startswith("Time zone at 47.5000,7.6000: Europe/Zurich.") and "the country code CH chose the zone" in swiss
    assert "candidate zones" in a.execute("tz-time", {"location": "47.5,7.6,DE"})["result"]["answer"]   # both fit DE
    assert a.execute("tz-time", {"timezone": "Asia/Seoul"})["result"]["answer"].startswith("Local time in Asia/Seoul")
    empty = FallbackAgents(http=client({}, calls), data_dir=tmp_path / "none", clock=clock, limiters=limiters(clock, clock.sleep))
    with pytest.raises(FallbackUnavailable) as err:
        empty.execute("tz-time", {"location": "37.5,127.0"})
    assert err.value.code == "source_unavailable"


def test_airport_lookup_names_the_time_zone_from_the_grid(tmp_path):
    from agent_market.fallback_agents.airports import sync
    calls = []
    sync(tmp_path / "airports.json", http=client({"https://davidmegginson.github.io/": httpx.Response(
        200, text=AIRPORT_CSV, headers={"last-modified": "Fri, 13 Nov 2026 02:53:52 GMT"})}, calls), now=lambda: 1.8e9)
    write_tz_grid(tmp_path / "tz-grid.bin")
    a, _ = agents(tmp_path, {}, calls)
    answer = a.execute("airport-lookup", {"code": "ICN"})["result"]["answer"]
    assert "country code KR (KR-28)" in answer and answer.split(";")[0].endswith(", time zone Asia/Seoul")


def test_airport_lookup_without_an_index_fails_closed(tmp_path):
    a, _ = agents(tmp_path / "empty", {})
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("airport-lookup", {"code": "ICN"})
    assert err.value.code == "source_unavailable"


def test_software_incident_puts_programs_before_same_named_packages_and_takes_spaced_names(tmp_path):
    ossl = nvd_cve("CVE-2026-0001", published="2026-01-01T00:00:00.000",
                   configurations=[{"nodes": [{"cpeMatch": [{"vulnerable": True, "criteria": "cpe:2.3:a:openssl:openssl:*:*:*:*:*:*:*:*",
                                                             "versionEndExcluding": "3.4.8"}]}]}])
    tomcat = nvd_cve("CVE-2026-0002", published="2026-01-02T00:00:00.000",
                     configurations=[{"nodes": [{"cpeMatch": [{"vulnerable": True, "criteria": "cpe:2.3:a:apache:tomcat:*:*:*:*:*:*:*:*",
                                                               "versionEndExcluding": "9.0.121"}]}]}])
    rust = dict(GH_ROW, ghsa_id="GHSA-phqj-4mhp-q6mq", summary="rust-openssl issue",
                vulnerabilities=[{"package": {"ecosystem": "rust", "name": "openssl"}, "first_patched_version": "0.10.80"}])
    calls = []
    a, _ = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(200, json=[rust])}, calls,
                  snapshot=seeded_snapshot(tmp_path, ossl, tomcat))
    out = a.execute("software-incident", {"query": "openssl"})["result"]
    assert [i["title"][:13] for i in out["items"]] == ["CVE-2026-0001", "GHSA-phqj-4mh"]
    assert out["source"].startswith("NVD (CPE product match") and "then GitHub Advisory" in out["source"]
    spaced = a.execute("software-incident", {"query": "Apache Tomcat"})["result"]
    assert spaced["items"][0]["fixed_version"] == "9.0.121" and len(calls) == 1, "spaced program names skip the package search"


# ------------------------------------------------------------------ dictionary, github.repo, domain (RDAP), unit.convert
def test_wiktionary_define_strips_markup_and_credits(tmp_path):
    body = {"en": [{"partOfSpeech": "Noun", "definitions": [
        {"definition": 'The <a href="/wiki/x">phenomenon</a> of making an unplanned, fortunate discovery.'}]}]}
    a, _ = agents(tmp_path, {"https://en.wiktionary.org/api/rest_v1/page/definition/serendipity": httpx.Response(200, json=body)})
    out = a.execute("wiktionary-define", {"word": "serendipity"})["result"]
    assert out["answer"] == "serendipity — Noun: (1) The phenomenon of making an unplanned, fortunate discovery."
    assert out["source"].startswith("Wiktionary (CC BY-SA 4.0") and out["url"] == "https://en.wiktionary.org/wiki/serendipity"


def test_github_repo_follows_one_move_on_the_same_host(tmp_path):
    calls = []
    repo = {"full_name": "react/react", "description": "UI library", "license": {"spdx_id": "MIT"}, "stargazers_count": 252591,
            "forks_count": 50000, "open_issues_count": 900, "default_branch": "main", "archived": False,
            "pushed_at": "2026-11-13T10:28:38Z", "html_url": "https://github.com/react/react", "owner": {"email": "x@y.z"}}
    a, _ = agents(tmp_path, {"https://api.github.com/repos/facebook/react": httpx.Response(301, headers={"location": "https://api.github.com/repositories/10270250"}),
                             "https://api.github.com/repositories/10270250": httpx.Response(200, json=repo)}, calls)
    env = a.execute("github-repo", {"repo": "https://github.com/facebook/react"})
    answer = env["result"]["answer"]
    assert answer.startswith("react/react: UI library. License MIT; 252591 stars;") and "Requested facebook/react" in answer
    assert "x@y.z" not in json.dumps(env) and len(calls) == 2


def test_rdap_domain_uses_the_bootstrap_server_and_drops_contacts(tmp_path):
    boot = {"publication": "2026-10-28T22:00:04Z", "services": [[["org"], ["https://rdap.example-registry.org/rdap/"]]]
            + [[[f"t{i}"], [f"https://rdap{i}.example/"]] for i in range(120)]}
    rdap = {"events": [{"eventAction": "registration", "eventDate": "1995-03-27T05:00:00Z"},
                       {"eventAction": "expiration", "eventDate": "2033-03-28T05:00:00Z"},
                       {"eventAction": "last update of RDAP database", "eventDate": "2026-11-13T21:15:25Z"}],
            "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "Gandi SAS"]]]},
                         {"roles": ["registrant"], "vcardArray": ["vcard", [["fn", {}, "text", "Jane Private"], ["email", {}, "text", "jane@x.org"]]]}],
            "status": ["client transfer prohibited"], "nameservers": [{"ldhName": "NS1.EXAMPLE.ORG"}]}
    calls = []
    a, _ = agents(tmp_path, {"https://data.iana.org/rdap/dns.json": httpx.Response(200, json=boot),
                             "https://rdap.example-registry.org/rdap/domain/python.org": httpx.Response(200, json=rdap)}, calls)
    env = a.execute("rdap-domain", {"domain": "Python.org"})
    assert env["result"]["answer"] == ("python.org: registered 1995-03-27; expires 2033-03-28; last changed ?; registrar Gandi SAS; "
                                       "status client transfer prohibited; name servers ns1.example.org.")
    assert "Jane" not in json.dumps(env) and "jane@" not in json.dumps(env)
    assert env["freshness"]["data_as_of"] == {"RDAP registry": "2026-11-13T21:15:25Z"}
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("rdap-domain", {"domain": "example.zzzz"})
    assert err.value.code == "not_found"


def test_unit_convert_exact_factors_temperature_and_mismatch(tmp_path):
    from agent_market.fallback_agents.agents import convert_units
    a, _ = agents(tmp_path, {})
    assert a.execute("unit-convert", {"value": 10, "from": "miles", "to": "km"})["result"]["answer"] == "10 mile = 16.09344 kilometer"
    assert convert_units(212, "°F", "C")[0] == pytest.approx(100)
    assert convert_units(1, "gallon", "liter")[0] == pytest.approx(3.785411784)
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("unit-convert", {"value": 3, "from": "kg", "to": "mile"})
    assert err.value.code == "invalid_input"


# ------------------------------------------------------------------ hourly watch of the fallback agents
def write_usage(root, rows):
    folder = root / "usage"
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{rows[0]['at'][:10]}.jsonl", "a") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_watch_records_health_snapshots_quota_and_alerts_once_a_day(tmp_path):
    from agent_market.fallback_agents.watch import health, observe
    import sqlite3
    now = 1794600000.0
    at = lambda s: __import__("datetime").datetime.fromtimestamp(now - s, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    write_usage(tmp_path, [{"at": at(900), "agent": "cve-org", "ok": False, "code": "source_unavailable"},
                           {"at": at(800), "agent": "cve-org", "ok": False, "code": "rate_limited"},
                           {"at": at(700), "agent": "cve-org", "ok": False, "code": "source_unavailable"},
                           {"at": at(600), "agent": "public-holidays", "ok": False, "code": "not_found"},
                           {"at": at(500), "agent": "nvd-cve", "ok": False, "code": "stale"},
                           {"at": at(400), "agent": "nvd-cve", "ok": True, "code": None}])
    db = sqlite3.connect(tmp_path / "nvd-cve.sqlite3")
    db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('synced_at', ?)", (repr(now - 7 * 3600),))
    db.commit(); db.close()
    state = {}
    line = observe(state, tmp_path, now, (0, 60, int(now) + 1200))
    assert line["agents"]["cve-org"]["status"] == "failing" and line["agents"]["public-holidays"]["status"] == "healthy"
    assert line["agents"]["nvd-cve"]["stale"] == 1 and line["stale_failures"] == 1
    assert line["snapshots"]["nvd"]["over_limit"] is True and line["snapshots"]["airports"]["present"] is False
    assert {a["key"] for a in line["alerts"]} == {"source_failing:cve-org", "snapshot_stale:nvd", "quota_low:github"}
    assert observe(state, tmp_path, now + 3600, (0, 60, int(now) + 4800))["alerts"] == [], "one alert a day per key"
    (tmp_path / "watch").mkdir()
    (tmp_path / "watch" / "state.json").write_text(json.dumps(state))
    assert health("nvd-cve", tmp_path)["status"] == "failing" and health("nvd-cve", tmp_path)["snapshot_problem"]
    assert health("unit-convert", tmp_path)["status"] == "idle"


def test_watch_runs_outside_the_measurement_window(tmp_path):
    from agent_market.fallback_agents.watch import FallbackWatch
    import time as _t
    base = _t.mktime((2026, 11, 14, 10, 30, 0, 0, 0, -1))
    w = FallbackWatch(data_dir=tmp_path, clock=lambda: base, quota=lambda: None)
    assert w.due()
    out = w.run()
    assert out["failing"] == [] and (tmp_path / "watch" / "state.json").exists() and not w.due()
    quiet = FallbackWatch(data_dir=tmp_path, clock=lambda: base + 26 * 60, quota=lambda: None)  # 10:56
    assert not quiet.due()


# ------------------------------------------------------------------ place.search and book.search (Wikidata, CC0)
def wikidata_routes(search_ids, bindings):
    return {"https://www.wikidata.org/w/api.php": httpx.Response(200, json={"search": [{"id": i} for i in search_ids]}),
            "https://query.wikidata.org/sparql": httpx.Response(200, json={"results": {"bindings": bindings}})}


def b(**kw):
    return {k: {"value": v} for k, v in kw.items()}


def test_wikidata_place_takes_the_first_hit_with_coordinates(tmp_path):
    calls = []
    rows = [b(item="http://www.wikidata.org/entity/Q18927486", itemLabel="Eiffel Tower", itemDescription="painting"),
            b(item="http://www.wikidata.org/entity/Q243", itemLabel="Eiffel Tower", itemDescription="tower in Paris, France",
              P625="Point(2.294479 48.858296)", P131="x", P131Label="7th arrondissement of Paris", P17="y", P17Label="France")]
    a, _ = agents(tmp_path, wikidata_routes(["Q18927486", "Q243"], rows), calls)
    out = a.execute("wikidata-place", {"query": "Eiffel Tower"})["result"]
    assert out["answer"] == ("Eiffel Tower — tower in Paris, France (Wikidata Q243): coordinates latitude 48.85830, "
                             "longitude 2.29448; located in 7th arrondissement of Paris, France.")
    assert out["url"] == "https://www.wikidata.org/wiki/Q243" and out["source"] == "Wikidata (CC0)" and len(calls) == 2
    assert "VALUES+%3Fitem" in calls[1] or "VALUES" in __import__("urllib.parse").parse.unquote_plus(calls[1])


def test_wikidata_book_names_the_author_and_year(tmp_path):
    rows = [b(item="http://www.wikidata.org/entity/Q161531", itemLabel="War and Peace", itemDescription="1869 novel by Leo Tolstoy",
              P50="a", P50Label="Leo Tolstoy", P577="1869-01-01T00:00:00Z", P136="g", P136Label="historical fiction")]
    a, _ = agents(tmp_path, wikidata_routes(["Q161531"], rows))
    out = a.execute("wikidata-book", {"title": "War and Peace"})["result"]
    assert out["answer"] == ("War and Peace — 1869 novel by Leo Tolstoy (Wikidata Q161531); author Leo Tolstoy; "
                             "first published 1869; genre historical fiction.")
    b2, _ = agents(tmp_path / "b", wikidata_routes(["Q1"], [b(item="http://www.wikidata.org/entity/Q1", itemLabel="X")]))
    with pytest.raises(FallbackUnavailable) as err:
        b2.execute("wikidata-book", {"title": "No author here"})
    assert err.value.code == "not_found"


def test_host_limits_are_shared_across_processes(tmp_path):
    """R30 (PM 11-15): two limiters on one shared file (as two processes would be) keep one spacing, one window
    and one rest between them."""
    from agent_market.fallback_agents.limits import HostLimiter, SourceBusy
    clock = Clock()
    path = tmp_path / "host-limits" / "api.gleif.org.json"
    a = HostLimiter(1.0, 2, 60.0, clock, clock.sleep, shared=path, wall=clock)
    b = HostLimiter(1.0, 2, 60.0, clock, clock.sleep, shared=path, wall=clock)
    with a.slot(3.0):
        pass
    t0 = clock.t
    with b.slot(3.0):          # the other "process" waits for the shared spacing
        pass
    assert clock.t - t0 == pytest.approx(1.0)
    with pytest.raises(SourceBusy, match="allowance"):   # the window of 2 is used up by both together
        with a.slot(3.0):
            pass
    clock.t += 61
    with b.slot(3.0):
        b.observed(429, {"retry-after": "120"})
    with pytest.raises(SourceBusy, match="resting"):     # a 429 seen by one rests the other too
        with a.slot(3.0):
            pass
    assert a.resting() == pytest.approx(120.0)


def test_default_agents_share_host_limits_under_the_data_folder(tmp_path):
    a = FallbackAgents(data_dir=tmp_path)
    assert a.limiters["api.gleif.org"].shared == tmp_path / "host-limits" / "api.gleif.org.json"


# ------------------------------------------------------------------ gate grading for book and site substitutes (ops 11-15)
def test_gold_slugs_and_judges_for_book_and_site_substitutes():
    from agent_market.fallback_agents import gold_check as g
    assert g.SLUG["wikidata-book"] == "book-author-brief" and g.SLUG["site-readiness"] == "website-trust-brief"
    case = {"truth": {"author": "Virginia Woolf", "year": 1927}}
    good = {"answer": "To the Lighthouse (1927 novel), author Virginia Woolf (born 1882)."}
    assert g.judge("wikidata-book", case, good)["pass"]
    assert not g.judge("wikidata-book", case, {"answer": "To the Lighthouse, author Virginia Woolf, published 1928."})["pass"]
    assert not g.judge("wikidata-book", case, None)["pass"]
    site = {"input": {"domain": "example.com"}}
    robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    truth = {"robots": robots, "robots_note": None, "llms_txt": False, "sitemap_xml": True}
    answer = {"domain": "example.com", "signals": {"robots_txt": {"present": True},
              "ai_crawlers": {"GPTBot": "blocked", "ClaudeBot": "allowed (by the * rule)"},
              "llms_txt": {"present": False}, "sitemap_xml": {"present": True}}, "source": "x"}
    assert g.judge_site(site, answer, truth)["pass"]
    wrong = {**answer, "signals": {**answer["signals"], "ai_crawlers": {"GPTBot": "allowed"}}}
    assert g.judge_site(site, wrong, truth)["problems"] == ["GPTBot"]
    unknown = {**answer, "signals": {**answer["signals"], "llms_txt": {"present": None, "note": "not read"}}}
    assert g.judge_site(site, unknown, {**truth, "llms_txt": True})["pass"]          # the agent's unknown is not graded
    down = {"robots": None, "robots_note": "could not read: timed out", "llms_txt": None, "sitemap_xml": None}
    said = {"domain": "example.com", "signals": {"robots_txt": {"present": False, "note": "could not read: timed out"}},
            "source": "x"}
    assert g.judge_site(site, said, down)["pass"] and not g.judge_site(site, answer, down)["pass"]
    absent = {"robots": None, "robots_note": "HTTP 404", "llms_txt": False, "sitemap_xml": False}
    assert not g.judge_site(site, answer, absent)["pass"]                              # it said present
    assert g.applies("site-readiness", site) and not g.applies("site-readiness", {"input": {}})


def test_usgs_quakes_near_a_point_filters_the_feed_by_distance_and_days(tmp_path):
    """PM 11-15 13:53: lat/lon/radius_km/days from the same USGS feed, no extra request (workflow 0aac4347)."""
    from datetime import datetime, timezone
    now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    ms = lambda days_ago: int((now.timestamp() - days_ago * 86400) * 1000)

    def at(mag, t, place, lat, lon):
        return {"properties": {"mag": mag, "time": t, "place": place, "tsunami": 0, "url": "https://e/x"},
                "geometry": {"type": "Point", "coordinates": [lon, lat, 10.0]}}
    week = {"metadata": {"generated": ms(0)}, "features": [
        at(5.1, ms(1), "near Tokyo", 35.7, 139.8), at(4.9, ms(6), "Izu", 34.6, 139.4),
        at(6.0, ms(2), "Chile", -33.4, -70.6)]}
    calls = []
    clock = Clock()
    a = FallbackAgents(http=client({"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson":
                                    httpx.Response(200, json=week)}, calls), data_dir=tmp_path, clock=clock,
                       utc_now=lambda: now, limiters=limiters(clock, clock.sleep))
    tokyo = a.execute("usgs-quakes", {"lat": 35.68, "lon": 139.76, "radius_km": 1000, "days": 7, "min_magnitude": 4.5})
    answer = tokyo["result"]["answer"]
    assert answer.startswith("2 earthquakes of magnitude 4.5 or more within 1000 km of 35.6800,139.7600 in the past 7 days")
    assert "near Tokyo, 4 km away, lat 35.700 lon 139.800" in answer and "Chile" not in answer
    short = a.execute("usgs-quakes", {"near": "35.68,139.76", "radius_km": 500, "days": 3})["result"]["answer"]
    assert short.startswith("1 earthquake") and "Izu" not in short
    none = a.execute("usgs-quakes", {"lat": 0.0, "lon": 0.0, "radius_km": 100, "days": 7})["result"]["answer"]
    assert none.startswith("No earthquake of magnitude 4.5 or more within 100 km of 0.0000,0.0000")
    assert len(calls) == 1                                              # one feed, filtered on our side
    with pytest.raises(FallbackUnavailable):
        a.execute("usgs-quakes", {"lat": 35.0})


def write_country_grid(path, step=10.0):
    """A tiny country grid: KR at 30-40N 120-130E, a KR|KP border cell at 40-50N 120-130E, a disputed IN|PK|CN cell
    at 30-40N 70-80E, sea elsewhere."""
    import json as _json
    import struct
    import zlib
    from array import array
    rows, cols = round(180 / step), round(360 / step)
    zones = ["", "KR", "KP", "IN", "PK", "CN"]
    sets = [["KP", "KR"], ["CN", "IN", "PK"], ["KR"]]
    body = bytearray()
    for r in range(rows):
        runs = [(0, 0)]
        if r == 4:
            runs = [(0, 0), (30, 32768), (31, 0)]
        if r == 5:
            runs = [(0, 0), (25, 32769), (26, 0), (30, 1), (31, 32770), (32, 0)]   # 130-140E: a KR coast cell
        body += struct.pack("<I", len(runs)) + array("H", [c for c, _ in runs]).tobytes() + array("H", [v for _, v in runs]).tobytes()
    header = {"format": "avc-country-grid-1", "step": step, "rows": rows, "cols": cols, "zones": zones, "sets": sets,
              "disputed": [1], "countries": {}}
    raw = _json.dumps(header).encode()
    path.write_bytes(b"AVCTZ1\n" + struct.pack("<I", len(raw)) + raw + zlib.compress(bytes(body)))


def test_holiday_calendar_takes_a_point_through_the_country_grid(tmp_path):
    """PM 11-15 13:58: an address hub gives coordinates only; one country inside it, none near a border, at sea or in
    a disputed area."""
    write_country_grid(tmp_path / "country-grid.bin")
    a, _ = agents(tmp_path, {})
    seoul = a.execute("holiday-calendar", {"country": "37.5665,126.9780", "year": 2026})["result"]["answer"]
    assert seoul.startswith("National public holidays in South Korea, 2026") or "Korea" in seoul[:60]
    assert "2026-03-01" in seoul
    for point, words in (("45.0,125.0", "border (KP, KR)"), ("35.0,75.0", "disputed area (CN, IN, PK)"),
                         ("0.0,0.0", "at sea")):
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("holiday-calendar", {"country": point, "year": 2026})
        assert err.value.code == "not_found" and words in str(err.value)
    assert "2026-03-01" in a.execute("holiday-calendar", {"country": "45.0,125.0,KR", "year": 2026})["result"]["answer"]
    assert "2026-03-01" in a.execute("holiday-calendar", {"country": "35.0,135.0", "year": 2026})["result"]["answer"]  # coast
    empty, _ = agents(tmp_path / "none", {})
    with pytest.raises(FallbackUnavailable) as err:
        empty.execute("holiday-calendar", {"country": "37.5,127.0"})
    assert err.value.code == "source_unavailable"


def test_gold_judges_for_rdap_wiki_grounding_and_sec_filings():
    """ops 11-15 14:2x: the three substitutes the gate could not run."""
    from agent_market.fallback_agents import gold_check as g
    assert g.SLUG["rdap-domain"] == "website-trust-brief" and g.SLUG["wiki-grounding"] == "topic-evidence-brief"
    assert g.SLUG["sec-filings"] == "company-due-diligence"
    rdap = {"truth": {"registered": "2013-06-18", "registrar": "MarkMonitor Inc."}}
    good = {"answer": "doordash.com: registered 2013-06-18; expires 2027-06-18; registrar MarkMonitor Inc.; status x."}
    assert g.judge("rdap-domain", rdap, good)["pass"]
    assert not g.judge("rdap-domain", rdap, {"answer": "doordash.com: registered 2013-06-19; registrar MarkMonitor Inc."})["pass"]
    topic = {"input": {"topic": "Machine learning"}, "truth": {"wiki": {"title": "Machine learning"}}}
    assert g.case_arguments("wiki-grounding", topic) == {"question": "What is Machine learning?"}
    assert g.judge("wiki-grounding", topic, {"sources": ["https://en.wikipedia.org/wiki/Machine_learning"]})["pass"]
    assert g.judge("wiki-grounding", {"truth": {"wiki": {"title": "C++"}}},
                   {"sources": ["https://en.wikipedia.org/wiki/C%2B%2B"]})["pass"]
    assert not g.judge("wiki-grounding", topic, {"sources": ["https://en.wikipedia.org/wiki/Deep_learning"]})["pass"]
    company = {"input": {"name": "Rand Capital Corp", "country": "US"}, "truth": {"cik": "81955"}}
    assert g.case_arguments("sec-filings", company) == {"company": "Rand Capital Corp"}
    assert g.judge("sec-filings", company, {"answer": "Matched SEC filer: RAND CAPITAL CORP (SEC CIK 81955), by exact company name."})["pass"]
    assert not g.judge("sec-filings", company, {"answer": "No SEC EDGAR registration matches (company Rand)."})["pass"]
    assert g.applies("sec-filings", company) and not g.applies("sec-filings", {"truth": {"cik": None}})
    assert not g.applies("rdap-domain", {"truth": {}}) and g.applies("wiki-grounding", topic)


def test_census_geocode_answers_us_addresses_and_does_not_send_others(tmp_path):
    """PM 11-15 14:25: U.S. addresses only, the address string the only thing sent; others answer not_found."""
    calls = []
    hit = {"result": {"addressMatches": [{"matchedAddress": "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
                                          "coordinates": {"x": -77.0365, "y": 38.8977}}]}}
    a, _ = agents(tmp_path, {"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress": httpx.Response(200, json=hit)}, calls)
    out = a.execute("census-geocode", {"address": "1600 Pennsylvania Ave NW, Washington, DC 20500"})["result"]
    assert out["answer"] == "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500: lat 38.897700 lon -77.036500, country code US."
    assert "address=1600" in calls[0] and "benchmark=Public_AR_Current" in calls[0]
    for address in ("Tokyo Tower, Minato, Tokyo, Japan", "서울특별시 중구 세종대로 110"):
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("census-geocode", {"address": address})
        assert err.value.code == "not_found" and "U.S. addresses only" in str(err.value)
    assert len(calls) == 1                                                     # neither was sent
    miss, _ = agents(tmp_path / "m", {"https://geocoding.geo.census.gov/": httpx.Response(200, json={"result": {"addressMatches": []}})})
    with pytest.raises(FallbackUnavailable) as err:
        miss.execute("census-geocode", {"address": "1 Nowhere Road, Atlantis"})
    assert err.value.code == "not_found"


def test_census_geocode_drops_a_match_on_another_street():
    """workflow us-street check 11-15: the Census matcher turned 2301 N Highland Ave into 2301 Highland Dr."""
    from agent_market.fallback_agents.agents import same_street
    assert not same_street("2301 N Highland Ave, Los Angeles, CA, USA", "2301 HIGHLAND DR, LOS ANGELES, CA, 90016")
    assert same_street("2301 N Highland Ave, Los Angeles, CA, USA", "2301 N HIGHLAND AVE, LOS ANGELES, CA, 90068")
    assert same_street("116 5th Ave N, Nashville, TN, USA", "116 5TH AVE N, NASHVILLE, TN, 37219")
    assert not same_street("24 Beacon St, Boston", "42 BEACON ST, BOSTON, MA, 02133")
    assert same_street("1600 Pennsylvania Avenue NW, Washington, DC 20500", "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500")


def test_an_old_grid_reports_its_age_and_turns_stale(tmp_path):
    """PM 11-15 14:57: a grid's build date is its data date; past MAX_AGE the slot moves on with 'stale'."""
    import json as _json
    import struct
    from datetime import datetime, timezone
    write_tz_grid(tmp_path / "tz-grid.bin")
    raw = (tmp_path / "tz-grid.bin").read_bytes()
    size = struct.unpack_from("<I", raw, 7)[0]
    header = _json.loads(raw[11:11 + size])
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)

    def with_built(days):
        h = _json.dumps({**header, "built": datetime.fromtimestamp(now.timestamp() - days * 86400, timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M:%SZ")}).encode()
        (tmp_path / "tz-grid.bin").write_bytes(raw[:7] + struct.pack("<I", len(h)) + h + raw[11 + size:])
        clock = Clock()
        return FallbackAgents(http=client({}), data_dir=tmp_path, clock=clock, wall=lambda: now.timestamp(),
                              utc_now=lambda: now, limiters=limiters(clock, clock.sleep))
    env = with_built(30).execute("tz-time", {"location": "37.5,127.0"})
    assert env["freshness"]["age_seconds"] == 30 * 86400 and env["freshness"]["data_as_of"]["time zone grid built"]
    with pytest.raises(FallbackUnavailable) as err:
        with_built(500).execute("tz-time", {"location": "37.5,127.0"})
    assert err.value.code == "stale"


def test_freshness_lists_every_local_data_file_with_its_age(tmp_path):
    """PM 11-15 14:57: the ops watch reads each file's own date, limit and renewal; missing or old is stale."""
    import json as _json
    from agent_market.fallback_agents import freshness
    now = 1.8e9
    (tmp_path / "airports.json").write_text(_json.dumps({"fetched_at": now - 2 * 86400, "airports": {}}))
    write_tz_grid(tmp_path / "tz-grid.bin")
    rows = {r["file"]: r for r in freshness.report(tmp_path, now=now)}
    assert rows["airports.json"]["age_days"] == 2.0 and not rows["airports.json"]["stale"]
    assert rows["country-grid.bin"] == {**rows["country-grid.bin"], "present": False, "stale": True}
    assert rows["tz-grid.bin"]["present"] and rows["tz-grid.bin"]["date_kind"] == "file time"   # the test grid has no built
    old = freshness.report(tmp_path, now=now + 10 * 86400)
    assert next(r for r in old if r["file"] == "airports.json")["stale"]


def test_gold_judge_for_arxiv_search():
    """PM 11-15 16:07: topic-evidence-brief papers seat; the truth's paper phrase in a returned title."""
    from agent_market.fallback_agents import gold_check as g
    case = {"input": {"topic": "Public transport"}, "truth": {"paper_phrase": "public transport"}}
    assert g.SLUG["arxiv-search"] == "topic-evidence-brief" and g.applies("arxiv-search", case)
    assert g.case_arguments("arxiv-search", case) == {"query": "Public transport"}
    good = {"items": [{"title": "Demand models for public transport networks", "url": "https://arxiv.org/abs/2401.1"}]}
    assert g.judge("arxiv-search", case, good)["pass"]
    assert not g.judge("arxiv-search", case, {"items": [{"title": "Transport of heat", "url": "https://arxiv.org/abs/1"}]})["pass"]
    assert not g.judge("arxiv-search", case, {"items": [{"title": "Public transport", "url": "http://x"}]})["pass"]
    assert not g.applies("arxiv-search", {"truth": {}})
    ageing = {"input": {"topic": "Population ageing"}, "truth": {"paper_phrase": "population ageing"}}
    loose = {"items": [{"title": "Simulation for competition of languages with an ageing sexual population", "url": "https://a/1"}]}
    assert not g.judge("arxiv-search", ageing, loose)["pass"]                      # words apart: not the phrase
    assert g.judge("arxiv-search", ageing, {"items": [{"title": "Ageing populations and pensions", "url": "https://a/2"}]})["pass"]
    income = {"input": {"topic": "Income distribution"}, "truth": {"paper_phrase": "income inequality"}}
    assert g.judge("arxiv-search", income, {"items": [{"title": "The Gompertz-Pareto Income Distribution", "url": "https://a/3"}]})["pass"]


def test_mcp_registry_lookup_reads_latest_and_not_found_is_an_answer(tmp_path):
    """PM 11-15 16:12: name -> latest entry; a missing name is listed false, not an error."""
    entry = {"server": {"name": "biz.agentconcierge/agent-concierge", "version": "1.0.0", "websiteUrl": "https://agentconcierge.biz",
                        "remotes": [{"type": "streamable-http", "url": "https://agentconcierge.biz/mcp"}]},
             "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "publishedAt": "2026-11-09T12:48:24Z"}}}
    base = "https://registry.modelcontextprotocol.io/v0.1/servers"
    routes = {base + "/biz.agentconcierge%2Fagent-concierge/versions/latest": httpx.Response(200, json=entry),
              base + "?": httpx.Response(200, json={"servers": [entry]})}
    calls = []
    a, _ = agents(tmp_path, routes, calls)
    out = a.execute("mcp-registry", {"name": "biz.agentconcierge/agent-concierge"})["result"]
    assert out["listed"] and out["version"] == "1.0.0" and out["status"] == "active"
    assert out["published_at"] == "2026-11-09T12:48:24Z" and out["remotes"] == ["https://agentconcierge.biz/mcp"]
    missing = a.execute("mcp-registry", {"name": "io.github.nobody/nothing"})["result"]
    assert missing["listed"] is False and "no entry" in missing["source"]
    found = a.execute("mcp-registry", {"query": "biz.agentconcierge/agent-concierge"})["result"]
    assert found["listed"] and "search=biz.agentconcierge" in calls[-1]
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("mcp-registry", {"name": "not a name"})
    assert err.value.code == "invalid_input"


def test_github_releases_lists_tags_gaps_and_open_issues(tmp_path):
    """PM 11-15 16:12: releases and issues, two calls, issues without pull requests, no made-up release."""
    rel = [{"tag_name": "v2.32.3", "published_at": "2026-10-30T10:00:00Z"}, {"tag_name": "v2.32.2", "published_at": "2026-09-30T10:00:00Z"},
           {"tag_name": "v3.0.0rc1", "published_at": "2026-09-01T00:00:00Z", "prerelease": True}, {"tag_name": "draft", "draft": True}]
    iss = [{"number": 7001, "title": "Timeouts ignored", "created_at": "2026-11-14T01:00:00Z"},
           {"number": 7000, "title": "Bump deps", "created_at": "2026-11-13T01:00:00Z", "pull_request": {}}]
    calls = []
    a, _ = agents(tmp_path, {"https://api.github.com/repos/psf/requests/releases": httpx.Response(200, json=rel),
                             "https://api.github.com/repos/psf/requests/issues": httpx.Response(200, json=iss)}, calls)
    out = a.execute("github-releases", {"repository": "https://github.com/psf/requests"})["result"]
    assert out["answer"] == ("psf/requests: recent releases (newest first): v2.32.3 2026-10-30; v2.32.2 2026-09-30; "
                             "v3.0.0rc1 2026-09-01 (pre-release). Gaps between them: 30, 29 days. "
                             "Newest open issues: #7001 Timeouts ignored (2026-11-14).")
    assert len(calls) == 2
    assert out["latest_tag"] == "v2.32.3" and out["latest_date"] == "2026-10-30" and out["release_gap_days"] == [30, 29]
    assert out["open_issues"] == [{"number": 7001, "title": "Timeouts ignored", "date": "2026-11-14"}] and out["repo"] == "psf/requests"
    empty, _ = agents(tmp_path / "e", {"https://api.github.com/repos/a/b/releases": httpx.Response(200, json=[]),
                                       "https://api.github.com/repos/a/b/issues": httpx.Response(200, json=[])})
    assert empty.execute("github-releases", {"repo": "a/b"})["result"]["answer"] == \
        "a/b: no GitHub releases published (tags may still exist). No open issues."
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("github-releases", {"repo": "not a repo"})
    assert err.value.code == "invalid_input"


def test_package_releases_reads_one_npm_document(tmp_path):
    """PM 11-15 16:12: latest and its date, maintainers, deprecation, stable release gaps, repository."""
    doc = {"dist-tags": {"latest": "4.17.21"}, "maintainers": [{"name": "a"}, {"name": "b"}],
           "repository": {"type": "git", "url": "git+https://github.com/lodash/lodash.git"},
           "versions": {"4.17.21": {}, "4.17.20": {}, "4.17.19": {}, "5.0.0-beta.1": {}},
           "time": {"created": "2012-04-23T00:00:00Z", "4.17.21": "2021-02-20T15:42:16Z", "4.17.20": "2020-08-13T16:53:54Z",
                    "4.17.19": "2020-07-08T17:14:40Z", "5.0.0-beta.1": "2021-03-01T00:00:00Z"}}
    calls = []
    a, _ = agents(tmp_path, {"https://registry.npmjs.org/lodash": httpx.Response(200, json=doc)}, calls)
    out = a.execute("package-releases", {"package": "lodash", "ecosystem": "npm"})["result"]
    assert out["answer"] == ("lodash (npm): latest 4.17.21 released 2021-02-20; 2 maintainers; not deprecated; 4 versions in all; "
                             "recent stable releases: 4.17.21 2021-02-20, 4.17.20 2020-08-13, 4.17.19 2020-07-08 (gaps 191, 36 days); "
                             "repository https://github.com/lodash/lodash.")
    assert out["repository_github"] == "lodash/lodash" and out["repository"] == "https://github.com/lodash/lodash"
    assert out["latest_version"] == "4.17.21" and out["latest_date"] == "2021-02-20" and out["maintainers"] == 2
    assert out["deprecated"] is False and out["release_gap_days"] == [191, 36]
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("package-releases", {"package": "requests", "ecosystem": "PyPI"})
    assert err.value.code == "source_unavailable" and len(calls) == 1


def test_gold_judge_for_package_releases():
    """workflow 11-15: package-risk-audit v2 meta seat; the truth's latest version, npm cases only for now."""
    from agent_market.fallback_agents import gold_check as g
    case = {"input": {"ecosystem": "npm", "package": "lodash", "version": "4.17.21"}, "truth": {"latest_version": "4.18.1"}}
    assert g.SLUG["package-releases"] == "package-risk-audit" and g.applies("package-releases", case)
    assert g.case_arguments("package-releases", case) == {"ecosystem": "npm", "package": "lodash"}
    assert g.judge("package-releases", case, {"latest_version": "4.18.1", "answer": "x", "source": "npm"})["pass"]
    assert not g.judge("package-releases", case, {"latest_version": "4.17.21", "answer": "x", "source": "npm"})["pass"]
    assert not g.applies("package-releases", {"input": {"ecosystem": "PyPI"}})


def test_tls_certificate_refuses_names_that_reach_private_addresses(tmp_path):
    """workflow 11-15: the handshake goes only to a checked public address; nothing is connected otherwise."""
    a, _ = agents(tmp_path, {})
    connected = []
    a.connect = lambda addr, timeout: connected.append(addr)
    a.resolve = lambda host: [(2, 1, 6, "", ("10.0.0.5", 443))]
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("tls-certificate", {"domain": "intranet-example.com"})
    assert err.value.code == "invalid_input" and connected == []
    a.resolve = lambda host: [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]
    with pytest.raises(FallbackUnavailable):
        a.execute("tls-certificate", {"domain": "mixed-example.com"})
    assert connected == []
    for bad in ("localhost", "10.0.0.1", "printer.local"):
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("tls-certificate", {"domain": bad})
        assert err.value.code == "invalid_input"


def test_gold_judges_for_software_incident_and_github_releases():
    """workflow 11-15: the fix seat compares first patched versions; the activity seat the latest release tag."""
    from agent_market.fallback_agents import gold_check as g
    cve = {"input": {"cve_id": "CVE-2021-23337"},
           "truth": {"fixes": [{"ecosystem": "npm", "name": "lodash", "first_patched_version": "4.17.21"}]}}
    assert g.SLUG["software-incident"] == "cve-incident-brief" and g.applies("software-incident", cve)
    assert g.case_arguments("software-incident", cve) == {"query": "CVE-2021-23337"}
    good = {"items": [], "cve_id": "CVE-2021-23337", "packages": [{"ecosystem": "npm", "name": "lodash", "first_patched_version": "4.17.21"}]}
    assert g.judge("software-incident", cve, good)["pass"]
    assert not g.judge("software-incident", cve, {**good, "packages": [{"name": "lodash", "first_patched_version": "4.17.20"}]})["pass"]
    assert not g.applies("software-incident", {"input": {"cve_id": "CVE-1"}, "truth": {"kev": True}})
    repo = {"input": {"package": "lodash", "ecosystem": "npm"},
            "truth": {"repository_github": "lodash/lodash", "latest_release_tag": "4.18.1", "github_releases": True}}
    assert g.case_arguments("github-releases", repo) == {"repo": "lodash/lodash"} and g.applies("github-releases", repo)
    assert g.judge("github-releases", repo, {"answer": "x", "latest_tag": "4.18.1"})["pass"]
    assert not g.judge("github-releases", repo, {"answer": "x", "latest_tag": "4.17.0"})["pass"]
    none = {"input": {}, "truth": {"repository_github": "a/b", "latest_release_tag": None, "github_releases": False}}
    assert g.judge("github-releases", none, {"answer": "a/b: no GitHub releases published (tags may still exist)."})["pass"]
    assert not g.judge("github-releases", none, {"answer": "a/b: recent releases", "latest_tag": "v1"})["pass"]
    assert not g.applies("github-releases", {"input": {}, "truth": {"repository_github": None}})


def test_gold_judge_for_gdelt_news():
    """workflow 11-15 (36fe030f): news seat; fresh, linked and on-topic items, judged against the clock."""
    from datetime import datetime, timedelta, timezone
    from agent_market.fallback_agents import gold_check as g
    case = {"input": {"topic": "Wind power"}, "truth": {}}
    assert g.SLUG["gdelt-news"] == "topic-evidence-brief" and g.applies("gdelt-news", case)
    assert g.case_arguments("gdelt-news", case) == {"query": "Wind power"}
    day = lambda n: (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = [{"title": "Offshore wind power auction", "url": "https://n/1", "published": day(1)},
             {"title": "Grid news", "url": "https://n/2", "published": day(2)},
             {"title": "Energy prices", "url": "https://n/3", "published": day(3)}]
    assert g.judge("gdelt-news", case, {"items": items, "source": "x"})["pass"]
    assert not g.judge("gdelt-news", case, {"items": items[1:], "source": "x"})["pass"]                 # 2 items, none on topic
    old = [{**i, "published": day(20)} for i in items]
    assert not g.judge("gdelt-news", case, {"items": old, "source": "x"})["pass"]


def test_software_incident_keeps_every_patched_branch(tmp_path):
    """workflow 3737c5aa: the cve fix truth lists every patched branch of a package (log4j-core 2.15.0 and 2.12.2)."""
    from agent_market.fallback_agents import gold_check as g
    log4j = {"ecosystem": "maven", "name": "org.apache.logging.log4j:log4j-core"}
    row = dict(GH_ROW, vulnerabilities=[{"package": log4j, "first_patched_version": "2.15.0"},
                                        {"package": log4j, "first_patched_version": "2.12.2"},
                                        {"package": log4j, "first_patched_version": None},
                                        {"package": {"ecosystem": "maven", "name": "x:y"}, "first_patched_version": None}])
    a, _ = agents(tmp_path, {"https://api.github.com/advisories": httpx.Response(200, json=[row])}, [])
    out = a.execute("software-incident", {"query": "CVE-2021-44228"})["result"]
    assert out["packages"] == [dict(log4j, first_patched_version="2.15.0"), dict(log4j, first_patched_version="2.12.2"),
                               {"ecosystem": "maven", "name": "x:y"}]
    truth = {"fixes": [dict(log4j, first_patched_version="2.15.0"), dict(log4j, first_patched_version="2.12.2")]}
    assert g.judge("software-incident", {"input": {"cve_id": "CVE-2021-44228"}, "truth": truth}, out)["pass"]


def test_owned_data_agents_name_a_source_license_or_leave_it_empty():
    """PM 11-15 16:52/17:02: each owned data agent has its source license (name and https address) or None when no
    license was found, kept in source_terms.py so the research/news adapter digest does not move."""
    from agent_market.owned_data_agents.catalog import SPECS
    from agent_market.owned_data_agents import docs
    from agent_market.owned_data_agents.source_terms import LICENSES, SUSPENDED
    assert set(LICENSES) == set(SPECS) | {docs.ID} and len(LICENSES) == 8
    for agent_id, value in LICENSES.items():
        assert value is None or "(https://" in value, agent_id
    assert "gdeltproject.org" in LICENSES["technology-news"] and SUSPENDED == {}   # GDELT since 11-16
    assert "Context7" not in LICENSES["technical-docs"]
    assert all("license" not in spec for spec in SPECS.values()) and "license" not in docs.SPEC


def test_suspended_owned_agent_answers_without_calling_its_source(monkeypatch):
    """PM 11-15 17:02: a suspended owned agent answers its notice without calling the source; tools/list unchanged.
    (technology-news was suspended for the Hacker News terms and reads GDELT since 11-16; the mechanism stays.)"""
    from fastapi.testclient import TestClient
    from agent_market.owned_data_agents import source_terms
    from agent_market.owned_data_agents.catalog import tool_spec
    from agent_market.owned_data_agents.engine import DataAgents
    from agent_market.owned_data_agents.service import create_app

    monkeypatch.setitem(source_terms.SUSPENDED, "technology-news", "This agent is suspended (test).")

    class NoCalls(DataAgents):
        def execute(self, agent_id, arguments):
            raise AssertionError("the source must not be called")
    with TestClient(create_app(enabled=True, engine=NoCalls())) as client:
        path = "/api/owned-data-agents/technology-news/mcp"
        listed = client.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).json()
        assert listed["result"]["tools"] == [tool_spec("technology-news")]
        called = client.post(path, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "search_technology_news", "arguments": {"query": "ai", "limit": 1}}}).json()
        assert called["result"]["isError"] is True and "suspended" in called["result"]["content"][0]["text"]


def test_sole_member_substitutes_are_probed_and_alert_at_once(tmp_path):
    """PM 11-16 06:4x: a required slot whose only usable member is ours stops whole when it fails; one probe an hour,
    an alert on the first failure, and a refused ledger reservation is 'unprobed', never a failure."""
    from agent_market.fallback_agents import watch as w
    from agent_market.fallback_agents.agents import FallbackUnavailable
    defs = tmp_path / "defs"
    defs.mkdir()
    (defs / "x.json").write_text(json.dumps({"slug": "x", "status": "candidate", "slots": [
        {"slot": "web", "required": True, "chain": [
            {"kind": "external", "resource_id": 50972, "tool": "t"},                       # prohibits in the table
            {"kind": "agentcon", "agent_id": "wiki-grounding", "tool": "t", "state": "planned"}]},
        {"slot": "papers", "required": True, "chain": [
            {"kind": "external", "resource_id": 999999, "tool": "t", "state": "active",
             "terms": {"status": "allowed", "source": "https://x.test/terms"}},
            {"kind": "agentcon", "agent_id": "arxiv-search", "tool": "t"}]},
        {"slot": "news", "required": False, "chain": [{"kind": "agentcon", "agent_id": "gdelt-news", "tool": "t"}]}]}))
    assert w.sole_members(defs) == {"wiki-grounding": ["x/web"]}
    assert w.probe_input("wiki-grounding") is not None

    class Down:
        def execute(self, agent_id, arguments):
            raise FallbackUnavailable("source_unavailable", "down")

    class Busy:
        def execute(self, agent_id, arguments):
            raise FallbackUnavailable("rate_limited", "ledger")
    assert w.probe("wiki-grounding", {"question": "q"}, make=Down) == "source_unavailable"
    assert w.probe("wiki-grounding", {"question": "q"}, make=Busy) == "unprobed"
    line = w.observe({}, tmp_path, 1_800_000_000.0, None, {"wiki-grounding": ("source_unavailable", ["x/web"])})
    assert any(a["key"] == "sole_member_failing:wiki-grounding" for a in line["alerts"])
    assert line["agents"]["wiki-grounding"]["probe"] == "source_unavailable"
    line = w.observe({}, tmp_path, 1_800_000_000.0, None, {"wiki-grounding": ("ok", ["x/web"])})
    assert not any(a["key"].startswith("sole_member") for a in line["alerts"])


def test_sec_company_profile_describes_the_filer_from_its_registration(tmp_path):
    """workflow 11-16 (company-due-diligence v2 background): company.profile.v1 (PM 11-16) from SEC submissions, said to be
    a filing profile and not an encyclopedia article; CIK, exact name or ticker; a shared name is not guessed."""
    from agent_market.fallback_agents import gold_check as g
    subs = {"cik": 320193, "name": "Apple Inc.", "sic": "3571", "sicDescription": "Electronic Computers",
            "stateOfIncorporation": "CA", "stateOfIncorporationDescription": "CA", "tickers": ["AAPL"],
            "exchanges": ["Nasdaq"], "addresses": {"business": {"city": "CUPERTINO", "stateOrCountryDescription": "CA"}}}
    tickers = {str(i): {"cik_str": 900000 + i, "ticker": f"T{i}", "title": f"Filler Company {i} Inc"} for i in range(1200)}
    tickers["a"] = {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
    tickers["b"] = {"cik_str": 1, "ticker": "TWA", "title": "Twin Co"}
    tickers["c"] = {"cik_str": 2, "ticker": "TWB", "title": "Twin Co"}
    a, _ = agents(tmp_path, {"https://data.sec.gov/submissions/CIK0000320193.json": httpx.Response(200, json=subs),
                             "https://www.sec.gov/files/company_tickers.json": httpx.Response(200, json=tickers)})
    for title in ("CIK 320193", "0000320193", "Apple Inc.", "apple", "AAPL"):
        out = a.execute("sec-company-profile", {"company": title})["result"]
        assert out["title"] == "Apple Inc." and "(SEC CIK 320193)" in out["summary"], title
    assert "Electronic Computers (SIC 3571)" in out["summary"] and "Cupertino, CA" in out["summary"]
    assert out["summary"].endswith("Company profile from SEC EDGAR filings (not an encyclopedia article).")
    assert "not an encyclopedia article" in out["source"]
    for title, code in (("Twin Co", "not_found"), ("Nobody Here Corp", "not_found"), ("a|b", "invalid_input")):
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("sec-company-profile", {"company": title})
        assert err.value.code == code, title
    case = {"truth": {"cik": "320193", "sec_title": "APPLE INC."}}
    assert g.SLUG["sec-company-profile"] == "company-due-diligence" and g.applies("sec-company-profile", case)
    assert g.case_arguments("sec-company-profile", case) == {"company": "CIK 320193"}
    assert out["cik"] == "320193" and out["industry"] == "Electronic Computers" and out["tickers"] == ["AAPL"]
    assert g.judge("sec-company-profile", case, out)["pass"]


def test_census_match_with_another_zip_code_is_not_the_address():
    """us-street 11-16: the State House address matched the same street in another ZIP code, 12 km away."""
    from agent_market.fallback_agents.agents import same_street
    assert not same_street("24 Beacon St, Boston, MA 02133, USA", "24 BEACON ST, BOSTON, MA, 02136")
    assert same_street("24 Beacon St, Boston, MA 02133, USA", "24 BEACON ST, BOSTON, MA, 02133")
    assert same_street("1600 Pennsylvania Avenue NW, Washington, DC", "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500")
    assert not same_street("2301 North Highland Avenue, Los Angeles, CA 90068", "2301 HIGHLAND DR, LOS ANGELES, CA, 90016")


def test_wikipedia_summary_falls_back_to_a_search_with_the_same_title_words(tmp_path):
    """company v2 11-16 (workflow): exact titles are case- and punctuation-exact, so "Bjs Restaurants" missed
    "BJ's Restaurants"; one title search then takes only an article with the same title up to case and punctuation."""
    from agent_market.fallback_agents.agents import title_words
    calls = []

    def handler(request):
        url = str(request.url)
        calls.append(url)
        if "generator=prefixsearch" in url:
            return httpx.Response(200, json={"query": {"pages": [
                {"index": 1, "pageid": 9, "title": "BJ's Wholesale Club", "fullurl": "https://en.wikipedia.org/wiki/BJ%27s_Wholesale_Club",
                 "extract": "BJ's Wholesale Club is a warehouse club chain."},
                {"index": 2, "pageid": 7, "title": "BJ's Restaurants", "fullurl": "https://en.wikipedia.org/wiki/BJ%27s_Restaurants",
                 "extract": "BJ's Restaurants, Inc. is an American restaurant chain."}]}})
        return httpx.Response(200, json={"query": {"pages": [{"title": "Bjs Restaurants", "missing": True}]}})
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": handler})
    out = a.execute("wikipedia-summary", {"title": "Bjs Restaurants"})["result"]
    assert out["title"] == "BJ's Restaurants" and "restaurant chain" in out["summary"]
    assert len(calls) == 2 and "titles=Bjs+Restaurants" in calls[0] and "gpssearch=Bjs+Restaurants" in calls[1]
    with pytest.raises(FallbackUnavailable) as err:                 # no title with the asked words: still not found
        a.execute("wikipedia-summary", {"title": "Qwzx Restaurants"})
    assert err.value.code == "not_found"
    assert title_words("BJ\u2019s Restaurants") == title_words("Bjs restaurants") == ["bjs", "restaurants"]


def test_wikipedia_summary_takes_the_same_title_before_a_longer_one(tmp_path):
    """company v2 11-16: SEC names arrive in capitals ("DEXCOM"); the exact title misses and the title search lists
    "Dexcom CGM" before "Dexcom": the same title wins."""
    def handler(request):
        if "generator=prefixsearch" in str(request.url):
            return httpx.Response(200, json={"query": {"pages": [
                {"index": 1, "pageid": 2, "title": "Dexcom CGM", "fullurl": "https://en.wikipedia.org/wiki/Dexcom_CGM",
                 "extract": "Dexcom CGM is a glucose monitor."},
                {"index": 2, "pageid": 1, "title": "Dexcom", "fullurl": "https://en.wikipedia.org/wiki/Dexcom",
                 "extract": "Dexcom, Inc. is an American healthcare company."}]}})
        return httpx.Response(200, json={"query": {"pages": [{"title": "DEXCOM", "missing": True}]}})
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": handler})
    assert a.execute("wikipedia-summary", {"title": "DEXCOM"})["result"]["title"] == "Dexcom"


def test_wikipedia_summary_never_answers_with_a_longer_title(tmp_path):
    """PM 11-16: a short general title must not land on another subject ("Nope" -> "Nope (band)", "Mercury" ->
    "Mercury Records"); only the same title up to case and punctuation is taken."""
    def handler(request):
        params = request.url.params
        if "gpssearch" in params:
            word = params["gpssearch"]
            return httpx.Response(200, json={"query": {"pages": [
                {"index": 1, "pageid": 11, "title": f"{word} (band)", "fullurl": f"https://en.wikipedia.org/wiki/{word}_(band)",
                 "extract": f"{word} are a rock band."},
                {"index": 2, "pageid": 12, "title": f"{word} Records", "fullurl": f"https://en.wikipedia.org/wiki/{word}_Records",
                 "extract": f"{word} Records is a record label."}]}})
        if params["titles"] == "Mercury":
            return httpx.Response(200, json={"query": {"pages": [
                {"title": "Mercury", "pageprops": {"disambiguation": ""}, "extract": "Mercury may refer to:"}]}})
        return httpx.Response(200, json={"query": {"pages": [{"title": params["titles"], "missing": True}]}})
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": handler})
    for title in ("Nope", "Mercury"):
        with pytest.raises(FallbackUnavailable) as err:
            a.execute("wikipedia-summary", {"title": title})
        assert err.value.code == "not_found", title


def test_wikipedia_summary_gold_counts_not_found_right_for_a_company_without_an_article():
    """holdout-r5-wiki 11-16 (workflow): truth.wiki_article False means not_found is the right answer; an article
    there is wrong; companies and topics with an article are graded on the title as before."""
    from agent_market.fallback_agents import gold_check as g
    none = {"truth": {"wiki_article": False, "wiki": None}}
    assert g.judge("wikipedia-summary", none, None, "not_found")["pass"] is True
    assert g.judge("wikipedia-summary", none, None, "source_unavailable")["pass"] is False
    assert g.judge("wikipedia-summary", none, {"title": "Grayscale"})["pass"] is False
    has = {"truth": {"wiki_article": True, "wiki": {"title": "Dexcom"}}}
    assert g.judge("wikipedia-summary", has, {"title": "Dexcom"})["pass"] is True
    assert g.judge("wikipedia-summary", has, None, "not_found")["pass"] is False
    topic = {"truth": {"wiki": {"title": "Telehealth"}}}
    assert g.judge("wikipedia-summary", topic, {"title": "Telehealth"})["pass"] is True
def test_a_bug_of_ours_is_internal_error_and_a_bad_source_answer_stays_source_unavailable(tmp_path):
    """PM 11-16 source review: KeyError/TypeError in our parsing read as source_unavailable; now internal_error with
    the exception type in the usage line, and the watch alerts at the first one. A broken answer (ValueError) and an
    HTTP failure stay source_unavailable."""
    from agent_market.fallback_agents import watch as w
    from agent_market.fallback_agents.agents import failure_code
    from agent_market.fallback_agents.limits import SourceBusy
    from agent_market.fallback_agents.net import SourceError
    assert failure_code(KeyError("x")) == failure_code(TypeError()) == failure_code(AttributeError()) == "internal_error"
    assert failure_code(ValueError("bad json")) == failure_code(SourceError("down")) == "source_unavailable"
    assert failure_code(SourceBusy("pause")) == "rate_limited"
    a, _ = agents(tmp_path, {"https://en.wikipedia.org/w/api.php": httpx.Response(200, json={"query": {"pages": [
        {"title": "X", "extract": None, "fullurl": 7}]}})})
    a._wikipedia_summary = lambda args, remaining: a._cached(("k",), (1, 1), lambda rem: {}["missing"], remaining)
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("wikipedia-summary", {"title": "X"})
    assert err.value.code == "internal_error" and "not the source" in str(err.value)
    line = json.loads((tmp_path / "usage").glob("*.jsonl").__next__().read_text().splitlines()[-1])
    assert line["code"] == "internal_error" and line["exception"] == "KeyError"
    import time as _time
    watched = w.observe({}, tmp_path, _time.time() + 5, None)
    assert any(x["key"] == "internal_error:wikipedia-summary" for x in watched["alerts"])


def test_cve_checks_apply_to_the_cve_contracts_only():
    from agent_market.fallback_agents.agents import contract_check
    with pytest.raises(FallbackUnavailable):
        contract_check("cve.record.v1", {"cve_id": "CVE-2021-1"}, {"cve_id": "CVE-2021-2"})
    with pytest.raises(FallbackUnavailable):
        contract_check("cve.record.v1", {"cve_id": "CVE-2021-1"}, {"cve_id": "CVE-2021-1", "cvss_score": 5.0})
    with pytest.raises(FallbackUnavailable):
        contract_check("cve.exploited.v1", {"cve_id": "CVE-2021-1"}, {"cve_id": "CVE-2021-9"})
    contract_check("encyclopedia.summary.v1", {"title": "x"}, {"title": "y", "cvss_score": 1})   # not a CVE contract

def test_gold_judge_for_mcp_registry():
    """agent team 11-16: listed false for a made-up name; a listed server needs the same name and the frozen version
    or a later publish."""
    from agent_market.fallback_agents.gold_check import judge
    absent = {"truth": {"listed": False}}
    assert judge("mcp-registry", absent, {"listed": False, "source": "x"})["pass"]
    assert not judge("mcp-registry", absent, {"listed": True, "name": "a/b", "source": "x"})["pass"]
    case = {"truth": {"listed": True, "name": "io.github.a/b", "version": "1.2.0", "published_at": "2026-11-01T00:00:00Z"}}
    hit = {"listed": True, "name": "io.github.a/b", "version": "1.2.0", "published_at": "2026-11-01T00:00:00Z", "source": "x"}
    assert judge("mcp-registry", case, hit)["pass"]
    assert judge("mcp-registry", case, {**hit, "version": "1.3.0", "published_at": "2026-11-17T00:00:00Z"})["pass"]
    assert not judge("mcp-registry", case, {**hit, "version": "1.1.0", "published_at": "2026-10-01T00:00:00Z"})["pass"]
    assert not judge("mcp-registry", case, {**hit, "name": "io.github.a/other"})["pass"]


def test_gold_judge_for_met_weather_against_nws_hours():
    """PM 11-16: met-weather's temperature against the NWS hour that contains its time, within 3 C."""
    from agent_market.fallback_agents.gold_check import judge
    case = {"truth": {"tolerance_c": 3.0, "nws_hourly": [
        {"start": "2026-11-17T08:00:00-05:00", "end": "2026-11-17T09:00:00-05:00", "temp_c": 5.0},
        {"start": "2026-11-17T09:00:00-05:00", "end": "2026-11-17T10:00:00-05:00", "temp_c": 6.0}]}}
    met = {"temperature_c": 7.4, "time": "2026-11-17T14:00:00Z", "source": "Based on data from MET Norway (CC BY 4.0)"}
    assert judge("met-weather", case, met)["pass"]                       # 14:00Z = 09:00-05:00, gap 1.4
    assert not judge("met-weather", case, {**met, "temperature_c": 10.5})["pass"]
    assert not judge("met-weather", case, {**met, "time": "2026-11-17T20:00:00Z"})["pass"]   # outside the frozen hours


def test_gold_met_weather_builder_keeps_celsius_hours():
    from scripts.gold_met_weather import POINTS, build
    pages = {"https://api.weather.gov/points/40.7128,-74.0060": {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly"}},
             "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly": {"properties": {"periods": [
                 {"startTime": "2026-11-17T08:00:00-05:00", "endTime": "2026-11-17T09:00:00-05:00", "temperature": 41, "temperatureUnit": "F"}]}}}
    cases = build(lambda url: pages[url], POINTS[:1])
    saved = build(lambda url: pages[url], POINTS[:1], grids={"New York, NY": "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly"})
    assert saved == cases                                  # the saved addresses give the same set, one call a point
    assert cases[0]["input"] == {"city": "New York, NY", "latitude": 40.7128, "longitude": -74.006}
    assert cases[0]["truth"]["nws_hourly"][0]["temp_c"] == 5.0 and len(POINTS) >= 30

def test_sun_times_agent_computes_without_a_network_call(tmp_path):
    """sun.times.v1 (workflow 11-16): no outside call; times in the place's own zone from the offline grid, the date
    read as that zone's calendar date; UTC with a note where the grid gives no single zone; polar days are answers."""
    from datetime import datetime, timezone
    calls = []
    clock = Clock()
    bare = FallbackAgents(http=client({}, calls), data_dir=tmp_path / "none", clock=clock, limiters=limiters(clock, clock.sleep))
    out = bare.execute("sun-times", {"latitude": 51.5074, "longitude": -0.1278, "date": "2024-06-21"})["result"]
    assert out["polar"] == "none" and out["timezone"] == "UTC" and out["sunrise"] == "2024-06-21T03:43:00Z"
    assert "sunrise 03:43 UTC" in out["answer"] and "Times in UTC (time zone not certain)." in out["answer"]

    write_tz_grid(tmp_path / "tz-grid.bin")
    a = FallbackAgents(http=client({}, calls), data_dir=tmp_path, clock=clock, limiters=limiters(clock, clock.sleep),
                       utc_now=lambda: datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc))
    seoul = a.execute("sun-times", {"latitude": 37.5665, "longitude": 126.978, "date": "2026-11-20"})["result"]
    assert seoul["timezone"] == "Asia/Seoul" and seoul["sunrise"] == "2026-11-20T07:17:00+09:00"
    assert "sunrise 07:17 KST" in seoul["answer"] and "(Asia/Seoul)" in seoul["answer"]
    today = a.execute("sun-times", {"location": "37.5665,126.978"})["result"]
    assert today["date"] == "2026-11-20"           # 20:00 UTC on the 19th is the 20th in Seoul
    border = a.execute("sun-times", {"latitude": 45.0, "longitude": 8.0, "date": "2026-11-20"})["result"]
    assert border["timezone"] == "UTC" and "time zone not certain" in border["answer"]
    polar = bare.execute("sun-times", {"location": "69.6492,18.9553", "date": "2024-12-21"})["result"]
    assert polar["polar"] == "always_down" and "sunrise" not in polar and polar["day_length_minutes"] == 0
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("sun-times", {"location": "Seoul"})
    assert err.value.code == "invalid_input" and calls == []


def test_site_reachability_agent_reports_status_and_final_address(tmp_path):
    """site.reachability.v1 (workflow 11-16): one GET, redirects hop by hop, the domain echoed in the answer."""
    a, _ = agents(tmp_path, {"https://python.org/": httpx.Response(301, headers={"location": "https://www.python.org/"}),
                             "https://www.python.org/": httpx.Response(200, text="ok")})
    out = a.execute("site-reachability", {"domain": "python.org"})["result"]
    assert out["reachable"] is True and out["status"] == 200 and out["final_url"] == "https://www.python.org/"
    assert out["redirects"] == 1 and "python.org answered HTTP 200" in out["answer"]
    down, _ = agents(tmp_path, {"https://example.com/": httpx.Response(503)})
    out = down.execute("site-reachability", {"url": "https://example.com/"})["result"]
    assert out["reachable"] is False and out["status"] == 503
    with pytest.raises(FallbackUnavailable):
        a.execute("site-reachability", {"domain": "localhost"})


def test_gold_judge_for_mcp_registry():
    """agent team 11-16: listed false for a made-up name; a listed server needs the same name and the frozen version
    or a later publish."""
    from agent_market.fallback_agents.gold_check import judge
    absent = {"truth": {"listed": False}}
    assert judge("mcp-registry", absent, {"listed": False, "source": "x"})["pass"]
    assert not judge("mcp-registry", absent, {"listed": True, "name": "a/b", "source": "x"})["pass"]
    case = {"truth": {"listed": True, "name": "io.github.a/b", "version": "1.2.0", "published_at": "2026-11-01T00:00:00Z"}}
    hit = {"listed": True, "name": "io.github.a/b", "version": "1.2.0", "published_at": "2026-11-01T00:00:00Z", "source": "x"}
    assert judge("mcp-registry", case, hit)["pass"]
    assert judge("mcp-registry", case, {**hit, "version": "1.3.0", "published_at": "2026-11-17T00:00:00Z"})["pass"]
    assert not judge("mcp-registry", case, {**hit, "version": "1.1.0", "published_at": "2026-10-01T00:00:00Z"})["pass"]
    assert not judge("mcp-registry", case, {**hit, "name": "io.github.a/other"})["pass"]


def test_gold_judge_for_met_weather_against_nws_hours():
    """PM 11-16: met-weather's temperature against the NWS hour that contains its time, within 3 C."""
    from agent_market.fallback_agents.gold_check import judge
    case = {"truth": {"tolerance_c": 3.0, "nws_hourly": [
        {"start": "2026-11-17T08:00:00-05:00", "end": "2026-11-17T09:00:00-05:00", "temp_c": 5.0},
        {"start": "2026-11-17T09:00:00-05:00", "end": "2026-11-17T10:00:00-05:00", "temp_c": 6.0}]}}
    met = {"temperature_c": 7.4, "time": "2026-11-17T14:00:00Z", "source": "Based on data from MET Norway (CC BY 4.0)"}
    assert judge("met-weather", case, met)["pass"]                       # 14:00Z = 09:00-05:00, gap 1.4
    assert not judge("met-weather", case, {**met, "temperature_c": 10.5})["pass"]
    assert not judge("met-weather", case, {**met, "time": "2026-11-17T20:00:00Z"})["pass"]   # outside the frozen hours


def test_gold_met_weather_builder_keeps_celsius_hours():
    from scripts.gold_met_weather import POINTS, build
    pages = {"https://api.weather.gov/points/40.7128,-74.0060": {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly"}},
             "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly": {"properties": {"periods": [
                 {"startTime": "2026-11-17T08:00:00-05:00", "endTime": "2026-11-17T09:00:00-05:00", "temperature": 41, "temperatureUnit": "F"}]}}}
    cases = build(lambda url: pages[url], POINTS[:1])
    saved = build(lambda url: pages[url], POINTS[:1], grids={"New York, NY": "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly"})
    assert saved == cases                                  # the saved addresses give the same set, one call a point
    assert cases[0]["input"] == {"city": "New York, NY", "latitude": 40.7128, "longitude": -74.006}
    assert cases[0]["truth"]["nws_hourly"][0]["temp_c"] == 5.0 and len(POINTS) >= 30



# ---------------------------------------------------------------- dns-spf-dmarc (agent team 11-17)
def _dns_answer(ident, records, rcode=0, truncated=False):
    import struct
    q = b"".join(bytes([len(p)]) + p.encode() for p in "example.com".split(".")) + b"\x00" + struct.pack(">HH", 16, 1)
    flags = 0x8180 | rcode | (0x0200 if truncated else 0)
    out = struct.pack(">HHHHHH", ident, flags, 1, len(records), 0, 0) + q
    for rec in records:
        chunks = [rec[i:i + 255].encode() for i in range(0, len(rec), 255)] or [b""]
        data = b"".join(bytes([len(c)]) + c for c in chunks)
        out += b"\xc0\x0c" + struct.pack(">HHIH", 16, 1, 300, len(data)) + data
    return out


def test_dns_txt_reads_answers_joins_long_strings_and_retries_truncated_over_tcp():
    from agent_market.fallback_agents import dns_txt
    long_spf = "v=spf1 " + "include:_spf.example.net " * 15 + "-all"         # over 255 bytes: two strings
    seen = []
    def udp(packet, server, family, timeout):
        seen.append("udp")
        return _dns_answer(int.from_bytes(packet[:2], "big"), [], truncated=True)
    def tcp(packet, server, family, timeout):
        seen.append("tcp")
        return _dns_answer(int.from_bytes(packet[:2], "big"), [long_spf, "google-site-verification=x"])
    assert dns_txt.txt("example.com", server="192.0.2.53", udp=udp, tcp=tcp) == [long_spf, "google-site-verification=x"]
    assert seen == ["udp", "tcp"]
    nx = lambda packet, *a: _dns_answer(int.from_bytes(packet[:2], "big"), [], rcode=3)
    assert dns_txt.txt("missing.example.com", server="192.0.2.53", udp=nx) == []
    with pytest.raises(dns_txt.DnsError):
        dns_txt.txt("x.example.com", server="192.0.2.53", udp=lambda packet, *a: _dns_answer(1 ^ int.from_bytes(packet[:2], "big"), []))
    with pytest.raises(dns_txt.DnsError):
        dns_txt.txt("x.example.com", server="192.0.2.53", udp=lambda packet, *a: _dns_answer(int.from_bytes(packet[:2], "big"), [], rcode=2))


def test_mail_auth_agent_quotes_spf_and_dmarc_and_names_what_is_missing(tmp_path):
    a, _ = agents(tmp_path, {})
    records = {"example.org": ["v=spf1 include:_spf.google.com ~all", "google-site-verification=abc"],
               "_dmarc.example.org": ["v=DMARC1; p=quarantine; rua=mailto:d@example.org"],
               "bare.example.org": ["some other text"], "_dmarc.bare.example.org": []}
    asked = []
    a.dns_txt = lambda name, timeout: asked.append(name) or records.get(name, [])
    env = a.execute("dns-spf-dmarc", {"domain": "https://Example.org/path", "record_type": "TXT"})
    assert asked == ["example.org", "_dmarc.example.org"]
    answer = env["result"]["answer"]
    assert "v=spf1 include:_spf.google.com ~all" in answer and "policy quarantine" in answer
    assert "DKIM is not checked" in answer and "google-site-verification" not in answer
    env = a.execute("dns-spf-dmarc", {"domain": "bare.example.org"})
    assert "no SPF record published" in env["result"]["answer"] and "no DMARC record published" in env["result"]["answer"]
    a.execute("dns-spf-dmarc", {"domain": "example.org"})
    assert asked.count("example.org") == 1                                  # cached
    for bad in ("localhost", "10.0.0.1", "intranet", "x.local"):
        with pytest.raises(FallbackUnavailable):
            a.execute("dns-spf-dmarc", {"domain": bad})


def test_mail_auth_agent_reports_two_spf_records_as_invalid(tmp_path):
    a, _ = agents(tmp_path, {})
    a.dns_txt = lambda name, timeout: ["v=spf1 a -all", "v=spf1 mx -all"] if not name.startswith("_dmarc") else []
    answer = a.execute("dns-spf-dmarc", {"domain": "double.example.org"})["result"]["answer"]
    assert "2 SPF records (invalid: only one is allowed)" in answer

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
    assert set(SPECS) == {"nvd-cve", "cve-org", "cisa-kev", "github-advisory", "package-registry", "depsdev-package", "gleif-lei", "sec-edgar"}
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
        "https://api.deps.dev/v3/projects/github.com%2Flodash%2Flodash": httpx.Response(200, json={
            "scorecard": {"date": "2026-08-24T00:00:00Z", "overallScore": 7.5}} if scorecard else {}),
    }
    return routes


def test_depsdev_agent_reports_default_version_repo_and_scorecard(tmp_path):
    a, _ = agents(tmp_path, depsdev_routes())
    env = a.execute("depsdev-package", {"package": "lodash", "ecosystem": "npm"})
    assert env["result"] == {"latest_version": "4.18.1", "deprecated": False, "source": "deps.dev; OpenSSF Scorecard",
                             "released_at": "2026-04-01T21:01:20Z", "repository": "https://github.com/lodash/lodash",
                             "scorecard": 7.5}
    assert env["freshness"]["data_as_of"]["OpenSSF Scorecard"] == "2026-08-24T00:00:00Z"
    assert env["sources"][0]["license"].startswith("Generated data CC BY 4.0")


def test_depsdev_agent_without_scorecard_keeps_version_facts(tmp_path):
    routes = depsdev_routes(scorecard=False)
    a, _ = agents(tmp_path, routes)
    out = a.execute("depsdev-package", {"package": "lodash", "ecosystem": "npm"})["result"]
    assert "scorecard" not in out and out["source"] == "deps.dev" and out["latest_version"] == "4.18.1"
    del routes["https://api.deps.dev/v3/projects/github.com%2Flodash%2Flodash"]
    routes["https://api.deps.dev/v3/projects/"] = httpx.Response(500)
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
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("gleif-lei", {"name": "Apple"})
    assert err.value.code == "not_found"


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

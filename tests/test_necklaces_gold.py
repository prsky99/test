import io
import json
import urllib.error

import pytest

from agent_market.necklaces import gold


class FakeFetcher:
    """Answers the public endpoints from canned data; records every call."""

    def __init__(self, nvd_fails=lambda cid: False):
        self.calls = 0
        self.urls = []
        self.nvd_fails = nvd_fails

    def json(self, url, body=None):
        self.calls += 1
        self.urls.append(url)
        if url.startswith("https://registry.npmjs.org/"):
            return {"version": "9.9.9"}
        if url.startswith("https://pypi.org/pypi/"):
            return {"info": {"version": "9.9.9"}}
        if url == "https://api.osv.dev/v1/query":
            name, version = body["package"]["name"], body.get("version")
            if version is None:
                return {"vulns": [{"id": f"GHSA-{name}", "aliases": [f"CVE-2020-{abs(hash(name)) % 9000 + 1000}"],
                                   "affected": [{"package": {"name": name}, "versions": ["1.0.0", "1.1.0", "1.2.0"]}]}]}
            if version == "9.9.9":
                return {}
            return {"vulns": [{"id": f"GHSA-{name}", "aliases": [f"CVE-2020-{abs(hash(name)) % 9000 + 1000}"]}]}
        if "known_exploited_vulnerabilities" in url:
            return {"vulnerabilities": [{"cveID": f"CVE-{2015 + i % 9}-{10000 + i}", "dateAdded": f"{2021 + i % 4}-01-01"}
                                        for i in range(200)]}
        if url.startswith("https://api.first.org/"):
            ids = url.split("cve=")[1].split(",")
            return {"data": [{"cve": c, "epss": "0.5"} for c in ids]}
        if url.startswith("https://services.nvd.nist.gov/"):
            cid = url.split("cveId=")[1]
            if self.nvd_fails(cid):
                return None
            return {"vulnerabilities": [{"cve": {"published": "2021-01-01", "metrics": {"cvssMetricV31": [
                {"type": "Primary", "cvssData": {"baseScore": 9.8, "version": "3.1"}}]}}}]}
        if url.startswith("https://raw.githubusercontent.com/CVEProject/"):
            return {"cveMetadata": {"datePublished": "2021"},
                    "containers": {"cna": {"metrics": [{"cvssV3_1": {"baseScore": 7.5, "version": "3.1"}}]}}}
        raise AssertionError(url)


def test_fold_merges_aliases():
    items = gold.fold([{"id": "GHSA-1", "aliases": ["CVE-2021-1", "PYSEC-1"]}, {"id": "GHSA-0"}])
    assert items == [{"id": "GHSA-0", "ids": ["GHSA-0"]}, {"id": "GHSA-1", "ids": ["CVE-2021-1", "GHSA-1", "PYSEC-1"]}]


def test_pick_affected_version_prefers_listed_versions_then_introduced():
    listed = [{"id": "A", "affected": [{"package": {"name": "x"}, "versions": ["1", "2", "3"]}]}]
    assert gold.pick_affected_version(listed, "x") == "2"
    ranged = [{"id": "A", "affected": [{"package": {"name": "x"}, "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2"}]}]}]},
              {"id": "B", "affected": [{"package": {"name": "x"}, "ranges": [{"events": [{"introduced": "1.4"}]}]}]}]
    assert gold.pick_affected_version(ranged, "x") == "1.4"
    assert gold.pick_affected_version(listed, "other") is None


def test_split_is_disjoint_stratified_and_deterministic():
    cases = [{"case_id": f"c{i}", "stratum": "a" if i % 7 < 4 else "b"} for i in range(103)]
    first, again = gold.split(cases), gold.split(list(reversed(cases)))
    assert first == again
    ids = [c["case_id"] for name in gold.SPLITS for c in first[name]]
    assert len(ids) == len(set(ids)) == 90
    for name in gold.SPLITS:
        strata = [c["stratum"] for c in first[name]]
        assert len(strata) == 30
    counts = [[c["stratum"] for c in first[name]].count("a") for name in gold.SPLITS]
    assert max(counts) - min(counts) <= 1


def test_build_writes_three_files_and_manifest(tmp_path):
    fake = FakeFetcher(nvd_fails=lambda cid: cid.endswith("0"))
    result = gold.build(tmp_path, ["package-risk-audit", "cve-incident-brief"], fetcher=fake, raw_dir=tmp_path / "raw")
    for slug in ("package-risk-audit", "cve-incident-brief"):
        folder = tmp_path / "gold" / slug
        manifest = json.loads((folder / "manifest.json").read_text())
        assert set(manifest["files"]) == set(gold.SPLITS)
        for name in gold.SPLITS:
            rows = [json.loads(line) for line in (folder / f"{name}.jsonl").read_text().splitlines()]
            assert len(rows) == manifest["files"][name]["cases"] == 30
            assert all(r["task_type"] == "same_role" and r["truth_sources"] for r in rows)
    pkg = json.loads((tmp_path / "raw" / "package-cases.json").read_text())
    assert {c["stratum"] for c in pkg} == {"vulnerable", "clean"}
    cves = json.loads((tmp_path / "raw" / "cve-cases.json").read_text())
    assert {c["stratum"] for c in cves} == {"kev", "not_kev"}
    sources = {c["truth"]["cvss"]["source"] for c in cves if c["case_id"].endswith("0")}
    assert sources == {"cvelistV5"}
    assert {c["truth"]["cvss"]["source"] for c in cves if not c["case_id"].endswith("0")} == {"NVD"}
    assert result["calls"] == fake.calls


def test_fetcher_backs_off_on_429_and_gives_up_on_404(monkeypatch):
    slept = []
    responses = [urllib.error.HTTPError("u", 429, "slow", {"Retry-After": "3"}, None),
                 io.BytesIO(b'{"ok": true}')]

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        assert req.get_header("User-agent") == gold.USER_AGENT
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return Resp(item.getvalue())

    monkeypatch.setattr(gold.urllib.request, "urlopen", fake_urlopen)
    f = gold.Fetcher(spacing={"example.org": 0}, sleep=slept.append)
    assert f.json("https://example.org/x") == {"ok": True}
    assert 3.0 in slept
    monkeypatch.setattr(gold.urllib.request, "urlopen",
                        lambda req, timeout: (_ for _ in ()).throw(urllib.error.HTTPError("u", 404, "no", {}, None)))
    assert f.json("https://example.org/y") is None
    monkeypatch.setattr(gold.urllib.request, "urlopen",
                        lambda req, timeout: (_ for _ in ()).throw(urllib.error.HTTPError("u", 403, "no", {}, None)))
    with pytest.raises(urllib.error.HTTPError):
        f.json("https://example.org/z")


def test_resplit_reads_saved_cases_without_network(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    cases = [{"case_id": f"c{i}", "stratum": "x" if i % 3 else "y", "task_type": "same_role",
              "input": {}, "truth": {}, "truth_sources": [{"name": "s"}]} for i in range(95)]
    (raw / "package-cases.json").write_text(json.dumps(cases))
    out = gold.resplit(tmp_path, raw)
    assert set(out) == {"package-risk-audit"}
    assert all(v["cases"] == 30 for v in out["package-risk-audit"]["files"].values())


def test_record_truth_prefers_cna_then_adp():
    class F:
        def __init__(self, doc):
            self.doc = doc

        def json(self, url, body=None):
            return self.doc
    cna = {"containers": {"cna": {"providerMetadata": {"shortName": "apache"},
                                  "metrics": [{"cvssV3_1": {"baseScore": 10.0, "version": "3.1"}}]}}}
    assert gold.cvelist_metrics(F(cna), "CVE-2021-44228") == {"score": 10.0, "version": "3.1", "from": "cna", "provider": "apache"}
    adp = {"containers": {"cna": {}, "adp": [{"providerMetadata": {"shortName": "CISA-ADP"},
                                              "metrics": [{"cvssV3_1": {"baseScore": 7.5, "version": "3.1"}}]}]}}
    assert gold.cvelist_metrics(F(adp), "CVE-2024-1")["from"] == "adp"
    cases = [{"case_id": "CVE-2024-1", "truth": {}, "truth_sources": []}]
    assert gold.add_record_truth(F(adp), cases) == 1 and cases[0]["truth"]["cvss_record"]["score"] == 7.5
    assert gold.add_record_truth(F(adp), cases) == 0

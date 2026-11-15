"""cve-incident-brief v2 fix answers: GitHub reviewed advisories per CVE, resumable, open-source CVEs first."""
import json

from agent_market.necklaces import gold_cve_fixes as fx, gold_repos


def setup(tmp_path):
    folder = tmp_path / "gold" / "cve-incident-brief"
    folder.mkdir(parents=True)
    rows = [("CVE-2021-44228", "GitHub_M"), ("CVE-2023-36802", "microsoft"), ("CVE-2022-22965", "snyk")]
    (folder / "holdout-r1.jsonl").write_text("".join(json.dumps(
        {"case_id": c, "input": {"cve_id": c}, "stratum": "kev", "truth": {"cvss": {"score": 9.8}, "cvss_record": {"provider": p}, "kev": True}})
        + "\n" for c, p in rows))
    (folder / "manifest.json").write_text(json.dumps({"files": {}}))
    return folder


def fake(limit=99):
    calls = []

    def get(url):
        if len(calls) >= limit:
            raise gold_repos.Budget("system_share")
        calls.append(url)
        if "CVE-2021-44228" in url:
            return 200, [{"ghsa_id": "GHSA-jfh8", "vulnerabilities": [
                {"package": {"ecosystem": "maven", "name": "org.apache.logging.log4j:log4j-core"}, "first_patched_version": "2.15.0"},
                {"package": {"ecosystem": "maven", "name": "x:y"}, "first_patched_version": None}]}]
        if "CVE-2022-22965" in url:
            return 200, [{"ghsa_id": "GHSA-36p3", "vulnerabilities": [
                {"package": {"ecosystem": "maven", "name": "org.springframework:spring-beans"}, "first_patched_version": {"identifier": "5.3.18"}}]}]
        return 200, []
    return get, calls


def test_open_source_cves_first_resume_and_only_cases_with_fixes(tmp_path):
    folder = setup(tmp_path)
    get, calls = fake(limit=2)
    out = fx.step(tmp_path, get)
    assert out == {"asked": 2, "with_fixes": 2, "left": 1, "stopped": "system_share"}
    assert "CVE-2023-36802" not in " ".join(calls)                      # the Microsoft one is asked last
    get, calls = fake()
    out = fx.step(tmp_path, get)
    assert len(calls) == 1 and out["written"] == {"cases": 2, "strata": {"kev": 2}}
    written = {json.loads(l)["case_id"]: json.loads(l) for l in (folder / "holdout-v2-fix.jsonl").read_text().splitlines()}
    assert written["CVE-2021-44228"]["truth"]["fixes"] == [
        {"ecosystem": "maven", "name": "org.apache.logging.log4j:log4j-core", "first_patched_version": "2.15.0"}]
    assert written["CVE-2022-22965"]["truth"]["fixes"][0]["first_patched_version"] == "5.3.18"
    assert written["CVE-2021-44228"]["truth"]["cvss"]["score"] == 9.8                # the earlier truth is kept

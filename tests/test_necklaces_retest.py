import json

from agent_market.necklaces import model, retest, runner
from tests.test_necklaces_runner import Fail, caller_from


def pkg_case(case_id, ids, latest="4.17.21"):
    return {"case_id": case_id, "input": {"package": "lodash", "ecosystem": "npm", "version": "4.17.20"},
            "truth": {"advisories": [{"id": i, "ids": [i]} for i in ids], "latest_version": latest}, "stratum": "x"}


def package_defn():
    defn = next(d for d in model.load_valid() if d["slug"] == "package-risk-audit")
    for slot in defn["slots"]:
        for m in slot["chain"]:
            if m["kind"] == "agentcon":
                m["state"] = "active"
    return defn


def test_graders():
    case = pkg_case("a", ["CVE-2021-23337", "CVE-2020-28500"])
    assert retest.grade_advisories(case, {"items": [{"id": "CVE-2021-23337"}, {"id": "CVE-2020-28500"}]})
    assert not retest.grade_advisories(case, {"items": [{"id": "CVE-2021-23337"}]})
    assert retest.grade_advisories(pkg_case("b", []), {"items": []})
    assert retest.grade_health(case, {"answers": [{"text": "latest 4.17.21"}]})
    cve = {"truth": {"cvss": {"score": 10.0}, "cvss_record": {"score": 9.8}, "kev": False}}
    assert retest.grade_record(cve, {"cvss_scores": [9.8]}) and not retest.grade_record(cve, {"cvss_scores": [7.0]})
    assert retest.grade_exploited(cve, {"kev": False}) and not retest.grade_exploited(cve, {"kev": None})


def test_run_set_writes_daily_lines_and_single_baselines(tmp_path):
    defn = package_defn()
    cases = [pkg_case("c1", ["CVE-2021-23337"]), pkg_case("c2", [])]
    answers = {367249: "CVE-2021-23337", 286623: Fail(), 130453: "CVE-2021-23337", 47161: "nothing",
               "package-registry": {"latest_version": "4.17.21"}}
    clock = iter(range(0, 1000, 1))
    out = retest.run_set(defn, cases, caller_from(answers), root=tmp_path, singles=True,
                         clock=lambda: next(clock), now=lambda: 1_800_000_000)
    assert out == {"slug": "package-risk-audit", "split": "tuning", "cases": 2, "passed": 2, "of": 2,
                   "stopped_by_budget": False, "seconds": out["seconds"]}
    lines = [json.loads(l) for l in (tmp_path / "retest" / "20270115.jsonl").read_text().splitlines()]
    kinds = {l["type"] for l in lines}
    assert kinds == {"case", "member", "single"}
    singles = [l for l in lines if l["type"] == "single"]
    assert {l["resource_id"] for l in singles} == {367249, 286623, 47161, 130453}
    assert any(l["ok"] is False for l in singles if l["resource_id"] == 286623)
    assert (tmp_path / "results" / "package-risk-audit" / "selftest-20270115.jsonl").exists()


def test_run_set_stops_at_the_time_budget(tmp_path):
    defn = package_defn()
    cases = [pkg_case(f"c{i}", []) for i in range(5)]
    ticks = iter(range(0, 100_000, 100))       # every clock read moves 100 s on
    out = retest.run_set(defn, cases, caller_from({367249: "none", 286623: "none", "package-registry": "4.17.21"}),
                         root=tmp_path, budget_s=300, clock=lambda: next(ticks), now=lambda: 1_800_000_000)
    assert out["stopped_by_budget"] and out["cases"] == 3


def test_budget_counts_the_provider_domain_not_our_relay():
    member = {"kind": "external", "resource_id": 367249, "registrable_domain": "poparecon.com"}
    assert retest.provider_url(member) == "https://poparecon.com/"
    seen = []

    class Budget:
        def reserve(self, url, system, n=1):
            seen.append(url)
            return True, "ok"

        def note(self, *a):
            pass
    call = runner.budgeted_caller(lambda m, a, t: "ok", "necklace_retest", retest.provider_url, Budget())
    call(member, {}, 1)
    assert seen == ["https://poparecon.com/"]


def test_gateway_caller_uses_the_public_relay_with_the_qa_header():
    sent = []

    class Resp:
        def __init__(self, data, status=200):
            self.data, self.status_code = data, status

        def json(self):
            return self.data

    class Client:
        def post(self, url, json, headers, timeout=None):
            sent.append((url, json["method"], headers.get("X-Agentcon-QA")))
            if json["method"] == "initialize":
                return Resp({"result": {}})
            return Resp({"result": {"structuredContent": {"items": ["CVE-1"]}}})
    call = retest.gateway_caller(Client(), "https://example.test")
    out = call({"kind": "external", "resource_id": 5, "tool": "t"}, {"q": 1}, 3)
    assert out == {"items": ["CVE-1"]}
    assert sent == [("https://example.test/api/gateway/mcp/5", "initialize", "necklace_retest"),
                    ("https://example.test/api/gateway/mcp/5", "tools/call", "necklace_retest")]


def test_relay_throttle_is_not_a_provider_pause():
    class Resp:
        def __init__(self, status, data):
            self.status_code, self.data = status, data

        def json(self):
            return self.data
    noted = []

    class Budget:
        def reserve(self, url, system, n=1):
            return True, "ok"

        def note(self, url, system, status):
            noted.append(url)

    def client_with(resp):
        class Client:
            def post(self, url, json, headers, timeout=None):
                return Resp(200, {"result": {}}) if json["method"] == "initialize" else resp
        return Client()
    member = {"kind": "external", "resource_id": 1, "tool": "t", "registrable_domain": "p.example"}
    relay_429 = runner.budgeted_caller(retest.gateway_caller(client_with(Resp(429, {}))), "necklace_retest",
                                       retest.provider_url, Budget())
    try:
        relay_429(member, {}, 3)
    except Exception as exc:
        assert exc.error_code == "relay_throttled"
    assert noted == []
    paused = Resp(200, {"error": {"message": "The provider asked for a pause", "data": {"retry_after": 30}}})
    provider_429 = runner.budgeted_caller(retest.gateway_caller(client_with(paused)), "necklace_retest",
                                          retest.provider_url, Budget())
    try:
        provider_429(member, {}, 3)
    except Exception as exc:
        assert exc.error_code == "PROVIDER_429"
    assert noted == ["https://p.example/"]


def test_relay_pacer_waits_between_cases_and_never_oversends():
    now = [0.0]
    slept = []
    pacer = retest.RelayPacer(per_minute=4, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    assert all(pacer.take() for _ in range(4)) and not pacer.take()
    pacer.wait_for(2)
    assert slept and now[0] >= 60
    assert retest.requests_per_case(next(d for d in model.load_valid() if d["slug"] == "cve-incident-brief")) == 6


def test_registry_grader_accepts_cik_or_lei():
    us = {"truth": {"cik": "320193", "lei": None}}
    assert retest.grade_registry(us, {"answers": [{"text": "Apple Inc. CIK 0000320193"}]})
    eu = {"truth": {"cik": None, "lei": "529900D6BF99LW9R2E68"}}
    assert retest.grade_registry(eu, {"legal_name": "SAP SE", "identifiers": {"lei": "529900D6BF99LW9R2E68"}})
    assert not retest.grade_registry(eu, {"legal_name": "SAP SE"})


def test_topic_graders():
    case = {"truth": {"papers": [{"doi": "10.1038/nprot.2013.143", "title": "Genome engineering using the CRISPR-Cas9 system"}],
                      "wiki": {"title": "CRISPR gene editing", "description": "Gene editing method"}}}
    assert retest.grade_papers(case, {"answers": [{"text": "doi 10.1038/NPROT.2013.143"}]})
    assert retest.grade_papers(case, {"items": [{"title": "Genome engineering using the CRISPR-Cas9 system"}]})
    assert not retest.grade_papers(case, {"items": [{"title": "Something else"}]})
    assert retest.grade_background(case, {"text": "CRISPR gene editing is a gene editing method"})
    assert retest.grade_background(case, {"text": "a method for gene editing"})
    assert not retest.grade_background(case, {"text": "a recipe for bread"})
    assert retest.grade_web(case, {"answer": "see https://example.org"}) and not retest.grade_web(case, {"answer": "x"})

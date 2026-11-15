import json
import time

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
    # c2 is a clean version, but 367249 lists an advisory for it: a wrong answer since R25 (passed 1 of 2)
    assert out == {"slug": "package-risk-audit", "split": "tuning", "cases": 2, "passed": 1, "excluded": 0, "of": 2,
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

        def note(self, url, system, status, evidence=None):
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
    assert retest.grade_web(case, {"answer": "CRISPR gene editing, see https://example.org"})
    assert not retest.grade_web(case, {"answer": "see https://example.org"})       # R25: a bare link is not grounding
    assert not retest.grade_web(case, {"answer": "CRISPR gene editing"})             # and no link is no grounding


# ---------------------------------------------------------------- company-due-diligence v1 task (PM 11-15 decisions)
FILING = {"form": "10-K", "date": "2026-11-03", "accession": "0000320193-26-000026", "valid_until": "2099-01-01"}
US_CASE = {"case_id": "US:CIK320193", "input": {"name": "Apple Inc", "country": "US"},
           "truth": {"cik": "320193", "ticker": "AAPL", "lei": "HWUPKR0MPOU8FGXBT394", "sec_title": "Apple Inc.",
                     "filings": FILING}}
JP_CASE = {"case_id": "JP:x", "input": {"name": "Toyota", "country": "JP"},
           "truth": {"lei": "5493006W3QUS5LMH6R84", "legal_name": "TOYOTA MOTOR CORPORATION", "cik": None}}
PEARL_FILINGS = {"text": json.dumps({"company": {"cik": 320193, "ticker": "AAPL"}, "filings": [
    {"form": "8-K", "filingDate": "2026-11-09", "accession": "0001140361-26-042798"},
    {"form": "10-K", "filingDate": "2026-11-03", "accession": "0000320193-26-000026"}]})}


def necklace_output(filings=PEARL_FILINGS):
    return {"registry": {"answers": [{"legal_name": "Apple Inc.", "cik": "320193", "ticker": "AAPL"}]},
            "background": {"answers": [{"text": "Apple Inc. is an American multinational technology company that designs consumer electronics"}]},
            "filings": {"answers": [filings]}}


def test_company_background_names_the_company():
    assert retest.grade_background(US_CASE, {"text": "Apple Inc. is an American multinational technology company that designs consumer electronics"})
    assert not retest.grade_background(US_CASE, {"text": "Inc. is a legal form"})          # legal words do not count
    assert retest.grade_background(JP_CASE, {"text": "Toyota Motor Corporation is a Japanese multinational automotive manufacturer in Aichi"})


def test_filings_pass_with_the_truth_or_a_later_periodic_filing_only():
    assert retest.grade_filings(US_CASE, {"answers": [PEARL_FILINGS]})
    later = {"text": json.dumps({"filings": [{"form": "10-Q", "filingDate": "2027-01-30", "accession": "x" * 18}]})}
    assert retest.grade_filings(US_CASE, later)
    older = {"text": json.dumps({"filings": [{"form": "10-Q", "filingDate": "2026-08-01", "accession": "1" * 18}]})}
    assert not retest.grade_filings(US_CASE, older)
    current_report = {"text": json.dumps({"filings": [{"form": "8-K", "filingDate": "2026-12-01"}]})}
    assert not retest.grade_filings(US_CASE, current_report)              # only periodic forms count


def test_the_task_needs_cik_filing_and_description_together():
    assert retest.grade_company_task(US_CASE, necklace_output())
    sec_edgar_alone = {"registry": {"answers": [{"legal_name": "Apple Inc.", "cik": "320193", "ticker": "AAPL"}]}}
    assert not retest.grade_company_task(US_CASE, sec_edgar_alone)       # our substitute alone has no filing
    encyclopedia_alone = {"background": {"answers": [{"text": "Apple Inc. (NASDAQ: AAPL) is a technology company"}]}}
    assert not retest.grade_company_task(US_CASE, encyclopedia_alone)
    assert not retest.grade_company_task(US_CASE, {"filings": {"answers": [PEARL_FILINGS]}})   # no description
    defn = next(d for d in model.load_valid() if d["slug"] == "company-due-diligence")
    assert retest.grade(defn, US_CASE, necklace_output())["ok"] is True


def test_cases_outside_the_task_are_not_run_or_graded(tmp_path):
    defn = next(d for d in model.load_valid() if d["slug"] == "company-due-diligence")
    assert retest.company_excluded(JP_CASE) == "out_of_task"
    no_truth = {**US_CASE, "truth": {k: v for k, v in US_CASE["truth"].items() if k != "filings"}}
    assert retest.company_excluded(no_truth) == "out_of_task"
    expired = {**US_CASE, "truth": {**US_CASE["truth"], "filings": {**FILING, "valid_until": "2026-01-01"}}}
    assert retest.company_excluded(expired) == "truth_expired"
    calls = []
    out = retest.run_set(defn, [JP_CASE, expired], lambda m, a, t: calls.append(m) or {}, root=tmp_path)
    assert calls == [] and out["excluded"] == 2 and out["passed"] == 0


def test_singles_are_every_lead_pearl_and_our_substitute_on_the_whole_task():
    defn = next(d for d in model.load_valid() if d["slug"] == "company-due-diligence")
    approved = {"substitutes": [["sec-edgar", "company.registry.v1"]]}      # ops-approved 11-15 (approvals.json)
    members = retest.single_members(defn, "background", approved)
    # 58997's terms prohibit our use (agent team 11-15): it is never measured alone either
    assert sorted((s, m.get("resource_id") or m.get("agent_id")) for s, m in members) == [
        ("background", 241601), ("domain", 52559), ("registry", "sec-edgar")]
    assert ("registry", "sec-edgar") not in [(s, m.get("agent_id")) for s, m in retest.single_members(defn, "background")]
    one = retest.single_definition(defn, "background", next(m for s, m in members if s == "background"))
    assert one["slots"][0]["chain"][0]["input_map"] == {"query": "{{input.name}}"} and "depends_on" not in one["slots"][0]


def test_the_shipped_company_definition_has_three_verified_pearl_leads():
    from agent_market.necklaces import judge
    defn = next(d for d in model.load_valid() if d["slug"] == "company-due-diligence")
    verified = {(241601, "encyclopedia.summary.v1"), (58997, "sec.filings.v1"), (52559, "domain.lookup.v1")}
    leads = judge.pearls(defn, verified)
    assert sorted(p["resource_id"] for p in leads if p["pearl"]) == [52559, 58997, 241601]
    domains = [m["registrable_domain"] for s in defn["slots"] for m in s["chain"] if m["kind"] == "external"]
    assert len(domains) == len(set(domains))                    # no provider in two steps
    assert defn["scope"] == {"country": ["US"]} and defn["min_pearls_answered"] == 2


# ---------------------------------------------------------------- relay concurrency and edge capacity (PM 11-15 10:40)
class Full:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def post(self, url, json, headers, timeout):
        self.calls += 1
        status, body, extra = self.replies.pop(0)
        resp = type("R", (), {"status_code": status, "headers": extra, "json": lambda self_: body})()
        return resp


def test_a_full_edge_is_retried_once_then_counted_as_our_capacity():
    import threading
    ok_result = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"kev": True}}}
    full = (503, {"detail": "busy"}, {"X-Execution-Error": "CAPACITY_EXCEEDED"})
    client = Full([full, (200, ok_result, {}), full, (200, ok_result, {})])
    pacer = retest.RelayPacer(per_minute=100)
    call = retest.gateway_caller(client, "https://x.test", pacer, slots=threading.BoundedSemaphore(2), sleep=lambda s: None)
    member = {"kind": "external", "resource_id": 1, "tool": "t"}
    assert call(member, {}, 10) == {"kev": True} and client.calls == 4
    client = Full([full, full])
    call = retest.gateway_caller(client, "https://x.test", pacer, slots=threading.BoundedSemaphore(2), sleep=lambda s: None)
    try:
        call(member, {}, 10)
    except Exception as exc:
        assert exc.error_code == "our_capacity"
    else:
        raise AssertionError("no capacity error")
    unavailable = (200, {"jsonrpc": "2.0", "id": 1, "error": {"message": "The execution is unavailable."}}, {})
    assert retest.capacity_exceeded(*unavailable[:1], {}, unavailable[1])


def test_our_capacity_is_not_a_failure_of_the_case_or_the_member(tmp_path):
    defn = runner_defn = next(d for d in model.load_valid() if d["slug"] == "package-risk-audit")

    def caller(member, args, timeout):
        error = Exception("edge full")
        error.error_code = "our_capacity"
        raise error
    cases = [{"case_id": "c1", "input": {"package": "lodash", "ecosystem": "npm"}, "truth": {}}]
    out = retest.run_set(runner_defn, cases, caller, root=tmp_path)
    assert out["excluded"] == 1 and out["passed"] == 0 and out["cases"] == 0
    lines = [json.loads(x) for x in next((tmp_path / "retest").glob("*.jsonl")).read_text().splitlines()]
    assert [x["type"] for x in lines] == ["excluded"] and lines[0]["why"] == "our_capacity"
    assert defn["slug"] == "package-risk-audit"


def test_a_gate_round_can_take_the_public_engine_path(tmp_path, monkeypatch):
    """PM R26: one gate round runs through the registered-agent engine that public runs use, not the relay."""
    import copy
    defn = copy.deepcopy(next(d for d in model.load_valid() if d["slug"] == "package-risk-audit"))
    for slot in defn["slots"]:
        for m in slot["chain"]:
            m["state"] = "active"
    folder = tmp_path / "gold" / "package-risk-audit"
    folder.mkdir(parents=True)
    case = {"case_id": "p1", "input": {"package": "lodash", "ecosystem": "npm"},
            "truth": {"advisories": [], "latest_version": "9.9.9"}}
    (folder / "tuning.jsonl").write_text(json.dumps(case) + "\n")
    (folder / "manifest.json").write_text(json.dumps({"valid_until": "2999-01-01"}))   # a set must be valid (PM 13:0x)
    seen = []

    class Engine:
        store = None

        def _call_registered(self, node, args):
            seen.append(node["resource_id"])
            return {"vulns": [], "version": "9.9.9"}
    monkeypatch.setattr(retest.runner, "budgeted_caller", lambda caller, system, url_of, budget=None: caller)
    out = retest.run_daily(defn, root=tmp_path, split="tuning", singles=False, budget_s=60, path="engine",
                           engine=Engine())
    assert out["path"] == "engine" and out["passed"] == 1 and seen


# ---------------------------------------------------------------- R25: every grader fails a wrong answer
def test_wrong_answers_fail_every_grader():
    clean = {"truth": {"advisories": [], "latest_version": "4.17.21"}}
    assert retest.grade_advisories(clean, {"items": []})
    assert not retest.grade_advisories(clean, {"items": [{"id": "CVE-2099-0001"}]})     # anything listed is wrong
    vulnerable = {"truth": {"advisories": [{"ids": ["CVE-2021-23337", "GHSA-35JH-R3H4-6JHM"]}]}}
    assert retest.grade_advisories(vulnerable, {"items": [{"id": "GHSA-35JH-R3H4-6JHM"}]})
    dump = {"items": [{"id": "CVE-2021-23337"}] + [{"id": f"CVE-2099-{i:04d}"} for i in range(5)]}
    assert not retest.grade_advisories(vulnerable, dump)                                  # a dump of ids
    assert retest.grade_health(clean, {"text": "latest 4.17.21"})
    assert not retest.grade_health(clean, {"text": "latest 4.17.210"})
    assert not retest.grade_health({"truth": {"latest_version": "1.2"}}, {"text": "1.2.3"})
    registry = {"truth": {"cik": "1750", "lei": None}}
    assert retest.grade_registry(registry, {"cik": "0000001750"})
    assert not retest.grade_registry(registry, {"cik": "17501"})                          # not inside another number
    assert not retest.grade_background(US_CASE, {"text": "Apple"})                         # an echo, not a description
    assert not retest.grade_background(US_CASE, {"text": "Banana Republic is an American clothing and accessories retailer"})
    assert not retest.grade_company_task(US_CASE, {"r": "CIK 320193 Apple " + "x" * 80})   # no filing


def _package_set(tmp_path, versions):
    import copy
    defn = copy.deepcopy(next(d for d in model.load_valid() if d["slug"] == "package-risk-audit"))
    for slot in defn["slots"]:
        for m in slot["chain"]:
            m["state"] = "active"
    folder = tmp_path / "gold" / "package-risk-audit"
    folder.mkdir(parents=True)
    rows = [{"case_id": f"p{i}", "input": {"package": f"pkg{i}", "ecosystem": "npm"},
             "truth": {"advisories": [], "latest_version": v}} for i, v in enumerate(versions)]
    (folder / "holdout-r1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (folder / "manifest.json").write_text(json.dumps({"valid_until": "2999-01-01"}))
    return defn


def test_live_retest_runs_five_cases_and_the_whole_set_after_one_failure(tmp_path, monkeypatch):
    """PM 11:4x decision 1: 5 sample cases a day; one failure reruns all 30 that day."""
    defn = _package_set(tmp_path, ["9.9.9"] * 30)
    asked = []

    class Engine:
        store = None
        answer = "9.9.9"

        def _call_registered(self, node, args):
            asked.append(args.get("package") or args.get("name"))
            return {"vulns": [], "version": self.answer}
    monkeypatch.setattr(retest.runner, "budgeted_caller", lambda caller, system, url_of, budget=None: caller)
    engine = Engine()
    out = retest.run_daily(defn, root=tmp_path, split="holdout-r1", singles=False, budget_s=300, path="engine",
                           engine=engine, sample=(10, 5))
    assert out["cases"] == 5 and out["passed"] == 5 and out["sample"] == [10, 5] and not out.get("escalated")
    engine.answer = "0.0.1"                       # every answer now wrong: the sample fails, the whole set runs
    out = retest.run_daily(defn, root=tmp_path, split="holdout-r1", singles=False, budget_s=300, path="engine",
                           engine=engine, sample=(10, 5))
    assert out["escalated"] is True and out["sample_result"]["cases"] == 5 and out["cases"] == 30


def test_shared_cache_answers_once_per_member_and_input_inside_retests():
    """PM 11:4x decision 2: retest-only sharing, marked on the case line, error answers not kept."""
    cache, calls = retest.SharedMemberCache(clock=lambda: 0), []

    def caller(member, args, timeout_s):
        calls.append(args["q"])
        return {"error": "rate"} if args["q"] == "bad" else {"ok": args["q"]}
    shared = cache.wrap(caller)
    member = {"kind": "external", "resource_id": 7, "tool": "t"}
    assert shared(member, {"q": "a"}, 5) == shared(member, {"q": "a"}, 5) == {"ok": "a"}
    shared(member, {"q": "bad"}, 5)
    shared(member, {"q": "bad"}, 5)
    shared({"kind": "agentcon", "agent_id": "x", "tool": "t"}, {"q": "a"}, 5)
    assert calls == ["a", "bad", "bad", "a"] and cache.take_hits() == 1 and cache.take_hits() == 0


def test_two_necklaces_escalating_on_one_provider_stay_inside_its_share_and_defer(tmp_path, monkeypatch):
    """PM 12:50: whole-set reruns on the same day never pass a provider's share; one that would not fit is deferred
    (no case cut short). The real ledger counts in a temporary folder."""
    from agent_market import provider_budget as pb
    monkeypatch.setattr(pb, "DIR", tmp_path / "ledger")
    defn = _package_set(tmp_path, ["9.9.9"] * 30)
    calls = []

    class Engine:
        store = None

        def _call_registered(self, node, args):
            calls.append(node["resource_id"])
            return {"vulns": [], "version": "0.0.1"}            # always wrong: every sample fails
    lead_domains = {m["registrable_domain"] for s in defn["slots"] for m in model.live_members(s, "external")[:1]}
    first = retest.run_daily(defn, root=tmp_path, split="holdout-r1", singles=False, budget_s=600, path="engine",
                             engine=Engine(), sample=(0, 5))
    assert first["escalated"] is True and first["cases"] == 30           # 5 + 30 = 35 = the necklace_retest share
    second = retest.run_daily(defn, root=tmp_path, split="holdout-r1", singles=False, budget_s=600, path="engine",
                              engine=Engine(), sample=(5, 5))
    assert second.get("deferred", {}).get("why") == "provider_share" or second["cases"] == 0
    ledger = pb.status(directory=tmp_path / "ledger")["domains"]
    for name in lead_domains:
        assert ledger[pb.domain(f"https://{name}/")]["by"].get("necklace_retest", 0) <= pb.share_limit("necklace_retest", name)
    again = retest.run_daily(defn, root=tmp_path, split="holdout-r1", singles=False, budget_s=600, path="engine",
                             engine=Engine(), require_room=True)
    assert again["deferred"]["why"] == "provider_share" and again["cases"] == 0     # still no room today


def test_ledger_room_reads_share_total_and_pauses():
    from agent_market import provider_budget as pb
    defn = {"slots": [{"slot": "s", "fanout": 1, "chain": [{"kind": "external", "state": "active", "resource_id": 1,
                                                          "tool": "t", "registrable_domain": "a.example"}]}]}
    used = lambda n, paused=False: (lambda: {"domains": {"a.example": {"total": n, "by": {"necklace_retest": n},
                                                                       **({"paused": {"at": "x"}} if paused else {})}}})
    assert retest.ledger_room(defn, 30, status=used(0)) == {}
    assert retest.ledger_room(defn, 30, status=used(10)) == {"a.example": [30, pb.share_limit("necklace_retest", "a.example") - 10]}
    assert retest.ledger_room(defn, 1, status=used(0, paused=True)) == {"a.example": [1, 0]}


def test_relay_calls_never_hold_more_than_two_edge_slots():
    """PM 12:50: however many necklaces retest, our relay requests share one process-wide pair of slots."""
    import threading as th
    now, peak, lock = [0], [0], th.Lock()

    class Client:
        def post(self, url, json, headers, timeout):
            with lock:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            time.sleep(0.02)
            with lock:
                now[0] -= 1
            return type("R", (), {"status_code": 200, "headers": {}, "json": lambda self: {"result": {"ok": 1}}})()
    pacer = type("P", (), {"take": lambda self: True})()
    call = retest.gateway_caller(Client(), "https://x.test", pacer)
    member = {"kind": "external", "resource_id": 1, "tool": "t", "registrable_domain": "a.example"}
    workers = [th.Thread(target=lambda: call(member, {}, 5)) for _ in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert 1 <= peak[0] <= retest.RELAY_CONCURRENCY == 2

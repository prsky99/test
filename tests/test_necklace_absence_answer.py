"""PM 11-17 (company-diligence-brief): a slot marked absence_is_answer answers "no record" when every member said
not_found; a step that needs its values is then not run, and neither counts as a failure."""
from agent_market.necklaces import runner
from tests.test_necklaces_model import ext, own
from tests.test_necklaces_runner import Fail, caller_from


def defn():
    return {"slug": "diligence", "version": 1, "status": "candidate", "name": "D", "summary": "s",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"],
                             "additionalProperties": False},
            "budget_ms": {"total": 3000, "slot": 2500},
            "slots": [
                {"slot": "screen", "contract": "x.v1", "required": True, "fanout": 1, "chain": [ext(1, "a.com")]},
                {"slot": "registry", "contract": "x.v1", "required": True, "fanout": 1, "absence_is_answer": True,
                 "chain": [own(10, agent_id="reg1"), own(11, agent_id="reg2")]},
                {"slot": "filings", "contract": "x.v1", "required": True, "fanout": 1, "depends_on": ["registry"],
                 "chain": [dict(ext(2, "b.com"), input_map={"t": "{{slot.registry.ticker}}"})]}]}


def test_every_member_not_found_is_the_answer_and_the_next_step_is_skipped_not_failed():
    calls = []
    out = runner.Runner(caller_from({1: "screened", 10: Fail("not_found"), 11: Fail("not_found")}, calls)).run(
        defn(), {"q": "x"})
    assert out["ok"] and out["failed_slot"] is None
    reg = out["output"]["registry"]
    assert reg["not_found"] and reg["sources"] == ["src2"] and reg["note"].startswith("No record found in src2 as of ")
    assert "clear" not in reg["note"].lower() and "safe" not in reg["note"].lower()
    assert out["output"]["filings"] == {"skipped": True, "note": runner.UPSTREAM_ABSENT_NOTE}
    assert sorted(rid for rid, _ in calls) == [1, 10, 11]                  # both registry members asked, filings not


def test_a_member_that_failed_otherwise_keeps_the_step_failed():
    out = runner.Runner(caller_from({1: "screened", 10: Fail("not_found"), 11: Fail("source_unavailable")})).run(
        defn(), {"q": "x"})
    assert not out["ok"] and out["failed_slot"] == "registry"


def test_without_the_mark_not_found_is_still_a_failure():
    d = defn()
    del d["slots"][1]["absence_is_answer"]
    out = runner.Runner(caller_from({1: "screened", 10: Fail("not_found"), 11: Fail("not_found")})).run(d, {"q": "x"})
    assert not out["ok"] and out["failed_slot"] == "registry"


def test_only_not_found_counts_a_timeout_a_403_a_5xx_or_an_empty_or_invalid_answer_keeps_it_failed():
    for other in (Fail("timeout"), Fail("UPSTREAM_HTTP_403"), Fail("UPSTREAM_5XX"), Fail("contract_invalid"),
                  Fail("UPSTREAM_EMPTY")):
        out = runner.Runner(caller_from({1: "screened", 10: Fail("not_found"), 11: other})).run(defn(), {"q": "x"})
        assert not out["ok"] and out["failed_slot"] == "registry", other.error_code


def test_a_source_never_asked_is_left_out_and_with_none_asked_the_step_fails():
    d = defn()
    d["slots"][1]["chain"][1]["upstream"] = ["src3"]
    # the second registry member's call never went out (our ledger said no): only the first source is named
    out = runner.Runner(caller_from({1: "screened", 10: Fail("not_found"), 11: Fail("budget_domain_daily_total")})).run(
        d, {"q": "x"})
    assert out["ok"] and out["output"]["registry"]["sources"] == ["src2"]
    assert "src3" not in out["output"]["registry"]["note"]
    # no call reached any source: no "no record" answer, the step fails
    out = runner.Runner(caller_from({1: "screened", 10: Fail("capacity"), 11: Fail("budget_domain_daily_total")})).run(
        d, {"q": "x"})
    assert not out["ok"] and out["failed_slot"] == "registry"


def test_the_sec_source_name_says_its_scope():
    from agent_market.necklaces.runner import SOURCE_NAMES
    assert SOURCE_NAMES["sec-edgar"] == "SEC EDGAR (companies with a ticker)"    # agent team 11-17: its index scope

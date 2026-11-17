"""PM 11-18: company v3 round 1 failed 14 companies without a Wikipedia article: the search member's results were
about others (identity_mismatch, rightly dropped) and the next member timed out on the missing title. A member marked
absence_final (our wikipedia-summary, an exact-title lookup) that says "no article" ends the step: later members are
not called and the step answers "No encyclopedia article found". Fakes only, no network."""
import copy

from agent_market.necklaces import model, runner
from tests.test_necklace_encyclopedia_identity import DEFN, STATE as BASE

# the order the runtime chain gives once wikipedia-summary passed its substitute gate: the verified pearl 241601,
# then our approved substitute (provisional standing), then 47189 with no standing (watch.runtime_chain)
STATE = dict(BASE, standing={"external": {"241601|encyclopedia.summary.v1": "verified_pearl"}, "own": {}})


class NoRecord(Exception):
    code = "not_found"


def defn_with(final: bool):
    d = copy.deepcopy(model.load(DEFN))
    for s in d["slots"]:
        if s["slot"] == "background":
            by = {(m.get("resource_id") or m.get("agent_id")): m for m in s["chain"]}
            summary = dict(by["wikipedia-summary"], absence_final=final)
            s["chain"] = [by[241601], summary, by[47189]]
    return d


def caller_for(called):
    def caller(member, args, timeout_s):
        key = member.get("agent_id") or member.get("resource_id")
        called.append(key)
        if key == "sec-edgar":
            return {"legal_name": "Canary Staked SUI ETF", "cik": "2060703", "ticker": "SUIS"}
        if key == "sec-filings":
            return {"answer": "Matched SEC filer: Canary Staked SUI ETF (SEC CIK 2060703). 2026-11-13 10-Q "
                              "(accession 0001999371-26-025344)"}
        if key == 241601:                                   # results about other subjects only
            return [{"title": "Sui (blockchain)", "snippet": "a layer-1 blockchain"}]
        if key == "wikipedia-summary":
            raise NoRecord("no article")
        if key == 47189:
            raise TimeoutError("missing title")             # what 47189 did on 11-18
        raise RuntimeError("not this member")
    return caller


def test_an_authoritative_no_article_ends_the_step():
    called = []
    out = runner.Runner(caller_for(called), watch_state=STATE).run(defn_with(True), {"name": "Canary Staked SUI ETF", "country": "US"})
    assert 47189 not in called
    assert out["output"]["background"] == {"not_found": True, "note": runner.NOT_FOUND_NOTE}
    assert [a["error_class"] for a in out["attempts"]["background"]] == ["identity_mismatch", "not_found"]


def test_without_the_mark_the_chain_goes_on_as_before():
    called = []
    out = runner.Runner(caller_for(called), watch_state=STATE).run(defn_with(False), {"name": "Canary Staked SUI ETF", "country": "US"})
    assert 47189 in called
    assert "background" not in out["output"] or out["output"]["background"] != {"not_found": True, "note": runner.NOT_FOUND_NOTE}

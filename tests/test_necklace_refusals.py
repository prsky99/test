"""PM 11-16 source review: our side's refusals are one list (refusals.py) for the runner, the gate, the public service
and the value measure; a provider cap on a public run is our refusal, not a member failure."""
from agent_market.necklaces import model, refusals, retest, runner, service, value
from tests.test_necklace_encyclopedia_identity import DEFN, STATE


def test_one_list_and_what_it_holds():
    for code in ("provider_cap", "capacity", "our_capacity", "CAPACITY_EXCEEDED", "quota_exhausted", "relay_throttled",
                 "PROVIDER_429", "rate_limited", "budget_domain_daily_total", "budget_held_for_higher_priority"):
        assert refusals.is_ours(code), code
    for code in ("not_found", "contract_invalid", "identity_mismatch", "timeout", "deadline", "late",
                 "RuntimeError", "relay_502", "budget_no_domain", None, ""):
        assert not refusals.is_ours(code), code
    assert refusals.not_sent("provider_cap") and refusals.not_sent("budget_no_domain") and refusals.not_sent("deadline")
    assert not refusals.not_sent("PROVIDER_429") and not refusals.not_sent("not_found")


def test_the_five_places_read_it():
    attempt = {"error_class": "provider_cap", "ok": False}
    assert retest.not_measured({"background": [attempt]}) == "provider_cap"
    assert service.capacity_failure({"slots": {"background": {"failed": True}},
                                     "attempts": {"background": [attempt]}})
    defn = {"slots": [{"slot": "background"}]}
    out = value.measure(defn, {}, {"output": {}, "attempts": {"background": [dict(attempt, chars_in=10, chars_out=0)]},
                                   "latency_ms": 1}, None)
    assert out is not None


def test_a_provider_cap_then_not_found_is_not_found():
    """limits.DomainCap refuses 241601 on a public run (Refused('provider_cap')), then a member says it has no
    article: the step answers 'No encyclopedia article found', not a failed step."""
    from agent_market.necklaces.limits import Refused

    class NoRecord(Exception):
        code = "not_found"
    defn = model.load(DEFN)

    def caller(member, args, timeout_s):
        key = member.get("agent_id") or member.get("resource_id")
        if key == "sec-edgar":
            return {"legal_name": "Kodiak Sciences Inc.", "cik": "1468748", "ticker": "KOD"}
        if key == "sec-filings":
            return {"answer": "Matched SEC filer: Kodiak Sciences Inc. (SEC CIK 1468748). 2026-11-06 10-Q "
                              "(accession 0001468748-26-000050)"}
        if key == 241601:
            raise Refused("provider_cap")
        if key in (47189, 143970):
            return {}
        if key == "wikipedia-summary":
            raise NoRecord("no record")
        raise RuntimeError("not this member")
    out = runner.Runner(caller, watch_state=STATE).run(defn, {"name": "Kodiak Sciences Inc", "country": "US"})
    errors = [a["error_class"] for a in out["attempts"]["background"]]
    assert errors[0] == "provider_cap" and "not_found" in errors
    assert out["output"]["background"] == {"not_found": True, "note": runner.NOT_FOUND_NOTE}


def test_a_string_relay_error_is_read_as_its_message():
    """retest.gateway_caller: a JSON-RPC error that is a plain string is a member error, never an AttributeError."""
    import httpx

    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": "upstream exploded"})
    pacer = retest.RelayPacer(clock=lambda: 0.0, sleep=lambda s: None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        call = retest.gateway_caller(client, "https://example.test", pacer, sleep=lambda s: None)
        try:
            call({"kind": "external", "resource_id": 1, "tool": "t"}, {}, 5)
        except AttributeError:
            raise
        except Exception as exc:
            assert "upstream exploded" in str(exc)

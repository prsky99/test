"""scripts.necklace_gate check (PM 11-15 10:31): a member holds a seat only when our public relay admits it."""
import httpx

from agent_market.necklaces import model
from scripts import necklace_gate


class Relay(httpx.BaseTransport):
    def __init__(self, denied, full=()):
        self.denied, self.full, self.seen = denied, set(full), []

    def handle_request(self, request):
        import json
        rid = int(request.url.path.rsplit("/", 1)[1])
        body = json.loads(request.content)
        self.seen.append((rid, request.headers.get("X-Agentcon-QA"), body["method"], body.get("params", {}).get("arguments")))
        if rid in self.full:
            return httpx.Response(503, json={"detail": "busy"}, headers={"X-Execution-Error": "CAPACITY_EXCEEDED"})
        if rid in self.denied and body["method"] == "tools/call":     # the relay admits initialize, refuses the tool
            return httpx.Response(403, json={"detail": "This connection is not allowed."},
                                  headers={"X-Execution-Error": "POLICY_DENIED", "X-Execution-Reference": f"ref-{rid}"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ok"}]}})


def shipped_company():
    return next(d for d in model.load_valid() if d["slug"] == "company-due-diligence")


def company():
    """company-due-diligence as it was before the 11-15 terms check (58997 runnable): these tests are about the
    relay, the shipped definition's prohibited filings member is tested below."""
    import copy
    defn = copy.deepcopy(shipped_company())
    for slot in defn["slots"]:
        for m in slot["chain"]:
            m["terms"] = {"status": "unknown"}       # a member value wins over member_terms.json (58997 prohibits)
    return defn


VERIFIED = {(241601, "encyclopedia.summary.v1"), (58997, "sec.filings.v1"), (52559, "domain.lookup.v1")}
APPROVED = [["sec-edgar", "company.registry.v1"]]


NOW = 1_800_000_000.0


def prints(**override):
    """The fingerprint file as ops writes it (resources[rid], measured now), every member unchanged."""
    import time as _t
    at = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(NOW))
    resources = {str(rid): {"baseline": "a", "current": "a", "measured_at": at} for rid in (52559, 58997, 241601)}
    resources.update(override)
    return {"resources": resources}


def run(denied, full=(), fingerprints=None):
    relay = Relay(denied, full)
    ledger = dict(reserve=lambda url, system: (True, None), note=lambda *a: None,
                  pacer=type("P", (), {"wait_for": lambda self, n: None})())
    with httpx.Client(transport=relay) as client:
        out = necklace_gate.check(company(), client, "https://example.test", verified=VERIFIED, substitutes=APPROVED,
                                  probe_fn=lambda c, b, m, a: necklace_gate.probe(c, b, m, a, **ledger),
                                  prints=prints() if fingerprints is None else fingerprints, now=NOW)
    return out, relay


def test_gate_does_not_judge_a_member_without_a_fresh_fingerprint():
    """PM 12:0x (11-15): the same closed verdict as the watch; the old file shape (pearls[rid]) reads as unknown."""
    out, _ = run(set(), fingerprints={"pearls": {"58997": {"server_fp": "x"}}})
    assert out["ok"] is False
    assert any("not judged (fingerprint unknown)" in p for p in out["problems"])
    out, _ = run(set(), fingerprints=prints(**{"58997": {"baseline": "a", "current": "b", "measured_at": "2027-01-15T08:00:00Z"}}))
    filings = next(s for s in out["slots"] if s["slot"] == "filings")["members"][0]
    assert (filings["fingerprint"], filings["seat_eligible"]) == ("changed", False)
    old = prints(**{"241601": {"baseline": "a", "current": "a", "measured_at": "2026-01-01T00:00:00Z"}})
    out, _ = run(set(), fingerprints=old)
    assert any("241601 not judged (fingerprint stale)" in p for p in out["problems"])


def test_every_external_member_is_probed_with_the_gate_label():
    out, relay = run(set())
    assert sorted({rid for rid, *_ in relay.seen}) == [52559, 58997, 241601]
    assert {qa for _, qa, *_ in relay.seen} == {"necklace_gate"}
    calls = {rid: args for rid, _, method, args in relay.seen if method == "tools/call"}
    assert calls == {241601: {"query": "Apple Inc."}, 58997: {"ticker": "AAPL"}, 52559: {"domain": "apple.com"}}
    assert out["pearls"]["in_every_run"] == ["background", "filings"] and out["ok"] is True


def test_a_relay_denied_pearl_loses_its_seat_with_the_reason():
    out, _ = run({58997})
    filings = next(s for s in out["slots"] if s["slot"] == "filings")
    member = filings["members"][0]
    assert (member["relay"], member["stage"], member["error_code"], member["reference"], member["seat_eligible"]) == (
        "denied", "tools/call", "POLICY_DENIED", "ref-58997", False)
    assert filings["usable"] is False and filings["seated_lead"] is None
    assert out["pearls"]["in_every_run"] == ["background"] and out["pearls"]["met_in_every_run"] is False
    assert out["pearls"]["met_when_optional_inputs_given"] is True          # background + domain
    assert "a required slot has no member that can run" in out["problems"] and out["ok"] is False


def test_our_substitutes_hold_their_seat_without_the_relay():
    out, _ = run(set())
    registry = next(s for s in out["slots"] if s["slot"] == "registry")
    assert registry["members"][0] == {"rank": 1, "kind": "agentcon", "tool": "find_sec_company", "id": "sec-edgar",
                                      "terms": "allowed", "substitute_approved": True, "seat_eligible": True}


def test_admitted_rows_carry_empty_reason_fields_and_a_full_edge_is_not_a_denial(monkeypatch):
    monkeypatch.setattr(necklace_gate.time, "sleep", lambda s: None)
    out, relay = run(set(), full={52559})
    background = next(s for s in out["slots"] if s["slot"] == "background")["members"][0]
    assert (background["error_code"], background["reference"]) == (None, None)
    domain = next(s for s in out["slots"] if s["slot"] == "domain")["members"][0]
    assert (domain["relay"], domain["error_code"], domain["seat_eligible"]) == ("our_capacity", "CAPACITY_EXCEEDED", False)
    assert [r for r in relay.seen if r[0] == 52559].__len__() == 2                 # retried once
    assert any("not judged (our_capacity" in p for p in out["problems"])


def test_our_relay_pace_and_a_provider_failure_are_not_denials():
    import httpx as hx

    class Paced(hx.BaseTransport):
        def handle_request(self, request):
            import json as js
            if js.loads(request.content)["method"] == "initialize":
                return hx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            return hx.Response(429, json={"detail": "Too many agent executions"})
    ledger = dict(reserve=lambda url, system: (True, None), note=lambda *a: None,
                  pacer=type("P", (), {"wait_for": lambda self, n: None})())
    member = {"kind": "external", "resource_id": 1, "tool": "t", "registrable_domain": "a.com"}
    with hx.Client(transport=Paced()) as client:
        assert necklace_gate.probe(client, "https://x.test", member, {}, **ledger)["relay"] == "throttled"

    class Unconfirmed(hx.BaseTransport):
        def handle_request(self, request):
            return hx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                          "error": {"code": -32000, "message": "The execution outcome is unconfirmed."}})
    with hx.Client(transport=Unconfirmed()) as client:
        assert necklace_gate.probe(client, "https://x.test", member, {}, **ledger)["relay"] == "failed"


def test_our_relay_429_never_pauses_a_provider_in_the_ledger():
    """11-15 11:42 incident: the check wrote our relay's 429 to the ledger and paused four providers for the day."""
    import httpx as hx
    noted = []

    class Paced(hx.BaseTransport):
        def handle_request(self, request):
            return hx.Response(429, json={"detail": "Too many agent executions: 10 tools/call or messages a minute"})
    ledger = dict(reserve=lambda url, system: (True, None), note=lambda *a, **kw: noted.append(a + (kw.get("evidence"),)),
                  pacer=type("P", (), {"wait_for": lambda self, n: None})())
    member = {"kind": "external", "resource_id": 1, "tool": "t", "registrable_domain": "a.com"}
    with hx.Client(transport=Paced()) as client:
        assert necklace_gate.probe(client, "https://x.test", member, {}, **ledger)["relay"] == "throttled"
    assert noted == []

    class ProviderPause(hx.BaseTransport):
        def handle_request(self, request):
            return hx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                          "error": {"message": "provider asked to pause", "data": {"retry_after": 60}}})
    with hx.Client(transport=ProviderPause()) as client:
        necklace_gate.probe(client, "https://x.test", member, {}, **ledger)
    assert [n[2] for n in noted] == [429]                    # a real provider pause is still reported
    assert noted[0][3]["origin"] == "provider_rpc" and noted[0][3]["retry_after"] == 60   # with its evidence


def test_gate_days_keep_provider_domains_apart():
    """PM 11:4x decision 4: necklaces sharing a provider domain go on different days, at most five a day."""
    defs = {d["slug"]: d for d in model.load_all()}
    days = necklace_gate.gate_days([defs[s] for s in ("quakes-near-address", "book-author-brief",
                                                      "website-trust-brief", "company-due-diligence")], ordered=True)
    assert [d["slug"] for d in days[0]] == ["quakes-near-address", "book-author-brief", "website-trust-brief"]   # 11-17
    assert [d["slug"] for d in days[1]] == ["company-due-diligence"]
    for day in days:
        seen = set()
        for d in day:
            mine = {m["registrable_domain"] for s in d["slots"] for m in s["chain"] if m.get("kind") == "external"}
            assert not mine & seen
            seen |= mine
        assert len(day) <= 5
    company_day = next(day for day in days if any(d["slug"] == "company-due-diligence" for d in day))
    assert not {"book-author-brief", "website-trust-brief"} & {d["slug"] for d in company_day}   # shared pearls



def test_a_slot_whose_only_member_is_prohibited_is_not_ready_and_never_called():
    """PM 12:46 (11-15): 58997's terms prohibit our use; the filings slot stays required and empty, the gate says
    it is not ready and why, and nothing is sent to filings.tools."""
    relay = Relay(set())
    ledger = dict(reserve=lambda url, system: (True, None), note=lambda *a, **kw: None,
                  pacer=type("P", (), {"wait_for": lambda self, n: None})())
    with httpx.Client(transport=relay) as client:
        out = necklace_gate.check(shipped_company(), client, "https://example.test", verified=VERIFIED,
                                  substitutes=APPROVED, prints=prints(), now=NOW,
                                  probe_fn=lambda c, b, m, a: necklace_gate.probe(c, b, m, a, **ledger))
    assert 58997 not in {rid for rid, *_ in relay.seen}
    filings = next(s for s in out["slots"] if s["slot"] == "filings")
    assert filings["usable"] is False and filings["terms_prohibited"] == [58997] and filings["members"] == []
    assert any(p.startswith("slot filings: not ready") and "terms prohibit 58997" in p for p in out["problems"])
    assert out["ok"] is False


def test_a_prohibited_member_is_never_seated_even_if_a_chain_kept_it(monkeypatch):
    """PM 12:46 point 3: a prohibited member as a lead fails the gate (second lock behind runtime_chain)."""
    defn = company()
    defn["slots"][1]["chain"][0]["terms"] = {"status": "prohibits", "source": "https://x.example/terms",
                                             "checked_at": "2026-11-15"}
    monkeypatch.setattr(necklace_gate, "runtime_chain", lambda slot, slug, state: slot["chain"])
    relay = Relay(set())
    with httpx.Client(transport=relay) as client:
        out = necklace_gate.check(defn, client, "https://example.test", verified=VERIFIED, substitutes=APPROVED,
                                  prints=prints(), now=NOW, probe_fn=lambda *a: {"relay": "admitted"})
    background = next(s for s in out["slots"] if s["slot"] == "background")
    assert background["members"][0]["seat_eligible"] is False and background["members"][0]["why"] == "terms_prohibits"
    assert any("terms prohibit our use" in p for p in out["problems"]) and out["ok"] is False


def test_invokera_necklaces_go_on_different_days_and_one_domain_is_a_warning():
    """PM 13:42: 38608 (book), 38613 (holidays) and 38614 (time) share invokera.com."""
    from agent_market.necklaces import templates
    book = next(d for d in model.load_all() if d["slug"] == "book-author-brief")
    holidays = templates.stamp("airport", "holidays")
    days = necklace_gate.gate_days([book, holidays], ordered=True)
    assert [[d["slug"] for d in day] for day in days] == [["book-author-brief"], ["holidays-at-airport"]]
    both = {"slug": "x", "slots": [
        {"slot": "a", "required": True, "chain": [{"kind": "external", "state": "active", "resource_id": 38614,
                                                   "tool": "t", "registrable_domain": "invokera.com"}]},
        {"slot": "b", "required": True, "chain": [{"kind": "external", "state": "active", "resource_id": 38613,
                                                   "tool": "t", "registrable_domain": "invokera.com"}]}]}
    assert necklace_gate.shared_domain_warnings(both) == [
        "slots a and b rest only on external members of invokera.com (one failure domain)"]
    assert necklace_gate.shared_domain_warnings(book) == []

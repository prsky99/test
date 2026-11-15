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


def company():
    return next(d for d in model.load_valid() if d["slug"] == "company-due-diligence")


VERIFIED = {(241601, "encyclopedia.summary.v1"), (58997, "sec.filings.v1"), (52559, "domain.lookup.v1")}
APPROVED = [["sec-edgar", "company.registry.v1"]]


def run(denied, full=()):
    relay = Relay(denied, full)
    ledger = dict(reserve=lambda url, system: (True, None), note=lambda *a: None)
    with httpx.Client(transport=relay) as client:
        out = necklace_gate.check(company(), client, "https://example.test", verified=VERIFIED, substitutes=APPROVED,
                                  probe_fn=lambda c, b, m, a: necklace_gate.probe(c, b, m, a, **ledger))
    return out, relay


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
                                      "substitute_approved": True, "seat_eligible": True}


def test_admitted_rows_carry_empty_reason_fields_and_a_full_edge_is_not_a_denial(monkeypatch):
    monkeypatch.setattr(necklace_gate.time, "sleep", lambda s: None)
    out, relay = run(set(), full={52559})
    background = next(s for s in out["slots"] if s["slot"] == "background")["members"][0]
    assert (background["error_code"], background["reference"]) == (None, None)
    domain = next(s for s in out["slots"] if s["slot"] == "domain")["members"][0]
    assert (domain["relay"], domain["error_code"], domain["seat_eligible"]) == ("our_capacity", "CAPACITY_EXCEEDED", False)
    assert [r for r in relay.seen if r[0] == 52559].__len__() == 2                 # retried once
    assert any("our edge was full" in p for p in out["problems"])

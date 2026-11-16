"""C14 (PM 11-16 20:21): only members whose terms are allowed or silent run; unknown waits, prohibits never runs."""
from agent_market.necklaces import members, model, retest, watch


def slot_of(*members_):
    return {"slot": "papers", "contract": "papers.search.v1", "required": True, "fanout": 2, "chain": list(members_)}


def ext(rid):
    return {"kind": "external", "resource_id": rid, "tool": "t", "registrable_domain": "x.example", "state": "active",
            "input_map": {}}


def test_unknown_and_prohibited_members_are_not_run_or_measured_alone(monkeypatch):
    status = {1: "allowed", 2: "silent", 3: "unknown", 4: "prohibits"}
    monkeypatch.setattr(model, "terms_status", lambda m: status.get(m.get("resource_id"), "unknown"))
    slot = slot_of(ext(1), ext(2), ext(3), ext(4))
    assert [m["resource_id"] for m in watch.runtime_chain(slot, "s", {})] == [1, 2]
    defn = {"slug": "s", "slots": [slot]}
    assert [m["resource_id"] for _, m in retest.single_members(defn, "papers", {})] == [1, 2]
    assert model.runnable(ext(2)) and not model.runnable(ext(3)) and not model.runnable(ext(4))


def test_engine_caller_hands_the_slot_time_to_the_registered_call():
    """C05 (PM 11-16): engine_caller passes the slot's remaining time on; before, the proxy got no timeout."""
    from agent_market.necklaces import runner
    seen = {}

    class Engine:
        def _call_registered(self, node, args, binding=None, *, timeout=None):
            seen.update(node=node, args=args, timeout=timeout)
            return {"ok": True}
    call = runner.engine_caller(Engine())
    member = {"kind": "external", "resource_id": 39577, "tool": "search_papers"}
    assert call(member, {"query": "x"}, 1.25) == {"ok": True}
    assert seen["timeout"] == 1.25 and seen["node"]["resource_id"] == 39577


def test_our_own_agents_run_by_source_licence_or_by_their_substitute_gate(monkeypatch):
    """PM 11-16 22:xx: a catalogue fallback whose sources name a licence is allowed; an approved or provisional
    substitute runs while its terms are not on file; a prohibition stops even our own."""
    from agent_market.necklaces import model as m
    own = {"kind": "agentcon", "agent_id": "tz-time", "tool": "get_local_time"}
    monkeypatch.setattr(m, "terms_status", lambda member: {"tz-time": "allowed", "new-agent": "unknown",
                                                           "banned": "prohibits"}[member["agent_id"]])
    assert m.runnable(own)
    new = {"kind": "agentcon", "agent_id": "new-agent", "tool": "t"}
    assert not m.runnable(new)
    assert m.runnable(dict(new, substitute_state="approved")) and m.runnable(dict(new, substitute_state="provisional"))
    assert not m.runnable({"kind": "agentcon", "agent_id": "banned", "tool": "t", "substitute_state": "approved"})
    assert not m.runnable({"kind": "external", "agent_id": "new-agent", "resource_id": 9, "tool": "t",
                           "substitute_state": "approved"})

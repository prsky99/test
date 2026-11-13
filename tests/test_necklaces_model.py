import copy

import pytest

from agent_market.necklaces import model


def ext(rid, domain, tool="search_items", **kw):
    m = {"kind": "external", "resource_id": rid, "tool": tool, "registrable_domain": domain,
         "upstream": ["src"], "read_only_hint": True, "destructive_hint": False,
         "idempotent_hint": True, "resend_safe": True, "state": "active", "input_map": {"q": "{{input.q}}"}}
    m.update(kw)
    return m


def own(rid, agent_id="owned", **kw):
    m = {"kind": "agentcon", "agent_id": agent_id, "resource_id": rid, "tool": "search_owned",
         "registrable_domain": "agentconcierge.biz", "upstream": ["src2"], "read_only_hint": True,
         "destructive_hint": False, "idempotent_hint": True, "resend_safe": True, "state": "active",
         "input_map": {"q": "{{input.q}}"}}
    m.update(kw)
    return m


def base():
    return {
        "slug": "topic-brief", "version": 1, "status": "candidate", "name": "Topic brief",
        "summary": "Two sources in one answer.",
        "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
        "budget_ms": {"total": 5000, "slot": 3500},
        "slots": [
            {"slot": "papers", "contract": "x.v1", "required": True, "fanout": 1,
             "chain": [ext(1, "a.com"), ext(2, "b.com"), own(10)]},
            {"slot": "news", "contract": "y.v1", "required": True, "fanout": 1,
             "chain": [ext(3, "c.com"), ext(4, "d.com"), own(11, agent_id="owned2")]},
        ],
    }


def errors(defn):
    return model.validate(defn, check_contracts=False)


def test_valid_definition_has_no_errors_and_no_gaps():
    defn = base()
    assert errors(defn) == []
    assert model.readiness(defn) == []


@pytest.mark.parametrize("slug", ["Topic", "ab", "topic--brief", "-topic", "t" * 41, "topic_brief"])
def test_slug_rule(slug):
    defn = base()
    defn["slug"] = slug
    assert any("slug" in e for e in errors(defn))


def test_agentcon_members_must_come_last_and_at_most_two():
    defn = base()
    chain = defn["slots"][0]["chain"]
    chain.insert(0, chain.pop())  # Agentcon first
    assert any("after every external" in e for e in errors(defn))
    defn = base()
    defn["slots"][0]["chain"] += [own(12, agent_id="o3"), own(13, agent_id="o4")]
    assert any("at most 2 Agentcon" in e for e in errors(defn))


def test_external_member_needs_explicit_read_only_hint():
    defn = base()
    del defn["slots"][0]["chain"][0]["read_only_hint"]
    assert any("readOnlyHint" in e for e in errors(defn))
    defn = base()
    defn["slots"][0]["chain"][0]["destructive_hint"] = True
    assert any("destructive" in e for e in errors(defn))


@pytest.mark.parametrize("tool", ["create_order", "send_email", "pay_invoice", "execute_marketplace_tool", "submit_offer"])
def test_action_and_payment_verbs_are_rejected_even_with_read_only_hint(tool):
    defn = base()
    defn["slots"][0]["chain"][0]["tool"] = tool
    assert any("action, write or payment" in e for e in errors(defn))


def test_resend_safe_needs_idempotent_hint():
    defn = base()
    defn["slots"][0]["chain"][0]["idempotent_hint"] = None
    assert any("resend_safe" in e for e in errors(defn))


def test_one_failure_domain_owns_at_most_one_slot():
    defn = base()
    defn["slots"][1]["chain"][0]["registrable_domain"] = "a.com"
    assert any("failure domain a.com" in e for e in errors(defn))


def test_necklace_needs_two_required_slots_or_a_fanout():
    defn = base()
    defn["slots"][1]["required"] = False
    assert any("two required slots" in e for e in errors(defn))
    defn["slots"] = defn["slots"][:1]
    defn["slots"][0]["fanout"] = 2
    assert errors(defn) == []


def test_fanout_cannot_exceed_external_members():
    defn = base()
    defn["slots"][0]["fanout"] = 3
    assert any("fanout 3" in e for e in errors(defn))


def test_budget_respects_complex_answer_limit():
    defn = base()
    defn["budget_ms"] = {"total": 6000, "slot": 3000}
    assert any("budget_ms.total" in e for e in errors(defn))


def test_readiness_reports_missing_members_and_shared_domain():
    defn = base()
    slot = defn["slots"][0]
    slot["chain"][1]["state"] = "pending_test"
    slot["chain"][2]["state"] = "planned"
    gaps = model.readiness(defn)
    assert "slot papers: 1 active external members, need 2" in gaps
    assert "slot papers: no active Agentcon member" in gaps
    assert "slot papers: no member outside the primary's failure domain" in gaps
    assert any("not a strict pearl" in g for g in model.readiness(base(), pearl_ids={99}))


def test_digest_ignores_lifecycle_fields_but_not_chain_changes():
    defn = base()
    moved = copy.deepcopy(defn)
    moved["status"] = "live"
    moved["notes"] = "approved"
    assert model.digest(moved) == model.digest(defn)
    changed = copy.deepcopy(defn)
    changed["slots"][0]["chain"].reverse()
    assert model.digest(changed) != model.digest(defn)


def test_shipped_definitions_are_valid():
    defs = model.load_valid()
    assert {d["slug"] for d in defs} >= {"package-risk-audit", "cve-incident-brief"}
    for defn in defs:
        for slot in defn["slots"]:
            for member in slot["chain"]:
                assert "tx_hash" not in member["input_map"] and "agent_id" not in member["input_map"]

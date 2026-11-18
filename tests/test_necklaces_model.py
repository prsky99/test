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
        "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"],
                         "additionalProperties": False},
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
    chain.insert(0, chain.pop())  # AgentValCon fallback first
    assert any("after every external" in e for e in errors(defn))
    defn = base()
    defn["slots"][0]["chain"] += [own(12, agent_id="o3"), own(13, agent_id="o4")]
    assert any("at most 2 AgentValCon fallback" in e for e in errors(defn))


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
    assert "slot papers: no active AgentValCon fallback member" in gaps
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


def test_roles_without_fallback_are_optional_with_two_externals_only():
    defn = base()
    defn["slots"].append({"slot": "price", "contract": "crypto.price.v1", "required": True, "fanout": 1,
                          "chain": [ext(5, "e.com")]})
    errs = errors(defn)
    assert any("may only be an optional slot" in e for e in errs)
    assert any("at least two external members" in e for e in errs)
    defn["slots"][-1].update(required=False, chain=[ext(5, "e.com"), ext(6, "f.com")])
    assert errors(defn) == []


def test_a_necklace_stays_within_five_required_slots_and_three_stages():
    """PM E8 (11-15), raised 16:09 (user instruction: 3+ agents): at most 5 required slots, still 3 stages."""
    import copy
    defn = base()
    template = copy.deepcopy(defn["slots"][0])
    for n in range(len(defn["slots"]), model.MAX_REQUIRED_SLOTS + 1):
        extra = copy.deepcopy(template)
        extra["slot"] = f"extra_{n}"
        for i, m in enumerate(extra["chain"]):
            if m.get("resource_id"):
                m["resource_id"] = 900 + 10 * n + i
            m["registrable_domain"] = f"d{n}{i}.example"
        defn["slots"].append(extra)
    assert any("at most 5 required slots" in e for e in model.validate(defn, check_contracts=False))
    defn["slots"][-1]["required"] = False
    assert not any("required slots" in e for e in model.validate(defn, check_contracts=False))
    names = [s["slot"] for s in defn["slots"]]
    for i in range(1, len(names)):
        defn["slots"][i]["depends_on"] = [names[i - 1]]
    assert any("at most 3 stages" in e for e in model.validate(defn, check_contracts=False))


def test_terms_of_use_status_per_member():
    """PM 13:0x (11-15): a terms field per member; fallbacks are confirmed by the licences in their catalogue."""
    member = ext(1, "a.example")
    assert model.terms_status(member) == "unknown"
    for status in ("allowed", "silent", "prohibits"):
        checked = dict(member, terms={"status": status, "source": "https://a.example/terms", "checked_at": "2026-11-15"})
        assert model.terms_status(checked) == status and not model._member_errors("s", 0, checked)
    assert model._member_errors("s", 0, dict(member, terms={"status": "allowed"}))        # no source or day
    assert model._member_errors("s", 0, dict(member, terms={"status": "maybe"}))
    assert not model._member_errors("s", 0, dict(member, terms={"status": "unknown"}))
    assert model.terms_status({"kind": "agentcon", "agent_id": "usgs-quakes"}) == "allowed"
    assert model.terms_status({"kind": "agentcon", "agent_id": "not-a-fallback"}) == "unknown"
    report = model.terms_report(model.load_all())
    assert sum(report["members"].values()) == len(report["rows"])



def test_our_own_registered_agents_take_their_terms_from_the_member():
    """PM 12:46: 133018, 133019 and 133023 are judged by their source's terms written on the member."""
    own_agent = {"kind": "agentcon", "agent_id": "owned-news", "resource_id": 999133018, "tool": "t"}   # not in the table
    assert model.terms_status(own_agent) == "unknown"
    # PM 17:02: the shared table's verdict on our own data agent counts (133018 was Hacker News: prohibits, 05d2bc0f;
    # GDELT only since 11-16 and allowed in the table, PM 11-18)
    assert model.terms_status(dict(own_agent, resource_id=133018)) == "allowed"
    checked = dict(own_agent, terms={"status": "silent", "source": "https://source.example/", "checked_at": "2026-11-16"})
    assert model.terms_status(checked) == "silent"
    banned = {"kind": "agentcon", "agent_id": "usgs-quakes", "terms": {"status": "prohibits",
              "source": "https://x.example/", "checked_at": "2026-11-16"}}
    assert model.terms_status(banned) == "prohibits"          # a checked member value wins over the catalogue


def test_terms_come_from_one_table_for_every_definition_and_stamp():
    """PM 13:53: member_terms.json holds each member's terms once; stamps and definitions read the same value."""
    from agent_market.necklaces import templates
    assert model.terms_status({"kind": "external", "resource_id": 58997}) == "prohibits"
    assert model.terms_status({"kind": "external", "resource_id": 37322}) == "allowed"
    assert model.terms_status({"kind": "external", "resource_id": 999999999}) == "unknown"
    quakes = next(s for s in templates.stamp("airport", "quakes")["slots"] if s["slot"] == "quakes")
    assert model.terms_status(quakes["chain"][0]) == "allowed"            # 37322, never copied into the stamp
    for defn in model.load_all():                                          # one source: no inline copies left
        assert not any(m.get("terms") for s in defn["slots"] for m in s["chain"]), defn["slug"]


def test_topic_background_leads_with_the_verified_encyclopedia_pearl():
    defn = model.load("agent_market/necklaces/definitions/topic-evidence-brief.json")
    background = next(s for s in defn["slots"] if s["slot"] == "background")
    assert model.primary(background)["resource_id"] == 241601


def test_scope_notice_fits_what_the_page_shows():
    """Growth bb9ead9a shows the notice on the page and in the MCP tool, and hides one over 600 characters."""
    defn = base()
    defn["scope_notice"] = "x" * 601
    assert any("600 characters" in e for e in model.validate(defn, check_contracts=False))
    defn["scope_notice"] = "National public holidays only."
    assert not any("scope_notice" in e for e in model.validate(defn, check_contracts=False))

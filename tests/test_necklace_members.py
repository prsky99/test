"""PM 16:03 (user instruction d4670360): provisional members, standing order and upgrade lines."""
import json
import time

from agent_market.necklaces import judge, members, model
from agent_market.necklaces.watch import runtime_chain, upgrade_lines
from tests.test_necklaces_model import base

NOW = time.time()


def iso(days_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(NOW - days_ago * 86400))


def snapshot():
    return {"agents": {
        "1": {"roles": [{"role": "x.v1", "outcome": "succeeded", "score": 92, "verified_pearl": True, "tested_at": iso(1)}]},
        "2": {"roles": [{"role": "x.v1", "outcome": "succeeded", "score": 79.2, "tested_at": iso(2)}]},
        "3": {"roles": [{"role": "y.v1", "outcome": "succeeded", "score": 69.9, "tested_at": iso(1)}]},
        "4": {"roles": [{"role": "y.v1", "outcome": "succeeded", "score": 80, "tested_at": iso(8)}]},
        "5": {"roles": [{"role": "y.v1", "outcome": "failed", "score": 90, "tested_at": iso(1)}]}}}


def test_the_bar_for_a_provisional_external_member():
    found = members.external_standing(snapshot(), NOW)
    assert found == {"1|x.v1": "verified_pearl", "2|x.v1": "provisional"}       # 69.9, 8 days old, failed: not
    assert members.PROVISIONAL == {"min_score": 70.0, "days": 7}


def test_standing_needs_read_only_active_and_terms_not_prohibiting():
    block = {"external": {"1|x.v1": "provisional"}, "own": {}}
    m = {"kind": "external", "resource_id": 1, "tool": "t", "read_only_hint": True, "destructive_hint": False}
    assert members.standing(m, "x.v1", block) == "provisional"
    assert members.standing(dict(m, read_only_hint=False), "x.v1", block) is None
    assert members.standing(dict(m, destructive_hint=True), "x.v1", block) is None
    assert members.standing(dict(m, state="planned"), "x.v1", block) is None
    assert members.standing(m, "x.v1", None) is None


def test_a_pearl_leads_a_provisional_member_and_an_unranked_one_goes_last():
    defn = base()
    slot = defn["slots"][0]                     # chain 1, 2, own 10
    block = {"external": {"2|x.v1": "verified_pearl", "1|x.v1": "provisional"}, "own": {}}
    chain = runtime_chain(slot, defn["slug"], {"standing": block})
    assert [m.get("resource_id") for m in chain if m["kind"] == "external"] == [2, 1]
    assert [m.get("standing") for m in chain if m["kind"] == "external"] == ["verified_pearl", "provisional"]
    block = {"external": {"2|x.v1": "provisional"}, "own": {}}
    chain = runtime_chain(slot, defn["slug"], {"standing": block})
    assert [m.get("resource_id") for m in chain if m["kind"] == "external"] == [2, 1]     # unranked 1 after
    assert [m.get("resource_id") for m in runtime_chain(slot, defn["slug"], {}) if m["kind"] == "external"] == [1, 2]


def test_a_provisional_own_substitute_runs_and_counts(tmp_path):
    defn = base()
    slot = defn["slots"][1]
    own = next(m for m in slot["chain"] if m["kind"] == "agentcon")
    own["state"] = "planned"
    approvals = tmp_path / "approvals.json"
    approvals.write_text(json.dumps({"substitutes": [
        {"agent_id": own["agent_id"], "slot_role": "y.v1", "state": "provisional", "at": "2026-11-15T16:30:00+0900"}]}))
    states = judge.load_substitute_states(approvals)
    assert states == {f"{own['agent_id']}|y.v1": "provisional"}
    chain = runtime_chain(slot, defn["slug"], {"standing": {"external": {}, "own": states}})
    mine = next(m for m in chain if m["kind"] == "agentcon")
    assert mine["substitute_state"] == "provisional" and mine["standing"] == "provisional" and members.counted(mine)
    assert not any(m["kind"] == "agentcon" for m in runtime_chain(slot, defn["slug"], {"standing": {"external": {}}}))


def test_counted_falls_back_to_the_pearl_flag_without_standing():
    assert members.counted({"pearl": True}) and not members.counted({})
    assert not members.counted({"pearl": True, "standing": None})


def test_upgrade_lines_name_slots_a_pearl_can_lead(tmp_path):
    defn = base()
    block = {"external": {"2|x.v1": "verified_pearl", "3|y.v1": "provisional"}, "own": {}}
    roles = {"y.v1": {"final_pearl": 99}}
    found = members.upgrades([defn], block, roles)
    assert {(f["slot"], f["pearl"], f["in_chain"]) for f in found} == {("papers", 2, True), ("news", 99, False)}
    path = tmp_path / "upgrades.jsonl"
    upgrade_lines([defn], dict(block, snapshot_generated="g1"), NOW, path)
    line = json.loads(path.read_text())
    assert line["snapshot"] == "g1" and "at" in line


def test_demand_is_warned_not_refused():
    defn = base()
    assert model.validate(defn, check_contracts=False) == []
    found = model.warnings(defn)
    assert any("demand is empty" in w for w in found) and any("2 required roles" in w for w in found)
    defn["demand"] = "Top 5 topic in our query log, week of 11-09 (search and RAG)"
    assert not any("demand" in w for w in model.warnings(defn)) and model.digest(defn) == model.digest(base())


def test_members_json_tells_approved_and_provisional_apart():
    defn = base()
    own = next(m for m in defn["slots"][1]["chain"] if m["kind"] == "agentcon")
    own["state"] = "planned"
    block = {"external": {"1|x.v1": "verified_pearl"}, "own": {f"{own['agent_id']}|y.v1": "provisional"}}
    rows = judge.members([defn], standing=block)["members"]
    by = {(r["slot"], r["resource_id"] or r["agent_id"]): r for r in rows}
    assert by[("papers", 1)]["standing"] == "verified_pearl" and by[("papers", 2)]["standing"] is None
    mine = by[("news", own.get("resource_id") or own["agent_id"])]
    assert mine["substitute_state"] == "provisional" and mine["standing"] == "provisional"
    assert "standing" not in judge.members([defn])["members"][0]


def test_member_rules_are_numbers_for_the_methodology_page():
    got = members.rules({"verified_rule": {"min_score": 85, "successes_on_different_days": 2}})
    assert got["verified_pearl"] == {"min_score": 85, "successes_on_different_days": 2}
    assert got["provisional"]["min_score"] == members.PROVISIONAL["min_score"] and got["provisional"]["within_days"] == 7


def test_our_provisional_member_leads_before_an_external_one_that_passes_neither_bar():
    defn = base()
    slot = defn["slots"][1]                     # chain 3, 4, own owned2
    block = {"external": {}, "own": {"owned2|y.v1": "provisional"}}
    own = next(m for m in slot["chain"] if m["kind"] == "agentcon")
    own["state"] = "planned"
    chain = runtime_chain(slot, defn["slug"], {"standing": block})
    assert [m.get("agent_id") or m.get("resource_id") for m in chain] == ["owned2", 3, 4]
    running = dict(defn, slots=[dict(s, chain=runtime_chain(s, defn["slug"], {"standing": block})) for s in defn["slots"]])
    lead = next(p for p in judge.pearls(running, set()) if p["role"] == "news")
    assert (lead["kind"], lead["agent_id"], lead["standing"]) == ("agentcon", "owned2", "provisional")
    assert [a.get("resource_id") for a in lead["alternates"]] == [3, 4]


def test_our_own_data_agent_prohibited_by_the_terms_table_is_never_called():
    """PM 17:02: 133018 (our Hacker News data agent, kind agentcon with a resource_id) is prohibits in the terms
    table; the chain drops it and the runner never calls it."""
    from agent_market.necklaces import runner
    hn = {"kind": "agentcon", "resource_id": 133018, "tool": "search_technology_news", "read_only_hint": True,
          "destructive_hint": False, "state": "active", "registrable_domain": "agentconcierge.biz", "upstream": ["hn"],
          "input_map": {"query": "{{input.q}}"}}
    assert model.terms_status(hn) == "prohibits"
    crossref = dict(hn, resource_id=133019, tool="search_research_papers")
    assert model.terms_status(crossref) == "allowed"
    defn = base()
    defn["slots"][1]["chain"] = [hn]
    assert runtime_chain(defn["slots"][1], defn["slug"], {}) == []
    called = []

    def caller(member, args, timeout_s):
        called.append(member.get("resource_id") or member.get("agent_id"))
        return {"items": [{"title": "x"}]}
    from agent_market.necklaces.watch import runtime_definition
    runner.Runner(caller).run(runtime_definition(defn, {}), {"q": "lodash"})
    assert 133018 not in called


def test_each_step_says_how_many_outside_members_can_run_and_count():
    """PM 11-16 06:5x (growth): pearls[i] carries external_usable (outside members in the running chain with a
    counted standing) and external_listed (outside members in the running chain)."""
    defn = base()
    block = {"external": {"1|x.v1": "verified_pearl"}, "own": {}}
    running = dict(defn, slots=[dict(s, chain=runtime_chain(s, defn["slug"], {"standing": block})) for s in defn["slots"]])
    by_role = {p["role"]: p for p in judge.pearls(running, {(1, "x.v1")})}
    assert (by_role["papers"]["external_usable"], by_role["papers"]["external_listed"]) == (1, 2)
    assert (by_role["news"]["external_usable"], by_role["news"]["external_listed"]) == (0, 2)

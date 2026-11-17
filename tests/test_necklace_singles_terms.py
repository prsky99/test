"""A member whose terms prohibit our use is not measured alone either (11-16: 34550 and 34807 left the topic chain
by terms, but the singles list still named them, so the singles step would have called them directly).

11-17: topic v2's papers step has no external member any more and its singles follow the whole-task rule
(tests/test_necklace_topic_singles.py), so this checks a necklace still measured on its contrast slot's external
members."""
from agent_market.necklaces import model, retest


def contrast_necklace():
    for defn in model.load_valid():
        slug = defn["slug"]
        if slug in retest.TASK_GRADERS or slug in retest.SINGLE_TASK_GRADERS or slug not in retest.CONTRAST:
            continue
        slot = next((s for s in defn["slots"] if s["slot"] == retest.CONTRAST[slug]), None)
        if slot and model.live_members(slot, "external"):
            return defn, slot
    raise AssertionError("no necklace measured on its contrast slot's external members")


def test_singles_skip_a_member_whose_terms_prohibit(monkeypatch):
    defn, slot = contrast_necklace()
    ids = [m["resource_id"] for m in model.live_members(slot, "external")]
    banned = ids[0]
    monkeypatch.setattr(model, "terms_status", lambda m: "prohibits" if m.get("resource_id") == banned else "silent")
    got = [m["resource_id"] for _, m in retest.single_members(defn, slot["slot"], {})]
    assert banned not in got and got == [i for i in ids if i != banned]

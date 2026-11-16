"""A member whose terms prohibit our use is not measured alone either (11-16: 34550 and 34807 left the topic chain
by terms, but the singles list still named them, so the singles step would have called them directly)."""
from agent_market.necklaces import model, retest


def test_singles_skip_a_member_whose_terms_prohibit(monkeypatch):
    defn = next(d for d in model.load_valid() if d["slug"] == "topic-evidence-brief")
    papers = next(s for s in defn["slots"] if s["slot"] == "papers")
    ids = [m["resource_id"] for m in model.live_members(papers, "external")]
    banned = ids[0]
    monkeypatch.setattr(model, "terms_status", lambda m: "prohibits" if m.get("resource_id") == banned else "silent")
    got = [m["resource_id"] for _, m in retest.single_members(defn, "papers", {})]
    assert banned not in got and got == [i for i in ids if i != banned]

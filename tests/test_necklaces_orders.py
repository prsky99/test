"""After a necklace request (PM 11-15 14:57 part 3): classification and the finished-notice bundle."""
from datetime import datetime, timedelta, timezone

import pytest

from agent_market.necklaces import orders

DEFS = [{"slug": "book-author-brief", "name": "Book and author brief",
         "slots": [{"slot": "book", "contract": "book.search.v1"}, {"slot": "author", "contract": "encyclopedia.summary.v1"}]}]
ROLES = {"book.search.v1": {"final_pearl": 38608}, "encyclopedia.summary.v1": {"final_pearl": 241601},
         "geocode.address.v1": {"final_pearl": 264482}, "earthquake.feed.v1": {"final_pearl": 178542},
         "timezone.time.v1": {"provisional_pearl": 38614}, "airport.lookup.v1": {"final_pearl": 86011},
         "weather.forecast.v1": {}, "holiday.calendar.v1": {"provisional_pearl": 38613}}


def req(task, wanted="the answer"):
    return {"task": task, "example_input": "x", "wanted_output": wanted}


def live_entry(now=None):
    now = now or datetime.now(timezone.utc)
    stamp = (now - timedelta(hours=1)).isoformat()
    pearl = {"resource_id": 38608, "role": "book", "pearl": True,
             "alternates": [{"kind": "external"}, {"kind": "agentcon", "agent_id": "book-own", "tool": "t"}]}
    return {"slug": "book-author-brief", "name": "Book and author brief", "status": "live", "gate_passed_at": stamp,
            "pearls": [pearl, dict(pearl, resource_id=241601, role="author")],
            "quality": {"tested_at": stamp, "delta_pp": 12.0, "success_rate": 0.97},
            "input_schema": {"properties": {"title": {"type": "string"}}}, "example_input": {"title": "Dune"},
            "scope_notice": "Books in English only.", "fallback": {"depth": "agentvalcon", "slots_without_own": []},
            "comparison": {"cases": 5, "measured_at": "2026-11-20", "with": {"calls": 1, "tokens": 300, "seconds": 2.3,
                           "accuracy": 1.0}, "without": {"calls": 3, "tokens": 1200, "seconds": 2.0, "accuracy": 0.8},
                           "without_full": {"calls": 8, "tokens": 9000, "seconds": 6.2, "accuracy": 0.8,
                                            "estimated": ["find_agents"]}}}


def test_existing_necklace_in_tests_answers_building_and_live_answers_its_address():
    out = orders.classify(req("Who wrote a book, with a biography of the author"), DEFS, {"necklaces": []}, ROLES)
    assert (out["class"], out["status"], out["necklace"]) == ("existing", "building", "book-author-brief")
    out = orders.classify(req("Who wrote a book, with a biography of the author"), DEFS,
                          {"necklaces": [live_entry()]}, ROLES)
    assert (out["class"], out["status"]) == ("existing", "live")
    assert out["answer"].endswith("/necklaces/book-author-brief.")
    assert out["console_status"] == "resolved" and out["admin_response"].startswith("Live: A necklace already")


def test_buildable_from_three_pearls_and_reviewing_with_two_roles_or_a_provisional_one():
    out = orders.classify(req("Earthquakes near a street address and the nearest airport"), DEFS, {}, ROLES)
    assert (out["class"], out["status"], out["reason"]) == ("buildable", "building", "buildable")
    assert out["pearls"] == {"airport.lookup.v1": 86011, "earthquake.feed.v1": 178542, "geocode.address.v1": 264482}
    out = orders.classify(req("Earthquakes near a street address"), DEFS, {}, ROLES)       # PM 16:09: 3+ roles
    assert (out["class"], out["status"], out["reason"]) == ("buildable", "reviewing", "two_roles")
    out = orders.classify(req("Local time zone and earthquakes at an airport code"), DEFS, {}, ROLES)
    assert (out["class"], out["status"], out["pending_roles"]) == ("buildable", "reviewing", ["timezone.time.v1"])


@pytest.mark.parametrize("task,reason", [
    ("Send an email to my team with today's headlines", "needs_writes_or_payments"),
    ("Buy the cheapest flight and pay with my card", "needs_writes_or_payments"),
    ("Weather forecast and public holidays for a city", "no_verified_agent_for"),
    ("Find a book by its title", "one_agent_enough"),
    ("Book, wikipedia note, earthquakes, a street address, an airport code and the weather", "too_many_parts"),
    ("Summarise the tickets in our internal Jira", "needs_login"),
    ("Find the cheapest price for a laptop across shops", "price_comparison"),
    ("Look up this person's LinkedIn profile", "people_lookup"),
    ("Summarise the vibe of my favourite band", "needs_review"),
])
def test_cannot_build_says_why(task, reason):
    out = orders.classify(req(task), [], {}, ROLES)
    assert out["reason"] == reason
    assert out["class"] == "cannot_build"
    assert out["admin_response"].startswith("Reviewing: " if reason == "needs_review" else "Cannot build: ")
    if reason == "one_agent_enough":
        assert out["card"].endswith("/agent/38608")
    if reason == "no_verified_agent_for":
        assert out["missing_roles"] == ["weather.forecast.v1"]


def test_notice_bundle_comes_from_the_snapshot_and_waits_for_the_gate(tmp_path, monkeypatch):
    import json
    folder = tmp_path / "gateway-data/necklaces"       # PM 21:33: our own fallback counts only with a passed check
    folder.mkdir(parents=True)
    (folder / "approvals.json").write_text(json.dumps({"substitutes": [
        {"resource_id": "avc:book-own", "agent_id": "book-own", "tool": "t", "state": "approved",
         "at": "2026-11-18T21:00:00+0900", "gate_record": {"connect_test": "x"}}]}))
    monkeypatch.setenv("AGENTCON_PROJECT_ROOT", str(tmp_path))
    from agent_market.concierge import necklace_surface
    snap = {"necklaces": [live_entry()]}
    bundle = orders.notice("book-author-brief", snap)
    assert bundle["address"].endswith("/necklaces/book-author-brief")
    assert bundle["run"]["http"]["url"].endswith("/api/necklaces/book-author-brief/run")
    assert bundle["run"]["http"]["json"] == {"input": {"title": "Dune"}}
    assert bundle["run"]["mcp_tool"] == necklace_surface.tool_name("book-author-brief")
    text = bundle["admin_response"]
    assert text.startswith("Live: Your necklace is ready") and bundle["console_status"] == "resolved"
    for part in ("Address: https://agentconcierge.biz/necklaces/book-author-brief", "a person opens",
                 necklace_surface.tool_name("book-author-brief"), "POST https://agentconcierge.biz/api/necklaces/",
                 '"title": "Dune"', "Scope and limits: Books in English only.",
                 "Tested fallbacks per step: book: 1 other agent, 1 of ours"):
        assert part in text, part
    if hasattr(necklace_surface, "comparison_line"):
        assert "5 cases (2026-11-20)" in text
    assert "9,000" not in text                     # PM 11-16: the estimated full value is not shown in the notice
    not_yet = dict(live_entry(), status="trial")
    with pytest.raises(LookupError):
        orders.notice("book-author-brief", {"necklaces": [not_yet]})
    with pytest.raises(LookupError):
        orders.notice("missing", snap)


def test_cannot_build_names_what_to_use_instead():
    snap = {"necklaces": [live_entry()]}
    out = orders.classify(req("Weather forecast for the town where a book was written"), DEFS, snap, ROLES)
    assert out["reason"] == "no_verified_agent_for"
    kinds = [(a["kind"], a.get("slug") or a.get("resource_id")) for a in out["alternatives"]]
    assert kinds[0] == ("necklace", "book-author-brief") and ("agent", 38608) in kinds
    assert "Instead you can use: the necklace Book and author brief" in out["admin_response"]

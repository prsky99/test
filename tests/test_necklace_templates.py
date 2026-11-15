"""Location-hub templates (100-necklace plan 4-1, PM 12:50): one hub x one consumer stamps one candidate."""
from agent_market.necklaces import model, runner, templates


def test_address_x_quakes_stamps_the_shipped_definition_members():
    stamped = templates.stamp("address", "quakes")
    shipped = model.load("agent_market/necklaces/definitions/quakes-near-address.json")
    assert stamped["slug"] == shipped["slug"] and model.validate(stamped) == []
    ids = lambda d: [[(m.get("resource_id"), m["tool"]) for m in s["chain"]] for s in d["slots"]]
    assert ids(stamped) == ids(shipped)
    assert len(stamped["slots"]) <= model.MAX_REQUIRED_SLOTS


def test_a_hub_without_the_field_goes_through_the_time_zone_bridge():
    """PM 13:42: a geocoder gives no time zone or country; the coordinates-to-time-zone bridge (own agent, contract
    name to settle with the agent team) sits between, so address and airport hubs open local-time and holidays."""
    stamped = templates.stamp("address", "local-time")
    assert [s["slot"] for s in stamped["slots"]] == ["location", "zone", "local_time"]
    assert stamped["slots"][2]["depends_on"] == ["zone"]
    assert stamped["slots"][2]["chain"][0]["input_map"] == {"timeZone": "{{slot.zone.timezone}}"}
    assert any("timezone.at_point.v1 has no file" in w for w in
               next(r for r in templates.pairs() if (r["hub"], r["consumer"]) == ("address", "holidays"))["why"])
    assert runner.slot_reference_problems(stamped) == []
    assert runner.normalize("timezone.at_point.v1", {"timezone": "Asia/Tokyo", "country_code": "jp"}, {}) == {
        "timezone": "Asia/Tokyo", "country_code": "JP"}
    assert runner.normalize("timezone.at_point.v1", "The zone is Europe/Paris.", {})["timezone"] == "Europe/Paris"
    assert runner.normalize("timezone.at_point.v1", {"note": "ocean"}, {}) is None


def test_waiting_leads_are_planned_and_the_ip_hub_needs_a_rule():
    rows = {(r["hub"], r["consumer"]): r for r in templates.pairs()}
    assert rows[("airport", "quakes")]["valid"] and rows[("airport", "quakes")]["waiting_for"] == []
    assert rows[("airport", "holidays")]["valid"] and rows[("airport", "holidays")]["waiting_for"] == [38613]
    assert not rows[("ip", "local-time")]["valid"]
    assert any("no AgentValCon fallback" in w for w in rows[("ip", "local-time")]["why"])
    holidays = templates.stamp("airport", "holidays")
    assert "year" in holidays["input_schema"]["required"]
    assert model.live_members(holidays["slots"][1], "external") == []      # 38613 planned: not ready yet


def test_the_hub_stages_country_and_time_zone_for_consumers():
    ip = runner.normalize("ip.lookup.v1", {"latitude": 37.42, "longitude": -122.08, "country_code": "US",
                                           "timezone": "America/Los_Angeles"}, {})
    assert (ip["country_code"], ip["timezone"]) == ("US", "America/Los_Angeles")
    airport = runner.normalize("airport.lookup.v1", {"iata": "LAX", "lat": 33.94, "lon": -118.41, "country": "US"}, {})
    assert airport["country_code"] == "US" and "timezone" not in airport
    assert runner.render(templates.CONSUMERS["holidays"]["chain"][1]["input_map"],
                         {"slot.location.country_code": "US", "year": 2026}) == {"country": "US", "year": 2026}

"""Location-hub templates (100-necklace plan 4-1, PM 12:50): one hub x one consumer stamps one candidate."""
from agent_market.necklaces import model, runner, templates


def test_address_x_quakes_stamps_the_shipped_definition_members():
    stamped = templates.stamp("address", "quakes")
    shipped = model.load("agent_market/necklaces/definitions/quakes-near-address.json")
    assert stamped["slug"] == shipped["slug"] and model.validate(stamped) == []
    ids = lambda d: [[(m.get("resource_id"), m["tool"]) for m in s["chain"]] for s in d["slots"]]
    assert ids(stamped) == ids(shipped)
    assert len(stamped["slots"]) <= model.MAX_REQUIRED_SLOTS


def test_a_hub_that_does_not_give_the_field_does_not_stamp():
    assert templates.stamp("address", "local-time") is None          # a geocoder gives no time zone
    assert templates.stamp("address", "holidays") is None            # nor a country code


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

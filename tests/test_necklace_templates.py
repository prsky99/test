"""Location-hub templates (100-necklace plan 4-1, PM 12:50): one hub x one consumer stamps one candidate."""
from agent_market.necklaces import model, runner, templates


def test_address_x_quakes_stamps_the_shipped_definition_members():
    stamped = templates.stamp("address", "quakes")
    shipped = model.load("agent_market/necklaces/definitions/quakes-near-address.json")
    assert stamped["slug"] == shipped["slug"] and model.validate(stamped) == []
    ids = lambda d: [[(m.get("resource_id"), m["tool"]) for m in s["chain"]] for s in d["slots"]]
    assert ids(stamped) == ids(shipped)
    assert len(stamped["slots"]) <= model.MAX_REQUIRED_SLOTS


def test_local_time_reads_the_hub_point_and_keeps_boundary_candidates():
    """PM 13:58: no bridge step; tz-time takes the hub's "lat,lon" in location. Near a zone boundary it may answer with
    several candidate zones, and the necklace passes them on as they are, never picking one."""
    stamped = templates.stamp("airport", "local-time")
    assert [s["slot"] for s in stamped["slots"]] == ["location", "local_time"]
    assert stamped["slots"][1]["chain"] == [m for m in stamped["slots"][1]["chain"] if m["kind"] == "agentcon"]
    assert stamped["slots"][1]["chain"][0]["input_map"] == {"location": "{{slot.location.point}}"}
    ip = templates.stamp("ip", "local-time")
    assert ip["slots"][1]["chain"][0]["resource_id"] == 38614          # an IP hub gives the zone, 38614 can read it
    assert templates.stamp("address", "holidays") is None              # no country code from a street geocoder
    answer = {"answer": "Near a time-zone boundary: candidates America/Indiana/Indianapolis or America/Chicago; "
                        "local time 09:15 or 08:15", "source": "IANA tz"}
    seen = {}

    def caller(member, args, timeout_s):
        seen[member["tool"]] = args
        if member["tool"] == "airport_info":
            return {"iata": "IND", "lat": 39.7173, "lon": -86.2944, "country": "US"}
        return answer
    out = runner.Runner(caller, watch_state={"substitutes": [["tz-time", "timezone.time.v1"]]}).run(stamped, {"code": "IND"})
    text = str(out["output"]["local_time"])
    assert seen["get_local_time"] == {"location": "39.717300,-86.294400"}
    assert "America/Indiana/Indianapolis" in text and "America/Chicago" in text


def test_waiting_leads_are_planned_and_the_ip_hub_needs_a_rule():
    rows = {(r["hub"], r["consumer"]): r for r in templates.pairs()}
    assert rows[("airport", "quakes")]["valid"] and rows[("airport", "quakes")]["waiting_for"] == []
    assert rows[("airport", "holidays")]["valid"] and rows[("airport", "holidays")]["waiting_for"] == [38613]
    assert not rows[("ip", "local-time")]["valid"]
    assert any("no AgentValCon fallback" in w for w in rows[("ip", "local-time")]["why"])
    assert "note" in rows[("airport", "local-time")]
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

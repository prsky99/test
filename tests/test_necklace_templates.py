"""Location-hub templates (100-necklace plan 4-1, PM 12:50): one hub x one consumer stamps one candidate."""
from agent_market.necklaces import model, runner, templates


def test_address_x_quakes_stamps_the_shipped_definition_members():
    stamped = templates.stamp("address", "quakes")
    shipped = model.load("agent_market/necklaces/definitions/quakes-near-address.json")
    assert stamped["slug"] == shipped["slug"] and model.validate(stamped) == []
    ids = lambda d: [[(m.get("resource_id"), m["tool"]) for m in s["chain"]] for s in d["slots"]]
    # v2 (11-19) adds a local_time step after the hub and the consumer: the stamp gives those two. The shipped
    # stamp crosses the leads like the shipped definition (37322 leads location, 178542 quakes: one lead per domain)
    assert ids(stamped) == ids(shipped)[:len(stamped["slots"])] and len(stamped["slots"]) == 2
    assert [s["chain"][0]["resource_id"] for s in stamped["slots"]] == [37322, 178542]   # crossed leads
    assert len(stamped["slots"]) <= model.MAX_REQUIRED_SLOTS


def test_local_time_reads_the_hub_point_and_keeps_boundary_candidates():
    """PM 13:58: no bridge step; tz-time takes the hub's "lat,lon" in location. Near a zone boundary it may answer with
    several candidate zones, and the necklace passes them on as they are, never picking one."""
    stamped = templates.stamp("airport", "local-time")
    assert [s["slot"] for s in stamped["slots"]] == ["location", "local_time"]
    assert stamped["slots"][1]["chain"] == [m for m in stamped["slots"][1]["chain"] if m["kind"] == "agentcon"]
    assert stamped["slots"][1]["chain"][0]["input_map"] == {
        "location": "{{slot.location.point}},{{slot.location.country_code}}"}      # airport gives the country
    assert templates.stamp("address", "local-time")["slots"][1]["chain"][0]["input_map"] == {
        "location": "{{slot.location.point}}"}
    ip = templates.stamp("ip", "local-time")
    assert ip["slots"][1]["chain"][0]["resource_id"] == 38614          # an IP hub gives the zone, 38614 can read it
    assert templates.stamp("address", "holidays") is not None          # holiday-calendar finds the country itself
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
    assert seen["get_local_time"] == {"location": "39.717300,-86.294400,US"}
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
                         {"slot.location.point": "39.7,-86.3", "year": 2026}) == {"country": "39.7,-86.3", "year": 2026}


def test_airport_lookup_sentence_gives_country_code_and_time_zone():
    """Agent team 11-15: airport-lookup's contract allows only answer/url/source, so it writes 'country code US' and
    'time zone America/Los_Angeles' in its sentence; a boundary answer gives no single zone."""
    plain = {"answer": "Los Angeles International Airport (IATA LAX): Los Angeles, US (US-CA), large airport, "
                       "lat 33.942501 lon -118.407997, country code US, time zone America/Los_Angeles", "source": "x"}
    out = runner.normalize("airport.lookup.v1", plain, {})
    assert (out["lat"], out["country_code"], out["timezone"]) == (33.942501, "US", "America/Los_Angeles")
    edge = {"answer": "Airport, lat 41.5 lon -87.5, country code US, time zone near a boundary: America/Chicago or "
                      "America/Indiana/Indianapolis", "source": "x"}
    out = runner.normalize("airport.lookup.v1", edge, {})
    assert out["country_code"] == "US" and "timezone" not in out


def test_the_hub_reads_lat_lon_from_the_fallback_sentence():
    """Without this the airport-lookup fallback answered but staged no point (found 11-15 while reading its answer)."""
    out = runner.normalize("airport.lookup.v1", {"answer": "Kahului (IATA OGG): large airport, lat 20.896263 lon "
                                                           "-156.431837, elevation 54 ft"}, {})
    assert out["point"] == "20.896263,-156.431837"


def test_address_opens_holidays_through_the_point_and_airport_passes_its_code():
    """Agent team 7dac5775: holiday-calendar takes "lat,lon" in country; a hub that gives an ISO code passes that."""
    address = templates.stamp("address", "holidays")
    member = address["slots"][1]["chain"]
    assert [m.get("agent_id") for m in member] == ["holiday-calendar"]                # 38613 needs a code
    assert member[0]["input_map"] == {"country": "{{slot.location.point}}", "year": "{{input.year}}"}
    airport = templates.stamp("airport", "holidays")["slots"][1]["chain"]
    assert airport[0]["resource_id"] == 38613
    assert airport[1]["input_map"]["country"] == "{{slot.location.country_code}}"
    assert model.validate(address) == [] and runner.slot_reference_problems(address) == []

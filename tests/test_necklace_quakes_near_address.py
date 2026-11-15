"""quakes-near-address: location hub normalizers, the live-reference graders and the gold builder (workflow 11-15)."""
import json
import time

from agent_market.necklaces import gold_places, model, retest, runner

NOW = 1_763_200_000.0                                     # fixed clock for every grade
TOKYO = {"lat": 35.658581, "lon": 139.745433, "kind": "landmark", "tolerance_km": 3, "radius_km": 1000, "days": 7,
         "min_magnitude": 4.5}
CASE = {"case_id": "place:Tokyo Tower", "input": {"address": "Tokyo Tower, Minato, Tokyo, Japan"}, "truth": TOKYO}
SURE = {"id": "us1", "mag": 5.6, "lat": 38.3, "lon": 142.4, "time": NOW - 2 * 86400}       # ~370 km from Tokyo
SMALL = {"id": "us2", "mag": 4.8, "lat": 34.0, "lon": 139.5, "time": NOW - 86400}


def quake(event, iso=True):
    when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(event["time"])) if iso else int(event["time"] * 1000)
    return {"magnitude": event["mag"], "lat": event["lat"], "lon": event["lon"], "time": when, "place": "x"}


def test_location_hub_reads_coordinates_from_geocoder_ip_and_text():
    geo = {"query": "q", "results": [{"name": "1600 Pennsylvania Ave NW", "lat": 38.8975862, "lon": -77.0366871}]}
    assert runner.normalize("geocode.address.v1", geo, {})["point"] == "38.897586,-77.036687"
    assert runner.normalize("ip.lookup.v1", {"ip": "8.8.8.8", "latitude": 37.4, "longitude": -122.1}, {})["lat"] == 37.4
    assert runner.normalize("airport.lookup.v1", "LAX is at 33.9425, -118.4081", {})["lon"] == -118.4081
    assert runner.normalize("geocode.address.v1", {"results": []}, {}) is None          # nothing resolved: the slot fails
    assert runner.normalize("geocode.address.v1", {"lat": 0, "lon": 0}, {}) is None      # null island is not an answer


def test_quake_normalizer_keeps_events_once_and_needs_a_said_none():
    raw = {"count": 2, "strongest": quake(SURE), "quakes": [quake(SURE), quake(SMALL)], "center": {"lat": 35.6, "lon": 139.7}}
    out = runner.normalize("earthquake.feed.v1", raw, {})
    assert out["count"] == 2 and out["center"] == {"lat": 35.6, "lon": 139.7}
    geojson = {"features": [{"properties": {"mag": 5.6, "time": int(SURE["time"] * 1000)},
                             "geometry": {"coordinates": [142.4, 38.3, 10]}}]}
    assert runner.normalize("earthquake.feed.v1", geojson, {})["events"][0]["lat"] == 38.3
    assert runner.normalize("earthquake.feed.v1", {"count": 0, "earthquakes": []}, {}) == {"events": [], "count": 0}
    assert runner.normalize("earthquake.feed.v1", "Quakes are common in Japan.", {}) is None


def test_quake_grader_drops_wrong_answers():
    ref = [SURE, SMALL]
    good = {"answers": [{"events": [quake(SURE), quake(SMALL)]}]}
    assert retest.grade_quakes(CASE, good, NOW, ref)
    assert retest.grade_quakes(CASE, {"answers": [{"events": [quake(SURE, iso=False)]}]}, NOW, ref)   # epoch ms
    assert not retest.grade_quakes(CASE, {"answers": [{"events": [quake(SMALL)]}]}, NOW, ref)  # the strongest missing
    wrong_mag = dict(SURE, mag=6.4)
    assert not retest.grade_quakes(CASE, {"answers": [{"events": [quake(wrong_mag)]}]}, NOW, ref)
    far = {"mag": 6.0, "lat": -33.4, "lon": -70.6, "time": NOW - 3600}                   # Chile: a global list
    assert not retest.grade_quakes(CASE, {"answers": [{"events": [quake(SURE), quake(far)]}]}, NOW, ref)
    assert not retest.grade_quakes(CASE, {"answers": [{"text": "no data"}]}, NOW, ref)      # silence
    assert not retest.grade_quakes(CASE, {"answers": [{"events": [], "count": 0}]}, NOW, ref)  # 'none' is wrong here


def test_quake_grader_does_not_owe_edge_events():
    fresh = dict(SURE, time=NOW - 600)                    # ten minutes old: a feed may not have it yet
    edge = dict(SURE, lat=43.9, lon=146.0, time=NOW - 86400)   # ~1,000 km: inside or outside by a geocoder's metres
    weak = dict(SURE, mag=4.6)
    empty = {"answers": [{"events": [], "count": 0}]}
    for ref in ([fresh], [edge], [weak], []):
        assert retest.grade_quakes(CASE, empty, NOW, ref)


def test_location_grader_uses_tolerance_and_ignores_epicentres():
    assert retest.grade_location(CASE, {"answers": [{"lat": 35.6586, "lon": 139.7454}]})
    assert not retest.grade_location(CASE, {"answers": [{"lat": 35.70, "lon": 139.80}]})   # ~7 km off a landmark
    city = dict(CASE, truth=dict(TOKYO, kind="city", tolerance_km=25))
    assert retest.grade_location(city, {"answers": [{"lat": 35.70, "lon": 139.80}]})
    near_quake = {"answers": [{"events": [{"magnitude": 4.9, "lat": 35.66, "lon": 139.75}]}]}
    assert not retest.grade_location(CASE, near_quake)
    assert retest.grade_location(CASE, "Tokyo Tower is at 35.6586, 139.7454")


def test_task_needs_both_parts(monkeypatch):
    monkeypatch.setattr(retest, "quakes_reference", lambda truth, now=None, get=None: [SURE])
    both = {"location": {"answers": [{"lat": 35.6586, "lon": 139.7454}]}, "quakes": {"answers": [{"events": [quake(SURE)]}]}}
    assert retest.grade_quakes_task(CASE, both)
    assert not retest.grade_quakes_task(CASE, {"quakes": both["quakes"]})          # a quake feed alone
    assert not retest.grade_quakes_task(CASE, {"location": both["location"]})      # a geocoder alone
    assert retest.quakes_excluded(CASE) is None
    monkeypatch.setattr(retest, "quakes_reference", lambda truth, now=None, get=None: None)
    assert retest.quakes_excluded(CASE) == "reference_unavailable"


def test_reference_is_asked_once_per_place_and_window():
    calls = []

    def get(url):
        calls.append(url)
        return {"features": [{"id": "us1", "properties": {"mag": 5.6, "time": int(SURE["time"] * 1000)},
                              "geometry": {"coordinates": [142.4, 38.3, 10]}}]}
    retest._QUAKE_REFERENCE.clear()
    first = retest.quakes_reference(TOKYO, NOW, get)
    assert retest.quakes_reference(TOKYO, NOW + 60, get) == first and len(calls) == 1
    assert "maxradiuskm=1000" in calls[0] and "minmagnitude=4.5" in calls[0] and "latitude=35.658581" in calls[0]
    assert first[0]["time"] == SURE["time"]
    assert retest.quakes_reference(dict(TOKYO, lat=1.0), NOW, lambda url: None) is None
    retest._QUAKE_REFERENCE.clear()


def test_definition_validates_and_single_feed_gets_the_typed_address():
    defn = model.load("agent_market/necklaces/definitions/quakes-near-address.json")
    assert model.validate(defn) == []
    quakes = next(s for s in defn["slots"] if s["slot"] == "quakes")
    by_id = {m["resource_id"]: m for m in quakes["chain"]}
    one = retest.single_definition(defn, "quakes", by_id[178542])
    assert one["slots"][0]["chain"][0]["input_map"]["near"] == "{{input.address}}"
    alone = retest.single_definition(defn, "quakes", by_id[37322])
    assert "lat" not in alone["slots"][0]["chain"][0]["input_map"]            # it cannot read an address


def test_stage_passes_coordinates_to_the_feed():
    seen = {}

    def caller(member, args, timeout_s):
        if member["tool"] == "geocode_address":
            return {"results": [{"lat": 35.658581, "lon": 139.745433, "name": "Tokyo Tower"}]}
        seen[member["resource_id"]] = args
        return {"count": 1, "quakes": [quake(SURE)]}
    defn = model.load("agent_market/necklaces/definitions/quakes-near-address.json")
    result = runner.Runner(caller).run(defn, {"address": "Tokyo Tower, Minato, Tokyo, Japan"})
    assert seen[37322]["lat"] == 35.658581 and seen[37322]["lon"] == 139.745433 and seen[37322]["radius_km"] == 1000
    assert result["output"]["quakes"]["answers"][0]["events"][0]["mag"] == 5.6


def test_gold_builder_reads_wikidata_coordinates():
    class Fake:
        calls = 0

        def json(self, url):
            self.calls += 1
            if "Uluru" in url:
                return {"entities": {"-1": {"missing": ""}}}
            return {"entities": {"Q1": {"id": "Q1", "claims": {"P625": [{"mainsnak": {"datavalue": {"value": {
                "latitude": 35.6585805, "longitude": 139.7454329}}}}]}}}}
    cases = gold_places.place_cases(Fake())
    assert len(cases) == len(gold_places.PLACES) - 1
    tower = next(c for c in cases if c["case_id"] == "place:Tokyo Tower")
    assert abs(tower["truth"]["lat"] - 35.65858) < 1e-5 and tower["truth"]["tolerance_km"] == 3
    assert {c["stratum"] for c in cases} == {"asia-pacific", "americas-west", "mediterranean-himalaya", "stable"}
    assert len({c["case_id"] for c in cases}) == len(cases)
    json.dumps(cases)



def test_airport_cases_come_from_ourairports_and_grade_like_addresses():
    csv_text = ("id,ident,type,name,latitude_deg,longitude_deg,iso_country,iata_code\n"
                "1,RJAA,large_airport,Narita International Airport,35.764702,140.386002,JP,NRT\n"
                "2,XXXX,heliport,Fake,1,1,JP,HND\n"
                "3,KLAX,large_airport,Los Angeles International Airport,33.942501,-118.407997,US,LAX\n")
    cases, dropped = gold_places.airport_cases(csv_text)
    assert {c["input"]["code"] for c in cases} == {"NRT", "LAX"} and "HND" in dropped     # heliport rows ignored
    nrt = next(c for c in cases if c["input"]["code"] == "NRT")
    assert nrt["truth"]["tolerance_km"] == 5 and nrt["stratum"] == "asia-pacific"
    assert retest.TASK_GRADERS["quakes-near-airport"] is retest.grade_quakes_task
    defn = model.load("agent_market/necklaces/definitions/quakes-near-airport.json")
    assert model.validate(defn) == [] and runner.slot_reference_problems(defn) == []


def test_airport_lookup_substitute_is_judged_on_the_airport_point():
    """Substitute gate for airport-lookup (PM 13:58): its answer's 'lat X lon Y' within 5 km of OurAirports; a lost
    sign (the first rule's bug, 11-15 13:49) is 4,878 km off and fails."""
    from agent_market.fallback_agents.gold_check import SLUG, judge
    case = {"truth": {"lat": 20.896263, "lon": -156.431837, "tolerance_km": 5}}
    text = {"answer": "Kahului International Airport (IATA OGG): lat 20.896263 lon -156.431837, elevation 54 ft"}
    assert SLUG["airport-lookup"] == "quakes-near-airport"
    assert judge("airport-lookup", case, text)["pass"] is True
    assert judge("airport-lookup", case, {"answer": "lat 20.896263 lon 156.431837"})["pass"] is False
    assert judge("airport-lookup", case, {"latitude": 20.93, "longitude": -156.44})["pass"] is True
    assert judge("airport-lookup", case, {"answer": "no such airport"})["pass"] is False


def test_the_quake_contract_takes_the_point_search_both_feeds_use():
    """Agent team 11-15: usgs-quakes can join the quakes slot once the contract has the point-search fields; the
    magnitude is a number (the definitions send 4.5)."""
    import json as _json
    from jsonschema import Draft202012Validator
    schema = _json.loads(open("agent_market/necklaces/contracts/earthquake.feed.v1.json").read())["input_schema"]
    check = Draft202012Validator(schema)
    defn = model.load("agent_market/necklaces/definitions/quakes-near-address.json")
    quakes = next(s for s in defn["slots"] if s["slot"] == "quakes")
    staged = {"slot.location.lat": 35.6586, "slot.location.lon": 139.7454, "slot.location.point": "35.658600,139.745400"}
    for member in quakes["chain"]:
        assert not list(check.iter_errors(runner.render(member["input_map"], staged))), member["resource_id"]
    assert list(check.iter_errors({"radius_km": 5000})) and list(check.iter_errors({"near": "Tokyo"}))
    assert not list(check.iter_errors({"min_magnitude": 5}))                          # the pearl tests' input


def test_our_usgs_feed_answers_in_a_sentence_and_ends_the_quake_chain():
    """Agent team 82d1a98d: usgs-quakes answers 'M5.1 2026-11-15 03:12 UTC, place, 4 km away, lat X lon Y; ...' or
    'No earthquake of magnitude ...' (a normal answer); both necklaces end their quakes chain with it."""
    answer = {"answer": "2 earthquakes of magnitude 4.5 or more within 1000 km of 35.6800,139.7600 in the past 7 days "
                        "(USGS, newest first): M5.1 2026-11-15 03:12 UTC, 10 km SE of Hachijo-jima, Japan, 4 km away, "
                        "lat 35.700 lon 139.800; M4.7 2026-11-13 21:05 UTC, near Tokyo, 30 km away, lat 35.9 lon 140.1 "
                        "(tsunami flag).", "source": "USGS"}
    out = runner.normalize("earthquake.feed.v1", answer, {})
    assert [(e["mag"], e["lat"], e["time"]) for e in out["events"]] == [(5.1, 35.7, "2026-11-15T03:12:00Z"),
                                                                        (4.7, 35.9, "2026-11-13T21:05:00Z")]
    none = runner.normalize("earthquake.feed.v1", {"answer": "No earthquake of magnitude 4.5 or more within 1000 km "
                                                             "of 1,2 in the USGS feed for the week."}, {})
    assert none == {"events": [], "count": 0}
    for slug in ("quakes-near-address", "quakes-near-airport"):
        defn = model.load(f"agent_market/necklaces/definitions/{slug}.json")
        quakes = next(s for s in defn["slots"] if s["slot"] == "quakes")
        assert quakes["chain"][-1]["agent_id"] == "usgs-quakes" and model.validate(defn) == []

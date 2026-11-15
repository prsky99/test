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

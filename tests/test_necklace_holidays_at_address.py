"""holidays-at-address (country grid c378a302): the grader, the definition and the gold builder that keeps countries."""
import json

from agent_market.necklaces import gold_holidays, model, retest, runner

CASE = {"truth": {"lat": 35.7647, "lon": 140.3860, "tolerance_km": 5, "country_code": "JP", "year": 2026,
                  "holidays": ["2026-01-01", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20"]}}
ANSWER = {"answer": "National public holidays in Japan (JP), 2026 (national public holidays only; ...): 2026-01-01 "
                    "New Year's Day; 2026-01-12 Coming of Age Day; 2026-02-11 Foundation Day; 2026-02-23 Emperor's "
                    "Birthday; 2026-03-20 Vernal Equinox Day."}


def test_holidays_grader_drops_another_country_and_a_thin_answer():
    assert retest.grade_holidays(CASE, ANSWER)
    us = {"answer": "National public holidays in United States (US), 2026: 2026-01-01; 2026-01-19; 2026-02-16; "
                    "2026-05-25; 2026-07-03; 2026-09-07; 2026-11-26; 2026-12-25."}
    assert not retest.grade_holidays(CASE, us)
    assert not retest.grade_holidays(CASE, {"answer": "2026-01-01 New Year's Day."})
    assert not retest.grade_holidays(CASE, {"answer": "No holidays found."})
    both = {"location": {"answers": [{"lat": 35.7647, "lon": 140.386}]}, "holidays": {"answers": [ANSWER]}}
    assert retest.grade_holidays_task(CASE, both)
    assert not retest.grade_holidays_task(CASE, {"holidays": both["holidays"]})


def test_definition_reads_the_point_for_holiday_calendar():
    defn = model.load("agent_market/necklaces/definitions/holidays-at-address.json")
    assert model.validate(defn) == [] and runner.slot_reference_problems(defn) == []
    holidays = next(s for s in defn["slots"] if s["slot"] == "holidays")
    assert [m.get("agent_id") for m in holidays["chain"]] == ["holiday-calendar"]
    assert holidays["chain"][0]["input_map"] == {"country": "{{slot.location.point}}", "year": "{{input.year}}"}


def test_builder_keeps_fetched_countries_and_stops_at_the_share(tmp_path):
    raw = tmp_path / "gold" / "raw" / "airports-20261115"
    raw.mkdir(parents=True)
    rows = [{"input": {"code": c}, "stratum": "x", "truth": {"lat": 1, "lon": 2, "name": f"{c} Airport", "country": cc}}
            for c, cc in (("NRT", "JP"), ("LAX", "US"), ("GUM", "GU"), ("CDG", "FR"))]
    (raw / "airport-cases.json").write_text(json.dumps({"cases": rows}))
    calls = []

    def get(url):
        calls.append(url)
        if len(calls) > 2:                                   # the third country is past the day's share
            raise RuntimeError("provider budget: system_share")
        return json.dumps([{"date": "2026-01-01", "global": True, "types": ["Public"]},
                           {"date": "2026-03-01", "global": False, "types": ["Public"]}])
    out = gold_holidays.build(tmp_path, get)
    assert out["cases"] == 2 and out["countries"] == 3 and "system_share" in out["stopped"]   # Guam left out
    assert not any(u.endswith("/GU") for u in calls)
    kept = {p.stem for p in (tmp_path / "gold" / "raw" / "nager-2026").glob("*.json")}
    assert len(kept) == 2
    again = gold_holidays.build(tmp_path, lambda url: json.dumps([{"date": "2026-07-14", "global": True}]))
    assert again["cases"] == 3 and again["stopped"] is None                 # the kept two are not asked again

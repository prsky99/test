"""sun.times computed locally (agent team 11-16): checked against published sunrise and sunset times, within 2 min."""
from datetime import date, datetime

import pytest

from agent_market.fallback_agents.sun import sun_times


def minutes(a: str, b: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return abs((datetime.strptime(a, fmt) - datetime.strptime(b, fmt)).total_seconds()) / 60


@pytest.mark.parametrize("lat,lon,day,rise,set_", [
    (51.5074, -0.1278, date(2024, 6, 21), "2024-06-21T03:43:00Z", "2024-06-21T20:21:00Z"),     # London, BST 04:43/21:21
    (40.7128, -74.0060, date(2024, 12, 21), "2024-12-21T12:16:00Z", "2024-12-21T21:32:00Z"),   # New York, EST 07:16/16:32
    (-33.8688, 151.2093, date(2024, 6, 21), "2024-06-20T21:00:00Z", "2024-06-21T06:54:00Z"),   # Sydney, AEST 07:00/16:54
])
def test_known_places_within_two_minutes(lat, lon, day, rise, set_):
    out = sun_times(lat, lon, day)
    assert out["state"] == "normal"
    assert minutes(out["sunrise"], rise) <= 2 and minutes(out["sunset"], set_) <= 2


def test_polar_day_and_night_have_no_invented_times():
    winter, summer = sun_times(69.6492, 18.9553, date(2024, 12, 21)), sun_times(69.6492, 18.9553, date(2024, 6, 21))
    assert winter == {**winter, "state": "always_down", "sunrise": None, "sunset": None, "day_length_minutes": 0}
    assert summer == {**summer, "state": "always_up", "sunrise": None, "sunset": None, "day_length_minutes": 1440}


def test_day_length_near_twelve_hours_at_the_equator_and_bad_coordinates_refused():
    assert abs(sun_times(-0.18, -78.47, date(2024, 9, 22))["day_length_minutes"] - 726) <= 3
    with pytest.raises(ValueError):
        sun_times(91, 0, date(2024, 1, 1))

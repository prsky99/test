"""Sunrise, sunset and day length computed locally (sun.times.v1, PM 11-16 weather-outdoor-brief).

No outside call: the NOAA solar calculator equations (Meeus, "Astronomical Algorithms"), the same ones behind
NOAA's public calculator (https://gml.noaa.gov/grad/solcalc/calcdetails.html). Sunrise and sunset are the moments the
sun's upper limb touches a sea-level horizon with standard refraction (zenith 90.833 degrees). Accuracy is about a
minute between the polar circles; terrain, elevation and unusual refraction are not modelled.

Near the poles the sun may stay up (``always_up``) or down (``always_down``) all day; then there is no sunrise or
sunset and the state says so instead of an invented time.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

ZENITH = 90.833          # degrees: 90 + 34' refraction + 16' solar semi-diameter


def _julian_century(d: date, minutes_utc: float) -> float:
    jd = d.toordinal() + 1721424.5 + minutes_utc / 1440.0
    return (jd - 2451545.0) / 36525.0


def _sun(t: float) -> tuple[float, float]:
    """(declination in degrees, equation of time in minutes) at Julian century T."""
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t)) + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    mean_obliq = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    obliq = mean_obliq + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(obliq)) * math.sin(math.radians(app_long))))
    y = math.tan(math.radians(obliq / 2)) ** 2
    l0r = math.radians(l0)
    eot = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
                           - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    return decl, eot


def _hour_angle(lat: float, decl: float) -> float | None:
    """Degrees, or None when the sun never reaches the horizon (cos outside [-1, 1])."""
    cos_h = (math.cos(math.radians(ZENITH)) / (math.cos(math.radians(lat)) * math.cos(math.radians(decl)))
             - math.tan(math.radians(lat)) * math.tan(math.radians(decl)))
    if cos_h > 1:
        return None          # below the horizon all day
    if cos_h < -1:
        return -1.0          # above the horizon all day (marker)
    return math.degrees(math.acos(cos_h))


def _event_minutes(d: date, lat: float, lon: float, rising: bool) -> float | str:
    """Minutes after 00:00 UTC of D, refined twice; or "always_up" / "always_down"."""
    minutes = 720 - 4 * lon
    for _ in range(3):
        decl, eot = _sun(_julian_century(d, minutes))
        h = _hour_angle(lat, decl)
        if h is None:
            return "always_down"
        if h == -1.0:
            return "always_up"
        minutes = 720 - 4 * (lon + (h if rising else -h)) - eot
    return minutes


def _iso(d: date, minutes: float) -> str:
    at = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return (at + timedelta(seconds=30)).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def sun_times(lat: float, lon: float, d: date) -> dict:
    """{state, sunrise, sunset, day_length_minutes, solar_noon} for the local day D at (lat, lon): the solar day
    whose noon falls on D at that longitude, so Seoul's 20 March sunrise is 06:36 local (21:36 UTC on 19 March).

    state: "normal", "always_up" or "always_down". Times are UTC (ISO 8601, minute precision)."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or any(map(math.isnan, (lat, lon))):
        raise ValueError("coordinate out of range")
    decl, eot = _sun(_julian_century(d, 720 - 4 * lon))
    noon = 720 - 4 * lon - eot
    rise, set_ = _event_minutes(d, lat, lon, True), _event_minutes(d, lat, lon, False)
    out = {"solar_noon": _iso(d, noon)}
    if isinstance(rise, str) or isinstance(set_, str):
        state = rise if isinstance(rise, str) else set_
        out.update(state=state, sunrise=None, sunset=None, day_length_minutes=1440 if state == "always_up" else 0)
        return out
    out.update(state="normal", sunrise=_iso(d, rise), sunset=_iso(d, set_),
               day_length_minutes=int(round(set_ - rise)))
    return out

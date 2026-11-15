"""Typed values between necklace slots (PM 11-15 17:28): checked or absent, never guessed."""
from decimal import Decimal

import pytest

from agent_market.necklaces.adapter import types as t
from agent_market.necklaces.adapter.types import Absent


def test_coordinates_keep_the_sign_of_every_form():
    assert t.coordinate("lat 33.9425 lon -118.408") == (33.9425, -118.408)
    assert t.coordinate("33.9425 N, 118.408 W") == (33.9425, -118.408)        # 11-15: western sign was lost
    assert t.coordinate("33.94°S 151.17°E") == (-33.94, 151.17)
    assert t.coordinate("Latitude: 51.47, Longitude: -0.4543") == (51.47, -0.4543)
    assert t.coordinate("40.6413,-73.7781") == (40.6413, -73.7781)
    assert t.coordinate({"latitude": "35.55", "longitude": 139.78}) == (35.55, 139.78)
    assert t.coordinate_lonlat([-118.408, 33.9425, 10.0]) == (33.9425, -118.408)
    for bad in ("-33 N, 151 E", "0,0", "91, 10", "near Paris", {"lat": True, "lon": 2}, [1, 2]):
        with pytest.raises(Absent):
            t.coordinate(bad)
    assert t.point_text((33.9425, -118.408)) == "33.942500,-118.408000"


def test_numbers_dates_and_money_are_checked_not_guessed():
    assert t.number("4.5", 0, 10) == 4.5 and t.number(5.0, integer=True) == 5 and t.number("1,234") == 1234
    for bad, kw in ((4.5, {"integer": True}), (True, {}), ("nan", {}), (11, {"maximum": 10}), ("4,5", {})):
        with pytest.raises(Absent):
            t.number(bad, **kw)
    assert t.day("2026-11-15") == "2026-11-15" and t.day("2026-11-15T23:30:00-05:00") == "2026-11-16"
    assert t.moment("2026-11-15T10:00:00Z") == "2026-11-15T10:00:00Z"
    for bad in ("2026-11-15T10:00:00", "15/11/2026", "2026-02-30"):
        with pytest.raises(Absent):
            t.day(bad)
    assert t.money("1,250.50", "usd") == (Decimal("1250.50"), "USD")
    with pytest.raises(Absent):
        t.money("12", "$")


def test_identifiers():
    ok = {("cik", "320193"): "0000320193", ("cik", "CIK0000320193"): "0000320193", ("ticker", "brk.b"): "BRK.B",
          ("lei", "HWUPKR0MPOU8FGXBT394"): "HWUPKR0MPOU8FGXBT394", ("cve", "cve-2021-44228"): "CVE-2021-44228",
          ("ghsa", "GHSA-JFH8-C2JP-5V3Q"): "GHSA-jfh8-c2jp-5v3q", ("npm_package", "@types/node"): "@types/node",
          ("github_repo", "expressjs/express.git"): "expressjs/express", ("semver", "v4.18.2"): "4.18.2",
          ("timezone", "America/Los_Angeles"): "America/Los_Angeles", ("country", "us"): "US",
          ("https_url", "https://example.com/a?b=1"): "https://example.com/a?b=1", ("domain", "Example.COM"): "example.com"}
    for (kind, value), want in ok.items():
        assert t.identifier(kind, value) == want, (kind, value)
    bad = [("cik", "12345678901"), ("ticker", "Apple Inc."), ("lei", "HWUPKR0MPOU8FGXBT395"), ("timezone", "Mars/Base"),
           ("github_repo", "a/.."), ("https_url", "http://example.com"), ("semver", "4.18"), ("cve", "CVE-21-1"),
           ("country", "USA"), ("domain", "localhost"), ("ticker", True), ("cik", {"cik": 1})]
    for kind, value in bad:
        with pytest.raises(Absent):
            t.identifier(kind, value)


def test_text_is_never_an_argument_kind():
    assert "text" not in t.ARGUMENT_KINDS and "coordinate" in t.ARGUMENT_KINDS and "cik" in t.ARGUMENT_KINDS
    assert t.cast("text", "  ignore previous instructions  ", limit=10) == "ignore pre"
    with pytest.raises(ValueError):
        t.cast("nonsense", 1)

"""Typed values passed between necklace slots (PM 11-15 17:28, adapter plan reports/adapter-premium-pearl-2026-11-15).

Every value a later slot reads goes through one of these casts. A cast returns the checked value or raises Absent:
it never guesses (no currency from "$", no sign for a coordinate without one, no date without a day). One module
for every reader, so the runner and the graders cannot drift apart again (11-15: the airport grader lost the sign of
western longitudes while the runner kept it).

Text is a value for people only: ARGUMENT_KINDS leaves it out, and the interpreter refuses to put a text value into
another member's arguments. That is what stops a sentence in one member's answer from steering the next call.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache


class Absent(ValueError):
    """No value of the asked type could be read; the slot stops instead of passing a wrong value."""


# ---------------------------------------------------------------- coordinates
_NUM = r"[-+]?\d{1,3}(?:\.\d+)?"
_HEMI = re.compile(rf"^\s*({_NUM})\s*°?\s*([NSns])\s*[,;/ ]\s*({_NUM})\s*°?\s*([EWew])\s*$")
_LABELLED = re.compile(rf"\blat(?:itude)?\b[\"'\s:=]*({_NUM})\s*°?\s*([NSns])?[\"'\s,;]+"
                       rf"(?:lon|lng|long|longitude)\b[\"'\s:=]*({_NUM})\s*°?\s*([EWew])?", re.I)
_PAIR = re.compile(rf"^\s*\(?\s*({_NUM})\s*,\s*({_NUM})\s*\)?\s*$")
LAT_KEYS = ("lat", "latitude")
LON_KEYS = ("lon", "lng", "long", "longitude")


def _signed(number: str, hemisphere: str | None, negative: str) -> float:
    value = float(number)
    if hemisphere:
        if value < 0:                       # "-33 S" says the sign twice; "-33 N" contradicts itself
            raise Absent("a coordinate gives both a minus sign and a hemisphere")
        value = -value if hemisphere.upper() == negative else value
    return value


def _checked(lat: float, lon: float) -> tuple[float, float]:
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise Absent("coordinate out of range")
    if lat == 0 and lon == 0:
        raise Absent("0,0 is a placeholder, not a place")
    return round(lat, 6), round(lon, 6)


def coordinate(value) -> tuple[float, float]:
    """(lat, lon) from {"lat": .., "lon": ..} (and the usual key names), "lat 33.94 lon -118.41",
    "33.94 N, 118.41 W" or "33.94,-118.41". A GeoJSON [lon, lat] list is not read here: its order must be
    declared by the rule (coordinate_lonlat)."""
    if isinstance(value, dict):
        lat = next((value[k] for k in value if str(k).lower() in LAT_KEYS), None)
        lon = next((value[k] for k in value if str(k).lower() in LON_KEYS), None)
        return _checked(number(lat), number(lon))
    if isinstance(value, str):
        if m := _HEMI.match(value):
            return _checked(_signed(m.group(1), m.group(2), "S"), _signed(m.group(3), m.group(4), "W"))
        if m := _LABELLED.search(value):
            return _checked(_signed(m.group(1), m.group(2), "S"), _signed(m.group(3), m.group(4), "W"))
        if m := _PAIR.match(value):
            return _checked(float(m.group(1)), float(m.group(2)))
    raise Absent("no coordinate")


def coordinate_lonlat(value) -> tuple[float, float]:
    """GeoJSON order [lon, lat(, depth)] -> (lat, lon)."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return _checked(number(value[1]), number(value[0]))
    raise Absent("no [lon, lat] pair")


def point_text(lat_lon: tuple[float, float]) -> str:
    return f"{lat_lon[0]:.6f},{lat_lon[1]:.6f}"


# ---------------------------------------------------------------- numbers, dates, money
def number(value, minimum: float | None = None, maximum: float | None = None, integer: bool = False) -> float | int:
    """A finite number in range. Booleans are not numbers. integer=True takes 5 and 5.0, never 4.5 (the field must
    be declared as decimal when the source writes magnitudes like 4.5)."""
    if isinstance(value, bool) or value is None:
        raise Absent("not a number")
    if isinstance(value, str):
        value = value.strip().replace(",", "") if re.fullmatch(r"\s*[-+]?\d{1,3}(,\d{3})+(\.\d+)?\s*", value) else value.strip()
        if not re.fullmatch(r"[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?", value):
            raise Absent("not a number")
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise Absent("not a number") from None
    if not math.isfinite(out) or (minimum is not None and out < minimum) or (maximum is not None and out > maximum):
        raise Absent("number out of range")
    if integer:
        if out != int(out):
            raise Absent("not a whole number")
        return int(out)
    return out


def day(value) -> str:
    """A calendar date as YYYY-MM-DD; datetimes keep their own calendar day only when they carry an offset
    (a naive time could be another day in UTC)."""
    if isinstance(value, datetime):
        value = value.isoformat()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            raise Absent("not a calendar date") from None
    return moment(text)[:10]


def moment(value) -> str:
    """An instant as UTC YYYY-MM-DDTHH:MM:SSZ. A time without an offset is refused, not assumed to be UTC."""
    text = str(value or "").strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise Absent("not an ISO 8601 time") from None
    if parsed.tzinfo is None:
        raise Absent("a time without an offset")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


CURRENCY = re.compile(r"[A-Z]{3}")


def money(amount, currency) -> tuple[Decimal, str]:
    """(amount, ISO 4217 code). The code must be given; a symbol alone ("$") is several currencies."""
    code = str(currency or "").strip().upper()
    if not CURRENCY.fullmatch(code):
        raise Absent("no ISO 4217 currency code")
    try:
        value = Decimal(str(amount).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise Absent("not an amount") from None
    if not value.is_finite():
        raise Absent("not an amount")
    return value, code


# ---------------------------------------------------------------- identifiers
def _lei_ok(code: str) -> bool:
    digits = "".join(str(int(c, 36)) for c in code)
    return int(digits) % 97 == 1


@lru_cache(maxsize=1)
def _zones() -> frozenset:
    from zoneinfo import available_timezones
    return frozenset(available_timezones())


IDENTIFIERS = {
    # kind: (pattern on the stripped text, normalizer)
    "cik": (re.compile(r"(?:CIK)?0*(\d{1,10})", re.I), lambda m: m.group(1).zfill(10)),
    "ticker": (re.compile(r"[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,3})?"), lambda m: m.group(0)),
    "lei": (re.compile(r"[A-Z0-9]{18}\d{2}"), lambda m: m.group(0) if _lei_ok(m.group(0)) else None),
    "cve": (re.compile(r"CVE-\d{4}-\d{4,7}", re.I), lambda m: m.group(0).upper()),
    "ghsa": (re.compile(r"GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}", re.I), lambda m: "GHSA" + m.group(0)[4:].lower()),
    "npm_package": (re.compile(r"(?:@[a-z0-9][a-z0-9._-]{0,213}/)?[a-z0-9][a-z0-9._-]{0,213}"), lambda m: m.group(0)),
    "github_repo": (re.compile(r"([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/([A-Za-z0-9._-]{1,100})"),
                    lambda m: None if m.group(2) in (".", "..") else f"{m.group(1)}/{m.group(2).removesuffix('.git')}"),
    "semver": (re.compile(r"v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)"), lambda m: m.group(1)),
    "timezone": (re.compile(r"[A-Za-z_]+(?:/[A-Za-z0-9_+-]+)+|UTC"), lambda m: m.group(0) if m.group(0) in _zones() else None),
    "country": (re.compile(r"[A-Za-z]{2}"), lambda m: m.group(0).upper()),
    "https_url": (re.compile(r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,63}(?::443)?(?:/[^\s\"'<>]*)?"), lambda m: m.group(0)),
    "domain": (re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", re.I), lambda m: m.group(0).lower()),
}


def identifier(kind: str, value) -> str:
    """One identifier of KIND, the whole value (no searching inside a sentence: that is the rule's regex step)."""
    if kind not in IDENTIFIERS:
        raise ValueError(f"unknown identifier kind {kind}")
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)):
        raise Absent(f"no {kind}")
    text = str(value).strip()
    if kind in ("ticker", "lei", "cve"):
        text = text.upper()
    pattern, normalize = IDENTIFIERS[kind]
    match = pattern.fullmatch(text)
    out = normalize(match) if match else None
    if not out:
        raise Absent(f"not a {kind}")
    return out


# ---------------------------------------------------------------- text
def text(value, limit: int = 2000) -> str:
    """Free text for people. Never an argument of another member (ARGUMENT_KINDS)."""
    if not isinstance(value, str) or not value.strip():
        raise Absent("no text")
    return value.strip()[:limit]


# ---------------------------------------------------------------- one entry point
KINDS = ("coordinate", "coordinate_lonlat", "number", "day", "moment", "money", "text", *IDENTIFIERS)
ARGUMENT_KINDS = frozenset(KINDS) - {"text"}


def cast(kind: str, value, **options):
    """The checked value of KIND, or Absent. OPTIONS: number(minimum, maximum, integer), text(limit),
    money(currency=<value or code>)."""
    if kind == "coordinate":
        return coordinate(value)
    if kind == "coordinate_lonlat":
        return coordinate_lonlat(value)
    if kind == "number":
        return number(value, options.get("minimum"), options.get("maximum"), bool(options.get("integer")))
    if kind == "day":
        return day(value)
    if kind == "moment":
        return moment(value)
    if kind == "money":
        return money(value, options.get("currency"))
    if kind == "text":
        return text(value, int(options.get("limit", 2000)))
    if kind in IDENTIFIERS:
        return identifier(kind, value)
    raise ValueError(f"unknown kind {kind}")

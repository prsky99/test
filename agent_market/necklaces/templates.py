"""Location-hub templates: stamp a necklace definition from a hub and a consumer (100-necklace plan 4-1, PM 12:50).

An IP hub stamps but does not validate today: ip.lookup.v1 has no AgentValCon fallback, so model.NO_FALLBACK_ROLES
keeps it to optional slots, and a hub is required (the PM decides whether two independent IP pearls may hold a
required hub). A hub turns what a person types (an address, an IP, an airport code) into a place: runner.norm_location stages
lat, lon, point ("lat,lon"), and country_code and timezone when the answer gives them. A consumer reads those staged
fields in a second stage. One hub times one consumer is one definition, three slots at most (PM E8). The members are
the ones the verify snapshot and the relay check found; a consumer whose lead is not a verified pearl yet stamps
with that lead "planned", so the definition validates and the gate check reports the slot as not ready until the
pearl verifies (then the lead turns active and the definition goes to the gate queue).

    .venv/bin/python -m agent_market.necklaces.templates list
    .venv/bin/python -m agent_market.necklaces.templates stamp ip local-time [--write]

Stamped files are candidates. Gold sets and graders are made per necklace (gold_places for the quake consumer).
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from . import model


def _member(kind, tool, input_map, upstream, *, rid=None, agent_id=None, domain=None, state="active", pearl=False):
    m = {"kind": kind, "tool": tool, "upstream": upstream, "read_only_hint": True, "destructive_hint": False,
         "idempotent_hint": True, "resend_safe": True, "state": state, "input_map": input_map}
    if kind == "external":
        m.update(resource_id=rid, registrable_domain=domain)
        if pearl:
            m["pearl"] = True
    else:
        m.update(agent_id=agent_id, resource_id=None, registrable_domain="agentconcierge.biz", state="planned")
    return m


HUBS = {
    "address": {
        "input": "address", "schema": {"type": "string", "minLength": 3, "maxLength": 300},
        "help": "A street address, landmark or city, for example Tokyo Tower, Minato, Tokyo, Japan.",
        "example": "Tokyo Tower, Minato, Tokyo, Japan", "point": (35.6586, 139.7454, "JP", "Asia/Tokyo"),
        "contract": "geocode.address.v1",
        "gives": {"lat", "lon", "point"},
        "chain": [_member("external", "geocode_address", {"query": "{{input.address}}"}, ["google-maps"], rid=264482,
                          domain="dmvtransit.com", pearl=True),
                  _member("external", "geocode", {"address": "{{input.address}}"}, ["us-census"], rid=37322,
                          domain="datakoot.com")]},
    "ip": {
        "input": "ip", "schema": {"type": "string", "pattern": r"^(\d{1,3}\.){3}\d{1,3}$|^[0-9a-fA-F:]{3,39}$"},
        "help": "A public IPv4 or IPv6 address, for example 8.8.8.8.", "example": "8.8.8.8",
        "point": (37.422, -122.085, "US", "America/Los_Angeles"),
        "contract": "ip.lookup.v1", "gives": {"lat", "lon", "point", "country_code", "timezone"},
        "chain": [_member("external", "lookup_ip", {"ip": "{{input.ip}}"}, ["ipai"], rid=241082, domain="ipipai.com",
                          pearl=True),
                  _member("external", "ip_geolocation", {"ip": "{{input.ip}}"}, ["ipv4.fr"], rid=167478,
                          domain="ipv4.fr", pearl=True)]},
    "airport": {
        "input": "code", "schema": {"type": "string", "pattern": "^[A-Za-z]{3,4}$"},
        "help": "An airport's IATA or ICAO code, for example LAX.", "example": "LAX",
        "point": (33.9425, -118.408, "US", "America/Los_Angeles"),
        "contract": "airport.lookup.v1", "gives": {"lat", "lon", "point", "country_code"},
        "chain": [_member("external", "airport_info", {"code": "{{input.code}}"}, ["ourairports"], rid=86011,
                          domain="tidydata.workers.dev", pearl=True),
                  _member("agentcon", "lookup_airport", {"code": "{{input.code}}"}, ["ourairports"],
                          agent_id="airport-lookup")]},
}

CONSUMERS = {
    "quakes": {
        "slot": "quakes", "contract": "earthquake.feed.v1", "needs": {"lat", "lon", "point"},
        "title": "Earthquakes near", "what": "the M4.5+ earthquakes within 1,000 km in the last 7 days (USGS data)",
        "chain": [_member("external", "earthquakes", {"lat": "{{slot.location.lat}}", "lon": "{{slot.location.lon}}",
                                                      "radius_km": 1000, "days": 7, "min_magnitude": 4.5, "limit": 20},
                          ["usgs"], rid=37322, domain="datakoot.com", pearl=True),
                  _member("external", "earthquakes", {"near": "{{slot.location.point}}", "radius_km": 1000,
                                                      "period": "week", "min_magnitude": 4.5, "limit": 20},
                          ["usgs"], rid=178542, domain="augur-trade.com", pearl=True)]},
    "local-time": {
        "slot": "local_time", "contract": "timezone.time.v1", "needs": {"timezone"},
        "title": "Local time at", "what": "the current local time, UTC offset and daylight-saving state there (IANA tz)",
        "chain": [_member("external", "get_current_time", {"timeZone": "{{slot.location.timezone}}"}, ["iana-tz"],
                          rid=38614, domain="invokera.com", state="planned"),
                  _member("agentcon", "get_local_time", {"timezone": "{{slot.location.timezone}}"}, ["iana-tz"],
                          agent_id="tz-time")]},
    "holidays": {
        "slot": "holidays", "contract": "holiday.calendar.v1", "needs": {"country_code"}, "year": True,
        "title": "Public holidays at", "what": "that country's public holidays in the year asked",
        "chain": [_member("external", "get_public_holidays", {"countryCode": "{{slot.location.country_code}}",
                                                              "year": "{{input.year}}"}, ["nager-date"],
                          rid=38613, domain="invokera.com", state="planned"),
                  _member("agentcon", "get_holidays", {"country": "{{slot.location.country_code}}",
                                                       "year": "{{input.year}}"}, ["python-holidays"],
                          agent_id="holiday-calendar")]},
}


# A bridge sits between a hub and a consumer when the hub lacks a field the consumer reads (PM 13:42, 11-15): the
# agent team builds an own agent that turns coordinates into a time zone (and country), so address and airport
# hubs open local-time and holidays without an IP hub. The contract name is a proposal to settle with the agent
# team; until its file and agent exist the stamp does not validate (the list says what it waits for).
BRIDGES = {
    "zone": {"slot": "zone", "contract": "timezone.at_point.v1", "needs": {"lat", "lon"},
             "gives": {"timezone", "country_code"},
             "chain": [_member("agentcon", "timezone_at_point", {"lat": "{{slot.location.lat}}",
                                                                 "lon": "{{slot.location.lon}}"},
                               ["timezone-boundaries"], agent_id="coords-timezone")]},
}


def _bridge_for(hub: dict, use: dict) -> dict | None:
    for bridge in BRIDGES.values():
        if bridge["needs"] <= hub["gives"] and use["needs"] <= hub["gives"] | bridge["gives"]:
            return bridge
    return None


def _read_from_bridge(chain: list[dict], bridge: dict) -> list[dict]:
    for member in chain:
        for key, value in list(member["input_map"].items()):
            for field in bridge["gives"]:
                if value == "{{slot.location." + field + "}}":
                    member["input_map"][key] = "{{slot." + bridge["slot"] + "." + field + "}}"
    return chain


def stamp(hub_key: str, consumer_key: str) -> dict | None:
    """The candidate definition for HUB x CONSUMER (through a bridge when the hub lacks a field), or None."""
    hub, use = HUBS[hub_key], CONSUMERS[consumer_key]
    bridge = None if use["needs"] <= hub["gives"] else _bridge_for(hub, use)
    if not use["needs"] <= hub["gives"] and bridge is None:
        return None
    props = {hub["input"]: dict(hub["schema"])}
    required = [hub["input"]]
    example = {hub["input"]: hub["example"]}
    helps = {hub["input"]: hub["help"]}
    if use.get("year"):
        props["year"] = {"type": "integer", "minimum": 1975, "maximum": 2100}
        required.append("year")
        example["year"] = 2026
        helps["year"] = "The calendar year, for example 2026."
    location = {"slot": "location", "contract": hub["contract"], "required": True, "fanout": 1,
                "chain": copy.deepcopy(hub["chain"])}
    second = {"slot": use["slot"], "contract": use["contract"], "required": True, "fanout": 1,
              "depends_on": ["location"], "chain": copy.deepcopy(use["chain"])}
    middle = None
    if bridge is not None:
        middle = {"slot": bridge["slot"], "contract": bridge["contract"], "required": True, "fanout": 1,
                  "depends_on": ["location"], "chain": copy.deepcopy(bridge["chain"])}
        second["chain"] = _read_from_bridge(second["chain"], bridge)
        reads = {v for m in second["chain"] for v in m["input_map"].values() if isinstance(v, str)}
        second["depends_on"] = [bridge["slot"]] + (["location"] if any("{{slot.location." in v for v in reads) else [])
    slug = f"{consumer_key}-near-{hub_key}" if consumer_key == "quakes" else f"{consumer_key}-at-{hub_key}"
    lat, lon, country, zone = hub["point"]
    staged = {"slot.location.lat": lat, "slot.location.lon": lon, "slot.location.point": f"{lat:.6f},{lon:.6f}",
              "slot.location.country_code": country, "slot.location.timezone": zone}
    planned = [m["resource_id"] for m in second["chain"] if m["kind"] == "external" and m["state"] == "planned"]
    return {
        "slug": slug, "version": 1, "status": "candidate",
        "name": f"{use['title']} {'an ' if hub_key in ('address', 'ip', 'airport') else ''}{hub_key if hub_key != 'ip' else 'IP'}",
        "summary": f"Where the {hub_key if hub_key != 'ip' else 'IP address'} is and {use['what']}, in one answer: "
                   f"the place is resolved first, then the second step reads it.",
        "input_schema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
        "budget_ms": {"total": 5000, "slot": 2500},
        "synthesis": {"kind": "merge-v1", "rules": [
            "the location step resolves the input once; the second step reads only what it staged",
            "a run counts only when at least two verified pearls answered",
            "every statement keeps its source link"]},
        "answer_set": f"{slug}-v1",
        "slots": [location] + ([middle] if middle else []) + [second],
        "notes": (f"Stamped from the location-hub template (necklaces.templates: hub {hub_key}, consumer {consumer_key}). "
                  + (f"Lead {', '.join(map(str, planned))} is planned until the verify snapshot lists it as a verified "
                     f"pearl for {use['contract']}; until then the gate check reports the slot as not ready. "
                     if planned else "")
                  + "Gold set and grader are made for this necklace before the gate."),
        "min_pearls_answered": 2,
        "probe_input": {**example, **{k: v for k, v in staged.items() if k.split(".")[2] in use["needs"]},
                        **({f"slot.{bridge['slot']}.{k.split('.')[2]}": v for k, v in staged.items()
                            if k.split(".")[2] in bridge["gives"]} if bridge else {})},
        "input_help": helps,
    }


def pairs() -> list[dict]:
    """Every hub x consumer, whether it stamps, and which leads still wait to become verified pearls."""
    out = []
    for hub_key in HUBS:
        for consumer_key in CONSUMERS:
            defn = stamp(hub_key, consumer_key)
            row = {"hub": hub_key, "consumer": consumer_key, "stamps": defn is not None}
            if defn and len(defn["slots"]) == 3:
                row["bridge"] = defn["slots"][1]["contract"]
            if defn:
                row["slug"] = defn["slug"]
                row["waiting_for"] = [m["resource_id"] for s in defn["slots"] for m in s["chain"]
                                      if m["kind"] == "external" and m["state"] == "planned"]
                problems = model.validate(defn)
                row["valid"] = not problems
                if problems:
                    row["why"] = problems
            out.append(row)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    one = sub.add_parser("stamp")
    one.add_argument("hub", choices=sorted(HUBS))
    one.add_argument("consumer", choices=sorted(CONSUMERS))
    one.add_argument("--write", action="store_true", help="write definitions/<slug>.json (never over an existing one)")
    args = parser.parse_args(argv)
    if args.command == "list":
        for row in pairs():
            print(json.dumps(row, ensure_ascii=False))
        return 0
    defn = stamp(args.hub, args.consumer)
    if defn is None:
        parser.error(f"hub {args.hub} does not give what {args.consumer} reads")
    if args.write:
        path = Path(model.DEFINITIONS) / f"{defn['slug']}.json"
        if path.exists():
            parser.error(f"{path} exists; a stamp never overwrites a definition")
        path.write_text(json.dumps(defn, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(path)
    else:
        print(json.dumps(defn, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

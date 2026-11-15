"""Gold set for the location hub necklaces, first quakes-near-address (100-necklace plan 4-1 and 7-2, workflow 11-15).

The task: where an address or landmark is (coordinates) and the M4.5+ earthquakes within 1,000 km of it in the last
7 days. Truth has two parts with different lifetimes:

- the place's coordinates, fixed: Wikidata P625 of the English Wikipedia article (one request per place, spaced one
  second, built once); a landmark must be met within 3 km, a city within 25 km (a geocoder gives a city's centre)
- the earthquakes, live: retest.quakes_reference asks the USGS FDSN event service with the same window when the case
  is graded, so the truth is never older than the answer (a stored list would be wrong within hours)

Places cover four strata: the Pacific rim in Asia and Oceania, the Americas' west, the Mediterranean to the Himalaya,
and stable regions where an empty week is the usual right answer. Cases go into tuning / holdout-r1 / holdout-r2 by
gold.split (30 each).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote

from .gold import Fetcher, _now, split, write_set
from .judge import DEFAULT_ROOT

SLUG = "quakes-near-address"
ANSWER_SET = "quakes-near-address-v1"
RADIUS_KM, DAYS, MIN_MAGNITUDE = 1000, 7, 4.5
TOLERANCE_KM = {"landmark": 3, "city": 25, "airport": 5, "street": 1.5}
WIKIDATA = "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=claims&sites=enwiki&titles="

# (address as a person types it, English Wikipedia title, kind, stratum)
PLACES = [
    ("Tokyo Tower, Minato, Tokyo, Japan", "Tokyo Tower", "landmark", "asia-pacific"),
    ("Osaka Castle, Osaka, Japan", "Osaka Castle", "landmark", "asia-pacific"),
    ("Sapporo Clock Tower, Sapporo, Japan", "Sapporo Clock Tower", "landmark", "asia-pacific"),
    ("Sendai Station, Sendai, Japan", "Sendai Station", "landmark", "asia-pacific"),
    ("Fukuoka Tower, Fukuoka, Japan", "Fukuoka Tower", "landmark", "asia-pacific"),
    ("Sakurajima, Kagoshima, Japan", "Sakurajima", "city", "asia-pacific"),
    ("Taipei 101, Taipei, Taiwan", "Taipei 101", "landmark", "asia-pacific"),
    ("Taroko National Park, Hualien, Taiwan", "Taroko National Park", "city", "asia-pacific"),
    ("Rizal Park, Manila, Philippines", "Rizal Park", "landmark", "asia-pacific"),
    ("Mount Apo, Davao, Philippines", "Mount Apo", "city", "asia-pacific"),
    ("National Monument, Jakarta, Indonesia", "National Monument (Indonesia)", "landmark", "asia-pacific"),
    ("Borobudur, Magelang, Indonesia", "Borobudur", "landmark", "asia-pacific"),
    ("Mount Bromo, East Java, Indonesia", "Mount Bromo", "city", "asia-pacific"),
    ("Lake Toba, North Sumatra, Indonesia", "Lake Toba", "city", "asia-pacific"),
    ("Sky Tower, Auckland, New Zealand", "Sky Tower (Auckland)", "landmark", "asia-pacific"),
    ("Hagley Park, Christchurch, New Zealand", "Hagley Park", "city", "asia-pacific"),
    ("Suva, Fiji", "Suva", "city", "asia-pacific"),
    ("Port Moresby, Papua New Guinea", "Port Moresby", "city", "asia-pacific"),
    ("Port Vila, Vanuatu", "Port Vila", "city", "asia-pacific"),
    ("Apia, Samoa", "Apia", "city", "asia-pacific"),
    ("Petropavlovsk-Kamchatsky, Russia", "Petropavlovsk-Kamchatsky", "city", "asia-pacific"),
    ("Yuzhno-Sakhalinsk, Russia", "Yuzhno-Sakhalinsk", "city", "asia-pacific"),
    ("N Seoul Tower, Seoul, South Korea", "N Seoul Tower", "landmark", "asia-pacific"),
    ("Haeundae Beach, Busan, South Korea", "Haeundae Beach", "landmark", "asia-pacific"),
    ("Guam", "Guam", "city", "asia-pacific"),
    ("Honiara, Solomon Islands", "Honiara", "city", "asia-pacific"),
    ("Nouméa, New Caledonia", "Nouméa", "city", "asia-pacific"),
    ("Golden Gate Bridge, San Francisco, CA, USA", "Golden Gate Bridge", "landmark", "americas-west"),
    ("Griffith Observatory, Los Angeles, CA, USA", "Griffith Observatory", "landmark", "americas-west"),
    ("Space Needle, Seattle, WA, USA", "Space Needle", "landmark", "americas-west"),
    ("Mount St. Helens, Washington, USA", "Mount St. Helens", "city", "americas-west"),
    ("Ted Stevens Anchorage International Airport, Anchorage, AK, USA",
     "Ted Stevens Anchorage International Airport", "landmark", "americas-west"),
    ("Kodiak, Alaska, USA", "Kodiak, Alaska", "city", "americas-west"),
    ("Unalaska, Alaska, USA", "Unalaska, Alaska", "city", "americas-west"),
    ("Hilo, Hawaii, USA", "Hilo, Hawaii", "city", "americas-west"),
    ("Palacio de Bellas Artes, Mexico City, Mexico", "Palacio de Bellas Artes", "landmark", "americas-west"),
    ("Monte Albán, Oaxaca, Mexico", "Monte Albán", "landmark", "americas-west"),
    ("Acapulco, Guerrero, Mexico", "Acapulco", "city", "americas-west"),
    ("Guatemala City, Guatemala", "Guatemala City", "city", "americas-west"),
    ("San Salvador, El Salvador", "San Salvador", "city", "americas-west"),
    ("Managua, Nicaragua", "Managua", "city", "americas-west"),
    ("San José, Costa Rica", "San José, Costa Rica", "city", "americas-west"),
    ("Quito, Ecuador", "Quito", "city", "americas-west"),
    ("Bogotá, Colombia", "Bogotá", "city", "americas-west"),
    ("Lima, Peru", "Lima", "city", "americas-west"),
    ("Arequipa, Peru", "Arequipa", "city", "americas-west"),
    ("La Paz, Bolivia", "La Paz", "city", "americas-west"),
    ("Santiago, Chile", "Santiago", "city", "americas-west"),
    ("Valparaíso, Chile", "Valparaíso", "city", "americas-west"),
    ("Antofagasta, Chile", "Antofagasta", "city", "americas-west"),
    ("Mendoza, Argentina", "Mendoza, Argentina", "city", "americas-west"),
    ("Stanley Park, Vancouver, BC, Canada", "Stanley Park", "city", "americas-west"),
    ("Victoria, British Columbia, Canada", "Victoria, British Columbia", "city", "americas-west"),
    ("Reno, Nevada, USA", "Reno, Nevada", "city", "americas-west"),
    ("Temple Square, Salt Lake City, UT, USA", "Temple Square", "landmark", "americas-west"),
    ("Hagia Sophia, Istanbul, Turkey", "Hagia Sophia", "landmark", "mediterranean-himalaya"),
    ("İzmir, Turkey", "İzmir", "city", "mediterranean-himalaya"),
    ("Acropolis of Athens, Athens, Greece", "Acropolis of Athens", "landmark", "mediterranean-himalaya"),
    ("Heraklion, Crete, Greece", "Heraklion", "city", "mediterranean-himalaya"),
    ("Colosseum, Rome, Italy", "Colosseum", "landmark", "mediterranean-himalaya"),
    ("Mount Etna, Sicily, Italy", "Mount Etna", "city", "mediterranean-himalaya"),
    ("Mount Vesuvius, Naples, Italy", "Mount Vesuvius", "city", "mediterranean-himalaya"),
    ("Azadi Tower, Tehran, Iran", "Azadi Tower", "landmark", "mediterranean-himalaya"),
    ("Persepolis, Fars, Iran", "Persepolis", "landmark", "mediterranean-himalaya"),
    ("Arg-e Bam, Bam, Iran", "Arg-e Bam", "landmark", "mediterranean-himalaya"),
    ("Kathmandu Durbar Square, Kathmandu, Nepal", "Kathmandu Durbar Square", "landmark", "mediterranean-himalaya"),
    ("Faisal Mosque, Islamabad, Pakistan", "Faisal Mosque", "landmark", "mediterranean-himalaya"),
    ("Kabul, Afghanistan", "Kabul", "city", "mediterranean-himalaya"),
    ("Tashkent, Uzbekistan", "Tashkent", "city", "mediterranean-himalaya"),
    ("Almaty, Kazakhstan", "Almaty", "city", "mediterranean-himalaya"),
    ("Bishkek, Kyrgyzstan", "Bishkek", "city", "mediterranean-himalaya"),
    ("Belém Tower, Lisbon, Portugal", "Belém Tower", "landmark", "mediterranean-himalaya"),
    ("Algiers, Algeria", "Algiers", "city", "mediterranean-himalaya"),
    ("Yerevan, Armenia", "Yerevan", "city", "mediterranean-himalaya"),
    ("Tbilisi, Georgia", "Tbilisi", "city", "mediterranean-himalaya"),
    ("Masada, Israel", "Masada", "landmark", "mediterranean-himalaya"),
    ("Potala Palace, Lhasa, China", "Potala Palace", "landmark", "mediterranean-himalaya"),
    ("Chengdu, Sichuan, China", "Chengdu", "city", "mediterranean-himalaya"),
    ("Kunming, Yunnan, China", "Kunming", "city", "mediterranean-himalaya"),
    ("Eiffel Tower, Paris, France", "Eiffel Tower", "landmark", "stable"),
    ("Brandenburg Gate, Berlin, Germany", "Brandenburg Gate", "landmark", "stable"),
    ("Big Ben, London, UK", "Big Ben", "landmark", "stable"),
    ("Red Square, Moscow, Russia", "Red Square", "landmark", "stable"),
    ("Stockholm Palace, Stockholm, Sweden", "Stockholm Palace", "landmark", "stable"),
    ("Helsinki Cathedral, Helsinki, Finland", "Helsinki Cathedral", "landmark", "stable"),
    ("Palace of Culture and Science, Warsaw, Poland", "Palace of Culture and Science", "landmark", "stable"),
    ("Sydney Opera House, Sydney, Australia", "Sydney Opera House", "landmark", "stable"),
    ("Uluru, Northern Territory, Australia", "Uluru", "landmark", "stable"),
    ("Kings Park, Perth, Australia", "Kings Park, Western Australia", "city", "stable"),
    ("Table Mountain, Cape Town, South Africa", "Table Mountain", "city", "stable"),
    ("Johannesburg, South Africa", "Johannesburg", "city", "stable"),
    ("Nairobi, Kenya", "Nairobi", "city", "stable"),
    ("Lagos, Nigeria", "Lagos", "city", "stable"),
    ("Cathedral of Brasília, Brasília, Brazil", "Cathedral of Brasília", "landmark", "stable"),
    ("Obelisco de Buenos Aires, Buenos Aires, Argentina", "Obelisco de Buenos Aires", "landmark", "stable"),
    ("Willis Tower, Chicago, IL, USA", "Willis Tower", "landmark", "stable"),
    ("CN Tower, Toronto, Canada", "CN Tower", "landmark", "stable"),
    ("Washington Monument, Washington, DC, USA", "Washington Monument", "landmark", "stable"),
    ("Statue of Liberty, New York, NY, USA", "Statue of Liberty", "landmark", "stable"),
    ("Miami, Florida, USA", "Miami", "city", "stable"),
    ("Dallas, Texas, USA", "Dallas", "city", "stable"),
]


def coordinates(entity: dict) -> tuple[float, float] | None:
    for claim in ((entity or {}).get("claims") or {}).get("P625") or []:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
        if isinstance(value.get("latitude"), (int, float)) and isinstance(value.get("longitude"), (int, float)):
            return round(value["latitude"], 6), round(value["longitude"], 6)
    return None


def place_cases(f: Fetcher) -> list[dict]:
    cases = []
    for address, title, kind, stratum in PLACES:
        body = f.json(WIKIDATA + quote(title, safe="")) or {}
        entity = next((e for qid, e in (body.get("entities") or {}).items() if not qid.startswith("-")), None)
        where = coordinates(entity)
        if where is None:
            continue
        cases.append({"case_id": "place:" + title, "task_type": "whole_task", "stratum": stratum,
                      "input": {"address": address},
                      "truth": {"lat": where[0], "lon": where[1], "qid": entity.get("id"), "kind": kind,
                                "tolerance_km": TOLERANCE_KM[kind], "radius_km": RADIUS_KM, "days": DAYS,
                                "min_magnitude": MIN_MAGNITUDE},
                      "truth_sources": [{"name": "Wikidata P625 (coordinate location) of the English Wikipedia article",
                                         "url": f"https://www.wikidata.org/wiki/{entity.get('id')}", "fetched_at": _now()},
                                        {"name": "USGS FDSN event service, asked when the case is graded",
                                         "url": "https://earthquake.usgs.gov/fdsnws/event/1/"}]})
    return cases


# quakes-near-airport (PM 13:42): the airport's reference point from OurAirports (public domain), one download of
# airports.csv through the shared ledger as reference_checks; the quakes part is the same live USGS reference.
AIRPORT_SLUG = "quakes-near-airport"
OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORTS = {
    "asia-pacific": ["NRT", "HND", "KIX", "CTS", "FUK", "OKA", "SDJ", "TPE", "KHH", "MNL", "CEB", "DVO", "CGK", "DPS",
                     "SUB", "AKL", "CHC", "WLG", "NAN", "POM", "ICN", "PUS", "GUM", "HKG", "KUL"],
    "americas-west": ["SFO", "LAX", "SEA", "PDX", "ANC", "FAI", "HNL", "OGG", "MEX", "GDL", "ACA", "GUA", "SAL", "MGA",
                      "SJO", "BOG", "UIO", "LIM", "SCL", "MDZ", "YVR", "SLC", "LAS", "SAN", "SJC"],
    "mediterranean-himalaya": ["IST", "ADB", "ATH", "HER", "FCO", "CTA", "NAP", "IKA", "KTM", "ISB", "KBL", "TAS", "ALA",
                               "FRU", "LIS", "ALG", "EVN", "TBS", "TLV", "LXA", "CTU", "KMG", "SKG", "SOF", "OTP"],
    "stable": ["CDG", "FRA", "LHR", "AMS", "SVO", "ARN", "HEL", "WAW", "SYD", "MEL", "PER", "CPT", "JNB", "NBO", "LOS",
               "GRU", "EZE", "ORD", "YYZ", "JFK", "MIA", "DFW", "ATL", "DXB", "SIN"],
}


def airport_cases(csv_text: str) -> tuple[list[dict], list[str]]:
    import csv
    import io
    wanted = {code: stratum for stratum, codes in AIRPORTS.items() for code in codes}
    found = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        code = (row.get("iata_code") or "").strip()
        if code in wanted and code not in found and row.get("type") in ("large_airport", "medium_airport"):
            try:
                found[code] = (round(float(row["latitude_deg"]), 6), round(float(row["longitude_deg"]), 6),
                               row.get("name") or "", row.get("ident") or "", row.get("iso_country") or "")
            except (KeyError, ValueError):
                continue
    cases = []
    for code, stratum in wanted.items():
        if code not in found:
            continue
        lat, lon, name, ident, country = found[code]
        cases.append({"case_id": "airport:" + code, "task_type": "whole_task", "stratum": stratum,
                      "input": {"code": code},
                      "truth": {"lat": lat, "lon": lon, "name": name, "icao": ident, "country": country,
                                "kind": "airport", "tolerance_km": TOLERANCE_KM["airport"], "radius_km": RADIUS_KM,
                                "days": DAYS, "min_magnitude": MIN_MAGNITUDE},
                      "truth_sources": [{"name": "OurAirports airports.csv (public domain)", "url": OURAIRPORTS,
                                         "fetched_at": _now()},
                                        {"name": "USGS FDSN event service, asked when the case is graded",
                                         "url": "https://earthquake.usgs.gov/fdsnws/event/1/"}]})
    return cases, sorted(set(wanted) - set(found))


def build_airports(root: Path = DEFAULT_ROOT, get=None, raw_dir: Path | None = None) -> dict:
    from .gold_filings import fetch_text
    raw = (get or fetch_text)(OURAIRPORTS)
    text = raw.encode("latin-1", "replace").decode("utf-8", "replace") if get is None else raw   # fetch_text reads latin-1
    cases, dropped = airport_cases(text)
    if raw_dir:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "airport-cases.json").write_text(json.dumps({"cases": cases, "dropped": dropped}, ensure_ascii=False))
    manifest = write_set(Path(root), AIRPORT_SLUG, split(cases),
                         {"answer_set": "quakes-near-airport-v1", "built_from": len(cases),
                          "listed": sum(len(v) for v in AIRPORTS.values())})
    return {"manifest": manifest, "dropped": dropped}


# census-geocode substitute (US addresses only, PM 14:25): US street addresses, a split of its own in the
# quakes-near-address folder. Street address (P6375) and coordinates (P625) from Wikidata; city and state as typed.
US_BUILDINGS = [
    ("White House", "Washington, DC"), ("United States Capitol", "Washington, DC"),
    ("Thomas Jefferson Building", "Washington, DC"), ("Empire State Building", "New York, NY"),
    ("Chrysler Building", "New York, NY"), ("Flatiron Building", "New York, NY"),
    ("Metropolitan Museum of Art", "New York, NY"), ("Solomon R. Guggenheim Museum", "New York, NY"),
    ("Madison Square Garden", "New York, NY 10001"), ("Willis Tower", "Chicago, IL"), ("Wrigley Field", "Chicago, IL"),
    ("Art Institute of Chicago", "Chicago, IL"), ("Space Needle", "Seattle, WA"), ("Seattle Central Library", "Seattle, WA"),
    ("Transamerica Pyramid", "San Francisco, CA"), ("Coit Tower", "San Francisco, CA"),
    ("Griffith Observatory", "Los Angeles, CA"), ("Walt Disney Concert Hall", "Los Angeles, CA"),
    ("Dodger Stadium", "Los Angeles, CA"), ("Hollywood Bowl", "Los Angeles, CA 90068"), ("Getty Center", "Los Angeles, CA"),
    ("Fenway Park", "Boston, MA"), ("Massachusetts State House", "Boston, MA 02133"), ("Independence Hall", "Philadelphia, PA"),
    ("Philadelphia Museum of Art", "Philadelphia, PA 19130"), ("Gateway Arch", "St. Louis, MO"), ("Graceland", "Memphis, TN"),
    ("Texas State Capitol", "Austin, TX"), ("Reunion Tower", "Dallas, TX"),
    ("Colorado State Capitol", "Denver, CO"), ("Bellagio (resort)", "Las Vegas, NV"), ("ʻIolani Palace", "Honolulu, HI"),
    ("Mall of America", "Bloomington, MN"), ("Lambeau Field", "Green Bay, WI"),
    ("Rock and Roll Hall of Fame", "Cleveland, OH"), ("Biltmore Estate", "Asheville, NC"), ("Georgia Aquarium", "Atlanta, GA"),
    ("Salt Lake Temple", "Salt Lake City, UT"), ("Hearst Castle", "San Simeon, CA"), ("Smithsonian Institution Building", "Washington, DC"),
    ("Kennedy Space Center Visitor Complex", "Merritt Island, FL"), ("Fontainebleau Miami Beach", "Miami Beach, FL"),
    ("Wisconsin State Capitol", "Madison, WI"), ("Oregon State Capitol", "Salem, OR"),
]


# 11-15 tuning round (agent team, 23 of 28): Ryman Auditorium left out (its Wikidata point sits at Opryland, not at
# 116 5th Ave N), ZIP codes added where the Census matched another street of the same name (State House 02133) or
# found none (Madison Square Garden, Philadelphia Museum of Art, Hollywood Bowl with the street written out).
# Street addresses typed by the workflow team where Wikidata has none (P6375 on 12 of 45 on 11-15); the truth point is
# still the building's Wikidata P625, and the tuning round shows any address that lands farther than the tolerance.
TYPED_STREETS = {
    "Empire State Building": "350 5th Ave", "Chrysler Building": "405 Lexington Ave", "Flatiron Building": "175 5th Ave",
    "Metropolitan Museum of Art": "1000 5th Ave", "Solomon R. Guggenheim Museum": "1071 5th Ave",
    "Willis Tower": "233 S Wacker Dr", "Wrigley Field": "1060 W Addison St", "Space Needle": "400 Broad St",
    "Transamerica Pyramid": "600 Montgomery St", "Coit Tower": "1 Telegraph Hill Blvd",
    "Griffith Observatory": "2800 E Observatory Rd", "Walt Disney Concert Hall": "111 S Grand Ave",
    "Dodger Stadium": "1000 Vin Scully Ave", "Hollywood Bowl": "2301 North Highland Avenue", "Getty Center": "1200 Getty Center Dr",
    "Fenway Park": "4 Jersey St", "Massachusetts State House": "24 Beacon St", "Independence Hall": "520 Chestnut St",
    "Philadelphia Museum of Art": "2600 Benjamin Franklin Parkway", "Graceland": "3764 Elvis Presley Blvd",
    "Reunion Tower": "300 Reunion Blvd E", "Colorado State Capitol": "200 E Colfax Ave",
    "Bellagio (resort)": "3600 S Las Vegas Blvd", "ʻIolani Palace": "364 S King St", "Mall of America": "60 E Broadway",
    "Lambeau Field": "1265 Lombardi Ave", "Rock and Roll Hall of Fame": "1100 E 9th St",
    "Georgia Aquarium": "225 Baltimore Ave NW", "Texas State Capitol": "1100 Congress Ave",
    "Wisconsin State Capitol": "2 E Main St", "Oregon State Capitol": "900 Court St NE",
}


def street_address(entity: dict) -> str | None:
    for claim in ((entity or {}).get("claims") or {}).get("P6375") or []:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict) and isinstance(value.get("text"), str) and value["text"][:1].isdigit():
            return value["text"].strip()
    return None


def us_street_cases(f: Fetcher) -> tuple[list[dict], list[str]]:
    cases, dropped = [], []
    for title, city in US_BUILDINGS:
        body = f.json(WIKIDATA + quote(title, safe="")) or {}
        entity = next((e for qid, e in (body.get("entities") or {}).items() if not qid.startswith("-")), None)
        where, street = coordinates(entity), street_address(entity) or TYPED_STREETS.get(title)
        if where is None or not street:
            dropped.append(title)
            continue
        street = street.split(",")[0].strip()
        cases.append({"case_id": "street:" + title, "task_type": "whole_task", "stratum": "us-street",
                      "input": {"address": f"{street}, {city}, USA"},
                      "truth": {"lat": where[0], "lon": where[1], "qid": entity.get("id"), "kind": "street",
                                "country": "US", "tolerance_km": TOLERANCE_KM["street"], "radius_km": RADIUS_KM,
                                "days": DAYS, "min_magnitude": MIN_MAGNITUDE},
                      "truth_sources": [{"name": "Wikidata P6375 (street address) and P625 (coordinates)",
                                         "url": f"https://www.wikidata.org/wiki/{entity.get('id')}", "fetched_at": _now()}]})
    return cases, dropped


def build_us_streets(root: Path = DEFAULT_ROOT, fetcher: Fetcher | None = None) -> dict:
    """Write gold/quakes-near-address/us-street.jsonl and its manifest entry (other splits stay as they are)."""
    import hashlib
    f = fetcher or Fetcher(spacing={"www.wikidata.org": 1.0})
    cases, dropped = us_street_cases(f)
    folder = Path(root) / "gold" / SLUG
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (folder / "us-street.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("files", {})["us-street"] = {"cases": len(cases), "strata": {"us-street": len(cases)},
                                                     "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                                     "for": "census-geocode substitute gate"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"cases": len(cases), "dropped": dropped, "calls": f.calls}


def build(root: Path = DEFAULT_ROOT, fetcher: Fetcher | None = None, raw_dir: Path | None = None) -> dict:
    f = fetcher or Fetcher(spacing={"www.wikidata.org": 1.0})
    cases = place_cases(f)
    if raw_dir:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "place-cases.json").write_text(json.dumps(cases, ensure_ascii=False))
    manifest = write_set(Path(root), SLUG, split(cases), {"answer_set": ANSWER_SET, "built_from": len(cases),
                                                         "listed": len(PLACES)})
    return {"manifest": manifest, "calls": f.calls, "dropped": [t for _, t, _, _ in PLACES
                                                                if "place:" + t not in {c["case_id"] for c in cases}]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--airports", action="store_true", help="build quakes-near-airport from OurAirports instead")
    parser.add_argument("--us-streets", action="store_true", help="add the us-street split for census-geocode")
    args = parser.parse_args(argv)
    if args.us_streets:
        print(json.dumps(build_us_streets(args.root), ensure_ascii=False))
        return 0
    if args.airports:
        print(json.dumps(build_airports(args.root, raw_dir=args.raw_dir), ensure_ascii=False))
        return 0
    print(json.dumps(build(args.root, raw_dir=args.raw_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

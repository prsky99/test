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
TOLERANCE_KM = {"landmark": 3, "city": 25}
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
    args = parser.parse_args(argv)
    print(json.dumps(build(args.root, raw_dir=args.raw_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

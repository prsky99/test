"""Build the offline country grid read by agent_market.fallback_agents.country_grid (PM 11-15 13:58).

Run OUTSIDE production, in the same throwaway Python 3.12 venv as the time-zone grid, with shapely and pyshp,
on Natural Earth 1:10m Admin 0 countries and disputed areas (public domain, naturalearthdata.com):

    /tmp/tzbuild/bin/pip install shapely pyshp
    /tmp/tzbuild/bin/python scripts/build_country_grid.py build <dir with the two unzipped shapefiles> \
        gateway-data/fallback-agents/country-grid.bin
    /tmp/tzbuild/bin/python scripts/build_country_grid.py check <same dir> gateway-data/fallback-agents/country-grid.bin \
        --airports gateway-data/fallback-agents/airports.json

Production never imports shapely; it reads the file (gateway-data, not in git) in the time-zone grid's format
(agent_market/fallback_agents/tz_grid.py): names are ISO 3166-1 alpha-2 codes, "" is no country (sea).

A cell takes the country found at its four corners and its centre when all five agree; otherwise it is a boundary
cell holding the candidates. A point in a Natural Earth disputed area, or in a country polygon without an ISO code
(Somaliland, Northern Cyprus, Siachen Glacier ...), is never one country: its cell holds the administering country
and every claimant named in the area's note ("Admin. by India; Claimed by Pakistan") and is listed in the header's
"disputed" sets.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import struct
import time
import zlib
from array import array
from pathlib import Path

STEP = float(os.environ.get("COUNTRY_GRID_STEP", "0.02"))
COLS = round(360 / STEP)
ROWS = round(180 / STEP)
MAGIC = b"AVCTZ1\n"
SET_BASE = 32768
BAND = 200
ATTRIBUTION = ("Country borders: Natural Earth 1:10m Admin 0 countries and disputed areas (public domain, "
               "naturalearthdata.com); a precomputed 0.02-degree grid.")


def _layers(folder: Path):
    import shapefile
    from shapely.geometry import shape
    countries = shapefile.Reader(str(folder / "ne_10m_admin_0_countries.shp"))
    by_name = {}
    polys = []
    for sr in countries.iterShapeRecords():
        rec = sr.record.as_dict()
        code = rec["ISO_A2_EH"] if re.fullmatch(r"[A-Z]{2}", rec["ISO_A2_EH"] or "") else None
        for key in ("NAME", "NAME_LONG", "ADMIN", "SOVEREIGNT", "BRK_NAME"):
            if code and rec.get(key):
                by_name.setdefault(str(rec[key]).lower(), code)
        polys.append((shape(sr.shape.__geo_interface__), code, rec["NAME"]))
    disputed = shapefile.Reader(str(folder / "ne_10m_admin_0_disputed_areas.shp"))
    areas = []
    for sr in disputed.iterShapeRecords():
        rec = sr.record.as_dict()
        names = re.findall(r"(?:Admin\. by|Claimed by|claimed by|and)\s+([A-Z][A-Za-z .'-]+?)(?=;|,| and |$)",
                           rec.get("NOTE_BRK") or "")
        codes = {by_name.get(n.strip().lower()) for n in names} | {by_name.get(str(rec.get("SOVEREIGNT") or "").lower())}
        if re.fullmatch(r"[A-Z]{2}", rec.get("ISO_A2_EH") or ""):
            codes.add(rec["ISO_A2_EH"])
        areas.append((shape(sr.shape.__geo_interface__), tuple(sorted(c for c in codes if c)), rec.get("BRK_NAME")))
    return polys, areas


def _values(polys, areas, lats, lons):
    """Value per point: a country code, "" for none, or ("DISPUTED", codes...) for a disputed point."""
    import numpy as np
    import shapely
    out = np.full(lats.shape, "", dtype=object)
    for geom, code, name in polys:
        x0, y0, x1, y1 = geom.bounds
        mask = (lons >= x0) & (lons <= x1) & (lats >= y0) & (lats <= y1)
        if not mask.any():
            continue
        inside = shapely.contains_xy(geom, lons[mask], lats[mask])
        idx = np.flatnonzero(mask)[inside]
        if code:
            out.flat[idx] = code
        else:   # one by one: assigning a tuple to many cells of an object array would spread its items over them
            for i in idx:
                out.flat[i] = ("DISPUTED", "?" + str(name))
    for geom, codes, name in areas:
        x0, y0, x1, y1 = geom.bounds
        mask = (lons >= x0) & (lons <= x1) & (lats >= y0) & (lats <= y1)
        if not mask.any():
            continue
        inside = shapely.contains_xy(geom, lons[mask], lats[mask])
        for i in np.flatnonzero(mask)[inside]:
            out.flat[i] = ("DISPUTED",) + codes
    return out


def build(folder: Path, path: Path) -> dict:
    import numpy as np
    started = time.time()
    polys, areas = _layers(folder)
    for geom, _, _ in polys + [(a, None, None) for a, _, _ in areas]:
        import shapely
        shapely.prepare(geom)
    names: dict[str, int] = {}
    sets: dict[tuple, int] = {}
    disputed_sets: set[int] = set()
    encoded = bytearray()
    boundary = disputed_cells = total = 0
    lon_edges = -180 + np.arange(COLS + 1) * STEP
    lon_mid = -180 + (np.arange(COLS) + 0.5) * STEP
    for start in range(0, ROWS, BAND):
        stop = min(ROWS, start + BAND)
        lat_edges = 90 - np.arange(start, stop + 1) * STEP
        ey, ex = np.meshgrid(lat_edges, lon_edges, indexing="ij")
        edge = _values(polys, areas, ey, ex)
        lat_mid = 90 - (np.arange(start, stop) + 0.5) * STEP
        my, mx = np.meshgrid(lat_mid, lon_mid, indexing="ij")
        mid = _values(polys, areas, my, mx)
        for r in range(stop - start):
            starts, values, last = array("H"), array("H"), None
            for c in range(COLS):
                samples = {edge[r, c], edge[r, c + 1], edge[r + 1, c], edge[r + 1, c + 1], mid[r, c]}
                total += 1
                if len(samples) == 1 and not isinstance(next(iter(samples)), tuple):
                    value = names.setdefault(next(iter(samples)), len(names))
                else:
                    codes, is_disputed = set(), False
                    for s in samples:
                        if isinstance(s, tuple):
                            is_disputed = True
                            codes.update(x for x in s[1:] if not x.startswith("?"))
                        elif s:
                            codes.add(s)
                    key = tuple(sorted(codes)) + (("*disputed*",) if is_disputed else ())
                    for code in codes:
                        names.setdefault(code, len(names))
                    k = sets.setdefault(key, len(sets))
                    if is_disputed:
                        disputed_sets.add(k)
                        disputed_cells += 1
                    else:
                        boundary += 1
                    value = SET_BASE + k
                if value != last:
                    starts.append(c)
                    values.append(value)
                    last = value
            encoded += struct.pack("<I", len(starts)) + starts.tobytes() + values.tobytes()
    zone_list = [n for n, _ in sorted(names.items(), key=lambda x: x[1])]
    set_list = [[c for c in s if c != "*disputed*"] for s, _ in sorted(sets.items(), key=lambda x: x[1])]
    header = {"format": "avc-country-grid-1", "step": STEP, "rows": ROWS, "cols": COLS, "zones": zone_list,
              "sets": set_list, "disputed": sorted(disputed_sets), "countries": {},
              "attribution": ATTRIBUTION, "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "natural_earth": (folder / "ne_10m_admin_0_countries.VERSION.txt").read_text().strip()
              if (folder / "ne_10m_admin_0_countries.VERSION.txt").exists() else None,
              "boundary_cells": boundary, "disputed_cells": disputed_cells, "cells": total}
    raw = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(MAGIC + struct.pack("<I", len(raw)) + raw + zlib.compress(bytes(encoded), 9))
    tmp.replace(path)
    return {"seconds": round(time.time() - started), "bytes": path.stat().st_size, "countries": len(zone_list),
            "boundary_share": round(boundary / total, 5), "disputed_share": round(disputed_cells / total, 5)}


def check(folder: Path, path: Path, airports: Path | None, points: int, seed: int) -> dict:
    import importlib.util
    import sys
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_market/fallback_agents"))
    spec = importlib.util.spec_from_file_location(
        "country_grid", Path(__file__).resolve().parents[1] / "agent_market/fallback_agents/country_grid.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    grid = module.CountryGrid(path)
    polys, areas = _layers(folder)

    def truth(lat, lon):
        v = _values(polys, areas, np.array([lat]), np.array([lon]))[0]
        return None if isinstance(v, tuple) else v

    def compare(lat, lon, want=None):
        got = grid.lookup(lat, lon)
        t = truth(lat, lon) if want is None else want
        if got["country"] is not None:
            return ("right" if got["country"] == t else "wrong"), t, got
        if t is None:
            return "disputed_not_decided", t, got
        return ("candidates_have_truth" if t in got["candidates"] else "candidates_missing_truth"), t, got
    rnd = random.Random(seed)
    out, tally = {}, {}
    land = 0
    while land < points:     # land points only: the sea is "" everywhere and says little
        lat, lon = rnd.uniform(-60, 75), rnd.uniform(-180, 180)
        if not truth(lat, lon) and truth(lat, lon) is not None:
            continue
        land += 1
        kind, _, _ = compare(lat, lon)
        tally[kind] = tally.get(kind, 0) + 1
    out["random_land"] = tally
    if airports:
        data = json.loads(airports.read_text(encoding="utf-8"))
        seen, tally, problems = set(), {}, []
        for rec in (data.get("airports") or {}).values():
            if rec.get("type") not in ("large_airport", "medium_airport") or rec.get("ident") in seen:
                continue
            seen.add(rec["ident"])
            lat, lon = float(rec["latitude_deg"]), float(rec["longitude_deg"])
            kind, t, got = compare(lat, lon, rec.get("iso_country"))
            tally[kind] = tally.get(kind, 0) + 1
            if kind in ("wrong", "candidates_missing_truth"):
                problems.append({"ident": rec["ident"], "ourairports": rec.get("iso_country"), "got": got})
        out["airports_vs_ourairports"] = tally
        out["airport_problems"] = problems[:60]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("folder", type=Path)
    b.add_argument("path", type=Path)
    c = sub.add_parser("check")
    c.add_argument("folder", type=Path)
    c.add_argument("path", type=Path)
    c.add_argument("--airports", type=Path)
    c.add_argument("--points", type=int, default=20_000)
    c.add_argument("--seed", type=int, default=20261115)
    args = parser.parse_args(argv)
    if args.cmd == "build":
        print(json.dumps(build(args.folder, args.path)))
    else:
        print(json.dumps(check(args.folder, args.path, args.airports, args.points, args.seed), ensure_ascii=False))


if __name__ == "__main__":
    main()

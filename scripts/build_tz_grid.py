"""Build the offline time-zone grid read by agent_market.fallback_agents.tz_grid (PM 11-15 13:52, option B).

Run OUTSIDE production, in a throwaway Python 3.12 venv that has timezonefinder (MIT) and its boundary data
(timezone-boundary-builder, ODbL 1.0, from OpenStreetMap contributors):

    python3.12 -m venv /tmp/tzbuild && /tmp/tzbuild/bin/pip install timezonefinder==9.2.0
    /tmp/tzbuild/bin/python scripts/build_tz_grid.py build gateway-data/fallback-agents/tz-grid.bin
    /tmp/tzbuild/bin/python scripts/build_tz_grid.py check gateway-data/fallback-agents/tz-grid.bin \
        --airports gateway-data/fallback-agents/airports.json

Production code never imports timezonefinder; it reads the file this writes (gateway-data, not in git).

Grid: cells of STEP degrees. A cell takes the zone found at its four corners and its centre when all five agree;
otherwise it is a boundary cell holding the distinct zones found (candidates), and the reader answers "near a time
zone boundary" with them. Rows are run-length encoded. The header carries the zone names, candidate sets, the
countries of each zone (tzdata zone1970.tab and zone.tab) and the attribution.

File: b"AVCTZ1\\n", uint32 header length, header JSON (utf-8), then zlib of the rows. Each row is uint32 run count,
then that many uint16 start columns and that many uint16 values. A value below 32768 is a zone index; 32768 + k is
candidate set k.
"""
from __future__ import annotations

import argparse
import json
import random
import struct
import sys
import time
import zlib
from array import array
from multiprocessing import Pool
from pathlib import Path

import os

STEP = float(os.environ.get("TZ_GRID_STEP", "0.02"))   # a coarser step only for a quick trial
COLS = round(360 / STEP)
ROWS = round(180 / STEP)
MAGIC = b"AVCTZ1\n"
SET_BASE = 32768
ATTRIBUTION = ("Time zone boundaries: timezone-boundary-builder (github.com/evansiroky/timezone-boundary-builder), "
               "ODbL 1.0, data from OpenStreetMap contributors; computed with timezonefinder (MIT).")

_tf = None


def _finder():
    global _tf
    if _tf is None:
        from timezonefinder import TimezoneFinder
        _tf = TimezoneFinder()
    return _tf


def _zone(lat: float, lon: float) -> str:
    lon = -180.0 if lon >= 180.0 else lon
    lat = max(-90.0, min(90.0, lat))
    return _finder().timezone_at(lng=lon, lat=lat) or "Etc/Unknown"


def _band(rows: range):
    """Run-length encoded cells of the given rows (row 0 is the northern edge, lat 90):
    list of (row, [(start col, zone name or sorted tuple of candidates), ...])."""
    out = []
    top = [_zone(90 - rows.start * STEP, -180 + c * STEP) for c in range(COLS + 1)]
    for r in rows:
        lat_top, lat_bot = 90 - r * STEP, 90 - (r + 1) * STEP
        mid = (lat_top + lat_bot) / 2
        bottom = [_zone(lat_bot, -180 + c * STEP) for c in range(COLS + 1)]
        runs, last = [], None
        for c in range(COLS):
            zones = {top[c], top[c + 1], bottom[c], bottom[c + 1], _zone(mid, -180 + (c + 0.5) * STEP)}
            value = zones.pop() if len(zones) == 1 else tuple(sorted(zones))
            if value != last:
                runs.append((c, value))
                last = value
        out.append((r, runs))
        top = bottom
    return out


def _countries() -> dict[str, list[str]]:
    import tzdata
    base = Path(tzdata.__file__).parent / "zoneinfo"
    out: dict[str, set] = {}
    for name in ("zone1970.tab", "zone.tab"):
        path = base / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                for cc in parts[0].split(","):
                    out.setdefault(parts[2], set()).add(cc)
    return {z: sorted(c) for z, c in out.items()}


def build(path: Path, workers: int) -> dict:
    import importlib.metadata as md
    started = time.time()
    bands = [range(r, min(r + 25, ROWS)) for r in range(0, ROWS, 25)]
    names: dict[str, int] = {}
    sets: dict[tuple, int] = {}
    encoded = bytearray()
    boundary = total = 0
    expected = 0
    with Pool(workers) as pool:
        for chunk in pool.imap(_band, bands):          # in row order: each band is written as it arrives
            for r, runs in chunk:
                assert r == expected
                expected += 1
                starts, values = array("H"), array("H")
                for i, (c, zones) in enumerate(runs):
                    width = (runs[i + 1][0] if i + 1 < len(runs) else COLS) - c
                    total += width
                    if isinstance(zones, tuple):
                        boundary += width
                        for z in zones:
                            names.setdefault(z, len(names))
                        value = SET_BASE + sets.setdefault(zones, len(sets))
                    else:
                        value = names.setdefault(zones, len(names))
                    starts.append(c)
                    values.append(value)
                encoded += struct.pack("<I", len(starts)) + starts.tobytes() + values.tobytes()
    zone_list = [n for n, _ in sorted(names.items(), key=lambda x: x[1])]
    countries = _countries()
    header = {"format": "avc-tz-grid-1", "step": STEP, "rows": ROWS, "cols": COLS, "zones": zone_list,
              "sets": [list(s) for s, _ in sorted(sets.items(), key=lambda x: x[1])],
              "countries": {z: countries.get(z, []) for z in zone_list},
              "attribution": ATTRIBUTION, "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "timezonefinder": md.version("timezonefinder"), "boundary_data": md.version("timezonefinder-data"),
              "boundary_cells": boundary, "cells": total}
    raw = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode()
    body = zlib.compress(bytes(encoded), 9)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(MAGIC + struct.pack("<I", len(raw)) + raw + body)
    tmp.replace(path)
    return {"seconds": round(time.time() - started), "bytes": path.stat().st_size, "zones": len(zone_list),
            "sets": len(sets), "boundary_cells": boundary, "cells": total,
            "boundary_share": round(boundary / total, 5)}


def check(path: Path, airports: Path | None, points: int, seed: int) -> dict:
    """Compare the grid's answers with timezonefinder: random points, then every large and medium airport."""
    import importlib.util   # the reader file alone: the build venv has no production dependencies
    spec = importlib.util.spec_from_file_location(
        "tz_grid", Path(__file__).resolve().parents[1] / "agent_market/fallback_agents/tz_grid.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    TzGrid = module.TzGrid
    grid = TzGrid(path)
    rnd = random.Random(seed)

    def compare(lat, lon):
        truth = _zone(lat, lon)
        got = grid.lookup(lat, lon)
        if got["zone"] is not None:
            return "right" if got["zone"] == truth else "wrong", truth, got
        return ("boundary_has_truth" if truth in got["candidates"] else "boundary_missing_truth"), truth, got
    out = {}
    tally: dict[str, int] = {}
    for _ in range(points):
        lat, lon = rnd.uniform(-90, 90), rnd.uniform(-180, 180)
        kind, _, _ = compare(lat, lon)
        tally[kind] = tally.get(kind, 0) + 1
    out["random"] = tally
    if airports:
        data = json.loads(airports.read_text(encoding="utf-8"))
        seen, tally, wrong = set(), {}, []
        for rec in (data.get("airports") or {}).values():
            if rec.get("type") not in ("large_airport", "medium_airport") or rec.get("ident") in seen:
                continue
            seen.add(rec["ident"])
            try:
                lat, lon = float(rec["latitude_deg"]), float(rec["longitude_deg"])
            except (KeyError, TypeError, ValueError):
                continue
            kind, truth, got = compare(lat, lon)
            tally[kind] = tally.get(kind, 0) + 1
            if kind in ("wrong", "boundary_missing_truth"):
                wrong.append({"ident": rec["ident"], "truth": truth, "got": got})
        out["airports"] = tally
        out["airport_problems"] = wrong[:50]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("path", type=Path)
    b.add_argument("--workers", type=int, default=6)
    c = sub.add_parser("check")
    c.add_argument("path", type=Path)
    c.add_argument("--airports", type=Path)
    c.add_argument("--points", type=int, default=100_000)
    c.add_argument("--seed", type=int, default=20261115)
    args = parser.parse_args(argv)
    if args.cmd == "build":
        print(json.dumps(build(args.path, args.workers)))
    else:
        print(json.dumps(check(args.path, args.airports, args.points, args.seed), ensure_ascii=False))


if __name__ == "__main__":
    main()

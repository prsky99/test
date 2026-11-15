"""Offline coordinate -> IANA time zone lookup from a prebuilt grid (PM 11-15 13:52, option B; no dependencies).

The grid is built outside production by scripts/build_tz_grid.py (timezonefinder over timezone-boundary-builder
data, ODbL) and kept at gateway-data/fallback-agents/tz-grid.bin (not in git). A cell whose corners and centre
fell in different zones is a boundary cell: the answer then names no single zone but the candidates, and a
country code (when the caller has one) narrows them through the zones' countries in tzdata's zone tables.
"""
from __future__ import annotations

import bisect
import json
import re
import struct
import threading
import zlib
from pathlib import Path

MAGIC = b"AVCTZ1\n"
SET_BASE = 32768
POINT = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*(?:,\s*([A-Za-z]{2}))?\s*$")


def parse_point(text: str):
    """(lat, lon, country or None) from "lat,lon" or "lat,lon,CC"; None when the text is not a coordinate pair."""
    match = POINT.match(str(text or ""))
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon, (match.group(3) or "").upper() or None


class TzGrid:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._loaded = None

    def _load(self):
        with self._lock:
            if self._loaded is None:
                raw = self.path.read_bytes()
                if not raw.startswith(MAGIC):
                    raise ValueError("not a time-zone grid file")
                size = struct.unpack_from("<I", raw, len(MAGIC))[0]
                start = len(MAGIC) + 4
                header = json.loads(raw[start:start + size])
                body = zlib.decompress(raw[start + size:])
                offsets, pos = [], 0
                for _ in range(header["rows"]):
                    n = struct.unpack_from("<I", body, pos)[0]
                    offsets.append((pos + 4, n))
                    pos += 4 + 4 * n
                self._loaded = (header, memoryview(body), offsets)
            return self._loaded

    @property
    def header(self) -> dict:
        return self._load()[0]

    def lookup(self, lat: float, lon: float, country: str | None = None) -> dict:
        """{"zone": name or None, "candidates": [...], "boundary": bool, "narrowed_by_country": bool}."""
        header, body, offsets = self._load()
        step, rows, cols = header["step"], header["rows"], header["cols"]
        r = min(rows - 1, max(0, int((90 - lat) / step)))
        c = min(cols - 1, max(0, int((lon + 180) / step)))
        start, n = offsets[r]
        starts = body[start:start + 2 * n].cast("H")
        values = body[start + 2 * n:start + 4 * n].cast("H")
        value = values[bisect.bisect_right(starts, c) - 1]
        if value < SET_BASE:
            return {"zone": header["zones"][value], "candidates": [header["zones"][value]], "boundary": False,
                    "narrowed_by_country": False}
        candidates = list(header["sets"][value - SET_BASE])
        if country:
            fits = [z for z in candidates if country in (header["countries"].get(z) or [])]
            if len(fits) == 1:
                return {"zone": fits[0], "candidates": candidates, "boundary": True, "narrowed_by_country": True}
            if fits:
                candidates = fits
        return {"zone": None, "candidates": candidates, "boundary": True, "narrowed_by_country": False}

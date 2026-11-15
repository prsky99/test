"""Offline coordinate -> country (ISO 3166-1 alpha-2) from a prebuilt grid (PM 11-15 13:58; no dependencies).

Built outside production by scripts/build_country_grid.py from Natural Earth (public domain) and kept at
gateway-data/fallback-agents/country-grid.bin (not in git), in the time-zone grid's file format. A cell near a
border gives the candidate countries; a disputed area never gives one country (its administering country and the
claimants are the candidates, and "disputed" is set).
"""
from __future__ import annotations

from pathlib import Path

try:
    from .tz_grid import SET_BASE, TzGrid
except ImportError:   # loaded as a lone file by the build script's check (no package)
    from tz_grid import SET_BASE, TzGrid


class CountryGrid(TzGrid):
    def __init__(self, path: Path | str):
        super().__init__(path)

    COAST_CELLS = 3   # about 6 km: Natural Earth's coastline is coarse, a harbour or a fjord shore can fall at sea

    def lookup(self, lat: float, lon: float, country: str | None = None) -> dict:
        """{"country": code or None, "candidates": [...], "boundary": bool, "disputed": bool, "sea": bool,
        "near_coast": bool}. A point at sea takes the one country found within COAST_CELLS cells, if only one."""
        found = self._cell(lat, lon)
        found["near_coast"] = False
        if not found["sea"]:
            return found
        step = self.header["step"]
        near = set()
        for ring in range(1, self.COAST_CELLS + 1):
            for dy in range(-ring, ring + 1):
                for dx in range(-ring, ring + 1):
                    if max(abs(dy), abs(dx)) != ring:
                        continue
                    other = self._cell(lat + dy * step, ((lon + dx * step + 180) % 360) - 180)
                    if other["disputed"]:
                        return {**found, "candidates": other["candidates"], "disputed": True, "sea": False}
                    near.update(other["candidates"])
            if near:
                break
        if len(near) == 1:
            return {"country": next(iter(near)), "candidates": sorted(near), "boundary": False, "disputed": False,
                    "sea": False, "near_coast": True}
        if near:
            return {"country": None, "candidates": sorted(near), "boundary": True, "disputed": False, "sea": False,
                    "near_coast": True}
        return found

    def _cell(self, lat: float, lon: float) -> dict:
        header, body, offsets = self._load()
        step, rows, cols = header["step"], header["rows"], header["cols"]
        r = min(rows - 1, max(0, int((90 - lat) / step)))
        c = min(cols - 1, max(0, int((lon + 180) / step)))
        start, n = offsets[r]
        starts = body[start:start + 2 * n].cast("H")
        values = body[start + 2 * n:start + 4 * n].cast("H")
        import bisect
        value = values[bisect.bisect_right(starts, c) - 1]
        if value < SET_BASE:
            code = header["zones"][value]
            return {"country": code or None, "candidates": [code] if code else [], "boundary": False,
                    "disputed": False, "sea": not code}
        k = value - SET_BASE
        candidates, disputed = list(header["sets"][k]), k in set(header.get("disputed") or [])
        if len(candidates) == 1 and not disputed:   # a coast cell: one country and the sea
            return {"country": candidates[0], "candidates": candidates, "boundary": False, "disputed": False,
                    "sea": False}
        return {"country": None, "candidates": candidates, "boundary": True, "disputed": disputed, "sea": False}

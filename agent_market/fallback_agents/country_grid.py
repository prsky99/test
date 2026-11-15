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

    def lookup(self, lat: float, lon: float, country: str | None = None) -> dict:
        """{"country": code or None, "candidates": [...], "boundary": bool, "disputed": bool, "sea": bool}."""
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
        return {"country": None, "candidates": list(header["sets"][k]), "boundary": True,
                "disputed": k in set(header.get("disputed") or []), "sea": False}

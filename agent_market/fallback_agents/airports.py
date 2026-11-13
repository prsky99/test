"""Local airport index from OurAirports (public domain), refreshed once a day.

    python -m agent_market.fallback_agents.airports --sync     # one CSV download (~13 MB), written atomically

Only airports with an IATA or ICAO code are kept (closed ones are dropped). Request-time lookups read the local
index only; without it the airport agent fails as source_unavailable, never guessing.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import threading
import time
from pathlib import Path

from .limits import limiters as make_limiters
from .net import get

CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
FIELDS = ("ident", "type", "name", "latitude_deg", "longitude_deg", "elevation_ft", "iso_country", "iso_region",
          "municipality", "scheduled_service", "icao_code", "iata_code")


def default_path() -> Path:
    return Path(os.environ.get("FALLBACK_AGENTS_DATA", "gateway-data/fallback-agents")) / "airports.json"


def build_index(text: str) -> dict:
    rows = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("type") == "closed":
            continue
        iata, icao = (row.get("iata_code") or "").strip().upper(), (row.get("icao_code") or row.get("gps_code") or "").strip().upper()
        if not (iata or icao):
            continue
        rec = {k: (row.get(k) or "").strip() for k in FIELDS}
        rec["iata_code"], rec["icao_code"] = iata, icao
        if iata:
            rows.setdefault(iata, rec)
        if icao:
            rows.setdefault(icao, rec)
    if len(rows) < 5000:
        raise ValueError("airport list too small")
    return rows


def sync(path: Path | None = None, *, http=None, limiters=None, now=time.time) -> dict:
    path = Path(path or default_path())
    response = get(CSV_URL, limiters=limiters or make_limiters(), http=http, seconds=120, limit=40 * 1024 * 1024,
                   accept="text/csv, text/plain, */*")
    index = build_index(response.content.decode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched_at": now(), "source_last_modified": response.headers.get("last-modified", ""),
                               "airports": index}, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    return {"codes": len(index), "path": str(path)}


class AirportIndex:
    """The local index, reloaded when the file changes."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or default_path())
        self.lock = threading.Lock()
        self.loaded = (None, None)  # (mtime, data)

    def data(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        with self.lock:
            if self.loaded[0] != mtime:
                self.loaded = (mtime, json.loads(self.path.read_text(encoding="utf-8")))
            return self.loaded[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the local OurAirports index for the airport fallback.")
    parser.add_argument("--sync", action="store_true", required=True)
    parser.add_argument("--path", type=Path, default=None)
    args = parser.parse_args(argv)
    print(json.dumps(sync(args.path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

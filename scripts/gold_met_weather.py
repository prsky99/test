"""Answer set for the met-weather substitute gate (PM 11-16: 30 US points checked against the US National Weather
Service; run it right before the gate, a forecast changes every hour).

    .venv/bin/python -m scripts.gold_met_weather --split substitute-us-r1

For each of 30 fixed US city points the NWS API (api.weather.gov, US Government work, public domain; User-Agent with
contact required) is read twice: /points/{lat},{lon} for the hourly forecast address (saved the day before with
--grids-only into nws-grids.json; weather.gov has a 60-call day total), then that hourly forecast. The
next 12 hours are frozen as truth (start time with offset, temperature in Celsius) in
gateway-data/necklaces/gold/met-weather/<split>.jsonl. The judge compares met-weather's temperature with the NWS
hour that contains met-weather's time, within 3 °C (the role tasks' tolerance). This is an independent source:
met-weather reads MET Norway, not NWS. Every call is reserved in the shared ledger as 'gate'. Accuracy measured on US
locations only (PM): other regions are checked for shape and freshness by the gate's quality checks.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SLUG = "met-weather"
UA = {"User-Agent": "AgentValCon-gold/1.0 (+https://agentconcierge.biz; contact@agentconcierge.biz)",
      "Accept": "application/geo+json"}
# 30 US places spread over the regions NWS forecasts (coordinates of city centres, 4 decimals)
POINTS = [
    ("New York, NY", 40.7128, -74.0060), ("Los Angeles, CA", 34.0522, -118.2437), ("Chicago, IL", 41.8781, -87.6298),
    ("Houston, TX", 29.7604, -95.3698), ("Phoenix, AZ", 33.4484, -112.0740), ("Philadelphia, PA", 39.9526, -75.1652),
    ("San Antonio, TX", 29.4241, -98.4936), ("San Diego, CA", 32.7157, -117.1611), ("Dallas, TX", 32.7767, -96.7970),
    ("Denver, CO", 39.7392, -104.9903), ("Seattle, WA", 47.6062, -122.3321), ("Boston, MA", 42.3601, -71.0589),
    ("Miami, FL", 25.7617, -80.1918), ("Atlanta, GA", 33.7490, -84.3880), ("Minneapolis, MN", 44.9778, -93.2650),
    ("Detroit, MI", 42.3314, -83.0458), ("Salt Lake City, UT", 40.7608, -111.8910), ("Portland, OR", 45.5152, -122.6784),
    ("Las Vegas, NV", 36.1699, -115.1398), ("Nashville, TN", 36.1627, -86.7816), ("New Orleans, LA", 29.9511, -90.0715),
    ("Kansas City, MO", 39.0997, -94.5786), ("Albuquerque, NM", 35.0844, -106.6504), ("Boise, ID", 43.6150, -116.2023),
    ("Anchorage, AK", 61.2181, -149.9003), ("Honolulu, HI", 21.3069, -157.8583), ("Billings, MT", 45.7833, -108.5007),
    ("Charlotte, NC", 35.2271, -80.8431), ("Pittsburgh, PA", 40.4406, -79.9959), ("Fargo, ND", 46.8772, -96.7898),
    ("Omaha, NE", 41.2565, -95.9345), ("Tampa, FL", 27.9506, -82.4572),     # spares: the first 30 that answer are kept
]


def hours(forecast: dict, keep: int = 12) -> list[dict]:
    out = []
    for p in (forecast.get("properties") or {}).get("periods") or []:
        t, unit = p.get("temperature"), p.get("temperatureUnit")
        if not isinstance(t, (int, float)) or unit not in ("F", "C"):
            continue
        c = (t - 32) * 5 / 9 if unit == "F" else float(t)
        out.append({"start": p.get("startTime"), "end": p.get("endTime"), "temp_c": round(c, 2)})
        if len(out) >= keep:
            break
    return out


def grid_urls(get, points=POINTS) -> dict:
    """{name: hourly forecast URL} from /points (the grid of a point does not change from day to day). Built the day
    before (ops 11-16: weather.gov has a 60-call day total, so /points and the forecasts go on two days)."""
    out = {}
    for name, lat, lon in points:
        meta = get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
        url = (meta.get("properties") or {}).get("forecastHourly")
        if isinstance(url, str) and url.startswith("https://api.weather.gov/"):
            out[name] = url
    return out


def build(get, points=POINTS, grids=None):
    grids = grids if grids is not None else grid_urls(get, points)
    cases = []
    for name, lat, lon in points:
        url = grids.get(name)
        if not url:
            continue
        series = hours(get(url))
        if series:
            cases.append({"case_id": f"wx:{name}", "input": {"city": name, "latitude": lat, "longitude": lon},
                          "stratum": "us", "task_type": "substitute",
                          "truth": {"nws_hourly": series, "tolerance_c": 3.0}})
    return cases


def main(argv=None) -> int:
    from agent_market.concierge.http_security import validate_public_url
    from agent_market.provider_budget import reserve
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--split", default="substitute-us-r1")
    p.add_argument("--grids-only", action="store_true", help="read /points only and save the forecast addresses")
    ns = p.parse_args(argv)
    out = ROOT / "gateway-data/necklaces/gold" / SLUG / f"{ns.split}.jsonl"
    grid_file = out.with_name("nws-grids.json")
    if out.exists():
        print(f"{out} exists; a split is never rewritten"); return 2
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = httpx.Client(headers=UA, timeout=15, follow_redirects=False)

    def get(url):
        ok, why = reserve(url, "gate")
        if not ok:
            raise SystemExit(f"ledger refused: {why}")
        validate_public_url(url)
        r = client.get(url)
        r.raise_for_status()
        time.sleep(1.0)
        return r.json()
    if ns.grids_only:
        grids = grid_urls(get)
        grid_file.parent.mkdir(parents=True, exist_ok=True)
        grid_file.write_text(json.dumps({"fetched_at": fetched, "grids": grids}, indent=1))
        print(f"saved {len(grids)} forecast addresses to {grid_file}")
        return 0 if len(grids) >= 30 else 1
    grids = json.loads(grid_file.read_text())["grids"] if grid_file.exists() else None
    cases = build(get, grids=grids)[:30]
    if len(cases) < 30:
        print(f"only {len(cases)} cases; not written"); return 1
    src = [{"name": "US National Weather Service API (public domain)", "url": "https://api.weather.gov/",
            "fetched_at": fetched}]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for c in cases:
            fh.write(json.dumps({**c, "truth_sources": src}, ensure_ascii=False) + "\n")
    print(f"wrote {len(cases)} cases to {out} at {fetched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

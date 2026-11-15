"""Latest SEC periodic filing per company, the filings part of the company-due-diligence answer (PM 11-15 decision 2).

The task passes only when the necklace combines three things: the right SEC CIK, the company's latest periodic filing
and a description of that company. This module builds the filings truth from SEC EDGAR's public quarterly form indexes
(two files: this quarter and the last), so no per-company call is made:

- truth per case: the latest 10-K, 10-Q, 20-F or 40-F (amendments left out) with its date and accession number
- an answer passes with that filing or any later periodic filing of the same company (newer filings are allowed)
- the truth is valid for VALID_DAYS after it was built; after that the case is not graded ("truth_expired") until the
  file is rebuilt (precision review R24)
- a company without a periodic filing in the two quarters has no filings truth and is out of this version's task

The truth lives in gold/company-due-diligence/filings-truth.json, apart from the split files, so their sha256 in the
manifest stays as it was. Each index download goes through the shared provider ledger as reference_checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .gold import USER_AGENT, _now
from .judge import DEFAULT_ROOT

SLUG = "company-due-diligence"
PERIODIC = ("10-K", "10-Q", "20-F", "40-F")
VALID_DAYS = 100
SYSTEM = "reference_checks"
INDEX = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{q}/form.idx"
LINE = re.compile(r"^(?P<form>\S+(?: \S+)?)\s{2,}(?P<name>.+?)\s{2,}(?P<cik>\d{1,10})\s{2,}(?P<date>\d{4}-\d{2}-\d{2})\s{2,}"
                  r"(?P<file>edgar/data/\S+)$")


def quarters(today: date) -> list[tuple[int, int]]:
    q = (today.month - 1) // 3 + 1
    prev = (today.year, q - 1) if q > 1 else (today.year - 1, 4)
    return [prev, (today.year, q)]


def parse_index(text: str, ciks: set[str]) -> dict[str, dict]:
    """Latest periodic filing per wanted CIK in one form.idx."""
    out: dict[str, dict] = {}
    for line in text.splitlines():
        match = LINE.match(line.rstrip())
        if not match or match["form"] not in PERIODIC:
            continue
        cik = str(int(match["cik"]))
        if cik not in ciks:
            continue
        accession = Path(match["file"]).stem
        current = out.get(cik)
        if current is None or (match["date"], accession) > (current["date"], current["accession"]):
            out[cik] = {"form": match["form"], "date": match["date"], "accession": accession}
    return out


def fetch_text(url: str, reserve=None, note=None, opener=None) -> str:
    import urllib.request
    if reserve is None or note is None:
        from ..provider_budget import note as _note, reserve as _reserve
        reserve, note = reserve or _reserve, note or _note
    ok, why = reserve(url, SYSTEM)
    if not ok:
        raise RuntimeError(f"provider budget: {why}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=120) as response:
            note(url, SYSTEM, getattr(response, "status", 200), evidence="provider_http")
            return response.read().decode("latin-1")
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code:
            note(url, SYSTEM, code, evidence="provider_http")
        raise


def us_cases(root: Path) -> list[dict]:
    folder = Path(root) / "gold" / SLUG
    rows = []
    for path in sorted(folder.glob("*.jsonl")):
        rows += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("input", {}).get("country") == "US" and r.get("truth", {}).get("cik")]


def build(root: Path = DEFAULT_ROOT, get=fetch_text, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    cases = us_cases(root)
    ciks = {str(int(c["truth"]["cik"])) for c in cases}
    latest: dict[str, dict] = {}
    for year, q in quarters(today):
        for cik, filing in parse_index(get(INDEX.format(year=year, q=q)), ciks).items():
            if cik not in latest or (filing["date"], filing["accession"]) > (latest[cik]["date"], latest[cik]["accession"]):
                latest[cik] = filing
    as_of = _now()
    valid_until = (today + timedelta(days=VALID_DAYS)).isoformat()
    truth = {c["case_id"]: dict(latest[str(int(c["truth"]["cik"]))], as_of=as_of, valid_until=valid_until,
                                source="SEC EDGAR full-index form.idx")
             for c in cases if str(int(c["truth"]["cik"])) in latest}
    text = json.dumps({"built_at": as_of, "valid_days": VALID_DAYS, "quarters": quarters(today), "cases": truth},
                      ensure_ascii=False, indent=1, sort_keys=True)
    path = Path(root) / "gold" / SLUG / "filings-truth.json"
    path.write_text(text + "\n", encoding="utf-8")
    return {"us_cases": len(cases), "with_filing": len(truth), "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "file": str(path)}


def attach(root: Path, cases: list[dict]) -> list[dict]:
    """Put each case's filings truth on it (load time only; split files stay unchanged)."""
    path = Path(root) / "gold" / SLUG / "filings-truth.json"
    try:
        truth = json.loads(path.read_text(encoding="utf-8"))["cases"]
    except (OSError, ValueError, KeyError):
        return cases
    for case in cases:
        if case.get("case_id") in truth:
            case.setdefault("truth", {})["filings"] = truth[case["case_id"]]
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

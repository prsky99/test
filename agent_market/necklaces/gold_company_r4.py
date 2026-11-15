"""company-due-diligence holdout-r4: 60 unseen held-out cases for the necklace's launch gate (ops 11-16 07:0x, PM 07:00:
the company gate runs today; every earlier company set was seen by a substitute gate).

Selection: SEC's own list of companies with a ticker (www.sec.gov/files/company_tickers.json), in a fixed pseudo-random
order (sha256 of "r4:" + CIK, so no hand-picking), skipping every CIK of an earlier company case, kept when the
company's latest periodic filing is a 10-K or 10-Q. That last rule follows the necklace's stated scope (companies that
file with the US SEC as US filers: scope country US); foreign private issuers (20-F, 40-F) are out of that scope.
Nothing else is filtered.

Truth (fixed at build time): CIK, ticker and EDGAR name from the ticker list; the latest 10-K or 10-Q (form, date,
accession) from data.sec.gov/submissions. The truth source is SEC, the same source our own substitutes sec-edgar and
sec-filings read: there is no other authoritative source for a CIK or a filing. The manifest says so, so a case a
member answers from SEC is not mistaken for an independent check. Calls are reference_checks through the ledger
(sec.gov's day total 600; SEC fair access: declared User-Agent with the contact mail, at most 4 a second).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

from .gold import _now
from .gold_filings import fetch_text
from .gold_sec import SUBMISSIONS, TICKERS, earlier_ids
from .judge import DEFAULT_ROOT

SLUG = "company-due-diligence"
SPLIT = "holdout-r4"
CASES = 60
VALID_DAYS = 60
PERIODIC_US = ("10-K", "10-Q")
LEGAL = {"CORP": "Corp", "INC": "Inc", "CO": "Co", "LTD": "Ltd", "PLC": "plc", "LP": "LP", "LLC": "LLC", "NV": "NV",
         "SA": "SA", "AG": "AG", "HOLDINGS": "Holdings", "GROUP": "Group", "TRUST": "Trust", "BANCORP": "Bancorp"}


def typed(title: str) -> str:
    """The EDGAR name as a person types it: 'RAND CAPITAL CORP' -> 'Rand Capital Corp' (slashes and state tags out)."""
    title = re.sub(r"\s*/[A-Z]{2}/?\s*$", "", title).replace("/", " ")
    words = []
    for w in title.split():
        bare = w.strip(".,").upper()
        words.append(LEGAL.get(bare, w if any(c.isdigit() for c in w) else w.capitalize()))
    return " ".join(words).replace(" ,", ",")


def _latest_us_periodic(submissions: dict) -> dict | None:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    for form, filed, accession in zip(recent.get("form") or [], recent.get("filingDate") or [],
                                      recent.get("accessionNumber") or []):
        if form in ("10-K", "10-Q", "20-F", "40-F"):
            return {"form": form, "date": filed, "accession": accession} if form in PERIODIC_US else None
    return None


def build_cases(root: Path, get=fetch_text, today: date | None = None, sleep=time.sleep, limit_calls: int = 95):
    today = today or date.today()
    valid_until = (today + timedelta(days=VALID_DAYS)).isoformat()
    seen_ids, seen_ciks = earlier_ids(root)
    rows = list(json.loads(get(TICKERS)).values())
    order = sorted({int(r["cik_str"]): r for r in rows}.values(),
                   key=lambda r: hashlib.sha256(f"r4:{int(r['cik_str'])}".encode()).hexdigest())
    cases, skipped, calls = [], {"seen": 0, "not_us_periodic": 0}, 1
    for row in order:
        if len(cases) >= CASES or calls >= limit_calls:
            break
        cik = int(row["cik_str"])
        if str(cik) in seen_ciks or f"US:CIK{cik}" in seen_ids:
            skipped["seen"] += 1
            continue
        sleep(0.3)
        calls += 1
        sub = json.loads(get(SUBMISSIONS.format(cik=cik)))
        latest = _latest_us_periodic(sub)
        if not latest:
            skipped["not_us_periodic"] += 1
            continue
        title = sub.get("name") or row.get("title") or ""
        cases.append({"case_id": f"US4:CIK{cik}", "task_type": "same_role", "stratum": "us_filer",
                      "input": {"name": typed(title), "country": "US"},
                      "truth": {"cik": str(cik), "ticker": row.get("ticker"), "sec_title": title, "lei": None,
                                "sec_registered": True,
                                "filings": dict(latest, as_of=_now(), valid_until=valid_until,
                                                source="SEC EDGAR submissions")},
                      "truth_sources": [{"name": "SEC company_tickers.json", "url": TICKERS, "fetched_at": _now()},
                                        {"name": "SEC EDGAR submissions", "url": SUBMISSIONS.format(cik=cik),
                                         "fetched_at": _now()}]})
    return cases, dict(skipped, calls=calls)


def build(root: Path = DEFAULT_ROOT, get=fetch_text, today: date | None = None, sleep=time.sleep) -> dict:
    cases, info = build_cases(root, get, today, sleep)
    folder = Path(root) / "gold" / SLUG
    if len(cases) < CASES:
        return {"cases": len(cases), "written": False, **info}
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (folder / f"{SPLIT}.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("files", {})[SPLIT] = {
        "cases": len(cases), "strata": {"us_filer": len(cases)}, "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "for": "company-due-diligence launch gate, rounds 1 and 2 (30 + 30, ops 11-16)",
        "selection": "SEC ticker list in sha256('r4:'+CIK) order, unseen CIKs, latest periodic 10-K or 10-Q "
                     "(the necklace's scope: US SEC filers); nothing else filtered",
        "truth_sources": ["SEC company_tickers.json (CIK, ticker, EDGAR name)",
                          "SEC EDGAR submissions (latest 10-K or 10-Q)"],
        "same_source_note": "the truth source is SEC, which our own substitutes sec-edgar and sec-filings also read; "
                            "no independent source exists for a CIK or a filing"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"cases": len(cases), "written": True, **info}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""company-due-diligence holdout-r3-sec: fresh SEC cases for the sec-filings substitute re-verdict (PM 11-15 14:34).

Why: sec-filings failed its gate 28 of 30 on legal-name suffixes (CO), and after the cases already seen only 12
with a CIK were left. This split mixes on purpose:
- US filers typed with their legal suffix (Co, Corp, Inc, Ltd, plc, ...) as people write them;
- foreign issuers that file 20-F or 40-F (S.A., AG, N.V., plc, Ltd, Corp);
- companies with no SEC EDGAR registration (private, non-US), whose right answer is "no registration".

Truth is SEC's own data, fixed at build time: the CIK and ticker from www.sec.gov/files/company_tickers.json, the
filer's EDGAR name, entity type and latest periodic filing (10-K, 20-F or 40-F: form, date, accession) from
data.sec.gov/submissions. A company counts as unregistered only when neither the ticker file nor an EDGAR company
search (browse-edgar, exact name) has it. Every call goes through the shared ledger as reference_checks (SEC fair
access: declared User-Agent with the contact mail, well under 10 requests a second). No case id or CIK is shared
with an earlier company case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from .gold import _now
from .gold_filings import fetch_text
from .judge import DEFAULT_ROOT

SLUG = "company-due-diligence"
SPLIT = "holdout-r3-sec"
VALID_DAYS = 100
TICKERS = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEARCH = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={name}&type=&dateb=&owner=include&count=10&output=atom"
PERIODIC = ("10-K", "20-F", "40-F")

# (name as a person types it, ticker to find the CIK by, country of the issuer, stratum)
LISTED = [
    ("Coca-Cola Co", "KO", "US", "suffix"), ("Ford Motor Co", "F", "US", "suffix"),
    ("Procter & Gamble Co", "PG", "US", "suffix"), ("Walt Disney Co", "DIS", "US", "suffix"),
    ("Boeing Co", "BA", "US", "suffix"), ("Hershey Co", "HSY", "US", "suffix"), ("Clorox Co", "CLX", "US", "suffix"),
    ("Southern Co", "SO", "US", "suffix"), ("Kroger Co", "KR", "US", "suffix"), ("Home Depot Inc", "HD", "US", "suffix"),
    ("Exxon Mobil Corp", "XOM", "US", "suffix"), ("Gap Inc", "GAP", "US", "suffix"),
    ("Toyota Motor Corp", "TM", "JP", "foreign"), ("Sony Group Corp", "SONY", "JP", "foreign"),
    ("Shell plc", "SHEL", "GB", "foreign"), ("BP p.l.c.", "BP", "GB", "foreign"), ("Unilever PLC", "UL", "GB", "foreign"),
    ("Novartis AG", "NVS", "CH", "foreign"), ("UBS Group AG", "UBS", "CH", "foreign"),
    ("ASML Holding N.V.", "ASML", "NL", "foreign"), ("Banco Santander, S.A.", "SAN", "ES", "foreign"),
    ("Telefonica, S.A.", "TEF", "ES", "foreign"), ("Canadian National Railway Co", "CNI", "CA", "foreign"),
    ("Royal Bank of Canada", "RY", "CA", "foreign"), ("Infosys Ltd", "INFY", "IN", "foreign"),
    ("Taiwan Semiconductor Manufacturing Co Ltd", "TSM", "TW", "foreign"),
]
UNREGISTERED = [("Robert Bosch GmbH", "DE"), ("Aldi Sued", "DE"), ("Lidl Stiftung & Co. KG", "DE"),
                ("Bosch Siemens Hausgeraete GmbH", "DE"), ("Ferrero International S.A.", "LU")]


def _json(get, url):
    return json.loads(get(url))


def _latest_periodic(submissions: dict) -> dict | None:
    recent = ((submissions.get("filings") or {}).get("recent") or {})
    for form, filed, accession in zip(recent.get("form") or [], recent.get("filingDate") or [],
                                      recent.get("accessionNumber") or []):
        if form in PERIODIC:
            return {"form": form, "date": filed, "accession": accession}
    return None


def earlier_ids(root: Path) -> tuple[set, set]:
    ids, ciks = set(), set()
    for path in (Path(root) / "gold" / SLUG).glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                case = json.loads(line)
                ids.add(case.get("case_id"))
                if (case.get("truth") or {}).get("cik"):
                    ciks.add(str(int(case["truth"]["cik"])))
    return ids, ciks


def build_cases(root: Path, get=fetch_text, today: date | None = None, sleep=time.sleep) -> tuple[list[dict], dict]:
    today = today or date.today()
    valid_until = (today + timedelta(days=VALID_DAYS)).isoformat()
    seen_ids, seen_ciks = earlier_ids(root)
    tickers = {str(v["ticker"]).upper(): v for v in _json(get, TICKERS).values()}
    by_title = {str(v["title"]).upper() for v in tickers.values()}
    cases, dropped = [], {}
    for typed, ticker, country, stratum in LISTED:
        row = tickers.get(ticker)
        if not row:
            dropped[typed] = "ticker not in SEC company_tickers"
            continue
        cik = int(row["cik_str"])
        if str(cik) in seen_ciks:
            dropped[typed] = "CIK already in an earlier company case"
            continue
        sleep(0.25)
        sub = _json(get, SUBMISSIONS.format(cik=cik))
        latest = _latest_periodic(sub)
        if not latest:
            dropped[typed] = "no 10-K, 20-F or 40-F in recent filings"
            continue
        case_id = f"SEC3:CIK{cik}"
        if case_id in seen_ids:
            continue
        cases.append({"case_id": case_id, "task_type": "same_role", "stratum": stratum,
                      "input": {"name": typed, "country": country},
                      "truth": {"cik": str(cik), "ticker": ticker, "sec_title": sub.get("name"),
                                "entity_type": sub.get("entityType"), "sec_registered": True,
                                "filings": dict(latest, as_of=_now(), valid_until=valid_until,
                                                source="SEC EDGAR submissions")},
                      "truth_sources": [{"name": "SEC company_tickers.json", "url": TICKERS, "fetched_at": _now()},
                                        {"name": "SEC EDGAR submissions", "url": SUBMISSIONS.format(cik=cik),
                                         "fetched_at": _now()}]})
    for typed, country in UNREGISTERED:
        if typed.upper() in by_title:
            dropped[typed] = "in SEC company_tickers"
            continue
        sleep(0.25)
        atom = get(SEARCH.format(name=quote(typed)))
        if re.search(r"<cik>\s*\d+\s*</cik>", atom, re.I) or "<entry>" in atom:
            dropped[typed] = "EDGAR company search found a filer"
            continue
        cases.append({"case_id": "SEC3:none:" + re.sub(r"[^A-Za-z0-9]+", "-", typed).strip("-"),
                      "task_type": "same_role", "stratum": "unregistered", "input": {"name": typed, "country": country},
                      "truth": {"cik": None, "sec_registered": False},
                      "truth_sources": [{"name": "SEC company_tickers.json (absent)", "url": TICKERS, "fetched_at": _now()},
                                        {"name": "EDGAR company search (no filer)", "url": SEARCH.format(name=quote(typed)),
                                         "fetched_at": _now()}]})
    return cases, dropped


def build(root: Path = DEFAULT_ROOT, get=fetch_text, today: date | None = None) -> dict:
    cases, dropped = build_cases(root, get, today)
    folder = Path(root) / "gold" / SLUG
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (folder / f"{SPLIT}.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    strata: dict[str, int] = {}
    for c in cases:
        strata[c["stratum"]] = strata.get(c["stratum"], 0) + 1
    manifest.setdefault("files", {})[SPLIT] = {"cases": len(cases), "strata": strata,
                                               "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                               "for": "sec-filings substitute re-verdict (PM 11-15 14:34)"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"cases": len(cases), "with_cik": sum(1 for c in cases if c["truth"]["cik"]), "strata": strata,
            "dropped": dropped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

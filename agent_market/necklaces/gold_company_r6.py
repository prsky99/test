"""company holdout-r6: 30 unseen companies for the sec-company-profile substitute gate (ops 11-16, PM decision).

sec-company-profile moved to its own contract company.profile.v1 (agent team 53a620cc) and has to be judged again on
a set it has not seen: holdout-r4-g2 was its first gate (08:11) and holdout-r5 is the necklace's launch gate. Selection
is holdout-r4's rule with its own seed (SEC's ticker list in sha256("r6:" + CIK) order, every CIK of an earlier company
case skipped, latest periodic filing a 10-K or 10-Q); nothing else is filtered. Truth: CIK, ticker and the EDGAR name
from SEC submissions (the name the profile must answer with), plus the latest 10-K or 10-Q as in r4. Calls are
reference_checks through the ledger (sec.gov), about one per case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date
from pathlib import Path

from .gold_company_r4 import build_cases
from .gold_filings import fetch_text
from .judge import DEFAULT_ROOT

SLUG = "company-due-diligence"
SPLIT = "holdout-r6"
CASES = 30


def build(root: Path = DEFAULT_ROOT, get=fetch_text, today: date | None = None, sleep=time.sleep) -> dict:
    cases, info = build_cases(root, get, today, sleep, limit_calls=60, seed="r6", prefix="US6", count=CASES)
    if len(cases) < CASES:
        return {"cases": len(cases), "written": False, **info}
    folder = Path(root) / "gold" / SLUG
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (folder / f"{SPLIT}.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("files", {})[SPLIT] = {
        "cases": len(cases), "strata": {"us_filer": len(cases)}, "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "for": "sec-company-profile substitute gate on company.profile.v1 (ops 11-16; not for the necklace gate)",
        "selection": "SEC ticker list in sha256('r6:'+CIK) order, unseen CIKs, latest periodic 10-K or 10-Q; "
                     "nothing else filtered",
        "truth_sources": ["SEC company_tickers.json (CIK, ticker)", "SEC EDGAR submissions (EDGAR name, latest 10-K or 10-Q)"],
        "same_source_kind": "official",
        "same_source_rule": "official register (PM 11-16 07:05): the answer key is SEC, which sec-company-profile reads "
                            "too; the builder fetched it from SEC itself"}
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

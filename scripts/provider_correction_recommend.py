"""Agent team's recommendation on a provider correction request (PM decision 11-15 11:2x).

    .venv/bin/python -m scripts.prod_ro_sql -c "SELECT id, resource_id, field, proposed, evidence_url, status, created
        FROM provider_claims.provider_correction_requests WHERE status IN ('open','held') ORDER BY created"
    .venv/bin/python -m scripts.provider_correction_recommend cr_xxxx declined "The proposed name is another product's."

Within 48 hours of each request. This only appends a line to gateway-data/provider-claims/recommendations.jsonl
(outside git and outside the database). The admin review panel shows it next to the request; a staff member records
the decision there. Nothing here or in any job writes the decision to the database.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from agent_market.provider_self_claims import RECOMMENDATIONS


def append(request_id: str, recommendation: str, reason: str, by: str = "agent team", path: Path = RECOMMENDATIONS,
           now=time.time) -> dict:
    if not re.fullmatch(r"cr_[A-Za-z0-9_-]{8,40}", request_id or ""):
        raise ValueError("request id looks like cr_…")
    if recommendation not in ("applied", "declined", "held"):
        raise ValueError("recommendation is applied, declined or held")
    reason = " ".join(str(reason or "").split())
    if not 1 <= len(reason) <= 300:
        raise ValueError("one reason line, at most 300 characters")
    row = {"request_id": request_id, "recommendation": recommendation, "reason": reason, "by": by[:40],
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now()))}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("request_id")
    parser.add_argument("recommendation", choices=("applied", "declined", "held"))
    parser.add_argument("reason")
    args = parser.parse_args(argv)
    print(json.dumps(append(args.request_id, args.recommendation, args.reason), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

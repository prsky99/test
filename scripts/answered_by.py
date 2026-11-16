"""Who answered each slot in one necklace gate round (PM 11-16: kept with the verdict, so a recount gives the same
numbers; r12 attaches it to scripts.gate_round).

    .venv/bin/python -m scripts.answered_by <slug> <split> <day YYYYMMDD> [--data gateway-data/necklaces]

Reads retest/<day>.jsonl for the round's case ids (set = split or split-rerun, type case or excluded) and
results/<slug>/selftest-<day>.jsonl for each case's slots (the answering member's kind and rank) and attempts
(rank -> the member's resource id, or our tool name). The last detail line of a case counts (a rerun replaces the
first measurement). A case excluded before any slot ran (ledger, relay) has no slots and is counted apart.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _lines(path: Path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def count(data: Path, slug: str, split: str, day: str) -> dict:
    root = Path(data)
    ids = {l["case_id"] for l in _lines(root / "retest" / f"{day}.jsonl")
           if l.get("slug") == slug and l.get("set") in (split, split + "-rerun") and l.get("type") in ("case", "excluded")}
    last = {}
    for d in _lines(root / "results" / slug / f"selftest-{day}.jsonl"):
        if d.get("case_id") in ids:
            last[d["case_id"]] = d
    slots: dict[str, dict] = {}
    for case_id, d in sorted(last.items()):
        for slot, s in (d.get("slots") or {}).items():
            row = slots.setdefault(slot, {"external": 0, "agentcon": 0, "none": 0, "by_member": Counter()})
            if s.get("status") != "answered" or not s.get("kind"):
                row["none"] += 1
                continue
            row[s["kind"]] += 1
            hit = next((x for x in (d.get("attempts") or {}).get(slot, [])
                        if x.get("rank") == s.get("rank") and x.get("ok")), None) or {}
            row["by_member"][str(hit.get("resource_id") or hit.get("tool") or "?")] += 1
    return {"slug": slug, "split": split, "day": day, "cases_in_round": len(ids), "cases": len(last),
            "cases_without_slots": sum(1 for d in last.values() if not d.get("slots")),
            "slots": {k: dict(v, by_member=dict(sorted(v["by_member"].items()))) for k, v in sorted(slots.items())}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slug")
    parser.add_argument("split")
    parser.add_argument("day")
    parser.add_argument("--data", type=Path, default=Path("gateway-data/necklaces"))
    args = parser.parse_args(argv)
    print(json.dumps(count(args.data, args.slug, args.split, args.day), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

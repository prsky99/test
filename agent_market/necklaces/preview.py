"""Preview publication of a necklace whose gate rounds have not passed yet (user decision 11-18 via PM 11:56).

"website-trust 공개 해줘": if the 17:10 and 21:10 rounds do not pass, the necklace still goes public tonight, marked
"Preview — test runs in progress" with the pass count we measured (e.g. 52 of 60). A preview never says it passed the
gate, never shows measured value against doing the task yourself, and keeps every failure guard of a live necklace
(watch holds, substitutes, the retest holds); runs are capped lower than a live necklace (limits.PREVIEW_PER_DAY).

The record lives in gateway-data/necklaces/preview.json, one line per round, written by this module only:
    {"rounds": [{"slug", "version", "definition_digest", "split", "passed", "total", "at", "by"}]}
The definition's status "preview" plus a record for the same version and digest makes the judge write a public entry
with status "preview"; without such a record the entry shows the note only, no count (PM 17:2x). The rounds are the gate rounds
of that definition as measured (scripts/gate_round.py status), never picked: every round of the version is counted.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from . import model

FILE = "preview.json"
NOTE = "Preview — test runs in progress"


def load(root: Path) -> list[dict]:
    try:
        raw = json.loads((Path(root) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = raw.get("rounds") if isinstance(raw, dict) else None
    return [r for r in rows or [] if isinstance(r, dict)]


def _count(value) -> bool:
    return type(value) is int and value >= 0


def measured(defn: dict, rows: list[dict]) -> dict | None:
    """{"note", "tests": {"passed", "total"}, "rounds": [...]} over every recorded round of this version and digest;
    None when there is none or a row does not add up (nothing is shown that we did not measure)."""
    digest = model.digest(defn)
    mine = [r for r in rows if r.get("slug") == defn["slug"] and r.get("version") == defn["version"]
            and r.get("definition_digest") == digest]
    if not mine or not all(_count(r.get("passed")) and _count(r.get("total")) and 0 < r["total"]
                            and r["passed"] <= r["total"] for r in mine):
        return None
    rounds = [{"split": r.get("split"), "passed": r["passed"], "total": r["total"], "at": r.get("at")}
              for r in sorted(mine, key=lambda r: r.get("at") or "")]
    return {"note": NOTE, "gate_passed": False,
            "tests": {"passed": sum(r["passed"] for r in rounds), "total": sum(r["total"] for r in rounds)},
            "rounds": rounds}


def unmeasured() -> dict:
    """The preview field when no round of this version and digest was measured (PM 17:2x, 11-18: the v2 rounds did
    not run). Only the note: no tests and no rounds keys, so nothing shows a count, and never a zero."""
    return {"note": NOTE, "gate_passed": False}


def record(root: Path, defn: dict, split: str, passed: int, total: int, by: str, now: float | None = None) -> dict:
    """Add one round (replacing an earlier line of the same split for this version and digest); atomic write."""
    if not (_count(passed) and _count(total) and 0 < total and passed <= total):
        raise ValueError("passed and total must be counts with 0 <= passed <= total and total > 0")
    digest = model.digest(defn)
    rows = [r for r in load(root) if not (r.get("slug") == defn["slug"] and r.get("split") == split
                                          and r.get("version") == defn["version"]
                                          and r.get("definition_digest") == digest)]
    line = {"slug": defn["slug"], "version": defn["version"], "definition_digest": digest, "split": split,
            "passed": passed, "total": total, "by": by,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if now is None else now))}
    rows.append(line)
    path = Path(root) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".preview.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"rounds": rows}, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record one measured gate round for a preview necklace.")
    parser.add_argument("slug")
    parser.add_argument("--split", required=True)
    parser.add_argument("--passed", type=int, required=True)
    parser.add_argument("--total", type=int, required=True)
    parser.add_argument("--by", required=True)
    parser.add_argument("--root", type=Path, default=Path("gateway-data/necklaces"))
    parser.add_argument("--definitions", type=Path, default=model.DEFINITIONS)
    args = parser.parse_args(argv)
    found = [d for d in model.load_valid(args.definitions) if d["slug"] == args.slug]
    if not found:
        print(json.dumps({"recorded": False, "error": "unknown_slug"}))
        return 2
    line = record(args.root, found[0], args.split, args.passed, args.total, args.by)
    print(json.dumps({"recorded": True, **line}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

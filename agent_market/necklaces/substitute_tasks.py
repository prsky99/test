"""Open a substitute task when a fallback really ran (user decision 11-18 via PM 19:2x; docs/PRODUCTION_SYSTEM.md 7-1).

A necklace goes public with pearls and outside fallbacks. When a public run needed a step's fallback (stage 2: the
representative member failed and an outside fallback answered), the role should get our own substitute, so a task
for the agent team is opened: one line in <root>/substitute-tasks.jsonl {role, slug, slot, first_seen, runs}, once
per role. A role that already has a substitute that passed its substitute gate gets no task. Only external public
runs count (our own tests and QA runs do not).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

FALLBACK_STAGE = 2
DAYS = 2
FILE = "substitute-tasks.jsonl"


def open_tasks(root: Path, definitions: list[dict], now: float | None = None, days: int = DAYS) -> list[dict]:
    """New task lines written this call (none twice for a role)."""
    from .connect_gate import GATE_PASSED
    from .judge import load_substitute_states
    now = time.time() if now is None else now
    root = Path(root)
    roles = {(d["slug"], s["slot"]): s.get("contract") for d in definitions for s in d["slots"]}
    states = load_substitute_states(root / "approvals.json")
    covered = {key.split("|", 1)[1] for key, state in states.items() if state in GATE_PASSED}
    path = root / FILE
    opened = set()
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            opened.add(json.loads(line).get("role"))
        except ValueError:
            continue
    seen: dict[str, dict] = {}
    for d in range(days):
        name = time.strftime("%Y%m%d", time.gmtime(now - d * 86400))
        runs = root / "runs" / f"{name}.jsonl"
        for raw in runs.read_text(encoding="utf-8").splitlines() if runs.exists() else []:
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if event.get("source") != "external":
                continue
            for slot, stage in (event.get("stages") or {}).items():
                role = roles.get((event.get("slug"), slot))
                if stage != FALLBACK_STAGE or not role or role in covered or role in opened:
                    continue
                row = seen.setdefault(role, {"role": role, "slug": event.get("slug"), "slot": slot,
                                             "first_seen": event.get("at"), "runs": 0, "for": "agent team",
                                             "why": "the step's fallback answered a public run; build our substitute"})
                row["runs"] += 1
                if (event.get("at") or "") < (row["first_seen"] or "~"):
                    row["first_seen"] = event.get("at")
    if seen:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in seen.values():
                handle.write(json.dumps(dict(row, opened_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))),
                                        ensure_ascii=False, sort_keys=True) + "\n")
    return list(seen.values())

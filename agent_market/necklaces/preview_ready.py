"""Which definitions can take the connection gate today, and where each stands (user decision 11-18 via PM 19:4x;
docs/PRODUCTION_SYSTEM.md 7-1). A table, no calls; the gate itself is connect_gate.

A definition is ready for the gate when it has three or more different roles (slot contracts) and the gate's static
checks pass (connect_gate.static_checks): every required step has a representative pearl and an outside fallback, or
is an own_fallback step with a substitute that passed its gate (then outside pearls on two or more steps); terms
allowed or silent; the watch fresh with no hold. The table also shows
the latest connection gate line of the version and digest, so "ready", "passed" and "held" read from one place.

    .venv/bin/python -m agent_market.necklaces.preview_ready            # the table
    .venv/bin/python -m agent_market.necklaces.preview_ready --json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import model

MIN_ROLES = 3


def roles(defn: dict) -> list[str]:
    out = []
    for slot in defn["slots"]:
        if slot.get("contract") not in out:
            out.append(slot.get("contract"))
    return out


def check(defn: dict, *, states: dict | None, watch_state: dict | None, watch_problem: str | None,
          connect: dict | None = None, verified: set | None = None) -> dict:
    """{"slug", "status", "ready", "blocked", "roles", "connect"} for one definition."""
    from .connect_gate import static_checks
    from .watch import runtime_definition
    running = runtime_definition(defn, watch_state or {})
    blocked = []
    found = roles(defn)
    if len(found) < MIN_ROLES:
        blocked.append(f"roles {len(found)} < {MIN_ROLES}")
    for c in static_checks(defn, running, states, watch_state, watch_problem, verified):
        if not c["ok"]:
            blocked.append(f"{c['check']}: {c['why']}")
    return {"slug": defn["slug"], "version": defn["version"], "status": defn["status"], "ready": not blocked,
            "blocked": blocked, "roles": found, "connect": connect}


def run(root: Path, definitions_dir: Path = model.DEFINITIONS, now: float | None = None) -> list[dict]:
    from . import connect_gate, judge, retest
    now = time.time() if now is None else now
    _, watch_problem = judge.load_watch_state(root, now)
    watch_state = retest.gate_watch_state(root)
    states = judge.load_substitute_states(Path(root) / "approvals.json")
    verified = judge.verified_pearls()
    out = []
    for defn in model.load_valid(definitions_dir):
        connect = connect_gate.state_of(root, defn, now) if connect_gate.history(root, defn) else None
        out.append(check(defn, states=states, watch_state=watch_state, watch_problem=watch_problem, connect=connect,
                         verified=verified))
    return out


def table(rows: list[dict]) -> str:
    lines = ["| slug | status | roles | ready for the gate | blocked by | connection gate |", "|---|---|---|---|---|---|"]
    for r in rows:
        c = r.get("connect")
        gate = "-" if not c else (f"passed {c['passed_at']}" + (f", held {c['hold']}" if c.get("hold") else "")
                                  if c.get("passed_at") else f"not passed ({c.get('hold')})")
        lines.append(f"| {r['slug']} | {r['status']} | {len(r['roles'])} | {'yes' if r['ready'] else 'no'} | "
                     + ("; ".join(r["blocked"]) or "-") + f" | {gate} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("gateway-data/necklaces"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = run(args.root)
    print(json.dumps(rows, ensure_ascii=False, indent=1) if args.json else table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

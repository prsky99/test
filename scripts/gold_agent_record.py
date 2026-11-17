"""Answer set for the agent-record substitute gate (agent team 11-17, PM: ready for when the catalog index exists).

    .venv/bin/python -m scripts.gold_agent_record --split record-r1

Start condition: the daily catalog index (gateway-data/agent-record/index.sqlite3) exists and is under 48 hours old;
otherwise nothing is built and the exit code is 3, so the gate does not start.

Cases: 25 official MCP Registry servers taken from the catalog in a fixed pseudo-random order (md5 of id and the
split name), by registry name, plus 5 made-up registry names that no catalog row holds (found false). Truth is read
right before the gate from the production database through scripts.prod_ro_sql (SELECT only, one connection, the
read log): found, agent id, grade, and whether the row is under security review (then no grade is expected).
Reachability status is not judged: it changes every hour and the index is a daily copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SLUG = "mcp-server-trust-check"
MAX_INDEX_AGE = 48 * 3600
FIELDS = ("id", "registry_name", "eval_grade", "eval_security", "active")


def select_sql(split: str, n: int) -> str:
    salt = split.replace("'", "")
    return ("SELECT id, details::jsonb->>'registry_name', eval_grade, eval_security, active FROM resources "
            "WHERE source='mcp-registry' AND kind='mcp' AND details::jsonb->>'registry_name' IS NOT NULL "
            f"ORDER BY md5(id::text || '{salt}') LIMIT {int(n)}")


def parse_rows(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != len(FIELDS) or not parts[0].strip().isdigit():
            continue
        rows.append(dict(zip(FIELDS, (p.strip() for p in parts))))
    return rows


def made_up(split: str, n: int = 5) -> list[str]:
    return [f"io.github.agentvalcon-none/{hashlib.sha256(f'{split}:{i}'.encode()).hexdigest()[:12]}" for i in range(n)]


def cases_from(rows: list[dict], fake: list[str]) -> list[dict]:
    out = []
    for r in rows:
        reviewing = r["eval_security"] in ("quarantine", "review")
        truth = {"found": True, "agent_id": int(r["id"]), "reviewing": reviewing,
                 "grade": None if reviewing or r["eval_grade"] not in tuple("ABCDEF") else r["eval_grade"]}
        out.append({"case_id": f"record:{r['registry_name']}", "input": {"name": r["registry_name"]},
                    "task_type": "substitute", "stratum": "listed", "truth": truth})
    for name in fake:
        out.append({"case_id": f"record:{name}", "input": {"name": name}, "task_type": "substitute",
                    "stratum": "absent", "truth": {"found": False}})
    return out


def index_ok(now: float | None = None) -> tuple[bool, str]:
    from agent_market.agent_record_index import Index, path
    built = Index().built_at()
    now = time.time() if now is None else now
    if built is None:
        return False, f"no catalog index at {path()}"
    if now - built > MAX_INDEX_AGE:
        return False, f"catalog index is {int((now - built) / 3600)} hours old"
    return True, "ok"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--split", default="record-r1")
    ns = p.parse_args(argv)
    ok, why = index_ok()
    if not ok:
        print(f"not started: {why}"); return 3
    out = ROOT / "gateway-data/necklaces/gold" / SLUG / f"{ns.split}.jsonl"
    if out.exists():
        print(f"{out} exists; a split is never rewritten"); return 2
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run = subprocess.run([sys.executable, "-m", "scripts.prod_ro_sql", "-c", select_sql(ns.split, 25)],
                         cwd=ROOT, capture_output=True, text=True, timeout=120)
    rows = parse_rows(run.stdout)
    if run.returncode != 0 or len(rows) < 25:
        print(f"only {len(rows)} catalog rows (exit {run.returncode}); not written"); return 1
    cases = cases_from(rows, made_up(ns.split))
    src = [{"name": "AgentValCon catalog (production database, read only through scripts.prod_ro_sql)",
            "fetched_at": fetched}]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for c in cases:
            fh.write(json.dumps({**c, "truth_sources": src}, ensure_ascii=False) + "\n")
    print(f"wrote {len(cases)} cases to {out} at {fetched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

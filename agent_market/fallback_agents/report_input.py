"""Results of AgentValCon fallback agents in the input shape of the test report v2 (``scripts/report_v2.py import``).

    python -m agent_market.fallback_agents.report_input --out exports/pearls/avc-results.json [agent_id ...]
    .venv/bin/python -m scripts.report_v2 import exports/pearls/avc-results.json --no-board   # search & RAG team

Each agent runs the workflow team's fixed role tasks for its contract (``role_tasks/role-tasks-v1.jsonl``) through
the same ``FallbackAgents.execute`` path a necklace slot uses. Report ids live in their own namespace
``avc:<agent_id>`` (PM 11-14: plan A, no catalog resource), so they never collide with catalog resource ids and are
never ranked as pearls. The answer text handed to the report is the whole envelope (result, sources and licenses,
freshness), so the data-quality rules (accuracy against the case, freshness from the stated dates) apply unchanged.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from .agents import FallbackAgents, FallbackUnavailable
from .catalog import SPECS

NAMESPACE = "avc:"


def report_id(agent_id: str) -> str:
    return NAMESPACE + agent_id


def results(agent_ids=None, agents: FallbackAgents | None = None, cases_for=None, clock=time.time) -> list[dict]:
    from ..necklaces import role_tasks
    agents = agents or FallbackAgents()
    by_role = cases_for() if cases_for else role_tasks.by_role()
    out = []
    for agent_id in agent_ids or sorted(SPECS):
        spec = SPECS[agent_id]
        for case in by_role.get(spec["contract"], []):
            started = clock()
            t0 = time.monotonic()
            row = {"id": report_id(agent_id), "role": spec["contract"], "tool": spec["tool"],
                   "arguments": case["input"], "case": case, "started": started,
                   "host": urlsplit(spec["sources"][0]["url"]).hostname,
                   "endpoint": f"in-process:agent_market.fallback_agents/{agent_id}",
                   "source": "agentvalcon fallback (in-process)", "http": None}
            try:
                envelope = agents.execute(agent_id, case["input"])
                text = json.dumps(envelope, ensure_ascii=False)
                row.update(outcome="succeeded", reason=None, full_text=text, excerpt=text[:1000],
                           structured=envelope["result"])
            except FallbackUnavailable as exc:
                # Out of coverage (e.g. a concert for the national-holiday agent) is a failed version, as the
                # report rules count it; the reason keeps the agent's own words.
                row.update(outcome="failed", reason=f"{exc.code}: {exc}", full_text="", excerpt="", structured=None)
            row["latency_ms"] = int((time.monotonic() - t0) * 1000)
            out.append(row)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write AgentValCon fallback results for scripts.report_v2 import.")
    parser.add_argument("agents", nargs="*", help="agent ids (default: all)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    unknown = [a for a in args.agents if a not in SPECS]
    if unknown:
        parser.error("unknown agent ids: " + ", ".join(unknown))
    from .net import budget
    with budget("substitute_tests"):  # report runs are our own readiness tests in the shared daily ledger
        rows = results(args.agents or None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"namespace": NAMESPACE, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                    "results": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({r["id"]: r["outcome"] for r in rows}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

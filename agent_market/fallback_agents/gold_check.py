"""Score fallback agents against a necklace gold set (workflow team, ``agent_market/necklaces/gold.py``).

    python -m agent_market.fallback_agents.gold_check nvd-cve cve-org cisa-kev --out report.json
    python -m agent_market.fallback_agents.gold_check github-advisory --out report.json

Only the ``tuning`` split is read unless ``--split`` names another; the held-out
rounds belong to the ops launch gate. Every case is a real call through the agent
(its pacing and cache included), so this is the same path a necklace slot uses.

Pass rules (per case):
- nvd-cve: CVSS version equal to the NVD truth and score within 0.1 (cvelistV5 truth when NVD had none).
- cve-org (PM 11-14): the score equals the value of the source it names, the CVE record's CNA or ADP
  block (``truth.cvss_record``), and that source is named; no score when the record has none.
- cisa-kev: ``kev`` equal to the truth (and the listing date when listed). EPSS is
  reported separately: same band (<0.01, 0.01-0.1, 0.1-0.5, >=0.5) as the truth; EPSS
  moves daily, so a band change is shown, not counted as a failure.
- github-advisory: every truth advisory group (aliases folded) that has a GHSA id is
  found (recall 1.0 over GHSA-coverable groups), and a clean truth gets no advisory.
  Recall over all groups (OSV-only PYSEC groups included) is reported too.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from .agents import FallbackAgents, FallbackUnavailable
from .catalog import SPECS, contract
from .net import budget

SLUG = {"nvd-cve": "cve-incident-brief", "cve-org": "cve-incident-brief", "cisa-kev": "cve-incident-brief",
        "github-advisory": "package-risk-audit", "package-registry": "package-risk-audit",
        "depsdev-package": "package-risk-audit"}
BANDS = (0.01, 0.1, 0.5)


def band(x):
    if x is None:
        return None
    return sum(x >= b for b in BANDS)


def judge(agent_id: str, case: dict, result: dict | None) -> dict:
    truth = case["truth"]
    if result is None:
        return {"pass": False}
    if agent_id == "cve-org":
        # PM 11-14: the value must equal the value of the source it names (CNA or ADP in the CVE record).
        want = truth.get("cvss_record")
        if want is None or want.get("score") is None:
            return {"pass": result.get("cvss_score") is None, "got": [result.get("cvss_score"), result.get("source")],
                    "want": None}
        label = f"{str(want.get('from', '')).upper()} {want.get('provider', '')}"
        ok = (result.get("cvss_version") == want.get("version") and result.get("cvss_score") is not None
              and abs(result["cvss_score"] - float(want["score"])) <= 0.1 and label in str(result.get("source")))
        return {"pass": ok, "got": [result.get("cvss_score"), result.get("cvss_version"), result.get("source")],
                "want": [want.get("score"), want.get("version"), label]}
    if agent_id == "nvd-cve":
        want = truth["cvss"]
        ok = (result.get("cvss_version") == want.get("version") and result.get("cvss_score") is not None
              and abs(result["cvss_score"] - float(want["score"])) <= 0.1)
        return {"pass": ok, "got": [result.get("cvss_score"), result.get("cvss_version")],
                "want": [want.get("score"), want.get("version"), want.get("source")]}
    if agent_id == "cisa-kev":
        ok = result["kev"] == truth["kev"] and (not truth["kev"] or result.get("kev_date_added") == truth.get("kev_date_added"))
        return {"pass": ok, "epss_band_same": band(result.get("epss")) == band(truth.get("epss")),
                "epss_present": "epss" in result, "got": [result["kev"], result.get("kev_date_added"), result.get("epss")],
                "want": [truth["kev"], truth.get("kev_date_added"), truth.get("epss")]}
    if agent_id == "github-advisory":
        found = set()
        for item in result["items"]:
            found.add(item["id"])
            found.update(item.get("aliases") or [])
        groups, seen = [], set()
        for adv in truth["advisories"]:
            key = frozenset(adv["ids"])
            if key not in seen:
                seen.add(key)
                groups.append(key)
        coverable = [g for g in groups if any(i.startswith("GHSA-") for i in g)]
        hit = [g for g in groups if g & found]
        hit_cov = [g for g in coverable if g & found]
        ok = (len(hit_cov) == len(coverable)) and (bool(groups) or not result["items"])
        return {"pass": ok, "recall_all": round(len(hit) / len(groups), 3) if groups else None,
                "recall_ghsa": round(len(hit_cov) / len(coverable), 3) if coverable else None,
                "got": len(result["items"]), "want_groups": len(groups), "want_ghsa_groups": len(coverable)}
    if agent_id in ("package-registry", "depsdev-package"):
        # Gold truth is the registry's latest version at build time; a release since then shows as a miss
        # and is listed, not hidden.
        return {"pass": result.get("latest_version") == truth.get("latest_version"),
                "got": result.get("latest_version"), "want": truth.get("latest_version"),
                "signals": sorted(k for k in result if k != "source")}
    raise ValueError(agent_id)


def role_task_check(agent_ids, agents: FallbackAgents | None = None) -> dict:
    """Run the workflow team's fixed role tasks (role_tasks/role-tasks-v1.jsonl) for each agent's contract."""
    from ..necklaces import role_tasks
    from urllib.parse import urlsplit
    from .net import get
    agents = agents or FallbackAgents()
    out = {}
    for agent_id in agent_ids:
        rows = []
        rag = Path(role_tasks.FILE).with_name("role-tasks-rag-v1.jsonl")  # search & RAG's verified tasks
        cases = role_tasks.load() + (role_tasks.load(rag) if rag.exists() else [])
        for case in cases:
            if case["contract"] != SPECS[agent_id]["contract"]:
                continue
            try:
                result = agents.execute(agent_id, case["input"])["result"]
            except FallbackUnavailable as exc:
                rows.append({"case_id": case["case_id"], "pass": False, "error": exc.code})
                continue
            ok, why = role_tasks.score(case, json.dumps(result), result)
            for field, url in ((case.get("expect") or {}).get("dynamic") or {}).items():
                # Only registry "latest" checks run here; other live references (e.g. a weather service this
                # project does not use) are listed as not checked, never as passed.
                # Only a registry "latest" document compares field-for-field with a version; anything else is
                # listed as not checked rather than passed vacuously.
                if not isinstance(url, str) or urlsplit(url).hostname not in ("registry.npmjs.org", "pypi.org"):
                    if isinstance(url, str):
                        why = why + [f"{field}: live reference {urlsplit(url).hostname} not checked"]
                    continue
                live = json.loads(get(url, limiters=agents.limiters, seconds=5, limit=1 << 20).content)
                if result.get(field) != live.get("version"):
                    ok, why = False, why + [f"{field} {result.get(field)} != live {live.get('version')}"]
            rows.append({"case_id": case["case_id"], "pass": ok, "why": why})
        out[agent_id] = {"passed": sum(r["pass"] for r in rows), "cases": len(rows), "rows": rows}
    return out


def budget_system(split: str) -> str:
    """Held-out rounds are gate runs (ops 11-14); tuning runs are our own readiness tests."""
    return "gate" if split.startswith("holdout") else "substitute_tests"


def check(agent_ids, root: Path, split: str = "tuning", agents: FallbackAgents | None = None,
          pause: float = 0.0, sleep=time.sleep) -> dict:
    with budget(budget_system(split)):
        return _check(agent_ids, root, split, agents, pause, sleep)


def _check(agent_ids, root, split, agents, pause, sleep):
    agents = agents or FallbackAgents()
    report = {"split": split, "agents": {}}
    for agent_id in agent_ids:
        path = root / "gold" / SLUG[agent_id] / f"{split}.jsonl"
        cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows = []
        for case in cases:
            started = time.monotonic()
            result, code, cache = None, None, None
            allowed = contract(SPECS[agent_id]["contract"])["input_schema"]["properties"]
            arguments = {k: v for k, v in case["input"].items() if k in allowed}
            try:
                envelope = agents.execute(agent_id, arguments)
                result, cache = envelope["result"], envelope["cache"]["status"]
            except FallbackUnavailable as exc:
                code = exc.code
            row = {"case_id": case["case_id"], "stratum": case.get("stratum"), "ms": int((time.monotonic() - started) * 1000),
                   "error": code, "cache": cache, **judge(agent_id, case, result)}
            rows.append(row)
            if pause:
                sleep(pause)
        ms = [r["ms"] for r in rows if r["error"] is None]
        summary = {"cases": len(rows), "passed": sum(r["pass"] for r in rows),
                   "errors": {c: sum(r["error"] == c for r in rows) for c in {r["error"] for r in rows if r["error"]}},
                   "p50_ms": int(statistics.median(ms)) if ms else None,
                   "p95_ms": int(sorted(ms)[max(0, int(len(ms) * 0.95 + 0.5) - 1)]) if ms else None,
                   "gold_sha256": None}
        manifest = root / "gold" / SLUG[agent_id] / "manifest.json"
        if manifest.exists():
            summary["gold_sha256"] = json.loads(manifest.read_text())["files"].get(split, {}).get("sha256")
            summary["gold_created_at"] = json.loads(manifest.read_text()).get("created_at")
        if agent_id == "cisa-kev":
            summary["epss_band_same"] = sum(bool(r.get("epss_band_same")) for r in rows)
            summary["epss_present"] = sum(bool(r.get("epss_present")) for r in rows)
        report["agents"][agent_id] = {"summary": summary, "cases": rows}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score AgentValCon fallback agents against a necklace gold set.")
    parser.add_argument("agents", nargs="+", choices=sorted(SLUG))
    parser.add_argument("--root", type=Path, default=Path("gateway-data/necklaces"))
    parser.add_argument("--split", default="tuning")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pause", type=float, default=0.0, help="seconds between cases")
    parser.add_argument("--role-tasks", action="store_true", help="also run the fixed role tasks")
    args = parser.parse_args(argv)
    report = check(args.agents, args.root, args.split, pause=args.pause)
    if args.role_tasks:
        with budget(budget_system(args.split)):
            report["role_tasks"] = role_task_check(args.agents)
        print(json.dumps({k: [v["passed"], v["cases"]] for k, v in report["role_tasks"].items()}))
    report["at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v["summary"] for k, v in report["agents"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Machine-readable test evidence v1 (PM 11-16 assignment 3, due 11-28; with search and RAG).

    .venv/bin/python -m scripts.test_evidence [--out exports/pearls/evidence] [--only RID]

One record per stored test (a report v2 version file under exports/pearls/reports/<rid>/<role>/), read-only, written
as one JSON file per agent: exports/pearls/evidence/agents/<rid>.json = {schema, subject, generated, roles:[{role,
tool, summary}], records:[...]}. The summary is report_v2.role_task_summary (the same function the verify snapshot
uses, so the counts agree): records of a role tool = tasks_run, records with result.correct = tasks_correct.

Rules (PM 11-16 21:5x and source review C04):
- Public role-task sets (workflow:role-tasks-v1, rag:role-tasks-rag-v1, live:<url>) may show the task input.
  Every other set, and a record that names no set, shows only hashes of the case id (never the input or the truth),
  so a private holdout answer set is never published.
- A record missing any required key (endpoint, tool fingerprint, evaluator version, answer set, case id, response
  hash) is kept but marked complete: false with the missing keys, and qualifies is false. Missing keys never count as
  equal to anything.
- The answer itself is never included, only its hashes. Times are ISO 8601 +09:00. A field without a value is left
  out; signature stays null until the December signing.
Only our own tests are here (report v2 stores our role-task calls and our in-process substitutes, nothing else).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import report_v2 as V  # noqa: E402  (tests repoint V.OUT; one module object)

SCHEMA = "avc.test-evidence.v1"
PUBLIC_SETS = ("workflow:role-tasks-v1", "rag:role-tasks-rag-v1")
PUBLIC_PREFIXES = ("live:",)
REQUIRED = ("endpoint", "tool_fingerprint", "evaluator_version", "answer_set", "case_id", "response_hash")
MAX_RECORDS = 200
KST = dt.timezone(dt.timedelta(hours=9))


def _iso(ts) -> str | None:
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return None
    return dt.datetime.fromtimestamp(ts, KST).isoformat(timespec="seconds") if ts > 0 else None


def public_set(name) -> bool:
    return isinstance(name, str) and (name in PUBLIC_SETS or name.startswith(PUBLIC_PREFIXES))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record(v: dict) -> dict:
    """One evidence record for one stored test version."""
    missing = [k for k in REQUIRED if v.get(k) in (None, "")]
    answer_set = v.get("answer_set")
    task = {}
    if answer_set:
        task["answer_set"] = answer_set
    if public_set(answer_set):
        if v.get("case_id"):
            task["case_id"] = v["case_id"]
        if isinstance(v.get("arguments"), dict):
            task["input"] = v["arguments"]
    elif v.get("case_id"):     # private or unnamed set: hashes only (PM 11-16)
        task["case_id_sha256"] = _sha(f"{answer_set or ''}:{v['case_id']}")
    subject = {"kind": "agent", "id": str(v.get("resource_id")), "tool": v.get("tool")}
    if v.get("tool_fingerprint"):
        subject["tool_fingerprint"] = "sha256:" + str(v["tool_fingerprint"])
        subject["fingerprint_version"] = v.get("fingerprint_version") or "fingerprint-v1"
    if v.get("endpoint"):
        subject["endpoint"] = v["endpoint"]
    run = {"at": _iso(v.get("tested")), "attempt_id": v.get("attempt_id"), "runner": v.get("source")}
    evaluator = {"version": v.get("evaluator_version"), "methodology": V.METHODOLOGY_VERSION,
                 "rules": (v.get("judgement") or {}).get("rules")}
    correct = bool(V.passing(v))
    result = {"outcome": v.get("outcome"), "correct": correct, "verdict": v.get("content_verdict"),
              "score": (v.get("quality") or {}).get("score") if isinstance(v.get("quality"), dict) else None}
    content = {"response_sha256": v.get("response_hash"), "answer_sha256": v.get("answer_sha256")}
    out = {"schema": SCHEMA, "type": "run", "subject": _clean(subject), "role": V.canonical(v.get("role")),
           "task": task, "run": _clean(run), "evaluator": _clean(evaluator), "result": _clean(result),
           "content": _clean(content), "complete": not missing, "qualifies": correct and not missing,
           "signature": None}
    if missing:
        out["missing"] = missing
    return out


def _clean(d: dict) -> dict:
    return {k: x for k, x in d.items() if x not in (None, "")}


def agent_evidence(rid, now=None) -> dict | None:
    """Every stored test of one agent, newest first (at most MAX_RECORDS), with the per role-tool summary."""
    now = time.time() if now is None else now
    base = V.OUT / "reports" / str(rid)
    if not base.is_dir():
        return None
    versions, roles = [], {}
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        for v in V.versions_of(rid, folder.name):
            versions.append(v)
            roles.setdefault((V.canonical(v.get("role") or folder.name), v.get("tool")), folder.name)
    if not versions:
        return None
    versions.sort(key=lambda v: float(v.get("tested") or 0), reverse=True)
    summary = []
    for (role, tool), folder in sorted(roles.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        summary.append({"role": role, "tool": tool, "summary": V.role_task_summary(rid, folder, tool, now)})
    return {"schema": SCHEMA, "subject": {"kind": "agent", "id": str(rid)}, "generated": _iso(now),
            "records_total": len(versions), "roles": summary,
            "records": [record(v) for v in versions[:MAX_RECORDS]]}


def write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def build(out: Path, only=None, now=None) -> dict:
    """Write one file per agent with stored tests; returns counts for the run log."""
    base = V.OUT / "reports"
    rids = [only] if only else sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
    written = records = incomplete = 0
    for rid in rids:
        data = agent_evidence(rid, now)
        if data is None:
            continue
        write_atomic(out / "agents" / f"{rid}.json", data)
        written += 1
        records += data["records_total"]
        incomplete += sum(1 for r in data["records"] if not r["complete"])
    return {"agents": written, "records": records, "incomplete_in_files": incomplete}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default=str(ROOT / "exports/pearls/evidence"))
    p.add_argument("--only")
    ns = p.parse_args(argv)
    print(json.dumps(build(Path(ns.out), ns.only)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

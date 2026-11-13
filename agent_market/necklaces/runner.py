"""Necklace runner: parallel slots, chain v2 fallbacks, charter stages, body-free run events.

Design: reports/necklace-design-2026-11-14 (b) and reports/necklace-watch-2026-11-14.

- Slots that do not depend on each other run in parallel (one thread each) under the
  necklace deadline (``budget_ms.total``, 5 s for a complex answer).
- In a slot the ``fanout`` lead members run together. If none returns a usable
  answer, the next members of the runtime chain (watch demotions and exclusions
  applied) are tried one by one: remaining external members first, then at most two
  AgentValCon fallbacks. A member is called at most once per slot in a run.
- Every member call goes through the caller given to the runner. In production that
  is the workflow engine's registered-agent path (execution permission, public
  endpoint check, health, no paid tools, argument validation, edge gateway), so the
  runner adds no new way to reach a provider.
- Each slot records its stage (1 lead answered, 2 an external fallback answered,
  3 an AgentValCon fallback answered, 4 every member failed).
- The run event keeps no input and no output, only outcome, stages, timing and the
  failed slot, for 90 days of metadata (watch design, section 5).
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from pathlib import Path

from . import model
from .watch import runtime_chain

MIN_ATTEMPT_MS = 600


@dataclass
class Attempt:
    resource_id: int | None
    tool: str
    kind: str
    rank: int
    ok: bool
    ms: int
    error_class: str | None = None


@dataclass
class SlotResult:
    slot: str
    required: bool
    fanout: int = 1
    answers: list = field(default_factory=list)       # (member, canonical) pairs that passed
    attempts: list = field(default_factory=list)

    @property
    def stage(self) -> int:
        if not self.answers:
            return 4
        used = [a for a in self.attempts if a.ok]
        if any(a.kind == "external" and a.rank <= self.fanout for a in used):
            return 1          # a lead (fan-out) member answered
        return 2 if any(a.kind == "external" for a in used) else 3

    def used(self) -> dict:
        ok = [a for a in self.attempts if a.ok]
        best = min(ok, key=lambda a: a.rank) if ok else None
        return {"rank": best.rank if best else None, "kind": best.kind if best else None,
                "failed": not self.answers, "stage": self.stage}


# ---------------------------------------------------------------- argument mapping
TEMPLATE = re.compile(r"^\{\{input\.([a-z_][a-z0-9_]*)\}\}$")


def render(input_map: dict, values: dict) -> dict:
    """Fill ``{{input.x}}`` templates; an argument whose input is absent is left out."""
    args = {}
    for key, value in input_map.items():
        match = TEMPLATE.match(value) if isinstance(value, str) else None
        if match:
            if values.get(match.group(1)) not in (None, ""):
                args[key] = values[match.group(1)]
        else:
            args[key] = value
    return args


def in_coverage(member: dict, values: dict) -> bool:
    for key, allowed in (member.get("coverage") or {}).items():
        if key in values and values[key] not in allowed:
            return False
    return True


# ---------------------------------------------------------------- normalizers
ADVISORY_ID = re.compile(r"\b(GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}|CVE-\d{4}-\d{4,}|PYSEC-\d{4}-\d+|OSV-\d{4}-\d+|RUSTSEC-\d{4}-\d{4}|GO-\d{4}-\d{4})\b", re.I)
CVSS = re.compile(r"(?:cvss[^0-9]{0,40}|base[ _]?score[^0-9]{0,10}|\"score\"\s*:\s*)(\d{1,2}(?:\.\d)?)", re.I)
URL = re.compile(r"https://[^\s\"'<>)\]]+")
KEV_YES = re.compile(r"(known exploited|\bkev\b|cisa kev|actively exploited|exploited in the wild)", re.I)
KEV_NO = re.compile(r"(not (in|on|listed in) (the )?(cisa )?(kev|known exploited)|\"kev\"\s*:\s*false|\"in_kev\"\s*:\s*false)", re.I)


def _text(raw) -> str:
    return raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, default=str)


def norm_advisories(raw, values):
    text = _text(raw)
    if not text.strip():
        return None
    ids = sorted({m.group(1).upper() for m in ADVISORY_ID.finditer(text)})
    return {"items": [{"id": i} for i in ids], "urls": URL.findall(text)[:20]}


def norm_record(raw, values):
    text = _text(raw)
    if values.get("cve_id", "").upper() not in text.upper():
        return None
    score = next((float(m.group(1)) for m in CVSS.finditer(text) if 0 <= float(m.group(1)) <= 10), None)
    return {"cve_id": values["cve_id"], "cvss_score": score, "references": URL.findall(text)[:20]}


def norm_exploited(raw, values):
    text = _text(raw)
    if not text.strip():
        return None
    structured = raw if isinstance(raw, dict) else {}
    if isinstance(structured.get("kev"), bool):
        kev = structured["kev"]
    else:
        kev = bool(KEV_YES.search(text)) and not KEV_NO.search(text)
    return {"cve_id": values.get("cve_id"), "kev": kev}


def norm_generic(raw, values):
    text = _text(raw)
    return {"text": text[:4000], "urls": URL.findall(text)[:20]} if text.strip() else None


NORMALIZERS = {"package.advisories.v1": norm_advisories, "cve.record.v1": norm_record,
               "cve.exploited.v1": norm_exploited}


# ---------------------------------------------------------------- synthesis (merge-v1)
def merge(contract: str, answers: list) -> dict:
    sources = [f"{m.get('kind')}:{m.get('resource_id') or m.get('agent_id')}" for m, _ in answers]
    if contract == "package.advisories.v1":
        counts: dict[str, int] = {}
        for _, canon in answers:
            for item in canon["items"]:
                counts[item["id"]] = counts.get(item["id"], 0) + 1
        return {"items": [{"id": i, "sources": n, "agreed": n >= 2} for i, n in sorted(counts.items())],
                "sources": sources}
    if contract == "cve.record.v1":
        scores = sorted({c["cvss_score"] for _, c in answers if c.get("cvss_score") is not None})
        return {"cve_id": answers[0][1]["cve_id"], "cvss_score": scores[0] if len(scores) == 1 else None,
                "cvss_scores": scores, "agreed": len(scores) == 1 and len(answers) >= 2,
                "conflict": len(scores) > 1, "sources": sources}
    if contract == "cve.exploited.v1":
        values = {c["kev"] for _, c in answers}
        return {"cve_id": answers[0][1]["cve_id"], "kev": values.pop() if len(values) == 1 else None,
                "conflict": len(values) > 1, "sources": sources}
    return {"answers": [c for _, c in answers], "sources": sources}


# ---------------------------------------------------------------- runner
class Runner:
    def __init__(self, caller, *, watch_state: dict | None = None, clock=time.monotonic, workers: int = 8):
        """``caller(member, args, timeout_s)`` returns the raw tool output or raises."""
        self.caller, self.watch_state, self.clock, self.workers = caller, watch_state or {}, clock, workers

    def _call(self, member, rank, values, contract, deadline):
        started = self.clock()
        left = deadline - started
        if left * 1000 < MIN_ATTEMPT_MS:
            return Attempt(member.get("resource_id"), member["tool"], member["kind"], rank, False, 0, "deadline"), None
        try:
            raw = self.caller(member, render(member.get("input_map") or {}, values), left)
            canon = NORMALIZERS.get(contract, norm_generic)(raw, values)
            ok, error = canon is not None, None if canon is not None else "contract_invalid"
        except Exception as exc:   # every failure of one member is that member's, never the run's
            canon, ok, error = None, False, getattr(exc, "error_code", None) or type(exc).__name__
        ms = int((self.clock() - started) * 1000)
        return Attempt(member.get("resource_id"), member["tool"], member["kind"], rank, ok, ms, error), canon

    def run_slot(self, slug: str, slot: dict, values: dict, deadline: float) -> SlotResult:
        result = SlotResult(slot["slot"], bool(slot.get("required", True)), max(1, slot.get("fanout", 1)))
        chain = [m for m in runtime_chain(slot, slug, self.watch_state) if in_coverage(m, values)]
        ranked = list(enumerate(chain, start=1))
        externals = [(r, m) for r, m in ranked if m["kind"] == "external"]
        fanout = max(1, slot.get("fanout", 1))
        lead, rest = externals[:fanout], [x for x in ranked if x not in externals[:fanout]]
        with ThreadPoolExecutor(max_workers=max(1, len(lead))) as pool:
            futures = [pool.submit(self._call, m, r, values, slot["contract"], deadline) for r, m in lead]
            for future in futures:
                attempt, canon = future.result()
                result.attempts.append(attempt)
                if attempt.ok:
                    result.answers.append((next(m for r, m in lead if r == attempt.rank), canon))
        for rank, member in rest:      # externals first, then AgentValCon fallbacks (chain order)
            if result.answers:
                break
            attempt, canon = self._call(member, rank, values, slot["contract"], deadline)
            result.attempts.append(attempt)
            if attempt.ok:
                result.answers.append((member, canon))
        return result

    def run(self, defn: dict, values: dict) -> dict:
        started = self.clock()
        deadline = started + defn["budget_ms"]["total"] / 1000
        slots = defn["slots"]
        results: dict[str, SlotResult] = {}
        with ThreadPoolExecutor(max_workers=min(self.workers, len(slots))) as pool:
            pending = {pool.submit(self.run_slot, defn["slug"], slot, values, deadline): slot["slot"] for slot in slots}
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    results[pending.pop(future)] = future.result()
        failed = [s.slot for s in results.values() if s.required and not s.answers]
        output = {name: (merge(next(sl["contract"] for sl in slots if sl["slot"] == name), r.answers)
                         if r.answers else {"missing": True}) for name, r in results.items()}
        return {
            "slug": defn["slug"], "version": defn["version"], "digest": model.digest(defn),
            "ok": not failed, "completed": not failed,
            "completed_external_only": not failed and all(
                a.kind == "external" for r in results.values() for a in r.attempts if a.ok),
            "failed_slot": failed[0] if failed else None,
            "latency_ms": int((self.clock() - started) * 1000),
            "slots": {name: r.used() for name, r in results.items()},
            "attempts": {name: [a.__dict__ for a in r.attempts] for name, r in results.items()},
            "output": output,
        }


def run_event(result: dict, source: str, at: float | None = None) -> dict:
    """The body-free line for ``runs/<date>.jsonl``: no input, no output."""
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if at is None else at)),
            "slug": result["slug"], "version": result["version"], "source": source,
            "outcome": "succeeded" if result["ok"] else "failed", "failed_slot": result["failed_slot"],
            "latency_ms": result["latency_ms"],
            "stages": {name: s["stage"] for name, s in result["slots"].items()},
            "agentcon_used": any(s["kind"] == "agentcon" for s in result["slots"].values())}


def append_event(root: Path, event: dict):
    path = Path(root) / "runs" / (event["at"][:10].replace("-", "") + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def engine_caller(engine):
    """Production caller: the workflow engine's registered-agent path with all its guards."""
    def call(member, args, timeout_s):
        node = {"resource_id": member["resource_id"], "kind": "mcp", "data": {"tool": member["tool"]}}
        return engine._call_registered(node, args)
    return call

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
import threading
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
    raw: str | None = None


@dataclass
class SlotResult:
    slot: str
    required: bool
    fanout: int = 1
    answers: list = field(default_factory=list)       # (member, canonical) pairs that passed
    attempts: list = field(default_factory=list)
    abandoned: int = 0

    @property
    def status(self) -> str:
        """answered, partial (answered while another call timed out), timeout or failed."""
        timed = any(a.error_class in ("timeout", "late", "deadline") for a in self.attempts)
        if self.answers:
            return "partial" if timed else "answered"
        return "timeout" if timed else "failed"

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
                "failed": not self.answers, "stage": self.stage, "status": self.status}


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
# A CVSS base score, never the CVSS version ("CVSS:3.1/AV:...", "cvssV3_1", "version": "3.1").
SCORE_KEYS = ("baseScore", "base_score", "cvss_score", "cvssScore", "score")
CVSS_TEXT = re.compile(r"(?:base[ _-]?score|cvss[ _-]?score)\W{0,12}(\d{1,2}(?:\.\d)?)", re.I)
CVSS_VECTOR = re.compile(r"cvss:\d\.\d/|cvssv\d_\d|\bv\d\.\d\b", re.I)


def find_score(raw):
    """The first numeric base score in a structured answer (depth-first), else one written in the text."""
    stack = [raw]
    while stack:
        node = stack.pop(0)
        if isinstance(node, dict):
            for key in SCORE_KEYS:
                value = node.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 10:
                    return float(value)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    text = CVSS_VECTOR.sub(" ", _text(raw))
    match = CVSS_TEXT.search(text)
    return float(match.group(1)) if match and 0 <= float(match.group(1)) <= 10 else None
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
    return {"cve_id": values["cve_id"], "cvss_score": find_score(raw), "references": URL.findall(text)[:20]}


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
# Process-wide cap on member calls in flight, abandoned ones included (a caller that ignores its
# timeout keeps its thread until it returns); a call over the cap is not sent (error "capacity").
MAX_INFLIGHT = 32
_INFLIGHT = threading.BoundedSemaphore(MAX_INFLIGHT)


class Runner:
    """One necklace run under an absolute deadline (PM F04, 11-14).

    - absolute deadline = start + budget_ms.total; each slot also stops at start + budget_ms.slot
    - every call gets what is left of its slot deadline as its timeout
    - a call that ends after its slot deadline is "late" and never counts; a call still running at the
      slot deadline is recorded as "timeout" and abandoned
    - optional slots run under the same slot deadline; a slow optional slot never fails the run
    - the executor is shut down without waiting (wait=False, cancel_futures=True); calls already running
      keep their worker thread until they return, which the process-wide cap accounts for
    """

    def __init__(self, caller, *, watch_state: dict | None = None, clock=time.monotonic, workers: int = 8,
                 keep_raw: int = 0, inflight=None):
        """``caller(member, args, timeout_s)`` returns the raw tool output or raises. ``keep_raw`` keeps that
        many characters of each raw answer on the attempt (self-tests only; public gold inputs)."""
        self.caller, self.watch_state, self.clock, self.workers = caller, watch_state or {}, clock, workers
        self.keep_raw = keep_raw
        self.inflight = _INFLIGHT if inflight is None else inflight

    def _call(self, member, rank, values, contract, deadline):
        started = self.clock()
        left = deadline - started
        if left * 1000 < MIN_ATTEMPT_MS:
            return Attempt(member.get("resource_id"), member["tool"], member["kind"], rank, False, 0, "deadline"), None
        try:
            raw = self.caller(member, render(member.get("input_map") or {}, values), left)
            canon = NORMALIZERS.get(contract, norm_generic)(raw, values)
            ok, error = canon is not None, None if canon is not None else "contract_invalid"
            kept = _text(raw)[:self.keep_raw] if self.keep_raw else None
        except Exception as exc:   # every failure of one member is that member's, never the run's
            canon, ok, error = None, False, (getattr(exc, "error_code", None) or getattr(exc, "code", None)
                                            or type(exc).__name__)
            kept = str(exc)[:self.keep_raw] if self.keep_raw else None
        finished = self.clock()
        if finished > deadline:          # an answer after the deadline never counts
            canon, ok, error = None, False, "late"
        ms = int((finished - started) * 1000)
        return Attempt(member.get("resource_id"), member["tool"], member["kind"], rank, ok, ms, error, kept), canon

    # -- scheduling helpers
    def _submit(self, pool, st, rank, member, values, run_started):
        if not self.inflight.acquire(blocking=False):
            st["result"].attempts.append(Attempt(member.get("resource_id"), member["tool"], member["kind"], rank,
                                                 False, 0, "capacity"))
            return False
        future = pool.submit(self._call, member, rank, values, st["slot"]["contract"], st["deadline"])
        future.add_done_callback(lambda _f: self.inflight.release())   # also runs when cancelled
        st["inflight"][future] = (rank, member)
        return True

    def _advance(self, pool, st, values, run_started):
        """Start the next chain member of a slot that has no answer and nothing in flight."""
        while st["queue"] and not st["inflight"] and not st["result"].answers:
            rank, member = st["queue"].pop(0)
            if (st["deadline"] - self.clock()) * 1000 < MIN_ATTEMPT_MS:
                st["result"].attempts.append(Attempt(member.get("resource_id"), member["tool"], member["kind"],
                                                     rank, False, 0, "deadline"))
                st["queue"].clear()
                return
            self._submit(pool, st, rank, member, values, run_started)

    @staticmethod
    def _settled(st, now) -> bool:
        if st["inflight"]:
            return now >= st["deadline"]
        return bool(st["result"].answers) or not st["queue"] or now >= st["deadline"]

    def _abandon(self, st, now, run_started, reason="timeout"):
        for future, (rank, member) in list(st["inflight"].items()):
            st.setdefault("abandoned_futures", []).append(future)
            st["result"].attempts.append(Attempt(member.get("resource_id"), member["tool"], member["kind"], rank,
                                                 False, int((now - run_started) * 1000), reason))
            st["result"].abandoned += 1
        st["inflight"].clear()

    def run(self, defn: dict, values: dict) -> dict:
        started = self.clock()
        total_s = defn["budget_ms"]["total"] / 1000
        deadline = started + total_s
        slot_deadline = started + min(total_s, defn["budget_ms"].get("slot", defn["budget_ms"]["total"]) / 1000)
        pool = ThreadPoolExecutor(max_workers=self.workers)
        states: dict[str, dict] = {}
        try:
            for slot in defn["slots"]:
                chain = [m for m in runtime_chain(slot, defn["slug"], self.watch_state) if in_coverage(m, values)]
                ranked = list(enumerate(chain, start=1))
                fanout = max(1, slot.get("fanout", 1))
                lead = [(r, m) for r, m in ranked if m["kind"] == "external"][:fanout]
                st = {"slot": slot, "required": bool(slot.get("required", True)),
                      "result": SlotResult(slot["slot"], bool(slot.get("required", True)), fanout),
                      "queue": [x for x in ranked if x not in lead], "inflight": {},
                      "deadline": min(deadline, slot_deadline)}
                states[slot["slot"]] = st
                for rank, member in lead:
                    self._submit(pool, st, rank, member, values, started)
                self._advance(pool, st, values, started)
            while True:
                now = self.clock()
                for st in states.values():
                    if st["inflight"] and now >= st["deadline"]:
                        self._abandon(st, now, started)
                    self._advance(pool, st, values, started)
                if all(self._settled(st, now) for st in states.values()):
                    break
                waiting = {f: st for st in states.values() for f in st["inflight"]}
                if not waiting or now >= deadline:
                    for st in states.values():
                        self._abandon(st, now, started)
                    break
                until = min(st["deadline"] for st in states.values() if st["inflight"])
                done, _ = wait(list(waiting), timeout=max(0.0, min(until, deadline) - now),
                               return_when=FIRST_COMPLETED)
                for future in done:
                    st = waiting[future]
                    if future not in st["inflight"]:
                        continue
                    rank, member = st["inflight"].pop(future)
                    attempt, canon = future.result()
                    st["result"].attempts.append(attempt)
                    if attempt.ok:
                        st["result"].answers.append((member, canon))
        finally:
            still_running = sum(1 for st in states.values() for f in st.get("abandoned_futures", []) if not f.done())
            pool.shutdown(wait=False, cancel_futures=True)
        results = {name: st["result"] for name, st in states.items()}
        failed = [s.slot for s in results.values() if s.required and not s.answers]
        output = {name: (merge(states[name]["slot"]["contract"], r.answers) if r.answers else {"missing": True})
                  for name, r in results.items()}
        return {
            "slug": defn["slug"], "version": defn["version"], "digest": model.digest(defn),
            "ok": not failed, "completed": not failed,
            "completed_external_only": not failed and all(
                a.kind == "external" for r in results.values() for a in r.attempts if a.ok),
            "failed_slot": failed[0] if failed else None,
            "latency_ms": int((self.clock() - started) * 1000),
            "abandoned_calls": sum(r.abandoned for r in results.values()),
            "pending_at_return": still_running,
            "slots": {name: r.used() for name, r in results.items()},
            "attempts": {name: [a.__dict__ for a in r.attempts] for name, r in results.items()},
            "output": output,
        }


# ---------------------------------------------------------------- run source (north star)
# Runs we start ourselves always carry their origin; nothing we run can count as external.
OUR_ORIGINS = ("retest", "watch", "gate", "qa", "user_slo", "public_check", "growth_check", "rehearsal")
# The traffic rule's internal User-Agents predate the AgentValCon brand; ours are caught here too.
OUR_UA = re.compile(r"agentvalcon|agentcon", re.I)
# Same funnel classes as scripts/north_star.py (OLD_CLASS maps traffic.client_of classes onto them).
CLIENT_CLASS = {"internal": "internal", "ai_bot": "crawler", "verifier": "probe", "browser": "external",
                "script": "external", "other": "external", "headless": "external"}


def classify_source(origin: str | None = None, *, ip: str | None = None, ua: str | None = None,
                    qa: str | None = None, principal: str | None = None, internal_ips=frozenset(),
                    internal_principals=frozenset()) -> tuple[str, str]:
    """(source class, origin) for a run event. Only ``external`` counts for the north star.

    Our own runs (daily retest, watch, ops gate, QA tools, user_slo, public checks, growth screen
    checks) are internal by origin. Public requests use the traffic rule: X-Agentcon-QA, our
    User-Agents, internal addresses and our edge principals are internal; crawlers and probes are
    kept apart. An unknown origin is never treated as external by default."""
    if origin in OUR_ORIGINS:
        return "internal", origin
    if origin != "public":
        return "internal", origin or "unknown"
    if qa or (principal and principal in internal_principals) or OUR_UA.search(ua or ""):
        return "internal", "public"
    from ..concierge.traffic import client_of
    client, _ = client_of(ip, ua, internal_ips, qa)
    return CLIENT_CLASS.get(client, "external"), "public"


def run_event(result: dict, source: str, origin: str | None = None, at: float | None = None) -> dict:
    """The body-free line for ``runs/<date>.jsonl``: no input, no output."""
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if at is None else at)),
            "slug": result["slug"], "version": result["version"], "source": source, "origin": origin,
            "outcome": "succeeded" if result["ok"] else "failed", "failed_slot": result["failed_slot"],
            "latency_ms": result["latency_ms"],
            "stages": {name: s["stage"] for name, s in result["slots"].items()},
            "agentcon_used": any(s["kind"] == "agentcon" for s in result["slots"].values())}


def append_event(root: Path, event: dict):
    path = Path(root) / "runs" / (event["at"][:10].replace("-", "") + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def engine_caller(engine, fallbacks=None):
    """Production caller. External members (and any member with a resource_id) go through the
    workflow engine's registered-agent path with all its guards. AgentValCon fallbacks without a
    resource_id run in-process through agent_market.fallback_agents (PM path A)."""
    def call(member, args, timeout_s):
        if member.get("kind") == "agentcon" and not isinstance(member.get("resource_id"), int):
            lib = fallbacks
            if lib is None:
                from .. import fallback_agents as lib
            return lib.slot_output(lib.run(member["agent_id"], args))
        node = {"resource_id": member["resource_id"], "kind": "mcp", "data": {"tool": member["tool"]}}
        return engine._call_registered(node, args)
    return call


class BudgetDenied(Exception):
    def __init__(self, why: str):
        super().__init__(why)
        self.error_code = "budget_" + why


# Only a pause the provider itself asked for counts against its domain. Our own relay's rate limit
# (HTTP 429 from agentconcierge.biz, error "relay_throttled") never does (11-14 05:1x incident).
RATE_LIMITED = ("PROVIDER_429",)


def budgeted_caller(caller, system: str, url_of, budget=None):
    """Wrap a caller for runs we start ourselves (daily retest, gate) with the shared provider
    budget (deploy/PROVIDER_BUDGET.md): reserve before every external call, report a 429 after it.
    Public user runs are service traffic and do not use this wrapper. AgentValCon fallbacks run on
    our own host and are not counted."""
    if budget is None:
        from .. import provider_budget as budget

    def call(member, args, timeout_s):
        if member.get("kind") != "external":
            return caller(member, args, timeout_s)
        url = url_of(member)
        ok, why = budget.reserve(url, system)
        if not ok:
            raise BudgetDenied(why)
        try:
            return caller(member, args, timeout_s)
        except Exception as exc:
            code = str(getattr(exc, "status", "") or getattr(exc, "error_code", "") or "")
            if any(mark in code.upper() for mark in RATE_LIMITED):
                budget.note(url, system, 429)
            raise
    return call


def resource_url(store):
    """url_of for budgeted_caller: the registered endpoint of the member's resource."""
    def url_of(member):
        row = store.resource(member["resource_id"]) or {}
        return row.get("url") or ""
    return url_of

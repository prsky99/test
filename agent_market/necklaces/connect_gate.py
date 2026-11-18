"""The necklace gate is a connection test (user decisions 11-18 via PM 19:2x; docs/PRODUCTION_SYSTEM.md 7-1).

"목걸이 연결을 단계별로 진행해서 전부 통과 실행이 확인되서 결과가 나온 상태에서 다시 연결 테스트 3회를 했을 때 통과하면 공개."
The members were graded already (pearls, substitute gates); the gate checks that the chain connects, runs and falls
back. No accuracy grading, no held-out answer set.

Stage 1, step by step (development):
- the steps are joined one at a time in definition order; each partial chain runs for real and the new step must give
  contract-shaped output before the next step is added
- with every step joined, the whole chain must complete within its time budget
- per required step, the representative member is left out for one run and a fallback must answer the step: an outside
  member, or, on a step marked own_fallback (no outside fallback exists in the market), our approved substitute
Stage 2, three connection runs (the public gate): with stage 1 passed, the whole chain runs again on three different
task inputs (tuning only); all three must pass. One failure sends the failing step back to stage 1 and stage 2 starts
over. With both stages passed and an ops approval the necklace goes live (two keys).

Static rules (no call): every required step has a representative pearl (verified or final, or a provisional member
with a report v2 of 70 or more) and at least one outside fallback member, or is marked own_fallback with a substitute
whose substitute gate passed (also three connection runs: substitute_gate below); a necklace with own_fallback steps
needs outside pearls on two or more steps; terms allowed or silent; the watch fresh with no hold.

Lines go to <root>/connect/<slug>.jsonl {slug, version, digest, kind: gate|daily|substitute, ok, stage1, stage2, ...}.
After going live, one connection run a day (kind daily) keeps it open; the judge holds it when that run fails or is
older than DAILY_STALE_HOURS. Outside calls go through the shared ledger as "gate".

    .venv/bin/python -m agent_market.necklaces.connect_gate <slug>                       # stages 1 and 2
    .venv/bin/python -m agent_market.necklaces.connect_gate <slug> --daily               # one connection run
    .venv/bin/python -m agent_market.necklaces.connect_gate <slug> --substitute AGENT --slot STEP   # a substitute
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from . import model

CONNECT_RUNS = 3
DAILY_STALE_HOURS = 48
GATE_PASSED = ("approved", "provisional")     # substitute gate passed (deploy/NECKLACE_GATE.md section 10)
USABLE_TERMS = ("allowed", "silent")
ANSWERED = ("answered", "partial")
PEARL = ("verified_pearl", "provisional")      # standing of an outside member that counts (necklaces.members)
MIN_OUTSIDE_PEARL_STEPS = 2                    # with own_fallback steps (PM 19:2x)


def tuning_inputs(root: Path, slug: str, n: int = CONNECT_RUNS) -> list[dict]:
    """The first n different inputs of the tuning set (never a held-out split)."""
    path = Path(root) / "gold" / slug / "tuning.jsonl"
    seen, out = set(), []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        if not line.strip():
            continue
        values = json.loads(line).get("input") or {}
        key = json.dumps(values, sort_keys=True)
        if values and key not in seen:
            seen.add(key)
            out.append(values)
        if len(out) >= n:
            break
    return out


def required(defn: dict) -> list[str]:
    return [s["slot"] for s in defn["slots"] if s.get("required", True)]


def leaving_out(defn: dict, state: dict, slot_name: str, which: str, keep: str | None = None) -> dict:
    """A copy of the runtime state with members of one step marked excluded for this run only: "lead" leaves out the
    step's first member in running order, "others" every member but the agent id ``keep``. The watch is not touched."""
    from .watch import member_key, runtime_chain
    state = copy.deepcopy(state or {})
    marks = state.setdefault("members", {})
    slot = next(s for s in defn["slots"] if s["slot"] == slot_name)
    chain = runtime_chain(slot, defn["slug"], state)
    dropped = chain[:1] if which == "lead" else [m for m in chain if m.get("agent_id") != keep or m["kind"] != "agentcon"]
    for m in dropped:
        marks.setdefault(member_key(defn["slug"], slot_name, m), {})["excluded"] = True
    return state


def partial(defn: dict, upto: int) -> dict:
    """The definition with its first ``upto`` steps only (the steps it depends on come first in definition order)."""
    names = {s["slot"] for s in defn["slots"][:upto]}
    out = copy.deepcopy(defn)
    out["slots"] = [dict(s, depends_on=[d for d in s.get("depends_on") or [] if d in names])
                    for s in out["slots"][:upto]]
    return out


def step_ok(result: dict, slot_name: str, kinds: tuple = ("external", "agentcon")) -> tuple[bool, str | None]:
    used = (result.get("slots") or {}).get(slot_name) or {}
    if used.get("failed") or used.get("status") not in ANSWERED:
        return False, f"{slot_name}: {used.get('status') or 'no answer'}"
    if used.get("kind") not in kinds:
        return False, f"{slot_name}: answered by {used.get('kind')}"
    return True, None


TRACE_RAW = 200


def trace(result: dict) -> list[dict]:
    """Every failed attempt of the run (agent team 21:30, 11-18: 52559's three failures could not be told apart, the
    lines kept only the step name): step, member, error class, time and the first characters of the raw answer."""
    out = []
    for slot, attempts in (result.get("attempts") or {}).items():
        for a in attempts or []:
            if not a.get("ok"):
                out.append({"slot": slot, "member": a.get("resource_id") or a.get("tool"), "kind": a.get("kind"),
                            "error_class": a.get("error_class"), "ms": a.get("ms"),
                            "raw": (a.get("raw") or "")[:TRACE_RAW] or None})
    return out


def _row(row: dict, result: dict) -> dict:
    failures = trace(result)
    return dict(row, trace=failures) if failures else row


def run_ok(defn: dict, result: dict) -> tuple[bool, str | None]:
    if not result.get("completed"):
        return False, f"not completed (failed step {result.get('failed_slot')})"
    total = (defn.get("budget_ms") or {}).get("total")
    if not total:
        return False, "no time budget in definition"            # closed (PM 21:28)
    if result.get("latency_ms", 0) > total:
        return False, f"over the time budget ({result.get('latency_ms')} ms)"
    for name in required(defn):
        ok, why = step_ok(result, name)
        if not ok:
            return False, why
    return True, None


def _pearl(m: dict, contract: str, verified: set | None) -> bool:
    return m.get("standing") in PEARL or bool(verified and (m.get("resource_id"), m.get("contract") or contract) in verified)


def static_checks(defn: dict, running: dict, states: dict | None, watch_state: dict | None,
                  watch_problem: str | None, verified: set | None = None) -> list[dict]:
    """The step rules, terms and watch (no call)."""
    from .judge import watch_hold
    checks, pearl_steps, own_steps = [], 0, 0
    for slot in running["slots"]:
        if not slot.get("required", True):
            continue
        name, contract = slot["slot"], slot.get("contract")
        outside = model.live_members(slot, "external")
        pearls = [m for m in outside if _pearl(m, contract, verified)]
        bad = [m.get("resource_id") for m in outside if model.terms_status(m) not in USABLE_TERMS]
        checks.append({"check": f"terms:{name}", "ok": not bad,
                       "why": f"terms not allowed or silent: {bad}" if bad else None})
        own = [m for m in slot.get("chain") or [] if m.get("kind") == "agentcon"
               and (states or {}).get(f"{m.get('agent_id')}|{contract}") in GATE_PASSED]
        if slot.get("own_fallback"):
            own_steps += 1
            ok = bool(own)
            why = None if ok else "own_fallback step without a substitute that passed its gate"
            pearl_steps += bool(pearls)
        else:
            pearl_steps += bool(pearls)
            ok = bool(pearls) and len(outside) >= 2
            why = None if ok else ("no representative pearl" if not pearls else "no outside fallback member")
        checks.append({"check": f"members:{name}", "ok": ok, "why": why})
    if own_steps:
        checks.append({"check": "outside_pearls", "ok": pearl_steps >= MIN_OUTSIDE_PEARL_STEPS,
                       "why": None if pearl_steps >= MIN_OUTSIDE_PEARL_STEPS else
                       f"{pearl_steps} steps with an outside pearl (needs {MIN_OUTSIDE_PEARL_STEPS} with own_fallback steps)"})
    hold = watch_problem or watch_hold(defn["slug"], watch_state, None)
    checks.append({"check": "watch", "ok": not hold, "why": hold})
    return checks


def stage1(defn: dict, caller, values: dict, watch_state: dict | None, runner_cls) -> list[dict]:
    """Step by step, then the whole chain, then a fallback run per required step."""
    rows = []
    for k in range(1, len(defn["slots"]) + 1):
        part = partial(defn, k)
        name = part["slots"][-1]["slot"]
        result = runner_cls(caller, watch_state=watch_state).run(part, values)
        ok, why = step_ok(result, name)
        if not ok and not part["slots"][-1].get("required", True):
            ok, why = True, f"optional step: {why}"
        rows.append(_row({"check": f"join:{k}:{name}", "ok": ok, "why": why}, result))
        if not ok:
            return rows                         # the step to fix: nothing further is joined
    result = runner_cls(caller, watch_state=watch_state).run(defn, values)
    ok, why = run_ok(defn, result)
    rows.append(_row({"check": "whole", "ok": ok, "why": why, "latency_ms": result.get("latency_ms")}, result))
    for slot in defn["slots"]:
        if not slot.get("required", True):
            continue
        state = leaving_out(defn, watch_state or {}, slot["slot"], "lead")
        result = runner_cls(caller, watch_state=state).run(defn, values)
        kinds = ("external", "agentcon") if slot.get("own_fallback") else ("external",)
        ok, why = step_ok(result, slot["slot"], kinds)
        rows.append(_row({"check": f"fallback:{slot['slot']}", "ok": ok, "why": why}, result))
    return rows


def stage2(defn: dict, caller, inputs: list[dict], watch_state: dict | None, runner_cls) -> list[dict]:
    rows = []
    for i, values in enumerate(inputs[:CONNECT_RUNS]):
        result = runner_cls(caller, watch_state=watch_state).run(defn, values)
        ok, why = run_ok(defn, result)
        rows.append(_row({"check": f"connect:{i + 1}", "ok": ok, "why": why, "latency_ms": result.get("latency_ms")},
                         result))
    return rows


def gate(defn: dict, caller, inputs: list[dict], *, watch_state: dict | None, states: dict | None,
         watch_problem: str | None = None, verified: set | None = None, daily: bool = False,
         runner_cls=None) -> dict:
    from .runner import Runner
    from .watch import runtime_definition
    runner_cls = runner_cls or Runner
    body = {"slug": defn["slug"], "version": defn["version"], "digest": model.digest(defn),
            "kind": "daily" if daily else "gate"}
    if daily:
        body["stage2"] = stage2(defn, caller, inputs[:1], watch_state, runner_cls)
        body["ok"] = bool(inputs) and all(r["ok"] for r in body["stage2"])
        return body
    running = runtime_definition(defn, watch_state or {})
    body["static"] = static_checks(defn, running, states, watch_state, watch_problem, verified)
    if len(inputs) < CONNECT_RUNS:
        body["static"].append({"check": "inputs", "ok": False, "why": f"{len(inputs)} tuning inputs (needs {CONNECT_RUNS})"})
    body["stage1"] = stage1(defn, caller, inputs[0], watch_state, runner_cls) if inputs else []
    passed1 = bool(body["stage1"]) and all(r["ok"] for r in body["stage1"])
    body["stage2"] = stage2(defn, caller, inputs, watch_state, runner_cls) if passed1 else []
    body["ok"] = (all(c["ok"] for c in body["static"]) and passed1 and len(body["stage2"]) == CONNECT_RUNS
                  and all(r["ok"] for r in body["stage2"]))
    return body


def with_candidate(defn: dict, watch_state: dict | None, slot_name: str, agent_id: str) -> dict:
    """A copy of the watch state in which the substitute under test counts as approved for its step's role (PM 21:2x,
    agent team 21:2x, 11-18): the running chain keeps a planned AgentValCon member only once it is approved, so a
    substitute taking the gate that approves it was dropped and nobody answered its step. Only this run's copy changes;
    other unapproved substitutes stay out and the watch file is not touched."""
    slot = next(s for s in defn["slots"] if s["slot"] == slot_name)
    member = next((m for m in slot.get("chain") or [] if m.get("kind") == "agentcon" and m.get("agent_id") == agent_id),
                  None)
    if member is None:
        raise ValueError(f"{agent_id} is not an AgentValCon member of step {slot_name}")
    state = copy.deepcopy(watch_state or {})
    pair = [agent_id, model.member_contract(slot, member)]
    if pair not in [list(x) for x in state.get("substitutes") or []]:
        state.setdefault("substitutes", []).append(pair)
    return state


def substitute_gate(defn: dict, slot_name: str, agent_id: str, caller, inputs: list[dict], *,
                    watch_state: dict | None, runner_cls=None) -> dict:
    """A substitute's own gate (PM 19:2x, the agent team uses the same harness): put in its step with every other
    member of the step left out, the whole chain runs on three different inputs and the substitute answers each."""
    from .runner import Runner
    runner_cls = runner_cls or Runner
    state = leaving_out(defn, with_candidate(defn, watch_state, slot_name, agent_id), slot_name, "others", keep=agent_id)
    slot_budget = (defn.get("budget_ms") or {}).get("slot") or (defn.get("budget_ms") or {}).get("total")
    rows = []
    for i, values in enumerate(inputs[:CONNECT_RUNS]):
        result = runner_cls(caller, watch_state=state).run(defn, values)
        # user decision 11-18 (CLAUDE.md): a substitute is approved when, put at the end of its step's chain, it gives
        # an answer in the contract's form within the time budget on three different inputs; its accuracy is not
        # graded. So only its own step is judged here: the other steps' results (a flaky pearl elsewhere, the pearl
        # count of the run) are recorded in "chain" and never fail the substitute (agent team 21:2x, 11-18).
        ok, why = step_ok(result, slot_name, ("agentcon",))
        ms = next((a.get("ms") for a in (result.get("attempts") or {}).get(slot_name) or []
                   if a.get("ok") and a.get("kind") == "agentcon"), None)
        if ok and not slot_budget:
            ok, why = False, "no step budget in definition"       # closed (PM 21:28): nothing to hold the time to
        elif ok and ms is None:
            ok, why = False, f"{slot_name}: no timing for the substitute's answer"
        elif ok and ms > slot_budget:
            ok, why = False, f"{slot_name}: {ms} ms over the step budget {slot_budget} ms"
        rows.append(_row({"check": f"substitute:{i + 1}", "ok": ok, "why": why, "ms": ms,
                          "chain": run_ok(defn, result)[1]}, result))
    contract = next(s["contract"] for s in defn["slots"] if s["slot"] == slot_name)
    return {"slug": defn["slug"], "version": defn["version"], "digest": model.digest(defn), "kind": "substitute",
            "agent_id": agent_id, "slot": slot_name, "contract": contract, "stage2": rows,
            "ok": len(rows) == CONNECT_RUNS and all(r["ok"] for r in rows)}


def record(root: Path, body: dict, now: float | None = None) -> dict:
    line = dict(body, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if now is None else now)))
    path = Path(root) / "connect" / f"{body['slug']}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    return line


def history(root: Path, defn: dict) -> list[dict]:
    """Gate and daily lines of this version and digest, oldest first (substitute lines are apart)."""
    path = Path(root) / "connect" / f"{defn['slug']}.jsonl"
    digest = model.digest(defn)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("version") == defn["version"] and row.get("digest") == digest and row.get("kind") in ("gate", "daily"):
            rows.append(row)
    return sorted(rows, key=lambda r: r.get("at") or "")


def state_of(root: Path, defn: dict, now: float) -> dict:
    """{"passed_at", "last_at", "last_ok", "hold"} for the judge."""
    from .judge import _parse_time
    rows = history(root, defn)
    passed = next((r for r in rows if r.get("kind") == "gate" and r.get("ok")), None)
    last = rows[-1] if rows else None
    hold = None
    if passed is None:
        hold = "connect_not_passed"
    elif not last.get("ok"):
        hold = "connect_failed"
    elif now - (_parse_time(last.get("at")) or 0) > DAILY_STALE_HOURS * 3600:
        hold = "connect_stale"
    return {"passed_at": passed.get("at") if passed else None, "last_at": last.get("at") if last else None,
            "last_ok": last.get("ok") if last else None, "hold": hold}


def relay_run(defn: dict, root: Path, *, daily: bool = False, substitute: tuple | None = None,
              base: str | None = None) -> dict:
    """The gate, one daily run or a substitute gate through the public relay, recorded; outside calls on "gate"."""
    import httpx
    from . import judge, retest, runner
    now = time.time()
    watch_state = retest.gate_watch_state(root)
    _, watch_problem = judge.load_watch_state(root, now)
    inputs = tuning_inputs(root, defn["slug"])
    pacer = retest.RelayPacer()
    with httpx.Client(timeout=12, headers={"User-Agent": "AgentValCon-NecklaceConnect/1.0"}) as client:
        call = runner.budgeted_caller(retest.gateway_caller(client, base or retest.BASE, pacer), "gate",
                                      retest.provider_url)
        if substitute:
            body = substitute_gate(defn, substitute[1], substitute[0], call, inputs, watch_state=watch_state)
        else:
            body = gate(defn, call, inputs, watch_state=watch_state,
                        states=judge.load_substitute_states(Path(root) / "approvals.json"),
                        watch_problem=watch_problem, verified=judge.verified_pearls(), daily=daily)
    return record(root, body)


def daily_run(defn: dict, root: Path) -> dict:
    """The scheduler's one connection run a day for a live necklace."""
    line = relay_run(defn, Path(root), daily=True)
    return {"slug": defn["slug"], "connect": "daily", "ok": line["ok"], "at": line["at"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slug")
    parser.add_argument("--root", type=Path, default=Path("gateway-data/necklaces"))
    parser.add_argument("--daily", action="store_true", help="one connection run (after the necklace is live)")
    parser.add_argument("--substitute", help="a substitute's gate: its agent id (with --slot)")
    parser.add_argument("--slot", help="the step the substitute is put in")
    parser.add_argument("--base", default=None)
    args = parser.parse_args(argv)
    if bool(args.substitute) != bool(args.slot):
        parser.error("--substitute and --slot go together")
    defn = next((d for d in model.load_valid() if d["slug"] == args.slug), None)
    if defn is None:
        print(json.dumps({"error": "unknown_slug"}))
        return 2
    line = relay_run(defn, args.root, daily=args.daily, base=args.base,
                     substitute=(args.substitute, args.slot) if args.substitute else None)
    print(json.dumps(line, ensure_ascii=False))
    return 0 if line["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Value proof of a necklace: one necklace call against an agent calling the member tools itself (plan 3.1, PM 11-15).

Both paths are measured on the same held-out case in the same retest run (the R23 pairing: same case, same day),
from what the run actually did:

- necklace path: 1 call; tokens = characters of the input sent and the necklace answer received, divided by 4;
  time = the run's latency; correct = the case passed the necklace's grader.
- direct path (an agent without the necklace): one call per member call the run made (the agent would have to make
  them too, its retries included); tokens = characters of every member call's arguments and answer, divided by 4;
  time = per stage the slowest slot (slots of one stage called in parallel, a slot's attempts one after another),
  summed over stages; correct = the case passed and every required slot was answered by its lead (an agent without
  the necklace has no fallback chain; when a fallback rescued a slot the direct path counts as wrong).

Two values (PM 11-15 15:11). Conservative (``direct``, the default number on pages): finding the agents and merging
their answers are left out, so it never makes the necklace look better than it is. Full (``direct_full``): the
direct path also pays find_agents per slot, tools/list per member server and one merge pass; the find sizes are
estimates until search and RAG measure them (listed under "estimated"). Numbers are published only for necklaces
that passed the gate (judge).
"""
from __future__ import annotations

import json
import math
import statistics

CHARS_PER_TOKEN = 4
NOT_SENT = ("deadline", "capacity", "budget")       # attempts that never reached a member

# Full value (PM 11-15 15:11): the direct path also has to find the agents and merge their answers, which is the
# saving the user named. Per slot one find_agents call; per member server it calls one tools/list (names and
# schemas); then one merge pass that reads every answer it collected and writes the final answer. The sizes below
# are ESTIMATES until search and RAG measure the find step on 11-16 (then they come from that measurement and the
# "estimated" list shrinks). The merge input is not estimated: it is the answers actually received.
FIND_AGENTS = {"chars": 6000, "ms": 1500, "estimated": True}       # one find_agents answer (5 candidate cards)
TOOLS_LIST = {"chars": 4000, "ms": 600, "estimated": True}         # one tools/list with input schemas


def _tokens(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


def _stages(defn: dict) -> dict[str, int]:
    depth: dict[str, int] = {}
    for slot in defn["slots"]:
        depth[slot["slot"]] = 1 + max((depth.get(d, 0) for d in slot.get("depends_on") or []), default=0)
    return depth


def measure(defn: dict, inputs: dict, result: dict, correct: bool | None) -> dict:
    """The two paths for one run (correct None = not graded: the value is not counted)."""
    out_chars = len(json.dumps(result.get("output") or {}, ensure_ascii=False, default=str))
    in_chars = len(json.dumps(inputs or {}, ensure_ascii=False, default=str))
    calls, chars, per_slot_ms = 0, 0, {}
    for slot, attempts in (result.get("attempts") or {}).items():
        sent = [a for a in attempts if not str(a.get("error_class") or "").startswith(NOT_SENT)]
        calls += len(sent)
        chars += sum(int(a.get("chars_in") or 0) + int(a.get("chars_out") or 0) for a in sent)
        per_slot_ms[slot] = sum(int(a.get("ms") or 0) for a in sent)
    by_stage: dict[int, int] = {}
    for slot, stage in _stages(defn).items():
        by_stage[stage] = max(by_stage.get(stage, 0), per_slot_ms.get(slot, 0))
    required = [s["slot"] for s in defn["slots"] if s.get("required", True)]
    leads = all(((result.get("slots") or {}).get(s) or {}).get("rank") == 1 for s in required)
    direct = {"calls": calls, "tokens": _tokens(chars), "ms": sum(by_stage.values()),
              "correct": None if correct is None else bool(correct and leads)}
    return {"necklace": {"calls": 1, "tokens": _tokens(in_chars + out_chars), "ms": int(result.get("latency_ms") or 0),
                         "correct": correct},
            "direct": direct, "direct_full": _full(defn, result, direct, in_chars, out_chars)}


def _full(defn: dict, result: dict, direct: dict, in_chars: int, out_chars: int) -> dict:
    """The direct path with finding (find_agents per slot, tools/list per member server called) and merging (every
    answer received plus the task in, the final answer out). Same grader verdict as the conservative direct path."""
    slots = len(defn["slots"])
    servers = set()
    answers = 0
    for slot, attempts in (result.get("attempts") or {}).items():
        for a in attempts:
            if str(a.get("error_class") or "").startswith(NOT_SENT):
                continue
            servers.add(a.get("resource_id") or (slot, a.get("rank")))
            answers += int(a.get("chars_out") or 0)
    find_chars = slots * FIND_AGENTS["chars"] + len(servers) * TOOLS_LIST["chars"]
    merge_chars = answers + in_chars + out_chars
    estimated = [name for name, part in (("find_agents", FIND_AGENTS), ("tools_list", TOOLS_LIST)) if part["estimated"]]
    return {"calls": direct["calls"] + slots + len(servers),
            "tokens": direct["tokens"] + _tokens(find_chars + merge_chars),
            # find_agents for the slots of one stage can run together, tools/list per server likewise
            "ms": direct["ms"] + max(_stages(defn).values(), default=0) * (FIND_AGENTS["ms"] + TOOLS_LIST["ms"]),
            "correct": direct["correct"], "estimated": estimated,
            "parts": {"find_tokens": _tokens(find_chars), "merge_tokens": _tokens(merge_chars)}}


def summarize(values: list[dict]) -> dict | None:
    """Medians of calls, tokens and time and the share correct over graded cases, for the judge snapshot."""
    graded = [v for v in values if v and v["necklace"].get("correct") is not None]
    if not graded:
        return None

    def side(name):
        rows = [v[name] for v in graded]
        return {"calls": statistics.median(r["calls"] for r in rows), "tokens": statistics.median(r["tokens"] for r in rows),
                "ms": statistics.median(r["ms"] for r in rows),
                "correct_rate": round(sum(1 for r in rows if r["correct"]) / len(rows), 3)}
    out = {"cases": len(graded), "necklace": side("necklace"), "direct": side("direct"),
           "method": "necklaces.value (median per case; tokens = characters / 4; direct leaves finding and merging out)"}
    full = [v for v in graded if v.get("direct_full")]
    if len(full) == len(graded):
        out["direct_full"] = dict(side("direct_full"), estimated=sorted({e for v in full for e in v["direct_full"]["estimated"]}))
    return out


def comparison(value: dict | None) -> dict | None:
    """The summary in the form growth shows (design note 11-15): with = one necklace call, without = the agent
    calling the same members itself; seconds from medians in ms, accuracy as a share 0-1 (necklace_surface.comparison). None when not measured."""
    if not value or not value.get("cases"):
        return None

    def side(row):
        return {"calls": row["calls"], "tokens": row["tokens"], "seconds": round(row["ms"] / 1000, 1),
                "accuracy": row["correct_rate"]}
    out = {"cases": value["cases"], "measured_at": str(value.get("until") or "")[:10] or None,
           "since": str(value.get("since") or "")[:10] or None,
           "with": side(value["necklace"]), "without": side(value["direct"]), "method": value.get("method")}
    if value.get("direct_full"):            # PM 15:11: the full value next to the conservative one
        out["without_full"] = dict(side(value["direct_full"]), estimated=value["direct_full"].get("estimated") or [])
    return out

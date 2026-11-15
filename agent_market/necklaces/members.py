"""Member standing: verified pearl or provisional member (user instruction 11-15 16:03 via PM d4670360).

"Two verified pearls" is no longer the condition to publish a necklace. A run counts when at least
``min_pearls_answered`` of its steps were answered by a counted member, a verified pearl or a provisional one;
a step without a pearl runs on a provisional member, and when its pearl is verified the pearl leads again and the
provisional member becomes a fallback (``runtime_chain`` orders by standing). The answer gate does not change
(held-out 95% and delta > 0): only the bar for members is lower.

Provisional member (the lowest bar, ``PROVISIONAL``):
- external: active, read-only (readOnlyHint true, destructiveHint not true), terms not prohibiting, and the latest
  test report v2 for that role in the search team's verify snapshot succeeded with a score of at least 70 within the
  last 7 days. The snapshot keeps the latest report per agent and role, so an earlier pass followed by a failure
  does not count (closed).
- own substitute (AgentValCon): approved by ops, or marked "provisional" by ops in approvals.json "substitutes"
  (passed the 30-case held-out gate; ops 11-15). The member keeps substitute_state (approved | provisional).
Verified pearl: the snapshot marks the agent a verified pearl for that role (85+, two successes on different days).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

PROVISIONAL = {"min_score": 70.0, "days": 7}      # one place to change the bar (PM 16:03 item 2)
COUNTED = ("verified_pearl", "provisional")


def _project() -> Path:
    root = os.environ.get("AGENTCON_PROJECT_ROOT")
    return Path(root) if root else Path(".")


def external_standing(snapshot: dict | None, now: float | None = None) -> dict[str, str]:
    """{"<agent id>|<role>": "verified_pearl" | "provisional"} from the verify snapshot; {} when there is none."""
    from .judge import _parse_time
    now = time.time() if now is None else now
    out: dict[str, str] = {}
    for agent_id, agent in ((snapshot or {}).get("agents") or {}).items():
        if not str(agent_id).isdigit():
            continue
        for role in (agent or {}).get("roles") or []:
            if not isinstance(role, dict) or not role.get("role"):
                continue
            key = f"{int(agent_id)}|{role['role']}"
            tested = _parse_time(role.get("tested_at"))
            if role.get("verified_pearl") is True:
                out[key] = "verified_pearl"
            elif (role.get("outcome") == "succeeded" and isinstance(role.get("score"), (int, float))
                  and role["score"] >= PROVISIONAL["min_score"] and tested is not None
                  and now - tested <= PROVISIONAL["days"] * 86400):
                out.setdefault(key, "provisional")
    return out


def load(verify_path: Path | None = None, approvals_path: Path | None = None, now: float | None = None) -> dict:
    """The standing block the watch copies into its state every hour (next to "substitutes")."""
    from .judge import CHECK_PEARL_SNAPSHOT, DEFAULT_ROOT, load_substitute_states, snapshot_problem, verify_snapshot_path
    try:
        snapshot = json.loads(Path(verify_path or verify_snapshot_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = None
    if snapshot is not None and CHECK_PEARL_SNAPSHOT and snapshot_problem(snapshot, now):
        snapshot = None          # stale or another evaluator version: no external member is counted (closed)
    return {"external": external_standing(snapshot, now),
            "own": load_substitute_states(Path(approvals_path or (_project() / DEFAULT_ROOT / "approvals.json"))),
            "snapshot_generated": (snapshot or {}).get("generated"), "rule": dict(PROVISIONAL),
            "verified_rule": (snapshot or {}).get("verified_rule")}


def rules(block: dict | None) -> dict:
    """The two member bars as numbers, for the judge snapshot and the methodology page (growth 11-15): verified from
    the verify snapshot's own verified_rule (scripts/report_v2 PASS_MARK, CONFIRM_DAYS), provisional from PROVISIONAL."""
    verified = (block or {}).get("verified_rule") or {}
    return {"verified_pearl": {"min_score": verified.get("min_score"),
                               "successes_on_different_days": verified.get("successes_on_different_days")},
            "provisional": {"min_score": PROVISIONAL["min_score"], "within_days": PROVISIONAL["days"],
                            "reports": 1, "own_substitute": "passed a 30-case held-out gate"}}


def read_only(member: dict) -> bool:
    return member.get("read_only_hint") is True and member.get("destructive_hint") is not True


def standing(member: dict, contract: str, block: dict | None) -> str | None:
    """verified_pearl, provisional or None for one chain member of a slot with this contract."""
    from . import model
    if block is None:
        return None
    if member.get("state", "active") != "active" or model.terms_status(member) == "prohibits":
        return None
    if member.get("kind") == "agentcon":        # our own substitutes are never official pearls
        return "provisional" if member.get("substitute_state") in ("approved", "provisional") else None
    if not read_only(member) or not isinstance(member.get("resource_id"), int):
        return None
    return (block.get("external") or {}).get(f"{member['resource_id']}|{contract}")


def counted(member: dict) -> bool:
    """For the runner: a member counted toward min_pearls_answered. Without a standing block (an old watch state)
    the definition's own pearl flag is used, as before."""
    if "standing" in member:
        return member["standing"] in COUNTED
    return bool(member.get("pearl"))


def upgrades(definitions: list[dict], block: dict, roles: dict | None = None) -> list[dict]:
    """Slots a newly verified pearl can lead (PM 16:03 item 5): a slot whose best member is provisional while a
    verified pearl for its role exists, in the chain (it leads at once by standing) or only in the role groups
    (a definition change and a new gate are needed)."""
    out = []
    for defn in definitions:
        if defn.get("status") == "retired":
            continue
        for slot in defn["slots"]:
            ranks = [(m, standing(m, slot["contract"], block)) for m in slot["chain"] if m.get("kind") == "external"]
            pearls = [m for m, s in ranks if s == "verified_pearl"]
            provisional = [m for m, s in ranks if s == "provisional"]
            first = next((m for m in slot["chain"] if m.get("kind") == "external" and m.get("state", "active") == "active"),
                         None)
            if pearls and first is not None and first not in pearls:
                out.append({"slug": defn["slug"], "slot": slot["slot"], "contract": slot["contract"],
                            "lead_now": first.get("resource_id"), "pearl": pearls[0]["resource_id"], "in_chain": True})
            elif not pearls and provisional:
                final = ((roles or {}).get(slot["contract"]) or {}).get("final_pearl")
                if final and final not in {m.get("resource_id") for m in slot["chain"]}:
                    out.append({"slug": defn["slug"], "slot": slot["slot"], "contract": slot["contract"],
                                "lead_now": provisional[0].get("resource_id"), "pearl": final, "in_chain": False})
    return out

"""Necklace launch gate tool (deploy/NECKLACE_GATE.md). Built by the workflow team; ops runs it and records verdicts
(the team that builds a necklace does not pass it itself, PM 11-15).

    .venv/bin/python -m scripts.necklace_gate check <slug> [--base https://agentconcierge.biz]

``check`` (PM 11-15 10:31): before a member may hold a seat in a slot it must be callable through our public relay, the
path the gate rounds and the daily retests use; passing a direct role test is not enough. For every external member of
every slot it sends an MCP ``initialize`` and one read-only ``tools/call`` with the definition's public
``probe_input`` to /api/gateway/mcp/<id> (X-Agentcon-QA: necklace_gate, through the shared
provider ledger as 'gate') and records whether the relay admitted it and, when not, the denial code and reference the
relay returns (X-Execution-Error, X-Execution-Reference; ops resolves the reference in the server log). It also lists
which leads are verified pearls (verify snapshot) and which AgentValCon substitutes ops approved, and computes how many
verified pearls can answer in one run when every relay-denied member is left out (min_pearls_answered).

The rounds, grading, judging, approve and revoke follow (gate document sections 3-6).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agent_market.necklaces import judge, model
from agent_market.necklaces.retest import BASE, QA_GATE, provider_url
from agent_market.necklaces.runner import render
from agent_market.necklaces.watch import runtime_chain

OUT = Path("logs/ops/necklace-gate")
SEATED = "seat_eligible"


class OurCapacity(Exception):
    """The edge answered CAPACITY_EXCEEDED twice: our side was full, the member is not judged (PM 11-15 10:40)."""


def _post(client, url, method, params, sleep=time.sleep):
    """One relay request inside our own concurrency cap (2 of the edge's 4 slots), retried once when the edge is full."""
    from agent_market.necklaces.retest import _RELAY_SLOTS, capacity_exceeded
    for attempt in (1, 2):
        with _RELAY_SLOTS:
            response = client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                   headers={"Content-Type": "application/json", "Accept": "application/json",
                                            "MCP-Protocol-Version": "2025-06-18", "X-Agentcon-QA": QA_GATE},
                                   timeout=15)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not capacity_exceeded(response.status_code, response.headers, body if isinstance(body, dict) else {}):
            return response
        if attempt == 1:
            sleep(0.3)
    raise OurCapacity(method)


def _denial(response) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    result = body.get("result") if isinstance(body, dict) else None
    message = (error or {}).get("message") or (body or {}).get("detail") if isinstance(body, dict) else ""
    if isinstance(result, dict) and result.get("isError"):
        message = " ".join(p.get("text", "") for p in result.get("content") or [] if isinstance(p, dict))
    return {"http_status": response.status_code,
            "error_code": response.headers.get("X-Execution-Error") or (error or {}).get("code")
            or ("TOOL_ERROR" if isinstance(result, dict) and result.get("isError") else None),
            "reference": response.headers.get("X-Execution-Reference"), "message": str(message or "")[:300]}


def _note(note, target, response):
    """Tell the shared ledger only what the provider said. Our relay's HTTP 429 is our own pace (10 agent requests a
    minute per address) and must never pause a provider for every system (11-14 05:11 and 11-15 11:42 incidents); a
    provider's pause comes back as a JSON-RPC error with retry_after, as in necklaces.retest.gateway_caller."""
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = (body or {}).get("error") if isinstance(body, dict) else None
    detail = (error or {}).get("data") if isinstance((error or {}).get("data"), dict) else {}
    if detail.get("retry_after") or "pause" in str((error or {}).get("message", "")).lower():
        note(target, "gate", 429, evidence={"origin": "provider_rpc", "retry_after": detail.get("retry_after"),
                                            "message": str((error or {}).get("message") or "")})


def _answered(response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    result = body.get("result") if isinstance(body, dict) else None
    return 200 <= response.status_code < 300 and isinstance(result, dict) and not result.get("isError")


_PACER = None


def _pace(pacer, requests: int):
    """Our relay allows 10 agent requests a minute per address; the check keeps under it (RelayPacer, 9 a minute)
    so its own pace is never read as a member's answer (11-15 11:41: five members got our 429 and were misread)."""
    global _PACER
    if pacer is None:
        from agent_market.necklaces.retest import RelayPacer
        _PACER = _PACER or RelayPacer()
        pacer = _PACER
    pacer.wait_for(requests)
    return pacer


def _state(response) -> str:
    """denied = our execution policy refused the tool (403); throttled = our relay's own pace (429); failed = the call
    ran and the provider did not give an answer (error result, unconfirmed outcome, 5xx)."""
    if response.status_code == 403:
        return "denied"
    if response.status_code == 429:
        return "throttled"
    return "failed"


def probe(client, base: str, member: dict, args: dict | None = None, reserve=None, note=None, pacer=None) -> dict:
    """The relay's answer for one member: initialize, then (with probe arguments) one read-only tools/call, because the
    relay admits a connection and refuses the tool later (11-15: 58997 passed initialize, every call got 403)."""
    url = f"{base}/api/gateway/mcp/{member['resource_id']}"
    if reserve is None or note is None:
        from agent_market.provider_budget import note as _ledger_note, reserve as _reserve
        reserve, note = reserve or _reserve, note or _ledger_note
    target = provider_url(member)
    ok, why = reserve(target, "gate")
    if not ok:
        return {"relay": "not_checked", "why": f"provider budget: {why}"}
    started = time.monotonic()
    empty = {"http_status": None, "error_code": None, "reference": None, "message": ""}   # filled when the relay refuses
    pacer = _pace(pacer, 2 if args is not None else 1)
    try:
        first = _post(client, url, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                  "clientInfo": {"name": "necklace-gate", "version": "1"}})
        _note(note, target, first)
        if not _answered(first):
            return {"relay": _state(first), "stage": "initialize", **_denial(first)}
        if args is None:
            return {"relay": "admitted", "stage": "initialize", "tools_call": "not_checked", **empty}
        call = _post(client, url, "tools/call", {"name": member["tool"], "arguments": args})
    except OurCapacity as exc:
        return {"relay": "our_capacity", "stage": str(exc), **dict(empty, error_code="CAPACITY_EXCEEDED")}
    _note(note, target, call)
    ms = int((time.monotonic() - started) * 1000)
    if not _answered(call):
        return {"relay": _state(call), "stage": "tools/call", "ms": ms, **_denial(call)}
    return {"relay": "admitted", "stage": "tools/call", "ms": ms, **empty, "http_status": call.status_code}


FINGERPRINTS = Path("gateway-data/fingerprints/pearls.json")


def check(defn: dict, client, base: str = BASE, verified=None, substitutes=None, probe_fn=probe, prints=None,
          now=None) -> dict:
    from agent_market.necklaces.watch import PASSING_PRINTS, fingerprint_status, load_json
    verified = judge.verified_pearls() if verified is None else verified
    prints = load_json(FINGERPRINTS, {}) if prints is None else prints
    state = {"substitutes": judge.load_substitutes(Path("gateway-data/necklaces/approvals.json"))
             if substitutes is None else substitutes}
    slots, seated_pearl_slots, problems = [], [], model.validate(defn)
    if verified is None:     # PM 13:0x: no snapshot, older than 72 hours or another evaluator version
        problems.append("verified pearls not judged (verify snapshot missing, older than 72 hours or graded with "
                        "another evaluator version)")
    sample = defn.get("probe_input")          # a public example input, staged values as slot.<slot>.<field>
    for slot in defn["slots"]:
        chain = runtime_chain(slot, defn["slug"], state)
        rows = []
        for rank, member in enumerate(chain, start=1):
            row = {"rank": rank, "kind": member["kind"], "tool": member["tool"],
                   "id": member.get("resource_id") or member.get("agent_id")}
            if member["kind"] == "external":
                row["verified_pearl"] = bool(verified) and (member["resource_id"], slot["contract"]) in verified
                args = render(member.get("input_map") or {}, sample) if sample else None
                row.update(probe_fn(client, base, member, args))
                # the same closed fingerprint verdict as the watch (PM 12:0x): unknown or stale is not judged
                row["fingerprint"] = fingerprint_status(prints, member["resource_id"], now)
                row[SEATED] = row["relay"] == "admitted" and row.get("tools_call") != "not_checked" \
                    and row["fingerprint"] in PASSING_PRINTS
                if row["relay"] in ("our_capacity", "throttled"):
                    problems.append(f"slot {slot['slot']}: member {row['id']} not judged ({row['relay']}, check again)")
                if row["fingerprint"] in ("unknown", "stale"):
                    problems.append(f"slot {slot['slot']}: member {row['id']} not judged (fingerprint {row['fingerprint']})")
                elif row["fingerprint"] not in PASSING_PRINTS:
                    problems.append(f"slot {slot['slot']}: member {row['id']} fingerprint {row['fingerprint']}")
            else:
                row["substitute_approved"] = bool(member.get("substitute_approved"))
                row[SEATED] = True                       # runs in-process on our host, not through the relay
            rows.append(row)
        seated = [r for r in rows if r[SEATED]]
        lead = next((r for r in seated if r["kind"] == "external"), None)
        if lead and lead.get("verified_pearl"):
            seated_pearl_slots.append(slot["slot"])
        slots.append({"slot": slot["slot"], "contract": slot["contract"], "required": slot.get("required", True),
                      "depends_on": slot.get("depends_on"), "requires_input": slot.get("requires_input"),
                      "members": rows, "seated_lead": lead["id"] if lead else None,
                      "seated_lead_is_pearl": bool(lead and lead.get("verified_pearl")),
                      "usable": bool(seated)})
    need = defn.get("min_pearls_answered") or 2
    always = [s["slot"] for s in slots if s["slot"] in seated_pearl_slots and not s.get("requires_input")]
    if any(s["required"] and not s["usable"] for s in slots):
        problems.append("a required slot has no member that can run")
    return {"slug": defn["slug"], "version": defn["version"], "definition_digest": model.digest(defn),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "base": base, "slots": slots,
            "pearls": {"seated_pearl_slots": seated_pearl_slots, "in_every_run": always, "needed_per_run": need,
                       "met_in_every_run": len(always) >= need,
                       "met_when_optional_inputs_given": len(seated_pearl_slots) >= need},
            "problems": problems, "ok": not problems and len(always) >= need}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("check", help="relay admission per member and pearl seats (no answer-set calls)")
    one.add_argument("slug")
    one.add_argument("--base", default=BASE)
    args = parser.parse_args(argv)
    defn = next((d for d in model.load_valid() if d["slug"] == args.slug), None)
    if defn is None:
        parser.error(f"unknown necklace {args.slug}")
    import httpx
    with httpx.Client(headers={"User-Agent": "AgentValCon-NecklaceGate/1.0"}) as client:
        result = check(defn, client, args.base)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"check-{args.slug}-v{defn['version']}-{time.strftime('%Y%m%d-%H%M')}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"file": str(path), "ok": result["ok"], "pearls": result["pearls"],
                      "denied": [(s["slot"], m["id"], m.get("error_code"), m.get("reference")) for s in result["slots"]
                                 for m in s["members"] if m.get("relay") == "denied"]}, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

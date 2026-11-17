"""The one necklace run entry for every public surface (MCP necklace_<slug>, A2A necklace-<slug>,
web run button): ``necklace_surface.RUN = service.run_for_surface``.

The surface has already checked that the necklace may be offered (live, gate, two pearls, Δ > 0,
retest within 48 hours, fallback rules). This entry adds what belongs to the runner:

- the snapshot entry must match the definition the ops gate approved (version and digest)
- consent: a web run must carry ``necklace_notice=necklace-v1`` (the checkbox, never stored);
  MCP and A2A callers get the same sentence in the tool and skill descriptions
- input: one JSON object that matches the necklace input schema; values that look like
  credentials are refused (the workflow engine's ``sensitive`` check), nothing is sent
- members run through the registered-agent path (execution permission, public endpoint,
  no paid tools, argument validation) or, for AgentValCon fallbacks, in-process
- a body-free run event is written; without request metadata the run never counts as external
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from pathlib import Path

from . import limits, model, runner
from .judge import DEFAULT_ROOT

NOTICE = "necklace-v1"
# Value shapes of common credentials. workflows.sensitive() checks key names, Bearer/Basic and local
# paths but not token values, so a necklace input is also checked here (nothing is sent on a match).
TOKEN = re.compile(r"(?:\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-[A-Za-z0-9_-]{16,}"
                   r"|\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}|\bxox[abpors]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b"
                   r"|\bAIza[0-9A-Za-z_-]{30,}|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|-----BEGIN [A-Z ]*PRIVATE KEY"
                   r"|\b0x[0-9a-fA-F]{64}\b)")
SOURCES = ("mcp", "a2a", "web")


class Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _finite(value, depth=0) -> bool:
    """JSON numbers only: NaN and the infinities are refused anywhere in the input."""
    if depth > 32:
        return False
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _finite(v, depth + 1) for k, v in value.items())
    if isinstance(value, list):
        return all(_finite(v, depth + 1) for v in value)
    return value is None or isinstance(value, (str, int, bool))


INTEGER = re.compile(r"-?\d{1,18}")
NUMBER = re.compile(r"-?(\d{1,18}(\.\d{1,12})?|\.\d{1,12})([eE][-+]?\d{1,3})?")


def form_values(schema: dict, values: dict) -> dict:
    """A web form sends every field as text (PM 11-15 11:4x): turn text into the schema's integer, number or boolean
    before the JSON Schema check. Text that is not a clean value of that type stays text, so the check refuses it."""
    props = (schema or {}).get("properties") or {}
    out = dict(values)
    for key, value in values.items():
        kind = (props.get(key) or {}).get("type")
        if not isinstance(value, str):
            continue
        text = value.strip()
        if kind == "integer" and INTEGER.fullmatch(text):
            out[key] = int(text)
        elif kind == "number" and NUMBER.fullmatch(text):
            number = float(text)
            if math.isfinite(number):
                out[key] = int(number) if number.is_integer() and "." not in text and "e" not in text.lower() else number
        elif kind == "boolean" and text.lower() in ("true", "on", "1", "yes", "false", "off", "0", "no"):
            out[key] = text.lower() in ("true", "on", "1", "yes")
    return out


def check_input(schema: dict, values) -> dict:
    """Validate with the definition's JSON Schema 2020-12 validator (checked and cached when the
    definition loads, PM F11). A refused input never reaches a member: run_for_surface checks this
    before the runner exists."""
    if not isinstance(values, dict) or not _finite(values):
        raise Refused("invalid_input")
    try:
        validator = model.input_validator(schema)
    except Exception:
        raise Refused("invalid_input") from None
    if next(validator.iter_errors(values), None) is not None:
        raise Refused("invalid_input")
    return values


def definition_for(entry: dict, definitions_dir: Path | None = None) -> dict:
    definitions_dir = definitions_root() if definitions_dir is None else definitions_dir
    defn = next((d for d in model.load_valid(definitions_dir) if d["slug"] == entry.get("slug")), None)
    if defn is None:
        raise Refused("not_found")
    if entry.get("version") != defn["version"] or entry.get("definition_digest") != model.digest(defn):
        raise Refused("definition_changed")
    return defn


OUR_CAPACITY = "our_capacity"
DETAILS = ("full", "brief")            # response detail (PM 11-17): full is the default, brief is necklaces/brief.py
# Our side was full: the edge's in-flight limit (CAPACITY_EXCEEDED, after 3be2317c only when the origin could not take
# it either), the runner's process-wide cap (capacity) or the relay cap of our own tests (our_capacity).
# PM 11-16: every refusal of ours (refusals.is_ours: caps, quota, ledger, pace), not only the capacity codes


def capacity_failure(result: dict) -> bool:
    """True when a required step failed and every failed call of the failing steps hit our own capacity."""
    failed = [name for name, slot in result.get("slots", {}).items() if slot.get("failed")]
    attempts = [a for name in failed for a in result.get("attempts", {}).get(name, []) if not a.get("ok")]
    codes = [a.get("error_class") for a in attempts if a.get("error_class") not in ("deadline", "not_needed")]
    from .refusals import is_ours
    return bool(codes) and all(is_ours(code) for code in codes)


def connection_failure(result: dict) -> bool:
    """True when a failed required step never called a member because a value from an earlier step was empty."""
    failed = [name for name, slot in result.get("slots", {}).items() if slot.get("failed")]
    return any(a.get("error_class") == "connection_empty"
               for name in failed for a in result.get("attempts", {}).get(name, []))


def data_root() -> Path:
    """Run events live next to the snapshot the surface reads: <AGENTCON_PROJECT_ROOT>/gateway-data/necklaces
    (a release runs from its own folder, so a relative path would scatter events per release)."""
    project = os.environ.get("AGENTCON_PROJECT_ROOT")
    return Path(project) / "gateway-data" / "necklaces" if project else DEFAULT_ROOT


def definitions_root() -> Path:
    """The reviewed definitions shipped with the code; NECKLACE_DEFINITIONS_DIR only for isolated tests."""
    return Path(os.environ.get("NECKLACE_DEFINITIONS_DIR") or model.DEFINITIONS)


def note_refusal(root, slug, code: str, surface: str):
    """One line per run refused before anything was sent (PM 11-17 08:5x: rate_limited per day decides whether the
    run limits or MAX_INFLIGHT go up). Kept in refusals/<date>.jsonl, apart from runs/, so run counts do not change.
    No client, address or input is written."""
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        path = Path(data_root() if root is None else root) / "refusals" / (at[:10].replace("-", "") + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": at, "slug": slug, "code": code, "surface": surface}, sort_keys=True) + "\n")
    except OSError:
        pass   # counting never changes the answer


OWN_SOURCE = "agentcon:AgentValCon agent"


def public_output(output):
    """The run output as the public sees it (growth 11-18): our own members are named "AgentValCon agent", never by
    their internal agent id or avc: resource id; outside members keep their catalog id. Graders and round records read
    the runner's result, not this."""
    if not isinstance(output, dict):
        return output
    out = {}
    for name, slot in output.items():
        if isinstance(slot, dict) and isinstance(slot.get("sources"), list):
            slot = dict(slot, sources=[OWN_SOURCE if isinstance(s, str) and s.startswith("agentcon:") else s
                                       for s in slot["sources"]])
        out[name] = slot
    return out


def run_for_surface(front, entry: dict, arguments, source: str, meta: dict | None = None, *,
                    root: Path | None = None, definitions_dir: Path | None = None,
                    caller=None, sensitive=None, limiter=None, cache=None, domains=None, quota_budget=None) -> dict:
    """``meta`` = {ip, ua, qa, principal, internal_ips} of the request; without it the run counts as internal.

    Wired at app assembly: ``necklace_surface.RUN = service.run_for_surface`` (PM F05, 11-14)."""
    root = data_root() if root is None else Path(root)
    definitions_dir = definitions_root() if definitions_dir is None else Path(definitions_dir)
    try:
        if source not in SOURCES:
            raise Refused("invalid_source")
        defn = definition_for(entry, definitions_dir)
        values = dict(arguments) if isinstance(arguments, dict) else None
        if values is None:
            raise Refused("invalid_input")
        notice = values.pop("necklace_notice", None)
        # PM 11-17: a response option, not a necklace input (the definition and its digest stay as they are)
        detail = values.pop("detail", None) or "full"
        if detail not in DETAILS:
            raise Refused("invalid_input")
        if source == "web" and notice != NOTICE:
            raise Refused("consent_required")
        if source == "web":
            values = form_values(defn["input_schema"], values)
        check_input(defn["input_schema"], values)
        for key, allowed in (defn.get("scope") or {}).items():       # PM 11-15: out of scope -> notice, no call
            if values.get(key) not in allowed:
                return {"ok": False, "output": None, "stages": {}, "error_code": "out_of_scope",
                        "notice": defn.get("scope_notice")}
        if sensitive is None:
            from ..workflows import sensitive
        if sensitive(values) or TOKEN.search(json.dumps(values, ensure_ascii=False)):
            raise Refused("sensitive_input")
        # PM R21: per client, per necklace and total run limits before anything is sent
        if defn.get("status") == "preview":         # user 11-18 via PM: a preview runs under lower caps
            (limits.LIMITER if limiter is None else limiter).admit(defn["slug"], (meta or {}).get("ip"), preview=True)
        else:
            (limits.LIMITER if limiter is None else limiter).admit(defn["slug"], (meta or {}).get("ip"))
    except (Refused, limits.Refused) as exc:
        wait = getattr(exc, "retry_after", None)
        if exc.code == "rate_limited":
            note_refusal(root, entry.get("slug"), exc.code, source)
        return {"ok": False, "output": None, "stages": {}, "error_code": exc.code,
                **({"retry_after_s": wait} if wait else {})}
    cache = limits.CACHE if cache is None else cache
    cache_key = cache.key(defn["slug"], defn["version"], model.digest(defn), values)
    cached = cache.get(cache_key)
    try:
        watch_state = json.loads((Path(root) / "watch" / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        watch_state = {}
    if cached is not None:
        result = dict(cached, latency_ms=0, cached=True)
    else:
        if caller is None:
            caller = runner.engine_caller(front.workflows)
        caller = (limits.DOMAINS if domains is None else domains).wrap(caller)
        caller = runner.live_quota_caller(caller, quota_budget)     # PM 17:24: 80% of a provider's published day
        result = runner.Runner(caller, watch_state=watch_state).run(defn, values)
        result["ran_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())   # when the members answered
        cache.put(cache_key, result)
    if meta is None:
        source_class, origin = runner.classify_source(None)
    else:
        source_class, origin = runner.classify_source(
            "public", ip=meta.get("ip"), ua=meta.get("ua"), qa=meta.get("qa"), principal=meta.get("principal"),
            internal_ips=meta.get("internal_ips") or frozenset(),
            internal_principals=meta.get("internal_principals") or frozenset())
    event = runner.run_event(result, source_class, origin)
    event["surface"] = source
    event["run_id"] = uuid.uuid4().hex      # one run counts once in the north star, however often a file is read
    if not result["ok"] and capacity_failure(result):
        event["our_capacity"] = True     # the north star counts this apart from the members' failures
    if not result["ok"] and connection_failure(result):
        event["connection_empty"] = True  # PM 17:28: a required value from an earlier step was empty (ours)
    if result.get("cached"):
        event["cached"] = True          # served from the short result cache: no member was called
    capacity = sum(1 for tries in (result.get("attempts") or {}).values() for a in tries
                   if isinstance(a, dict) and a.get("error") == "capacity")
    if capacity:
        event["capacity_attempts"] = capacity   # PM 11-17 08:5x: member calls not sent, MAX_INFLIGHT was full
    try:
        runner.append_event(root, event)
    except OSError:
        pass   # the answer still goes back; a missing event only lowers the count
    error_code = None if result["ok"] else "slot_failed:" + str(result["failed_slot"])
    if not result["ok"] and capacity_failure(result):
        error_code = OUR_CAPACITY           # our side was full; not the members' failure (PM 11-15 11:22)
    output = public_output(result["output"])         # our own members named "AgentValCon agent" (growth 11-18)
    if detail == "brief" and isinstance(output, dict):
        from .brief import brief
        output = brief(output)                      # the same facts and links, fewer tokens (PM 11-17)
    return {"ok": result["ok"], "output": output, "detail": detail,
            "stages": {name: s["stage"] for name, s in result["slots"].items()},
            "statuses": {name: s["status"] for name, s in result["slots"].items()},
            "cached": bool(result.get("cached")),
            "ran_at": result.get("ran_at"),           # a cached answer keeps the time of the run that produced it
            "error_code": error_code}

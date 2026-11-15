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
# Our side was full: the edge's in-flight limit (CAPACITY_EXCEEDED, after 3be2317c only when the origin could not take
# it either), the runner's process-wide cap (capacity) or the relay cap of our own tests (our_capacity).
CAPACITY_CODES = ("CAPACITY_EXCEEDED", "capacity", "our_capacity")


def capacity_failure(result: dict) -> bool:
    """True when a required step failed and every failed call of the failing steps hit our own capacity."""
    failed = [name for name, slot in result.get("slots", {}).items() if slot.get("failed")]
    attempts = [a for name in failed for a in result.get("attempts", {}).get(name, []) if not a.get("ok")]
    codes = [a.get("error_class") for a in attempts if a.get("error_class") not in ("deadline", "not_needed")]
    return bool(codes) and all(code in CAPACITY_CODES for code in codes)


def data_root() -> Path:
    """Run events live next to the snapshot the surface reads: <AGENTCON_PROJECT_ROOT>/gateway-data/necklaces
    (a release runs from its own folder, so a relative path would scatter events per release)."""
    project = os.environ.get("AGENTCON_PROJECT_ROOT")
    return Path(project) / "gateway-data" / "necklaces" if project else DEFAULT_ROOT


def definitions_root() -> Path:
    """The reviewed definitions shipped with the code; NECKLACE_DEFINITIONS_DIR only for isolated tests."""
    return Path(os.environ.get("NECKLACE_DEFINITIONS_DIR") or model.DEFINITIONS)


def run_for_surface(front, entry: dict, arguments, source: str, meta: dict | None = None, *,
                    root: Path | None = None, definitions_dir: Path | None = None,
                    caller=None, sensitive=None, limiter=None, cache=None, domains=None) -> dict:
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
        if source == "web" and notice != NOTICE:
            raise Refused("consent_required")
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
        (limits.LIMITER if limiter is None else limiter).admit(defn["slug"], (meta or {}).get("ip"))
    except (Refused, limits.Refused) as exc:
        return {"ok": False, "output": None, "stages": {}, "error_code": exc.code}
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
    if not result["ok"] and capacity_failure(result):
        event["our_capacity"] = True     # the north star counts this apart from the members' failures
    if result.get("cached"):
        event["cached"] = True          # served from the short result cache: no member was called
    try:
        runner.append_event(root, event)
    except OSError:
        pass   # the answer still goes back; a missing event only lowers the count
    error_code = None if result["ok"] else "slot_failed:" + str(result["failed_slot"])
    if not result["ok"] and capacity_failure(result):
        error_code = OUR_CAPACITY           # our side was full; not the members' failure (PM 11-15 11:22)
    return {"ok": result["ok"], "output": result["output"],
            "stages": {name: s["stage"] for name, s in result["slots"].items()},
            "statuses": {name: s["status"] for name, s in result["slots"].items()},
            "cached": bool(result.get("cached")),
            "ran_at": result.get("ran_at"),           # a cached answer keeps the time of the run that produced it
            "error_code": error_code}

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
import re
from pathlib import Path

from . import model, runner
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


def check_input(schema: dict, values) -> dict:
    """The subset of JSON Schema the necklace inputs use: object, required, additionalProperties,
    string (enum, pattern, minLength, maxLength), integer and number."""
    if not isinstance(values, dict):
        raise Refused("invalid_input")
    props = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if values.get(key) in (None, ""):
            raise Refused("invalid_input")
    if schema.get("additionalProperties") is False and set(values) - set(props):
        raise Refused("invalid_input")
    for key, value in values.items():
        rule = props.get(key) or {}
        kind = rule.get("type")
        if kind == "string":
            if not isinstance(value, str):
                raise Refused("invalid_input")
            if "enum" in rule and value not in rule["enum"]:
                raise Refused("invalid_input")
            if "pattern" in rule and not re.search(rule["pattern"], value):
                raise Refused("invalid_input")
            if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", 10_000):
                raise Refused("invalid_input")
        elif kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise Refused("invalid_input")
        elif kind == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            raise Refused("invalid_input")
    return values


def definition_for(entry: dict, definitions_dir: Path = model.DEFINITIONS) -> dict:
    defn = next((d for d in model.load_valid(definitions_dir) if d["slug"] == entry.get("slug")), None)
    if defn is None:
        raise Refused("not_found")
    if entry.get("version") != defn["version"] or entry.get("definition_digest") != model.digest(defn):
        raise Refused("definition_changed")
    return defn


def run_for_surface(front, entry: dict, arguments, source: str, meta: dict | None = None, *,
                    root: Path = DEFAULT_ROOT, definitions_dir: Path = model.DEFINITIONS,
                    caller=None, sensitive=None) -> dict:
    """``meta`` = {ip, ua, qa, principal} of the request; without it the run counts as internal."""
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
        if sensitive is None:
            from ..workflows import sensitive
        if sensitive(values) or TOKEN.search(json.dumps(values, ensure_ascii=False)):
            raise Refused("sensitive_input")
    except Refused as exc:
        return {"ok": False, "output": None, "stages": {}, "error_code": exc.code}
    try:
        watch_state = json.loads((Path(root) / "watch" / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        watch_state = {}
    if caller is None:
        caller = runner.engine_caller(front.workflows)
    result = runner.Runner(caller, watch_state=watch_state).run(defn, values)
    if meta is None:
        source_class, origin = runner.classify_source(None)
    else:
        source_class, origin = runner.classify_source(
            "public", ip=meta.get("ip"), ua=meta.get("ua"), qa=meta.get("qa"), principal=meta.get("principal"),
            internal_ips=meta.get("internal_ips") or frozenset(),
            internal_principals=meta.get("internal_principals") or frozenset())
    event = runner.run_event(result, source_class, origin)
    event["surface"] = source
    try:
        runner.append_event(root, event)
    except OSError:
        pass   # the answer still goes back; a missing event only lowers the count
    return {"ok": result["ok"], "output": result["output"],
            "stages": {name: s["stage"] for name, s in result["slots"].items()},
            "error_code": None if result["ok"] else "slot_failed:" + str(result["failed_slot"])}

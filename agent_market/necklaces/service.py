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
                    caller=None, sensitive=None) -> dict:
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
            "statuses": {name: s["status"] for name, s in result["slots"].items()},
            "error_code": None if result["ok"] else "slot_failed:" + str(result["failed_slot"])}

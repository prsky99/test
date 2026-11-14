"""Necklace definitions: loading, structural validation, readiness gaps and digest.

Rules come from reports/necklace-production-2026-11-14/process.md and the
PM decisions of 2026-11-14:

- a slug is a task name, ``^[a-z][a-z0-9]*(-[a-z0-9]+)*$``, 3 to 40 characters
- every slot has an ordered chain: external members first, then at most two
  AgentValCon fallback members at the end
- every external member must carry an explicit ``readOnlyHint=true``, must not be
  destructive, and its tool name must not look like an action or payment verb
- a member without an explicit idempotent hint cannot be marked ``resend_safe``
- within one necklace a failure domain (registrable domain) may own the primary
  member of at most one slot
- a necklace has at least two required slots, or one slot fanning out to two
  or more pearls
- the latency budget for a complex answer is 5 seconds

``validate`` returns structural errors (a definition with errors must not be
used). ``readiness`` returns qualification gaps (a valid definition can still be
short of members before it may enter the gold-set trial).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..collector.usage import _DENY

ROOT = Path(__file__).resolve().parent
DEFINITIONS = ROOT / "definitions"
CONTRACTS = ROOT / "contracts"

SLUG = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
SLOT_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
STATUSES = ("candidate", "qualifying", "trial", "live", "held", "retired")
KINDS = ("external", "agentcon")
MEMBER_STATES = ("active", "pending_test", "planned", "removed")
MAX_AGENTCON = 2
MAX_EXTERNAL = 6
MAX_TOTAL_MS = 5000
# PM decision 11-14 (agent team survey): no keyless free source allows commercial redistribution, so these
# roles get no AgentValCon fallback; they may only be optional slots with at least two external members.
NO_FALLBACK_ROLES = ("crypto.price.v1", "ip.lookup.v1", "stock.quote.v1")
# Fields that describe where a definition is in its lifecycle. They do not change
# what runs, so they are left out of the digest that the ops approval binds to.
NON_MATERIAL = ("status", "notes", "replaced_by")


class DefinitionError(ValueError):
    pass


def load(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_all(directory: Path | str = DEFINITIONS) -> list[dict]:
    return [load(p) for p in sorted(Path(directory).glob("*.json"))]


def contract_ids(directory: Path | str = CONTRACTS) -> list[str]:
    """The canonical role names (PM 11-14): every role used anywhere must be one of these files."""
    return sorted(p.stem for p in Path(directory).glob("*.json"))


def load_contract(contract_id: str, directory: Path | str = CONTRACTS) -> dict | None:
    path = Path(directory) / f"{contract_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def digest(defn: dict) -> str:
    """sha256 over the canonical JSON of everything that changes what runs."""
    material = {k: v for k, v in defn.items() if k not in NON_MATERIAL}
    text = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def live_members(slot: dict, kind: str | None = None) -> list[dict]:
    return [m for m in slot.get("chain") or []
            if m.get("state", "active") == "active" and (kind is None or m.get("kind") == kind)]


def primary(slot: dict) -> dict | None:
    externals = live_members(slot, "external")
    return externals[0] if externals else None


def is_parallel(defn: dict) -> bool:
    """True when slots have no data dependency on each other (all read the necklace input)."""
    return all(not slot.get("depends_on") for slot in defn.get("slots") or [])


def _member_errors(slot_id: str, idx: int, m: dict) -> list[str]:
    where = f"slot {slot_id} member {idx}"
    errors = []
    kind = m.get("kind")
    if kind not in KINDS:
        errors.append(f"{where}: kind must be one of {KINDS}")
    if m.get("state", "active") not in MEMBER_STATES:
        errors.append(f"{where}: state must be one of {MEMBER_STATES}")
    tool = m.get("tool")
    if not isinstance(tool, str) or not tool:
        errors.append(f"{where}: tool is required")
    elif _DENY.search(tool):
        errors.append(f"{where}: tool {tool!r} looks like an action, write or payment tool")
    if kind == "external":
        if not isinstance(m.get("resource_id"), int):
            errors.append(f"{where}: external member needs an integer resource_id")
        if m.get("read_only_hint") is not True:
            errors.append(f"{where}: external member needs an explicit readOnlyHint=true")
        if not m.get("registrable_domain"):
            errors.append(f"{where}: external member needs registrable_domain (failure domain)")
    if kind == "agentcon":
        # Runs in-process through agent_market.fallback_agents by agent_id (path A), or through the
        # registered-agent path when it has a resource_id (path B); either way agent_id names it.
        if not m.get("agent_id"):
            errors.append(f"{where}: AgentValCon fallback member needs agent_id")
        rid = m.get("resource_id")
        if rid is not None and not isinstance(rid, int):
            errors.append(f"{where}: resource_id must be an integer or absent")
    if m.get("destructive_hint") is True:
        errors.append(f"{where}: destructive tools are not allowed")
    if m.get("resend_safe") is True and m.get("idempotent_hint") is not True:
        errors.append(f"{where}: resend_safe needs an explicit idempotentHint=true")
    if not isinstance(m.get("upstream"), list) or not m.get("upstream"):
        errors.append(f"{where}: upstream must list the data sources (use [\"unknown\"] if not known)")
    if not isinstance(m.get("input_map"), dict):
        errors.append(f"{where}: input_map must map tool arguments from the necklace input")
    return errors


# ---------------------------------------------------------------- input schema (PM F11, 11-14)
INPUT_DIALECT = Draft202012Validator          # one explicit draft, never inferred from "$schema"
_VALIDATORS: dict[str, Draft202012Validator] = {}


def input_schema_errors(schema: dict) -> list[str]:
    """Checked when a definition loads: a valid 2020-12 schema, closed to extra fields, no references."""
    errors = []
    if schema.get("additionalProperties") is not False:
        errors.append("input_schema must set additionalProperties to false")
    if schema.get("$schema") not in (None, "https://json-schema.org/draft/2020-12/schema"):
        errors.append("input_schema must use JSON Schema 2020-12")
    if '"$ref"' in json.dumps(schema) or '"$dynamicRef"' in json.dumps(schema):
        errors.append("input_schema must not use references")
    try:
        input_validator(schema)
    except SchemaError as exc:
        errors.append(f"input_schema is not valid JSON Schema 2020-12: {exc.message}")
    return errors


def input_validator(schema: dict) -> Draft202012Validator:
    """The checked validator for one schema, cached by its canonical text."""
    key = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    validator = _VALIDATORS.get(key)
    if validator is None:
        INPUT_DIALECT.check_schema(schema)
        validator = _VALIDATORS[key] = INPUT_DIALECT(schema)
    return validator


def validate(defn: dict, *, check_contracts: bool = True) -> list[str]:
    errors: list[str] = []
    slug = defn.get("slug")
    if not isinstance(slug, str) or not SLUG.match(slug) or not 3 <= len(slug) <= 40:
        errors.append("slug must match ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ and be 3 to 40 characters")
    if not isinstance(defn.get("version"), int) or defn["version"] < 1:
        errors.append("version must be a positive integer")
    if defn.get("status") not in STATUSES:
        errors.append(f"status must be one of {STATUSES}")
    for key in ("name", "summary"):
        if not isinstance(defn.get(key), str) or not defn[key].strip():
            errors.append(f"{key} is required")
    schema = defn.get("input_schema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        errors.append("input_schema must be a JSON object schema")
    else:
        errors.extend(input_schema_errors(schema))
    budget = defn.get("budget_ms") or {}
    total = budget.get("total")
    if not isinstance(total, int) or not 0 < total <= MAX_TOTAL_MS:
        errors.append(f"budget_ms.total must be 1..{MAX_TOTAL_MS}")
    elif not isinstance(budget.get("slot"), int) or not 0 < budget["slot"] <= total:
        errors.append("budget_ms.slot must be positive and not above budget_ms.total")
    slots = defn.get("slots")
    if not isinstance(slots, list) or not slots:
        return errors + ["slots must be a non-empty list"]

    seen_slots = set()
    owner_domains: dict[str, str] = {}
    required = 0
    for slot in slots:
        sid = slot.get("slot")
        if not isinstance(sid, str) or not SLOT_ID.match(sid):
            errors.append(f"slot id {sid!r} must be lowercase snake case")
            continue
        if sid in seen_slots:
            errors.append(f"slot id {sid!r} is repeated")
        seen_slots.add(sid)
        if slot.get("required", True):
            required += 1
        contract = slot.get("contract")
        if not isinstance(contract, str) or not contract:
            errors.append(f"slot {sid}: contract is required")
        elif check_contracts and load_contract(contract) is None:
            errors.append(f"slot {sid}: contract {contract} has no file in contracts/")
        chain = slot.get("chain")
        if not isinstance(chain, list) or not chain:
            errors.append(f"slot {sid}: chain must be a non-empty list")
            continue
        kinds = [m.get("kind") for m in chain]
        if "agentcon" in kinds and "external" in kinds[kinds.index("agentcon"):]:
            errors.append(f"slot {sid}: AgentValCon fallback members must come after every external member")
        if kinds.count("agentcon") > MAX_AGENTCON:
            errors.append(f"slot {sid}: at most {MAX_AGENTCON} AgentValCon fallback members")
        if kinds.count("external") > MAX_EXTERNAL:
            errors.append(f"slot {sid}: at most {MAX_EXTERNAL} external members")
        pairs = set()
        for idx, m in enumerate(chain):
            errors += _member_errors(sid, idx, m)
            key = (m.get("resource_id"), m.get("agent_id"), m.get("tool"))
            if key in pairs:
                errors.append(f"slot {sid}: member {idx} repeats another member")
            pairs.add(key)
        fanout = slot.get("fanout", 1)
        if not isinstance(fanout, int) or fanout < 1:
            errors.append(f"slot {sid}: fanout must be a positive integer")
        elif fanout > max(1, kinds.count("external")):
            errors.append(f"slot {sid}: fanout {fanout} exceeds the external members")
        first = next((m for m in chain if m.get("kind") == "external"), None)
        if first and first.get("registrable_domain"):
            domain = first["registrable_domain"]
            if domain in owner_domains:
                errors.append(f"slot {sid}: failure domain {domain} already owns slot {owner_domains[domain]}")
            owner_domains[domain] = sid
        if contract in NO_FALLBACK_ROLES:
            if slot.get("required", True):
                errors.append(f"slot {sid}: {contract} has no AgentValCon fallback and may only be an optional slot")
            if kinds.count("external") < 2:
                errors.append(f"slot {sid}: {contract} needs at least two external members")
        for dep in slot.get("depends_on") or []:
            if dep not in seen_slots:
                errors.append(f"slot {sid}: depends_on {dep!r} must name an earlier slot")
    single_fanout = len(slots) == 1 and isinstance(slots[0].get("fanout", 1), int) and slots[0].get("fanout", 1) >= 2
    if required < 2 and not single_fanout:
        errors.append("a necklace needs two required slots, or one slot fanning out to two or more pearls")
    return errors


def readiness(defn: dict, pearl_ids: set[int] | None = None) -> list[str]:
    """Qualification gaps before the gold-set trial (process.md step 3)."""
    gaps = []
    for slot in defn.get("slots") or []:
        if not slot.get("required", True):
            continue
        sid = slot.get("slot")
        externals = live_members(slot, "external")
        agentcon = live_members(slot, "agentcon")
        if len(externals) < 2:
            gaps.append(f"slot {sid}: {len(externals)} active external members, need 2")
        if not agentcon:
            gaps.append(f"slot {sid}: no active AgentValCon fallback member")
        lead = primary(slot)
        if lead is not None:
            if pearl_ids is not None and lead.get("resource_id") not in pearl_ids:
                gaps.append(f"slot {sid}: primary {lead.get('resource_id')} is not a strict pearl")
            outside = [m for m in externals + agentcon
                       if m.get("registrable_domain") != lead.get("registrable_domain")]
            if not outside:
                gaps.append(f"slot {sid}: no member outside the primary's failure domain")
    return gaps


def load_valid(directory: Path | str = DEFINITIONS) -> list[dict]:
    defs = load_all(directory)
    problems = {d.get("slug"): validate(d) for d in defs}
    bad = {k: v for k, v in problems.items() if v}
    if bad:
        raise DefinitionError(json.dumps(bad, ensure_ascii=False, indent=1))
    slugs = [d["slug"] for d in defs]
    if len(slugs) != len(set(slugs)):
        raise DefinitionError("two definition files share a slug")
    return defs

"""Fixed role tasks for pearl tests (report v2): two or three inputs per necklace role
with expected results checked against the member's raw response text.

File: ``role_tasks/role-tasks-v1.jsonl`` (one case per line, same shape as the gold
sets: case_id, role, contract, task_type, input, expect, truth_sources). Every
expected value was checked against its public source on the date in
``truth_sources[].checked_on``. Public, non-personal inputs only.

``expect`` keys:
- ``must_include_all`` / ``must_include_any``: words or identifiers that must appear
  (case-insensitive, as whole words). With ``alias_groups``, any alias of a group counts for it.
  A word the case's own input already contains is not asked for (R10, 11-15).
- ``must_include_https_url``: at least one ``https://`` link
- ``kev``: True means the text says the CVE is in the KEV catalog; False means it
  does not claim a KEV listing
- ``numeric``: ``{field: {"equals"|"at_least": number}}`` read from structured output
- ``published_within_days`` and ``dynamic`` need live data and are left to the runner
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FILE = Path(__file__).resolve().parent / "role_tasks" / "role-tasks-v1.jsonl"
KEV_WORDS = re.compile(r"(known exploited|\bkev\b|cisa kev|exploited in the wild|actively exploited)", re.I)
NEGATED_KEV = re.compile(r"(not (in|on|listed in) (the )?(cisa )?(kev|known exploited)|kev\W+(false|no)\b|\"kev\"\s*:\s*false)", re.I)


def load(path: Path = FILE) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def by_role(path: Path = FILE) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for case in load(path):
        out.setdefault(case["role"], []).append(case)
    return out


def _has(text: str, word: str) -> bool:
    """WORD as a whole word or identifier in TEXT (lower case): "MIT" is not found in "commits" (R10)."""
    word = word.lower()
    if not word:
        return False
    before = r"(?<![a-z0-9])" if word[0].isalnum() else ""     # "°C" still follows a number: "9°C"
    after = r"(?![a-z0-9])" if word[-1].isalnum() else ""
    return re.search(before + re.escape(word) + after, text) is not None


def _flat(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flat(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flat(v) for v in value)
    return "" if value is None else str(value)


def _echo(case: dict, word: str, groups: dict) -> bool:
    """True when the case's own input already says WORD (or an alias of it): repeating it proves nothing (R10)."""
    given = _flat(case.get("input")).lower()
    return any(_has(given, alias) for alias in groups.get(word, [word]))


def fact_checks(case: dict) -> int:
    """How many checks of CASE ask for a fact its input does not already give (R10, precision review 11-15).
    Words the input contains and a bare https link are not facts; KEV, numeric fields and dated items are."""
    expect = case.get("expect") or {}
    groups = {g[0]: g for g in expect.get("alias_groups") or []}
    count = sum(1 for word in expect.get("must_include_all") or [] if not _echo(case, word, groups))
    count += 1 if any(not _echo(case, w, groups) for w in expect.get("must_include_any") or []) else 0
    count += 1 if "kev" in expect else 0
    count += len(expect.get("numeric") or {})
    return count


def _dig(data, field):
    for part in field.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def score(case: dict, text: str, structured: dict | None = None) -> tuple[bool, list[str]]:
    """(passed, reasons for failure). Checks that need live data are skipped, not passed silently."""
    expect, low, reasons = case.get("expect") or {}, (text or "").lower(), []
    groups = {g[0]: g for g in expect.get("alias_groups") or []}
    # Words the input already says are not asked for (R10): an answer that only repeats its input proves nothing.
    for word in expect.get("must_include_all") or []:
        if _echo(case, word, groups):
            continue
        if not any(_has(low, alias) for alias in groups.get(word, [word])):
            reasons.append(f"missing {word}")
    anyof = [w for w in expect.get("must_include_any") or [] if not _echo(case, w, groups)]
    if anyof and not any(_has(low, w) for w in anyof):
        reasons.append("none of " + ", ".join(anyof))
    if expect.get("must_include_https_url") and "https://" not in low:
        reasons.append("no https link")
    if "kev" in expect:
        listed = bool(KEV_WORDS.search(text or "")) and not NEGATED_KEV.search(text or "")
        if structured is not None and isinstance(_dig(structured, "kev"), bool):
            listed = _dig(structured, "kev")
        if expect["kev"] and not listed:
            reasons.append("KEV listing not reported")
        if not expect["kev"] and listed:
            reasons.append("claims a KEV listing that does not exist")
    for field, rule in (expect.get("numeric") or {}).items():
        value = _dig(structured or {}, field)
        if not isinstance(value, (int, float)):
            reasons.append(f"{field} missing in structured output")
        elif "equals" in rule and abs(value - rule["equals"]) > 0.05:
            reasons.append(f"{field}={value}, expected {rule['equals']}")
        elif "at_least" in rule and value < rule["at_least"]:
            reasons.append(f"{field}={value}, expected at least {rule['at_least']}")
    return not reasons, reasons

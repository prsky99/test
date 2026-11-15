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
NEGATED_KEV = re.compile(r"""(not\s+(?:currently\s+)?(?:in|on|listed\s+(?:in|on)|part\s+of|included\s+in)\s+(?:the\s+)?(?:cisa\s+)?
    (?:kev|known\s+exploited)|\b(?:in_?)?kev\W{0,3}(?:false|no|none|not\s+listed|unlisted|absent)\b
    |\bkev\b[^.\n]{0,40}\bnot\s+(?:listed|present|found|included)\b|\bno\s+kev\s+(?:entry|listing|record)\b
    |"(?:in_?)?kev"\s*:\s*false)""", re.I | re.X)


# A KEV flag under its usual key names (11-15 PM: mcp/37141 answered "in_kev": true and scored "KEV listing not
# reported", since \bkev\b never matches inside in_kev).
KEV_KEYS = ("kev", "in_kev", "is_kev", "kev_listed", "in_cisa_kev", "cisa_kev", "known_exploited", "knownexploited")
KEV_TRUE = re.compile(r'"?(?:in_|is_)?(?:cisa_)?kev(?:_listed)?"?\s*[:=]\s*true\b|"known_?exploited"\s*:\s*true\b', re.I)


def kev_flag(structured):
    """The boolean a structured answer gives for a KEV listing under any KEV_KEYS name, nested; None when absent."""
    def walk(data, depth=0):
        if depth > 6:
            return None
        if isinstance(data, dict):
            for key, value in data.items():
                if str(key).lower() in KEV_KEYS and isinstance(value, bool):
                    return value
            for value in data.values():
                found = walk(value, depth + 1)
                if found is not None:
                    return found
        elif isinstance(data, list):
            for value in data[:50]:
                found = walk(value, depth + 1)
                if found is not None:
                    return found
        return None
    return walk(structured) if structured is not None else None


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


# Other names a numeric field goes by in real answers (R12: NVD nests the score as metrics...cvssData.baseScore).
FIELD_NAMES = {"cvss_score": ("cvss_score", "cvss", "basescore", "base_score", "cvss3_score", "cvssv3_score", "cvss_v3",
                              "cvss3", "cvss_v31", "score"),
               "epss": ("epss", "epss_score", "epss_probability")}


def _find_number(data, names, depth=0):
    """The first number under any key in NAMES, searched through nested objects and lists (R12)."""
    if depth > 8:
        return None
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in names and isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
        for value in data.values():
            found = _find_number(value, names, depth + 1)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data[:50]:
            found = _find_number(value, names, depth + 1)
            if found is not None:
                return found
    return None


def _number_in_text(text, field):
    """A number the text gives for FIELD ("CVSS 10.0", "cvss_score: 9.8", "base score 7.5/10"), or None (R12)."""
    label = {"cvss_score": r"cvss(?:[\s_]*v?3(?:\.\d)?)?(?:[\s_]*(?:base[\s_]*)?score)?|base[\s_]*score",
             "epss": r"epss(?:[\s_]*(?:score|probability))?"}.get(
        field, re.escape(field).replace("_", "[ _]"))
    m = re.search(r"(?:" + label + r")\W{0,5}(\d{1,3}(?:\.\d+)?)(?![\d.]*/[A-Z])", text or "", re.I)  # not a vector
    return float(m.group(1)) if m else None


def number_for(field, structured, text):
    value = _dig(structured or {}, field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        value = _find_number(structured or {}, FIELD_NAMES.get(field, (field,)))
    if value is None:
        value = _number_in_text(text, field)
    return value


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
        listed = bool(KEV_WORDS.search(text or "") or KEV_TRUE.search(text or "")) and not NEGATED_KEV.search(text or "")
        flag = kev_flag(structured)
        if flag is not None:
            listed = flag
        if expect["kev"] and not listed:
            reasons.append("KEV listing not reported")
        if not expect["kev"] and listed:
            reasons.append("claims a KEV listing that does not exist")
    for field, rule in (expect.get("numeric") or {}).items():
        value = number_for(field, structured, text)
        if not isinstance(value, (int, float)):
            reasons.append(f"{field} missing in the answer")
        elif "equals" in rule and abs(value - rule["equals"]) > 0.05:
            reasons.append(f"{field}={value}, expected {rule['equals']}")
        elif "at_least" in rule and value < rule["at_least"]:
            reasons.append(f"{field}={value}, expected at least {rule['at_least']}")
    return not reasons, reasons

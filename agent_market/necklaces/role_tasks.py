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


# ---------------------------------------------------------------- rotating recent KEV case (search team, PM 11-15 10:24)
# cve.exploited needs one CVE added to CISA KEV in the last 30 days, replaced weekly, so a stale copy of the catalog that
# does not know recent additions fails accuracy. The case changes every week, so it lives with the run data (not in git)
# and load() adds it to the fixed cases of FILE for every reader.
KEV_FEED = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
RECENT_DAYS = 30
REFRESH_DAYS = 7
REFERENCE_SYSTEM = "reference_checks"


def recent_kev_path() -> Path:
    import os
    project = os.environ.get("AGENTCON_PROJECT_ROOT")
    base = Path(project) if project else Path(__file__).resolve().parents[2]
    return base / "gateway-data" / "necklaces" / "role_tasks" / "recent-kev.jsonl"


def recent_kev_case(feed: dict, today: str) -> dict | None:
    """The newest KEV addition within RECENT_DAYS of today as a role-task case, or None."""
    from datetime import date, timedelta
    floor = (date.fromisoformat(today) - timedelta(days=RECENT_DAYS)).isoformat()
    rows = [v for v in feed.get("vulnerabilities") or []
            if isinstance(v, dict) and re.fullmatch(r"CVE-\d{4}-\d{4,}", str(v.get("cveID", "")))
            and floor <= str(v.get("dateAdded", "")) <= today]
    if not rows:
        return None
    newest = max(rows, key=lambda v: (v["dateAdded"], v["cveID"]))
    cve = newest["cveID"]
    return {"case_id": "kev-recent-" + cve.lower(), "contract": "cve.exploited.v1", "role": "cve.exploited.v1",
            "task_type": "role_test", "rotating": "weekly-recent-kev",
            "expect": {"kev": True, "kev_date_added": newest["dateAdded"]}, "input": {"cve_id": cve},
            "note": f"added to KEV within {RECENT_DAYS} days of {today}; replaced weekly",
            "truth_sources": [{"checked_on": today, "name": "CISA KEV",
                               "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"}]}


def _fetch_feed(get=None) -> dict:
    if get is not None:
        return get(KEV_FEED)
    import urllib.request
    from ..provider_budget import note, reserve
    from .gold import USER_AGENT
    ok, why = reserve(KEV_FEED, REFERENCE_SYSTEM)
    if not ok:
        raise RuntimeError(f"provider budget: {why}")
    request = urllib.request.Request(KEV_FEED, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            note(KEV_FEED, REFERENCE_SYSTEM, getattr(response, "status", 200), evidence="provider_http")
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        if getattr(exc, "code", None):
            note(KEV_FEED, REFERENCE_SYSTEM, exc.code, evidence="provider_http")
        raise


def refresh_recent_kev(today: str | None = None, path: Path | None = None, get=None, force: bool = False) -> dict:
    """Replace the rotating case when it is missing or older than REFRESH_DAYS (one KEV feed download through the
    shared ledger). Nothing is written when the feed has no addition in the last RECENT_DAYS."""
    import time
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    path = path or recent_kev_path()
    current = load_plain(path) if path.exists() else []
    checked = max((s.get("checked_on", "") for c in current for s in c.get("truth_sources") or []), default="")
    from datetime import date
    if not force and checked and (date.fromisoformat(today) - date.fromisoformat(checked)).days < REFRESH_DAYS:
        return {"refreshed": False, "case_id": current[0]["case_id"] if current else None, "checked_on": checked}
    case = recent_kev_case(_fetch_feed(get), today)
    if case is None:
        return {"refreshed": False, "why": f"no KEV addition in the last {RECENT_DAYS} days"}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {"refreshed": True, "case_id": case["case_id"], "kev_date_added": case["expect"]["kev_date_added"]}


def load_plain(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load(path: Path = FILE) -> list[dict]:
    """The cases of PATH; for the fixed v1 file also the rotating recent-KEV case when one exists."""
    cases = load_plain(path)
    if path == FILE:
        recent = recent_kev_path()
        if recent.exists():
            try:
                cases += [c for c in load_plain(recent) if c.get("rotating") == "weekly-recent-kev"]
            except (OSError, ValueError):
                pass
    return cases


def current(case: dict, today: str | None = None) -> bool:
    """False once a case's facts may be out of date: "valid_until" (YYYY-MM-DD, KST day) has passed. A case built on
    the latest SEC filing (PM 11-15 13:46) stops being asked before the next periodic report can replace it."""
    until = case.get("valid_until")
    if not until:
        return True
    if today is None:
        from datetime import datetime, timedelta, timezone
        today = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
    return str(today) <= str(until)


def by_role(path: Path = FILE, today: str | None = None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for case in load(path):
        if current(case, today):
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
    count += 1 if expect.get("must_not_match") else 0
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
    # A "no such record" answer (PM 11-15 13:46: a company with no SEC registration) fails when it still names a
    # record, such as another company's accession number or CIK.
    for pattern in expect.get("must_not_match") or []:
        if re.search(pattern, text or "", re.I):
            reasons.append(f"names a record that does not exist ({pattern})")
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

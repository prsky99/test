"""The one necklace retest runner: trial self-tests, daily retests and gate rounds.

- External members are called through the public relay ``/api/gateway/mcp/<resource_id>`` with
  ``X-Agentcon-QA: necklace_retest`` (all relay guards apply; the error ledger and the north star
  set the calls apart) and the shared provider budget (deploy/PROVIDER_BUDGET.md).
- AgentValCon fallbacks without a resource_id run in-process (fallback_agents, PM path A).
- Each case is graded per slot against the frozen gold truth; the case passes when every required
  slot passes. The contrast slot (advisories, record) is also run with each external member alone
  for the single baseline (Δ).
- Lines go to ``<root>/retest/<YYYYMMDD>.jsonl`` in the shape daily.py reads; full answers for
  review go to ``<root>/results/<slug>/selftest-<YYYYMMDD>.jsonl`` (inputs are public gold cases).
- A run stops when its time budget (35 minutes by default) is spent; the rest waits for the next day.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import threading
import time
from pathlib import Path

from . import model, runner
from .judge import DEFAULT_ROOT, _iso

BASE = "https://agentconcierge.biz"
QA = "necklace_retest"
QA_GATE = "necklace_gate"           # gate rounds and the gate check (deploy/NECKLACE_GATE.md 3절)
BUDGET_SECONDS = 35 * 60
CONTRAST = {"package-risk-audit": "advisories", "cve-incident-brief": "record", "company-due-diligence": "background",
            "topic-evidence-brief": "papers", "quakes-near-address": "quakes"}


# ---------------------------------------------------------------- public relay caller
RELAY_PER_MINUTE = 9      # the public gateway allows 10 agent requests a minute per address


class RelayPacer:
    """Our own relay's per-address limit. Waiting happens between cases (wait_for), never inside a case,
    so the 5-second necklace deadline is not spent queueing; a call over the limit is not sent."""

    def __init__(self, per_minute: int = RELAY_PER_MINUTE, clock=time.monotonic, sleep=time.sleep):
        self.per_minute, self.clock, self.sleep, self.sent = per_minute, clock, sleep, []

    def _trim(self):
        now = self.clock()
        self.sent = [t for t in self.sent if now - t < 60]
        return now

    def wait_for(self, n: int):
        n = min(n, self.per_minute)
        while True:
            now = self._trim()
            if len(self.sent) + n <= self.per_minute:
                return
            self.sleep(60 - (now - self.sent[0]) + 0.2)

    def take(self) -> bool:
        self._trim()
        if len(self.sent) >= self.per_minute:
            return False
        self.sent.append(self.clock())
        return True


def _fail(code: str, message: str = ""):
    error = Exception(message or code)
    error.error_code = code
    return error


# PM 11-15 10:40: the edge runs 4 executions at once; our own tests use at most 2 so outside runs keep a slot.
RELAY_CONCURRENCY = 2
_RELAY_SLOTS = threading.BoundedSemaphore(RELAY_CONCURRENCY)
CAPACITY = "our_capacity"      # the edge's CAPACITY_EXCEEDED: our side, never the member's failure
# PM R23 (11-15): failures that say nothing about the member - our own budget or pace, our edge, the provider asking for
# a pause - leave a run "not measured" instead of failed, for the necklace and for every single baseline alike.
NOT_MEASURED = (CAPACITY, "relay_throttled", "PROVIDER_429")


def not_measured(attempts: dict) -> str | None:
    for slot_attempts in attempts.values():
        for a in slot_attempts:
            code = a.get("error_class") or ""
            if code in NOT_MEASURED or code.startswith("budget_"):
                return code
    return None


def capacity_exceeded(status: int, headers, data: dict) -> bool:
    error = (data or {}).get("error") or {}
    detail = error.get("data") if isinstance(error.get("data"), dict) else {}
    text = str(error.get("message") or (data or {}).get("detail") or "")
    return (status == 503 or headers.get("X-Execution-Error") == "CAPACITY_EXCEEDED"
            or detail.get("error_code") == "CAPACITY_EXCEEDED" or "execution is unavailable" in text.lower())


def gateway_caller(client, base: str = BASE, pacer: RelayPacer | None = None, slots=None, sleep=time.sleep):
    pacer = pacer or RelayPacer()
    slots = _RELAY_SLOTS if slots is None else slots

    def post(url, method, params, timeout_s):
        started = time.monotonic()
        if not slots.acquire(timeout=max(0.0, timeout_s)):
            raise _fail(CAPACITY, f"no free relay slot of {RELAY_CONCURRENCY}")
        try:
            return client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                               headers={"Content-Type": "application/json", "Accept": "application/json",
                                        "MCP-Protocol-Version": "2025-06-18", "X-Agentcon-QA": QA},
                               timeout=max(0.5, timeout_s - (time.monotonic() - started)))
        finally:
            slots.release()

    def rpc(url, method, params, timeout_s=12.0):
        started = time.monotonic()
        for attempt in (1, 2):                       # one retry when the edge is full, then it is our capacity
            if not pacer.take():
                raise _fail("relay_throttled", "local relay pace reached")
            r = post(url, method, params, timeout_s - (time.monotonic() - started))
            try:
                data = r.json()
            except ValueError:
                data = {}
            if not capacity_exceeded(r.status_code, getattr(r, "headers", None) or {}, data if isinstance(data, dict) else {}):
                break
            if attempt == 2 or timeout_s - (time.monotonic() - started) < 1.0:
                raise _fail(CAPACITY, "edge execution slots full (CAPACITY_EXCEEDED)")
            sleep(0.3)
        if r.status_code == 429:
            raise _fail("relay_throttled", "our relay rate limit")      # not the provider's pause
        if "result" not in data:
            err = data.get("error") or {}
            detail = err.get("data") if isinstance(err.get("data"), dict) else {}
            if detail.get("retry_after") or "pause" in str(err.get("message", "")).lower():
                error = _fail("PROVIDER_429", str(err.get("message")))   # the provider asked for a pause
                # the ledger pauses a domain only with this evidence (provider_budget.pause_evidence)
                error.pause_evidence = {"origin": "provider_rpc", "retry_after": detail.get("retry_after"),
                                        "message": str(err.get("message") or "")}
                raise error
            reason = (getattr(r, "headers", None) or {}).get("X-Execution-Error")
            ref = (getattr(r, "headers", None) or {}).get("X-Execution-Reference")
            raise _fail(f"relay_{r.status_code}", str(err.get("message") or data.get("detail") or f"HTTP {r.status_code}")
                        + (f" [{reason}]" if reason else "") + (f" ref {ref}" if ref else ""))
        return data["result"]

    def call(member, args, timeout_s):
        if member.get("kind") == "agentcon" and not isinstance(member.get("resource_id"), int):
            from .. import fallback_agents
            return fallback_agents.slot_output(fallback_agents.run(member["agent_id"], args))
        url = f"{base}/api/gateway/mcp/{member['resource_id']}"
        started = time.monotonic()
        rpc(url, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "necklace-retest", "version": "1"}}, timeout_s)
        # the call gets what is left of the slot deadline, so one slow provider cannot overrun the necklace
        result = rpc(url, "tools/call", {"name": member["tool"], "arguments": args},
                     timeout_s - (time.monotonic() - started))
        if result.get("isError"):
            error = Exception("tool error")
            error.error_code = "UPSTREAM_TOOL_ERROR"
            raise error
        return result.get("structuredContent") or result.get("content") or result
    return call


def provider_url(member: dict) -> str:
    """The budget counts the pearl provider's registrable domain, never our relay host."""
    return f"https://{member['registrable_domain']}/"


# ---------------------------------------------------------------- graders (frozen gold truth)
def _text(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str).lower()


def _token(value: str, text: str) -> bool:
    """VALUE as a whole token of TEXT (not inside a longer number, version or id)."""
    return re.search(r"(?<![\w.])" + re.escape(value.lower()) + r"(?![\w]|\.\d)", text) is not None


def grade_advisories(case, slot_out) -> bool:
    """PM R25: a clean version passes only with no advisory listed; otherwise 90% of the truth's advisories must be
    found and at least half of what was listed must be true (a dump of every id does not pass)."""
    if not slot_out or slot_out.get("missing"):
        return False
    found = {i["id"].upper() for i in slot_out.get("items", [])}
    truth = case["truth"]["advisories"]
    if not truth:
        return not found                  # a clean version: listing anything is a wrong answer
    known = {x.upper() for adv in truth for x in adv["ids"]}
    hit = sum(1 for adv in truth if {x.upper() for x in adv["ids"]} & found)
    return hit / len(truth) >= 0.9 and len(found & known) >= len(found) / 2


def grade_health(case, slot_out) -> bool:
    """The registry's latest version as a whole version token (1.2 does not match 1.2.3)."""
    latest = case["truth"].get("latest_version")
    return bool(slot_out) and not slot_out.get("missing") and bool(latest) and _token(latest, _text(slot_out))


def grade_record(case, slot_out) -> bool:
    if not slot_out or slot_out.get("missing"):
        return False
    truth = {case["truth"]["cvss"].get("score"), (case["truth"].get("cvss_record") or {}).get("score")} - {None}
    scores = [s for s in (slot_out.get("cvss_scores") or [slot_out.get("cvss_score")]) if s is not None]
    return any(abs(s - t) <= 0.1 for s in scores for t in truth)


def grade_exploited(case, slot_out) -> bool:
    return bool(slot_out) and not slot_out.get("missing") and slot_out.get("kev") is case["truth"]["kev"]


def grade_registry(case, slot_out) -> bool:
    """A company identity passes when it names the truth's SEC CIK or GLEIF LEI."""
    if not slot_out or slot_out.get("missing"):
        return False
    text = _text(slot_out)
    cik, lei = case["truth"].get("cik"), case["truth"].get("lei")
    return bool((cik and re.search(r"(?<!\d)0*" + re.escape(str(int(cik))) + r"(?!\d)", text))
                or (lei and _token(lei, text)))


STOP = {"the", "of", "and", "a", "an", "in", "for", "to", "or", "by", "on", "with"}


def grade_papers(case, slot_out) -> bool:
    """At least one of the topic's most-cited papers (OpenAlex, title search), by DOI or title."""
    if not slot_out or slot_out.get("missing"):
        return False
    text = _text(slot_out)
    return any((p.get("doi") and p["doi"].lower() in text) or (p.get("title") and p["title"].lower()[:60] in text)
               for p in case["truth"]["papers"])


LEGAL_WORDS = {"inc", "corp", "co", "ltd", "plc", "ag", "se", "sa", "nv", "spa", "asa", "ab", "oyj", "group", "holdings",
               "holding", "company", "corporation", "limited", "incorporated", "the", "and"}


def company_words(case) -> set[str]:
    """Distinctive words of the company's typed and legal names (legal forms and short words left out)."""
    from .gold import name_key
    names = [case["input"].get("name"), case["truth"].get("legal_name"), case["truth"].get("sec_title")]
    return {w for n in names if n for w in name_key(n).split() if len(w) > 2 and w not in LEGAL_WORDS}


def grade_background(case, slot_out) -> bool:
    """The encyclopedia answer is about the topic: its title, or two words of its short description. For a company
    case (no wiki truth): it names the company by one of its distinctive words."""
    if not slot_out or slot_out.get("missing"):
        return False
    if "wiki" not in case["truth"]:
        text = _text(slot_out)
        words = company_words(case)
        named = [w for w in words if re.search(r"\b" + re.escape(w) + r"\b", text)]
        # R25: a description, not an echo of the name: at least two distinctive words of the name (all when it has
        # fewer) and some text beyond them
        return len(named) >= min(2, len(words)) and len(re.sub(r"[^a-z]", "", text)) >= 60
    text, wiki = _text(slot_out), case["truth"]["wiki"]
    if wiki["title"].lower() in text:
        return True
    words = {w for w in (wiki.get("description") or "").lower().split() if w not in STOP and len(w) > 2}
    return len([w for w in words if w in text]) >= 2


def grade_web(case, slot_out) -> bool:
    """R25: a grounded answer about the topic: an https link and the topic named (its title, or two words of its
    short description); a bare link no longer passes."""
    if not slot_out or slot_out.get("missing") or "https://" not in _text(slot_out):
        return False
    wiki = (case["truth"] or {}).get("wiki")
    if not wiki:
        return False
    text = _text(slot_out)
    if wiki["title"].lower() in text:
        return True
    words = {w for w in (wiki.get("description") or "").lower().split() if w not in STOP and len(w) > 2}
    return len([w for w in words if w in text]) >= 2


GRADERS = {"advisories": grade_advisories, "health": grade_health, "record": grade_record,
           "exploited": grade_exploited, "registry": grade_registry, "papers": grade_papers,
           "background": grade_background, "web": grade_web}


FILING = re.compile(r'"form"\s*:\s*"(?P<form>10-K|10-Q|20-F|40-F)"(?P<rest>[^{}]*)', re.I)   # _text lower-cases
FILING_DATE = re.compile(r'"filing_?date"\s*:\s*"(\d{4}-\d{2}-\d{2})"', re.I)
ACCESSION = re.compile(r'"accession(?:_?number)?"\s*:\s*"([0-9-]{18,20})"', re.I)


def grade_filings(case, slot_out) -> bool:
    """The latest periodic filing (PM 11-15 decision 2): the truth's 10-K/10-Q/20-F/40-F or any later periodic filing,
    read from the structured answer (form, filingDate, accession)."""
    truth = case["truth"].get("filings")
    if not truth or not slot_out or (isinstance(slot_out, dict) and slot_out.get("missing")):
        return False
    text = _text(slot_out).replace('\\"', '"')
    for match in FILING.finditer(text):
        dated = FILING_DATE.search(match["rest"])
        acc = ACCESSION.search(match["rest"])
        if acc and acc.group(1).replace("-", "") == truth["accession"].replace("-", ""):
            return True
        if dated and dated.group(1) > truth["date"]:
            return True
    return False


def grade_company_task(case, output) -> bool:
    """company-due-diligence as one task, for the necklace and for every single member alike (the delta compares the
    same task on the same case; PM 11-15 decision 2): it passes only with all three parts, which no one agent gives -
    the truth's SEC CIK, the company's latest periodic filing (or a later one) and a description naming the company."""
    text = _text(output or {})
    cik = case["truth"].get("cik")
    has_cik = bool(cik) and re.search(r"\b0*" + re.escape(str(int(cik))) + r"\b", text) is not None
    return has_cik and grade_filings(case, output) and grade_background(case, {"text": text})


def company_excluded(case, today: str | None = None) -> str | None:
    """Cases outside v1's task are not graded: no filings truth (no periodic filing in the indexed quarters) or a
    truth past its validity (rebuild with necklaces.gold_filings)."""
    truth = case["truth"].get("filings")
    if case.get("input", {}).get("country") != "US" or not truth:
        return "out_of_task"
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    return "truth_expired" if today > truth.get("valid_until", "") else None


TASK_EXCLUDE = {"company-due-diligence": company_excluded}
GRADERS["filings"] = grade_filings


# ---------------------------------------------------------------- quakes-near-address (location hub, workflow 11-15)
USGS_FDSN = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&latitude={lat}&longitude={lon}"
             "&maxradiuskm={radius}&starttime={start}&minmagnitude={mag}&orderby=magnitude&limit=200")
REFERENCE_SECONDS = 600                 # one USGS query per place per ten minutes, through the shared ledger
FEED_LAG_SECONDS = 1800                 # feeds and caches can trail USGS by minutes: the newest half hour is not owed
_QUAKE_REFERENCE: dict = {}


def km(lat1, lon1, lat2, lon2) -> float:
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def epoch(value) -> float | None:
    """An event time as seconds: ISO 8601 text, or epoch seconds or milliseconds (USGS gives milliseconds)."""
    from datetime import datetime
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value / 1000 if value > 1e11 else float(value)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _fetch_json(url: str):
    import urllib.request
    from ..provider_budget import note, reserve
    from .gold import USER_AGENT
    ok, _why = reserve(url, "reference_checks")
    if not ok:
        return None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            note(url, "reference_checks", getattr(response, "status", 200), evidence="provider_http")
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:                              # noqa: BLE001 - no reference means the case is not graded
        if getattr(exc, "code", None):
            note(url, "reference_checks", exc.code, evidence="provider_http")
        return None


def quakes_reference(truth: dict, now: float | None = None, get=_fetch_json) -> list[dict] | None:
    """USGS events for the case's place and window, asked when the case is graded (cached ten minutes)."""
    now = time.time() if now is None else now
    key = (truth["lat"], truth["lon"], truth["radius_km"], int(now // REFERENCE_SECONDS))
    if key not in _QUAKE_REFERENCE:
        start = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - truth["days"] * 86400))
        body = get(USGS_FDSN.format(lat=truth["lat"], lon=truth["lon"], radius=truth["radius_km"], start=start,
                                    mag=truth["min_magnitude"]))
        if not isinstance(body, dict) or not isinstance(body.get("features"), list):
            return None
        events = []
        for feature in body["features"]:
            props, coords = feature.get("properties") or {}, (feature.get("geometry") or {}).get("coordinates") or []
            if isinstance(props.get("mag"), (int, float)) and len(coords) >= 2:
                events.append({"id": feature.get("id"), "mag": float(props["mag"]), "lat": coords[1], "lon": coords[0],
                               "time": epoch(props.get("time"))})
        if len(_QUAKE_REFERENCE) > 500:
            _QUAKE_REFERENCE.clear()
        _QUAKE_REFERENCE[key] = events
    return _QUAKE_REFERENCE[key]


def grade_location(case, slot_out) -> bool:
    """Coordinates within the case's tolerance of the place (landmark 3 km, city 25 km), anywhere in the answer that
    is not an earthquake (an event has a magnitude)."""
    truth = case["truth"]
    if not slot_out:
        return False
    for node, _ in runner._walk(slot_out):
        if isinstance(node, dict) and not any(str(k).lower() in runner.MAG_KEYS for k in node):
            here = runner._coords(node)
            if here and km(here[0], here[1], truth["lat"], truth["lon"]) <= truth["tolerance_km"]:
                return True
    for match in runner.POINT_TEXT.finditer(_text(slot_out)):
        lat, lon = float(match.group(1)), float(match.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180 and km(lat, lon, truth["lat"], truth["lon"]) <= truth["tolerance_km"]:
            return True
    return False


def grade_quakes(case, slot_out, now: float | None = None, reference=None) -> bool:
    """The answer's events against USGS for the same place and window:
    - it must list events or say there are none (silence is not an answer)
    - no event may lie beyond the radius (with a 10 % and location margin): an answer for the wrong place fails
    - when USGS has an event that is surely in the window (well inside the radius, older than half an hour, not at
      the week's edge, at least 0.2 above the minimum magnitude), the strongest such event must be in the answer
      (magnitude within 0.3, epicentre within 50 km, time within 5 minutes when both give one)"""
    truth = case["truth"]
    now = time.time() if now is None else now
    quakes = runner.norm_quakes(slot_out, {}) if slot_out else None
    if quakes is None:
        return False
    radius, tol = truth["radius_km"], truth["tolerance_km"]
    for e in quakes["events"]:
        if km(e["lat"], e["lon"], truth["lat"], truth["lon"]) > 1.1 * radius + tol:
            return False
    reference = quakes_reference(truth, now) if reference is None else reference
    if reference is None:
        return False
    sure = [e for e in reference if e["time"] is not None
            and km(e["lat"], e["lon"], truth["lat"], truth["lon"]) <= 0.9 * radius - tol
            and FEED_LAG_SECONDS <= now - e["time"] <= (truth["days"] - 0.5) * 86400
            and e["mag"] >= truth["min_magnitude"] + 0.2]
    if not sure:
        return True
    strongest = max(sure, key=lambda e: e["mag"])
    for e in quakes["events"]:
        when = epoch(e.get("time"))
        if abs(e["mag"] - strongest["mag"]) <= 0.3 and km(e["lat"], e["lon"], strongest["lat"], strongest["lon"]) <= 50 \
                and (when is None or abs(when - strongest["time"]) <= 300):
            return True
    return False


def grade_quakes_task(case, output) -> bool:
    """quakes-near-address as one task, for the necklace and every single member alike: the place's coordinates and
    the nearby earthquakes together. 178542 takes a place name by itself, so the quakes alone are not the task."""
    return grade_location(case, output) and grade_quakes(case, output)


def quakes_excluded(case, now: float | None = None) -> str | None:
    """No USGS answer for the reference: the case is not graded (counted apart, never a failure)."""
    return None if quakes_reference(case["truth"], now) is not None else "reference_unavailable"


GRADERS["location"] = grade_location
GRADERS["quakes"] = grade_quakes
TASK_EXCLUDE["quakes-near-address"] = quakes_excluded

# ---------------------------------------------------------------- book-author-brief (workflow 11-15)
def _surname(case) -> str:
    return case["truth"]["author"].split()[-1].lower()


def _named(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text) is not None


def grade_book(case, slot_out) -> bool:
    """The book's author (by surname) and its first publication year, within one year (editions and translations
    shift it)."""
    if not slot_out:
        return False
    text = _text(slot_out)
    years = {int(y) for y in re.findall(r"(?<!\d)(1[5-9]\d\d|20[0-2]\d)(?!\d)", text)}
    return _named(text, _surname(case)) and any(abs(y - case["truth"]["year"]) <= 1 for y in years)


def grade_author(case, slot_out) -> bool:
    """An encyclopedia note on the author: the surname and the author's birth year."""
    if not slot_out:
        return False
    text = _text(slot_out)
    return _named(text, _surname(case)) and re.search(r"(?<!\d)" + str(case["truth"]["birth_year"]) + r"(?!\d)",
                                                      text) is not None


def grade_book_task(case, output) -> bool:
    """book-author-brief as one task, for the necklace and every single member alike: the book part (author, first
    year) read from the book step when there is one, and the author's birth year from the author step. A book
    search alone has no birth year; the book's own encyclopedia entry has the year but not the author's birth."""
    output = output or {}
    book = output.get("book") if "book" in output else output
    author = output.get("author") if "author" in output else output
    return grade_book(case, book) and grade_author(case, author)


GRADERS["book"] = grade_book
GRADERS["author"] = grade_author


# ---------------------------------------------------------------- website-trust-brief (workflow 11-15)
# Crawlers both readiness answers speak about (search and AI-search agents, plus the AI training agents the
# fallback lists). A clear case is all allowed or all blocked; anything between is "mixed" and any verdict passes
# that speaks about crawler access, because feeds check different agent lists.
CRAWLERS = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "anthropic-ai", "Google-Extended", "PerplexityBot",
            "CCBot", "Googlebot", "Bingbot")
BLOCKED_WORDS = ("block", "disallow", "not allowed", "denied", "fail", "cannot fetch", "can't fetch", "restricted")
ALLOWED_WORDS = ("pass", "allowed", "may fetch", "can fetch", "accessible", "permitted", "no restrictions")
_ROBOTS_REFERENCE: dict = {}


def _fetch_robots(url: str):
    """(status, text) of a robots.txt through the shared ledger as reference_checks; None when it cannot be read."""
    import urllib.error
    import urllib.request
    from ..provider_budget import note, reserve
    from .gold import USER_AGENT
    ok, _why = reserve(url, "reference_checks")
    if not ok:
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=15) as r:
            note(url, "reference_checks", getattr(r, "status", 200), evidence="provider_http")
            return 200, r.read(500_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        note(url, "reference_checks", exc.code, evidence="provider_http")
        return (exc.code, "") if exc.code in (404, 410) else None
    except Exception:                                     # noqa: BLE001 - unreadable: the case is not graded
        return None


def robots_reference(domain: str, now: float | None = None, get=_fetch_robots) -> str | None:
    """'allowed', 'blocked' or 'mixed' for the home page under today's robots.txt (cached ten minutes); a missing
    robots.txt allows everything; None when it cannot be read (5xx, timeout, budget)."""
    from urllib.robotparser import RobotFileParser
    now = time.time() if now is None else now
    key = (domain, int(now // REFERENCE_SECONDS))
    if key not in _ROBOTS_REFERENCE:
        got = get(f"https://{domain}/robots.txt")
        if got is None:
            return None
        status, text = got
        if status != 200:
            verdict = "allowed"
        else:
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            blocked = [bot for bot in CRAWLERS if not parser.can_fetch(bot, f"https://{domain}/")]
            verdict = "allowed" if not blocked else "blocked" if len(blocked) == len(CRAWLERS) else "mixed"
        if len(_ROBOTS_REFERENCE) > 500:
            _ROBOTS_REFERENCE.clear()
        _ROBOTS_REFERENCE[key] = verdict
    return _ROBOTS_REFERENCE[key]


def grade_registration(case, slot_out) -> bool:
    """The RDAP registration date, to the day (one day of slack for time zones)."""
    from datetime import date, timedelta
    if not slot_out:
        return False
    text, truth = _text(slot_out), date.fromisoformat(case["truth"]["registered"])
    return any(str(truth + timedelta(days=d)) in text for d in (-1, 0, 1))


def grade_crawlers(case, slot_out, now: float | None = None, reference: str | None = None) -> bool:
    """A crawler verdict that agrees with robots.txt read now: all allowed must be said as allowed (and no named
    crawler said blocked), all blocked as blocked; a mixed file needs only a word about crawler access."""
    if not slot_out:
        return False
    text = _text(slot_out)
    if not re.search(r"crawl|robots|bot\b|bots\b|" + "|".join(b.lower() for b in CRAWLERS), text):
        return False
    verdict = reference or robots_reference(case["truth"]["domain"], now)
    if verdict is None:
        return False
    said_blocked = any(w in text for w in BLOCKED_WORDS)
    positive = re.sub(r"disallow\w*|not allowed|not permitted|inaccessible", " ", text)   # "disallowed" is no 'allowed'
    said_allowed = any(w in positive for w in ALLOWED_WORDS)
    if verdict == "allowed":
        return said_allowed and not any(re.search(re.escape(b.lower()) + r"\W{1,6}(blocked|disallowed)", text)
                                        for b in CRAWLERS)
    if verdict == "blocked":
        return said_blocked
    return said_blocked or said_allowed


def grade_site_task(case, output) -> bool:
    """website-trust-brief as one task, for the necklace and every single member alike: the registration date and a
    crawler verdict. A domain lookup says nothing about crawlers; a readiness check gives no registration date."""
    output = output or {}
    registration_part = output.get("registration") if "registration" in output else output
    crawlers_part = output.get("crawlers") if "crawlers" in output else output
    return grade_registration(case, registration_part) and grade_crawlers(case, crawlers_part)


def site_excluded(case, now: float | None = None) -> str | None:
    return None if robots_reference(case["truth"]["domain"], now) is not None else "reference_unavailable"


GRADERS["registration"] = grade_registration
GRADERS["crawlers"] = grade_crawlers
TASK_EXCLUDE["website-trust-brief"] = site_excluded

TASK_GRADERS = {"company-due-diligence": grade_company_task, "quakes-near-address": grade_quakes_task,
                "book-author-brief": grade_book_task, "website-trust-brief": grade_site_task}
CONTRAST["book-author-brief"] = "author"
CONTRAST["website-trust-brief"] = "crawlers"


def grade(defn: dict, case: dict, output: dict) -> dict:
    """Pass per slot; the case passes when every required slot passes (optional slots are reported only). A case outside
    the necklace's task gets ok None and why (it is counted apart, never as a pass or a failure)."""
    why = (TASK_EXCLUDE.get(defn["slug"]) or (lambda c: None))(case)
    if why:
        return {"slots": {}, "ok": None, "excluded": why}
    per = {}
    for slot in defn["slots"]:
        grader = GRADERS.get(slot["slot"])
        if grader:
            per[slot["slot"]] = grader(case, output.get(slot["slot"]))
    required = [s["slot"] for s in defn["slots"] if s.get("required", True) and s["slot"] in per]
    return {"slots": per, "ok": all(per[s] for s in required)}


def requests_per_case(defn: dict) -> int:
    """Relay requests one case may need when the leads answer: initialize and tools/call per lead."""
    return 2 * sum(min(slot.get("fanout", 1), len(model.live_members(slot, "external"))) for slot in defn["slots"])


SINGLE_FROM_INPUT = {"legal_name": "name", "point": "address", "author": "title"}      # a single agent gets what the person typed instead of a staged value


def single_definition(defn: dict, slot_name: str, member: dict) -> dict:
    """The necklace reduced to one slot answered by one member (no fallbacks, no stages): the single baseline. A staged
    template reads the typed input where one stands for it (legal name -> name); other staged values are absent, as
    they would be for a person using that agent alone."""
    single = copy.deepcopy(defn)
    slot = next(s for s in single["slots"] if s["slot"] == slot_name)
    member = copy.deepcopy(member)
    for key, value in list((member.get("input_map") or {}).items()):
        found = model.SLOT_TEMPLATE.fullmatch(value) if isinstance(value, str) else None
        if found:
            if found.group(2) in SINGLE_FROM_INPUT:
                member["input_map"][key] = "{{input." + SINGLE_FROM_INPUT[found.group(2)] + "}}"
            else:
                del member["input_map"][key]
    slot["chain"], slot["fanout"], slot["required"] = [dict(member, state="active")], 1, True
    for key in ("depends_on", "requires_input"):
        slot.pop(key, None)
    single.pop("min_pearls_answered", None)
    single["slots"] = [slot]
    return single


def single_members(defn: dict, contrast: str, watch_state: dict | None = None) -> list[tuple[str, dict]]:
    """Members measured alone. With a whole-task grader (company-due-diligence, PM 11-15 decision 2): every lead pearl
    of every slot and the AgentValCon substitutes in the run chain, so the delta is not owed to our own substitute.
    Otherwise the external members of the contrast slot, as before."""
    if defn["slug"] not in TASK_GRADERS:
        slot = next(s for s in defn["slots"] if s["slot"] == contrast)
        return [(contrast, m) for m in model.live_members(slot, "external")]
    from .watch import runtime_chain
    out = []
    for slot in defn["slots"]:
        chain = runtime_chain(slot, defn["slug"], watch_state or {})
        leads = [m for m in chain if m["kind"] == "external"][:slot.get("fanout", 1)]
        out += [(slot["slot"], m) for m in leads + [m for m in chain if m["kind"] == "agentcon"]]
    return out


# ---------------------------------------------------------------- run
def load_cases(root: Path, slug: str, split: str) -> list[dict]:
    """The split's cases; GoldSetInvalid when the answer set has no validity or is past it (PM 13:0x)."""
    from .gold import GoldSetInvalid, validity_problem
    why = validity_problem(root, slug)
    if why:
        raise GoldSetInvalid(f"{slug}: {why}")
    path = Path(root) / "gold" / slug / f"{split}.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if slug == "company-due-diligence":
        from .gold_filings import attach
        cases = attach(root, cases)
    return cases


def run_set(defn: dict, cases: list[dict], caller, *, root: Path = DEFAULT_ROOT, split: str = "tuning",
            singles: bool = False, budget_s: float = BUDGET_SECONDS, watch_state: dict | None = None,
            clock=time.monotonic, now=time.time, pacer: RelayPacer | None = None,
            shared_cache: SharedMemberCache | None = None) -> dict:
    started = clock()
    day = time.strftime("%Y%m%d", time.localtime(now()))
    lines, details = [], []
    done = passed = excluded = 0
    contrast = CONTRAST.get(defn["slug"])
    exclude = TASK_EXCLUDE.get(defn["slug"]) or (lambda c: None)
    for case in cases:
        if clock() - started > budget_s:
            break
        why = exclude(case)
        if why:                         # outside the task: not run, not graded, counted apart (no provider call)
            lines.append({"type": "excluded", "slug": defn["slug"], "version": defn["version"],
                          "case_id": case["case_id"], "set": split, "at": _iso(now()), "why": why})
            excluded += 1
            continue
        if pacer is not None:
            pacer.wait_for(requests_per_case(defn))
        result = runner.Runner(caller, watch_state=watch_state, keep_raw=2000).run(defn, case["input"])
        verdict = grade(defn, case, result["output"])
        at = _iso(now())
        ours = not_measured(result["attempts"])
        if ours and not verdict["ok"] and shared_cache is not None:
            shared_cache.take_hits()            # the shared count belongs to this case, not the next one
        if ours and not verdict["ok"]:           # our budget, pace or edge, or a provider pause: not a failure (R23)
            lines.append({"type": "excluded", "slug": defn["slug"], "version": defn["version"],
                          "case_id": case["case_id"], "set": split, "at": at, "why": ours})
            details.append({"case_id": case["case_id"], "excluded": ours, "attempts": result["attempts"]})
            excluded += 1
            continue
        shared = shared_cache.take_hits() if shared_cache is not None else 0
        lines.append({"type": "case", "slug": defn["slug"], "version": defn["version"], "case_id": case["case_id"],
                      "set": split, "at": at, "ok": verdict["ok"], "completed": result["completed"], "shared": shared,
                      "completed_external_only": result["completed_external_only"],
                      "latency_ms": result["latency_ms"], "slots": result["slots"], "graded": verdict["slots"]})
        for slot, attempts in result["attempts"].items():
            for a in attempts:
                lines.append({"type": "member", "slug": defn["slug"], "version": defn["version"], "slot": slot,
                              "resource_id": a["resource_id"], "tool": a["tool"], "kind": a["kind"], "at": at,
                              "ok": None if not_measured({slot: [a]}) else a["ok"],
                              "contract_valid": a["error_class"] != "contract_invalid",
                              "latency_ms": a["ms"], "error_class": a["error_class"]})
        details.append({"case_id": case["case_id"], "verdict": verdict, "output": result["output"],
                        "slots": result["slots"], "attempts": result["attempts"]})
        if singles and contrast:
            for slot_name, member in single_members(defn, contrast, watch_state):
                one = single_definition(defn, slot_name, member)
                if pacer is not None and member["kind"] == "external":
                    pacer.wait_for(2)
                out = runner.Runner(caller).run(one, case["input"])
                task = TASK_GRADERS.get(defn["slug"])
                ok = task(case, out["output"]) if task else GRADERS[contrast](case, out["output"].get(contrast))
                if not ok and not_measured(out["attempts"]):
                    ok = None                             # not measured (R23): never a failure of the single member
                lines.append({"type": "single", "slug": defn["slug"], "resource_id": member.get("resource_id"),
                              "agent_id": member.get("agent_id"), "kind": member["kind"], "tool": member["tool"],
                              "case_id": case["case_id"], "at": at, "ok": ok})
        done += 1
        passed += bool(verdict["ok"])
    retest = Path(root) / "retest" / f"{day}.jsonl"
    retest.parent.mkdir(parents=True, exist_ok=True)
    with retest.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    review = Path(root) / "results" / defn["slug"] / f"selftest-{day}.jsonl"
    review.parent.mkdir(parents=True, exist_ok=True)
    with review.open("a", encoding="utf-8") as handle:
        for line in details:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return {"slug": defn["slug"], "split": split, "cases": done, "passed": passed, "excluded": excluded,
            "of": len(cases),
            "stopped_by_budget": done + excluded < len(cases), "seconds": round(clock() - started, 1)}


# PM 11:4x (11-15) decision 1: a live necklace retests 5 held-out cases a day and walks one held-out set of 30 in
# 6 days (r1, then r2 the next 6 days); one failure among the 5 reruns the whole 30 that day. The gate is not cut.
SAMPLE_PER_DAY = 5
SAMPLE_DAYS = 6


def sample_window(now: float) -> tuple[str, int]:
    """(split, first case index) of today's 5 live retest cases."""
    day = int(now // 86400)
    cycle, step = divmod(day, SAMPLE_DAYS)
    return ("holdout-r1" if cycle % 2 == 0 else "holdout-r2"), step * SAMPLE_PER_DAY


class SharedMemberCache:
    """Member answers shared between necklaces inside the scheduled retests only (PM 11:4x decision 2): the same
    member called with the same arguments within ten minutes answers once. It never serves public runs and is apart
    from the public result cache (necklaces.limits); every case line says how many answers it shared ("shared"),
    and error answers are not kept."""

    TTL_S = 600

    def __init__(self, clock=time.monotonic):
        self.clock, self.lock, self.store, self.hits = clock, threading.Lock(), {}, 0

    def wrap(self, caller):
        def call(member, args, timeout_s):
            if member.get("kind") != "external":
                return caller(member, args, timeout_s)
            key = (member.get("resource_id"), member.get("tool"), json.dumps(args, sort_keys=True, default=str))
            with self.lock:
                kept = self.store.get(key)
                if kept and self.clock() - kept[0] < self.TTL_S:
                    self.hits += 1
                    return kept[1]
            answer = caller(member, args, timeout_s)
            if not runner.is_error(runner.unwrap(answer)):
                with self.lock:
                    if len(self.store) > 2000:
                        self.store.clear()
                    self.store[key] = (self.clock(), answer)
            return answer
        return call

    def take_hits(self) -> int:
        with self.lock:
            hits, self.hits = self.hits, 0
        return hits


def ledger_room(defn: dict, cases: int, system: str = "necklace_retest", status=None) -> dict:
    """{domain: [needed, left]} for every lead's provider domain that has not enough of SYSTEM's share left today
    for CASES cases (one call per lead per case; a paused domain has none). The ledger refuses calls past the share
    anyway; this says beforehand that a whole-set rerun would be cut short, so it is deferred instead (PM 12:50)."""
    from .. import provider_budget as pb
    data = (status or pb.status)()
    need: dict[str, int] = {}
    for slot in defn["slots"]:
        for member in model.live_members(slot, "external")[:slot.get("fanout", 1)]:
            name = pb.domain(provider_url(member))
            if name:
                need[name] = need.get(name, 0) + cases
    short = {}
    for name, n in need.items():
        entry = (data.get("domains") or {}).get(name) or {"total": 0, "by": {}}
        left = 0 if entry.get("paused") else min(pb.share_limit(system, name) - (entry.get("by") or {}).get(system, 0),
                                                 pb.domain_total(name) - entry.get("total", 0))
        if left < n:
            short[name] = [n, max(left, 0)]
    return short


def daily_split(now: float) -> str:
    """The daily retest walks the 60 held-out cases in two days: r1 on even days, r2 on odd days."""
    return "holdout-r1" if int(now // 86400) % 2 == 0 else "holdout-r2"


def open_engine():
    """The public run path's workflow engine on the operating store (ops runs this with the operating settings):
    registered-agent guards, McpProxy and the in-process AgentValCon fallbacks, exactly as run_for_surface uses them."""
    from ..application_runtime import open_runtime_storage
    from ..concierge.proxy import McpProxy
    from ..workflows import runtime_for
    storage = open_runtime_storage(None)
    return runtime_for(storage.store, McpProxy(storage.store)), storage.close


def run_daily(defn: dict, *, root: Path = DEFAULT_ROOT, split: str, singles: bool, budget_s: float,
              base: str = BASE, system: str = "necklace_retest", limit: int = 30, path: str = "relay",
              engine=None, sample: tuple[int, int] | None = None, shared_cache: SharedMemberCache | None = None,
              require_room: bool = False, room=ledger_room) -> dict:
    """One scheduled retest of one necklace. path "relay" goes through the public relay (daily retests, self-tests);
    path "engine" calls through the same registered-agent engine as public runs (PM R26: one gate round takes the path
    users take, so the gate does not pass a path that public runs never use)."""
    from .judge import load_substitutes
    from .watch import load_json
    # the same runtime chain as the public path: watch demotions and exclusions, ops-approved substitutes
    watch_state = load_json(Path(root) / "watch" / "state.json", {})
    watch_state["substitutes"] = load_substitutes(Path(root) / "approvals.json")
    from .gold import GoldSetInvalid
    try:
        cases = load_cases(root, defn["slug"], split)[:limit]
    except GoldSetInvalid as exc:          # not run: no case line, so the judge holds it after 48 hours
        return {"slug": defn["slug"], "split": split, "cases": 0, "passed": 0, "not_run": str(exc), "path": path}
    started = time.monotonic()
    if require_room:                           # a deferred whole-set rerun starts only when it fits (PM 12:50)
        short = room(defn, len(cases), system)
        if short:
            return {"slug": defn["slug"], "split": split, "cases": 0, "passed": 0, "path": path,
                    "deferred": {"why": "provider_share", "short": short}}

    def measure(base_caller, pacer=None):
        source = shared_cache.wrap(base_caller) if shared_cache is not None else base_caller
        call = runner.budgeted_caller(source, system, provider_url)
        if sample is None:
            return run_set(defn, cases, call, root=root, split=split, singles=singles, budget_s=budget_s,
                           pacer=pacer, watch_state=watch_state, shared_cache=shared_cache)
        first, count = sample
        part = run_set(defn, cases[first:first + count], call, root=root, split=split, singles=singles,
                       budget_s=budget_s, pacer=pacer, watch_state=watch_state, shared_cache=shared_cache)
        if part["passed"] >= part["cases"]:
            return dict(part, sample=[first, count])
        short = room(defn, len(cases), system)
        if short:              # the whole set would be cut short by today's provider share: next free hour
            return dict(part, sample=[first, count], deferred={"why": "provider_share", "short": short})
        left = budget_s - (time.monotonic() - started)    # one failure: the whole set again (decision 1)
        whole = run_set(defn, cases, call, root=root, split=split, singles=False, budget_s=max(left, 0),
                        pacer=pacer, watch_state=watch_state, shared_cache=shared_cache)
        return dict(whole, sample=[first, count], sample_result=part, escalated=True)

    if path == "engine":
        close = None
        if engine is None:
            engine, close = open_engine()
        try:
            out = measure(runner.engine_caller(engine))
        finally:
            if close:
                close()
        return dict(out, path="engine")
    import httpx
    pacer = RelayPacer()
    with httpx.Client(timeout=12, headers={"User-Agent": "AgentValCon-NecklaceRetest/1.0"}) as client:
        out = measure(gateway_caller(client, base, pacer), pacer)
    return dict(out, path="relay")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a necklace on its gold set through the public relay.")
    parser.add_argument("slug")
    parser.add_argument("--split", default="tuning", choices=("tuning", "holdout-r1", "holdout-r2"))
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--singles", action="store_true", help="also run the single baseline (weekly)")
    parser.add_argument("--activate-planned", action="store_true",
                        help="treat planned AgentValCon fallbacks as active (self-test before the substitute gate)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--system", default="necklace_retest", choices=("necklace_retest", "gate", "adhoc"))
    parser.add_argument("--path", default="relay", choices=("relay", "engine"),
                        help="engine: the public run path on the operating store (ops, one gate round; PM R26)")
    args = parser.parse_args(argv)
    defn = next(d for d in model.load_valid() if d["slug"] == args.slug)
    if args.activate_planned:
        for slot in defn["slots"]:
            for m in slot["chain"]:
                if m["kind"] == "agentcon" and m.get("state") == "planned":
                    m["state"] = "active"
    if args.path == "engine":
        print(json.dumps(run_daily(defn, root=args.root, split=args.split, singles=args.singles,
                                   budget_s=BUDGET_SECONDS, system=args.system, limit=args.limit, path="engine"),
                         ensure_ascii=False))
        return 0
    import httpx
    pacer = RelayPacer()
    with httpx.Client(timeout=12, headers={"User-Agent": "AgentValCon-NecklaceRetest/1.0"}) as client:
        call = runner.budgeted_caller(gateway_caller(client, args.base, pacer), args.system, provider_url)
        result = run_set(defn, load_cases(args.root, args.slug, args.split)[:args.limit], call,
                         root=args.root, split=args.split, singles=args.singles, pacer=pacer)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

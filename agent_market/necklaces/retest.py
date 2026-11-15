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
import time
from pathlib import Path

from . import model, runner
from .judge import DEFAULT_ROOT, _iso

BASE = "https://agentconcierge.biz"
QA = "necklace_retest"
QA_GATE = "necklace_gate"           # gate rounds and the gate check (deploy/NECKLACE_GATE.md 3절)
BUDGET_SECONDS = 35 * 60
CONTRAST = {"package-risk-audit": "advisories", "cve-incident-brief": "record", "company-due-diligence": "background",
            "topic-evidence-brief": "papers"}


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


def gateway_caller(client, base: str = BASE, pacer: RelayPacer | None = None):
    pacer = pacer or RelayPacer()

    def rpc(url, method, params, timeout_s=12.0):
        if not pacer.take():
            raise _fail("relay_throttled", "local relay pace reached")
        r = client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                        headers={"Content-Type": "application/json", "Accept": "application/json",
                                 "MCP-Protocol-Version": "2025-06-18", "X-Agentcon-QA": QA},
                        timeout=max(0.5, timeout_s))
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 429:
            raise _fail("relay_throttled", "our relay rate limit")      # not the provider's pause
        if "result" not in data:
            err = data.get("error") or {}
            detail = err.get("data") if isinstance(err.get("data"), dict) else {}
            if detail.get("retry_after") or "pause" in str(err.get("message", "")).lower():
                raise _fail("PROVIDER_429", str(err.get("message")))   # the provider asked for a pause
            reason = r.headers.get("X-Execution-Error")
            ref = r.headers.get("X-Execution-Reference")
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


def grade_advisories(case, slot_out) -> bool:
    if not slot_out or slot_out.get("missing"):
        return False
    found = {i["id"].upper() for i in slot_out.get("items", [])}
    truth = case["truth"]["advisories"]
    if not truth:
        return True                       # a clean version: nothing to miss
    hit = sum(1 for adv in truth if {x.upper() for x in adv["ids"]} & found)
    return hit / len(truth) >= 0.9


def grade_health(case, slot_out) -> bool:
    latest = case["truth"].get("latest_version")
    return bool(slot_out) and not slot_out.get("missing") and bool(latest) and latest.lower() in _text(slot_out)


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
    ids = [case["truth"].get("lei"), case["truth"].get("cik")]
    return any(i and i.lower() in text for i in ids)


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
        return any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in company_words(case))
    text, wiki = _text(slot_out), case["truth"]["wiki"]
    if wiki["title"].lower() in text:
        return True
    words = {w for w in (wiki.get("description") or "").lower().split() if w not in STOP and len(w) > 2}
    return len([w for w in words if w in text]) >= 2


def grade_web(case, slot_out) -> bool:
    return bool(slot_out) and not slot_out.get("missing") and "https://" in _text(slot_out)


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


TASK_GRADERS = {"company-due-diligence": grade_company_task}


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


SINGLE_FROM_INPUT = {"legal_name": "name"}      # a single agent gets what the person typed instead of a staged value


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
    path = Path(root) / "gold" / slug / f"{split}.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if slug == "company-due-diligence":
        from .gold_filings import attach
        cases = attach(root, cases)
    return cases


def run_set(defn: dict, cases: list[dict], caller, *, root: Path = DEFAULT_ROOT, split: str = "tuning",
            singles: bool = False, budget_s: float = BUDGET_SECONDS, watch_state: dict | None = None,
            clock=time.monotonic, now=time.time, pacer: RelayPacer | None = None) -> dict:
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
        lines.append({"type": "case", "slug": defn["slug"], "version": defn["version"], "case_id": case["case_id"],
                      "set": split, "at": at, "ok": verdict["ok"], "completed": result["completed"],
                      "completed_external_only": result["completed_external_only"],
                      "latency_ms": result["latency_ms"], "slots": result["slots"], "graded": verdict["slots"]})
        for slot, attempts in result["attempts"].items():
            for a in attempts:
                lines.append({"type": "member", "slug": defn["slug"], "version": defn["version"], "slot": slot,
                              "resource_id": a["resource_id"], "tool": a["tool"], "kind": a["kind"], "at": at,
                              "ok": a["ok"], "contract_valid": a["error_class"] != "contract_invalid",
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


def daily_split(now: float) -> str:
    """The daily retest walks the 60 held-out cases in two days: r1 on even days, r2 on odd days."""
    return "holdout-r1" if int(now // 86400) % 2 == 0 else "holdout-r2"


def run_daily(defn: dict, *, root: Path = DEFAULT_ROOT, split: str, singles: bool, budget_s: float,
              base: str = BASE, system: str = "necklace_retest", limit: int = 30) -> dict:
    """One scheduled retest of one necklace through the public relay (same path as the CLI)."""
    import httpx
    from .judge import load_substitutes
    from .watch import load_json
    # the same runtime chain as the public path: watch demotions and exclusions, ops-approved substitutes
    watch_state = load_json(Path(root) / "watch" / "state.json", {})
    watch_state["substitutes"] = load_substitutes(Path(root) / "approvals.json")
    pacer = RelayPacer()
    with httpx.Client(timeout=12, headers={"User-Agent": "AgentValCon-NecklaceRetest/1.0"}) as client:
        call = runner.budgeted_caller(gateway_caller(client, base, pacer), system, provider_url)
        return run_set(defn, load_cases(root, defn["slug"], split)[:limit], call, root=root, split=split,
                       singles=singles, budget_s=budget_s, pacer=pacer, watch_state=watch_state)


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
    args = parser.parse_args(argv)
    defn = next(d for d in model.load_valid() if d["slug"] == args.slug)
    if args.activate_planned:
        for slot in defn["slots"]:
            for m in slot["chain"]:
                if m["kind"] == "agentcon" and m.get("state") == "planned":
                    m["state"] = "active"
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

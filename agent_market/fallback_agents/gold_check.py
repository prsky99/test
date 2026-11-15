"""Score fallback agents against a necklace gold set (workflow team, ``agent_market/necklaces/gold.py``).

    python -m agent_market.fallback_agents.gold_check nvd-cve cve-org cisa-kev --out report.json
    python -m agent_market.fallback_agents.gold_check github-advisory --out report.json

Only the ``tuning`` split is read unless ``--split`` names another; the held-out
rounds belong to the ops launch gate. Every case is a real call through the agent
(its pacing and cache included), so this is the same path a necklace slot uses.

Pass rules (per case):
- nvd-cve: CVSS version equal to the NVD truth and score within 0.1 (cvelistV5 truth when NVD had none).
- cve-org (PM 11-14): the score equals the value of the source it names, the CVE record's CNA or ADP
  block (``truth.cvss_record``), and that source is named; no score when the record has none.
- cisa-kev: ``kev`` equal to the truth (and the listing date when listed). EPSS is
  reported separately: same band (<0.01, 0.01-0.1, 0.1-0.5, >=0.5) as the truth; EPSS
  moves daily, so a band change is shown, not counted as a failure.
- github-advisory: every truth advisory group (aliases folded) that has a GHSA id is
  found (recall 1.0 over GHSA-coverable groups), and a clean truth gets no advisory.
  Recall over all groups (OSV-only PYSEC groups included) is reported too.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from .agents import FallbackAgents, FallbackUnavailable
from .catalog import SPECS, contract
from .net import budget

SLUG = {"gleif-lei": "company-due-diligence", "sec-edgar": "company-due-diligence",
        "wikipedia-summary": "topic-evidence-brief", "nvd-cve": "cve-incident-brief", "cve-org": "cve-incident-brief", "cisa-kev": "cve-incident-brief",
        "github-advisory": "package-risk-audit", "package-registry": "package-risk-audit",
        "depsdev-package": "package-risk-audit",
        "airport-lookup": "quakes-near-airport",   # workflow 11-15 (PM 13:58): OurAirports truth, gold_places
        "wikidata-book": "book-author-brief", "site-readiness": "website-trust-brief",   # ops 11-15 14:0x
        "rdap-domain": "website-trust-brief", "wiki-grounding": "topic-evidence-brief",
        "sec-filings": "company-due-diligence",                                          # ops 11-15 14:2x
        # one 30-case set is enough for a substitute verdict; the quake truth is the place, the quakes are live
        "usgs-quakes": "quakes-near-address",                                            # workflow 11-15
        "census-geocode": "quakes-near-address",   # split us-street: US street addresses (gold_places --us-streets)
        "arxiv-search": "topic-evidence-brief",    # PM 11-15 16:07: the paper phrase in a returned title
        "package-releases": "package-risk-audit",  # workflow 11-15 (meta seat of package-risk-audit v2)
        "software-incident": "cve-incident-brief",  # cve v2 fix seat; needs truth.fixes (first patched versions)
        "github-releases": "package-risk-audit",    # split holdout-v2-activity (gold_repos.py, workflow 9da8aa94)
        "gdelt-news": "topic-evidence-brief"}       # news seat (workflow 36fe030f): judged on the answer itself
BANDS = (0.01, 0.1, 0.5)


def band(x):
    if x is None:
        return None
    return sum(x >= b for b in BANDS)


def judge(agent_id: str, case: dict, result: dict | None) -> dict:
    truth = case["truth"]
    if result is None:
        return {"pass": False}
    if agent_id == "cve-org":
        # PM 11-14: the value must equal the value of the source it names (CNA or ADP in the CVE record).
        want = truth.get("cvss_record")
        if want is None or want.get("score") is None:
            return {"pass": result.get("cvss_score") is None, "got": [result.get("cvss_score"), result.get("source")],
                    "want": None}
        label = f"{str(want.get('from', '')).upper()} {want.get('provider', '')}"
        ok = (result.get("cvss_version") == want.get("version") and result.get("cvss_score") is not None
              and abs(result["cvss_score"] - float(want["score"])) <= 0.1 and label in str(result.get("source")))
        return {"pass": ok, "got": [result.get("cvss_score"), result.get("cvss_version"), result.get("source")],
                "want": [want.get("score"), want.get("version"), label]}
    if agent_id == "nvd-cve":
        want = truth["cvss"]
        ok = (result.get("cvss_version") == want.get("version") and result.get("cvss_score") is not None
              and abs(result["cvss_score"] - float(want["score"])) <= 0.1)
        return {"pass": ok, "got": [result.get("cvss_score"), result.get("cvss_version")],
                "want": [want.get("score"), want.get("version"), want.get("source")]}
    if agent_id == "cisa-kev":
        ok = result["kev"] == truth["kev"] and (not truth["kev"] or result.get("kev_date_added") == truth.get("kev_date_added"))
        return {"pass": ok, "epss_band_same": band(result.get("epss")) == band(truth.get("epss")),
                "epss_present": "epss" in result, "got": [result["kev"], result.get("kev_date_added"), result.get("epss")],
                "want": [truth["kev"], truth.get("kev_date_added"), truth.get("epss")]}
    if agent_id == "github-advisory":
        found = set()
        for item in result["items"]:
            found.add(item["id"])
            found.update(item.get("aliases") or [])
        groups, seen = [], set()
        for adv in truth["advisories"]:
            key = frozenset(adv["ids"])
            if key not in seen:
                seen.add(key)
                groups.append(key)
        coverable = [g for g in groups if any(i.startswith("GHSA-") for i in g)]
        hit = [g for g in groups if g & found]
        hit_cov = [g for g in coverable if g & found]
        ok = (len(hit_cov) == len(coverable)) and (bool(groups) or not result["items"])
        return {"pass": ok, "recall_all": round(len(hit) / len(groups), 3) if groups else None,
                "recall_ghsa": round(len(hit_cov) / len(coverable), 3) if coverable else None,
                "got": len(result["items"]), "want_groups": len(groups), "want_ghsa_groups": len(coverable)}
    if agent_id in ("gleif-lei", "sec-edgar"):
        # Each source is judged on the cases it can answer: an LEI for GLEIF, a CIK for SEC (None = not applicable).
        key, field = ("lei", "LEI") if agent_id == "gleif-lei" else ("cik", "SEC CIK")
        want = truth.get(key)
        if not want:
            return {"pass": None, "applicable": False}
        got = ((result or {}).get("identifiers") or {}).get(field)
        return {"pass": got == want, "applicable": True, "got": got, "want": want}
    if agent_id == "wikidata-book":
        # book-author-brief truth (Wikidata P50 and P577): the answer names the author and the publication year
        text = str((result or {}).get("answer") or "").lower()
        author, year = str(truth.get("author") or ""), truth.get("year")
        ok = bool(author) and author.lower() in text and (year is None or str(year) in text)
        return {"pass": ok, "got": text[:200], "want": [author, year]}
    if agent_id == "site-readiness":
        return judge_site(case, result)
    if agent_id == "rdap-domain":
        # website-trust-brief truth (an RDAP registration event): the registration date and the registrar
        text = str((result or {}).get("answer") or "")
        date, registrar = str(truth.get("registered") or ""), str(truth.get("registrar") or "")
        ok = bool(date) and date in text and (not registrar or registrar.lower() in text.lower())
        return {"pass": ok, "got": text[:200], "want": [date, registrar]}
    if agent_id == "wiki-grounding":
        # topic-evidence-brief truth: the topic's Wikipedia article is among the quoted sources
        want = (truth.get("wiki") or {}).get("title")
        sources = [str(u) for u in (result or {}).get("sources") or []]
        from urllib.parse import unquote
        link = "https://en.wikipedia.org/wiki/" + str(want or "").replace(" ", "_")
        ok = bool(want) and any(unquote(u.split("#")[0]).replace(" ", "_") == link for u in sources)
        return {"pass": ok, "got": sources[:5], "want": link}
    if agent_id == "gdelt-news":
        # News has no fixed truth: at least 3 items with an https link and a date in the last 8 days, and at least one
        # title carrying a word of the topic (4 letters or more); judged at grading time against the clock
        import re as _re
        from datetime import datetime as _dt, timezone as _tz
        words = {w for w in _re.findall(r"[a-z0-9]+", str((case.get("input") or {}).get("topic") or "").lower()) if len(w) >= 4}
        now = _dt.now(_tz.utc)
        fresh = []
        for item in (result or {}).get("items") or []:
            try:
                when = _dt.strptime(str(item.get("published")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
            except ValueError:
                continue
            if str(item.get("url") or "").startswith("https://") and (now - when).days <= 8:
                fresh.append(item)
        on_topic = [i for i in fresh if words & set(_re.findall(r"[a-z0-9]+", str(i.get("title") or "").lower()))]
        return {"pass": len(fresh) >= 3 and bool(on_topic), "fresh": len(fresh), "on_topic": len(on_topic)}
    if agent_id == "software-incident":
        # every first patched version the truth names must be among the answer's packages (same name, same version)
        got = {(str(p.get("name")).lower(), p.get("first_patched_version")) for p in (result or {}).get("packages") or []
               if isinstance(p, dict)}
        want = [(str(f.get("name")).lower(), f.get("first_patched_version")) for f in truth.get("fixes") or []]
        return {"pass": bool(want) and all(w in got for w in want), "got": sorted(map(str, got))[:10], "want": want}
    if agent_id == "github-releases":
        # gold_repos truth: the latest GitHub release tag, or no releases at all (github_releases false)
        if truth.get("github_releases") is False or not truth.get("latest_release_tag"):
            ok = not (result or {}).get("latest_tag") and "no GitHub releases" in str((result or {}).get("answer") or "")
            return {"pass": ok, "got": (result or {}).get("latest_tag"), "want": None}
        return {"pass": (result or {}).get("latest_tag") == truth["latest_release_tag"],
                "got": (result or {}).get("latest_tag"), "want": truth["latest_release_tag"]}
    if agent_id == "arxiv-search":
        # topic-evidence-brief truth gives a paper phrase (its papers are OpenAlex's most cited, which arXiv does not
        # hold): a returned paper with an https link must carry the phrase, or the asked topic, as a phrase in its
        # title: words next to each other in order (a two-word phrase may be reversed: "ageing population"), hyphens
        # and a plural s aside. Loose words do not count (PM 16:12 check: "...with an ageing sexual population").
        import re as _re

        def words(text):
            return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _re.findall(r"[a-z0-9]+", str(text).lower())]

        def has(title, phrase):
            t, p = words(title), words(phrase)
            if not p:
                return False
            orders = [p, p[::-1]] if len(p) == 2 else [p]
            return any(t[i:i + len(o)] == o for o in orders for i in range(len(t) - len(o) + 1))
        phrases = [x for x in (truth.get("paper_phrase"), (case.get("input") or {}).get("topic")) if x]
        items = [i for i in (result or {}).get("items") or [] if isinstance(i, dict)]
        hits = [i for i in items if str(i.get("url") or "").startswith("https://")
                and any(has(i.get("title") or "", ph) for ph in phrases)]
        return {"pass": bool(hits), "got": [i.get("title") for i in items[:5]], "want": phrases}
    if agent_id == "sec-filings":
        # company-due-diligence truth (EDGAR CIK): the filer the answer matched is that CIK
        want = str(truth.get("cik") or "").lstrip("0")
        text = str((result or {}).get("answer") or "")
        if truth.get("sec_registered") is False:     # holdout-r3-sec: no registration is the right answer (workflow)
            return {"pass": "no sec edgar registration" in text.lower() and "(SEC CIK" not in text,
                    "got": text[:160], "want": "no registration"}
        return {"pass": bool(want) and f"(SEC CIK {want})" in text, "got": text[:160], "want": want}
    if agent_id == "wikipedia-summary":
        want = (truth.get("wiki") or {}).get("title")
        return {"pass": bool(want) and (result or {}).get("title") == want, "got": (result or {}).get("title"), "want": want}
    if agent_id == "usgs-quakes":
        # the quake part of quakes-near-address: events against USGS asked when graded (retest.grade_quakes: none
        # beyond the radius, the strongest sure event present); not graded when USGS cannot be read
        from agent_market.necklaces import retest
        if retest.quakes_reference(truth) is None:
            return {"pass": None, "applicable": False, "why": "reference_unavailable"}
        return {"pass": retest.grade_quakes(case, result)}
    if agent_id == "census-geocode":
        return judge("airport-lookup", case, result)      # the same point check: lat/lon within the case tolerance
    if agent_id == "airport-lookup":
        # The airport's reference point within the case tolerance (5 km) of OurAirports, read from the answer's
        # "lat X lon Y" or structured lat/lon (workflow 11-15, the same truth quakes-near-airport grades with).
        import math
        import re as _re
        text = json.dumps(result, ensure_ascii=False, default=str)
        found = _re.search(r"\blat(?:itude)?\b[\"\s:=]*(-?\d+(?:\.\d+)?)[\"\s,;]+lon(?:gitude)?\b[\"\s:=]*"
                           r"(-?\d+(?:\.\d+)?)", text, _re.I)
        if not found:
            return {"pass": False, "got": None, "want": [truth["lat"], truth["lon"]]}
        lat, lon = float(found.group(1)), float(found.group(2))
        p1, p2 = math.radians(lat), math.radians(truth["lat"])
        a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(truth["lon"] - lon) / 2) ** 2
        km = 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))
        return {"pass": km <= truth.get("tolerance_km", 5), "km": round(km, 2), "got": [lat, lon],
                "want": [truth["lat"], truth["lon"]]}
    if agent_id in ("package-registry", "depsdev-package", "package-releases"):
        # Gold truth is the registry's latest version at build time; a release since then shows as a miss
        # and is listed, not hidden.
        return {"pass": result.get("latest_version") == truth.get("latest_version"),
                "got": result.get("latest_version"), "want": truth.get("latest_version"),
                "signals": sorted(k for k in result if k != "source")}
    raise ValueError(agent_id)


def role_task_check(agent_ids, agents: FallbackAgents | None = None, before_call=None) -> dict:
    """Run the workflow team's fixed role tasks (role_tasks/role-tasks-v1.jsonl) for each agent's contract.
    BEFORE_CALL(agent_id), when given, runs before each call outside its budget (the gate's pacing, ops 11-15:
    arxiv-search's role tasks failed 0/3 when they ran right after the cases)."""
    from ..necklaces import role_tasks
    from urllib.parse import urlsplit
    from .net import get
    agents = agents or FallbackAgents()
    out = {}
    for agent_id in agent_ids:
        rows = []
        rag = Path(role_tasks.FILE).with_name("role-tasks-rag-v1.jsonl")  # search & RAG's verified tasks
        cases = role_tasks.load() + (role_tasks.load(rag) if rag.exists() else [])
        for case in cases:
            if case["contract"] != SPECS[agent_id]["contract"]:
                continue
            try:
                if before_call:
                    before_call(agent_id)
                result = agents.execute(agent_id, case["input"])["result"]
            except FallbackUnavailable as exc:
                rows.append({"case_id": case["case_id"], "pass": False, "error": exc.code})
                continue
            ok, why = role_tasks.score(case, json.dumps(result), result)
            for field, url in ((case.get("expect") or {}).get("dynamic") or {}).items():
                # Only registry "latest" checks run here; other live references (e.g. a weather service this
                # project does not use) are listed as not checked, never as passed.
                # Only a registry "latest" document compares field-for-field with a version; anything else is
                # listed as not checked rather than passed vacuously.
                if not isinstance(url, str) or urlsplit(url).hostname not in ("registry.npmjs.org", "pypi.org"):
                    if isinstance(url, str):
                        why = why + [f"{field}: live reference {urlsplit(url).hostname} not checked"]
                    continue
                live = json.loads(get(url, limiters=agents.limiters, seconds=5, limit=1 << 20).content)
                if result.get(field) != live.get("version"):
                    ok, why = False, why + [f"{field} {result.get(field)} != live {live.get('version')}"]
            rows.append({"case_id": case["case_id"], "pass": ok, "why": why})
        out[agent_id] = {"passed": sum(r["pass"] for r in rows), "cases": len(rows), "rows": rows}
    return out


def budget_system(split: str) -> str:
    """Held-out rounds are gate runs (ops 11-14); tuning runs are our own readiness tests."""
    return "gate" if split.startswith("holdout") else "substitute_tests"


def site_truth(domain: str, agents: FallbackAgents | None = None) -> dict:
    """What the website serves at grading time, read again by the grader (ops 11-15): robots.txt text (None when it
    could not be read, with the reason), and whether llms.txt and sitemap.xml are served (None when unknown). A fresh
    reader with no cache, through the same public-address and same-site redirect checks as the agent."""
    reader = agents or FallbackAgents()
    left = lambda: 20.0
    base = f"https://{domain}"
    robots, why = reader._site_get(base + "/robots.txt", left, domain)
    out = {"robots": robots, "robots_note": why}
    for name, path in (("llms_txt", "/llms.txt"), ("sitemap_xml", "/sitemap.xml")):
        body, note = reader._site_get(base + path, left, domain)
        if body is not None:
            out[name] = True if name == "llms_txt" else ("<sitemapindex" in body[:2000] or "<urlset" in body[:2000])
        else:
            out[name] = False if note and note.startswith("HTTP 4") else None
    return out


def judge_site(case: dict, result: dict | None, truth: dict | None = None) -> dict:
    """website.ai_readiness.v1 against the site itself at grading time (website-trust-brief, ops 11-15).

    - robots.txt present must agree with the grader's read. When the grader cannot read it either (5xx, time-out,
      redirect off the site), the case passes only if the agent also says it could not read it (the case still
      counts: telling "unreadable" apart from "absent" is part of the task).
    - every crawler the agent lists (GPTBot, ClaudeBot, anthropic-ai, Google-Extended, PerplexityBot, CCBot) must have
      the grader's allowed/blocked verdict for the site root, by urllib.robotparser on the grader's copy.
    - llms.txt and sitemap.xml presence must agree where both sides know it (the agent's None, a file robots.txt
      kept it from reading, and the grader's None are not compared)."""
    from urllib.robotparser import RobotFileParser
    signals = (result or {}).get("signals") or {}
    domain = case["input"]["domain"].strip().lower()
    truth = truth if truth is not None else site_truth(domain)
    problems = []
    agent_robots = (signals.get("robots_txt") or {}).get("present")
    if truth["robots"] is None and not str(truth.get("robots_note") or "").startswith("HTTP 4"):
        ok = agent_robots is False and str((signals.get("robots_txt") or {}).get("note") or "") != ""
        return {"pass": ok, "got": signals.get("robots_txt"), "want": {"robots_txt": "unreadable"}}
    if bool(agent_robots) != (truth["robots"] is not None):
        problems.append("robots_txt")
    if truth["robots"] is not None:
        parser = RobotFileParser()
        parser.parse(truth["robots"].splitlines())
        for bot, verdict in (signals.get("ai_crawlers") or {}).items():
            want = "allowed" if parser.can_fetch(bot, f"https://{domain}/") else "blocked"
            if not str(verdict).startswith(want):
                problems.append(bot)
    for name in ("llms_txt", "sitemap_xml"):
        got = (signals.get(name) or {}).get("present")
        if got is not None and truth.get(name) is not None and bool(got) != truth[name]:
            problems.append(name)
    return {"pass": not problems and bool(signals), "problems": problems}


def case_arguments(agent_id: str, case: dict) -> dict:
    """The tool arguments for a gold case: the case input cut to the slot contract's fields, with the necklace
    names mapped to the contract's (topic-evidence-brief gives ``topic``; encyclopedia.summary.v1 takes
    ``title``). One function for tuning runs and the ops gate (scripts.substitute_gate), so both call the agent
    the same way."""
    allowed = contract(SPECS[agent_id]["contract"])["input_schema"]["properties"]
    if agent_id == "usgs-quakes":
        # in the necklace it reads the place the location step resolved; alone it gets the truth point (workflow)
        truth = case["truth"]
        return {"lat": truth["lat"], "lon": truth["lon"], "radius_km": truth["radius_km"], "days": truth["days"],
                "min_magnitude": truth["min_magnitude"], "limit": 20}
    arguments = {k: v for k, v in case["input"].items() if k in allowed}
    if "title" in allowed and "title" not in arguments and case["input"].get("topic"):
        arguments["title"] = case["input"]["topic"]
    if agent_id == "software-incident" and case["input"].get("cve_id"):
        arguments = {"query": case["input"]["cve_id"]}                       # software.incident.v1 takes a query
    if agent_id == "github-releases":
        # the seat's input is the repository the package step found (gold_repos truth); nothing else is given
        repo = (case.get("truth") or {}).get("repository_github")
        arguments = {"repo": repo} if repo else {}
    if agent_id in ("arxiv-search", "gdelt-news") and "query" not in arguments and case["input"].get("topic"):
        arguments["query"] = case["input"]["topic"]                         # papers.search.v1 takes a query
    if "question" in allowed and "question" not in arguments and case["input"].get("topic"):
        arguments["question"] = f"What is {case['input']['topic']}?"        # web.grounding.v1 takes a question
    if "company" in allowed and "company" not in arguments and case["input"].get("name"):
        arguments["company"] = case["input"]["name"]                       # sec.filings.v1: the company name only
    return arguments


def applies(agent_id: str, case: dict) -> bool:
    """False when the source cannot answer the case at all (no LEI for GLEIF, no CIK for SEC): no call is made."""
    if agent_id in ("gleif-lei", "sec-edgar"):
        return bool((case.get("truth") or {}).get("lei" if agent_id == "gleif-lei" else "cik"))
    if agent_id == "sec-filings":
        truth = case.get("truth") or {}
        return bool(truth.get("cik")) or truth.get("sec_registered") is False
    if agent_id == "arxiv-search":
        return bool((case.get("truth") or {}).get("paper_phrase"))
    if agent_id == "software-incident":
        return (case.get("truth") or {}).get("fixes") is not None
    if agent_id == "gdelt-news":
        return bool((case.get("input") or {}).get("topic"))
    if agent_id == "github-releases":
        return bool((case.get("truth") or {}).get("repository_github"))
    if agent_id == "package-releases":   # npm only until PyPI's terms are read (11-16)
        return (case.get("input") or {}).get("ecosystem") == "npm"
    if agent_id == "census-geocode":                     # US addresses only (its coverage)
        return (case.get("truth") or {}).get("country") == "US" or str(case["input"].get("address", "")).endswith("USA")
    if agent_id == "rdap-domain":
        return bool((case.get("truth") or {}).get("registered"))
    if agent_id == "wiki-grounding":
        return bool(((case.get("truth") or {}).get("wiki") or {}).get("title"))
    if agent_id == "site-readiness":   # every site applies; an unreadable robots.txt is graded in judge_site
        return bool((case.get("input") or {}).get("domain"))
    return True


def check(agent_ids, root: Path, split: str = "tuning", agents: FallbackAgents | None = None,
          pause: float = 0.0, sleep=time.sleep, limit: int | None = None, offset: int = 0,
          quiet=None, clock=time.time) -> dict:
    """QUIET(ts) -> True stops the run before the next case (the CLI passes the measurement windows)."""
    with budget(budget_system(split)):
        return _check(agent_ids, root, split, agents, pause, sleep, limit, offset, quiet, clock)


def _check(agent_ids, root, split, agents, pause, sleep, limit=None, offset=0, quiet=None, clock=time.time):
    agents = agents or FallbackAgents()
    report = {"split": split, "agents": {}}
    for agent_id in agent_ids:
        path = root / "gold" / SLUG[agent_id] / f"{split}.jsonl"
        cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows, run, seen = [], 0, 0
        for case in cases:
            if not applies(agent_id, case):
                rows.append({"case_id": case["case_id"], "stratum": case.get("stratum"), "ms": 0, "error": None,
                             "cache": None, "pass": None, "applicable": False})
                continue
            seen += 1
            if seen <= offset or (limit is not None and run >= limit):  # the daily test share is small; the rest waits for another day
                continue
            if quiet and quiet(clock()):  # never measure inside the public measurement windows (PM 11-14)
                report["stopped"] = "quiet_window"
                continue
            run += 1
            started = time.monotonic()
            result, code, cache = None, None, None
            arguments = case_arguments(agent_id, case)
            try:
                envelope = agents.execute(agent_id, arguments)
                result, cache = envelope["result"], envelope["cache"]["status"]
            except FallbackUnavailable as exc:
                code = exc.code
            row = {"case_id": case["case_id"], "stratum": case.get("stratum"), "ms": int((time.monotonic() - started) * 1000),
                   "error": code, "cache": cache, **judge(agent_id, case, result)}
            rows.append(row)
            if pause:
                sleep(pause)
        ms = [r["ms"] for r in rows if r["error"] is None and r.get("applicable", True)]
        applicable = [r for r in rows if r.get("applicable", True)]
        summary = {"cases": len(applicable), "passed": sum(bool(r["pass"]) for r in applicable),
                   "not_applicable": len(rows) - len(applicable),
                   "not_run": len(cases) - len(rows),
                   "errors": {c: sum(r["error"] == c for r in rows) for c in {r["error"] for r in rows if r["error"]}},
                   "p50_ms": int(statistics.median(ms)) if ms else None,
                   "p95_ms": int(sorted(ms)[max(0, int(len(ms) * 0.95 + 0.5) - 1)]) if ms else None,
                   "gold_sha256": None}
        manifest = root / "gold" / SLUG[agent_id] / "manifest.json"
        if manifest.exists():
            summary["gold_sha256"] = json.loads(manifest.read_text())["files"].get(split, {}).get("sha256")
            summary["gold_created_at"] = json.loads(manifest.read_text()).get("created_at")
        if agent_id == "cisa-kev":
            summary["epss_band_same"] = sum(bool(r.get("epss_band_same")) for r in rows)
            summary["epss_present"] = sum(bool(r.get("epss_present")) for r in rows)
        report["agents"][agent_id] = {"summary": summary, "cases": rows}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score AgentValCon fallback agents against a necklace gold set.")
    parser.add_argument("agents", nargs="+", choices=sorted(SLUG))
    parser.add_argument("--root", type=Path, default=Path("gateway-data/necklaces"))
    parser.add_argument("--split", default="tuning")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pause", type=float, default=0.0, help="seconds between cases")
    parser.add_argument("--role-tasks", action="store_true", help="also run the fixed role tasks")
    parser.add_argument("--limit", type=int, default=None, help="run at most N applicable cases per agent")
    parser.add_argument("--offset", type=int, default=0, help="skip the first N applicable cases (another day's share)")
    args = parser.parse_args(argv)
    from ..necklaces.watch import in_quiet_window
    if in_quiet_window(time.time()):
        parser.exit(75, "measurement window (:55-:10, 03:50-05:10): try again later\n")
    report = check(args.agents, args.root, args.split, pause=args.pause, limit=args.limit, offset=args.offset,
                   quiet=in_quiet_window)
    if args.role_tasks:
        with budget(budget_system(args.split)):
            report["role_tasks"] = role_task_check(args.agents)
        print(json.dumps({k: [v["passed"], v["cases"]] for k, v in report["role_tasks"].items()}))
    report["at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v["summary"] for k, v in report["agents"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

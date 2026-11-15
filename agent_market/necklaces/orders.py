"""After a necklace request is received (PM 11-15 14:57 part 3; plan reports/necklace-promotion-orders-2026-11-15 3.3).

Growth takes the request (task, example_input, wanted_output; no contact, user decision 11-10 and PM option A) and
stores it in customer_inquiries under necklace_order with a receipt number and a status address. This module does the
step after that, without touching the production database:

- ``classify``: which of three a request is, with the reason:
  existing (a necklace with every role it needs; offered now, or still in its tests -> building),
  buildable (two or three roles, each with a final pearl; roles whose pearl is still provisional -> reviewing),
  cannot_build (needs writes, payments or messages; one role is enough, so the single pearl is the answer; a role has
  no verified agent; more than three roles, the required-slot cap; or no known role, which a person reads).
- ``notice``: the bundle for the finished notice on the status page: the necklace address, how to run it (HTTP, MCP,
  A2A), the measured value (judge snapshot ``comparison``, only after the gate), scope and limits, and fallback depth.
  Everything comes from the same snapshot the pages read (necklace_surface), so the notice and the page agree.

Both print JSON plus one English paragraph the operator pastes as the answer in the console's requests tab.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .judge import DEFAULT_ROOT

DEFINITIONS = Path(__file__).resolve().parent / "definitions"
ROLE_GROUPS = Path("reports/pearls-2026-11-14/role_groups.json")
BASE = "https://agentconcierge.biz"
MAX_ROLES = 3                                   # runner MAX_REQUIRED_SLOTS

# Words that name what a role does, matched as whole words in the request (lower case). Kept narrow: a request
# that matches nothing goes to a person, which is better than a wrong "we cannot".
ROLE_WORDS = {
    "airport.lookup.v1": r"airports?|iata|icao",
    "book.search.v1": r"books?|isbn|novels?|first published|publication year",
    "company.registry.v1": r"company registry|registered company|legal entity|lei|incorporat\w*",
    "country.indicator.v1": r"gdp|inflation rate|population of|unemployment|economic indicators?",
    "crypto.price.v1": r"crypto\w*|bitcoin|ethereum|token price",
    "cve.exploited.v1": r"exploited|kev",
    "cve.record.v1": r"cve(?:-\d{4}-\d+)?|cvss|vulnerabilit(?:y|ies)",
    "dictionary.define.v1": r"defin(?:e|ition)s?|meaning of (?:the )?word|dictionary",
    "domain.lookup.v1": r"whois|domain registration|registrar|domain age|rdap",
    "earthquake.feed.v1": r"earthquakes?|quakes?|seismic",
    "encyclopedia.summary.v1": r"wikipedia|encyclopedia|biograph\w*|background on|about the author",
    "events.search.v1": r"events? near|concerts?|meetups?|conferences?",
    "fx.rate.v1": r"exchange rates?|fx|currency conversion|convert (?:usd|eur|jpy|krw)",
    "geocode.address.v1": r"address(?:es)?|geocod\w*|coordinates|latitude|longitude|landmark",
    "github.repo.v1": r"github|repositor(?:y|ies)|stars and forks",
    "holiday.calendar.v1": r"public holidays?|bank holidays?|holidays?",
    "ip.lookup.v1": r"ip address|ip lookup|geolocate (?:an )?ip",
    "news.search.v1": r"news|headlines|articles? (?:about|on)",
    "package.advisories.v1": r"advisor(?:y|ies)|security advisor\w*|osv",
    "package.health.v1": r"maintenance|maintained|downloads|last release",
    "package.risk.v1": r"npm|pypi|package risk|dependency risk",
    "papers.search.v1": r"papers?|research|arxiv|studies|scholarly|citations?",
    "place.search.v1": r"restaurants?|places? near|points? of interest|cafes?|shops? near",
    "sec.filings.v1": r"sec filings?|10-k|10-q|20-f|edgar|cik",
    "software.incident.v1": r"outages?|status page|incidents?",
    "stock.quote.v1": r"stock price|share price|ticker price|stock quote",
    "timezone.time.v1": r"time ?zones?|local time|utc offset",
    "translate.text.v1": r"translat\w*",
    "unit.convert.v1": r"convert units?|unit conversion|miles to|kg to|celsius|fahrenheit",
    "weather.forecast.v1": r"weather|forecast|temperature",
    "web.grounding.v1": r"web search|search the web|grounded answer|sources on the web",
    "website.ai_readiness.v1": r"robots\.txt|crawlers?|llms\.txt|ai readiness",
}
_ROLE_RE = {role: re.compile(r"\b(?:" + words + r")\b", re.I) for role, words in ROLE_WORDS.items()}
# Writes, payments and messages: never built (read-only members only, project rule).
WRITES = re.compile(r"\b(?:send (?:an? )?(?:email|e-mail|sms|message|text)|post (?:to|on)|tweet|publish|pay|payments?|"
                    r"buy|purchase|place an order|book (?:a|the) (?:flight|hotel|table|room)|transfer (?:money|funds)|"
                    r"trade|sell|delete|sign up|create an account|submit (?:a|the) form|register me)\b", re.I)

ANSWERS = {
    "existing": "A necklace already does this: {name}. Run it at {url}.",
    "building": "A necklace for this is being tested: {name} ({url}). We will put its address and what we measured here once it passes its gate.",
    "buildable": "We can build this from agents we have tested ({roles_text}). We will build and test it, then answer here with its address, how to run it and what we measured.",
    "reviewing": "Parts of this have tested agents; {pending} still needs more tests before we can build on it. We will answer here when that is settled.",
    "needs_writes_or_payments": "We cannot build this: it needs an agent to send, buy, pay, post or change something, and our necklaces only read.",
    "one_agent_enough": "One tested agent already does this, so a necklace would add nothing: {card}.",
    "no_verified_agent_for": "We cannot build this yet: we have no verified agent for {missing}. We keep testing agents and will say so here if that changes.",
    "too_many_parts": "We cannot build this as one necklace: it needs {count} different kinds of agent and a necklace holds at most 3.",
    "needs_review": "A person on our team is reading this request; we will answer here.",
}
ROLE_NAMES = {role: role.rsplit(".v", 1)[0].replace(".", " ").replace("_", " ") for role in ROLE_WORDS}


# What the operator sets in the console (customer_inquiries status and admin_response, growth 11-15): the status page
# shows admin_response as written, so the step is the paragraph's first words; settled answers are resolved.
CONSOLE_STATUS = {"reviewing": "in_progress", "building": "in_progress", "live": "resolved", "cannot_build": "resolved"}
STEP_WORDS = {"reviewing": "Reviewing", "building": "Building", "live": "Live", "cannot_build": "Cannot build"}


def console(status: str, answer: str) -> dict:
    return {"console_status": CONSOLE_STATUS[status], "admin_response": f"{STEP_WORDS[status]}: {answer}"}


def roles_in(request: dict) -> list[str]:
    text = " ".join(str(request.get(k) or "") for k in ("task", "example_input", "wanted_output"))
    found = [role for role, rx in _ROLE_RE.items() if rx.search(text)]
    if "cve.exploited.v1" in found and "cve.record.v1" not in found:
        found.append("cve.record.v1")
    if "package.risk.v1" in found and {"package.advisories.v1", "package.health.v1"} & set(found):
        found.remove("package.risk.v1")             # the narrower roles say what is wanted
    return sorted(found)


def load_definitions(folder: Path = DEFINITIONS) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(folder).glob("*.json"))]


def load_snapshot(root: Path = DEFAULT_ROOT) -> dict:
    from ..concierge import necklace_surface
    return necklace_surface.load(Path(root) / "necklaces.json")


def load_roles(path: Path = ROLE_GROUPS) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("roles") or {}
    except (OSError, ValueError):
        return {}


def _entry(snapshot: dict, slug: str) -> dict | None:
    return next((e for e in snapshot.get("necklaces") or [] if isinstance(e, dict) and e.get("slug") == slug), None)


def alternatives(found: list[str], definitions: list[dict], snapshot: dict, roles: dict, base: str = BASE,
                 limit: int = 3) -> list[dict]:
    """What the requester can use instead (PM 15:11): offered necklaces covering part of the request first, then the
    pearl of each role it names. Necklaces still in their tests are not offered as an alternative."""
    from ..concierge import necklace_surface
    out = []
    for d in definitions:
        part = set(found) & {s["contract"] for s in d["slots"]}
        entry = _entry(snapshot, d["slug"])
        if part and entry and necklace_surface.offered(entry):
            out.append({"kind": "necklace", "slug": d["slug"], "url": f"{base}/necklaces/{d['slug']}",
                        "text": f"the necklace {d.get('name') or d['slug']} ({base}/necklaces/{d['slug']}) for "
                                + ", ".join(ROLE_NAMES[r] for r in sorted(part))})
    for r in found:
        pearl = (roles.get(r) or {}).get("final_pearl")
        if pearl:
            out.append({"kind": "agent", "resource_id": pearl, "url": f"{base}/agent/{pearl}",
                        "text": f"a tested agent for {ROLE_NAMES[r]} ({base}/agent/{pearl})"})
    return out[:limit]


def classify(request: dict, definitions: list[dict], snapshot: dict, roles: dict, base: str = BASE) -> dict:
    """{class, status, reason, roles, ..., answer}; status follows growth's steps (reviewing, building, live,
    cannot_build)."""
    from ..concierge import necklace_surface
    found = roles_in(request)
    text = " ".join(str(request.get(k) or "") for k in ("task", "wanted_output"))

    def out(cls, status, reason, **extra):
        answer = ANSWERS[reason].format(**{k: v for k, v in extra.items() if isinstance(v, (str, int))})
        if status == "cannot_build" and reason != "one_agent_enough":
            alt = alternatives(found, definitions, snapshot, roles, base)
            if alt:
                extra["alternatives"] = alt
                answer += " Instead you can use: " + "; ".join(a["text"] for a in alt) + "."
        return {"class": cls, "status": status, "reason": reason, "roles": found, **extra, "answer": answer,
                **console(status, answer)}
    if WRITES.search(text):
        return out("cannot_build", "cannot_build", "needs_writes_or_payments")
    if not found:
        return out("cannot_build", "reviewing", "needs_review")
    covering = [d for d in definitions if set(found) <= {s["contract"] for s in d["slots"]}]
    if covering:
        covering.sort(key=lambda d: len(d["slots"]))
        best = None
        for d in covering:
            entry = _entry(snapshot, d["slug"])
            if entry and necklace_surface.offered(entry):
                best = (d, entry)
                break
        d = best[0] if best else covering[0]
        url = base + "/necklaces/" + d["slug"]
        if best:
            return out("existing", "live", "existing", necklace=d["slug"], name=d.get("name") or d["slug"], url=url)
        return out("existing", "building", "building", necklace=d["slug"], name=d.get("name") or d["slug"], url=url)
    if len(found) > MAX_ROLES:
        return out("cannot_build", "cannot_build", "too_many_parts", count=len(found))
    final = {r: (roles.get(r) or {}).get("final_pearl") for r in found}
    provisional = {r: (roles.get(r) or {}).get("provisional_pearl") for r in found}
    missing = [r for r in found if not final[r] and not provisional[r]]
    if missing:
        return out("cannot_build", "cannot_build", "no_verified_agent_for", missing=", ".join(ROLE_NAMES[r] for r in missing),
                   missing_roles=missing)
    if len(found) == 1:
        role = found[0]
        pearl = final[role] or provisional[role]
        return out("cannot_build", "cannot_build", "one_agent_enough", pearl=pearl, card=f"{base}/agent/{pearl}")
    pending = [r for r in found if not final[r]]
    if pending:
        return out("buildable", "reviewing", "reviewing", pearls={r: final[r] or provisional[r] for r in found},
                   pending=", ".join(ROLE_NAMES[r] for r in pending), pending_roles=pending)
    return out("buildable", "building", "buildable", pearls=final, roles_text=", ".join(ROLE_NAMES[r] for r in found))


def _n(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def full_line(value: dict | None) -> str | None:
    """The full value (PM 15:11) in one sentence, saying which parts are estimates; None when not measured."""
    full = (value or {}).get("without_full") if isinstance(value, dict) else None
    if not isinstance(full, dict) or not isinstance(value.get("with"), dict):
        return None
    w = value["with"]
    est = " (finding sizes estimated)" if full.get("estimated") else ""
    return (f"Counting the finding of agents and the merging of their answers too{est}: about "
            f"{format(round(full['tokens']), ',')} \u2192 {format(round(w['tokens']), ',')} tokens and "
            f"{format(round(full['seconds'], 1), 'g')} s \u2192 {format(round(w['seconds'], 1), 'g')} s.")


def notice(slug: str, snapshot: dict, base: str = BASE) -> dict:
    """The finished-notice bundle for the status page, from the snapshot the pages read; refused unless offered."""
    from ..concierge import necklace_surface
    entry = _entry(snapshot, slug)
    if not entry:
        raise LookupError(f"{slug} is not in the snapshot")
    if not necklace_surface.offered(entry):
        raise LookupError(f"{slug} is not offered (status {entry.get('status')}); the notice waits for its gate")
    item = necklace_surface.public_item(entry, base)
    example = necklace_surface.example_input(entry) or {}
    run = {"http": {"method": "POST", "url": f"{base}/api/necklaces/{slug}/run", "json": {"input": example}},
           "mcp_tool": item.get("mcp_tool"), "a2a_skill": item.get("a2a_skill"), "page": item.get("url")}
    value = item.get("comparison")
    measured = necklace_surface.comparison_line(entry) if value and hasattr(necklace_surface, "comparison_line") else None
    fallback = item.get("fallback") or {}
    limits = [x for x in (item.get("scope_notice"), necklace_surface.free_now(entry)) if x]
    pearls = item.get("pearls") or []
    lines = [f"Your necklace is ready: {entry.get('name') or slug}.",
             f"Address: {item.get('url')}.",
             f"How to use it: a person opens {item.get('url')} and fills in the form; an agent calls the MCP tool "
             f"{run['mcp_tool']} or the A2A skill {run['a2a_skill']}; over HTTP, POST {run['http']['url']} with the JSON "
             f"body {json.dumps(run['http']['json'], ensure_ascii=False)}.",
             measured or "Not measured yet against calling the agents directly; the numbers appear on the necklace "
                         "page once they are.",
             *([full_line(entry.get("comparison"))] if value and full_line(entry.get("comparison"))
               and "Including finding" not in (measured or "") else []),     # growth 4737338c says it in the line
             "Scope and limits: " + " ".join(limits or ["no limits stated beyond the input form."])]
    steps = [f"{p.get('role') or 'step'}: {_n(p['alternates']['external'], 'other agent')}, {p['alternates']['agentcon']} of ours"
             for p in pearls if p.get("alternates")]
    page_line = necklace_surface.fallback_line(entry)
    if steps or page_line:
        lines.append(" ".join(x for x in (page_line, ("Tested fallbacks per step: " + "; ".join(steps) + ".")
                                          if steps else None) if x))
    else:
        lines.append("Fallbacks: none tested yet; if an agent fails, that step fails.")
    return {"slug": slug, "address": item.get("url"), "run": run, "comparison": entry.get("comparison") if value else None, "scope_notice": item.get("scope_notice"),
            "limits": limits, "fallback": fallback, "answer": " ".join(lines), **console("live", " ".join(lines))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify", help="classify one request (a JSON file with task, example_input, wanted_output)")
    c.add_argument("request", type=Path)
    n = sub.add_parser("notice", help="the finished-notice bundle of an offered necklace")
    n.add_argument("--slug", required=True)
    for p in (c, n):
        p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    snapshot = load_snapshot(args.root)
    if args.cmd == "classify":
        request = json.loads(args.request.read_text(encoding="utf-8"))
        result = classify(request, load_definitions(), snapshot, load_roles())
    else:
        try:
            result = notice(args.slug, snapshot)
        except LookupError as exc:
            print(json.dumps({"error": str(exc)}))
            return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

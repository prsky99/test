"""company-due-diligence holdout-r3: fresh LEI cases for the gleif-lei substitute re-verdict (PM 11-15 08:4x).

Why: 30 of the 40 LEI cases in holdout-r1 and r2 were used by the 11-14 and 11-15 gates, so the re-verdict
needs cases nobody has seen. Rules from PM and the agent team:
- 30 or more cases with an LEI, non-US listed companies spread over countries, group names that also have
  same-name subsidiaries are fine (they are the hard part)
- the five names of the 11-15 analysis are left out: Philips, Zurich Insurance, Accenture, HSBC, Novo Nordisk
- no case_id or LEI shared with any earlier company case (raw cases and every split)
- the answer is GLEIF's public record (legal name, legal-address country, active entity)

Two phases, each one outside call, both through the shared provider ledger as 'adhoc'
(deploy/PROVIDER_BUDGET.md; gleif.org had used its 60 for the day when this was written):
1. candidates: one Wikidata wbgetentities call for 50 hand-picked non-US listed companies (English Wikipedia
   titles, 20 countries, group names included) -> their LEI (P1278) -> raw file. A SPARQL query over all
   listed companies timed out twice on 11-15 (08:47, 08:48), so the list is fixed here instead
2. gleif: one GLEIF call for all chosen LEIs (filter[lei]) -> holdout-r3.jsonl and a manifest entry
Wikidata only proposes candidates; every truth field comes from GLEIF.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from .gold import USER_AGENT, _now, name_key
from .judge import DEFAULT_ROOT

SLUG = "company-due-diligence"
SPLIT = "holdout-r3"
EXCLUDED = ("Philips", "Zurich Insurance", "Accenture", "HSBC", "Novo Nordisk")
PER_COUNTRY = 4
CHOOSE = 44            # chosen for the GLEIF check; at least MINIMUM must survive it
MINIMUM = 30
SYSTEM = "adhoc"
WIKIDATA = ("https://www.wikidata.org/w/api.php?action=wbgetentities&sites=enwiki&props=claims%7Clabels%7Csitelinks"
            "&languages=en&sitefilter=enwiki&redirects=yes&format=json&titles=")
GLEIF = "https://api.gleif.org/api/v1/lei-records?page%5Bsize%5D=200&filter%5Blei%5D="
# (English Wikipedia title, what a person types, legal-address country). None of these is in gold.NON_US or
# NON_US_MORE; group names with same-name subsidiaries (Toyota, Samsung, AXA, Generali, KBC, Tata) are on purpose.
TITLES = [
    ("Toyota", "Toyota", "JP"), ("Sony", "Sony", "JP"), ("Hitachi", "Hitachi", "JP"), ("Honda", "Honda", "JP"),
    ("Samsung Electronics", "Samsung Electronics", "KR"), ("Hyundai Motor Company", "Hyundai Motor", "KR"),
    ("SK Hynix", "SK Hynix", "KR"),
    ("Commerzbank", "Commerzbank", "DE"), ("Adidas", "Adidas", "DE"), ("Infineon Technologies", "Infineon", "DE"),
    ("E.ON", "E.ON", "DE"),
    ("AXA", "AXA", "FR"), ("Société Générale", "Societe Generale", "FR"), ("L'Oréal", "L'Oreal", "FR"),
    ("Kering", "Kering", "FR"),
    ("Vodafone", "Vodafone", "GB"), ("Reckitt", "Reckitt", "GB"), ("Standard Chartered", "Standard Chartered", "GB"),
    ("Aviva", "Aviva", "GB"),
    ("Swiss Re", "Swiss Re", "CH"), ("Holcim", "Holcim", "CH"), ("Givaudan", "Givaudan", "CH"),
    ("Ahold Delhaize", "Ahold Delhaize", "NL"), ("Wolters Kluwer", "Wolters Kluwer", "NL"), ("Adyen", "Adyen", "NL"),
    ("Intesa Sanpaolo", "Intesa Sanpaolo", "IT"), ("Assicurazioni Generali", "Generali", "IT"),
    ("BBVA", "BBVA", "ES"), ("Repsol", "Repsol", "ES"), ("Inditex", "Inditex", "ES"),
    ("H&M", "H&M", "SE"), ("Sandvik", "Sandvik", "SE"),
    ("Telenor", "Telenor", "NO"), ("Norsk Hydro", "Norsk Hydro", "NO"),
    ("Vestas", "Vestas", "DK"), ("DSV (company)", "DSV", "DK"),
    ("Neste", "Neste", "FI"), ("UPM-Kymmene", "UPM", "FI"),
    ("KBC Group", "KBC", "BE"), ("UCB (company)", "UCB", "BE"),
    ("Erste Group", "Erste Group", "AT"), ("OMV", "OMV", "AT"),
    ("Galp Energia", "Galp", "PT"), ("Kerry Group", "Kerry Group", "IE"),
    ("Royal Bank of Canada", "Royal Bank of Canada", "CA"), ("Shopify", "Shopify", "CA"), ("Enbridge", "Enbridge", "CA"),
    ("BHP", "BHP", "AU"), ("Commonwealth Bank", "Commonwealth Bank", "AU"),
    ("Tata Consultancy Services", "Tata Consultancy Services", "IN"),
]
LEI = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
_FORMS = re.compile(r"(?:[\s,]+(?:AG|SE|SA|S\.A\.|N\.V\.|NV|plc|PLC|P\.L\.C\.|Ltd\.?|Limited|Corporation|Corp\.?|Inc\.?"
                    r"|Co\.?,? Ltd\.?|Company|Holdings?|Group|ASA|A/S|AB|Oyj|S\.p\.A\.|SpA|KGaA|& Co\.?|GmbH|K\.K\.))+$",
                    re.I)
KEEP_REGISTRATION = ("ISSUED", "LAPSED", "PENDING_TRANSFER", "PENDING_ARCHIVAL")


def short_name(label: str) -> str:
    """What a person types: the label without trailing legal forms ("Toyota Motor Corporation" -> "Toyota Motor")."""
    out = _FORMS.sub("", label.strip()).strip(" ,")
    return out or label.strip()


def excluded(name: str) -> bool:
    key = name_key(name)
    return any(name_key(x) in key for x in EXCLUDED)


def used(root: Path) -> tuple[set[str], set[str], set[str]]:
    """LEIs, case ids and typed-name keys of every earlier company case (raw cases and all split files)."""
    rows = []
    raw = root / "gold" / "raw" / "company-cases.json"
    if raw.exists():
        rows += json.loads(raw.read_text(encoding="utf-8"))
    for path in sorted((root / "gold" / SLUG).glob("*.jsonl")):
        if path.stem != SPLIT:
            rows += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    leis = {r["truth"]["lei"] for r in rows if r.get("truth", {}).get("lei")}
    return leis, {r["case_id"] for r in rows}, {name_key(r["input"]["name"]) for r in rows}


def candidates(entities: dict, titles=TITLES) -> list[dict]:
    """(name, country, LEI) for each listed title whose Wikidata item carries exactly one LEI (P1278)."""
    by_title = {t: (name, cc) for t, name, cc in titles}
    out, taken = [], set()
    for entity in (entities.get("entities") or {}).values():
        title = ((entity.get("sitelinks") or {}).get("enwiki") or {}).get("title")
        if title not in by_title:       # a listed title that redirects ("Galp Energia" -> "Galp"): match by name
            label = ((entity.get("labels") or {}).get("en") or {}).get("value") or ""
            near = [t for t, name, _ in titles if t not in taken and name_key(name)
                    and (name_key(name) in name_key(title or "") or name_key(name) in name_key(label))]
            if len(near) != 1:
                continue
            title = near[0]
        taken.add(title)
        values = {c.get("mainsnak", {}).get("datavalue", {}).get("value")
                  for c in (entity.get("claims") or {}).get("P1278", []) if c.get("rank") != "deprecated"}
        values = {v for v in values if isinstance(v, str) and LEI.match(v)}
        if len(values) != 1:
            continue
        name, cc = by_title[title]
        out.append({"label": ((entity.get("labels") or {}).get("en") or {}).get("value") or title, "name": name,
                    "country": cc, "lei": values.pop(), "links": len(titles) - [t for t, _, _ in titles].index(title),
                    "item": entity.get("id")})
    return out


def choose(cands: list[dict], used_leis: set[str], used_ids: set[str], used_names: set[str],
           per_country: int = PER_COUNTRY, target: int = CHOOSE) -> list[dict]:
    """Best-known first, round robin over countries, at most PER_COUNTRY a country, no ambiguous short names."""
    seen_lei, seen_name, by_country = set(), set(), {}
    for c in sorted(cands, key=lambda c: (-c["links"], c["lei"])):
        key = name_key(c["name"])
        if (c["lei"] in used_leis or f"{c['country']}:{c['lei']}" in used_ids or key in used_names or excluded(c["name"])
                or excluded(c["label"]) or c["lei"] in seen_lei or key in seen_name or len(key) < 2):
            continue
        seen_lei.add(c["lei"])
        seen_name.add(key)
        by_country.setdefault(c["country"], []).append(c)
    queues = [q[:per_country] for _, q in sorted(by_country.items(), key=lambda kv: (-kv[1][0]["links"], kv[0]))]
    out = []
    while len(out) < target and any(queues):
        for q in queues:
            if q and len(out) < target:
                out.append(q.pop(0))
    return out


def cases_from(chosen: list[dict], gleif: dict) -> list[dict]:
    records = {r["id"]: r for r in gleif.get("data") or []}
    out = []
    for c in chosen:
        r = records.get(c["lei"])
        if not r:
            continue
        entity, registration = r["attributes"]["entity"], r["attributes"].get("registration") or {}
        if (entity.get("status") != "ACTIVE" or registration.get("status") not in KEEP_REGISTRATION
                or entity["legalAddress"]["country"] != c["country"]):
            continue
        out.append({"case_id": f"{c['country']}:{c['lei']}", "task_type": "same_role", "stratum": "has_lei",
                    "input": {"name": c["name"], "country": c["country"]},
                    "truth": {"lei": c["lei"], "legal_name": entity["legalName"]["name"], "cik": None},
                    "truth_sources": [{"name": "GLEIF", "url": f"https://api.gleif.org/api/v1/lei-records/{c['lei']}",
                                       "fetched_at": _now()}]})
    return out


def fetch(url: str, *, opener=urllib.request.urlopen, reserve=None, note=None, timeout: float = 120.0):
    """One GET through the shared ledger: nothing is sent when the ledger says no."""
    if reserve is None or note is None:
        from ..provider_budget import note as _note, reserve as _reserve
        reserve, note = reserve or _reserve, note or _note
    ok, why = reserve(url, SYSTEM)
    if not ok:
        raise RuntimeError(f"provider budget: {why}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with opener(request, timeout=timeout) as response:
            note(url, SYSTEM, getattr(response, "status", 200), evidence="provider_http")
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        note(url, SYSTEM, exc.code, evidence="provider_http")
        raise


def run_candidates(root: Path, get=fetch) -> dict:
    leis, ids, names = used(root)
    cands = candidates(get(WIKIDATA + quote("|".join(t for t, _, _ in TITLES), safe="")))
    chosen = choose(cands, leis, ids, names)
    path = root / "gold" / "raw" / "company-r3-candidates.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": _now(), "source": "Wikidata wbgetentities (candidates only)", "found": len(cands),
                                "chosen": chosen}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"found": len(cands), "chosen": len(chosen), "countries": len({c["country"] for c in chosen}),
            "file": str(path)}


def run_gleif(root: Path, get=fetch) -> dict:
    chosen = json.loads((root / "gold" / "raw" / "company-r3-candidates.json").read_text(encoding="utf-8"))["chosen"]
    leis, ids, _ = used(root)
    chosen = [c for c in chosen if c["lei"] not in leis and f"{c['country']}:{c['lei']}" not in ids]
    cases = cases_from(chosen, get(GLEIF + ",".join(c["lei"] for c in chosen)))
    if len(cases) < MINIMUM:
        return {"written": False, "cases": len(cases), "why": f"fewer than {MINIMUM} cases passed the GLEIF check"}
    folder = root / "gold" / SLUG
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in cases)
    (folder / f"{SPLIT}.jsonl").write_text(text, encoding="utf-8")
    (root / "gold" / "raw" / "company-r3-cases.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("files", {})[SPLIT] = {
        "cases": len(cases), "strata": {"has_lei": len(cases)}, "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "created_at": _now(), "built_from": "Wikidata candidates, GLEIF truth (agent_market/necklaces/gold_r3.py)",
        "excluded_names": list(EXCLUDED), "countries": sorted({c["input"]["country"] for c in cases})}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"written": True, "cases": len(cases), "countries": len({c["input"]["country"] for c in cases}),
            "sha256": manifest["files"][SPLIT]["sha256"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=("candidates", "gleif", "all"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    if args.phase == "all":
        first = run_candidates(args.root)
        result = dict(run_gleif(args.root), candidates=first)
    else:
        result = (run_candidates if args.phase == "candidates" else run_gleif)(args.root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("written", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())

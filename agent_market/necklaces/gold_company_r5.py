"""company-due-diligence holdout-r5: 60 unseen held-out cases for the v2 gate (PM 11-16: round 1 on holdout-r4 failed,
the definition changed, so both rounds start again on a set nobody has seen).

Selection is holdout-r4's rule with its own seed (SEC's ticker list in sha256("r5:" + CIK) order, every CIK of an
earlier company case skipped, kept when the latest periodic filing is a 10-K or 10-Q). Nothing else is filtered, so
small filers come in at the share the ticker list has (PM: keep the real mix).

New in r5, truth.background (PM 11-16 ②(b)): whether English Wikipedia has an article about the company.
- First Wikidata, whose items carry the SEC CIK (property P5531): an item with that CIK and an English Wikipedia
  sitelink -> wiki_article true, matched_by wikidata_cik (one SPARQL query for all 60).
- A company Wikidata does not map is looked up by name in one Wikipedia batch call (its name without legal forms,
  redirects followed); a standard page whose short description reads as a company and whose title is the company's
  name -> wiki_article true, matched_by title. Otherwise wiki_article false: "No encyclopedia article found" is then
  the right answer, and an article about another company is wrong.
Every call is a reference_check through the ledger (sec.gov day total 600; Wikidata and Wikipedia one call each).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from .gold_company_r4 import CASES, build_cases
from .gold_filings import fetch_text
from .gold_repos import fetch_json
from .judge import DEFAULT_ROOT
from .runner import COMPANY_WORDS, name_words, search_name

SLUG = "company-due-diligence"
SPLIT = "holdout-r5"
SPARQL = "https://query.wikidata.org/sparql?"
WIKI = "https://en.wikipedia.org/w/api.php?"


def wikidata_articles(ciks: list[str], get=fetch_json) -> dict[str, dict]:
    """CIK -> {"title", "url"} for items with that CIK (P5531, padded or not) and an English Wikipedia article."""
    values = " ".join(f'"{c.zfill(10)}" "{c}"' for c in ciks)
    query = ("SELECT ?cik ?article WHERE { VALUES ?cik { " + values + " } ?item wdt:P5531 ?cik . "
             "?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }")
    _, body = get(SPARQL + urlencode({"format": "json", "query": query}))
    out = {}
    for row in ((body or {}).get("results") or {}).get("bindings") or []:
        cik, url = str(int(row["cik"]["value"])), row["article"]["value"]
        title = url.rsplit("/wiki/", 1)[-1].replace("_", " ")
        out.setdefault(cik, {"title": _unquote(title), "url": url})
    return out


def _unquote(text: str) -> str:
    from urllib.parse import unquote
    return unquote(text)


def title_articles(names: dict[str, str], get=fetch_json) -> dict[str, dict]:
    """CIK -> {"title", "url"} where the company's name (legal forms dropped) is a standard page about a company."""
    asked = {cik: search_name(name) for cik, name in names.items() if search_name(name)}
    if not asked:
        return {}
    _, body = get(WIKI + urlencode({"action": "query", "format": "json", "formatversion": 2, "redirects": 1,
                                    "prop": "description|info|pageprops", "inprop": "url",
                                    "titles": "|".join(sorted(set(asked.values())))}))
    query = (body or {}).get("query") or {}
    renamed = {r["from"]: r["to"] for r in query.get("normalized") or []}
    renamed.update({r["from"]: r["to"] for r in query.get("redirects") or []})
    pages = {p["title"]: p for p in query.get("pages") or []
             if not p.get("missing") and "disambiguation" not in (p.get("pageprops") or {})}
    out = {}
    for cik, asked_title in asked.items():
        title = asked_title
        for _ in range(3):
            title = renamed.get(title, title)
        page = pages.get(title)
        if not page:
            continue
        same_name = sorted(set(name_words(title.split(" (")[0]))) == sorted(set(name_words(names[cik])))
        if same_name and COMPANY_WORDS.search(str(page.get("description") or "").lower()):
            out[cik] = {"title": page["title"], "url": page.get("fullurl")}
    return out


def item_ciks(items: list[str], get=fetch_json) -> dict[str, set]:
    """Wikidata item -> the SEC CIKs it carries (P5531), for items found by search."""
    if not items:
        return {}
    query = ("SELECT ?item ?cik WHERE { VALUES ?item { " + " ".join(f"wd:{i}" for i in sorted(set(items))) + " } "
             "OPTIONAL { ?item wdt:P5531 ?cik . } }")
    _, body = get(SPARQL + urlencode({"format": "json", "query": query}))
    out: dict[str, set] = {}
    for row in ((body or {}).get("results") or {}).get("bindings") or []:
        item = row["item"]["value"].rsplit("/", 1)[-1]
        out.setdefault(item, set())
        if row.get("cik"):
            out[item].add(str(int(row["cik"]["value"])))
    return out


def search_articles(names: dict[str, str], get=fetch_json, per: int = 3) -> dict[str, dict]:
    """CIK -> {"title", "url"} by Wikipedia search (11-16: EDGAR's upper-case names miss exact titles, and Wikidata
    lacks many CIKs). A hit is a standard page whose title is the company's name (same distinctive words, case
    ignored) with a company description, whose Wikidata item does not carry a different CIK (one SPARQL call)."""
    hits: dict[str, list[str]] = {}
    for cik, name in names.items():
        query = search_name(name)
        if not query:
            continue
        _, body = get(WIKI + urlencode({"action": "query", "format": "json", "formatversion": 2, "list": "search",
                                        "srsearch": query, "srlimit": per, "srnamespace": 0}))
        hits[cik] = [r["title"] for r in ((body or {}).get("query") or {}).get("search") or []]
    titles = sorted({t for ts in hits.values() for t in ts})
    pages: dict[str, dict] = {}
    for start in range(0, len(titles), 50):
        _, body = get(WIKI + urlencode({"action": "query", "format": "json", "formatversion": 2,
                                        "prop": "description|info|pageprops", "inprop": "url",
                                        "titles": "|".join(titles[start:start + 50])}))
        for page in ((body or {}).get("query") or {}).get("pages") or []:
            if not page.get("missing") and "disambiguation" not in (page.get("pageprops") or {}):
                pages[page["title"]] = page
    chosen = {}
    for cik, ts in hits.items():
        for title in ts:
            page = pages.get(title)
            if not page:
                continue
            same = sorted(set(name_words(title.split(" (")[0]))) == sorted(set(name_words(names[cik])))
            if same and COMPANY_WORDS.search(str(page.get("description") or "").lower()):
                chosen[cik] = page
                break
    items = item_ciks([p["pageprops"]["wikibase_item"] for p in chosen.values()
                       if (p.get("pageprops") or {}).get("wikibase_item")], get)
    out = {}
    for cik, page in chosen.items():
        carried = items.get((page.get("pageprops") or {}).get("wikibase_item"), set())
        if carried and cik not in carried:
            continue                                   # the page is another SEC filer's
        out[cik] = {"title": page["title"], "url": page.get("fullurl")}
    return out


def refresh_background(root: Path = DEFAULT_ROOT, get=fetch_json) -> dict:
    """Redo truth.background on the written split without new SEC calls (11-16: the first build missed articles)."""
    folder = Path(root) / "gold" / SLUG
    path = folder / f"{SPLIT}.jsonl"
    cases = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    for case in cases:
        case["truth_sources"] = [s for s in case["truth_sources"] if not s["name"].startswith("Wikidata")]
    info = add_background(cases, get)
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    path.write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["files"][SPLIT]
    entry.update(sha256=hashlib.sha256(text.encode()).hexdigest(), background=info, strata=_strata(cases))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def add_background(cases: list[dict], get=fetch_json) -> dict:
    ciks = [c["truth"]["cik"] for c in cases]
    by_cik = wikidata_articles(ciks, get)
    rest = {c["truth"]["cik"]: c["truth"]["sec_title"] for c in cases if c["truth"]["cik"] not in by_cik}
    by_title = title_articles(rest, get)
    by_search = search_articles({c: n for c, n in rest.items() if c not in by_title}, get)
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for case in cases:
        cik = case["truth"]["cik"]
        found, how = ((by_cik.get(cik), "wikidata_cik") if cik in by_cik else
                      (by_title.get(cik), "title") if cik in by_title else (by_search.get(cik), "search"))
        case["truth"]["background"] = {"wiki_article": bool(found), "title": (found or {}).get("title"),
                                       "url": (found or {}).get("url"), "matched_by": how if found else None}
        # both gate rounds get companies with and without an article in the same share (the split halves strata)
        case["stratum"] = "us_filer_wiki" if found else "us_filer_no_wiki"
        case["truth_sources"].append({"name": "Wikidata (SEC CIK, P5531) and English Wikipedia", "url": SPARQL.rstrip("?"),
                                      "fetched_at": at})
    return {"wikidata_cik": len(by_cik), "title": len(by_title), "search": len(by_search),
            "no_article": sum(1 for c in cases if not c["truth"]["background"]["wiki_article"])}


def _strata(cases: list[dict]) -> dict:
    out: dict[str, int] = {}
    for c in cases:
        out[c["stratum"]] = out.get(c["stratum"], 0) + 1
    return out


def build(root: Path = DEFAULT_ROOT, get=fetch_text, get_json=fetch_json, today: date | None = None,
          sleep=time.sleep) -> dict:
    cases, info = build_cases(root, get, today, sleep, seed="r5", prefix="US5")
    if len(cases) < CASES:
        return {"cases": len(cases), "written": False, **info}
    info.update(add_background(cases, get_json))
    folder = Path(root) / "gold" / SLUG
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (folder / f"{SPLIT}.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("files", {})[SPLIT] = {
        "cases": len(cases), "strata": _strata(cases), "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "for": "company-due-diligence v2 launch gate, rounds 1 and 2 (30 + 30; PM 11-16 after holdout-r4 round 1 failed)",
        "selection": "SEC ticker list in sha256('r5:'+CIK) order, unseen CIKs, latest periodic 10-K or 10-Q "
                     "(the necklace's scope: US SEC filers); nothing else filtered, so small filers keep their share",
        "truth_sources": ["SEC company_tickers.json (CIK, ticker, EDGAR name)",
                          "SEC EDGAR submissions (latest 10-K or 10-Q)",
                          "Wikidata P5531 (SEC CIK, CC0) to English Wikipedia; else a Wikipedia title lookup, then "
                          "a Wikipedia search whose page's Wikidata item carries no other CIK"],
        "background": {k: info[k] for k in ("wikidata_cik", "title", "search", "no_article")},
        "background_rule": "truth.background.wiki_article false: 'No encyclopedia article found' (not_found) is the "
                           "right answer and any other company's article is wrong (PM 11-16 ②(b))",
        "same_source_kind": "official",
        "same_source_rule": "official register (PM 11-16 07:05): the answer key is SEC, the official register, "
                            "fetched by this builder from SEC itself; our substitutes sec-edgar and sec-filings read SEC too. "
                            "Such cases are not counted as failures; the case line says same_source_official "
                            "(retest.same_source_official). The strict count applies to secondary indexes only."}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"cases": len(cases), "written": True, **info}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--refresh-background", action="store_true", help="redo truth.background only (no SEC calls)")
    args = parser.parse_args(argv)
    out = refresh_background(args.root) if args.refresh_background else build(args.root)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

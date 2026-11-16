"""topic-evidence-brief holdout-r3: topics nobody has seen, for the arxiv-search re-verdict and the necklace gate
(agent team 11-15; topic-evidence-brief is priority 1, PM 16:35).

Why: the 90 cases of tuning, holdout-r1 and holdout-r2 were all used by the 11-15 substitute gates. Truth is built as
before (gold.topic_cases): the Wikipedia summary (title, short description, page) and the topic's most cited articles
in OpenAlex (title search on the phrase that must stand in a paper title). Topics are science, technology and social
science, where arXiv and OpenAlex have papers. Calls go through the shared ledger as reference_checks: Wikipedia in one
batch call (action API, up to 50 titles), OpenAlex one call per topic; the builder resumes (progress file) and writes
the split once every topic is done. A topic without a standard Wikipedia page or with fewer than 3 papers is left out.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urlencode

from .gold import _now
from .gold_repos import Budget, fetch_json
from .judge import DEFAULT_ROOT

SLUG = "topic-evidence-brief"
SPLIT = "holdout-r3"
PER_TOPIC = 10
WIKI = "https://en.wikipedia.org/w/api.php?"
# 11-16 (PM 06:5x): OpenAlex now allows about 100 keyless searches a day (the ledger keeps 50), so the papers truth
# may come from Crossref instead (bibliographic metadata CC0; sorted by citation count). Each case names its source.
CROSSREF = ("https://api.crossref.org/works?query.title=%s&filter=type:journal-article&sort=is-referenced-by-count"
            "&order=desc&rows=%d&select=DOI,title&mailto=contact@agentconcierge.biz")   # Crossref's polite pool (ops 11-16)
PAPER_SOURCES = {"openalex": {"name": "OpenAlex (title search, most cited)", "url": "https://api.openalex.org/works"},
                 "crossref": {"name": "Crossref (title search, most referenced)", "url": "https://api.crossref.org/works"}}
OPENALEX = ("https://api.openalex.org/works?per-page=%d&sort=cited_by_count:desc&select=doi,title,publication_year"
            "&filter=type:article,title.search:%s")

# (Wikipedia title, phrase that must stand in a paper title or None for the title in lower case, stratum)
TOPICS = [(t, k or t.lower(), "stem") for t, k in [
    ("CRISPR", "crispr"), ("Lithium-ion battery", "lithium-ion batter"), ("Ocean acidification", None),
    ("Differential privacy", None), ("Synaptic plasticity", None), ("Topological insulator", None),
    ("Neutrino oscillation", None), ("Gene therapy", None), ("Epigenetics", None), ("Computer vision", None),
    ("Speech recognition", None), ("Recommender system", None), ("Anomaly detection", None),
    ("Knowledge graph", None), ("Homomorphic encryption", None), ("Post-quantum cryptography", None),
    ("Solid-state battery", None), ("Carbon capture and storage", "carbon capture"), ("Metamaterial", None),
    ("Optogenetics", None), ("Neuroplasticity", None)]] + [(t, k or t.lower(), "society") for t, k in [
    ("Online learning", None), ("Behavioral economics", None), ("Supply chain resilience", None),
    ("Work–life balance", "work-life balance"), ("Teacher burnout", None), ("Universal health care", None),
    ("Algorithmic bias", None), ("Platform economy", None), ("Climate migration", None), ("Energy poverty", None),
    ("Financial inclusion", None), ("Green bond", None), ("Labor productivity", None), ("Social network analysis", None),
    ("Urban heat island", None), ("Vaccine hesitancy", None), ("Food waste", None), ("Digital literacy", None)]]


def used_topics(root: Path, split: str = SPLIT) -> set[str]:
    out = set()
    for path in (Path(root) / "gold" / SLUG).glob("*.jsonl"):
        if path.stem == split or path.stem.startswith(split + "-"):   # its own parts (holdout-r4-wiki) are not "seen"
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.add(json.loads(line)["case_id"])
    return out


def step(root: Path = DEFAULT_ROOT, get=fetch_json, split: str = SPLIT, topics=None, progress_name: str = "r3-progress.json",
         purpose: str = "arxiv-search re-verdict and the necklace gate (11-15)", papers_source: str = "openalex",
         target: int | None = None) -> dict:
    """One resumable round for SPLIT (holdout-r3 by default; holdout-r4 from gold_topics_r4 with its own topics).

    TARGET (PM 11-16, topic gate round 2 within OpenAlex's 50 a day): stop once TARGET topics, taken in the fixed
    TOPICS order, have papers, and write the split with exactly those; the topics after them are not asked and not
    used. The order is the code's, set before any answer was seen, so nothing is picked by its result."""
    topics = TOPICS if topics is None else topics
    folder = Path(root) / "gold" / SLUG
    progress_path = folder / progress_name
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
    seen = used_topics(root, split)
    todo = [(t, p, s) for t, p, s in topics if "topic:" + t not in seen]
    stopped = None
    try:
        if "wiki" not in progress:
            url = WIKI + urlencode({"action": "query", "format": "json", "formatversion": 2, "redirects": 1,
                                    "prop": "description|info|pageprops", "inprop": "url",
                                    "titles": "|".join(t for t, _, _ in todo)})
            _, body = get(url)
            pages = {}
            renamed = {r["from"]: r["to"] for r in ((body or {}).get("query") or {}).get("redirects") or []}
            for page in ((body or {}).get("query") or {}).get("pages") or []:
                if page.get("missing") or "disambiguation" in (page.get("pageprops") or {}):
                    continue
                pages[page["title"]] = {"title": page["title"], "description": page.get("description"),
                                        "url": page.get("fullurl")}
            progress["wiki"] = {t: pages.get(renamed.get(t, t)) for t, _, _ in todo}
            progress["wiki_at"] = _now()
        for title, phrase, stratum in todo:
            if target is not None and sum(1 for t, _, _ in todo
                                          if "papers" in (progress.get("topics") or {}).get(t, {})) >= target:
                break
            row = progress.setdefault("topics", {}).setdefault(title, {})
            if "papers" in row or "dropped" in row:
                continue
            if not progress["wiki"].get(title):
                row["dropped"] = "no standard Wikipedia page"
                continue
            if papers_source == "crossref":
                _, body = get(CROSSREF % (quote(phrase), PER_TOPIC))
                papers = [{"doi": (w.get("DOI") or "").lower(), "title": (w.get("title") or [None])[0]}
                          for w in ((body or {}).get("message") or {}).get("items") or []
                          if w.get("DOI") and (w.get("title") or [None])[0]]
            else:
                _, works = get(OPENALEX % (PER_TOPIC, quote(phrase)))
                papers = [{"doi": (w.get("doi") or "").replace("https://doi.org/", "").lower(), "title": w.get("title")}
                          for w in (works or {}).get("results") or [] if w.get("doi") and w.get("title")]
            if len(papers) < 3:
                row["dropped"] = f"fewer than 3 papers in {PAPER_SOURCES[papers_source]['name']}"
                continue
            row.update(papers=papers, phrase=phrase, stratum=stratum, at=_now(), papers_source=papers_source)
    except Budget as exc:
        stopped = str(exc)
    folder.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    rows = progress.get("topics") or {}
    left = [t for t, _, _ in todo if "papers" not in rows.get(t, {}) and "dropped" not in rows.get(t, {})]
    built = [t for t, _, _ in todo if "papers" in rows.get(t, {})]
    if target is not None and len(built) >= target:
        left = []                                    # the topics after the first TARGET are not built (PM 11-16)
    out = {"done": sum(1 for r in rows.values() if "papers" in r), "left": len(left),
           "dropped": {t: r["dropped"] for t, r in rows.items() if "dropped" in r}, "stopped": stopped}
    if not left and "wiki" in progress:
        out["written"] = write_split(root, progress, todo, split, purpose, target=target)
    return out


def write_split(root: Path, progress: dict, todo, split: str = SPLIT,
                purpose: str = "arxiv-search re-verdict and the necklace gate (11-15)", target: int | None = None) -> dict:
    cases = []
    for title, _, _ in todo:
        row = (progress.get("topics") or {}).get(title) or {}
        if "papers" not in row:
            continue
        if target is not None and len(cases) >= target:
            break
        wiki = progress["wiki"][title]
        cases.append({"case_id": "topic:" + title, "task_type": "same_role", "stratum": row["stratum"],
                      "input": {"topic": wiki["title"]},
                      "truth": {"wiki": wiki, "papers": row["papers"], "paper_phrase": row["phrase"]},
                      "truth_sources": [{"name": "Wikipedia (action API, description)", "url": WIKI.rstrip("?"),
                                         "fetched_at": progress["wiki_at"]},
                                        {**PAPER_SOURCES[row.get("papers_source", "openalex")],
                                         "fetched_at": row["at"]}]})
    folder = Path(root) / "gold" / SLUG
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (folder / f"{split}.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    strata: dict[str, int] = {}
    for c in cases:
        strata[c["stratum"]] = strata.get(c["stratum"], 0) + 1
    manifest.setdefault("files", {})[split] = {"cases": len(cases), "strata": strata,
                                               "sha256": hashlib.sha256(text.encode()).hexdigest(), "for": purpose,
                                               "selection": "not filtered by any source's coverage (PM 11-16 06:5x)"
                                                            + (f"; the first {target} topics with papers in the fixed "
                                                               "TOPICS order of the builder (set before any answer was "
                                                               "seen), the topics after them not built and not used "
                                                               "(PM 11-16, OpenAlex 50 a day)" if target else ""),
                                               "same_source_kind": "secondary",
                                               "same_source_rule": "secondary index (PM 11-16 07:05): a papers answer from "
                                                                   "a member whose upstream is this case's papers source "
                                                                   "(OpenAlex, Crossref) is marked same_source; the gate "
                                                                   "must also pass with those cases counted as failures "
                                                                   "(PM 11-16 07:0x, retest.same_source)",
                                               "truth_sources": ["Wikipedia action API (title, description, page)"] + sorted(
                                                   {PAPER_SOURCES[(progress.get("topics") or {}).get(c["case_id"][6:], {})
                                                                  .get("papers_source", "openalex")]["name"] for c in cases})}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"cases": len(cases), "strata": strata}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(step(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

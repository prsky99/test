"""topic-evidence-brief papers answer key "papers-two-index-v1" (PM 11-17 decision, before the v2 gate rounds).

Why: the old key was one index (OpenAlex, title search, ten most cited) and a member reading OpenAlex was counted as a
failure (same source), so a member reading an independent index (Crossref) failed whenever the two indexes ranked
citations differently, even when it named an influential paper. The task is "influential papers on the topic", not
"OpenAlex's order". So a paper counts when two independent indexes both rank it high:

    G = (OpenAlex top 10  ∩  Crossref top 50)  ∪  (Crossref top 10  ∩  OpenAlex top 50)      matched by DOI

k is fixed at 10/50 by the PM before any answer of these sets was seen; it is not tuned on holdout-r3 or any set.
A topic whose G is empty is left out before the round, and the count is written in the manifest. The pass line of the
gate (28/30 and a positive delta) is unchanged; the v1 round of 11-17 is not graded again.

Calls (shared ledger, reference_checks): per topic one OpenAlex search (per-page 50) and one Crossref search (rows 50),
both sorted by citations; for a new topic list one Wikipedia batch call. Raw lists are kept in the progress file first,
and the builder resumes. Every split has exactly 30 cases (the round's denominator is fixed, PM 11-17): topics are
taken in a fixed order and a topic with an empty G is replaced by the next one, so nothing is picked by its answer.
  holdout-r5-2i: the 30 topics of holdout-r5 (their Wikipedia facts reused), then FILL_R5 (gold_topics_r7.TOPICS[:22])
  holdout-r6-2i: gold_topics_r6.TOPICS, then FILL_R6 (gold_topics_r7.TOPICS[22:])
The two fill lists are halves of one list checked on 11-16 (unused, no redirect onto a used topic), so the splits
never share a topic whichever is built first. The fill topics a split used are listed in its manifest.
usage: python -m agent_market.necklaces.gold_topics_two_index holdout-r5-2i|holdout-r6-2i [--root R]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urlencode

from .gold import _now
from .gold_repos import Budget, fetch_json
from .gold_topics_r3 import CROSSREF, OPENALEX, SLUG, WIKI
from .judge import DEFAULT_ROOT

RULE = "papers-two-index-v1"
TOP, WIDE = 10, 50
DECIDED = "PM 11-17 decision (k fixed at 10/50 before any answer of these sets was seen; no tuning on holdout-r3)"
SOURCES = [{"name": "OpenAlex (title search, most cited, top 50)", "url": "https://api.openalex.org/works"},
           {"name": "Crossref (title search, most referenced, top 50)", "url": "https://api.crossref.org/works"}]
TARGET = 30
FILL_AT = 22          # gold_topics_r7.TOPICS[:22] fill holdout-r5-2i, [22:] fill holdout-r6-2i


def _doi(value) -> str:
    return str(value or "").replace("https://doi.org/", "").strip().lower()


def openalex_list(body) -> list[dict]:
    return [{"doi": _doi(w.get("doi")), "title": w.get("title")} for w in (body or {}).get("results") or []
            if w.get("doi") and w.get("title")]


def crossref_list(body) -> list[dict]:
    return [{"doi": _doi(w.get("DOI")), "title": (w.get("title") or [None])[0]}
            for w in ((body or {}).get("message") or {}).get("items") or [] if w.get("DOI") and (w.get("title") or [None])[0]]


def two_index(oa: list[dict], cr: list[dict], top: int = TOP, wide: int = WIDE) -> list[dict]:
    """G = (OpenAlex top ∩ Crossref wide) ∪ (Crossref top ∩ OpenAlex wide), by DOI, OpenAlex order first."""
    oa_wide, cr_wide = {p["doi"] for p in oa[:wide]}, {p["doi"] for p in cr[:wide]}
    out, seen = [], set()
    for p in [p for p in oa[:top] if p["doi"] in cr_wide] + [p for p in cr[:top] if p["doi"] in oa_wide]:
        if p["doi"] not in seen:
            seen.add(p["doi"])
            out.append({"doi": p["doi"], "title": p["title"]})
    return out


def topics_for(root: Path, split: str) -> list[tuple[str, str, str, dict | None]]:
    """(Wikipedia title, title phrase, stratum, Wikipedia facts or None) in the split's fixed order."""
    from .gold_topics_r7 import TOPICS as FILL
    if split == "holdout-r5-2i":
        path = Path(root) / "gold" / SLUG / "holdout-r5.jsonl"
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return ([(r["case_id"][len("topic:"):], r["truth"]["paper_phrase"], r["stratum"], r["truth"]["wiki"]) for r in rows]
                + [(t, p, s, None) for t, p, s in FILL[:FILL_AT]])
    if split == "holdout-r6-2i":
        from .gold_topics_r6 import TOPICS
        return [(t, p, s, None) for t, p, s in list(TOPICS) + list(FILL[FILL_AT:])]
    raise ValueError(f"unknown split {split}")


def base_topics(root: Path, split: str) -> set[str]:
    """The split's own list before any fill topic (the rest of topics_for are fill topics)."""
    if split == "holdout-r5-2i":
        path = Path(root) / "gold" / SLUG / "holdout-r5.jsonl"
        return {json.loads(x)["case_id"][len("topic:"):] for x in path.read_text(encoding="utf-8").splitlines() if x.strip()}
    from .gold_topics_r6 import TOPICS
    return {t for t, _, _ in TOPICS}


def step(root: Path = DEFAULT_ROOT, split: str = "holdout-r6-2i", get=fetch_json) -> dict:
    folder = Path(root) / "gold" / SLUG
    progress_path = folder / f"{split}-progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
    topics = topics_for(root, split)
    rows = progress.setdefault("topics", {})
    stopped = None

    def save():
        folder.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    def built():
        return sum(1 for t, *_ in topics if rows.get(t, {}).get("papers"))

    def fetch_wiki():
        wanted = [t for t, _, _, w in topics if w is None]
        _, body = get(WIKI + urlencode({"action": "query", "format": "json", "formatversion": 2, "redirects": 1,
                                        "prop": "description|info|pageprops", "inprop": "url", "titles": "|".join(wanted)}))
        pages, renamed = {}, {r["from"]: r["to"] for r in ((body or {}).get("query") or {}).get("redirects") or []}
        for page in ((body or {}).get("query") or {}).get("pages") or []:
            if page.get("missing") or "disambiguation" in (page.get("pageprops") or {}):
                continue
            pages[page["title"]] = {"title": page["title"], "description": page.get("description"), "url": page.get("fullurl")}
        progress["wiki"] = {t: pages.get(renamed.get(t, t)) for t in wanted}
        progress["wiki_at"] = _now()
        save()
    try:
        for title, phrase, stratum, wiki in topics:
            if built() >= TARGET:
                break
            row = rows.setdefault(title, {})
            if "papers" in row or "dropped" in row:
                continue
            if wiki is None and "wiki" not in progress:
                fetch_wiki()                      # once, only when a topic without Wikipedia facts is reached
            wiki = wiki or (progress.get("wiki") or {}).get(title)
            if not wiki:
                row["dropped"] = "no standard Wikipedia page"
                continue
            if "openalex" not in row:
                _, body = get(OPENALEX % (WIDE, quote(phrase)))
                row["openalex"], row["openalex_at"] = openalex_list(body), _now()      # raw first
                save()
            if "crossref" not in row:
                _, body = get(CROSSREF % (quote(phrase), WIDE))
                row["crossref"], row["crossref_at"] = crossref_list(body), _now()
            papers = two_index(row["openalex"], row["crossref"])
            row.update(phrase=phrase, stratum=stratum, wiki=wiki)
            if papers:
                row["papers"] = papers
            else:
                row["dropped"] = "no paper in both indexes' top lists (G empty)"
            save()
    except Budget as exc:
        stopped = str(exc)
    save()
    out = {"split": split, "built": built(), "stopped": stopped,
           "dropped": {t: r["dropped"] for t, r in rows.items() if "dropped" in r}}
    if built() >= TARGET:
        out["written"] = write_split(root, split, topics, progress)
    elif not stopped:
        out["short"] = f"only {built()} topics with a non-empty G in the whole list; the split is not written"
    return out


def write_split(root: Path, split: str, topics, progress: dict) -> dict:
    rows = progress.get("topics") or {}
    cases, dropped = [], {}
    for title, *_ in topics:
        row = rows.get(title) or {}
        if "dropped" in row:
            dropped[title] = row["dropped"]
        if not row.get("papers"):
            continue
        if len(cases) >= TARGET:
            break
        cases.append({"case_id": "topic:" + title, "task_type": "same_role", "stratum": row["stratum"],
                      "input": {"topic": row["wiki"]["title"]},
                      "truth": {"wiki": row["wiki"], "papers": row["papers"], "paper_phrase": row["phrase"],
                                "papers_rule": RULE},
                      "truth_sources": [{"name": "Wikipedia (action API, description)", "url": WIKI.rstrip("?"),
                                         "fetched_at": progress.get("wiki_at") or "from holdout-r5"},
                                        {**SOURCES[0], "fetched_at": row.get("openalex_at")},
                                        {**SOURCES[1], "fetched_at": row.get("crossref_at")}]})
    folder = Path(root) / "gold" / SLUG
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (folder / f"{split}.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    strata: dict[str, int] = {}
    for c in cases:
        strata[c["stratum"]] = strata.get(c["stratum"], 0) + 1
    manifest.setdefault("files", {})[split] = {
        "cases": len(cases), "strata": strata, "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "for": "topic-evidence-brief v2 gate rounds (11-18)",
        "grading_rule": {"name": RULE, "decided": DECIDED, "top": TOP, "wide": WIDE,
                         "rule": "G = (OpenAlex top 10 ∩ Crossref top 50) ∪ (Crossref top 10 ∩ OpenAlex top 50) by DOI; "
                                 "a papers answer passes when it names one paper of G (DOI or title)",
                         "same_source": "not applied to papers: the key needs both indexes, so no one member's index is "
                                        "the key's source (PM 11-17); the strict count of PM 11-16 07:0x was for a "
                                        "one-index key"},
        "dropped_topics": dropped, "dropped_count": len(dropped),
        "filled_topics": [c["case_id"][len("topic:"):] for c in cases
                          if c["case_id"][len("topic:"):] not in base_topics(root, split)],
        "fill_rule": "a topic with an empty G (or no Wikipedia page) is replaced by the next topic of the fixed fill "
                     "list (gold_topics_r7.TOPICS[:22] for holdout-r5-2i, [22:] for holdout-r6-2i), so the round "
                     "keeps 30 cases (PM 11-17) and the two splits never share a topic",
        "selection": ("the topics of holdout-r5 in its order, then the fill list" if split == "holdout-r5-2i" else
                      "gold_topics_r6.TOPICS in its order, then the fill list") + "; the first 30 with a non-empty G "
                     "(orders fixed before any answer was seen)",
        "truth_sources": ["Wikipedia action API (title, description, page)"] + [s["name"] for s in SOURCES]}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"cases": len(cases), "dropped": len(dropped)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("split", choices=("holdout-r5-2i", "holdout-r6-2i"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(step(args.root, args.split), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

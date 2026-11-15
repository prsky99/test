"""topic-evidence-brief holdout-r4: a fresh sample for the 11-16 re-verdicts of wiki-grounding and arxiv-search after
their fixes (agent team 78caa6e4; PM 11-16 06:5x: a new sample, not r3 again).

Built exactly like holdout-r3 (gold_topics_r3: Wikipedia title, description and page in one batch call; the most
cited OpenAlex articles for the title phrase, one call a topic; resumable under the ledger as reference_checks).
Selection: topics from science, technology and the social sciences, none used in tuning, holdout-r1, r2 or r3.
NOT filtered by arXiv coverage (PM 06:5x: only allowed once arxiv-search's definition states its field and routes
other topics elsewhere); the manifest entry says so and names the truth sources.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gold_topics_r3 import step as _step
from .judge import DEFAULT_ROOT

SPLIT = "holdout-r4"
TOPICS = [(t, k or t.lower(), "stem") for t, k in [
    ("Spintronics", None), ("Quantum dot", None), ("Nanomedicine", None), ("Biofilm", None), ("Prion", None),
    ("Circadian rhythm", None), ("Telomere", None), ("Powered exoskeleton", "exoskeleton"), ("Swarm robotics", None),
    ("Natural language processing", None), ("Sentiment analysis", None), ("Explainable artificial intelligence", "explainable"),
    ("Zero-knowledge proof", None), ("Smart contract", None), ("Software-defined networking", None),
    ("Lidar", None), ("Hydrogel", None), ("Biochar", None), ("Desalination", None), ("Green hydrogen", None),
    ("Permafrost", None), ("Tsunami", None), ("Wildfire", None)]] + [(t, k or t.lower(), "society") for t, k in [
    ("Gentrification", None), ("Behavioral finance", None), ("Crowdfunding", None), ("Sharing economy", None),
    ("Fake news", None), ("Echo chamber (media)", "echo chamber"), ("Central bank digital currency", None),
    ("Cyberbullying", None), ("Telehealth", None), ("Gamification", None), ("Social entrepreneurship", None),
    ("Human capital flight", "brain drain"), ("Tax evasion", None), ("Electoral system", None), ("Food desert", None),
    ("Digital nomad", None), ("Precarious work", None), ("Urban sprawl", None)]]


def step(root: Path = DEFAULT_ROOT, get=None, papers_source: str = "openalex") -> dict:
    kwargs = {"papers_source": papers_source} if get is None else {"get": get, "papers_source": papers_source}
    return _step(root, split=SPLIT, topics=TOPICS, progress_name="r4-progress.json",
                 purpose="wiki-grounding and arxiv-search re-verdicts after 78caa6e4 (11-16)", **kwargs)


WIKI_SPLIT = "holdout-r4-wiki"


def wiki_split(root: Path = DEFAULT_ROOT) -> dict:
    """PM 11-16 07:0x: the part of r4 whose truth is Wikipedia only, written as soon as the one Wikipedia batch is in
    (no OpenAlex needed), so wiki-grounding's gate runs today. Same topics and selection as r4 (fresh, unfiltered);
    cases carry truth.wiki and truth.paper_phrase but no papers. The OpenAlex part (holdout-r4) follows."""
    import hashlib
    folder = Path(root) / "gold" / "topic-evidence-brief"
    progress = json.loads((folder / "r4-progress.json").read_text(encoding="utf-8"))
    wiki = progress.get("wiki") or {}
    seen = _seen(root)
    cases = []
    for title, phrase, stratum in TOPICS:
        page = wiki.get(title)
        if not page or "topic:" + title in seen:
            continue
        cases.append({"case_id": "topic:" + title, "task_type": "same_role", "stratum": stratum,
                      "input": {"topic": page["title"]}, "truth": {"wiki": page, "paper_phrase": phrase},
                      "truth_sources": [{"name": "Wikipedia (action API, description)",
                                         "url": "https://en.wikipedia.org/w/api.php", "fetched_at": progress["wiki_at"]}]})
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (folder / f"{WIKI_SPLIT}.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    strata: dict[str, int] = {}
    for c in cases:
        strata[c["stratum"]] = strata.get(c["stratum"], 0) + 1
    manifest.setdefault("files", {})[WIKI_SPLIT] = {
        "cases": len(cases), "strata": strata, "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "for": "wiki-grounding re-verdict after 78caa6e4 (11-16)",
        "selection": "the holdout-r4 topics with a standard Wikipedia page; split from holdout-r4 by truth source "
                     "(Wikipedia only, PM 11-16 07:0x); not filtered by any source's coverage",
        "truth_sources": ["Wikipedia action API (title, description, page)"],
        "same_topics_as": SPLIT}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"cases": len(cases), "strata": strata}


def _seen(root: Path) -> set:
    from .gold_topics_r3 import used_topics
    return used_topics(root, SPLIT)     # every file but r4 and its parts (holdout-r4-*)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--papers-source", choices=("openalex", "crossref"), default="openalex")
    parser.add_argument("--wiki-split", action="store_true", help="write holdout-r4-wiki from the Wikipedia batch")
    args = parser.parse_args(argv)
    print(json.dumps(wiki_split(args.root) if args.wiki_split else step(args.root, papers_source=args.papers_source),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

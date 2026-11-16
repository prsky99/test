"""topic-evidence-brief holdout-r6: a fresh 30-case sample for topic-evidence-brief v2 gate round 1 (11-18/19) (PM 11-16 18:3x).

Built exactly like holdout-r3 to r5 (gold_topics_r3.step: one Wikipedia batch, OpenAlex most cited per topic, resumable
under the ledger as reference_checks). Ops runs it on 11-18 within that day's OpenAlex share (38 reference checks):
the builder stops once 30 topics, in this fixed order, have papers, so up to 8 topics may drop before the set
falls short. Topics: science, technology and the social sciences, none used in tuning or holdout-r1 to r5 (r4's list
included), none among the wikipedia-summary B topics, and none whose Wikipedia redirect lands on a used topic
(checked 11-16 18:4x); the list was fixed before any answer was seen.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gold_topics_r3 import step as _step
from .judge import DEFAULT_ROOT

SPLIT = "holdout-r6"
ROUND_CASES = 30
TOPICS = [(t, k or t.lower(), "stem") for t, k in [
    ('Retrieval-augmented generation', None),
    ('Prompt engineering', None),
    ('Self-supervised learning', None),
    ('Neural architecture search', None),
    ('Active learning (machine learning)', None),
    ('Graph database', None),
    ('Vector database', None),
    ('Serverless computing', None),
    ('Fog computing', None),
    ('Blockchain oracle', None),
    ('Quantum key distribution', None),
    ('Quantum error correction', None),
    ('Single-cell sequencing', None),
    ('Prime editing', None),
    ('Long COVID', None),
    ('Antibody–drug conjugate', 'antibody-drug conjugate'),
    ('Liquid biopsy', None),
    ('Microbiome', None),
    ('Wearable technology', None),
    ('Brain–computer interface', None),
    ('Soft robotics', None),
    ('3D printing', None),
    ('Carbon nanotube', None),
    ('Direct air capture', None)]] + [
    (t, k or t.lower(), "society") for t, k in [
    ('Conditional cash transfer', None),
    ('Carbon tariff', None),
    ('Housing First', 'housing first'),
    ('Nudge theory', None),
    ('Effective altruism', None),
    ('Creator economy', None),
    ('Attention economy', None),
    ('Surveillance capitalism', None),
    ('Right to repair', None),
    ('Fast fashion', None),
    ('Overtourism', None),
    ('Food sovereignty', None),
    ('Land value tax', None),
    ('Citizen science', None),
    ('Deliberative democracy', None),
    ('Choice architecture', None),
    ('Social prescribing', None),
    ('Peer-to-peer lending', None)]]


def step(root: Path = DEFAULT_ROOT, get=None, papers_source: str = "openalex") -> dict:
    kwargs = {"papers_source": papers_source} if get is None else {"get": get, "papers_source": papers_source}
    return _step(root, split=SPLIT, topics=TOPICS, progress_name="r6-progress.json",
                 purpose="topic-evidence-brief v2 gate round 1 (11-18/19)", target=ROUND_CASES, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--papers-source", choices=("openalex", "crossref"), default="openalex")
    args = parser.parse_args(argv)
    print(json.dumps(step(args.root, papers_source=args.papers_source), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

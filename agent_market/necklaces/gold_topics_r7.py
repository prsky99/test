"""topic-evidence-brief holdout-r7: a fresh 30-case sample for topic-evidence-brief v2 gate round 2 (11-19) (PM 11-16 18:3x).

Built exactly like holdout-r3 to r5 (gold_topics_r3.step: one Wikipedia batch, OpenAlex most cited per topic, resumable
under the ledger as reference_checks). Ops runs it on 11-19 within that day's OpenAlex share (40 reference checks):
the builder stops once 30 topics, in this fixed order, have papers, so up to 10 topics may drop before the set
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

SPLIT = "holdout-r7"
ROUND_CASES = 30
TOPICS = [(t, k or t.lower(), "stem") for t, k in [
    ('Quantum simulator', None),
    ('Neural radiance field', None),
    ('Mixture of experts', None),
    ('Speculative decoding', None),
    ('Model compression', None),
    ('Adversarial machine learning', None),
    ('Machine unlearning', None),
    ('Synthetic data', None),
    ('TinyML', None),
    ('Threshold cryptosystem', None),
    ('Confidential computing', None),
    ('Software supply chain', None),
    ('Memory safety', None),
    ('WebAssembly', None),
    ('Microservices', None),
    ('Chaos engineering', None),
    ('Digital phenotyping', None),
    ('Precision agriculture', None),
    ('Vertical farming', None),
    ('Cultured meat', None),
    ('Phage therapy', None),
    ('Senolytic', None),
    ('Psychedelic therapy', None),
    ('Exascale computing', None)]] + [
    (t, k or t.lower(), "society") for t, k in [
    ('Four-day workweek', None),
    ('Doughnut (economic model)', 'doughnut economics'),
    ('Degrowth', None),
    ('Carbon price', None),
    ('Just transition', None),
    ('Climate finance', None),
    ('Loss and damage (climate change)', 'loss and damage climate change'),
    ('Payment for ecosystem services', None),
    ('Social impact bond', None),
    ('Community land trust', None),
    ('Child care', None),
    ('Brain circulation', None),
    ('Gig worker', None),
    ('Digital Services Act', None),
    ('Digital sovereignty', None),
    ('Data cooperative', None),
    ('Algorithmic management', None),
    ('Employee monitoring', None),
    ('Polycrisis', None),
    ('Filter bubble', None)]]


def step(root: Path = DEFAULT_ROOT, get=None, papers_source: str = "openalex") -> dict:
    kwargs = {"papers_source": papers_source} if get is None else {"get": get, "papers_source": papers_source}
    return _step(root, split=SPLIT, topics=TOPICS, progress_name="r7-progress.json",
                 purpose="topic-evidence-brief v2 gate round 2 (11-19)", target=ROUND_CASES, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--papers-source", choices=("openalex", "crossref"), default="openalex")
    args = parser.parse_args(argv)
    print(json.dumps(step(args.root, papers_source=args.papers_source), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

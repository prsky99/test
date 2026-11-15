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


def step(root: Path = DEFAULT_ROOT, get=None) -> dict:
    kwargs = {} if get is None else {"get": get}
    return _step(root, split=SPLIT, topics=TOPICS, progress_name="r4-progress.json",
                 purpose="wiki-grounding and arxiv-search re-verdicts after 78caa6e4 (11-16)", **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(step(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

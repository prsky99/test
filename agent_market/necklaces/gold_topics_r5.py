"""topic-evidence-brief holdout-r5: a second fresh sample, for round 2 of the necklace's launch gate (PM 11-16 06:5x:
publish topic-evidence-brief today; the gate needs 60 unseen held-out cases in two rounds of 30).

Built exactly like holdout-r3 and r4 (gold_topics_r3.step: Wikipedia batch, OpenAlex most cited per topic, resumable
under the ledger as reference_checks). Topics: science, technology and the social sciences, none used in tuning,
holdout-r1 to r4; not filtered by any source's coverage; the manifest entry names the selection and truth sources.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gold_topics_r3 import step as _step
from .judge import DEFAULT_ROOT

SPLIT = "holdout-r5"
TOPICS = [(t, k or t.lower(), "stem") for t, k in [
    ("Microfluidics", None), ("Metabolomics", None), ("Proteomics", None), ("Organoid", None), ("Pharmacogenomics", None),
    ("Bioprinting", "3d bioprinting"), ("Neuromorphic engineering", "neuromorphic"), ("Photonic crystal", None),
    ("Plasmonics", None), ("Thermoelectric materials", "thermoelectric"), ("Sodium-ion battery", None),
    ("Vehicle-to-grid", None), ("Smart grid", None), ("Digital twin", None), ("Federated search", None),
    ("Knowledge distillation", None), ("Few-shot learning", None), ("Data lake", None),
    ("Post-traumatic stress disorder", None), ("Sarcopenia", None), ("Urban agriculture", None)]] + [
    (t, k or t.lower(), "society") for t, k in [
    ("Universal design", None), ("Participatory budgeting", None), ("Open data", None), ("Algorithmic trading", None),
    ("Green infrastructure", None), ("Microcredit", None), ("Impact investing", None), ("Corporate venture capital", None),
    ("Remittance", None), ("Energy transition", None), ("Carbon offset", None), ("Plastic pollution", None),
    ("Social robot", None), ("E-government", None), ("Digital health", None), ("Media literacy", None),
    ("Quiet quitting", None), ("Platform cooperative", None), ("Loss aversion", None)]]


def step(root: Path = DEFAULT_ROOT, get=None) -> dict:
    kwargs = {} if get is None else {"get": get}
    return _step(root, split=SPLIT, topics=TOPICS, progress_name="r5-progress.json",
                 purpose="topic-evidence-brief launch gate round 2 (11-16)", **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(step(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

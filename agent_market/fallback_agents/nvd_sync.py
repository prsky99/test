"""Build or refresh the local NVD snapshot (see ``nvd_store``). Kept apart so ``-m`` runs cleanly."""
import argparse
import json
from pathlib import Path

from .nvd_store import Snapshot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build or refresh the local NVD snapshot for the nvd-cve fallback.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", action="store_true")
    group.add_argument("--update", action="store_true")
    parser.add_argument("--path", type=Path, default=None)
    args = parser.parse_args(argv)
    report = Snapshot(args.path).sync("full" if args.full else "update")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

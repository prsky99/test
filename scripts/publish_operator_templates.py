"""Explicit additive publication of execution-reviewed operator templates."""

import argparse
import json
from pathlib import Path

from agent_market.operator_workflow_templates import install, review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument(
        "--catalog", choices=("initial", "categories"), default="initial"
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--verify-only", action="store_true")
    modes.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    recipes = None
    minimums = None
    if args.catalog == "categories":
        from agent_market.operator_workflow_categories import (
            definitions,
            CATEGORY_NAMES,
        )

        recipes = definitions
        minimums = {key: 3 for key in CATEGORY_NAMES}
    if args.verify_only:
        approved = review(args.proof, recipes=recipes)
        print(json.dumps({"qualified": list(approved), "applied": False}))
        return 0 if approved else 1
    from agent_market.application_runtime import open_runtime_storage
    from scripts.agentcon_config import read_settings

    root = Path(__file__).resolve().parents[1]
    runtime = open_runtime_storage(
        ":memory:", values=read_settings(root / "gateway-data/agentcon.env")
    )
    try:
        templates = install(
            runtime.store, args.proof, recipes=recipes, minimum_per_category=minimums
        )
        print(
            json.dumps(
                {
                    "templates": templates,
                    "applied": True,
                    "server_restarted": False,
                    "customer_workflows_modified": False,
                }
            )
        )
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

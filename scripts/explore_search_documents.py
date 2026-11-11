"""Explicit PostgreSQL search-document provisioning and bounded maintenance.

This command never restarts a service, changes execution authority or installs
OpenSearch. Status reads only counts; refresh publishes derived search facts.
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "install", "refresh"))
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--batch", type=int, default=25)
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.batch <= 100 or not 1 <= args.rounds <= 100:
        parser.error("Use batch 1–100 and rounds 1–100.")
    from scripts.agentcon_config import read_settings
    from agent_market.application_runtime import _connect, _private_bytes
    from agent_market.storage_adapter import open_store
    from agent_market import explore_documents as documents

    settings = read_settings(args.root / "gateway-data/agentcon.env")
    connection = _connect(
        _private_bytes(settings["APPLICATION_POSTGRES_DSN_FILE"], 16384)
        .decode()
        .strip()
    )
    if args.action == "status":
        connection.execute("SET default_transaction_read_only=on")
    store = open_store(
        "postgresql",
        connection=connection,
        workflow_key=_private_bytes(settings["APPLICATION_WORKFLOW_KEY_FILE"], 32),
    )
    try:
        if args.action == "install":
            result = documents.install(store)
        elif args.action == "refresh":
            worker = documents.Refresher(store, batch=args.batch, interval=0)
            results = []
            for _ in range(args.rounds):
                row = worker.run()
                results.append(row)
                if not row["checked"] and not row.get("unchanged"):
                    break
            result = {"rounds": results}
        else:
            with store.tx(readonly=True):
                installed = documents.available(store)
                result = {"installed": installed}
                if installed:
                    for table, key in (
                        ("explore_documents", "documents"),
                        ("explore_document_queue", "queued"),
                    ):
                        result[key] = store._execute(
                            "SELECT count(*) FROM agentcon_search." + table
                        ).fetchone()[0]
                    result["current_policy_documents"] = store._execute(
                        "SELECT count(*) FROM agentcon_search.explore_documents WHERE policy_hash=%s",
                        (documents.policy_hash(),),
                    ).fetchone()[0]
        print(json.dumps(result))
    finally:
        store.close()
        connection.close()


if __name__ == "__main__":
    main()

"""Inventory legacy visitor tokens without printing credential values."""

import argparse
import json

from agent_market.concierge.token_hygiene import inventory_and_scrub


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", action="append", required=True)
    parser.add_argument("--apply", action="store_true", help="Mask raw token text after creating a private rollback file")
    parser.add_argument("--backup-dir", help="Private, untracked directory with owner-only permissions")
    args = parser.parse_args()
    if args.apply and not args.backup_dir:
        parser.error("--apply requires --backup-dir")
    for database in args.db:
        print(json.dumps(inventory_and_scrub(database, apply=args.apply, backup_dir=args.backup_dir)))


if __name__ == "__main__":
    main()

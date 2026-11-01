"""Audit fixed repository storage evidence; no database/path/DSN option."""
from pathlib import Path
import sys


def main():
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from agent_market.store_migration_readiness import main as audit
    return audit()


if __name__ == '__main__':
    raise SystemExit(main())

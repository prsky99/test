#!/usr/bin/env python3
"""Historical single-report transformation experiment is retired.

Use explicit --db paths for the shared read-only aggregate report inventory.
Importing this compatibility entry point never opens or changes a database.
"""
try:
    from .migrate_all_to_gateway import main
except ImportError:
    from migrate_all_to_gateway import main


if __name__ == '__main__':
    raise SystemExit(main())

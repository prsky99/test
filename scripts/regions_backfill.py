"""Re-derive resources.regions from the listing text for the rows whose value changes (real task a05, 11-13).

The region table (gateway/constraints.REGIONS) gained Poland and other country names. Raising
gateway/store.CONSTRAINTS_VERSION would rewrite all ~419k rows in one transaction at start-up. This
changes only the rows whose packed regions differ, in short batches. Each changed row fires the
public.resources trigger: its vector is invalidated and queued again, so it leaves vector search
until jobs re-embeds it (2026-11-09: about 2 per second). Run it at night.

    .venv/bin/python -m scripts.regions_backfill count --dsn-file <dsn>          # read-only
    .venv/bin/python -m scripts.regions_backfill apply --dsn-file <dsn> --i-have-approval
"""
import argparse
import json
import sys
import time

import psycopg

from agent_market.gateway import constraints as cons

READ_BATCH = 5000
WRITE_BATCH = 200


def wanted(name, description):
    """The value gateway/store._text_constraints writes for this text."""
    return cons.pack(cons.regions_in_text(f"{name} {description}"))


def changes(connection):
    """[(id, old, new)] for every row whose regions value differs; streamed in id order."""
    found, last = [], 0
    while True:
        rows = connection.execute("""SELECT id, name, description, regions FROM public.resources
            WHERE id > %s ORDER BY id LIMIT %s""", (last, READ_BATCH)).fetchall()
        if not rows:
            return found
        for rid, name, description, regions in rows:
            value = wanted(name or '', description or '')
            if (value or None) != (regions or None):
                found.append((rid, regions, value))
        last = rows[-1][0]


def summary(found):
    added = {}
    for _, old, new in found:
        for code in set(str(new or '').strip(',').split(',')) - set(str(old or '').strip(',').split(',')) - {''}:
            added[code] = added.get(code, 0) + 1
    return {'rows': len(found), 'codes_added': dict(sorted(added.items(), key=lambda kv: -kv[1]))}


def apply(connection, found):
    began, done = time.monotonic(), 0
    for start in range(0, len(found), WRITE_BATCH):
        chunk = found[start:start + WRITE_BATCH]
        with connection.transaction():
            for rid, old, new in chunk:
                done += connection.execute("""UPDATE public.resources SET regions=%s
                    WHERE id=%s AND regions IS NOT DISTINCT FROM %s""", (new, rid, old)).rowcount
        time.sleep(0.2)
    return {'updated': done, 'seconds': round(time.monotonic() - began, 1)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('action', choices=('count', 'apply'))
    parser.add_argument('--dsn-file', required=True)
    parser.add_argument('--i-have-approval', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'apply' and not args.i_have_approval:
        parser.error('apply writes production rows; pass --i-have-approval only after approval')
    dsn = open(args.dsn_file).read().strip()
    options = '-c statement_timeout=60000' + (' -c default_transaction_read_only=on' if args.action == 'count' else '')
    with psycopg.connect(dsn, autocommit=True, options=options) as connection:
        began = time.monotonic()
        found = changes(connection)
        result = {**summary(found), 'scan_seconds': round(time.monotonic() - began, 1)}
        if args.action == 'apply':
            result.update(apply(connection, found))
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())

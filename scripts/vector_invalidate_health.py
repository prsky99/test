"""Stop a health change from invalidating a listing's vector (2026-11-11, PM decision; user approval required).

application_vector_invalidate (a public trigger function) bumped the vector generation, deleted the
provenance and the legacy vector on every health_status change. Search filters health at query time,
so the same text was queued and its vector rewritten on every health flap (3,643 of 6,585 listings
re-indexed in one hour had their previous text). The new body leaves health_status out of the
changed-field list; eval_security (quarantine) and every text field still invalidate.

The body is taken from the application's own definition (_invariant_ddl), because every attachment
compares pg_proc.prosrc with it exactly. Order: deploy code that accepts both bodies to every role
(VECTOR_HEALTH_DEFAULT stays True), rehearse, approve, apply. The trigger itself and the public
trigger count (5) do not change. One connection.

    .venv/bin/python -m scripts.vector_invalidate_health status --dsn-file <dsn>
    .venv/bin/python -m scripts.vector_invalidate_health apply  --dsn-file <dsn> --i-have-approval
    .venv/bin/python -m scripts.vector_invalidate_health rollback --dsn-file <dsn> --i-have-approval
"""
import argparse
import json
import sys

import psycopg

from agent_market.application_store_postgres import _invariant_ddl

NAME = 'application_vector_invalidate'


def definition(health):
    sql = next(sql for sql in _invariant_ddl(vector_health=health) if sql.startswith('CREATE FUNCTION %s()' % NAME))
    return sql.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION public.', 1).replace('public. ' + NAME, 'public.' + NAME, 1)


def body(health):
    return definition(health).split('$$')[1]


def status(connection):
    source = connection.execute("""SELECT p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.proname=%s""", (NAME,)).fetchall()
    triggers = connection.execute("""SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal""").fetchone()[0]
    current = source[0][0] if len(source) == 1 else None
    return {'body': 'health_invalidates' if current == body(True) else 'health_kept' if current == body(False) else 'unknown',
            'public_triggers': triggers}


def change(connection, health):
    before = status(connection)
    if before['body'] == 'unknown' or before['public_triggers'] != 5:
        raise SystemExit('refused: unexpected starting state %s' % before)
    connection.execute("SET lock_timeout='2s'")
    connection.execute(definition(health))
    after = status(connection)
    if after['public_triggers'] != 5 or after['body'] != ('health_invalidates' if health else 'health_kept'):
        raise SystemExit('unexpected result %s' % after)
    return {'before': before, 'after': after}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('action', choices=('status', 'apply', 'rollback'))
    parser.add_argument('--dsn-file', required=True)
    parser.add_argument('--i-have-approval', action='store_true')
    args = parser.parse_args(argv)
    if args.action != 'status' and not args.i_have_approval:
        parser.error(args.action + ' changes the database; pass --i-have-approval only after approval')
    with psycopg.connect(open(args.dsn_file).read().strip(), autocommit=True) as connection:
        if args.action == 'apply':
            result = change(connection, False)
        elif args.action == 'rollback':
            result = change(connection, True)
        else:
            result = status(connection)
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())

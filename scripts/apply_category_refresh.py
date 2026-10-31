"""Refresh stored categories to the current classifier rules (PostgreSQL catalog).

Usage:
    python -m scripts.apply_category_refresh            # dry run: counts only
    python -m scripts.apply_category_refresh --apply    # writes a backup, then updates

Directly registered listings keep their declared category, as in the SQLite
refresh. Each update is compare-and-set on the category that was read, and the
backup file lists every (id, old, new) so the change can be reverted with --revert.
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def open_store():
    from scripts.agentcon_config import read_settings
    from agent_market.application_runtime import _private_bytes, _connect
    from agent_market.storage_adapter import open_store as open_application
    settings = read_settings(str(ROOT / 'gateway-data/agentcon.env'))
    def path(name):
        value = Path(settings[name])
        return str(value if value.is_absolute() else ROOT / value)
    connection = _connect(_private_bytes(path('APPLICATION_POSTGRES_DSN_FILE'), 16384).decode().strip())
    store = open_application('postgresql', connection=connection,
                             workflow_key=_private_bytes(path('APPLICATION_WORKFLOW_KEY_FILE'), 32),
                             required_capabilities=('full_application',))
    return store, connection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--revert', metavar='BACKUP')
    args = parser.parse_args()
    from agent_market.gateway.classify import classify_listing, VERSION
    from agent_market.gateway.store import extract_tool_search_text, LEGACY_ALIASES
    store, connection = open_store()
    try:
        if args.revert:
            rows = [json.loads(line) for line in Path(args.revert).open(encoding='utf-8')]
            reverted = 0
            for start in range(0, len(rows), 500):
                with store.tx():
                    for row in rows[start:start + 500]:
                        reverted += store._execute('UPDATE public.resources SET category=%s WHERE id=%s AND category=%s',
                                                   (row['old'], row['id'], row['new'])).rowcount
            print(json.dumps({'reverted': reverted, 'rows': len(rows)}))
            return
        changes, moves = [], collections.Counter()
        with store.tx(readonly=True):
            cursor = connection.cursor(name='category_refresh')
            cursor.execute('SELECT id,source,name,description,category,usage_tools FROM public.resources')
            for rid, source, name, description, category, tools in cursor:
                if source == 'registered':
                    new = LEGACY_ALIASES.get(category, category)
                else:
                    new = classify_listing(f"{name or ''} {description or ''}",
                                           extract_tool_search_text(tools) if tools else '')
                if new != category:
                    changes.append({'id': rid, 'old': category, 'new': new})
                    moves[(category, new)] += 1
            cursor.close()
        summary = {'classifier_version': VERSION, 'changes': len(changes),
                   'top_moves': [[a, b, n] for (a, b), n in moves.most_common(10)]}
        if not args.apply:
            print(json.dumps({'dry_run': True, **summary}))
            return
        backup = ROOT / 'gateway-data' / 'backups' / f'category-refresh-{time.strftime("%Y%m%d-%H%M%S")}.jsonl'
        backup.parent.mkdir(parents=True, exist_ok=True)
        with backup.open('w', encoding='utf-8') as handle:
            for row in changes:
                handle.write(json.dumps(row) + '\n')
        updated = 0
        for start in range(0, len(changes), 500):
            with store.tx():
                for row in changes[start:start + 500]:
                    updated += store._execute('UPDATE public.resources SET category=%s WHERE id=%s AND category=%s',
                                              (row['new'], row['id'], row['old'])).rowcount
        print(json.dumps({'applied': True, 'updated': updated, 'backup': str(backup.relative_to(ROOT)), **summary}))
    finally:
        store.close()
        connection.close()


if __name__ == '__main__':
    main()

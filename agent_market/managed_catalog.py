"""Local lifecycle ownership, separate from upstream discovery membership."""
import time

RESOURCE_COLUMNS = {
    'registry_missing_since': 'REAL',
    'managed_at': 'REAL',
    'inactive_reason': 'TEXT',
}


def ensure_schema(db):
    columns = {row[1] for row in db.execute('PRAGMA table_info(resources)')}
    for name, declaration in RESOURCE_COLUMNS.items():
        if name not in columns:
            db.execute(f'ALTER TABLE resources ADD COLUMN {name} {declaration}')
    db.execute('CREATE INDEX IF NOT EXISTS resources_source_seen ON resources(source,last_seen)')
    # Adopt existing observations without inventing a successful verification.
    db.execute('''UPDATE resources SET managed_at=last_check_at
                  WHERE managed_at IS NULL AND last_check_at IS NOT NULL''')


def mark_missing(db, source, before, now=None):
    """A completed discovery scan changes membership metadata only."""
    return db.execute('''UPDATE resources SET registry_missing_since=?
        WHERE source=? AND last_seen<? AND registry_missing_since IS NULL''',
        (time.time() if now is None else now, source, before)).rowcount


def mark_ids_missing(db, identities, now=None):
    moment = time.time() if now is None else now
    changed = 0
    for identity in identities:
        changed += db.execute('''UPDATE resources
            SET registry_missing_since=COALESCE(registry_missing_since,?) WHERE id=?''',
            (moment, identity)).rowcount
    return changed

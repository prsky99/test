"""Fixed SQLite indexes for catalog readers and shared evaluation; no row changes."""
import re
import sqlite3


LIVE_PREDICATE = "active=1 AND health_status IN ('healthy','reachable') AND COALESCE(eval_security,'') != 'quarantine'"
INDEX_DEFINITIONS = (
    ('resources_live_recent_kind',
     'CREATE INDEX resources_live_recent_kind ON resources(kind,COALESCE(first_seen,0) DESC,id DESC) WHERE '+LIVE_PREDICATE),
    ('resources_live_recent',
     'CREATE INDEX resources_live_recent ON resources(active,COALESCE(first_seen,0) DESC,id DESC,kind) WHERE '+LIVE_PREDICATE),
    ('resources_front_count',
     'CREATE INDEX resources_front_count ON resources(active,health_status,kind,category,eval_security,auth_observed,auth_declared)'),
    ('resources_evaluation_count',
     'CREATE INDEX resources_evaluation_count ON resources(active,kind,eval_score)'),
)
_REQUIRED_COLUMNS = frozenset(('id','kind','active','health_status','eval_security','first_seen',
                               'category','auth_observed','auth_declared','eval_score'))


class IndexSetupError(ValueError):
    """Expose a bounded operation code, never database content or a private path."""


def _canonical_sql(sql):
    tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]",sql or '')
    return tuple(token if token[:1] in ("'",'"') else token.casefold() for token in tokens)


def inspect_front_query_indexes(db):
    """Refuse an unexpected schema or another owner's conflicting named object."""
    if not isinstance(db,sqlite3.Connection):raise IndexSetupError('sqlite_required')
    table = db.execute("SELECT type FROM sqlite_master WHERE name='resources' COLLATE NOCASE").fetchone()
    columns = {row[1] for row in db.execute('PRAGMA table_info(resources)')}
    if not table or table[0]!='table' or not _REQUIRED_COLUMNS.issubset(columns):
        raise IndexSetupError('catalog_schema_required')
    present,missing = [],[]
    for name,sql in INDEX_DEFINITIONS:
        row = db.execute('SELECT type,tbl_name,sql FROM sqlite_master WHERE name=? COLLATE NOCASE',(name,)).fetchone()
        if row is None:
            missing.append(name)
        elif row[0]!='index' or row[1].casefold()!='resources' or _canonical_sql(row[2])!=_canonical_sql(sql):
            raise IndexSetupError('index_name_conflict')
        else:present.append(name)
    return {'present':present,'missing':missing}


def ensure_front_query_indexes(db):
    """Install fixed definitions atomically without committing caller work."""
    inspect_front_query_indexes(db)
    owned = not db.in_transaction
    db.execute('BEGIN IMMEDIATE' if owned else 'SAVEPOINT a2a_front_query_indexes')
    try:
        before = inspect_front_query_indexes(db)
        for name,sql in INDEX_DEFINITIONS:
            if name in before['missing']:db.execute(sql)
        if owned:db.commit()
        else:db.execute('RELEASE SAVEPOINT a2a_front_query_indexes')
        return {'created':len(before['missing']),'existing':len(before['present'])}
    except BaseException:
        if owned:db.rollback()
        else:
            db.execute('ROLLBACK TO SAVEPOINT a2a_front_query_indexes')
            db.execute('RELEASE SAVEPOINT a2a_front_query_indexes')
        raise

"""Private bounded catalog read pilot; no Store wiring, schema or public DTO.

JSON remains raw text. Content hashes are registry freshness preconditions, not
connection versions or execution evidence. Explicit ID ordering is pagination,
not search relevance or recommendation quality. Caller owns the adapter.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import math
import re
import threading

from .storage_adapter import SQLiteAdapter, PostgresAdapter, Statement

PROFILE = 'bounded-catalog-read-v1'
MAX_BATCH = 50
MAX_PAGE = 50
COLUMNS = ('id','key','source','kind','url','name','description','category','active',
           'first_seen','last_seen','health_status','last_check_at','last_ok_at',
           'eval_score','eval_grade','eval_security','eval_at','content_hash',
           'auth_declared','auth_observed','auth_info','details','usage_tools',
           'usage_full_tools','usage_full_hash','usage_tools_hash','usage_guide')
HEALTH = frozenset(('unknown','healthy','reachable','failing','down','retired'))
KINDS = frozenset(('a2a','mcp','x402'))
ERRORS = frozenset(('invalid_request','invalid_record','stale_resource','session_closed','thread_violation','isolation_required'))


class CatalogError(ValueError):
    def __init__(self, code='invalid_request'):
        self.code = code if code in ERRORS else 'invalid_request'
        super().__init__(self.code)


def _text(value, maximum, *, nullable=False, code='invalid_request'):
    if value is None and nullable: return value
    if type(value) is not str or '\0' in value: raise CatalogError(code)
    try: size = len(value.encode('utf-8'))
    except UnicodeError: raise CatalogError(code) from None
    if size > maximum: raise CatalogError(code)
    return value


def _id(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value < 2**63:
        raise CatalogError()
    return value


def _time(value, *, nullable=False, code='invalid_request'):
    if value is None and nullable: return value
    if type(value) not in (int,float) or not 0 <= value < 2**53 or not math.isfinite(value):
        raise CatalogError(code)
    return value


@dataclass(frozen=True)
class CatalogFilter:
    kind: str | None = None
    category: str | None = None
    source: str | None = None
    active: bool | None = None
    health_status: str | None = None
    min_last_seen: float | None = None

    def __post_init__(self):
        if self.kind is not None and (type(self.kind) is not str or self.kind not in KINDS): raise CatalogError()
        for value in (self.category,self.source):
            if value is not None: _text(value,256)
        if self.active is not None and type(self.active) is not bool: raise CatalogError()
        if self.health_status is not None and (type(self.health_status) is not str or self.health_status not in HEALTH): raise CatalogError()
        _time(self.min_last_seen,nullable=True)

    def _values(self):
        active = None if self.active is None else int(self.active)
        return (self.kind,self.kind,self.category,self.category,self.source,self.source,
                active,active,self.health_status,self.health_status,self.min_last_seen,self.min_last_seen)


@dataclass(frozen=True, repr=False)
class CatalogResource:
    """Selected raw private columns; never serialize this as a public response."""
    _values: tuple

    def __repr__(self): return '<CatalogResource private>'
    @property
    def id(self): return self._values[0]
    @property
    def content_hash(self): return self._values[18]
    def as_private_dict(self): return dict(zip(COLUMNS,self._values))


@dataclass(frozen=True, repr=False)
class CatalogBatch:
    found: tuple
    missing: tuple

    def __repr__(self): return '<CatalogBatch private>'


def _record(row):
    values = tuple(row)
    if tuple(row.keys()) != COLUMNS or len(values) != len(COLUMNS): raise CatalogError('invalid_record')
    data = dict(zip(COLUMNS,values))
    try: _id(data['id'])
    except CatalogError: raise CatalogError('invalid_record') from None
    for name,maximum in (('key',512),('source',256),('url',4096),('name',1024),('description',8192),('category',256)):
        _text(data[name],maximum,code='invalid_record')
    if data['kind'] not in KINDS or type(data['kind']) is not str: raise CatalogError('invalid_record')
    if type(data['active']) is not int or data['active'] not in (0,1): raise CatalogError('invalid_record')
    if data['health_status'] is not None and (type(data['health_status']) is not str or data['health_status'] not in HEALTH): raise CatalogError('invalid_record')
    for name in ('first_seen','last_seen'): _time(data[name],code='invalid_record')
    for name in ('last_check_at','last_ok_at','eval_at'): _time(data[name],nullable=True,code='invalid_record')
    score=data['eval_score']
    if score is not None and (type(score) not in (int,float) or not math.isfinite(score) or not 0 <= score <= 100): raise CatalogError('invalid_record')
    for name in ('auth_declared','auth_observed'):
        if data[name] is not None and (type(data[name]) is not int or data[name] not in (0,1)): raise CatalogError('invalid_record')
    for name in ('content_hash','usage_full_hash','usage_tools_hash'):
        _text(data[name],256,nullable=True,code='invalid_record')
    for name in ('eval_grade','eval_security'):
        _text(data[name],64,nullable=True,code='invalid_record')
    for name in ('auth_info','details','usage_tools','usage_full_tools','usage_guide'):
        _text(data[name],16384,nullable=True,code='invalid_record')
    return CatalogResource(values)


_SELECT = 'SELECT '+','.join(COLUMNS)+' FROM resources'
# Both dialects are declared explicitly. No user value becomes SQL text.
_GET = Statement('catalog.get',_SELECT+' WHERE id=?',_SELECT+' WHERE id=%s',readonly=True)
_KEY = Statement('catalog.key',_SELECT+' WHERE key=?',_SELECT+' WHERE key=%s',readonly=True)
_BATCH = Statement('catalog.batch',_SELECT+' WHERE id IN ('+','.join(('?',)*MAX_BATCH)+')',
                   _SELECT+' WHERE id IN ('+','.join(('%s',)*MAX_BATCH)+')',readonly=True)
_WHERE_SQLITE = ' WHERE (? IS NULL OR kind=?) AND (? IS NULL OR category=?) AND (? IS NULL OR source=?) AND (? IS NULL OR active=?) AND (? IS NULL OR health_status=?) AND (? IS NULL OR last_seen>=?)'
_WHERE_PG = ' WHERE (%s::text IS NULL OR kind=%s) AND (%s::text IS NULL OR category=%s) AND (%s::text IS NULL OR source=%s) AND (%s::integer IS NULL OR active=%s) AND (%s::text IS NULL OR health_status=%s) AND (%s::double precision IS NULL OR last_seen>=%s)'
_LIST = Statement('catalog.list',_SELECT+_WHERE_SQLITE+' AND id>? ORDER BY id ASC LIMIT ?',
                  _SELECT+_WHERE_PG+' AND id>%s ORDER BY id ASC LIMIT %s',readonly=True)
_COUNT = Statement('catalog.count','SELECT COUNT(*) AS n FROM resources'+_WHERE_SQLITE,
                   'SELECT COUNT(*) AS n FROM resources'+_WHERE_PG,readonly=True)
_ISOLATION = Statement('catalog.isolation',"SELECT CASE read_uncommitted WHEN 0 THEN 'serializable' ELSE 'read uncommitted' END AS isolation FROM pragma_read_uncommitted()",
                       "SELECT current_setting('transaction_isolation') AS isolation",readonly=True)


class _CatalogView:
    def __init__(self,session):
        self._session,self._active,self._owner = session,True,threading.get_ident()

    def _check(self):
        if not self._active: raise CatalogError('session_closed')
        if self._owner != threading.get_ident(): raise CatalogError('thread_violation')

    def get(self,rid,*,expected_hash=None):
        self._check();_id(rid)
        if expected_hash is not None:
            if type(expected_hash) is not str or not re.fullmatch('[0-9a-f]{64}',expected_hash): raise CatalogError()
        rows=self._session.execute(_GET,(rid,)).rows
        result=_record(rows[0]) if rows else None
        if expected_hash is not None and (result is None or result.content_hash != expected_hash): raise CatalogError('stale_resource')
        return result

    def get_by_key(self,key):
        self._check();_text(key,512)
        rows=self._session.execute(_KEY,(key,)).rows
        return _record(rows[0]) if rows else None

    def batch(self,ids):
        self._check()
        if type(ids) is not tuple or len(ids)>MAX_BATCH: raise CatalogError()
        for rid in ids: _id(rid)
        unique=tuple(dict.fromkeys(ids))
        if not unique: return CatalogBatch((),())
        rows=self._session.execute(_BATCH,unique+(None,)*(MAX_BATCH-len(unique))).rows
        found={record.id:record for record in map(_record,rows)}
        return CatalogBatch(tuple(found[rid] for rid in unique if rid in found),tuple(rid for rid in unique if rid not in found))

    def list(self,filters=CatalogFilter(),*,limit=MAX_PAGE,after_id=0):
        self._check()
        if type(filters) is not CatalogFilter or type(limit) is not int or not 1 <= limit <= MAX_PAGE: raise CatalogError()
        _id(after_id,zero=True)
        return tuple(map(_record,self._session.execute(_LIST,filters._values()+(after_id,limit)).rows))

    def count(self,filters=CatalogFilter()):
        self._check()
        if type(filters) is not CatalogFilter: raise CatalogError()
        value=self._session.execute(_COUNT,filters._values()).rows[0]['n']
        if type(value) is not int or not 0 <= value < 2**63: raise CatalogError('invalid_record')
        return value


class CatalogRepository:
    """Read-only subset over an explicit adapter; never initializes a schema."""
    def __init__(self,adapter):
        if type(adapter) not in (SQLiteAdapter,PostgresAdapter): raise CatalogError()
        self._adapter=adapter

    @contextmanager
    def snapshot(self):
        with self._adapter.transaction(readonly=True) as session:
            # The caller configures isolation before attaching the adapter.
            # Reject dirty/statement snapshots rather than claiming repeatable
            # catalog reads. Never mutate caller isolation configuration.
            isolation=session.execute(_ISOLATION).rows[0]['isolation']
            if isolation not in ('repeatable read','serializable'): raise CatalogError('isolation_required')
            view=_CatalogView(session)
            try: yield view
            finally: view._active=False

    def get(self,rid,*,expected_hash=None):
        with self.snapshot() as view:return view.get(rid,expected_hash=expected_hash)
    def get_by_key(self,key):
        with self.snapshot() as view:return view.get_by_key(key)
    def batch(self,ids):
        with self.snapshot() as view:return view.batch(ids)
    def list(self,filters=CatalogFilter(),*,limit=MAX_PAGE,after_id=0):
        with self.snapshot() as view:return view.list(filters,limit=limit,after_id=after_id)
    def count(self,filters=CatalogFilter()):
        with self.snapshot() as view:return view.count(filters)

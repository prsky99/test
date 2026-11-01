"""Private revision-bound index metadata; no embeddings, schema auto-init or Store.

The writer enqueues through its existing explicit Session. Workers compute any
future index outside transactions, then publish only a hash under head/lease/
fence checks. This profile neither implements vectors/FTS nor certifies quality.
"""
from dataclasses import dataclass
import hashlib
import math
import re
import secrets

from .storage_adapter import SQLiteAdapter, PostgresAdapter, Session, Statement

PROFILE = 'revision-bound-catalog-index-v1'
ERROR_CODES = frozenset(('index_failed', 'invalid_projection', 'worker_cancelled'))
STATES = frozenset(('pending', 'claimed', 'indexed', 'failed', 'superseded'))


class IndexOutboxError(ValueError):
    def __init__(self, code='invalid_request'):
        self.code = code if code in ('invalid_request', 'invalid_record', 'stale_revision', 'revision_conflict') else 'invalid_request'
        super().__init__(self.code)


def _integer(value):
    if type(value) is not int or not 1 <= value < 2**63:
        raise IndexOutboxError()
    return value


def _hash(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise IndexOutboxError()
    return value


def _time(value):
    if type(value) not in (int, float) or not 0 <= value < 2**53 or not math.isfinite(value):
        raise IndexOutboxError()
    return value


def _worker(value):
    if type(value) is not str or not re.fullmatch('[A-Za-z0-9_.-]{1,64}', value):
        raise IndexOutboxError()
    return value


def _identity(value):
    if type(value) is not str or not re.fullmatch('cij_[0-9a-f]{64}', value):
        raise IndexOutboxError()
    return value


@dataclass(frozen=True, repr=False)
class IndexJob:
    job_id: str
    resource_id: int
    revision: int
    corpus_hash: str
    model_hash: str
    state: str
    fence: int
    created: float
    updated: float
    error_code: str | None
    projection_hash: str | None

    def __repr__(self):
        return '<IndexJob private>'


@dataclass(frozen=True, repr=False)
class IndexClaim:
    job_id: str
    resource_id: int
    revision: int
    corpus_hash: str
    model_hash: str
    worker_id: str
    token: str
    fence: int
    lease_until: float

    def __repr__(self):
        return '<IndexClaim private>'


@dataclass(frozen=True, repr=False)
class IndexProjection:
    resource_id: int
    revision: int
    corpus_hash: str
    model_hash: str
    projection_hash: str
    job_id: str
    indexed_at: float

    def __repr__(self):
        return '<IndexProjection private>'


INDEX_SCHEMA = (
    Statement('catalog.index_head_schema',
        'CREATE TABLE catalog_index_heads (resource_id INTEGER PRIMARY KEY, model_hash TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), corpus_hash TEXT NOT NULL, updated REAL NOT NULL)',
        'CREATE TABLE catalog_index_heads (resource_id BIGINT PRIMARY KEY, model_hash TEXT NOT NULL, revision BIGINT NOT NULL CHECK(revision>0), corpus_hash TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL)'),
    Statement('catalog.index_job_schema',
        "CREATE TABLE catalog_index_jobs (job_id TEXT PRIMARY KEY, resource_id INTEGER NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), corpus_hash TEXT NOT NULL, model_hash TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','claimed','indexed','failed','superseded')), worker_id TEXT, token TEXT, fence INTEGER NOT NULL DEFAULT 0 CHECK(fence>=0), lease_until REAL, created REAL NOT NULL, updated REAL NOT NULL, finished REAL, error_code TEXT, projection_hash TEXT, UNIQUE(resource_id,revision,corpus_hash,model_hash))",
        "CREATE TABLE catalog_index_jobs (job_id TEXT PRIMARY KEY, resource_id BIGINT NOT NULL, revision BIGINT NOT NULL CHECK(revision>0), corpus_hash TEXT NOT NULL, model_hash TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','claimed','indexed','failed','superseded')), worker_id TEXT, token TEXT, fence BIGINT NOT NULL DEFAULT 0 CHECK(fence>=0), lease_until DOUBLE PRECISION, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL, finished DOUBLE PRECISION, error_code TEXT, projection_hash TEXT, UNIQUE(resource_id,revision,corpus_hash,model_hash))"),
    Statement('catalog.index_projection_schema',
        'CREATE TABLE catalog_index_projections (resource_id INTEGER NOT NULL, model_hash TEXT NOT NULL, revision INTEGER NOT NULL, corpus_hash TEXT NOT NULL, projection_hash TEXT NOT NULL, job_id TEXT NOT NULL, indexed_at REAL NOT NULL, PRIMARY KEY(resource_id,model_hash))',
        'CREATE TABLE catalog_index_projections (resource_id BIGINT NOT NULL, model_hash TEXT NOT NULL, revision BIGINT NOT NULL, corpus_hash TEXT NOT NULL, projection_hash TEXT NOT NULL, job_id TEXT NOT NULL, indexed_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(resource_id,model_hash))'),
    Statement('catalog.index_pending_index',
        'CREATE INDEX catalog_index_jobs_pending ON catalog_index_jobs(state,created,job_id)',
        'CREATE INDEX catalog_index_jobs_pending ON catalog_index_jobs(state,created,job_id)'),
)

_ENSURE_HEAD = Statement('catalog.index_ensure_head',
    'INSERT INTO catalog_index_heads VALUES (?,?,?,?,?) ON CONFLICT(resource_id) DO NOTHING',
    'INSERT INTO catalog_index_heads VALUES (%s,%s,%s,%s,%s) ON CONFLICT(resource_id) DO NOTHING')
_LOCK_HEAD = Statement('catalog.index_lock_head',
    'UPDATE catalog_index_heads SET updated=updated WHERE resource_id=? RETURNING revision,corpus_hash,model_hash',
    'UPDATE catalog_index_heads SET updated=updated WHERE resource_id=%s RETURNING revision,corpus_hash,model_hash')
_ADVANCE_HEAD = Statement('catalog.index_advance_head',
    'UPDATE catalog_index_heads SET revision=?,corpus_hash=?,model_hash=?,updated=? WHERE resource_id=?',
    'UPDATE catalog_index_heads SET revision=%s,corpus_hash=%s,model_hash=%s,updated=%s WHERE resource_id=%s')
_SUPERSEDE_OLD = Statement('catalog.index_supersede_old',
    "UPDATE catalog_index_jobs SET state='superseded',worker_id=NULL,token=NULL,lease_until=NULL,finished=COALESCE(finished,?),updated=? WHERE resource_id=? AND revision<? AND state!='superseded'",
    "UPDATE catalog_index_jobs SET state='superseded',worker_id=NULL,token=NULL,lease_until=NULL,finished=COALESCE(finished,%s),updated=%s WHERE resource_id=%s AND revision<%s AND state!='superseded'")
_INSERT_JOB = Statement('catalog.index_enqueue',
    "INSERT INTO catalog_index_jobs (job_id,resource_id,revision,corpus_hash,model_hash,state,created,updated) VALUES (?,?,?,?,?,'pending',?,?) ON CONFLICT(resource_id,revision,corpus_hash,model_hash) DO NOTHING",
    "INSERT INTO catalog_index_jobs (job_id,resource_id,revision,corpus_hash,model_hash,state,created,updated) VALUES (%s,%s,%s,%s,%s,'pending',%s,%s) ON CONFLICT(resource_id,revision,corpus_hash,model_hash) DO NOTHING")
_GET_JOB = Statement('catalog.index_job',
    'SELECT job_id,resource_id,revision,corpus_hash,model_hash,state,fence,created,updated,error_code,projection_hash FROM catalog_index_jobs WHERE job_id=?',
    'SELECT job_id,resource_id,revision,corpus_hash,model_hash,state,fence,created,updated,error_code,projection_hash FROM catalog_index_jobs WHERE job_id=%s', readonly=True)
_CLAIM = Statement('catalog.index_claim',
    "UPDATE catalog_index_jobs SET state='claimed',worker_id=?,token=?,fence=fence+1,lease_until=?,updated=? WHERE job_id=(SELECT j.job_id FROM catalog_index_jobs j JOIN catalog_index_heads h ON h.resource_id=j.resource_id AND h.model_hash=j.model_hash AND h.revision=j.revision AND h.corpus_hash=j.corpus_hash WHERE j.state='pending' OR (j.state='claimed' AND j.lease_until<=?) ORDER BY j.created,j.job_id LIMIT 1) AND (state='pending' OR (state='claimed' AND lease_until<=?)) RETURNING job_id,resource_id,revision,corpus_hash,model_hash,worker_id,token,fence,lease_until",
    "UPDATE catalog_index_jobs SET state='claimed',worker_id=%s,token=%s,fence=fence+1,lease_until=%s,updated=%s WHERE job_id=(SELECT j.job_id FROM catalog_index_jobs j JOIN catalog_index_heads h ON h.resource_id=j.resource_id AND h.model_hash=j.model_hash AND h.revision=j.revision AND h.corpus_hash=j.corpus_hash WHERE j.state='pending' OR (j.state='claimed' AND j.lease_until<=%s) ORDER BY j.created,j.job_id LIMIT 1) AND (state='pending' OR (state='claimed' AND lease_until<=%s)) RETURNING job_id,resource_id,revision,corpus_hash,model_hash,worker_id,token,fence,lease_until")
_LOCK_EXPECTED_HEAD = Statement('catalog.index_lock_expected_head',
    'UPDATE catalog_index_heads SET updated=updated WHERE resource_id=? AND model_hash=? AND revision=? AND corpus_hash=? RETURNING revision',
    'UPDATE catalog_index_heads SET updated=updated WHERE resource_id=%s AND model_hash=%s AND revision=%s AND corpus_hash=%s RETURNING revision')
_INDEXED = Statement('catalog.index_complete',
    "UPDATE catalog_index_jobs SET state='indexed',worker_id=NULL,token=NULL,lease_until=NULL,projection_hash=?,error_code=NULL,finished=?,updated=? WHERE job_id=? AND resource_id=? AND revision=? AND corpus_hash=? AND model_hash=? AND state='claimed' AND worker_id=? AND token=? AND fence=? AND lease_until=? AND lease_until>? RETURNING job_id",
    "UPDATE catalog_index_jobs SET state='indexed',worker_id=NULL,token=NULL,lease_until=NULL,projection_hash=%s,error_code=NULL,finished=%s,updated=%s WHERE job_id=%s AND resource_id=%s AND revision=%s AND corpus_hash=%s AND model_hash=%s AND state='claimed' AND worker_id=%s AND token=%s AND fence=%s AND lease_until=%s AND lease_until>%s RETURNING job_id")
_FAILED = Statement('catalog.index_fail',
    "UPDATE catalog_index_jobs SET state='failed',worker_id=NULL,token=NULL,lease_until=NULL,error_code=?,finished=?,updated=? WHERE job_id=? AND resource_id=? AND revision=? AND corpus_hash=? AND model_hash=? AND state='claimed' AND worker_id=? AND token=? AND fence=? AND lease_until=? AND lease_until>? RETURNING job_id",
    "UPDATE catalog_index_jobs SET state='failed',worker_id=NULL,token=NULL,lease_until=NULL,error_code=%s,finished=%s,updated=%s WHERE job_id=%s AND resource_id=%s AND revision=%s AND corpus_hash=%s AND model_hash=%s AND state='claimed' AND worker_id=%s AND token=%s AND fence=%s AND lease_until=%s AND lease_until>%s RETURNING job_id")
_SUPERSEDE_CLAIM = Statement('catalog.index_supersede_claim',
    "UPDATE catalog_index_jobs SET state='superseded',worker_id=NULL,token=NULL,lease_until=NULL,finished=COALESCE(finished,?),updated=? WHERE job_id=? AND resource_id=? AND revision=? AND corpus_hash=? AND model_hash=? AND state='claimed' AND worker_id=? AND token=? AND fence=? AND lease_until=? RETURNING job_id",
    "UPDATE catalog_index_jobs SET state='superseded',worker_id=NULL,token=NULL,lease_until=NULL,finished=COALESCE(finished,%s),updated=%s WHERE job_id=%s AND resource_id=%s AND revision=%s AND corpus_hash=%s AND model_hash=%s AND state='claimed' AND worker_id=%s AND token=%s AND fence=%s AND lease_until=%s RETURNING job_id")
_PUBLISH = Statement('catalog.index_publish_metadata',
    'INSERT INTO catalog_index_projections VALUES (?,?,?,?,?,?,?) ON CONFLICT(resource_id,model_hash) DO UPDATE SET revision=excluded.revision,corpus_hash=excluded.corpus_hash,projection_hash=excluded.projection_hash,job_id=excluded.job_id,indexed_at=excluded.indexed_at',
    'INSERT INTO catalog_index_projections VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(resource_id,model_hash) DO UPDATE SET revision=excluded.revision,corpus_hash=excluded.corpus_hash,projection_hash=excluded.projection_hash,job_id=excluded.job_id,indexed_at=excluded.indexed_at')
_PROJECTION = Statement('catalog.index_projection',
    "SELECT p.resource_id,p.revision,p.corpus_hash,p.model_hash,p.projection_hash,p.job_id,p.indexed_at FROM catalog_index_projections p JOIN catalog_index_heads h ON h.resource_id=p.resource_id AND h.model_hash=p.model_hash AND h.revision=p.revision AND h.corpus_hash=p.corpus_hash JOIN catalog_index_jobs j ON j.job_id=p.job_id AND j.state='indexed' AND j.resource_id=p.resource_id AND j.model_hash=p.model_hash AND j.revision=p.revision AND j.corpus_hash=p.corpus_hash AND j.projection_hash=p.projection_hash WHERE p.resource_id=? AND p.model_hash=?",
    "SELECT p.resource_id,p.revision,p.corpus_hash,p.model_hash,p.projection_hash,p.job_id,p.indexed_at FROM catalog_index_projections p JOIN catalog_index_heads h ON h.resource_id=p.resource_id AND h.model_hash=p.model_hash AND h.revision=p.revision AND h.corpus_hash=p.corpus_hash JOIN catalog_index_jobs j ON j.job_id=p.job_id AND j.state='indexed' AND j.resource_id=p.resource_id AND j.model_hash=p.model_hash AND j.revision=p.revision AND j.corpus_hash=p.corpus_hash AND j.projection_hash=p.projection_hash WHERE p.resource_id=%s AND p.model_hash=%s", readonly=True)


def _job(row):
    try:
        job = IndexJob(*row)
        _identity(job.job_id); _integer(job.resource_id); _integer(job.revision)
        _hash(job.corpus_hash); _hash(job.model_hash)
        if job.state not in STATES or type(job.fence) is not int or not 0 <= job.fence < 2**63:
            raise IndexOutboxError()
        _time(job.created); _time(job.updated)
        if job.error_code is not None and job.error_code not in ERROR_CODES: raise IndexOutboxError()
        if job.projection_hash is not None: _hash(job.projection_hash)
        return job
    except (ValueError, TypeError):
        raise IndexOutboxError('invalid_record') from None


def _claim_values(claim):
    if type(claim) is not IndexClaim: raise IndexOutboxError()
    _identity(claim.job_id); _integer(claim.resource_id); _integer(claim.revision)
    _hash(claim.corpus_hash); _hash(claim.model_hash); _worker(claim.worker_id)
    if type(claim.token) is not str or not re.fullmatch('[0-9a-f]{32}', claim.token): raise IndexOutboxError()
    _integer(claim.fence); _time(claim.lease_until)
    return (claim.job_id, claim.resource_id, claim.revision, claim.corpus_hash,
            claim.model_hash, claim.worker_id, claim.token, claim.fence, claim.lease_until)


def enqueue(session, *, resource_id, revision, corpus_hash, model_hash, now):
    """Enqueue in the writer's existing transaction; never commits independently."""
    if type(session) is not Session: raise IndexOutboxError()
    _integer(resource_id); _integer(revision); _hash(corpus_hash); _hash(model_hash); _time(now)
    identity = 'cij_' + hashlib.sha256(f'{resource_id}:{revision}:{corpus_hash}:{model_hash}'.encode('ascii')).hexdigest()
    session.execute(_ENSURE_HEAD, (resource_id, model_hash, revision, corpus_hash, now))
    head = session.execute(_LOCK_HEAD, (resource_id,)).rows[0]
    try: _integer(head['revision']); _hash(head['corpus_hash']); _hash(head['model_hash'])
    except IndexOutboxError: raise IndexOutboxError('invalid_record') from None
    if revision < head['revision']: raise IndexOutboxError('stale_revision')
    if revision == head['revision'] and (corpus_hash != head['corpus_hash'] or model_hash != head['model_hash']):
        raise IndexOutboxError('revision_conflict')
    if revision > head['revision']:
        session.execute(_ADVANCE_HEAD, (revision, corpus_hash, model_hash, now, resource_id))
        session.execute(_SUPERSEDE_OLD, (now, now, resource_id, revision))
    session.execute(_INSERT_JOB, (identity, resource_id, revision, corpus_hash, model_hash, now, now))
    job = _job(session.execute(_GET_JOB, (identity,)).rows[0])
    if (job.resource_id, job.revision, job.corpus_hash, job.model_hash) != (resource_id, revision, corpus_hash, model_hash):
        raise IndexOutboxError('invalid_record')
    return job


class CatalogIndexOutbox:
    """Caller-owned explicit adapter; metadata-only index state, no auto-init."""
    def __init__(self, adapter):
        if type(adapter) not in (SQLiteAdapter, PostgresAdapter): raise IndexOutboxError()
        self._adapter = adapter

    def claim(self, worker_id, *, now, lease_seconds=30):
        _worker(worker_id); _time(now)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 60: raise IndexOutboxError()
        lease_until = _time(now + lease_seconds)
        token = secrets.token_hex(16)
        with self._adapter.transaction() as session:
            rows = session.execute(_CLAIM, (worker_id, token, lease_until, now, now, now)).rows
            if not rows: return None
            claim = IndexClaim(*rows[0])
            try: _claim_values(claim)
            except IndexOutboxError: raise IndexOutboxError('invalid_record') from None
            return claim

    def _finish(self, claim, value, now, *, failed):
        _claim_values(claim); _time(now)
        if failed:
            if type(value) is not str or value not in ERROR_CODES: raise IndexOutboxError()
        else: _hash(value)
        with self._adapter.transaction() as session:
            return self._finish_in(session, claim, value, now, failed=failed)

    def _finish_in(self, session, claim, value, now, *, failed):
        if type(session) is not Session: raise IndexOutboxError()
        values = _claim_values(claim); _time(now)
        if failed:
            if type(value) is not str or value not in ERROR_CODES: raise IndexOutboxError()
        else: _hash(value)
        head = session.execute(_LOCK_EXPECTED_HEAD,
            (claim.resource_id, claim.model_hash, claim.revision, claim.corpus_hash)).rows
        if not head:
            changed = session.execute(_SUPERSEDE_CLAIM, (now, now) + values).rows
            if changed: return 'superseded'
            rows = session.execute(_GET_JOB, (claim.job_id,)).rows
            if rows:
                job = _job(rows[0])
                if job.state == 'superseded' and (job.resource_id, job.revision, job.corpus_hash, job.model_hash) == (claim.resource_id, claim.revision, claim.corpus_hash, claim.model_hash):
                    return 'superseded'
            return 'stale_claim'
        changed = session.execute(_FAILED if failed else _INDEXED, (value, now, now) + values + (now,)).rows
        if not changed: return 'stale_claim'
        if not failed:
            session.execute(_PUBLISH, (claim.resource_id, claim.model_hash, claim.revision,
                claim.corpus_hash, value, claim.job_id, now))
        return 'failed' if failed else 'indexed'

    def complete(self, claim, projection_hash, *, now):
        return self._finish(claim, projection_hash, now, failed=False)

    def fail(self, claim, error_code, *, now):
        return self._finish(claim, error_code, now, failed=True)

    def indexed_projection(self, resource_id, model_hash):
        _integer(resource_id); _hash(model_hash)
        with self._adapter.transaction(readonly=True) as session:
            rows = session.execute(_PROJECTION, (resource_id, model_hash)).rows
            if not rows: return None
            try:
                result = IndexProjection(*rows[0])
                _integer(result.resource_id); _integer(result.revision)
                _hash(result.corpus_hash); _hash(result.model_hash); _hash(result.projection_hash)
                _identity(result.job_id); _time(result.indexed_at)
                return result
            except (ValueError, TypeError):
                raise IndexOutboxError('invalid_record') from None

    def job(self, job_id):
        _identity(job_id)
        with self._adapter.transaction(readonly=True) as session:
            rows = session.execute(_GET_JOB, (job_id,)).rows
            return _job(rows[0]) if rows else None

"""Fenced legacy sqlite-vec publications, separate from observation purposes.

Caller-owned SQLite connections and locks only. Declared model identity is not
an independent weights attestation. No connection, path, extension, environment,
model service or public authority is opened here.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import html
import json
import math
import re
import secrets
import sqlite3
import struct
import threading
import time
import weakref
from urllib.parse import unquote

from .observation_guards import FIELDS as _BINDING_FIELDS
from .concierge.recommendation_security import public_data, secret_name

PROFILE = 'legacy-vector-publication-v1'
RECIPE = 'legacy-vector-public-text-v1'
DIMENSION = 768
MIN_NORM_SQUARED = 1e-30
MAX_NORM_SQUARED = 1e30
LEASE_SECONDS = 90
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 60
MAX_BATCH = 50
RETENTION_PAUSE = 60  # seconds between retention sweeps that found less than a full batch
RETENTION_BATCH = 200  # expired jobs one snapshot sweep removes
MAX_SOURCE_BYTES = 65536
MAX_VALUE_BYTES = 16384
ERRORS = ('invalid_model', 'invalid_source', 'invalid_vector', 'invalid_claim',
          'invalid_request', 'invalid_schema', 'caller_transaction', 'database_error',
          'commit_unknown', 'broken', 'model_mismatch')
FAILURES = ('embedding_failed', 'invalid_response', 'invalid_vector')
_RAW = ('id', 'key', 'kind', 'url', 'content_hash', 'name', 'description',
        'category', 'active', 'usage_tools_hash', 'usage_full_hash')
_URL = re.compile(r'(?i)\b(?:https?|wss?)://[^\s<>"\x27]+')
_EMAIL = re.compile(r'(?i)[A-Z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}')
_QUOTED_ASSIGNMENT = re.compile(
    r'''(?P<prefix>["'](?P<name>[A-Za-z][A-Za-z _-]{0,47})["']\s*:\s*)'''
    r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,}\]]+)''')
_LOCAL_PATH = re.compile(
    r'''(?i)(?:\bfile://[^\s<>"']+|\b[A-Z]:[\\/][^\s<>"']+|'''
    r'''(?<![\w:])/(?:Users|home|private|var|tmp|etc|opt|root|workspace)/[^\s<>"']+)''')
_REGISTRY = weakref.WeakValueDictionary()
_REGISTRY_LOCK = threading.Lock()


class VectorError(ValueError):
    def __init__(self, code='database_error'):
        self.code = code if code in ERRORS else 'database_error'
        super().__init__(self.code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('ascii')).hexdigest()


def _id(value):
    return type(value) is int and 1 <= value < 2**63


def _time(value):
    return type(value) in (int, float) and 0 <= value < 2**53 and math.isfinite(value)


def _now():
    return time.time()


def _hash(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


@dataclass(frozen=True, repr=False)
class ModelDescriptor:
    model_id: str
    revision: str = 'declared-tag-v1'
    dimension: int = DIMENSION
    float_format: str = 'float32-le'
    metric: str = 'cosine'
    recipe_id: str = RECIPE
    weights_digest: str | None = None

    def __post_init__(self):
        for value in (self.model_id, self.revision):
            if type(value) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}', value):
                raise VectorError('invalid_model')
        if (type(self.dimension) is not int or self.dimension != DIMENSION
                or self.float_format != 'float32-le' or self.metric != 'cosine'
                or self.recipe_id != RECIPE or self.weights_digest is not None and not _hash(self.weights_digest)):
            raise VectorError('invalid_model')

    @property
    def digest(self):
        self.__post_init__()
        return _digest([PROFILE, self.model_id, self.revision, self.dimension,
                        self.float_format, self.metric, self.recipe_id, self.weights_digest])

    def __repr__(self):
        return '<VectorModel declared-private>'


@dataclass(frozen=True, repr=False)
class Source:
    resource_id: int
    source_hash: str
    corpus_hash: str
    text: str

    def __repr__(self):
        return '<VectorSource private>'


def source(row):
    if (type(row) is not dict or len(row) > 128 or not _id(row.get('id'))
            or any(key not in row for key in ('name', 'description', 'category', 'active', 'kind', 'url'))
            or type(row['active']) is not int or row['active'] not in (0, 1)):
        raise VectorError('invalid_source')
    raw, total = [], 0
    for field in _RAW:
        value = row.get(field)
        if value is None:
            encoded = b''
        elif type(value) is str:
            if len(value) > MAX_VALUE_BYTES or '\0' in value:
                raise VectorError('invalid_source')
            try:
                encoded = value.encode('utf-8')
            except UnicodeError:
                raise VectorError('invalid_source') from None
        elif type(value) is int and -(2**63) <= value < 2**63:
            encoded = str(value).encode('ascii')
        else:
            raise VectorError('invalid_source')
        if len(encoded) > MAX_VALUE_BYTES:
            raise VectorError('invalid_source')
        total += len(encoded)
        if total > MAX_SOURCE_BYTES:
            raise VectorError('invalid_source')
        raw.append([field, field in row, value])
    texts = []
    for field, maximum in (('name', 200), ('category', 200), ('description', 500)):
        text = row[field]
        if text is None:
            text = ''
        if type(text) is not str:
            raise VectorError('invalid_source')
        for _ in range(3):
            text = html.unescape(unquote(text)).replace('\\/', '/')
        # Preserve public prose, but omit known quoted credentials as well as
        # assignment forms. This is not an arbitrary secret detector.
        text = _QUOTED_ASSIGNMENT.sub(
            lambda match: match['prefix'] + '[REDACTED]' if secret_name(match['name']) else match[0], text)
        text = public_data(text)
        text = _EMAIL.sub(' ', _URL.sub(' ', text))
        text = _LOCAL_PATH.sub(' ', text)
        text = re.sub(r'<[^>]{0,4096}>', ' ', text)
        text = ' '.join(text.replace('[REDACTED]', ' ').split())[:maximum]
        texts.append(text)
    text = f'{texts[0]} [{texts[1]}]: {texts[2]}'
    return Source(row['id'], _digest([PROFILE, 'raw-source-v1', raw]),
                  _digest([RECIPE, text]), text)


def validate_vector(values, descriptor):
    """Validate the actual float32 payload, including a safe cosine norm range.

    The supported native profile rejects squared norms outside 1e-30..1e30.
    Values are never rescaled to conceal native underflow or overflow.
    """
    if type(descriptor) is not ModelDescriptor:
        raise VectorError('invalid_model')
    descriptor.__post_init__()
    if type(values) not in (list, tuple) or len(values) != descriptor.dimension:
        raise VectorError('invalid_vector')
    try:
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
            raise VectorError('invalid_vector')
        blob = struct.pack('<' + 'f' * descriptor.dimension, *values)
        actual = struct.unpack('<' + 'f' * descriptor.dimension, blob)
    except (OverflowError, ValueError, struct.error):
        raise VectorError('invalid_vector') from None
    norm = math.fsum(value * value for value in actual)
    if (not all(math.isfinite(value) for value in actual)
            or not MIN_NORM_SQUARED <= norm <= MAX_NORM_SQUARED):
        raise VectorError('invalid_vector')
    return blob, hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True, repr=False)
class Claim:
    job_id: str
    resource_id: int
    generation: int
    source_hash: str
    corpus_hash: str
    descriptor_hash: str
    token: str
    fence: int
    lease_until: float
    text: str

    def __post_init__(self):
        if (type(self.job_id) is not str or not re.fullmatch('lvj_[0-9a-f]{32}', self.job_id)
                or not _id(self.resource_id) or not _id(self.generation) or not _id(self.fence)
                or any(not _hash(value) for value in (self.source_hash, self.corpus_hash, self.descriptor_hash))
                or type(self.token) is not str or not re.fullmatch('[0-9a-f]{48}', self.token)
                or not _time(self.lease_until) or type(self.text) is not str or len(self.text) > 2048):
            raise VectorError('invalid_claim')

    def __repr__(self):
        return '<VectorClaim private>'


_DDL = (
    'CREATE TABLE IF NOT EXISTS vec_outbox(resource_id INTEGER PRIMARY KEY,enqueued_at REAL NOT NULL,reason TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS legacy_vector_generations(resource_id INTEGER PRIMARY KEY,generation INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS legacy_vector_heads(resource_id INTEGER PRIMARY KEY,job_id TEXT NOT NULL)',
    '''CREATE TABLE IF NOT EXISTS legacy_vector_jobs(job_id TEXT PRIMARY KEY,resource_id INTEGER NOT NULL,
       generation INTEGER NOT NULL,status TEXT NOT NULL,source_hash TEXT,corpus_hash TEXT,descriptor_hash TEXT,
       token TEXT,fence INTEGER NOT NULL DEFAULT 0,lease_until REAL,attempts INTEGER NOT NULL DEFAULT 0,
       not_before REAL NOT NULL DEFAULT 0,created REAL NOT NULL,finished REAL,error_code TEXT)''',
    'CREATE INDEX IF NOT EXISTS legacy_vector_jobs_created ON legacy_vector_jobs(created,job_id)',
    'CREATE INDEX IF NOT EXISTS legacy_vector_jobs_resource_status ON legacy_vector_jobs(resource_id,status)',
    'CREATE INDEX IF NOT EXISTS legacy_vector_heads_job ON legacy_vector_heads(job_id,resource_id)',
    '''CREATE TABLE IF NOT EXISTS legacy_vector_provenance(resource_id INTEGER PRIMARY KEY,job_id TEXT NOT NULL,
       generation INTEGER NOT NULL,source_hash TEXT NOT NULL,corpus_hash TEXT NOT NULL,
       descriptor_hash TEXT NOT NULL,vector_hash TEXT NOT NULL,indexed_at REAL NOT NULL)''',
    'CREATE TABLE IF NOT EXISTS legacy_vector_control(id INTEGER PRIMARY KEY,profile TEXT NOT NULL,descriptor_hash TEXT,descriptor_json TEXT)',
)
_ELIGIBLE = "active=1 AND COALESCE(health_status,'unknown')!='retired' AND COALESCE(eval_security,'')!='quarantine'"
# Listings without a current vector or an unfinished job. Shared with the
# PostgreSQL read-snapshot backfill scan, so both use one cataloged statement.
_BACKFILL_SELECTION = ''' AND NOT EXISTS(
                SELECT 1 FROM legacy_vector_heads h JOIN legacy_vector_jobs j USING(job_id)
                WHERE h.resource_id=resources.id AND j.status IN ('pending','claimed','failed'))
                AND NOT EXISTS(SELECT 1 FROM legacy_vector_provenance p
                    JOIN legacy_vector_heads h USING(resource_id) JOIN legacy_vector_generations g USING(resource_id)
                    WHERE p.resource_id=resources.id AND p.job_id=h.job_id AND p.generation=g.generation
                    AND p.descriptor_hash=?)'''


def _rows(db, sql, params=()):
    cursor = db.execute(sql, params)
    columns = tuple(item[0] for item in cursor.description) if cursor.description else ()
    return tuple(dict(zip(columns, row)) for row in cursor.fetchall())


def _enqueue_body(rid):
    # rid is a fixed NEW/OLD trigger expression or a literal bootstrap column.
    return f'''
      INSERT OR IGNORE INTO legacy_vector_generations VALUES({rid},1);
      UPDATE legacy_vector_generations SET generation=generation+1 WHERE resource_id={rid};
      UPDATE legacy_vector_jobs SET status='superseded',finished=CAST(strftime('%s','now') AS REAL)
        WHERE resource_id={rid} AND status IN ('pending','claimed');
      INSERT INTO legacy_vector_heads VALUES({rid},'lvj_'||lower(hex(randomblob(16))))
        ON CONFLICT(resource_id) DO UPDATE SET job_id=excluded.job_id;
      INSERT INTO legacy_vector_jobs(job_id,resource_id,generation,status,created)
        SELECT h.job_id,{rid},g.generation,'pending',CAST(strftime('%s','now') AS REAL)
        FROM legacy_vector_heads h JOIN legacy_vector_generations g USING(resource_id) WHERE h.resource_id={rid};
    '''


def install(db):
    """Participate in the caller's setup transaction; never commit its writes."""
    if not isinstance(db, sqlite3.Connection):
        raise VectorError('invalid_request')
    try:
        tables = _rows(db, "SELECT name,type,sql FROM main.sqlite_schema WHERE name IN ('resources','vec_resources')")
        by_name = {row['name']: row for row in tables}
        vector_sql = by_name.get('vec_resources', {}).get('sql') or ''
        if (set(by_name) != {'resources', 'vec_resources'} or by_name['resources']['type'] != 'table'
                or not re.search(r'\bUSING\s+vec0\s*\(', vector_sql, re.I)
                or not re.search(r'\bembedding\s+float\s*\[\s*768\s*\]\s+distance_metric\s*=\s*cosine\b', vector_sql, re.I)
                or _rows(db, "SELECT name FROM temp.sqlite_schema WHERE name IN ('resources','vec_resources','vec_outbox')")):
            raise VectorError('invalid_schema')
        columns = {row['name'] for row in _rows(db, "SELECT name FROM pragma_table_info('resources','main')")}
        if not {'id', 'name', 'description', 'category', 'active', 'kind', 'url', 'health_status', 'eval_security'} <= columns:
            raise VectorError('invalid_schema')
        for sql in _DDL:
            db.execute(sql)
        db.execute('INSERT OR IGNORE INTO legacy_vector_control VALUES(1,?,NULL,NULL)', (PROFILE,))
        db.execute('INSERT OR IGNORE INTO legacy_vector_generations SELECT id,1 FROM resources')
        fields = tuple(name for name in dict.fromkeys(_BINDING_FIELDS + ('health_status', 'eval_security')) if name in columns)
        changed = ' OR '.join('OLD.' + field + ' IS NOT NEW.' + field for field in fields)
        eligible = "NEW.active=1 AND COALESCE(NEW.health_status,'unknown')!='retired' AND COALESCE(NEW.eval_security,'')!='quarantine'"
        invalidation = '''
          UPDATE legacy_vector_generations SET generation=generation+1 WHERE resource_id=NEW.id;
          DELETE FROM legacy_vector_provenance WHERE resource_id=NEW.id;
          DELETE FROM vec_resources WHERE rowid=NEW.id;
          UPDATE legacy_vector_jobs SET status='superseded',finished=CAST(strftime('%s','now') AS REAL)
            WHERE resource_id=NEW.id AND status IN ('pending','claimed');
          DELETE FROM vec_outbox WHERE resource_id=NEW.id;
        '''
        triggers = (
            f'''CREATE TRIGGER IF NOT EXISTS legacy_vector_resource_insert AFTER INSERT ON resources BEGIN
                INSERT INTO legacy_vector_generations VALUES(NEW.id,1) ON CONFLICT(resource_id) DO UPDATE SET generation=generation+1;
                INSERT OR REPLACE INTO vec_outbox SELECT NEW.id,CAST(strftime('%s','now') AS REAL),'new' WHERE {eligible}; END''',
            f'''CREATE TRIGGER IF NOT EXISTS legacy_vector_resource_update AFTER UPDATE OF {','.join(fields)} ON resources WHEN {changed} BEGIN
                {invalidation}
                INSERT OR REPLACE INTO vec_outbox SELECT NEW.id,CAST(strftime('%s','now') AS REAL),'source' WHERE {eligible}; END''',
            '''CREATE TRIGGER IF NOT EXISTS legacy_vector_resource_delete AFTER DELETE ON resources BEGIN
                UPDATE legacy_vector_generations SET generation=generation+1 WHERE resource_id=OLD.id;
                DELETE FROM legacy_vector_provenance WHERE resource_id=OLD.id;
                DELETE FROM vec_resources WHERE rowid=OLD.id;
                DELETE FROM vec_outbox WHERE resource_id=OLD.id;
                DELETE FROM legacy_vector_heads WHERE resource_id=OLD.id;
                UPDATE legacy_vector_jobs SET status='superseded',finished=CAST(strftime('%s','now') AS REAL)
                  WHERE resource_id=OLD.id AND status IN ('pending','claimed'); END''',
            'CREATE TRIGGER IF NOT EXISTS legacy_vector_outbox_insert AFTER INSERT ON vec_outbox BEGIN ' + _enqueue_body('NEW.resource_id') + ' END',
            'CREATE TRIGGER IF NOT EXISTS legacy_vector_outbox_update AFTER UPDATE ON vec_outbox BEGIN ' + _enqueue_body('NEW.resource_id') + ' END',
        )
        for sql in triggers:
            db.execute(sql)
        # Adopt only queue intent, never old vectors as verified provenance.
        missing = _rows(db, '''SELECT o.resource_id FROM vec_outbox o LEFT JOIN legacy_vector_heads h USING(resource_id)
                              WHERE h.resource_id IS NULL ORDER BY o.resource_id LIMIT 500''')
        for row in missing:
            db.execute('UPDATE vec_outbox SET reason=reason WHERE resource_id=?', (row['resource_id'],))
    except VectorError:
        raise
    except Exception:
        raise VectorError('invalid_schema') from None


def lookup(db):
    with _REGISTRY_LOCK:
        value = _REGISTRY.get(id(db))
        return value if value is not None and value.db is db else None


def register(db, lock):
    with _REGISTRY_LOCK:
        value = _REGISTRY.get(id(db))
        if value is not None and value.db is db:
            if value.lock is not lock:
                raise VectorError('invalid_request')
            return value
        value = VectorIndex(db, lock)
        _REGISTRY[id(db)] = value
        return value


class VectorIndex:
    _retention_after = 0.0  # next retention sweep (claim_batch); per long-lived writer index

    def __init__(self, db, lock):
        if not isinstance(db, sqlite3.Connection) or not hasattr(lock, '__enter__') or db.in_transaction:
            raise VectorError('caller_transaction')
        self.db, self.lock, self.broken, self._reading = db, lock, False, False

    @contextmanager
    def _tx(self):
        with self.lock:
            if self.broken:
                raise VectorError('broken')
            if self.db.in_transaction:
                raise VectorError('caller_transaction')
            try:
                self.db.execute('BEGIN IMMEDIATE')
                yield
                try:
                    self.db.commit()
                except BaseException:
                    self.broken = True
                    raise VectorError('commit_unknown') from None
            except BaseException as exc:
                try:
                    self.db.rollback()
                except BaseException:
                    self.broken = True
                if isinstance(exc, (VectorError, KeyboardInterrupt, SystemExit)):
                    raise
                raise VectorError('database_error') from None

    @contextmanager
    def read_snapshot(self):
        with self.lock:
            if self.broken:
                raise VectorError('broken')
            if self.db.in_transaction:
                raise VectorError('caller_transaction')
            before = self.db.execute('PRAGMA query_only').fetchone()[0]
            try:
                self.db.execute('PRAGMA query_only=ON')
                self.db.execute('BEGIN')
                self._reading = True
                yield self.db
            except VectorError:
                raise
            except Exception:
                raise VectorError('database_error') from None
            finally:
                self._reading = False
                try:
                    self.db.rollback()
                    self.db.execute('PRAGMA query_only=' + str(int(before)))
                except BaseException as exc:
                    self.broken = True
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    raise VectorError('database_error') from None

    def _pin(self, descriptor, *, bind=True):
        if type(descriptor) is not ModelDescriptor:
            raise VectorError('invalid_model')
        value = descriptor.digest
        rows = _rows(self.db, 'SELECT * FROM legacy_vector_control ORDER BY id LIMIT 2')
        if len(rows) != 1 or rows[0]['id'] != 1 or rows[0]['profile'] != PROFILE:
            raise VectorError('invalid_schema')
        if rows[0]['descriptor_hash'] is None and bind:
            self.db.execute('UPDATE legacy_vector_control SET descriptor_hash=?,descriptor_json=? WHERE id=1',
                            (value, _canonical(vars(descriptor))))
        elif rows[0]['descriptor_hash'] is not None and rows[0]['descriptor_hash'] != value:
            raise VectorError('model_mismatch')
        return value

    def _request(self, limit, resource_ids, expected_resources):
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
            raise VectorError('invalid_request')
        ids = None
        if resource_ids is not None:
            if (type(resource_ids) not in (tuple, list) or not 1 <= len(resource_ids) <= MAX_BATCH
                    or any(not _id(value) for value in resource_ids) or len(set(resource_ids)) != len(resource_ids)):
                raise VectorError('invalid_request')
            ids = tuple(resource_ids)
        expected = {}
        if expected_resources is not None:
            if type(expected_resources) not in (tuple, list) or not 1 <= len(expected_resources) <= MAX_BATCH:
                raise VectorError('invalid_request')
            for row in expected_resources:
                if (type(row) is not dict or not _id(row.get('id')) or row['id'] in expected
                        or not {'id', 'name', 'description', 'category'} <= row.keys() or len(row) > 128):
                    raise VectorError('invalid_request')
                expected[row['id']] = row
            if ids is None:
                ids = tuple(expected)
            elif set(ids) != set(expected):
                raise VectorError('invalid_request')
        return ids, expected

    def _resource(self, rid, expected=None):
        rows = _rows(self.db, 'SELECT * FROM resources WHERE id=?', (rid,))
        if not rows:
            return None
        row = rows[0]
        if (row.get('active') != 1 or row.get('health_status') == 'retired' or row.get('eval_security') == 'quarantine'):
            return None
        if expected is not None and any(row.get(key) != value for key, value in expected.items() if key in _RAW):
            return None
        return row

    def _current(self, rid, descriptor):
        control = _rows(self.db, 'SELECT * FROM legacy_vector_control ORDER BY id LIMIT 2')
        if not (len(control) == 1 and control[0]['id'] == 1 and control[0]['profile'] == PROFILE
                and control[0]['descriptor_hash'] == descriptor.digest):
            return False
        resource = self._resource(rid)
        if resource is None:
            return False
        state = _rows(self.db, '''SELECT p.*,g.generation AS current_generation,h.job_id AS current_job,j.status
            FROM legacy_vector_provenance p JOIN legacy_vector_generations g USING(resource_id)
            JOIN legacy_vector_heads h USING(resource_id) JOIN legacy_vector_jobs j ON j.job_id=p.job_id
            WHERE p.resource_id=?''', (rid,))
        if not state:
            return False
        p = state[0]
        try:
            data = source(resource)
        except VectorError:
            return False
        if not (p['generation'] == p['current_generation'] and p['job_id'] == p['current_job']
                and p['status'] == 'indexed' and p['source_hash'] == data.source_hash
                and p['corpus_hash'] == data.corpus_hash and p['descriptor_hash'] == descriptor.digest):
            return False
        blob = _rows(self.db, 'SELECT embedding FROM vec_resources WHERE rowid=?', (rid,))
        return bool(blob and type(blob[0]['embedding']) is bytes and hashlib.sha256(blob[0]['embedding']).hexdigest() == p['vector_hash'])

    def ensure_jobs(self, descriptor, limit=1, resource_ids=None, expected_resources=None):
        ids, expected = self._request(limit, resource_ids, expected_resources)
        with self._tx():
            self._pin(descriptor, bind=False)
            self._bootstrap(limit)
            where = '' if ids is None else ' AND id IN (' + ','.join('?' for _ in ids) + ')'
            selection = '' if ids is not None else _BACKFILL_SELECTION
            parameters = ids if ids is not None else (descriptor.digest,)
            rows = _rows(self.db, 'SELECT id FROM resources WHERE ' + _ELIGIBLE + where + selection + ' ORDER BY id LIMIT ?',
                         parameters + (limit,))
            count = 0
            for row in rows:
                rid = row['id']
                if self._resource(rid, expected.get(rid)) is None or self._current(rid, descriptor):
                    continue
                jobs = _rows(self.db, '''SELECT j.status,j.attempts FROM legacy_vector_heads h JOIN legacy_vector_jobs j USING(job_id)
                    WHERE h.resource_id=?''', (rid,))
                if jobs and jobs[0]['status'] in ('pending', 'claimed', 'failed'):
                    continue
                self.db.execute("INSERT OR REPLACE INTO vec_outbox VALUES(?,?,'backfill')", (rid, _now()))
                count += 1
            return count

    def _bootstrap(self, limit):
        rows = _rows(self.db, '''SELECT o.resource_id FROM vec_outbox o LEFT JOIN legacy_vector_heads h USING(resource_id)
            WHERE h.resource_id IS NULL ORDER BY o.resource_id LIMIT ?''', (limit,))
        for row in rows:
            self.db.execute('UPDATE vec_outbox SET reason=reason WHERE resource_id=?', (row['resource_id'],))

    def _expired_jobs(self, cutoff):
        """Expired job ids found outside the writer transaction, or None to sweep inside it."""
        return None

    def _delete_expired(self, job_ids, cutoff):
        raise NotImplementedError

    def claim_batch(self, descriptor, limit=1, resource_ids=None, expected_resources=None):
        ids, expected = self._request(limit, resource_ids, expected_resources)
        start = _now()
        # Decided once, before the transaction: deciding again inside it let a pause that
        # ended in between run the full sweep under the writer lock (2026-11-01 21:15, 1.07 s).
        due = bool(_time(start) and start >= self._retention_after)
        expired = self._expired_jobs(start - 7 * 86400) if due else None
        with self._tx():
            value = self._pin(descriptor)
            self._bootstrap(limit)
            now = _now()
            if not _time(now):
                raise VectorError('invalid_request')
            self.db.execute('''UPDATE legacy_vector_jobs SET status='failed',error_code='lease_exhausted',finished=?
                WHERE job_id IN (SELECT j.job_id FROM legacy_vector_jobs j JOIN legacy_vector_heads h USING(job_id)
                WHERE j.status='claimed' AND j.attempts>=3 AND j.lease_until<=? ORDER BY j.job_id LIMIT 50)''', (now, now))
            # The sweep scans every week-old head and provenance job even when nothing is
            # deletable (79 ms on 2M jobs, twice a second). Keep sweeping while batches come
            # back full; after a short one, look again only after RETENTION_PAUSE.
            if due and expired is not None:
                # Found by a read snapshot; the delete re-checks each id under the writer lock.
                deleted = self._delete_expired(expired, start - 7 * 86400) if expired else 0
                self._retention_after = 0.0 if len(expired) >= RETENTION_BATCH else now + RETENTION_PAUSE
            elif due:
                deleted = self.db.execute('''DELETE FROM legacy_vector_jobs WHERE job_id IN (
                SELECT j.job_id FROM legacy_vector_jobs j
                LEFT JOIN legacy_vector_heads h ON h.job_id=j.job_id
                LEFT JOIN legacy_vector_provenance p ON p.job_id=j.job_id
                WHERE j.status IN ('indexed','failed','superseded') AND j.finished<?
                AND h.job_id IS NULL AND p.job_id IS NULL ORDER BY j.finished,j.job_id LIMIT 500)''', (now - 7 * 86400,)).rowcount
                self._retention_after = 0.0 if deleted >= 500 else now + RETENTION_PAUSE
            clause = '' if ids is None else ' AND j.resource_id IN (' + ','.join('?' for _ in ids) + ')'
            parameters = () if ids is None else ids
            # Imported queue intent can outlive its resource or generation.
            # Retire a bounded set, and exclude all such heads before LIMIT so
            # one obsolete entry cannot hide eligible work behind it.
            self.db.execute('''UPDATE legacy_vector_jobs SET status='superseded',finished=?,lease_until=NULL
                WHERE job_id IN (SELECT j.job_id FROM (SELECT j.* FROM legacy_vector_jobs j
                JOIN legacy_vector_heads h USING(job_id)
                WHERE (j.status='pending' OR (j.status='claimed' AND j.lease_until<=?))'''
                + clause + ' ORDER BY j.created,j.job_id LIMIT ?) j '
                + '''
                LEFT JOIN resources r ON r.id=j.resource_id
                LEFT JOIN legacy_vector_generations g ON g.resource_id=j.resource_id
                WHERE r.id IS NULL OR COALESCE(r.active,0)!=1 OR r.health_status='retired'
                    OR r.eval_security='quarantine' OR g.generation IS NULL OR g.generation!=j.generation)''',
                (now, now) + parameters + (MAX_BATCH,))
            jobs = _rows(self.db, '''SELECT j.* FROM legacy_vector_jobs j JOIN legacy_vector_heads h USING(job_id)
                JOIN resources r ON r.id=j.resource_id
                JOIN legacy_vector_generations g ON g.resource_id=j.resource_id AND g.generation=j.generation
                WHERE r.active=1 AND COALESCE(r.health_status,'unknown')!='retired'
                AND COALESCE(r.eval_security,'')!='quarantine'
                AND j.attempts<3 AND j.not_before<=? AND (j.status='pending' OR (j.status='claimed' AND j.lease_until<=?))'''
                + clause + ' ORDER BY j.created,j.job_id LIMIT ?',
                (now, now) + parameters + (MAX_BATCH,))
            result = []
            for job in jobs:
                row = self._resource(job['resource_id'], expected.get(job['resource_id']))
                if row is None:
                    continue
                try:
                    data = source(row)
                except VectorError:
                    self.db.execute("UPDATE legacy_vector_jobs SET status='failed',error_code='invalid_source',finished=? WHERE job_id=?",
                                    (now, job['job_id']))
                    continue
                generation = _rows(self.db, 'SELECT generation FROM legacy_vector_generations WHERE resource_id=?', (data.resource_id,))[0]['generation']
                if generation != job['generation']:
                    continue
                if job['source_hash'] is not None and (job['source_hash'], job['corpus_hash'], job['descriptor_hash']) != (data.source_hash, data.corpus_hash, value):
                    self.db.execute("UPDATE legacy_vector_jobs SET status='superseded',finished=?,lease_until=NULL WHERE job_id=?",
                                    (now, job['job_id']))
                    continue
                token = secrets.token_hex(24)
                fence = job['fence'] + 1
                lease = now + LEASE_SECONDS
                self.db.execute('''UPDATE legacy_vector_jobs SET status='claimed',source_hash=?,corpus_hash=?,descriptor_hash=?,
                    token=?,fence=?,lease_until=?,attempts=attempts+1,error_code=NULL WHERE job_id=?''',
                    (data.source_hash, data.corpus_hash, value, token, fence, lease, job['job_id']))
                result.append(Claim(job['job_id'], data.resource_id, generation, data.source_hash,
                                    data.corpus_hash, value, token, fence, lease, data.text))
                if len(result) >= limit:
                    break
            return tuple(result)

    def _owned(self, claim, descriptor):
        if (type(claim) is not Claim or type(claim.job_id) is not str or not re.fullmatch('lvj_[0-9a-f]{32}', claim.job_id)
                or type(descriptor) is not ModelDescriptor or claim.descriptor_hash != descriptor.digest):
            return False
        try:
            claim.__post_init__()
        except VectorError:
            return False
        control = _rows(self.db, 'SELECT * FROM legacy_vector_control ORDER BY id LIMIT 2')
        if not (len(control) == 1 and control[0]['id'] == 1 and control[0]['profile'] == PROFILE
                and control[0]['descriptor_hash'] == descriptor.digest):
            return False
        jobs = _rows(self.db, '''SELECT j.*,h.job_id AS current_job,g.generation AS current_generation
            FROM legacy_vector_jobs j JOIN legacy_vector_heads h USING(resource_id)
            JOIN legacy_vector_generations g USING(resource_id) WHERE j.job_id=?''', (claim.job_id,))
        if not jobs:
            return False
        job = jobs[0]
        now = _now()
        if not (_time(now) and job['status'] == 'claimed' and job['current_job'] == claim.job_id
                and job['generation'] == job['current_generation'] == claim.generation
                and job['token'] == claim.token and job['fence'] == claim.fence
                and job['lease_until'] == claim.lease_until and now < claim.lease_until
                and (job['source_hash'], job['corpus_hash'], job['descriptor_hash']) ==
                (claim.source_hash, claim.corpus_hash, claim.descriptor_hash)):
            return False
        row = self._resource(claim.resource_id)
        if row is None:
            return False
        try:
            data = source(row)
        except VectorError:
            return False
        return data.source_hash == claim.source_hash and data.corpus_hash == claim.corpus_hash and data.text == claim.text

    def publish(self, claim, vector, descriptor):
        blob, vector_hash = validate_vector(vector, descriptor)
        with self._tx():
            if not self._owned(claim, descriptor):
                return 'stale'
            now = _now()
            self.db.execute('DELETE FROM vec_resources WHERE rowid=?', (claim.resource_id,))
            self.db.execute('INSERT INTO vec_resources(rowid,embedding) VALUES(?,?)', (claim.resource_id, blob))
            self.db.execute('''INSERT INTO legacy_vector_provenance VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(resource_id) DO UPDATE SET job_id=excluded.job_id,generation=excluded.generation,
                source_hash=excluded.source_hash,corpus_hash=excluded.corpus_hash,descriptor_hash=excluded.descriptor_hash,
                vector_hash=excluded.vector_hash,indexed_at=excluded.indexed_at''',
                (claim.resource_id, claim.job_id, claim.generation, claim.source_hash, claim.corpus_hash, claim.descriptor_hash, vector_hash, now))
            self.db.execute("UPDATE legacy_vector_jobs SET status='indexed',finished=?,lease_until=NULL WHERE job_id=? AND token=? AND fence=?",
                            (now, claim.job_id, claim.token, claim.fence))
            self.db.execute('DELETE FROM vec_outbox WHERE resource_id=? AND EXISTS(SELECT 1 FROM legacy_vector_heads WHERE resource_id=? AND job_id=?)',
                            (claim.resource_id, claim.resource_id, claim.job_id))
            self._after_publish(claim, blob, descriptor, vector_hash)
            return 'indexed'

    def _after_publish(self, claim, blob, descriptor, vector_hash):
        pass

    def fail(self, claim, descriptor, code='embedding_failed'):
        if code not in FAILURES:
            raise VectorError('invalid_request')
        with self._tx():
            if not self._owned(claim, descriptor):
                return 'stale'
            now = _now()
            job = _rows(self.db, 'SELECT attempts FROM legacy_vector_jobs WHERE job_id=?', (claim.job_id,))[0]
            status = 'failed' if job['attempts'] >= MAX_ATTEMPTS else 'pending'
            self.db.execute('UPDATE legacy_vector_jobs SET status=?,not_before=?,lease_until=NULL,error_code=?,finished=? WHERE job_id=?',
                            (status, now + BACKOFF_SECONDS, code, now if status == 'failed' else None, claim.job_id))
            return 'failed'

    def current_ids(self, ids, descriptor):
        if (type(ids) not in (list, tuple, set) or len(ids) > 100 or any(not _id(rid) for rid in ids)
                or type(descriptor) is not ModelDescriptor):
            raise VectorError('invalid_request')
        with self.lock:
            if self._reading:
                return {rid for rid in ids if self._current(rid, descriptor)}
            with self.read_snapshot():
                return {rid for rid in ids if self._current(rid, descriptor)}

    def inspect(self, job_id, descriptor):
        if type(job_id) is not str or not re.fullmatch('lvj_[0-9a-f]{32}', job_id):
            raise VectorError('invalid_request')
        with self.read_snapshot():
            rows = _rows(self.db, 'SELECT status,resource_id FROM legacy_vector_jobs WHERE job_id=?', (job_id,))
            return {'profile': PROFILE, 'found': bool(rows), 'status': rows[0]['status'] if rows else 'missing',
                    'current': bool(rows and self._current(rows[0]['resource_id'], descriptor)), 'replay_performed': False}

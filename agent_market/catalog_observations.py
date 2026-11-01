"""Private typed observation ownership; no legacy writer or server integration.

Registry data, authority and immutable connection/evidence history stay outside
this boundary. Caller owns the adapter, write control and observation provenance.
Owner clocks are explicit, not trustworthy wall-clock or execution attestation.
"""
from dataclasses import dataclass
import json
import math
import re

from .storage_adapter import SQLiteAdapter, PostgresAdapter, Statement, Row
from .catalog_repository import COLUMNS, _record
from .catalog_writer import (
    PROFILE as REGISTRY_PROFILE, CORPUS_PROFILE, _EXTRA, _LOCK, _INVALIDATE,
    _object, _canonical, _digest, _time, _integer, _hash, WriterError,
)
from .catalog_index_outbox import enqueue

PROFILE = 'owned-catalog-observations-v1'
OWNERS = ('health', 'survey', 'evaluation')
ERRORS = ('invalid_command', 'invalid_record', 'write_disabled', 'unversioned_resource',
          'stale_observation', 'operation_conflict', 'revision_conflict')


class ObservationError(ValueError):
    def __init__(self, code='invalid_command'):
        self.code = code if code in ERRORS else 'invalid_command'
        super().__init__(self.code)


def _op(value):
    if type(value) is not str or not re.fullmatch('ob_[0-9a-f]{32}', value):
        raise ObservationError()


def _id(value):
    if type(value) is not int or not 1 <= value < 2**63:
        raise ObservationError()


def _json(text, kind):
    if type(text) is not str or len(text) > 12288:
        raise ObservationError()
    wrapped = json.loads(_object('{"value":' + text + '}'))
    if set(wrapped) != {'value'} or type(wrapped['value']) is not kind:
        raise ObservationError()
    return wrapped['value']


def _tools(value):
    if len(value) > 100:
        raise ObservationError()
    names = set()
    for item in value:
        if (type(item) is not dict or type(item.get('name')) is not str
                or not 1 <= len(item['name']) <= 100 or item['name'] in names):
            raise ObservationError()
        names.add(item['name'])
    return sorted(value, key=lambda item: item['name'])


@dataclass(frozen=True, repr=False)
class HealthObservation:
    outcome: str
    next_check_at: float | None = None
    def __post_init__(self): _normalized(self)
    def __repr__(self): return '<HealthObservation private>'


@dataclass(frozen=True, repr=False)
class SurveyObservation:
    tools_json: str = '[]'
    guide_json: str = '{}'
    full_tools_json: str | None = None
    error_code: str | None = None
    def __post_init__(self): _normalized(self)
    def __repr__(self): return '<SurveyObservation private>'


@dataclass(frozen=True, repr=False)
class EvaluationObservation:
    score: float
    grade: str
    security: str
    def __post_init__(self): _normalized(self)
    def __repr__(self): return '<EvaluationObservation private>'


def _normalized(command):
    try:
        if type(command) is HealthObservation:
            if type(command.outcome) is not str or command.outcome not in ('healthy', 'reachable', 'fail'):
                raise ObservationError()
            _time(command.next_check_at, nullable=True)
            return 'health', command.outcome, {'outcome': command.outcome, 'next_check_at': command.next_check_at}
        if type(command) is SurveyObservation:
            if command.error_code is not None:
                if (command.error_code != 'survey_failed' or type(command.error_code) is not str
                        or command.tools_json != '[]' or command.guide_json != '{}' or command.full_tools_json is not None):
                    raise ObservationError()
                return 'survey', 'failed', {'error_code': 'survey_failed'}
            tools = _tools(_json(command.tools_json, list))
            guide = _json(command.guide_json, dict)
            full = None
            if command.full_tools_json is not None:
                from .capability_registry import full_tools
                raw = _tools(_json(command.full_tools_json, list))
                full = full_tools(raw)
                # Refuse unsupported top-level tool fields instead of silently
                # dropping them. Complete schema keywords remain intact.
                if raw != full or [item['name'] for item in full] != [item['name'] for item in tools]:
                    raise ObservationError()
            payload = {'tools': tools, 'guide': guide, 'full_tools': full}
            _object(_canonical(payload))
            return 'survey', 'succeeded', payload
        if type(command) is EvaluationObservation:
            if type(command.score) not in (int, float) or not math.isfinite(command.score) or not 0 <= command.score <= 100:
                raise ObservationError()
            if type(command.grade) is not str or command.grade not in ('A', 'B', 'C', 'D', 'F', 'U'):
                raise ObservationError()
            if type(command.security) is not str or command.security not in ('ok', 'review', 'quarantine', 'unknown'):
                raise ObservationError()
            return 'evaluation', 'recorded', {'score': float(command.score), 'grade': command.grade, 'security': command.security}
    except ObservationError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ObservationError() from None
    raise ObservationError()


@dataclass(frozen=True, repr=False)
class ObservationResult:
    status: str
    owner: str
    resource_id: int
    revision: int | None
    replayed: bool = False
    def __repr__(self): return '<ObservationResult private>'


@dataclass(frozen=True, repr=False)
class ObservationHead:
    resource_id: int
    owner: str
    observed_at: float
    revision: int
    outcome: str
    def __repr__(self): return '<ObservationHead private>'


OBSERVATION_SCHEMA = (
    Statement('catalog.observation_heads_schema',
        'CREATE TABLE catalog_observation_heads(resource_id BIGINT NOT NULL,owner TEXT NOT NULL,observed_at REAL NOT NULL,revision BIGINT NOT NULL,outcome TEXT NOT NULL,operation_id TEXT NOT NULL,PRIMARY KEY(resource_id,owner))',
        'CREATE TABLE catalog_observation_heads(resource_id BIGINT NOT NULL,owner TEXT NOT NULL,observed_at DOUBLE PRECISION NOT NULL,revision BIGINT NOT NULL,outcome TEXT NOT NULL,operation_id TEXT NOT NULL,PRIMARY KEY(resource_id,owner))'),
    Statement('catalog.observation_operations_schema',
        'CREATE TABLE catalog_observation_operations(operation_id TEXT PRIMARY KEY,command_hash TEXT NOT NULL,owner TEXT NOT NULL,status TEXT NOT NULL,resource_id BIGINT NOT NULL,revision BIGINT,observed_at REAL NOT NULL,outcome TEXT NOT NULL,payload TEXT NOT NULL)',
        'CREATE TABLE catalog_observation_operations(operation_id TEXT PRIMARY KEY,command_hash TEXT NOT NULL,owner TEXT NOT NULL,status TEXT NOT NULL,resource_id BIGINT NOT NULL,revision BIGINT,observed_at DOUBLE PRECISION NOT NULL,outcome TEXT NOT NULL,payload TEXT NOT NULL)'),
    Statement('catalog.observation_health_history_index',
        'CREATE INDEX catalog_observation_health_history ON catalog_observation_operations(resource_id,owner,status,observed_at)',
        'CREATE INDEX catalog_observation_health_history ON catalog_observation_operations(resource_id,owner,status,observed_at)'),
)
_RESOURCE_FIELDS = COLUMNS + _EXTRA
_STATE_SQL = 'SELECT ' + ','.join('r.' + field for field in _RESOURCE_FIELDS) + ''',v.revision,v.hash_profile,v.content_hash AS version_content_hash,v.corpus_hash,v.model_hash,v.updated_at AS registry_observed_at
 FROM resources r LEFT JOIN catalog_resource_revisions v ON v.resource_id=r.id'''
_STATE = Statement('catalog.observation_state', _STATE_SQL + ' WHERE r.id=?', _STATE_SQL + ' WHERE r.id=%s FOR UPDATE OF r', readonly=True)
_HEAD = Statement('catalog.observation_head', 'SELECT resource_id,owner,observed_at,revision,outcome FROM catalog_observation_heads WHERE resource_id=? AND owner=?',
                  'SELECT resource_id,owner,observed_at,revision,outcome FROM catalog_observation_heads WHERE resource_id=%s AND owner=%s', readonly=True)
_GET_OP = Statement('catalog.observation_operation', 'SELECT command_hash,status,owner,resource_id,revision FROM catalog_observation_operations WHERE operation_id=?',
                    'SELECT command_hash,status,owner,resource_id,revision FROM catalog_observation_operations WHERE operation_id=%s', readonly=True)
_HEALTH = Statement('catalog.observation_health',
    'UPDATE resources SET health_status=?,consecutive_failures=?,failing_since=?,last_check_at=?,last_ok_at=?,next_check_at=?,health_ok_24h=?,health_n_24h=? WHERE id=?',
    'UPDATE resources SET health_status=%s,consecutive_failures=%s,failing_since=%s,last_check_at=%s,last_ok_at=%s,next_check_at=%s,health_ok_24h=%s,health_n_24h=%s WHERE id=%s')
_HEALTH_COUNT = Statement('catalog.observation_health_counts',
    "SELECT COUNT(*) AS n,COALESCE(SUM(CASE WHEN outcome IN ('healthy','reachable') THEN 1 ELSE 0 END),0) AS ok FROM catalog_observation_operations WHERE resource_id=? AND owner='health' AND status='committed' AND observed_at>? AND observed_at<=?",
    "SELECT COUNT(*) AS n,COALESCE(SUM(CASE WHEN outcome IN ('healthy','reachable') THEN 1 ELSE 0 END),0) AS ok FROM catalog_observation_operations WHERE resource_id=%s AND owner='health' AND status='committed' AND observed_at>%s AND observed_at<=%s", readonly=True)
_SURVEY = Statement('catalog.observation_survey', 'UPDATE resources SET usage_tools=?,usage_tools_hash=?,usage_guide=?,usage_full_tools=?,usage_full_hash=?,cap_checked_at=?,eval_at=NULL WHERE id=?',
    'UPDATE resources SET usage_tools=%s,usage_tools_hash=%s,usage_guide=%s,usage_full_tools=%s,usage_full_hash=%s,cap_checked_at=%s,eval_at=NULL WHERE id=%s')
_SURVEY_FAIL = Statement('catalog.observation_survey_failed', 'UPDATE resources SET cap_checked_at=NULL,eval_at=NULL WHERE id=?', 'UPDATE resources SET cap_checked_at=NULL,eval_at=NULL WHERE id=%s')
_EVAL = Statement('catalog.observation_evaluation', 'UPDATE resources SET eval_score=?,eval_grade=?,eval_security=?,eval_at=? WHERE id=?',
    'UPDATE resources SET eval_score=%s,eval_grade=%s,eval_security=%s,eval_at=%s WHERE id=%s')
_REV = Statement('catalog.observation_revision', 'UPDATE catalog_resource_revisions SET revision=revision+1 WHERE resource_id=? AND revision=? RETURNING revision',
    'UPDATE catalog_resource_revisions SET revision=revision+1 WHERE resource_id=%s AND revision=%s RETURNING revision')
_CLOCK = Statement('catalog.observation_clock',
    'INSERT INTO catalog_observation_heads VALUES (?,?,?,?,?,?) ON CONFLICT(resource_id,owner) DO UPDATE SET observed_at=excluded.observed_at,revision=excluded.revision,outcome=excluded.outcome,operation_id=excluded.operation_id',
    'INSERT INTO catalog_observation_heads VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(resource_id,owner) DO UPDATE SET observed_at=excluded.observed_at,revision=excluded.revision,outcome=excluded.outcome,operation_id=excluded.operation_id')
_RECEIPT = Statement('catalog.observation_receipt', 'INSERT INTO catalog_observation_operations VALUES (?,?,?,?,?,?,?,?,?)',
    'INSERT INTO catalog_observation_operations VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)')


def _receipt(row, *, replayed=False):
    try:
        _hash(row['command_hash']); _id(row['resource_id'])
        if row['owner'] not in OWNERS or type(row['owner']) is not str or row['status'] not in ('committed', 'conflict'):
            raise ValueError
        if row['revision'] is not None: _id(row['revision'])
        elif row['status'] != 'conflict': raise ValueError
        return ObservationResult(row['status'], row['owner'], row['resource_id'], row['revision'], replayed)
    except (ValueError, TypeError, KeyError):
        raise ObservationError('invalid_record') from None


def _head(row):
    try:
        _id(row['resource_id']); _id(row['revision']); _time(row['observed_at'])
        if type(row['owner']) is not str or row['owner'] not in OWNERS: raise ValueError
        allowed = {'health': ('healthy', 'reachable', 'fail'), 'survey': ('succeeded', 'failed'), 'evaluation': ('recorded',)}
        if type(row['outcome']) is not str or row['outcome'] not in allowed[row['owner']]: raise ValueError
        return ObservationHead(*(row[key] for key in ('resource_id', 'owner', 'observed_at', 'revision', 'outcome')))
    except (ValueError, TypeError, KeyError):
        raise ObservationError('invalid_record') from None


class CatalogObservations:
    def __init__(self, adapter):
        if type(adapter) not in (SQLiteAdapter, PostgresAdapter): raise ObservationError()
        self._adapter = adapter

    def reconcile(self, operation_id):
        _op(operation_id)
        with self._adapter.transaction(readonly=True) as session:
            rows = session.execute(_GET_OP, (operation_id,)).rows
            return _receipt(rows[0]) if rows else None

    def current(self, resource_id, owner):
        _id(resource_id)
        if type(owner) is not str or owner not in OWNERS: raise ObservationError()
        with self._adapter.transaction(readonly=True) as session:
            rows = session.execute(_HEAD, (resource_id, owner)).rows
            return _head(rows[0]) if rows else None

    def record(self, resource_id, command, *, operation_id, expected_revision, observed_at):
        _id(resource_id); _id(expected_revision); _op(operation_id)
        if expected_revision >= 2**63 - 1: raise ObservationError()
        owner, outcome, payload = _normalized(command)
        try:
            now = _time(observed_at)
            if owner == 'health' and command.next_check_at is not None and command.next_check_at < now: raise ObservationError()
            encoded = _object(_canonical(payload))
        except (WriterError, ValueError, TypeError, OverflowError): raise ObservationError() from None
        fingerprint = _digest([PROFILE, resource_id, owner, payload, expected_revision, now])
        with self._adapter.transaction() as session:
            controls = session.execute(_LOCK).rows
            if len(controls) != 1 or type(controls[0]['enabled']) is not int or controls[0]['enabled'] != 1:
                raise ObservationError('write_disabled')
            receipts = session.execute(_GET_OP, (operation_id,)).rows
            if receipts:
                if receipts[0]['command_hash'] != fingerprint: raise ObservationError('operation_conflict')
                return _receipt(receipts[0], replayed=True)
            rows = session.execute(_STATE, (resource_id,)).rows
            row = rows[0] if rows else None
            if row is None:
                result = ObservationResult('conflict', owner, resource_id, None)
            else:
                if row['revision'] is None or row['hash_profile'] != REGISTRY_PROFILE: raise ObservationError('unversioned_resource')
                try:
                    _record(Row(COLUMNS, tuple(row[key] for key in COLUMNS)))
                    _id(row['revision']); _hash(row['version_content_hash']); _hash(row['corpus_hash']); _hash(row['model_hash'])
                    if row['revision'] >= 2**63-1 or row['version_content_hash'] != row['content_hash'] or row['registry_observed_at'] != row['last_seen']:
                        raise ValueError
                    if row['corpus_hash'] != _digest([CORPUS_PROFILE, row['kind'], row['name'], row['description'], row['category']]): raise ValueError
                except (ValueError, TypeError, KeyError, UnicodeError): raise ObservationError('invalid_record') from None
                if row['revision'] != expected_revision:
                    result = ObservationResult('conflict', owner, resource_id, row['revision'])
                else:
                    heads = session.execute(_HEAD, (resource_id, owner)).rows
                    current = _head(heads[0]) if heads else None
                    if current is not None and current.revision > expected_revision: raise ObservationError('invalid_record')
                    clock = current.observed_at if current is not None else None
                    field = {'health': 'last_check_at', 'survey': 'cap_checked_at', 'evaluation': 'eval_at'}[owner]
                    try:
                        existing = _time(row[field], nullable=True)
                    except WriterError: raise ObservationError('invalid_record') from None
                    if now < row['last_seen'] or any(value is not None and now <= value for value in (clock, existing)):
                        raise ObservationError('stale_observation')
                    if owner == 'evaluation':
                        surveys = session.execute(_HEAD, (resource_id, 'survey')).rows
                        survey = _head(surveys[0]) if surveys else None
                        if survey is not None and survey.revision > expected_revision: raise ObservationError('invalid_record')
                        try: survey_stamp = _time(row['cap_checked_at'], nullable=True)
                        except WriterError: raise ObservationError('invalid_record') from None
                        if any(value is not None and now < value for value in
                               (survey.observed_at if survey is not None else None, survey_stamp)):
                            raise ObservationError('stale_observation')
                    if owner == 'health':
                        try:
                            failures = _integer(row['consecutive_failures'], maximum=2**63-2)
                            since = _time(row['failing_since'], nullable=True)
                            last_ok = _time(row['last_ok_at'], nullable=True)
                        except WriterError: raise ObservationError('invalid_record') from None
                        up = outcome in ('healthy', 'reachable')
                        failures = 0 if up else failures + 1
                        since = None if up else now if since is None else since
                        status = outcome if up else 'down' if failures >= 3 else 'failing'
                        counts = session.execute(_HEALTH_COUNT, (resource_id, now - 86400, now)).rows[0]
                        for key in ('n', 'ok'):
                            if type(counts[key]) is not int or not 0 <= counts[key] < 2**63-1: raise ObservationError('invalid_record')
                        session.execute(_HEALTH, (status, failures, since, now, now if up else last_ok, command.next_check_at,
                                                 counts['ok'] + int(up), counts['n'] + 1, resource_id))
                    elif owner == 'survey':
                        if outcome == 'failed': session.execute(_SURVEY_FAIL, (resource_id,))
                        else:
                            full = payload['full_tools']
                            session.execute(_SURVEY, (_canonical(payload['tools']), _digest(payload['tools']), _canonical(payload['guide']),
                                _canonical(full) if full is not None else None, _digest(full) if full is not None else None, now, resource_id))
                    else:
                        session.execute(_EVAL, (payload['score'], payload['grade'], payload['security'], now, resource_id))
                    revision = session.execute(_REV, (resource_id, expected_revision)).rows
                    if len(revision) != 1 or revision[0]['revision'] != expected_revision + 1: raise ObservationError('revision_conflict')
                    session.execute(_INVALIDATE, (resource_id,))
                    enqueue(session, resource_id=resource_id, revision=expected_revision+1, corpus_hash=row['corpus_hash'], model_hash=row['model_hash'], now=now)
                    session.execute(_CLOCK, (resource_id, owner, now, expected_revision+1, outcome, operation_id))
                    result = ObservationResult('committed', owner, resource_id, expected_revision+1)
            session.execute(_RECEIPT, (operation_id, fingerprint, owner, result.status, resource_id, result.revision, now, outcome, encoded))
            return result

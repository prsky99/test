"""Bounded prospective migration from an explicit owned-copy subset.

No paths, Store initialization or operating backend switch. A held source fence
covers participating copy writers; PostgreSQL does not exclude arbitrary SQL.
Private baseline clocks refer to the copy receipt, never invented live evidence.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import html
import json
import threading
import re
from urllib.parse import unquote, urlsplit

from .storage_adapter import SQLiteAdapter, PostgresAdapter, Session, Statement, Row
from .catalog_shadow import RESOURCE_FIELDS, _copy_snapshot, _resources, _proposed
from .catalog_repository import COLUMNS, _record, _ISOLATION
from .catalog_writer import PROFILE as REGISTRY_PROFILE, CORPUS_PROFILE, _OWNED, _digest, _LOCK, _time, _integer, _hash
from .catalog_observations import _head
from .catalog_index import MODEL_HASH
from .catalog_index_outbox import enqueue

PROFILE = 'owned-catalog-copy-v1'
SOURCE_PROFILE = 'owned-legacy-subset-v1'
DOMAINS = ('auth','trial','history','authority','fts_vector','unselected_fields','uncoordinated_writers')
SOURCE_TABLES = ('resources','catalog_copy_source_control','catalog_copy_source_clocks','catalog_copy_source_exclusions')
TARGET_TABLES = ('resources','catalog_resource_revisions','catalog_write_operations','catalog_write_controls',
    'catalog_index_heads','catalog_index_jobs','catalog_index_projections','catalog_index_artifacts','catalog_index_terms',
    'catalog_observation_heads','catalog_observation_operations','connection_versions','capability_evidence',
    'capability_approvals','capability_eligibility','catalog_copy_imports','catalog_copy_mappings')
MAX_RESOURCES = 100

_TARGET_COLUMNS = {'resources': ('id',
               'key',
               'source',
               'kind',
               'url',
               'name',
               'description',
               'category',
               'active',
               'first_seen',
               'last_seen',
               'health_status',
               'last_check_at',
               'last_ok_at',
               'eval_score',
               'eval_grade',
               'eval_security',
               'eval_at',
               'content_hash',
               'auth_declared',
               'auth_observed',
               'auth_info',
               'details',
               'usage_tools',
               'usage_full_tools',
               'usage_full_hash',
               'usage_tools_hash',
               'usage_guide',
               'networks',
               'price_usdc',
               'pay_to',
               'method',
               'calls_30d',
               'payers_30d',
               'last_called',
               'host',
               'desc_lang',
               'regions',
               'cap_checked_at',
               'consecutive_failures',
               'failing_since',
               'next_check_at',
               'health_ok_24h',
               'health_n_24h'),
 'catalog_resource_revisions': ('resource_id',
                                'revision',
                                'content_hash',
                                'hash_profile',
                                'corpus_hash',
                                'model_hash',
                                'updated_at'),
 'catalog_write_operations': ('operation_id',
                              'command_hash',
                              'status',
                              'change_kind',
                              'resource_id',
                              'revision',
                              'created_at'),
 'catalog_write_controls': ('id', 'enabled', 'revision'),
 'catalog_index_heads': ('resource_id', 'model_hash', 'revision', 'corpus_hash', 'updated'),
 'catalog_index_jobs': ('job_id',
                        'resource_id',
                        'revision',
                        'corpus_hash',
                        'model_hash',
                        'state',
                        'worker_id',
                        'token',
                        'fence',
                        'lease_until',
                        'created',
                        'updated',
                        'finished',
                        'error_code',
                        'projection_hash'),
 'catalog_index_projections': ('resource_id',
                               'model_hash',
                               'revision',
                               'corpus_hash',
                               'projection_hash',
                               'job_id',
                               'indexed_at'),
 'catalog_index_artifacts': ('resource_id',
                             'revision',
                             'corpus_hash',
                             'model_hash',
                             'job_id',
                             'artifact_hash',
                             'document',
                             'materialized_at'),
 'catalog_index_terms': ('resource_id', 'term'),
 'catalog_observation_heads': ('resource_id', 'owner', 'observed_at', 'revision', 'outcome', 'operation_id'),
 'catalog_observation_operations': ('operation_id',
                                    'command_hash',
                                    'owner',
                                    'status',
                                    'resource_id',
                                    'revision',
                                    'observed_at',
                                    'outcome',
                                    'payload'),
 'connection_versions': ('id',
                         'resource_id',
                         'binding_hash',
                         'schema_hash',
                         'profile_version',
                         'schema_complete',
                         'created'),
 'capability_evidence': ('id',
                         'version_id',
                         'scope',
                         'outcome',
                         'started',
                         'finished',
                         'recorded',
                         'expires',
                         'code',
                         'operation_ref',
                         'contract_id',
                         'validator_version',
                         'dataset_version',
                         'cases',
                         'successes',
                         'artifact_hash'),
 'capability_approvals': ('version_id', 'contract_id', 'tool', 'created'),
 'capability_eligibility': ('resource_id', 'version_id', 'outcome', 'executed_at', 'expires'),
 'catalog_copy_imports': ('operation_id',
                          'fingerprint',
                          'source_digest',
                          'source_epoch',
                          'model_hash',
                          'resources',
                          'initial_revision'),
 'catalog_copy_mappings': ('resource_id',
                           'operation_id',
                           'source_hash',
                           'proposed_hash',
                           'source_row_hash',
                           'initial_revision')}
_SOURCE_COLUMNS = {
    "resources": RESOURCE_FIELDS,
    "catalog_copy_source_control": ("id","epoch","profile"),
    "catalog_copy_source_clocks": ("resource_id","owner","observed_at","outcome"),
    "catalog_copy_source_exclusions": ("domain","records"),
}


class CopyError(ValueError):
    def __init__(self, code='invalid_request', *, unsupported=None):
        self.code = code if code in ('invalid_request','unsupported_schema','invalid_source','unsupported_data',
            'source_closed','thread_violation','source_changed','target_not_empty','target_not_disabled',
            'operation_conflict','invalid_record','unsupported_model') else 'invalid_request'
        self._unsupported = unsupported
        super().__init__(self.code)
    def summary(self):
        return {'profile':PROFILE,'complete':False,'issue':self.code,
                'unsupported_domains':dict(self._unsupported) if self._unsupported is not None else None,
                'operating_cutover_authorized':False}


def _adapter(value):
    if type(value) not in (SQLiteAdapter,PostgresAdapter): raise CopyError()


def _operation(value):
    if type(value) is not str or not re.fullmatch('cp_[0-9a-f]{32}',value): raise CopyError()


def _schema(session, tables):
    path=session.execute(_PATH).rows
    if len(path)!=1 or path[0]['path']!='pg_catalog,public':raise CopyError('unsupported_schema')
    rows = session.execute(_TABLES).rows
    main = 'main' if session._adapter.dialect == 'sqlite' else 'public'
    kind = 'table' if main == 'main' else 'r'
    if len(rows) != len(tables) or {(row['name'],row['namespace'],row['kind']) for row in rows} != {(name,main,kind) for name in tables}:
        raise CopyError('unsupported_schema')
    expected=_SOURCE_COLUMNS if tables==SOURCE_TABLES else _TARGET_COLUMNS
    for name,columns in expected.items():
        if tuple(row['name'] for row in session.execute(_COLUMNS,(name,)).rows) != columns:
            raise CopyError('unsupported_schema')


_TABLES = Statement('catalog.copy_schema',
    "SELECT name,'main' AS namespace,type AS kind FROM main.sqlite_schema WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' UNION ALL SELECT name,'temp' AS namespace,type AS kind FROM temp.sqlite_schema WHERE type IN ('table','view') LIMIT 101",
    "SELECT c.relname AS name,n.nspname AS namespace,c.relkind::text AS kind FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE (n.nspname='public' OR n.oid=pg_catalog.pg_my_temp_schema()) AND c.relkind IN ('r','p','v','m','f') LIMIT 101",readonly=True)
_PATH = Statement('catalog.copy_search_path',"SELECT 'pg_catalog,public' AS path",
    "SELECT pg_catalog.array_to_string(pg_catalog.current_schemas(true),',') AS path",readonly=True)
_COLUMNS = Statement('catalog.copy_resource_columns',
    "SELECT name FROM pragma_table_info(?,'main') ORDER BY cid LIMIT 65",
    "SELECT a.attname AS name FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum LIMIT 65",readonly=True)
_SOURCE_LOCK = Statement('catalog.copy_source_lock','SELECT id,epoch,profile FROM main.catalog_copy_source_control ORDER BY id LIMIT 2',
    'SELECT id,epoch,profile FROM public.catalog_copy_source_control ORDER BY id LIMIT 2 FOR UPDATE',readonly=True)
_READ_SOURCE = Statement('catalog.copy_source_resources','SELECT '+','.join(RESOURCE_FIELDS)+' FROM main.resources ORDER BY id LIMIT 101',
    'SELECT '+','.join(RESOURCE_FIELDS)+' FROM public.resources ORDER BY id LIMIT 101',readonly=True)
_READ_CLOCKS = Statement('catalog.copy_source_clocks','SELECT resource_id,owner,observed_at,outcome FROM main.catalog_copy_source_clocks ORDER BY resource_id,owner LIMIT 301',
    'SELECT resource_id,owner,observed_at,outcome FROM public.catalog_copy_source_clocks ORDER BY resource_id,owner LIMIT 301',readonly=True)
_READ_EXCLUSIONS = Statement('catalog.copy_source_exclusions','SELECT domain,records FROM main.catalog_copy_source_exclusions ORDER BY domain LIMIT 8',
    'SELECT domain,records FROM public.catalog_copy_source_exclusions ORDER BY domain LIMIT 8',readonly=True)


def _credential_free(row):
    from .concierge.security import public_metadata
    for value in row.values():
        if type(value)is not str:continue
        for _ in range(3):value=html.unescape(unquote(value)).replace('\\/','/')
        try:decoded=json.loads(value)
        except (ValueError,TypeError):decoded=value
        if public_metadata(decoded)!=decoded:raise CopyError('unsupported_data')


def _load(session):
    try:
        _schema(session,SOURCE_TABLES)
        controls=session.execute(_SOURCE_LOCK).rows
        if len(controls)!=1 or controls[0]['id']!=1 or type(controls[0]['id'])is not int or controls[0]['profile']!=SOURCE_PROFILE: raise CopyError('invalid_source')
        epoch=controls[0]['epoch'];_integer(epoch,maximum=2**63-2)
        if epoch<1: raise CopyError('invalid_source')
        exclusions=session.execute(_READ_EXCLUSIONS).rows
        records={row['domain']:row['records'] for row in exclusions}
        if len(exclusions)!=len(DOMAINS) or set(records)!=set(DOMAINS): raise CopyError('invalid_source')
        for value in records.values():
            if value is not None:_integer(value,maximum=10**9)
        if any(value is None or value>0 for value in records.values()): raise CopyError('unsupported_data',unsupported=records)
        rows=session.execute(_READ_SOURCE).rows
        if not 1<=len(rows)<=MAX_RESOURCES: raise CopyError('invalid_source')
        snapshot={name:() for name in ('resources','revisions','heads','jobs','projections')}
        snapshot['resources']=tuple(dict(row) for row in rows)
        raw=_copy_snapshot(snapshot)['resources'];_resources(raw)
        mapped=[]
        for row in raw:
            _record(Row(COLUMNS,tuple(row[key] for key in COLUMNS)))
            if any(row[name] is not None for name in ('auth_declared','auth_observed','auth_info')): raise CopyError('unsupported_data')
            _credential_free(row)
            if row['content_hash'] is not None:_hash(row['content_hash'])
            if urlsplit(row['url']).username is not None or urlsplit(row['url']).password is not None: raise CopyError('unsupported_data')
            if row['first_seen']>row['last_seen']: raise CopyError('invalid_source')
            data,new_hash,corpus=_proposed(row,hashes=True)
            for key in ('consecutive_failures','health_ok_24h','health_n_24h'):_integer(row[key])
            for key in ('cap_checked_at','failing_since','next_check_at'):_time(row[key],nullable=True)
            if row['health_ok_24h']>row['health_n_24h']:raise CopyError('invalid_source')
            mapped.append((row,data,new_hash,corpus))
        clocks=session.execute(_READ_CLOCKS).rows
        if len(clocks)>3*MAX_RESOURCES: raise CopyError('invalid_source')
        by_id={row['id']:row for row in raw};heads={}
        for row in clocks:
            if row['resource_id'] not in by_id: raise CopyError('invalid_source')
            head=_head(dict(row)|{'revision':epoch})
            key=(head.resource_id,head.owner)
            if key in heads: raise CopyError('invalid_source')
            heads[key]=(head.observed_at,head.outcome)
        for row in raw:
            defaults=(('health','last_check_at',row['health_status'] if row['health_status'] in ('healthy','reachable') else 'fail'),
                      ('survey','cap_checked_at','succeeded'),('evaluation','eval_at','recorded'))
            for owner,field,outcome in defaults:
                stamp=row[field];key=(row['id'],owner)
                if stamp is not None and (key not in heads or stamp>heads[key][0]):heads[key]=(stamp,outcome)
        descriptor={'epoch':epoch,'resources':list(raw),'clocks':[list(key+value) for key,value in sorted(heads.items())],'excluded':records}
        return epoch,tuple(mapped),heads,_digest([PROFILE,descriptor])
    except CopyError:raise
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise CopyError('invalid_source')from None


class CopySource:
    def __init__(self,session,epoch,mapped,heads,digest):
        self._session,self._epoch,self._mapped,self._heads,self._digest=session,epoch,mapped,heads,digest
        self._active,self._owner=True,threading.get_ident()
    def __repr__(self):return '<CopySource private>'
    def _check(self):
        if not self._active:raise CopyError('source_closed')
        if self._owner!=threading.get_ident():raise CopyError('thread_violation')
        loaded=_load(self._session)
        if loaded[3]!=self._digest:raise CopyError('source_changed')
        return loaded
    def summary(self):
        epoch,mapped,_,_=self._check()
        return {'profile':PROFILE,'supported_subset_complete':True,'resources':len(mapped),
            'source_epoch':epoch,'unsupported_domains':{name:0 for name in DOMAINS},
            'participating_source_writers_fenced':True,'all_runtime_writers_excluded':False,
            'source_native_read_only_transaction':False,'source_rows_mutated':False,
            'fence':'sqlite_write_reservation'if self._session._adapter.dialect=='sqlite'else'postgres_cooperative_control_row',
            'cross_database_atomic':False,'operating_cutover_authorized':False}


@contextmanager
def source_snapshot(adapter):
    _adapter(adapter)
    with adapter.transaction() as session:
        isolation=session.execute(_ISOLATION).rows[0]['isolation']
        if isolation not in ('serializable','repeatable read','read committed'):raise CopyError('invalid_source')
        epoch,mapped,heads,digest=_load(session)
        source=CopySource(session,epoch,mapped,heads,digest)
        try:yield source
        finally:source._active=False


COPY_SCHEMA=(
 Statement('catalog.copy_imports_schema',
  'CREATE TABLE catalog_copy_imports(operation_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,source_digest TEXT NOT NULL,source_epoch BIGINT NOT NULL,model_hash TEXT NOT NULL,resources BIGINT NOT NULL,initial_revision BIGINT NOT NULL)',
  'CREATE TABLE catalog_copy_imports(operation_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,source_digest TEXT NOT NULL,source_epoch BIGINT NOT NULL,model_hash TEXT NOT NULL,resources BIGINT NOT NULL,initial_revision BIGINT NOT NULL)'),
 Statement('catalog.copy_mappings_schema',
  'CREATE TABLE catalog_copy_mappings(resource_id BIGINT PRIMARY KEY,operation_id TEXT NOT NULL,source_hash TEXT,proposed_hash TEXT NOT NULL,source_row_hash TEXT NOT NULL,initial_revision BIGINT NOT NULL)',
  'CREATE TABLE catalog_copy_mappings(resource_id BIGINT PRIMARY KEY,operation_id TEXT NOT NULL,source_hash TEXT,proposed_hash TEXT NOT NULL,source_row_hash TEXT NOT NULL,initial_revision BIGINT NOT NULL)'))
_GET_IMPORT=Statement('catalog.copy_receipt','SELECT * FROM catalog_copy_imports WHERE operation_id=?','SELECT * FROM catalog_copy_imports WHERE operation_id=%s',readonly=True)
_CONTROL_COUNT=Statement('catalog.copy_control_count','SELECT COUNT(*) AS n FROM catalog_write_controls',
    'SELECT COUNT(*) AS n FROM catalog_write_controls',readonly=True)
_EMPTY=tuple(Statement('catalog.copy_empty_'+name,'SELECT COUNT(*) AS n FROM '+name,'SELECT COUNT(*) AS n FROM '+name,readonly=True)for name in TARGET_TABLES if name!='catalog_write_controls')
_INSERT_RESOURCE=Statement('catalog.copy_insert_resource','INSERT INTO resources ('+','.join(RESOURCE_FIELDS)+') VALUES ('+','.join('?'for _ in RESOURCE_FIELDS)+') RETURNING '+','.join(RESOURCE_FIELDS),
    'INSERT INTO resources ('+','.join(RESOURCE_FIELDS)+') VALUES ('+','.join('%s'for _ in RESOURCE_FIELDS)+') RETURNING '+','.join(RESOURCE_FIELDS))
_INSERT_REVISION=Statement('catalog.copy_insert_revision','INSERT INTO catalog_resource_revisions VALUES (?,?,?,?,?,?,?) RETURNING *','INSERT INTO catalog_resource_revisions VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *')
_INSERT_HEAD=Statement('catalog.copy_insert_baseline','INSERT INTO catalog_observation_heads VALUES (?,?,?,?,?,?) RETURNING *','INSERT INTO catalog_observation_heads VALUES (%s,%s,%s,%s,%s,%s) RETURNING *')
_INSERT_MAPPING=Statement('catalog.copy_insert_mapping','INSERT INTO catalog_copy_mappings VALUES (?,?,?,?,?,?) RETURNING *','INSERT INTO catalog_copy_mappings VALUES (%s,%s,%s,%s,%s,%s) RETURNING *')
_INSERT_IMPORT=Statement('catalog.copy_insert_receipt','INSERT INTO catalog_copy_imports VALUES (?,?,?,?,?,?,?) RETURNING *','INSERT INTO catalog_copy_imports VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *')
_SEQUENCE=Statement('catalog.copy_sequence','SELECT ? AS source_max_id',"SELECT pg_catalog.setval('public.resources_id_seq'::pg_catalog.regclass,%s,true)")


def _insert(session,statement,values):
    rows=session.execute(statement,values).rows
    if len(rows)!=1 or _digest(tuple(rows[0]))!=_digest(values):raise CopyError('invalid_record')


@dataclass(frozen=True,repr=False)
class CopyResult:
    status:str
    replayed:bool
    resources:int
    initial_revision:int
    source_epoch:int
    def __repr__(self):return '<CopyResult private>'


def _result(row,replayed=False):
    try:
        _operation(row['operation_id']);_hash(row['fingerprint']);_hash(row['source_digest']);_hash(row['model_hash'])
        _integer(row['source_epoch'],maximum=2**63-2);_integer(row['resources'],maximum=MAX_RESOURCES)
        if row['source_epoch']<1 or row['resources']<1 or row['initial_revision']!=row['source_epoch']+1:raise ValueError
        return CopyResult('committed',replayed,row['resources'],row['initial_revision'],row['source_epoch'])
    except (ValueError,KeyError,TypeError):raise CopyError('invalid_record')from None


class CatalogCopy:
    def __init__(self,adapter):
        _adapter(adapter);self._adapter=adapter
    def reconcile(self,operation_id):
        _operation(operation_id)
        with self._adapter.transaction(readonly=True)as session:
            rows=session.execute(_GET_IMPORT,(operation_id,)).rows
            return _result(rows[0])if rows else None
    def apply(self,source,*,operation_id,model_hash=MODEL_HASH):
        if type(source)is not CopySource:raise CopyError()
        _operation(operation_id)
        if model_hash!=MODEL_HASH or type(model_hash)is not str:raise CopyError('unsupported_model')
        if source._session._adapter is self._adapter:raise CopyError()
        epoch,mapped,heads,digest=source._check()
        fingerprint=_digest([PROFILE,digest,epoch,model_hash])
        with self._adapter.transaction()as session:
            _schema(session,TARGET_TABLES)
            control=session.execute(_LOCK).rows
            if len(control)!=1 or type(control[0]['enabled'])is not int or session.execute(_CONTROL_COUNT).rows[0]['n']!=1:raise CopyError('invalid_record')
            receipts=session.execute(_GET_IMPORT,(operation_id,)).rows
            if receipts:
                if receipts[0]['fingerprint']!=fingerprint:raise CopyError('operation_conflict')
                return _result(receipts[0],True)
            if control[0]['enabled']!=0:raise CopyError('target_not_disabled')
            if any(session.execute(stmt).rows[0]['n']!=0 for stmt in _EMPTY):raise CopyError('target_not_empty')
            revision=epoch+1
            for row,data,new_hash,corpus in mapped:
                target=dict(row)
                target.update({key:data[key]for key in _OWNED})
                target['content_hash']=new_hash
                _insert(session,_INSERT_RESOURCE,tuple(target[key]for key in RESOURCE_FIELDS))
                _insert(session,_INSERT_REVISION,(row['id'],revision,new_hash,REGISTRY_PROFILE,corpus,model_hash,row['last_seen']))
                enqueue(session,resource_id=row['id'],revision=revision,corpus_hash=corpus,model_hash=model_hash,now=row['last_seen'])
                _insert(session,_INSERT_MAPPING,(row['id'],operation_id,row['content_hash'],new_hash,_digest(row),revision))
            for (rid,owner),(stamp,outcome)in sorted(heads.items()):
                _insert(session,_INSERT_HEAD,(rid,owner,stamp,revision,outcome,operation_id))
            # PostgreSQL sequence allocation is intentionally nontransactional.
            # Logical row rollback is verified; no gap-free/sequence rollback claim.
            session.execute(_SEQUENCE,(max(row['id']for row,_,_,_ in mapped),))
            source._check()
            _insert(session,_INSERT_IMPORT,(operation_id,fingerprint,digest,epoch,model_hash,len(mapped),revision))
            return CopyResult('committed',False,len(mapped),revision,epoch)

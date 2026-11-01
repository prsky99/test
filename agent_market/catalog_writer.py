"""Private atomic registry writer pilot; no operating Store/schema wiring.

Strict versioned inputs intentionally differ from legacy truncation/JSON hashes.
Only the registry-owned columns are replaced. External observations and immutable
connection/evidence history are not synthesized. Connections and schema are
trusted caller-owned inputs, not a public authorization boundary.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

from .storage_adapter import SQLiteAdapter, PostgresAdapter, Statement
from .catalog_repository import COLUMNS

PROFILE = 'atomic-catalog-registry-v1'
CORPUS_PROFILE = 'registry-text-corpus-v1'
ERRORS = frozenset(('invalid_command','write_disabled','unversioned_resource',
                    'operation_conflict','stale_observation','revision_conflict','invalid_record'))


class WriterError(ValueError):
    def __init__(self,code='invalid_command'):
        self.code=code if code in ERRORS else 'invalid_command'
        super().__init__(self.code)


def _text(value,maximum,*,nullable=False,nonempty=False):
    if value is None and nullable:return value
    if type(value) is not str or '\0' in value:raise WriterError()
    try:size=len(value.encode('utf-8'))
    except UnicodeError:raise WriterError() from None
    if size>maximum or nonempty and not value.strip():raise WriterError()
    return value


def _integer(value,*,nullable=False,maximum=2**63-1):
    if value is None and nullable:return value
    if type(value) is not int or not 0<=value<=maximum:raise WriterError()
    return value


def _time(value,*,nullable=False):
    if value is None and nullable:return value
    if type(value) not in (int,float) or not 0<=value<2**53 or not math.isfinite(value):raise WriterError()
    return float(value)


def _hash(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value):raise WriterError()
    return value


def _operation(value):
    if type(value) is not str or not re.fullmatch('co_[0-9a-f]{32}',value):raise WriterError()
    return value


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)


def _digest(value):return hashlib.sha256(_canonical(value).encode('ascii')).hexdigest()


def _object(text):
    _text(text,12288)
    def nonfinite(_value):raise WriterError()
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise WriterError()
            result[key]=value
        return result
    try:
        value=json.loads(text,object_pairs_hook=pairs,parse_constant=nonfinite)
        if type(value) is not dict:raise WriterError()
        pending=[(value,0)];count=0
        while pending:
            item,depth=pending.pop();count+=1
            if count>1024 or depth>12:raise WriterError()
            if type(item) is dict:
                for key,child in item.items():
                    _text(key,1024);pending.append((child,depth+1))
            elif type(item) is list:pending.extend((child,depth+1) for child in item)
            elif type(item) is str:_text(item,12288)
            elif item is None or type(item) is bool:pass
            elif type(item) is int:
                if not -(2**63)<=item<2**63:raise WriterError()
            elif type(item) is float:
                if not math.isfinite(item):raise WriterError()
            else:raise WriterError()
        encoded=_canonical(value);_text(encoded,12288)
        return encoded
    except (ValueError,TypeError,RecursionError,OverflowError):raise WriterError() from None


@dataclass(frozen=True,repr=False)
class RegistryUpsert:
    key: str
    source: str
    kind: str
    url: str
    name: str
    description: str
    category: str
    networks: tuple = ()
    price_usdc: int | None = None
    pay_to: str | None = None
    method: str | None = None
    details_json: str = '{}'
    calls_30d: int | None = None
    payers_30d: int | None = None
    last_called: float | None = None
    desc_lang: str | None = None
    regions: str | None = None
    auth_declared: int | None = None

    def __repr__(self):return '<RegistryUpsert private>'
    def __post_init__(self):_normalized(self)


def _normalized(command):
    if type(command) is not RegistryUpsert:raise WriterError()
    for name,size in (('key',512),('source',256),('url',4096),('name',800),('description',8000),('category',256)):
        _text(getattr(command,name),size,nonempty=name!='description')
    if len(command.name)>200 or len(command.description)>2000:raise WriterError()
    if type(command.kind) is not str or command.kind not in ('mcp','a2a','x402'):raise WriterError()
    if type(command.networks) is not tuple or len(command.networks)>32:raise WriterError()
    for item in command.networks:
        if type(item) is not str or not re.fullmatch('[A-Za-z0-9_.:-]{1,64}',item):raise WriterError()
    for value in (command.price_usdc,command.calls_30d,command.payers_30d):_integer(value,nullable=True)
    _integer(command.auth_declared,nullable=True,maximum=1)
    _time(command.last_called,nullable=True)
    for value,size in ((command.pay_to,256),(command.method,64),(command.desc_lang,64),(command.regions,1024)):_text(value,size,nullable=True)
    try:
        parsed=urlsplit(command.url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or any(ord(c)<33 or ord(c)==127 for c in command.url):raise WriterError()
        parsed.port
    except (ValueError,UnicodeError):raise WriterError() from None
    return {'key':command.key,'source':command.source,'kind':command.kind,'url':command.url,'name':command.name,
            'description':command.description,'category':command.category,
            'networks':','+','.join(sorted(set(command.networks)))+',','price_usdc':command.price_usdc,
            'pay_to':command.pay_to.lower() if command.pay_to else None,'method':command.method,
            'details':_object(command.details_json),'calls_30d':command.calls_30d,'payers_30d':command.payers_30d,
            'last_called':_time(command.last_called,nullable=True),'host':parsed.hostname,
            'desc_lang':command.desc_lang,'regions':command.regions,'auth_declared':command.auth_declared}


@dataclass(frozen=True,repr=False)
class WriteResult:
    status: str
    change: str
    resource_id: int | None
    revision: int | None
    replayed: bool = False
    def __repr__(self):return '<WriteResult private>'


# This deliberately supported schema is private fixture/migration source, never
# automatically executed by the writer and never applied to an operating Store.
_EXTRA = ('networks','price_usdc','pay_to','method','calls_30d','payers_30d','last_called','host',
          'desc_lang','regions','cap_checked_at','consecutive_failures','failing_since','next_check_at',
          'health_ok_24h','health_n_24h')
_REAL = frozenset(('first_seen','last_seen','last_check_at','last_ok_at','eval_score','eval_at','last_called','cap_checked_at','failing_since','next_check_at'))
_INT = frozenset(('active','auth_declared','auth_observed','price_usdc','calls_30d','payers_30d','consecutive_failures','health_ok_24h','health_n_24h'))
_REQUIRED = frozenset(('key','source','kind','url','name','description','category','first_seen','last_seen','active','details','networks'))
def _resource_schema(postgres):
    declarations=[]
    for name in COLUMNS+_EXTRA:
        if name=='id':declaration='BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY' if postgres else 'INTEGER PRIMARY KEY'
        else:
            declaration=('DOUBLE PRECISION' if postgres else 'REAL') if name in _REAL else 'BIGINT' if name in _INT else 'TEXT'
            if name in _REQUIRED:declaration+=' NOT NULL'
            if name=='key':declaration+=' UNIQUE'
        declarations.append(name+' '+declaration)
    return 'CREATE TABLE resources ('+','.join(declarations)+')'
RESOURCE_SCHEMA=(Statement('catalog.writer_resources',_resource_schema(False),_resource_schema(True)),)
WRITE_SCHEMA=(
 Statement('catalog.writer_revisions',
  'CREATE TABLE catalog_resource_revisions(resource_id INTEGER PRIMARY KEY,revision BIGINT NOT NULL,content_hash TEXT NOT NULL,hash_profile TEXT NOT NULL,corpus_hash TEXT NOT NULL,model_hash TEXT NOT NULL,updated_at REAL NOT NULL)',
  'CREATE TABLE catalog_resource_revisions(resource_id BIGINT PRIMARY KEY,revision BIGINT NOT NULL,content_hash TEXT NOT NULL,hash_profile TEXT NOT NULL,corpus_hash TEXT NOT NULL,model_hash TEXT NOT NULL,updated_at DOUBLE PRECISION NOT NULL)'),
 Statement('catalog.writer_operations',
  'CREATE TABLE catalog_write_operations(operation_id TEXT PRIMARY KEY,command_hash TEXT NOT NULL,status TEXT NOT NULL,change_kind TEXT NOT NULL,resource_id BIGINT,revision BIGINT,created_at REAL NOT NULL)',
  'CREATE TABLE catalog_write_operations(operation_id TEXT PRIMARY KEY,command_hash TEXT NOT NULL,status TEXT NOT NULL,change_kind TEXT NOT NULL,resource_id BIGINT,revision BIGINT,created_at DOUBLE PRECISION NOT NULL)'),
 Statement('catalog.writer_controls','CREATE TABLE catalog_write_controls(id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL,revision BIGINT NOT NULL)',
  'CREATE TABLE catalog_write_controls(id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL,revision BIGINT NOT NULL)'),
 Statement('catalog.writer_controls_default','INSERT INTO catalog_write_controls VALUES (1,0,0)','INSERT INTO catalog_write_controls VALUES (1,0,0)'))
_LOCK=Statement('catalog.writer_lock','SELECT enabled,revision FROM catalog_write_controls WHERE id=1',
 'SELECT enabled,revision FROM catalog_write_controls WHERE id=1 FOR UPDATE',readonly=True)
_GET_OP=Statement('catalog.writer_operation','SELECT command_hash,status,change_kind,resource_id,revision FROM catalog_write_operations WHERE operation_id=?',
 'SELECT command_hash,status,change_kind,resource_id,revision FROM catalog_write_operations WHERE operation_id=%s',readonly=True)
_STATE=Statement('catalog.writer_state','SELECT r.id,r.last_seen,r.content_hash,r.url,r.kind,r.health_status,v.revision,v.hash_profile FROM resources r LEFT JOIN catalog_resource_revisions v ON v.resource_id=r.id WHERE r.key=?',
 'SELECT r.id,r.last_seen,r.content_hash,r.url,r.kind,r.health_status,v.revision,v.hash_profile FROM resources r LEFT JOIN catalog_resource_revisions v ON v.resource_id=r.id WHERE r.key=%s FOR UPDATE OF r',readonly=True)
_OWNED=('source','kind','url','name','description','category','networks','price_usdc','pay_to','method','details','calls_30d','payers_30d','last_called','host','desc_lang','regions','auth_declared')
_INSERT_COLS=_OWNED+('key','first_seen','last_seen','active','health_status','content_hash','consecutive_failures','health_ok_24h','health_n_24h')
_INSERT=Statement('catalog.writer_insert','INSERT INTO resources ('+','.join(_INSERT_COLS)+') VALUES ('+','.join(('?',)*len(_INSERT_COLS))+') RETURNING id',
 'INSERT INTO resources ('+','.join(_INSERT_COLS)+') VALUES ('+','.join(('%s',)*len(_INSERT_COLS))+') RETURNING id')
_UPDATE=Statement('catalog.writer_update','UPDATE resources SET '+','.join(n+'=?' for n in _OWNED)+',last_seen=?,active=1,content_hash=?,cap_checked_at=NULL,eval_at=NULL WHERE id=?',
 'UPDATE resources SET '+','.join(n+'=%s' for n in _OWNED)+',last_seen=%s,active=1,content_hash=%s,cap_checked_at=NULL,eval_at=NULL WHERE id=%s')
_TOUCH=Statement('catalog.writer_touch','UPDATE resources SET last_seen=?,active=1 WHERE id=?','UPDATE resources SET last_seen=%s,active=1 WHERE id=%s')
_RESET=Statement('catalog.writer_reset',"UPDATE resources SET health_status='unknown',consecutive_failures=0,failing_since=NULL,next_check_at=NULL,health_ok_24h=0,health_n_24h=0 WHERE id=?",
 "UPDATE resources SET health_status='unknown',consecutive_failures=0,failing_since=NULL,next_check_at=NULL,health_ok_24h=0,health_n_24h=0 WHERE id=%s")
_REV_NEW=Statement('catalog.writer_revision_new','INSERT INTO catalog_resource_revisions VALUES (?,?,?,?,?,?,?)','INSERT INTO catalog_resource_revisions VALUES (%s,%s,%s,%s,%s,%s,%s)')
_REV_UPDATE=Statement('catalog.writer_revision_update','UPDATE catalog_resource_revisions SET revision=?,content_hash=?,hash_profile=?,corpus_hash=?,model_hash=?,updated_at=? WHERE resource_id=? AND revision=? RETURNING revision',
 'UPDATE catalog_resource_revisions SET revision=%s,content_hash=%s,hash_profile=%s,corpus_hash=%s,model_hash=%s,updated_at=%s WHERE resource_id=%s AND revision=%s RETURNING revision')
_INVALIDATE=Statement('catalog.writer_invalidate','DELETE FROM capability_eligibility WHERE resource_id=?','DELETE FROM capability_eligibility WHERE resource_id=%s')
_RECEIPT=Statement('catalog.writer_receipt','INSERT INTO catalog_write_operations VALUES (?,?,?,?,?,?,?)','INSERT INTO catalog_write_operations VALUES (%s,%s,%s,%s,%s,%s,%s)')


def _receipt(row,*,replayed=False):
    status,change,rid,revision=(row[n] for n in ('status','change_kind','resource_id','revision'))
    if type(status) is not str or status not in ('committed','conflict') or type(change) is not str:raise WriterError('invalid_record')
    if (status=='conflict' and change!='') or (status=='committed' and change not in ('new','changed','unchanged')):raise WriterError('invalid_record')
    if rid is None or revision is None:
        if status!='conflict' or rid is not None or revision is not None:raise WriterError('invalid_record')
    elif type(rid) is not int or not 1<=rid<2**63 or type(revision) is not int or not 1<=revision<2**63:raise WriterError('invalid_record')
    return WriteResult(status,change,rid,revision,replayed)


class CatalogWriter:
    def __init__(self,adapter,*,model_hash):
        if type(adapter) not in (SQLiteAdapter,PostgresAdapter):raise WriterError()
        self._adapter,self._model_hash=adapter,_hash(model_hash)

    def reconcile(self,operation_id):
        _operation(operation_id)
        with self._adapter.transaction(readonly=True) as session:
            rows=session.execute(_GET_OP,(operation_id,)).rows
            return _receipt(rows[0]) if rows else None

    def upsert(self,command,*,operation_id,expected_revision,observed_at):
        data=_normalized(command);_operation(operation_id);_integer(expected_revision,maximum=2**63-2);now=_time(observed_at)
        digest=_digest([PROFILE,data])
        corpus=_digest([CORPUS_PROFILE,data['kind'],data['name'],data['description'],data['category']])
        fingerprint=_digest([PROFILE,data,expected_revision,now,self._model_hash])
        with self._adapter.transaction() as session:
            controls=session.execute(_LOCK).rows
            if len(controls)!=1 or type(controls[0]['enabled']) is not int or controls[0]['enabled']!=1:raise WriterError('write_disabled')
            receipts=session.execute(_GET_OP,(operation_id,)).rows
            if receipts:
                if receipts[0]['command_hash']!=fingerprint:raise WriterError('operation_conflict')
                return _receipt(receipts[0],replayed=True)
            rows=session.execute(_STATE,(data['key'],)).rows
            old=rows[0] if rows else None
            if old is not None and (old['revision'] is None or old['hash_profile']!=PROFILE):raise WriterError('unversioned_resource')
            revision=old['revision'] if old else 0
            if type(revision) is not int or not 0<=revision<2**63-1:raise WriterError('invalid_record')
            if revision!=expected_revision:
                result=WriteResult('conflict','',old['id'] if old else None,revision if old else None)
            else:
                if old and now<_time(old['last_seen']):raise WriterError('stale_observation')
                values=tuple(data[n] for n in _OWNED)
                if old is None:
                    created=session.execute(_INSERT,values+(data['key'],now,now,1,'unknown',digest,0,0,0)).rows
                    rid=created[0]['id'];revision=1;change='new'
                    session.execute(_REV_NEW,(rid,revision,digest,PROFILE,corpus,self._model_hash,now))
                else:
                    rid=old['id'];revision+=1
                    change='unchanged' if old['content_hash']==digest else 'changed'
                    if change=='unchanged':session.execute(_TOUCH,(now,rid))
                    else:
                        session.execute(_UPDATE,values+(now,digest,rid))
                        if old['url']!=data['url'] or old['kind']!=data['kind'] or old['health_status']=='retired':session.execute(_RESET,(rid,))
                    changed=session.execute(_REV_UPDATE,(revision,digest,PROFILE,corpus,self._model_hash,now,rid,revision-1)).rows
                    if len(changed)!=1:raise WriterError('revision_conflict')
                # Invalidate the current cache only; immutable history remains.
                session.execute(_INVALIDATE,(rid,))
                from .catalog_index_outbox import enqueue
                enqueue(session,resource_id=rid,revision=revision,corpus_hash=corpus,model_hash=self._model_hash,now=now)
                result=WriteResult('committed',change,rid,revision)
            session.execute(_RECEIPT,(operation_id,fingerprint,result.status,result.change,result.resource_id,result.revision,now))
            return result

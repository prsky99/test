"""Fenced private lexical artifacts, with deterministic bounded ASCII matching.

The declared index is a source-owned token/posting contract, not FTS5/BM25,
semantic vectors, provider verification, or a public search/authorization API.
"""
from dataclasses import dataclass
import hashlib
import html
import json
import re
import unicodedata
from urllib.parse import unquote

from .storage_adapter import SQLiteAdapter, PostgresAdapter, Statement, Row
from .catalog_repository import COLUMNS, KINDS, _record
from .catalog_writer import PROFILE as WRITER_PROFILE, CORPUS_PROFILE, _digest
from .catalog_index_outbox import CatalogIndexOutbox, _claim_values, _integer, _hash, _time

PROFILE = 'catalog-lexical-artifact-v1'
MODEL_HASH = _digest([PROFILE,'ascii-wholewords-lower-2..32-and-id-order-v1',
                      'public-agent-html-percent-combined3-redact-url-email-omission-v1',unicodedata.unidata_version,128])
MAX_TERMS = 128
MAX_DOCUMENT_BYTES = 12288
MAX_QUERY_TERMS = 8
_TERM = re.compile(r'[a-z][a-z0-9]{1,31}')
_WORDS = re.compile(r'\b[A-Za-z][A-Za-z0-9]{1,31}\b')
_URLS = re.compile(r'(?i)\b(?:https?|wss?)://[^\s<>"\x27]+')
_EMAIL = re.compile(r'(?i)[A-Z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}')


class IndexArtifactError(ValueError):
    def __init__(self,code='invalid_request'):
        self.code=code if code in ('invalid_request','unsupported_model','stale_source','invalid_artifact','invalid_record','result_limit') else 'invalid_request'
        super().__init__(self.code)


def _canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
def _sha(text):return hashlib.sha256(text.encode('ascii')).hexdigest()


@dataclass(frozen=True,repr=False)
class IndexArtifact:
    resource_id: int
    revision: int
    corpus_hash: str
    model_hash: str
    document: str
    artifact_hash: str
    def __repr__(self):return '<IndexArtifact private>'
    @property
    def terms(self):return tuple(json.loads(self.document)['terms'])


@dataclass(frozen=True,repr=False)
class SearchHit:
    resource_id: int
    revision: int
    kind: str
    matched_terms: tuple
    def __repr__(self):return '<SearchHit private>'


def _validate(artifact):
    if type(artifact) is not IndexArtifact:raise IndexArtifactError('invalid_artifact')
    try:
        _integer(artifact.resource_id);_integer(artifact.revision);_hash(artifact.corpus_hash);_hash(artifact.model_hash);_hash(artifact.artifact_hash)
        if type(artifact.document) is not str or len(artifact.document)>MAX_DOCUMENT_BYTES or len(artifact.document.encode('utf-8'))>MAX_DOCUMENT_BYTES:raise ValueError
        data=json.loads(artifact.document)
        if type(data) is not dict or set(data)!= {'profile','resource_id','revision','corpus_hash','model_hash','kind','terms'}:raise ValueError
        if data['profile']!=PROFILE or data['model_hash']!=MODEL_HASH or type(data['kind']) is not str or data['kind'] not in KINDS:raise ValueError
        if type(data['resource_id']) is not int or type(data['revision']) is not int:raise ValueError
        if (data['resource_id'],data['revision'],data['corpus_hash'],data['model_hash'])!=(artifact.resource_id,artifact.revision,artifact.corpus_hash,artifact.model_hash):raise ValueError
        terms=data['terms']
        if type(terms) is not list or len(terms)>MAX_TERMS or any(type(term) is not str or not _TERM.fullmatch(term)for term in terms):raise ValueError
        if terms!=sorted(set(terms))or artifact.document!=_canonical(data)or artifact.artifact_hash!=_sha(artifact.document):raise ValueError
        return data
    except (ValueError,TypeError,UnicodeError,RecursionError,OverflowError):raise IndexArtifactError('invalid_artifact')from None


def _make(raw,revision,corpus_hash,model_hash):
    if model_hash!=MODEL_HASH:raise IndexArtifactError('unsupported_model')
    try:
        if _digest([CORPUS_PROFILE,raw['kind'],raw['name'],raw['description'],raw['category']])!=corpus_hash:raise IndexArtifactError('stale_source')
        from .concierge.connections import public_agent
        from .concierge.security import public_metadata
        public=public_agent({key:raw[key]for key in ('id','kind','name','description','category')},resource=raw,store=None)
        text=' '.join(public[key]for key in ('kind','name','description','category'))
        # Known invocation bindings are projected first. URLs and email spans are
        # then omitted rather than indexed as provider/credential query tokens.
        for _ in range(3):text=html.unescape(unquote(text)).replace('\\/','/')
        # Decoding can reveal credential syntax which the first projection
        # could not see. Redact the normalized text before making query terms.
        text=public_metadata(text)
        text=_EMAIL.sub(' ',_URLS.sub(' ',text)).replace('[REDACTED]',' ')
        terms=sorted({match[0].lower()for match in _WORDS.finditer(text)})
        if len(terms)>MAX_TERMS:raise IndexArtifactError('result_limit')
        document=_canonical({'profile':PROFILE,'resource_id':raw['id'],'revision':revision,'corpus_hash':corpus_hash,
                             'model_hash':model_hash,'kind':raw['kind'],'terms':terms})
        result=IndexArtifact(raw['id'],revision,corpus_hash,model_hash,document,_sha(document))
        _validate(result)
        return result
    except IndexArtifactError:raise
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,OverflowError):raise IndexArtifactError('invalid_record')from None


ARTIFACT_SCHEMA=(
 Statement('catalog.artifact_schema',
  'CREATE TABLE catalog_index_artifacts(resource_id INTEGER PRIMARY KEY,revision BIGINT NOT NULL,corpus_hash TEXT NOT NULL,model_hash TEXT NOT NULL,job_id TEXT NOT NULL,artifact_hash TEXT NOT NULL,document TEXT NOT NULL,materialized_at REAL NOT NULL)',
  'CREATE TABLE catalog_index_artifacts(resource_id BIGINT PRIMARY KEY,revision BIGINT NOT NULL,corpus_hash TEXT NOT NULL,model_hash TEXT NOT NULL,job_id TEXT NOT NULL,artifact_hash TEXT NOT NULL,document TEXT NOT NULL,materialized_at DOUBLE PRECISION NOT NULL)'),
 Statement('catalog.artifact_terms_schema','CREATE TABLE catalog_index_terms(resource_id BIGINT NOT NULL,term TEXT NOT NULL,PRIMARY KEY(resource_id,term))',
  'CREATE TABLE catalog_index_terms(resource_id BIGINT NOT NULL,term TEXT NOT NULL,PRIMARY KEY(resource_id,term))'),
 Statement('catalog.artifact_terms_lookup','CREATE INDEX catalog_index_terms_lookup ON catalog_index_terms(term,resource_id)',
  'CREATE INDEX catalog_index_terms_lookup ON catalog_index_terms(term,resource_id)'))
_SOURCE_COLS=','.join('r.'+name+' AS source_'+name for name in COLUMNS)
_CURRENT_BASE='SELECT '+_SOURCE_COLS+''' FROM resources r JOIN catalog_resource_revisions v ON v.resource_id=r.id
 JOIN catalog_index_heads h ON h.resource_id=r.id AND h.revision=v.revision AND h.corpus_hash=v.corpus_hash AND h.model_hash=v.model_hash'''
_CURRENT=Statement('catalog.artifact_current',_CURRENT_BASE+' WHERE r.id=? AND v.revision=? AND v.corpus_hash=? AND v.model_hash=? AND v.hash_profile=?',
 _CURRENT_BASE+' WHERE r.id=%s AND v.revision=%s AND v.corpus_hash=%s AND v.model_hash=%s AND v.hash_profile=%s',readonly=True)
_SAVE=Statement('catalog.artifact_save',
 'INSERT INTO catalog_index_artifacts VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(resource_id) DO UPDATE SET revision=excluded.revision,corpus_hash=excluded.corpus_hash,model_hash=excluded.model_hash,job_id=excluded.job_id,artifact_hash=excluded.artifact_hash,document=excluded.document,materialized_at=excluded.materialized_at',
 'INSERT INTO catalog_index_artifacts VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(resource_id) DO UPDATE SET revision=excluded.revision,corpus_hash=excluded.corpus_hash,model_hash=excluded.model_hash,job_id=excluded.job_id,artifact_hash=excluded.artifact_hash,document=excluded.document,materialized_at=excluded.materialized_at')
_DELETE_TERMS=Statement('catalog.artifact_clear_terms','DELETE FROM catalog_index_terms WHERE resource_id=?','DELETE FROM catalog_index_terms WHERE resource_id=%s')
_ADD_TERM=Statement('catalog.artifact_add_term','INSERT INTO catalog_index_terms VALUES (?,?)','INSERT INTO catalog_index_terms VALUES (%s,%s)')
_SELECT_ARTIFACT='SELECT a.resource_id,a.revision,a.corpus_hash,a.model_hash,a.document,a.artifact_hash,'+_SOURCE_COLS+''' FROM catalog_index_artifacts a
 JOIN catalog_resource_revisions v ON v.resource_id=a.resource_id AND v.revision=a.revision AND v.corpus_hash=a.corpus_hash AND v.model_hash=a.model_hash
 JOIN catalog_index_heads h ON h.resource_id=a.resource_id AND h.revision=a.revision AND h.corpus_hash=a.corpus_hash AND h.model_hash=a.model_hash
 JOIN catalog_index_projections p ON p.resource_id=a.resource_id AND p.revision=a.revision AND p.corpus_hash=a.corpus_hash AND p.model_hash=a.model_hash AND p.job_id=a.job_id AND p.projection_hash=a.artifact_hash
 JOIN catalog_index_jobs j ON j.job_id=a.job_id AND j.state='indexed' AND j.resource_id=a.resource_id AND j.revision=a.revision AND j.corpus_hash=a.corpus_hash AND j.model_hash=a.model_hash AND j.projection_hash=a.artifact_hash
 JOIN resources r ON r.id=a.resource_id'''
_READ=Statement('catalog.artifact_read',_SELECT_ARTIFACT+' WHERE a.resource_id=? AND a.model_hash=? AND v.hash_profile=?',
 _SELECT_ARTIFACT+' WHERE a.resource_id=%s AND a.model_hash=%s AND v.hash_profile=%s',readonly=True)
_SEARCH_SQLITE=" WHERE a.resource_id IN (SELECT resource_id FROM catalog_index_terms WHERE term IN (?,?,?,?,?,?,?,?) GROUP BY resource_id HAVING COUNT(DISTINCT term)=?) AND a.model_hash=? AND v.hash_profile=? AND r.active=1 AND r.health_status IN ('healthy','reachable') AND COALESCE(r.eval_security,'unknown')!='quarantine' AND (? IS NULL OR r.kind=?) ORDER BY a.resource_id LIMIT ?"
_SEARCH_PG=" WHERE a.resource_id IN (SELECT resource_id FROM catalog_index_terms WHERE term IN (%s,%s,%s,%s,%s,%s,%s,%s) GROUP BY resource_id HAVING COUNT(DISTINCT term)=%s) AND a.model_hash=%s AND v.hash_profile=%s AND r.active=1 AND r.health_status IN ('healthy','reachable') AND COALESCE(r.eval_security,'unknown')!='quarantine' AND (%s::text IS NULL OR r.kind=%s) ORDER BY a.resource_id LIMIT %s"
_SEARCH=Statement('catalog.artifact_search',_SELECT_ARTIFACT+_SEARCH_SQLITE,_SELECT_ARTIFACT+_SEARCH_PG,readonly=True)


def _raw(row):
    try:return _record(Row(COLUMNS,tuple(row['source_'+name]for name in COLUMNS))).as_private_dict()
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,OverflowError):raise IndexArtifactError('invalid_record')from None


def _stored(row):
    try:
        artifact=IndexArtifact(*(row[name]for name in ('resource_id','revision','corpus_hash','model_hash','document','artifact_hash')))
        _validate(artifact)
        if artifact!=_make(_raw(row),artifact.revision,artifact.corpus_hash,artifact.model_hash):raise IndexArtifactError('invalid_record')
        return artifact
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):raise IndexArtifactError('invalid_record')from None


class CatalogIndex:
    def __init__(self,adapter):
        if type(adapter)not in (SQLiteAdapter,PostgresAdapter):raise IndexArtifactError()
        self._adapter=adapter
        self._outbox=CatalogIndexOutbox(adapter)

    def build(self,claim):
        _claim_values(claim)
        if claim.model_hash!=MODEL_HASH:raise IndexArtifactError('unsupported_model')
        with self._adapter.transaction(readonly=True)as session:
            rows=session.execute(_CURRENT,(claim.resource_id,claim.revision,claim.corpus_hash,claim.model_hash,WRITER_PROFILE)).rows
            if not rows:raise IndexArtifactError('stale_source')
            return _make(_raw(rows[0]),claim.revision,claim.corpus_hash,claim.model_hash)

    def publish(self,claim,artifact,*,now):
        _claim_values(claim);_time(now);_validate(artifact)
        if (artifact.resource_id,artifact.revision,artifact.corpus_hash,artifact.model_hash)!=(claim.resource_id,claim.revision,claim.corpus_hash,claim.model_hash):raise IndexArtifactError('invalid_artifact')
        with self._adapter.transaction()as session:
            state=self._outbox._finish_in(session,claim,artifact.artifact_hash,now,failed=False)
            if state!='indexed':return state
            rows=session.execute(_CURRENT,(claim.resource_id,claim.revision,claim.corpus_hash,claim.model_hash,WRITER_PROFILE)).rows
            if not rows:raise IndexArtifactError('stale_source')
            if artifact!=_make(_raw(rows[0]),claim.revision,claim.corpus_hash,claim.model_hash):raise IndexArtifactError('invalid_artifact')
            session.execute(_SAVE,(artifact.resource_id,artifact.revision,artifact.corpus_hash,artifact.model_hash,claim.job_id,artifact.artifact_hash,artifact.document,now))
            session.execute(_DELETE_TERMS,(artifact.resource_id,))
            for term in artifact.terms:session.execute(_ADD_TERM,(artifact.resource_id,term))
            return state

    def artifact(self,resource_id):
        _integer(resource_id)
        with self._adapter.transaction(readonly=True)as session:
            rows=session.execute(_READ,(resource_id,MODEL_HASH,WRITER_PROFILE)).rows
            return _stored(rows[0])if rows else None

    def search(self,query,*,kind=None,limit=20):
        if type(query)is not str or len(query)>256 or type(limit)is not int or not 1<=limit<=50:raise IndexArtifactError()
        if kind is not None and(type(kind)is not str or kind not in KINDS):raise IndexArtifactError()
        words=query.split()
        if not 1<=len(words)<=MAX_QUERY_TERMS or any(not re.fullmatch('[A-Za-z][A-Za-z0-9]{1,31}',word)for word in words):raise IndexArtifactError()
        terms=tuple(sorted({word.lower()for word in words}))
        parameters=terms+(None,)*(MAX_QUERY_TERMS-len(terms))+(len(terms),MODEL_HASH,WRITER_PROFILE,kind,kind,limit)
        with self._adapter.transaction(readonly=True)as session:
            rows=session.execute(_SEARCH,parameters).rows
            hits=[]
            for row in rows:
                artifact=_stored(row)
                if not set(terms)<=set(artifact.terms):raise IndexArtifactError('invalid_record')
                hits.append(SearchHit(artifact.resource_id,artifact.revision,_raw(row)['kind'],terms))
            return tuple(hits)

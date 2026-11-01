"""Rebuildable pgvector projection; publication provenance remains authoritative.

No connection is inferred or opened here. Provision explicitly on a reviewed
Store. Native generation/source/model/vector checks still gate search results.
"""
import hashlib
import math
import struct

from .legacy_vector_index import VectorError

PROFILE = 'agentcon-pgvector-hnsw-768-cosine-v1'


def vector_literal(blob):
    if type(blob) is not bytes or len(blob) != 3072:
        raise VectorError('invalid_vector')
    values = struct.unpack('<768f',blob)
    if any(not math.isfinite(v) for v in values) or not 1e-30 <= math.fsum(v*v for v in values) <= 1e30:
        raise VectorError('invalid_vector')
    return '[' + ','.join(format(v,'.9g') for v in values) + ']'


def available(store):
    with store.tx(readonly=True):
        if store._execute("SELECT to_regclass('agentcon_search.configuration')").fetchone()[0] is None:
            return False
        rows=store._execute('SELECT profile FROM agentcon_search.configuration WHERE id=1').fetchall()
        if len(rows)!=1 or rows[0][0]!=PROFILE:
            raise VectorError('invalid_schema')
        column=store._execute("SELECT format_type(atttypid,atttypmod) FROM pg_attribute WHERE attrelid='agentcon_search.embeddings'::regclass AND attname='embedding' AND NOT attisdropped").fetchone()
        indexes=store._execute("SELECT indexdef FROM pg_indexes WHERE schemaname='agentcon_search' AND indexname='embeddings_cosine_hnsw'").fetchall()
        if not column or column[0]!='vector(768)' or len(indexes)!=1 or 'USING hnsw (embedding vector_cosine_ops)' not in indexes[0][0]:
            raise VectorError('invalid_schema')
        return True


def publish(store, claim, blob, descriptor, vector_hash):
    store._execute('''INSERT INTO agentcon_search.embeddings(resource_id,descriptor_hash,vector_hash,embedding)
        VALUES(%s,%s,%s,%s::public.vector)
        ON CONFLICT(resource_id) DO UPDATE SET descriptor_hash=EXCLUDED.descriptor_hash,
        vector_hash=EXCLUDED.vector_hash,embedding=EXCLUDED.embedding''',
        (claim.resource_id,descriptor.digest,vector_hash,vector_literal(blob)))


def nearest(store, blob, descriptor, *, kind=None, category=None, verified_only=False):
    # Metadata filtering is not execution authorization. Publication proofs are
    # still checked by the caller in the same read snapshot.
    configure_scan(store, filtered=True)
    return [row[0] for row in store._execute('''SELECT e.resource_id
        FROM agentcon_search.embeddings e JOIN public.resources r ON r.id=e.resource_id
        WHERE e.descriptor_hash=%s AND r.active=1 AND r.health_status!='retired'
          AND COALESCE(r.eval_security,'')!='quarantine'
          AND (%s::text IS NULL OR r.kind=%s)
          AND (%s::text IS NULL OR r.category=%s)
          AND (%s=0 OR r.trial_ok=1)
        ORDER BY e.embedding <=> %s::public.vector LIMIT 100''',
        (descriptor.digest,kind,kind,category,category,int(verified_only),vector_literal(blob))).fetchall()]


def configure_scan(store, *, filtered=False):
    """Per-query bounded scan; only confirmed pgvector 0.8+ gets iteration."""
    store._execute("SET LOCAL hnsw.ef_search=200")
    if not filtered:
        return False
    index = store._vector_index
    supported = getattr(index, '_quality_iterative_supported', None)
    if supported is None:
        version = store._execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        raw = version[0] if version else ''
        import re
        match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', raw) if isinstance(raw, str) else None
        supported = bool(match and tuple(map(int, match.groups())) >= (0, 8, 0))
        index._quality_iterative_supported = supported
    if supported:
        store._execute("SET LOCAL hnsw.iterative_scan='strict_order'")
        store._execute("SET LOCAL hnsw.max_scan_tuples=5000")
        store._execute("SET LOCAL hnsw.scan_mem_multiplier=1")
    return supported


def cleanup(store):
    # Changed/deleted publications cannot rank as current, even before cleanup.
    # Find stale rows without the writer lock (a full comparison can take seconds under
    # load and would block every writer); the short delete re-checks the same predicate.
    with store.tx(readonly=True):
        stale = [row[0] for row in store._execute('''SELECT e.resource_id FROM agentcon_search.embeddings e
            LEFT JOIN public.legacy_vector_provenance p ON p.resource_id=e.resource_id
            WHERE p.resource_id IS NULL OR p.vector_hash<>e.vector_hash
              OR p.descriptor_hash<>e.descriptor_hash LIMIT 256''').fetchall()]
    if not stale:
        return 0
    marks = ','.join(['%s'] * len(stale))  # bound integer ids; the store accepts at most 256 parameters
    with store.tx():
        return store._execute('''DELETE FROM agentcon_search.embeddings WHERE resource_id IN (
            SELECT e.resource_id FROM agentcon_search.embeddings e
            LEFT JOIN public.legacy_vector_provenance p ON p.resource_id=e.resource_id
            WHERE e.resource_id IN (''' + marks + ''') AND (p.resource_id IS NULL OR p.vector_hash<>e.vector_hash
              OR p.descriptor_hash<>e.descriptor_hash))''', tuple(stale)).rowcount


def install(store):
    """Explicit, transactional projection build; durable vector bytes stay intact."""
    with store.tx():
        if store._execute("SELECT to_regclass('agentcon_search.configuration')").fetchone()[0] is not None:
            raise VectorError('invalid_schema')
        if not store._execute("SELECT 1 FROM pg_extension WHERE extname='vector'").fetchone():
            raise VectorError('invalid_schema')
        store._execute("SET LOCAL statement_timeout TO '900s'")
        store._execute("SET LOCAL maintenance_work_mem TO '512MB'")
        store._execute('CREATE SCHEMA IF NOT EXISTS agentcon_search')
        store._execute('REVOKE ALL ON SCHEMA agentcon_search FROM PUBLIC')
        store._execute('CREATE TABLE agentcon_search.configuration(id BIGINT PRIMARY KEY CHECK(id=1),profile TEXT NOT NULL)')
        store._execute('''CREATE TABLE agentcon_search.embeddings(resource_id BIGINT PRIMARY KEY,
            descriptor_hash TEXT NOT NULL,vector_hash TEXT NOT NULL,embedding public.vector(768) NOT NULL)''')
        count=0
        # A server cursor bounds memory for the initial projection of old bytes.
        with store._connection.cursor(name='ac_vector_projection') as cursor:
            cursor.execute('''SELECT v.rowid,v.embedding,p.descriptor_hash,p.vector_hash
                FROM public.vec_resources v JOIN public.legacy_vector_provenance p ON p.resource_id=v.rowid''')
            while True:
                batch=cursor.fetchmany(128)
                if not batch:break
                values=[]
                for rid,raw,descriptor,vector_hash in batch:
                    blob=bytes(raw)
                    if hashlib.sha256(blob).hexdigest()!=vector_hash:
                        raise VectorError('invalid_vector')
                    values.append((rid,descriptor,vector_hash,vector_literal(blob)))
                with store._connection.cursor() as writer:
                    writer.executemany('INSERT INTO agentcon_search.embeddings VALUES(%s,%s,%s,%s::public.vector)',values)
                count+=len(values)
        store._execute('CREATE INDEX embeddings_cosine_hnsw ON agentcon_search.embeddings USING hnsw(embedding public.vector_cosine_ops) WITH(m=16,ef_construction=64)')
        store._execute('INSERT INTO agentcon_search.configuration VALUES(1,%s)',(PROFILE,))
        store._execute('ANALYZE agentcon_search.embeddings')
    store._vector_index.ann_enabled=available(store)
    return {'profile':PROFILE,'indexed':count,'approximate':True,'provenance_required':True}

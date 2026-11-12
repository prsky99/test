"""Rebuildable pgvector projection; publication provenance remains authoritative.

No connection is inferred or opened here. Provision explicitly on a reviewed
Store. Native generation/source/model/vector checks still gate search results.
"""
import hashlib
import math
import struct

from .legacy_vector_index import VectorError

PROFILE = 'agentcon-pgvector-hnsw-768-cosine-v1'

# Per-kind halfvec HNSW (11-11 draft D'). One graph over every kind answered a kind-filtered search
# with about 60 of 100 rows and recall@100 0.26 after touching ~30,000 blocks (live MCP is 12% of
# the vectors). Each kind gets its own partial index, used only when the column and all three valid
# indexes exist, so code and database can change in either order (scripts.embeddings_kind_indexes).
KINDS = ('a2a', 'mcp', 'x402')
KIND_INDEXES = {kind: 'embeddings_half_' + kind for kind in KINDS}
LAYOUT_SECONDS = 300


def layout(store):
    """{'kind_column': bool, 'kind_indexes': bool}, re-read every LAYOUT_SECONDS. Caller holds a session."""
    import time
    index = getattr(store, '_vector_index', None)
    cached = getattr(index, '_kind_layout', None)
    if cached and time.monotonic() - cached[0] < LAYOUT_SECONDS:
        return cached[1]
    column = bool(store._execute("""SELECT 1 FROM pg_attribute WHERE attrelid='agentcon_search.embeddings'::regclass
        AND attname='kind' AND NOT attisdropped""").fetchall())
    valid = store._execute("""SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='agentcon_search'
        AND c.relname IN ('embeddings_half_a2a','embeddings_half_mcp','embeddings_half_x402')
        AND i.indisvalid AND i.indisready""").fetchone()[0]
    value = {'kind_column': column, 'kind_indexes': column and valid == len(KINDS)}
    if index is not None:
        index._kind_layout = (time.monotonic(), value)
    return value


def kind_search(store, kind):
    """(kind clause, order expression, query cast) for one kind's own graph, or None for the shared graph.
    The kind is a literal from KINDS, so the planner can prove the partial index predicate."""
    if kind not in KINDS or not layout(store)['kind_indexes']:
        return None
    return "e.kind='%s'" % kind, 'e.embedding::public.halfvec(768)', 'public.halfvec(768)'


def kind_graph_search(store, kind, run, limit=100):
    """Ids nearest first through the per-kind graphs, also when no kind is asked for (11-12 PM, A3).

    RUN(clause, order, cast) executes one caller's query and returns (resource_id, distance) rows, nearest
    first. With a kind (or before D' exists) it runs once, as before. Without a kind it runs once per kind
    graph and merges by distance: every global top-LIMIT row is in its own kind's top LIMIT, so the merge is
    the shared graph's answer, and nothing reads the shared graph (embeddings_cosine_hnsw), which is then
    only maintained on insert and may be dropped after 72 h without scans (separate approval)."""
    own = kind_search(store, kind)
    if kind is not None and own is None and layout(store)['kind_indexes']:
        # Every stored vector is one of KINDS (its own graph); another kind has none, and without the
        # shared graph this would be an exact scan of every vector.
        return []
    if kind is not None or own is not None or not layout(store)['kind_indexes']:
        clause, order, cast = own or ('TRUE', 'e.embedding', 'public.vector')
        return [row[0] for row in run(clause, order, cast)]
    rows = []
    for each in KINDS:
        rows += list(run(*kind_search(store, each)))
    rows.sort(key=lambda row: (row[1], row[0]))
    return [row[0] for row in rows[:limit]]


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
        if not column or column[0]!='vector(768)':
            raise VectorError('invalid_schema')
        if len(indexes)==1 and 'USING hnsw (embedding vector_cosine_ops)' in indexes[0][0]:
            return True
        # Without the shared graph (dropped after 72 h without scans, a separately approved DB change) every
        # search reads the per-kind graphs (kind_graph_search), so the vector store stays usable only while
        # all three are valid. Any other layout is still refused.
        if not indexes and layout(store)['kind_indexes']:
            return True
        raise VectorError('invalid_schema')


def publish(store, claim, blob, descriptor, vector_hash):
    if layout(store)['kind_column']:
        store._execute('''INSERT INTO agentcon_search.embeddings(resource_id,descriptor_hash,vector_hash,embedding,kind)
            VALUES(%s,%s,%s,%s::public.vector,(SELECT kind FROM public.resources WHERE id=%s))
            ON CONFLICT(resource_id) DO UPDATE SET descriptor_hash=EXCLUDED.descriptor_hash,
            vector_hash=EXCLUDED.vector_hash,embedding=EXCLUDED.embedding,kind=EXCLUDED.kind
            WHERE embeddings.vector_hash IS DISTINCT FROM EXCLUDED.vector_hash
               OR embeddings.descriptor_hash IS DISTINCT FROM EXCLUDED.descriptor_hash
               OR embeddings.kind IS DISTINCT FROM EXCLUDED.kind''',
            (claim.resource_id,descriptor.digest,vector_hash,vector_literal(blob),claim.resource_id))
        return
    store._execute('''INSERT INTO agentcon_search.embeddings(resource_id,descriptor_hash,vector_hash,embedding)
        VALUES(%s,%s,%s,%s::public.vector)
        ON CONFLICT(resource_id) DO UPDATE SET descriptor_hash=EXCLUDED.descriptor_hash,
        vector_hash=EXCLUDED.vector_hash,embedding=EXCLUDED.embedding
        WHERE embeddings.vector_hash IS DISTINCT FROM EXCLUDED.vector_hash
           OR embeddings.descriptor_hash IS DISTINCT FROM EXCLUDED.descriptor_hash''',
        (claim.resource_id,descriptor.digest,vector_hash,vector_literal(blob)))


def nearest(store, blob, descriptor, *, kind=None, category=None, verified_only=False):
    # Metadata filtering is not execution authorization. Publication proofs are
    # still checked by the caller in the same read snapshot.
    configure_scan(store, filtered=True)
    literal = vector_literal(blob)

    def run(clause, order, cast):
        return store._execute('''SELECT e.resource_id, ''' + order + ''' <=> %s::''' + cast + ''' AS distance
        FROM agentcon_search.embeddings e JOIN public.resources r ON r.id=e.resource_id
        WHERE e.descriptor_hash=%s AND ''' + clause + ''' AND r.active=1 AND r.health_status!='retired'
          AND COALESCE(r.eval_security,'')!='quarantine'
          AND (%s::text IS NULL OR r.kind=%s)
          AND (%s::text IS NULL OR r.category=%s)
          AND (%s=0 OR r.trial_ok=1)
        ORDER BY ''' + order + ''' <=> %s::''' + cast + ''' LIMIT 100''',
        (literal,descriptor.digest,kind,kind,category,category,int(verified_only),literal)).fetchall()
    return kind_graph_search(store, kind, run)


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


# A listing waiting to be embedded again keeps its old row: the next publish usually
# writes the same vector (2026-11-09: 46% of 175k daily embeddings repeated the same
# text), and deleting the row first turned every such no-op into a delete plus insert on
# the HNSW-indexed table. Search still ignores the row until provenance matches it again.
_WAITING = '''NOT EXISTS (SELECT 1 FROM public.vec_outbox o WHERE o.resource_id=e.resource_id)
              AND NOT EXISTS (SELECT 1 FROM public.legacy_vector_heads h JOIN public.legacy_vector_jobs j USING(job_id)
                WHERE h.resource_id=e.resource_id AND j.status IN ('pending','claimed'))'''


# 11-10 10:59: the stale-row search (embeddings x provenance, temp files of 50-78 MB) passed the
# 5 s statement timeout under load. Cleanup is housekeeping: skip the round and try again later.
CLEANUP_TIMEOUT_BACKOFF = 300
CLEANUP_IDLE_REST = 300  # seconds after a search that found nothing to remove
_cleanup_backoff_until = 0.0


def cleanup(store):
    global _cleanup_backoff_until
    import logging
    import time
    if time.monotonic() < max(_cleanup_backoff_until, getattr(store, '_ann_cleanup_idle_until', 0.0)):
        return 0
    # Changed/deleted publications cannot rank as current, even before cleanup.
    # Find stale rows without the writer lock (a full comparison can take seconds under
    # load and would block every writer); the short delete re-checks the same predicate.
    try:
        with store.tx(readonly=True):
            stale = [row[0] for row in store._execute('''SELECT e.resource_id FROM agentcon_search.embeddings e
                LEFT JOIN public.legacy_vector_provenance p ON p.resource_id=e.resource_id
                WHERE (p.resource_id IS NULL OR p.vector_hash<>e.vector_hash
                  OR p.descriptor_hash<>e.descriptor_hash) AND ''' + _WAITING + ''' LIMIT 256''').fetchall()]
    except Exception as error:
        if getattr(error, 'code', None) != 'statement_failed':
            raise
        _cleanup_backoff_until = time.monotonic() + CLEANUP_TIMEOUT_BACKOFF
        logging.getLogger(__name__).warning('Vector cleanup search timed out under load; next try in %d s', CLEANUP_TIMEOUT_BACKOFF)
        return 0
    if not stale:
        # Nothing stale (the usual case): the search compares every published vector
        # (171k runs, 237 ms mean, 40,600 s of database time by 11-10), so rest before the next.
        store._ann_cleanup_idle_until = time.monotonic() + CLEANUP_IDLE_REST
        return 0
    marks = ','.join(['%s'] * len(stale))  # bound integer ids; the store accepts at most 256 parameters
    with store.tx():
        return store._execute('''DELETE FROM agentcon_search.embeddings WHERE resource_id IN (
            SELECT e.resource_id FROM agentcon_search.embeddings e
            LEFT JOIN public.legacy_vector_provenance p ON p.resource_id=e.resource_id
            WHERE e.resource_id IN (''' + marks + ''') AND (p.resource_id IS NULL OR p.vector_hash<>e.vector_hash
              OR p.descriptor_hash<>e.descriptor_hash) AND ''' + _WAITING + ''')''', tuple(stale)).rowcount


def reusable(store, claim, descriptor):
    """The stored embedding when the listing's last indexed job embedded this same text, else None.

    Health and other non-text changes invalidate a listing's vector (resources trigger), so
    the same text came back for embedding again. The row in agentcon_search.embeddings was
    written by the latest indexed job in the same transaction; when that job's corpus and
    model match the claim, the bytes are reused and checked against their stored hash.
    """
    rows = store._execute('''SELECT e.embedding::text, e.vector_hash FROM agentcon_search.embeddings e
        WHERE e.resource_id=%s AND e.descriptor_hash=%s AND EXISTS (
          SELECT 1 FROM (SELECT j.corpus_hash, j.descriptor_hash FROM public.legacy_vector_jobs j
            WHERE j.resource_id=%s AND j.status='indexed' ORDER BY j.finished DESC, j.job_id DESC LIMIT 1) last
          WHERE last.corpus_hash=%s AND last.descriptor_hash=%s)''',
        (claim.resource_id, descriptor.digest, claim.resource_id, claim.corpus_hash, descriptor.digest)).fetchall()
    if len(rows) != 1 or type(rows[0][0]) is not str:
        return None
    try:
        values = [float(v) for v in rows[0][0].strip('[]').split(',')]
    except ValueError:
        return None
    if len(values) != 768 or hashlib.sha256(struct.pack('<768f', *values)).hexdigest() != rows[0][1]:
        return None
    return values


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

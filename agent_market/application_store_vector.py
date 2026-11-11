"""PostgreSQL persistence for the existing fenced vector publication contract.

The reviewed pgvector HNSW projection is used when explicitly provisioned.
Other installations retain the bounded exact cosine compatibility path. Existing
generation, lease, model, source and vector-hash gates apply to both paths.
"""
from contextlib import contextmanager
import math
import struct

from . import legacy_vector_index
from .legacy_vector_index import VectorIndex, VectorError, PROFILE, ModelDescriptor, validate_vector

MAX_DENSE_ROWS = 20000
MAX_DENSE_BYTES = 80 * 1024 * 1024
# 11-11: a full sweep of every window read ~190k disk blocks every five minutes while the resources
# trigger already queues inserts and edits; the sweep is a safety net, so it runs once an hour.
BACKFILL_PAUSE = 3600  # seconds after a backfill sweep that found no listing to queue
# One backfill scan covers this many listing ids. The whole-catalog scan took 6.8-11 s on 289k
# listings and hit the 5 s statement timeout every 10 s (4,073 'rag index loop error', 11-10);
# a 20k-id window takes 0.3-2.5 s, and an empty sweep of every window then rests BACKFILL_PAUSE.
BACKFILL_WINDOW = 20000


class PostgresVectorIndex(VectorIndex):
    _backfill_after = 0.0  # next full backfill scan (ensure_jobs)
    _backfill_from = 0  # the next window starts after this listing id
    _backfill_swept = True  # the last scan finished a sweep of every window

    def __init__(self, store):
        from .concierge.retrieval_metrics import TimedLock
        # The catalog store's lock, timed: its waits show as lock_wait in Server-Timing (11-11).
        self.store, self.db, self.lock = store, store._db, TimedLock(store._lock)
        self.broken, self._reading = False, False
        with store.tx(readonly=True):
            present = store._execute('SELECT profile FROM legacy_vector_control WHERE id=1').fetchone()
        if present is None:
            with store.tx():
                store._execute('INSERT INTO legacy_vector_control(id,profile,descriptor_hash,descriptor_json) '
                    'VALUES(1,%s,NULL,NULL) ON CONFLICT(id) DO NOTHING', (PROFILE,))
        self.ann_enabled = store._ann_available()

    @contextmanager
    def _tx(self):
        """Use native ownership and distinguish a known rollback from lost commit."""
        from .application_store_postgres import ApplicationStoreError
        with self.lock:
            if self.broken:
                raise VectorError('broken')
            if self.db.in_transaction:
                raise VectorError('caller_transaction')
            try:
                with self.store.tx():
                    yield
            except ApplicationStoreError as error:
                if error.code in ('commit_unknown', 'connection_unusable', 'rollback_unknown'):
                    self.broken = True
                raise VectorError('commit_unknown' if error.code == 'commit_unknown' else 'database_error') from None

    def _after_publish(self, claim, blob, descriptor, vector_hash):
        if self.ann_enabled:
            from .postgres_ann import publish
            publish(self.store, claim, blob, descriptor, vector_hash)

    def kind_of(self, resource_id):
        with self.read_snapshot():
            row = self.store._execute('SELECT kind FROM public.resources WHERE id=%s', (resource_id,)).fetchone()
        return row[0] if row else None

    def reusable_vector(self, claim, descriptor):
        """The stored vector when this claim's text and model were already embedded, else None."""
        if not self.ann_enabled:
            return None
        from .postgres_ann import reusable
        try:
            with self.read_snapshot():
                return reusable(self.store, claim, descriptor)
        except VectorError:
            return None

    def ensure_jobs(self, descriptor, limit=1, resource_ids=None, expected_resources=None):
        if resource_ids is None and expected_resources is None:
            # The backfill scan reads every listing for seconds. Holding the
            # catalog writer lock meanwhile made Chat visitor writes hit their
            # lock timeout, so scan a read snapshot and let the writer
            # transaction re-check only the bounded candidates it found.
            # Once every listing is current the scan (670 ms on 230k listings) finds
            # nothing. Inserts and edits reach the queue through the resources trigger,
            # so after an empty scan look again only after BACKFILL_PAUSE.
            now, found = legacy_vector_index._now(), []
            if now >= self._backfill_after:
                # Set first: a scan that fails (statement timeout) also waits instead of
                # repeating every round.
                self._backfill_after = now + BACKFILL_PAUSE
                found = self._backfill_candidates(descriptor, limit)
                if found or not self._backfill_swept:
                    self._backfill_after = 0.0
            if not found:
                with self._tx():
                    self._pin(descriptor, bind=False)
                    self._bootstrap(limit)
                result = 0
            else:
                result = super().ensure_jobs(descriptor, len(found), found)
        else:
            result = super().ensure_jobs(descriptor, limit, resource_ids, expected_resources)
        if self.ann_enabled:
            from .postgres_ann import cleanup
            cleanup(self.store)
        return result

    def _expired_jobs(self, cutoff):
        # The sweep reads every week-old head and provenance job (80-370 ms on 2.1M jobs) even
        # when nothing is deletable. Inside the claim it held the writer lock every visitor
        # write waits on, 0.91 s at most (2026-11-01 /chat 503), so search a read snapshot.
        from .legacy_vector_index import RETENTION_BATCH
        with self.read_snapshot():
            rows = self.store._execute('''SELECT j.job_id FROM legacy_vector_jobs j
                LEFT JOIN legacy_vector_heads h ON h.job_id=j.job_id
                LEFT JOIN legacy_vector_provenance p ON p.job_id=j.job_id
                WHERE j.status IN ('indexed','failed','superseded') AND j.finished<%s
                AND h.job_id IS NULL AND p.job_id IS NULL ORDER BY j.finished,j.job_id LIMIT %s''',
                (cutoff, RETENTION_BATCH), max_rows=RETENTION_BATCH).fetchall()
        return [row[0] for row in rows]

    def _delete_expired(self, job_ids, cutoff):
        import json
        # Each id is checked again: a job may have become a head or gained provenance since.
        return self.store._execute('''DELETE FROM legacy_vector_jobs j
            WHERE j.job_id IN (SELECT value FROM jsonb_array_elements_text(%s::jsonb))
            AND j.status IN ('indexed','failed','superseded') AND j.finished<%s
            AND NOT EXISTS (SELECT 1 FROM legacy_vector_heads h WHERE h.job_id=j.job_id)
            AND NOT EXISTS (SELECT 1 FROM legacy_vector_provenance p WHERE p.job_id=j.job_id)''',
            (json.dumps(job_ids), cutoff)).rowcount

    def _backfill_candidates(self, descriptor, limit):
        from .legacy_vector_index import MAX_BATCH
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
            raise VectorError('invalid_request')
        with self.read_snapshot():
            self._pin(descriptor, bind=False)
            # Materialize the same publication and unfinished-job exclusions once,
            # instead of repeating correlated lookups for the entire catalog.
            low = self._backfill_from
            high = low + BACKFILL_WINDOW
            rows = self.store._execute("""WITH exclusions AS MATERIALIZED (
                SELECT h.resource_id FROM legacy_vector_heads h JOIN legacy_vector_jobs j USING(job_id)
                WHERE j.status IN ('pending','claimed','failed') AND h.resource_id>%s AND h.resource_id<=%s
                UNION
                SELECT p.resource_id FROM legacy_vector_provenance p
                JOIN legacy_vector_heads h USING(resource_id) JOIN legacy_vector_generations g USING(resource_id)
                WHERE p.job_id=h.job_id AND p.generation=g.generation AND p.descriptor_hash=%s
                AND p.resource_id>%s AND p.resource_id<=%s)
                SELECT r.id FROM resources r LEFT JOIN exclusions x ON x.resource_id=r.id
                WHERE r.id>%s AND r.id<=%s AND r.active=1 AND COALESCE(r.health_status,'unknown')!='retired'
                AND COALESCE(r.eval_security,'')!='quarantine' AND x.resource_id IS NULL
                ORDER BY r.id LIMIT %s""", (low, high, descriptor.digest, low, high, low, high, limit)).fetchall()
            last = self.store._execute('SELECT max(id) AS last FROM resources').fetchone()['last'] or 0
        found = [row['id'] for row in rows]
        if len(found) < limit:
            # This window is done (queued listings leave the candidates); move on, and wrap
            # after the last listing.
            self._backfill_from = 0 if high >= last else high
        self._backfill_swept = self._backfill_from == 0 and len(found) < limit
        return found

    def current_ids(self, ids, descriptor):
        from .legacy_vector_index import _id
        if (type(ids) not in (list,tuple,set) or len(ids)>100 or any(not _id(rid) for rid in ids)
                or type(descriptor) is not ModelDescriptor):
            raise VectorError('invalid_request')
        with self.lock:
            if self._reading:return self._current_batch(ids,descriptor)
            with self.read_snapshot():return self._current_batch(ids,descriptor)

    def _current_batch(self, ids, descriptor):
        """The exact publication gates, with bounded bulk reads instead of N+1."""
        from .legacy_vector_index import source
        from .application_store_resource_batches import resources
        control=self.store._execute('SELECT id,profile,descriptor_hash FROM legacy_vector_control ORDER BY id LIMIT 2').fetchall()
        if len(control)!=1 or tuple(control[0])!=(1,PROFILE,descriptor.digest) or not ids:return set()
        from psycopg import sql
        from .application_sql import placeholders
        ids=list(ids)
        query=sql.SQL("""SELECT p.resource_id,p.generation,p.job_id,p.source_hash,p.corpus_hash,p.descriptor_hash,p.vector_hash,
            g.generation AS current_generation,h.job_id AS current_job,j.status,encode(sha256(v.embedding),'hex') AS actual_hash
            FROM legacy_vector_provenance p JOIN legacy_vector_generations g USING(resource_id)
            JOIN legacy_vector_heads h USING(resource_id) JOIN legacy_vector_jobs j ON j.job_id=p.job_id
            JOIN vec_resources v ON v.rowid=p.resource_id WHERE p.resource_id IN ({})""").format(placeholders(len(ids), maximum=100))
        states=self.store._execute(query.as_string(),ids).fetchall()
        found={r['id']:dict(r) for r in resources(self.store,ids,"active=1 AND health_status!='retired' AND COALESCE(eval_security,'')!='quarantine'",(),allow_partial=True,source_only=True)}
        current=set()
        for state in states:
            row=found.get(state['resource_id'])
            if row is None:continue
            try:data=source(row)
            except VectorError:continue
            if (state['generation']==state['current_generation'] and state['job_id']==state['current_job']
                    and state['status']=='indexed' and state['source_hash']==data.source_hash
                    and state['corpus_hash']==data.corpus_hash and state['descriptor_hash']==descriptor.digest
                    and state['actual_hash']==state['vector_hash']):current.add(row['id'])
        return current

    @contextmanager
    def read_snapshot(self):
        with self.lock:
            if self.broken: raise VectorError('broken')
            if self.db.in_transaction: raise VectorError('caller_transaction')
            try:
                with self.store.tx(readonly=True):
                    self._reading = True
                    yield self.db
            except VectorError: raise
            except Exception: raise VectorError('database_error') from None
            finally: self._reading = False


def cosine(blob, query_blob):
    if type(blob) is not bytes or len(blob) != 3072 or type(query_blob) is not bytes or len(query_blob) != 3072:
        raise VectorError('invalid_vector')
    left, right = struct.unpack('<768f', blob), struct.unpack('<768f', query_blob)
    if any(not math.isfinite(value) for value in left + right): raise VectorError('invalid_vector')
    aa, bb = math.fsum(v * v for v in left), math.fsum(v * v for v in right)
    if not 1e-30 <= aa <= 1e30 or not 1e-30 <= bb <= 1e30: raise VectorError('invalid_vector')
    return max(0.0, min(2.0, 1.0 - math.fsum(a * b for a, b in zip(left, right)) / math.sqrt(aa * bb)))


def hybrid_search(engine, store, query, limit=15, kind=None, category=None, verified_only=False,
                  *, query_embedding=None, query_descriptor=None, embedding_supplied=False, _store_filter=None):
    from .gateway.classify import query_terms
    if (type(query) is not str or type(limit) is not int or not 1 <= limit <= 50
            or kind is not None and (type(kind) is not str or len(kind) > 64)
            or category is not None and (type(category) is not str or len(category) > 256)
            or store._db.in_transaction):
        return []
    query = query.replace('\0', '').strip()[:500]
    if not query: return []
    descriptor = engine.model_descriptor()
    embedding = query_embedding if embedding_supplied else engine.embed_query(query)
    supplied = query_descriptor if embedding_supplied else descriptor
    query_blob = None
    if embedding is not None and type(supplied) is ModelDescriptor and supplied.digest == descriptor.digest == engine.model_descriptor().digest:
        try: query_blob = validate_vector(embedding, descriptor)[0]
        except VectorError: pass
    index = store._vector_index
    conditions = ["active=1", "health_status!='retired'", "COALESCE(eval_security,'')!='quarantine'"]
    parameters = []
    if kind: conditions.append('kind=%s'); parameters.append(kind)
    if category: conditions.append('category=%s'); parameters.append(category)
    if verified_only: conditions.append('trial_ok=1')
    where = ' AND '.join(conditions)

    def visible(ids):
        if not ids: return {}
        result = {}
        for start in range(0, len(ids), 128):
            batch = ids[start:start + 128]
            from .application_store_resource_batches import resources as resource_batch
            rows = resource_batch(store, batch, where, parameters)
            result.update((row['id'], dict(row)) for row in rows)
        return result

    with index.read_snapshot() as read_db:
        bm25, dense = {}, {}
        terms = query_terms(query, limit=12)
        if terms:
            match = ' OR '.join('"' + term.replace('"', '') + '"' for term in terms)
            if store._native_lexical:
                from .postgres_lexical import ids as lexical_ids
                ids = lexical_ids(store, match, where, parameters, 60)
            else:
                ids = [row[0] for row in store._fts().execute('SELECT rowid FROM documents WHERE documents MATCH ? ORDER BY bm25(documents)', (match,))]
            for start in range(0, len(ids), 128):
                batch = ids[start:start + 128]; allowed = visible(batch)
                for rid in batch:
                    if rid in allowed: bm25[rid] = len(bm25) + 1
                    if len(bm25) == 60: break
                if len(bm25) == 60: break
        if query_blob is not None:
            # Over-capacity and malformed vector data retain lexical results.
            # Native SQL errors still abort the snapshot rather than committing
            # work after an uncertain database failure.
            ids = []
            if index.ann_enabled:
                from .postgres_ann import nearest as ann_nearest
                ids = ann_nearest(store, query_blob, descriptor, kind=kind, category=category,
                                  verified_only=verified_only)
            else:
                count = store._execute('SELECT COUNT(*) FROM vec_resources').fetchone()[0]
                if count <= MAX_DENSE_ROWS:
                    rows = store._execute('SELECT rowid,embedding FROM vec_resources ORDER BY rowid',
                        max_rows=MAX_DENSE_ROWS, max_bytes=MAX_DENSE_BYTES).fetchall()
                    try:
                        nearest = sorted(((row['rowid'], cosine(row['embedding'], query_blob)) for row in rows),
                            key=lambda pair: (pair[1], pair[0]))[:100]
                    except VectorError: nearest = []
                    ids = [rid for rid, _ in nearest]
            current, allowed = index.current_ids(ids, descriptor), visible(ids)
            for rid in ids:
                if rid in current and rid in allowed: dense[rid] = len(dense) + 1
        details = visible(sorted(set(bm25) | set(dense)))
        if engine.model_descriptor().digest != descriptor.digest: dense = {}
        scores = [(rid, (0.4 / (60 + bm25[rid]) if rid in bm25 else 0.0)
            + (0.6 / (60 + dense[rid]) if rid in dense else 0.0)) for rid in set(bm25) | set(dense) if rid in details]
        scores.sort(key=lambda pair: (-pair[1], pair[0]))
        columns = ('id', 'kind', 'source', 'name', 'url', 'description', 'category', 'health_status',
            'price_usdc', 'probe_latency_ms', 'eval_grade', 'eval_score', 'trial_ok', 'payers_30d', 'calls_30d')
        ranked = [{**{name: details[rid][name] for name in columns}, 'rrf_score': round(score, 4),
            'dense_match': rid in dense, 'bm25_match': rid in bm25} for rid, score in scores[:limit]]
        return _store_filter(read_db, ranked) if _store_filter is not None else ranked

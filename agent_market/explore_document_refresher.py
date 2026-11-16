"""Jobs-owned bounded loading of Explore search documents.

Kept apart from explore_documents.py on purpose: policy_hash() covers that module, so
loader changes here never invalidate documents that are already current.
"""
import hashlib
import json
import logging
import time

from . import explore_documents as documents

log = logging.getLogger("agent_market.explore_documents")


_LOWERED = set()


def background_priority(*, main_thread=False):
    """Run the calling thread at macOS utility QoS once (best effort; other systems and failures do nothing), so
    document rebuilding yields the CPU to request threads in the same process.

    The main thread only when MAIN_THREAD is asked (11-15 PM 20:3x, 20:5x): jobs runs rounds on its pool threads,
    and a round on a test's main thread lowered it for the rest of the pytest process (time.sleep(0.02) took about
    150 ms and test_request_timing failed after test_explore_documents_postgres). A command line process that
    rebuilds documents by hand (scripts/explore_search_documents.py refresh) asks for it, so it still yields the CPU
    to the request threads of the production Mac as before."""
    import sys
    import threading
    ident = threading.get_ident()
    if (ident in _LOWERED or sys.platform != 'darwin'
            or (threading.current_thread() is threading.main_thread() and not main_thread)):
        return
    _LOWERED.add(ident)
    try:
        import ctypes
        libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
        libc.pthread_set_qos_class_self_np(0x11, 0)   # QOS_CLASS_UTILITY
    except Exception:
        pass


class Refresher:
    """One jobs-owned bounded batch; source changes cannot publish stale facts."""

    # One round builds at most BATCH documents within BUDGET seconds (0.1 to 10 ms each) and
    # publishes them in one transaction; a commit per listing cost about 100 ms. The first
    # 25-per-5s setting capped the initial load at 300 per minute.
    BATCH, BUDGET = 200, 4.0
    # PM 11-14 14:2x: a policy change rebuilds about 420k documents; they go at one steady pace all day and night
    # (at most STEADY_BATCH per round of 5 s, 1,200 a minute, about 6 hours) on a low-priority thread. The pace never
    # changes for measurement hours: a measurement must see what visitors see.
    STEADY_BATCH = 100
    MAX_ATTEMPTS, PARK = 6, 7 * 86400
    # The stale-document scan reads every generation row (309k rows, 266 ms mean) even when
    # nothing changed; one scan per 5 s round cost 39,252 s of database time, the largest Explore
    # cost (2026-11-10). A scan that queues nothing rests SCAN_REST rounds; a busy one goes on.
    SCAN_REST = 12
    # Health observations change generations all day, so the scan rarely came back empty and ran
    # every 5 s: 1.36 s and about 10,000 disk blocks each, evicting the pages visitor searches read
    # (11-11: 4 scans in 30 s, 39k blocks). A scan now queues SCAN_FILL rounds of work at once and
    # does not run again while the queue still holds a full round; throughput is unchanged.
    SCAN_FILL = 6
    # 운영·SRE via PM 11-17 01:0x: one publication transaction per 100-document round held the global writer lock
    # (store.tx's pg_advisory_xact_lock) over a second during the 11-16 policy rebuild: after the round logged at
    # 02:16:42 the next came only at 02:17:11, and two 1 s lock timeouts and a deferred workflow round fell in that
    # gap. Every write now goes WRITE_CHUNK items per transaction, halving after a transaction passes WRITE_SLOW
    # (as the graph cap does, b040695b), with WRITE_PAUSE between transactions so waiting writers get the lock.
    WRITE_CHUNK, WRITE_SLOW, WRITE_PAUSE = 20, 0.3, 0.02

    def __init__(self, store, *, batch=STEADY_BATCH, interval=5, budget=BUDGET, clock=time.monotonic):
        self.store, self.batch, self.interval, self.budget, self.clock = (
            store,
            batch,
            interval,
            budget,
            clock,
        )
        self.rest_until = 0
        self.scan_after = 0
        self.carried = 0  # documents whose generation moved without a rebuild (sources unchanged)
        self.write_chunk = self.WRITE_CHUNK
        self.longest_write = 0.0  # seconds, the longest write transaction of the last round

    def _write(self, items, apply):
        """Apply items in short write transactions; the size halves after a slow one and recovers after a fast round."""
        size, done, slow = self.write_chunk, 0, False
        while done < len(items):
            part = items[done : done + size]
            started = time.monotonic()
            with self.store.tx():
                apply(part)
            took = time.monotonic() - started
            self.longest_write = max(self.longest_write, took)
            done += len(part)
            if took > self.WRITE_SLOW:
                slow, size = True, max(1, size // 2)
            if done < len(items):
                time.sleep(self.WRITE_PAUSE)
        self.write_chunk = size if slow else min(self.WRITE_CHUNK, size * 2)

    def due(self):
        return self.clock() >= self.rest_until

    def run(self):
        background_priority()
        from .application_store_resource_batches import resources
        from .concierge.discovery_contracts import contract_reads

        self.rest_until = self.clock() + self.interval
        self.longest_write = 0.0
        checked = written = skipped = 0

        @contract_reads
        def process():
            nonlocal checked, skipped
            with self.store.tx(readonly=True):
                if not documents.available(self.store):
                    self.rest_until = self.clock() + 300
                    return
            if self.clock() >= self.scan_after:
                # Poll existing durable generations, not a lossy in-process callback. The three-table
                # scan runs in a read snapshot; the write transaction only inserts the ids it found.
                # Inside the writer lock the scan held it 1-3.3 s every 5-10 minutes, with writers
                # waiting 60 times in an hour (11-11: 391 PostgreSQL lock timeouts, edge 503s).
                policy = documents.policy_hash()
                with self.store.tx(readonly=True):
                    # Most generation changes are health, capability and auth checks: the document's
                    # sources are the same, so only its generation moves (11-11: 7.2-9.9k identical
                    # documents rebuilt an hour kept jobs busy while load was 6-7).
                    # The digest is computed only for the rows the limited scan found: joining resources
                    # before the limit read 378k more blocks (+0.5 s) on production (11-11 22:5x).
                    scanned = self.store._execute(
                        """SELECT s.resource_id,s.generation,CASE WHEN s.policy_hash=%s AND s.source_digest="""
                        + documents.SOURCE_SQL
                        + """ THEN 1 ELSE 0 END FROM (
                            SELECT g.resource_id,g.generation,d.source_digest,d.policy_hash
                            FROM resource_observation_generations g
                            LEFT JOIN agentcon_search.explore_documents d ON d.resource_id=g.resource_id
                            LEFT JOIN agentcon_search.explore_document_queue q ON q.resource_id=g.resource_id
                            WHERE q.resource_id IS NULL AND (d.resource_id IS NULL OR
                                d.source_generation<>g.generation OR d.policy_hash<>%s)
                            ORDER BY g.resource_id LIMIT %s) s
                        LEFT JOIN resources r ON r.id=s.resource_id ORDER BY s.resource_id""",
                        (policy, policy, self.batch * self.SCAN_FILL),
                    ).fetchall()
                same = [{"id": row[0], "generation": row[1]} for row in scanned if row[2]]
                stale = [row[0] for row in scanned if not row[2]]
                found = 0

                def carry(part):
                    # The generation read with the matching digest must still be current: any
                    # change to a source field moves it, and that listing is rebuilt later.
                    nonlocal found
                    moved = self.store._execute(
                        """UPDATE agentcon_search.explore_documents d SET source_generation=g.generation
                        FROM resource_observation_generations g,
                            jsonb_to_recordset(%s::jsonb) AS seen(id bigint, generation bigint)
                        WHERE g.resource_id=d.resource_id AND d.resource_id=seen.id
                        AND g.generation=seen.generation AND d.policy_hash=%s""",
                        (json.dumps(part), policy),
                    ).rowcount
                    found += moved
                    self.carried += moved

                def enqueue(part):
                    # A listing deleted meanwhile is skipped (the queue references resources).
                    nonlocal found
                    found += self.store._execute(
                        """INSERT INTO agentcon_search.explore_document_queue(resource_id,queued_at)
                        SELECT r.id,%s FROM resources r
                        WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
                        ON CONFLICT(resource_id) DO NOTHING""",
                        (time.time(), json.dumps(part)),
                    ).rowcount

                self._write(same, carry)
                self._write(stale, enqueue)
                if not found:
                    self.scan_after = self.clock() + self.interval * self.SCAN_REST
            with self.store.tx(readonly=True):
                now = time.time()
                # Listings Explore can show come first; the rest of the queue follows.
                pending = self.store._execute(
                    """SELECT q.resource_id,q.queued_at,q.attempts FROM agentcon_search.explore_document_queue q
                    JOIN public.resources r ON r.id=q.resource_id
                    WHERE q.queued_at<=%s AND r.active=1 AND r.health_status IN ('healthy','reachable')
                    AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')
                    ORDER BY q.queued_at,q.resource_id LIMIT %s""",
                    (now, self.batch),
                ).fetchall()
                if len(pending) >= self.batch:
                    # A full round is still waiting: scanning now would only add to the backlog.
                    self.scan_after = max(self.scan_after, self.clock() + self.interval * self.SCAN_FILL)
                if len(pending) < self.batch:
                    chosen = [row[0] for row in pending]
                    pending += self.store._execute(
                        """SELECT resource_id,queued_at,attempts FROM agentcon_search.explore_document_queue
                        WHERE queued_at<=%s AND resource_id NOT IN
                        (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
                        ORDER BY queued_at,resource_id LIMIT %s""",
                        (now, json.dumps(chosen), self.batch - len(pending)),
                    ).fetchall()
                rows = resources(
                    self.store,
                    [row[0] for row in pending],
                    "active IN (0,1)",
                    (),
                    allow_partial=True,
                    hydrate_contracts=True,
                )
            queued = {row[0]: row[1] for row in pending}
            attempts = {row[0]: row[2] for row in pending}
            returned = {dict(raw)["id"] for raw in rows}
            # A listing the bounded read did not return (too large, or no longer matching) is
            # retried later with growing delays and parked after repeated misses, so it can
            # never hold the front of the queue and stall the load.
            missing = [rid for rid in queued if rid not in returned]
            def defer(part):
                for rid in part:
                    tries = attempts[rid] + 1
                    delay = self.PARK if tries >= self.MAX_ATTEMPTS else min(21600, 60 * 2 ** tries)
                    self.store._execute(
                        """UPDATE agentcon_search.explore_document_queue
                        SET queued_at=%s,attempts=%s WHERE resource_id=%s AND queued_at=%s""",
                        (time.time() + delay, tries, rid, queued[rid]),
                    )

            self._write(missing, defer)
            skipped += len(missing)
            started = time.monotonic()
            built, failed = [], []
            for raw in rows:
                if time.monotonic() - started > self.budget:
                    break  # the rest stay queued for the next round
                row = dict(raw)
                checked += 1
                try:
                    built.append((row["id"], documents.build(row), documents.source_digest(row)))
                except (ValueError, TypeError, RecursionError):
                    failed.append(row["id"])
            if not built and not failed:
                return
            # A commit per listing cost about 100 ms and one transaction per round held the writer over a second
            # (11-16): publication goes in WRITE_CHUNK-document transactions.
            def retry(part):
                for rid in part:
                    self.store._execute(
                        """UPDATE agentcon_search.explore_document_queue
                        SET queued_at=%s,attempts=attempts+1 WHERE resource_id=%s AND queued_at=%s""",
                        (time.time() + 300, rid, queued[rid]),
                    )

            def publish(part):
                nonlocal written
                # Lock the current sources against concurrent changes until publication completes.
                # The stored document's own bytes are hashed too: a document edited in place keeps
                # its document_hash column, and only a matching pair counts as the same document.
                policy = documents.policy_hash()
                current = {
                    row[0]: (row[1], row[2], row[3])
                    for row in self.store._execute(
                        "SELECT r.id,"
                        + documents.SOURCE_SQL
                        + ",g.generation,CASE WHEN d.policy_hash=%s AND d.document_hash="
                        "encode(sha256(convert_to(d.document,'UTF8')),'hex') THEN d.document_hash END "
                        "FROM resources r JOIN resource_observation_generations g ON g.resource_id=r.id "
                        "LEFT JOIN agentcon_search.explore_documents d ON d.resource_id=r.id "
                        "WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb)) FOR SHARE OF r",
                        (policy, json.dumps([rid for rid, _, _ in part])),
                        max_rows=len(part),
                    ).fetchall()
                }
                for rid, encoded, digest in part:
                    cur = current.get(rid)
                    if not cur or cur[0] != digest:
                        continue  # changed since it was read; the next round rebuilds it
                    if cur[2] and cur[2] == hashlib.sha256(encoded.encode()).hexdigest():
                        # Source bytes moved (a guide or contract rewritten) but the document is the
                        # same: record the new digest and generation without rewriting it.
                        self.store._execute(
                            """UPDATE agentcon_search.explore_documents SET source_digest=%s,source_generation=%s
                            WHERE resource_id=%s""",
                            (digest, cur[1], rid),
                        )
                        self.store._execute(
                            "DELETE FROM agentcon_search.explore_document_queue WHERE resource_id=%s AND queued_at=%s",
                            (rid, queued[rid]),
                        )
                        self.carried += 1
                        continue
                    self.store._execute(
                        """INSERT INTO agentcon_search.explore_documents VALUES(%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(resource_id) DO UPDATE SET source_digest=excluded.source_digest,
                        policy_hash=excluded.policy_hash,document=excluded.document,
                        document_hash=excluded.document_hash,updated_at=excluded.updated_at,source_generation=excluded.source_generation""",
                        (
                            rid,
                            digest,
                            documents.policy_hash(),
                            encoded,
                            hashlib.sha256(encoded.encode()).hexdigest(),
                            time.time(),
                            cur[1],
                        ),
                    )
                    self.store._execute(
                        "DELETE FROM agentcon_search.explore_document_queue WHERE resource_id=%s AND queued_at=%s",
                        (rid, queued[rid]),
                    )
                    written += 1

            self._write(failed, retry)
            self._write(built, publish)

        process()
        carried, self.carried = self.carried, 0
        if checked or skipped or carried:
            log.info("Explore search documents: checked=%d written=%d deferred=%d unchanged=%d longest_write_ms=%d",
                     checked, written, skipped, carried, round(self.longest_write * 1000))
        result = {"checked": checked, "written": written, "deferred": skipped}
        if carried:
            result["unchanged"] = carried
        return result


def load_status(store):
    """Aggregate loading progress for administrators; counts only, never listing content."""
    if not documents.available(store):
        return {"installed": False}
    with store.tx(readonly=True):
        row = store._execute(
            """SELECT (SELECT count(*) FROM agentcon_search.explore_documents),
                (SELECT count(*) FROM agentcon_search.explore_documents WHERE policy_hash=%s),
                count(*), count(*) FILTER (WHERE r.active=1 AND r.health_status IN ('healthy','reachable')
                    AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')),
                count(*) FILTER (WHERE q.attempts>0 AND q.attempts<%s), count(*) FILTER (WHERE q.attempts>=%s)
            FROM agentcon_search.explore_document_queue q JOIN public.resources r ON r.id=q.resource_id""",
            (documents.policy_hash(), Refresher.MAX_ATTEMPTS, Refresher.MAX_ATTEMPTS),
        ).fetchone()
    return {"installed": True, "documents": row[0], "current_policy_documents": row[1], "queued": row[2],
            "visible_queued": row[3], "retrying": row[4], "parked": row[5]}

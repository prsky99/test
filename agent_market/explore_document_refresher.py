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


class Refresher:
    """One jobs-owned bounded batch; source changes cannot publish stale facts."""

    # One round builds at most BATCH documents within BUDGET seconds (0.1 to 10 ms each) and
    # publishes them in one transaction; a commit per listing cost about 100 ms. The first
    # 25-per-5s setting capped the initial load at 300 per minute.
    BATCH, BUDGET = 200, 4.0
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

    def __init__(self, store, *, batch=BATCH, interval=5, budget=BUDGET, clock=time.monotonic):
        self.store, self.batch, self.interval, self.budget, self.clock = (
            store,
            batch,
            interval,
            budget,
            clock,
        )
        self.rest_until = 0
        self.scan_after = 0

    def due(self):
        return self.clock() >= self.rest_until

    def run(self):
        from .application_store_resource_batches import resources
        from .concierge.discovery_contracts import contract_reads

        self.rest_until = self.clock() + self.interval
        checked = written = skipped = 0

        @contract_reads
        def process():
            nonlocal checked, written, skipped
            with self.store.tx(readonly=True):
                if not documents.available(self.store):
                    self.rest_until = self.clock() + 300
                    return
            if self.clock() >= self.scan_after:
                # Poll existing durable generations, not a lossy in-process callback. The three-table
                # scan runs in a read snapshot; the write transaction only inserts the ids it found.
                # Inside the writer lock the scan held it 1-3.3 s every 5-10 minutes, with writers
                # waiting 60 times in an hour (11-11: 391 PostgreSQL lock timeouts, edge 503s).
                with self.store.tx(readonly=True):
                    stale = [row[0] for row in self.store._execute(
                        """SELECT g.resource_id FROM resource_observation_generations g
                        LEFT JOIN agentcon_search.explore_documents d ON d.resource_id=g.resource_id
                        LEFT JOIN agentcon_search.explore_document_queue q ON q.resource_id=g.resource_id
                        WHERE q.resource_id IS NULL AND (d.resource_id IS NULL OR
                            d.source_generation<>g.generation OR d.policy_hash<>%s)
                        ORDER BY g.resource_id LIMIT %s""",
                        (documents.policy_hash(), self.batch * self.SCAN_FILL),
                    ).fetchall()]
                found = 0
                if stale:
                    with self.store.tx():
                        # A listing deleted meanwhile is skipped (the queue references resources).
                        found = self.store._execute(
                            """INSERT INTO agentcon_search.explore_document_queue(resource_id,queued_at)
                            SELECT r.id,%s FROM resources r
                            WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
                            ON CONFLICT(resource_id) DO NOTHING""",
                            (time.time(), json.dumps(stale)),
                        ).rowcount
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
            if missing:
                with self.store.tx():
                    for rid in missing:
                        tries = attempts[rid] + 1
                        delay = self.PARK if tries >= self.MAX_ATTEMPTS else min(21600, 60 * 2 ** tries)
                        self.store._execute(
                            """UPDATE agentcon_search.explore_document_queue
                            SET queued_at=%s,attempts=%s WHERE resource_id=%s AND queued_at=%s""",
                            (time.time() + delay, tries, rid, queued[rid]),
                        )
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
            # One publication transaction per round: a commit per listing cost about 100 ms.
            with self.store.tx():
                for rid in failed:
                    self.store._execute(
                        """UPDATE agentcon_search.explore_document_queue
                        SET queued_at=%s,attempts=attempts+1 WHERE resource_id=%s AND queued_at=%s""",
                        (time.time() + 300, rid, queued[rid]),
                    )
                if built:
                    # Lock the current sources against concurrent changes until publication completes.
                    current = {
                        row[0]: (row[1], row[2])
                        for row in self.store._execute(
                            "SELECT r.id,"
                            + documents.SOURCE_SQL
                            + ",g.generation FROM resources r JOIN resource_observation_generations g ON g.resource_id=r.id "
                            "WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb)) FOR SHARE OF r",
                            (json.dumps([rid for rid, _, _ in built]),),
                            max_rows=len(built),
                        ).fetchall()
                    }
                    for rid, encoded, digest in built:
                        found = current.get(rid)
                        if not found or found[0] != digest:
                            continue  # changed since it was read; the next round rebuilds it
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
                                found[1],
                            ),
                        )
                        self.store._execute(
                            "DELETE FROM agentcon_search.explore_document_queue WHERE resource_id=%s AND queued_at=%s",
                            (rid, queued[rid]),
                        )
                        written += 1

        process()
        if checked or skipped:
            log.info("Explore search documents: checked=%d written=%d deferred=%d", checked, written, skipped)
        return {"checked": checked, "written": written, "deferred": skipped}


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

"""Explore's read of current search documents, bound by source generation.

Kept apart from explore_documents.py: policy_hash() covers that module, so changing how
documents are read never invalidates the documents already built.

explore_documents.read() recomputes the sha256 of every source field, including whole tool
contracts, on each read; for a page of large MCP contracts that cost 170-390 ms per 100
listings. A document instead records the observation generation it was built from, under a
lock that confirmed the source digest at publication. The attested generation trigger bumps
that number whenever any source field (and several others) changes, so an equal generation
means the same source bytes. A changed generation only sends the listing back to the
complete-contract path until jobs rebuilds it; it never serves stale facts.
"""

import json

from . import explore_documents as documents
from .concierge.retrieval_metrics import timed
from .postgres_capability_text import SEARCHABLE


# Row fields no admission check reads (selection, task_requirements, explore_search, execution_policy,
# content_policy, recommendation_security, protocols, capability_registry, 11-11). Cards re-read complete rows,
# so these never reach a visitor from here; skipping them cuts the decoded bytes of an Explore candidate
# (A2A about 24%, MCP about 7%: usage_tools stays, it is bound into the document).
SKIPPED = frozenset(("usage_full_tools", "eval_info", "usage_changes", "content_hash", "last_error"))


@timed("search_document")
def read(store, ids):
    """Current rows with their documents when generation, policy and document hash all match."""
    if not ids or not documents.available(store):
        return {}
    from .application_store_postgres import _CATALOG
    from psycopg import sql

    columns = [row[1] for row in _CATALOG["metadata"]["resources"] if row[1] not in SKIPPED]
    sizes = sql.SQL("+").join(
        sql.SQL("coalesce(octet_length(r.{}),0)").format(sql.Identifier(row[1]))
        for row in _CATALOG["metadata"]["resources"]
        if row[1] in columns and row[2] in ("TEXT", "BLOB")
    )
    statement = sql.SQL(
        """WITH budget AS MATERIALIZED (
        SELECT r.id,sum({}+octet_length(d.document)+%s) OVER (ORDER BY r.id) AS wire_bytes
        FROM resources r JOIN agentcon_search.explore_documents d ON d.resource_id=r.id
        JOIN resource_observation_generations g ON g.resource_id=r.id
        WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
        AND d.policy_hash=%s AND octet_length(d.document)<=%s AND d.source_generation=g.generation)
        SELECT {},d.document,d.source_digest,d.document_hash FROM budget b
        JOIN resources r ON r.id=b.id JOIN agentcon_search.explore_documents d ON d.resource_id=r.id
        JOIN resource_observation_generations g ON g.resource_id=r.id
        WHERE b.wire_bytes<=%s AND d.source_generation=g.generation
        AND d.document_hash=encode(sha256(convert_to(d.document,'UTF8')),'hex')
        AND """
        + SEARCHABLE
    ).format(sizes, sql.SQL(",").join(sql.SQL("r.{}").format(sql.Identifier(name)) for name in columns))
    rows = store._execute(
        statement.as_string(),
        (16 * len(columns) + 256, json.dumps(ids), documents.policy_hash(), documents.MAX_DOCUMENT_BYTES,
         documents.MAX_READ_BYTES),
        max_rows=len(ids),
        max_bytes=32 * 1024 * 1024,
    ).fetchall()
    found = {}
    for row in rows:
        value = dict(row)
        encoded = value.pop("document")
        fingerprint = value.pop("source_digest") + value.pop("document_hash")
        try:
            document = json.loads(encoded)
            if (document.get("profile") != documents.PROFILE or not isinstance(document["tools"], list)
                    or not isinstance(document["support"], dict) or not isinstance(document["text"], str)):
                continue
        except (ValueError, TypeError, KeyError, RecursionError):
            continue
        value["_explore_document"] = documents._Facts(
            tuple(value.get(key) for key in documents.BOUND_FIELDS),
            json.dumps(document["tools"], separators=(",", ":")),
            fingerprint,
        )
        value["_tool_support"] = document["support"]
        value["_capability_text"] = document["text"]
        found[value["id"]] = value
    return found


@timed("search_document")
def texts(store, ids):
    """Capability text of the documents read() would accept, without the row columns.

    Same policy, generation, size, hash and profile conditions as read(); Explore uses it to
    skip listings whose own text cannot satisfy the cheap admission condition (2026-11-04).
    The document is parsed here as read() does: some hold escaped NULs that PostgreSQL
    json casts reject, which would fail the whole search."""
    if not ids or not documents.available(store):
        return {}
    rows = store._execute(
        """SELECT r.id,d.document FROM resources r
        JOIN agentcon_search.explore_documents d ON d.resource_id=r.id
        JOIN resource_observation_generations g ON g.resource_id=r.id
        WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
        AND d.policy_hash=%s AND octet_length(d.document)<=%s AND d.source_generation=g.generation
        AND d.document_hash=encode(sha256(convert_to(d.document,'UTF8')),'hex')
        AND """ + SEARCHABLE,
        (json.dumps(ids), documents.policy_hash(), documents.MAX_DOCUMENT_BYTES),
        max_rows=len(ids),
        max_bytes=32 * 1024 * 1024,
    ).fetchall()
    found = {}
    for rid, encoded in rows:
        try:
            document = json.loads(encoded)
        except (ValueError, TypeError, RecursionError):
            continue
        if (isinstance(document, dict) and document.get("profile") == documents.PROFILE
                and isinstance(document.get("tools"), list) and isinstance(document.get("support"), dict)
                and isinstance(document.get("text"), str)):
            found[rid] = document["text"]
    return found

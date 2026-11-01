"""Rebuildable discovery-only facts, bound to current source bytes and policy.

This projection never authorizes execution or replaces a callable contract.
Provision explicitly. Missing/stale facts retain the original full-row path.
"""

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
import time

from .postgres_capability_text import SEARCHABLE
from .concierge.retrieval_metrics import timed

log = logging.getLogger(__name__)

# Exactly the sources consumed by the pure tool/text derivation. Existing
# observation generations cover all of these fields across every writer.
SOURCE_FIELDS = (
    "kind",
    "name",
    "description",
    "usage_tools",
    "usage_full_tools",
    "usage_full_hash",
    "usage_guide",
)

PROFILE = "explore-documents-v1"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_READ_BYTES = 24 * 1024 * 1024
SOURCE_SQL = (
    "encode(sha256(convert_to("
    + "||".join(
        f"coalesce(octet_length(r.{name})::text||':'||r.{name},'-')||'|'"
        for name in SOURCE_FIELDS
    )
    + ", 'UTF8')),'hex')"
)
BOUND_FIELDS = (
    "id",
    *[field for field in SOURCE_FIELDS if field != "usage_full_tools"],
)


@lru_cache(maxsize=1)
def policy_hash():
    """Invalidate derived facts when any of their policy implementations changes."""
    base = Path(__file__).parent
    names = (
        __file__,
        *(
            str(base / name)
            for name in (
                "concierge/selection.py",
                "concierge/task_requirements.py",
                "concierge/explore_search.py",
                "concierge/execution_policy.py",
                "capability_registry.py",
                "collector/usage.py",
                "postgres_capability_text.py",
            )
        ),
    )
    digest = hashlib.sha256()
    for name in names:
        data = Path(name).read_bytes()
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def source_digest(resource):
    digest = hashlib.sha256()
    for name in SOURCE_FIELDS:
        value = resource.get(name)
        if value is not None and type(value) is not str:
            raise ValueError("Discovery sources must be database text.")
        data = (
            b"-"
            if value is None
            else str(len(value.encode("utf-8"))).encode() + b":" + value.encode("utf-8")
        )
        digest.update(data + b"|")
    return digest.hexdigest()


def build(resource):
    """Precompute exactly the metadata consumed by discovery, not input contracts."""
    from .concierge.selection import _advertised_tools
    from .concierge.execution_policy import discovery_schema_supported
    from .postgres_capability_text import build as capability_text

    tools, support = [], {}
    for tool in _advertised_tools(resource):
        fact = {key: tool[key] for key in ("name", "id", "description") if key in tool}
        schema = tool.get("inputSchema")
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(properties, dict):
            fact["inputSchema"] = {"properties": {name: {} for name in properties}}
        tools.append(fact)
        if resource.get("kind") == "mcp" and isinstance(tool.get("name"), str):
            support.setdefault(tool["name"], discovery_schema_supported(tool))
    value = json.dumps(
        {
            "profile": PROFILE,
            "tools": tools,
            "support": support,
            "text": capability_text(resource),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(value.encode()) > MAX_DOCUMENT_BYTES:
        raise ValueError("Search document exceeds its byte budget.")
    return value


@dataclass(frozen=True, repr=False)
class _Facts:
    binding: tuple
    encoded: str
    cache_key: str


def is_search_row(resource):
    return type(resource.get("_explore_document")) is _Facts


def tools_for_search(resource):
    """Only a loader-created, row-bound object may supply discovery metadata."""
    facts = resource.get("_explore_document")
    if type(facts) is not _Facts or facts.binding != tuple(
        resource.get(key) for key in BOUND_FIELDS
    ):
        return None
    return json.loads(facts.encoded)


def cache_view(resource):
    """Make only the private marker serializable; every current row field stays in the task key."""
    facts = resource.get("_explore_document")
    if type(facts) is _Facts and facts.binding == tuple(
        resource.get(key) for key in BOUND_FIELDS
    ):
        return {**resource, "_explore_document": ("search-document", facts.cache_key)}
    return resource


def available(store):
    if getattr(store, "backend", None) != "postgresql":
        return False
    with store.tx(readonly=True):
        return bool(
            store._execute(
                "SELECT to_regclass('agentcon_search.explore_documents')"
            ).fetchone()[0]
        )


def install(store):
    """Explicit schema change only; queue existing IDs without reading declarations."""
    with store.tx():
        store._execute("CREATE SCHEMA IF NOT EXISTS agentcon_search")
        store._execute("REVOKE ALL ON SCHEMA agentcon_search FROM PUBLIC")
        store._execute("""CREATE TABLE agentcon_search.explore_documents(
            resource_id BIGINT PRIMARY KEY REFERENCES public.resources(id) ON DELETE CASCADE,
            source_digest TEXT NOT NULL,policy_hash TEXT NOT NULL,document TEXT NOT NULL,
            document_hash TEXT NOT NULL,updated_at DOUBLE PRECISION NOT NULL,source_generation BIGINT NOT NULL)""")
        store._execute("""CREATE TABLE agentcon_search.explore_document_queue(
            resource_id BIGINT PRIMARY KEY REFERENCES public.resources(id) ON DELETE CASCADE,
            queued_at DOUBLE PRECISION NOT NULL,attempts INTEGER NOT NULL DEFAULT 0)""")
        store._execute(
            "CREATE INDEX explore_document_queue_due ON agentcon_search.explore_document_queue(queued_at,resource_id)"
        )
        # Reuse the already attested resource observation generation trigger.
        # Adding a second resource trigger would break mixed-version Store readers.
        store._execute("""INSERT INTO agentcon_search.explore_document_queue(resource_id,queued_at)
            SELECT id,extract(epoch FROM clock_timestamp()) FROM public.resources""")
    return {"profile": PROFILE, "execution_authority": False}


@timed("search_document")
def read(store, ids):
    """Read lightweight current rows only when both source and derivation still match."""
    if not ids or not available(store):
        return {}
    from .application_store_postgres import _CATALOG
    from psycopg import sql

    columns = [
        row[1]
        for row in _CATALOG["metadata"]["resources"]
        if row[1] != "usage_full_tools"
    ]
    sizes = sql.SQL("+").join(
        sql.SQL("coalesce(octet_length(r.{}),0)").format(sql.Identifier(row[1]))
        for row in _CATALOG["metadata"]["resources"]
        if row[1] in columns and row[2] in ("TEXT", "BLOB")
    )
    statement = sql.SQL(
        """WITH budget AS MATERIALIZED (
        SELECT r.id,sum({}+octet_length(d.document)+%s) OVER (ORDER BY r.id) AS wire_bytes
        FROM resources r JOIN agentcon_search.explore_documents d ON d.resource_id=r.id
        WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))
        AND d.policy_hash=%s AND octet_length(d.document)<=%s)
        SELECT {},d.document,d.source_digest,d.document_hash FROM budget b
        JOIN resources r ON r.id=b.id JOIN agentcon_search.explore_documents d ON d.resource_id=r.id
        WHERE b.wire_bytes<=%s AND d.source_digest="""
        + SOURCE_SQL
        + """
        AND d.document_hash=encode(sha256(convert_to(d.document,'UTF8')),'hex')
        AND """
        + SEARCHABLE
    ).format(
        sizes,
        sql.SQL(",").join(
            sql.SQL("r.{}").format(sql.Identifier(name)) for name in columns
        ),
    )
    rows = store._execute(
        statement.as_string(),
        (
            16 * len(columns) + 256,
            json.dumps(ids),
            policy_hash(),
            MAX_DOCUMENT_BYTES,
            MAX_READ_BYTES,
        ),
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
            if (
                document.get("profile") != PROFILE
                or not isinstance(document["tools"], list)
                or not isinstance(document["support"], dict)
                or not isinstance(document["text"], str)
            ):
                continue
        except (ValueError, TypeError, KeyError, RecursionError):
            continue
        value["_explore_document"] = _Facts(
            tuple(value.get(key) for key in BOUND_FIELDS),
            json.dumps(document["tools"], separators=(",", ":")),
            fingerprint,
        )
        value["_tool_support"] = document["support"]
        value["_capability_text"] = document["text"]
        found[value["id"]] = value
    return found


def __getattr__(name):
    # The jobs refresher lives in its own module so changes to how documents are loaded
    # do not change policy_hash() and invalidate every document already built.
    if name == "Refresher":
        from .explore_document_refresher import Refresher
        return Refresher
    raise AttributeError(name)

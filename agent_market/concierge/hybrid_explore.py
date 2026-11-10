"""Public hybrid result projection without registering or executing providers."""

from urllib.parse import urlsplit
from contextlib import nullcontext
import re
import time
import threading

from .connections import public_agent
from .discovery import candidates, normalize_task
from .selection import search_terms, capability_terms
from .recommendation_security import usable_endpoint
from ..capability_registry import Registry
from ..search_quality import observed
from .discovery_contracts import contract_reads
from .retrieval_metrics import timed


# "8004" or "ERC-8004 agents" asks for the on-chain registry's agents, not a capability.
FOCUS_FILL = 12  # MCP listings checked for a task-led match when A2A already fills the page
ERC8004_QUERY = re.compile(r'(?:erc[- ]?)?8004(?:\s+(?:agents?|registry|registered(?: agents?)?|identity))?', re.I)
_parallel_explore = threading.BoundedSemaphore(1)
BROWSE_TEMPLATE_READ = 3  # listings read per browse slot so collapsed templates still fill the page


def _template_key(record):
    """Descriptions that differ only by the listing's own name, as when one registry mints many agents."""
    text = ' '.join(str(record.get('description') or '').split())
    name = str(record.get('name') or '').strip()
    if len(text) < 40 or not name:
        return None
    return re.sub(re.escape(name), '\0', text, flags=re.I).casefold()[:160]


def _collapse_templates(records):
    """Keep the first listing of each templated description so one registry cannot fill the browse page."""
    kept, seen = [], set()
    for record in records:
        key = _template_key(record)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        kept.append(record)
    return kept


@observed('explore')
@contract_reads
def scoped_explore(source, engine, query, kind, category, verified, no_auth, limit):
    """Overlap independent protocol reads within the existing pool's connection cap."""
    from .discovery import discovery_store
    from .protocols import search_protocols, merge_discovery_results
    pool = getattr(source, '_admin_read_pool', None)
    parallel = kind is None and getattr(source,'backend',None)=='postgresql' and getattr(pool,'maximum',0)>=2
    if not parallel or not _parallel_explore.acquire(blocking=False):
        with discovery_store(source) as store:
            return explore(store,engine,query,kind,category,verified,no_auth,limit)
    try:
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        from .discovery_contracts import isolated_contract_reads

        def read(protocol):
            # The caller holds no reader lease, so the workers cannot wait on their parent.
            with discovery_store(source) as store, isolated_contract_reads():
                return explore(store,engine,query,protocol,category,verified,no_auth,limit)

        with ThreadPoolExecutor(max_workers=2,thread_name_prefix='explore-read') as executor:
            pending=[executor.submit(copy_context().run,read,protocol) for protocol in search_protocols()]
            groups=[future.result() for future in pending]
        return merge_discovery_results(groups,limit)
    finally:
        _parallel_explore.release()


def _browse(store, kind, category, no_auth, *, limit=None, registry=None):
    from ..application_store_resource_batches import resources

    from psycopg import sql

    condition = "r.active=1 AND r.health_status IN ('healthy','reachable') AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')"
    condition += " AND (%s::text IS NULL OR r.category=%s) AND (%s=0 OR COALESCE(r.auth_observed,r.auth_declared,0)=0 OR r.kind='x402')"
    args = [category, category, int(no_auth)]
    if registry == 'erc8004':
        condition += " AND (r.source='erc8004' OR COALESCE(r.details,'') LIKE '%%\"erc8004\"%%')"
    predicate = sql.SQL(condition)
    grouped = []
    endpoints = {}
    with store.tx(readonly=True):
        for protocol in [kind] if kind else ["a2a", "mcp", "x402"]:
            order_by = ("CASE WHEN r.name ILIKE '%%8004%%' THEN 0 WHEN r.description ILIKE '%%8004%%' THEN 1 WHEN r.source='erc8004' THEN 2 ELSE 3 END, r.eval_score DESC NULLS LAST, r.first_seen DESC, r.id DESC"
                        if registry == 'erc8004' else "r.first_seen DESC, r.id DESC")
            rows = store._execute(
                sql.SQL("SELECT r.id,r.url FROM resources r WHERE {} AND r.kind=%s ORDER BY " + order_by + " LIMIT 3000").format(predicate).as_string(),
                (*args, protocol),
                max_rows=3000,
            ).fetchall()
            # Apply host diversity before reading full provider contracts. A
            # prolific provider must not exhaust the whole browse window.
            host_counts = {}
            diverse = []
            for rid, url in rows:
                if not usable_endpoint(url):
                    continue
                host = urlsplit(url or "").hostname or ""
                if host_counts.get(host, 0) >= 2:
                    continue
                host_counts[host] = host_counts.get(host, 0) + 1
                diverse.append(rid)
                endpoints[rid] = (protocol, url)
                if len(diverse) == 600:
                    break
            grouped.append(diverse)
        total = store._execute(
            sql.SQL("SELECT COUNT(*) FROM resources r WHERE {} AND (%s::text IS NULL OR r.kind=%s)").format(predicate).as_string(),
            (*args, kind, kind),
        ).fetchone()[0]
        ids = [
            rid
            for group in zip(
                *[
                    g + [None] * (max(map(len, grouped), default=0) - len(g))
                    for g in grouped
                ]
            )
            for rid in group
            if rid is not None
        ][:600]
        if limit is not None:
            from .explore_search import identity
            selected, seen = [], set()
            for rid in ids:
                if len(selected) >= min(600, limit * BROWSE_TEMPLATE_READ): break
                protocol, endpoint = endpoints[rid]
                key = identity({'id': rid, 'kind': protocol, 'url': endpoint})
                if key not in seen:
                    selected.append(rid); seen.add(key)
            ids = selected
        found = {r["id"]: dict(r) for r in resources(store, ids, "active=1", (), hydrate_contracts=True)}
    listed = _collapse_templates([found[rid] for rid in ids if rid in found])
    return (listed if limit is None else listed[:limit]), total


def _in_ranked_batches(store, ranked, size=100, *, documents=True, keep=None):
    """Yield complete current rows in ranked order, reading only as far as the page needs.

    KEEP(row, capability_text) is a necessary admission condition. Once fewer than half of
    a batch's documents satisfy it, later batches read only document texts first and fetch
    complete rows for the listings that still can be admitted (0-match searches read all
    600 candidates: 1.4 s -> about 0.4 s for large MCP pages, 2026-11-04)."""
    from ..application_store_resource_batches import resources
    from ..explore_document_reader import read as read_documents, texts as read_texts
    ids = [row['id'] for row in ranked]
    order = {row['id']: row for row in ranked}
    sparse = False
    for start in range(0, len(ids), size):
        batch = ids[start:start + size]
        if documents and keep is not None and sparse:
            known = read_texts(store, batch)
            # Only a current document's own text may rule a listing out; the rest are read as before.
            batch = [rid for rid in batch if rid not in known or keep(order[rid], known[rid])]
        prepared = read_documents(store, batch) if documents else {}
        if keep is not None and prepared:
            passing = sum(bool(keep(order[rid], row['_capability_text'])) for rid, row in prepared.items())
            sparse = passing * 2 < len(prepared)
        missing = [rid for rid in batch if rid not in prepared]
        rows = resources(store, missing, "active=1 AND health_status IN ('healthy','reachable') "
                         "AND COALESCE(eval_security,'') NOT IN ('quarantine','review')", (),
                         allow_partial=True, hydrate_contracts=True)
        from ..postgres_capability_text import attach
        # Missing/stale documents keep complete-contract admission; current facts avoid schema transfer.
        loaded = {row['id']: row for row in attach(store, [dict(row) for row in rows])}
        loaded.update(prepared)
        for rid in batch:
            if rid in loaded:
                yield {**loaded[rid], **{key: order[rid][key] for key in ('rrf_score', 'dense_match', 'bm25_match') if key in order[rid]}}


@timed('cards')
def _card(store, registry, resource, verified):
    from .front import _card_report_metadata
    version = registry.current(resource, create=False)
    projection = registry.projection(resource, version=version) if version else {}
    if verified and not projection.get("connection_readiness", {}).get(
        "verified_callable"
    ):
        return None
    columns = (
        "id",
        "kind",
        "source",
        "name",
        "url",
        "description",
        "category",
        "health_status",
        "price_usdc",
        "probe_latency_ms",
        "eval_grade",
        "eval_score",
        "last_check_at",
        "first_seen",
        "trial_ok",
        "auth_method",
        "auth_autonomy",
        "cap_tool_count",
    )
    value = {key: resource.get(key) for key in columns}
    value["description"] = str(value.get("description") or "")[:400]
    value["auth_required"] = (
        resource.get("auth_observed")
        if resource.get("auth_observed") is not None
        else resource.get("auth_declared")
    )
    item = public_agent(value, resource=resource, store=None)
    if projection:
        item.update(projection)
    else:
        item["connection_readiness"] = {
            "profile_available": False,
            "verified_callable": False,
            "reason": "not_verified",
            "verified_at": None,
            "evidence_scope": "execution",
        }
        item["capability_contracts"] = []
    item.update(_card_report_metadata(store, resource))
    return item


@observed('explore')
@contract_reads
def explore(store, engine, query, kind, category, verified, no_auth, limit):
    from .content_policy import hidden_from_public_list
    from .protocols import search_protocols, merge_discovery_results, requested_protocol
    selected = requested_protocol(query, {'kind': kind})
    if selected is None:
        groups, remaining = [], limit
        for protocol in search_protocols():
            # Listings about the task come first across protocols, so a page filled by A2A
            # bundles still checks a bounded number of MCP listings that may lead with the task.
            wanted = remaining if not groups else max(remaining, min(limit, FOCUS_FILL))
            group = explore(store, engine, query, protocol, category, verified, no_auth, wanted)
            groups.append(group)
            remaining = max(0, remaining - len(group['items']))
        merged = merge_discovery_results(groups, limit)
        return merged
    kind = selected

    normalized = normalize_task(query)
    from .query_intent import explicit_name
    needle = (explicit_name(query) or str(query).strip()).casefold()
    terms = search_terms(normalized)
    core = capability_terms(normalized)
    scope_terms=list(dict.fromkeys(terms+search_terms(query)))
    registry_filter = 'erc8004' if ERC8004_QUERY.fullmatch(str(query).strip()) else None
    if registry_filter:
        terms, core, scope_terms = ['8004'], ['8004'], ['8004']
    if (not str(query).strip() or registry_filter) and getattr(store, "backend", None) == "postgresql":
        found, exact_total = _browse(store, kind, category, no_auth, limit=None if verified else limit, registry=registry_filter)
    else:
        # Rank on compact fields; full contracts are read lazily, in ranked order, below.
        found = candidates(
            store, engine, query, kind=kind, category=category, maximum=600, ranking_only=True
        )
        exact_total = None
        from .retrieval_policy import order
        # Structural scoring is shadowed until the acceptance comparison passes.
        found = order(query, found, mode=getattr(engine, 'explore_rerank_mode', 'shadow') if isinstance(getattr(engine, 'explore_rerank_mode', 'shadow'), str) else 'shadow')
        # An exact name leads every window, not only windows wide enough to reach it in hybrid order.
        exact = [row for row in found if str(row.get("name") or "").casefold() == needle]
        if exact:
            found = exact + [row for row in found if str(row.get("name") or "").casefold() != needle]
    picked = []
    admitted = []
    hosts = {}
    seen = set()
    endpoints = set()
    providers = set()
    from .task_requirements import provider_identity
    from .explore_search import identity, task_advertised
    matches = 0
    registry = Registry(store)
    verified_ids = None
    # Build all badges from one current read snapshot. Execution still checks
    # live authority independently; no transaction spans an embedding request.
    snapshot = store.tx(readonly=True) if getattr(store, "backend", None) == "postgresql" else nullcontext()
    with snapshot:
        lazy = exact_total is None and getattr(store, "backend", None) == "postgresql"
        keep = None
        if terms and not registry_filter and str(query).strip():
            from .explore_search import named_match as named_listing
            from .selection import text_may_match
            # The first two checks of task_advertised, on the document text it would read.
            keep = lambda row, text: named_listing(query, row) or text_may_match(scope_terms, {'_capability_text': text}, core)
        full = _in_ranked_batches(store, found, documents=not verified, keep=keep) if lazy else iter(found)
        if verified and getattr(store, "backend", None) == "postgresql":
            import json

            with store.tx(readonly=True):
                # The card's badge reads execution evidence; eligibility rows are cleared by every
                # health observation, so prefilter on the same evidence and let _card decide.
                rows = store._execute(
                    """SELECT DISTINCT cv.resource_id FROM capability_evidence e
                    JOIN connection_versions cv ON cv.id=e.version_id
                    WHERE e.scope='execution' AND e.outcome='succeeded' AND e.expires>%s AND cv.schema_complete=1
                    AND cv.resource_id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))""",
                    (time.time(), json.dumps([row["id"] for row in found])),
                ).fetchall()
            verified_ids = {row[0] for row in rows}
        for resource in full:
            # The page needs one listing beyond the window to know that more exist.
            if lazy and matches > limit:
                break
            if resource.get('kind') != kind:
                continue
            if resource["id"] in seen:
                continue
            seen.add(resource["id"])
            if not usable_endpoint(resource.get("url")):
                continue
            if hidden_from_public_list(resource, query):
                continue
            if str(query).strip() and not terms and not registry_filter:
                # An unrecognized query is not an empty browse request. Keep exact
                # provider-name searches, but do not fill it with unrelated agents.
                from .explore_search import named_match
                if not named_match(query,resource):continue
            if terms and not registry_filter:
                from .task_requirements import input_requirements_match,supported_discovery_connection
                if not input_requirements_match(query,resource)or not supported_discovery_connection(resource):continue
            # The skips below only read what earlier listings admitted, so they run before the
            # costly task check: a listing they drop would be dropped after it as well.
            endpoint = identity(resource)
            if endpoint in endpoints:
                continue
            # One listing per named provider: sibling hosts of the same agent repeat a card.
            provider = provider_identity(resource)
            if provider is not None and provider in providers:
                continue
            if (
                no_auth
                and resource["kind"] != "x402"
                and bool(
                    resource.get("auth_observed")
                    if resource.get("auth_observed") is not None
                    else resource.get("auth_declared")
                )
            ):
                continue
            if verified_ids is not None and resource["id"] not in verified_ids:
                continue
            host = urlsplit(resource.get("url") or "").hostname or ""
            if hosts.get(host, 0) >= 2:
                continue
            if terms and not registry_filter and not task_advertised(query, resource, terms=scope_terms, core=core):
                continue
            endpoints.add(endpoint)
            if provider is not None:
                providers.add(provider)
            hosts[host] = hosts.get(host, 0) + 1
            matches += 1
            if verified:
                if len(picked) < limit:
                    item = _card(store, registry, resource, verified)
                    if item is not None:
                        picked.append(item)
                continue
            if len(admitted) < limit:
                admitted.append(resource)
        # Only final card subjects need their complete current contracts. A search
        # document is never passed to execution or used as a callable contract.
        from ..application_store_resource_batches import resources
        compact_ids = [row['id'] for row in admitted if '_explore_document' in row]
        complete = {row['id']: dict(row) for row in resources(store, compact_ids,
            "active=1 AND health_status IN ('healthy','reachable') AND COALESCE(eval_security,'') NOT IN ('quarantine','review')",
            (), allow_partial=True, hydrate_contracts=True)} if compact_ids else {}
        for row in admitted:
            resource = complete.get(row['id']) if '_explore_document' in row else row
            if resource is None or hidden_from_public_list(resource, query):
                continue
            item = _card(store, registry, resource, verified)
            if item is not None:
                picked.append(item)
    # Exact names stay first, then listings that name the task in their own name or
    # description before ones matched only through tool text; the hybrid order is kept within.
    from .selection import _term_in, _tool_purpose
    from ..gateway.classify import classify
    import math
    query_cat = classify(str(query).strip()) if str(query).strip() else "other"
    words = core or terms
    # "exchange rate" needs both words, as relevance admission does; one shared word is not the task.
    need = 0 if not words else min(len(words), 2) if len(words) <= 3 else math.ceil(len(words) * .75)
    def names(text):
        return bool(words) and sum(_term_in(word, text.lower()) for word in words) >= need
    def rank(row):
        name = str(row.get("name") or "")
        if name.casefold() == needle:
            return 0
        description = str(row.get("description") or "")
        cat = str(row.get("category") or "")
        cat_match = (cat == query_cat) if query_cat != "other" else True
        if names(name):
            return 1 if cat_match else 2
        # A listing that leads with the task is about it; a later mention is a side feature.
        if names(name + " " + _tool_purpose(description)):
            return 3 if cat_match else 4
        if names(name + " " + description):
            return 5 if cat_match else 6
        return 7
    # A place in the request ranks listings that state coverage of it before ones that do not.
    from .selection import place_fit
    placed = {id(row): place_fit(scope_terms, row) for row in picked} if scope_terms else {}
    picked.sort(key=lambda row: (rank(row), not placed.get(id(row), True)))
    for row in picked:
        # 'listing': the name or leading sentence names the task; 'mention': a later or tool-only match.
        row['match_basis'] = 'listing' if not words or rank(row) <= 4 else 'mention'
    return {
        "query": str(query).strip()[:500],
        "terms": terms,
        "total": exact_total if exact_total is not None and not verified else matches,
        "total_is_estimate": exact_total is None or bool(verified),
        "items": picked,
        "verified": bool(verified),
        "captured_at": time.time(),
        # Every candidate was examined without reaching the window: a wider window
        # (a later page) would admit exactly these listings again.
        "complete": lazy and matches <= limit,
    }

"""Bounded hybrid discovery over current public catalog data.

Query vectors are optional ranking evidence. Current source/model fences,
capability checks, protocol filters and verification rules remain authoritative.
"""

from contextlib import contextmanager
from itertools import zip_longest
import re

from ..legacy_vector_index import validate_vector
from .query_intent import interpret, explicit_name
from .retrieval_metrics import stage, count

MAX_CANDIDATES = 600
LEXICAL_FORMS = {'translation': ('translation','translate','translator'),
                 'convert': ('convert','conversion','converter'),
                 'unit': ('unit','units'), 'units': ('units','unit'),
                 'paper': ('paper','papers'), 'papers': ('papers','paper'),
                 'forecast': ('forecast','forecasts')}


def lexical_match(words, joiner):
    """Bounded inflection recall for the simple-token index; values stay parameterized."""
    from itertools import islice, product
    quote = lambda word: '"' + word.replace('"', '') + '"'
    if joiner == ' OR ':
        return ' OR '.join(quote(form) for word in words for form in LEXICAL_FORMS.get(word,(word,)))
    return ' OR '.join(' '.join(map(quote, combination)) for combination in
                       islice(product(*(LEXICAL_FORMS.get(word,(word,)) for word in words)),16))
# Coverage ranking reads tool names/descriptions; compact usage_tools carries the same ones.
RANKING_COLUMNS = ('kind', 'name', 'description', 'eval_score', 'usage_guide', 'usage_tools')


def ranking_text(resource):
    """Name, description and up to 32 advertised tools: the text candidate coverage reads."""
    from .selection import _advertised_tools
    tool_text = " ".join(str(t.get("name") or "") + " " + str(t.get("description") or "")[:700]
                         for t in _advertised_tools(resource)[:32])
    return str(resource.get("name", "")) + " " + str(resource.get("description", "")) + " " + tool_text


def normalize_task(task):
    from .chat_task_spec import canonical_text
    text = interpret(canonical_text(task)).positive
    if re.search(r'\bsql\b',text,re.I)and re.search(r'\b(?:run|execut)\w*\b',text,re.I):
        return 'sql query for '+text
    if re.search(r'\bsummari[sz]\w*\b',text,re.I)and re.search(r'\bmeeting\s+(?:notes|minutes|transcripts?)\b',text,re.I):
        return 'meeting notes for '+text
    # These phrases name equivalent capabilities, not hypothetical answers.
    if re.search(
        r"\b(?:transcrib\w*|transcript\w*|speech.to.text)\b|\b(?:spoken|podcast|audio|recording|interview)\b.*\b(?:text|transcript\w*)\b",
        text,
        re.I,
    ):
        return "audio transcription" + (
            " timestamps" if re.search(r"timestamp|time.coded", text, re.I) else ""
        )
    if re.search(r"\btranslat\w*\b", text, re.I):
        return "translation for " + text
    # "summarize a pdf research paper" asks for a summarizer; the paper is its input, not a search (rv2, 11-04).
    if (re.search(r'\bsummar(?:i[sz]\w*|y|ies)\b', text, re.I)
            and re.search(r'\b(?:pdfs?|papers?|documents?|files?|reports?)\b', text, re.I)):
        return "document summarization for " + text
    # "check the status of a website": an uptime check, not an order or shipment status (rv10, 11-04).
    if (re.search(r'\b(?:status|uptime|up or down|is (?:it )?(?:up|down|online))\b.{0,30}\b(?:websites?|sites?|urls?|domains?|web pages?)\b'
                 r'|\b(?:websites?|sites?|urls?|domains?)\b.{0,30}\b(?:status|uptime|up or down|is (?:up|down|online))\b', text, re.I)
            and not re.search(r'\b(?:orders?|shipments?|packages?|parcels?|deliver\w*|flights?|payments?|tickets?)\b', text, re.I)):
        return "website uptime monitoring for " + text
    if re.search(r"\b(?:documentation|docs|API reference)\b", text, re.I):
        return "documentation for " + text
    if re.search(
        r"\b(?:academic|scholarly|research)\b.*\b(?:papers?|articles?)\b"
        r"|\b(?:find|search|look\s+(?:up|for)|discover)\w*\b.{0,40}\b(?:papers?|scholarly articles?|journal articles?)\b",
        text,
        re.I,
    ):
        return "academic paper search for " + text
    if re.search(
        r"\b(?:review\w*|audit\w*)\b.*\b(?:pull requests?|PRs?)\b", text, re.I
    ):
        return "code review for " + text
    if re.search(r"\bgithub\b.*\b(?:issues?|prs?|pull requests?)\b|\b(?:issues?|prs?|pull requests?)\b.*\bgithub\b", text, re.I):
        return "github issues for " + text
    return text


@contextmanager
def discovery_store(source):
    pool = getattr(source, "_admin_read_pool", None)
    if getattr(source, "backend", None) == "postgresql" and pool is not None:
        # The vector index owns its own read snapshot; do not nest it in reader().
        with pool.lease_store() as store:
            store._quality_owner = source
            yield store
    else:
        yield source


def enabled(engine):
    return engine is not None and getattr(engine, "embeddings_enabled", False) is True


def candidates(
    store, engine, query, *, kind=None, category=None, maximum=MAX_CANDIDATES, retrieval_hint=None,
    ranking_only=False
):
    """RANKING_ONLY returns ranked ids with the compact fields used for ranking, without full contracts."""
    if kind not in (None, "a2a", "mcp", "x402") or not 1 <= maximum <= MAX_CANDIDATES:
        return []
    if retrieval_hint is not None and (type(retrieval_hint) is not str or len(retrieval_hint) > 500
            or any(ord(c) < 32 for c in retrieval_hint)):
        return []
    from .selection import search_terms, capability_terms, _term_in

    intent = interpret(query)
    normalized = normalize_task(intent.positive)
    retrieval = intent.retrieval_text(normalized)
    terms = list(dict.fromkeys(search_terms(retrieval) + search_terms(retrieval_hint or '')))[:12]
    core = capability_terms(normalized) or capability_terms(retrieval_hint or '')
    if not terms and not enabled(engine):
        return []
    descriptor = engine.model_descriptor() if enabled(engine) else None
    vector = None
    if getattr(store, "backend", None) != "postgresql" or getattr(store, '_native_lexical', True) is False:
        if engine is None:
            return []
        # Existing SQLite fixtures keep the same fenced hybrid implementation.
        with stage('embedding'):
            vector = engine.discovery_embedding(intent.positive) if enabled(engine) else None
        def current_details(read_db, ranked):
            result = []
            for row in ranked:
                stored = read_db.execute('SELECT * FROM resources WHERE id=?', (row['id'],)).fetchone()
                detail = dict(stored) if stored else {}
                if (not detail.get('active') or detail.get('health_status') not in ('healthy','reachable')
                        or detail.get('eval_security') in ('quarantine','review')):
                    continue
                result.append({**detail, **{key:row[key] for key in ('rrf_score','dense_match','bm25_match')}})
            return result
        result = engine.hybrid_search(
            store._db,
            ' '.join(terms),
            limit=min(50, maximum),
            kind=kind,
            category=category,
            query_embedding=vector,
            query_descriptor=descriptor,
            _store_filter=current_details,
        )
        count('returned_candidates', len(result))
        return result
    from ..application_store_resource_batches import resources
    from ..postgres_ann import vector_literal
    from ..postgres_lexical import QUERY
    from psycopg import sql

    lexical = []
    dense = []
    all_resources = {}
    # Exact lookup still needs current schema/readiness; no result cache bypasses
    # revocation, health or the caller's later relevance and verification gates.
    name = explicit_name(query)
    if name:
        with stage('exact'), store.tx(readonly=True):
            # Look the name up through resources_admin_name; a quoted FTS phrase
            # rechecked every candidate document and took seconds per protocol.
            exact_rows = store._execute(
                """SELECT r.id FROM public.resources r
                WHERE r.active=1 AND translate(r.name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') COLLATE "C"
                   =translate(%s,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') COLLATE "C"
                 AND LOWER(r.name)=LOWER(%s)
                 AND r.health_status IN ('healthy','reachable')
                 AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')
                 AND (%s::text IS NULL OR r.kind=%s) AND (%s::text IS NULL OR r.category=%s)
                ORDER BY r.last_ok_at DESC NULLS LAST,r.id DESC LIMIT 50""",
                (name, name, kind, kind, category, category),
            ).fetchall()
            found = resources(store, [r[0] for r in exact_rows], "active=1", ())
            exact = [dict(r) for r in found]
            exact = [r for r in exact if str(r.get('name') or '').casefold() == name.casefold()]
            from ..capability_registry import Registry
            from .task_requirements import input_requirements_match, supported_discovery_connection
            from .recommendation_security import usable_endpoint
            registry = Registry(store)
            exact = [r for r in exact if usable_endpoint(r.get('url')) and input_requirements_match(query, r) and supported_discovery_connection(r)
                     and (version := registry.current(r, create=False))
                     and registry.projection(r, version=version).get('connection_readiness', {}).get('verified_callable')]
        if exact:
            count('exact_shortcuts', 1)
            count('returned_candidates', min(maximum, len(exact)))
            return [{**r, 'rrf_score': 1 / 61, 'dense_match': False, 'bm25_match': True}
                    for r in exact[:maximum]]
    # Prefer all capability words; the bounded disjunction supplies recall when
    # exact wording differs. GIN performs membership, avoiding corpus-wide ranks.
    from .opensearch_lexical import lexical_ids
    with stage('lexical'), store.tx(readonly=True):
        seen_matches = set()
        for words, joiner in [(core, " "), (terms, " OR ")]:
            if not words or (joiner == " OR " and len(lexical) >= 60):
                continue
            match = lexical_match(words, joiner)
            if match in seen_matches:
                continue
            seen_matches.add(match)
            # The predicate below matches the partial index resources_search_lookup
            # (admin_query_indexes.SEARCH_INDEXES); change both together.
            # Match through the GIN index first: for common words the planner otherwise walks
            # every listing in recency order and rebuilds its text vector (measured 283 ms vs 62 ms).
            def postgres(match=match):
                return [row[0] for row in store._execute(
                    sql.SQL("""{}, hits AS MATERIALIZED (SELECT f.rowid FROM public.resources_fts f CROSS JOIN ac_query q
                    WHERE agentcon_search.lexical_document(f.name,f.description) @@ q.terms)
                    SELECT r.id FROM hits h JOIN public.resources r ON r.id=h.rowid
                    WHERE r.active=1 AND r.health_status IN ('healthy','reachable')
                     AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')
                     AND (%s::text IS NULL OR r.kind=%s) AND (%s::text IS NULL OR r.category=%s)
                    ORDER BY r.last_ok_at DESC NULLS LAST,r.id DESC LIMIT 300""").format(sql.SQL(QUERY)).as_string(),
                    (match, kind, kind, category, category),
                ).fetchall()]
            # OpenSearch (when configured) cuts the same matches by relevance instead of recency.
            lexical.extend(lexical_ids(words, joiner, kind, category, postgres))
        lexical = list(dict.fromkeys(lexical))[:500]
    count('lexical_candidates', len(lexical))
    with stage('embedding'):
        vector = engine.discovery_embedding(intent.positive) if enabled(engine) else None
    index = store._vector_index
    if vector is not None and index and index.ann_enabled:
        blob = validate_vector(vector, descriptor)[0]
        with stage('ann'), index.read_snapshot():
            from ..postgres_ann import configure_scan
            configure_scan(store, filtered=kind is not None or category is not None)
            found = store._execute(
                """SELECT e.resource_id FROM agentcon_search.embeddings e
                JOIN public.resources r ON r.id=e.resource_id
                WHERE e.descriptor_hash=%s AND r.active=1 AND r.health_status IN ('healthy','reachable')
                 AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')
                 AND (%s::text IS NULL OR r.kind=%s) AND (%s::text IS NULL OR r.category=%s)
                ORDER BY e.embedding <=> %s::public.vector LIMIT 100""",
                (
                    descriptor.digest,
                    kind,
                    kind,
                    category,
                    category,
                    vector_literal(blob),
                ),
            ).fetchall()
            ids = [row[0] for row in found]
            current = index.current_ids(ids, descriptor)
            dense = [rid for rid in ids if rid in current]
    count('dense_candidates', len(dense))
    # Index-time generated requests add recall only; every candidate still passes the
    # same projection, relevance and verification gates on the provider's own text.
    from .query_expansion import index as expansion_index
    with stage('expansion'):
        expanded = expansion_index().match(core or terms, kind=kind, limit=100)
    count('expansion_candidates', len(expanded))
    # Preserve every retrieval stream when the full-contract byte budget fills.
    ids = list(dict.fromkeys(rid for group in zip_longest(lexical, dense, expanded)
                             for rid in group if rid is not None))[:MAX_CANDIDATES]
    with stage('projection'), store.tx(readonly=True):
        compact = {}
        if ranking_only:
            # Stored ranking texts spare transferring and parsing tool JSON for every candidate.
            from ..postgres_capability_text import ranking_rows
            compact = ranking_rows(store, ids)
        count('compact_ranking_rows', len(compact))
        all_resources = dict(compact)
        all_resources.update({
            r["id"]: dict(r)
            for r in resources(
                store,
                [rid for rid in ids if rid not in compact],
                "active=1 AND health_status IN ('healthy','reachable') AND COALESCE(eval_security,'') NOT IN ('quarantine','review')",
                (), allow_partial=True,
                **({'columns': RANKING_COLUMNS} if ranking_only else {'hydrate_contracts': True}),
            )
        })

    count('projection_candidates_omitted', len(ids) - len(all_resources))

    def coverage(rid):
        r = all_resources[rid]
        text = r.get("_rank_text")
        if not isinstance(text, str):
            text = ranking_text(r)
        return sum(_term_in(word, text) for word in (core or terms)) / max(
            1, len(core or terms)
        )

    lexical = sorted(
        (rid for rid in lexical if rid in all_resources),
        key=lambda rid: (
            -coverage(rid),
            -float(all_resources[rid].get("eval_score") or 0),
            rid,
        ),
    )
    ranks = {rid: [i + 1, None, None] for i, rid in enumerate(lexical)}
    for i, rid in enumerate(dense):
        ranks.setdefault(rid, [None, None, None])[1] = i + 1
    for i, rid in enumerate(expanded):
        ranks.setdefault(rid, [None, None, None])[2] = i + 1

    def score(rid):
        return sum(1 / (60 + rank) for rank in ranks[rid] if rank)

    ordered = sorted(
        (rid for rid in ranks if rid in all_resources),
        key=lambda rid: (-score(rid), rid),
    )
    if descriptor is not None and engine.model_descriptor().digest != descriptor.digest:
        ordered = lexical
    if ranking_only and kind == "mcp" and core and len(ordered) > 40:
        from .selection import _service_focus
        bake_ok = bool({'baking', 'cooking', 'recipe', 'kitchen', 'flour'}.intersection(terms))
        bible_ok = bool({'bible', 'scripture', 'biblical', 'theology', 'thai'}.intersection(terms))
        def off_domain(rid):
            r = all_resources[rid]
            txt = (str(r.get('name') or '') + ' ' + str(r.get('description') or '')).lower()
            if not bake_ok and 'unit' in core and re.search(r'\b(?:baking|recipes?|kitchen|cooking|flour|gold price)\b', txt):
                return True
            if not bible_ok and any(w in ('translate', 'translation') for w in core) and re.search(r'\b(?:bible|scriptures?|quran|torah)\b', txt):
                return True
            return False
        def is_focused(rid):
            if off_domain(rid):
                return False
            return _service_focus(core, all_resources[rid], terms)
        foc = [rid for rid in ordered if is_focused(rid)]
        if len(foc) >= 5:
            foc_set = set(foc)
            ordered = foc + [rid for rid in ordered if rid not in foc_set and not off_domain(rid)][:20]
    count('returned_candidates', min(maximum, len(ordered)))
    return [
        {
            **all_resources[rid],
            "rrf_score": score(rid),
            "dense_match": ranks[rid][1] is not None,
            "bm25_match": ranks[rid][0] is not None,
        }
        for rid in ordered[:maximum]
    ]

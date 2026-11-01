"""Bounded structural reranking for Explore; never changes Chat evidence order."""
import time

from .capability_retrieval import ProjectionCache, word_present
from .query_intent import interpret, explicit_name
from .retrieval_metrics import count, stage

_facts = ProjectionCache()
MAX_RERANK = 40


def order(query, resources, *, mode='shadow', maximum=MAX_RERANK, budget_ms=30):
    if mode not in ('off', 'shadow', 'on') or type(maximum) is not int or not 1 <= maximum <= MAX_RERANK:
        raise ValueError('Invalid retrieval policy.')
    original = list(resources)
    if mode == 'off' or len(original) < 2 or explicit_name(query): return original
    # Compact ranking rows carry no tool data; scoring them would only record noise.
    if any('_rank_text' in r for r in original[:maximum]):
        count('rerank_skipped_compact', 1)
        return original
    from .selection import search_terms, capability_terms
    from .discovery import normalize_task
    normalized = normalize_task(query)
    terms = tuple(dict.fromkeys(search_terms(interpret(query).positive)))
    core = tuple(capability_terms(normalized))
    if not terms: return original
    scored = []; hits = 0; started = time.perf_counter()
    with stage('rerank'):
        for index, resource in enumerate(original[:maximum]):
            if (time.perf_counter()-started)*1000 > budget_ms:
                count('rerank_budget_exhausted', 1)
                count('projection_cache_hits', hits)
                count('reranked_candidates', len(scored))
                return original
            facts, hit = _facts.project(resource); hits += int(hit)
            # One real tool must cover the capability; never merge unrelated tools
            # into an imaginary skill. Metadata remains advisory, not proof.
            coherent = [t for t in facts.tools if all(word_present(w, t.text) for w in core)]
            tool_score = max((sum(word_present(w, t.text) for w in terms) / len(terms) for t in coherent), default=0)
            primary = sum(word_present(w, facts.text) for w in terms) / len(terms)
            score = 2 * tool_score + primary
            scored.append((-score, index, resource))
    ranked = [r for _, _, r in sorted(scored, key=lambda row: row[:2])] + original[maximum:]
    count('projection_cache_hits', hits)
    count('reranked_candidates', len(scored))
    count('rerank_order_changed', int([r['id'] for r in ranked] != [r['id'] for r in original]))
    return ranked if mode == 'on' else original

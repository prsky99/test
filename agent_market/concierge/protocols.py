"""Explicit protocol preferences are filters, never quality-ranking signals."""
import re

PROTOCOLS = frozenset(('a2a', 'mcp', 'x402'))
DEFAULT_PROTOCOL = 'a2a'
TOPIC_PROTOCOL = re.compile(r'\b(?:about|regarding|concerning|explain|explaining|learn(?:ing)?\s+about)\s+(?:the\s+)?(a2a|mcp|x402)\b')


def requested_protocol(text, data=None, default=None):
    data = data or {}
    value = data.get('protocol', data.get('kind'))
    if value is not None:
        if not isinstance(value,str):
            raise ValueError('Choose A2A, MCP, x402, or Any protocol.')
        value=value.strip().lower()
        if value=='any':
            return None
        if value not in ('','auto'):
            if value not in PROTOCOLS:
                raise ValueError('Choose A2A, MCP, x402, or Any protocol.')
            return value
    text=str(text).lower()
    excluded=set(re.findall(r'\b(?:not|no|without|except|excluding|instead of|non-)\s*(?:an?\s+)?(a2a|mcp|x402)\b',text))
    # "repositories about MCP servers" names the subject; only a protocol named
    # outside such a topic phrase selects it (x402 is never enabled by a topic).
    every = re.findall(r'\b(a2a|mcp|x402)\b', text)
    topical = re.findall(TOPIC_PROTOCOL, text)
    mentioned = {name for name in every if every.count(name) > topical.count(name)} - excluded
    if excluded and not mentioned:
        raise ValueError('Choose A2A, MCP, x402, or Any protocol.')
    if len(mentioned)>1:
        raise ValueError('Choose A2A, MCP, x402, or Any protocol.')
    return next(iter(mentioned)) if len(mentioned) == 1 else default


def search_protocols(selection=None):
    """Automatic and Any discovery never opt a caller into x402."""
    if selection in (None, '', 'auto', 'any'):
        return ('a2a', 'mcp')
    return (selection,) if selection in PROTOCOLS else ()


def merge_discovery_results(groups, limit):
    """Preserve admission checks; relevance precedes protocol across scoped searches."""
    result = dict(groups[0])
    items = [item for group in groups for item in group['items']]
    query = str(result.get('query') or '').strip()
    if query:
        # Task-led names and leading descriptions outrank incidental tool matches
        # across protocols. Stable ties preserve each scoped search's evidence order.
        from .discovery import normalize_task
        from .selection import capability_terms, search_terms, _term_in, _tool_purpose
        from .query_intent import explicit_name
        words = capability_terms(normalize_task(query)) or search_terms(query)
        needle = (explicit_name(query) or query).casefold()
        def focus(item):
            name = str(item.get('name') or '')
            description = str(item.get('description') or '')
            if name.casefold() == needle:return 0
            def covers(text):return bool(words) and all(_term_in(word,text.casefold()) for word in words)
            if covers(name):return 1
            if covers(name+' '+_tool_purpose(description)):return 2
            return 3
        # Within a tier, a listing whose name or leading sentence states the task stays ahead of
        # one that only mentions it in a tool (match_basis set by the scoped search).
        items.sort(key=lambda item: (focus(item), item.get('match_basis') == 'mention'))
    result['complete'] = all(group.get('complete') is True for group in groups) and len(items) <= limit
    result['items'] = items[:limit]
    result['total'] = sum(group.get('total', 0) for group in groups)
    result['total_is_estimate'] = any(group.get('total_is_estimate', False) for group in groups)
    if any('candidate_window_limited' in group for group in groups):
        result['candidate_window_limited'] = any(group.get('candidate_window_limited',False) for group in groups)
    for field in ('matched_report_count','historical_agent_count'):
        if any(field in group for group in groups):
            counts=[group.get(field)for group in groups]
            result[field]=sum(counts)if all(type(count)is int and count>=0 for count in counts)else None
    result['protocol_policy'] = 'a2a_then_mcp_explicit_x402'
    return result

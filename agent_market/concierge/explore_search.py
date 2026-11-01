"""Bounded public search assistance and task admission; never invokes providers."""
import difflib
import re

from .report_evidence import canonical_endpoint
from .discovery_contracts import task_facts
from .retrieval_metrics import timed

WORDS = ('weather', 'github', 'translation', 'translate', 'news', 'documentation', 'finance',
         'security', 'database', 'research', 'email', 'maps', 'travel', 'image', 'search',
         'summarize', 'calendar', 'payments', 'crypto', 'stocks', 'video', 'music', 'flight',
         'hotel', 'pdf', 'papers', 'forecast', 'climate', 'invoice', 'legal', 'issue', 'issues',
         'pull', 'request', 'requests', 'sender', 'send', 'text', 'scrape', 'scraper', 'website',
         'currency', 'exchange', 'rate', 'market', 'stock', 'quote', 'code', 'review', 'monitor',
         'speech', 'audio', 'transcribe', 'transcription', 'generate', 'generator', 'convert',
         'converter', 'summary', 'document', 'documents', 'agent', 'agents', 'data', 'files',
         'translator', 'repository', 'calculator', 'analytics', 'sentiment', 'blockchain', 'wallet')
WORD_SET = frozenset(WORDS)
# Words that carry no task on their own; a query of only these (or only symbols) is not searched.
STOPWORDS = frozenset('a an and the of or to in on for with by at from is are be it this that'.split())
BROWSE_WORDS = frozenset('data api apis agent agents tool tools server servers mcp a2a x402'.split())


def browse_query(query):
    """Generic directory words and empty language are catalog browsing, not a task."""
    words = {word.casefold() for word in re.findall(r'[^\W_]+', str(query or ''))} - STOPWORDS
    return bool(str(query or '').strip()) and (not words or words <= BROWSE_WORDS)


def searchable(query):
    """A query needs at least one letter or digit outside stopwords to be searched."""
    words = re.findall(r'[^\W_]+', str(query or ''))
    return any(word.casefold() not in STOPWORDS for word in words)
MISSPELLINGS = {
    'wether': 'weather', 'waether': 'weather', 'weathr': 'weather',
    'forecst': 'forecast', 'forcast': 'forecast', 'forcasst': 'forecast',
    'gihtub': 'github', 'githb': 'github',
    'traslate': 'translate', 'translte': 'translate', 'translat': 'translate', 'translatr': 'translator',
    'isues': 'issues', 'issu': 'issue', 'isue': 'issue',
    'pyments': 'payments', 'pymnt': 'payments',
    'documntation': 'documentation', 'documnt': 'document',
}
LANGUAGE_ALIASES = {
    'clima': 'weather', 'tiempo': 'weather', 'meteo': 'weather',
    'traduccion': 'translation', 'traduction': 'translation', 'traducao': 'translation',
}
ALIASES = {**MISSPELLINGS, **LANGUAGE_ALIASES}


def correct_word(word, aliases=True):
    """A known capability word for a likely misspelling; other words are returned unchanged.

    The first letter must match and the spelling must be close, so real words such as
    "tissue" or "analysis" are not read as "issue" or "analytics"."""
    if word in MISSPELLINGS:
        return MISSPELLINGS[word]
    if aliases and word in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[word]
    if word in {'analysis','analyses','tissue','sample'} or word in WORD_SET or word in STOPWORDS or len(word) < 4 or not word.isalpha():
        return word
    # Inflections of a known word (forecasts, translators, searching) are spelled correctly.
    if any(word.startswith(known) for known in WORD_SET if len(known) >= 4):
        return word
    close = [value for value in difflib.get_close_matches(word, WORDS, n=3, cutoff=0.75) if value[0] == word[0]]
    return close[0] if close else word


def corrected_task(text):
    """The task with likely capability misspellings fixed, or None when nothing changed."""
    parts = re.split(r'(\W+)', str(text or ''))
    # Foreign aliases are already understood by search; only misspellings are fixed here.
    # Only curated misspellings may rewrite a complete natural-language task.
    # Fuzzy guesses remain explicit suggestions; they must not turn current into currency.
    changed = [MISSPELLINGS.get(part.lower(),part) if part.isalpha() and part.isascii() else part for part in parts]
    fixed = [new if new != part.lower() else part for part, new in zip(parts, changed)]
    value = ''.join(fixed)
    return value if value != str(text or '') else None


def suggestions(query):
    """Offer explicit alternatives, never silently replace a name or protocol."""
    text = str(query or '').strip()
    match = re.fullmatch(r'(?:(a2a|mcp|x402)\s+)?([a-z]{2,24}(?:\s+[a-z]{2,24}){0,3})', text, re.I)
    if not match:
        return []
    protocol, phrase = match.groups()
    words = phrase.lower().split()
    corrected = [correct_word(word) for word in words]
    if corrected == words:
        return []
    return [((protocol.upper() if protocol.lower() != 'x402' else 'x402') + ' ' if protocol else '') + ' '.join(corrected)]


def identity(resource):
    endpoint = canonical_endpoint(resource.get('url'))
    return (resource.get('kind'), endpoint) if endpoint else ('resource', resource.get('id'))


def named_match(query, resource):
    from .query_intent import explicit_name
    named = explicit_name(query)
    name = str(resource.get('name') or '').casefold()
    needle = (named or str(query).strip()).casefold()
    return name == needle or bool(named and name.startswith(needle + ' '))


@task_facts
@timed('admission')
def task_advertised(query, resource, *, terms=None, core=None):
    """A task search requires one advertised capability, not marketing prose alone."""
    from .discovery import normalize_task
    from .selection import (search_terms, capability_terms, _advertised_tools, _task_tools,
                            _coherent_capability, _bound_elsewhere, _real_tool, task_scope_matches)
    from .execution_policy import discovery_schema_supported
    if not resource:
        return False
    if named_match(query, resource):
        return True
    if terms is None or core is None:
        normalized = normalize_task(query)
        terms = list(dict.fromkeys(search_terms(normalized) + search_terms(query)))
        core = capability_terms(normalized)
    if not terms:
        return True
    from .selection import text_may_match
    if not text_may_match(terms, resource, core):
        return False
    support = resource.get('_tool_support')
    if resource.get('kind') == 'mcp' and isinstance(support,dict) and support and all(value is False for value in support.values()):
        # Bound to the exact current source by attach(); no supported tool can pass below.
        return False
    tools = _advertised_tools(resource)
    if not task_scope_matches(terms, resource, core, tools=tools):
        return False
    directory = set(core).intersection({'discovery', 'marketplace', 'directory', 'catalog', 'routing'})
    if not directory:
        tools = _task_tools(tools, core)
    scoped = {**resource, 'name': '', 'description': ''}
    for tool in tools:
        if not _real_tool(tool):
            continue
        if resource.get('kind') == 'mcp':
            # Support stored for this exact source (see postgres_capability_text) skips schema validation.
            known = resource.get('_tool_support')
            supported = known.get(tool.get('name')) if isinstance(known, dict) else None
            if not (supported if isinstance(supported, bool) else discovery_schema_supported(tool)):
                continue
        if _coherent_capability(core or terms, scoped, [tool]) and not _bound_elsewhere(core, terms, tool):
            return True
    return False


def page(result, offset, limit):
    """Return only the requested payload page; preserve the server's scope facts."""
    items = result.get('items', [])
    selected = items[offset:offset + limit]
    more = len(items) > offset + limit and offset + limit < 300
    return {**result, 'items': selected, 'offset': offset, 'limit': limit,
            'has_more': more, 'next_offset': offset + limit if more else None,
            'next_cursor': 'o' + str(offset + limit) if more else None,
            # A likely misspelling gets one explicit correction even when loose matches exist.
            'suggestions': suggestions(result.get('query')) if not offset else []}

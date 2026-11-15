"""First-party technical documentation search over MDN Web Docs.

Context7 is no longer called (PM 11-15 17:02): its Addendum (section 2) licenses output for internal development,
educational and evaluation use only. The tool definition (description and output enum) is unchanged until the
registration is refreshed (activation.install); every query goes to MDN, whose prose is CC BY-SA 2.5.

Kept apart from catalog.py/engine.py/dispatch.py on purpose: those files are part of the
reviewed research and news adapter digest, and editing them would invalidate every saved
workflow that pins Research Papers or Technology News. This module has its own digest.
"""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import logging
import re
import threading
import time

from ..concierge.execution_policy import validate_arguments
from ..concierge.http_security import bounded_client, outbound_operation
from .catalog import array, obj, text
from .engine import DataUnavailable, clean, public_link, strict_json

ID = 'technical-docs'
KEY = 'agentconcierge-owned:' + ID
SPEC = {
    'name': 'Technical Documentation', 'tool': 'search_technical_docs',
    'description': ('Search current technical documentation pages: MDN Web Docs for web platform topics '
                    '(HTML, CSS, JavaScript, Web APIs) and Context7-indexed library and product documentation '
                    'for everything else.'),
    # Every answer names the license with the source (CC BY-SA 2.5 attribution: Mozilla Contributors, and each item
    # links to its page); the license address is in source_terms.LICENSES.
    'source_name': 'MDN Web Docs by Mozilla Contributors, CC BY-SA 2.5', 'source_url': 'https://developer.mozilla.org/',
    # Documentation changes slowly.
    'ttl': 86400, 'max_stale': 604800,
    'category': 'dev_tools',
    'input': obj({'query': {'type': 'string', 'minLength': 2, 'maxLength': 160},
                  'limit': {'type': 'integer', 'minimum': 1, 'maximum': 5}}),
    'data': obj({'query': text(160), 'source': {'enum': ['MDN Web Docs', 'Context7']},
                 'items': array(obj({'title': text(), 'url': text(2000), 'summary': text(), 'library': text(200),
                                     'indexed_at': text(40)})),
                 'partial': {'type': 'boolean'}}),
    'example': {'query': 'AbortController fetch', 'limit': 3}}

WEB = re.compile(r'\b(?:html|css|javascript|js|dom|web ?apis?|fetch|xmlhttprequest|websockets?|service ?workers?|'
                 r'web ?assembly|wasm|svg|canvas|webgl|webgpu|indexeddb|local ?storage|cors|mdn|aria|'
                 r'abortcontroller|promise|async ?function|event ?listener|http headers?|content-security-policy)\b', re.I)
UNSAFE = re.compile(r'https?://|<[^>]*>|\b(?:Bearer|Basic)\s|\b(?:api[_-]?key|token|password)\s*[:=]|'
                    r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|/(?:Users|home)/', re.I)
log = logging.getLogger(__name__)


def tool_spec():
    envelope = obj({'agent': {'const': ID},
        'source': obj({'name': text(100), 'url': text(2000)}),
        'retrieved_at': text(40),
        'cache': obj({'status': {'enum': ['live', 'fresh_cache', 'stale_cache']},
                      'age_seconds': {'type': 'integer', 'minimum': 0}}),
        'data': SPEC['data']})
    return deepcopy({'name': SPEC['tool'], 'description': SPEC['description'],
        'inputSchema': SPEC['input'], 'outputSchema': envelope,
        'annotations': {'readOnlyHint': True, 'destructiveHint': False,
                        'idempotentHint': True, 'openWorldHint': True}})


class DocsAgent:
    def __init__(self, *, http=None, clock=time.monotonic, utc_now=None):
        self.http, self.clock = http, clock
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.entries, self.failed_until = OrderedDict(), OrderedDict()
        self.lock = threading.Lock()

    def execute(self, arguments):
        spec = tool_spec()
        validate_arguments(spec, arguments)
        query = ' '.join(arguments['query'].split())
        if any(ord(c) < 32 for c in arguments['query']) or UNSAFE.search(query):
            raise ValueError('Use public search keywords.')
        key = (query.casefold(), arguments['limit'])
        with outbound_operation(6) as budget:
            with self.lock:
                entry = self.entries.get(key)
                cooling = self.failed_until.get(key, 0) > self.clock()
            age = self.clock() - entry[1] if entry else None
            if entry and age <= SPEC['ttl']:
                return self._cached(entry, age, 'fresh_cache')
            if cooling:
                return self._stale_or_fail(entry, age)
            try:
                with outbound_operation(min(5.5, budget.remaining())):
                    data = self._mdn(query, arguments['limit'])
                from .english import normalize
                data = normalize(data, None)
                output = {'agent': ID, 'source': {'name': SPEC['source_name'], 'url': SPEC['source_url']},
                          'retrieved_at': self.utc_now().isoformat().replace('+00:00', 'Z'),
                          'cache': {'status': 'live', 'age_seconds': 0}, 'data': data}
                validate_arguments({'inputSchema': spec['outputSchema']}, output)
            except Exception:
                with self.lock:
                    self.failed_until[key] = self.clock() + 60
                    while len(self.failed_until) > 128:
                        self.failed_until.popitem(last=False)
                return self._stale_or_fail(entry, age)
            with self.lock:
                self.entries[key] = (deepcopy(output), self.clock())
                self.entries.move_to_end(key)
                self.failed_until.pop(key, None)
                while len(self.entries) > 512:
                    self.entries.popitem(last=False)
            return output

    @staticmethod
    def _cached(entry, age, status):
        result = deepcopy(entry[0])
        result['cache'] = {'status': status, 'age_seconds': int(age)}
        return result

    def _stale_or_fail(self, entry, age):
        if entry and age <= SPEC['max_stale']:
            return self._cached(entry, age, 'stale_cache')
        raise DataUnavailable('Current source data is unavailable. No replacement data was generated.')

    def _get(self, host, path, params):
        if host != 'developer.mozilla.org':   # MDN only (PM 11-15)
            raise DataUnavailable('Source unavailable.')
        client = bounded_client(self.http, timeout=4, limit=524288,
            headers={'User-Agent': 'AgentConcierge-DataAgents/1.0 (+https://agentconcierge.biz)',
                     'Accept': 'application/json'})
        try:
            response = client.request('GET', 'https://' + host + path, params=params, timeout=4)
            if response.status_code != 200 or 'application/json' not in response.headers.get('content-type', '').lower():
                raise DataUnavailable('Source unavailable.')
            return strict_json(response.content)
        finally:
            client.close()

    def _mdn(self, query, limit):
        raw = self._get('developer.mozilla.org', '/api/v1/search', {'q': query, 'size': limit, 'locale': 'en-US'})
        rows = raw.get('documents')
        if type(rows) is not list:
            raise ValueError('Invalid source')
        items, seen = [], set()
        for row in rows[:10]:
            path = row.get('mdn_url') if isinstance(row, dict) else None
            url = public_link('https://developer.mozilla.org' + path) if type(path) is str and path.startswith('/en-US/docs/') else None
            title = clean(row.get('title')) if url else ''
            if not url or not title or url in seen:
                continue
            items.append({'title': title, 'url': url, 'summary': clean(row.get('summary')) or 'MDN reference page.',
                          'library': 'MDN Web Docs', 'indexed_at': ''})
            seen.add(url)
        return {'query': query, 'source': 'MDN Web Docs', 'items': items[:limit],
                'partial': len(items) < min(limit, len(rows))}


_engine = None
_engine_lock = threading.Lock()


def engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = DocsAgent()
        return _engine


def is_docs(resource):
    return resource.get('key') == KEY


def execute_local(store, resource, name, arguments, observed):
    """Run the registered first-party binding in process, like OwnedDispatch.execute."""
    from ..capability_registry import digest, version_parts
    from ..collector import usage
    from ..concierge.execution_policy import ExecutionDenied
    from ..observability import provider_dispatch
    from .service import display_text
    tools = [tool_spec()]
    compact = usage.compact_tools(tools)
    fresh = store.resource(resource['id'])
    if (resource.get('kind') != 'mcp' or resource.get('source') != 'agentconcierge-owned' or not is_docs(resource)
            or not str(resource.get('url', '')).endswith('/api/owned-data-agents/' + ID + '/mcp')
            or name != SPEC['tool'] or resource.get('usage_tools_hash') != usage.tools_hash(compact)
            or resource.get('usage_full_hash') != digest(tools)
            or not fresh or not fresh.get('active') or version_parts(fresh) != version_parts(resource)):
        return {'ok': False, 'error_code': 'SCHEMA_CHANGED', 'error': 'The registered capability needs review.'}
    started = time.monotonic()
    try:
        validate_arguments(tools[0], arguments)
        provider_dispatch()
        output = engine().execute(arguments)
        validate_arguments({'inputSchema': tools[0]['outputSchema']}, output)
    except ExecutionDenied as exc:
        return {'ok': False, 'error_code': exc.error_code, 'error': str(exc)}
    except (DataUnavailable, ValueError):
        return {'ok': False, 'hash_verified': True, 'error_code': 'UPSTREAM_TOOL_ERROR',
                'error': 'Current source data is unavailable. Try again shortly.'}
    result = {'content': [{'type': 'text', 'text': display_text(output)}], 'structuredContent': output, 'isError': False}
    if observed is not None:
        observed.update(transport_ok=True, protocol_valid=True)
    return {'ok': True, 'resource_id': resource['id'], 'tool': name, 'result': result,
            'sample_output': result['content'][0]['text'][:500], 'hash_verified': True,
            'latency_ms': int((time.monotonic() - started) * 1000)}


def check_source(store, rid):
    """One real example read establishes readiness, like activation.check_sources."""
    from ..config import health_interval_seconds
    started = time.monotonic()
    try:
        engine().execute(SPEC['example'])
    except (ValueError, TimeoutError):
        store.record_health(rid, 'failing', None, None, 'Public data source unavailable.', time.time() + 120)
        return False
    store.record_health(rid, 'healthy', None, int((time.monotonic() - started) * 1000), None, time.time() + health_interval_seconds())
    return True

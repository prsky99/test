"""Exact first-party projection of Technical Documentation into docs.search.v1.

A separate module with its own digest: the research/news adapter digest covers other
files, and saved workflows pin it, so this adapter must not change those files.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from .capability_contracts import validate
from .capability_registry import decoded, digest
from .concierge.execution_policy import validate_arguments
from .owned_data_agents.docs import ID, KEY, SPEC, tool_spec

PROFILE = 'owned-technical-docs-v1'
PATH = '/api/owned-data-agents/' + ID + '/mcp'
CONTRACT = 'docs.search.v1'
FILES = ['docs_capability_adapter.py', 'owned_data_agents/docs.py']
IMPLEMENTATION = digest([hashlib.sha256(Path(__file__).parent.joinpath(name).read_bytes()).hexdigest() for name in FILES])


def profile(resource, contract, tool):
    if (contract != CONTRACT or tool != SPEC['tool'] or resource.get('key') != KEY
            or not str(resource.get('url', '')).endswith(PATH)):
        return None
    if resource.get('source') != 'agentconcierge-owned':
        raise ValueError('Use the exact registered first-party documentation connection.')
    found = [t for t in decoded(resource.get('usage_full_tools'), []) if isinstance(t, dict) and t.get('name') == SPEC['tool']]
    expected = tool_spec()
    if len(found) != 1 or {k: found[0].get(k) for k in expected} != expected:
        raise ValueError('The first-party documentation schema changed.')
    return {'id': PROFILE, 'schema_hash': digest(expected), 'implementation_hash': IMPLEMENTATION,
        'input_notice': 'English technical documentation: MDN Web Docs for web platform topics, Context7 for libraries '
                        'and products. Queries use at most 160 characters; each call returns up to five pages.'}


def arguments(resource, contract, tool, supplied, *, expected=None):
    current = profile(resource, contract, tool)
    if current is None or expected is not None and current != expected:
        raise ValueError('The reviewed documentation connection changed.')
    validate(CONTRACT, supplied)
    if supplied['language'] != 'en' or len(supplied['query']) > 160:
        raise ValueError('This documentation connection supports English queries of at most 160 characters.')
    native = {'query': supplied['query'], 'limit': min(supplied['limit'], 5)}
    validate_arguments(tool_spec(), native)
    return native


def normalize(resource, contract, tool, supplied, output, *, expected=None):
    arguments(resource, contract, tool, supplied, expected=expected)
    validate_arguments({'inputSchema': tool_spec()['outputSchema']}, output)
    if output['agent'] != ID or output['data']['query'] != ' '.join(supplied['query'].split()):
        raise ValueError('The documentation output does not match the reviewed request.')
    observed = output['retrieved_at']
    parsed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError('The source retrieval timestamp must be UTC.')
    rows = output['data']['items']
    if len(rows) > min(supplied['limit'], 5):
        raise ValueError('The source result limit changed.')
    items = [{'title': r['title'], 'url': r['url'], 'excerpt': r['summary'] or 'Documentation page from ' + r['library'] + '.',
              'version': ('Indexed ' + r['indexed_at']) if r['indexed_at'] else 'Current ' + r['library'] + ' page',
              'retrieved_at': observed} for r in rows]
    value = {'items': items, 'partial': bool(output['data']['partial'] or output['cache']['status'] == 'stale_cache'
                                             or supplied['limit'] > 5)}
    validate(CONTRACT, supplied, value)
    return value

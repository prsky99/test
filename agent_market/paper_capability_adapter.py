"""Reviewed deterministic schema adapters; never discover, approve or invoke.

Native schemas remain unchanged. A matching explicit approval and current real
execution/adapter-contract evidence are required by the caller. Only fixed
public read-only tools are supported; there is no expression or URL injection.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .capability_contracts import validate
from .capability_registry import digest, decoded
from .concierge.execution_policy import validate_arguments

PROFILE = 'paper-docs-v1'
ENDPOINT = 'https://papers.openkrill.app/mcp'
TOOL = 'search_papers'
CONTRACT = 'docs.search.v1'
MANIFEST = json.loads(Path(__file__).with_name('capability_adapter_profiles.json').read_text())
IMPLEMENTATION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def profile(resource, contract, tool):
    if resource.get('url') != ENDPOINT or contract != CONTRACT or tool != TOOL:
        return None
    tools = decoded(resource.get('usage_full_tools'), [])
    found = [item for item in tools if type(item) is dict and item.get('name') == TOOL]
    if len(found) != 1:
        raise ValueError('The reviewed adapter tool is unavailable.')
    spec = {key: found[0].get(key) for key in ('name','inputSchema','outputSchema','annotations')}
    if spec != MANIFEST[PROFILE]:
        raise ValueError('The reviewed upstream schema or annotations changed.')
    return {'id': PROFILE, 'schema_hash': digest(spec), 'implementation_hash': IMPLEMENTATION,
            'input_notice': 'Public paper-index search; query is limited to 200 characters. Results are records, not endorsements.'}


def evidence_dataset(value):
    return 'adapter.' + value['id'] + '.' + digest(value)[:24]


def arguments(resource, contract, tool, supplied, *, expected=None):
    value = profile(resource, contract, tool)
    if expected is not None and value != expected:
        raise ValueError('The reviewed adapter changed.')
    if value is None:
        return dict(supplied)
    validate(contract, supplied)
    result = {'query': supplied['query'], 'limit': supplied['limit']}
    validate_arguments({'inputSchema': MANIFEST[PROFILE]['inputSchema']}, result)
    return result


def normalize(resource, contract, tool, supplied, output, *, expected=None):
    value = profile(resource, contract, tool)
    if expected is not None and value != expected:
        raise ValueError('The reviewed adapter changed.')
    if value is None:
        return output
    validate_arguments({'inputSchema': MANIFEST[PROFILE]['outputSchema']}, output)
    if (output['status'] not in ('ok','no_results') or output['count'] != len(output['results'])
            or output['query'] != supplied['query']):
        raise ValueError('The upstream did not confirm a complete search response.')
    if output['status'] == 'no_results' and output['results']:
        raise ValueError('The upstream search status contradicts its results.')
    # Preserve the provider's own source observation timestamp. Never refresh an
    # old cache timestamp merely because this adapter ran now.
    observed = output.get('as_of')
    if type(observed) is not str:
        raise ValueError('An upstream source observation timestamp is required.')
    retrieved = datetime.fromisoformat(observed.replace('Z','+00:00'))
    if retrieved.tzinfo is None or retrieved.utcoffset().total_seconds() != 0:
        raise ValueError('An upstream UTC source observation timestamp is required.')
    if output['asOf'] != retrieved.date().isoformat():
        raise ValueError('The upstream source dates contradict each other.')
    items = []
    for record in output['results']:
        title, url = record['title'], record['url']
        details = ['Paper index record: ' + title]
        if record.get('venue'): details.append('Venue: ' + record['venue'])
        if record.get('year') is not None: details.append('Year: ' + str(record['year']))
        if record.get('source'): details.append('Index: ' + record['source'])
        items.append({'title': title, 'url': url, 'excerpt': '. '.join(details),
                      'version': 'Unversioned index record', 'retrieved_at': observed})
    result = {'items': items, 'partial': bool(output.get('notes'))}
    validate(contract, supplied, result)
    return result

"""A separate canonical news-title rule; private typed/pair purposes stay private."""
import copy
import hmac
import json
import math
import time

from .capability_contracts import validate
from .capability_registry import digest

PROFILE = 'public-news-title-to-docs-v1'
SOURCE_NODE = 'workflow-public-news-source-v1'
NODE = 'workflow-public-docs-target-v1'
IDS = ('start', 'search-1', 'search-2')
EDGES = ({'id': 'start-search-1', 'source': 'start', 'target': 'search-1'},
         {'id': 'search-1-search-2', 'source': 'search-1', 'target': 'search-2'})
SOURCE_FIELDS = {'audience', 'contract', 'pin', 'input', 'profile', 'nonce', 'owner', 'reviewed_at'}
TARGET_FIELDS = {'audience', 'contract', 'pin', 'input', 'connection'}


def timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('A finite timestamp is required.')
    return value


def stamp(value):
    return int(value) if type(value) is float and value.is_integer() else value


def public_title(value):
    from .workflow_typed_flow import validate_title
    from .workflow_resolved_evidence import display_text
    from .workflows import public_outcome
    if validate_title(value) != value or display_text(value) != value or public_outcome(value) != value:
        raise ValueError('The title must already be a safe public query without privacy normalization.')
    return value


def connected(node):
    if not isinstance(node, dict): return False
    data = node.get('data'); signed = data.get('composition') if isinstance(data, dict) else None
    value = signed.get('payload') if isinstance(signed, dict) else None
    return isinstance(value, dict) and value.get('audience') == NODE


def is_flow(workflow):
    for node in workflow.get('nodes', []):
        data = node.get('data') if isinstance(node, dict) else None
        signed_value = data.get('composition') if isinstance(data, dict) else None
        value = signed_value.get('payload') if isinstance(signed_value, dict) else None
        if isinstance(value, dict) and value.get('audience') in (SOURCE_NODE, NODE): return True
    return False


def graph_value(workflow):
    return {key: workflow.get(key) for key in ('id', 'name', 'description', 'category', 'trigger_type', 'nodes', 'edges')}


def signed(runtime, value):
    return {'payload': value, 'mac': runtime.authority.signature(value)}


def connection(source, target):
    binding = source['data']['composition']['payload']
    return {'profile': PROFILE, 'source_id': IDS[1], 'target_id': IDS[2],
            'source_binding_hash': digest(binding), 'source_pin': copy.deepcopy(binding['pin']),
            'target_pin': copy.deepcopy(target['pin']), 'path': ['items', 0, 'title'],
            'target_field': 'query', 'fixed_target': copy.deepcopy(target['input']),
            'edges': copy.deepcopy(list(EDGES))}


def definition(runtime, workflow, *, current=True, now=None):
    """Verify shape/signatures separately from optional live catalog checks."""
    try:
        nodes = workflow['nodes']; edges = workflow['edges']
        if (workflow.get('trigger_type') != 'manual' or workflow.get('is_template') or workflow.get('is_active', 1) != 1
                or workflow.get('fallback_policy_fingerprint') or len(nodes) != 3
                or [node['id'] for node in nodes] != list(IDS) or edges != list(EDGES)):
            raise ValueError()
        start, source, target = nodes
        if (start.get('type') != 'trigger' or start.get('kind') != 'trigger' or start.get('data') != {}
                or set(start) - {'id', 'name', 'type', 'kind', 'position', 'data'}): raise ValueError()
        bindings = []
        for node, audience, contract, fields in ((source, SOURCE_NODE, 'news.search.v1', SOURCE_FIELDS),
                                                (target, NODE, 'docs.search.v1', TARGET_FIELDS)):
            data = node['data']; envelope = data['composition']; value = envelope['payload']
            if (set(value) != fields or value['audience'] != audience or value['contract'] != contract
                    or not hmac.compare_digest(envelope['mac'], runtime.authority.signature(value))
                    or node.get('type') != 'agent' or node.get('kind') != 'mcp'
                    or node.get('resource_id') != value['pin']['resource_id']
                    or set(node) - {'id', 'name', 'type', 'kind', 'resource_id', 'position', 'data'}
                    or set(data) != {'tool', 'input', 'composition'} or data['input'] != value['input']
                    or data['tool'] != value['pin']['approval']['tool']): raise ValueError()
            if current and runtime.fallback.pin(node['resource_id'], contract) != value['pin']: raise ValueError()
            bindings.append(value)
        one, two = bindings
        reference = timestamp(time.time() if now is None else now)
        if (one['profile'] != PROFILE or not isinstance(one['owner'], str) or not one['owner'].isdecimal()
                or not isinstance(one['nonce'], str) or len(one['nonce']) != 32
                or any(c not in '0123456789abcdef' for c in one['nonce'])
                or timestamp(one['reviewed_at']) > reference + 5
                or set(two['input']) != {'language', 'limit'} or two['input'].get('language') != 'en'
                or type(two['input'].get('limit')) is not int or not 1 <= two['input']['limit'] <= 5
                or {key: value for key, value in one['input'].items() if key not in ('query', 'from_utc')} != two['input']
                or public_title(one['input']['query']) != one['input']['query']
                or two['connection'] != connection(source, two)):
            raise ValueError()
        validate('news.search.v1', one['input'], now=reference)
        validate('docs.search.v1', {**two['input'], 'query': one['input']['query']})
        return one, two
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        raise ValueError('The canonical public connection changed or is unavailable.') from None


def checkpoint(runtime, store, row, node, *, expires=None):
    records = store.query('SELECT substr(payload,1,262145) AS payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id=?', (row['id'], node['id']))
    if len(records) != 1 or len(records[0]['payload']) > 262144: raise ValueError('A retained signed checkpoint is required.')
    value = json.loads(records[0]['payload']); record = value['record']
    if (not hmac.compare_digest(records[0]['signature'], runtime.authority.signature(value))
            or any(value.get(key) != expected for key, expected in {'audience': 'workflow-checkpoint-v1', 'run_id': row['id'], 'digest': row['digest'], 'node_id': node['id']}.items())
            or record['status'] != 'succeeded' or record['node_id'] != node['id'] or record['type'] != 'agent'
            or record['kind'] != 'mcp' or record['resource_id'] != node['resource_id']
            or record['data'] != value['flow_output']): raise ValueError('The source result is not a certain signed success.')
    started = timestamp(record['started']); latency = timestamp(record['latency_ms'])
    if (latency > 60000 or started < timestamp(row['created']) or started + latency / 1000 > time.time() + 5
            or expires is not None and timestamp(expires) <= started): raise ValueError('The signed checkpoint timing is invalid.')
    attempts = store.query('SELECT input_hash,status FROM workflow_execution_attempts WHERE run_id=? AND node_id=?', (row['id'], node['id']))
    expected = runtime.authority.signature({'audience': 'workflow-input-v1', 'digest': row['digest'], 'node_id': node['id'], 'input': record['input']})
    if len(attempts) != 1 or attempts[0]['status'] != 'succeeded' or not hmac.compare_digest(attempts[0]['input_hash'], expected):
        raise ValueError('The provider attempt is not a certain success.')
    return value


def source_proof(runtime, row, workflow, *, store=None, expires=None, current=True):
    store = store or runtime.store
    one, _ = definition(runtime, workflow, current=current, now=None if current else row['created'])
    value = checkpoint(runtime, store, row, workflow['nodes'][1], expires=expires)
    if value['record']['input'] != one['input']: raise ValueError('The source input changed.')
    output = value['flow_output']
    if not isinstance(output, dict): raise ValueError('A structured source result is required.')
    normalized = output.get('structuredContent', output)
    observed = value['record']['started'] + value['record']['latency_ms'] / 1000
    validate('news.search.v1', one['input'], normalized, now=observed)
    return value, normalized


def resolved(runtime, row, workflow, *, store=None, expires=None, current=True):
    _, target = definition(runtime, workflow, current=current, now=None if current else row['created'])
    cp, output = source_proof(runtime, row, workflow, store=store, expires=expires, current=current)
    args = {**target['input'], 'query': public_title(output['items'][0]['title'])}
    validate('docs.search.v1', args)
    return args, {'profile': PROFILE, 'source_id': IDS[1], 'source_checkpoint_hash': digest(cp),
                  'connection_hash': digest(target['connection'])}


def resolve(composer, node, row=None, workflow=None):
    from .workflow_typed_flow import _scope
    try:
        if row is None or workflow is None:
            row, workflow = _scope.get()
        composer.runtime.publication.run_scope(row, workflow)
        if node['id'] != IDS[2]: raise ValueError()
        return resolved(composer.runtime, row, workflow)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        raise ValueError('The authorized first news title could not be verified; no documentation request was sent.') from None


def validate_node(composer, node, args):
    from .workflow_typed_flow import _scope
    if node['id'] == IDS[1]:
        value = node['data']['composition']['payload']
        if value['audience'] != SOURCE_NODE or args != value['input'] or not hmac.compare_digest(node['data']['composition']['mac'], composer.runtime.authority.signature(value)):
            raise ValueError('The canonical source binding changed.')
        if composer.runtime.fallback.pin(node['resource_id'], 'news.search.v1') != value['pin']: raise ValueError('The source pin changed.')
        validate('news.search.v1', args)
        return value
    context = _scope.get()
    if context is None: raise ValueError('A current public-connection run scope is required.')
    row, workflow = context
    expected, _ = resolve(composer, node, row, workflow)
    if args != expected: raise ValueError('The derived documentation query changed.')
    return node['data']['composition']['payload']

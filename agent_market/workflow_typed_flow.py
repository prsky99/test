"""One explicitly reviewed, private informational data connection.

Provider text remains untrusted data. No expressions, URL fetching, coercion,
truncation, fan-out, default query or additional provider attempt is introduced.
"""
import copy
from contextlib import contextmanager
from contextvars import ContextVar
import hmac
import json
import math
import time
import unicodedata

from .capability_contracts import validate
from .capability_registry import digest

PROFILE = 'news-title-to-docs-v1'
NODE = 'workflow-composer-connected-node-v1'
NOTICE = 'workflow-composer-flow-v1'
_scope = ContextVar('workflow_typed_input_scope', default=None)


def validate_title(value):
    from .workflow_composer import objective
    # Reject rather than trim or stringify a provider's value.
    if (not isinstance(value, str) or value != value.strip() or '[REDACTED]' in value
            or any(unicodedata.category(c).startswith('C') for c in value)):
        raise ValueError('The connected title must be a nonempty public search string of at most 500 characters.')
    return objective(value)


def connected(node):
    if not isinstance(node, dict):return False
    data=node.get('data'); signed=data.get('composition') if isinstance(data,dict) else None
    payload=signed.get('payload') if isinstance(signed,dict) else None
    if not isinstance(payload,dict):return False
    from .workflow_paired_flow import NODE as PAIR_NODE
    from .workflow_public_flow import NODE as PUBLIC_NODE
    return payload.get('audience') in (NODE, PAIR_NODE, PUBLIC_NODE)


@contextmanager
def input_scope(row, workflow):
    token = _scope.set((row, workflow))
    try:
        yield
    finally:
        _scope.reset(token)


def connection(source, target_id):
    binding = source['data']['composition']['payload']
    return {'profile': PROFILE, 'source_id': source['id'], 'source_contract': 'news.search.v1',
            'source_pin': copy.deepcopy(binding['pin']), 'path': ['items', 0, 'title'],
            'source_binding_hash': digest(binding),
            'target_id': target_id, 'target_contract': 'docs.search.v1', 'target_field': 'query'}


def binding(composer, node):
    from . import workflow_public_flow as public_flow
    if public_flow.connected(node):
        return node['data']['composition']['payload']
    from .workflow_paired_flow import paired, _binding
    if paired(node):return _binding(composer,node)
    signed = node['data']['composition']; value = signed['payload']
    if (set(value) != {'audience', 'contract', 'pin', 'input', 'connection', 'sharing_authorized', 'sharing_notice'}
            or value['audience'] != NODE or value['contract'] != 'docs.search.v1'
            or value['sharing_authorized'] is not True or value['sharing_notice'] != NOTICE
            or not hmac.compare_digest(signed['mac'], composer.runtime.authority.signature(value))
            or node.get('kind') != 'mcp' or node.get('type') != 'agent'
            or node.get('resource_id') != value['pin']['resource_id']
            or node['data'].get('tool') != value['pin']['approval']['tool']
            or node['data'].get('input') != value['input']
            or set(node['data']) != {'tool', 'input', 'composition'}):
        raise ValueError('The reviewed input connection changed or is not authorized.')
    validate(value['contract'], value['input'])
    return value


def definition(composer, node, workflow):
    from . import workflow_public_flow as public_flow
    if public_flow.connected(node):
        _, value = public_flow.definition(composer.runtime, workflow)
        return value, workflow['nodes'][1]
    from .workflow_paired_flow import paired, definition as pair_definition
    if paired(node):return pair_definition(composer,node,workflow)
    p=binding(composer,node)
    sources=[n for n in workflow['nodes'] if n.get('id')==p['connection']['source_id']]
    if len(sources)!=1 or p['connection']!=connection(sources[0],node['id']):
        raise ValueError('The reviewed source input or connection changed.')
    return p,sources[0]


def source_proof(composer, source, row, workflow):
    """Read one complete succeeded news checkpoint in the current run scope."""
    if row['source'] != 'admin' or digest(workflow) != row['digest']:
        raise ValueError()
    authority = composer.runtime.authority.run(row['id'], workflow['id'], row['digest'], row['source'])
    principal = authority['principal']['payload']
    if principal['kind'] != 'admin' or principal['role'] != 'superadmin':
        raise ValueError()
    source_binding = source['data']['composition']['payload']
    if (source_binding['audience'] != 'workflow-composer-node-v1'
            or source_binding['contract'] != 'news.search.v1'
            or set(source['data']) != {'tool', 'input', 'composition'}
            or composer.validate_node(source, source['data']['input']) != source_binding):
        raise ValueError()
    rows = composer.store.query('SELECT substr(payload,1,262145) AS payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id=?',
                                (row['id'], source['id']))
    if len(rows) != 1 or len(rows[0]['payload']) > 262144:
        raise ValueError()
    checkpoint = json.loads(rows[0]['payload'])
    if (not hmac.compare_digest(rows[0]['signature'], composer.runtime.authority.signature(checkpoint))
            or any(checkpoint.get(k) != v for k, v in {'audience': 'workflow-checkpoint-v1',
                'run_id': row['id'], 'digest': row['digest'], 'node_id': source['id']}.items())):
        raise ValueError()
    record = checkpoint['record']; started=record['started']; latency=record['latency_ms']
    if (type(started) not in (int,float) or type(latency) not in (int,float)
            or not math.isfinite(started) or not math.isfinite(latency) or latency<0 or latency>60000):
        raise ValueError()
    observed = started + latency / 1000
    if (record['status'] != 'succeeded' or record['node_id'] != source['id']
            or record['resource_id'] != source_binding['pin']['resource_id']
            or record['input'] != source_binding['input'] or record['data'] != checkpoint['flow_output']
            or not math.isfinite(observed) or started < row['created'] or observed > time.time()+5):
        raise ValueError()
    output = checkpoint['flow_output']
    if not isinstance(output, dict):
        raise ValueError()
    normalized = output.get('structuredContent', output)
    validate('news.search.v1', record['input'], normalized, now=observed)
    return checkpoint, normalized


def resolve(composer, node, row=None, workflow=None):
    """Reconstruct input only from a signed succeeded source in this exact run."""
    from . import workflow_public_flow as public_flow
    if public_flow.connected(node):return public_flow.resolve(composer,node,row,workflow)
    from .workflow_paired_flow import paired, resolve as pair_resolve
    if paired(node):return pair_resolve(composer,node,row,workflow)
    try:
        if row is None or workflow is None:
            context = _scope.get()
            if context is None:
                raise ValueError()
            row, workflow = context
        p,source=definition(composer,node,workflow)
        if not any(e.get('source') == source['id'] and e.get('target') == node['id']
                   and not set(e) - {'id', 'source', 'target'} for e in workflow['edges']):
            raise ValueError()
        checkpoint, normalized = source_proof(composer,source,row,workflow)
        args = copy.deepcopy(p['input'])
        args['query'] = validate_title(normalized['items'][0]['title'])
        validate('docs.search.v1', args)
        return args, {'profile': PROFILE, 'source_id': source['id'], 'source_checkpoint_hash': digest(checkpoint)}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError):
        raise ValueError('The reviewed news title could not be verified as a safe documentation query; no downstream request was sent.') from None

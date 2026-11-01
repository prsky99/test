"""One private, explicitly authorized source and two controlled document calls.

The ordered targets share one signed news checkpoint. Nothing in this profile
authorizes public execution, delivery, publication, retries or quality grading.
"""
import copy
import hmac
import json
import math
import re
import time

from .capability_contracts import validate
from .capability_registry import digest
from .concierge.execution_policy import ExecutionDenied

PROFILE = 'news-title-docs-pair-v1'
NODE = 'workflow-controlled-pair-node-v1'
SHARE_NOTICE = 'workflow-controlled-pair-share-v1'
RUN_NOTICE = 'workflow-controlled-pair-run-v1'
IDS = ('start', 'search-1', 'search-2', 'search-3')
EDGES = (('start-search-1', 'start', 'search-1'),
         ('search-1-search-2', 'search-1', 'search-2'),
         ('search-1-search-3', 'search-1', 'search-3'))
FIELDS = {'audience', 'contract', 'pin', 'input', 'pair', 'side', 'sharing_authorized', 'sharing_notice'}
DESCRIPTOR_FIELDS = {'profile', 'nonce', 'owner', 'source_id', 'source_binding_hash', 'source_pin',
                     'target_ids', 'target_pins', 'input_template', 'edges', 'sharing_notice', 'reviewed_at'}


class PairBlocked(ExecutionDenied):
    """A later target was deliberately not invoked after uncertain/failed A."""

    def __init__(self, message):
        super().__init__(message, error_code='POLICY_DENIED')


def paired(node):
    if not isinstance(node, dict):
        return False
    data = node.get('data'); signed = data.get('composition') if isinstance(data, dict) else None
    value = signed.get('payload') if isinstance(signed, dict) else None
    return isinstance(value, dict) and value.get('audience') == NODE


def is_pair(workflow):
    return any(paired(node) for node in workflow.get('nodes', []))


def _binding(composer, node):
    signed = node['data']['composition']; value = signed['payload']
    if (set(value) != FIELDS or value['audience'] != NODE or value['contract'] != 'docs.search.v1'
            or value['sharing_authorized'] is not True or value['sharing_notice'] != SHARE_NOTICE
            or not hmac.compare_digest(signed['mac'], composer.runtime.authority.signature(value))
            or node.get('kind') != 'mcp' or node.get('type') != 'agent'
            or node.get('resource_id') != value['pin']['resource_id']
            or node['data'].get('tool') != value['pin']['approval']['tool']
            or node['data'].get('input') != value['input']
            or set(node['data']) != {'tool', 'input', 'composition'}
            or set(node) - {'id', 'name', 'type', 'kind', 'resource_id', 'position', 'data'}):
        raise ValueError('The controlled target binding changed.')
    validate('docs.search.v1', value['input'])
    return value


def build(composer, source, targets, *, owner, nonce, reviewed_at=None):
    """Sign two targets from separately pinned literal news/docs compiler nodes."""
    from .workflow_composer import NODE as LITERAL
    reviewed_at = time.time() if reviewed_at is None else reviewed_at
    if (not isinstance(owner, str) or not 1 <= len(owner) <= 128 or owner != owner.strip()
            or any(ord(c) < 32 for c in owner) or not isinstance(nonce, str)
            or not re.fullmatch(r'[a-f0-9]{32}', nonce) or source.get('id') != IDS[1]
            or not isinstance(targets, list) or len(targets) != 2
            or [node.get('id') for node in targets] != list(IDS[2:])
            or type(reviewed_at) not in (int, float) or not math.isfinite(reviewed_at)
            or reviewed_at < 0 or reviewed_at > time.time() + 5):
        raise ValueError('Provide one bounded owner, nonce, source and two ordered targets.')
    source_binding = composer.validate_node(source, source['data']['input'])
    if (not source_binding or source_binding['audience'] != LITERAL
            or source_binding['contract'] != 'news.search.v1'
            or set(source['data']) != {'tool', 'input', 'composition'}):
        raise ValueError('A pinned literal news source is required.')
    bindings = [composer.validate_node(node, node['data']['input']) for node in targets]
    if (any(not binding or binding['audience'] != LITERAL or binding['contract'] != 'docs.search.v1' for binding in bindings)
            or bindings[0]['pin']['resource_id'] == bindings[1]['pin']['resource_id']
            or bindings[0]['input'] != bindings[1]['input']
            or bindings[0]['input'] != {k: v for k, v in source_binding['input'].items() if k != 'from_utc'}):
        raise ValueError('Choose two distinct documentation targets with identical reviewed inputs.')
    descriptor = {'profile': PROFILE, 'nonce': nonce, 'owner': owner, 'source_id': IDS[1],
                  'source_binding_hash': digest(source_binding), 'source_pin': copy.deepcopy(source_binding['pin']),
                  'target_ids': list(IDS[2:]), 'target_pins': [copy.deepcopy(binding['pin']) for binding in bindings],
                  'input_template': copy.deepcopy(bindings[0]['input']), 'edges': [list(edge) for edge in EDGES],
                  'sharing_notice': SHARE_NOTICE, 'reviewed_at': reviewed_at}
    result = copy.deepcopy(targets)
    for index, node in enumerate(result):
        value = {'audience': NODE, 'contract': 'docs.search.v1', 'pin': bindings[index]['pin'],
                 'input': copy.deepcopy(bindings[index]['input']), 'pair': copy.deepcopy(descriptor),
                 'side': 'ab'[index], 'sharing_authorized': True, 'sharing_notice': SHARE_NOTICE}
        node['data'] = {'tool': value['pin']['approval']['tool'], 'input': copy.deepcopy(value['input']),
                        'composition': {'payload': value, 'mac': composer.runtime.authority.signature(value)}}
    return result


def definition(composer, node, workflow, *, current=True, now=None):
    """Verify the exact four-node definition and both shared signed bindings."""
    try:
        nodes = workflow['nodes']; edges = workflow['edges']
        if (workflow.get('trigger_type') != 'manual' or workflow.get('is_template')
                or workflow.get('fallback_policy_fingerprint')
                or not isinstance(nodes, list) or [item['id'] for item in nodes] != list(IDS)
                or any(set(edge) != {'id', 'source', 'target'} for edge in edges)
                or [(edge['id'], edge['source'], edge['target']) for edge in edges] != list(EDGES)):
            raise ValueError()
        start, source, a, b = nodes
        if (start.get('type') != 'trigger' or start.get('kind') != 'trigger' or start.get('data') != {}
                or set(start) - {'id', 'name', 'type', 'kind', 'position', 'data'}
                or set(source) - {'id', 'name', 'type', 'kind', 'resource_id', 'position', 'data'}):
            raise ValueError()
        one, two = _binding(composer, a), _binding(composer, b)
        pair = one['pair']
        source_binding = source['data']['composition']['payload']
        source_signed = source['data']['composition']
        reference = time.time() if now is None else now
        reviewed_at = pair.get('reviewed_at')
        from .workflow_composer import NODE as LITERAL
        if (set(pair) != DESCRIPTOR_FIELDS or two['pair'] != pair or pair['profile'] != PROFILE
                or one['side'] != 'a' or two['side'] != 'b' or node not in (a, b)
                or source_binding['audience'] != LITERAL or source_binding['contract'] != 'news.search.v1'
                or set(source_binding) != {'audience', 'contract', 'pin', 'input'}
                or set(source['data']) != {'tool', 'input', 'composition'}
                or not hmac.compare_digest(source_signed['mac'], composer.runtime.authority.signature(source_binding))
                or source.get('type') != 'agent' or source.get('kind') != 'mcp'
                or source.get('resource_id') != source_binding['pin']['resource_id']
                or source['data']['tool'] != source_binding['pin']['approval']['tool']
                or source['data']['input'] != source_binding['input']
                or pair['source_binding_hash'] != digest(source_binding) or pair['source_pin'] != source_binding['pin']
                or pair['source_id'] != IDS[1] or pair['target_ids'] != list(IDS[2:])
                or pair['target_pins'] != [one['pin'], two['pin']]
                or one['pin']['resource_id'] == two['pin']['resource_id']
                or one['input'] != two['input'] or pair['input_template'] != one['input']
                or one['input'] != {k: v for k, v in source_binding['input'].items() if k != 'from_utc'}
                or pair['edges'] != [list(edge) for edge in EDGES] or pair['sharing_notice'] != SHARE_NOTICE
                or not isinstance(pair['owner'], str) or not 1 <= len(pair['owner']) <= 128
                or not isinstance(pair['nonce'], str) or not re.fullmatch(r'[a-f0-9]{32}', pair['nonce'])
                or type(reference) not in (int, float) or not math.isfinite(reference) or reference < 0
                or type(reviewed_at) not in (int, float) or not math.isfinite(reviewed_at)
                or reviewed_at < 0 or reviewed_at > reference + 5):
            raise ValueError()
        validate('news.search.v1', source_binding['input'], now=now)
        if current:
            if composer.validate_node(source, source['data']['input']) != source_binding:
                raise ValueError()
            for binding in (one, two):
                if composer.runtime.fallback.pin(binding['pin']['resource_id'], 'docs.search.v1') != binding['pin']:
                    raise ValueError()
        return one if node['id'] == IDS[2] else two, source
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        raise ValueError('The reviewed controlled pair changed or is no longer eligible.') from None


def verify_definition(composer, workflow, *, now):
    """Verify retained shape/signatures without consulting live catalog state."""
    return definition(composer, workflow['nodes'][2], workflow, current=False, now=now)


def expected_scope(workflow):
    """Return declared scope only; callers must separately verify its evidence."""
    pair = workflow['nodes'][2]['data']['composition']['payload']['pair']
    return {'profile': PROFILE, 'pair_hash': digest(pair), 'nonce': pair['nonce'], 'owner': pair['owner'],
            'sharing_notice': SHARE_NOTICE, 'run_notice': RUN_NOTICE, 'sharing_authorized': True}


def _review_epoch(runtime, workflow):
    """A resumed control switch cannot revive a plan reviewed before it."""
    reviewed_at = workflow['nodes'][2]['data']['composition']['payload']['pair']['reviewed_at']
    controls = runtime.store.query('SELECT updated FROM execution_controls WHERE id=1')
    updated = controls[0]['updated'] if len(controls) == 1 else None
    if (type(reviewed_at) not in (int, float) or not math.isfinite(reviewed_at) or reviewed_at < 0
            or type(updated) not in (int, float) or not math.isfinite(updated) or updated < 0
            or updated > reviewed_at):
        raise PairBlocked('Execution controls changed after pair review; prepare a new pair.')


def admit(runtime, workflow, claims, pair_authority, pair_notice):
    if not is_pair(workflow):
        if pair_authority or pair_notice is not None:
            raise ValueError('Pair consent requires a controlled pair definition.')
        return None
    if (pair_authority is not True or pair_notice != RUN_NOTICE
            or claims['kind'] != 'admin' or claims['role'] != 'superadmin'):
        raise ValueError('Explicit authorization for one private controlled pair is required.')
    definition(runtime.composer, workflow['nodes'][2], workflow)
    _review_epoch(runtime, workflow)
    scope = expected_scope(workflow)
    if claims['subject'] != scope['owner']:
        raise ValueError('The reviewed pair belongs to another administrator.')
    return scope


def run_scope(runtime, row, workflow):
    if row['source'] != 'admin' or digest(workflow) != row['digest']:
        raise ValueError('Controlled pair execution scope changed.')
    _review_epoch(runtime, workflow)
    authority = runtime.authority.run(row['id'], workflow['id'], row['digest'], row['source'])
    principal = authority['principal']['payload']
    if (principal['kind'] != 'admin' or principal['role'] != 'superadmin'
            or principal.get('controlled_pair') != expected_scope(workflow)
            or principal['subject'] != expected_scope(workflow)['owner'] or authority.get('grant_id') is not None
            or runtime.budgets.get(row)['profile'] != 'standard'):
        raise ValueError('Current controlled pair execution authority is required.')
    return authority


def replay_scope(runtime, row, scope):
    """Check prior consent without renewing its principal or restarting work."""
    records = runtime.store.query('SELECT substr(payload,1,16385) AS payload,signature FROM workflow_run_authority WHERE run_id=?', (row['id'],))
    try:
        if len(records) != 1 or len(records[0]['payload']) > 16384:
            raise ValueError()
        value = json.loads(records[0]['payload']); envelope = value['principal']; principal = envelope['payload']
        if (not hmac.compare_digest(records[0]['signature'], runtime.authority.signature(value))
                or not hmac.compare_digest(envelope['signature'], runtime.authority.signature(principal))
                or any(value.get(k) != row[k] for k in ('workflow_id', 'digest', 'source'))
                or value.get('run_id') != row['id'] or principal.get('controlled_pair') != scope
                or principal.get('subject') != scope['owner'] or principal.get('role') != 'superadmin'
                or principal.get('kind') != 'admin' or value.get('grant_id') is not None):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError('The idempotency key belongs to another controlled pair authorization.') from None


def resolve(composer, node, row=None, workflow=None):
    from .workflow_typed_flow import _scope, source_proof, validate_title
    try:
        if row is None or workflow is None:
            context = _scope.get()
            if context is None:
                raise ValueError()
            row, workflow = context
        value, source = definition(composer, node, workflow)
        run_scope(composer.runtime, row, workflow)
        checkpoint, normalized = source_proof(composer, source, row, workflow)
        certainty = composer.store.query('SELECT status FROM workflow_execution_attempts WHERE run_id=? AND node_id=?', (row['id'], source['id']))
        if (not certainty or certainty[0]['status'] != 'succeeded'
                or checkpoint['record']['kind'] != 'mcp' or checkpoint['record']['type'] != 'agent'):
            raise ValueError()
        args = copy.deepcopy(value['input'])
        args['query'] = validate_title(normalized['items'][0]['title'])
        validate('docs.search.v1', args)
        return args, {'profile': PROFILE, 'source_id': source['id'], 'source_checkpoint_hash': digest(checkpoint),
                      'pair_hash': digest(value['pair']), 'side': value['side']}
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError):
        raise ValueError('The controlled source query could not be verified; no target request was sent.') from None


def validate_node(composer, node, args):
    from .workflow_typed_flow import _scope
    context = _scope.get()
    if context is None:
        raise ValueError('A current controlled pair execution scope is required.')
    row, workflow = context
    value, _ = definition(composer, node, workflow)
    resolved, _ = resolve(composer, node, row, workflow)
    if args != resolved:
        raise ValueError('The controlled documentation input changed.')
    return value


def dispatch_guard(runtime, row, workflow, node):
    """Stop B before preparation and again immediately before its dispatch."""
    if not is_pair(workflow):
        return
    run_scope(runtime, row, workflow)
    if node['id'] != IDS[3]:
        definition(runtime.composer, workflow['nodes'][2], workflow)
        return
    definition(runtime.composer, workflow['nodes'][2], workflow, current=False, now=row['created'])
    a = workflow['nodes'][2]
    records = runtime.store.query('SELECT substr(payload,1,262145) AS payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id=?',
                                  (row['id'], a['id']))
    certainty = runtime.store.query('SELECT status FROM workflow_execution_attempts WHERE run_id=? AND node_id=?', (row['id'], a['id']))
    if len(records) != 1 or len(records[0]['payload']) > 262144 or not certainty or certainty[0]['status'] != 'succeeded':
        raise PairBlocked('The first controlled target has no certain successful result.')
    args, provenance = resolve(runtime.composer, a, row, workflow)
    from .workflow_typed_flow import source_proof
    source_checkpoint, _ = source_proof(runtime.composer, workflow['nodes'][1], row, workflow)
    source_record = source_checkpoint['record']
    source_observed = source_record['started'] + source_record['latency_ms'] / 1000
    try:
        checkpoint = json.loads(records[0]['payload']); record = checkpoint['record']
        started = record['started']; latency = record['latency_ms']
        later = runtime.store.query('SELECT started FROM workflow_node_runs WHERE run_id=? AND node_id=?', (row['id'], IDS[3]))
        b_started = later[0]['started'] if len(later) == 1 else None
        if (not hmac.compare_digest(records[0]['signature'], runtime.authority.signature(checkpoint))
                or any(checkpoint.get(k) != v for k, v in {'audience': 'workflow-checkpoint-v1',
                    'run_id': row['id'], 'digest': row['digest'], 'node_id': a['id']}.items())
                or checkpoint.get('typed_input') != provenance or record['input'] != args
                or record['status'] != 'succeeded' or record['resource_id'] != a['resource_id']
                or record['node_id'] != a['id'] or record['kind'] != 'mcp' or record['type'] != 'agent'
                or record['data'] != checkpoint['flow_output']
                or digest(source_checkpoint) != provenance['source_checkpoint_hash']
                or type(started) not in (int, float) or type(latency) not in (int, float)
                or not math.isfinite(started) or not math.isfinite(latency) or not 0 <= latency <= 60000
                or started < row['created'] or started < source_observed or not math.isfinite(started + latency / 1000)
                or started + latency / 1000 > time.time() + 5
                or type(b_started) not in (int, float) or not math.isfinite(b_started)
                or b_started < started + latency / 1000):
            raise ValueError()
        output = record['data']
        if not isinstance(output, dict):
            raise ValueError()
        validate('docs.search.v1', args, output.get('structuredContent', output), now=started + latency / 1000)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise PairBlocked('The first controlled target proof is unavailable or invalid.') from None

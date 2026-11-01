"""Shared REST/MCP outcome reporting and non-executing recovery suggestions."""
import re
import time
import uuid

from ..fallback_independence import IndependenceDenied, require_distinct
from .protocols import requested_protocol

ERROR_TYPES = ('timeout', 'http_5xx', 'auth_error', 'schema_mismatch', 'rate_limit')
_FIELDS = frozenset(('resource_id', 'ok', 'error', 'task', 'error_type', 'protocol', 'visitor_token'))


def validate_report(body):
    if not isinstance(body, dict) or set(body) - _FIELDS:
        raise ValueError('Use the documented outcome report fields.')
    if type(body.get('resource_id')) is not int or not 0 < body['resource_id'] < 2**31 or type(body.get('ok')) is not bool:
        raise ValueError('resource_id must be a positive integer and ok must be a boolean.')
    for key, limit in (('task', 2000), ('error', 1000)):
        if key in body and (not isinstance(body[key], str) or len(body[key]) > limit):
            raise ValueError('Report text exceeds the supported format or length.')
    if 'error_type' in body and body['error_type'] not in ERROR_TYPES:
        raise ValueError('Choose a documented error_type.')
    if 'protocol' in body:
        requested_protocol('', {'protocol': body['protocol']})
    return body


def error_category(body):
    if body['ok']:
        return None
    explicit = body.get('error_type')
    if explicit:
        return {'http_5xx': 'server_error', 'auth_error': 'auth_required'}.get(explicit, explicit)
    text = body.get('error', '').lower()
    for category, pattern in (
        ('timeout', r'\b(?:timeout|timed out)\b'),
        ('auth_required', r'\b(?:401|403|auth(?:entication|orization)?|unauthorized|forbidden)\b'),
        ('rate_limit', r'\b429\b|\brate[ -]?limit(?:ed|ing)?\b'),
        ('schema_mismatch', r'\b(?:400|422|schema)\b'),
        ('server_error', r'\b5[0-9]{2}\b')):
        if re.search(pattern, text):
            return category
    return 'unspecified'


def session_task(front, visitor, task='', protocol_marker=None):
    previous, _ = front.book.last_results(visitor.id) if visitor else ([], 0)
    interests = front.book.interests(visitor.id) if visitor and not previous else []
    latest = previous[0] if previous else interests[0] if interests else {}
    task = task or str(latest.get('task') or '')[:2000]
    if protocol_marker is not None:
        protocol = requested_protocol(task, {'protocol': protocol_marker})
    elif 'protocol_filter' in latest:
        protocol = latest['protocol_filter']
    elif interests:
        protocol = latest.get('kind')
    else:
        protocol = requested_protocol(task)
    return task, protocol


def alternatives(front, visitor, resource_id, task='', protocol_marker=None):
    """Different failure domains are a negative guard, never an execution grant."""
    task, protocol = session_task(front, visitor, task, protocol_marker)
    failed = front.book.failed_resources(visitor.id) if visitor else set()
    failed = set(failed) | {resource_id}
    primary = front.store.resource(resource_id)
    if not task and primary:
        task = str(primary.get('name') or '')[:2000]
    empty = {'protocol': protocol, 'alternative': None, 'alternatives': [], 'workflows': [],
             'status': 'no_alternative', 'recovery_mode': 'suggestions_only', 'execution_authorized': False}
    if not task or not primary or len(failed) > 100:
        return empty
    excluded = failed | front.book.global_failing_resources()
    resources = [front.store.resource(rid) for rid in sorted(failed)]
    resources = [r for r in resources if r]
    found = []
    candidates = front.rec.search(task, kind=protocol, limit=24, exclude=excluded)
    for item in candidates:
        if not (item.get('capability_contract') or {}).get('verified_within_24h'):
            continue
        target = front.store.resource(item['id'])
        if not target:
            continue
        try:
            for failed_resource in resources:
                require_distinct(failed_resource, target,
                    alternate_tool=(item.get('tools') or [None])[0])
            for other in found:
                require_distinct(front.store.resource(other['id']), target)
        except (IndependenceDenied, TypeError, ValueError, KeyError):
            continue
        found.append(item)
        if len(found) == 3:
            break
    # A workflow suggestion still needs a fresh run authorization. Reject any
    # known failed/aliased agent in its graph before suggesting it as recovery.
    from .workflow_discovery import recommend
    proposed = recommend(front.store, task, {'protocol': protocol or 'any'}, runtime=front.workflows)
    workflows = []
    for workflow in proposed['workflows']:
        if not workflow['execution_availability']['available']:
            continue
        graph = front.store.get_workflow(workflow['id']) or {}
        from .discovery_state import execution_state
        bindings = []
        for node in graph.get('nodes', []):
            if node.get('type') in ('trigger', 'router', 'input_transform', 'output_transform'):
                continue
            rid = (node.get('data') or {}).get('resource_id') or node.get('resource_id')
            binding = front.store.resource(rid) if type(rid) is int else None
            if binding is None or not execution_state(front.store, binding)['verified']:
                bindings = []
                break
            bindings.append(binding)
        if not bindings:
            continue
        try:
            for binding in bindings:
                if binding['id'] in excluded:
                    raise IndependenceDenied('Failed workflow binding.')
                for failed_resource in resources:
                    require_distinct(failed_resource, binding)
            workflows.append(workflow)
        except (IndependenceDenied, TypeError, ValueError, KeyError):
            continue
    return {**empty, 'alternative': found[0] if found else None, 'alternatives': found,
            'workflows': workflows, 'status': 'alternatives_available' if found or workflows else 'no_alternative'}


def report_outcome(front, visitor, body):
    body = validate_report(body)
    rid = body['resource_id']
    if front.store.resource(rid) is None:
        raise ValueError('Resource not found.')
    # Caller feedback is remembered for this session; it is not Registry proof.
    front.book.record_outcome(visitor, rid, body['ok'])
    with front.store.tx() as db:
        db.execute('INSERT INTO feedback (need_id,resource_id,success,rating,created) VALUES (?,?,?,?,?)',
                   ('mcp_'+uuid.uuid4().hex[:8], rid, int(body['ok']), 5 if body['ok'] else 1, time.time()))
    recovery = alternatives(front, visitor, rid, body.get('task', ''), body.get('protocol')) if not body['ok'] else {
        'alternative': None, 'alternatives': [], 'workflows': [], 'status': 'recorded',
        'recovery_mode': 'suggestions_only', 'execution_authorized': False}
    return {'intent': 'report', 'ok': body['ok'], 'resource_id': rid,
            'error_category': error_category(body), 'revalidate_after_sec': 3600, **recovery}

"""Explain recorded execution admission without probing, authorizing or dispatching."""

import math

from .execution_errors import MESSAGES
from .execution_policy import (
    ExecutionDenied, admit, admit_tool, safe_registered_tool, tools_for,
)


def _state(available, reason_code, message, resource=None, http_status=None):
    checked = resource.get('last_check_at') if isinstance(resource, dict) else None
    if type(checked) not in (int, float) or not math.isfinite(checked) or checked <= 0:
        checked = None
    return {'available': bool(available), 'reason_code': reason_code, 'message': message,
            'http_status': http_status, 'checked_at': checked, 'scope': 'recorded_preflight'}


def _denied(resource, code):
    # Only surface a recorded HTTP status when admission actually rejected an
    # unavailable health state. An old error must not override current eligibility.
    if (isinstance(resource, dict) and resource.get('active')
            and resource.get('eval_security') not in ('quarantine', 'review')
            and resource.get('health_status') in (
                'unhealthy', 'dead', 'down', 'suspended', 'failing')):
        status = resource.get('last_status_code')
        if type(status) is int and 400 <= status <= 599:
            return _state(False, 'UPSTREAM_HTTP_ERROR',
                          f'A required agent returned HTTP {status} in its latest recorded health check. '
                          'Choose another available connection or retry after it recovers.',
                          resource, status)
    return _state(False, code if code in MESSAGES else 'POLICY_DENIED',
                  MESSAGES.get(code, MESSAGES['POLICY_DENIED']), resource)


def resource_execution_availability(resource, *, store=None, kind=None, tool=None, arguments=None,
                                    public=True, validate_inputs=True,
                                    require_schema_hash=True, probe_only=False):
    """Mirror admission from recorded metadata; availability is not verification.

    Testbench uses public admission and its existing surveyed-schema requirement.
    Workflow callers use the existing workflow admission mode and defer resolved
    argument validation to runtime. No Registry evidence is created or required.
    """
    try:
        if store is not None and isinstance(resource, dict):
            from ..capability_registry import known_schema_failure
            if known_schema_failure(store, resource):
                raise ExecutionDenied('The registered capability schema changed.',
                                      error_code='SCHEMA_CHANGED')
        admit(resource, kind, public=public, authorize_charge=bool(
            probe_only and isinstance(resource, dict) and resource.get('kind') == 'x402'))
        if resource.get('kind') == 'mcp':
            if validate_inputs:
                admit_tool(resource, tool, {} if arguments is None else arguments)
            else:
                registered = tools_for(resource)
                selected = tool
                if not selected or selected == 'execute':
                    selected = registered[0].get('name') if len(registered) == 1 else None
                spec = next((item for item in registered if item.get('name') == selected), None)
                if not spec:
                    raise ExecutionDenied('Select a registered tool name.', error_code='TOOL_UNAVAILABLE')
                if not safe_registered_tool(spec):
                    raise ExecutionDenied('Potentially destructive or credential-requiring tools are refused.')
            if require_schema_hash and not resource.get('usage_tools_hash'):
                raise ExecutionDenied('The registered capability schema is not verified.')
    except ExecutionDenied as exc:
        return _denied(resource, exc.error_code)
    return _state(True, 'READY',
                  'Recorded checks allow an execution attempt. A completed result is not guaranteed.',
                  resource)


def workflow_execution_availability(store, workflow):
    """Inspect published node bindings without changing the graph or fallback policy."""
    from ..execution_authority import require_enabled

    try:
        require_enabled(store, 'workflow')
        require_enabled(store, 'invoke')
    except ExecutionDenied:
        return _state(False, 'POLICY_DENIED', 'Execution is currently unavailable or paused.')
    nodes = workflow.get('nodes', []) if isinstance(workflow, dict) else []
    if not isinstance(nodes, list) or not nodes:
        return _state(False, 'RESOURCE_UNAVAILABLE', 'Choose an available published workflow.')
    observed = []
    for node in nodes:
        if not isinstance(node, dict):
            return _state(False, 'POLICY_DENIED', 'The published workflow needs review.')
        if node.get('type') in ('trigger', 'router','input_transform','output_transform'):
            continue
        data = node.get('data') or {}
        if not isinstance(data, dict):
            return _state(False, 'POLICY_DENIED', 'The published workflow needs review.')
        if (node.get('disabled') or node.get('is_active', True) in (False, 0)
                or data.get('disabled') or data.get('is_active', True) in (False, 0)):
            continue
        rid = node.get('resource_id') or data.get('resource_id')
        resource = store.resource(rid) if type(rid) is int and 0 < rid < 2**31 else None
        state = resource_execution_availability(
            resource, store=store, kind=node.get('kind'), tool=data.get('tool') or data.get('action'),
            public=False, validate_inputs=False, require_schema_hash=False,
        )
        if not state['available']:
            return state
        if state['checked_at'] is not None:
            observed.append(state['checked_at'])
    result = _state(True, 'READY',
                    'Recorded checks allow an execution attempt. A completed result is not guaranteed.')
    result['checked_at'] = min(observed) if observed else None
    return result


def invocation_execution_availability(store):
    """Expose the same global invocation switch enforced at dispatch time."""
    from ..execution_authority import require_enabled

    try:
        require_enabled(store, 'invoke')
    except ExecutionDenied:
        return _state(False, 'POLICY_DENIED', 'Execution is currently unavailable or paused.')
    return _state(True, 'READY', 'Recorded checks allow an execution attempt. A completed result is not guaranteed.')

"""Safe execution failure categories and private, metadata-only diagnostics."""
import logging
import re
import secrets


log = logging.getLogger('agent_market.execution')
MESSAGES = {
    'INVALID_INPUT': 'Review the tool inputs and try again.',
    'AUTH_REQUIRED': 'This connection requires separate provider authorization.',
    'RESOURCE_UNAVAILABLE': 'The registered agent is unavailable.',
    'POLICY_DENIED': 'Security checks blocked this agent connection. Choose another agent, or ask the provider to review its published connection.',
    'UNSAFE_TOOL': 'This tool is not available for informational requests.',
    'TOOL_UNAVAILABLE': 'Choose a tool registered for this agent.',
    'UNSUPPORTED_SCHEMA': 'This tool needs input validation that this connection does not support.',
    'SCHEMA_CHANGED': 'The agent connection changed. Review it before retrying.',
    'UPSTREAM_TIMEOUT': 'The agent did not finish within the time limit.',
    'UPSTREAM_NETWORK': 'The agent could not be reached. Check its availability before retrying.',
    'UPSTREAM_PROTOCOL': 'The agent returned an invalid protocol response.',
    'UPSTREAM_TOOL_ERROR': 'The agent could not complete the requested task.',
    'PENDING_RESULT': 'The agent has no completed output. This connection does not support task polling.',
    'CAPACITY_EXCEEDED': 'Agent execution is busy. Please try again shortly.',
    'EXECUTION_FAILED': 'The agent execution failed. Review its connection and registered tool.',
}
_REFERENCE = re.compile(r'ex_[0-9a-f]{24}\Z')


def reference():
    """Opaque support reference, independent of all visitor/authentication tokens."""
    return 'ex_' + secrets.token_hex(12)


def failure_code(value):
    """Accept only our fixed taxonomy; never classify arbitrary provider prose."""
    return value if isinstance(value, str) and value in MESSAGES else 'EXECUTION_FAILED'


def policy_code(reason):
    """Classify our own validation messages, not third-party response messages."""
    reason = str(reason).lower()
    if 'unsupported pattern or reference' in reason or 'schema exceeds' in reason:
        return 'UNSUPPORTED_SCHEMA'
    if 'changed' in reason or 'schema is not verified' in reason:
        return 'SCHEMA_CHANGED'
    if 'authorization' in reason or 'configured credential is unavailable' in reason:
        return 'AUTH_REQUIRED'
    if 'destructive' in reason or 'credential-requiring tools' in reason:
        return 'UNSAFE_TOOL'
    if 'ssrf' in reason or 'public origin' in reason or 'not eligible' in reason:
        return 'POLICY_DENIED'
    if 'unavailable' in reason or 'not found' in reason:
        return 'RESOURCE_UNAVAILABLE'
    if 'registered tool' in reason or 'registered capability' in reason:
        return 'TOOL_UNAVAILABLE'
    if 'time limit' in reason:
        return 'UPSTREAM_TIMEOUT'
    return 'INVALID_INPUT'


def fields(code, correlation_id=None):
    code = failure_code(code)
    result = {'error_code': code, 'error_message': MESSAGES[code]}
    if isinstance(correlation_id, str) and _REFERENCE.fullmatch(correlation_id):
        result['correlation_id'] = correlation_id
    return result


def record_failure(correlation_id, resource_id, protocol, code, *, stage='gateway', exception=None):
    """Never record request arguments, provider prose, URLs, headers or identities."""
    if not isinstance(correlation_id, str) or not _REFERENCE.fullmatch(correlation_id):
        return
    rid = resource_id if type(resource_id) is int and 0 < resource_id < 2**31 else None
    kind = protocol if protocol in ('a2a', 'mcp', 'x402') else 'unknown'
    stage = stage if stage in ('gateway', 'workflow', 'admission') else 'gateway'
    exception_kind = type(exception).__name__ if exception is not None else 'none'
    if not re.fullmatch(r'[A-Za-z_]{1,80}', exception_kind):
        exception_kind = 'Exception'
    log.warning('Execution failure reference=%s resource_id=%s protocol=%s code=%s stage=%s exception=%s',
                correlation_id, rid, kind, failure_code(code), stage, exception_kind)

"""Safe execution failure categories and private, metadata-only diagnostics."""
import contextvars
import logging
import re
import secrets


log = logging.getLogger('agent_market.execution')
QA_HEADER = b'x-agentcon-qa'
_QA = contextvars.ContextVar('agentcon_qa', default='')
_QA_NAME = re.compile(r'[a-z][a-z0-9_]{0,39}')


def qa_name(value):
    """Our own measurement tools send X-Agentcon-QA: <tool name>; anything else is ignored."""
    text = value.decode('latin-1', 'replace') if isinstance(value, bytes) else str(value or '')
    text = text.strip().lower()
    return text if _QA_NAME.fullmatch(text) else ''


class QAMark:
    """Pure ASGI middleware: marks the request context when our measurement header is present."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            return await self.app(scope, receive, send)
        name = next((qa_name(v) for k, v in scope.get('headers') or () if k == QA_HEADER), '')
        if not name:
            return await self.app(scope, receive, send)
        token = _QA.set(name)
        try:
            return await self.app(scope, receive, send)
        finally:
            _QA.reset(token)
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
# What the caller can do next, per code (growth plan 7 item 4, PM 11-14): returned after a failed first run so a
# connection does not end in a bare error. INVALID_INPUT adds the tool's required arguments (fix_for).
FIXES = {
    'INVALID_INPUT': 'Send it again with the tool\'s required arguments.',
    'AUTH_REQUIRED': 'This provider needs its own account or key, which this gateway does not pass on. Connect to the provider directly with your credentials, or choose another recommendation.',
    'RESOURCE_UNAVAILABLE': 'Our latest check found this agent unavailable. Choose another recommendation, or ask again later.',
    'POLICY_DENIED': 'Choose another recommendation; this connection did not pass our security checks.',
    'UNSAFE_TOOL': 'This gateway runs only tools that read. Use the provider directly, with its own authorization, for tools that change data.',
    'TOOL_UNAVAILABLE': 'Use the tool named in the recommendation, or list the tools on its gateway endpoint (tools/list) first.',
    'UNSUPPORTED_SCHEMA': 'Call the provider directly; its input schema uses features this gateway cannot validate.',
    'SCHEMA_CHANGED': 'The provider changed its tools since our last check. Ask for agents again to get the current tool and arguments.',
    'UPSTREAM_TIMEOUT': 'The provider did not answer in time and the outcome is unknown. Check before repeating it, or choose another recommendation.',
    'UPSTREAM_NETWORK': 'The provider could not be reached. Try again later, or choose another recommendation.',
    'UPSTREAM_PROTOCOL': 'The provider did not answer in the MCP protocol. Choose another recommendation.',
    'UPSTREAM_TOOL_ERROR': 'The provider\'s tool reported an error. Check the argument values, then try once more or choose another recommendation.',
    'PENDING_RESULT': 'The provider returned no finished output. Choose another recommendation.',
    'CAPACITY_EXCEEDED': 'Wait a few seconds and send it again.',
    'EXECUTION_FAILED': 'Ask for agents again, or choose another recommendation.',
}
_REFERENCE = re.compile(r'ex_[0-9a-f]{24}\Z')


def fix_for(code, tool_spec=None, retry_after=None):
    """One line on how to get past CODE; for INVALID_INPUT the required arguments of TOOL_SPEC with examples.
    A provider that asked for a pause (429 Retry-After, b47872a5: RESOURCE_UNAVAILABLE with retry_after) is not
    down: the line says how long to wait instead."""
    code = failure_code(code)
    if code == 'RESOURCE_UNAVAILABLE' and isinstance(retry_after, (int, float)) and 0 < retry_after <= 86400:
        return 'The provider asked for a pause. Wait %d seconds, then send it again.' % max(1, round(retry_after))
    text = FIXES[code]
    if code == 'INVALID_INPUT' and isinstance(tool_spec, dict):
        import json
        from .connections import example_arguments
        example = example_arguments(tool_spec)
        if example:
            text = text[:-1] + ', for example ' + json.dumps(example, separators=(',', ':')) + ' (fill in the values).'
    return text


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
    qa = _QA.get()
    log.warning('Execution failure reference=%s resource_id=%s protocol=%s code=%s stage=%s exception=%s%s',
                correlation_id, rid, kind, failure_code(code), stage, exception_kind, f' qa={qa}' if qa else '')

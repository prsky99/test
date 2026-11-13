"""PM 11-13: a card says why the gateway does not relay a tool (an action, or a read tool not verified as
read-only), and user_slo records that reason beside a failed connect sample without excluding it (decision 2)."""
from agent_market.concierge.gateway_exposure import ACTION_TOOL, UNVERIFIED_TOOL, unrelayed_note, unrelayed_reason


def tool(name, description='', **annotations):
    return {'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': {}},
            'annotations': annotations}


def test_unrelayed_reason_and_note():
    assert unrelayed_reason(tool('send_email', 'Send an email.')) == ACTION_TOOL
    assert unrelayed_reason(tool('get_x', readOnlyHint=False)) == ACTION_TOOL
    assert unrelayed_reason(tool('invoice_ocr', 'OCR a scanned invoice.')) == UNVERIFIED_TOOL
    assert unrelayed_note('X', None, UNVERIFIED_TOOL).startswith('The Agent Concierge gateway has not verified')
    assert unrelayed_note('X', None, ACTION_TOOL).startswith('This tool performs an action')
    assert unrelayed_note('X', None).startswith('This tool performs an action')


def test_user_slo_failure_reason():
    from scripts.user_slo import failure_reason
    blocked = {'tools': 0, 'error': None, 'connection_available': False}
    assert failure_reason(blocked, {'connection_reason': 'action_tool'}) == 'policy_blocked'
    assert failure_reason(blocked, {'connection_reason': 'not_verified_read_only'}) == 'unverified_tool'
    assert failure_reason(blocked, {}) == 'unrelayed'
    assert failure_reason({'tools': 0, 'error': 'timeout', 'connection_available': True}, {}) == 'connect_failed'
    assert failure_reason({'tools': 1, 'error': 'tool_unlisted', 'connection_available': False},
                          {'connection_reason': 'action_tool'}) == 'policy_blocked'
    assert failure_reason({'tools': 0, 'error': 'no_gateway_endpoint'}, None) == 'no_gateway_endpoint'
    assert failure_reason({'tools': 3, 'error': None, 'connection_available': True}, {}) is None

"""Direct-connect verdict for recommendations our gateway does not relay (PM 11-18, reports/write-action-measurement-2026-11-18).

A write task ("send email") is answered with a tool that acts, which our gateway never runs for a caller. Such a sample
is not dropped; it passes when the visitor gets what they need to connect directly, all four of:

  (a) the recommendation picked a write tool that fits the task (the task list says which topics write and what fits);
  (b) our answer says so: connection_available false, a reason we stand behind (action_tool, terms_restricted,
      provider_authorization), a note that sends the caller to the provider and the provider's direct_endpoint;
  (c) the provider's own server, at the direct_endpoint our card gave the caller, lists that tool in tools/list on a
      new connection (read only): the address the visitor actually receives is the one measured (PM 11-18);
  (d) nothing was executed: the provider read sends only initialize, notifications/initialized and tools/list.

The same verdict serves the listings whose terms keep them off our gateway (TERMS_RESTRICTED, 11-19): call verdict()
with no task pattern and the card's reason. Tool annotations are provider claims; nothing here relies on them.
"""
import json
import re


# Topics of the user_slo task list that ask for an action, with the tool names that do it. Marked here, in the task
# list's terms, never inferred from a provider's annotations (PM 11-18).
_SEND_MAIL = r'transactional[_\s-]*e?-?mail|(?:send|compose|deliver)\w*[_\s-]*(?:\w+[_\s-]*)?(?:e-?mail|mail|message|msg)|(?:e-?mail|mail|message)\w*[_\s-]*(?:send|compose|deliver)'
WRITE_TOPICS = {'send email': _SEND_MAIL, '이메일 보내기': _SEND_MAIL}
DIRECT_REASONS = ('action_tool', 'terms_restricted', 'provider_authorization')
READ_METHODS = ('initialize', 'notifications/initialized', 'tools/list')
BUDGET_SYSTEM = 'fingerprints'     # provider tools/list reads (provider_budget.SHARE)
ENDPOINT = re.compile(r'/api/gateway/mcp/(\d+)\b')


def write_topic(task):
    """The write topic a user_slo task was built from ('send email today 427' -> 'send email'), or None."""
    text = str(task or '')
    return next((topic for topic in WRITE_TOPICS if text.startswith(topic + ' ') or text == topic), None)


def resource_id(card, text=''):
    """The listing id behind the recommendation: the card's gateway endpoint, else the answer's Endpoint line."""
    for value in ((card or {}).get('usage_endpoint'), (card or {}).get('endpoint'), text):
        found = ENDPOINT.search(str(value or ''))
        if found:
            return int(found.group(1))
    return None


def fits(wanted, pattern):
    """(a) The recommended tool fits the task: a write task needs a tool whose name does the action."""
    if not wanted:
        return False, 'no_recommended_tool'
    if pattern is None:
        return True, None
    return (True, None) if re.search(pattern, str(wanted), re.I) else (False, 'tool_does_not_fit_task')


def guidance(card):
    """(b) Our answer gives an accurate direct-connect notice."""
    card = card or {}
    if card.get('connection_available') is not False:
        return False, 'not_marked_unrelayed'
    if card.get('connection_reason') not in DIRECT_REASONS:
        return False, 'reason_' + str(card.get('connection_reason'))
    note = str(card.get('connection_note') or '')
    if 'Connect through the provider' not in note and 'Connect from your own client' not in note:
        return False, 'no_direct_connect_note'
    if not isinstance(card.get('direct_endpoint'), str) or not card['direct_endpoint'].startswith('https://'):
        return False, 'no_direct_endpoint'          # a notice the caller cannot act on is incomplete (PM 11-18)
    return True, None


class ReadOnlyClient:
    """Wraps an httpx client so that only READ_METHODS can be sent; anything else raises (condition d)."""

    def __init__(self, client):
        self.client = client
        self.methods = []

    def post(self, url, json=None, headers=None):
        method = (json or {}).get('method')
        self.methods.append(method)
        if method not in READ_METHODS:
            raise PermissionError(f'direct_connect sends only {READ_METHODS}, not {method!r}')
        return self.client.post(url, json=json, headers=headers)


def _rpc(client, url, method, params=None, session=None, rid=None):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    if session:
        headers['Mcp-Session-Id'] = session
    body = {'jsonrpc': '2.0', 'method': method, **({'id': rid} if rid is not None else {}),
            **({'params': params} if params is not None else {})}
    response = client.post(url, json=body, headers=headers)
    text = response.text or ''
    if text.startswith('event:') or '\ndata:' in text:
        text = text.split('data:', 1)[1].strip()
    try:
        return response, json.loads(text) if text else {}
    except ValueError:
        return response, {}


def provider_tools(url, client, reserve, check_public):
    """(c) Tool names the provider lists on a new connection, and why not when it could not be read. The ledger is
    reserved first (3 calls); a refusal ends here without a call. Returns (names or None, reason, methods sent)."""
    try:
        check_public(url)
    except Exception:
        return None, 'not_public_url', []
    ok, why = reserve(url, BUDGET_SYSTEM, n=3)
    if not ok:
        return None, 'ledger_' + str(why), []
    guarded = ReadOnlyClient(client)
    try:
        init, first = _rpc(guarded, url, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                       'clientInfo': {'name': 'user-slo-direct', 'version': '1'}}, rid=1)
        if init.status_code != 200 or 'error' in first:
            return None, f'initialize_{init.status_code}', guarded.methods
        session = init.headers.get('mcp-session-id')
        _rpc(guarded, url, 'notifications/initialized', session=session)
        listed, body = _rpc(guarded, url, 'tools/list', session=session, rid=2)
        names = [t.get('name') for t in (body.get('result') or {}).get('tools') or [] if isinstance(t, dict)]
        return (names, None, guarded.methods) if names else (None, f'tools_list_{listed.status_code}', guarded.methods)
    except PermissionError:
        raise
    except Exception as error:   # a provider that times out or answers garbage: (c) fails, recorded
        return None, 'provider_error:' + type(error).__name__, guarded.methods


def verdict(task, card, wanted, names, methods, pattern=None, listed_reason=None):
    """The four conditions and the result. NAMES is the provider's tools/list (None when unread); METHODS what was sent."""
    a, why_a = fits(wanted, pattern)
    b, why_b = guidance(card)
    c = bool(names) and wanted in names
    why_c = None if c else (listed_reason or ('tool_not_listed_by_provider' if names else 'provider_not_read'))
    executed = [m for m in methods or [] if m not in READ_METHODS]
    d = not executed
    return {'a_tool_fits': a, 'b_direct_notice': b, 'c_provider_lists_tool': c, 'd_nothing_executed': d,
            'passed': a and b and c and d, 'why': [w for w in (why_a, why_b, why_c) if w] +
            (['executed:' + ','.join(map(str, executed))] if executed else []),
            'provider_tools': len(names or []), 'methods': list(methods or [])}


def judge(task, card, wanted, text, open_client, reserve, check_public):
    """Everything for one sample: the topic's pattern, one budgeted read of the card's direct_endpoint, the verdict."""
    topic = write_topic(task)
    url = (card or {}).get('direct_endpoint')
    names, reason, methods = None, None, []
    if isinstance(url, str) and url.startswith('https://'):
        with open_client() as client:
            names, reason, methods = provider_tools(url, client, reserve, check_public)
    else:
        reason = 'no_direct_endpoint'
    out = verdict(task, card, wanted, names, methods, WRITE_TOPICS.get(topic) if topic else None, reason)
    out['resource_id'] = resource_id(card, text)
    return out

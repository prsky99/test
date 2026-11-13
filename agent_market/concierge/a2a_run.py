"""A2A "run N {arguments}": run a tool we just recommended, in the same conversation (PM 11-14 04:0x, growth plan 7).

An A2A client cannot use our MCP `call` tool, so a recommendation ended there (11-13: three outside A2A
recommendations, no connection). The scope is exactly that of the MCP `call` tool and no wider:
- only item N of the list we recommended last to this visitor (book.last_results is per visitor, not per
  contextId; no URL, no endpoint, no other agent);
- only an MCP listing our gateway relays, its recommended tool, through the same run_admitted_call (gateway
  admit, execution policy: relay verbs, read-only, action tools blocked; timeouts; outcome records);
- never a payment, an x402 listing, a priced listing, or arguments that carry credentials;
- a tool that needs the provider's own authorization is refused by the gateway and its code is returned.
The provider's answer is passed on with its source (agent id, tool, time) and a failure code when it failed.
"""
import json
import re
from datetime import datetime, timezone

RUN = re.compile(r'^\s*run\s+#?([1-9])\b(.*)$', re.I | re.S)
MESSAGES = {
    'no_conversation': 'Run works inside a conversation: ask for agents first, then send "run 1" with the contextId I gave you.',
    'not_recommended': 'There is no recommendation with that number in your latest results. Ask for agents first.',
    'not_runnable_kind': 'Only an MCP tool our gateway relays can be run here. Use its endpoint from the recommendation instead.',
    'payment_not_supported': 'Paid listings cannot be run here.',
    'not_relayed': 'Our gateway does not relay this tool. Use the provider link from the recommendation.',
    'no_tool': 'This recommendation names no tool to run.',
    'credentials_not_accepted': 'Do not send keys, tokens or passwords here; this run passes no credentials on.',
    'bad_arguments': 'Arguments must be one JSON object, for example: run 1 {"location": "Paris"}',
}


def parse(text):
    """(number, arguments or None) for 'run N' / 'run N {...}'; None when the text is not a run command;
    (number, 'invalid') when the arguments are not one JSON object."""
    match = RUN.match(text or '')
    if not match:
        return None
    rest = match[2].strip()
    if not rest:
        return int(match[1]), None
    try:
        value = json.loads(rest)
    except ValueError:
        return int(match[1]), 'invalid'
    return (int(match[1]), value) if isinstance(value, dict) else (int(match[1]), 'invalid')


def refusal(code, extra=None):
    return MESSAGES[code], {'intent': 'run', 'ok': False, 'error_code': code, **(extra or {})}


def choose(front, results, number, arguments):
    """The recommended item and its tool, or a refusal (text, data)."""
    if not results or not 1 <= number <= len(results):
        return refusal('not_recommended')
    item = results[number - 1]
    rid = item.get('id')
    resource = front.store.resource(rid) if type(rid) is int else None
    if not resource:
        return refusal('not_recommended')
    if item.get('kind') == 'x402' or resource.get('kind') == 'x402' or item.get('price_usdc') or resource.get('price_usdc'):
        return refusal('payment_not_supported')
    if item.get('kind') != 'mcp' or resource.get('kind') != 'mcp':
        return refusal('not_runnable_kind')
    if item.get('tool_unlisted') is True or item.get('connection_available') is False:
        return refusal('not_relayed')
    schema = (item.get('tools_schema') or [None])[0]
    tool = (schema or {}).get('name') or (item.get('tools') or [None])[0]
    if not isinstance(tool, str) or not tool:
        return refusal('no_tool')
    if arguments == 'invalid':
        return refusal('bad_arguments')
    if arguments is None:
        from .connections import example_arguments
        example = example_arguments(schema) if isinstance(schema, dict) else {}
        text = (f'Recommendation {number} is {item.get("name") or "the agent"}, tool {tool}. Send: run {number} '
                + json.dumps(example, separators=(',', ':')) + ' (fill in the values).')
        return text, {'intent': 'run', 'ok': False, 'error_code': 'needs_arguments', 'tool': tool, 'resource_id': rid,
                      'example': {'text': f'run {number} ' + json.dumps(example, separators=(',', ':'))}}
    from ..edge_gateway.native import credential_input
    if credential_input(arguments):
        return refusal('credentials_not_accepted')
    return item, rid, tool


def answer(item, rid, tool, ok, execution, reply_text):
    """The A2A reply: provenance first, then the provider's answer or the failure code."""
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    source = {'agent_id': rid, 'agent': item.get('name'), 'tool': tool, 'at': at}
    head = f'Ran {tool} on {item.get("name") or "agent " + str(rid)} (agent {rid}) at {at}.'
    code = None if ok else (execution or {}).get('error_code') or 'EXECUTION_FAILED'
    text = head + '\n' + reply_text + ('' if ok else f'\nFailure code: {code}')
    return text, {'intent': 'run', 'ok': bool(ok), 'source': source, 'error_code': code, 'execution': execution}


RUN_HERE = re.compile(r'^Run here: call (\{.*\})$', re.M)


def a2a_wording(reply):
    """The same answer with each "Run here: call {...}" line in A2A form: "Run here: run N {arguments}"."""
    items = (reply.data or {}).get('recommendations') or []
    numbers = {i.get('id'): n for n, i in enumerate(items, 1) if isinstance(i, dict)}

    def swap(match):
        try:
            call = json.loads(match[1])
        except ValueError:
            return match[0]
        number = numbers.get(call.get('resource_id'))
        if not number:
            return match[0]
        return 'Run here: run %d %s' % (number, json.dumps(call.get('arguments') or {}, separators=(',', ':')))
    text = RUN_HERE.sub(swap, reply.text or '')
    if text == reply.text:
        return reply
    import dataclasses
    return dataclasses.replace(reply, text=text) if dataclasses.is_dataclass(reply) else type(reply)(text, *list(reply)[1:])

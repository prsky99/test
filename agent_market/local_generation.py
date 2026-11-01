"""Fixed operator-selected local generation protocols, without execution authority."""
import copy
from contextlib import contextmanager, ExitStack
import ipaddress
import re
from urllib.parse import urlsplit

import httpx


def validate_endpoint(endpoint, provider, *, allow_http=False):
    if provider not in ('ollama', 'openai') or type(endpoint) is not str or len(endpoint) > 2048:
        raise ValueError('Invalid local model configuration.')
    try:
        parsed = urlsplit(endpoint)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise ValueError('Invalid local model endpoint.') from None
    paths = ('', '/') if provider == 'ollama' else ('', '/', '/v1', '/v1/')
    if (parsed.scheme not in ('http', 'https') or not host or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in paths
            or '\\' in endpoint or '%' in parsed.netloc or port == 0
            or any(ord(c) < 33 or ord(c) > 126 for c in endpoint)):
        raise ValueError('Invalid local model endpoint.')
    if parsed.scheme == 'http':
        try:
            address = ipaddress.ip_address(host)
            local = address.is_loopback
        except ValueError:
            local = host == 'localhost'
        if not local and not (provider == 'openai' and allow_http is True):
            raise ValueError('Remote HTTP generation requires explicit operator authorization.')
    return endpoint.rstrip('/')


def chat_request(endpoint, provider, payload):
    if provider == 'ollama':
        return endpoint.rstrip('/') + '/api/chat', payload
    if provider != 'openai':
        raise ValueError('Unsupported generation protocol.')
    base = endpoint.rstrip('/')
    if not base.endswith('/v1'):
        base += '/v1'
    options = payload.get('options', {})
    body = {'model': payload['model'], 'messages': copy.deepcopy(payload['messages']), 'stream': False,
            'temperature': options.get('temperature', 0), 'max_tokens': options.get('num_predict', 500),
            'chat_template_kwargs': {'enable_thinking': False}}
    schema = payload.get('format')
    if type(schema) is dict:
        body['response_format'] = {'type': 'json_schema', 'json_schema': {
            'name': 'local_response', 'strict': True, 'schema': copy.deepcopy(schema)}}
    elif schema == 'json':
        body['response_format'] = {'type': 'json_object'}
    return base + '/chat/completions', body


def endpoints(endpoint, provider, fallback_endpoint='', *, allow_http=False):
    """An optional second endpoint has the same operator-approved protocol."""
    if not fallback_endpoint:
        return (endpoint,)
    primary = validate_endpoint(endpoint, provider, allow_http=allow_http)
    fallback = validate_endpoint(fallback_endpoint, provider, allow_http=allow_http)
    return (primary,) if primary == fallback else (primary, fallback)


@contextmanager
def chat_stream(client, endpoint, provider, payload, *, fallback_endpoint='', allow_http=False,
                guard=None, **kwargs):
    """Try the standby once before exposing a response; never replay consumed output.

    Invalid content, authorization errors, redirects and caller validation errors
    retain their original failure path. Only operator-configured endpoints enter.
    """
    targets = endpoints(endpoint, provider, fallback_endpoint, allow_http=allow_http)
    kwargs['follow_redirects'] = False
    for index, target in enumerate(targets):
        if guard is not None:
            guard()
        url, request = chat_request(target, provider, payload)
        with ExitStack() as stack:
            try:
                response = stack.enter_context(client.stream('POST', url, json=request, **kwargs))
            except httpx.TransportError:
                if index + 1 < len(targets):
                    continue
                raise
            if (response.status_code in (408, 425, 429) or 500 <= response.status_code <= 599) and index + 1 < len(targets):
                continue
            yield response
            return


def chat_post(client, endpoint, provider, payload, **kwargs):
    """Bound non-streaming generation responses without changing their validation."""
    with chat_stream(client, endpoint, provider, payload, **kwargs) as response:
        parts, size = [], 0
        for chunk in response.iter_bytes(chunk_size=4096):
            size += len(chunk)
            if size > 65536:
                raise ValueError('Local model response exceeded the bounded budget.')
            parts.append(chunk)
        headers = {k: v for k, v in response.headers.items() if k not in ('content-encoding', 'content-length')}
        return httpx.Response(response.status_code, headers=headers,
                              content=b''.join(parts), request=response.request)


def engine_stream(engine, payload, **kwargs):
    return chat_stream(engine.http, getattr(engine, 'generation_url', engine.ollama_url),
                       getattr(engine, 'generation_provider', 'ollama'), payload,
                       fallback_endpoint=getattr(engine, 'generation_fallback_url', ''),
                       allow_http=getattr(engine, 'generation_allow_http', False), **kwargs)


def completion(outer, provider, expected_model):
    if provider == 'ollama':
        return outer
    if provider != 'openai' or type(outer) is not dict or outer.get('model') != expected_model:
        raise ValueError('Unexpected local model response.')
    choices = outer.get('choices')
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        raise ValueError('Expected one completed response.')
    choice = choices[0]
    message = choice.get('message')
    if (choice.get('finish_reason') != 'stop' or type(message) is not dict
            or message.get('role') != 'assistant' or type(message.get('content')) is not str
            or set(message) - {'role', 'content', 'reasoning_content', 'reasoning', 'tool_calls', 'function_call', 'refusal'}
            or any(message.get(key) not in (None, '', []) for key in
                   ('reasoning_content', 'reasoning', 'tool_calls', 'function_call', 'refusal'))
            or re.search(r'<(?:think|tool_call)>|\[/?(?:THINK|TOOL_CALL)\]', message['content'], re.I)):
        raise ValueError('Incomplete or unauthorized local model response.')
    return {'done': True, 'message': {'role': 'assistant', 'content': message['content']}}


def engine_request(engine, payload):
    return chat_request(getattr(engine, 'generation_url', engine.ollama_url),
                        getattr(engine, 'generation_provider', 'ollama'), payload)


def engine_completion(engine, outer):
    return completion(outer, getattr(engine, 'generation_provider', 'ollama'), engine.generation_model)

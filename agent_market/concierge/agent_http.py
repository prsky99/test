"""Public document HEAD, anonymous cross-site recommendations and trusted browser-agent transports."""
import json
import math
import os
import time
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, Response


DOCUMENTS = frozenset(('/robots.txt', '/sitemap.xml', '/llms.txt', '/llms-full.txt',
    '/skill.md', '/.well-known/agent-card.json', '/.well-known/agent.json',
    '/.well-known/mcp.json', '/.well-known/mcp/server.json', '/status.json', '/.well-known/agent-entry.json', '/openapi.json'))
TRANSPORTS = frozenset(('/chat', '/mcp', '/a2a'))
ALLOWED_HEADERS = frozenset(('content-type', 'authorization', 'x-visitor-token',
    'mcp-session-id', 'mcp-protocol-version', 'a2a-version', 'last-event-id', 'accept', 'idempotency-key'))
# Public catalog reads carry no session, credential or payment; any origin may read them.
PUBLIC_READS = ('/api/explore', '/api/agents/', '/api/agent/v1/')
READ_HEADERS = frozenset(('accept', 'content-type', 'if-none-match'))


# Any browser page may ask for recommendations; execution, contact, feedback and
# session-bound routes keep the explicit origin list. Cookies and credentials are
# never forwarded, so a cross-site call is always an anonymous visitor.
PUBLIC_TRANSPORTS = frozenset(('/chat', '/mcp'))
PUBLIC_HEADERS = frozenset(('content-type', 'accept', 'x-visitor-token', 'mcp-session-id',
    'mcp-protocol-version', 'last-event-id'))
PUBLIC_MCP_TOOLS = frozenset(('hello', 'chat', 'search', 'find_agents', 'check_agent', 'whats_new', 'credit',
    'search_workflows', 'workflow_details'))
PUBLIC_EXPOSE = 'Mcp-Session-Id, X-Visitor-Token, Retry-After, RateLimit, RateLimit-Policy'
PUBLIC_LIMIT, PUBLIC_WINDOW = 60, 60.0  # cross-site calls per page origin, per instance
PUBLIC_MAX_BODY = 256 * 1024


def public_mcp_call(body):
    """Allow protocol handshakes and listings, and tool calls only to read-only tools."""
    try:
        message = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return True  # the transport answers malformed JSON itself
    for item in message if isinstance(message, list) else [message]:
        if not isinstance(item, dict) or item.get('method') != 'tools/call':
            continue
        params = item.get('params')
        if not isinstance(params, dict) or params.get('name') not in PUBLIC_MCP_TOOLS:
            return False
    return True


class OriginLimiter:
    def __init__(self, limit=None, window=None, size=10000):
        self.limit, self.window = limit or PUBLIC_LIMIT, window or PUBLIC_WINDOW
        self.size, self.calls = size, {}

    def wait(self, origin):
        """Seconds to wait before ORIGIN may call again; 0 records the call."""
        now = time.monotonic()
        calls = [t for t in self.calls.pop(origin, ()) if now - t < self.window]
        if len(calls) >= self.limit:
            self.calls[origin] = calls
            return max(1, math.ceil(self.window - (now - calls[0])))
        if len(self.calls) >= self.size:
            self.calls.pop(next(iter(self.calls)))
        self.calls[origin] = calls + [now]
        return 0


def public_read(path):
    return path in DOCUMENTS or path == '/api/explore' or path.startswith(PUBLIC_READS[1:])


def trusted_origins(public_origin):
    """Reject permissive or malformed configuration rather than widening trust."""
    values = {public_origin.rstrip('/'), 'https://agentconcierge.biz'}
    values.update(v.strip() for v in os.environ.get('AGENT_BROWSER_ORIGINS', '').split(',') if v.strip())
    for value in values:
        parsed = urlsplit(value)
        if (not value.isascii() or any(ord(ch) < 33 or ord(ch) == 127 for ch in value)
                or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or '*' in value):
            raise ValueError('Browser agent origins must be explicit HTTPS origins.')
        try:
            parsed.port
        except ValueError:
            raise ValueError('Browser agent origins require a valid port.') from None
    return frozenset(values)


class AgentHTTP:
    """Keep CORS separate from execution authorization and customer sessions."""
    def __init__(self, app, *, origins, security_headers):
        self.app, self.origins = app, origins
        self.security_headers = {**security_headers, 'Vary': 'Origin'}
        self.limiter = OriginLimiter()

    async def public_transport(self, scope, receive, send, origin):
        """Serve a recommendation request from any page as an anonymous visitor."""
        path, method = scope['path'], scope['method']
        headers = Headers(scope=scope)
        cors = {'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': PUBLIC_EXPOSE, 'Vary': 'Origin'}
        if method == 'OPTIONS':
            requested = {h.strip().lower() for h in headers.get('access-control-request-headers', '').split(',') if h.strip()}
            if headers.get('access-control-request-method') != 'POST' or not requested <= PUBLIC_HEADERS:
                return await Response(status_code=403, headers=self.security_headers)(scope, receive, send)
            return await Response(status_code=204, headers={
                **self.security_headers, 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST',
                'Access-Control-Allow-Headers': ', '.join(sorted(PUBLIC_HEADERS)),
                'Access-Control-Max-Age': '600'})(scope, receive, send)
        if method != 'POST':
            return await self.app(scope, receive, send)
        wait = self.limiter.wait(origin)
        if wait:
            return await JSONResponse({'error': 'Too many cross-site requests from this page. Retry later.'},
                status_code=429, headers={**self.security_headers, **cors, 'Retry-After': str(wait)})(scope, receive, send)
        # Strip ambient credentials: a cross-site page never acts for a signed-in customer.
        scope = {**scope, 'headers': [(k, v) for k, v in scope['headers'] if k.lower() not in (b'cookie', b'authorization')]}
        if path == '/mcp':
            chunks, size = [], 0
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunks.append(message.get('body', b''))
                size += len(chunks[-1])
                if size > PUBLIC_MAX_BODY:
                    return await JSONResponse({'error': 'Request body is too large.'}, status_code=413,
                        headers={**self.security_headers, **cors})(scope, receive, send)
                if not message.get('more_body'):
                    break
            body = b''.join(chunks)
            if not public_mcp_call(body):
                return await JSONResponse({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32001,
                    'message': 'Cross-site browser pages may call only read-only tools '
                    '(' + ', '.join(sorted(PUBLIC_MCP_TOOLS)) + '). Call other tools from a server-side client.'}},
                    status_code=403, headers={**self.security_headers, **cors})(scope, receive, send)
            pending = [{'type': 'http.request', 'body': body, 'more_body': False}]

            async def replay():
                return pending.pop() if pending else {'type': 'http.disconnect'}
            receive = replay

        async def deliver(message):
            if message['type'] == 'http.response.start':
                response_headers = MutableHeaders(scope=message)
                response_headers.add_vary_header('Origin')
                response_headers['Access-Control-Allow-Origin'] = '*'
                response_headers['Access-Control-Expose-Headers'] = PUBLIC_EXPOSE
            await send(message)

        await self.app(scope, receive, deliver)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path, method = scope['path'], scope['method']
        headers = Headers(scope=scope)
        transport = path in TRANSPORTS or path == '/' and method in ('POST', 'OPTIONS')
        origin = headers.get('origin') if transport else None
        if (origin is not None and origin not in self.origins and path in PUBLIC_TRANSPORTS
                and len(headers.getlist('origin')) == 1):
            return await self.public_transport(scope, receive, send, origin)
        if origin is not None:
            if origin not in self.origins or len(headers.getlist('origin')) != 1:
                return await JSONResponse({'error': 'Request origin is not allowed.'}, status_code=403,
                    headers=self.security_headers)(scope, receive, send)
            if method == 'OPTIONS':
                requested = {h.strip().lower() for h in headers.get('access-control-request-headers', '').split(',') if h.strip()}
                if headers.get('access-control-request-method') != 'POST' or not requested <= ALLOWED_HEADERS:
                    return await Response(status_code=403, headers=self.security_headers)(scope, receive, send)
                return await Response(status_code=204, headers={
                    **self.security_headers,
                    'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Methods': 'POST',
                    'Access-Control-Allow-Headers': ', '.join(sorted(ALLOWED_HEADERS)),
                    'Access-Control-Max-Age': '600', 'Vary': 'Origin'})(scope, receive, send)
        shared = not transport and public_read(path) and method in ('GET', 'HEAD', 'OPTIONS')
        if shared and method == 'OPTIONS':
            requested = {h.strip().lower() for h in headers.get('access-control-request-headers', '').split(',') if h.strip()}
            if headers.get('access-control-request-method') not in ('GET', 'HEAD') or not requested <= READ_HEADERS:
                return await Response(status_code=403, headers=self.security_headers)(scope, receive, send)
            return await Response(status_code=204, headers={
                **self.security_headers, 'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, HEAD', 'Access-Control-Allow-Headers': 'accept, content-type, if-none-match',
                'Access-Control-Max-Age': '600'})(scope, receive, send)
        head = method == 'HEAD' and (path in DOCUMENTS or path.startswith('/agents/category/'))
        if head:
            scope = {**scope, 'method': 'GET'}

        async def deliver(message):
            if message['type'] == 'http.response.start' and shared:
                # Never with credentials: the wildcard exposes only the public catalog read.
                response_headers = MutableHeaders(scope=message)
                response_headers['Access-Control-Allow-Origin'] = '*'
                response_headers['Access-Control-Expose-Headers'] = 'ETag, Server-Timing, Retry-After, RateLimit, RateLimit-Policy, Link'
            if message['type'] == 'http.response.start' and transport:
                response_headers = MutableHeaders(scope=message)
                response_headers.add_vary_header('Origin')
                if origin:
                    response_headers['Access-Control-Allow-Origin'] = origin
                    response_headers['Access-Control-Expose-Headers'] = ('Mcp-Session-Id, X-Visitor-Token, '
                        'Retry-After, RateLimit, RateLimit-Policy')
            if head and message['type'] == 'http.response.body':
                message = {**message, 'body': b''}
            await send(message)

        await self.app(scope, receive, deliver)

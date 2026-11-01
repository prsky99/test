"""One round trip for the reads a workspace page starts together (UI policy 11-01).

Every request to the site crosses Cloudflare and costs 0.4-1.0 s, while the server answers a read in
milliseconds. A page that opens with several reads therefore waits for the slowest of several round
trips. The browser sends them here as one GET; each read is replayed in process through the same
application, so it keeps its own authentication, rate limits, registered SQL and status code.
"""
import asyncio
import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

MAX_READS = 8
# Only customer reads; never this route, sign-in flows or anything outside the customer API.
ALLOWED = re.compile(r'/api/customer-(?!batch\b|auth/(?:begin|callback|github))[a-z0-9-]+(?:/[A-Za-z0-9_.-]+)*')


def router_for():
    from .workspace_service import WorkspaceRoute
    # Same route class as the other customer reads: errors are private (no-store) and logged alike.
    router = APIRouter(route_class=WorkspaceRoute)

    @router.get('/api/customer-batch')
    async def customer_batch(request: Request):
        reads = request.query_params.getlist('p')
        if not 1 <= len(reads) <= MAX_READS:
            raise HTTPException(400, 'Send between one and eight reads.')
        parsed = []
        for read in reads:
            path, _, query = read.partition('?')
            if len(read) > 400 or '..' in path or not ALLOWED.fullmatch(path):
                raise HTTPException(400, 'Only customer reads can be combined.')
            parsed.append((path, query))
        answers = await asyncio.gather(*(_replay(request, path, query) for path, query in parsed))
        return JSONResponse({'responses': answers}, headers={'Cache-Control': 'no-store'})

    return router


async def _replay(request, path, query):
    scope = dict(request.scope)
    scope.update({'path': path, 'raw_path': path.encode(), 'query_string': query.encode(),
                  'method': 'GET', 'root_path': ''})
    for key in [k for k in scope if k in ('route', 'endpoint', 'path_params') or k.startswith('fastapi_')]:
        scope.pop(key)
    scope['state'] = {}
    # Each answer is embedded in one JSON reply, so it must come back uncompressed: the outer
    # response is compressed once by the same middleware (11-02: gzip bytes broke every page).
    scope['headers'] = [(k, v) for k, v in scope.get('headers', []) if k.lower() != b'accept-encoding']
    status, headers, chunks = 500, [], []

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message):
        nonlocal status, headers
        if message['type'] == 'http.response.start':
            status, headers = message['status'], message.get('headers', [])
        elif message['type'] == 'http.response.body':
            chunks.append(message.get('body', b''))

    await request.app(scope, receive, send)
    names = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in headers}
    body = b''.join(chunks).decode('utf-8', 'replace')
    answer = {'status': status, 'content_type': names.get('content-type', ''), 'body': body}
    if 'retry-after' in names:
        answer['retry_after'] = names['retry-after']
    if 'application/json' in answer['content_type']:
        try:
            answer['json'] = json.loads(body)
            del answer['body']
        except ValueError:
            pass
    return answer

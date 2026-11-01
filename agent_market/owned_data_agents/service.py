"""Explicit opt-in stateless MCP transport for the reviewed public data agents."""
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..broker.server import RateLimiter
from ..workflow_publication_service import no_store, read_object
from .catalog import SPECS, tool_spec
from .engine import DataAgents, DataUnavailable

PREFIX = '/api/owned-data-agents'


def display_text(output):
    source = output['source']
    status = output['cache']['status'].replace('_', ' ')
    lines = []
    lines.extend([source['name'] + ' — ' + source['url'], 'Retrieved: ' + output['retrieved_at'],
                  'Data status: ' + status])
    data = output['data']
    for key, value in data.items():
        if key in ('items', 'partial', 'rate_limited', 'rate_limit_reset_seconds', 'rate_limit_message'):
            continue
        lines.append(key.replace('_', ' ').capitalize() + ': ' + str(value))
    for item in data.get('items', []):
        lines.append(' | '.join(key.replace('_', ' ').capitalize() + ': ' + str(value)
                               for key, value in item.items()))
    if 'items' in data and not data['items']:
        lines.append('No matching records were returned by this source.')
    if data.get('partial'):
        lines.append('This response contains a partial set of source records.')
    return '\n'.join(lines)


def router_for(*, enabled=False, engine=None):
    if type(enabled) is not bool:
        raise ValueError('Choose an explicit owned-agent setting.')
    router = APIRouter()
    if not enabled:
        return router
    if engine is not None and not isinstance(engine, DataAgents):
        raise ValueError('Use a reviewed data agent engine.')
    engine, limiter = engine or DataAgents(), RateLimiter(240)

    def agent(agent_id):
        # Technical Documentation lives outside the reviewed research/news modules (see docs.py).
        from . import docs
        if agent_id == docs.ID:
            return docs.SPEC, docs.tool_spec(), lambda arguments: docs.engine().execute(arguments)
        if agent_id in SPECS:
            return SPECS[agent_id], tool_spec(agent_id), lambda arguments: engine.execute(agent_id, arguments)
        return None

    @router.post(PREFIX + '/{agent_id}/mcp')
    async def mcp(agent_id: str, request: Request):
        headers = {**no_store(), 'X-Content-Type-Options': 'nosniff'}
        found = agent(agent_id)
        if found is None:
            return JSONResponse({'detail': 'Agent unavailable.'}, status_code=404, headers=headers)
        spec, declared, execute = found
        if not limiter.allow(request.client.host if request.client else 'unknown'):
            return JSONResponse({'detail': 'Request limit reached.'}, status_code=429,
                                headers={**headers, 'Retry-After': '60'})
        identity = None
        try:
            body = await read_object(request, 8192)
            if (set(body) - {'jsonrpc', 'id', 'method', 'params'} or body.get('jsonrpc') != '2.0'
                    or type(body.get('method')) is not str or 'id' in body and
                    (type(body['id']) not in (str, int) or len(str(body['id'])) > 100)):
                raise ValueError()
            identity = body.get('id')
            method, params = body['method'], body.get('params', {})
            modern = request.headers.get('mcp-protocol-version') == '2026-07-28'
            if type(params) is dict and '_meta' in params:
                if type(params['_meta']) is not dict:
                    raise ValueError()
                modern = modern or params['_meta'].get('io.modelcontextprotocol/protocolVersion') == '2026-07-28'
                params = {key:value for key,value in params.items() if key != '_meta'}
            if method == 'notifications/initialized' and 'id' not in body and params == {}:
                return JSONResponse({}, status_code=202, headers=headers)
            if 'id' not in body or type(params) is not dict:
                raise ValueError()
            if method == 'server/discover' and params == {}:
                result = {'protocolVersion':'2026-07-28','capabilities':{'tools':{}},
                          'serverInfo':{'name':'Agent Concierge '+spec['name'],'version':'1.0.0'},
                          'ttlMs':60000,'cacheScope':'public'}
            elif method == 'initialize':
                requested = params.get('protocolVersion')
                if type(requested) is not str or len(requested) > 32:
                    raise ValueError()
                supported = ('2024-11-05','2025-03-26','2025-06-18','2025-11-25')
                result = {'protocolVersion': requested if requested in supported else supported[-1], 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'Agent Concierge ' + spec['name'], 'version': '1.0.0'}}
            elif method == 'tools/list' and params == {}:
                result = {'tools': [declared]}
                if modern:
                    result.update(ttlMs=60000,cacheScope='public')
            elif method == 'tools/call':
                if set(params) != {'name', 'arguments'} or params['name'] != spec['tool']:
                    raise ValueError()
                output = await run_in_threadpool(execute, params['arguments'])
                result = {'content': [{'type': 'text', 'text': display_text(output)}],
                          'structuredContent': output, 'isError': False}
            else:
                return JSONResponse({'jsonrpc': '2.0', 'id': identity,
                    'error': {'code': -32601, 'message': 'Method unavailable.'}}, headers=headers)
            return JSONResponse({'jsonrpc': '2.0', 'id': identity, 'result': result}, headers=headers)
        except DataUnavailable:
            return JSONResponse({'jsonrpc': '2.0', 'id': identity, 'result': {
                'isError': True, 'content': [{'type': 'text', 'text':
                    'Current source data is unavailable. Try again shortly; no replacement data was generated.'}]}}, headers=headers)
        except (ValueError, TypeError, KeyError, UnicodeError, TimeoutError, RecursionError):
            return JSONResponse({'jsonrpc': '2.0', 'id': identity,
                'error': {'code': -32602, 'message': 'Provide valid public data arguments.'}}, headers=headers)

    return router


def create_app(*, enabled=False, engine=None):
    """A separate opt-in app factory, with no collector or operating DB access."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.include_router(router_for(enabled=enabled, engine=engine))
    return app

"""A first-party informational MCP agent with a fixed public-only corpus.

Serving this agent never registers it, approves a capability, supplies quality
evidence or changes recommendation ranking. Public transport is opt-in.
"""
import copy
from datetime import datetime, timezone
import json
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .broker.server import RateLimiter
from .capability_contracts import CONTRACTS, validate
from .workflow_publication_service import no_store, read_object
from .workflow_support import DOCS

TOOL = 'search_platform_guides'
PROFILE = 'first-party-public-guides-v1'


class PlatformGuideAgent:
    tool_name = TOOL
    server_name = 'Agent Concierge Public Guides'

    def tools(self):
        contract = CONTRACTS['docs.search.v1']
        return [{'name': self.tool_name, 'description': 'Search the approved public source corpus and return matching excerpts.',
            'inputSchema': copy.deepcopy(contract['input_schema']),
            'outputSchema': copy.deepcopy(contract['output_schema']),
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True,
                            'openWorldHint': False}}]

    def search(self, arguments):
        validate('docs.search.v1', arguments)
        query = arguments['query']
        if (len(query.encode('utf-8')) > 2000 or any(ord(c) < 32 for c in query)
                or re.search(r'https?://|\bBearer\s|\b(?:api[_-]?key|token)\s*[:=]|<[^>]*>', query, re.I)):
            raise ValueError('Use public guide keywords.')
        terms = set(re.findall('[a-z0-9]{2,}', query.lower()))
        ranked = []
        for doc in DOCS:
            words = set(re.findall('[a-z0-9]{2,}', (doc['title']+' '+doc['text']).lower()))
            overlap = len(terms & words)
            if overlap:
                ranked.append((-overlap, doc['id'], doc))
        ranked.sort(key=lambda item: item[:2])
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        result = {'items': [{'title': doc['title'],
            'url': 'https://agentconcierge.biz/api/platform-guides/'+doc['id'],
            'excerpt': doc['text'], 'version': doc.get('version', 'public-guidance-v1'), 'retrieved_at': now}
            for _, _, doc in ranked[:arguments['limit']]], 'partial': False}
        validate('docs.search.v1', arguments, result)
        return result


def router_for(*, enabled=False, agent=None, path_prefix='/api/platform-guides'):
    if type(enabled) is not bool:
        raise ValueError('Choose an explicit public guide setting.')
    if path_prefix not in ('/api/platform-guides','/api/document-search'):
        raise ValueError('Choose a supported owned agent transport.')
    router = APIRouter()
    if not enabled:
        return router
    if agent is not None and not isinstance(agent, PlatformGuideAgent):
        raise ValueError('Use a configured read-only corpus agent.')
    agent, limiter = agent or PlatformGuideAgent(), RateLimiter(120)

    @router.get(path_prefix+'/{guide_id}')
    def guide(guide_id: str):
        doc = next((doc for doc in DOCS if doc['id'] == guide_id), None)
        return JSONResponse({'ok': True, 'guide': doc} if doc else {'ok': False},
                            status_code=200 if doc else 404, headers=no_store())

    @router.post(path_prefix+'/mcp')
    async def mcp(request: Request):
        headers = {**no_store(), 'X-Content-Type-Options': 'nosniff'}
        if not limiter.allow(request.client.host if request.client else 'unknown'):
            return JSONResponse({'error': 'Request limit reached.'}, status_code=429, headers=headers)
        identity = None
        try:
            body = await read_object(request, 16384)
            if (type(body) is not dict or set(body)-{'jsonrpc', 'id', 'method', 'params'}
                    or body.get('jsonrpc') != '2.0' or type(body.get('method')) is not str
                    or 'id' in body and (type(body['id']) not in (str, int) or len(str(body['id'])) > 100)):
                raise ValueError()
            identity = body.get('id')
            method, params = body['method'], body.get('params', {})
            if method == 'notifications/initialized' and identity is None:
                return JSONResponse({}, status_code=202, headers=headers)
            if method == 'initialize':
                if type(params) is not dict or params.get('protocolVersion') not in ('2024-11-05', '2025-03-26', '2025-06-18'):
                    raise ValueError()
                result = {'protocolVersion': params['protocolVersion'], 'capabilities': {'tools': {}},
                          'serverInfo': {'name': agent.server_name, 'version': '1.0.0'}}
            elif method == 'tools/list' and params == {}:
                result = {'tools': agent.tools()}
            elif method == 'tools/call':
                if type(params) is not dict or set(params) != {'name', 'arguments'} or params['name'] != agent.tool_name:
                    raise ValueError()
                output = agent.search(params['arguments'])
                result = {'content': [{'type': 'text', 'text': json.dumps(output, ensure_ascii=True)}],
                          'structuredContent': output, 'isError': False}
            else:
                return JSONResponse({'jsonrpc': '2.0', 'id': identity,
                    'error': {'code': -32601, 'message': 'Method unavailable.'}}, headers=headers)
            return JSONResponse({'jsonrpc': '2.0', 'id': identity, 'result': result}, headers=headers)
        except (ValueError, TypeError, KeyError, UnicodeError, TimeoutError, RecursionError):
            return JSONResponse({'jsonrpc': '2.0', 'id': identity,
                'error': {'code': -32602, 'message': 'Provide bounded public guide arguments.'}}, headers=headers)

    return router

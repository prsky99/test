"""Bounded REST error normalization and explicit public conditional reads.

Protocol-native envelopes and credentialed requests remain outside shared caching. HTML is shared
only for the login-free public growth pages (GROWTH_PAGES, 11-10).
"""
import hashlib
import json

from starlette.datastructures import Headers, MutableHeaders
from .conditional_http import etag_matches
from .security import _QUOTA_SINK, quota_headers

# Permanent aliases of discovery documents (11-11): a 301 the edge can keep like the target.
EDGE_REDIRECTS = frozenset(('/.well-known/llms.txt','/.well-known/mcp/server-card.json'))
PUBLIC_READS = frozenset(('/api/overview','/api/insights','/api/explore','/api/workflows/templates',
    '/api/test/presets','/robots.txt','/sitemap.xml','/llms.txt','/llms-full.txt',
    '/.well-known/agent-card.json','/.well-known/mcp.json','/.well-known/mcp/server.json',
    '/.well-known/security.txt','/security.txt','/openapi.json')) | EDGE_REDIRECTS
# Agent discovery documents the Cloudflare cache rule keeps at the edge (11-03). s-maxage lets the
# edge hold them for ten minutes while browsers and agents still revalidate after 30 seconds;
# with max-age alone the edge copy expired after 30 seconds (4 HITs in 24 cold requests, 11-04).
EDGE_DOCUMENTS = frozenset(('/robots.txt','/sitemap.xml','/llms.txt','/llms-full.txt',
    '/.well-known/agent-card.json','/.well-known/mcp.json','/.well-known/mcp/server.json',
    '/.well-known/security.txt','/security.txt','/openapi.json')) | EDGE_REDIRECTS
# Public growth pages (11-10 PM approval): login-free, never personalized HTML/Markdown/JSON. Browsers
# and the edge may keep them for five minutes and serve a stale copy while refreshing for ten.
GROWTH_PAGES = frozenset(('/connect','/agents/tasks','/agents/best','/badges','/reports/state-of-ai-agents',
    '/claude-plugins/marketplace.json'))
GROWTH_PREFIXES = ('/agents/task/','/agents/best/','/agent/','/agents/compare/','/reports/state-of-ai-agents/',
    '/claude-plugins/')
GROWTH_CACHE = 'public, max-age=300, stale-while-revalidate=600'
ANALYTICS_COOKIES = ('_ga','_gid','_gcl')
TITLES = {400:'Bad request',401:'Authentication required',403:'Forbidden',404:'Not found',
    405:'Method not allowed',408:'Request timed out',409:'Conflict',413:'Payload too large',
    422:'Invalid request',429:'Too many requests',500:'Request failed',502:'Provider unavailable',
    503:'Service unavailable',504:'Provider timed out'}
MAX_BODY = 2 * 1024 * 1024


def problem_document(body, status, method):
    value = dict(body) if isinstance(body,dict) else {}
    code = value.get('error_code')
    if not isinstance(code,str) or not code or len(code)>100 or not all(c.isalnum() or c=='_' for c in code):
        code='HTTP_'+str(status)
    detail=value.get('detail') or value.get('error')
    if not isinstance(detail,str):detail=TITLES.get(status,'Request failed')
    value.update(type='https://agentconcierge.biz/errors/'+code.lower().replace('_','-'),
        title=value.get('title') if isinstance(value.get('title'),str) else TITLES.get(status,'Request failed'),
        status=status,detail=detail,error_code=code)
    # Unknown mutation outcomes require caller reconciliation, not automatic retries.
    value.setdefault('retryable',status==429 or method in ('GET','HEAD') and status in (408,425,502,503,504))
    return value


def growth_path(path):
    return (path in GROWTH_PAGES or path.startswith(GROWTH_PREFIXES)) and not path.endswith('/reported')


def shared_path(path):
    return path in PUBLIC_READS or path.startswith('/api/workflows/templates/') or growth_path(path)


def _session_cookie(header):
    """True when the Cookie header carries anything besides analytics cookies (which change no page)."""
    names=[part.split('=',1)[0].strip() for part in (header or '').split(';') if part.strip()]
    return any(not name.startswith(ANALYTICS_COOKIES) for name in names)


def _credentials(request,path):
    keys=('authorization','x-visitor-token','signature','signature-agent')
    if any(request.get(key) for key in keys):
        return True
    return _session_cookie(request.get('cookie')) if growth_path(path) else bool(request.get('cookie'))


class PublicHTTPContract:
    def __init__(self,app):self.app=app

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        path,method=scope['path'],scope['method'];request=Headers(scope=scope)
        rest=(path.startswith('/api/') or path in ('/chat','/unsubscribe'))
        cache=method in ('GET','HEAD') and shared_path(path) and not _credentials(request,path)
        sink={};token=_QUOTA_SINK.set(sink)
        start=None;parts=[];size=0;passthrough=False

        async def deliver(message):
            nonlocal start,size,passthrough
            if message['type']=='http.response.start':
                start=dict(message);headers=Headers(raw=message.get('headers',[]));media=headers.get('content-type','')
                protocol=path.startswith(('/api/gateway/mcp/','/api/gateway/a2a/','/api/gateway/x402/')) or 'payment-required' in headers
                transform=rest and message['status']>=400 and 'json' in media and not protocol
                passthrough=not (transform or cache) or 'text/event-stream' in media or headers.get('content-encoding')
                if passthrough:
                    values=MutableHeaders(scope=start)
                    for k,v in quota_headers(sink).items():values.setdefault(k,v)
                    await send(start)
                return
            if message['type']!='http.response.body' or passthrough:return await send(message)
            size+=len(message.get('body',b''));parts.append(message.get('body',b''))
            if size>MAX_BODY:
                passthrough=True;await send(start)
                for part in parts:await send({'type':'http.response.body','body':part,'more_body':True})
                parts.clear()
                if not message.get('more_body'):await send({'type':'http.response.body','body':b''})
                return
            if message.get('more_body'):return
            body=b''.join(parts);headers=MutableHeaders(scope=start);status=start['status']
            if rest and status>=400 and 'json' in headers.get('content-type','') and not path.startswith(('/api/gateway/mcp/','/api/gateway/a2a/','/api/gateway/x402/')) and 'payment-required' not in headers:
                try:parsed=json.loads(body)
                except (ValueError,UnicodeDecodeError):parsed={}
                if isinstance(parsed,dict) and 'jsonrpc' not in parsed and 'x402Version' not in parsed:
                    body=json.dumps(problem_document(parsed,status,method),ensure_ascii=True).encode()
                    headers['content-type']='application/problem+json'
                    headers['cache-control']='no-store'
                    if 'etag' in headers:del headers['etag']
                    if status==429:headers.setdefault('Retry-After','60')
            if cache and (status in (200,304) or status==301 and path in EDGE_REDIRECTS) and 'set-cookie' not in headers:
                headers['cache-control']=('public, max-age=30, s-maxage=600, stale-while-revalidate=3600'
                    if path in EDGE_DOCUMENTS else GROWTH_CACHE if growth_path(path)
                    else 'public, max-age=30, stale-while-revalidate=30')
                if growth_path(path):  # the same URL answers HTML or Markdown by Accept
                    vary=[v.strip() for v in headers.get('vary','').split(',') if v.strip()]
                    for name in ('Accept','Accept-Encoding'):
                        if name.lower() not in (v.lower() for v in vary):vary.append(name)
                    headers['vary']=', '.join(vary)
                if status==200 and method=='GET':
                    tag=headers.get('etag') or '"'+hashlib.sha256(body).hexdigest()[:24]+'"'
                    tag='W/'+tag if not tag.startswith('W/') else tag
                    headers['etag']=tag
                    if etag_matches(request.get('if-none-match'),tag):start['status']=304;body=b''
            for k,v in quota_headers(sink).items():headers.setdefault(k,v)
            if start['status']==304:
                if 'content-length' in headers:del headers['content-length']
            else:headers['content-length']=str(len(body))
            await send(start);await send({'type':'http.response.body','body':body})
        try:await self.app(scope,receive,deliver)
        finally:_QUOTA_SINK.reset(token)


class PublicDocumentHEAD:
    """Apply public HEAD after compression so its metadata matches GET."""
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        from .agent_http import DOCUMENTS
        head=(scope['type']=='http' and scope['method']=='HEAD' and
              (shared_path(scope['path']) or scope['path'] in DOCUMENTS or scope['path'].startswith('/agents/category/')))
        if not head:return await self.app(scope,receive,send)
        async def deliver(message):
            if message['type']=='http.response.body':message={**message,'body':b''}
            await send(message)
        await self.app({**scope,'method':'GET'},receive,deliver)

"""Authorized response recipes. Origin authorizes and scrubs before referencing Edge data.

Only signed Worker GETs to existing result handlers are eligible. Their original
authentication and response projection run unchanged. No capability is inferred
from a run ID, and no execution endpoint is called to recover a missing cache.
"""
import hashlib
import json
import re

from starlette.concurrency import run_in_threadpool

from .auth import canonical, verify_service
from .config import EdgeError, parse
from .result_transport import parent_results, collecting
from .state import nonce

MEDIA = 'application/vnd.agentconcierge.edge-result+json'
# Keep this explicit and identical to Worker resultPath. No history/list routes.
RESULT_PATH = re.compile(r'/api/(?:workflows/runs/[^/]+|workflow-apps(?:-v12)?/[^/]+/runs/[^/]+'
    r'|workspace(?:-flow)?-apps-v2/[^/]+/(?:runs/[^/]+|history)'
    r'|customer-organizations/[^/]+/authoring/(?:drafts/[^/]+/snapshots/[^/]+/runs(?:/[^/]+)?'
    r'|typed/flows/[^/]+/runs(?:/[^/]+)?|templates/drafts/[^/]+/runs))\Z')
RUN_POST = re.compile(r'/api/(?:workflows/run|workflow-apps(?:-v12)?/[^/]+/runs|workspace(?:-flow)?-apps-v2/[^/]+/runs'
    r'|customer-organizations/[^/]+/authoring/(?:drafts/[^/]+/snapshots/[^/]+/runs|typed/flows/[^/]+/runs|templates/drafts/[^/]+/runs))\Z')


def recipe(value, sources):
    """Closed JSON recipe; exact values only, with bounded small metadata literals."""
    index, strings = {}, []
    def collect(value, ref, depth=0):
        if depth > 20 or len(index) >= 4096:
            return
        packed = canonical(value)
        if isinstance(value,(dict,list,str)):
            index.setdefault(packed, ref)
        if isinstance(value, str) and (len(value) >= 48 or value and ref[3] and ref[3][-1]=='text'):
            strings.append((value, ref))
        if isinstance(value, dict):
            for k, v in value.items(): collect(v, [1, ref[1], ref[2], ref[3]+[k]], depth+1)
        elif isinstance(value, list):
            for k, v in enumerate(value): collect(v, [1, ref[1], ref[2], ref[3]+[k]], depth+1)
    for source in sources:
        collect(source['output'], [1, source['run_id'], source['wire_hash'], []])
    # Workflow text projections serialize output as sorted, ASCII JSON.
    serialized = [(key, [4, ref, hashlib.sha256(key.encode()).hexdigest()]) for key, ref in index.items()
                  if len(key)>=48 or key.startswith(('{','['))]
    candidates = sorted(strings+serialized, key=lambda x:len(x[0]), reverse=True)[:512]
    counts = {'literal': 0, 'refs': 0, 'nodes': 0}
    def literal(item):
        counts['literal'] += len(json.dumps(item, ensure_ascii=False).encode())
        if counts['literal'] > 12000:
            raise EdgeError('RESULT_UNAVAILABLE')
        return [0, item]
    def build(item, depth=0):
        counts['nodes'] += 1
        if depth > 32 or counts['nodes'] > 12000: raise EdgeError('RESULT_UNAVAILABLE')
        ref = index.get(canonical(item))
        if ref is not None:
            counts['refs'] += 1
            return ref
        if isinstance(item, dict): return [2, {k:build(v, depth+1) for k,v in item.items()}]
        if isinstance(item, list): return [3, [build(v, depth+1) for v in item]]
        if isinstance(item, str):
            # Exact substring references also cover output_select truncation.
            for source, source_ref in candidates:
                at = source.find(item) if len(item) >= 48 else -1
                if at >= 0:
                    counts['refs'] += 1
                    return source_ref if source == item else [5, source_ref, at, at+len(item)]
            # A brief wrapper around one long Provider result stays small.
            for source, source_ref in candidates:
                at = item.find(source)
                if at >= 0:
                    counts['refs'] += 1
                    return [6, [literal(item[:at]), source_ref, build(item[at+len(source):], depth+1)]]
            # MCP summaries can contain a truncated prefix of a long result.
            # Match a fixed anchor, then binary-search its exact prefix length.
            for source, source_ref in candidates:
                if len(source)<48: continue
                at=item.find(source[:48])
                if at<0: continue
                low,high=48,min(len(source),len(item)-at)
                while low<high:
                    middle=(low+high+1)//2
                    if item[at:at+middle]==source[:middle]:low=middle
                    else:high=middle-1
                counts['refs']+=1
                return [6,[literal(item[:at]),[5,source_ref,0,low],build(item[at+low:],depth+1)]]
        return literal(item)
    node = build(value)
    if not counts['refs']: raise EdgeError('RESULT_UNAVAILABLE')
    result = {'version': 1, 'recipe': node}
    if len(canonical(result).encode()) > 32768: raise EdgeError('RESULT_UNAVAILABLE')
    return result


def install(app, front):
    @app.middleware('http')
    async def direct_results(request, call_next):
        requested = request.headers.get('x-edge-result-view') == 'v1'
        service = getattr(front, 'edge_gateway', None)
        eligible = (not request.url.query and (request.method == 'GET' and RESULT_PATH.fullmatch(request.url.path)
                    or request.method == 'POST' and RUN_POST.fullmatch(request.url.path)))
        if request.method == 'POST' and request.url.path == '/mcp':
            if request.headers.get('x-edge-mcp-prepare') == 'v1':
                request.scope['headers'] = [(k,v) for k,v in request.scope['headers'] if k.lower()!=b'accept-encoding']+[(b'accept-encoding',b'identity')]
            response = await call_next(request)
            sources = request.scope.get('edge_result_sources')
            run_id = response.headers.get('x-edge-result-run')
            if run_id: del response.headers['x-edge-result-run']
            if not sources and run_id and service:
                from .result_transport import load_result
                try:
                    sources = [await run_in_threadpool(load_result, service, run_id)]
                except EdgeError:
                    return response
            if not sources: return response
            return await project_response(response, sources)
        if not requested or not eligible:
            return await call_next(request)
        if service is None:
            return await call_next(request)
        try:
            raw_body = await request.body() if request.method=='POST' else b''
            if len(raw_body)>262144: raise EdgeError('INVALID_INPUT',413)
            identity = verify_service(service.config.key, request.method, request.url.path, request.headers, raw_body, now=service.clock())
            await run_in_threadpool(nonce, service.store, identity, service.clock())
        except EdgeError:
            from starlette.responses import JSONResponse
            return JSONResponse({'error_code':'AUTH_REQUIRED'}, status_code=401)
        request.scope['headers'] = [(k,v) for k,v in request.scope['headers'] if k.lower()!=b'accept-encoding']+[(b'accept-encoding',b'identity')]
        with collecting() as observed:
            response = await call_next(request)
        if (not service.config.direct_result_delivery or response.status_code != 200
                or not response.headers.get('content-type', '').startswith('application/json')):
            return response
        try:
            if (await run_in_threadpool(service.summary))['preferred_backend'] != 'worker': return response
        except Exception:
            return response
        return await project_response(response,None,service,request.url.path if request.method=='POST' else None,observed)

    async def project_response(response, sources, service=None, post_path=None, observed=()):
        # Consume only already-authorized JSON, preserving headers/cookies/CORS.
        raw = bytearray()
        async for chunk in response.body_iterator:
            raw.extend(chunk)
        headers = dict(response.headers)
        headers.pop('content-length', None)
        cookies = response.headers.getlist('set-cookie')
        headers.pop('set-cookie',None)
        from starlette.responses import Response
        def reply(output, fields):
            result=Response(output,headers=fields,status_code=200,background=response.background)
            for cookie in cookies:result.headers.append('set-cookie',cookie)
            return result
        try:
            if len(raw) > 2097152: raise EdgeError('RESULT_UNAVAILABLE')
            parsed = parse(raw)
            if sources is None:
                nested = parsed.get('run') if type(parsed.get('run')) is dict else parsed
                run_id = nested.get('run_id') or nested.get('id')
                if post_path and (type(run_id) is not str or not 1<=len(run_id)<=160): raise EdgeError('RESULT_UNAVAILABLE')
                ids=set(observed)
                def visit(value,depth=0):
                    if depth>8 or len(ids)>=64:return
                    if isinstance(value,dict):
                        for k,v in value.items():
                            if k in ('id','run_id') and type(v) is str and re.fullmatch(r'(?:wr|wpr|wtr)_[a-f0-9]{32}',v):ids.add(v)
                            elif k in ('run','runs','result') and isinstance(v,(dict,list)):visit(v,depth+1)
                    elif isinstance(value,list):
                        for item in value[:100]:visit(item,depth+1)
                visit(parsed)
                sources=[]
                for identity in sorted(ids):sources.extend(await run_in_threadpool(parent_results,service,identity))
            answer = await run_in_threadpool(recipe, parsed, sources)
            if post_path:
                # Used only to GET this same completed result after a cache miss.
                answer['recovery'] = {'run_id':run_id}
                key = nested.get('run_key')
                if type(key) is str: answer['recovery']['workflow_key'] = key
            output = json.dumps(answer, ensure_ascii=False, separators=(',',':')).encode()
            # Always prefer an available recipe, regardless of result size.
            headers.update({'content-type':MEDIA, 'cache-control':'private, no-store'})
            return reply(output,headers)
        except Exception:
            headers['x-edge-result-source'] = 'origin'
            return reply(bytes(raw),headers)

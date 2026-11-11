"""Versioned execution APIs; no original bindings are returned to public callers."""
from functools import wraps
import logging
from pathlib import Path
import re

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .auth import RUN, canonical, derived, verify_service
import hashlib
import hmac
from .bootstrap import configure
from .config import EdgeError, parse
from .state import nonce

SDK = Path(__file__).with_name('sdk.js')
log = logging.getLogger(__name__)


def errors(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except EdgeError as exc:
            return JSONResponse({'error_code': exc.code, 'message': 'The approved execution is unavailable.'},
                                status_code=exc.status, headers={'Cache-Control': 'private, no-store'})
        except Exception as exc:
            # Provider text, configuration paths and internal diagnostics stay private: only the
            # error class and store code reach the server log (11-10 00:36: a 503 left no cause).
            log.warning('Edge gateway %s unavailable: %s %s', function.__name__, type(exc).__name__,
                        getattr(exc, 'code', ''))
            return JSONResponse({'error_code': 'UNAVAILABLE', 'message': 'The execution state could not be confirmed.'},
                                status_code=503, headers={'Cache-Control': 'private, no-store'})
    return wrapped


async def body(request, limit=8192):
    if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
        raise EdgeError('INVALID_REQUEST', 415)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise EdgeError('INVALID_REQUEST', 413)
    value = parse(raw)
    if type(value) is not dict:
        raise EdgeError('INVALID_REQUEST', 400)
    return bytes(raw), value


def bearer(request):
    header = request.headers.get('authorization', '')
    if not header.startswith('Bearer ') or len(header) > 2048:
        raise EdgeError('AUTH_REQUIRED', 401)
    return header[7:]


def install(app, front):
    configure(front)
    router = APIRouter()

    def required():
        current = front.edge_gateway
        if current is None:
            raise EdgeError('UNAVAILABLE')
        return current

    def client_origin(request):
        current = required()
        origin = request.headers.get('origin') or current.config.origin
        if origin != current.config.origin or request.url.query:
            raise EdgeError('AUTH_REQUIRED', 403)
        return origin

    def rate(request):
        ip = front.security.resolve_ip(request)
        if not front.security.allow_probe(ip, base_limit=10):
            raise EdgeError('CAPACITY_EXCEEDED', 429)

    async def internal(request, limit=8192):
        current = required()
        raw, value = await body(request, limit)
        if request.url.query:
            raise EdgeError('AUTH_REQUIRED', 401)
        identity = verify_service(current.config.key, request.method, request.url.path, request.headers, raw, now=current.clock())
        await run_in_threadpool(nonce, current.store, identity, current.clock())
        return current, value

    @router.post('/api/edge-gateway-internal/v1/output-observation')
    @errors
    async def output_observation(request:Request):
        from .output_monitor import record
        current,value=await internal(request,2048)
        return JSONResponse(await run_in_threadpool(record,current,value),headers={'Cache-Control':'private, no-store'})

    @router.post('/api/edge-gateway-internal/v1/output-relay-read')
    @errors
    async def output_relay_read(request:Request):
        from .output_relay import retained
        current,value=await internal(request,4096)
        return JSONResponse(await run_in_threadpool(retained,current,value),headers={'Cache-Control':'private, no-store'})

    @router.get('/sdk/agentconcierge-edge-v1.js', include_in_schema=False)
    async def sdk():
        return FileResponse(SDK, media_type='text/javascript', headers={'Cache-Control': 'public, max-age=300', 'X-Content-Type-Options': 'nosniff'})

    @router.post('/api/gateway-execution/v1/runs')
    @errors
    async def prepare(request: Request):
        current = required()
        origin = client_origin(request)
        rate(request)
        _, value = await body(request)
        principal = await run_in_threadpool(current.principal, request.headers.get('x-visitor-token'))
        answer = await run_in_threadpool(current.prepare, principal, origin, value)
        return JSONResponse(answer, headers={'Cache-Control': 'private, no-store'})

    @router.get('/api/gateway-execution/v1/runs/{run_id}')
    @errors
    async def status(run_id: str, request: Request):
        current = required()
        client_origin(request)
        if not RUN.fullmatch(run_id):
            raise EdgeError('INVALID_INPUT', 400)
        principal = await run_in_threadpool(current.principal, request.headers.get('x-visitor-token'))
        answer = await run_in_threadpool(current.status, principal, run_id)
        return JSONResponse(answer, headers={'Cache-Control': 'private, no-store'})

    async def origin_stream(run_id: str, request: Request):
        current = required()
        origin = request.headers.get('origin') or current.config.origin
        if request.url.query:raise EdgeError('AUTH_REQUIRED',403)
        if origin!=current.config.origin:
            from .admin_delivery import approved
            row=await run_in_threadpool(current.authorized,bearer(request),origin,run_id)
            await run_in_threadpool(approved,current,row)
        cors={'Access-Control-Allow-Origin':origin,'Vary':'Origin'}
        rate(request)
        if not RUN.fullmatch(run_id):
            raise EdgeError('INVALID_INPUT', 400)
        raw, payload = await body(request)
        relayed=request.headers.get('x-edge-origin-relay')=='v1'
        if relayed:
            identity=verify_service(current.config.key,request.method,request.url.path,request.headers,raw,now=current.clock())
            await run_in_threadpool(nonce,current.store,identity,current.clock())
        result = await current.origin(bearer(request), origin, run_id, payload)
        if not relayed:
            from .output_monitor import note
            await run_in_threadpool(note,current,'origin','public','edge_unavailable')
        if request.headers.get('X-Edge-Result-Format') == 'receipt' and result['state'] == 'succeeded':
            from .result_transport import store_result
            from .state import rows, transaction
            with transaction(current.store, readonly=True) as db:
                row = rows(db, 'run', (run_id,))[0]
            wire = canonical(result['output'])
            saved = await run_in_threadpool(store_result, current, run_id, row['attempt'], wire, hashlib.sha256(wire.encode()).hexdigest())
            return JSONResponse({'run_id': run_id, 'state': 'succeeded', 'wire_hash': saved['wire_hash'],
                                 'backend': 'origin'}, headers={'Cache-Control': 'private, no-store'})
        if request.headers.get('X-Edge-Result-Format') == 'json':
            output={'managed':result['managed']} if result.get('managed',{}).get('protocol')=='x402' else result['output']
            return JSONResponse({'run_id': run_id, 'state': result['state'], 'output': output,
                                 'backend': 'origin'}, headers={'Cache-Control': 'private, no-store',
                                 'X-Content-Type-Options': 'nosniff',**cors})

        async def events():
            yield 'event: result\ndata: ' + canonical(result) + '\n\n'
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',**cors})

    for prefix in ('edge', 'origin'):
        router.add_api_route(f'/api/{prefix}-gateway/v1/runs/{{run_id}}/stream', errors(origin_stream), methods=['POST'])

    @router.post('/api/edge-gateway/v1/health')
    @errors
    async def origin_health(request: Request):
        current = required()
        raw, _ = await body(request)
        verify_service(current.config.key, request.method, request.url.path, request.headers, raw, now=current.clock())
        return JSONResponse({'backend': 'origin'}, headers={'Cache-Control': 'private, no-store'})

    @router.post('/api/edge-gateway-internal/v1/claim')
    @errors
    async def claim(request: Request):
        current, value = await internal(request)
        if set(value) != {'access_token', 'origin', 'run_id', 'input'}:
            raise EdgeError('INVALID_INPUT', 400)
        result = await run_in_threadpool(current.claim, value['access_token'], value['origin'], value['run_id'], value['input'], 'worker')
        return JSONResponse(result, headers={'Cache-Control': 'private, no-store'})

    @router.post('/api/edge-gateway-internal/v1/public-prepare')
    @errors
    async def public_prepare(request: Request):
        current, value = await internal(request)
        fields = {'resource_id', 'input', 'origin', 'idempotency_key'}
        if (not fields <= set(value) or set(value) - fields - {'testbench'}
                or 'testbench' in value and value['testbench'] is not True
                or value['origin'] != current.config.origin):
            raise EdgeError('INVALID_INPUT', 400)
        if (current.config.canary_principal or not current.config.worker_ready
                or type(value['resource_id']) is not int
                or not current.config.catalog_protocols and not any(p.resource_id == value['resource_id'] for p in current.config.providers)):
            return JSONResponse({'backend': 'origin'}, headers={'Cache-Control': 'private, no-store'})
        from ..owned_data_agents.dispatch import is_owned
        selected = await run_in_threadpool(front.store.resource, value['resource_id'])
        if selected and is_owned(selected):
            # First-party handlers execute locally through the original public
            # gateway, retaining its input, authority and schema checks.
            return JSONResponse({'backend': 'origin'}, headers={'Cache-Control': 'private, no-store'})
        from .state import transaction
        def preferred():
            with transaction(current.store, readonly=True) as db:
                return current.route(db)[0]
        if await run_in_threadpool(preferred) != 'worker':
            return JSONResponse({'backend': 'origin'}, headers={'Cache-Control': 'private, no-store'})
        # Existing public Gateway POSTs already authorize this selected request; a signed Worker request
        # still passes the same execution gate, counted once here and only when the Worker runs it (a
        # request handed to Origin is counted by the Origin gateway instead, 11-11).
        # 11-11: the Worker turned this 429 into "The execution is unavailable." with no code (7 of 30
        # real-task failures). Over the limit, hand the request to the Origin gateway, which answers the
        # same gate with HTTP 429, Retry-After and RateLimit headers; nothing has been prepared or run.
        try:
            rate(request)
        except EdgeError as exc:
            if exc.code != 'CAPACITY_EXCEEDED':
                raise
            log.info('Edge public prepare over the execution gate: handed to the Origin gateway')
            return JSONResponse({'backend': 'origin'}, headers={'Cache-Control': 'private, no-store'})
        ip = front.security.resolve_ip(request)
        principal = hmac.new(derived(current.config.key, 'edge-public-principal-v1'), ip.encode(), hashlib.sha256).hexdigest()
        try:
            payload = value['input']
            if value.get('testbench'):
                provider, _ = await run_in_threadpool(current.admitted, value['resource_id'])
                if type(payload) is not dict or set(payload) - {'message', 'tool', 'arguments'}:
                    raise EdgeError('INVALID_INPUT', 400)
                payload = ({'message': payload.get('message', '')} if provider.kind == 'a2a' else
                           {'tool': payload.get('tool', ''), 'arguments': payload.get('arguments', {})} if provider.kind == 'mcp' else {'action': 'probe'})
            grant = await run_in_threadpool(current.prepare, principal, value['origin'], {
                'resource_id': value['resource_id'], 'input': payload, 'idempotency_key': value['idempotency_key'],
                'run_authority': True, 'sharing_authority': True})
        except EdgeError as exc:
            # 11-11: arguments that do not match the registered schema came back as HTTP 403 with no
            # JSON-RPC body (Worker AUTH_REQUIRED), so callers read "needs a key" (real tasks p02, p05,
            # a05). Nothing is prepared; the Origin gateway repeats the same check and answers -32602
            # "Review the tool inputs and try again." Every other refusal stays 403.
            if exc.code != 'PROFILE_UNAVAILABLE' and getattr(exc, 'denied', None) != 'INVALID_INPUT':
                raise
            return JSONResponse({'backend': 'origin'}, headers={'Cache-Control': 'private, no-store'})
        backend = 'worker' if grant['stream_path'].startswith('/api/edge-') else 'origin'
        binding = await run_in_threadpool(current.claim, grant['access_token'], value['origin'], grant['run_id'], payload, 'worker') if backend == 'worker' else None
        return JSONResponse({'backend': backend, **grant, 'input': payload, **({'binding': binding} if binding else {})},
                            headers={'Cache-Control': 'private, no-store'})

    @router.post('/api/edge-gateway-internal/v1/mcp-schema')
    @errors
    async def mcp_schema(request: Request):
        from .catalog import review_mcp
        current, value = await internal(request, 131072)
        if set(value) != {'run_id', 'attempt_id', 'tools', 'input'}:
            raise EdgeError('INVALID_INPUT', 400)
        answer = await run_in_threadpool(review_mcp, current, value['run_id'], value['attempt_id'], value['tools'], value['input'])
        return JSONResponse(answer, headers={'Cache-Control': 'private, no-store'})

    @router.post('/api/edge-gateway-internal/v1/complete')
    @errors
    async def complete(request: Request):
        current, value = await internal(request)
        if not {'run_id', 'attempt_id', 'outcome'} <= set(value) or set(value) - {'run_id', 'attempt_id', 'outcome', 'output_bytes', 'outcome_code', 'mcp_cleanup'}:
            raise EdgeError('INVALID_INPUT', 400)
        result = await run_in_threadpool(current.finish, value['run_id'], value['attempt_id'], value['outcome'], value.get('output_bytes', 0), value.get('outcome_code'))
        if value.get('mcp_cleanup') is not None:
            from .mcp_control import close
            await run_in_threadpool(close, current, value['run_id'], value['attempt_id'], value['mcp_cleanup'])
        return JSONResponse(result, headers={'Cache-Control': 'private, no-store'})

    @router.post('/api/edge-gateway-internal/v1/result')
    @errors
    async def receive_result(request: Request):
        from .result_transport import store_result
        current, value = await internal(request, 400000)
        # An already claimed execution must still commit its result while new
        # direct admissions are disabled during a rolling update or rollback.
        if set(value) != {'run_id', 'attempt_id', 'wire', 'wire_hash'}:
            raise EdgeError('INVALID_INPUT', 400)
        answer = await run_in_threadpool(store_result, current, value['run_id'], value['attempt_id'], value['wire'], value['wire_hash'])
        return JSONResponse(answer, headers={'Cache-Control': 'private, no-store'})

    app.include_router(router)
    from .result_view import install as install_result_view
    install_result_view(app, front)

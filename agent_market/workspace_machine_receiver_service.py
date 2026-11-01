"""Opt-in private inbox router; never mounted by the public frontend factory."""

import asyncio
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .workflow_publication_service import no_store
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical
from .workspace_machine_adapters import (MAX_TRANSPORT_BYTES, RECEIPT_SIGNATURE_HEADER, SIGNATURE_HEADER,
    decode_object, decode_transport, transport_receipt)

BASE = '/private/machine-inbox/{receiver_id}'


class ReceiverRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def secured(request):
            try:
                response = await handler(request)
            except HTTPException as error:
                response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
            except RequestValidationError:
                response = JSONResponse({'detail': 'The private inbox request is invalid.'}, status_code=400)
            except Exception:
                response = JSONResponse({'detail': 'The private inbox outcome is uncertain.'}, status_code=503)
            response.headers.update(no_store())
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'"
            return response
        return secured


def router_for(receiver, *, enabled=False, allowed_hosts=()):
    """Trusted app code explicitly mounts this on a separately protected origin.

    This does not provision DNS, TLS, ingress isolation or public enablement.
    There is deliberately no unauthenticated status or receipt replay endpoint.
    """
    router = APIRouter(route_class=ReceiverRoute)
    if type(enabled) is not bool or type(allowed_hosts) is not tuple:
        raise WorkspaceInvalid()
    if not enabled:
        return router
    if (not receiver.enabled or not allowed_hosts or len(allowed_hosts) > 8
            or any(type(host) is not str or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host)
                   or host.endswith('.') for host in allowed_hosts)):
        raise WorkspaceInvalid()
    limit = RateLimiter(120)

    @router.post(BASE)
    async def receive(receiver_id: str, request: Request):
        if request.url.scheme != 'https' or request.url.hostname not in allowed_hosts or request.query_params:
            raise HTTPException(404, 'The private inbox is unavailable.')
        if any(request.headers.get(key) for key in ('origin', 'cookie', 'authorization')):
            raise HTTPException(403, 'Use the provisioned machine signature.')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'Use the bounded JSON inbox profile.')
        if request.headers.get('content-encoding', 'identity').lower() != 'identity':
            raise HTTPException(415, 'Use an uncompressed inbox request.')
        signatures = request.headers.getlist(SIGNATURE_HEADER)
        if len(signatures) != 1 or not re.fullmatch(r'v1\.[a-f0-9]{64}', signatures[0]):
            raise HTTPException(401, 'The machine signature is unavailable.')
        if not limit.allow(request.client.host if request.client else 'private-inbox'):
            raise HTTPException(429, 'The private inbox request limit was reached.')
        length = request.headers.get('content-length')
        if length is not None and (len(length) > 8 or not length.isascii() or not length.isdigit() or int(length) > MAX_TRANSPORT_BYTES):
            raise HTTPException(413, 'The private inbox request exceeds its limit.')

        async def bounded_body():
            result = bytearray()
            async for chunk in request.stream():
                if len(result) + len(chunk) > MAX_TRANSPORT_BYTES:
                    raise HTTPException(413, 'The private inbox request exceeds its limit.')
                result.extend(chunk)
            return bytes(result)
        try:
            raw = await asyncio.wait_for(bounded_body(), timeout=5)
            # The authoritative protocol is read from the signed grant inside
            # receive; a wrapper never selects a different destination or key.
            wire = decode_object(raw)
            if 'jsonrpc' in wire:
                encoded, signature, identity = decode_transport(raw)
                if signature != signatures[0]:
                    raise WorkspaceDenied()
                receipt = await run_in_threadpool(receiver.receive, receiver_id, encoded, signature,
                                                 transport_protocol='a2a_inbox')
                return Response(_canonical(transport_receipt(receipt, identity)).encode('ascii'),
                                media_type='application/json', headers=no_store())
            receipt = await run_in_threadpool(receiver.receive, receiver_id, raw, signatures[0],
                                             transport_protocol='webhook')
            return Response(receipt.raw, media_type='application/json',
                            headers={**no_store(), RECEIPT_SIGNATURE_HEADER: receipt.signature})
        except WorkspaceDenied:
            raise HTTPException(409, 'The inbox proof is unavailable or the event was already recorded.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'The inbox state changed. Do not retry an uncertain dispatch.') from None
        except (WorkspaceInvalid, ValueError, TypeError, KeyError, UnicodeError, RecursionError, asyncio.TimeoutError):
            raise HTTPException(400, 'Provide the exact bounded signed inbox profile.') from None
    return router

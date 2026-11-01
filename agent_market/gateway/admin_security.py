"""Uniform resource and input boundaries for the administrator HTTP surface."""
import asyncio
import json
import inspect
import math
import threading
import logging
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

MAX_BODY_BYTES = 256 * 1024
MAX_CREDITS = 10**12
ASYNC_OPERATION_SECONDS = 35
_slots = threading.BoundedSemaphore(32)


def _origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid origin")
    return (parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80))


def check_origin(request):
    origin = request.headers.get("origin")
    if origin:
        try:
            if _origin(origin) == _origin(str(request.url)):
                return
        except ValueError:
            pass
        raise HTTPException(403, "Cross-origin admin requests are prohibited.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site admin requests are prohibited.")


def integer(value, name, minimum=1, maximum=MAX_CREDITS):
    if type(value) is not int or not minimum <= value <= maximum:
        raise HTTPException(400, f"{name} must be an integer between {minimum} and {maximum}.")
    return value


def number(value, name, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise HTTPException(400, f"Invalid {name}.")
    return value


def text(value, name, maximum=200, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise HTTPException(400, f"Invalid {name}.")
    return value


def validate_graph(nodes, edges):
    if not isinstance(nodes, list) or not isinstance(edges, list) or len(nodes) > 100 or len(edges) > 500:
        raise HTTPException(400, "Workflow limit: 100 nodes and 500 edges.")
    ids = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise HTTPException(400, "Invalid workflow node.")
        nid = text(node.get("id"), "node id", 128, required=True)
        if nid in ids or not isinstance(node.get("data", {}), dict):
            raise HTTPException(400, "Duplicate node id or invalid node data.")
        ids.add(nid)
        if "resource_id" in node:
            integer(node["resource_id"], "resource_id", -1000, 2**31-1)
        for key in ("name", "type", "kind"):
            if key in node:
                text(node[key], key, 500)
        node_data = node.get("data", {})
        if "resource_id" in node_data:
            integer(node_data["resource_id"], "resource_id", -1000, 2**31-1)
        position = node.get("position") or {}
        if not isinstance(position, dict):
            raise HTTPException(400, "Invalid node position.")
        for key in ("x", "y"):
            if key in position:
                number(position[key], "coordinate", -100000, 100000)
    for edge in edges:
        if not isinstance(edge, dict) or not isinstance(edge.get("source"), str) or not isinstance(edge.get("target"), str):
            raise HTTPException(400, "Invalid workflow edge.")
        if edge["source"] not in ids or edge["target"] not in ids:
            raise HTTPException(400, "Unknown workflow node.")


def validate_fields(path, data):
    string_fields = {"role", "body", "action", "admin_response", "comment", "description", "key_name", "key_value", "message", "name", "notes", "prompt", "proof_hash", "provider", "reviewer", "status", "tool", "account_id", "agent_id", "author", "campaign", "category", "client", "ip", "key", "kind", "method", "parent_key", "pay_to", "payout_address", "protocol", "reason", "to_address", "token", "tx_id", "url", "author_wallet", "google_client_id", "title", "wallet_address"}
    for key in string_fields & data.keys():
        if data[key] is not None:
            text(data[key], key, 100000 if key in ("message", "description", "comment", "prompt", "admin_response", "notes") else 4000)
    if "arguments" in data and not isinstance(data["arguments"], dict):
        raise HTTPException(400, "arguments must be an object.")
    if "resource_id" in data and data["resource_id"] is not None:
        integer(data["resource_id"], "resource_id", -1000, 2**31-1)
    if "rating" in data and data["rating"] is not None:
        integer(data["rating"], "rating", 1, 5)
    if "price_usdc" in data:
        integer(data["price_usdc"], "price_usdc", 0)
    if "price_sats" in data:
        integer(data["price_sats"], "price_sats", 0)
    for key in ("byo_api_keys", "is_paid", "require_google_auth"):
        if key in data and type(data[key]) is not bool:
            raise HTTPException(400, f"{key} must be a boolean.")
    if "networks" in data and (not isinstance(data["networks"], list) or len(data["networks"]) > 20 or any(not isinstance(n, str) for n in data["networks"])):
        raise HTTPException(400, "Invalid networks.")
    if "details" in data and not isinstance(data["details"], dict):
        raise HTTPException(400, "details must be an object.")
    if path.startswith(("/admin/api/auth/", "/admin/api/v2/auth/", "/admin/api/users")):
        for key in ("username", "password", "current_password", "new_password", "name", "role"):
            if key in data:
                text(data[key], key, 1024 if "password" in key else 200)
        if "role" in data and data["role"] not in ("superadmin", "admin", "operator", "viewer"):
            raise HTTPException(400, "Invalid administrator role.")
        if "active" in data and (type(data["active"]) is not int or data["active"] not in (0,1)):
            raise HTTPException(400, "active must be 0 or 1.")
    if path.startswith("/admin/api/payments/"):
        for key in ("amount", "amount_credits"):
            if key in data:
                integer(data[key], key)
        if "ttl_seconds" in data:
            number(data["ttl_seconds"], "ttl_seconds", 60, 30*86400)
        for key in ("account_id", "agent_id", "tx_id", "to_address", "payout_address", "reason"):
            if key in data:
                text(data[key], key, 500)
    if path.startswith("/admin/api/security/"):
        if "enabled" in data and type(data["enabled"]) is not bool:
            raise HTTPException(400, "enabled must be a boolean.")
        if "multiplier" in data:
            number(data["multiplier"], "multiplier", 0.1, 10)
        if data.get("duration") is not None:
            number(data["duration"], "duration", 1, 365*86400)
        if "ip" in data:
            import ipaddress
            try:
                ipaddress.ip_address(data["ip"])
            except (ValueError, TypeError):
                raise HTTPException(400, "Invalid IP address.")
    if "nodes" in data or "edges" in data:
        validate_graph(data.get("nodes", []), data.get("edges", []))
    if "timeout_seconds" in data:
        number(data["timeout_seconds"], "timeout_seconds", 2, 30)
    if "steps" in data and (not isinstance(data["steps"], list) or len(data["steps"]) > 100):
        raise HTTPException(400, "Workflow limit: 100 steps.")


class AdminRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def secured(request: Request):
            if not request.url.path.startswith("/admin/"):
                return await handler(request)
            if len(request.scope.get("query_string", b"")) > 8192:
                raise HTTPException(414, "Admin query exceeds limit.")
            check_origin(request)
            if not _slots.acquire(blocking=False):
                raise HTTPException(503, "Admin service busy.", headers={"Retry-After":"5"})
            try:
                if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                    body = bytearray()
                    try:
                        async with asyncio.timeout(10):
                            async for chunk in request.stream():
                                body.extend(chunk)
                                if len(body) > MAX_BODY_BYTES:
                                    raise HTTPException(413, "Admin request exceeds 256 KiB.")
                    except TimeoutError:
                        raise HTTPException(408, "Request body timed out.")
                    request._body = bytes(body)
                    if body:
                        try:
                            def bad_constant(value):
                                raise ValueError("Non-finite number")
                            def finite_float(value):
                                result = float(value)
                                if not math.isfinite(result):
                                    raise ValueError("Non-finite number")
                                return result
                            data = json.loads(body, parse_constant=bad_constant, parse_float=finite_float)
                            if not isinstance(data, dict):
                                raise ValueError("Object required")
                        except (ValueError, UnicodeError, RecursionError):
                            raise HTTPException(400, "A valid JSON object is required.")
                        request._json = data
                        validate_fields(request.url.path, data)
                if inspect.iscoroutinefunction(self.endpoint):
                    try:
                        async with asyncio.timeout(ASYNC_OPERATION_SECONDS):
                            return await handler(request)
                    except TimeoutError:
                        raise HTTPException(504, "Admin operation timed out.")
                return await handler(request)
            finally:
                _slots.release()
        async def contracted(request):
            try:
                response = await secured(request)
                if request.url.path.startswith('/admin/api/v2/'):
                    response.headers['Cache-Control'] = 'no-store'
                    response.headers.setdefault('Vary','Authorization, X-Dashboard')
                    if response.status_code >= 400 and hasattr(response,'body'):
                        try:
                            body=json.loads(response.body)
                        except (ValueError,TypeError):
                            body={}
                        if isinstance(body,dict) and 'error_code' not in body:
                            message=body.get('detail') if isinstance(body.get('detail'),str) else '요청을 처리하지 못했습니다.'
                            headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-type')}
                            return JSONResponse({**body,'error_code':'REQUEST_FAILED','message_ko':message,
                                                 'retryable':request.method in ('GET','HEAD') and response.status_code in (429,503,504)},status_code=response.status_code,headers=headers)
                return response
            except (HTTPException, RequestValidationError) as exc:
                if not request.url.path.startswith('/admin/api/v2/'):
                    raise
                status = exc.status_code if isinstance(exc, HTTPException) else 422
                codes = {400:'INVALID_REQUEST',401:'AUTH_REQUIRED',403:'FORBIDDEN',404:'NOT_FOUND',
                         409:'REVISION_CONFLICT',413:'REQUEST_TOO_LARGE',422:'INVALID_REQUEST',
                         428:'PASSWORD_CHANGE_REQUIRED',429:'RATE_LIMITED',503:'TEMPORARILY_UNAVAILABLE',504:'TIMEOUT'}
                message = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else '요청 형식과 값을 확인하세요.'
                return JSONResponse({'error_code': codes.get(status,'REQUEST_FAILED'), 'message_ko': message,
                                     'detail': message, 'retryable': request.method in ('GET','HEAD') and status in (429,503,504)}, status_code=status,
                                    headers={**(getattr(exc,'headers',None) or {}),'Cache-Control':'no-store','Vary':'Authorization, X-Dashboard'})
            except Exception:
                if not request.url.path.startswith('/admin/api/v2/'):
                    raise
                logging.getLogger(__name__).error('Renewal operation unavailable; inspect the scoped operational trace.')
                message='운영 정보를 지금 확인할 수 없습니다. 변경 요청은 자동으로 재시도하지 마세요.'
                return JSONResponse({'detail':message,'message_ko':message,'error_code':'TEMPORARILY_UNAVAILABLE',
                                     'retryable':request.method in ('GET','HEAD')},status_code=503,
                                    headers={'Cache-Control':'no-store','Vary':'Authorization, X-Dashboard'})
        return contracted

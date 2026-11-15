"""Routes of the AgentValCon Verified Registry (official MCP Registry API v0.1 shape, read only).

Base URL for organizations (GitHub Copilot "MCP Registry URL", VS Code ``chat.mcp.gallery.serviceUrl``):
``https://agentconcierge.biz/registry/verified`` — clients append ``/v0.1/servers``.

Answers come from the snapshot file in memory (verified_registry.SnapshotIndex); there is no database read here.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from .broker.server import RateLimiter
from . import verified_registry as R

BASE = "/registry/verified/v0.1"
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type"}
CACHE = "public, max-age=300"


def router_for(index: R.SnapshotIndex | None = None) -> APIRouter:
    index = index or R.default_index()
    router = APIRouter()
    limiter = RateLimiter(60)

    def client(request: Request) -> str:
        return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")

    def reply(data, status=200, etag=None):
        headers = {**CORS, "Cache-Control": CACHE if status == 200 else "no-store"}
        if etag:
            headers["ETag"] = etag
        return JSONResponse(data, status_code=status, headers=headers)

    def error(status, message, extra=None):
        # The official API answers {"error": "..."}; title/status/detail add the usual problem fields beside it.
        return JSONResponse({"error": message, "title": message, "status": status, "detail": message},
                            status_code=status, headers={**CORS, "Cache-Control": "no-store", **(extra or {})})

    def guard(request: Request):
        if not limiter.allow(client(request)):
            return error(429, "Too many requests", {"Retry-After": "60"})
        snapshot = index.current()
        if snapshot is None:
            return error(503, "The verified registry is preparing", {"Retry-After": "300"})
        if request.headers.get("if-none-match") == snapshot.etag:
            return Response(status_code=304, headers={**CORS, "Cache-Control": CACHE, "ETag": snapshot.etag})
        return snapshot

    @router.options(BASE + "/{rest:path}", include_in_schema=False)
    def preflight(rest: str):
        return Response(status_code=204, headers={**CORS, "Access-Control-Max-Age": "86400"})

    @router.get(BASE + "/servers", include_in_schema=False)
    def servers(request: Request, cursor: str | None = None, limit: str | None = None, search: str | None = None,
                version: str | None = None, updated_since: str | None = None, include_deleted: str | None = None):
        snapshot = guard(request)
        if not isinstance(snapshot, R.SnapshotIndex):
            return snapshot
        try:
            page = R.list_page(snapshot, cursor=cursor, limit=limit, search=search, version=version,
                               updated_since=updated_since, include_deleted=str(include_deleted).lower() == "true")
        except R.InvalidCursor:
            return error(400, "Invalid cursor parameter")
        except ValueError as exc:
            return error(400, str(exc))
        return reply(page, etag=snapshot.etag)

    # serverName arrives URL-encoded (io.github.x%2Fname); after decoding it holds exactly one '/'.
    @router.get(BASE + "/servers/{rest:path}", include_in_schema=False)
    def server(request: Request, rest: str):
        snapshot = guard(request)
        if not isinstance(snapshot, R.SnapshotIndex):
            return snapshot
        match = re.fullmatch(r"(?P<name>[^/]+/[^/]+)/versions(?:/(?P<version>[^/]+))?", rest)
        if not match:
            return error(404, "Server not found")
        name, wanted = match["name"], match["version"]
        found = R.versions(snapshot, name) if wanted is None else R.version(snapshot, name, wanted)
        if found is None:
            return error(404, "Server not found")
        return reply(found, etag=snapshot.etag)

    return router

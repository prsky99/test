"""Renewal aliases reuse private workspace endpoints and add reasoned staff audit.

No customer-organization access or global administrator privilege substitutes for
membership. Only the reviewed specialist families are mounted here.
"""
import re
import json
import logging
import time
import secrets
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .gateway import admin_auth
from .workspace_service import WorkspaceRoute

BASE = '/admin/api/workflow-workspaces'
RENEWAL = '/admin/api/v2/workspace-panels'
FAMILIES = ('typed-flows', 'reliability/typed', 'evidence', 'quality', 'machine-updates', 'lifecycle', 'remote-a2a', 'protocol-conformance', 'reliability', 'sdk-lifecycle', 'support-outcomes', 'advancement', 'product-composer', 'provider-claims')


def eligible(tail):
    """Expose only reviewed specialist families; other draft execution stays private."""
    return (tail == 'customers' or tail in {'app-factory/' + name for name in ('options', 'reviews', 'plan-reviews', 'intent-reviews', 'model-proposals', 'commits')}
            or any(tail == f or tail.startswith(f + '/') for f in FAMILIES)
            or bool(re.fullmatch(r'drafts/\{[^/{}]+\}/snapshots/\{[^/{}]+\}/(?:release-v2|product-test)(?:/.*)?', tail)))


def router_for(store, source, *, staff_core=False, catalog_tools=False):
    """Copy only existing endpoints, preserving their dependency/authorization closures."""
    router = APIRouter()

    def audit(request, reason, correlation, status):
        with store.tx() as db:
            user = admin_auth.get_session_user(db, request.headers.get('authorization', '')[7:])
            if not user or user.get('password_change_required'):
                raise HTTPException(401, 'A current individual staff session is required.')
            db.execute("""INSERT INTO admin_audit_logs (at, username, role, action, action_name, target, ip, status, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (time.time(), user['username'], user['role'],
                'CATALOG_TOOL_CHANGE' if catalog_tools else 'WORKSPACE_PANEL_CHANGE', '카탈로그 도구 변경' if catalog_tools else '전문 패널 변경 요청', request.url.path, None, status,
                json.dumps({'reason': reason, 'correlation': correlation}, ensure_ascii=False)))

    class ReasonedRoute(WorkspaceRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def reviewed(request: Request):
                if catalog_tools:
                    from .workflow_publication_service import no_store, same_origin
                    from fastapi.responses import JSONResponse
                    if (not same_origin(request) or request.headers.get('x-dashboard') != '1'
                            or not re.fullmatch(r'Bearer [a-f0-9]{64}', request.headers.get('authorization',''))):
                        return JSONResponse({'detail':'개인 최고관리자 세션이 필요합니다.'},status_code=401,headers=no_store())
                    with store.tx() as db:
                        user = admin_auth.get_session_user(db,request.headers['authorization'][7:])
                    if not user or user.get('password_change_required'):
                        return JSONResponse({'detail':'현재 개인 세션이 필요합니다.'},status_code=401,headers=no_store())
                    privileged = request.url.path.startswith(tuple('/admin/api/v2/catalog-tools' + p for p in ('/credentials','/connections','/capability-contracts','/actions','/payments','/rag')))
                    if user['role'] not in (('superadmin',) if privileged else ('superadmin','admin')):
                        return JSONResponse({'detail':'현재 작업에 필요한 관리자 권한이 없습니다.'},status_code=403,headers=no_store())
                if request.method == 'GET':
                    return await handler(request)
                # Authenticate and apply the existing origin boundary before recording intent.
                from .workflow_publication_service import no_store, same_origin
                from fastapi.responses import JSONResponse
                if (not same_origin(request) or request.headers.get('x-dashboard') != '1'
                        or not re.fullmatch(r'Bearer [a-f0-9]{64}', request.headers.get('authorization', ''))):
                    return JSONResponse({'detail': 'Use a same-origin individual staff session.'}, status_code=401, headers=no_store())
                raw = request.headers.get('x-admin-reason', '')
                reason = unquote(raw) if len(raw) <= 3600 else ''
                if not 4 <= len(reason.strip()) <= 300 or not reason.isprintable():
                    return JSONResponse({'detail': '변경 사유를 4~300자로 입력하세요.'}, status_code=400, headers=no_store())
                request.state.audit_reason = reason.strip()
                correlation = 'panel_' + secrets.token_hex(12)
                try:
                    await run_in_threadpool(audit, request, reason.strip(), correlation, 'REQUESTED')
                except HTTPException as error:
                    return JSONResponse({'detail': error.detail}, status_code=error.status_code, headers=no_store())
                except Exception:
                    return JSONResponse({'detail': '감사 기록을 저장하지 못해 요청을 실행하지 않았습니다.'}, status_code=503, headers=no_store())
                response = await handler(request)
                # Domain records remain authoritative if the session was revoked during execution.
                try:
                    await run_in_threadpool(audit, request, reason.strip(), correlation,
                                            'SUCCESS' if response.status_code < 400 else 'FAILED')
                except Exception:
                    logging.getLogger(__name__).warning('Specialist completion audit unavailable; consult domain audit and request intent.')
                    response.headers['X-Admin-Audit-State'] = 'pending'
                return response
            return reviewed

    for route in source.routes:
        if not isinstance(route, APIRoute):
            continue
        if catalog_tools:
            edge_test = re.fullmatch(r'/admin/api/v2/gateway/edge-test/(prepare|finish)', route.path)
            allowed = (route.path in ('/admin/api/register','/admin/api/register/inspect','/admin/api/test/execute','/admin/api/test/examples','/admin/api/test/agents','/admin/api/test-reports','/admin/api/test-reports/existing','/admin/api/capability-contracts','/admin/api/credentials','/admin/api/actions/crawl','/admin/api/actions/rescan','/admin/api/overview','/admin/api/owned-data/github-issues/search')
                or bool(re.fullmatch(r'/admin/api/(?:test/agents/\{[^/{}]+\}/spec|test-reports/\{[^/{}]+\}|connections/\{[^/{}]+\}(?:/contracts/\{[^/{}]+\}(?:/test)?)?|credentials/\{[^/{}]+\})',route.path)))
            allowed |= route.path in ('/admin/api/payments/overview','/admin/api/payments/ledger','/admin/api/payments/clearinghouse','/admin/api/payments/accounts') and route.methods == {'GET'}
            if not allowed and not edge_test:
                continue
            target = ('/admin/api/v2/catalog-tools/test/edge/' + edge_test[1] if edge_test else
                      '/admin/api/v2/catalog-tools' + route.path[len('/admin/api'):])
        elif staff_core:
            if route.path != BASE and not route.path.startswith(BASE + '/'):
                continue
            target = '/admin/api/v2/staff-workspaces' + route.path[len(BASE):]
        else:
            if not route.path.startswith(BASE + '/'):
                continue
            tail = route.path[len(BASE) + 1:]
            parts = tail.split('/', 1)
            if len(parts) != 2 or not eligible(parts[1]):
                continue
            target = RENEWAL + route.path[len(BASE):]
        router.add_api_route(target, route.endpoint, methods=route.methods,
                             dependencies=route.dependencies, route_class_override=ReasonedRoute,
                             include_in_schema=False, name='renewal_' + route.name)
    return router

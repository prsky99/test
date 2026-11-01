"""Explicit console boundaries; new routes never inherit machine/viewer access."""
import os

from fastapi import HTTPException

ROLES = ('superadmin', 'admin', 'operator', 'viewer')
SELF_SERVICE = frozenset({
    '/admin/api/auth/me', '/admin/api/auth/logout', '/admin/api/auth/change-password',
    '/admin/api/v2/auth/me', '/admin/api/v2/auth/logout', '/admin/api/v2/auth/change-password',
})
# Existing monitoring readers can continue; customer data and all writes require staff.
MACHINE_READS = frozenset({'/admin/api/overview', '/admin/api/timeseries'})
VIEWER_READS = frozenset({
    '/admin/api/v2/home/bootstrap', '/admin/api/v2/home/changes', '/admin/api/v2/home/work',
    '/admin/api/v2/gateway/summary', '/admin/api/v2/public/summary',
    '/admin/api/v2/system/storage', '/admin/api/v2/system/retention',
    '/admin/api/v2/system/retention/preview', '/admin/api/v2/console/services',
})


def enforce_staff_scope(user, method, path):
    if user.get('role') not in ROLES:
        raise HTTPException(403, '이 작업에 필요한 관리자 권한이 없습니다.')
    if user.get('password_change_required') and path not in SELF_SERVICE:
        raise HTTPException(428, '초기 비밀번호를 변경한 뒤 다시 로그인하세요.')
    if user.get('role') == 'viewer' and path not in SELF_SERVICE:
        if method != 'GET' or path not in VIEWER_READS:
            raise HTTPException(403, '조회자는 비식별 집계만 확인할 수 있습니다.')


def aggregate_overview(value):
    """Do not forward collector logs, source labels, configuration or action diagnostics."""
    def numbers(obj):
        return {k: v for k, v in (obj or {}).items() if type(v) in (int, float, bool) or v is None}
    catalog = numbers(value.get('public_catalog'))
    catalog['by_protocol'] = [{'kind': row['kind'], 'n': row.get('n', 0)}
        for row in value.get('public_catalog', {}).get('by_protocol', [])
        if row.get('kind') in ('a2a', 'mcp', 'x402')]
    return {'public_catalog': catalog, 'health': numbers(value.get('health')),
            'evaluation': {'grades': [{'grade': row['grade'], 'n': row.get('n', 0)}
                for row in value.get('evaluation', {}).get('grades', [])
                if row.get('grade') in ('A', 'B', 'C', 'D', 'F', 'static')]},
            'needs': numbers(value.get('needs')), 'captured_at': value.get('captured_at')}


def development_banner(html):
    if os.environ.get('AGENTCON_ADMIN_DEV') == '1' and os.environ.get('DEPLOYMENT_MODE') != 'production':
        return html.replace('<header', '<p role="status">개발 모드 · 로컬 조회만 허용됩니다. 변경 작업은 개인 로그인이 필요합니다.</p><header', 1)
    return html

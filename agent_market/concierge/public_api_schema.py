"""Explicit public OpenAPI surface; private routes remain callable by policy."""
from fastapi.openapi.utils import get_openapi
import copy

_PUBLIC = frozenset(('/', '/chat', '/me', '/unsubscribe', '/a2a', '/mcp',
    '/api/overview', '/api/insights', '/api/explore', '/api/agents/{rid}',
    '/api/connections/{agent_ref}', '/api/test/presets', '/api/test/execute',
    '/api/gateway/{kind}/{rid}', '/api/register', '/api/register/inspect', '/api/register/recent',
    '/api/contact/submit', '/api/privacy/opt-out',
    '/api/workflows/templates', '/api/workflows/templates/{template_id}',
    '/api/workflows/{template_id}/webapp', '/api/workflows/run',
    '/api/workflows/runs/{run_id}', '/api/workflows/runs/{run_id}/cancel',
    '/api/task-updates', '/api/task-updates/browser-config', '/api/task-updates/browser-confirm',
    '/api/task-updates/stop', '/api/task-updates/{watch_id}/action', '/api/task-updates/{watch_id}/events',
    '/api/agent/v1/discover', '/api/agent/v1/resume', '/api/agent/v1/report', '/api/agent/v1/check', '/api/feed/verified.json',
    '/api/ad-coin/v2/sponsored/offer'))
# Agent ad plan (A), PM 11-14 decision (a): edge-cached REST answers (/api/explore, /api/roles/<role>/best) carry no ad; a REST
# agent that wants the one labelled offer asks the ad route itself (listed when the AD Coin router is mounted).
SPONSORED_OFFER = '/api/ad-coin/v2/sponsored/offer'
ADS_NOTE = ('Ads: REST answers carry no ads. For the one offer labelled Sponsored for a task category, call GET '
            + SPONSORED_OFFER + '?category=<site category>&surface=rest; ads=none or the header Ads: none returns null. '
            'An offer never changes results, grades or their order.')
_DOCUMENTED = ('/api/agent/v1/entry', '/api/agent/v1/openapi.json', '/api/agent/v1/badge/{resource_id}.svg')


def install(app):
    app.openapi_schema = None
    def public_openapi():
        if app.openapi_schema is not None:
            return app.openapi_schema
        # FastAPI can defer included-router expansion. Generate in memory,
        # then publish only explicit paths and their reachable definitions.
        full = get_openapi(title='AgentValCon public API', version='1.0.0', description=ADS_NOTE, routes=app.routes)
        paths = {path:value for path,value in full['paths'].items() if path in _PUBLIC}
        # llms.txt links the entry, badge and discovery-schema documents; their routes stay
        # out of FastAPI's generated paths, so reuse the discovery contract's definitions.
        from ..agent_access.contracts import openapi_profile
        try:
            documented = openapi_profile(full)['paths']
        except KeyError:  # an app without the discovery routes publishes none of them
            documented = {}
        for path in _DOCUMENTED:
            if path in documented:
                paths[path] = copy.deepcopy(documented[path])
        components, pending = {}, [paths]
        while pending:
            value = pending.pop()
            if isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, dict):
                ref = value.get('$ref', '')
                if isinstance(ref, str) and ref.startswith('#/components/'):
                    category, name = ref[len('#/components/'):].split('/', 1)
                    name = name.replace('~1','/').replace('~0','~')
                    section = components.setdefault(category,{})
                    if name not in section:
                        section[name] = copy.deepcopy(full['components'][category][name])
                        pending.append(section[name])
                security_items = value.get('security', [])
                for security in security_items if isinstance(security_items, list) else []:
                    if not isinstance(security, dict):
                        continue
                    for name in security:
                        scheme = full.get('components',{}).get('securitySchemes',{}).get(name)
                        if scheme is not None:
                            components.setdefault('securitySchemes',{})[name] = copy.deepcopy(scheme)
                pending.extend(v for k,v in value.items() if k != '$ref')
        app.openapi_schema = {'openapi':full['openapi'],'info':full['info'],
                              'paths':paths,'components':components}
        return app.openapi_schema
    app.openapi = public_openapi

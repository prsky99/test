"""Resolve existing public execution authority into a short-lived Edge binding."""
import json

from ..capability_registry import Registry, full_tools, digest
from ..collector import usage
from ..concierge.execution_policy import admit_tool, validate_arguments, resolve_a2a
from ..concierge.http_security import validate_public_url
from .config import EdgeError, Provider, https_url

PROFILE = 'catalog-public-v1'


def mcp_revision(resource):
    """Use a registered handshake observation only as a negotiation hint."""
    guide = resource.get('usage_guide')
    try:
        guide = json.loads(guide) if isinstance(guide, str) else guide
    except (ValueError, TypeError):
        return None
    version = guide.get('protocol_version') if isinstance(guide, dict) else None
    return version if version in ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25') else None


def provider_for(service, resource):
    kind = resource['kind']
    if kind not in service.config.catalog_protocols:
        raise EdgeError('PROFILE_UNAVAILABLE', 400)
    endpoint, spec = resource['url'], '0.3'
    try:
        if kind == 'a2a':
            target = resolve_a2a(resource, service.front.courier, public=True)
            endpoint, spec = target['url'], '1.0' if target.get('v1') else '0.3'
            https_url(endpoint)
        else:
            # Queries in registered HTTP resources remain unchanged.
            from urllib.parse import urlsplit
            u = urlsplit(endpoint)
            https_url(u._replace(query='').geturl())
    except EdgeError:
        raise EdgeError('PROFILE_UNAVAILABLE', 400) from None
    validate_public_url(endpoint)
    version = Registry(service.store).current(resource)
    return Provider(resource['id'], version['id'], endpoint, 'json', False, kind, spec, True)


def payload_for(provider, value, resource):
    if provider.kind == 'a2a':
        from .service import message_input
        return message_input(value)
    if provider.kind == 'x402':
        if type(value) is not dict or value != {'action': 'probe'}:
            raise EdgeError('POLICY_DENIED', 400)
        return value
    if (type(value) is not dict or set(value) != {'tool', 'arguments'} or type(value['tool']) is not str
            or type(value['arguments']) is not dict):
        raise EdgeError('INVALID_INPUT', 400)
    if not resource.get('usage_tools_hash'):
        raise EdgeError('PROFILE_UNAVAILABLE', 400)
    admit_tool(resource, value['tool'], value['arguments'])
    # Large discovery contracts stay on the established Origin profile.
    source = resource.get('usage_full_tools') or resource.get('usage_tools') or '[]'
    if len(source if isinstance(source, str) else json.dumps(source)) > 60000:
        raise EdgeError('PROFILE_UNAVAILABLE', 400)
    if resource.get('usage_full_hash'):
        try:
            full = full_tools(json.loads(source) if isinstance(source, str) else source)
            # The compact pin hashes the stored survey, not the complete
            # execution contract returned by tools_for().
            registered = resource.get('usage_tools') or []
            registered = json.loads(registered) if isinstance(registered, str) else registered
            if (digest(full) != resource['usage_full_hash']
                    or usage.tools_hash(registered) != resource['usage_tools_hash']
                    or usage.tools_hash(usage.compact_tools(full)) != usage.tools_hash(sorted(registered, key=lambda t: t['name']))):
                raise ValueError('Registered schema hash changed')
            next(t for t in full if t['name'] == value['tool'])
        except (ValueError, TypeError, StopIteration):
            raise EdgeError('SCHEMA_CHANGED', 409) from None
        admit_tool({**resource, 'usage_tools': full}, value['tool'], value['arguments'])
    return value


def review_mcp(service, run_id, attempt, tools, value):
    from .state import transaction, rows
    with transaction(service.store, readonly=True) as db:
        found = rows(db, 'run', (run_id,))
    if not found or found[0]['attempt'] != attempt or found[0]['state'] != 'dispatch_reserved':
        raise EdgeError('ATTEMPT_CHANGED', 409)
    provider, resource = service.admitted(found[0]['resource_id'])
    if provider.kind != 'mcp' or provider.version_id != found[0]['version_id']:
        raise EdgeError('SCHEMA_CHANGED', 409)
    from .service import input_digest
    payload = payload_for(provider, value, resource)
    if input_digest(provider, payload) != found[0]['input_hash']:
        raise EdgeError('INPUT_CHANGED', 409)
    try:
        full = full_tools(tools)
        valid = usage.tools_hash(usage.compact_tools(tools)) == resource['usage_tools_hash']
        valid = valid and (not resource.get('usage_full_hash') or digest(full) == resource['usage_full_hash'])
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid:
        version = Registry(service.store).current(resource, create=False)
        Registry(service.store).record(version, scope='execution', outcome='failed', started=found[0]['created'],
                                       finished=service.clock(), code='SCHEMA_CHANGED')
        raise EdgeError('SCHEMA_CHANGED', 409)
    remote = next((tool for tool in tools if tool['name'] == payload['tool']), None)
    if remote is None:
        raise EdgeError('SCHEMA_CHANGED', 409)
    validate_arguments(remote, payload['arguments'])
    return {'approved': True}

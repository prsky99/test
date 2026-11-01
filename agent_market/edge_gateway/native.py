"""Use ticketed Edge delivery inside an already authorized Native node.

The durable parent fence is consumed before sending the one HTTP request. An
ambiguous or failed delivery never returns an instruction to execute on Origin.
Native orchestration still validates and persists node output. Direct delivery
uses an inbound signed receipt rather than downloading that output from Edge.
"""
import hashlib
import hmac
import re
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qsl

from ..capability_registry import Registry
from ..concierge.execution_policy import ExecutionDenied
from ..concierge.recommendation_security import secret_name
from ..concierge.http_security import bounded_client, OutboundBudget
from ..observability import current_attempt, provider_dispatch
from ..workflow_persistence import has_dispatch_guard
from .auth import canonical, derived, digest
from .config import EdgeError, load


def credential_input(value, depth=0):
    if depth > 15:
        return True
    if isinstance(value, dict):
        return any(secret_name(k) or credential_input(v, depth + 1) for k, v in value.items())
    if isinstance(value, list):
        return any(credential_input(v, depth + 1) for v in value)
    if isinstance(value, str) and '://' in value:
        try:
            url = urlsplit(value)
            if url.username is not None or any(secret_name(k) for k, _ in parse_qsl(url.query)):
                return True
        except ValueError:
            return True
    return isinstance(value, str) and bool(re.search(
        r'(?i)\b(?:Bearer|Basic)\s+|\b(?:sk-|ghp_|AIza|vt_|eyJ)[A-Za-z0-9_-]{12,}', value))


def service_for(store, courier=None):
    service = getattr(store, '_edge_gateway_service', None)
    if service is not None:
        return service
    # A queue-only role has no Front object. Use the same explicit configuration
    # and existing provisioned tables, without migrations or a competing server.
    config = load()
    if config is None:
        return None
    from ..concierge.managed_gateway import ManagedGateway
    from .service import Service
    front = SimpleNamespace(store=store, courier=courier)
    front.managed_gateway = ManagedGateway(front)
    return Service(front, config)


def execute(store, resource, payload, *, scope=None, courier=None, http=None):
    """Return None only before network dispatch, allowing existing Native IO."""
    from ..owned_data_agents.dispatch import is_owned
    if is_owned(resource):
        # First-party capabilities are verified local bindings. Edge HTTP would
        # send them back through our public ingress rather than their handler.
        return None
    if not has_dispatch_guard() or credential_input(payload):
        return None
    attempt = current_attempt(store)
    scope = scope or (attempt.id if attempt else None)
    if type(scope) is not str or not scope or len(scope) > 240:
        return None
    try:
        service = service_for(store, courier)
        if service is not None and service.available:
            from .state import transaction,rows
            saved_identity=hmac.new(derived(service.config.key,'edge-native-node-v1'),scope.encode(),hashlib.sha256).hexdigest()
            saved_principal=hmac.new(derived(service.config.key,'edge-native-principal-v1'),saved_identity.encode(),hashlib.sha256).hexdigest()
            with transaction(store,readonly=True) as db:previous=rows(db,'idempotency',(saved_principal,digest(saved_identity)))
            if previous and previous[0]['state']!='prepared':raise EdgeError('ALREADY_CLAIMED',409)
        if (service is None or not service.available or service.config.canary_principal
                or not service.config.native_node_delivery):
            return None
        if service.summary()['preferred_backend'] != 'worker':
            return None
        if resource.get('kind') not in ('a2a', 'mcp','x402') or resource.get('kind')=='x402' and payload!={'action':'probe'}:
            return None
        from .catalog import payload_for
        provider, fresh = service.admitted(resource['id'])
        expected = Registry(store).current(resource)
        if not expected or provider.version_id != expected['id']:
            raise EdgeError('SCHEMA_CHANGED', 409)
        payload = payload_for(provider, payload, fresh)
        if len(canonical(payload).encode()) > 7900:
            return None
        identity = hmac.new(derived(service.config.key, 'edge-native-node-v1'),
                            scope.encode(), hashlib.sha256).hexdigest()
        principal = hmac.new(derived(service.config.key, 'edge-native-principal-v1'),
                             identity.encode(), hashlib.sha256).hexdigest()
        grant = service.prepare(principal, service.config.origin, {
            'resource_id': resource['id'], 'input': payload, 'idempotency_key': identity,
            'run_authority': True, 'sharing_authority': True})
        if not grant['stream_path'].startswith('/api/edge-gateway/'):
            return None
        row = service.authorized(grant['access_token'], service.config.origin, grant['run_id'])
        if row['version_id'] != expected['id']:
            raise EdgeError('SCHEMA_CHANGED', 409)
        if row['state'] != 'prepared':
            raise EdgeError('ALREADY_CLAIMED', 409)
    except EdgeError as exc:
        if exc.code in ('SCHEMA_CHANGED', 'INPUT_CHANGED', 'ALREADY_CLAIMED', 'IDEMPOTENCY_CONFLICT'):
            code = 'SCHEMA_CHANGED' if exc.code == 'SCHEMA_CHANGED' else 'POLICY_DENIED'
            raise ExecutionDenied('The saved execution authority changed.', error_code=code) from None
        return None

    # No caller cookies, user identity, Provider URL, private session or platform
    # shared secret is sent. The short-lived ticket binds one run and input.
    client = bounded_client(http, allow_private=False, limit=65536, budget=OutboundBudget(12))
    from . import result_transport
    receipt = resource['kind']!='x402' and service.config.direct_result_delivery and result_transport.available(store)
    try:
        provider_dispatch()
    except BaseException:
        client.close()
        raise
    try:
        client.client.cookies.clear()
        response = client.post(service.config.origin + grant['stream_path'], json=payload,
            headers={'Content-Type': 'application/json', 'Origin': service.config.origin,
                     'Authorization': 'Bearer ' + grant['access_token'],
                     'X-Edge-Result-Format': 'receipt' if receipt else 'json'})
        value = response.json()
        if receipt:
            if (response.status_code != 200 or type(value) is not dict
                    or set(value) != {'run_id', 'state', 'wire_hash', 'backend'}
                    or value['run_id'] != grant['run_id'] or value['state'] != 'succeeded'
                    or value['backend'] not in ('worker', 'origin')):
                raise ValueError('Unconfirmed result receipt')
            saved = result_transport.load_result(service, grant['run_id'])
            if value['wire_hash'] != saved['wire_hash']:
                raise ValueError('Result receipt mismatch')
            result_transport.link_parent(service, grant['run_id'])
            return {'ok': True, 'result': saved['output'], 'hash_verified': True,
                    'delivery_backend': value['backend']}
        if (response.status_code != 200 or type(value) is not dict
                or set(value) != {'run_id', 'state', 'output', 'backend'} or value['run_id'] != grant['run_id']
                or value['backend'] not in ('worker', 'origin')
                or value['state'] not in (('succeeded','failed') if resource['kind']=='x402' else ('succeeded',)) or type(value['output']) is not dict):
            raise ValueError('Unconfirmed Edge result')
        return {'ok': True, 'result': value['output'], 'hash_verified': True,
                'delivery_backend': value['backend']}
    except ExecutionDenied:
        raise
    except Exception:
        if receipt:
            try:
                saved = result_transport.load_result(service, grant['run_id'])
                result_transport.link_parent(service, grant['run_id'])
                return {'ok': True, 'result': saved['output'], 'hash_verified': True,
                        'delivery_backend': saved['backend']}
            except Exception:
                pass
        return {'ok': False, 'error': 'The execution outcome could not be confirmed.',
                'error_code': 'UPSTREAM_PROTOCOL', 'hash_verified': False}
    finally:
        client.close()

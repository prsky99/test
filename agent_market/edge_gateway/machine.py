"""Ticketed public MCP execution; an accepted request never becomes a second IO.

The existing durable Edge run owns dispatch, including quota-driven Origin
delivery. Credentials, paid calls and local owned handlers retain their existing
authorized paths before a Ticket is created.
"""
import hashlib
import hmac
import re
import secrets
import time

from ..capability_registry import Registry
from ..concierge.execution_policy import admit_tool, ExecutionDenied
from ..concierge.http_security import bounded_client, OutboundBudget
from ..observability import journal_for, attempt_scope, provider_dispatch
from .auth import canonical, derived, digest
from .config import EdgeError
from .native import credential_input
from .state import rows, transaction


def refused(code='POLICY_DENIED', *, unknown=False):
    return {'ok': False, 'error': 'The execution outcome is unconfirmed.' if unknown else 'The execution request was refused.',
            'error_code': code, 'outcome': 'unknown' if unknown else 'denied', 'retry_safe': not unknown}


def execute(front, resource_id, tool, arguments, *, principal, idempotency_key=None, payment=None, http=None,
            prepare_only=False, stored_run=None):
    """None means pre-admission legacy IO; any accepted Ticket returns a result."""
    started = time.monotonic()
    if idempotency_key is not None and (type(idempotency_key) is not str
            or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', idempotency_key)):
        return refused('INVALID_INPUT')
    service = getattr(front.store, '_edge_gateway_service', None)
    def legacy():
        if stored_run is not None:
            return refused(unknown=True)
        # A rollout/profile change cannot turn an existing Ticket into new IO.
        if service is not None and service.available and idempotency_key is not None:
            if type(principal) is not str or not principal or len(principal) > 128:
                return refused()
            caller = hmac.new(derived(service.config.key, 'edge-machine-principal-v1'), principal.encode(), hashlib.sha256).hexdigest()
            identity = hmac.new(derived(service.config.key, 'edge-machine-request-v1'), idempotency_key.encode(), hashlib.sha256).hexdigest()
            try:
                with transaction(front.store, readonly=True) as db:
                    if rows(db, 'idempotency', (caller, digest(identity))):
                        return refused(unknown=True)
            except Exception:
                return refused('UPSTREAM_PROTOCOL', unknown=True)
        return None
    resource = front.store.resource(resource_id)
    from ..owned_data_agents.dispatch import is_owned
    if (not resource or is_owned(resource) or resource.get('kind') != 'mcp'
            or resource.get('price_usdc') or payment or credential_input(arguments)):
        return legacy()
    if (service is None or not service.available or not service.config.native_node_delivery
            or service.config.canary_principal):
        return legacy()
    if type(principal) is not str or not principal or len(principal) > 128:
        return refused()
    try:
        admit_tool(resource, tool, arguments)
        provider, fresh = service.admitted(resource_id)
        if provider.kind != 'mcp':
            return legacy()
        version = Registry(front.store).current(resource)
        if not version or provider.version_id != version['id']:
            return refused('SCHEMA_CHANGED')
        from .catalog import payload_for
        payload = payload_for(provider, {'tool': tool, 'arguments': arguments}, fresh)
        if len(canonical(payload).encode()) > 7900:
            return legacy()
    except (EdgeError, ExecutionDenied):
        # No Ticket exists; the established proxy reports exact legacy denials.
        return legacy()
    caller = hmac.new(derived(service.config.key, 'edge-machine-principal-v1'),
                      principal.encode(), hashlib.sha256).hexdigest()
    identity = hmac.new(derived(service.config.key, 'edge-machine-request-v1'),
                        (idempotency_key or secrets.token_hex(32)).encode(), hashlib.sha256).hexdigest()
    try:
        grant = service.prepare(caller, service.config.origin, {
            'resource_id': resource_id, 'input': payload, 'idempotency_key': identity,
            'run_authority': True, 'sharing_authority': True})
        path = grant['stream_path']
        if path not in (f'/api/edge-gateway/v1/runs/{grant["run_id"]}/stream',
                         f'/api/origin-gateway/v1/runs/{grant["run_id"]}/stream'):
            return refused(unknown=True)
        row = service.authorized(grant['access_token'], service.config.origin, grant['run_id'])
        if row['version_id'] != version['id']:
            return refused('SCHEMA_CHANGED', unknown=True)
        if stored_run is not None:
            if stored_run != grant['run_id']:
                return refused(unknown=True)
            from .result_transport import load_result, consume
            if row['state'] == 'failed':
                return {**refused('UPSTREAM_TOOL_ERROR'), 'outcome':'failed'} if consume(service,stored_run) else refused(unknown=True)
            if row['state'] != 'succeeded':
                return refused(unknown=True)
            saved = load_result(service, stored_run)
            if not consume(service, stored_run):
                return refused(unknown=True)
            return {'ok': True, 'result': saved['output'], 'hash_verified': True,
                    'transport_ok': True, 'protocol_valid': True, 'retry_safe': False,
                    'delivery_backend': row['backend'], 'latency_ms': 0}
        if row['state'] != 'prepared':
            return refused(unknown=True)
        if prepare_only:
            return {'_edge_plan': True, 'backend': row['backend'], **grant, 'input': payload}
    except EdgeError as exc:
        return refused('SCHEMA_CHANGED' if exc.code == 'SCHEMA_CHANGED' else 'POLICY_DENIED',
                       unknown=True)
    except Exception:
        # An idempotent request may already exist. Never bypass durable ownership.
        return refused('UPSTREAM_PROTOCOL', unknown=True)

    operation = journal_for(front.store).begin('execution', 'managed', resource_id=resource_id, proto='mcp')
    attempt = operation.attempt(resource_id)
    sent = False
    client = None
    try:
        client = bounded_client(http, allow_private=False, limit=65536, budget=OutboundBudget(12))
        with attempt_scope(attempt, finish_errors=False):
            provider_dispatch()
            client.client.cookies.clear()
            sent = True
            response = client.post(service.config.origin + path, json=payload,
                headers={'Content-Type': 'application/json', 'Origin': service.config.origin,
                         'Authorization': 'Bearer ' + grant['access_token'], 'X-Edge-Result-Format': 'json'})
            value = response.json()
            if (response.status_code != 200 or type(value) is not dict
                    or set(value) != {'run_id', 'state', 'output', 'backend'}
                    or value['run_id'] != grant['run_id'] or value['state'] != 'succeeded'
                    or value['backend'] not in ('worker', 'origin') or type(value['output']) is not dict):
                raise ValueError('Unconfirmed result')
        attempt.finish('succeeded'); operation.finish('succeeded')
        return {'ok': True, 'result': value['output'], 'hash_verified': True,
                'transport_ok': True, 'protocol_valid': True, 'retry_safe': False,
                'delivery_backend': value['backend'], 'latency_ms': int((time.monotonic() - started) * 1000)}
    except ExecutionDenied as exc:
        attempt.finish('denied', exc.error_code); operation.finish('denied', exc.error_code)
        return refused(exc.error_code)
    except Exception:
        state = 'unknown' if sent else 'failed'
        if sent:
            try:
                receipt = service.authorized(grant['access_token'], service.config.origin, grant['run_id'])
                if receipt['state'] == 'failed':
                    attempt.finish('failed', 'UPSTREAM_TOOL_ERROR'); operation.finish('failed', 'UPSTREAM_TOOL_ERROR')
                    return {**refused('UPSTREAM_TOOL_ERROR'), 'outcome': 'failed'}
            except Exception:
                pass
        attempt.finish(state, 'UPSTREAM_PROTOCOL'); operation.finish(state, 'UPSTREAM_PROTOCOL')
        return refused('UPSTREAM_PROTOCOL', unknown=sent)
    finally:
        if client is not None:
            client.close()

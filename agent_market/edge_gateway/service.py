"""Shared admission, durable dispatch ownership and free-first delivery policy."""
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import urlsplit

from ..capability_registry import Registry
from ..collector.a2a import _ACTION, _PII, message_request
from ..concierge.connections import bindings, gateway_agent_url
from ..concierge.execution_policy import ExecutionDenied, resolve_a2a
from ..concierge.http_security import validate_public_url
from ..execution_authority import require_enabled
from .auth import canonical, derived, digest, sign_ticket, verify_ticket
from .config import EdgeError, PROFILE
from .state import execute, ready, rows, transaction

OUTCOME_CODES = {
    'failed': {'EXECUTION_FAILED', 'PROVIDER_METHOD_UNSUPPORTED', 'PROVIDER_INPUT_REJECTED',
               'PROVIDER_ENDPOINT_UNAVAILABLE', 'PROVIDER_AUTH_REQUIRED', 'PROVIDER_RATE_LIMITED', 'PROVIDER_SCHEMA_CHANGED'},
    'outcome_unknown': {'OUTCOME_UNKNOWN', 'PROVIDER_PROTOCOL_INVALID', 'PROVIDER_TASK_PENDING'},
}


def input_digest(provider, payload):
    # Preserve existing stream tickets while pinning a configured unary method.
    if provider.catalog:
        return digest({'protocol': provider.kind, 'spec_version': provider.spec_version, 'input': payload})
    return digest(payload if provider.request_mode == 'stream' else {'request_mode': provider.request_mode, 'input': payload})


def day_at(now):
    return datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%d')


def message_input(value):
    if type(value) is not dict or set(value) != {'message'} or type(value['message']) is not str:
        raise EdgeError('INVALID_INPUT', 400)
    text = value['message']
    if not text.strip() or len(text) > 2000 or _ACTION.search(text) or _PII.search(text):
        raise EdgeError('POLICY_DENIED', 400)
    return {'message': text}


class Service:
    def __init__(self, front, config, *, clock=time.time, random=None):
        self.front, self.store, self.config, self.clock = front, front.store, config, clock
        import random as _random
        self.random = random or _random.SystemRandom().random   # half-open share (11-11)
        self.available = ready(self.store)

    def require_ready(self):
        if not self.available:
            raise EdgeError('NOT_PROVISIONED')

    def principal(self, visitor_token):
        visitor = self.front.book.by_token(visitor_token)
        if visitor is None:
            raise EdgeError('AUTH_REQUIRED', 401)
        return hmac.new(derived(self.config.key, 'edge-principal-v1'), visitor.id.encode(), hashlib.sha256).hexdigest()

    def admitted(self, resource_id):
        from .catalog import provider_for
        provider = next((p for p in self.config.providers if type(resource_id) is int and p.resource_id == resource_id), None)
        try:
            require_enabled(self.store, 'invoke')
            resource = self.front.managed_gateway.resource(resource_id, provider.kind if provider else None)
            if provider is None:
                return provider_for(self, resource), resource
            version = Registry(self.store).current(resource, create=False)
            if not version or version['id'] != provider.version_id:
                raise EdgeError('SCHEMA_CHANGED', 409)
            target = resolve_a2a(resource, self.front.courier, public=True)
            if target.get('v1') or target.get('url') != provider.endpoint:
                raise EdgeError('SCHEMA_CHANGED', 409)
            validate_public_url(provider.endpoint)
        except ExecutionDenied:
            raise EdgeError('POLICY_DENIED', 403) from None
        return provider, resource

    def policy(self, db, *, lock=False):
        name = 'policy_lock' if lock and getattr(self.store, 'backend', '') == 'postgresql' else 'policy'
        data = rows(db, name)
        if not data:
            raise EdgeError('NOT_PROVISIONED')
        return data[0]

    def route(self, db, *, reserve=False):
        now, config = self.clock(), self.config
        day = day_at(now)
        policy = self.policy(db)
        if not config.worker_ready:
            return 'origin', 'worker_not_ready'
        if policy['mode'] == 'origin':
            return 'origin', 'operator_origin'
        half_open = False
        if policy['cpu_blocked']:
            # 11-11: a monitor block is retried after HALF_OPEN_AFTER with a share of executions (half-open);
            # the monitor clears it when the probe window is clean. A block without a monitor audit row
            # (set by hand or before this rule) stays until an operator clears it.
            last = rows(db, 'audit_monitor_last')
            from .monitor import HALF_OPEN_AFTER, HALF_OPEN_SHARE
            if not (last and last[0]['action'] == 'auto-block' and now - last[0]['created'] >= HALF_OPEN_AFTER
                    and self.random() < HALF_OPEN_SHARE):
                return 'origin', 'cpu_blocked'
            half_open = True
        if policy['health_day'] != day or not 0 <= now - policy['health_at'] <= config.max_age:
            return 'origin', 'health_unconfirmed'
        if policy['usage_day'] != day or not 0 <= now - policy['observed_at'] <= config.max_age:
            return 'origin', 'usage_unconfirmed'
        used = rows(db, 'day', (day,))
        reservations = used[0]['reservations'] if used else 0
        # Reservations are deliberately cumulative within this UTC day. They are
        # not subtracted from delayed account analytics or reset by observations.
        if policy['reported_usage'] + reservations >= config.soft_limit:
            return 'origin', 'daily_reserve'
        if reserve:
            execute(db, 'day_init', (day,))
            execute(db, 'reserve', (day,))
        return 'worker', 'half_open' if half_open else 'free_available'

    def ticket(self, row, backend):
        now = self.clock()
        expiry = min(row['expires'], now + 120)
        if expiry <= now:
            raise EdgeError('EXPIRED', 410)
        prefix = 'edge' if backend == 'worker' else 'origin'
        return {'run_id': row['id'],
                'stream_path': f'/api/{prefix}-gateway/v1/runs/{row["id"]}/stream',
                'access_token': sign_ticket(self.config.key, row['id'], row['origin'], expiry),
                'expires_in_seconds': max(0, int(expiry - now))}

    def prepare(self, principal, origin, value):
        self.require_ready()
        if self.config.canary_principal and not hmac.compare_digest(self.config.canary_principal, principal):
            raise EdgeError('PROFILE_UNAVAILABLE', 400)
        if (type(value) is not dict or set(value) != {'resource_id', 'input', 'idempotency_key', 'run_authority', 'sharing_authority'}
                or value['run_authority'] is not True or value['sharing_authority'] is not True
                or type(value['idempotency_key']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', value['idempotency_key'])):
            raise EdgeError('INVALID_INPUT', 400)
        from .catalog import payload_for
        provider, resource = self.admitted(value['resource_id'])
        try:
            payload = payload_for(provider, value['input'], resource)
        except ExecutionDenied as exc:
            error = EdgeError('POLICY_DENIED', 403)
            error.denied = exc.error_code  # the public bridge hands argument mistakes to the Origin gateway
            raise error from None
        input_hash = input_digest(provider, payload)
        identity = digest(value['idempotency_key'])
        now = self.clock()
        from .result_transport import available
        receipt_tables = available(self.store)
        with transaction(self.store) as db:
            self.policy(db, lock=True)
            # Fixed, small maintenance batches; old tickets cannot outlive this
            # seven-day idempotency retention window.
            execute(db, 'prune_events', (now - 7 * 86400,))
            if receipt_tables:
                from .result_transport import sql, RESULT, CONTEXT
                sql(db, '''DELETE FROM workflow_checkpoints WHERE run_id IN (
                    SELECT id FROM edge_gateway_runs WHERE created<? AND state<>'dispatch_reserved'
                    ORDER BY created,id LIMIT 100) AND node_id IN (?,?,?,?)''', (now-7*86400,RESULT,CONTEXT,'edge-admin-delivery-v1','edge-admin-audit-v1'))
            execute(db, 'prune_runs', (now - 7 * 86400,))
            found = rows(db, 'idempotency', (principal, identity))
            if found:
                row = found[0]
                if row['resource_id'] != provider.resource_id or row['input_hash'] != input_hash or row['origin'] != origin:
                    raise EdgeError('IDEMPOTENCY_CONFLICT', 409)
                backend, _ = self.route(db)
                return self.ticket(row, backend)
            backend, _ = self.route(db, reserve=True)
            rid = 'er_' + secrets.token_hex(16)
            execute(db, 'insert', (rid, principal, identity, input_hash, provider.resource_id, provider.version_id,
                                   origin, backend, now, now + 120))
            row = rows(db, 'run', (rid,))[0]
        return self.ticket(row, backend)

    def authorized(self, token, origin, run_id):
        self.require_ready()
        claims = verify_ticket(self.config.key, token, origin, now=self.clock())
        if claims['run'] != run_id:
            raise EdgeError('AUTH_REQUIRED', 401)
        with transaction(self.store, readonly=True) as db:
            found = rows(db, 'run', (run_id,))
        if (not found or found[0]['origin'] != origin or self.config.canary_principal
                and not hmac.compare_digest(self.config.canary_principal, found[0]['principal'])):
            raise EdgeError('AUTH_REQUIRED', 401)
        return found[0]

    def claim(self, token, origin, run_id, payload, backend):
        if backend not in ('worker', 'origin'):
            raise EdgeError('INVALID_INPUT', 400)
        row = self.authorized(token, origin, run_id)
        admin_delivery=False
        if origin!=self.config.origin:
            from .admin_delivery import approved
            approved(self,row)
            admin_delivery=True
        from .catalog import payload_for, mcp_revision, PROFILE as CATALOG_PROFILE
        provider, resource = self.admitted(row['resource_id'])
        try:
            payload = payload_for(provider, payload, resource)
        except ExecutionDenied:
            raise EdgeError('POLICY_DENIED', 403) from None
        if input_digest(provider, payload) != row['input_hash']:
            raise EdgeError('INPUT_CHANGED', 409)
        if provider.version_id != row['version_id']:
            raise EdgeError('SCHEMA_CHANGED', 409)
        now = self.clock()
        attempt = 'ea_' + secrets.token_hex(16)
        with transaction(self.store) as db:
            self.policy(db, lock=True)
            # Lost attempts become unknown, never prepared again.
            execute(db, 'expire_unknown', (now, now - 180))
            active = rows(db, 'active')[0]['n']
            if active >= self.config.max_inflight:
                raise EdgeError('CAPACITY_EXCEEDED', 503)
            if backend == 'worker':
                preferred, _ = self.route(db)
                if preferred != 'worker':
                    raise EdgeError('ORIGIN_REQUIRED', 409)
            changed = execute(db, 'claim', (backend, attempt, run_id, now)).rowcount
            if changed != 1:
                raise EdgeError('ALREADY_CLAIMED', 409)
        wire = message_request({'spec_version': provider.spec_version}, payload['message'], request_id=attempt) if provider.kind == 'a2a' else {
            'jsonrpc': '2.0', 'id': attempt, 'method': 'tools/call' if provider.kind == 'mcp' else 'probe',
            'params': {'name': payload['tool'], 'arguments': payload['arguments']} if provider.kind == 'mcp' else {}}
        if provider.kind == 'a2a' and provider.spec_version == '0.3':
            wire['method'] = 'message/stream' if provider.request_mode == 'stream' else 'message/send'
        if provider.kind == 'a2a' and provider.request_mode == 'json' and provider.spec_version == '0.3':
            wire['params']['configuration'] = {'blocking': True}
        binding = {'attempt_id': attempt, 'endpoint': provider.endpoint, 'request': wire,
                **({'admin_delivery':True} if admin_delivery else {}),
                'request_mode': provider.request_mode,
                'protocol': provider.kind, 'spec_version': provider.spec_version,
                **({'mcp_schema_hash': resource['usage_full_hash']} if provider.kind == 'mcp' and resource.get('usage_full_hash') else {}),
                **({'mcp_protocol_version': mcp_revision(resource)} if provider.kind == 'mcp' and mcp_revision(resource) else {}),
                'gateway_url': gateway_agent_url(provider.resource_id, provider.kind),
                'bindings': sorted(bindings(resource) | {provider.endpoint, f'https://{urlsplit(provider.endpoint).netloc}/'}),
                'max_frame_bytes': 16384, 'max_output_bytes': 48000, 'timeout_ms': 8000,
                'profile': CATALOG_PROFILE if provider.catalog else PROFILE}
        if provider.kind == 'mcp' and backend == 'worker' and mcp_revision(resource):
            from .mcp_control import prepare
            try:
                binding['mcp_prepared'] = prepare(self, run_id, attempt, provider, payload, int((now + 8) * 1000))
            except Exception as error:
                self.finish(run_id, attempt, 'failed', 0,
                            'PROVIDER_SCHEMA_CHANGED' if getattr(error, 'code', '') == 'SCHEMA_CHANGED' else 'EXECUTION_FAILED')
                raise
        return binding

    def finish(self, run_id, attempt, outcome, output_bytes=0, outcome_code=None):
        self.require_ready()
        if (not re.fullmatch(r'ea_[a-f0-9]{32}', attempt or '')
                or outcome not in ('succeeded', 'failed', 'outcome_unknown')
                or type(output_bytes) is not int or not 0 <= output_bytes <= 262144):
            raise EdgeError('INVALID_INPUT', 400)
        if outcome_code is not None and (type(outcome_code) is not str or outcome_code not in OUTCOME_CODES.get(outcome, set())):
            raise EdgeError('INVALID_INPUT', 400)
        code = outcome_code or (None if outcome == 'succeeded' else 'OUTCOME_UNKNOWN' if outcome == 'outcome_unknown' else 'EXECUTION_FAILED')
        now = self.clock()
        with transaction(self.store) as db:
            self.policy(db, lock=True)
            found = rows(db, 'run', (run_id,))
            if not found or found[0]['attempt'] != attempt:
                raise EdgeError('ATTEMPT_CHANGED', 409)
            row = found[0]
            if row['state'] in ('succeeded', 'failed', 'outcome_unknown'):
                if row['state'] != outcome or row['error_code'] != code:
                    raise EdgeError('OUTCOME_CONFLICT', 409)
            else:
                execute(db, 'event', (run_id, attempt, outcome, now, output_bytes))
                if execute(db, 'finish', (outcome, now, code, run_id, attempt)).rowcount != 1:
                    raise EdgeError('OUTCOME_CONFLICT', 409)
                row = {**row, 'state': outcome, 'finished': now, 'error_code': code}
        # Worker-owned public endpoints can bypass ManagedGateway entirely.
        # Retry this local projection after a lost completion acknowledgement;
        # never repeat provider IO or refresh the original completion time.
        self.record_mcp_evidence(row)
        return {'ok': True}

    def record_mcp_evidence(self, row):
        if row['backend'] != 'worker':
            return
        resource = self.store.resource(row['resource_id'])
        if not resource or resource['kind'] != 'mcp':
            return
        registry = Registry(self.store)
        version = registry.current(resource, create=False)
        if not version or version['id'] != row['version_id']:
            return
        if not 0 < row['created'] <= row['finished'] <= time.time() + 5:
            return
        artifact = hashlib.sha256(canonical({'run': row['id'], 'attempt': row['attempt'],
                                            'version': row['version_id']}).encode()).hexdigest()
        def unrecorded():
            # Registry calls the guard under the shared writer transaction.
            return not self.store.query("""SELECT 1 FROM capability_evidence
                WHERE version_id=? AND scope='execution' AND artifact_hash=? LIMIT 1""",
                (version['id'], artifact))
        registry.record(version, scope='execution',
            outcome={'succeeded': 'succeeded', 'failed': 'failed', 'outcome_unknown': 'unknown'}[row['state']],
            started=row['created'], finished=row['finished'],
            code=None if row['state']=='succeeded' else 'UPSTREAM_TIMEOUT' if row['state']=='outcome_unknown' else 'UPSTREAM_TOOL_ERROR',
            artifact_hash=artifact, dataset='edge-worker-execution-v1', guard=unrecorded)

    def status(self, principal, run_id):
        self.require_ready()
        now = self.clock()
        with transaction(self.store) as db:
            execute(db, 'expire_unknown', (now, now - 180))
            found = rows(db, 'run', (run_id,))
            if not found or not hmac.compare_digest(found[0]['principal'], principal):
                raise EdgeError('AUTH_REQUIRED', 404)
            row = found[0]
            data = {'run_id': run_id, 'state': row['state'], 'error_code': row['error_code']}
            # Only the owner can obtain another delivery path for a still-unclaimed run.
            if row['state'] == 'prepared' and row['expires'] > now:
                data.update(self.ticket(row, 'origin'))
            return data

    async def origin(self, token, origin, run_id, payload):
        from starlette.concurrency import run_in_threadpool
        binding = await run_in_threadpool(self.claim, token, origin, run_id, payload, 'origin')
        row = self.authorized(token, origin, run_id)
        try:
            provider, _ = await run_in_threadpool(self.admitted, row['resource_id'])
            result = await self.front.managed_gateway.execute(row['resource_id'], kind=provider.kind, message=payload.get('message', ''),
                                                              tool=payload.get('tool', ''), arguments=payload.get('arguments', {}),
                                                              timeout=8, expected_version=row['version_id'],edge_first=False)
            outcome = 'succeeded' if result.get('execution_succeeded') else 'outcome_unknown' if result.get('task_status') == 'timeout' else 'failed'
            # ManagedGateway already applies public metadata and purpose-based binding projection.
            public = {'state': outcome, 'output': result.get('output') if outcome == 'succeeded' else None,
                      'error_code': None if outcome == 'succeeded' else 'OUTCOME_UNKNOWN' if outcome == 'outcome_unknown' else 'EXECUTION_FAILED'}
            if provider.kind != 'a2a':
                public['managed'] = result
            size = len(('event: result\ndata: ' + canonical(public) + '\n\n').encode())
            await run_in_threadpool(self.finish, run_id, binding['attempt_id'], outcome, size)
            return public
        except BaseException:
            await asyncio.shield(run_in_threadpool(self.finish, run_id, binding['attempt_id'], 'outcome_unknown'))
            raise

    def observe(self, requests, observed_at, *, healthy=False):
        """Trusted host observations only; public clients cannot set quota or readiness."""
        self.require_ready()
        now = self.clock()
        if (type(requests) is not int or not 0 <= requests <= 2**53 or type(observed_at) not in (int, float)
                or not 0 <= now - observed_at <= self.config.max_age or day_at(observed_at) != day_at(now)):
            raise EdgeError('INVALID_OBSERVATION', 400)
        with transaction(self.store) as db:
            policy = self.policy(db, lock=True)
            if policy['usage_day'] == day_at(now) and (observed_at < policy['observed_at'] or requests < policy['reported_usage']):
                raise EdgeError('STALE_OBSERVATION', 409)
            execute(db, 'observe', (day_at(now), requests, observed_at))
            if healthy:
                execute(db, 'health', (day_at(now), now))
            else:
                execute(db, 'health', ('', 0))

    def summary(self):
        if not self.available:
            return {'available': False, 'configured': True, 'reason': 'not_provisioned'}
        now = self.clock()
        with transaction(self.store, readonly=True) as db:
            backend, reason = self.route(db)
            policy = self.policy(db)
            counts = rows(db, 'summary', (now - 86400,))
            used = rows(db, 'day', (day_at(now),))
        return {'available': True, 'configured': True, 'preferred_backend': backend, 'reason': reason,
                'routing_scope': 'catalog_policy' if self.config.catalog_protocols else 'explicit_pins',
                'catalog_protocols': list(self.config.catalog_protocols),
                'native_node_delivery': self.config.native_node_delivery,
                'direct_result_delivery': self.config.direct_result_delivery,
                'revision': policy['revision'], 'worker_plan': 'free', 'daily_limit': 100000,
                'soft_limit': self.config.soft_limit, 'cpu_ms_limit': 10, 'window_utc': day_at(now),
                'account_requests_reported': policy['reported_usage'] if policy['usage_day'] == day_at(now) else None,
                'local_reservations': used[0]['reservations'] if used else 0,
                'observed_at': policy['observed_at'] or None, 'captured_at': now,
                'counts': counts, 'automatic_paid_upgrade': False}

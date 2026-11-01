"""Exact first-party bindings behind the existing managed execution gateway.

No loopback HTTP or edge-security exception is needed to call our own handlers.
All external data retrieval still uses the engine's pinned public networking.
"""
import time
import logging
import sqlite3

from ..capability_registry import digest, version_parts
from ..collector import usage
from ..concierge.execution_policy import ExecutionDenied, validate_arguments
from ..observability import provider_dispatch
from .catalog import SPECS, tool_spec
from .engine import DataUnavailable
from .service import PREFIX, display_text


def is_owned(resource):
    """First-party identity must never fall through to remote HTTP execution."""
    return (resource.get('source') == 'agentconcierge-owned'
            or str(resource.get('key', '')).startswith('agentconcierge-owned:'))


def resolve_local(proxy, resource):
    """Resolve approved existing bindings for every proxy, including CLI workers.

    This does not install resources, alter schemas or create an HTTP server.
    An inactive/malformed profile is denied rather than calling our public URL.
    """
    configured = getattr(proxy, '_owned_data_dispatch', None)
    if configured is not None and configured.applies(resource['id']):
        return configured
    if not is_owned(resource):
        return None
    import json
    from .activation import MARKER
    from .engine import DataAgents
    from .staging import origin
    store = proxy.store
    with store._lock:
        rows = store.query('SELECT value FROM meta WHERE key=?', (MARKER,))
        if not rows:
            raise ExecutionDenied('The local agent profile is unavailable.', error_code='POLICY_DENIED')
        try:
            base = origin(json.loads(rows[0]['value'])['origin'])
        except (ValueError, TypeError, KeyError):
            raise ExecutionDenied('The local agent profile needs review.', error_code='POLICY_DENIED') from None
        resources = {}
        for identity in SPECS:
            found = store.query('SELECT id FROM resources WHERE key=?', ('agentconcierge-owned:'+identity,))
            if found:
                resources[identity] = found[0]['id']
        engine = getattr(store, '_owned_data_engine', None)
        if engine is None:
            engine = store._owned_data_engine = DataAgents()
        configured = OwnedDispatch(store, engine, resources, base)
        proxy._owned_data_dispatch = configured
    if not configured.applies(resource['id']):
        raise ExecutionDenied('The local agent binding needs review.', error_code='SCHEMA_CHANGED')
    return configured


class OwnedDispatch:
    def __init__(self, store, engine, resources, origin):
        self.store, self.engine = store, engine
        self.bindings = {rid: (identity, origin.rstrip('/')+PREFIX+'/'+identity+'/mcp')
                         for identity, rid in resources.items()}
        self.bookkeeping_skipped = 0

    def applies(self, resource_id):
        return resource_id in self.bindings

    def execute(self, resource, name, arguments, observed):
        identity, endpoint = self.bindings[resource['id']]
        tools = [tool_spec(identity)]
        compact = usage.compact_tools(tools)
        fresh = self.store.resource(resource['id'])
        if (resource.get('kind') != 'mcp' or resource.get('source') != 'agentconcierge-owned'
                or resource.get('key') != 'agentconcierge-owned:'+identity
                or resource.get('url') != endpoint or name != SPECS[identity]['tool']
                or resource.get('usage_tools_hash') != usage.tools_hash(compact)
                or resource.get('usage_full_hash') != digest(tools)
                or not fresh or not fresh.get('active') or version_parts(fresh) != version_parts(resource)):
            return {'ok': False, 'error_code': 'SCHEMA_CHANGED', 'error': 'The registered capability needs review.'}
        started = time.monotonic()
        try:
            validate_arguments(tools[0], arguments)
            # Retain the same authority, lease/fence, cancellation and durable
            # prepared-to-dispatched boundary as remote provider execution.
            provider_dispatch()
            output = self.engine.execute(identity, arguments)
            validate_arguments({'inputSchema': tools[0]['outputSchema']}, output)
        except ExecutionDenied as exc:
            return {'ok': False, 'error_code': exc.error_code, 'error': str(exc)}
        except (DataUnavailable, ValueError):
            return {'ok': False, 'hash_verified': True, 'error_code': 'UPSTREAM_TOOL_ERROR',
                    'error': 'Current source data is unavailable. Try again shortly.'}
        result = {'content': [{'type': 'text', 'text': display_text(output)}],
                  'structuredContent': output, 'isError': False}
        if observed is not None:
            observed.update(transport_ok=True, protocol_valid=True)
        return {'ok': True, 'resource_id': resource['id'], 'tool': name, 'result': result,
                'sample_output': result['content'][0]['text'][:500], 'hash_verified': True,
                'latency_ms': int((time.monotonic()-started)*1000)}

    def bookkeep(self, resource_id, result, record_evidence):
        """Optional analytics must not time out already completed local reads.

        Durable checkpoints, dispatch authority and workflow completion do not
        use this path. Skipped evidence creates no positive verification claim.
        Never commit a caller's existing transaction or change a live timeout
        without holding the Store's connection lock.
        """
        acquired = self.store._lock.acquire(timeout=.02)
        saved_timeout = None
        try:
            if not acquired or self.store._db.in_transaction:
                return self._skipped()
            if getattr(self.store, 'backend', 'sqlite') != 'postgresql':
                saved_timeout = self.store._db.execute('PRAGMA busy_timeout').fetchone()[0]
                self.store._db.execute('PRAGMA busy_timeout=50')
            if result.get('ok'):
                with self.store.tx() as db:
                    db.execute('UPDATE resources SET calls_30d=COALESCE(calls_30d,0)+1,last_called=? WHERE id=?',
                               (time.time(), resource_id))
            record_evidence()
            return True
        except sqlite3.OperationalError as exc:
            if not any(word in str(exc).lower() for word in ('locked', 'busy')):
                raise
            return self._skipped()
        finally:
            if saved_timeout is not None:
                self.store._db.execute('PRAGMA busy_timeout='+str(int(saved_timeout)))
            if acquired:
                self.store._lock.release()

    def _skipped(self):
        self.bookkeeping_skipped += 1
        if self.bookkeeping_skipped == 1:
            logging.getLogger(__name__).warning('Owned agent analytics/evidence write skipped under catalog contention; source response retained.')
        return False

"""Prepare only MCP metadata on Origin; tool results stay on the Edge data path."""
import logging
import re
import hashlib
import hmac

from ..collector.capabilities import parse_jsonrpc
from ..concierge.http_security import bounded_client, OutboundBudget
from .catalog import review_mcp, mcp_revision
from .config import EdgeError
from .auth import canonical, derived

log = logging.getLogger(__name__)


def prepare(service, run_id, attempt, provider, payload, deadline_ms, *, http=None):
    client = bounded_client(http, allow_private=False, limit=65536, budget=OutboundBudget(5))
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'User-Agent': 'agent-concierge/1.0', 'Accept-Encoding': 'identity'}
    session = None
    handed_off = False

    def rpc(method, params, identity):
        nonlocal session
        # Protocol sessions are fresh; browser credentials and cookies never enter.
        client.client.cookies.clear()
        response = client.post(provider.endpoint, headers=headers,
                               json={'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params})
        value = parse_jsonrpc(response) or {}
        if (not 200 <= response.status_code < 300 or value.get('jsonrpc') != '2.0'
                or type(value.get('id')) is not type(identity) or value.get('id') != identity
                or ('result' in value) == ('error' in value)):
            raise EdgeError('UNAVAILABLE', 503)
        if 'error' in value:
            error = value['error']
            if not isinstance(error, dict) or type(error.get('code')) is not int:
                raise EdgeError('UNAVAILABLE', 503)
            return None, error['code']
        result = value['result']
        if not isinstance(result, dict):
            raise EdgeError('UNAVAILABLE', 503)
        if method in ('initialize', 'server/discover') and response.headers.get('mcp-session-id'):
            session = response.headers['mcp-session-id']
            if not re.fullmatch(r'[\x21-\x7e]{1,256}', session):
                session = None
                raise EdgeError('UNAVAILABLE', 503)
            headers['Mcp-Session-Id'] = session
        return result, None

    try:
        pinned = mcp_revision(service.store.resource(provider.resource_id))
        discovery, error = (None, None) if pinned else rpc('server/discover', {}, 1)
        if error is not None and error not in (-32600, -32601):
            raise EdgeError('UNAVAILABLE', 503)
        initialize = not discovery or not discovery.get('protocolVersion')
        if initialize:
            discovery, error = rpc('initialize', {'protocolVersion': pinned or '2025-06-18', 'capabilities': {},
                'clientInfo': {'name': 'agent-concierge', 'version': '1.0'}}, 1)
        version = (discovery or {}).get('protocolVersion')
        if error is not None or type(version) is not str or version not in ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25'):
            raise EdgeError('UNAVAILABLE', 503)
        headers['Mcp-Protocol-Version'] = version
        if initialize:
            client.client.cookies.clear()
            response = client.post(provider.endpoint, headers=headers,
                                   json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            # A notification has no answer to wait for; some stateless servers reply 400 to it (11-12: 45532,
            # -32600 Invalid Request) yet list and run tools normally. The Origin proxy never read this reply,
            # so the Edge path does not refuse on it either.
            if not 200 <= response.status_code < 300:
                log.info('MCP provider answered notifications/initialized with HTTP %s; continuing', response.status_code)
        listed, error = rpc('tools/list', {}, 2)
        if error is not None or not isinstance((listed or {}).get('tools'), list):
            raise EdgeError('UNAVAILABLE', 503)
        review_mcp(service, run_id, attempt, listed['tools'], payload)
        if service.clock() * 1000 >= deadline_ms:
            raise EdgeError('EXPIRED', 410)
        handed_off = True
        prepared = {'protocol_version': version, 'session_id': session, 'deadline_ms': deadline_ms}
        if session:
            cleanup = {'run_id': run_id, 'attempt_id': attempt, 'endpoint': provider.endpoint,
                       'protocol_version': version, 'session_id': session, 'expires': int(service.clock()) + 300}
            cleanup['signature'] = hmac.new(derived(service.config.key, 'edge-mcp-cleanup-v1'),
                                            canonical(cleanup).encode(), hashlib.sha256).hexdigest()
            prepared['cleanup'] = cleanup
        return prepared
    except EdgeError:
        raise
    except Exception:
        raise EdgeError('UNAVAILABLE', 503) from None
    finally:
        if session and not handed_off:
            try:
                client.client.cookies.clear()
                client.delete(provider.endpoint, headers=headers)
            except Exception:
                log.debug('MCP protocol session cleanup deferred to expiration')
        client.close()


def close(service, run_id, attempt, capsule, *, http=None):
    """Authenticate Origin-issued cleanup authority; never accept a new target."""
    if (not isinstance(capsule, dict) or set(capsule) != {'run_id', 'attempt_id', 'endpoint', 'protocol_version', 'session_id', 'expires', 'signature'}
            or capsule['run_id'] != run_id or capsule['attempt_id'] != attempt
            or type(capsule['expires']) is not int or not service.clock() < capsule['expires'] <= service.clock() + 301
            or type(capsule['signature']) is not str or not re.fullmatch(r'[a-f0-9]{64}', capsule['signature'])):
        return False
    value = {k: v for k, v in capsule.items() if k != 'signature'}
    expected = hmac.new(derived(service.config.key, 'edge-mcp-cleanup-v1'), canonical(value).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, capsule['signature']):
        return False
    client = bounded_client(http, allow_private=False, limit=1024, budget=OutboundBudget(1.5))
    try:
        client.client.cookies.clear()
        client.delete(capsule['endpoint'], headers={'Mcp-Session-Id': capsule['session_id'],
                      'Mcp-Protocol-Version': capsule['protocol_version']})
        return True
    except Exception:
        log.debug('MCP protocol session cleanup deferred to expiration')
        return False
    finally:
        client.close()

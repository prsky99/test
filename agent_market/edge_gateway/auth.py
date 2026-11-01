"""Domain-separated execution tickets and replay-protected service request MACs."""
import base64
import hashlib
import hmac
import json
import re
import time

from .config import EdgeError, parse

AUDIENCE = 'platform-execution-gateway'
RUN = re.compile(r'er_[a-f0-9]{32}\Z')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def derived(key, purpose):
    return hmac.new(key, purpose.encode('ascii'), hashlib.sha256).digest()


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def sign_ticket(key, run_id, origin, expires):
    payload = b64(canonical({'aud': AUDIENCE, 'run': run_id, 'origin': origin, 'exp': int(expires)}).encode())
    return payload + '.' + b64(hmac.new(derived(key, 'edge-ticket-v1'), payload.encode(), hashlib.sha256).digest())


def verify_ticket(key, token, origin, *, now=None):
    now = time.time() if now is None else now
    if type(token) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,1024}\.[A-Za-z0-9_-]{43}', token):
        raise EdgeError('AUTH_REQUIRED', 401)
    payload, signature = token.split('.')
    expected = b64(hmac.new(derived(key, 'edge-ticket-v1'), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise EdgeError('AUTH_REQUIRED', 401)
    try:
        obj = parse(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        if (type(obj) is not dict or set(obj) != {'aud', 'run', 'origin', 'exp'} or obj['aud'] != AUDIENCE
                or obj['origin'] != origin or type(obj['run']) is not str or not RUN.fullmatch(obj['run'])
                or type(obj['exp']) is not int or not now < obj['exp'] <= now + 125):
            raise ValueError()
    except (ValueError, TypeError):
        raise EdgeError('AUTH_REQUIRED', 401) from None
    return obj


def service_mac(key, method, path, timestamp, nonce, body):
    value = '\n'.join((method, path, timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()
    return hmac.new(derived(key, 'edge-service-v1'), value, hashlib.sha256).hexdigest()


def verify_service(key, method, path, headers, body, *, now=None):
    now = time.time() if now is None else now
    timestamp, nonce, signature = (headers.get('x-edge-time', ''), headers.get('x-edge-nonce', ''), headers.get('x-edge-signature', ''))
    if (not re.fullmatch(r'[0-9]{10}', timestamp) or abs(now - int(timestamp)) > 30
            or not re.fullmatch(r'[a-f0-9]{32}', nonce) or not re.fullmatch(r'[a-f0-9]{64}', signature)
            or not hmac.compare_digest(signature, service_mac(key, method, path, timestamp, nonce, body))):
        raise EdgeError('AUTH_REQUIRED', 401)
    return nonce

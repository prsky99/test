"""Opt-in Idempotency-Key handling for public and customer API writes.

A client that sends `Idempotency-Key` on a POST under /api/ gets exactly one execution
per key: a retry with the same body receives the stored response (marked
`Idempotent-Replayed: true`), a concurrent retry gets 409, and reusing the key for a
different body gets 422. Keys are scoped to the caller (session, visitor token or
address) and kept for 24 hours. Requests without the header are unchanged.
"""
from collections import OrderedDict
import base64
import hashlib
import json
import re
import threading
import time

from starlette.datastructures import Headers

KEY = re.compile(r'^[A-Za-z0-9_.:-]{8,128}$')
TTL = 24 * 3600
PENDING_TTL = 120
MAX_BODY = 256 * 1024
MAX_ENTRIES = 4096
STORED_HEADERS = ('content-type', 'location', 'x-visitor-token')


class MemoryBackend:
    def __init__(self, maximum=MAX_ENTRIES, clock=time.monotonic):
        self.values, self.lock, self.maximum, self.clock = OrderedDict(), threading.Lock(), maximum, clock

    def reserve(self, key, value, ttl):
        with self.lock:
            found = self.values.get(key)
            if found and found[0] > self.clock():
                return False
            self._put(key, value, ttl)
            return True

    def get(self, key):
        with self.lock:
            found = self.values.get(key)
            return found[1] if found and found[0] > self.clock() else None

    def put(self, key, value, ttl):
        with self.lock:
            self._put(key, value, ttl)

    def drop(self, key):
        with self.lock:
            self.values.pop(key, None)

    def _put(self, key, value, ttl):
        self.values.pop(key, None)
        self.values[key] = (self.clock() + ttl, value)
        while len(self.values) > self.maximum:
            self.values.popitem(last=False)


class RedisBackend:
    """Shares keys across service slots; any Redis error falls back to the local memory."""

    def __init__(self, hub, fallback):
        self.hub, self.fallback = hub, fallback

    def _client(self):
        try:
            client, _, _ = self.hub._operation()
            return client
        except Exception:
            return None

    def reserve(self, key, value, ttl):
        client = self._client()
        if client is None:
            return self.fallback.reserve(key, value, ttl)
        try:
            return bool(client.set(key, json.dumps(value), ex=ttl, nx=True))
        except Exception:
            return self.fallback.reserve(key, value, ttl)

    def get(self, key):
        client = self._client()
        if client is None:
            return self.fallback.get(key)
        try:
            raw = client.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return self.fallback.get(key)

    def put(self, key, value, ttl):
        client = self._client()
        if client is not None:
            try:
                client.set(key, json.dumps(value), ex=ttl)
                return
            except Exception:
                pass
        self.fallback.put(key, value, ttl)

    def drop(self, key):
        client = self._client()
        if client is not None:
            try:
                client.delete(key)
                return
            except Exception:
                pass
        self.fallback.drop(key)


def problem(status, title, detail, code):
    body = json.dumps({'type': 'https://agentconcierge.biz/errors/' + code.lower().replace('_', '-'),
                       'title': title, 'status': status, 'detail': detail, 'error_code': code}).encode()
    return status, [(b'content-type', b'application/problem+json'), (b'cache-control', b'no-store')], body


class Idempotency:
    def __init__(self, app, *, backend=None, scope_of=None, prefix='a2a:'):
        self.app, self.prefix = app, prefix
        self.backend = backend or MemoryBackend()
        self.scope_of = scope_of or (lambda scope, headers: (scope.get('client') or ('', 0))[0])

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST' or not scope['path'].startswith('/api/'):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        supplied = headers.get('idempotency-key')
        if supplied is None:
            return await self.app(scope, receive, send)
        if not KEY.fullmatch(supplied):
            return await self._reply(send, *problem(400, 'Invalid idempotency key',
                'Use 8 to 128 letters, digits, dot, colon, underscore or hyphen.', 'INVALID_IDEMPOTENCY_KEY'))
        # Read the body once so it can be fingerprinted and replayed to the application.
        chunks, more = [], True
        while more:
            message = await receive()
            if message['type'] != 'http.request':
                return await self.app(scope, receive, send)
            chunks.append(message.get('body', b''))
            more = message.get('more_body', False)
        body = b''.join(chunks)
        caller = hashlib.sha256(str(self.scope_of(scope, headers)).encode()).hexdigest()[:32]
        key = self.prefix + 'idem:' + hashlib.sha256('\n'.join((caller, scope['path'], supplied)).encode()).hexdigest()
        fingerprint = hashlib.sha256(body).hexdigest()
        if not self.backend.reserve(key, {'state': 'pending', 'fingerprint': fingerprint}, PENDING_TTL):
            found = self.backend.get(key) or {}
            if found.get('fingerprint') != fingerprint:
                return await self._reply(send, *problem(422, 'Idempotency key reused',
                    'This key was used for a different request. Use a new key for a new request.', 'IDEMPOTENCY_KEY_REUSED'))
            if found.get('state') != 'done':
                return await self._reply(send, *problem(409, 'Request in progress',
                    'The first request with this key is still running. Retry after it finishes.', 'IDEMPOTENCY_IN_PROGRESS'))
            stored = [(name.encode(), value.encode()) for name, value in found['headers']]
            stored.append((b'idempotent-replayed', b'true'))
            return await self._reply(send, found['status'], stored, base64.b64decode(found['body']))

        state = {'status': None, 'headers': [], 'body': [], 'size': 0, 'streaming': False}

        async def replay():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def capture(message):
            if message['type'] == 'http.response.start':
                state['status'] = message['status']
                kept = []
                for name, value in message.get('headers', []):
                    lowered = name.decode('latin-1').lower()
                    if lowered == 'content-type' and value.startswith(b'text/event-stream'):
                        state['streaming'] = True
                    if lowered in STORED_HEADERS:
                        kept.append((lowered, value.decode('latin-1')))
                state['headers'] = kept
            elif message['type'] == 'http.response.body' and not state['streaming']:
                state['size'] += len(message.get('body', b''))
                if state['size'] <= MAX_BODY:
                    state['body'].append(message.get('body', b''))
            await send(message)

        try:
            await self.app(scope, replay, capture)
        except BaseException:
            self.backend.drop(key)
            raise
        status = state['status'] or 500
        # Server errors, throttling and conflicts are not final outcomes; the client may retry.
        if status >= 500 or status in (408, 409, 429) or state['streaming'] or state['size'] > MAX_BODY:
            self.backend.drop(key)
            return
        self.backend.put(key, {'state': 'done', 'fingerprint': fingerprint, 'status': status, 'headers': state['headers'],
                               'body': base64.b64encode(b''.join(state['body'])).decode()}, TTL)

    @staticmethod
    async def _reply(send, status, headers, body):
        await send({'type': 'http.response.start', 'status': status,
                    'headers': headers + [(b'content-length', str(len(body)).encode())]})
        await send({'type': 'http.response.body', 'body': body})

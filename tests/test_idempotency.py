"""Opt-in Idempotency-Key: one execution per key, replay, conflict and reuse detection (2026-10-28)."""
import asyncio

from agent_market.concierge.idempotency import Idempotency, MemoryBackend
from tests.test_fast_single_recommendation import catalog  # noqa: F401


def test_same_key_replays_the_first_result_without_running_again(catalog):
    _, front, client, _, _ = catalog
    body = {'category': 'general', 'name': 'Idem Test', 'email': 'idem@example.com', 'subject': 'Retry check',
            'message': 'Checking a retried submission with the same key.', 'consent': True}
    headers = {'Idempotency-Key': 'retry-key-0001'}
    first = client.post('/api/contact/submit', json=body, headers=headers)
    second = client.post('/api/contact/submit', json=body, headers=headers)
    assert first.status_code == second.status_code
    assert first.content == second.content and second.headers.get('idempotent-replayed') == 'true'
    assert 'idempotent-replayed' not in first.headers
    reused = client.post('/api/contact/submit', json={**body, 'subject': 'Different'}, headers=headers)
    assert reused.status_code == 422 and reused.json()['error_code'] == 'IDEMPOTENCY_KEY_REUSED'
    assert client.post('/api/contact/submit', json=body, headers={'Idempotency-Key': 'bad key!'}).status_code == 400


def test_requests_without_a_key_are_unchanged(catalog):
    _, _, client, _, _ = catalog
    response = client.post('/api/register/inspect', json={'url': 'not a url'})
    assert 'idempotent-replayed' not in response.headers


def test_in_progress_and_server_errors_are_not_final():
    calls = []

    async def app(scope, receive, send):
        calls.append(await receive())
        status = 500 if len(calls) == 1 else 201
        await send({'type': 'http.response.start', 'status': status, 'headers': [(b'content-type', b'application/json')]})
        await send({'type': 'http.response.body', 'body': b'{}'})

    middleware = Idempotency(app, backend=MemoryBackend())
    scope = {'type': 'http', 'method': 'POST', 'path': '/api/workflows/run', 'headers': [(b'idempotency-key', b'run-key-0001')],
             'client': ('203.0.113.9', 1)}

    def run():
        sent = []
        async def receive():
            return {'type': 'http.request', 'body': b'{"a":1}', 'more_body': False}
        async def send(message):
            sent.append(message)
        asyncio.run(middleware(scope, receive, send))
        return sent[0]['status'], dict(sent[0]['headers'])
    assert run()[0] == 500          # not stored: the retry runs again
    assert run()[0] == 201
    status, headers = run()
    assert status == 201 and headers.get(b'idempotent-replayed') == b'true' and len(calls) == 2
    middleware.backend.reserve(middleware.prefix + 'idem:x', {'state': 'pending', 'fingerprint': 'f'}, 60)

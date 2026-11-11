"""11-11 provider ownership proof: a deterministic token, one well-known file or DNS TXT read, nothing stored yet."""
import httpx
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge import owner_proof as op

SECRET = 's' * 40


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv('OWNER_PROOF_SECRET', SECRET)
    monkeypatch.setattr('agent_market.broker.discovery.check_public_url', lambda url: None)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_token_is_deterministic_per_host_and_needs_a_secret(monkeypatch):
    a = op.instructions('https://Agent.Example/a2a')
    assert a['host'] == 'agent.example' and a['token'] == op.instructions('agent.example')['token']
    assert a['token'].startswith('agentconcierge-verify=') and a['token'] != op.instructions('other.example')['token']
    assert a['well_known']['url'] == 'https://agent.example/.well-known/agentconcierge-verify.txt'
    assert a['dns_txt']['name'] == '_agentconcierge.agent.example'
    monkeypatch.setenv('OWNER_PROOF_SECRET', 'short')
    with pytest.raises(op.ProofError) as error:
        op.instructions('agent.example')
    assert error.value.status == 503


@pytest.mark.parametrize('bad', ['localhost', '127.0.0.1', 'http://10.1.2.3/', 'printer.local', 'intranet'])
def test_private_hosts_get_no_token(bad):
    with pytest.raises(op.ProofError):
        op.instructions(bad)


def test_well_known_file_proves_ownership_without_storing():
    expected = op.token('agent.example')
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, text='# owner\n' + expected + '\n')
    result = op.verify('agent.example', '1.1.1.1', client_for(handler), op.Limiter())
    assert result == {**result, 'verified': True, 'method': 'well_known', 'stored': False}
    assert seen == ['https://agent.example/.well-known/agentconcierge-verify.txt']


def test_dns_txt_is_the_fallback_and_redirects_or_big_files_do_not_count():
    expected = op.token('agent.example')

    def handler(request):
        if request.url.host == 'cloudflare-dns.com':
            return httpx.Response(200, json={'Answer': [{'type': 16, 'data': '"' + expected + '"'}]})
        return httpx.Response(302, headers={'Location': 'https://elsewhere.example/token.txt'})
    assert op.verify('agent.example', '1.1.1.1', client_for(handler), op.Limiter())['method'] == 'dns_txt'

    def huge(request):
        if request.url.host == 'cloudflare-dns.com':
            return httpx.Response(200, json={})
        return httpx.Response(200, text=expected + 'x' * 5000)
    assert op.verify('agent.example', '1.1.1.1', client_for(huge), op.Limiter())['verified'] is False


def test_verification_is_rate_limited_per_ip_and_per_host():
    clock = [1000.0]
    limiter = op.Limiter(clock=lambda: clock[0])
    assert limiter.allow('ip', 'a.example') and not limiter.allow('other-ip', 'a.example')  # same host within 10 minutes
    for name in 'bcde':
        assert limiter.allow('ip', name + '.example')
    assert not limiter.allow('ip', 'f.example')  # five an hour from one address
    clock[0] += 3601
    assert limiter.allow('ip', 'f.example')


def test_routes(tmp_path, monkeypatch):
    from agent_market.concierge.front import Front, clear_front_caches, create_front_app
    from agent_market.gateway.store import Store
    monkeypatch.setattr(op, 'verify', lambda host, ip, **kw: {'host': host, 'verified': False, 'method': None, 'stored': None, 'message': 'x'})
    store = Store(str(tmp_path / 'o.db'))
    clear_front_caches()
    front = Front(store)
    client = TestClient(create_front_app(front, manage_book_lifecycle=False))
    try:
        r = client.get('/api/agent/v1/owner/token', params={'host': 'agent.example'})
        assert r.status_code == 200 and r.json()['token'] == op.token('agent.example') and r.headers['cache-control'] == 'no-store'
        assert client.get('/api/agent/v1/owner/token', params={'host': 'localhost'}).status_code == 400
        v = client.post('/api/agent/v1/owner/verify', json={'host': 'agent.example'})
        assert v.status_code == 200 and v.json()['verified'] is False
    finally:
        client.close()
        front.book.close()
        store._db.close()

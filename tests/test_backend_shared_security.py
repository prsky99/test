"""Security boundaries shared with collector, broker and seller administration."""
import ssl
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from agent_market.broker.discovery import public_client
from agent_market.broker.registry import Registry
from agent_market.broker.server import create_app as create_broker
from agent_market.collector.server import create_app as create_collector
from agent_market.config import BrokerConfig, SellerConfig
from agent_market.gateway.store import Store
from agent_market.ledger import Ledger
from agent_market.server import create_app as create_seller
from tests.test_market import NET


@pytest.mark.parametrize('service', ['collector','broker','seller'])
def test_all_secondary_management_surfaces_enforce_bearer_tokens(service):
    if service == 'collector':
        app = create_collector(Store(), None, 'audit-secret', run_background=False)
        paths = [('POST','/admin/crawl'),('POST','/admin/check/1')]
    elif service == 'broker':
        config = BrokerConfig(NET, '0x'+'1'*40, ':memory:', 'audit-secret', 1, 500, 1000, False)
        app = create_broker(config, verifier=Mock(), classifier=Mock(), fetcher=Mock(), registry=Registry(), ledger=Ledger())
        paths = [('GET','/stats')]
    else:
        app = create_seller(SellerConfig(NET, '0x'+'1'*40, ':memory:', 'audit-secret', 1), verifier=Mock(), worker=Mock(), ledger=Ledger())
        paths = [('GET','/stats')]
    client = TestClient(app, raise_server_exceptions=False)
    for method, path in paths:
        assert client.request(method,path).status_code == 401
        assert client.request(method,path,headers={'Authorization':b'Bearer \xff'}).status_code == 401
    if service == 'collector':
        response = client.post('/admin/crawl', headers={'Authorization':'Bearer audit-secret','Origin':'https://hostile.example'})
        assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
    else:
        assert client.get('/stats',headers={'Authorization':'Bearer audit-secret'}).status_code == 200


def test_shared_outbound_client_enforces_tls_and_disables_environment_proxies(monkeypatch):
    monkeypatch.setenv('HTTP_PROXY','http://127.0.0.1:9999')
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:9999')
    with public_client(verify=False,trust_env=True,follow_redirects=True) as client:
        assert client._trust_env is False and client.follow_redirects is False
        assert not any(client._mounts.values())
        assert client._transport._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED


def test_shared_public_client_fails_closed_if_transport_is_unsupported(monkeypatch):
    import agent_market.broker.discovery as discovery
    fake = Mock()
    fake._transport._pool = object()
    monkeypatch.setattr(discovery.httpx,'Client',lambda **kwargs:fake)
    with pytest.raises(RuntimeError,match='Secure public transport'):
        discovery.public_client()
    fake.close.assert_called_once()

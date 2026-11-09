"""Real-value paths stay closed unless AD_COIN_REAL_VALUE_ENABLED is set (separate from AD_COIN_V2_ENABLED)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2 import fiat_providers, real_value, real_value_http

PATHS = [('post', '/api/ad-coin/v2/real/deposits'), ('post', '/api/ad-coin/v2/real/deposits/d1/confirm'),
         ('post', '/api/ad-coin/v2/real/reserves/checkpoints'), ('get', '/api/ad-coin/v2/real/reserves/proof'),
         ('post', '/api/ad-coin/v2/real/withdrawals'), ('post', '/api/ad-coin/v2/real/withdrawals/w1/confirm'),
         ('post', '/api/ad-coin/v2/real/webhooks/stripe'), ('post', '/api/ad-coin/v2/real/webhooks/circle')]


@pytest.fixture
def switch_off(monkeypatch):
    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)
    monkeypatch.setenv('AD_COIN_V2_ENABLED', '1')  # v2 on must not open real value


@pytest.mark.parametrize('value', ['', '0', 'false', 'no', 'yes', 'on'])
def test_only_an_explicit_true_opens_real_value(monkeypatch, value):
    monkeypatch.setenv('AD_COIN_REAL_VALUE_ENABLED', value)
    assert real_value.is_real_value_enabled() is False


def test_routes_answer_404_when_closed(switch_off):
    called = []
    app = FastAPI()
    app.include_router(real_value_http.router_for(object(), 'clearing', resolve_auth=lambda r: called.append(r)))
    client = TestClient(app)
    for method, path in PATHS:
        response = client.request(method.upper(), path, content=b'{}')
        assert response.status_code == 404, path
    assert not called  # nothing behind the switch ran, not even authentication


@pytest.mark.parametrize('name', ['record_fiat_deposit', 'confirm_fiat_deposit', 'record_custody_reserve_checkpoint',
                                  'reconcile_proof_of_reserves', 'request_onchain_withdrawal',
                                  'confirm_onchain_withdrawal', 'cancel_onchain_withdrawal'])
def test_gateway_refuses_when_closed(switch_off, name):
    gateway = real_value.RealValueGateway(object(), object(), object())
    with pytest.raises(ContractError) as error:
        getattr(gateway, name)(*([None] * 12)[:getattr(gateway, name).__code__.co_argcount - 1])
    assert error.value.code == 'real_value_disabled' and error.value.status == 403


@pytest.mark.parametrize('name', ['handle_stripe_event', 'handle_circle_event'])
def test_webhook_handler_refuses_when_closed(switch_off, name):
    handler = fiat_providers.FiatWebhookHandler.__new__(fiat_providers.FiatWebhookHandler)
    with pytest.raises(ContractError) as error:
        getattr(handler, name)(b'{}', 'sig')
    assert error.value.code == 'real_value_disabled'


def test_live_service_does_not_mount_real_value_when_closed(switch_off):
    import inspect
    from agent_market.ad_coin.v2 import live_service
    source = inspect.getsource(live_service)
    guard = source.index('if not is_real_value_enabled():')
    assert guard < source.index('real_value_router(real_gateway')

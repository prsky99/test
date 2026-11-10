"""Coins are created only by issuance (PM decision 11-10, A): no product path mints from a clearing account."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# model_seed moves coins out of an external clearing account, i.e. creates them. Only the real-value
# deposit (mounted only when AD_COIN_REAL_VALUE_ENABLED is on, which stays off) may still use it.
ALLOWED_MODEL_SEED = {'agent_market/ad_coin/v2/real_value.py'}
MINT = re.compile(r'''(?<![.\w])kind\s*=\s*["']model_seed["']''')  # a ledger.post keyword, not SQL text


def product_sources():
    for path in sorted((ROOT / 'agent_market').rglob('*.py')):
        yield path.relative_to(ROOT).as_posix(), path.read_text()


def test_only_issuance_creates_coins_in_product_code():
    minting = {name for name, text in product_sources() if MINT.search(text)}
    assert minting == ALLOWED_MODEL_SEED, minting
    issuing = {name for name, text in product_sources() if re.search(r'''(?<![.\w])kind\s*=\s*["']issuance["']''', text)}
    assert issuing == {'agent_market/ad_coin/v2/points.py'}, issuing  # points.issue, capped by the ledger


def test_closed_paths_refuse_before_touching_anything():
    import pytest
    from agent_market.ad_coin.v2.ad_relay import AdRelayGateway
    from agent_market.ad_coin.v2.advertiser_platform import AdvertiserPlatformGateway
    from agent_market.ad_coin.v2.contracts import ContractError

    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError('store touched: ' + name)

    stage = AdvertiserPlatformGateway.__new__(AdvertiserPlatformGateway)
    stage.store = stage.ledger = Untouchable()
    with pytest.raises(ContractError) as error:
        stage.claim_stage_reward(offer_id='x', owner_id='y', stage_type='click', evidence={})
    assert (error.value.code, error.value.status) == ('issuance_only', 403)
    relay = AdRelayGateway.__new__(AdRelayGateway)
    relay.store = relay.ledger = Untouchable()
    with pytest.raises(ContractError) as error:
        relay.settle_relay_dispatch('x')
    assert (error.value.code, error.value.status) == ('issuance_only', 403)


def test_real_value_stays_off_by_default(monkeypatch):
    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)
    from agent_market.ad_coin.v2.real_value import is_real_value_enabled
    assert not is_real_value_enabled()

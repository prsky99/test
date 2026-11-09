"""AI AD Coin v1 is frozen as a test-only ledger (decision 2026-11-09)."""
import pytest

from agent_market.ad_coin import config
from agent_market.ad_coin.config import Settings, SettingsError, require_test_mode


def test_v1_is_marked_frozen_test_only():
    assert config.FROZEN_TEST_ONLY is True
    assert Settings().test_mode is True
    assert Settings.from_environment({'AD_COIN_TEST_MODE': '0', 'AD_COIN_ENABLED': '1'}).test_mode is True


@pytest.mark.parametrize('value', [False, 0, None, 'false'])
def test_test_mode_cannot_be_switched_off(value):
    with pytest.raises(SettingsError):
        require_test_mode(value)
    with pytest.raises(SettingsError):
        Settings(test_mode=value)
    with pytest.raises(SettingsError):
        Settings().with_(test_mode=value)


def test_service_and_signer_refuse_live_mode():
    from agent_market.ad_coin.receipts import Signer
    from agent_market.ad_coin.service import AdCoinService
    with pytest.raises(SettingsError):
        AdCoinService(object(), object(), test_mode=False)
    with pytest.raises(SettingsError):
        Signer(None, 'https://example.test', test_mode=False)

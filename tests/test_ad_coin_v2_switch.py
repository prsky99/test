"""AI AD Coin v2 stays off unless AD_COIN_V2_ENABLED is set explicitly."""
import pathlib
import re

import pytest

from agent_market.ad_coin.v2.live_service import is_v2_enabled

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_v2_is_off_without_the_switch(monkeypatch):
    monkeypatch.delenv('AD_COIN_V2_ENABLED', raising=False)
    assert is_v2_enabled() is False


@pytest.mark.parametrize('value', ['', '0', 'false', 'False', 'no', 'off', 'yes', ' 1', 'enabled'])
def test_only_an_explicit_true_turns_v2_on(monkeypatch, value):
    monkeypatch.setenv('AD_COIN_V2_ENABLED', value)
    assert is_v2_enabled() is False


@pytest.mark.parametrize('value', ['1', 'true', 'True'])
def test_explicit_values_turn_v2_on(monkeypatch, value):
    monkeypatch.setenv('AD_COIN_V2_ENABLED', value)
    assert is_v2_enabled() is True


def test_production_config_does_not_enable_v2():
    for path in (ROOT / 'deploy').rglob('*'):
        if path.is_file() and path.suffix in {'.env', '.example', '.plist', '.service', '.toml', '.yaml', '.yml', '.json'}:
            text = path.read_text(errors='ignore')
            assert not re.search(r'AD_COIN_V2_ENABLED\s*=\s*(1|true|True)', text), path


def test_front_mounts_v2_only_behind_the_switch():
    source = (ROOT / 'agent_market' / 'concierge' / 'front.py').read_text()
    if 'create_live_ad_coin_v2_router' not in source:
        return
    for match in re.finditer(r'app\.include_router\(create_live_ad_coin_v2_router', source):
        before = source[:match.start()].rsplit('\n', 3)
        assert any('if is_v2_enabled()' in line for line in before), 'v2 router must sit behind is_v2_enabled()'


def test_front_imports_v2_only_when_switched_on():
    source = (ROOT / 'agent_market' / 'concierge' / 'front.py').read_text()
    if 'create_live_ad_coin_v2_router' not in source:
        return
    switch = source.index("_environ.get('AD_COIN_V2_ENABLED'")
    assert switch < source.index('from ..ad_coin.v2.live_service import')


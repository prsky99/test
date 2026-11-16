"""agent_market/early_data.py: the 425 guard for one-use GETs under TLS 0-RTT (11-16, PM)."""
from types import SimpleNamespace

from agent_market.early_data import is_early, too_early


def req(**headers):
    return SimpleNamespace(headers={k.lower(): v for k, v in headers.items()})


def test_only_early_data_1_is_early():
    assert is_early(req(**{'Early-Data': '1'})) and is_early(req(**{'Early-Data': ' 1 '}))
    assert not is_early(req()) and not is_early(req(**{'Early-Data': '0'}))
    answer = too_early(req(**{'Early-Data': '1'}))
    assert answer.status_code == 425 and answer.headers['cache-control'] == 'no-store'
    assert too_early(req()) is None

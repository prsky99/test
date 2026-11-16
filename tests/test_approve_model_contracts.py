import pytest

from scripts import approve_model_contracts as amc


def test_only_limits_the_pairs_and_rejects_an_unknown_key():
    assert amc.selected(amc.PAIRS, []) == amc.PAIRS
    only = amc.selected(amc.PAIRS, ['agentconcierge-owned:technology-news'])
    assert [pair[0] for pair in only] == ['agentconcierge-owned:technology-news']
    assert all(pair[0] != 'mcp:app.openkrill/papers' for pair in only)
    with pytest.raises(SystemExit):
        amc.selected(amc.PAIRS, ['agentconcierge-owned:nope'])

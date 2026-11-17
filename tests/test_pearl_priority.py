"""PM 11-18 pearl priority: recommendations (gateway_exposure.order_key) and Explore (hybrid_explore's final sort) put
final, then verified pearls first, only for the tool the listing passed its role tests with (recommendations) or among
rows already about the task (Explore); never across a stronger key, never for a pearl whose terms prohibit our relay."""
import json

import pytest

from agent_market import pearls_public
from agent_market.concierge.gateway_exposure import order_key
from tests.test_fast_single_recommendation import catalog  # noqa: F401 -- shared isolated catalog fixture

PEARLS = [
    {'resource_id': 1, 'role': 'weather.forecast.v1', 'level': 'final', 'tool': 'get_forecast', 'terms': 'silent'},
    {'resource_id': 2, 'role': 'weather.forecast.v1', 'level': 'verified', 'tool': 'Forecast', 'terms': 'allowed'},
    {'resource_id': 3, 'role': 'weather.forecast.v1', 'level': 'provisional', 'tool': 'get_forecast', 'terms': 'silent'},
    {'resource_id': 4, 'role': 'sec.filings.v1', 'level': 'final', 'tool': 'list_filings', 'terms': 'prohibits'},
    {'resource_id': 5, 'role': 'ip.lookup.v1', 'level': 'verified', 'tool': 'ip_lookup', 'terms': 'unknown'},
    {'resource_id': 5, 'role': 'geocode.address.v1', 'level': 'final', 'tool': 'geocode', 'terms': 'unknown'},
]


@pytest.fixture
def pearls(tmp_path, monkeypatch):
    def write(entries=PEARLS):
        target = tmp_path / 'public-pearls.json'
        target.write_text(json.dumps({'schema': pearls_public.SCHEMA, 'pearls': entries, 'by_resource': {}}))
        monkeypatch.setenv('PEARLS_PUBLIC_PATH', str(target))
    write()
    return write


def test_rank_follows_the_role_tool_and_the_terms(pearls):
    rank = pearls_public.pearl_rank
    assert rank(1, 'get_forecast') == 0
    assert rank(2, 'forecast') == 1                 # tool names compare without case
    assert rank(1, 'other_tool') == 2               # a pearl for another tool is not a pearl for this card
    assert rank(1, '') == 2                         # a card with no chosen tool gets nothing
    assert rank(3, 'get_forecast') == 2             # provisional is no lift
    assert rank(4, 'list_filings') == 2             # terms prohibit our relay: it keeps its place
    assert rank(5, 'ip_lookup') == 1 and rank(5, 'geocode') == 0   # per role, by the card's tool
    assert rank(5) == 0 and rank(4) == 2            # Explore (no tool): the best relayable entry
    assert rank('1', 'get_forecast') == 2 and rank(None) == 2


def test_no_list_moves_nothing():
    # tests/conftest.py points PEARLS_PUBLIC_PATH at a missing file
    assert pearls_public.pearl_rank(1, 'get_forecast') == 2
    plain = {'id': 9, 'tools': ['get_forecast'], 'task_standing': 0}
    pearl = {'id': 1, 'tools': ['get_forecast'], 'task_standing': 0}
    assert sorted([plain, pearl], key=order_key) == [plain, pearl]


def test_recommendations_put_the_role_pearl_after_successes_and_before_recency(pearls):
    newest = {'id': 9, 'tools': ['get_forecast'], 'task_standing': 0}
    verified = {'id': 2, 'tools': ['forecast'], 'task_standing': 0}
    final = {'id': 1, 'tools': ['get_forecast'], 'task_standing': 0}
    wrong_tool = {'id': 1, 'tools': ['get_alerts'], 'task_standing': 0}
    assert sorted([newest, wrong_tool, verified, final], key=order_key) == [final, verified, newest, wrong_tool]
    # The stronger keys still come first: a recent real success, no paid or account note, not failing, no region limit.
    succeeded = {'id': 9, 'tools': ['x'], 'task_standing': 1}
    assert sorted([final, succeeded], key=order_key)[0] is succeeded
    paid = {'id': 1, 'tools': ['get_forecast'], 'task_standing': 1, 'access_note': 'Paid'}
    failing = {'id': 1, 'tools': ['get_forecast'], 'task_standing': -1}
    limited = {'id': 1, 'tools': ['get_forecast'], 'task_standing': 1, 'region_limited': True}
    assert sorted([paid, failing, limited, newest], key=order_key) == [newest, limited, failing, paid]
    # A pearl whose terms prohibit our relay is not lifted.
    prohibited = {'id': 4, 'tools': ['list_filings'], 'task_standing': 0}
    assert sorted([prohibited, newest], key=order_key) == [prohibited, newest]
    assert sorted([newest, prohibited], key=order_key) == [newest, prohibited]


def test_the_free_choice_slice_is_unchanged(pearls):
    # gateway_exposure.search keeps the first two keys as the free and not failing test.
    assert order_key({'id': 1, 'tools': ['get_forecast'], 'task_standing': 0})[:2] == (False, False)


def test_explore_lifts_pearls_within_a_relevance_step_only(catalog, pearls, monkeypatch):  # noqa: F811
    from agent_market.concierge.hybrid_explore import explore
    store, _, _, add, _ = catalog
    first = add('Weather Forecast Alpha', description='Weather forecast for any city.')
    second = add('Weather Forecast Beta', description='Weather forecast for any city.')
    pearl = add('Weather Forecast Gamma', description='Weather forecast for any city.')
    side = add('Field Notes', description='Notebook app. Also shows a weather forecast widget.')
    pearls([{'resource_id': pearl, 'role': 'weather.forecast.v1', 'level': 'final', 'tool': 'get_forecast',
             'terms': 'silent'},
            {'resource_id': side, 'role': 'weather.forecast.v1', 'level': 'verified', 'tool': 'get_forecast',
             'terms': 'silent'}])
    found = [dict(store.resource(i)) for i in (first, second, side, pearl)]
    monkeypatch.setattr('agent_market.concierge.hybrid_explore.candidates', lambda *a, **k: found)
    order = [item['id'] for item in explore(store, None, 'weather forecast', None, None, False, False, 45)['items']]
    assert order[:3] == [pearl, first, second]      # the pearl leads its step; the rest keep the hybrid order
    assert order[-1] == side                        # a pearl matched only later in its text does not jump a step


def test_explore_without_a_list_keeps_the_hybrid_order(catalog, monkeypatch):  # noqa: F811
    from agent_market.concierge.hybrid_explore import explore
    store, _, _, add, _ = catalog
    ids = [add(f'Weather Forecast {n}', description='Weather forecast for any city.') for n in range(3)]
    found = [dict(store.resource(i)) for i in ids]
    monkeypatch.setattr('agent_market.concierge.hybrid_explore.candidates', lambda *a, **k: found)
    assert [item['id'] for item in explore(store, None, 'weather forecast', None, None, False, False, 45)['items']] == ids

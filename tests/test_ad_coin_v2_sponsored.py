"""Public Sponsored slot: labelled, separate from recommendations, no personal data, fast at scale."""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.sponsored import LABEL, MAX_CARDS, SponsoredSlots
from agent_market.ad_coin.v2.sponsored_http import router_for
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import NOW, _activate_campaign, campaign_body, p1_suite  # noqa: F401

TAXONOMY, REGIONS = frozenset({'research', 'coding'}), frozenset({'US', 'KR'})


def slots_for(suite, **kw):
    return SponsoredSlots(suite.service.store, taxonomy=TAXONOMY, regions=REGIONS, clock=lambda: NOW / 1000, **kw)


def test_only_active_approved_campaigns_appear_with_the_label(p1_suite):  # noqa: F811
    _activate_campaign(p1_suite)
    base = '/api/ad-coin/v2/advertisers/' + p1_suite.advertiser + '/campaigns'
    draft = p1_suite.client.post(base, json=campaign_body(name='Draft only'), headers=p1_suite.headers('editor'))
    assert draft.status_code == 200
    cards = slots_for(p1_suite).cards('research', 'US')
    assert [card['label'] for card in cards] == [LABEL]
    assert cards[0]['advertiser'] == 'Research assistant AI' and 'Draft only' not in json.dumps(cards)
    assert set(cards[0]) == {'id', 'label', 'advertiser', 'text'}  # nothing about people or rankings
    assert slots_for(p1_suite).cards('coding', 'US') == [] and slots_for(p1_suite).cards('research', 'KR') == []


def test_unsupported_targeting_is_refused(p1_suite):  # noqa: F811
    with pytest.raises(ContractError) as error:
        slots_for(p1_suite).cards('medical', 'US')
    assert error.value.status == 422


def test_http_slot_is_public_cached_and_carries_no_reward(p1_suite):  # noqa: F811
    _activate_campaign(p1_suite)
    app = FastAPI()
    app.include_router(router_for(slots_for(p1_suite)))
    response = TestClient(app).get('/api/ad-coin/v2/sponsored', params={'category': 'research', 'region': 'US'})
    assert response.status_code == 200 and 'public' in response.headers['cache-control']
    body = response.json()
    assert body['label'] == LABEL and body['reward'] is None and 'never change which agents' in body['disclosure']
    assert 'set-cookie' not in response.headers
    assert TestClient(app).get('/api/ad-coin/v2/sponsored', params={'category': 'x', 'region': 'US'}).status_code == 422


class FakeStore:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    def atomic(self):
        from contextlib import nullcontext
        return nullcontext()

    def all(self, name, args):
        self.calls += 1
        return self.rows[:args[2]]


def synthetic(count):
    return [{'id': 'c%05d' % n, 'ends_ms': NOW + 10 ** 9,
             'payload_json': json.dumps({'name': 'Advertiser %d' % n, 'creative_text': 'Ad %d' % n,
                                         'task_categories': ['research' if n % 2 else 'coding'],
                                         'regions': ['US', 'KR']})} for n in range(count)]


def test_snapshot_is_reused_within_ttl_and_rotates_fairly():
    store = FakeStore(synthetic(10))
    clock = [NOW / 1000]
    slots = SponsoredSlots(store, taxonomy=TAXONOMY, regions=REGIONS, clock=lambda: clock[0], ttl_seconds=60)
    first = slots.cards('research', 'US')
    assert len(first) == MAX_CARDS and store.calls == 1
    clock[0] += 30
    slots.cards('research', 'US')
    assert store.calls == 1  # served from the snapshot
    clock[0] += 61
    later = slots.cards('research', 'US')
    assert store.calls == 2 and later != first  # refreshed and rotated


def test_lookup_stays_fast_with_five_thousand_campaigns():
    slots = SponsoredSlots(FakeStore(synthetic(5000)), taxonomy=TAXONOMY, regions=REGIONS, clock=lambda: NOW / 1000)
    started = time.perf_counter()
    slots.cards('research', 'US')
    build_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    for _ in range(1000):
        slots.cards('coding', 'KR')
    lookup_ms = (time.perf_counter() - started)  # total seconds for 1000 lookups = ms per lookup
    assert build_ms < 500, build_ms
    assert lookup_ms < 2, lookup_ms


def test_offer_candidates_are_filtered_by_target_in_sql(p1_suite):  # noqa: F811
    """The offer path used to read the first 20 active campaigns and filter afterwards, so matching
    campaigns beyond the first 20 were never offered. The targeting filter now runs in SQL."""
    _activate_campaign(p1_suite, name='Coding helper', task_categories=['coding'])
    _activate_campaign(p1_suite)
    store = p1_suite.service.store
    with store.atomic():
        research = store.all('campaigns_active_candidates_for_target', (NOW, NOW, 'research', 'US'))
        coding = store.all('campaigns_active_candidates_for_target', (NOW, NOW, 'coding', 'US'))
        nothing = store.all('campaigns_active_candidates_for_target', (NOW, NOW, 'research', 'KR'))
    assert [json.loads(r['payload_json'])['name'] for r in research] == ['Research assistant AI']
    assert [json.loads(r['payload_json'])['name'] for r in coding] == ['Coding helper']
    assert nothing == []

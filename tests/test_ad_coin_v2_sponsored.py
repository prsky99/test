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


def book_today(suite, campaign, category='research', region='US'):
    """Only campaigns booked for today appear (coin economy step 3); the first booking is supported."""
    from uuid import uuid4
    from agent_market.ad_coin.v2 import points
    from agent_market.ad_coin.v2.sponsored_booking import DAY_MS, SponsoredBookings
    points.issue(suite.service.ledger, 1000 * points.ATOMS_PER_COIN, reason='test-' + uuid4().hex)
    today = NOW - NOW % DAY_MS
    SponsoredBookings(suite.service.store, suite.service.ledger, taxonomy=TAXONOMY, regions=REGIONS).book(
        suite.advertiser, campaign_id=campaign['id'], day=time.strftime('%Y-%m-%d', time.gmtime(today / 1000)),
        task_category=category, region=region, request_id=uuid4().hex, now_ms=today - 1)


def slots_for(suite, **kw):
    return SponsoredSlots(suite.service.store, taxonomy=TAXONOMY, regions=REGIONS, clock=lambda: NOW / 1000, **kw)


def test_only_active_approved_campaigns_appear_with_the_label(p1_suite):  # noqa: F811
    book_today(p1_suite, _activate_campaign(p1_suite))
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
    book_today(p1_suite, _activate_campaign(p1_suite))
    app = FastAPI()
    app.include_router(router_for(slots_for(p1_suite)))
    response = TestClient(app).get('/api/ad-coin/v2/sponsored', params={'category': 'research', 'region': 'US'})
    assert response.status_code == 200 and 'private' in response.headers['cache-control']  # varies by country (11-11)
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
    # One booked row per campaign and target (the booked-today snapshot shape).
    return [{'id': 'c%05d' % n, 'ends_ms': NOW + 10 ** 9, 'task_category': 'research' if n % 2 else 'coding',
             'region': region,
             'payload_json': json.dumps({'name': 'Advertiser %d' % n, 'creative_text': 'Ad %d' % n})}
            for n in range(count) for region in ('US', 'KR')]


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


def test_contract_placements_limits_site_categories_and_unsold_regions():
    """docs/AD_COIN_SPONSORED_CONTRACT.md (11-11): placement explore|chat, limit 1..2, site categories map."""
    from agent_market.ad_coin.v2.sponsored import SITE_CATEGORIES
    store = FakeStore(synthetic(10))
    slots = SponsoredSlots(store, taxonomy={'research', 'coding', 'technology'}, regions=REGIONS, clock=lambda: NOW / 1000)
    slots._count = lambda *a: None
    body = slots.response('research', 'US', 'chat', 1)
    assert body['placement'] == 'chat' and len(body['cards']) == 1 and body['reward'] is None
    assert slots.response('research', 'FR', 'explore', 2)['cards'] == []          # region not sold: nothing to draw
    assert SITE_CATEGORIES['web_search'] == 'research'
    assert slots.response('web_search', 'US')['cards']                             # main-site category accepted
    for args in (('research', 'US', 'sidebar', 2), ('research', 'US', 'explore', 3), ('medical', 'US', 'explore', 1)):
        with pytest.raises(ContractError):
            slots.response(*args)


def test_http_reads_the_region_from_the_country_header_and_is_private():
    app = FastAPI()
    slots = SponsoredSlots(FakeStore(synthetic(4)), taxonomy=TAXONOMY, regions=REGIONS, clock=lambda: NOW / 1000)
    slots._count = lambda *a: None
    app.include_router(router_for(slots))
    client = TestClient(app)
    hit = client.get('/api/ad-coin/v2/sponsored', params={'category': 'research', 'placement': 'chat', 'limit': 1},
                     headers={'CF-IPCountry': 'us'})
    assert hit.status_code == 200 and len(hit.json()['cards']) == 1
    assert 'private' in hit.headers['cache-control'] and hit.headers['vary'] == 'CF-IPCountry'
    none = client.get('/api/ad-coin/v2/sponsored', params={'category': 'research'})   # no country: no cards
    assert none.status_code == 200 and none.json()['cards'] == []


def test_served_counts_wait_for_the_table_then_add_up(p1_suite):  # noqa: F811
    from agent_market.ad_coin.v2 import sponsored as sp
    book_today(p1_suite, _activate_campaign(p1_suite))
    clock = [NOW / 1000]
    slots = SponsoredSlots(p1_suite.service.store, taxonomy=TAXONOMY, regions=REGIONS, clock=lambda: clock[0])
    slots.response('research', 'US', 'explore', 1)
    clock[0] += sp.FLUSH_SECONDS + 1
    slots.response('research', 'US', 'explore', 1)                 # flush attempt: no table yet, counts kept
    assert sum(slots._served.values()) == 2
    from scripts.ad_coin_v2_migrate import migrate_impressions
    assert migrate_impressions(p1_suite.service.store) == {'sponsored_impressions_table': True}
    clock[0] += sp.FLUSH_SECONDS + 1
    slots.response('research', 'US', 'chat', 1)
    assert slots._served == {}
    from agent_market.ad_coin.sql_registry import unchecked
    store = p1_suite.service.store
    with unchecked(), store.atomic():
        rows = store.database.all("SELECT placement, served FROM adc2_sponsored_impressions ORDER BY placement")
    assert [(r['placement'], int(r['served'])) for r in rows] == [('chat', 1), ('explore', 2)]


def test_advertiser_report_shows_daily_served_counts_only(p1_suite):  # noqa: F811
    from agent_market.ad_coin.v2 import sponsored as sp
    from agent_market.ad_coin.v2.advertiser_history import sponsored_report
    store = p1_suite.service.store
    assert sponsored_report(store, p1_suite.advertiser, now_ms=NOW)['available'] is False   # before the table
    campaign = _activate_campaign(p1_suite)
    book_today(p1_suite, campaign)
    from scripts.ad_coin_v2_migrate import migrate_impressions
    migrate_impressions(store)
    clock = [NOW / 1000]
    slots = SponsoredSlots(store, taxonomy=TAXONOMY, regions=REGIONS, clock=lambda: clock[0])
    slots.response('research', 'US', 'explore', 1)
    slots.response('research', 'US', 'chat', 1)
    clock[0] += sp.FLUSH_SECONDS + 1
    slots.response('research', 'US', 'explore', 1)
    report = sponsored_report(store, p1_suite.advertiser, now_ms=NOW)
    assert report['available'] and report['totals'] == {'explore': 2, 'chat': 1}
    assert {r['placement'] for r in report['rows']} == {'explore', 'chat'}
    assert set(report['rows'][0]) == {'day', 'campaign_id', 'campaign', 'placement', 'task_category', 'region', 'served'}
    other = str(__import__('uuid').uuid4())
    assert sponsored_report(store, other, now_ms=NOW)['rows'] == []          # another advertiser sees nothing


def test_early_data_requests_are_answered_but_not_counted(p1_suite):  # noqa: F811
    """11-12 PM: a request marked Early-Data: 1 (RFC 8470, may be a TLS 0-RTT replay) gets the same cards and
    adds nothing to the served counts."""
    book_today(p1_suite, _activate_campaign(p1_suite))
    slots = slots_for(p1_suite)
    app = FastAPI()
    app.include_router(router_for(slots))
    client = TestClient(app)
    url = '/api/ad-coin/v2/sponsored?placement=explore&category=research'
    early = client.get(url, headers={'CF-IPCountry': 'US', 'Early-Data': '1'})
    assert early.status_code == 200 and len(early.json()['cards']) == 1
    assert sum(slots._served.values()) == 0
    normal = client.get(url, headers={'CF-IPCountry': 'US'})
    assert normal.json()['cards'] == early.json()['cards']
    assert sum(slots._served.values()) == 1
    qa = client.get(url, headers={'CF-IPCountry': 'US', 'X-Agentcon-QA': 'public_full_check'})
    assert qa.json()['cards'] == early.json()['cards']
    assert sum(slots._served.values()) == 1                      # our own measurements are not counted


def test_region_query_only_steers_uncounted_measurements(p1_suite):  # noqa: F811
    """11-12 PM: the country comes from CF-IPCountry; ?region= is ignored unless X-Agentcon-QA is present,
    and those requests are not counted, so nobody can redirect or inflate served counts with the query."""
    book_today(p1_suite, _activate_campaign(p1_suite))      # booked for research, US
    slots = slots_for(p1_suite)
    app = FastAPI()
    app.include_router(router_for(slots))
    client = TestClient(app)
    base = {'placement': 'explore', 'category': 'research'}
    ignored = client.get('/api/ad-coin/v2/sponsored', params={**base, 'region': 'US'}, headers={'CF-IPCountry': 'KR'})
    assert ignored.json()['cards'] == [] and sum(slots._served.values()) == 0           # ① query ignored: KR
    no_header = client.get('/api/ad-coin/v2/sponsored', params={**base, 'region': 'US'})
    assert no_header.json()['cards'] == []                                                # no country, no QA: nothing
    qa = client.get('/api/ad-coin/v2/sponsored', params={**base, 'region': 'US'},
                    headers={'CF-IPCountry': 'KR', 'X-Agentcon-QA': 'house_check'})
    assert len(qa.json()['cards']) == 1 and sum(slots._served.values()) == 0              # ② QA sees US, not counted
    kr = client.get('/api/ad-coin/v2/sponsored', params=base, headers={'CF-IPCountry': 'KR'})
    assert kr.json()['cards'] == []                                                       # ③ KR is KR (nothing booked)
    us = client.get('/api/ad-coin/v2/sponsored', params=base, headers={'CF-IPCountry': 'US'})
    assert len(us.json()['cards']) == 1 and sum(slots._served.values()) == 1


# ---- served counts are never left in memory (11-12 PM): timer, shutdown, no double count, retry on DB error ----

def _served_in_db(store):  # noqa: F811
    from agent_market.ad_coin.sql_registry import unchecked
    with unchecked(), store.atomic():
        row = store.database.one("SELECT COALESCE(SUM(served),0) AS n FROM adc2_sponsored_impressions")
    return int(row['n'])


def _counting_world(p1_suite):  # noqa: F811
    from scripts.ad_coin_v2_migrate import migrate_impressions
    book_today(p1_suite, _activate_campaign(p1_suite))
    migrate_impressions(p1_suite.service.store)
    return slots_for(p1_suite)                     # fixed clock: requests alone never make a flush due


def test_timer_writes_pending_counts_without_another_request(p1_suite):  # noqa: F811
    slots = _counting_world(p1_suite)
    for _ in range(3):
        slots.response('research', 'US', 'explore', 1)
    assert _served_in_db(p1_suite.service.store) == 0 and sum(slots._served.values()) == 3
    slots.start_timer(interval=0.05)
    deadline = time.time() + 5
    while _served_in_db(p1_suite.service.store) < 3 and time.time() < deadline:
        time.sleep(0.05)
    assert _served_in_db(p1_suite.service.store) == 3 and slots._served == {}
    assert slots.stop() == 0                                      # nothing left


def test_shutdown_writes_what_is_left(p1_suite):  # noqa: F811
    slots = _counting_world(p1_suite)
    app = FastAPI()
    app.include_router(router_for(slots))
    with TestClient(app) as client:                               # startup starts the timer (60 s: never fires here)
        for _ in range(2):
            client.get('/api/ad-coin/v2/sponsored', params={'category': 'research'}, headers={'CF-IPCountry': 'US'})
        assert _served_in_db(p1_suite.service.store) == 0
    assert _served_in_db(p1_suite.service.store) == 2 and slots._served == {}   # the slot going down wrote them


def test_concurrent_requests_and_flushes_never_count_twice(p1_suite):  # noqa: F811
    import threading
    slots = _counting_world(p1_suite)
    store = p1_suite.service.store

    def serve():
        for _ in range(50):
            slots.response('research', 'US', 'chat', 1)

    def flush():
        for _ in range(20):
            slots.flush_now()
    workers = [threading.Thread(target=serve) for _ in range(4)] + [threading.Thread(target=flush) for _ in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    slots.flush_now()
    assert _served_in_db(store) == 200 and slots._served == {}


def test_a_failed_write_keeps_the_counts_for_the_next_try(p1_suite, monkeypatch):  # noqa: F811
    slots = _counting_world(p1_suite)
    store = p1_suite.service.store
    for _ in range(4):
        slots.response('research', 'US', 'explore', 1)
    real = store.execute

    def broken(name, *args, **kw):
        if name == 'sponsored_impression_add':
            raise RuntimeError('database unavailable')
        return real(name, *args, **kw)
    monkeypatch.setattr(store, 'execute', broken)
    slots.flush_now()
    assert _served_in_db(store) == 0 and sum(slots._served.values()) == 4    # kept, not lost, not doubled
    monkeypatch.setattr(store, 'execute', real)
    slots.flush_now()
    assert _served_in_db(store) == 4 and slots._served == {}

"""Coin economy step 3: Sponsored day bookings paid with coins (PM decisions 2026-11-10)."""
import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES, OPERATOR_CAPABILITY
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.identity import Kind
from agent_market.ad_coin.v2.sponsored import SponsoredSlots
from agent_market.ad_coin.v2.sponsored_booking import DAY_MS, PLACEMENTS_PER_DAY, PRICE_ATOMS, SponsoredBookings
from agent_market.ad_coin.v2.sponsored_booking_http import router_for
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import NOW, _activate_campaign, p1_suite  # noqa: F401

COIN = points.ATOMS_PER_COIN
TAXONOMY, REGIONS = frozenset({'research', 'coding'}), frozenset({'US', 'KR'})
TODAY = NOW - NOW % DAY_MS


@pytest.fixture(autouse=True)
def _points_mode(monkeypatch):
    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)


def day_text(day_ms):
    return time.strftime('%Y-%m-%d', time.gmtime(day_ms / 1000))


def rid():
    return uuid4().hex


def fund(suite, coins=200, growth=1000):
    ledger = suite.service.ledger
    points.issue(ledger, growth * COIN, reason='test-' + rid())
    ledger.post('grant-' + rid(), [(points.GROWTH_ACCOUNT, str(-coins * COIN)), (suite.available, str(coins * COIN))],
                kind='grant')


def bookings(suite, clock=None):
    return SponsoredBookings(suite.service.store, suite.service.ledger, taxonomy=TAXONOMY, regions=REGIONS,
                             access=suite.service.access, clock=clock or (lambda: NOW / 1000))


def balance(suite, account):
    return int(suite.service.ledger.account(account)['balance_atoms'])


def book(suite, campaign, day_ms, *, now_ms=NOW, category='research', region='US', request_id=None):
    return bookings(suite).book(suite.advertiser, campaign_id=campaign['id'], day=day_text(day_ms),
                                task_category=category, region=region, request_id=request_id or rid(), now_ms=now_ms)


def test_first_booking_is_supported_then_the_advertiser_pays(p1_suite):  # noqa: F811
    s = p1_suite
    fund(s)
    campaign = _activate_campaign(s)
    before, growth, revenue = balance(s, s.available), balance(s, points.GROWTH_ACCOUNT), balance(s, points.REVENUE_ACCOUNT)
    first = book(s, campaign, TODAY + DAY_MS)
    assert first['paid_by'] == 'growth_support' and first['state'] == 'booked' and first['price_atoms'] == str(PRICE_ATOMS)
    assert balance(s, s.available) == before and balance(s, points.GROWTH_ACCOUNT) == growth - PRICE_ATOMS
    second = book(s, campaign, TODAY + 2 * DAY_MS)
    assert second['paid_by'] == 'advertiser' and balance(s, s.available) == before - PRICE_ATOMS
    assert balance(s, points.REVENUE_ACCOUNT) == revenue + 2 * PRICE_ATOMS


def test_same_request_is_one_booking_and_bad_requests_are_refused(p1_suite):  # noqa: F811
    s = p1_suite
    fund(s)
    campaign = _activate_campaign(s)
    request_id = rid()
    first = book(s, campaign, TODAY + DAY_MS, request_id=request_id)
    again = book(s, campaign, TODAY + DAY_MS, request_id=request_id)
    assert again['replayed'] and again['id'] == first['id']
    for day_ms, code in ((TODAY, 'day_not_bookable'), (TODAY + 31 * DAY_MS, 'day_not_bookable')):
        with pytest.raises(ContractError) as error:
            book(s, campaign, day_ms)
        assert error.value.code == code
    with pytest.raises(ContractError) as error:
        book(s, campaign, TODAY + DAY_MS)  # same campaign, day and target with a new request
    assert error.value.code == 'already_booked'
    with pytest.raises(ContractError) as error:
        book(s, campaign, TODAY + DAY_MS, category='medical')
    assert error.value.status == 422


def test_a_day_holds_two_placements_per_target(p1_suite):  # noqa: F811
    s = p1_suite
    fund(s, coins=400)
    campaigns = [_activate_campaign(s, name='Campaign %d' % n) for n in range(PLACEMENTS_PER_DAY + 1)]
    for campaign in campaigns[:PLACEMENTS_PER_DAY]:
        book(s, campaign, TODAY + DAY_MS)
    with pytest.raises(ContractError) as error:
        book(s, campaigns[-1], TODAY + DAY_MS)
    assert error.value.code == 'sponsored_day_full'
    book(s, campaigns[-1], TODAY + DAY_MS, region='KR')  # another region has its own placements


def test_an_unfunded_advertiser_cannot_book_after_the_support(p1_suite):  # noqa: F811
    s = p1_suite
    points.issue(s.service.ledger, 1000 * COIN, reason='test-' + rid())
    campaign = _activate_campaign(s)
    book(s, campaign, TODAY + DAY_MS)  # supported
    with pytest.raises(ContractError) as error:
        book(s, campaign, TODAY + 2 * DAY_MS)
    assert error.value.code == 'insufficient_balance'


def test_cancel_before_the_day_returns_every_coin(p1_suite):  # noqa: F811
    s = p1_suite
    fund(s)
    campaign = _activate_campaign(s)
    book(s, campaign, TODAY + DAY_MS)  # supported first booking
    paid = book(s, campaign, TODAY + 2 * DAY_MS)
    before = balance(s, s.available)
    cancelled = bookings(s).cancel(s.advertiser, paid['id'], now_ms=NOW)
    assert cancelled['state'] == 'refunded' and balance(s, s.available) == before + PRICE_ATOMS
    with pytest.raises(ContractError) as error:
        bookings(s).cancel(s.advertiser, paid['id'], now_ms=NOW)
    assert error.value.code == 'booking_not_cancellable'
    started = book(s, campaign, TODAY + 3 * DAY_MS)
    with pytest.raises(ContractError) as error:
        bookings(s).cancel(s.advertiser, started['id'], now_ms=TODAY + 3 * DAY_MS + 1)
    assert error.value.code == 'booking_day_started'


def test_settlement_refunds_platform_faults_only(p1_suite):  # noqa: F811
    s = p1_suite
    fund(s)
    served_campaign = _activate_campaign(s)
    book(s, served_campaign, TODAY + DAY_MS)  # supported first booking
    served = book(s, served_campaign, TODAY + 2 * DAY_MS)
    faulty_campaign = _activate_campaign(s, name='Suspended later')
    faulty = book(s, faulty_campaign, TODAY + 2 * DAY_MS)
    store = s.service.store
    from agent_market.ad_coin.sql_registry import unchecked
    with unchecked(), store.atomic():
        store._connection().execute("UPDATE adc2_campaigns SET state='suspended' WHERE id=?", (faulty_campaign['id'],))
    before = balance(s, s.available)
    after_day = TODAY + 3 * DAY_MS + 11 * 60_000
    assert bookings(s).settle_due(now_ms=TODAY + 3 * DAY_MS) == 1  # day one closes; day two waits for the delay
    assert bookings(s).settle_due(now_ms=after_day) == 2
    states = {row['id']: row['state'] for row in bookings(s).list(s.advertiser)['items']}
    assert states[served['id']] == 'served' and states[faulty['id']] == 'refunded'
    assert balance(s, s.available) == before + PRICE_ATOMS
    assert bookings(s).settle_due(now_ms=after_day) == 0


def test_snapshot_shows_only_campaigns_booked_for_today(p1_suite):  # noqa: F811
    s = p1_suite
    fund(s)
    booked = _activate_campaign(s, name='Booked today')
    _activate_campaign(s, name='Not booked')
    book(s, booked, TODAY, now_ms=TODAY - 1)
    slots = SponsoredSlots(s.service.store, taxonomy=TAXONOMY, regions=REGIONS, clock=lambda: NOW / 1000)
    cards = slots.cards('research', 'US')
    assert [card['advertiser'] for card in cards] == ['Booked today']
    assert slots.cards('research', 'KR') == []
    tomorrow = SponsoredSlots(s.service.store, taxonomy=TAXONOMY, regions=REGIONS,
                              clock=lambda: (TODAY + DAY_MS + 60_000) / 1000)
    assert tomorrow.cards('research', 'US') == []


def test_http_booking_needs_authority_csrf_and_an_idempotency_key(p1_suite):  # noqa: F811
    s = p1_suite
    fund(s)
    campaign = _activate_campaign(s)
    app = FastAPI()
    app.include_router(router_for(s.service, bookings(s), resolve_auth=s.resolver))
    client = TestClient(app)
    path = '/api/ad-coin/v2/advertisers/' + s.advertiser + '/sponsored-bookings'
    body = {'campaign_id': campaign['id'], 'day': day_text(TODAY + DAY_MS), 'task_category': 'research', 'region': 'US'}
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, json=body, headers=s.headers('user')).status_code == 403  # a person cannot book
    no_key = s.headers('approver')
    no_key.pop('Idempotency-Key')
    assert client.post(path, json=body, headers=no_key).status_code == 428
    no_csrf = s.headers('approver')
    no_csrf.pop('X-CSRF-Token')
    assert client.post(path, json=body, headers=no_csrf).status_code == 403
    done = client.post(path, json=body, headers=s.headers('approver'))
    assert done.status_code == 200 and done.json()['state'] == 'booked'
    listed = client.get(path, headers=s.headers('editor'))
    assert listed.status_code == 200 and [item['id'] for item in listed.json()['items']] == [done.json()['id']]
    refund = client.post('/api/ad-coin/v2/admin/sponsored-bookings/' + done.json()['id'] + '/refund',
                         json={'reason': 'Sponsored outage 2h'}, headers=s.headers('approver'))
    assert refund.status_code == 403 and refund.json()['error']['code'] == 'operator_required'
    staff, owner = str(uuid4()), str(uuid4())
    s.service.access.provision_principal(staff, Kind.HUMAN, owner_id=owner,
                                         capabilities=HUMAN_CAPABILITIES | {OPERATOR_CAPABILITY})
    token, csrf = 'tok-staff-' + rid(), 'csrf-staff-' + rid()
    s.resolver.register_human_session(token, csrf, principal_id=staff, owner_id=owner)
    staff_headers = {'Authorization': 'Bearer ' + token, 'X-AIAC-Contract': 'v6.2'}
    assert client.post('/api/ad-coin/v2/admin/sponsored-bookings/' + done.json()['id'] + '/refund',
                       json={'reason': 'Sponsored outage 2h'}, headers=staff_headers).status_code == 403  # no CSRF
    before = balance(s, points.GROWTH_ACCOUNT)  # the first booking was supported, so coins go back there
    refunded = client.post('/api/ad-coin/v2/admin/sponsored-bookings/' + done.json()['id'] + '/refund',
                           json={'reason': 'Sponsored outage 2h'}, headers={**staff_headers, 'X-CSRF-Token': csrf})
    assert refunded.status_code == 200 and refunded.json()['state'] == 'refunded'
    assert balance(s, points.GROWTH_ACCOUNT) == before + PRICE_ATOMS


def test_public_terms_match_the_approved_clauses_word_for_word():
    """The eight clauses the user approved (11-10) and term 9 (USDC, 11-11) appear unchanged in the English workspace."""
    import html as htmllib
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    report = (root / 'reports/AI-AD-Coin-Sponsored-광고주약관-조항초안-2026-11-10.md').read_text()
    clauses = re.findall(r'^> \*\*\d\. (.+?)\*\* (.+)$', report, re.M)
    assert len(clauses) == 8
    usdc = (root / 'reports/AI-AD-Coin-USDC-유료예약-설계-2026-11-11.md').read_text()   # term 9, approved 11-11
    clauses += re.findall(r'^> \*\*9\. (.+?)\*\* (.+)$', usdc, re.M)
    assert len(clauses) == 9
    page = (root / 'agent_market/ad_coin/v2/web/index.html').read_text()
    section = page[page.index('id="sponsored-terms"'):]
    section = section[:section.index('</section>')]
    items = [htmllib.unescape(re.sub(r'<[^>]+>', '', item)).strip()
             for item in re.findall(r'<li>(.*?)</li>', section, re.S)]
    expected = [title + ' ' + body for title, body in clauses]
    # 11-14: the public brand is AgentValCon (user decision); the approved clauses are otherwise unchanged
    straight = [item.replace('“', '"').replace('”', '"').replace('’', "'").replace('AgentValCon', 'Agent Concierge')
                for item in items]
    assert straight == expected
    assert 'Sponsored placement terms' in section and 'Paid Sponsored placements' in section and '<!--' not in page


def test_sponsored_only_campaigns_are_never_offered_for_rewarded_views(p1_suite):  # noqa: F811
    """11-11 (PM d): a per-view reward of 2 atoms marks a Sponsored-only campaign; P1 candidates skip it."""
    from tests.test_ad_coin_v2_p1 import NOW as P1_NOW
    s = p1_suite
    fund(s)
    only = _activate_campaign(s, name='Sponsored only', total_budget_atoms='2', daily_budget_atoms='2', gross_p1_atoms='2')
    store = s.service.store
    with store.atomic():
        ids = [r['id'] for r in store.all('campaigns_active_candidates_for_target', (P1_NOW, P1_NOW, 'research', 'US'))]
    assert only['id'] not in ids
    book(s, only, TODAY + DAY_MS)                                   # still bookable for Sponsored days

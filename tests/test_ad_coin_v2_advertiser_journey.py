"""The whole advertiser payment path, end to end, in process (AI AD Coin audit 11-17, for the 11-18 bundle).

A. A person: /advertise -> its links -> the advertiser workspace -> application -> campaign -> review -> start ->
   a paid day quote and a custom plan quote -> payment with a transaction hash -> confirmation by the worker ->
   the Sponsored slot serving it -> the advertiser's served counts.
B. An agent: what llms.txt, skill.md, agent-entry (advertise.keyless) and the A2A card say -> POST /sponsor ->
   GET /sponsor/{order_id} with X-Read-Key (review, then quote) -> POST .../payment -> confirmation -> serving ->
   taken down with a refund due.

Each step asserts the hand-off: what the previous answer tells the caller to do next works at the next step (paths,
headers, fields, amounts, chain id, token, expiry, state names). A gap the audit found and did not fix stays as a
strict xfail whose reason names it, so the file passes and records the gap until it is closed.

Only in-process clients, the throwaway PostgreSQL cluster of the other v2 tests, a fake Base chain (FakeRPC) and a
fixed KRW rate: no server, no public address, no real chain, wallet or key.
"""
import re
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.v2 import keyless_sponsor as keyless
from agent_market.ad_coin.v2 import paid_bookings as paid
from agent_market.ad_coin.v2.commercial import date_text, etag
from agent_market.ad_coin.v2.contracts import canonical_bytes
from agent_market.ad_coin.v2.sponsored_booking import DAY_MS, HORIZON_DAYS, PLACEMENTS_PER_DAY, day_ms_of
from agent_market.concierge import ad_slot
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_keyless_sponsor import (GOOD, _offline, order, review, rows, shop,  # noqa: F401
                                                   status, tomorrow)
from tests.test_ad_coin_v2_p1 import NOW, campaign_body, p1_suite  # noqa: F401
from tests.test_ad_coin_v2_paid_bookings import PAY_TO, FakeRPC, operator
from tests.test_ad_coin_v2_persistence import store, uid  # noqa: F401

TODAY = NOW - NOW % DAY_MS
DAY = time.strftime('%Y-%m-%d', time.gmtime((TODAY + DAY_MS) / 1000))


def text_of(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', value)).replace('&rsquo;', '’')


# ---------------------------------------------------------------------------------------------------------------------
# A. A person
# ---------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def person(p1_suite, monkeypatch):  # noqa: F811
    """The live v2 routes a signed-in person uses (the p1 session stands in for the site sign-in bridge)."""
    from agent_market.ad_coin.v2.admin_page import router_for as admin_page_router
    from agent_market.ad_coin.v2.ads_library import router_for as ads_library_router
    from agent_market.ad_coin.v2.advertiser_applications_http import router_for as applications_router
    from agent_market.ad_coin.v2.http import router_for
    from agent_market.ad_coin.v2.paid_bookings_http import router_for as paid_router
    from agent_market.ad_coin.v2.sponsored_booking import SponsoredBookings
    from agent_market.ad_coin.v2.sponsored_booking_http import router_for as coin_booking_router
    from agent_market.concierge.advertise_page import advertise_router
    from scripts.ad_coin_v2_migrate import migrate_impressions, migrate_paid, migrate_paid_plans
    monkeypatch.setenv(paid.ENABLED_ENV, '1')
    suite, service = p1_suite, p1_suite.service
    store = service.store
    migrate_paid(store)
    migrate_paid_plans(store)
    migrate_impressions(store)
    rpc = FakeRPC()
    bookings = paid.PaidBookings(store, paid.PaidConfig(pay_to=PAY_TO), rpc=rpc,
                                 sanctions=paid.Sanctions(addresses=['0x' + '9' * 40]), taxonomy=service.taxonomy,
                                 regions=service.regions, krw_rate=lambda: '1400', clock=lambda: (NOW + 60_000) / 1000)
    app = FastAPI()
    app.include_router(router_for(service, resolve_auth=suite.resolver, include_workspace=True))
    app.include_router(paid_router(service, bookings, resolve_auth=suite.resolver))
    app.include_router(applications_router(service, resolve_auth=suite.resolver))
    app.include_router(coin_booking_router(service, SponsoredBookings(
        store, service.ledger, taxonomy=service.taxonomy, regions=service.regions, access=service.access),
        resolve_auth=suite.resolver))
    app.include_router(admin_page_router())
    app.include_router(advertise_router())
    app.include_router(ads_library_router(store, clock=lambda: (TODAY + DAY_MS + 3_600_000) / 1000))
    client = TestClient(app)
    client.suite, client.bookings, client.rpc, client.store = suite, bookings, rpc, store
    return client


def test_a1_advertise_links_reach_the_workspace_the_terms_and_the_library(person):
    page = person.get('/advertise')
    assert page.status_code == 200
    links = set(re.findall(r'href="(/[^"]*)"', page.text))
    assert {'/ad-coin/v2#advertising', '/ad-coin/v2/advertise', '/ads/library'} <= links
    workspace = person.get('/ad-coin/v2')
    assert workspace.status_code == 200 and 'data-view="advertising"' in workspace.text
    assert 'href="/customer/sign-in"' in workspace.text                    # the site sign-in, then back here
    details = person.get('/ad-coin/v2/advertise')
    assert details.status_code == 200 and '@@' not in details.text
    for link in re.findall(r'href="(/ad-coin/[^"#]*)', details.text):
        assert person.get(link).status_code == 200, link
    assert person.get('/ads/library').status_code == 200 and person.get('/ads/library.json').status_code == 200


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='F-A1: /customer/sign-in only returns to /customer/* pages '
                   '(customer_navigation.destination), so a person who opened the advertiser workspace and signs in '
                   'lands on /customer/workspaces, which has no link back to /ad-coin/v2#advertising')
def test_a1b_sign_in_returns_to_the_advertiser_workspace():
    from agent_market.customer_navigation import destination
    assert destination('/ad-coin/v2') == '/ad-coin/v2'


def test_a2_numbers_on_the_pages_are_the_ones_the_code_uses(person):
    from agent_market.concierge import advertise_page
    on = text_of(person.get('/advertise').text)
    details = text_of(person.get('/ad-coin/v2/advertise').text)
    price = paid.PaidConfig(pay_to=PAY_TO).price_units
    assert advertise_page.PRICE_USDC * paid.USDC_UNITS == price and '5 USDC on Base per placement per day' in on
    assert PLACEMENTS_PER_DAY == 2 and 'two placements a day' in on and 'Each pair has two placements a day' in details
    assert HORIZON_DAYS == 30 and 'from tomorrow up to 30 days ahead' in details
    assert 'no stored balance and no subscription' in on and 'There is no stored balance and no subscription' in details
    for word in ('guaranteed', '#1', ' best ', 'top-rated', 'always use'):
        assert word not in on.lower() and word not in details.lower(), word


def _write(person, path, body, **headers):
    return person.post('/api/ad-coin/v2' + path, json=body, headers=person.suite.headers('user', **headers))


def _fresh(person, campaign):
    """The workspace's approveAndStart: a human challenge for approve_campaign, then approvals, then activation."""
    suite, base = person.suite, '/advertisers/' + campaign['advertiser_id'] + '/campaigns/' + campaign['id']
    intended = suite.service.contract.parse(
        'approveCampaign', canonical_bytes({'revision_hash': campaign['revision_hash'], 'fresh_action_id': uid(),
                                            'fresh_action_proof': 'p' * 43}),
        path_parameters={'advertiser_id': campaign['advertiser_id'], 'campaign_id': campaign['id']},
        if_match=etag(campaign))
    challenge = _write(person, '/human-challenges', {'action': 'approve_campaign', 'target_id': campaign['id'],
                                                      'target_revision_hash': campaign['revision_hash'],
                                                      'request_digest': intended.semantic_digest})
    assert challenge.status_code == 200, challenge.text
    approved = _write(person, base + '/approvals', {'revision_hash': campaign['revision_hash'],
                                                     'fresh_action_id': challenge.json()['fresh_action_id'],
                                                     'fresh_action_proof': challenge.json()['proof_challenge']},
                      **{'If-Match': etag(campaign)})
    assert approved.status_code == 200, approved.text
    started = _write(person, base + '/activation', {'revision_hash': approved.json()['revision_hash']},
                     **{'If-Match': etag(approved.json())})
    assert started.status_code == 200, started.text
    return started.json()


def _started_campaign(person):
    from agent_market.ad_coin.v2 import operator_review
    suite = person.suite
    applied = _write(person, '/advertiser-applications', {'display_name': 'Paper Finder Test'})
    assert applied.status_code == 200 and applied.json()['status'] == 'approved', applied.text   # opens at once
    advertiser = applied.json()['application_id']
    created = _write(person, '/advertisers/' + advertiser + '/campaigns', campaign_body(
        name='Paper Finder launch', total_budget_atoms='2', daily_budget_atoms='2', gross_p1_atoms='2',
        ends_at=date_text(NOW + 5 * DAY_MS),
        creative_text='Searches papers by topic and returns citations with abstracts.'))
    assert created.status_code == 200, created.text
    campaign = created.json()
    asked = _write(person, '/advertisers/' + advertiser + '/campaigns/' + campaign['id'] + '/review-request',
                   {'revision_hash': campaign['revision_hash']}, **{'If-Match': created.headers['etag']})
    assert asked.status_code == 200, asked.text
    operator_review.decide(suite.service, operator(suite), asked.json()['id'], verdict='eligible', reason_code='verified')
    current = person.get('/api/ad-coin/v2/advertisers/' + advertiser + '/campaigns/' + campaign['id'],
                         headers=suite.headers('user')).json()
    assert (current['state'], current['approval_status']) == ('eligible', 'unapproved')   # "Review and start" shows
    active = _fresh(person, current)
    assert active['state'] == 'active'
    return advertiser, active


def test_a3_application_campaign_review_start_quote_pay_confirm_serve_and_count(person):
    from agent_market.ad_coin.v2.advertiser_history import sponsored_report
    from agent_market.ad_coin.v2.sponsored import SponsoredSlots
    advertiser, campaign = _started_campaign(person)
    root = '/advertisers/' + advertiser
    quote = _write(person, root + '/paid-bookings', {'campaign_id': campaign['id'], 'day': DAY,
                                                     'task_category': 'research', 'region': 'US'})
    assert quote.status_code == 200, quote.text
    q = quote.json()
    # What the workspace's quote card reads (showPayment): amount_usdc, pay_to, expires_ms, day_ms, state.
    assert (q['state'], q['chain_id'], q['token'], q['pay_to'], q['network']) == (
        'quoted', 8453, paid.BASE_USDC, PAY_TO, 'Base')
    assert 5_000_001 <= int(q['amount_units']) <= 5_009_999 and q['amount_usdc'] == paid._usdc(q['amount_units'])
    assert q['expires_ms'] == NOW + 60_000 + paid.QUOTE_TTL_MS and q['day_ms'] == TODAY + DAY_MS
    tx = person.rpc.send(int(q['amount_units']), block=99)                     # two confirmations of three
    sent = _write(person, root + '/paid-bookings/' + q['id'] + '/payment', {'tx_hash': tx})
    assert sent.status_code == 200 and sent.json()['state'] == 'confirming', sent.text
    person.rpc.head = 102
    assert person.bookings.recheck(now_ms=NOW + 120_000) >= 1                  # the worker's pass confirms it
    listed = person.get('/api/ad-coin/v2' + root + '/paid-bookings', headers=person.suite.headers('user')).json()
    assert [(i['id'], i['state'], i['tx_hash']) for i in listed['items']] == [(q['id'], 'confirmed', tx)]
    day_clock = (TODAY + DAY_MS + 3_600_000) / 1000
    slots = SponsoredSlots(person.store, taxonomy=person.suite.service.taxonomy, regions=person.suite.service.regions,
                           clock=lambda: day_clock)
    served = slots.response('research', 'US', 'explore', 2)
    assert [c['id'] for c in served['cards']] == [campaign['id']] and served['label'] == 'Sponsored'
    assert served['cards'][0]['advertiser'] == 'Paper Finder launch'
    assert slots.flush_now() == 1
    report = sponsored_report(person.store, advertiser, now_ms=int(day_clock * 1000))
    assert report['totals']['explore'] == 1
    library = person.get('/ads/library.json').json()
    assert any(e['campaign_id'] == campaign['id'] for e in library['current'])
    assert library['rules']['affects'] == {'ranking': False, 'selection': False, 'test_results': False}


def test_a4_a_custom_plan_is_one_quote_one_payment_and_every_placement_serves(person):
    from agent_market.ad_coin.v2.sponsored import SponsoredSlots
    advertiser, campaign = _started_campaign(person)
    root = '/advertisers/' + advertiser
    options = _write(person, root + '/paid-plans/options', {'campaign_id': campaign['id'], 'budget_usdc': '10',
                                                            'task_categories': ['research'], 'regions': ['KR']})
    assert options.status_code == 200, options.text
    offered = options.json()
    assert offered['minimum_usdc'] == '10' and 'not charged' in offered['note']
    plan = offered['plans'][0]
    assert plan['placements'] == 2 and plan['total_usdc'] == '10'
    quoted = _write(person, root + '/paid-plans', {'campaign_id': campaign['id'], 'items': plan['items']})
    assert quoted.status_code == 200, quoted.text
    q = quoted.json()
    # The workspace's quote card for a plan reads items, placements, amount_usdc, pay_to and expires_ms.
    assert q['placements'] == 2 and [i['day'] for i in q['items']] == [i['day'] for i in plan['items']]
    assert (q['chain_id'], q['token'], q['pay_to']) == (8453, paid.BASE_USDC, PAY_TO)
    assert 10_000_001 <= int(q['amount_units']) <= 10_009_999
    tx = person.rpc.send(int(q['amount_units']))
    sent = _write(person, root + '/paid-plans/' + q['id'] + '/payment', {'tx_hash': tx})
    assert sent.status_code == 200 and sent.json()['state'] == 'confirmed', sent.text
    assert {i['state'] for i in sent.json()['items']} == {'confirmed'}
    for item in q['items']:
        day_ms = day_ms_of(item['day'])
        slots = SponsoredSlots(person.store, taxonomy=person.suite.service.taxonomy,
                               regions=person.suite.service.regions, clock=lambda d=day_ms: (d + 3_600_000) / 1000)
        assert [c['id'] for c in slots.response('research', 'KR', 'chat', 2)['cards']] == [campaign['id']], item


def test_a5_the_report_counts_agent_answers_too(person):
    """Once migrate-agent-ads widened the placement CHECK, MCP and A2A showings are counted with placement 'mcp' or
    'a2a'. The advertiser report and its totals must take those rows (they raised KeyError before 11-17)."""
    from agent_market.ad_coin.v2.advertiser_history import sponsored_report
    from scripts.ad_coin_v2_migrate import migrate_agent_ads
    advertiser, campaign = _started_campaign(person)
    migrate_agent_ads(person.store)
    with person.store.atomic():
        person.store.execute('sponsored_impression_add', (TODAY + DAY_MS, campaign['id'], 'research', 'US', 'mcp', 3))
        person.store.execute('sponsored_impression_add', (TODAY + DAY_MS, campaign['id'], 'research', 'US', 'explore', 2))
    report = sponsored_report(person.store, advertiser, now_ms=TODAY + DAY_MS)
    assert report['totals']['explore'] == 2 and report['totals']['mcp'] == 3
    answer = person.get('/api/ad-coin/v2/advertisers/' + advertiser + '/sponsored-report',
                        headers=person.suite.headers('user'))
    assert answer.status_code == 200 and answer.json()['totals']['mcp'] == 3


def test_a6_a_payment_of_another_amount_is_refused_and_late_ones_are_held_as_the_page_says(person):
    """11-17 audit F-A2: the page said a mismatched payment is held for review; R32 refuses it and attaches nothing.
    The page now says what happens: another amount is refused (returned by hand), a late exact one is held."""
    from agent_market.ad_coin.v2.admin_page import advertise_html
    page = text_of(advertise_html())
    assert 'a payment of any other amount than the quote is not attached to a booking' in page
    assert 'arrives after the quote expired is held for review' in page
    advertiser, campaign = _started_campaign(person)
    root = '/advertisers/' + advertiser
    q = _write(person, root + '/paid-bookings', {'campaign_id': campaign['id'], 'day': DAY, 'task_category': 'research',
                                                 'region': 'US'}).json()
    sent = _write(person, root + '/paid-bookings/' + q['id'] + '/payment', {'tx_hash': person.rpc.send(5_000_000)})
    assert sent.status_code == 409 and sent.json()['error']['code'] == 'amount_mismatch', sent.text
    late = paid.PaidBookings(person.store, person.bookings.config, rpc=person.rpc, sanctions=person.bookings.sanctions,
                             taxonomy=person.bookings.taxonomy, regions=person.bookings.regions, krw_rate=lambda: '1400',
                             clock=lambda: (q['expires_ms'] + 60_000) / 1000)
    held = late.submit(advertiser, q['id'], person.rpc.send(int(q['amount_units'])))
    assert held['state'] == 'review'


# ---------------------------------------------------------------------------------------------------------------------
# B. An agent with no account
# ---------------------------------------------------------------------------------------------------------------------

def test_b1_the_documents_name_the_routes_header_and_fields_the_api_takes(shop):  # noqa: F811
    from agent_market.ad_coin.v2.keyless_sponsor_http import router_for
    entry = ad_slot.buy_entry()['keyless']
    routes = {(m, r.path) for r in router_for(shop.sponsor).routes for m in getattr(r, 'methods', ())}
    assert ('POST', entry['path']) in routes
    assert ('GET', entry['path'] + '/{order_id}') in routes and ('POST', entry['path'] + '/{order_id}/payment') in routes
    for step, (method, path) in zip(entry['steps'], (('POST', entry['path']), ('GET', entry['path'] + '/{order_id}'),
                                                      ('POST', entry['path'] + '/{order_id}/payment'))):
        assert step.startswith(method + ' ' + path + ' '), step
    fields = {f.strip() for part in entry['body'] for f in part.split('|')}
    assert fields == {'name', 'text', 'url', 'category', 'region', 'day', 'budget_usdc'}
    refused = shop.post('/api/ad-coin/v2/sponsor', json={**GOOD, 'day': tomorrow(), 'extra': 1})
    assert refused.json()['error']['code'] == 'unknown_field'             # the documented set is the whole set
    created = order(shop)
    assert created.status_code == 201
    body = created.json()
    assert list(entry['headers']) == [body['read_key_header']] == ['X-Read-Key']
    assert body['status_url'] == entry['path'] + '/' + body['order_id'] and 'cannot be recovered' in body['note']
    line = ad_slot.buy_line()
    assert all(step in line for step in entry['steps'])
    card_text = ad_slot.a2a_advertise('How do I buy a sponsored placement?')
    assert card_text is not None and card_text[1]['keyless'] == entry


@pytest.mark.xfail(strict=True, raises=KeyError, reason='F-B1: the agent documents name the fields but not the values the API accepts '
                   '(region US/KR/JP/GB/DE, a site category, day YYYY-MM-DD from tomorrow to 30 days, budget_usdc of '
                   'at least 10); a wrong guess only gets unsupported_targeting or day_not_bookable')
def test_b1b_the_documents_say_which_values_are_accepted():
    from agent_market.ad_coin.v2.live_service import DEFAULT_REGIONS
    entry = ad_slot.buy_entry()['keyless']
    assert set(entry['accepted']['region']) == set(DEFAULT_REGIONS)


def test_b2_order_review_quote_pay_confirm_and_serve_in_the_steps_the_documents_give(shop, monkeypatch):  # noqa: F811
    from agent_market.ad_coin.v2.sponsored import SponsoredSlots
    from agent_market.ad_coin.v2.sponsored_agent import AgentOfferProvider
    from agent_market.ad_coin.v2 import auto_review
    monkeypatch.setenv(paid.ENABLED_ENV, '1')
    created = order(shop).json()
    order_id, key = created['order_id'], created['read_key']
    # step 2: in_review until the ad passes review
    assert status(shop, order_id, key).json()['state'] == 'in_review'
    review(shop, order_id)
    answer = status(shop, order_id, key).json()
    assert answer['state'] == 'approved' and answer['payment_url'] == created['status_url'] + '/payment'
    quote = answer['quote']
    # "the quote (exact USDC amount, pay_to, chain 8453, expiry)" and PAY_NOTE's field names
    for field in ('amount_usdc', 'pay_to', 'expires_at'):
        assert field in answer['note'] and quote[field], field
    assert (quote['chain_id'], quote['token'], quote['token_symbol'], quote['network']) == (
        8453, paid.BASE_USDC, 'USDC', 'Base')
    assert quote['expires_at'] == keyless._iso(quote['expires_ms'])
    assert 0 < quote['expires_ms'] - time.time() * 1000 <= paid.QUOTE_TTL_MS
    # step 3 with fewer confirmations than needed: confirming, then the worker's recheck confirms it
    shop.rpc.head = 100
    tx = shop.rpc.send(int(quote['amount_units']), block=99)
    sent = shop.post(answer['payment_url'], json={'tx_hash': tx}, headers={'X-Read-Key': key})
    assert sent.status_code == 200 and sent.json()['quote']['state'] == 'confirming', sent.text
    assert status(shop, order_id, key).json()['quote']['state'] == 'confirming'
    shop.rpc.head = 102
    shop.sponsor.bookings.recheck()
    assert status(shop, order_id, key).json()['quote']['state'] == 'confirmed'
    # serving on the booked day: the Explore card at once
    campaign_id = shop.sponsor._campaign_id(order_id)
    day_ms = day_ms_of(tomorrow())
    clock = lambda: (day_ms + 3_600_000) / 1000  # noqa: E731
    slots = SponsoredSlots(shop.store, taxonomy=shop.commercial.taxonomy, regions=shop.commercial.regions, clock=clock)
    cards = slots.response('web_search', 'US', 'explore', 2)['cards']
    assert [c['id'] for c in cards] == [campaign_id] and cards[0]['text'] == GOOD['text']
    # the agent offer: once approved (here by the automatic review with its checks passed) it follows MCP answers
    auto_review.run(shop.commercial, limit=50, screen=lambda *a, **k: [])
    provider = AgentOfferProvider(slots, clock=clock, url_check=lambda url: True)
    assert provider.refresh() == 1
    ad_slot.register(provider)
    try:
        ctx = ad_slot.context('mcp', 'find_agents', {'category': 'web_search'}, {'cf-ipcountry': 'US'})
        result = ad_slot.attach_mcp({'content': [{'type': 'text', 'text': 'organic'}], 'structuredContent': {}}, ctx)
    finally:
        ad_slot.register(None)
    [offer] = result['structuredContent']['sponsored']
    assert result['content'][0]['text'] == 'organic' and result['content'][-1]['text'].startswith('Sponsored: ')
    assert offer['advertiser'] == GOOD['name'] and offer['offer']['endpoint'] == GOOD['url']
    assert offer['disclosure']['affects'] == {'ranking': False, 'selection': False, 'test_results': False}
    assert provider.flush_now() == 1
    served = rows(shop.store, "SELECT placement,served FROM adc2_sponsored_impressions WHERE campaign_id='%s'" % campaign_id)
    assert served == [{'placement': 'mcp', 'served': 1}]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='F-B2: status says approved and quotes as soon as the campaign review passes, '
                   'but the agent offer (the MCP/A2A placement the documents sell) is reviewed separately and stays '
                   'pending or held (endpoint:not_in_catalog) until a person approves it; the buyer can pay and get '
                   'no MCP/A2A offer, and status never shows the offer state')
def test_b3_status_shows_the_agent_offer_state_before_the_buyer_pays(shop):  # noqa: F811
    created = order(shop).json()
    review(shop, created['order_id'])
    answer = status(shop, created['order_id'], created['read_key']).json()
    assert answer['state'] == 'approved' and answer['quote'] is not None
    assert answer.get('offer_state') in ('approved', 'pending')


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='F-B3: a USDC transfer that lands after expires_at cannot be posted: pay() looks '
                   'only at a live quote (no_open_quote), so the late-payment review that PaidBookings.submit gives a '
                   'person never runs for a keyless order and the money is attached to nothing')
def test_b4_a_late_payment_is_kept_for_review(shop):  # noqa: F811
    created = order(shop).json()
    order_id, key = created['order_id'], created['read_key']
    review(shop, order_id)
    quote = status(shop, order_id, key).json()['quote']
    tx = shop.rpc.send(int(quote['amount_units']))
    later = time.time() + paid.QUOTE_TTL_MS / 1000 + 60
    shop.sponsor.bookings._clock = lambda: later
    sent = shop.post('/api/ad-coin/v2/sponsor/' + order_id + '/payment', json={'tx_hash': tx},
                     headers={'X-Read-Key': key})
    assert sent.status_code == 200 and sent.json()['quote']['state'] == 'review', sent.text


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='F-B4: /advertise says your own report shows how often the placement was shown; '
                   'a keyless buyer has no workspace and the status answer carries no served counts')
def test_b5_a_keyless_buyer_can_read_served_counts(shop):  # noqa: F811
    created = order(shop).json()
    review(shop, created['order_id'])
    answer = status(shop, created['order_id'], created['read_key']).json()
    assert 'served' in answer


def test_b6_takedown_after_payment_shows_the_refund_due_and_stops_serving(shop, monkeypatch):  # noqa: F811
    from agent_market.ad_coin.v2 import auto_review
    from agent_market.ad_coin.v2.sponsored import SponsoredSlots
    monkeypatch.setenv(paid.ENABLED_ENV, '1')
    created = order(shop).json()
    order_id, key = created['order_id'], created['read_key']
    review(shop, order_id)
    quote = status(shop, order_id, key).json()['quote']
    shop.post('/api/ad-coin/v2/sponsor/' + order_id + '/payment', json={'tx_hash': shop.rpc.send(int(quote['amount_units']))},
              headers={'X-Read-Key': key})
    auto_review.takedown(shop.commercial, auto_review.principal(shop.commercial.access), order_id, reason='misleading offer')
    body = status(shop, order_id, key).json()
    assert body['state'] == 'taken_down' and body['refunds'][0]['state'] == 'refund_due'
    assert body['refunds'][0]['amount_usdc'] == quote['amount_usdc'] and 'by the operator' in body['note']
    day_ms = day_ms_of(tomorrow())
    slots = SponsoredSlots(shop.store, taxonomy=shop.commercial.taxonomy, regions=shop.commercial.regions,
                           clock=lambda: (day_ms + 3_600_000) / 1000)
    assert slots.response('web_search', 'US', 'explore', 2)['cards'] == []


# ---------------------------------------------------------------------------------------------------------------------
# Public wording on the path, against the code and the ad rules
# ---------------------------------------------------------------------------------------------------------------------

def test_c1_the_agent_card_never_says_advertising_is_disabled_next_to_the_advertise_skill():
    from agent_market.concierge import front
    source = open(front.__file__, encoding='utf-8').read()
    assert 'advertising delivery is disabled' not in source.lower()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='F-C2: ad_rules.RESTRICTED matches inside words (cure in secure, election '
                   'in selection, crypto in cryptography), so ordinary ad text is held for a person')
@pytest.mark.parametrize('line', ['Secure web search with source selection.', 'Accurate cryptography checks for APIs.'])
def test_c2_ordinary_words_are_not_held_as_a_restricted_class(line):
    from agent_market.ad_coin.v2.ad_rules import flags
    assert 'text:restricted_class' not in flags('text', line)


def test_c3_clicks_are_described_as_the_code_counts_them():
    """Clicks on an offer's link are counted on our server (sponsored_http.sponsored_click, count_click); the pages
    must not say clicks are not counted."""
    from agent_market.ad_coin.v2.admin_page import advertise_html
    assert 'We do not count clicks' not in advertise_html()
    assert 'not clicks or people' not in open('agent_market/ad_coin/v2/web/app.js', encoding='utf-8').read()

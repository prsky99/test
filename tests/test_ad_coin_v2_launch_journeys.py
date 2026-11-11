"""Launch readiness (PM 11-10): the first person, advertiser and operator on a production-like v2.

Each test walks a journey through the live router with production settings (site sign-in bridge,
persistent link key, model activation as stored, no test mTLS header) and pins where it stops today.
reports/AI-AD-Coin-출시준비점검-2026-11-10.md explains each stop.
"""
from uuid import uuid4

import pytest

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.economy import CoinEconomy
from agent_market.ad_coin.v2.ledger import ModelLedger
from agent_market.ad_coin.v2.sponsored_booking import SponsoredBookings
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_site_session import COOKIE, headers, site  # noqa: F401


@pytest.fixture(autouse=True)
def _points_mode(monkeypatch):
    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)


def test_first_person_signs_in_but_has_no_way_to_earn_points(site):  # noqa: F811
    token = site.identity.sign_in('cu_' + 'a' * 32)
    session = site.get('/ad-coin/v2/ui/session', headers=headers(token))
    assert session.status_code == 200                                    # possible now
    wallet = session.json()['wallets'][0]
    assert wallet['available_atoms'] == '0'
    # Points come from ad rewards (needs an active campaign) or a growth grant (needs an operator).
    offer = site.post('/api/ad-coin/v2/offers', json={'task_category': 'research', 'language': 'en',
                                                     'coarse_region': 'US'},
                      headers=headers(token, **{'Idempotency-Key': str(uuid4()), 'X-AIAC-Contract': 'v6.2',
                                                'X-CSRF-Token': site.identity.csrf(token)}))
    assert offer.status_code != 200                                      # no campaign, no reward
    exchange = site.post('/api/ad-coin/v2/points-exchanges', json={'credits': 1},
                         headers=headers(token, **{'Idempotency-Key': str(uuid4()),
                                                   'X-CSRF-Token': site.identity.csrf(token)}))
    assert exchange.status_code == 409 and exchange.json()['error']['code'] == 'insufficient_balance'


def test_no_route_makes_a_signed_in_person_an_advertiser_or_an_operator(site):  # noqa: F811
    token = site.identity.sign_in('cu_' + 'b' * 32)
    session = site.get('/ad-coin/v2/ui/session', headers=headers(token)).json()
    assert session['advertisers'] == []
    write = headers(token, **{'Idempotency-Key': str(uuid4()), 'X-CSRF-Token': site.identity.csrf(token)})
    # Step 2 (11-11) added /advertiser-applications; making an advertiser directly or an operator stays closed.
    for path in ('/api/ad-coin/v2/advertisers',
                 '/api/ad-coin/v2/admin/operators', '/api/ad-coin/v2/admin/advertisers'):
        assert site.post(path, json={}, headers=write).status_code in (404, 405)  # no such route
    refused = site.get('/api/ad-coin/v2/admin/overview', headers=headers(token))
    assert refused.status_code == 403 and refused.json()['error']['code'] == 'operator_required'


def test_campaign_activation_is_switched_off_in_a_fresh_database(store):  # noqa: F811
    store.migrate_model()
    with store.atomic():
        control = store.one('commercial_control', ())
    assert control is not None and not control['model_activation_enabled']


def test_growth_budget_is_empty_until_an_operator_issues_coins(store):  # noqa: F811
    store.migrate_model()
    ledger = ModelLedger(store)
    economy = CoinEconomy(store, ledger)
    advertiser = str(uuid4())
    from agent_market.ad_coin.v2.access import Access
    Access(store).provision_advertiser(advertiser, str(uuid4()))
    from agent_market.ad_coin.v2.contracts import ContractError
    with pytest.raises(ContractError) as error:
        economy.welcome_grant(advertiser)                                # growth budget is 0
    assert error.value.code == 'insufficient_balance'
    bookings = SponsoredBookings(store, ledger, taxonomy=('research',), regions=('US',))
    assert not bookings._support_allowed(advertiser, 0)                  # first-booking support is off at 0
    economy.issue_monthly('2026-11', 100_000 * points.ATOMS_PER_COIN)   # the monthly cap, by an operator
    assert economy.welcome_grant(advertiser)['atoms'] == str(points.WELCOME_GRANT_ATOMS)
    with pytest.raises(ContractError):
        economy.issue_monthly('2026-12', 1)                              # cap counts the real UTC month


def test_step1_an_operator_granted_on_the_server_can_run_the_operator_api(site):  # noqa: F811
    """PM step 1 (11-11): scripts.ad_coin_grant_operator opens the operator journey (c)."""
    from scripts import ad_coin_grant_operator as tool
    customer = 'cu_' + 'c' * 32
    token = site.identity.sign_in(customer)
    site.get('/ad-coin/v2/ui/session', headers=headers(token))
    write = headers(token, **{'X-CSRF-Token': site.identity.csrf(token)})
    issue = {'month': '2026-11', 'amount_atoms': str(1000 * points.ATOMS_PER_COIN)}
    assert site.post('/api/ad-coin/v2/admin/coins/issuance', json=issue, headers=write).status_code == 403
    tool.run(site.store, tool.principal_id_for(customer, b'L' * 32), 'grant')
    assert site.get('/api/ad-coin/v2/admin/reconcile', headers=headers(token)).status_code == 200
    done = site.post('/api/ad-coin/v2/admin/coins/issuance', json=issue, headers=write)
    assert done.status_code == 200, done.text                  # in the test database only
    held = site.get('/api/ad-coin/v2/admin/overview', headers=headers(token)).json()['coins']
    assert held['growth_budget_atoms'] == str(1000 * points.ATOMS_PER_COIN)


def _operator(site, customer='cu_' + 'f' * 32):  # noqa: F811
    from scripts import ad_coin_grant_operator as tool
    token = site.identity.sign_in(customer)
    site.get('/ad-coin/v2/ui/session', headers=headers(token))
    tool.run(site.store, tool.principal_id_for(customer, b'L' * 32), 'grant')
    return token


def test_step2_a_catalog_provider_applies_is_approved_and_gets_a_campaign_reviewed(site):  # noqa: F811
    """PM step 2 (11-11): application -> operator approval -> campaign -> operator review -> eligible."""
    from tests.test_ad_coin_v2_p1 import campaign_body
    applicant = site.identity.sign_in('cu_' + 'e' * 32)
    site.get('/ad-coin/v2/ui/session', headers=headers(applicant))
    write = headers(applicant, **{'X-CSRF-Token': site.identity.csrf(applicant)})
    form = {'display_name': 'Research Agent Co', 'listing_url': 'https://agentconcierge.biz/new/en/agent.html?id=abc'}
    assert site.post('/api/ad-coin/v2/advertiser-applications', json={**form, 'listing_url': 'https://evil.example/x'},
                     headers=write).status_code == 422                       # catalog pages only
    applied = site.post('/api/ad-coin/v2/advertiser-applications', json=form, headers=write)
    assert applied.status_code == 200 and applied.json()['status'] == 'pending', applied.text
    application = applied.json()['application_id']
    assert site.post('/api/ad-coin/v2/advertiser-applications', json=form, headers=write).json()['replayed']

    op = _operator(site)
    op_write = headers(op, **{'X-CSRF-Token': site.identity.csrf(op)})
    listed = site.get('/api/ad-coin/v2/admin/applications', headers=headers(op)).json()['items']
    assert [(i['application_id'], i['display_name'], i['listing_url']) for i in listed] == [
        (application, form['display_name'], form['listing_url'])]
    assert site.get('/api/ad-coin/v2/admin/applications', headers=headers(applicant)).status_code == 403
    approved = site.post('/api/ad-coin/v2/admin/applications/' + application + '/decision',
                         json={'approve': True}, headers=op_write)
    assert approved.status_code == 200 and approved.json()['status'] == 'approved'
    assert approved.json()['welcome']['note'] == 'growth_budget_empty'     # step 3 (issuance) fills it
    assert site.get('/api/ad-coin/v2/admin/applications', headers=headers(op)).json()['items'] == []

    base = '/api/ad-coin/v2/advertisers/' + application + '/campaigns'
    contract = {'X-AIAC-Contract': 'v6.2'}
    created = site.post(base, json=campaign_body(), headers=headers(applicant, **contract, **{
        'Idempotency-Key': str(uuid4()), 'X-CSRF-Token': site.identity.csrf(applicant)}))
    assert created.status_code == 200, created.text
    campaign = created.json()
    review = site.post(base + '/' + campaign['id'] + '/review-request', json={'revision_hash': campaign['revision_hash']},
                       headers=headers(applicant, **contract, **{'Idempotency-Key': str(uuid4()),
                                       'X-CSRF-Token': site.identity.csrf(applicant), 'If-Match': created.headers['etag']}))
    assert review.status_code == 200, review.text
    pending_reviews = site.get('/api/ad-coin/v2/admin/reviews', headers=headers(op)).json()['items']
    assert [r['review_id'] for r in pending_reviews] == [review.json()['id']]
    decided = site.post('/api/ad-coin/v2/admin/reviews/' + review.json()['id'] + '/decision',
                        json={'verdict': 'eligible', 'reason_code': 'catalog_provider'}, headers=op_write)
    assert decided.status_code == 200 and decided.json()['state'] == 'eligible'


def test_step2_rejected_application_stays_suspended(site):  # noqa: F811
    applicant = site.identity.sign_in('cu_' + 'd' * 32)
    site.get('/ad-coin/v2/ui/session', headers=headers(applicant))
    write = headers(applicant, **{'X-CSRF-Token': site.identity.csrf(applicant)})
    applied = site.post('/api/ad-coin/v2/advertiser-applications', headers=write, json={
        'display_name': 'Unlisted', 'listing_url': 'https://agentconcierge.biz/new/en/agent.html?id=none'}).json()
    op = _operator(site, 'cu_' + '9' * 32)
    op_write = headers(op, **{'X-CSRF-Token': site.identity.csrf(op)})
    path = '/api/ad-coin/v2/admin/applications/' + applied['application_id'] + '/decision'
    assert site.post(path, json={'approve': False}, headers=op_write).status_code == 422   # a reason is required
    rejected = site.post(path, json={'approve': False, 'reason': 'not in the catalog'}, headers=op_write)
    assert rejected.status_code == 200 and rejected.json()['status'] == 'rejected'
    assert site.store.one('advertiser_get', (applied['application_id'],))['status'] == 'suspended'
    assert site.post(path, json={'approve': True}, headers=op_write).status_code == 409


def test_ids_updates_and_operator_history_without_new_tables(site):  # noqa: F811
    """PM 11-11 ①②④: copyable IDs, the advertiser's updates inbox and the operator's one-advertiser view."""
    applicant = site.identity.sign_in('cu_' + '5' * 32)
    site.get('/ad-coin/v2/ui/session', headers=headers(applicant))
    write = headers(applicant, **{'X-CSRF-Token': site.identity.csrf(applicant)})
    application = site.post('/api/ad-coin/v2/advertiser-applications', headers=write, json={
        'display_name': 'History Co', 'listing_url': 'https://agentconcierge.biz/new/en/agent.html?id=h'}).json()['application_id']
    session = site.get('/ad-coin/v2/ui/session', headers=headers(applicant)).json()
    assert [(a['id'], a['status']) for a in session['advertisers']] == [(application, 'suspended')]   # pending, with its ID
    op = _operator(site, 'cu_' + '6' * 32)
    site.post('/api/ad-coin/v2/admin/applications/' + application + '/decision', json={'approve': True},
              headers=headers(op, **{'X-CSRF-Token': site.identity.csrf(op)}))
    inbox = site.get('/api/ad-coin/v2/advertisers/' + application + '/updates', headers=headers(applicant))
    assert inbox.status_code == 200, inbox.text
    assert [i['text'] for i in inbox.json()['items'] if i['kind'] == 'application'][0].startswith('Application approved')
    history = site.get('/api/ad-coin/v2/admin/advertisers/' + application + '/history', headers=headers(op))
    assert history.status_code == 200 and history.json()['status'] == 'active'
    assert {'advertiser_applied', 'advertiser_approved'} <= {e['event'] for e in history.json()['events']}
    assert history.json()['paid_bookings'] == []                       # no paid table yet: an empty list, not an error
    assert site.get('/api/ad-coin/v2/admin/advertisers/' + application + '/history',
                    headers=headers(applicant)).status_code == 403
    other = site.identity.sign_in('cu_' + '4' * 32)
    site.get('/ad-coin/v2/ui/session', headers=headers(other))
    assert site.get('/api/ad-coin/v2/advertisers/' + application + '/updates', headers=headers(other)).status_code == 403

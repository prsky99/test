"""Operator-screen campaign review (PM step 2, option A)."""
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES, OPERATOR_CAPABILITY
from agent_market.ad_coin.v2.admin_http import router_for
from agent_market.ad_coin.v2.identity import Kind
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import campaign_body, p1_suite  # noqa: F401


def in_review(suite, **changes):
    base = '/api/ad-coin/v2/advertisers/' + suite.advertiser + '/campaigns'
    created = suite.client.post(base, json=campaign_body(**changes), headers=suite.headers('editor'))
    campaign = created.json()
    review = suite.client.post(base + '/' + campaign['id'] + '/review-request',
                               json={'revision_hash': campaign['revision_hash']},
                               headers=suite.headers('editor', **{'If-Match': created.headers['etag']}))
    assert review.status_code == 200, review.text
    return campaign, review.json()


def admin(suite, *, operator=True):
    person, owner = str(uuid4()), str(uuid4())
    caps = HUMAN_CAPABILITIES | ({OPERATOR_CAPABILITY} if operator else set())
    suite.service.access.provision_principal(person, Kind.HUMAN, owner_id=owner, capabilities=caps)
    token, csrf = 'tok-op-' + uuid4().hex, 'csrf-op-' + uuid4().hex
    suite.resolver.register_human_session(token, csrf, principal_id=person, owner_id=owner)
    app = FastAPI()
    app.include_router(router_for(suite.service, resolve_auth=suite.resolver))
    return TestClient(app), {'Authorization': 'Bearer ' + token, 'X-AIAC-Contract': 'v6.2', 'X-CSRF-Token': csrf}


def test_operator_lists_and_decides_pending_reviews(p1_suite):  # noqa: F811
    s = p1_suite
    campaign, review = in_review(s, name='Pending one')
    client, h = admin(s)
    listed = client.get('/api/ad-coin/v2/admin/reviews', headers=h)
    assert listed.status_code == 200
    item = next(i for i in listed.json()['items'] if i['review_id'] == review['id'])
    assert item['name'] == 'Pending one' and item['task_categories'] == ['research']
    decided = client.post('/api/ad-coin/v2/admin/reviews/' + review['id'] + '/decision',
                          json={'verdict': 'eligible', 'reason_code': 'catalog_provider'}, headers=h)
    assert decided.status_code == 200, decided.text
    assert decided.json()['state'] == 'eligible'
    got = s.client.get('/api/ad-coin/v2/advertisers/' + s.advertiser + '/campaigns/' + campaign['id'],
                       headers=s.headers('editor'))
    assert got.json()['state'] == 'eligible'                     # ready for budget approval and activation
    again = client.post('/api/ad-coin/v2/admin/reviews/' + review['id'] + '/decision',
                        json={'verdict': 'rejected', 'reason_code': 'late'}, headers=h)
    assert again.status_code == 409                              # decided once
    assert all(i['review_id'] != review['id'] for i in client.get('/api/ad-coin/v2/admin/reviews', headers=h).json()['items'])


def test_rejection_and_refusals(p1_suite):  # noqa: F811
    s = p1_suite
    _, review = in_review(s, name='To reject')
    client, h = admin(s)
    path = '/api/ad-coin/v2/admin/reviews/' + review['id'] + '/decision'
    assert client.post(path, json={'verdict': 'maybe', 'reason_code': 'x'}, headers=h).status_code == 422
    assert client.post(path, json={'verdict': 'rejected', 'reason_code': 'Bad Reason!'}, headers=h).status_code == 422
    no_csrf = {k: v for k, v in h.items() if k != 'X-CSRF-Token'}
    assert client.post(path, json={'verdict': 'rejected', 'reason_code': 'misleading'}, headers=no_csrf).status_code == 403
    person, ph = admin(s, operator=False)
    assert person.get('/api/ad-coin/v2/admin/reviews', headers=ph).status_code == 403
    assert person.post(path, json={'verdict': 'eligible', 'reason_code': 'x'}, headers=ph).status_code == 403
    done = client.post(path, json={'verdict': 'rejected', 'reason_code': 'misleading'}, headers=h)
    assert done.status_code == 200 and done.json()['state'] == 'rejected'

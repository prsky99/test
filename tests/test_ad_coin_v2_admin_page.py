"""Korean v2 operator screen: static shell in the shared design, read-only data from the operator API."""
import re

from fastapi import FastAPI
from starlette.testclient import TestClient

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.admin_page import PATH, router_for


def client():
    app = FastAPI()
    app.include_router(router_for())
    return TestClient(app)


def test_page_is_korean_and_uses_only_the_shared_design_files():
    c = client()
    page = c.get(PATH)
    assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
    html = page.text
    assert '<html lang="ko">' in html and '코인 보유량과 대사' in html and 'x402 실제 결제 시험 조건' in html
    assert '@@' not in html and '<style' not in html and 'style=' not in html
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    assert sheets and all(s.startswith('/new/en/assets/') for s in sheets)
    script = re.search(r'src="(' + re.escape(PATH) + r'/assets/admin\.[0-9a-f]{16}\.js)"', html).group(1)
    js = c.get(script)
    assert js.status_code == 200 and js.headers['content-type'].startswith('text/javascript')
    assert 'immutable' in js.headers['cache-control']
    assert c.get(script, headers={'if-none-match': js.headers['etag']}).status_code == 304
    assert c.get(PATH + '/assets/other.js').status_code == 404


def test_script_only_reads_and_loads_both_panels_in_parallel():
    js = client().get(re.search(r'src="([^"]+admin\.[0-9a-f]+\.js)"', client().get(PATH).text).group(1)).text
    assert 'Promise.allSettled' in js and "get('/overview')" in js and "get('/reconcile')" in js
    assert "method:" not in js and 'POST' not in js  # read only
    assert 'BigInt' in js  # atoms exceed Number's safe range


def test_x402_condition_follows_the_user_decision():
    assert points.X402_TEST_MIN_HOLDINGS_ATOMS == 100_000 * points.ATOMS_PER_COIN
    assert points.X402_TEST_SPEND_DIVISOR == 1000

    class Ledger:
        def __init__(self, balances):
            self.balances = balances

        def account(self, account_id):
            return {'balance_atoms': str(self.balances.get(account_id, 0))}

    coin = points.ATOMS_PER_COIN
    below = points.platform_holdings(Ledger({points.GROWTH_ACCOUNT: 60_000 * coin, points.REVENUE_ACCOUNT: 1_000 * coin,
                                              points.ISSUANCE_ACCOUNT: -61_000 * coin}))['x402_test']
    assert below == {'eligible': False, 'min_holdings_atoms': str(100_000 * coin),
                     'remaining_atoms': str(39_000 * coin), 'spend_limit_atoms': str(61 * coin)}
    at = points.platform_holdings(Ledger({points.GROWTH_ACCOUNT: 100_000 * coin}))
    assert at['x402_test']['eligible'] and at['x402_test']['remaining_atoms'] == '0'
    assert at['x402_test']['spend_limit_atoms'] == str(100 * coin) and at['issued_atoms'] == '0'

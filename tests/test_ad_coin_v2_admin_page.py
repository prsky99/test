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
    assert '<html lang="ko">' in html and '코인 보유량과 대사' in html and 'x402' not in html
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
    # Writes (step 2, 11-11) go only to the two decision APIs and always carry the site CSRF token.
    import re as _re
    assert set(_re.findall(r"post\('(/[a-z-]+)/", js)) == {'/applications', '/reviews', '/paid-bookings'}
    assert "'X-CSRF-Token': await siteCsrf()" in js and js.count("method: 'POST'") == 1
    assert 'BigInt' in js  # atoms exceed Number's safe range


def test_holdings_carry_no_x402_condition():
    """The x402 test rule is about the USDC wallet, not AD Coin (user correction 11-10)."""
    assert not any(name.startswith('X402') for name in dir(points))

    class Ledger:
        def account(self, account_id):
            return {'balance_atoms': str({points.GROWTH_ACCOUNT: 7, points.REVENUE_ACCOUNT: 3,
                                          points.ISSUANCE_ACCOUNT: -10}.get(account_id, 0))}

    held = points.platform_holdings(Ledger())
    assert held == {'growth_budget_atoms': '7', 'coin_revenue_atoms': '3', 'platform_holdings_atoms': '10',
                    'issued_atoms': '10', 'atoms_per_coin': points.ATOMS_PER_COIN}


def test_step2_sections_are_korean_and_load_on_click():
    html = client().get(PATH).text
    assert '광고주 신청' in html and '캠페인 심사' in html and 'id="load-applications"' in html and 'id="load-reviews"' in html
    assert '카탈로그에 등록된 에이전트·MCP 제공자만 승인합니다' in html


def test_advertise_landing_is_english_honest_and_follows_the_usdc_switch(monkeypatch):
    monkeypatch.delenv('AD_COIN_PAID_BOOKING_ENABLED', raising=False)
    page = client().get('/ad-coin/v2/advertise')
    assert page.status_code == 200 and '<html lang="en">' in page.text and '@@' not in page.text
    for fact in ('5 USDC', 'per placement per day', 'USDC payments open soon', 'never changes which agents we recommend',
                 'We do not count clicks', 'contact@agentconcierge.biz'):
        assert fact in page.text, fact
    assert '<style' not in page.text and 'style=' not in page.text
    monkeypatch.setenv('AD_COIN_PAID_BOOKING_ENABLED', '1')
    assert 'USDC payments open soon' not in client().get('/ad-coin/v2/advertise').text


def test_v2_workspace_links_straight_to_the_sign_in_page():
    """11-12 PM: /new/en/sign-in.html answers 303 to /customer/sign-in; link there directly (one round trip less)."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'agent_market/ad_coin/v2/web'
    for name in ('index.html', 'app.js', 'advertise.html', 'admin.html', 'admin.js'):
        assert '/new/en/sign-in.html' not in (root / name).read_text(), name
    assert 'id="sign-in" class="btn primary" href="/customer/sign-in"' in (root / 'index.html').read_text()

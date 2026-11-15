"""/ads/library loads its own stylesheets (PM 11-15, same fault as /advertise and /methodology, 73170eb5).

The page links the growth shell's stylesheets but sent no CSP of its own, so the default policy (style-src
'unsafe-inline' only) applied and production showed it unstyled. The JSON route keeps its headers as they were."""
import re

from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401


def style_src(response):
    found = re.search(r"style-src ([^;]*)", response.headers.get('content-security-policy', ''))
    return found.group(1).split() if found else []


def test_ad_library_page_allows_its_stylesheets_and_json_is_unchanged(store):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.ad_coin.v2.ads_library import router_for
    from agent_market.concierge.growth_pages import PAGE_CSP
    store.migrate_model()
    app = FastAPI()
    app.include_router(router_for(store))
    client = TestClient(app)
    page = client.get('/ads/library')
    assert page.status_code == 200 and '/new/en/assets/styles.css' in page.text
    assert page.headers['content-security-policy'] == PAGE_CSP and "'self'" in style_src(page)
    assert page.headers['cache-control'] == 'public, max-age=600'
    data = client.get('/ads/library.json')
    assert data.status_code == 200 and 'content-security-policy' not in data.headers
    assert data.headers['cache-control'] == 'public, max-age=600'

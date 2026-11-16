"""PM 11-16 source review 3.6 (user: apply as soon as possible): with a release's fixed files, pages, bundles and assets
are assembled once per process; the bytes and headers stay exactly what a fresh assembly gives."""
import re

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge import pearl_view as pv
from agent_market.concierge.front import create_front_app
from tests.test_concierge import populated


def site():
    return TestClient(create_front_app(populated().app.state.front))


@pytest.fixture
def fixed(monkeypatch):
    monkeypatch.setattr(pv, 'ASSETS_FIXED', True)
    for name in ('_assembled', '_bundles'):
        monkeypatch.setattr(pv, name, type(getattr(pv, name))())
    monkeypatch.setattr(pv, '_asset_versions', {'at': None, 'map': {}})
    return site()


def test_a_working_tree_is_not_treated_as_a_fixed_release():
    assert pv.ASSETS_FIXED is (pv.ROOT.parent.parent.name == 'releases') and pv.ROOT.parent.parent.name != 'releases'


def test_a_kept_page_is_byte_for_byte_a_fresh_assembly(fixed, monkeypatch):
    first = fixed.get('/new/en/explore.html')
    calls = []
    real = pv._assemble
    monkeypatch.setattr(pv, '_assemble', lambda *a: calls.append(a) or real(*a))
    again = fixed.get('/new/en/explore.html')
    assert calls == [] and again.content == first.content
    assert again.headers['content-security-policy'] == first.headers['content-security-policy']
    monkeypatch.setattr(pv, 'ASSETS_FIXED', False)        # the same app, assembled afresh
    fresh = fixed.get('/new/en/explore.html')
    assert fresh.content == first.content
    assert fresh.headers['content-security-policy'] == first.headers['content-security-policy']


def test_a_changed_input_is_assembled_again(fixed):
    one = pv.page_response('<html><head></head><body><script>a()</script></body></html>', public=True, page='x.html')
    two = pv.page_response('<html><head></head><body><script>b()</script></body></html>', public=True, page='x.html')
    assert one.body != two.body and one.headers['content-security-policy'] != two.headers['content-security-policy']
    assert len(pv._assembled) == 2
    private = pv.page_response('<html><head></head><body><script>a()</script></body></html>', public=False, page='x.html')
    assert private.headers['cache-control'] == 'no-store' and private.body == one.body   # headers per call


def test_panels_moved_out_are_served_after_a_kept_page_answers(fixed):
    page = fixed.get('/new/en/explore.html').text
    version = re.search(r'panels\.js\?v=([0-9a-f]{16})', page)
    if not version:
        pytest.skip('no panels split on this page')
    with pv._panels_lock:
        pv._panels.clear()
    fixed.get('/new/en/explore.html')
    assert pv.panels_body(version[1])[0] is not None


def test_bundles_and_assets_keep_their_bytes_and_digests(fixed, monkeypatch):
    home = fixed.get('/new/en/index.html').text
    css = re.search(r'href="(/new/en/assets/bundle\.css\?[^"]+)"', home)[1].replace('&amp;', '&')
    kept = [fixed.get(css), fixed.get('/new/en/assets/app.js'), fixed.get('/new/en/assets/pearl.webp')]
    monkeypatch.setattr(pv, 'ASSETS_FIXED', False)        # the same app, built afresh
    plain = fixed
    for a, path in zip(kept, (css, '/new/en/assets/app.js', '/new/en/assets/pearl.webp')):
        b = plain.get(path)
        assert a.status_code == b.status_code == 200 and a.content == b.content and a.headers['etag'] == b.headers['etag'], path
    version = re.search(r'v=([0-9a-f]{16})', css)[1]
    assert 'immutable' in kept[0].headers['cache-control'] and version in kept[0].headers['etag']
    assert fixed.get('/new/en/assets/app.js?v=0000000000000000').headers['cache-control'] == 'no-store'

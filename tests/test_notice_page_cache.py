"""11-13 PM 20:5x: the notice pages (privacy, terms, cookies, disclosures, ...) may sit at the edge like the live pages.

They were no-store, so every visit went LAX -> tunnel -> this Mac (disclosures 6.68 s at 18:31, DYNAMIC); the bytes
are the same for every visitor. A request with a cookie or credentials still gets no-store, the pages stay noindex,
and no s-maxage is used (Cloudflare then hands out nothing stale). reports/page-body-time-2026-11-13.
"""
import json
from pathlib import Path

import pytest

from agent_market.concierge.pearl_view import NOTICE_PAGES, PUBLIC_PAGE_CACHE
from tests.test_pearl_frontend import client  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'new/en-manifest.json').read_text())


def test_every_notice_page_is_a_published_presentation_page():
    assert NOTICE_PAGES <= set(MANIFEST['presentation_only_pages'])
    assert not NOTICE_PAGES & set(MANIFEST['live_pages'])


@pytest.mark.parametrize('name', sorted(NOTICE_PAGES))
def test_a_notice_page_is_shared_without_credentials_and_private_with_them(client, name):  # noqa: F811
    path = '/new/en/' + name
    plain = client.get(path, headers={'Accept': 'text/html'})
    assert plain.status_code == 200
    assert plain.headers['cache-control'] == PUBLIC_PAGE_CACHE and 's-maxage' not in plain.headers['cache-control']
    assert 'set-cookie' not in plain.headers
    assert plain.headers['x-robots-tag'] == 'noindex,noarchive'  # unchanged: these pages were never indexed
    for headers in ({'Cookie': 'session=1'}, {'Authorization': 'Bearer x'}):
        r = client.get(path, headers={'Accept': 'text/html', **headers})
        assert r.status_code == 200 and r.headers['cache-control'] == 'no-store', headers
    assert client.get(path).text == plain.text  # the same bytes for every visitor


def test_other_presentation_pages_stay_private(client):  # noqa: F811
    for name in ('components.html', 'gallery.html', 'workspace-studio.html'):
        r = client.get('/new/en/' + name)
        assert r.status_code == 200 and r.headers['cache-control'] == 'no-store', name

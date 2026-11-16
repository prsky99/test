"""Search Console 11-16 (WNC-20237597): no sitemap address may answer noindex or 404 (PM 12:2x).

The growth sitemap and the growth pages read the same snapshot through the same functions, so on one snapshot every
listed address must answer 200 and be indexable. The edge must not keep a noindex copy longer than the sitemap:
the daily snapshot can turn yesterday's noindex page into an indexed one, and the sitemap lists it within the hour.
"""
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge import growth_catalog as gc
from agent_market.concierge import growth_pages as g
from agent_market.concierge.public_http_contract import (EDGE_DOCUMENT_CACHE, GROWTH_BROWSER_CACHE, GROWTH_CACHE,
                                                         GROWTH_EDGE_HEADER, GROWTH_NOINDEX_BROWSER_CACHE,
                                                         PublicHTTPContract)
from tests.test_growth_pages import client, write  # noqa: F401
from tests.test_noindex_tiers import tiered_snapshot

# Addresses another router serves (necklaces, methodology, weekly reports, the advertising page)
OTHER_ROUTERS = ('/necklaces/', '/methodology', '/reports/weekly', '/advertise')


def robots(html):
    found = re.search(r'<meta name="robots" content="([^"]*)"', html)
    return found[1] if found else ''


def test_every_growth_sitemap_address_answers_200_and_is_indexable(client):  # noqa: F811
    c, folder = client
    write(folder, tiered_snapshot())
    paths = [p for p in g.sitemap_paths(g.SNAPSHOT.read()) if not p.startswith(OTHER_ROUTERS)]
    for prefix in ('/agent/', '/agents/best/', '/agents/compare/', '/agents/task/'):   # every kind is exercised
        assert any(p.startswith(prefix) for p in paths), prefix
    assert {'/agents/best', '/agents/tasks', '/connect', '/badges'} <= set(paths)
    for path in paths:
        r = c.get(path, headers={'Accept': 'text/html'}, follow_redirects=False)
        assert r.status_code == 200, (path, r.status_code)
        assert robots(r.text).startswith('index'), (path, robots(r.text))
        assert 'noindex' not in r.headers.get('x-robots-tag', ''), path


def test_a_stale_snapshot_lists_no_snapshot_pages_and_they_say_noindex(client, monkeypatch):  # noqa: F811
    c, folder = client
    write(folder, tiered_snapshot())
    snap = g.SNAPSHOT.read()
    monkeypatch.setattr(g, 'fresh', lambda snapshot, now=None: False)
    paths = g.sitemap_paths(snap)
    assert not any(p.startswith(('/agent/', '/agents/best', '/agents/compare/', '/agents/task')) for p in paths)
    r = c.get('/agent/100', headers={'Accept': 'text/html'})
    assert r.status_code == 200 and robots(r.text).startswith('noindex')


def contract_app(folder):
    app = FastAPI()
    app.include_router(g.growth_router())
    return TestClient(PublicHTTPContract(app))


def test_the_edge_keeps_a_noindex_growth_page_no_longer_than_the_sitemap(client):  # noqa: F811
    _, folder = client
    write(folder, tiered_snapshot())
    site = contract_app(folder)
    indexed = site.get('/agent/100', headers={'Accept': 'text/html'})
    assert indexed.headers['cache-control'] == GROWTH_BROWSER_CACHE
    assert indexed.headers[GROWTH_EDGE_HEADER] == GROWTH_CACHE
    for path in ('/agent/200', '/agent/300', '/agent/401', '/agents/best/web_search/x402'):   # x402, thin, duplicate
        r = site.get(path, headers={'Accept': 'text/html'})
        assert r.status_code == 200 and 'noindex' in r.headers['x-robots-tag'], path
        assert r.headers['cache-control'] == GROWTH_NOINDEX_BROWSER_CACHE, path
        assert r.headers[GROWTH_EDGE_HEADER] == EDGE_DOCUMENT_CACHE, path
    sitemap_edge = EDGE_DOCUMENT_CACHE      # /sitemap.xml and its parts (public_http_contract.EDGE_DOCUMENTS)
    assert int(re.search(r'max-age=(\d+)', sitemap_edge)[1]) <= 600


def test_left_out_agents_are_exactly_the_noindex_ones(client):  # noqa: F811
    c, folder = client
    write(folder, tiered_snapshot())
    snap = g.SNAPSHOT.read()
    listed = {int(p.rsplit('/', 1)[1]) for p in gc.sitemap_paths(snap) if re.fullmatch(r'/agent/\d+', p)}
    for rid in snap['catalog']:
        r = c.get('/agent/%d' % rid, headers={'Accept': 'text/html'})
        assert (rid in listed) == robots(r.text).startswith('index'), rid

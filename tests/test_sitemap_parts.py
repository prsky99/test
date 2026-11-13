"""11-13 PM 20:5x: /sitemap.xml is an index of parts small enough for one first flight.

The single urlset (about 10,000 addresses) was 39 KB with gzip and took 5-6 s from Korea on an edge HIT; responses
over about 14.6 KB paused on loss in 19 of 35 samples (reports/page-body-time-2026-11-13). The parts carry the same
addresses in the same order, the parts are cached like /sitemap.xml, and unknown part names are 404.
"""
import gzip
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from agent_market.concierge import sitemap_parts as sp
from agent_market.concierge.public_http_contract import EDGE_DOCUMENT_CACHE
from agent_market.concierge.public_metadata import ORIGIN, sitemap

NS = '{http://www.sitemaps.org/schemas/sitemap/0.9}'


def sitemap_locs(client):
    """Every page address a crawler finds from /sitemap.xml (index -> parts), through a test client."""
    return sp.expand(lambda url: client.get(urlsplit(url).path).text, '/sitemap.xml')


def synthetic_paths(agents=9200):
    return (['/agents/category/c%d' % i for i in range(20)] + ['/connect', '/agents/tasks']
            + ['/agents/task/task-number-%d' % i for i in range(200)]
            + ['/agents/compare/%d-vs-%d' % (i, i + 7) for i in range(565)]
            + ['/agent/%d' % (300000 - i * 31) for i in range(agents)])


def test_the_parts_keep_every_address_in_order_and_fit_one_first_flight():
    head, paths = sitemap(ORIGIN), synthetic_paths()
    parts = sp.split(head, paths)
    assert list(parts)[0] == 'pages' and len(parts) == 1 + -(-9200 // sp.AGENTS_PER_PART)
    single = [e.text for e in ET.fromstring(head).iter(NS + 'loc')] + [ORIGIN + p for p in paths]
    found = [e.text for xml in parts.values() for e in ET.fromstring(xml).iter(NS + 'loc')]
    assert sorted(found) == sorted(single) and len(found) == len(single)
    pages = [e.text for e in ET.fromstring(parts['pages']).iter(NS + 'loc')]
    assert not any('/agent/' in u for u in pages)
    for name, xml in parts.items():
        assert len(gzip.compress(xml.encode(), 6)) < 14000, name  # inside the first flight with headers


def test_the_index_names_each_part_and_part_names_are_strict():
    parts = sp.split(sitemap(ORIGIN), synthetic_paths(4100))
    root = ET.fromstring(sp.index(ORIGIN, parts))
    assert root.tag == NS + 'sitemapindex'
    assert [e.text for e in root.iter(NS + 'loc')] == [ORIGIN + '/sitemaps/%s.xml' % n for n in parts]
    for path in ('/sitemaps/pages.xml', '/sitemaps/agents-1.xml', '/sitemaps/agents-12.xml'):
        assert sp.is_part(path)
    for path in ('/sitemaps/../x.xml', '/sitemaps/agents-0.xml', '/sitemaps/pages.json', '/sitemap.xml', '/sitemaps/x.xml'):
        assert not sp.is_part(path)


def test_the_site_serves_the_index_and_its_parts(w):
    _, c, _ = w
    index = c.get('/sitemap.xml')
    assert index.status_code == 200 and 'application/xml' in index.headers['content-type']
    assert ET.fromstring(index.text).tag == NS + 'sitemapindex'
    assert index.headers['cache-control'] == EDGE_DOCUMENT_CACHE
    for loc in [e.text for e in ET.fromstring(index.text).iter(NS + 'loc')]:
        part = c.get(urlsplit(loc).path)
        assert part.status_code == 200 and ET.fromstring(part.text).tag == NS + 'urlset'
        assert part.headers['cache-control'] == EDGE_DOCUMENT_CACHE and 's-maxage' not in part.headers['cache-control']
        head = c.head(urlsplit(loc).path)
        assert head.status_code == 200 and not head.content
    assert c.get('/sitemaps/agents-99.xml').status_code == 404
    assert c.get('/sitemap.xml', headers={'Cookie': 'session=1'}).headers['cache-control'] != EDGE_DOCUMENT_CACHE


from tests.test_concierge import w  # noqa: E402,F401 (fixture)

"""/methodology (super-gap strategy supplement 1, PM 11-14): the method as HTML from docs/methodology/methodology.json.

Numbers come from the generated file (scripts.methodology reads the scoring code), are in the first HTML response,
and the page states what is measured without "best", "guaranteed" or "#1".
"""
import json
import re

from agent_market.concierge import methodology_page as mp
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def test_the_page_shows_the_generated_numbers_and_no_promise_words():
    data = mp.method()
    assert data and data['version'] == 'v1'
    value = mp.page_html(data=data)
    text = re.sub(r'<[^>]+>', ' ', value)
    for expected in ('scores 85 or more on 2 different days', 'Score (out of 100)', 'Tests per day', '120',
                     'up to 1000 ms: 10 points', 'Roles (' + str(len(data['roles'])) + ')', 'airport.lookup.v1',
                     'necklace · pass total', 'necklace · held out cases', 'report v2 · musts', 'Changelog',
                     'Machine-readable (JSON)'):
        assert expected in text or expected in value, expected
    for word in ('guaranteed', 'Guaranteed', '#1', ' best '):
        assert word not in text, word
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', value, re.S)[1])
    assert ld['@type'] == 'TechArticle' and ld['version'] == 'v1' and ld['encoding']['contentUrl'].endswith('/methodology.json')


def test_routes_sitemap_and_llms(client):  # noqa: F811
    page = client.get('/methodology', headers={'Accept': 'text/html'})
    assert page.status_code == 200 and 'Verification method v1' in page.text
    machine = client.get('/methodology.json')
    assert machine.status_code == 200 and machine.json() == mp.method()
    log = client.get('/methodology/changelog')
    assert log.status_code == 200 and 'First public version' in log.text
    assert '/methodology' in client.get('/llms.txt').text
    from agent_market.concierge.growth_pages import sitemap_paths
    assert {'/methodology', '/methodology/changelog'} <= set(sitemap_paths({'tasks': [], 'catalog': [], 'captured': 0}))


def test_a_missing_method_file_hides_the_page_instead_of_inventing_numbers(tmp_path):
    assert mp.method(tmp_path / 'none.json') is None
    assert mp.page_html(data={}) is None


def test_method_advertise_necklace_and_check_reads_are_kept_at_the_edge(client):  # noqa: F811
    """11-14: these answered no-store and took 1.2-6 s from Korea; they are the same for everyone."""
    for path, policy in (('/methodology', 'public, max-age=21600'), ('/methodology/changelog', 'public, max-age=21600'),
                         ('/advertise', 'public, max-age=21600'), ('/methodology.json', 'public, max-age=600'),
                         ('/api/necklaces', 'public, max-age=60'), ('/api/feed/necklaces.json', 'public, max-age=60'),
                         ('/api/roles', 'public, max-age=60')):
        r = client.get(path, headers={'Accept': 'text/html'} if not path.endswith(('.json', 'necklaces', 'roles')) else {})
        assert r.status_code == 200 and r.headers['cache-control'].startswith(policy), (path, r.headers['cache-control'])

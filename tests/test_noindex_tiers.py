"""11-14 PM decision (search B): x402, thin and duplicate agent pages (and compare/best pages with x402) are
noindex, follow and leave the sitemap; the indexed pages are unchanged; the pages themselves keep working.
"""
import re

from agent_market.concierge import growth_catalog as gc
from agent_market.concierge import growth_pages as g
from tests.test_growth_pages import NOW, agent, client, snapshot, write  # noqa: F401

LONG = 'Weather forecasts for any city, with hourly and daily detail.'


def tiered_snapshot():
    value = snapshot()
    value['catalog'] = ([agent(100 + i, category='web_search', eval_score=90 - i, tool_count=3, description=LONG) for i in range(4)]
                        + [agent(200 + i, category='web_search', kind='x402', eval_score=95 - i, description=LONG) for i in range(4)]
                        + [agent(300, category='web_search', tool_count=3, description='Short.'),        # thin
                           agent(301, category='web_search', tool_count=0, description=LONG),            # MCP with no tools
                           agent(400, category='dev_tools', kind='a2a', name='Twin', eval_score=70, description=LONG),
                           agent(401, category='dev_tools', kind='a2a', name='twin ', eval_score=60, description=LONG)])  # duplicate
    return value


def robots(html):
    return re.search(r'<meta name="robots" content="([^"]*)"', html)[1]


def test_the_sitemap_lists_only_indexed_pages_and_every_listed_page_is_indexed(client):  # noqa: F811
    c, folder = client
    write(folder, tiered_snapshot())
    snap = g.SNAPSHOT.read()
    paths = gc.sitemap_paths(snap)
    agents = {int(p.rsplit('/', 1)[1]) for p in paths if p.startswith('/agent/')}
    assert {100, 101, 102, 103, 400} <= agents                  # task agents of the snapshot may be listed too
    assert not agents & {200, 201, 202, 203, 300, 301, 401}
    assert not any(p.endswith('/x402') for p in paths)
    for p in paths:
        if p.startswith('/agent') and '/compare/' in p:
            a, b = (int(x) for x in p.rsplit('/', 1)[1].split('-vs-'))
            assert snap['catalog'][a]['kind'] != 'x402' and snap['catalog'][b]['kind'] != 'x402'
    for p in paths:
        if p.startswith(('/agent/', '/agents/compare/', '/agents/best/')):
            r = c.get(p, headers={'Accept': 'text/html'})
            assert r.status_code == 200 and robots(r.text).startswith('index'), p
            assert 'x-robots-tag' not in r.headers, p


def test_left_out_pages_still_answer_with_noindex_follow_and_their_own_canonical(client):  # noqa: F811
    c, folder = client
    write(folder, tiered_snapshot())
    for rid in (200, 300, 301, 401):
        r = c.get('/agent/%d' % rid, headers={'Accept': 'text/html'})
        assert r.status_code == 200 and robots(r.text) == 'noindex, follow', rid
        assert r.headers['x-robots-tag'] == 'noindex, follow'
        assert '<link rel="canonical" href="%s/agent/%d">' % (g.ORIGIN, rid) in r.text
    r = c.get('/agents/best/web_search/x402', headers={'Accept': 'text/html'})
    assert r.status_code == 200 and robots(r.text) == 'noindex, follow' and r.headers['x-robots-tag'] == 'noindex, follow'
    kept = c.get('/agent/400', headers={'Accept': 'text/html'})
    assert robots(kept.text).startswith('index') and 'x-robots-tag' not in kept.headers


def test_the_markdown_copy_of_a_left_out_page_carries_the_header_too(client):  # noqa: F811
    c, folder = client
    write(folder, tiered_snapshot())
    r = c.get('/agent/200', headers={'Accept': 'text/markdown'})
    assert r.status_code == 200 and r.headers.get('x-robots-tag') == 'noindex, follow'
    kept = c.get('/agent/100', headers={'Accept': 'text/markdown'})
    assert kept.status_code == 200 and 'x-robots-tag' not in kept.headers

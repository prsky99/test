"""Every indexed agent page is linked from a list page (Search Console 11-16, PM plan A) and x402 rankings and
comparisons no longer lead crawlers to x402 agent pages (plan B).

On 11-16, 2,692 of the 3,863 indexed agent pages were linked from no ranking, task or comparison page, and Search
Console showed 8,787 addresses 'discovered, currently not indexed'. Each category now has a full list of its indexed
agents (/agents/best/<category>/all, then /all/2, ...), 100 a page, with the category's description and a short summary,
linked from its ranking and from /agents/best and listed in the sitemap.
"""
import re

from agent_market.concierge import growth_catalog as gc
from agent_market.concierge import growth_pages as g
from tests.test_growth_pages import agent, client, snapshot, write  # noqa: F401
from tests.test_noindex_tiers import tiered_snapshot

LONG = 'Weather forecasts for any city, with hourly and daily detail.'


def robots(html):
    return re.search(r'<meta name="robots" content="([^"]*)"', html)[1]


def big_snapshot(count=230):
    value = snapshot()
    value['catalog'] = [agent(1000 + i, category='web_search', eval_score=100 - i % 90, tool_count=2, description=LONG)
                        for i in range(count)]
    value['catalog'] += [agent(5000 + i, category='dev_tools', kind='x402', description=LONG) for i in range(5)]
    return value


def test_every_indexed_agent_page_is_linked_from_a_hub_page(client):  # noqa: F811
    c, folder = client
    write(folder, big_snapshot())
    snap = g.SNAPSHOT.read()
    linked = set()
    for path in gc.sitemap_paths(snap):
        if re.fullmatch(r'/agent/\d+', path):
            continue
        r = c.get(path, headers={'Accept': 'text/html'})
        assert r.status_code == 200 and robots(r.text).startswith('index'), path
        linked |= {int(x) for x in re.findall(r'href="/agent/(\d+)"', r.text)}
    indexed = gc.indexed_agents(snap)
    assert {1000 + i for i in range(230)} <= indexed <= linked   # the snapshot's task agents are indexed too


def test_the_list_has_100_a_page_in_ranking_order_with_the_category_summary(client):  # noqa: F811
    c, folder = client
    write(folder, big_snapshot())
    snap = g.SNAPSHOT.read()
    paths = gc.sitemap_paths(snap)
    assert {'/agents/best/web_search/all', '/agents/best/web_search/all/2', '/agents/best/web_search/all/3'} <= set(paths)
    assert '/agents/best/web_search/all/4' not in paths and not any('/dev_tools/all' in p for p in paths)  # x402 only
    first = c.get('/agents/best/web_search/all', headers={'Accept': 'text/html'})
    ids = [int(x) for x in re.findall(r'<li class="history-row">.*?href="/agent/(\d+)"', first.text)]
    assert len(ids) == 100 and ids == [a['id'] for a in gc.listed(snap, 'web_search')][:100]
    assert 'About this category' in first.text and '230 MCP' in first.text and 'page 1 of 3' in first.text
    assert '<link rel="canonical" href="%s/agents/best/web_search/all">' % g.ORIGIN in first.text
    last = c.get('/agents/best/web_search/all/3', headers={'Accept': 'text/html'})
    assert last.status_code == 200 and len(re.findall(r'<li class="history-row">', last.text)) == 30
    for missing in ('/agents/best/web_search/all/1', '/agents/best/web_search/all/4', '/agents/best/nope/all',
                    '/agents/best/web_search/all/x', '/agents/best/dev_tools/all'):
        assert c.get(missing, headers={'Accept': 'text/html'}).status_code == 404, missing


def test_rankings_link_their_full_list(client):  # noqa: F811
    c, folder = client
    write(folder, big_snapshot())
    ranking = c.get('/agents/best/web_search', headers={'Accept': 'text/html'}).text
    assert 'href="/agents/best/web_search/all"' in ranking and 'All 230 listed' in ranking
    index = c.get('/agents/best', headers={'Accept': 'text/html'}).text
    assert 'href="/agents/best/web_search/all"' in index and 'Every listed agent, by category' in index


def test_x402_rankings_and_comparisons_are_noindex_nofollow_and_other_left_out_pages_keep_follow(client):  # noqa: F811
    c, folder = client
    write(folder, tiered_snapshot())
    snap = g.SNAPSHOT.read()
    r = c.get('/agents/best/web_search/x402', headers={'Accept': 'text/html'})
    assert robots(r.text) == 'noindex, nofollow' and r.headers['x-robots-tag'] == 'noindex, nofollow'
    assert 'href="/agent/200"' in r.text                   # people still see the same list
    x402_pair = next((a, b) for a, b in gc.pairs(snap) if not gc.compare_indexed(snap, a, b))
    r = c.get(gc.compare_path(*x402_pair), headers={'Accept': 'text/html'})
    assert r.status_code == 200 and robots(r.text) == 'noindex, nofollow' and r.headers['x-robots-tag'] == 'noindex, nofollow'
    for rid in (200, 300, 401):                              # x402, thin and duplicate agent pages keep follow
        r = c.get('/agent/%d' % rid, headers={'Accept': 'text/html'})
        assert robots(r.text) == 'noindex, follow' and r.headers['x-robots-tag'] == 'noindex, follow', rid

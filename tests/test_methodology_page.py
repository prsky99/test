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
    assert data and data['version'] == 'v1.5'   # 11-19: one-day pearl check, 8 windows (v1.4: connection gate)
    days = data['verified_pearl']['successes_on_different_days']
    pearl_rule = 'scores 85 or more on its role task' if days == 1 else f'scores 85 or more on {days} different days'
    value = mp.page_html(data=data)
    text = re.sub(r'<[^>]+>', ' ', value)
    for expected in (pearl_rule, 'Score (out of 100)', 'Tests per day, at most', 'Test windows per day',
                     str(data['role_test']['tests_per_window']),
                     'up to 1000 ms: 10 points', 'Roles (' + str(len(data['roles'])) + ')', 'airport.lookup.v1',
                     'necklace · gate', 'connection test', 'necklace · stage 2 connection runs', 'report v2 · musts', 'Changelog',
                     'Machine-readable (JSON)'):
        assert expected in text or expected in value, expected
    for word in ('guaranteed', 'Guaranteed', '#1', ' best '):
        assert word not in text, word
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', value, re.S)[1])
    assert ld['@type'] == 'TechArticle' and ld['version'] == 'v1.5' and ld['encoding']['contentUrl'].endswith('/methodology.json')


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
    # 11-15 R78: the method pages follow /methodology.json (ten minutes); the advertiser page stays a growth page
    for path, policy in (('/methodology', 'public, max-age=600'), ('/methodology/changelog', 'public, max-age=600'),
                         ('/advertise', 'public, max-age=300'), ('/methodology.json', 'public, max-age=600'),  # 11-15: browser 5 min, edge 6 h
                         ('/api/necklaces', 'public, max-age=60'), ('/api/feed/necklaces.json', 'public, max-age=60'),
                         ('/api/roles', 'public, max-age=60')):
        r = client.get(path, headers={'Accept': 'text/html'} if not path.endswith(('.json', 'necklaces', 'roles')) else {})
        assert r.status_code == 200 and r.headers['cache-control'].startswith(policy), (path, r.headers['cache-control'])
    assert client.get('/advertise', headers={'Accept': 'text/html'}).headers['cloudflare-cdn-cache-control'].startswith(
        'public, max-age=21600')


def test_what_we_measure_comes_first_with_its_source():
    """E10 (PM 11-15): the page opens with what a badge does not tell and the three things we record."""
    page = mp.page_html(data={'version': 'v1', 'name': 'Verification method v1'}, log=[])
    first = page.index('What we measure')
    assert first < page.index('1. Who is tested')
    for item in ('Real calls.', 'Changes to its tools.', 'Last success.'):
        assert page.index(item) > first
    assert mp.TREND_STUDY in page and '9,695' in page


def test_gate_section_tells_rules_from_what_has_run(tmp_path, monkeypatch):
    """11-15 (workflow team, from code): 0.95 is the gate's rate, the 0.8 hold comes at the next daily check, and while
    nothing is offered the page says the retest rules have not been applied to a live necklace."""
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))      # no snapshot: nothing offered
    data = mp.method()
    page = mp.page_html(data=data, log=[])
    text = re.sub(r'<[^>]+>', ' ', page)
    assert 'immediate hold' not in text and 'keeps passing its retests' not in text
    assert 'after opening · connection runs a day' in text and 'retest · pass rate' not in text
    assert 'runs three times on different inputs' in text and 'older than 48 hours' in text
    assert 'held out' not in text and '57/60' not in text and 'delta' not in text.lower()
    assert 'No necklace is offered yet' in text
    assert "each server's tool" not in page and 'records what changed' in page


def test_a_one_day_rule_reads_without_different_days():
    """PM 11-18 (one daily check): with successes_on_different_days 1 the page says the score is judged on the role task."""
    data = mp.method()
    data = {**data, 'verified_pearl': {**data['verified_pearl'], 'successes_on_different_days': 1}}
    text = re.sub(r'<[^>]+>', ' ', mp.page_html(data=data))
    assert 'scores 85 or more on its role task.' in text and '1 different days' not in text


def test_the_necklace_gate_paragraph_describes_the_connection_test_and_no_retest_numbers():
    """PM 11-18 19:5x (workflow team, methodology v1.4): section 5 says what the connection test is; the old retest-score and delta
    sentence and its numbers are gone."""
    text = re.sub(r'<[^>]+>', ' ', mp.page_html(data=mp.method()))
    for expected in ('opens only after its connection test', 'every step has a fallback agent (our own agent where no other provider exists)',
                     'runs three times on different inputs', 'one connection run a day keeps it open'):
        assert ' '.join(expected.split()) in ' '.join(text.split()), expected
    for gone in ('retest success below 0.8', 'a delta of 0 or less', '57 of 60'):
        assert gone not in text, gone

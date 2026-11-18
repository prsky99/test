"""Verified pearls and necklaces on Home, Agent Status and About (PM 11-18, reports/necklace-marketing-2026-11-18 section 5).

The page bytes are the same for every visitor: the cards are fixed HTML, and the numbers arrive after load from one small
public list (/api/pearls/public: counts of the public pearl list, and the number of necklaces offered now from the judged
necklace snapshot). The necklace card is hidden until one necklace is offered, so 0 and 1 are pinned here."""
import json
from pathlib import Path

import pytest

from agent_market.concierge import necklace_surface as ns
from agent_market.concierge import pearl_badge as pb
from tests.test_necklace_agent_paths import open_topic
from tests.test_necklace_surface import iso
from tests.test_pearl_frontend import client  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / 'new/en'


def put_pearls(root, rows):
    folder = root / 'gateway-data/pearls'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'public-pearls.json').write_text(json.dumps({'schema': pb.SCHEMA, 'generated': '2026-11-18T09:20:00+09:00', 'pearls': rows}))
    pb._cache.update(key=None, value={}, counts={'final': 0, 'verified': 0, 'jobs': 0, 'agents': 0})


def row(agent, role, level, **extra):
    value = {'resource_id': agent, 'role': role, 'label': None, 'level': level, 'passed': 3, 'of': 3, 'days': 2,
             'last_checked': '2026-11-17', 'terms': 'silent'}
    value.update(extra)
    return value


def test_the_counts_are_the_final_and_verified_rows_of_the_public_list_and_no_other_level(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    assert pb.counts() == {'final': 0, 'verified': 0, 'jobs': 0, 'agents': 0}   # no file: nothing, no error
    put_pearls(tmp_path, [row(1, 'a.b.v1', 'final'), row(2, 'a.b.v1', 'verified'), row(3, 'c.d.v1', 'final'),
                          row(4, 'e.f.v1', 'provisional'), row(5, 'g.h.v1', 'verified', terms='prohibits'),
                          row(6, 'a.v1', 'verified'), row(6, 'b.v1', 'verified'), row(6, 'c.v1', 'verified'), row(6, 'd.v1', 'verified'),
                          {'level': 'final'}])
    # four roles of one agent all count, a broken row not; 7 different jobs and 5 different agents (an agent can be a pearl for more jobs)
    assert pb.counts() == {'final': 2, 'verified': 6, 'jobs': 7, 'agents': 5}
    (tmp_path / 'gateway-data/pearls/public-pearls.json').write_text('{broken')
    pb._cache.update(key=None, value={}, counts={'final': 0, 'verified': 0, 'jobs': 0, 'agents': 0})
    assert pb.counts() == {'final': 0, 'verified': 0, 'jobs': 0, 'agents': 0}


def test_no_necklace_offered_means_zero_and_one_offered_means_one(client, tmp_path, monkeypatch):  # noqa: F811
    _, _, site, _, _ = client if isinstance(client, tuple) and len(client) == 5 else (None, None, client, None, None)
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    put_pearls(tmp_path, [row(1, 'a.b.v1', 'final')])
    empty = site.get('/api/pearls/public').json()
    assert empty['necklaces_live'] == 0 and empty['counts'] == {'final': 1, 'verified': 0, 'jobs': 1, 'agents': 1}
    open_topic(monkeypatch, tmp_path)                                       # one judged, fresh, live necklace
    put_pearls(tmp_path / 'root', [row(1, 'a.b.v1', 'final'), row(2, 'a.b.v1', 'verified')])
    one = site.get('/api/pearls/public').json()
    assert one['necklaces_live'] == 1 and one['counts'] == {'final': 1, 'verified': 1, 'jobs': 1, 'agents': 2}
    assert ns.live_count() == 1


def test_a_necklace_in_testing_or_stopped_is_not_counted(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from tests.test_necklace_surface import necklace
    now = datetime.now(timezone.utc)
    testing = necklace('topic-evidence-brief', status='testing')
    held = necklace('website-trust-brief', status='held', gate_passed_at=iso(now - timedelta(hours=2)))
    assert ns.live_count({'necklaces': [testing, held]}, now) == 0
    assert ns.live_count({'necklaces': []}, now) == 0 and ns.live_count({}, now) == 0


@pytest.mark.parametrize('page', ['index.html', 'agent-status.html'])
def test_the_pearl_card_is_fixed_html_and_the_necklace_card_starts_hidden(page):
    html = (PAGES / page).read_text(encoding='utf-8')
    assert 'data-metric="pearls"' in html and '<h2>Verified pearls</h2>' in html
    assert 'href="https://agentconcierge.biz/methodology">How we test</a>' in html
    assert '<div class="metric-card" data-necklace-metric hidden>' in html and 'data-metric="necklaces"' in html
    assert '<strong class="metric-value" data-metric="pearls">—</strong>' in html        # no number in the bytes


def test_the_script_fills_the_numbers_once_and_shows_the_necklace_card_from_one_on():
    script = (PAGES / 'assets/pearl-ui.js').read_text(encoding='utf-8')
    assert script.count("fetch('/api/pearls/public'") == 1                                  # one request for Explore and Home
    assert "all('[data-necklace-metric]').forEach(node=>{node.hidden=live<1;});" in script
    assert "text('[data-metric=\"pearls\"]',format(total))" in script and script.count('homeCounts();') == 1
    assert "' across '+format(Number(counts.jobs))+' jobs'" in script                         # the line names the jobs, from the API
    assert 'MutationObserver' in script and "card.textContent==='—'" in script                 # the panels arrive after the script
    assert 'innerHTML' not in script[script.index('let homeData'):script.index('function homeCounts')]
    # strict mode: a function declared in a block is not visible outside it, so the helpers sit before the operating-only region
    assert script.index('function homeCounts') < script.index('homeCounts();') < script.index('const OPERATING')   # called in the scope that defines it
    assert script.index('function homeCounts') < script.index('const OPERATING')


def test_about_explains_pearls_and_necklaces_in_plain_words_with_the_real_rules():
    html = (PAGES / 'about.html').read_text(encoding='utf-8')
    assert html.count('What are pearls?') == 1 and html.count('What are necklaces?') == 1
    for fact in ('at least 85 out of 100', 'two different days', 'at least 57 of 60 test runs pass (95%)', '95th percentile',
                 'only the values we measured'):
        assert fact in html, fact
    assert html.count('href="https://agentconcierge.biz/methodology"') >= 2
    assert 'An agent can be a pearl for more than one job.' in html                          # 86011 is a pearl for three jobs (PM 11-18)
    assert 'Steps have a fallback agent where one has passed our tests' in html and 'Each step has a fallback agent' not in html
    assert 'about-necklace-art' in html                                                      # the drawing of the necklace stays
    lowered = html[html.index('id="about-pearls"'):html.index('<section class="reference-about-start">')].lower()
    for word in ('faster', 'cheaper', 'guarantee', 'best '):
        assert word not in lowered, word
    from agent_market.necklaces import gate_rules
    assert gate_rules.TOTAL_PASS == 57 and gate_rules.P95_MS == 5000                          # the numbers the page states


def test_home_stays_the_same_bytes_for_every_visitor(client):  # noqa: F811
    site = client[2] if isinstance(client, tuple) else client
    first = site.get('/new/en/index.html', headers={'Accept': 'text/html'})
    second = site.get('/new/en/index.html', headers={'Accept': 'text/html', 'User-Agent': 'another visitor'})
    assert first.status_code == 200 and first.content == second.content


def test_a_preview_necklace_is_counted_apart_from_the_open_ones(tmp_path, monkeypatch):
    """PM 11-18 (user decision): website-trust opens as "Preview — test runs in progress" when it misses the gate. It runs and
    shows on its page, the API counts it apart (necklaces_preview), the card says "N open · M preview" and no gate claim is made."""
    from datetime import datetime, timedelta, timezone
    from tests.test_necklace_surface import necklace
    now = datetime.now(timezone.utc)
    preview = necklace('website-trust', status='preview', gate_passed_at=None,
                       preview={'note': 'Preview \u2014 test runs in progress', 'gate_passed': False, 'tests': {'passed': 41, 'total': 60}})
    live = necklace('topic-evidence-brief', gate_passed_at=iso(now - timedelta(hours=2)))
    assert ns.offered(preview, now) and ns.live_count({'necklaces': [preview]}, now) == 0
    assert ns.preview_count({'necklaces': [preview, live]}, now) == 1 and ns.live_count({'necklaces': [preview, live]}, now) == 1
    # without recorded test runs a preview is not offered, and a stopped preview is not counted
    bare = necklace('website-trust', status='preview', gate_passed_at=None)
    assert not ns.offered(bare, now) and ns.preview_count({'necklaces': [bare]}, now) == 0
    assert ns.preview_count({'necklaces': [dict(preview, status='held')]}, now) == 0
    item = ns.public_item(preview, now=now)
    assert item['status'] == 'preview' and item['offered'] is True
    assert item['preview'] == {'note': 'Preview \u2014 test runs in progress', 'gate_passed': False, 'tests': {'passed': 41, 'total': 60}}
    assert 'Preview \u2014 test runs in progress (41 of 60 test runs passed so far)' in ns.standing_line(preview, now)
    status, page = ns.page('website-trust', snapshot={'necklaces': [preview]}, now=now)
    assert status == 200 and 'Preview \u2014 test runs in progress' in page and 'passed our gate' not in page
    assert ns.details('website-trust', snapshot={'necklaces': [preview]}, now=now) is not None
    assert ns.live({'necklaces': [preview, live]}, now) == [live]       # a preview is not promoted in answers
    script = open('new/en/assets/pearl-ui.js', encoding='utf-8').read()
    assert 'necklaces_preview' in script and "' open \u00b7 '" in script and "' preview'" in script


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
    assert "all('[data-necklace-metric]').forEach(node=>{node.hidden=shown<1;});" in script   # open plus preview (PM 11-18)
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



def test_a_preview_without_measured_rounds_shows_the_note_and_no_number():
    """Workflow team 11-18 17:2x (PM): no v2 round ran today, so entry['preview'] is only {note, gate_passed: false}: no tests and no
    rounds, not even a zero. The necklace still runs and is counted as a preview; the page and the API draw no number."""
    from datetime import datetime, timezone
    from tests.test_necklace_surface import necklace
    now = datetime.now(timezone.utc)
    note = 'Preview — test runs in progress'
    entry = necklace('website-trust', status='preview', gate_passed_at=None, preview={'note': note, 'gate_passed': False})
    assert ns.has_preview(entry) and ns.offered(entry, now) and ns.preview_count({'necklaces': [entry]}, now) == 1
    assert ns.live_count({'necklaces': [entry]}, now) == 0
    item = ns.public_item(entry, now=now)
    assert item['preview'] == {'note': note, 'gate_passed': False} and 'tests' not in item['preview']
    assert ns.standing_line(entry, now) == 'Standing: ' + note + '.'
    status, page = ns.page('website-trust', snapshot={'necklaces': [entry]}, now=now)
    assert status == 200 and note in page and 'test runs passed so far' not in page and 'passed our gate' not in page
    # a preview block that does not say gate_passed false is not a preview; a held preview keeps its page but is not offered
    assert not ns.has_preview(dict(entry, preview={'note': note})) and not ns.offered(dict(entry, preview={'note': note}), now)
    held = dict(entry, status='held', held_reason='own_members_unapproved')
    assert not ns.offered(held, now) and ns.page('website-trust', snapshot={'necklaces': [held]}, now=now)[0] == 200
    assert ns.preview_count({'necklaces': [held]}, now) == 0


def test_a_preview_necklace_prints_no_accuracy_speed_or_comparison_figure_anywhere():
    """PM 17:3x condition: a preview has no measured round, so no promo figure (accuracy, time, tokens, comparison) comes out of
    the page, the API item, the MCP tool list, the A2A skills or the llms.txt section, even when the entry still carries the blocks."""
    from datetime import datetime, timezone
    from tests.test_necklace_surface import necklace
    now = datetime.now(timezone.utc)
    note = 'Preview — test runs in progress'
    side = lambda a: {'accuracy': a, 'seconds': 3.2, 'tokens': 1200, 'calls': 4}
    entry = necklace('website-trust', status='preview', gate_passed_at=None, preview={'note': note, 'gate_passed': False},
                     comparison={'cases': 30, 'measured_at': '2026-11-17', 'with': side(0.9), 'without': side(0.7)})
    assert ns.comparison(entry) is not None and ns.offered(entry, now)           # the figures exist in the entry
    snap = {'necklaces': [entry]}
    item = ns.public_item(entry, now=now)
    assert 'comparison' not in item and not (set(item['quality']) & {'success_rate', 'best_single_rate', 'delta_pp', 'passed', 'cases'})
    assert item['cost'] == {} and item['completion'] == {}
    status, page = ns.page('website-trust', snapshot=snap, now=now)
    assert status == 200 and note in page
    assert '>Completion<' not in page and '>Fallbacks by step<' in page      # no completion frame on a preview, only the step fallbacks
    for text in ('Typical time', 'Recent test success', 'Against its best single member', 'Recent completion', 'Without AgentValCon fallbacks', 'Last retest', '1200', '90%', '3.2 s', 'Verified 95%'):   # the entry's own figures never appear
        assert text not in page, text
    tool = [t for t in ns.tools(snap, now) if t['name'] == 'necklace_website_trust'][0]        # the preview runs from the tool list
    skill = ns.skills(snapshot=snap, now=now)[0]
    for text in ('Recent tests', 'measured', '1200', '90%', 'Verified 95%'):
        assert text not in tool['description'], text
        assert text not in skill['description'], text
    assert 'website-trust' not in ns.llms_section(snapshot=snap, now=now)          # not promoted in the guide text
    assert ns.live(snap, now) == [] and [e['slug'] for e in ns.available(snap, now)] == ['website-trust']


def test_a_preview_runs_without_a_delta_or_a_retest_but_not_with_a_stale_one():
    """Workflow team 17:2x: the judge's preview has quality null (or only tested_at) before the first retest and no positive delta
    is asked of it. The surface must offer it then; a recorded retest older than the freshness window still stops it; live is unchanged."""
    from datetime import datetime, timedelta, timezone
    from tests.test_necklace_surface import necklace
    now = datetime.now(timezone.utc)
    block = {'note': 'Preview — test runs in progress', 'gate_passed': False}
    entry = necklace('website-trust', status='preview', gate_passed_at=None, preview=dict(block), quality=None)
    assert ns.offered(entry, now) and [e['slug'] for e in ns.available({'necklaces': [entry]}, now)] == ['website-trust']
    assert ns.live({'necklaces': [entry]}, now) == []
    fresh = dict(entry, quality={'tested_at': (now - timedelta(hours=3)).isoformat()})
    stale = dict(entry, quality={'tested_at': (now - timedelta(hours=ns.FRESH_HOURS + 1)).isoformat()})
    assert ns.offered(fresh, now) and not ns.offered(stale, now)
    assert not ns.offered(dict(entry, status='held'), now)
    # live keeps both conditions: a positive delta and a retest inside the window
    live_entry = necklace('topic-evidence-brief')
    assert ns.offered(live_entry, now)
    assert not ns.offered(dict(live_entry, quality={'tested_at': (now - timedelta(hours=3)).isoformat()}), now)
    assert not ns.offered(dict(live_entry, quality=None), now)

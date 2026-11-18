"""Verified pearls on the agent page and in the public list reader (PM 11-18, growth)."""
import json

import pytest

from agent_market.concierge import pearl_badge as pb
from tests.test_growth_pages import catalog_snapshot, client, write  # noqa: F401
from tests.test_pearl_frontend import client as client_full  # noqa: F401


def row(**extra):
    value = {'resource_id': 100, 'role': 'fx.rate.v1', 'label': 'Exchange rates', 'level': 'final', 'passed': 3, 'of': 3,
             'days': 2, 'last_checked': '2026-11-16', 'score': 90.0, 'terms': 'silent'}
    value.update(extra)
    return value


@pytest.fixture
def pearls(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    (root / 'gateway-data/pearls').mkdir(parents=True)
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(root))
    pb._cache.update(key=None, value={})
    file = root / 'gateway-data/pearls/public-pearls.json'

    def put(rows, schema=pb.SCHEMA):
        file.write_text(json.dumps({'schema': schema, 'generated': '2026-11-18T09:20:00+09:00', 'pearls': rows}))
    return put


def test_only_final_and_verified_rows_with_measured_numbers_are_read(pearls):
    pearls([row(), row(resource_id=101, level='verified', role='a.b.v1', label=None),
            row(resource_id=102, level='provisional'), row(resource_id=103, passed=4), row(resource_id=104, last_checked='yesterday'),
            row(resource_id=105, days=True), {'role': 'x.v1'}, 'junk'])
    found = pb.load()
    assert set(found) == {100, 101}
    assert not any(r['direct'] for rows_ in found.values() for r in rows_)
    assert pb.badge_text(found[100][0]) == 'Final pearl, #1 for Exchange rates'
    assert pb.badge_text(found[101][0]) == 'Verified pearl' and pb.role_name(found[101][0]) == 'a b'
    assert pb.public_levels() == {'100': 'final', '101': 'verified'}
    assert pb.measured_line(found[100][0]) == 'Passed 3 of 3 role tasks · confirmed on 2 different days · last checked 2026-11-16'


def test_a_missing_broken_or_foreign_file_shows_nothing(pearls, tmp_path):
    assert pb.load() == {}
    pearls([row()], schema='something-else')
    assert pb.load() == {}
    (tmp_path / 'root/gateway-data/pearls/public-pearls.json').write_text('{not json')
    assert pb.load() == {} and pb.public_levels() == {}


def test_a_pearl_agent_page_shows_the_badge_the_measured_line_and_the_method_link(client, pearls):  # noqa: F811
    c, folder = client
    write(folder, catalog_snapshot())
    pearls([row()])
    page = c.get('/agent/100').text
    assert 'Final pearl, #1 for Exchange rates' in page
    assert 'Passed 3 of 3 role tasks · confirmed on 2 different days · last checked 2026-11-16' in page
    assert 'href="/methodology"' in page and 'pearl-badge' in page
    pearls([row(level='verified')])
    assert 'Verified pearl' in c.get('/agent/100').text and 'Final pearl' not in c.get('/agent/100').text


def test_an_agent_that_is_not_a_pearl_keeps_its_page(client, pearls):  # noqa: F811
    c, folder = client
    write(folder, catalog_snapshot())
    before = c.get('/agent/100').text
    pearls([row(resource_id=999), row(level='provisional')])
    after = c.get('/agent/100')
    assert after.status_code == 200 and after.text == before and 'pearl-badge' not in after.text


def test_the_public_levels_route_lists_final_and_verified_pearls_only(pearls, client_full):
    pearls([row(), row(resource_id=101, level='verified'), row(resource_id=102, level='provisional')])
    r = client_full.get('/api/pearls/public')
    assert r.status_code == 200 and r.headers['cache-control'].startswith('public')
    assert r.json()['levels'] == {'100': 'final', '101': 'verified'} and r.json()['method'] == '/methodology'
    assert 'set-cookie' not in r.headers


def test_the_explore_card_marks_pearls_from_one_small_list_read_once():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / 'new/en/assets/pearl-ui.js').read_text(encoding='utf-8')
    assert "fetch('/api/pearls/public'" in script and script.count("fetch('/api/pearls/public'") == 1
    assert 'Final pearl' in script and 'Verified pearl' in script and 'markPearls();previewAgent' in script
    assert 'innerHTML' not in script[script.index('let pearlLevels'):script.index('renderExplore = function')]


def test_a_member_whose_terms_prohibit_our_relay_is_shown_with_the_fixed_direct_note(client, pearls, client_full):  # noqa: F811
    c, folder = client
    write(folder, catalog_snapshot())
    pearls([row(terms='prohibits'), row(resource_id=101, level='verified', terms='silent')])
    assert pb.DIRECT_NOTE == "Connect directly — we don't relay this agent (provider terms)"
    page = c.get('/agent/100').text
    assert 'Final pearl, #1 for Exchange rates' in page
    assert "Connect directly — we don&#x27;t relay this agent (provider terms)" in page
    assert 'Passed 3 of 3 role tasks' in page                      # the test result is still shown as measured
    assert pb.direct_ids() == ['100']
    levels = client_full.get('/api/pearls/public').json()
    assert levels['levels'] == {'100': 'final', '101': 'verified'} and levels['direct'] == ['100']
    assert levels['direct_note'] == pb.DIRECT_NOTE
    pearls([row(terms='silent')])
    assert 'Connect directly' not in c.get('/agent/100').text and pb.direct_ids() == []
    assert client_full.get('/api/pearls/public').json()['direct'] == []


def test_the_explore_card_adds_the_direct_note_for_the_listed_agents():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / 'new/en/assets/pearl-ui.js').read_text(encoding='utf-8')
    assert 'pearlDirect.includes(card.dataset.id)' in script and 'd.direct_note' in script


def test_a_pearl_without_an_evidence_page_is_not_shown_as_having_no_evidence(pearls, monkeypatch, tmp_path):
    """PM 11-18 11:4x: /agent/32931 (a final pearl, 89.7, two days) said "No recorded evidence yet". 34 of the 60 pearl agents
    are not in the evidence snapshot; their basic page now carries the pearl badge, the role task section and the direct note."""
    from fastapi.testclient import TestClient
    from agent_market.concierge import growth_catalog
    from agent_market.concierge import growth_pages as g
    from agent_market.concierge.front import create_front_app
    from tests.test_concierge import populated
    from tests.test_growth_pages import snapshot
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    (tmp_path / 'public-pages').mkdir()
    monkeypatch.setattr(g, 'SNAPSHOT', g.Snapshot())
    write(tmp_path / 'public-pages', snapshot())
    growth_catalog._basic.clear()
    world = populated()
    store = world.app.state.front.store
    catalog = {int(k) for k in ((g.SNAPSHOT.read() or {}).get('catalog') or {})}
    plain, pearl_id = [r['id'] for r in store.query('SELECT id FROM resources WHERE active=1 ORDER BY id') if r['id'] not in catalog][:2]
    site = TestClient(create_front_app(world.app.state.front))
    pearls([row(resource_id=pearl_id, terms='prohibits')])
    page = site.get('/agent/%d' % pearl_id, headers={'Accept': 'text/html'}).text
    assert 'Final pearl, #1 for Exchange rates' in page and 'Passed 3 of 3 role tasks' in page
    assert 'Connect directly' in page and 'href="/methodology"' in page
    assert 'No recorded evidence yet' not in page and 'Evidence: the role task results above.' in page
    assert 'Connection address' in page                                   # the listing card stays
    other = site.get('/agent/%d' % plain, headers={'Accept': 'text/html'}).text
    assert 'No recorded evidence yet' in other and 'pearl-badge' not in other   # an agent that is not a pearl is unchanged



def test_one_confirmation_day_reads_as_one_day_and_the_chip_names_the_score_not_two_days():
    """PM 11-18 (one daily check): a pearl confirmed on one day says "1 day", not "1 different days"; more days keep the old wording."""
    assert pb.measured_line(row(days=1)) == 'Passed 3 of 3 role tasks \u00b7 confirmed on 1 day \u00b7 last checked 2026-11-16'
    assert pb.measured_line(row(days=3)).endswith('confirmed on 3 different days \u00b7 last checked 2026-11-16')
    script = open('new/en/assets/pearl-ui.js', encoding='utf-8').read()
    assert 'Scored at least 85 out of 100 on our role task tests.' in script and 'two different days' not in script


def test_in_testing_reads_the_public_count(tmp_path, monkeypatch):
    # PM 11-18 21:43: the home row's "pearls being verified" number comes from the public list; None (shown as a dash)
    # when the file is missing, broken or has no count (PM 21:46: never a made-up 0)
    import json
    from agent_market.concierge import pearl_badge as pb
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    pb._cache.update(key=None, value={}, in_testing=None)
    assert pb.in_testing() is None
    file = tmp_path / 'gateway-data/pearls/public-pearls.json'
    file.parent.mkdir(parents=True)
    file.write_text(json.dumps({'schema': pb.SCHEMA, 'pearls': [], 'counts': {'in_testing': 56}}))
    assert pb.in_testing() == 56
    file.write_text(json.dumps({'schema': pb.SCHEMA, 'pearls': [], 'counts': {'in_testing': 'many'}}))
    assert pb.in_testing() is None
    file.write_text(json.dumps({'schema': pb.SCHEMA, 'pearls': []}))              # an older file without the count
    assert pb.in_testing() is None
    file.write_text('{broken')
    assert pb.in_testing() is None
    file.write_text(json.dumps({'schema': pb.SCHEMA, 'pearls': [], 'counts': {'in_testing': 0}}))
    assert pb.in_testing() == 0                                                     # a measured zero stays zero
    file.unlink()
    assert pb.in_testing() is None

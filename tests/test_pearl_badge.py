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
            row(resource_id=105, days=True), row(resource_id=106, terms='prohibits'), {'role': 'x.v1'}, 'junk'])
    found = pb.load()
    assert set(found) == {100, 101}
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

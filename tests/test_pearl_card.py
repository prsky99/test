"""PM 11-18: recommendation cards carry the pearl field from the public pearl list (agent_market/pearls_public)."""
import json

from agent_market import pearls_public
from agent_market.concierge.connections import public_agent

DOC = {'schema': pearls_public.SCHEMA, 'pearls': [
    {'resource_id': 7, 'role': 'fx.rate.v1', 'level': 'final'},
    {'resource_id': 7, 'role': 'crypto.price.v1', 'level': 'verified'},
    {'resource_id': 8, 'role': 'fx.rate.v1', 'level': 'provisional'},
    {'resource_id': 10, 'role': 'sec.filings.v1', 'level': 'final', 'terms': 'prohibits'}], 'by_resource': {}}


def _card(rid):
    return public_agent({'id': rid, 'kind': 'mcp', 'name': 'x', 'url': 'https://x.example/mcp', 'tools': ['t']})


def test_a_pearl_card_says_which_roles(tmp_path, monkeypatch):
    target = tmp_path / 'p.json'
    target.write_text(json.dumps(DOC))
    monkeypatch.setenv('PEARLS_PUBLIC_PATH', str(target))
    assert _card(7)['pearl'] == {'level': 'final', 'roles': ['fx.rate.v1', 'crypto.price.v1']}
    assert 'pearl' not in _card(8)          # provisional: no field
    assert 'pearl' not in _card(9)
    assert 'pearl' not in _card(10)         # terms prohibit us: not shown as a pearl, as on the pages


def test_no_list_means_no_field():
    assert 'pearl' not in _card(7)          # tests/conftest.py points the list at a missing file

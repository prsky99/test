"""Explore browsing shows one listing per templated description (web award review, stage 2)."""
from agent_market.concierge.hybrid_explore import _collapse_templates, _template_key

CITY = '{} is an AI agent on Central City, where people and AI agents work together in shared rooms.'


def listing(rid, name, description):
    return {'id': rid, 'name': name, 'description': description}


def test_registry_minted_agents_collapse_to_their_first_listing():
    rows = [listing(1, 'Orundito', CITY.format('Orundito')), listing(2, 'Weather Now', 'Hourly forecasts for any city with alerts and radar tiles.'),
            listing(3, 'Elellano', CITY.format('Elellano')), listing(4, 'RANDET48', CITY.format('randet48'))]
    assert [row['id'] for row in _collapse_templates(rows)] == [1, 2]


def test_distinct_short_or_unnamed_descriptions_are_never_merged():
    rows = [listing(1, 'A', 'Search news.'), listing(2, 'B', 'Search news.'), listing(3, '', CITY.format('x')),
            listing(4, '', CITY.format('y')), listing(5, 'Tide', 'Tide tables and surf forecasts for coastal spots worldwide.'),
            listing(6, 'Swell', 'Swell height and wind forecasts for surf breaks across Europe.')]
    assert [row['id'] for row in _collapse_templates(rows)] == [1, 2, 3, 4, 5, 6]
    assert _template_key(rows[0]) is None and _template_key(rows[2]) is None

"""Improvement check round 14: Explore filters must stay read-only and agree with their cards."""
from agent_market.capability_registry import Registry
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_explore_report_identity import explore, history


def test_report_filter_never_registers_connections(catalog, monkeypatch):
    store, _, client, add, now = catalog
    rid = add('Historical Weather', trial_ok=1)
    history(store, rid, created_at=now - 3600)
    original = Registry.current

    def read_only(self, resource, *, create=True):
        # Production's public reader cannot write connection rows; a write here was a 500.
        assert create is False, 'report filter tried to register a connection version'
        return original(self, resource, create=False)
    monkeypatch.setattr(Registry, 'current', read_only)
    for verified in ('false', 'true'):
        body = explore(client, kind='mcp', verified=verified)
        assert body['has_report'] is True
    assert explore(client, kind='mcp')['items'][0]['id'] == rid


def test_workspace_list_links_each_workspace_and_marks_overview():
    from agent_market.customer_identity_view import workspaces_page
    html = workspaces_page().body.decode()
    assert 'data-workspace-section="overview" aria-current="page"' in html
    assert 'data-workspace-section="account" aria-current' not in html
    assert "link.href='/customer/organizations?workspace='+w.id" in html


def test_adult_listing_phrases_are_explicit():
    from agent_market.concierge.content_policy import adult_listing
    assert adult_listing({'name': 'EscortFox', 'description': 'Read-only search of the EscortFox escort directory: cities, services'})
    assert adult_listing({'name': 'X', 'description': 'NSFW image generator'})
    assert not adult_listing({'name': 'Adult education finder', 'description': 'Courses for adult learners.'})
    assert not adult_listing({'name': 'Convoy planner', 'description': 'Plan a police escort route for a convoy.'})


def test_adult_listing_is_hidden_from_public_search_unless_named(catalog):
    _, _, client, add, now = catalog
    add('Weather Escorts', description='Weather forecasts and an escort directory of companions by city.', report_at=now - 1)
    add('Weather', report_at=now - 2)
    names = [item['name'] for item in client.get('/api/explore', params={'q': 'weather'}).json()['items']]
    assert 'Weather' in names and 'Weather Escorts' not in names
    named = [item['name'] for item in client.get('/api/explore', params={'q': 'Weather Escorts'}).json()['items']]
    assert 'Weather Escorts' in named


def test_hybrid_explore_hides_adult_listing_unless_named(catalog, monkeypatch):
    from agent_market.concierge import hybrid_explore
    store, _, _, add, now = catalog
    ids = [add('Weather Escorts', description='Weather forecasts and an escort directory of companions by city.', report_at=now - 1),
           add('Weather', report_at=now - 2)]
    rows = [dict(store.resource(rid)) for rid in ids]
    monkeypatch.setattr('agent_market.concierge.hybrid_explore.candidates', lambda *a, **k: [dict(r) for r in rows])
    names = [i['name'] for i in hybrid_explore.explore(store, None, 'weather', 'mcp', None, False, False, 10)['items']]
    assert 'Weather' in names and 'Weather Escorts' not in names
    named = [i['name'] for i in hybrid_explore.explore(store, None, 'Weather Escorts', 'mcp', None, False, False, 10)['items']]
    assert 'Weather Escorts' in named

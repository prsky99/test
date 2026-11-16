"""Our own data agents say so wherever they are recommended (PM 11-15 16:48); ranking is untouched.

A listing is ours when its catalog source is agentconcierge-owned; its data source comes from the owned agent spec.
Explore rows carry no key, so the endpoint path also identifies the agent. The daily snapshot marks our agents for
/agent/<id> pages without a database read."""
from agent_market.concierge import operated_by as ob
from agent_market.owned_data_agents.catalog import SPECS

OWN = {'id': 7, 'source': 'agentconcierge-owned', 'key': 'agentconcierge-owned:technology-news', 'name': 'Technology News',
       'url': 'https://agentconcierge.biz/api/owned-data-agents/technology-news/mcp', 'kind': 'mcp'}


def test_ours_by_key_or_endpoint_and_nothing_else():
    found = ob.operated(OWN)
    assert found == {'operated_by': 'AgentValCon', 'data_source': {'name': SPECS['technology-news']['source_name'],
                                                                   'url': SPECS['technology-news']['source_url']}}
    assert ob.operated({**OWN, 'key': None}) == found                                  # explore rows: no key
    assert ob.operated({**OWN, 'source': 'registry'}) is None
    assert ob.operated({'source': 'agentconcierge-owned', 'key': 'agentconcierge-owned:unknown'})['data_source'] is None
    assert ob.line(found).startswith('Operated by AgentValCon, with data from The GDELT Project (gdeltproject.org), DOC 2.0 API under its own terms')
    assert ob.line(found).endswith('Ranked by the same checks as every other agent.') and ob.line(None) == ''


def test_snapshot_marks_our_agents_and_readers_keep_only_safe_values():
    class Store:
        def query(self, sql, params):
            assert sql == 'SELECT id FROM resources WHERE key=?'
            return [{'id': 7}] if params == ('agentconcierge-owned:technology-news',) else []
    snapshot = {'catalog': [{'id': 7, 'name': 'Technology News'}, {'id': 8, 'name': 'Other'}],
                'tasks': [{'agents': [{'id': 7}]}]}
    assert ob.add_operators(Store(), snapshot) == 2
    assert snapshot['catalog'][0]['operated_by'] == 'AgentValCon' and 'operated_by' not in snapshot['catalog'][1]
    assert ob.clean(snapshot['catalog'][0])['data_source']['url'].startswith('https://')
    assert ob.clean({'operated_by': 'Someone'}) == {}
    assert ob.clean({'operated_by': 'AgentValCon', 'data_source': {'name': 'x', 'url': 'javascript:alert(1)'}})['data_source'] is None


def test_agent_page_and_methodology_say_it():
    from agent_market.concierge.growth_catalog import operator_note
    note = operator_note({'operated_by': 'AgentValCon', 'data_source': {'name': 'Crossref', 'url': 'https://www.crossref.org/'}})
    assert note.startswith('<p class="agent-operator">Operated by AgentValCon, with data from Crossref')
    assert operator_note({'name': 'Other'}) == ''
    from agent_market.concierge import methodology_page as mp
    import json
    data = json.load(open('docs/methodology/methodology.json', encoding='utf-8'))
    assert 'Some listed agents are operated by AgentValCon itself' in mp.page_html(data=data, log=[])


def test_card_data_carries_the_operator(tmp_path):
    from agent_market.gateway.store import Store
    from agent_market.concierge.front import _card_data
    store = Store(str(tmp_path / 'own.db'))
    rid = store.upsert_resource({'key': OWN['key'], 'name': 'Technology News', 'kind': 'mcp', 'source': OWN['source'],
                                 'url': OWN['url'], 'description': 'Recent Hacker News stories', 'category': 'news'})
    card = _card_data(store.resource(rid), store)
    assert card['operated_by'] == 'AgentValCon' and card['data_source']['name'] == SPECS['technology-news']['source_name']
    other = store.upsert_resource({'key': 'x:1', 'name': 'Other', 'kind': 'mcp', 'source': 'registry',
                                   'url': 'https://other.example/mcp', 'description': 'Other', 'category': 'news'})
    assert 'operated_by' not in _card_data(store.resource(other), store)
    store._db.close()

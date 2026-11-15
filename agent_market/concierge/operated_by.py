"""Which listings AgentValCon itself operates (PM 11-15 16:48): our owned data agents are recommended by the same
ranking as every other agent, so each place that shows one says so, with the public source its data comes from.

A listing is ours when its catalog source is 'agentconcierge-owned' and its key names one of the owned data agent
specs (owned_data_agents.catalog.SPECS and the technical documentation agent). The data source name and address come
from that spec; a license is not invented here: the source's own terms apply and the address leads to them.
Nothing here changes a rank or a score.
"""
import re

OPERATOR = 'AgentValCon'
URL = re.compile(r'/api/owned-data-agents/([a-z0-9-]{1,60})/mcp\b')
SOURCE = 'agentconcierge-owned'
PREFIX = SOURCE + ':'


def _specs():
    from ..owned_data_agents.catalog import SPECS
    from ..owned_data_agents import docs
    return {**SPECS, docs.ID: docs.SPEC}


def operated(resource):
    """{'operated_by': 'AgentValCon', 'data_source': {'name', 'url'}} for one of our listings, else None."""
    if not isinstance(resource, dict) or resource.get('source') != SOURCE:
        return None
    key = str(resource.get('key') or '')
    identity = key[len(PREFIX):] if key.startswith(PREFIX) else None
    if identity is None:   # explore rows carry no key; the endpoint names the agent
        match = URL.search(str(resource.get('url') or ''))
        identity = match.group(1) if match else None
    try:
        spec = _specs().get(identity) if identity else None
    except Exception:
        spec = None
    source = ({'name': spec['source_name'], 'url': spec['source_url']}
              if isinstance(spec, dict) and spec.get('source_name') and spec.get('source_url') else None)
    return {'operated_by': OPERATOR, 'data_source': source}


def line(found):
    """One English sentence for people and agents, or ''."""
    if not found:
        return ''
    source = found.get('data_source')
    return ('Operated by AgentValCon' + (', with data from ' + source['name'] + ' under its own terms (' + source['url'] + ')'
                                         if source else '')
            + '. Ranked by the same checks as every other agent.')


def add_operators(store, snapshot):
    """Marks our own agents in the daily task-page snapshot (jobs), so /agent/<id> says who operates them without a
    database read. Eight lookups by key with the registered statement; returns how many agents were marked."""
    agents = list(snapshot.get('catalog') or [])
    for task in snapshot.get('tasks') or []:
        agents += task.get('agents') or []
    ours = {}
    for identity in _specs():
        rows = store.query('SELECT id FROM resources WHERE key=?', (PREFIX + identity,))
        if rows:
            ours[rows[0]['id']] = operated({'source': SOURCE, 'key': PREFIX + identity})
    for agent in agents:
        found = ours.get(agent.get('id'))
        if found:
            agent.update(found)
    return sum(1 for agent in agents if agent.get('id') in ours)


def clean(item):
    """The two fields as a snapshot reader keeps them: only our operator name and an https source of plain text."""
    if not isinstance(item, dict) or item.get('operated_by') != OPERATOR:
        return {}
    source = item.get('data_source')
    ok = (isinstance(source, dict) and isinstance(source.get('name'), str) and 0 < len(source['name']) <= 100
          and isinstance(source.get('url'), str) and source['url'].startswith('https://') and len(source['url']) <= 300)
    return {'operated_by': OPERATOR, 'data_source': {'name': source['name'], 'url': source['url']} if ok else None}

"""Reviewed live Testbench recipes; public output contains managed IDs only."""
from ..workflow_templates import NEWS_URL, NEWS_TOOL, NEWS_TECH_ARGS, DOCS_URL, PADEL_URL
from .execution_availability import resource_execution_availability, invocation_execution_availability

RECIPES = (
    ('tech-news', 'Technology news', 'Read recent technology news with source links.',
     NEWS_URL, NEWS_TOOL, {**NEWS_TECH_ARGS, 'limit':2}),
    ('camera-docs', 'Camera documentation', 'Search official camera permission guidance.',
     DOCS_URL, 'search_docs', {'query':'camera permissions android ios', 'limit':2}),
    ('racket-search', 'Racket comparison research', 'Find published racket records and source links.',
     PADEL_URL, 'search_rackets', {'query':'nox at10', 'limit':2}),
    ('train-routes', 'Famous train routes', 'Read a short list of well-known train journeys.',
     'https://trainrouter.com/mcp', 'famous_routes', {'limit':2}),
)


def live_examples(store):
    """Resolve reviewed public bindings without running discovery or a provider task."""
    examples = []
    control = invocation_execution_availability(store)
    from ..owned_data_agents.activation import MARKER
    active = store.query('SELECT value FROM meta WHERE key=?', (MARKER,))
    selected = RECIPES
    if active:
        import json
        from ..owned_data_agents.staging import recipes
        selected = recipes(json.loads(active[0]['value'])['origin'])
    for key, title, description, url, tool, arguments in selected:
        availability = resource_execution_availability(None) if control['available'] else control
        item = {'id':key, 'title':title, 'desc':description, 'protocol':'mcp',
                'tool':tool, 'args':dict(arguments), 'prompt':'', 'resource_id':None,
                'available':False, 'simulated':False, 'execution_availability':availability}
        if not control['available']:
            examples.append(item)
            continue
        from ..owned_data_agents.activation import resource_rows
        rows = resource_rows(store, url)
        if rows is None:
            rows = store.query('SELECT id FROM resources WHERE kind=? AND url=? ORDER BY active DESC,id DESC LIMIT 1', ('mcp',url))
        if rows:
            resource = store.resource(rows[0]['id'])
            availability = resource_execution_availability(
                resource, kind='mcp', tool=tool, arguments=arguments, store=store,
            )
            item['execution_availability'] = availability
            if availability['available']:
                item.update(resource_id=resource['id'], available=True)
        examples.append(item)
    return examples

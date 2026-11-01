"""Bounded discovery over reviewed public workflow projections, without execution."""
import re

from .engine import clean_external
from .protocols import requested_protocol, search_protocols


ALIASES = {
    'research': r'\b(?:papers?|research|academic|scholarly|arxiv|pubmed)\b|\ub17c\ubb38|\ud559\uc220|\uc5f0\uad6c',
    'news': r'\b(?:news|headlines?|stories)\b|\ub274\uc2a4',
    'country': r'\b(?:countr(?:y|ies)|nation(?:s|al)?)\b|\uad6d\uac00|\ub098\ub77c',
    'indicator': r'\b(?:indicators?|population|economic|economy|gdp)\b|\uc9c0\ud45c|\uc778\uad6c|\uacbd\uc81c',
    'package': r'\b(?:packages?|npm|dependencies|dependency)\b|\ud328\ud0a4\uc9c0|\uc758\uc874\uc131',
    'advisory': r'\b(?:advisories|advisory|security|vulnerabilit\w*|cve)\b|\ubcf4\uc548|\ucde8\uc57d\uc810',
}
STOP = frozenset('a an the find get show me please recommend recommended want need workflow workflows template templates agent agents for of to that which can and or with related recent daily technology tech ai records current about some searches search searching resolve return retrieve review brief digest metadata information create build make generate connected use using'.split())
CONSTRAINTS = frozenset('email slack discord telegram send delete write trade payment deploy image video audio weather calendar spreadsheet'.split())
WORKFLOW = re.compile(r'\b(?:workflows?|templates?)\b|\uc6cc\ud06c\ud50c\ub85c\uc6b0|\ud15c\ud50c\ub9bf', re.I)
AUTHORING = re.compile(r'\b(?:create|generate|build|edit|modify)\b.*\bworkflows?\b|\uc0c8\ub85c.*\uc0dd\uc131|\uc790\ub3d9.*\uc0dd\uc131|\uc6cc\ud06c\ud50c\ub85c\uc6b0.*(?:\uc218\uc815|\uc0dd\uc131|\ub9cc\ub4e4)', re.I)


def wants_workflow(text, data=None):
    data = data or {}
    return (data.get('resource_type') == 'workflow' or data.get('intent') == 'find_workflow'
            or data.get('resource_type') != 'agent' and bool(WORKFLOW.search(str(text))))


def terms(value):
    text = str(value or '').casefold()[:20000]
    concepts = {name for name, pattern in ALIASES.items() if re.search(pattern, text)}
    remaining = text
    for pattern in ALIASES.values():
        remaining = re.sub(pattern, ' ', remaining)
    words = {word for word in re.findall(r'[a-z][a-z0-9_-]{1,49}', remaining) if word not in STOP}
    return concepts, words


def document(template):
    pieces = [str(template.get(key) or '')[:2000] for key in ('name', 'description', 'tags')]
    for node in template.get('nodes', [])[:50]:
        data = node.get('data', {})
        pieces.extend(str(value or '')[:500] for value in (node.get('name'), data.get('action'), data.get('tool')))
        if isinstance(data.get('input'), dict):
            pieces.extend(str(key)[:80] for key in data['input'])
    return ' '.join(pieces)


def relevance(template, query):
    if not query or not query.strip():
        return 1
    from .query_intent import interpret
    intent = interpret(query)
    concepts, words = terms(intent.positive)
    excluded_concepts, excluded_words = terms(' '.join(intent.excluded))
    doc_concepts, doc_words = terms(document(template))
    nodes = [n for n in template.get('nodes', []) if n.get('type') != 'trigger']
    node_concepts = set()
    for node in nodes:
        data = node.get('data') or {}
        task_text = ' '.join(str(v or '') for v in (node.get('name'), data.get('action'), data.get('tool'), data.get('contract_id')))
        node_concepts.update(terms(task_text.replace('_', ' ').replace('.', ' '))[0])
        if data.get('contract_id') == 'docs.search.v1':
            node_concepts.add('research')
    if (excluded_concepts - concepts) & node_concepts:
        return 0
    if excluded_words & CONSTRAINTS & doc_words:
        return 0
    if concepts:
        # Titles and tags cannot invent a capability absent from the steps.
        capabilities = node_concepts if nodes else doc_concepts
        if not concepts <= capabilities or not (words & CONSTRAINTS) <= doc_words:
            return 0
        title_concepts, title_words = terms(template.get('name'))
        extras = capabilities - concepts
        title = re.sub(r'\btech\b', 'technology', str(template.get('name') or '').casefold())
        # Count topic words once; capability synonyms already earned coverage.
        topical = words - {'related', 'please', 'recommend', 'records'}
        title_terms = set(re.findall(r'[a-z]{3,}', title))
        # Capability coverage precedes topic fit, focused scope and freshness.
        return (100*len(concepts) + 20*len(title_concepts & concepts)
                + 8*len(topical & title_terms) + len(words & (doc_words | title_words))
                - 40*len(extras) - max(0, len(nodes)-len(concepts)))
    return len(words) if words and words <= doc_words else 0


def node_protocols(template):
    return sorted({n.get('kind') for n in template.get('nodes', []) if n.get('type') != 'trigger'
                   and n.get('kind') in ('a2a', 'mcp', 'x402')})


_UNSET = object()


def published_templates(store, category=None, query=None, *, runtime=None, protocol=_UNSET):
    protocol = requested_protocol(query) if protocol is _UNSET else protocol
    from ..workflows import public_template
    from .execution_availability import workflow_execution_availability
    runtime = runtime or getattr(store, '_workflow_runtime', None)
    workflows, _ = store.list_workflows(is_template=1, active_only=True, category=category, limit=1000)
    found = []
    for workflow in workflows:
        projected = public_template(workflow, runtime)
        if not projected:
            continue
        # Ensure no node in the template references an inactive or quarantined/review agent
        has_unsafe_node = False
        for n in projected.get('nodes', []):
            rid = n.get('resource_id') or (n.get('data') or {}).get('resource_id')
            if rid:
                res = store.resource(rid)
                if not res or not res.get('active') or res.get('eval_security') in ('quarantine', 'review'):
                    has_unsafe_node = True
                    break
        if has_unsafe_node:
            continue
        score = relevance(projected, query)
        protocols = node_protocols(projected)
        if score <= 0 or not protocols or set(protocols) - set(search_protocols(protocol)):
            continue
        projected['node_protocols'] = protocols
        projected['fallback_available'] = bool(runtime and runtime.fallback.available(projected))
        projected['execution_availability'] = workflow_execution_availability(store, workflow)
        priority = 0 if protocols == ['a2a'] else 1
        found.append((priority, score, workflow.get('updated_at') or 0, projected['id'], projected))
    found.sort(key=lambda item: (item[0], -item[1], -item[2], -item[3]))
    return [item[4] for item in found]


def summary(template):
    return {
        'id': template['id'], 'name': clean_external(template.get('name'), 180),
        'description': clean_external(template.get('description'), 400),
        'definition_hash': template['definition_hash'], 'node_protocols': template['node_protocols'],
        'execution_availability': template['execution_availability'],
        'step_names': [clean_external(n.get('name'), 100) for n in template.get('nodes', []) if n.get('type') != 'trigger'][:12],
        'detail_path': f'/api/workflows/templates/{template["id"]}',
        'page_path': '/new/en/workflows.html',
        'download_path': f'/api/workflows/{template["id"]}/webapp',
    }


def published_detail(store, template_id, *, runtime=None):
    from ..workflows import public_template
    from .execution_availability import workflow_execution_availability
    if type(template_id) is not int or not 0 < template_id < 2**31:
        return None
    original = store.get_workflow(template_id)
    if not original or not original.get('is_active') or not original.get('is_template'):
        return None
    runtime = runtime or getattr(store, '_workflow_runtime', None)
    value = public_template(original, runtime)
    if value is not None:
        value['node_protocols'] = node_protocols(value)
        value['execution_availability'] = workflow_execution_availability(store, original)
    return value


def recommend(store, task, data=None, *, runtime=None, offset=0, limit=3):
    data = data or {}
    protocol = requested_protocol(task, data)
    candidates = published_templates(store, query=task, runtime=runtime, protocol=protocol)
    selected = candidates[offset:offset+min(3, max(1, limit))]
    result = {'resource_type': 'workflow', 'task': task[:2000], 'protocol': protocol,
              'recommendations': [], 'workflows': [summary(item) for item in selected],
              'status': 'matched' if selected else 'no_match',
              'next_actions': [{'action': 'browse_workflows', 'method': 'GET', 'path': '/api/workflows/templates'}]}
    if not selected:
        unfiltered = published_templates(store, query=task, runtime=runtime) if protocol else []
        result['reason_code'] = 'protocol_mismatch' if unfiltered else 'no_catalog_match'
    return result

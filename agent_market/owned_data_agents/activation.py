"""Idempotent operating activation of reviewed owned-agent examples.

Run only while composing the new frontend. Existing workflow history and custom
templates remain intact; old builtin definitions stay recoverable in the DB.
"""
import json
from copy import deepcopy
import time

from ..collector import usage
from ..config import health_interval_seconds
from .catalog import SPECS, tool_spec
from .service import PREFIX
from .staging import VERSION, definitions

MARKER = 'owned_data_agents_public_v1'
SCHEMA_REVISION = 'public-data-contracts-2026-10-29'


def resource_rows(store, endpoint):
    """Prefer immutable first-party keys over newer duplicate URL listings."""
    profile = store.query('SELECT value FROM meta WHERE key=?', (MARKER,))
    base = json.loads(profile[0]['value'])['origin'] if profile else 'https://agentconcierge.biz'
    for identity in SPECS:
        if endpoint == base.rstrip('/')+PREFIX+'/'+identity+'/mcp':
            return store.query('SELECT id FROM resources WHERE key=? AND source=? AND kind=? AND url=?',
                ('agentconcierge-owned:'+identity, 'agentconcierge-owned', 'mcp', endpoint))
    return None


def install(store, base_url):
    from .staging import origin
    base_url = origin(base_url)
    resources = {}
    for identity, spec in SPECS.items():
        tools = [tool_spec(identity)]
        from ..capability_registry import Registry, digest
        prior_rows = store.query('SELECT id FROM resources WHERE key=?', ('agentconcierge-owned:' + identity,))
        previous = store.resource(prior_rows[0]['id']) if prior_rows else None
        # Only an already reviewed, unchanged local tool may carry its approval
        # into the new local binding. Execution evidence is never copied.
        previous_version = Registry(store).current(previous, create=False) if previous else None
        approvals = []
        if (previous and previous.get('source') == 'agentconcierge-owned'
                and previous.get('url') == base_url + PREFIX + '/' + identity + '/mcp'
                and previous.get('usage_full_hash') == digest(tools) and previous_version):
            approvals = store.query('SELECT contract_id,tool FROM capability_approvals WHERE version_id=?',
                                   (previous_version['id'],))
        rid = store.upsert_resource({'key': 'agentconcierge-owned:' + identity,
            'source': 'agentconcierge-owned', 'kind': 'mcp',
            'url': base_url + PREFIX + '/' + identity + '/mcp',
            'name': spec['name'], 'description': spec['description'],
            'category': spec.get('category', 'data_utility'), 'price_usdc': 0,
            'details': {'owned_schema_revision': SCHEMA_REVISION}})
        resource = store.resource(rid)
        # This is the locally declared schema, not a fabricated remote survey or
        # execution report. Do not overwrite subsequent collector observations.
        prior=deepcopy(tools)
        if identity=='research-papers':
            prior[0]['inputSchema']['properties']['query']['maxLength']=160
            prior[0]['outputSchema']['properties']['data']['properties']['query']['maxLength']=160
        legacy_research=(identity=='research-papers' and resource.get('usage_full_tools') and
                         json.loads(resource['usage_full_tools'])==prior)
        if not resource.get('usage_tools_hash') or legacy_research:
            compact = usage.compact_tools(tools)
            store.record_usage(rid, compact, usage.tools_hash(compact), {}, None, None, full_tools=tools)
        if approvals:
            current = store.resource(rid)
            current_version = Registry(store).current(current)
            if current_version['id'] != previous_version['id']:
                from ..capability_contracts import CONTRACTS
                for approval in approvals:
                    if approval['contract_id'] in CONTRACTS:
                        Registry(store).approve(current, approval['contract_id'], approval['tool'])
        resources[identity] = rid
    _install_docs(store, base_url)
    from .catalog import ADMIN_SPECS
    with store.tx() as db:
        for identity in ADMIN_SPECS:
            # Administrator-only sources are never public listings, chat options or workflow steps.
            db.execute("UPDATE resources SET active=0 WHERE key=? AND source=? AND active=1",
                       ('agentconcierge-owned:' + identity, 'agentconcierge-owned'))
    with store.tx() as db:
        found = db.execute('SELECT value FROM meta WHERE key=?', (MARKER,)).fetchone()
        if not found:
            old = [r[0] for r in db.execute("SELECT workflow_id FROM workflow_seed_registry WHERE seed_key LIKE 'live-workflow-hub-v1:%'")]
            # Preserve complete old definitions and their run history in place.
            # Only retire builtin hub entries, never user-created workflows.
            for wid in old:
                db.execute('UPDATE agent_workflows SET is_template=0,is_active=0 WHERE id=?', (wid,))
            for definition in definitions(base_url):
                prior = db.execute('SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?', (definition['seed_key'],)).fetchone()
                if prior:
                    continue
                wid = store.create_workflow(definition)
                db.execute('INSERT INTO workflow_seed_registry VALUES (?,?)', (definition['seed_key'], wid))
            db.execute('INSERT INTO meta VALUES (?,?)', (MARKER, json.dumps({
                'version': VERSION, 'origin': base_url, 'retired_builtin_ids': old, 'at': time.time()})))
    return resources


def check_sources(store, engine, resources):
    """Actual source executions establish readiness, not an invented HTTP check."""
    from concurrent.futures import ThreadPoolExecutor
    def check(item):
        identity, rid = item
        started = time.monotonic()
        try:
            engine.execute(identity, SPECS[identity]['example'])
        except (ValueError, TimeoutError):
            store.record_health(rid, 'failing', None, None, 'Public data source unavailable.', time.time() + 120)
        else:
            store.record_health(rid, 'healthy', None, int((time.monotonic()-started)*1000), None, time.time() + health_interval_seconds())
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(check, resources.items()))


def _install_docs(store, base_url):
    """Technical Documentation: same listing shape, separate module and approval (see docs.py)."""
    from . import docs
    from ..capability_registry import digest
    tools = [docs.tool_spec()]
    rid = store.upsert_resource({'key': docs.KEY, 'source': 'agentconcierge-owned', 'kind': 'mcp',
        'url': base_url + PREFIX + '/' + docs.ID + '/mcp', 'name': docs.SPEC['name'],
        'description': docs.SPEC['description'], 'category': docs.SPEC['category'], 'price_usdc': 0,
        'details': {'owned_schema_revision': SCHEMA_REVISION}})
    if store.resource(rid).get('usage_full_hash') != digest(tools):
        compact = usage.compact_tools(tools)
        store.record_usage(rid, compact, usage.tools_hash(compact), {}, None, None, full_tools=tools)
    return rid

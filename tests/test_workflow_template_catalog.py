"""Hub replacement, actual protocol execution and output boundary regressions."""
import json
import os
import sqlite3

import httpx
import pytest

from agent_market.collector import usage
from agent_market.concierge.notify import Courier
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.store import Store
from agent_market.workflow_templates import definitions, NEWS_URL, NEWS_RESEARCH_URL, DOCS_URL, PADEL_URL
from agent_market.workflow_template_install import replace_templates, verified_recipes
from agent_market import workflow_template_install
from agent_market.workflows import WorkflowError, WorkflowRuntime, project_output
from tests.test_mcp_proxy import MockRemoteMcp
from tests.test_workflow_runtime import wait


class RecipeTransport(httpx.BaseTransport):
    def __init__(self):
        self.calls = []
        self.tools = {}
        for recipe in definitions():
            for node in recipe['nodes'][1:]:
                data = node['data']; endpoint = data['resource_ref']['url']
                schema = {'type': 'object', 'properties': {k: {'type': 'boolean' if type(v) is bool else 'integer' if type(v) is int else 'string'} for k, v in data['input'].items()}, 'required': list(data['input'])}
                tool = {'name': data['action'], 'inputSchema': schema, 'annotations': {'readOnlyHint': True, 'destructiveHint': False}}
                bucket = self.tools.setdefault(endpoint, {})
                bucket[tool['name']] = tool

    def handle_request(self, request):
        remote = MockRemoteMcp(list(self.tools[str(request.url)].values()))
        body = json.loads(request.content or '{}')
        if body.get('method') == 'tools/call':
            tool = body['params']['name']; args = body['params']['arguments']; self.calls.append((tool, args))
            content = [{'type': 'text', 'text': 'Official catalogue comparison. Ratings are calculated estimates.'}]
            structured = {}
            if tool == 'trending':
                assert args == {'topic':'developer-tools','window':'24h','limit':3}
                structured = {'status':'ok','posts':[{'title':'Controlled developer release',
                    'url':'https://example.com/release','source_name':'Controlled publication',
                    'published_at':'2026-10-19T00:00:00Z'}]}
            elif tool == 'search_papers':
                assert args == {'query':'large language model reasoning','open_access_only':True,'limit':3}
                structured = {'status':'ok','results':[{'title':'Controlled AI research paper',
                    'url':'https://doi.org/10.0000/controlled','year':2026,
                    'venue':'Controlled research journal','doi':'10.0000/controlled'}]}
            elif tool == 'search_docs':
                structured = {'results': [{'title': 'Camera permissions', 'url': 'https://example.com/docs', 'snippet': 'Permission guidance'}]}
            elif tool == 'search_rackets':
                structured = {'results': [{'slug': slug, 'name': slug.title(), 'year': 2025, 'shape': 'round', 'ratings': {'control': 8}, 'page': 'https://example.com/' + slug} for slug in ('first-model', 'second-model')]}
            elif tool == 'compare_rackets':
                assert args == {'a': 'first-model', 'b': 'second-model'}
            remote.call_result = {'content': content, 'structuredContent': structured}
        return remote.handle_request(request)


def register(store, transport):
    for endpoint, tools in transport.tools.items():
        identity = store.upsert_resource({'key': 'mcp:' + endpoint, 'source': 'test', 'kind': 'mcp', 'url': endpoint, 'name': 'Controlled provider', 'description': 'Controlled test provider', 'category': 'data_utility', 'price_usdc': 0, 'details': {}})
        compact = usage.compact_tools(list(tools.values()))
        store.record_usage(identity, tools=compact, digest=usage.tools_hash(compact), guide={}, changes=None, trial={'ok': True})
    return store


@pytest.fixture
def verified(tmp_path):
    store = Store(str(tmp_path / 'proof.db')); store.path = str(tmp_path / 'proof.db'); transport = RecipeTransport(); register(store, transport)
    client = httpx.Client(transport=transport)
    runtime = WorkflowRuntime(store, McpProxy(store, allow_private=True, http=client), Courier())
    for workflow in store.list_workflows(is_template=1)[0]:
        result = wait(runtime, runtime.submit(workflow, actor='template-verifier', source='verification'))
        assert result['status'] == 'succeeded', result
        assert len(result['node_results']) == 3
        assert all(node['status'] == 'succeeded' for node in result['node_results'])
        if workflow['name'].startswith('Daily'):
            assert all('Internal model' not in node['output'] and 'Provider-only' not in node['output'] for node in result['node_results'])
    assert len(transport.calls) == 6
    yield store, transport
    client.close(); store._db.close()


def test_all_three_real_protocol_graphs_and_proofs(verified):
    store, _ = verified
    assert set(verified_recipes(store.path)) == {NEWS_URL, NEWS_RESEARCH_URL, DOCS_URL, PADEL_URL}


def test_replacement_backup_history_and_restart(verified, tmp_path):
    proof, transport = verified
    path = tmp_path / 'target.db'; store = register(Store(str(path)), transport)
    private_id = store.create_workflow({'name': 'Keep my workflow', 'nodes': [], 'edges': [], 'is_template': 0})
    old_ids = [w['id'] for w in store.list_workflows(is_template=1)[0]]
    # Create a historical audit record that must survive hub definition deletion.
    runtime = WorkflowRuntime(store)
    with store.tx() as db:
        db.execute("INSERT INTO workflow_runs (id,workflow_id,digest,snapshot,actor,source,status,created) VALUES ('historical',?,'old','{}','test','test','failed',1)", (old_ids[0],))
    store._db.close()
    result = replace_templates(path, proof.path, tmp_path / 'security-backups')
    assert result['deleted'] == 3
    assert os.stat(result['backup']).st_mode & 0o777 == 0o600
    backup = json.loads(open(result['backup']).read()); assert len(backup['templates']) == 3
    reopened = Store(str(path))
    assert reopened.get_workflow(private_id)['name'] == 'Keep my workflow'
    assert reopened.query("SELECT id FROM workflow_runs WHERE id='historical'")
    workflows, total = reopened.list_workflows(is_template=1); assert total == 3
    assert all(w['id'] not in old_ids and len(w['nodes']) == 3 for w in workflows)
    changed = workflows[0]['id']; reopened.update_workflow(changed, {'name': 'My reviewed title', 'is_active': 0})
    reopened._db.close(); reopened = Store(str(path))
    assert reopened.get_workflow(changed)['name'] == 'My reviewed title'
    assert reopened.get_workflow(changed)['is_active'] == 0
    assert reopened.list_workflows(is_template=1)[1] == 3
    reopened._db.close()


def test_missing_target_endpoint_rolls_back(verified, tmp_path):
    proof, _ = verified
    path = tmp_path / 'missing.db'; store = Store(str(path)); before = store.list_workflows(is_template=1)[0]; store._db.close()
    with pytest.raises(ValueError, match='not registered'):
        replace_templates(path, proof.path, tmp_path / 'security-backups')
    with sqlite3.connect(path) as db:
        assert [row[0] for row in db.execute('SELECT id FROM agent_workflows ORDER BY id')] == sorted(w['id'] for w in before)


def test_stale_or_mismatched_schema_proof_rejected(verified):
    proof, _ = verified
    with proof.tx() as db: db.execute("UPDATE resources SET usage_tools_hash='changed'")
    with pytest.raises(ValueError, match='schema'):
        verified_recipes(proof.path)


def test_mid_transaction_failure_restores_all_definitions(verified, tmp_path):
    proof, transport = verified
    path = tmp_path / 'rollback.db'; store = register(Store(str(path)), transport)
    before = [dict(row) for row in store.query('SELECT id,name,steps FROM agent_workflows ORDER BY id')]
    with store.tx() as db:
        db.execute("CREATE TRIGGER installation_failure BEFORE INSERT ON agent_workflows WHEN NEW.name='Padel Racket Discovery & Comparison' BEGIN SELECT RAISE(ABORT,'test installation failure'); END")
    store._db.close()
    with pytest.raises(sqlite3.IntegrityError, match='installation failure'):
        replace_templates(path, proof.path, tmp_path / 'security-backups')
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        assert [dict(row) for row in db.execute('SELECT id,name,steps FROM agent_workflows ORDER BY id')] == before


def test_replacement_loads_required_vector_extension_without_removing_triggers(verified, tmp_path, monkeypatch):
    proof, transport = verified
    path = tmp_path / 'vector-maintenance.db'
    store = register(Store(str(path)), transport)
    before = [tuple(row) for row in store.query(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'legacy_vector_%' ORDER BY name")]
    if not before:
        store._db.close()
        pytest.skip('sqlite-vec is unavailable in this runtime')
    store._db.close()
    original_load = workflow_template_install.load_sqlite_vec
    loaded = []

    def initialize(db):
        result = original_load(db)
        loaded.append(db.execute('SELECT vec_version()').fetchone()[0])
        with pytest.raises(sqlite3.OperationalError, match='not authorized'):
            db.execute("SELECT load_extension('unused-fixture-extension')")
        return result

    monkeypatch.setattr(workflow_template_install, 'load_sqlite_vec', initialize)
    result = replace_templates(path, proof.path, tmp_path / 'security-backups')
    assert result['deleted'] == 3 and len(result['installed']) == 3 and len(loaded) == 1
    with sqlite3.connect(path) as db:
        after = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'legacy_vector_%' ORDER BY name").fetchall()
        assert after == before


def test_missing_required_vector_extension_refuses_before_backup_and_changes(verified, tmp_path, monkeypatch):
    proof, transport = verified
    path = tmp_path / 'vector-unavailable.db'
    store = register(Store(str(path)), transport)
    if not store.query("SELECT 1 FROM sqlite_master WHERE name='vec_resources'"):
        store._db.close()
        pytest.skip('sqlite-vec is unavailable in this runtime')
    before = [tuple(row) for row in store.query('SELECT id,name,steps FROM agent_workflows ORDER BY id')]
    resources = [tuple(row) for row in store.query('SELECT id,usage_tools,usage_tools_hash,usage_updated_at FROM resources ORDER BY id')]
    store._db.close()
    monkeypatch.setattr(workflow_template_install, 'load_sqlite_vec', lambda db: False)
    directory = tmp_path / 'security-backups'
    with pytest.raises(ValueError, match='vector extension is unavailable'):
        replace_templates(path, proof.path, directory)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT id,name,steps FROM agent_workflows ORDER BY id').fetchall() == before
        assert db.execute('SELECT id,usage_tools,usage_tools_hash,usage_updated_at FROM resources ORDER BY id').fetchall() == resources
    assert list(directory.glob('*.json')) == []


def test_empty_catalogue_does_not_invent_resource_ids(tmp_path):
    store = Store(str(tmp_path / 'empty.db'))
    templates, total = store.list_workflows(is_template=1)
    assert total == 3
    assert all('resource_id' not in n for w in templates for n in w['nodes'])
    store._db.close()


@pytest.mark.parametrize('selection', [{'path': '__import__("os")'}, {'path': 'missing'}, {'path': 'items', 'limit': 99}, {'path': 'items', 'fields': {}}])
def test_output_selection_fails_closed(selection):
    with pytest.raises(WorkflowError): project_output({'items': []}, selection)


def test_output_selection_bounds_text_and_excludes_unselected_fields():
    result = project_output({'items': [{'title': 'a' * 200, 'private': 'hidden'}]}, {'path': 'items', 'fields': {'title': 'title'}, 'max_text': 100})
    assert result == {'items': [{'title': 'a' * 100}], 'truncated': True}

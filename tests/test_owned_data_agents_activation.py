"""Operating composition remains opt-in and preserves existing admission gates."""
import json
import re

from fastapi.testclient import TestClient
import pytest

from agent_market.concierge.front import Front, create_front_app, clear_front_caches
from agent_market.gateway.store import Store
from agent_market.owned_data_agents.activation import install, MARKER
from agent_market.owned_data_agents.english import normalize
from agent_market.owned_data_agents.service import PREFIX
from agent_market.owned_data_agents.staging import TEST_IDS
from agent_market.owned_data_agents.verification import wait
from agent_market.concierge.testbench_examples import live_examples
from tests.test_owned_data_agents import engine  # noqa: F401


@pytest.fixture
def operating(tmp_path, engine, monkeypatch):  # noqa: F811
    core, calls, state = engine
    monkeypatch.setattr('agent_market.owned_data_agents.engine.DataAgents', lambda **_:core)
    # Startup also checks Technical Documentation; keep it off the network.
    import httpx
    from agent_market.owned_data_agents import docs
    from tests.test_technical_docs_agent import agent
    docs_core, docs_http = agent(lambda request: httpx.Response(200, json={'documents': [{'mdn_url': '/en-US/docs/Web/API/AbortController',
        'title': 'AbortController', 'summary': 'Aborts requests.'}]}))
    monkeypatch.setattr(docs, 'engine', lambda: docs_core)
    clear_front_caches()
    store = Store(str(tmp_path/'activation.sqlite3'))
    front = Front(store, public_url='https://agentconcierge.biz')
    app = create_front_app(front, owned_data_agents_enabled=True, manage_book_lifecycle=False)
    with TestClient(app, base_url='https://agentconcierge.biz') as client:
        try:
            yield front, client, core, calls, state
        finally:
            for future in front.workflows.futures.values():
                future.result(timeout=30)
            front.book.close()
            clear_front_caches()
    docs_http.close()
    store._db.close()


def test_installed_four_examples_and_three_templates_use_actual_data(operating):
    front, client, core, calls, _ = operating
    presets = live_examples(front.store)
    assert [r['id'] for r in presets] == list(TEST_IDS)
    assert all(r['available'] for r in presets)
    for row in presets:
        reply = front.proxy.execute(row['resource_id'],row['tool'],row['args'],public=True)
        assert reply['ok'], reply
        assert reply['result']['structuredContent']['source']['url'].startswith('https://')
    workflows, _ = front.store.list_workflows()
    templates = [w for w in workflows if w['is_template'] and w['is_active']]
    assert len(templates) == 3
    for workflow in templates:
        submitted = front.workflows.submit(workflow)
        result = wait(front.workflows,submitted)
        assert result['status'] == 'succeeded', result
    assert {r.url.host for r in calls} == {'hn.algolia.com','api.crossref.org','api.worldbank.org','registry.npmjs.org','api.osv.dev','api.github.com'}
    response = client.post(PREFIX+'/country-profile/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call',
        'params':{'name':'get_country_profile','arguments':{'country_code':'US'}}})
    assert response.status_code == 200 and response.json()['result']['isError'] is False


def test_activation_is_idempotent_preserves_custom_and_history(tmp_path):
    store = Store(str(tmp_path/'preserve.sqlite3'))
    old = store.query('SELECT workflow_id FROM workflow_seed_registry')
    custom = store.create_workflow({'name':'Custom untouched','is_template':1,'nodes':[],'edges':[]})
    first = install(store,'https://agentconcierge.biz')
    count = store.list_workflows()[1]
    assert first == install(store,'https://agentconcierge.biz')
    assert store.list_workflows()[1] == count
    assert store.get_workflow(custom)['is_template'] == 1
    for row in old:
        saved = store.get_workflow(row[0])
        assert saved and not saved['is_template'] and saved['nodes']
    assert store.query('SELECT value FROM meta WHERE key=?',(MARKER,))
    store._db.close()


def test_modified_owned_binding_and_kill_switch_are_not_bypassed(operating):
    front, _, _, _, _ = operating
    row = live_examples(front.store)[0]
    rid = row['resource_id']
    with front.store.tx() as db:
        db.execute("UPDATE resources SET url='https://untrusted.example/mcp' WHERE id=?",(rid,))
    result = front.proxy.execute(rid,row['tool'],row['args'],public=True)
    assert not result['ok'] and result['error_code'] == 'SCHEMA_CHANGED'
    with front.store.tx() as db:
        db.execute('UPDATE execution_controls SET invoke_enabled=0')
    other = live_examples(front.store)[1]
    assert not other['available']
    assert not front.proxy.execute(rid,row['tool'],row['args'],public=True)['ok']


def test_english_translates_prose_and_omits_unavailable_records():
    raw = {'query':'public research','items':[{'title':'\ud55c\uae00 \uc81c\ubaa9','url':'https://example.org/record', 'publisher':'Research press'}],'partial':False}
    translated = normalize(raw,lambda value:'Research on connected agents')
    assert translated['items'][0]['title'] == 'Research on connected agents'
    assert normalize(raw)['items'] == [] and normalize(raw)['partial']
    invalid = normalize(raw,lambda value:'<script>bad</script>')
    assert not invalid['items']
    assert not re.search(r'[\uac00-\ud7af]',json.dumps(translated,ensure_ascii=False))
    assert normalize({'description':'Contact person@example.invalid token=abc'})['description'] == 'Contact [contact omitted] [private text omitted]'


@pytest.mark.parametrize('path',['/new/en/sign-in.html','/new/en/workspace.html','/new/en/account.html'])
def test_account_pages_remain_out_of_search_index(operating,path):
    _, client, _, _, _ = operating
    reply = client.get(path)
    assert reply.status_code == 200
    assert 'noindex' in reply.headers['x-robots-tag']
    assert 'noindex, noarchive' in reply.text


def test_operating_browser_runs_examples_templates_and_exported_apps(operating, browser, tmp_path):  # noqa: F811
    from types import SimpleNamespace
    from tests.test_owned_data_agents_browser import test_staged_four_examples_and_three_templates_execute_and_download as exercise
    front, client, _, calls, _ = operating
    resources = {binding[0]:rid for rid,binding in front.proxy._owned_data_dispatch.bindings.items()}
    exercise((SimpleNamespace(store=front.store,resources=resources),client,calls),browser,tmp_path)


from tests.test_front_workflow_browser import browser  # noqa: E402,F401

import time
import pytest
from fastapi.testclient import TestClient
from tests.admin_public_helpers import prepare, approved
from agent_market.config import GatewayConfig
from agent_market.gateway.server import create_app
from agent_market.gateway.store import Store
from tests.test_gateway import NET

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def completed_run(client,response,headers):
    assert response.status_code == 202
    identity=response.json()['run_id']
    for _ in range(500):
        data=client.get('/admin/api/workflows/runs/'+identity,headers=headers).json()
        if data['status'] in ('succeeded','failed','cancelled'):return data
        time.sleep(.01)
    pytest.fail('Workflow stayed pending')

@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test_reports_wf.sqlite3")
    store = Store(db_path)
    report_subject = store.upsert_resource({
        'key': 'mcp:https://padeltrue.com/mcp/', 'kind': 'mcp',
        'url': 'https://padeltrue.com/mcp/', 'name': 'PadelTrue',
        'source': 'test', 'description': 'Isolated report subject.',
        'category': 'data_utility', 'networks': [], 'details': {},
    })
    store.create_test_report({
        "resource_id": report_subject,
        "title": "Comprehensive Verification: PadelTrue MCP",
        "slug": "padeltrue-test-unit",
        "kind": "mcp",
        "source": "mcp_registry",
        "agent_name": "PadelTrue",
        "agent_url": "https://padeltrue.com/mcp/",
        "category": "data_utility",
        "eval_grade": "A",
        "eval_score": 99.9,
        "status_code": 200,
        "latency_ms": 320.0,
        "is_success": 1,
        "test_method": "MCP JSON-RPC",
        "tool_name": "search_rackets",
        "input_wire": {"method": "tools/call"},
        "output_wire": {"result": "ok"},
        "summary": "PadelTrue unit test verification",
        "content_md": "# PadelTrue Test Report\n\n## Pros and Cons\n\n### Pros\n- Fast\n### Cons\n- No sort",
        "pros": ["Fast response", "Rich catalog"],
        "cons": ["Lacks sort"],
        "workflow_recommendation": "Integrate into sports coach workflow",
        "tags": "sports,padel,mcp",
    })
    config = GatewayConfig(NET, None, db_path, None, 1, 3600, 900, False, True)
    app = create_app(config, store=store)
    test_client=TestClient(app)
    test_client._public_test_store=store
    return test_client

def test_list_and_get_test_reports(client):
    # Unauthenticated should fail (or return auth required based on settings)
    # Login as sadmin
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # List test reports
    r = client.get("/admin/api/test-reports", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["total"] >= 1
    assert len(data["reports"]) >= 1
    report = data["reports"][0]
    assert report["eval_grade"] == "A"
    assert "Fast response" in report["pros"]

    # Filter by kind
    r_mcp = client.get("/admin/api/test-reports?kind=mcp", headers=headers)
    assert r_mcp.status_code == 200
    assert len(r_mcp.json()["reports"]) >= 1

    r_none = client.get("/admin/api/test-reports?kind=nonexistent", headers=headers)
    assert r_none.status_code == 200
    assert len(r_none.json()["reports"]) == 0

    # Get specific report
    r_detail = client.get(f"/admin/api/test-reports/{report['id']}", headers=headers)
    assert r_detail.status_code == 200
    detail = r_detail.json()["report"]
    assert detail["agent_name"] == "PadelTrue"
    assert "input_wire" in detail
    assert "output_wire" in detail
    assert "content_md" in detail

def test_create_test_report(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    new_report = {
        "title": "Scheduled Verification: Capacitor MCP",
        "slug": "scheduled-capacitor-unit",
        "kind": "mcp",
        "source": "mcp_registry",
        "agent_name": "io.capawesome/capacitor-mcp",
        "agent_url": "https://mcp.capawesome.io/mcp",
        "category": "dev_tools",
        "eval_grade": "A",
        "eval_score": 99.8,
        "status_code": 200,
        "latency_ms": 410.0,
        "is_success": 1,
        "test_method": "MCP tools/call",
        "tool_name": "search_docs",
        "summary": "Capacitor docs unit test report",
        "content_md": "# Capacitor Docs Verification",
        "pros": ["Authoritative documentation"],
        "cons": ["Requires Accept header"],
        "workflow_recommendation": "Use in mobile app generator",
        "tags": "mobile,capacitor,mcp",
    }
    # A success report needs a recorded execution of the current connection; a claim alone is refused.
    r = client.post("/admin/api/test-reports", json=new_report, headers=headers)
    assert r.status_code == 422 and r.json()["error_code"] == "EXECUTION_EVIDENCE_REQUIRED"
    failed = {**new_report, "slug": "scheduled-capacitor-unit-failed", "is_success": 0, "eval_grade": None, "eval_score": None,
              "status_code": 503, "summary": "Capacitor docs did not respond"}
    r = client.post("/admin/api/test-reports", json=failed, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert isinstance(r.json()["id"], int)

def test_workflows_lifecycle_and_run(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # List default seeded workflows
    r = client.get("/admin/api/workflows", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["total"] == 3
    wf1 = data["workflows"][0]
    assert "steps" in wf1
    assert len(wf1["steps"]) >= 1

    # Execute workflow run and verify real output
    run_resp = client.post(f"/admin/api/workflows/{wf1['id']}/run", headers=headers)
    run_data = completed_run(client,run_resp,headers)
    assert run_data['status']=='failed'
    assert run_data['workflow_id']==wf1['id']
    assert any(n['status']=='failed' for n in run_data['node_results'])
    assert run_data['final_deliverable']['distribution']['status']=='NOT_REQUESTED'

    # Create new workflow
    new_wf = {
        "name": "Custom Currency & Dispatch Pipeline",
        "description": "Chains Forex converter to A2A SMS dispatcher",
        "category": "finance",
        "trigger_type": "scheduled",
        "tags": "forex,a2a,alerts",
        "steps": [
            {"step": 1, "resource_id": 17881, "name": "Forex", "kind": "x402", "action": "convert"},
            {"step": 2, "resource_id": 61212, "name": "Kenoodl Phone", "kind": "a2a", "action": "dispatch"}
        ]
    }
    create_resp = client.post("/admin/api/workflows", json=new_wf, headers=headers)
    assert create_resp.status_code == 200
    created_id = create_resp.json()["id"]

    # Update workflow
    update_resp = client.put(f"/admin/api/workflows/{created_id}", json={"name": "Updated Pipeline Name"}, headers=headers)
    assert update_resp.status_code == 200

    # Verify update
    get_resp = client.get(f"/admin/api/workflows/{created_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["workflow"]["name"] == "Updated Pipeline Name"


def test_visual_dag_workflow_nodes_edges_and_execution(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # Create a visual DAG graph workflow with nodes and edges
    dag_wf = {
        "name": "Visual Multi-Agent Yield & Alert DAG",
        "description": "Visual DAG connecting weather probe to currency converter and alert dispatcher",
        "category": "finance",
        "trigger_type": "manual",
        "nodes": [
            {
                "id": "node-trigger-1",
                "type": "trigger",
                "name": "Manual Run Trigger",
                "kind": "trigger",
                "position": {"x": 50, "y": 150},
                "data": {"trigger_type": "manual"}
            },
            {
                "id": "node-agent-1",
                "type": "agent",
                "name": "Forex Live Rate",
                "kind": "x402",
                "resource_id": 17881,
                "position": {"x": 340, "y": 120},
                "data": {"action": "convert", "input": {"from": "USD", "to": "KRW", "amount": 500}}
            },
            {
                "id": "node-agent-2",
                "type": "agent",
                "name": "SMS Dispatcher",
                "kind": "a2a",
                "resource_id": 61212,
                "position": {"x": 680, "y": 150},
                "data": {
                    "action": "message/send",
                    "input": {"message": "Yield notification with FX rate: {{$node['Forex Live Rate'].output}}"}
                }
            }
        ],
        "edges": [
            {"id": "e1", "source": "node-trigger-1", "target": "node-agent-1"},
            {"id": "e2", "source": "node-agent-1", "target": "node-agent-2"}
        ]
    }

    create_res = client.post("/admin/api/workflows", json=dag_wf, headers=headers)
    assert create_res.status_code == 200
    assert create_res.json()["ok"] is True
    wf_id = create_res.json()["id"]

    # Verify nodes and edges are stored and retrieved
    get_res = client.get(f"/admin/api/workflows/{wf_id}", headers=headers)
    assert get_res.status_code == 200
    wf_data = get_res.json()["workflow"]
    assert "nodes" in wf_data
    assert "edges" in wf_data
    assert len(wf_data["nodes"]) == 3
    assert len(wf_data["edges"]) == 2

    # Execute DAG workflow
    run_res = client.post(f"/admin/api/workflows/{wf_id}/run", headers=headers)
    run_info=completed_run(client,run_res,headers)
    assert run_info['status']=='failed'
    assert [n['node_id'] for n in run_info['node_results']]==['node-trigger-1','node-agent-1','node-agent-2']
    assert run_info['node_results'][-1]['status']=='blocked'
    assert run_info['node_results'][-1]['attempts']==0


def test_admin_ui_has_visual_workflow_canvas_and_zero_n8n(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    ui_resp = client.get("/admin/ui", headers=headers)
    assert ui_resp.status_code == 200
    html = ui_resp.text

    # Strict compliance test: Absolutely NO "n8n" references in the user-visible UI!
    assert "n8n" not in html.lower(), "Found unexpected n8n reference in Admin UI!"

    # Verify Visual Canvas elements exist in the Admin UI
    assert 'id="workflowCanvasContainer"' in html
    assert 'id="wfSvgCanvas"' in html
    assert 'id="wfNodesLayer"' in html
    assert 'id="wfInspector"' in html
    assert 'id="btnAddNodeDropdownBtn"' in html
    assert 'id="btnCanvasAutoLayout"' in html
    assert 'id="btnRunCanvasWorkflow"' in html
    assert 'id="btnSaveCanvasWorkflow"' in html

    # Verify Expanded Views and Modals
    assert 'id="aiComposerPrompt"' in html
    assert 'id="btnRunAiComposer"' in html
    assert 'id="workflowTemplatesView"' in html
    assert 'id="workflowMyView"' in html
    assert 'id="workflowLLMView"' in html
    assert 'id="workflowAppExportModal"' in html
    assert 'id="workflowShareModal"' in html
    assert 'id="workflowPublishModal"' in html
    assert 'id="workflowReviewModal"' in html
    assert 'id="credentialEditModal"' in html


def test_workflow_templates_hub_and_filtering(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # List templates (is_template=1)
    res = client.get("/admin/api/workflows?is_template=1", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["total"] >= 3
    for t in data["workflows"]:
        assert t["is_template"] == 1
        assert t["author"] == "Agent Concierge"
        assert t["rating_avg"] == 0.0

    # Filter by category
    res_dev = client.get("/admin/api/workflows?is_template=1&category=dev_tools", headers=headers)
    assert res_dev.status_code == 200
    assert len(res_dev.json()["workflows"]) >= 1
    assert res_dev.json()["workflows"][0]["category"] == "dev_tools"

    # Sort by popular and rating
    res_pop = client.get("/admin/api/workflows?is_template=1&sort_by=popular", headers=headers)
    assert res_pop.status_code == 200
    assert len(res_pop.json()["workflows"]) >= 1


def test_workflow_forking_and_my_page(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # Get first template
    tmpl_res = client.get("/admin/api/workflows?is_template=1", headers=headers)
    tmpl = tmpl_res.json()["workflows"][0]
    initial_forks = tmpl.get("forks_count", 0)

    # Fork template into My Workflows
    fork_res = client.post(
        f"/admin/api/workflows/{tmpl['id']}/fork",
        json={"author": "Researcher_Alice", "name": "Alice's Flight Agent"},
        headers=headers,
    )
    assert fork_res.status_code == 200
    forked = fork_res.json()["workflow"]
    assert forked["name"] == "Alice's Flight Agent"
    assert forked["is_template"] == 0
    assert forked["parent_workflow_id"] == tmpl["id"]
    assert forked["author"] == "Researcher_Alice"

    # Verify original template forks_count was incremented
    tmpl_check = client.get(f"/admin/api/workflows/{tmpl['id']}", headers=headers).json()["workflow"]
    assert tmpl_check["forks_count"] == initial_forks + 1

    # Verify My Workflows listing (is_template=0)
    my_res = client.get("/admin/api/workflows?is_template=0", headers=headers)
    assert my_res.status_code == 200
    my_ids = [w["id"] for w in my_res.json()["workflows"]]
    assert forked["id"] in my_ids

    # Delete forked workflow and verify it is permanently removed
    del_res = client.delete(f"/admin/api/workflows/{forked['id']}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["ok"] is True

    # Verify it is no longer listed in My Workflows
    my_res_after = client.get("/admin/api/workflows?is_template=0", headers=headers)
    assert my_res_after.status_code == 200
    my_ids_after = [w["id"] for w in my_res_after.json()["workflows"]]
    assert forked["id"] not in my_ids_after


def test_workflow_publish_to_template_hub(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # Create a custom personal workflow
    custom_wf = {
        "name": "Custom Crypto Arbitrage Pipeline",
        "description": "Calculates spot vs perpetual price discrepancies across DEXs",
        "category": "finance_crypto",
        "trigger_type": "manual",
        "is_template": 0,
        "author": "Trader_Bob",
        "steps": [
            {"step": 1, "resource_id": 17881, "name": "Forex", "kind": "x402", "action": "convert"}
        ]
    }
    create_res = client.post("/admin/api/workflows", json=custom_wf, headers=headers)
    wf_id = create_res.json()["id"]

    prepare(client._public_test_store,headers)
    # Publish to Template Hub
    pub_res = client.post(
        f"/admin/api/workflows/{wf_id}/publish-template",
        json={
            "author": "Trader_Bob",
            "author_wallet": "0xBobLightningOrUSDC",
            "category": "finance_crypto",
            "tags": "crypto,arbitrage,defi",
            "reason": "Synthetic public template review"
        },
        headers=headers
    )
    assert not client.get(f"/admin/api/workflows/{wf_id}",headers=headers).json()['workflow']['is_template']
    assert approved(client,headers,pub_res)['published']
    published_wf=client.get(f"/admin/api/workflows/{wf_id}",headers=headers).json()['workflow']
    assert published_wf['is_template']==1
    assert published_wf['author']=='Trader_Bob'
    assert published_wf.get('author_wallet')!='0xBobLightningOrUSDC'


def test_workflow_reviews_and_ratings(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # Review workflow 1
    rev_res = client.post(
        "/admin/api/workflows/1/reviews",
        json={"rating": 5, "reviewer": "Agent QA Bot", "comment": "Seamless DAG orchestration."},
        headers=headers
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["ok"] is True

    # List reviews
    list_rev = client.get("/admin/api/workflows/1/reviews", headers=headers)
    assert list_rev.status_code == 200
    assert len(list_rev.json()["reviews"]) >= 1
    assert list_rev.json()["reviews"][0]["rating"] == 5


def test_prompt_to_dag_ai_auto_composer(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    prompt_req = {
        "prompt": "Find flight deals from Seoul to San Francisco and convert ticket cost with live forex rates"
    }
    ai_res = client.post("/admin/api/workflows/ai-generate", json=prompt_req, headers=headers)
    assert ai_res.status_code == 422
    assert 'No matching registered agents' in ai_res.json()['detail']


def test_standalone_pwa_web_app_export(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    export_req = {
        "title": "Flight & Forex Express App",
        "description": "Standalone offline/online PWA Web App",
        "is_paid": True,
        "price_sats": 750,
        "wallet_address": "creator@ln.tips",
        "require_google_auth": True,
        "google_client_id": "12345678-client.apps.googleusercontent.com"
    }
    exp_res = client.post("/admin/api/workflows/1/export-app", json=export_req, headers=headers)
    assert exp_res.status_code == 400
    templates=client.get('/admin/api/workflows?is_template=1',headers=headers).json()['workflows']
    from agent_market.workflows import public_template
    template=next(t for t in templates if public_template(t))
    exported=client.post(f"/admin/api/workflows/{template['id']}/export-app",json={},headers=headers)
    assert exported.status_code==200
    config=exported.json()['config']
    assert config['workflow_id']==template['id']
    assert config['execution_mode']=='server'
    assert 'google_client_id' not in config and 'wallet_address' not in config


def test_platform_credentials_management(client):
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # 1. Register Gemini Key
    save_gemini = client.post(
        "/admin/api/credentials",
        json={
            "key_name": "GEMINI_API_KEY",
            "key_value": "AIzaSyTestGeminiKey123456",
            "provider": "gemini",
            "description": "Gemini 2.5 Flash Production Key"
        },
        headers=headers
    )
    assert save_gemini.status_code == 200

    # 2. List credentials - check masking for security
    list_res = client.get("/admin/api/credentials", headers=headers)
    assert list_res.status_code == 200
    creds = list_res.json()["credentials"]
    gemini_entry = next(c for c in creds if c["key_name"] == "GEMINI_API_KEY")
    assert gemini_entry["has_value"] is True
    assert "AIz" in gemini_entry["masked_value"]
    assert "3456" in gemini_entry["masked_value"]
    assert "TestGeminiKey" not in gemini_entry["masked_value"]  # masked!

    # 3. Delete credential
    del_res = client.delete("/admin/api/credentials/GEMINI_API_KEY", headers=headers)
    assert del_res.status_code == 200

    # Verify deletion
    list_after = client.get("/admin/api/credentials", headers=headers).json()["credentials"]
    assert not any(c["key_name"] == "GEMINI_API_KEY" for c in list_after)


def test_all_templates_require_actual_agents_and_safe_export(client):
    response=client.post('/admin/api/auth/login',json={'username':'sadmin','password':'sadmin'},headers={'X-Dashboard':'1'})
    headers={'Authorization':'Bearer '+response.json()['token'],'X-Dashboard':'1'}
    templates=client.get('/admin/api/workflows?is_template=1&limit=50',headers=headers).json()['workflows']
    assert len(templates)==3
    from agent_market.workflows import public_template
    for template in templates:
        response=client.post(f"/admin/api/workflows/{template['id']}/run",json={},headers=headers)
        result=completed_run(client,response,headers)
        assert result['status']=='failed' # This fixture deliberately has no registered providers.
        assert all(n['status']!='COMPLETED' for n in result['node_results'])
        assert result['final_deliverable']['distribution']['status']=='NOT_REQUESTED'
        response=client.post(f"/admin/api/workflows/{template['id']}/export-app",json={},headers=headers)
        if public_template(template):
            assert response.status_code==200
            assert 'sample_output' not in str(response.json()['config'])
        else:assert response.status_code==400





def seed_registered_replacements(client):
    store=client.app.state.front.store
    for category in ('dev_tools','travel_maps_weather','finance_crypto'):
        for kind in ('mcp','a2a'):
            rid=store.upsert_resource({'key':kind+':https://replacement.example/'+category,'source':'test','kind':kind,'url':'https://replacement.example/'+category,'name':category+' discovery Agent','description':'Registered replacement agent','category':category,'price_usdc':0,'details':{}})
            with store.tx() as db:db.execute("UPDATE resources SET health_status='healthy',eval_grade='A',eval_score=98 WHERE id=?",(rid,))

def test_workflow_agent_alternatives_recommendation(client):
    seed_registered_replacements(client)
    primary_id = client.app.state.front.store.upsert_resource({
        'key': 'fixture:weather-primary', 'source': 'test', 'kind': 'mcp',
        'url': 'https://weather-primary.example/mcp', 'name': 'Registered weather primary',
        'description': 'Synthetic registered replacement subject', 'category': 'travel_maps_weather',
        'price_usdc': 0, 'details': {},
    })
    """테스트: 서비스 중지 또는 비활성화 에이전트에 대한 동일·유사 대체 에이전트 추천 API 검증"""
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # Use a registered subject rather than an invented negative simulation ID.
    res = client.get(f"/admin/api/workflows/agents/alternatives?agent_id={primary_id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "alternatives" in data
    assert data["target_agent"]["id"] == primary_id
    assert data["target_agent"]["category"] == "travel_maps_weather"
    assert len(data["alternatives"]) >= 1

    # The primary subject must be excluded from its replacement list.
    alt_ids = [a["id"] for a in data["alternatives"]]
    assert primary_id not in alt_ids

    # 첫 번째 추천 항목 검증: 유사도, 추천 사유, 도구 정보
    first_alt = data["alternatives"][0]
    assert "similarity_pct" in first_alt
    assert first_alt["similarity_pct"] >= 60
    assert "match_reason" in first_alt
    assert "tools" in first_alt
    assert first_alt["health_status"] != "down"

    # 2. 프로토콜 필터링 (kind=mcp)
    res_mcp = client.get("/admin/api/workflows/agents/alternatives?kind=mcp", headers=headers)
    assert res_mcp.status_code == 200
    for a in res_mcp.json()["alternatives"]:
        assert a["kind"] == "mcp"

    # 3. 검색 쿼리 필터링 (q=discovery)
    res_q = client.get("/admin/api/workflows/agents/alternatives?q=discovery", headers=headers)
    assert res_q.status_code == 200
    assert len(res_q.json()["alternatives"]) >= 1
    assert any("discovery" in (a["name"] + a.get("url", "") + a.get("description", "")).lower() for a in res_q.json()["alternatives"])


def test_free_agent_replacement_test_workflows(client):
    seed_registered_replacements(client)
    """무료 에이전트 워크플로우 템플릿 3종 생성 및 각 비활성화 노드 대체 추천/교체 기능 테스트"""
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}

    # 1. 템플릿 목록 조회
    res = client.get("/admin/api/workflows?is_template=1", headers=headers)
    assert res.status_code == 200
    templates = res.json()["workflows"]

    test_wf_names = ["Test suspended development workflow"]
    store = client.app.state.front.store
    resources = store.query("SELECT id FROM resources WHERE url LIKE 'https://replacement.example/%' LIMIT 3")
    nodes = [{'id':'start','type':'trigger','name':'Manual Trigger','data':{}}]
    for index, resource in enumerate(resources):
        nodes.append({'id':f'agent-{index}','type':'agent','name':'Test provider','kind':'mcp','resource_id':resource['id'],
                      'is_active':index != 0,'disabled':index == 0,
                      'data':{'resource_id':resource['id'],'category':'dev_tools','status':'suspended' if index == 0 else 'active',
                              'suspend_reason':'Test-only suspension' if index == 0 else ''}})
    nodes[1]['resource_id'] = nodes[1]['data']['resource_id'] = 99901
    identity = store.create_workflow({'name':test_wf_names[0],'category':'dev_tools','is_template':0,'nodes':nodes,
                                     'edges':[{'source':nodes[i]['id'],'target':nodes[i+1]['id']} for i in range(3)]})
    found_test_wfs = [store.get_workflow(identity)]

    # 2. 각 워크플로우별 노드 상태 및 비활성화 에이전트 검증
    for twf in found_test_wfs:
        detail_res = client.get(f"/admin/api/workflows/{twf['id']}", headers=headers)
        assert detail_res.status_code == 200
        wf = detail_res.json()["workflow"]

        nodes = wf.get("nodes") or []
        assert len(nodes) == 4, f"Workflow {twf['name']} must have 4 nodes (1 trigger + 3 agents)"

        agent_nodes = [n for n in nodes if n.get("type") == "agent"]
        assert len(agent_nodes) == 3

        suspended_nodes = [
            n for n in agent_nodes
            if n.get("is_active") is False or n.get("disabled") is True or n.get("data", {}).get("status") == "suspended"
        ]
        active_nodes = [
            n for n in agent_nodes
            if n not in suspended_nodes
        ]

        # 정확히 1개의 노드만 비활성화/서비스 중지 상태여야 함
        assert len(suspended_nodes) == 1, f"Workflow {twf['name']} must have exactly 1 suspended node"
        assert len(active_nodes) == 2, f"Workflow {twf['name']} must have 2 active free nodes"

        susp_node = suspended_nodes[0]
        assert susp_node.get("data", {}).get("suspend_reason"), "Suspended node must have a suspend_reason"
        susp_rid = susp_node.get("resource_id")
        assert susp_rid in (99901, 99902, 99903)

        # 3. 대체 에이전트 추천 API 호출 검증
        cat = susp_node.get("data", {}).get("category") or twf["category"]
        kind = susp_node.get("kind")
        alt_url = f"/admin/api/workflows/agents/alternatives?agent_id={susp_rid}&category={cat}&kind={kind}"
        alt_res = client.get(alt_url, headers=headers)
        assert alt_res.status_code == 200
        alt_data = alt_res.json()
        assert alt_data["ok"] is True
        assert len(alt_data["alternatives"]) >= 1

        top_alt = alt_data["alternatives"][0]
        assert top_alt["id"] != susp_rid
        assert top_alt["similarity_pct"] >= 75
        assert top_alt["health_status"] in ("healthy", "reachable")

        # 4. 대체 에이전트로 교체 시뮬레이션
        # targetNodeId의 메타데이터를 top_alt로 교체
        susp_node["name"] = top_alt["name"]
        susp_node["kind"] = top_alt["kind"]
        susp_node["resource_id"] = top_alt["id"]
        susp_node["is_active"] = True
        susp_node["disabled"] = False
        susp_node["data"]["name"] = top_alt["name"]
        susp_node["data"]["kind"] = top_alt["kind"]
        susp_node["data"]["resource_id"] = top_alt["id"]
        susp_node["data"]["is_active"] = True
        susp_node["data"]["status"] = "active"
        if "suspend_reason" in susp_node["data"]:
            del susp_node["data"]["suspend_reason"]

        prepare(client._public_test_store,headers)
        # 교체 반영 저장
        update_res = client.put(
            f"/admin/api/workflows/{twf['id']}",
            json={
                "reason": "Synthetic live definition replacement review",
                "name": twf["name"],
                "description": twf["description"],
                "category": twf["category"],
                "nodes": nodes,
                "edges": wf["edges"],
            },
            headers=headers
        )
        assert update_res.status_code==200,update_res.text
        assert update_res.json()["ok"]

        # 교체 후 검증: GET으로 다시 읽어와서 더 이상 중단된 노드가 없어야 함
        get_res = client.get(f"/admin/api/workflows/{twf['id']}", headers=headers)
        assert get_res.status_code == 200
        updated_wf = get_res.json()["workflow"]

        updated_susp = [
            n for n in updated_wf["nodes"]
            if n.get("type") == "agent" and (n.get("is_active") is False or n.get("disabled") is True)
        ]
        assert len(updated_susp) == 0, "After replacement, all nodes must be active"


def test_downloaded_standalone_app_excludes_llm_api_key():
    """테스트: 독립 실행형 앱 다운로드 템플릿에서 'LLM API Key' 설정 영역 및 관련 소스가 완전히 제거되었는지 검증"""
    import os
    dashboard_html_path = os.path.join(
        os.path.dirname(__file__), "..", "agent_market", "gateway", "dashboard.html"
    )
    with open(dashboard_html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 1. 'LLM API Key (선택 사항, 브라우저에 안전하게 저장됨)' 텍스트가 dashboard.html 소스상에 존재하지 않아야 함
    assert "LLM API Key" not in html_content
    assert "appExportByoKeyCheck" not in html_content
    assert "byoKeyBox" not in html_content
    assert "byoKeyInput" not in html_content
    assert "a2a_byo_key" not in html_content
    assert "saveByoKey" not in html_content
    assert "toggleKeySettings" not in html_content


def test_edited_inputs_require_save_before_execution(client):
    response=client.post('/admin/api/auth/login',json={'username':'sadmin','password':'sadmin'},headers={'X-Dashboard':'1'})
    headers={'Authorization':'Bearer '+response.json()['token'],'X-Dashboard':'1'}
    template=client.get('/admin/api/workflows',headers=headers).json()['workflows'][0]
    template['nodes'][-1]['data']['input']={'message':'Changed input'}
    response=client.post(f"/admin/api/workflows/{template['id']}/run",json={'nodes':template['nodes'],'edges':template['edges']},headers=headers)
    assert response.status_code==409
    prepare(client._public_test_store,headers)
    response=client.put(f"/admin/api/workflows/{template['id']}",json={'nodes':template['nodes'],'edges':template['edges'],'reason':'Synthetic changed input review'},headers=headers)
    assert approved(client,headers,response)['published']
    result=completed_run(client,client.post(f"/admin/api/workflows/{template['id']}/run",json={},headers=headers),headers)
    assert result['status']=='failed' # The fixture has no live registered provider.
    assert result['final_deliverable']['distribution']['status']=='NOT_REQUESTED'




def test_shared_export_runtime_source_is_synchronized():
    from pathlib import Path
    builder=Path('agent_market/concierge/workflow_app.js').read_text()
    assert builder in Path('extracted_html.txt').read_text()
    assert builder in Path('agent_market/gateway/dashboard.html').read_text()
    assert 'await client.run(cfg.workflow_id, {definitionHash:cfg.definition_hash})' in builder
    assert '{template_id:workflowId}' in builder
    assert 'Math.random' not in builder and 'isLoggedIn' not in builder








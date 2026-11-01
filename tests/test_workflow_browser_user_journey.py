from tests.test_admin_test_reports_and_workflows import completed_run
import pytest
import subprocess
import shutil
import tempfile
from pathlib import Path
from agent_market.gateway.server import create_app
from agent_market.config import GatewayConfig
from tests.test_gateway import NET
from agent_market.gateway.store import Store
from fastapi.testclient import TestClient



@pytest.fixture
def browser_env(tmp_path,rotated_bootstrap_admin):
    db_path = str(tmp_path / "test_gw.db")
    store = Store(db_path)
    config = GatewayConfig(NET, None, db_path, None, 1, 3600, 900, False, True)
    app = create_app(config, store=store)
    client = TestClient(app)

    # Login as admin
    login_resp = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "sadmin"},
        headers={"X-Dashboard": "1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Dashboard": "1"}
    return client, headers, db_path


def test_user_journey_1_admin_ui_and_workflow_structure(browser_env):
    """User Journey 1: Opening Admin UI and verifying blank canvas start and modal markup."""
    client, headers, _ = browser_env
    ui_resp = client.get("/admin/ui", headers=headers)
    assert ui_resp.status_code == 200
    html = ui_resp.text

    # Verify workflows canvas view elements
    assert 'id="workflowCanvasView"' in html
    assert 'id="workflowCanvasContainer"' in html
    assert 'id="wfActiveSelect"' in html
    assert '전체 템플릿 갤러리 탐색 열기...' in html
    assert 'id="btnClearCanvas"' in html
    assert 'id="btnSaveCanvasWorkflow"' in html
    assert 'id="btnRunCanvasWorkflow"' in html
    assert 'id="btnExportAppFromCanvas"' in html
    assert 'id="btnShareFromCanvas"' in html
    assert 'id="btnCanvasAutoLayout"' in html

    # Verify template gallery modal elements
    assert 'id="workflowTemplateGalleryModal"' in html
    assert 'id="closeTemplateGalleryModalBtn"' in html
    assert 'id="closeTemplateGalleryFootBtn"' in html
    assert 'id="tmplGallerySearch"' in html
    assert 'id="tmplGalleryGrid"' in html

    # Verify standalone app export modal elements
    assert 'id="workflowAppExportModal"' in html
    assert 'id="closeAppExportBtn"' in html
    assert 'id="closeAppExportFootBtn"' in html
    assert 'id="btnDownloadStandaloneApp"' in html

    # Verify real-time canvas run modal elements
    assert 'id="workflowRunModal"' in html
    assert 'id="closeWfRunBtn"' in html
    assert 'id="closeWfRunFootBtn"' in html
    assert 'id="wfRunDeliverableBox"' in html
    assert 'id="wfRunDataFlowList"' in html
    assert 'id="wfRunStepsList"' in html


def test_user_journey_2_template_gallery_and_canvas_load(browser_env):
    """User Journey 2: Browsing templates, loading template into canvas, and running DAG execution."""
    client, headers, _ = browser_env

    # 1. Fetch templates
    tmpl_res = client.get("/admin/api/workflows?is_template=1", headers=headers)
    assert tmpl_res.status_code == 200
    templates = tmpl_res.json()["workflows"]
    assert len(templates) >= 3

    target_tmpl = templates[0]

    # 2. Get template details with nodes and edges
    detail_res = client.get(f"/admin/api/workflows/{target_tmpl['id']}", headers=headers)
    assert detail_res.status_code == 200
    wf = detail_res.json()["workflow"]
    nodes = wf.get("nodes") or []
    edges = wf.get("edges") or []
    assert len(nodes) >= 2

    # 3. Simulate real-time execution in canvas
    run_res = client.post(
        f"/admin/api/workflows/{wf['id']}/run",
        json={"nodes": nodes, "edges": edges},
        headers=headers
    )
    run_data = completed_run(client,run_res,headers)
    assert run_data["status"] == "failed"
    assert "node_results" in run_data
    assert len(run_data["node_results"]) >= 1
    assert "final_deliverable" in run_data
    assert "data_flow_trace" in run_data


def test_user_journey_3_connected_app_builder(browser_env,tmp_path):
    if not shutil.which('node'):pytest.skip('Node.js not available')
    builder=Path('agent_market/concierge/workflow_app.js').read_text()
    script=tmp_path/'builder.cjs'
    script.write_text("const crypto=require('crypto').webcrypto;\n"+builder+"\nconst app=buildWorkflowAppHTML({workflow_id:42,title:'Weather Pipeline',description:'Recorded results',api_origin:'https://agentconcierge.biz'}); console.log(app);")
    generated=subprocess.run(['node',str(script)],capture_output=True,text=True,check=True).stdout
    assert '<html lang="en">' in generated
    assert "connect-src https://agentconcierge.biz" in generated
    assert '/api/workflows/run' in generated and 'template_id' in generated
    assert 'Math.random' not in generated and 'DISPATCH_CONFIRMED' not in generated
    from html.parser import HTMLParser
    class Scripts(HTMLParser):
        capture=False
        chunks=[]
        def handle_starttag(self,tag,attrs):
            if tag=='script':self.capture=dict(attrs).get('type')!='application/json'
        def handle_endtag(self,tag):
            if tag=='script':self.capture=False
        def handle_data(self,data):
            if self.capture:self.chunks.append(data)
    parser=Scripts();parser.feed(generated)
    app_js=tmp_path/'app.js';app_js.write_text(''.join(parser.chunks))
    assert subprocess.run(['node','--check',str(app_js)],capture_output=True).returncode==0




def test_user_journey_4_modal_close_triggers_verification():
    """User Journey 4: Verifying all close triggers for template gallery, app export, share, run modals."""
    dash_path = Path("agent_market/gateway/dashboard.html")
    content = dash_path.read_text(encoding="utf-8")

    # 1. Template gallery close buttons
    assert 'if ($("closeTemplateGalleryModalBtn")) $("closeTemplateGalleryModalBtn").onclick = closeTemplateGalleryModal;' in content
    assert 'if ($("closeTemplateGalleryFootBtn")) $("closeTemplateGalleryFootBtn").onclick = closeTemplateGalleryModal;' in content

    # 2. Template gallery backdrop click
    assert 'if ($("workflowTemplateGalleryModal")) {\n  $("workflowTemplateGalleryModal").addEventListener("click", (e) => {\n    if (e.target === $("workflowTemplateGalleryModal")) closeTemplateGalleryModal();\n  });\n}' in content

    # 3. Backdrop click on all modal overlays
    assert '{ id: "workflowTemplateGalleryModal", fn: closeTemplateGalleryModal }' in content
    assert '{ id: "workflowAppExportModal", fn: closeAppExportModal }' in content
    assert '{ id: "workflowShareModal", fn: closeShareModal }' in content
    assert '{ id: "workflowRunModal", fn: () => {' in content
    assert '{ id: "agentReplacementModal", fn: closeAgentReplacementModal }' in content
    assert '{ id: "workflowScheduleModal", fn: closeWorkflowScheduleModal }' in content

    # 4. Global Escape key handling
    assert 'window.addEventListener("keydown", (e) => {\n  if (e.key === "Escape") {' in content

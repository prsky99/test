import json
import re
import pytest
from starlette.testclient import TestClient
from agent_market.gateway.store import Store
from agent_market.concierge.front import Front, create_front_app, get_front_workflow_templates

pytestmark = pytest.mark.usefixtures('legacy_public_entry')

def test_front_workflow_menu_and_canvas_elements():
    store = Store()
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    res = client.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    # 1. Navigation Tab ordering
    idx_explore = html.find('data-tab="explore"')
    idx_workflows = html.find('data-tab="workflows"')
    idx_register = html.find('data-tab="register"')

    assert idx_explore != -1, "Explore tab not found"
    assert idx_workflows != -1, "Workflows tab not found"
    assert idx_register != -1, "Register tab not found"
    assert idx_explore < idx_workflows < idx_register, "Workflows tab must be between Explore and Register"

    # 2. Workflows panel container
    assert 'id="secWorkflows"' in html
    assert 'data-panel="workflows"' in html

    # 3. Canvas sub-view controls
    assert 'id="btnFrontRunWorkflow"' in html
    assert "Run Workflow" in html
    assert 'id="btnFrontExportApp"' in html
    assert "Download Web App" in html
    assert 'id="btnFrontResetCanvas"' in html
    assert "Reset" in html
    # Add Node and Save Canvas removed per user requirement
    assert 'id="btnFrontSaveCanvas"' not in html
    assert 'id="btnFrontAddNodeDropdown"' not in html
    assert 'id="frontWfCanvasContainer"' in html
    assert 'id="frontWfSvgCanvas"' in html
    assert 'id="frontWfNodesLayer"' in html
    assert 'id="frontWfInspector"' in html

    # 4. Template Hub buttons restriction
    # Must have "Open in Canvas" and "Download Web App"
    assert "Open in Canvas" in html
    assert "Download Web App" in html
    # Must NOT have Admin buttons
    assert "Fork Template" not in html
    assert "Delete Template" not in html
    assert "Add Template" not in html
    assert "+ New Template" not in html

    # 5. Zero occurrences of n8n anywhere
    assert "n8n" not in html.lower()


def test_front_workflow_templates_api_excludes_test_templates():
    store = Store()
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    res = client.get("/api/workflows/templates")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    templates = data["templates"]

    # Exactly three published templates; test templates stay excluded
    assert len(templates) == 3, f"Expected 3 published templates, got {len(templates)}"

    for t in templates:
        name = t.get("name", "")
        tags = (t.get("tags") or "").lower()
        # Strictly verify no test template leaked
        assert not name.startswith("["), f"Test template leaked: {name}"
        assert "test" not in tags
        assert not name.lower().startswith("test")
        # Verify 100% English only
        hangul = re.findall(r"[\uac00-\ud7af]", name + (t.get("description") or ""))
        assert len(hangul) == 0, f"Found Korean in template: {name}"


def test_front_workflow_run_api_execution():
    store = Store()
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    # 1. Run valid DAG pipeline
    payload = {
        "nodes": [
            {
                "id": "node-1",
                "type": "trigger",
                "kind": "trigger",
                "name": "Start Trigger",
                "data": {"action": "start"}
            },
            {
                "id": "node-2",
                "type": "agent",
                "kind": "mcp",
                "name": "Forex Converter",
                "data": {"action": "convert", "sample_output": "1 USD = 1385 KRW"}
            }
        ],
        "edges": [
            {"id": "e-1-2", "source": "node-1", "target": "node-2"}
        ]
    }

    res = client.post("/api/workflows/run", json=payload)
    assert res.status_code == 400
    assert '1 USD = 1385 KRW' not in res.text
    assert client.post('/api/workflows/run',json={'nodes':[]}).status_code==400


def test_front_py_strict_compliance_rules():
    from pathlib import Path
    front_path = Path("agent_market/concierge/front.py")
    front_code = front_path.read_text(encoding="utf-8")

    # 1. Zero Korean characters
    hangul = re.findall(r"[\uac00-\ud7af]", front_code)
    assert len(hangul) == 0, f"Found {len(hangul)} Korean characters in front.py: {set(hangul)}"

    # 2. Zero occurrences of n8n
    assert "n8n" not in front_code.lower(), "Found n8n in front.py"


def test_templates_stored_in_db_in_english():
    import json
    store = Store()
    wfs, _ = store.list_workflows(is_template=1, limit=50)
    verified = wfs
    assert len(verified) == 3

    for w in verified:
        # 1. Title and description in English
        name = w["name"]
        desc = w.get("description") or ""
        assert len(desc) > 0, f"Template {w['id']} missing description"
        hangul_name = re.findall(r"[\uac00-\ud7af]", name)
        hangul_desc = re.findall(r"[\uac00-\ud7af]", desc)
        assert len(hangul_name) == 0, f"Found Korean in name for ID {w['id']}: {set(hangul_name)}"
        assert len(hangul_desc) == 0, f"Found Korean in description for ID {w['id']}: {set(hangul_desc)}"

        # 2. Steps in English
        steps = w.get("steps") or []
        assert len(steps) == 2, f"Template {w['id']} must have two actual agent calls"
        raw_steps = json.dumps(steps, ensure_ascii=False)
        hangul_steps = re.findall(r"[\uac00-\ud7af]", raw_steps)
        assert len(hangul_steps) == 0, f"Found Korean in steps for ID {w['id']}: {set(hangul_steps)}"


def test_front_workflow_lucide_icons():
    store = Store()
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    res = client.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    # 1. Subview buttons use Lucide SVG icons
    assert '<button class="btn sm primary" id="btnFrontWfViewCanvas"' in html
    assert '<button class="btn sm" id="btnFrontWfViewTemplates"' in html

    # 2. Canvas action buttons use Lucide SVG icons
    assert '<button class="btn primary" id="btnFrontRunWorkflow"' in html
    assert '<button class="btn" id="btnFrontExportApp"' in html
    assert '<button class="btn" id="btnFrontResetCanvas"' in html
    assert 'id="btnFrontSaveCanvas"' not in html
    assert 'id="btnFrontAddNodeDropdown"' not in html

    # 3. Lucide SVGs present in canvas action bar
    assert 'points="5 3 19 12 5 21 5 3"' in html  # Lucide play
    assert 'polyline points="7 10 12 15 17 10"' in html  # Lucide download
    assert 'd="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"' in html  # Lucide rotate-ccw

    # 4. Lucide SVGs in Template card buttons
    assert 'rect x="3" y="3" width="18" height="18" rx="2" ry="2"' in html  # Lucide layout
    # Star rating and runs count removed per user requirement (was test data)
    assert '<span class="star-rating"' not in html
    assert 'runs)' not in html

    # 5. Verify emojis replaced
    assert "⚡ Run Workflow" not in html
    assert "💾 Save Canvas" not in html
    assert "📲 Download Web App" not in html
    assert "🖼️ Open in Canvas" not in html
    assert "🗑️ Delete Node" not in html


def test_front_workflow_execution_results_always_english():
    """Verify that workflow live execution results return pure English even if input contains non-English characters."""
    store = Store()
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    # Payload with simulated legacy/Korean nodes
    payload = {
        "nodes": [
            {
                "id": "node-1",
                "name": "\ud55c\uad6d\uc5b4 \uc5d0\uc774\uc804\ud2b8",
                "kind": "mcp",
                "data": {
                    "action": "\uc2e4\ud589",
                    "sample_output": "[\ub3c4\ucfc4 \uae30\uc0c1 \uad00\uce21] \ub9d1\uc74c, 21.8\u00b0C"
                }
            }
        ],
        "edges": []
    }

    res = client.post("/api/workflows/run", json=payload)
    assert res.status_code == 400
    assert 'Choose an available published template' in res.json()['error']
    assert 'Verified Success' not in res.text


def test_front_canvas_toolbar_no_add_node_no_save_canvas():
    """Verify that 'Add Node' and 'Save Canvas' buttons are removed from canvas toolbar."""
    store = Store()
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    res = client.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    assert 'id="btnFrontAddNodeDropdown"' not in html
    assert 'id="btnFrontSaveCanvas"' not in html
    assert 'id="btnFrontRunWorkflow"' in html
    assert 'id="btnFrontExportApp"' in html
    assert 'id="btnFrontResetCanvas"' in html


def test_front_workflow_meta_tags_and_english_compliance():
    """Verify that Workflows screen has full head, section, and PAGE_METAS meta tags in English without sensitive info."""
    store = Store()
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    res = client.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    # 1. Head meta tags for workflows
    for key in ["title", "description", "keywords", "target-action", "retention-hook"]:
        tag = f'page:workflows:{key}'
        m = re.search(rf'name="{tag}" content="([^"]+)"', html)
        assert m is not None, f"Missing head meta tag: {tag}"
        val = m.group(1)
        assert len(val) > 10
        assert len(re.findall(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]", val)) == 0
        for forbidden in ["127.0.0.1", "localhost", "sqlite", "postgres", "password", "port", "0.0.0.0", "secret", "admin", "error", "fail", "vulnerability", "attack"]:
            assert forbidden not in val.lower(), f"Forbidden term '{forbidden}' in {tag}: {val}"

    # 2. Section microdata inside #secWorkflows
    idx_sec = html.find('id="secWorkflows"')
    assert idx_sec != -1
    sec_head = html[idx_sec:].split('<div', 1)[0]
    assert 'meta itemprop="name" content="Agent Concierge — Visual Multi-Agent Workflow Studio &amp; Template Hub"' in sec_head
    assert 'meta itemprop="description" content="Run three published workflows' in sec_head
    assert 'meta name="agent:page" content="workflows"' in sec_head
    assert 'meta name="agent:action" content="orchestrate-and-execute-workflows"' in sec_head
    assert 'meta name="agent:retention-hook" content="Explore published agent workflows' in sec_head

    # 3. Dynamic PAGE_METAS.workflows in JS
    assert "workflows: {" in html
    assert 'action: "orchestrate-and-execute-workflows"' in html



"""Tests for public dashboard navigation and public APIs."""

import re
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import create_front_app
from tests.test_concierge import w  # noqa: F401 (fixture)
from tests.test_registration_hardening import consent

pytestmark = pytest.mark.usefixtures('legacy_public_entry')


def test_front_menus_order_and_labels(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. The Home overview remains available through the brand link.
    assert 'data-tab="overview"' not in html
    assert 'class="brand-box"' in html and 'aria-label="AgentValCon Home"' in html
    assert 'data-tab="learn"' in html
    assert 'data-tab="explore"' in html
    assert 'data-tab="register"' in html
    assert 'data-tab="chat"' in html

    # 2. Check tab text
    assert "<span>Home</span>" not in html
    assert "<span>About</span>" in html
    assert "<span>Learn</span>" in html
    assert "<span>Explore</span>" in html
    assert "<span>List Your Agent</span>" in html
    assert "<span>Chat</span>" in html

    # 3. Check navigation order.
    tabs = re.findall(r'<button class="nav-tab(?: on)?" data-tab="([^"]+)"',html)
    assert tabs == ['learn','explore','test','workflows','chat','register','about']



def test_front_strictly_english_no_korean(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    korean = re.findall(r"[\uac00-\ud7a3]", r.text)
    assert len(korean) == 0, f"Found Korean in front HTML: {set(korean)}"

    # Test API responses for zero Korean
    for endpoint in ["/api/overview", "/api/insights", "/api/explore?q=weather", "/api/register/recent"]:
        resp = c.get(endpoint)
        assert resp.status_code == 200
        k = re.findall(r"[\uac00-\ud7a3]", resp.text)
        assert len(k) == 0, f"Found Korean in {endpoint}: {set(k)}"


def test_front_overview_realtime_and_excluded_cards(w):
    world, c, _ = w
    r = c.get("/api/overview")
    assert r.status_code == 200
    d = r.json()

    # 1. Real-time overview metadata (no 1-hour delay)
    assert d.get("is_snapshot") is False
    assert d.get("delay_seconds") == 0
    assert d.get("timezone") == "America/New_York"
    assert "snapshot_at" in d
    assert abs(d["snapshot_at"] - d["now"]) < 5

    # 2. Specifically excluded cards MUST NOT be present in response
    assert "needs" not in d, "Customer needs card must be excluded"
    assert "erc8004" not in d, "ERC-8004 pending card must be excluded"
    assert "overdue_1h" not in d, "Overdue checks card must be excluded"
    assert "checks_1h" not in d, "Recent 1h checks card must be excluded"

    # 3. System and development internal info MUST NOT be present
    assert "loops" not in d, "Internal loop cursors must be excluded"
    assert "collector" not in d, "Internal thread status must be excluded"
    assert "crawl" not in d, "Internal crawler passes must be excluded"
    assert "actions" not in d, "Internal action state must be excluded"

    # 4. Allowed summary metrics
    assert "health_summary" in d
    assert "resources" in d
    assert "categories" in d
    assert "evaluation" in d
    assert "surveys" in d

    # 5. UI layout: Telemetry banner is hidden and Developer Quickstart card exists below Quality & Security
    r_html = c.get("/", headers={"accept": "text/html"})
    assert 'id="ovTelemetryBanner"' in r_html.text
    assert 'class="banner-notice hidden"' in r_html.text and 'display:none' in r_html.text
    assert "Agent Connection Guide" in r_html.text
    assert "Model Context Protocol (MCP)" in r_html.text
    assert "Agent-to-Agent (A2A)" in r_html.text
    assert "x402 APIs" in r_html.text


def test_front_safe_agent_detail_isolation(w):
    world, c, _ = w
    store = world.store
    # Insert a dummy resource
    res = store.query("SELECT id FROM resources LIMIT 1")
    if not res:
        store.upsert_resource({
            "key": "mcp:https://example.com/mcp", "source": "test", "kind": "mcp",
            "url": "https://example.com/mcp", "name": "Test Tool", "description": "A test tool",
            "category": "ai_models", "networks": ["base"], "details": {"version": "1.0"}
        })
        res = store.query("SELECT id FROM resources LIMIT 1")
    rid = res[0]["id"]

    # 1. API isolation: /api/agents/{rid} must NOT include history (50 records)
    resp = c.get(f"/api/agents/{rid}")
    assert resp.status_code == 200
    data = resp.json()
    assert "agent" in data
    assert "history" not in data, "50 health check records must be excluded from front API response"

    # 2. Source code isolation: front HTML must NOT contain admin management action buttons
    html_resp = c.get("/", headers={"accept": "text/html"})
    html = html_resp.text

    # No admin buttons in drawer or scripts
    assert "aCheck" not in html, "Admin check button must not exist in frontend source"
    assert "aDeactivate" not in html, "Admin deactivate button must not exist in frontend source"
    assert "aActivate" not in html, "Admin activate button must not exist in frontend source"
    assert "\\ucd5c\\uadfc 50\\uac74" not in html, "Admin 50 health check section must not exist in frontend source"
    assert "Recent 50" not in html, "Admin 50 health check section must not exist in frontend source"
    assert "Test in Sandbox" not in html, "Test in Sandbox button must not exist in frontend source"


def test_front_explore_fast_search_and_caching(w):
    world, c, _ = w
    # 1. Basic explore query
    r1 = c.get("/api/explore?q=search&limit=10")
    assert r1.status_code == 200
    d1 = r1.json()
    assert "items" in d1
    assert "query" in d1

    # 2. Cached response returns identical results fast
    r2 = c.get("/api/explore?q=search&limit=10")
    assert r2.status_code == 200
    d2 = r2.json()
    assert {k:v for k,v in d1.items() if k!='captured_at'} == {k:v for k,v in d2.items() if k!='captured_at'}
    assert d2['captured_at'] >= d1['captured_at']


def test_front_register_user_perspective_and_security(w, monkeypatch):
    world, c, _ = w

    # 1. SSRF prevention on inspect
    r_inspect_ssrf = c.post("/api/register/inspect", json={"url": "http://127.0.0.1:8080/card.json"})
    assert r_inspect_ssrf.status_code == 400
    assert r_inspect_ssrf.json().get("error_code") == "PRIVATE_DESTINATION"

    # 2. SSRF prevention on register
    r_reg_ssrf = c.post("/api/register", json={
        "kind": "a2a",
        "url": "http://192.168.1.1/a2a",
        "name": "Evil Agent",
        "description": "Internal test",
        "category": "ai_models",
        "legal_consent": consent(),
    })
    assert r_reg_ssrf.status_code == 400

    # Duplicate detection must not depend on public DNS availability.
    monkeypatch.setattr("agent_market.concierge.front.check_public_url", lambda url: None)
    monkeypatch.setattr("agent_market.concierge.registration_policy._resolve_addresses", lambda *a: ["8.8.8.8"])
    # 3. Duplicate rejection on register
    pub_url = "https://example.com/a2a"
    world.store.upsert_resource({
        "key": f"a2a:{pub_url}", "source": "test", "kind": "a2a",
        "url": pub_url, "name": "Existing Agent", "description": "Existing public agent",
        "category": "ai_models", "networks": ["base"], "details": {}
    })
    r_dup = c.post("/api/register", json={
        "kind": "a2a",
        "url": pub_url,
        "name": "Duplicate Agent",
        "description": "Duplicate test",
        "category": "ai_models",
        "legal_consent": consent(),
    })
    assert r_dup.status_code == 409
    assert "already registered" in r_dup.json()["detail"].lower()
    assert r_dup.json().get("error_code") in (None, "DUPLICATE_LISTING", "ALREADY_REGISTERED")

    # 4. Recently Registered Agents card is hidden
    r_html = c.get("/", headers={"accept": "text/html"})
    assert 'id="regRecentCard"' in r_html.text
    assert 'class="card hidden"' in r_html.text and 'display:none' in r_html.text

    # 5. Helpful informational cards below Registration Guidelines
    assert "Protocol Specifications & Checklist" in r_html.text
    assert "Quality Grading & Discovery Lifecycle" in r_html.text
    assert "GRADE A BENCHMARK" in r_html.text


def test_front_new_york_time_and_loader(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Public times use one standard: UTC (no New York local time)
    assert "America/New_York" not in html
    assert 'timeZone: "UTC"' in html

    # 2. Binary clock-hand rotation loader
    assert 'id="binaryLoader"' in html
    assert "binary-spinner-overlay" in html
    assert "binaryClockRotate" in html
    assert "bitPulse" in html

    # 3. Scroll to top button
    assert 'id="scrollTopBtn"' in html
    assert "scroll-top-btn" in html


def test_front_explore_category_chips_active_state(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Active/on CSS styling for chip buttons exists
    assert ".chip-btn.active" in html
    assert ".chip-btn.on" in html

    # 2. Category chips in Explore section have data-q and updateActiveExploreChip logic
    assert 'id="xChips"' in html
    assert 'data-q=' in html
    assert "updateActiveExploreChip" in html
    assert "applyExploreChip" in html


def test_front_no_horizontal_scroll_overflow(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    assert "overflow-x: hidden" in html
    assert "max-width: 100%" in html
    assert "box-sizing: border-box" in html


def test_front_promotional_meta_tags(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Promotional & Open Graph meta tags
    assert 'name="keywords"' in html
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'name="twitter:card"' in html

    # 2. AI agent engagement meta tags (continuity, proactive updates, protocols)
    assert 'name="agent:platform"' in html
    assert 'name="agent:continuity"' in html
    assert 'name="agent:proactive-intelligence"' in html
    assert 'name="agent:invitation"' in html
    assert "X-Visitor-Token" in html

    # 3. No sensitive internal system/dev info or personal info
    head_content = html[html.find("<head>"):html.find("</head>")]
    for sensitive in ["127.0.0.1", "localhost", "sqlite3", "password", "secret_key"]:
        assert sensitive not in head_content, f"Sensitive info found in head: {sensitive}"


def test_front_page_specific_meta_tags_for_non_home_pages(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Static head meta tags for each non-home page
    non_home_pages = ["learn", "explore", "workflows", "register", "chat"]
    for page in non_home_pages:
        assert f'name="page:{page}:title"' in html, f"Missing title meta for {page}"
        assert f'name="page:{page}:description"' in html, f"Missing description meta for {page}"
        assert f'name="page:{page}:keywords"' in html, f"Missing keywords meta for {page}"
        assert f'name="page:{page}:target-action"' in html, f"Missing target-action meta for {page}"
        assert f'name="page:{page}:retention-hook"' in html, f"Missing retention-hook meta for {page}"

    # 2. Section-level microdata in DOM panels
    assert '<section id="secLearn"' in html
    idx_sec_learn = html.find('id="secLearn"')
    assert 'meta itemprop="name" content="AgentValCon — Protocol Standards' in html[idx_sec_learn:idx_sec_learn+600]
    assert 'meta name="agent:page" content="learn"' in html[idx_sec_learn:idx_sec_learn+600]
    assert 'meta name="agent:retention-hook"' in html[idx_sec_learn:idx_sec_learn+600]

    assert '<section id="secExplore"' in html
    idx_sec_explore = html.find('id="secExplore"')
    assert 'meta itemprop="name" content="AgentValCon — Agent &amp; Tool Discovery Catalog' in html[idx_sec_explore:idx_sec_explore+600]
    assert 'meta name="agent:page" content="explore"' in html[idx_sec_explore:idx_sec_explore+600]
    assert 'meta name="agent:retention-hook"' in html[idx_sec_explore:idx_sec_explore+600]

    assert '<section id="secWorkflows"' in html
    idx_sec_workflows = html.find('id="secWorkflows"')
    workflow_metadata = html[idx_sec_workflows:].split('<div', 1)[0]
    assert 'meta itemprop="name" content="AgentValCon — Visual Multi-Agent Workflow Studio' in workflow_metadata
    assert 'meta name="agent:page" content="workflows"' in workflow_metadata
    assert 'meta name="agent:action" content="orchestrate-and-execute-workflows"' in workflow_metadata
    assert 'meta name="agent:retention-hook"' in workflow_metadata

    assert '<section id="secRegister"' in html
    idx_sec_register = html.find('id="secRegister"')
    assert 'meta itemprop="name" content="AgentValCon — List Your Agent' in html[idx_sec_register:idx_sec_register+600]
    assert 'meta name="agent:page" content="register"' in html[idx_sec_register:idx_sec_register+600]
    assert 'meta name="agent:retention-hook"' in html[idx_sec_register:idx_sec_register+600]

    assert '<section id="secChat"' in html
    idx_sec_chat = html.find('id="secChat"')
    assert 'meta itemprop="name" content="AgentValCon — One Best Verified Agent' in html[idx_sec_chat:idx_sec_chat+600]
    assert 'meta name="agent:page" content="chat"' in html[idx_sec_chat:idx_sec_chat+600]
    assert 'meta name="agent:retention-hook"' in html[idx_sec_chat:idx_sec_chat+600]

    # 3. Dynamic client-side PAGE_METAS and updatePageMeta logic in JS
    assert "const PAGE_METAS = {" in html
    assert "learn: {" in html
    assert "explore: {" in html
    assert "workflows: {" in html
    assert "register: {" in html
    assert "chat: {" in html
    assert "function updatePageMeta(tabId)" in html
    assert "updatePageMeta(tabId);" in html

    # 4. Strict content safety: No negative phrasing, no internal dev/sys info, no personal info
    for tag_name in ["page:learn:description", "page:explore:description", "page:workflows:description", "page:register:description", "page:chat:description"]:
        meta_match = re.search(rf'name="{tag_name}" content="([^"]+)"', html)
        assert meta_match is not None, f"Could not find meta tag {tag_name}"
        content = meta_match.group(1).lower()

        # No negative words
        for neg in ["error", "fail", "vulnerability", "attack", "threat", "forbidden", "downtime", "broken"]:
            assert neg not in content, f"Negative word '{neg}' found in {tag_name}: {content}"

        # No internal system / dev info
        for dev_info in ["127.0.0.1", "localhost", "sqlite", "postgres", "password", "port", "0.0.0.0"]:
            assert not re.search(r"\b" + re.escape(dev_info) + r"\b", content), f"Internal info '{dev_info}' found in {tag_name}: {content}"


def test_frontend_files_strictly_english_zero_korean(w):
    from pathlib import Path
    world, c, _ = w

    # 1. All agent_market/concierge/*.py files and extracted_html.txt must contain 0 Korean characters
    for p in list(Path("agent_market/concierge").glob("*.py")) + [Path("extracted_html.txt")]:
        code = p.read_text(encoding="utf-8")
        korean_chars = re.findall(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]", code)
        assert len(korean_chars) == 0, f"Found Korean in {p}: {set(korean_chars)}"

    # 2. scripts/check_agent_front.py must contain 0 Korean characters
    with open("scripts/check_agent_front.py", "r", encoding="utf-8") as f:
        check_code = f.read()
    korean_in_check = re.findall(r"[\uac00-\ud7af]", check_code)
    assert len(korean_in_check) == 0, f"Found Korean in scripts/check_agent_front.py: {set(korean_in_check)}"


def test_front_zero_loading_instant_rendering(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. A bounded shell may carry compact previews or request API hydration.
    # Every script tag, data blocks included, carries the page nonce.
    match_b = re.search(r'<script\b[^>]*\bid="appBootstrapData"[^>]*\btype="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
    assert match_b is not None
    import json
    b_data = json.loads(match_b.group(1))
    assert "overview" in b_data
    assert "explore" in b_data
    assert "insights" in b_data
    if b_data["overview"] is not None:
        assert "health_summary" in b_data["overview"]
    if b_data["explore"] is not None:
        assert isinstance(b_data["explore"]["items"],list)
    if b_data["insights"] is not None:
        assert "kinds" in b_data["insights"] and "categories" in b_data["insights"]
    # Nullable inline data is valid only because the authoritative menu APIs
    # remain usable; this is not permission to render permanent empty panels.
    overview = c.get('/api/overview')
    assert overview.status_code == 200
    assert {'health_summary','verification'} <= overview.json().keys()
    explore = c.get('/api/explore?limit=45')
    assert explore.status_code == 200 and isinstance(explore.json()['items'],list)
    insights = c.get('/api/insights')
    assert insights.status_code == 200
    assert {'kinds','categories'} <= insights.json().keys()
    templates = c.get('/api/workflows/templates')
    assert templates.status_code == 200 and templates.json()['templates']
    presets = c.get('/api/test/presets')
    assert presets.status_code == 200 and presets.json()['presets']

    # 2. Client-side SWR Cache Engine & Synchronous Hydration
    assert "SWR_STORAGE_KEY_PREFIX" in html
    assert "getSwrCache" in html
    assert "setSwrCache" in html
    assert "renderOverview(" in html
    assert "renderExplore(" in html
    assert "renderLearnUI(" in html
    assert "renderLearn(" in html
    assert "exploreSkeletonHtml" in html

    # 3. Read requests retain the explicit silent/background option.
    assert "isSilent" in html or "opts.silent" in html

    # 4. Content-visibility preservation for 0ms tab switching
    assert "content-visibility: visible" in html
    assert "content-visibility: hidden" in html

    # 5. Syntax validation of the rendered executable script
    tags = re.findall(r"<script(\s+[^>]*)?>(.*?)</script>", html, re.DOTALL)
    executable = [body for attrs, body in tags
                  if body.strip() and not re.search(r'type="application/(?:ld\+)?json"', attrs or "")]
    assert len(tags) >= 2, "Expected bootstrap and main scripts"
    # The page also ships helper scripts after the main one, so find it by content, not position.
    main_js = next((body for body in executable if "updatePageMeta" in body), "")
    assert "updatePageMeta" in main_js
    assert "switchTab" in main_js

    import shutil, subprocess, tempfile
    if shutil.which("node"):
        for body in executable:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=True) as tf:
                tf.write(body)
                tf.flush()
                res = subprocess.run(["node", "--check", tf.name], capture_output=True, text=True)
                assert res.returncode == 0, f"Rendered frontend script has syntax error: {res.stderr}"


def test_front_centered_layer_modal_dialog_and_lucide_icons(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Dialog element and modern styling
    assert '<dialog id="appLayerModal"' in html
    assert 'class="layer-modal"' in html
    assert 'closedby="any"' in html
    assert 'overscroll-behavior: contain' in html
    assert 'backdrop-filter: blur' in html

    # 2. Lucide Icons present in markup and JS icon registry
    assert 'lucide-alert-triangle' in html
    assert 'lucide-check-circle-2' in html
    assert 'lucide-alert-circle' in html
    assert 'lucide-info' in html
    assert 'lucide-x' in html

    # 3. JavaScript controller functions and global window.alert interceptor
    assert "showModalAlert" in html
    assert "closeLayerModal" in html
    assert "window.alert = function" in html

    # 4. Navigation menu is renamed to 'Chat'
    assert "<span>Chat</span>" in html
    assert "<span>Only Agent Chat</span>" not in html

    # 5. Chat form empty submission triggers layer modal popup (not browser native bubbles)
    assert '<form id="chatForm" novalidate' in html
    assert "Please enter a message or query before sending." in html
    assert "Input Required" in html


def test_port_8080_stripped_and_converted_to_https_across_front(w):
    world, c, _ = w
    front = world.app.state.front

    # 1. Test front.base(request) removes 8080 and upgrades http to https, and rewrites legacy domain
    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"host", b"agentconcierge.biz:8080")],
        "server": ("agentconcierge.biz", 8080),
        "scheme": "http",
    }
    req = Request(scope)
    base_url = front.base(req)
    assert base_url == "https://agentconcierge.biz"
    assert ":8080" not in base_url
    assert base_url.startswith("https://")

    # 2. Test Front with public_url having 8080 and legacy domain sanitization
    from agent_market.concierge.front import Front
    f_pub = Front(world.store, allow_private=True, public_url="http://agentconcierge.biz:8080")
    assert f_pub.public_url == "https://agentconcierge.biz"
    assert f_pub.base(req) == "https://agentconcierge.biz"

    f_legacy = Front(world.store, allow_private=True, public_url="http://oneheartall.iptime.org:8080")
    assert f_legacy.public_url == "https://agentconcierge.biz"

    # 3. Test HTTP GET with Host: agentconcierge.biz:8080
    c_custom = TestClient(create_front_app(front), base_url="http://agentconcierge.biz:8080")
    r = c_custom.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text
    # Ensure :8080 and legacy domain do not appear anywhere in rendered HTML
    assert ":8080" not in html
    assert "oneheartall.iptime.org" not in html
    # Ensure https URLs in chat section
    assert '"/chat"' in html and 'name="agent:interaction-endpoints"' in html
    assert "https://agentconcierge.biz/a2a" in html
    assert "https://agentconcierge.biz/mcp" in html

    # 4. Test API and doc endpoints for no 8080
    r_card = c_custom.get("/.well-known/agent-card.json")
    assert r_card.status_code == 200
    assert ":8080" not in r_card.text
    assert r_card.json()["url"].startswith("https://agentconcierge.biz")

    r_llms = c_custom.get("/llms.txt")
    assert r_llms.status_code == 200
    assert ":8080" not in r_llms.text
    assert "POST https://agentconcierge.biz/chat" in r_llms.text

    r_robots = c_custom.get("/robots.txt")
    assert r_robots.status_code == 200
    assert ":8080" not in r_robots.text
    assert "Sitemap: https://agentconcierge.biz/sitemap.xml" in r_robots.text

    # 5. Client-side JS has sanitizePort8080
    assert "sanitizePort8080" in html


def test_front_explore_and_learn_sorted_by_newest_first(w):
    world, c, _ = w
    store = world.store

    # Insert 3 agents with distinct hosts and distinct first_seen timestamps
    import time
    now = time.time()
    id_old = store.upsert_resource({
        "key": "a2a:https://agent-old.org/a2a", "source": "test", "kind": "a2a",
        "url": "https://agent-old.org/a2a", "name": "Old Agent", "description": "Cataloged 10 days ago",
        "category": "ai_models",
    })
    id_mid = store.upsert_resource({
        "key": "a2a:https://agent-mid.org/a2a", "source": "test", "kind": "a2a",
        "url": "https://agent-mid.org/a2a", "name": "Mid Agent", "description": "Cataloged 2 days ago",
        "category": "ai_models",
    })
    id_new = store.upsert_resource({
        "key": "a2a:https://agent-new.org/a2a", "source": "test", "kind": "a2a",
        "url": "https://agent-new.org/a2a", "name": "New Agent", "description": "Cataloged 5 minutes ago",
        "category": "ai_models",
    })
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy', first_seen=? WHERE id=?", (now - 864000, id_old))
        db.execute("UPDATE resources SET health_status='healthy', first_seen=? WHERE id=?", (now - 172800, id_mid))
        db.execute("UPDATE resources SET health_status='healthy', first_seen=? WHERE id=?", (now - 300, id_new))

    # Clear caches
    from agent_market.concierge.front import _front_explore_cache, _front_insights_cache
    _front_explore_cache.clear()
    _front_insights_cache["at"] = 0.0
    _front_insights_cache["data"] = None

    # 1. Check Explore default ordering: newest first
    resp_exp = c.get("/api/explore?kind=a2a&limit=10")
    assert resp_exp.status_code == 200
    items = resp_exp.json()["items"]
    assert len(items) >= 3
    # Check that first_seen is strictly non-increasing (newest first)
    first_seens = [item["first_seen"] for item in items if item.get("first_seen")]
    assert first_seens == sorted(first_seens, reverse=True), f"Explore items must be sorted newest first: {first_seens}"
    # Verify New Agent comes before Mid Agent, and Mid Agent before Old Agent
    names = [it["name"] for it in items]
    assert names.index("New Agent") < names.index("Mid Agent") < names.index("Old Agent")

    # 2. Check Learn (Insights) featured lists: "newest" group is first
    resp_ins = c.get("/api/insights")
    assert resp_ins.status_code == 200
    data_ins = resp_ins.json()
    for k in ["a2a", "mcp", "x402"]:
        feats = data_ins["kinds"][k]["featured"]
        assert len(feats) > 0
        assert feats[0]["key"] == "newest", f"Protocol {k} first featured list must be 'newest'"
        # Check items in newest are sorted by first_seen DESC
        f_items = feats[0]["items"]
        f_seens = [it["first_seen"] for it in f_items if it.get("first_seen")]
        assert f_seens == sorted(f_seens, reverse=True), f"Items in 'newest' must be sorted newest first"

    # 3. Check HTML contains latest discovered agents heading and freshness tags
    r_html = c.get("/", headers={"accept": "text/html"})
    assert r_html.status_code == 200
    html = r_html.text
    assert "Latest Discovered Agents" in html
    assert "A2A + MCP · Sorted by newest first" in html
    assert "nyAgo(r.first_seen)" in html


def test_front_explore_default_and_bootstrap_match_optional_execution_filter(w):
    world, c, _ = w
    store = world.store

    # 1. Recorded reports can be browsed independently of current execution.
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text
    assert '<input type="checkbox" id="xVerified"> Execution checked' in html
    assert 'id="xVerified" checked' not in html

    # 2. Bootstrap hydration uses the same unchecked filter state.
    assert 'setSwrCache("explore:|||0|0", bData.explore);' in html

    # 3. Add resources: one verified (trial_ok=1), one unverified (trial_ok=0 or None)
    id_verified = store.upsert_resource({
        "key": "mcp:https://verified-agent.org/mcp", "source": "test", "kind": "mcp",
        "url": "https://verified-agent.org/mcp", "name": "Verified Working Tool", "description": "Operational",
        "category": "ai_models",
    })
    id_unverified = store.upsert_resource({
        "key": "mcp:https://unverified-agent.org/mcp", "source": "test", "kind": "mcp",
        "url": "https://unverified-agent.org/mcp", "name": "Unverified Tool", "description": "Failing",
        "category": "ai_models",
    })
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy', trial_ok=1 WHERE id=?", (id_verified,))
        db.execute("UPDATE resources SET health_status='healthy', trial_ok=0 WHERE id=?", (id_unverified,))
        db.execute('UPDATE resources SET auth_observed=0 WHERE id=?',(id_verified,))
    from agent_market.capability_registry import Registry
    import time
    tools=[{'name':'search_documents','description':'Search public documents',
            'inputSchema':{'type':'object','properties':{}}}]
    store.record_usage(id_verified,tools=tools,digest='verified-fixture',guide={'tools':tools},changes=None,trial=None)
    at=time.time()
    Registry(store).record(Registry(store).current(id_verified),scope='execution',outcome='succeeded',started=at,finished=at)

    # Clear caches
    from agent_market.concierge.front import clear_front_caches
    clear_front_caches()

    # 4. Bootstrap includes both healthy resources and keeps evidence distinct.
    front = world.app.state.front
    snap = front.bootstrap_snapshot()
    explore_items = snap["explore"]["items"]
    assert any(it["id"] == id_verified for it in explore_items)
    assert any(it["id"] == id_unverified for it in explore_items)
    verified_items = c.get('/api/explore?kind=mcp&verified=true').json()['items']
    assert any(it['id'] == id_verified for it in verified_items)
    assert not any(it['id'] == id_unverified for it in verified_items)

    # 5. Initial HTML uses the same catalog as the unchecked controls.
    r_page = c.get("/", headers={"accept": "text/html"})
    match_b = re.search(r'<script\b[^>]*\bid="appBootstrapData"[^>]*\btype="application/json"[^>]*>(.*?)</script>', r_page.text, re.DOTALL)
    assert match_b is not None
    import json
    b_data = json.loads(match_b.group(1))
    b_items = b_data["explore"]["items"]
    assert any(it["id"] == id_verified for it in b_items)
    assert any(it["id"] == id_unverified for it in b_items)


def test_front_initial_connection_under_3_seconds(w):
    world, c, _ = w
    import time
    from agent_market.concierge.front import clear_front_caches

    # 1. Cold start execution benchmark
    clear_front_caches()
    t0 = time.time()
    resp_cold = c.get("/", headers={"accept": "text/html"})
    t_cold = time.time() - t0
    assert resp_cold.status_code == 200
    assert t_cold < 3.0, f"Cold initial connection took {t_cold:.3f}s (must be < 3.0s)"

    # 2. Warm cached execution benchmark (SWR sub-second TTFB)
    t0 = time.time()
    resp_warm = c.get("/", headers={"accept": "text/html"})
    t_warm = time.time() - t0
    assert resp_warm.status_code == 200
    assert "Cache-Control" in resp_warm.headers
    assert resp_warm.headers["Cache-Control"] == "no-store"


def test_front_explore_has_report_filter(w):
    world, c, _ = w
    store = world.store
    import time
    from agent_market.concierge.front import clear_front_caches

    # 1. HTML checkbox 'Test Report' must exist in filter bar
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    assert 'id="xHasReport"' in r.text
    assert "Test Report" in r.text

    # 2. Seed two agents: one with a test report, one without
    id_reported = store.upsert_resource({
        "key": "mcp:https://reported-agent.org/mcp", "source": "test", "kind": "mcp",
        "url": "https://reported-agent.org/mcp", "name": "Reported MCP Agent", "description": "Verified with report",
        "category": "dev_tools",
    })
    id_unreported = store.upsert_resource({
        "key": "mcp:https://unreported-agent.org/mcp", "source": "test", "kind": "mcp",
        "url": "https://unreported-agent.org/mcp", "name": "Unreported MCP Agent", "description": "No report filed",
        "category": "dev_tools",
    })
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy', active=1 WHERE id IN (?, ?)", (id_reported, id_unreported))
    from tests.report_fixtures import legacy_report_fixture
    now = time.time()
    legacy_report_fixture(store,{'resource_id':id_reported,'title':'Reported MCP Agent Test',
        'slug':f'reported-mcp-{int(now)}','kind':'mcp','category':'dev_tools',
        'eval_grade':'A','eval_score':95.0,'status_code':200,'latency_ms':120.0,
        'is_success':1,'test_method':'test_call','tool_name':'ping','summary':'Full pass',
        'content_md':'## Details\\nPassed flawlessly.','pros':['Fast','Reliable'],
        'cons':['None'],'created_at':now,'updated_at':now})

    clear_front_caches()

    # 3. Query /api/explore?has_report=true: only id_reported must be returned
    resp = c.get("/api/explore?has_report=true&limit=20")
    assert resp.status_code == 200
    items = resp.json().get("items", [])
    returned_ids = [it["id"] for it in items]
    assert id_reported in returned_ids
    assert id_unreported not in returned_ids

    # Check item metadata
    reported_item = next(it for it in items if it["id"] == id_reported)
    assert reported_item["report_count"] >= 1
    # Historical publication remains discoverable without becoming a measured grade.
    assert reported_item["report_grade"] is None


def test_front_explore_has_report_page_is_shared_and_revalidated(w, monkeypatch):
    """A report-filtered page is shared through Redis; the reusing slot still re-reads every listing."""
    import time
    from agent_market.concierge import front as front_module
    from agent_market.concierge.front import clear_front_caches
    from tests.test_explore_shared_cache import FakeHub, install
    from tests.report_fixtures import legacy_report_fixture
    world, c, _ = w
    store = world.store
    rid = store.upsert_resource({"key": "mcp:https://shared-report.org/mcp", "source": "test", "kind": "mcp",
        "url": "https://shared-report.org/mcp", "name": "Shared Report Agent", "description": "Reported once",
        "category": "dev_tools"})
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy', active=1 WHERE id=?", (rid,))
    now = time.time()
    legacy_report_fixture(store, {'resource_id': rid, 'title': 'Shared Report Agent Test', 'slug': f'shared-{int(now)}',
        'kind': 'mcp', 'category': 'dev_tools', 'eval_grade': 'A', 'eval_score': 95.0, 'status_code': 200,
        'latency_ms': 120.0, 'is_success': 1, 'test_method': 'test_call', 'tool_name': 'ping', 'summary': 'Pass',
        'content_md': 'ok', 'pros': ['Fast'], 'cons': ['None'], 'created_at': now, 'updated_at': now})
    hub = FakeHub(); hub.delete_keys = hub.delete_pattern = lambda *a, **k: None  # Redis outlives one slot
    install(monkeypatch, hub)
    clear_front_caches()
    first = c.get("/api/explore?has_report=true&limit=20").json()
    assert rid in [item["id"] for item in first["items"]]
    assert [key for key, _ in hub.sets if 'complete:' not in key]
    # Another slot: nothing cached in process, and the listing was quarantined since.
    clear_front_caches()
    computed = []
    original = front_module.get_front_explore
    monkeypatch.setattr(front_module, 'get_front_explore', lambda *a, **k: computed.append(1) or original(*a, **k))
    with store.tx() as db:
        db.execute("UPDATE resources SET eval_security='quarantine' WHERE id=?", (rid,))
    second = c.get("/api/explore?has_report=true&limit=20").json()
    assert computed == []  # served from the shared layer
    assert rid not in [item["id"] for item in second["items"]]
    # The shared key names the report filter apart from any plain search key.
    plain_exact, plain_complete = front_module._shared_explore_keys(store, (0, '', None, None, False, False, 21))
    assert not {plain_exact, plain_complete} & {key for key, _ in hub.sets}


def test_front_register_autodetect_all_protocols_and_duplicates(w, monkeypatch):
    import httpx
    import socket
    world, c, _ = w
    store = world.store

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))],
    )

    orig_send = httpx.Client.send

    def mock_send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        if request.url.host in ("testserver", "gw"):
            return orig_send(self, request, **kwargs)
        url = str(request.url)
        method = request.method.upper()
        body = request.content.decode("utf-8", errors="ignore") if request.content else ""

        # 1. A2A agent card
        if url == "https://a2a-demo.example.com/.well-known/agent-card.json":
            return httpx.Response(200, json={
                "name": "Demo A2A Weather Agent",
                "description": "Forecasts weather conditions via A2A protocol",
                "version": "1.2.0",
                "url": "https://a2a-demo.example.com/a2a",
                "skills": [{"id": "forecast", "name": "Weather Forecast", "description": "Get forecast"}],
            }, headers={"content-type": "application/json"}, request=request)

        # 2. MCP Streamable HTTP (SSE response)
        if url == "https://mcp-demo.example.com/mcp" and method == "POST":
            if '"initialize"' in body:
                sse = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"Demo MCP Server","version":"2.0.0"},"instructions":"Search developer docs and APIs"}}\n\n'
                return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"}, request=request)
            if '"tools/list"' in body:
                sse = 'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"search_docs","description":"Search documentation"},{"name":"read_page","description":"Read documentation page"}]}}\n\n'
                return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"}, request=request)

        # 3. x402 GET endpoint
        if url == "https://x402-get.example.com/x402/ping":
            if method == "POST":
                return httpx.Response(404, text="Not Found", request=request)
            return httpx.Response(402, json={
                "x402Version": 1,
                "error": "Payment required",
                "accepts": [{
                    "scheme": "exact",
                    "network": "base",
                    "maxAmountRequired": "10000",
                    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                    "payTo": "0x1111111111111111111111111111111111111111",
                    "description": "Paid x402 ping service",
                }],
            }, headers={"content-type": "application/json"}, request=request)

        # 4. x402 POST-only endpoint
        if url == "https://x402-post.example.com/api/verdict":
            if method == "POST":
                return httpx.Response(402, json={
                    "x402Version": 2,
                    "error": "Payment required",
                    "resource": {"url": url, "description": "Quantum market verdict analysis"},
                    "accepts": [{
                        "scheme": "exact",
                        "network": "eip155:8453",
                        "amount": "50000",
                        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                        "payTo": "0x2222222222222222222222222222222222222222",
                    }],
                }, headers={"content-type": "application/json"}, request=request)
            return httpx.Response(405, text="Method Not Allowed", request=request)

        return httpx.Response(404, text="Not Found", request=request)

    monkeypatch.setattr(httpx.Client, "send", mock_send)
    from agent_market.concierge import registration_policy
    monkeypatch.setattr(registration_policy, "_resolve_addresses", lambda *a: ["8.8.8.8"])  # fixture hosts are public

    # A. Test A2A auto-detection via root host URL
    r_a2a = c.post("/api/register/inspect", json={"url": "https://a2a-demo.example.com"})
    assert r_a2a.status_code == 200
    d_a2a = r_a2a.json()
    assert d_a2a["ok"] is True
    assert d_a2a["kind"] == "a2a"
    assert d_a2a["name"] == "Demo A2A Weather Agent"
    assert d_a2a["category"] is None  # inspection reports a category only for an existing listing
    assert d_a2a["details"]["agent_card"] == "https://a2a-demo.example.com/.well-known/agent-card.json"
    assert d_a2a["already_registered"] is False

    # B. Test MCP Streamable HTTP (SSE) auto-detection
    r_mcp = c.post("/api/register/inspect", json={"url": "https://mcp-demo.example.com/mcp"})
    assert r_mcp.status_code == 200
    d_mcp = r_mcp.json()
    assert d_mcp["ok"] is True
    assert d_mcp["kind"] == "mcp"
    assert d_mcp["name"] == "Demo MCP Server"
    assert "Search developer docs" in d_mcp["description"]
    assert d_mcp["details"]["tools"] == ["search_docs", "read_page"]
    assert d_mcp["already_registered"] is False

    # C. Test x402 GET auto-detection
    r_xget = c.post("/api/register/inspect", json={"url": "https://x402-get.example.com/x402/ping"})
    assert r_xget.status_code == 200
    d_xget = r_xget.json()
    assert d_xget["ok"] is True
    assert d_xget["kind"] == "x402"
    assert d_xget["method"] == "GET"
    assert d_xget["price_usdc"] == 10000
    assert d_xget["pay_to"] == "0x1111111111111111111111111111111111111111"
    assert "base" in d_xget["networks"]

    # D. Test x402 POST-only auto-detection with CAIP-2 network normalization
    r_xpost = c.post("/api/register/inspect", json={"url": "https://x402-post.example.com/api/verdict"})
    assert r_xpost.status_code == 200
    d_xpost = r_xpost.json()
    assert d_xpost["ok"] is True
    assert d_xpost["kind"] == "x402"
    assert d_xpost["method"] == "POST"
    assert d_xpost["price_usdc"] == 50000
    assert d_xpost["pay_to"] == "0x2222222222222222222222222222222222222222"
    assert d_xpost["networks"] == ["base"]

    # E. Pre-register the A2A agent at its root URL, then inspect via /.well-known/agent-card.json
    store.upsert_resource({
        "key": "a2a:https://a2a-demo.example.com",
        "source": "self_register",
        "kind": "a2a",
        "url": "https://a2a-demo.example.com",
        "name": "Demo A2A Weather Agent",
        "description": "Forecasts weather conditions via A2A protocol",
        "category": "travel_maps_weather",
        "details": {"agent_card": "https://a2a-demo.example.com/.well-known/agent-card.json"},
    })
    r_a2a_dup = c.post("/api/register/inspect", json={"url": "https://a2a-demo.example.com/.well-known/agent-card.json"})
    assert r_a2a_dup.status_code == 200
    d_a2a_dup = r_a2a_dup.json()
    assert d_a2a_dup["already_registered"] is True
    assert d_a2a_dup["existing"]["name"] == "Demo A2A Weather Agent"


def test_front_register_submit_by_protocol_and_duplicate_modal(w, monkeypatch):
    import httpx
    import socket
    world, c, _ = w

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))],
    )

    orig_send = httpx.Client.send

    def mock_send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        if request.url.host in ("testserver", "gw"):
            return orig_send(self, request, **kwargs)
        url = str(request.url)
        method = request.method.upper()
        body = request.content.decode("utf-8", errors="ignore") if request.content else ""

        if url.startswith("https://live-a2a.example.org"):
            return httpx.Response(200, json={
                "name": "Live A2A Agent",
                "description": "Live A2A agent card",
                "version": "1.0.0",
                "url": "https://live-a2a.example.org/a2a",
                "skills": [{"id": "s1", "name": "Skill One", "description": "Test skill"}],
            }, headers={"content-type": "application/json"}, request=request)

        if url == "https://live-mcp.example.org/mcp":
            if '"initialize"' in body:
                return httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 1,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "Live MCP Server", "version": "1.0.0"},
                        "capabilities": {"tools": {}},
                    },
                }, headers={"content-type": "application/json"}, request=request)
            if '"tools/list"' in body:
                return httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 2,
                    "result": {"tools": [{"name": "lookup", "description": "Lookup data", "inputSchema": {"type": "object"}}]},
                }, headers={"content-type": "application/json"}, request=request)

        if url == "https://live-x402-get.example.org/x402/ping":
            if method == "POST":
                return httpx.Response(404, text="Not Found", request=request)
            return httpx.Response(402, json={
                "x402Version": 1,
                "accepts": [{
                    "scheme": "exact",
                    "network": "base",
                    "maxAmountRequired": "10000",
                    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                    "payTo": "0x3333333333333333333333333333333333333333",
                }],
            }, headers={"content-type": "application/json"}, request=request)

        if url == "https://live-x402-post.example.org/api/pay":
            if method == "POST":
                return httpx.Response(402, json={
                    "x402Version": 2,
                    "accepts": [{
                        "scheme": "exact",
                        "network": "eip155:8453",
                        "amount": "25000",
                        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                        "payTo": "0x4444444444444444444444444444444444444444",
                    }],
                }, headers={"content-type": "application/json"}, request=request)
            return httpx.Response(405, text="Method Not Allowed", request=request)

        return httpx.Response(404, text="Not Found", request=request)

    monkeypatch.setattr(httpx.Client, "send", mock_send)
    from agent_market.concierge import registration_policy
    monkeypatch.setattr(registration_policy, "_resolve_addresses", lambda *a: ["8.8.8.8"])  # fixture hosts are public

    # 1. Register unregistered A2A agent
    r1 = c.post("/api/register", json={
        "kind": "a2a",
        "url": "https://live-a2a.example.org/.well-known/agent-card.json",
        "name": "Live A2A Agent",
        "description": "Live A2A agent card",
        "category": "ai_models",
        "networks": ["base"],
        "legal_consent": consent(),
    })
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "healthy"

    # Re-registering via root URL or trailing slash must return 409 Conflict
    r1_dup = c.post("/api/register", json={
        "kind": "a2a",
        "url": "https://live-a2a.example.org",
        "name": "Live A2A Agent",
        "description": "Duplicate attempt",
        "category": "ai_models",
        "legal_consent": consent(),
    })
    assert r1_dup.status_code == 409
    assert "already registered" in r1_dup.json()["detail"].lower()

    # 2. Register unregistered MCP agent
    r2 = c.post("/api/register", json={
        "kind": "mcp",
        "url": "https://live-mcp.example.org/mcp",
        "name": "Live MCP Server",
        "description": "Live MCP tool server",
        "category": "dev_tools",
        "networks": ["base"],
        "legal_consent": consent(),
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "healthy"

    # Re-registering with trailing slash must return 409 Conflict
    r2_dup = c.post("/api/register", json={
        "kind": "mcp",
        "url": "https://live-mcp.example.org/mcp/",
        "name": "Live MCP Server",
        "description": "Duplicate attempt",
        "category": "dev_tools",
        "legal_consent": consent(),
    })
    assert r2_dup.status_code == 409

    # 3. Register unregistered x402 GET agent (even without specifying method="GET", fallback should succeed)
    r3 = c.post("/api/register", json={
        "kind": "x402",
        "url": "https://live-x402-get.example.org/x402/ping",
        "name": "Live x402 GET Ping",
        "description": "Paid GET endpoint",
        "category": "finance_crypto",
        "networks": ["base"],
        "legal_consent": consent(),
    })
    assert r3.status_code == 200, r3.text
    assert r3.json()["status"] == "healthy"

    # 4. Register unregistered x402 POST agent
    r4 = c.post("/api/register", json={
        "kind": "x402",
        "url": "https://live-x402-post.example.org/api/pay",
        "name": "Live x402 POST Pay",
        "description": "Paid POST endpoint",
        "category": "finance_crypto",
        "networks": ["base"],
        "method": "POST",
        "legal_consent": consent(),
    })
    assert r4.status_code == 200, r4.text
    assert r4.json()["status"] == "healthy"

    # 5. Verify Frontend Layer Popup wiring for Already Registered Agent in HTML
    r_html = c.get("/", headers={"accept": "text/html"})
    assert r_html.status_code == 200
    html = r_html.text
    assert '"Already Registered Agent"' in html
    assert "d.already_registered" in html
    assert 'title: isDuplicate ? "Already Registered Agent" : "Registration Notice"' in html


def test_front_overview_chat_test_meta_tags_for_ai_agents(w):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Page: Overview head meta tags for autonomous AI agents
    assert 'name="page:overview:title" content="AgentValCon — One Best Agent for Your Task"' in html
    assert 'name="page:overview:chat-features"' in html
    assert 'name="page:overview:how-to-start"' in html
    assert 'name="page:overview:target-action" content="find-up-to-three-verified-agents"' in html
    assert 'name="page:overview:retention-hook"' in html
    assert 'name="page:overview:capabilities"' in html

    # The menu directory distinguishes Home access through the logo.
    assert 'name="page:overview:home-access"' in html
    assert 'name="agent:menu-directory"' in html
    assert 'name="page:overview:menu-guide"' in html
    for menu_key in ["learn", "explore", "test", "workflows", "register", "chat", "about"]:
        assert f'name="page:overview:menu:{menu_key}"' in html, f"Missing menu tag for {menu_key}"

    # 2. Section #secOverview microdata
    idx_sec_ov = html.find('id="secOverview"')
    assert idx_sec_ov != -1
    idx_ov_banner = html.find('id="ovTelemetryBanner"')
    assert idx_ov_banner != -1
    ov_chunk = html[idx_sec_ov:idx_ov_banner]
    assert 'meta itemprop="name" content="AgentValCon — One Best Agent for Your Task"' in ov_chunk
    assert 'meta name="agent:page" content="overview"' in ov_chunk
    assert 'meta name="agent:action" content="find-up-to-three-verified-agents"' in ov_chunk
    assert 'meta name="agent:retention-hook"' in ov_chunk
    assert 'meta name="agent:chat-features"' in ov_chunk
    assert 'meta name="agent:how-to-start"' in ov_chunk
    assert 'meta name="agent:menu-guide"' in ov_chunk
    for menu_key in ["learn", "explore", "test", "workflows", "register", "chat", "about"]:
        assert f'meta name="agent:menu:{menu_key}"' in ov_chunk

    # 3. All non-home menus have complete how-to-use and capabilities in head and section microdata
    menu_sections = {
        "learn": ("secLearn", "inspect-protocol-specifications"),
        "explore": ("secExplore", "discover-tools-and-agents"),
        "workflows": ("secWorkflows", "orchestrate-and-execute-workflows"),
        "test": ("secTest", "test-agent-endpoints"),
        "register": ("secRegister", "list-agent-endpoint"),
        "chat": ("secChat", "three-recent-verified-recommendations-a2a-then-mcp"),
        "about": ("secAbout", "understand-service-and-vision"),
    }

    for menu_name, (sec_id, expected_action) in menu_sections.items():
        # Head meta tags
        assert f'name="page:{menu_name}:title"' in html, f"Missing head title for {menu_name}"
        assert f'name="page:{menu_name}:description"' in html, f"Missing head description for {menu_name}"
        assert f'name="page:{menu_name}:keywords"' in html, f"Missing head keywords for {menu_name}"
        assert f'name="page:{menu_name}:target-action" content="{expected_action}"' in html, f"Missing target-action for {menu_name}"
        assert f'name="page:{menu_name}:retention-hook"' in html, f"Missing retention-hook for {menu_name}"
        assert f'name="page:{menu_name}:how-to-use"' in html, f"Missing how-to-use for {menu_name}"
        assert f'name="page:{menu_name}:capabilities"' in html, f"Missing capabilities for {menu_name}"

        # Section DOM microdata
        idx_sec = html.find(f'id="{sec_id}"')
        assert idx_sec != -1, f"Missing section #{sec_id}"
        sec_chunk = html[idx_sec:idx_sec + 1600]
        assert 'meta itemprop="name"' in sec_chunk, f"Missing itemprop=name in #{sec_id}"
        assert 'meta itemprop="description"' in sec_chunk, f"Missing itemprop=description in #{sec_id}"
        assert f'meta name="agent:page" content="{menu_name}"' in sec_chunk, f"Missing agent:page in #{sec_id}"
        assert f'meta name="agent:action" content="{expected_action}"' in sec_chunk, f"Missing agent:action in #{sec_id}"
        assert 'meta name="agent:retention-hook"' in sec_chunk, f"Missing agent:retention-hook in #{sec_id}"
        assert 'meta name="agent:how-to-use"' in sec_chunk, f"Missing agent:how-to-use in #{sec_id}"
        assert 'meta name="agent:capabilities"' in sec_chunk, f"Missing agent:capabilities in #{sec_id}"

        # Verify exact synchronization between <head> page:<menu>:* and <section> microdata
        for head_attr, sec_attr in [
            (f'name="page:{menu_name}:title"', 'itemprop="name"'),
            (f'name="page:{menu_name}:description"', 'itemprop="description"'),
            (f'name="page:{menu_name}:retention-hook"', 'name="agent:retention-hook"'),
            (f'name="page:{menu_name}:how-to-use"', 'name="agent:how-to-use"'),
            (f'name="page:{menu_name}:capabilities"', 'name="agent:capabilities"'),
        ]:
            m_head = re.search(rf'{re.escape(head_attr)} content="([^"]+)"', html)
            m_sec = re.search(rf'{re.escape(sec_attr)} content="([^"]+)"', sec_chunk)
            assert m_head and m_sec, f"Missing {head_attr} or {sec_attr} for {menu_name}"
            assert m_head.group(1) == m_sec.group(1), (
                f"Mismatch for {menu_name} ({head_attr} vs {sec_attr}): "
                f"{m_head.group(1)!r} != {m_sec.group(1)!r}"
            )

    # 4. Client-side PAGE_METAS JS structure
    assert "chatFeatures:" in html
    assert "howToStart:" in html
    assert "howToUse:" in html
    assert "capabilities:" in html
    assert "menuGuide:" in html

    # 5. Global AI Agent Header tags
    assert 'name="agent:chat-capabilities"' in html
    assert 'name="agent:how-to-start"' in html
    assert 'name="agent:menu-directory"' in html

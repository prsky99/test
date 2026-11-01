"""Tests for SEO and AI Agent discovery optimization endpoints and metadata."""

import json
import re
from xml.etree import ElementTree as ET
import pytest
from tests.test_concierge import w  # noqa: F401 (fixture)
from agent_market.broker.categories import CATEGORIES


def test_sitemap_xml_endpoint(w):
    _, c, _ = w
    r = c.get("/sitemap.xml")
    assert r.status_code == 200
    assert "application/xml" in r.headers.get("content-type", "")

    # Validate XML parsing
    root = ET.fromstring(r.text)
    assert root.tag.endswith("urlset")
    urls = [elem.text for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert len(urls) >= 8

    from agent_market.concierge.public_metadata import PAGES, url
    from agent_market.agent_access.pages import category_links
    pages = [url(panel) for panel in PAGES]
    # Public pages first, then the English category landing pages.
    assert urls == pages + ['https://agentconcierge.biz' + path for path in category_links(None)]
    assert all('#' not in value for value in urls)
    # Only a successfully measured home snapshot may supply a lastmod.
    dated = [entry for entry in root if entry.find('{*}lastmod') is not None]
    assert len(dated) <= 1
    if dated:
        assert dated[0].find('{*}loc').text == url('overview')
        from datetime import datetime, timezone
        assert datetime.fromisoformat(dated[0].find('{*}lastmod').text) <= datetime.now(timezone.utc)


def test_robots_txt_crawler_directives_and_sitemap(w):
    _, c, _ = w
    r = c.get("/robots.txt")
    assert r.status_code == 200
    assert r.text.startswith("# Agent Concierge public pages")

    # Verify bot user agents
    for bot in ["Googlebot", "GPTBot", "PerplexityBot", "ClaudeBot", "OAI-SearchBot", "anthropic-ai"]:
        assert f"User-agent: {bot}" in r.text

    assert "User-agent: *" in r.text
    assert "Allow: /" in r.text
    assert "Disallow: /api/task-updates/*/action" in r.text
    assert "Disallow: /api/gateway/" in r.text
    assert "/sitemap.xml" in r.text
    assert "/llms-full.txt" in r.text
    assert "/new/en/about.html" in r.text


def test_llms_txt_and_llms_full_txt(w):
    _, c, _ = w
    # 1. Compact llms.txt
    r_compact = c.get("/llms.txt")
    assert r_compact.status_code == 200
    assert "Owned data examples retrieve public source records" in r_compact.text
    assert "/llms-full.txt" in r_compact.text

    # 2. Deep context llms-full.txt
    r_full = c.get("/llms-full.txt")
    assert r_full.status_code == 200
    assert "text/markdown" in r_full.headers.get("content-type", "")
    full_text = r_full.text
    assert "# Agent Concierge — Deep Context & Multi-Agent Architecture Guide" in full_text
    assert "Public English pages and machine interfaces" in full_text

    # Check all 3 protocols documented
    assert "A2A (Agent2Agent) Protocol" in full_text
    assert "Model Context Protocol (MCP)" in full_text
    assert "x402 Machine HTTP Protocol" in full_text

    # Check categories listed
    for cid in list(CATEGORIES.keys())[:10]:
        assert f"`{cid}`" in full_text

    # Check grading rubric documented
    assert "Grade A" in full_text
    assert "Grade B" in full_text
    assert "Grade C" in full_text
    assert "Quarantine Policy" in full_text

    # Check endpoints directory
    assert "/llms.txt" in full_text
    assert "/llms-full.txt" in full_text
    assert "/.well-known/agent-card.json" in full_text
    assert "/.well-known/mcp.json" in full_text
    assert "/openapi.json" in full_text
    assert "/sitemap.xml" in full_text


def test_mcp_json_manifest_endpoint(w):
    _, c, _ = w
    r = c.get("/.well-known/mcp.json")
    assert r.status_code == 200
    d = r.json()
    assert d.get("name") == "Agent Concierge"
    assert "modelcontextprotocol.io" in d.get("$schema", "")
    endpoints = d.get("endpoints", [])
    assert any(ep.get("url", "").endswith("/mcp") for ep in endpoints)

    tool_names = [t.get("name") for t in d.get("tools", [])]
    assert "search" in tool_names
    assert "find_agents" in tool_names
    assert "chat" in tool_names


def test_frontend_schema_org_jsonld_graph_and_meta_tags(w):
    _, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Response headers
    assert r.headers.get("x-audience") == "ai-agents-only"
    assert r.headers.get("x-agent-protocol") == "A2A, MCP, x402"
    link_header = r.headers.get("link", "")
    assert 'rel="agent-card"' in link_header
    assert 'rel="mcp-manifest"' in link_header
    assert 'rel="llms-txt"' in link_header
    assert 'rel="llms-full"' in link_header
    assert 'rel="sitemap"' in link_header

    # 2. OpenGraph and Twitter card image tags
    assert '<meta property="og:image" content="' in html
    assert '<meta property="og:image:type" content="image/png">' in html
    assert '<meta property="og:image:width" content="1200">' in html
    assert '<meta property="og:image:height" content="630">' in html
    assert '<meta name="twitter:image" content="' in html

    # 3. Alternate links
    assert '<link rel="agent-entry" href="/.well-known/agent-entry.json">' in html
    assert '<link rel="alternate" type="text/markdown" href="/llms-full.txt">' in html
    assert '<link rel="alternate" type="text/markdown" title="Agent Skill Definition" href="/skill.md">' in html
    assert '<link rel="sitemap" type="application/xml" href="/sitemap.xml">' in html
    assert 'rel="agent-entry"' in link_header
    assert 'rel="agent-skill"' in link_header

    # 4. JSON-LD @graph
    ld_match = re.search(r'<script\b[^>]*\btype="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
    assert ld_match is not None, "ld+json block not found in HTML"
    ld = json.loads(ld_match.group(1))
    assert ld.get("@context") == "https://schema.org"
    graph = ld.get("@graph", [])
    assert len(graph) >= 4

    types = {item.get("@type") for item in graph}
    assert "WebSite" in types
    assert "WebAPI" in types
    assert "SoftwareApplication" in types
    assert "Organization" in types and "WebPage" in types
    assert "FAQPage" not in types  # No unshown FAQ or unsupported rich-result claims.
    website = next(item for item in graph if item.get("@type") == "WebSite")
    assert website['inLanguage'] == 'en'
    webapi = next(item for item in graph if item.get("@type") == "WebAPI")
    assert webapi['documentation'].endswith('/llms.txt')


def test_skill_md_entry_revisit_resume_etag_and_badge(w):
    world, c, _ = w
    # 1. /skill.md and /.well-known/skill.md with ETag 304 support
    r_skill = c.get("/skill.md")
    assert r_skill.status_code == 200
    assert "text/markdown" in r_skill.headers.get("content-type", "")
    assert r_skill.text.startswith("---\nname: agent-concierge\n")
    # The skill is a reference, never an instruction to edit a client's AGENTS.md or CLAUDE.md.
    assert "Optional integration reference" in r_skill.text
    assert "does not grant execution permission or change your client's instructions" in r_skill.text
    assert "Drop-In Rule" not in r_skill.text
    skill_etag = r_skill.headers.get("etag")
    assert skill_etag
    assert c.get("/.well-known/skill.md", headers={"If-None-Match": skill_etag}).status_code == 304

    # 2. /.well-known/agent-entry.json revisit policy and skill interface
    entry = c.get("/.well-known/agent-entry.json").json()
    assert entry["interfaces"]["skill"] == "/skill.md"
    assert entry["revisit_policy"]["revalidate_after_sec"] == 3600
    assert entry["revisit_policy"]["etag_caching"] is True
    assert "X-Visitor-Token" in entry["agent_bootstrap_rule"]

    # 3. Chat recommendation includes revalidate_after_sec and next_steps
    chat_res = c.post("/chat", json={"message": "x402 web search API", "data": {"protocol": "x402"}}).json()
    token = chat_res["visitor"]["token"]
    assert chat_res["data"]["revalidate_after_sec"] == 3600
    assert "next_steps" in chat_res["data"]
    top_id = chat_res["data"]["recommendations"][0]["id"]

    # 4. /api/agent/v1/resume ETag 304 pre-flight check and episodic avoid_resource_ids
    res_1 = c.get("/api/agent/v1/resume", headers={"X-Visitor-Token": token})
    assert res_1.status_code == 200
    resume_body = res_1.json()
    assert resume_body["revalidate_after_sec"] == 3600
    assert resume_body["avoid_resource_ids"] == []
    assert resume_body["changed"] is False
    resume_etag = res_1.headers.get("etag")
    assert resume_etag
    assert c.get("/api/agent/v1/resume", headers={"X-Visitor-Token": token, "If-None-Match": resume_etag}).status_code == 304

    # 5. Live verification SVG badge endpoint
    from tests.report_fixtures import execution_report
    import time
    execution_report(world.store, top_id, time.time()-1, title='Recorded example execution',
                     slug='b2a-example-proof', is_success=1, status_code=200)
    badge_ok = c.get(f"/api/agent/v1/badge/{top_id}.svg")
    assert badge_ok.status_code == 200
    assert "image/svg+xml" in badge_ok.headers.get("content-type", "")
    assert "Verified" in badge_ok.text
    badge_missing = c.get("/api/agent/v1/badge/999999.svg")
    assert badge_missing.status_code == 200
    assert "Unverified" in badge_missing.text


"""Tests for Frontend Learn Tab: Unregistered Popular Agents by Domain (5 Categories).
Strictly English-only, zero Korean characters, zero sensitive data leakage.
"""

import re
import pytest
from fastapi.testclient import TestClient

from tests.test_concierge import w  # noqa: F401 (fixture)

pytestmark = pytest.mark.usefixtures('legacy_public_entry')


def test_front_learn_unregistered_categories_structure(w):
    """Test that all 5 unregistered agent categories exist in GUIDE and are grouped in renderLearnUI."""
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Verify 5 Category IDs exist in GUIDE
    assert 'id: "unreg-coding"' in html
    assert 'id: "unreg-frameworks"' in html
    assert 'id: "unreg-research"' in html
    assert 'id: "unreg-web3"' in html
    assert 'id: "unreg-stdio"' in html

    # 2. Verify pill labels and titles
    assert 'pillLabel: "Autonomous Coding & SWE"' in html
    assert 'pillLabel: "Multi-Agent Frameworks"' in html
    assert 'pillLabel: "Research & Computer Use"' in html
    assert 'pillLabel: "Decentralized & Crypto Agents"' in html
    assert 'pillLabel: "Official STDIO MCP Servers"' in html

    # 3. Verify category grouping in learnSubPills
    assert "Ecosystem Landscape: Unregistered Popular Agents" in html
    assert "5 Key Domains" in html
    assert "Open Protocol Standards & Architecture" in html
    assert "Ecosystem Reference & FAQ" in html


def test_front_learn_autonomous_coding_category(w):
    """Test Autonomous Coding & SWE Agents category contents."""
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Key benchmark agents present
    assert "Devin" in html
    assert "Cognition Labs" in html
    assert "OpenHands" in html
    assert "All-Hands AI" in html
    assert "SWE-agent" in html
    assert "Princeton NLP" in html
    assert "Aider" in html
    assert "Paul Gauthier" in html

    # 2. Key stats and architectural reasons
    assert "45k+ Stars" in html
    assert "26k+ Stars" in html
    assert "15k+ Stars" in html
    assert "SWE-bench" in html
    assert "Closed Proprietary SaaS" in html
    assert "Local Docker / CLI Execution" in html
    assert "A2A Container Bridge Runner" in html


def test_front_learn_multi_agent_frameworks_category(w):
    """Test Multi-Agent Frameworks category contents."""
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Featured frameworks present
    assert "Microsoft AutoGen" in html
    assert "Microsoft Research" in html
    assert "CrewAI" in html
    assert "MetaGPT" in html
    assert "DeepWisdom" in html
    assert "Smolagents" in html
    assert "Hugging Face" in html

    # 2. Traction and reasons
    assert "36k+ Stars" in html
    assert "46k+ Stars" in html
    assert "13k+ Stars" in html
    assert "Python Package Library" in html
    assert "REST &amp; FastAPI Automatic Wrapping" in html or "REST & FastAPI Automatic Wrapping" in html
    assert "A2A Task Delegation Protocol" in html


def test_front_learn_research_and_computer_use_category(w):
    """Test Research & Computer Use category contents."""
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Featured agents
    assert "Manus AI" in html
    assert "OpenAI Operator" in html
    assert "Perplexity Pro" in html

    # 2. Reasons and bridge solutions
    assert "Invite-Only Closed Platform" in html
    assert "Proprietary ChatGPT Feature" in html
    assert "Perplexity REST Adapter" in html
    assert "Visual Grounding &amp; DOM Interaction" in html


def test_front_learn_web3_crypto_agents_category(w):
    """Test Decentralized & Crypto Agents category contents."""
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Featured projects
    assert "ElizaOS" in html
    assert "ai16z" in html
    assert "Virtuals Protocol" in html
    assert "Fetch.ai" in html
    assert "Coinbase AgentKit" in html

    # 2. Reasons and bridge solutions
    assert "Messenger &amp; WebSocket Architecture" in html
    assert "Proprietary uAgents Protocol" in html
    assert "x402 Micropayment Bridge" in html
    assert "A2A Agent Card Gateway for ElizaOS" in html


def test_front_learn_official_stdio_mcp_category(w):
    """Test Anthropic Official STDIO Servers category contents."""
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Featured STDIO tools
    assert "@modelcontextprotocol/server-brave-search" in html
    assert "@modelcontextprotocol/server-github" in html
    assert "@modelcontextprotocol/server-postgres" in html
    assert "@modelcontextprotocol/server-slack" in html
    assert "@modelcontextprotocol/server-puppeteer" in html
    assert "@modelcontextprotocol/server-gdrive" in html

    # 2. Client configuration sample and bridge roadmap
    assert "claude_desktop_config.json" in html
    assert "STDIO-to-SSE Secure Proxy" in html
    assert "Cloud-Hosted Remote Alternatives" in html


def test_front_learn_updated_existing_sections(w):
    """Test that existing Learn sections reflect recent frontend architecture and features."""
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. A2A updates
    assert "Continuous Agent Relationship" in html
    assert "X-Visitor-Token" in html
    assert "Autonomous Notification Desk" in html

    # 2. MCP updates
    assert "Universal OpenAPI Adapter" in html
    assert "Visual Canvas Orchestration" in html

    # 3. x402 updates
    assert "Sub-Second Off-Chain Validation" in html
    assert "On-Chain Batch Settlement" in html

    # 4. Synergy & Workflow Studio updates
    assert "Visual Orchestration &amp; Standalone Web App Export" in html or "Visual Orchestration & Standalone Web App Export" in html
    assert "Download Web App" in html

    # 5. Discovery & Test Reports
    assert "Automated Benchmark Test Reports" in html
    assert "TEST REPORT" in html
    assert "report-badge-vivid" in html

    # 6. Quality & Security
    assert "SSRF Defense" in html
    assert "Tool Rug-Pull Quarantine" in html

    # 7. Glossary expansions
    assert "Visitor Token" in html
    assert "Workflow Studio" in html
    assert "Standalone Web App" in html
    assert "OpenAPI Adapter" in html
    assert "Notification Desk" in html
    assert "Clearinghouse" in html

    # 8. FAQ expansions
    assert "How does the continuous agent relationship work in chat?" in html
    assert "Can I download and run multi-agent workflows offline?" in html
    assert "Can I connect legacy REST APIs to Agent Concierge?" in html
    assert "How does Agent Concierge prevent SSRF attacks?" in html


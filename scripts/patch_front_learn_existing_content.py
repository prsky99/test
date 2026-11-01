# -*- coding: utf-8 -*-
"""Update existing sections in Learn tab (a2a, mcp, x402, compare, together, discovery, quality, glossary, faq).
Reflects recent frontend architecture: Workflow Studio canvas, Standalone Web App export,
Benchmark Test Reports, Continuous Agent relationships (X-Visitor-Token), OpenAPI adapter,
Clearinghouse micropayments, and security sandbox audits.
Strictly English-only, zero Korean characters, zero sensitive data leakage.
"""

from pathlib import Path
import py_compile
import re
import subprocess
import sys
import tempfile

EXTRACTED_PATH = Path("extracted_html.txt")
FRONT_PY_PATH = Path("agent_market/concierge/front.py")

# Updated A2A Section
NEW_A2A_HTML = """
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>A2A (Agent2Agent)</b> is an open communication standard that allows AI agents constructed on disparate frameworks and models to <b>delegate tasks and exchange rich artifacts</b>.
      Initiated by Google in April 2025 and hosted by the Linux Foundation, it provides a neutral protocol layer for multi-agent collaboration.
    </p>
    <div style="background:var(--chip);border-left:4px solid var(--k-a2a);padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0;font-size:13.5px">
      <b>Analogy:</b> If MCP is how an agent interacts with <b>tools</b>, A2A is how an agent <b>outsources an entire job to a specialized peer agent</b>.
      The caller does not need to know what model, internal memory, or toolchain the delegate agent runs.
    </div>
    <h4 style="margin:16px 0 6px 0">Core Concepts</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li><b>Agent Card</b> — Machine-readable identity record served at <code>/.well-known/agent-card.json</code> detailing capabilities (<b>Skills</b>), endpoints, and authentication.</li>
      <li><b>Task</b> — Asynchronous stateful job lifecycle: Submitted → Working → (Input Required) → Completed / Failed / Canceled.</li>
      <li><b>Message &amp; Parts</b> — Structured multi-modal payloads combining text, files, and data objects.</li>
      <li><b>Artifact</b> — Completed deliverables (reports, code, charts, datasets) with push notifications and streaming.</li>
      <li><b>Continuous Agent Relationship</b> — Persistent session continuity using <code>X-Visitor-Token</code> headers, allowing caller agents and human operators to resume multi-turn dialogues across disconnects.</li>
      <li><b>Autonomous Notification Desk</b> — Bidirectional callback webhooks with 6-digit challenge handshake verification for asynchronous task completion dispatches.</li>
    </ul>
    <h4 style="margin:16px 0 6px 0">How It Works</h4>
    <ol style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li>The client reads the delegate's <code>Agent Card</code> to verify skills, price models, and communication parameters.</li>
      <li>Submits a task request using <code>SendMessage</code> (v1.0) or <code>message/send</code> (v0.3) with an optional <code>X-Visitor-Token</code> for session continuity.</li>
      <li>Synchronous tasks return immediately; asynchronous tasks are monitored via <code>GetTask</code> or dispatched to registered webhooks.</li>
      <li>Deliverables are returned as structured Artifacts, rendered natively on interactive consoles or compiled into workflows.</li>
    </ol>
    <div style="margin-top:14px" data-live="a2a"></div>
    <div data-featured="a2a"></div>
"""

# Updated MCP Section
NEW_MCP_HTML = """
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>MCP (Model Context Protocol)</b> is an open standard connecting AI models to external tools, live data, and structured context.
      Released by Anthropic in November 2024, it has become the universal standard supported across major AI runtimes and developer tools.
    </p>
    <div style="background:var(--chip);border-left:4px solid var(--k-mcp);padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0;font-size:13.5px">
      <b>Analogy:</b> Just as USB-C replaced fragmented proprietary cables, building an MCP server <b>once</b> makes it immediately usable in <b>Claude, ChatGPT, Cursor, VS Code</b>, and autonomous agents without custom adapters.
    </div>
    <h4 style="margin:16px 0 6px 0">Core Capabilities</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li><b>Tools</b> — Executable functions called by AI models (e.g. database query, web search, GitHub issue creation, code editing).</li>
      <li><b>Resources</b> — Read-only context and data files exposed directly to AI context windows.</li>
      <li><b>Prompts</b> — Pre-engineered workflow templates and interaction recipes.</li>
      <li><b>Universal OpenAPI Adapter</b> — Agent Concierge automatically wraps traditional Swagger / OpenAPI 3.0 specifications into remote MCP tool endpoints with zero manual code.</li>
      <li><b>Visual Canvas Orchestration</b> — Drag and drop verified MCP tools directly into Agent Concierge's Workflow Studio canvas to chain multi-tool execution pipelines.</li>
    </ul>
    <h4 style="margin:16px 0 6px 0">How It Works</h4>
    <ol style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li><code>initialize</code> — Negotiates protocol version, capabilities, and server features.</li>
      <li><code>tools/list</code> — Server returns available tools with parameter JSON schemas and semantic descriptions.</li>
      <li>Model analyzes descriptions and autonomously selects parameters.</li>
      <li><code>tools/call</code> — Executes requested tool over JSON-RPC 2.0 (Streamable HTTP / stdio) and returns results with strict sandbox verification.</li>
    </ol>
    <div style="margin-top:14px" data-live="mcp"></div>
    <div data-featured="mcp"></div>
"""

# Updated x402 Section
NEW_X402_HTML = """
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>x402</b> revives the historic <b>HTTP 402 Payment Required</b> status code to enable instant, pay-per-request API monetization using stablecoins (<b>USDC</b>).
      Published by Coinbase in 2025, it empowers autonomous AI agents to transact independently without human credit card setups.
    </p>
    <div style="background:var(--chip);border-left:4px solid var(--k-x402);padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0;font-size:13.5px">
      <b>Analogy:</b> A digital vending machine for AI: no accounts, no subscriptions, no monthly minimums.
      An agent drops in $0.001 USDC on Base or Solana per API call and receives immediate service autonomously.
    </div>
    <h4 style="margin:16px 0 6px 0">Architecture &amp; Clearinghouse Settlement</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li><b>Sub-Second Off-Chain Validation</b> — Agent Concierge's integrated Clearinghouse verifies cryptographic signatures and payment intent headers without blocking on blockchain confirmation times.</li>
      <li><b>On-Chain Batch Settlement</b> — Aggregated payment commitments are settled in batches to Base and EVM networks, minimizing gas overhead to fractions of a cent.</li>
      <li><b>Zero Account Overhead</b> — Autonomous caller agents pay on-the-fly per invocation; service providers receive instantaneous liquidity with zero chargeback risk.</li>
    </ul>
    <h4 style="margin:16px 0 6px 0">How It Works</h4>
    <ol style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li>Agent makes a standard HTTP request to the service endpoint.</li>
      <li>Server returns <code>HTTP 402</code> with payment parameters: Price (USDC), chain, and receiving wallet.</li>
      <li>Agent signs payment with its self-custodial wallet and attaches payment proof to the request header.</li>
      <li>Clearinghouse verifies settlement in sub-second time, and the API fulfills the request.</li>
    </ol>
    <div style="margin-top:14px" data-live="x402"></div>
    <div data-featured="x402"></div>
"""

# Updated Compare Section
NEW_COMPARE_HTML = """
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Dimension</th>
            <th><span class="kind-badge k-a2a">A2A</span></th>
            <th><span class="kind-badge k-mcp">MCP</span></th>
            <th><span class="kind-badge k-x402">x402</span></th>
          </tr>
        </thead>
        <tbody>
          <tr><th>Primary Role</th><td>Agent-to-agent delegation</td><td>AI-to-tool integration</td><td>Per-call API monetization</td></tr>
          <tr><th>Analogy</th><td>Outsourcing to a specialist</td><td>USB-C standard port</td><td>Digital vending machine</td></tr>
          <tr><th>Originator</th><td>Google → Linux Foundation (2025)</td><td>Anthropic (2024)</td><td>Coinbase (2025)</td></tr>
          <tr><th>Transport</th><td>JSON-RPC · gRPC · HTTP</td><td>JSON-RPC 2.0 (Streamable HTTP)</td><td>Standard HTTP + 402 responses</td></tr>
          <tr><th>Discovery</th><td>Agent Card · ERC-8004</td><td>Official MCP Registry</td><td>x402 Bazaar · Catalog Feeds</td></tr>
          <tr><th>Payment &amp; Auth</th><td>Declared on card (OAuth, x402)</td><td>Mostly free · OAuth for SaaS</td><td>USDC micropayments · Zero accounts</td></tr>
          <tr><th>Visual Studio Node</th><td>Task Delegation Step</td><td>Tool Execution Step</td><td>Monetized Data Step</td></tr>
          <tr><th>Test Report Audits</th><td>Stateful task completion tests</td><td>Schema &amp; live trial tests</td><td>Payment handshake &amp; payload tests</td></tr>
          <tr><th>Session Continuity</th><td>X-Visitor-Token &amp; Webhooks</td><td>Stateful SSE connection</td><td>Cryptographic signature proofs</td></tr>
          <tr><th>Best Suited For</th><td>Multi-step workflows &amp; delegation</td><td>Context enrichment &amp; tool invocation</td><td>Paid premium data &amp; single-call APIs</td></tr>
        </tbody>
      </table>
    </div>
"""

# Updated Synergy Section
NEW_TOGETHER_HTML = """
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      The three standards are not competitors; they operate at complementary architectural layers to form complete autonomous systems:
    </p>
    <ol style="padding-left:18px;margin:0;line-height:1.8;font-size:13.5px">
      <li><b>Task Delegation (A2A)</b> — An autonomous coordinator agent receives a user mission via A2A to perform multi-source research and financial modeling.</li>
      <li><b>Tool Context (MCP)</b> — The coordinator queries internal company documents, git repositories, and web search engines using local or remote MCP servers.</li>
      <li><b>Premium Data Settlement (x402)</b> — To fetch real-time market data or proprietary satellite imagery, it calls a paid endpoint, settling $0.005 USDC via x402 in sub-seconds.</li>
      <li><b>Deliverable Assembly &amp; Notification (A2A)</b> — The synthesized model is packaged as an A2A Artifact and dispatched to the caller's registered webhook callback.</li>
    </ol>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Visual Orchestration &amp; Standalone Web App Export</h4>
    <p style="font-size:13px;color:var(--text-muted);line-height:1.6;margin:0 0 10px 0">
      In Agent Concierge's <b>Visual Workflow Studio</b> (<code>#workflows</code>), you can drag and drop nodes from all three protocol families onto an interactive canvas.
      Once assembled and verified, click <b>Download Web App</b> to export the entire multi-agent pipeline into a standalone, single-file HTML/JS application that runs anywhere with zero server setup.
    </p>
"""

# Updated Discovery Section
NEW_DISCOVERY_HTML = """
    <ul style="padding-left:18px;margin:0;line-height:1.8;font-size:13.5px">
      <li><b>Agent Concierge Live Catalog (<code>#explore</code>)</b> — Unified, searchable directory indexing over 94,000+ live resources across A2A, MCP, and x402 with sub-millisecond SWR client caching.</li>
      <li><b>Automated Benchmark Test Reports (<code>✦ TEST REPORT</code>)</b> — Over 200+ deeply audited agents featuring verified execution reports, real-world latency measurements, pass rates, and interactive testing workflows.</li>
      <li><b>x402 Bazaar</b> — Official registry maintained by Coinbase indexing prices, settlement addresses, and 30-day payment volume.</li>
      <li><b>MCP Registry</b> — Official directory for remote and local MCP servers with parameter schemas and repository links.</li>
      <li><b>ERC-8004 On-Chain Registry</b> — Ethereum standard for Trustless Agents recording decentralized identity, reputation, and endpoint URIs on Base and Ethereum.</li>
      <li><b>.well-known Discovery</b> — Direct automated scanning of public domain endpoints at <code>/.well-known/agent-card.json</code>.</li>
    </ul>
"""

# Updated Quality Section
NEW_QUALITY_HTML = """
    <h4 style="margin:0 0 6px 0">Health Lifecycle States</h4>
    <ul style="padding-left:18px;margin:0 0 14px 0;line-height:1.7;font-size:13px">
      <li><span class="s-healthy font-semibold">healthy</span> — Responding according to protocol specifications (x402 returns valid 402, MCP initializes, A2A card opens).</li>
      <li><span class="s-reachable font-semibold">reachable</span> — Endpoint online but requires authentication or API credentials to complete probe.</li>
      <li><span class="s-failing font-semibold">failing</span> — 1–2 consecutive probe failures. Retried after 15 minutes; temporarily demoted from recommendations.</li>
      <li><span class="s-down font-semibold">down</span> — 3+ consecutive failures. Continuously probed for recovery.</li>
      <li><span class="s-retired font-semibold">retired</span> — Unresponsive for &gt;7 days. Excluded from active indexes.</li>
    </ul>

    <h4 style="margin:16px 0 6px 0">Automated Quality Rubric (Grades A–F)</h4>
    <p style="font-size:13px;color:var(--text-muted);margin:0 0 12px 0;line-height:1.6">
      Endpoints are evaluated across 6 dimensions without subjective LLM bias: <b>Availability</b> (25%), <b>Schema Quality</b> (20%), <b>Security Posture</b> (20%), <b>Context Efficiency</b> (15%), <b>Protocol Adherence</b> (10%), and <b>Maintenance Freshness</b> (10%).
    </p>

    <h4 style="margin:16px 0 6px 0">Security Sandbox &amp; Abuse Prevention</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>SSRF Defense</b> — Automated blocking of RFC-1918 private subnet IP ranges, loopback localhost addresses, and internal network endpoints.</li>
      <li><b>Adversarial Anomaly Filtration</b> — Detection of prompt injection attempts, hidden zero-width unicode payload characters, and behavioral mutations.</li>
      <li><b>Tool Rug-Pull Quarantine</b> — Immediate isolation of endpoints whose tool parameter schemas change without version bumps or audit revalidation.</li>
    </ul>
"""

# Updated Glossary Entries
NEW_GLOSSARY_ITEMS = [
    ["HTTP 402", "Payment Required status code specifying amount, token, and wallet address."],
    ["USDC", "USD-pegged stablecoin with 6 decimals allowing sub-cent micropayments ($0.000001)."],
    ["Base", "High-throughput Ethereum Layer 2 chain widely used for low-fee x402 transactions."],
    ["Facilitator", "Service validating and settling blockchain micropayment proofs on behalf of API providers."],
    ["x402 Bazaar", "Public discovery index of x402-enabled paid endpoints and real-time pricing."],
    ["MCP Tool", "Callable function definition exposed by an MCP server to an AI model."],
    ["tools/list", "JSON-RPC method returning available tools and parameter schemas."],
    ["tools/call", "JSON-RPC method executing an MCP tool with provided arguments."],
    ["JSON-RPC 2.0", "Standard lightweight RPC protocol utilized by both MCP and A2A."],
    ["Streamable HTTP", "HTTP POST transport supporting streaming responses for remote MCP."],
    ["Agent Card", "Standardized JSON identity record defining skills, endpoints, and credentials."],
    ["Skill", "Declared capability description published in an A2A Agent Card."],
    ["Task", "Stateful asynchronous job instance managed across peer agents."],
    ["Artifact", "Deliverable output object returned upon A2A task completion."],
    ["Visitor Token", "Cryptographically random token (X-Visitor-Token) preserving multi-turn chat continuity without tracking PII."],
    ["Workflow Studio", "Visual canvas interface for dragging, connecting, and running multi-agent execution pipelines."],
    ["Standalone Web App", "Portable zero-dependency single-file HTML application exported from visual workflow studio."],
    ["OpenAPI Adapter", "Automated proxy converter mapping OpenAPI 3.0 / Swagger REST specs into native MCP tools and A2A cards."],
    ["Test Report", "Automated verification audit validating live tool execution pass rate, latency percentiles, and schema integrity."],
    ["Notification Desk", "Asynchronous agent callback webhook manager with 6-digit challenge handshake verification."],
    ["Clearinghouse", "High-throughput off-chain payment verification and batch on-chain settlement engine."],
    ["ERC-8004", "On-chain standard for decentralized agent identity and verification."],
    [".well-known", "Standard IETF URI prefix used for automated agent card discovery."],
    ["Tool Poisoning", "Adversarial exploit injecting malicious hidden instructions inside tool descriptions."],
    ["Rug Pull", "Unauthorized mutation of tool definitions after initial verification."],
    ["Quarantine", "Security isolation state for compromised or hostile agent servers."]
]

# Updated FAQ Items
NEW_FAQ_ITEMS = [
    ["Which protocol should I choose for my project?", "Choose MCP if you want to connect tools to Claude/ChatGPT/Cursor; choose A2A if you are delegating autonomous jobs across agents; choose x402 if you are monetizing API calls per request with crypto."],
    ["Are MCP servers free to use?", "The majority of community MCP servers are free and open-source. Commercial SaaS tools may require OAuth login or existing service accounts."],
    ["Does reachable mean an error?", "No. Reachable indicates the endpoint server is online and operational, but requires user credentials or an API key for full functional probing."],
    ["How are recommended agents vetted?", "Services are continuously validated via real connectivity probes, automated tool tests, and security sandbox audits. Quarantined services are blocked."],
    ["Can I register my own agent?", "Yes. Navigate to the Register tab, enter your public endpoint URL, and our gateway will perform an automated live verification probe."],
    ["How does the continuous agent relationship work in chat?", "Agent Concierge assigns a persistent visitor token (X-Visitor-Token) shown in the chat console header. You can copy or import this token to resume previous sessions across browser reloads or machine-to-machine runners."],
    ["Can I download and run multi-agent workflows offline?", "Yes. In the Workflow Studio (#workflows), you can design or load a template and click 'Download Web App' to get a single-file HTML application with self-contained client-side orchestration."],
    ["What does the '✦ TEST REPORT' badge represent?", "It indicates that the agent has undergone comprehensive automated trial executions, with latency benchmarks, tool call verification, and live test reports available in the agent details drawer."],
    ["Can I connect legacy REST APIs to Agent Concierge?", "Yes. Use our built-in OpenAPI Adapter to paste any OpenAPI 3.0 or Swagger schema URL; the gateway automatically exposes it as a standard MCP tool server and A2A Agent Card."],
    ["How does Agent Concierge prevent SSRF attacks?", "All registered endpoints undergo strict IP validation. Private RFC-1918 subnets, localhost addresses, and internal network ports are blocked at the proxy boundary."]
]

def main():
    html = EXTRACTED_PATH.read_text(encoding="utf-8")

    # Replace A2A section
    old_a2a_pattern = r'id: "a2a", group: "protocols", pillLabel: "A2A Protocol", kind: "a2a", title: "A2A — Agent-to-Agent Delegation Protocol", html: `.*?`\s*\},'
    m_a2a = re.search(old_a2a_pattern, html, re.DOTALL)
    assert m_a2a, "Could not find old A2A section"
    new_a2a = f'id: "a2a", group: "protocols", pillLabel: "A2A Protocol", kind: "a2a", title: "A2A — Agent-to-Agent Delegation Protocol", html: `{NEW_A2A_HTML}`}},'
    html = html[:m_a2a.start()] + new_a2a + html[m_a2a.end():]
    print("✓ Updated A2A section")

    # Replace MCP section
    old_mcp_pattern = r'id: "mcp", group: "protocols", pillLabel: "MCP Protocol", kind: "mcp", title: "MCP — Model Context Protocol: USB-C for AI", html: `.*?`\s*\},'
    m_mcp = re.search(old_mcp_pattern, html, re.DOTALL)
    assert m_mcp, "Could not find old MCP section"
    new_mcp = f'id: "mcp", group: "protocols", pillLabel: "MCP Protocol", kind: "mcp", title: "MCP — Model Context Protocol: USB-C for AI", html: `{NEW_MCP_HTML}`}},'
    html = html[:m_mcp.start()] + new_mcp + html[m_mcp.end():]
    print("✓ Updated MCP section")

    # Replace x402 section
    old_x402_pattern = r'id: "x402", group: "protocols", pillLabel: "x402 Micropayments", kind: "x402", title: "x402 — Micropayments via HTTP 402", html: `.*?`\s*\},'
    m_x402 = re.search(old_x402_pattern, html, re.DOTALL)
    assert m_x402, "Could not find old x402 section"
    new_x402 = f'id: "x402", group: "protocols", pillLabel: "x402 Micropayments", kind: "x402", title: "x402 — Micropayments via HTTP 402", html: `{NEW_X402_HTML}`}},'
    html = html[:m_x402.start()] + new_x402 + html[m_x402.end():]
    print("✓ Updated x402 section")

    # Replace compare section
    old_compare_pattern = r'id: "compare", group: "protocols", pillLabel: "Side-by-Side Comparison", title: "Side-by-Side Comparison", html: `.*?`\s*\},'
    m_compare = re.search(old_compare_pattern, html, re.DOTALL)
    assert m_compare, "Could not find old compare section"
    new_compare = f'id: "compare", group: "protocols", pillLabel: "Side-by-Side Comparison", title: "Side-by-Side Comparison", html: `{NEW_COMPARE_HTML}`}},'
    html = html[:m_compare.start()] + new_compare + html[m_compare.end():]
    print("✓ Updated compare section")

    # Replace together section
    old_together_pattern = r'id: "together", group: "protocols", pillLabel: "Synergy & Composition", title: "Synergy: Using All Three Together", html: `.*?`\s*\},'
    m_together = re.search(old_together_pattern, html, re.DOTALL)
    assert m_together, "Could not find old together section"
    new_together = f'id: "together", group: "protocols", pillLabel: "Synergy & Composition", title: "Synergy: Using All Three Together", html: `{NEW_TOGETHER_HTML}`}},'
    html = html[:m_together.start()] + new_together + html[m_together.end():]
    print("✓ Updated together section")

    # Replace discovery section
    old_discovery_pattern = r'id: "discovery", group: "reference", pillLabel: "Live Agent Discovery", title: "Where to Find Live Agents", html: `.*?`\s*\},'
    m_discovery = re.search(old_discovery_pattern, html, re.DOTALL)
    assert m_discovery, "Could not find old discovery section"
    new_discovery = f'id: "discovery", group: "reference", pillLabel: "Live Agent Discovery", title: "Where to Find Live Agents", html: `{NEW_DISCOVERY_HTML}`}},'
    html = html[:m_discovery.start()] + new_discovery + html[m_discovery.end():]
    print("✓ Updated discovery section")

    # Replace quality section
    old_quality_pattern = r'id: "quality", group: "reference", pillLabel: "Quality & Health Grading", title: "Health Status & 6-Axis Quality Grading", html: `.*?`\s*\},'
    m_quality = re.search(old_quality_pattern, html, re.DOTALL)
    assert m_quality, "Could not find old quality section"
    new_quality = f'id: "quality", group: "reference", pillLabel: "Quality & Health Grading", title: "Health Status & 6-Axis Quality Grading", html: `{NEW_QUALITY_HTML}`}},'
    html = html[:m_quality.start()] + new_quality + html[m_quality.end():]
    print("✓ Updated quality section")

    # Replace glossary section
    import json
    glossary_json = json.dumps(NEW_GLOSSARY_ITEMS, indent=4, ensure_ascii=False)
    # Format cleanly inside JS
    glossary_code = f'id: "glossary", group: "reference", pillLabel: "Terminology Dictionary", title: "Terminology Dictionary", glossary: {glossary_json}'
    old_glossary_pattern = r'id: "glossary", group: "reference", pillLabel: "Terminology Dictionary", title: "Terminology Dictionary", glossary:\s*\[.*?\]\s*\},'
    m_glossary = re.search(old_glossary_pattern, html, re.DOTALL)
    assert m_glossary, "Could not find old glossary section"
    html = html[:m_glossary.start()] + glossary_code + "}," + html[m_glossary.end():]
    print("✓ Updated glossary section")

    # Replace faq section
    faq_json = json.dumps(NEW_FAQ_ITEMS, indent=4, ensure_ascii=False)
    faq_code = f'id: "faq", group: "reference", pillLabel: "Frequently Asked Questions", title: "Frequently Asked Questions", faq: {faq_json}'
    old_faq_pattern = r'id: "faq", group: "reference", pillLabel: "Frequently Asked Questions", title: "Frequently Asked Questions", faq:\s*\[.*?\]\s*\}\s*\];'
    m_faq = re.search(old_faq_pattern, html, re.DOTALL)
    assert m_faq, "Could not find old faq section"
    html = html[:m_faq.start()] + faq_code + "}\n];" + html[m_faq.end():]
    print("✓ Updated faq section")

    # Verify zero Korean characters in HTML
    korean = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", html)
    if korean:
        print(f"ERROR: Found Korean characters in HTML: {set(korean)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed on HTML!")

    # Verify node syntax
    scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) >= 2, "Expected script tags in HTML"
    main_js = scripts[-1]

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=True) as tf:
        tf.write(main_js)
        tf.flush()
        chk = subprocess.run(["node", "--check", tf.name], capture_output=True, text=True)
        if chk.returncode != 0:
            print("ERROR: Node syntax check failed!")
            print(chk.stderr)
            sys.exit(1)
    print("✓ Node syntax check passed on modified frontend JavaScript!")

    # Write extracted_html.txt
    EXTRACTED_PATH.write_text(html, encoding="utf-8")
    print("✓ Updated extracted_html.txt")

    # Update front.py
    front_code = FRONT_PY_PATH.read_text(encoding="utf-8")
    m = re.search(r'\nHTML = ([\'"].*?[\'"])\n\ndef create_front_app', front_code, re.DOTALL)
    assert m, "Could not locate HTML definition in front.py"

    new_front_code = front_code[:m.start(1)] + repr(html) + front_code[m.end(1):]

    korean_front = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", new_front_code)
    if korean_front:
        print(f"ERROR: Found Korean characters in front.py: {set(korean_front)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed on front.py!")

    FRONT_PY_PATH.write_text(new_front_code, encoding="utf-8")
    py_compile.compile(str(FRONT_PY_PATH), doraise=True)
    print("✓ Successfully patched and compiled front.py!")

if __name__ == "__main__":
    main()

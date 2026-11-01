# -*- coding: utf-8 -*-
"""Patch frontend Learn tab with 5 comprehensive Unregistered Popular Agent categories.
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

# HTML Content for Category 1: Autonomous Coding & SWE
HTML_UNREG_CODING = """
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Autonomous Coding &amp; Software Engineering (SWE) Agents</b> represent the frontier of generative AI in software development.
      Unlike traditional code completion assistants (e.g. GitHub Copilot autocomplete), autonomous SWE agents can ingest complex issue tickets,
      analyze entire multi-repository codebases, reproduce bugs, write and execute unit tests, and submit verified Pull Requests with zero human intervention.
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--accent);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> While these agents hold top spots on academic benchmarks (such as SWE-bench) and enjoy tens of thousands of GitHub stars,
      <b>none are currently registered as public A2A or remote MCP endpoints</b> on standard directories. They operate as proprietary closed-session SaaS platforms,
      interactive terminal CLI tools, or local Docker sandbox containers.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Featured Benchmark Leaders &amp; Unregistered Status Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Agent Name</th>
            <th>Developer / Organization</th>
            <th>Stature &amp; Traction</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>Devin</b></td>
            <td>Cognition Labs</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">Pioneer</span> · World's first autonomous AI software engineer</td>
            <td>End-to-end task breakdown, terminal command execution, multi-file code editing, self-debugging, and automated cloud deployments.</td>
            <td><b>Closed Proprietary SaaS</b>: Operates exclusively inside isolated web sessions at <code>devin.ai</code>. Provides no public A2A Agent Card or remote MCP endpoints.</td>
          </tr>
          <tr>
            <td><b>OpenHands</b><br><span style="font-size:11px;color:var(--text-dim)">(formerly OpenDevin)</span></td>
            <td>All-Hands AI</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">45k+ Stars</span> · #1 open-source autonomous coding agent</td>
            <td>Combines bash terminal execution, syntax tree editing, and headless web browsing inside secure Docker containers to resolve GitHub issues.</td>
            <td><b>Local Docker / CLI Execution</b>: Designed as a self-hosted container environment. Does not publish a persistent remote public HTTPS A2A endpoint.</td>
          </tr>
          <tr>
            <td><b>SWE-agent</b></td>
            <td>Princeton NLP</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">15k+ Stars</span> · Leading SWE-bench benchmark agent</td>
            <td>Specialized Agent-Computer Interface (ACI) that navigates repository structures, edits lines by range, and generates verified Pull Requests.</td>
            <td><b>Research CLI Batch Tool</b>: Packaged as an offline Python evaluation framework for benchmark testing rather than a 24/7 network service daemon.</td>
          </tr>
          <tr>
            <td><b>Aider</b></td>
            <td>Paul Gauthier</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">26k+ Stars</span> · Premier terminal AI pair programmer</td>
            <td>Directly pairs with developers in local git repositories, editing files in place with automated git commit messages and repo AST maps.</td>
            <td><b>Local Interactive CLI</b>: Runs entirely inside developer terminal sessions over stdin/stdout; lacks remote HTTP or Agent Card interfaces.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">Detailed Profiles &amp; Technical Architectures</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b style="font-size:14px;color:var(--accent)">1. Devin (Cognition Labs)</b>
          <span class="chip">Closed SaaS</span>
        </div>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0 0 8px 0">
          Devin is equipped with its own virtual sandbox including a sandboxed Linux shell, browser, and code editor. It independently plans solutions, reads API documentation, writes tests, and resolves compilation errors across complex dependencies.
        </p>
        <div style="font-size:11.5px;color:var(--text-dim)">
          <b>Integration Barrier:</b> Sessions are strictly browser-authenticated. Machine-to-machine invocation requires enterprise private API integration or headless browser proxying.
        </div>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b style="font-size:14px;color:var(--ok)">2. OpenHands (All-Hands AI)</b>
          <span class="chip">Docker Sandbox</span>
        </div>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0 0 8px 0">
          An extensible open-source platform providing micro-agents (CodeActAgent, PlannerAgent). It executes actions inside an isolated Docker runtime to safely run compilers, package managers, and web servers without compromising host machines.
        </p>
        <div style="font-size:11.5px;color:var(--text-dim)">
          <b>How to Run:</b> <code>docker run -it --pull=always -e SANDBOX_USER_ID=$(id -u) -p 3000:3000 ghcr.io/all-hands-ai/openhands:latest</code>
        </div>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b style="font-size:14px;color:var(--text)">3. SWE-agent (Princeton NLP)</b>
          <span class="chip">Research ACI</span>
        </div>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0 0 8px 0">
          SWE-agent introduced the Agent-Computer Interface (ACI), tailoring terminal outputs specifically for LLM consumption (compact search results, file viewer with syntax windows, targeted line replacer).
        </p>
        <div style="font-size:11.5px;color:var(--text-dim)">
          <b>Primary Target:</b> Benchmarking repository bug resolution on SWE-bench Verified dataset with automated evaluation harnesses.
        </div>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b style="font-size:14px;color:var(--text)">4. Aider (Paul Gauthier)</b>
          <span class="chip">Git-Native CLI</span>
        </div>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0 0 8px 0">
          Aider inspects local git repositories using tree-sitter AST maps to identify relevant code contexts. It edits multiple files concurrently and writes coherent git commit messages automatically.
        </p>
        <div style="font-size:11.5px;color:var(--text-dim)">
          <b>How to Run:</b> <code>pip install aider-chat &amp;&amp; aider --model claude-3-7-sonnet</code>
        </div>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Interoperability &amp; Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>A2A Container Bridge Runner</b>: We are engineering an open bridge container that wraps OpenHands and SWE-agent with an A2A Task server, allowing Agent Concierge users to dispatch coding tasks via standardized <code>/.well-known/agent-card.json</code> endpoints.</li>
      <li><b>Remote MCP Coding Server</b>: Exposing code editing and AST mapping primitives over Streamable HTTP MCP so that external orchestration agents can utilize SWE tools safely.</li>
      <li><b>Security Sandboxing Requirement</b>: Autonomous SWE agents require strict network isolation, ephemeral Docker containers, and permission checkpoints before executing arbitrary shell commands or pushing git branches.</li>
    </ul>
"""

# HTML Content for Category 2: Multi-Agent Orchestration Frameworks
HTML_UNREG_FRAMEWORKS = """
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Multi-Agent Orchestration Frameworks</b> are foundational engines that coordinate collaborative teams of specialized AI agents.
      Rather than relying on a single monolithic prompt, these frameworks assign distinct personas (e.g. Architect, Researcher, Programmer, Quality Auditor)
      that debate, review, and refine deliverables through structured multi-turn conversations.
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--k-mcp);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> Frameworks like Microsoft AutoGen, CrewAI, and MetaGPT command <b>over 120,000 GitHub stars combined</b>.
      However, they are distributed as <b>code libraries (Python/TypeScript SDKs)</b> meant for internal application development,
      rather than persistent, publicly reachable A2A or MCP endpoints.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Featured Frameworks &amp; Stature Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Framework / Engine</th>
            <th>Developer / Organization</th>
            <th>Stature &amp; Traction</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>Microsoft AutoGen</b></td>
            <td>Microsoft Research</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">36k+ Stars</span> · Enterprise multi-agent conversation standard</td>
            <td>Multi-agent conversation patterns, human-in-the-loop oversight, code execution, and modular event-driven group chats (AutoGen 0.4+).</td>
            <td><b>Python Package Library</b>: Developers assemble agents in Python code. Does not publish a public remote A2A endpoint or hosted Agent Card.</td>
          </tr>
          <tr>
            <td><b>CrewAI</b></td>
            <td>CrewAI Inc.</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">26k+ Stars</span> · #1 role-based multi-agent workforce toolkit</td>
            <td>Defines collaborative crews with explicit roles, backstories, and goal-driven tasks. Supports sequential and hierarchical process management.</td>
            <td><b>SDK &amp; Authenticated Enterprise Cloud</b>: Open-source core is a local library. Enterprise cloud requires private API keys behind auth gates.</td>
          </tr>
          <tr>
            <td><b>MetaGPT</b></td>
            <td>DeepWisdom</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">46k+ Stars</span> · Virtual software team simulator</td>
            <td>Encapsulates Standard Operating Procedures (SOPs). Simulates an entire software agency: Product Managers (PRDs), Architects, and Coders.</td>
            <td><b>Open-Source Framework</b>: Designed for local script execution and automated document pipeline generation, not a persistent public web service.</td>
          </tr>
          <tr>
            <td><b>Smolagents</b></td>
            <td>Hugging Face</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">13k+ Stars</span> · Code-as-action lightweight runtime</td>
            <td>Agents write executable Python code snippets to invoke tools and reason, drastically reducing token overhead compared to JSON schemas.</td>
            <td><b>Library Distribution</b>: Distributed as a pip package on PyPI and Hugging Face Hub without a public standalone HTTPS gateway.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">Architectural Models &amp; Collaboration Paradigms</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--accent);display:block;margin-bottom:6px">1. AutoGen Event-Driven Multi-Agent Protocol</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          AutoGen 0.4 restructured agents around an asynchronous message-passing core (Actor model). Agents exchange typed messages over topics, making it ideal for distributed event systems and microservice topologies.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--ok);display:block;margin-bottom:6px">2. CrewAI Hierarchical Task Orchestration</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          CrewAI introduces managerial agents that dynamically delegate subtasks to specialized subordinate agents based on real-time task outcomes, enabling automated research, drafting, and quality review pipelines.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--text);display:block;margin-bottom:6px">3. MetaGPT SOP State Machine</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          MetaGPT maps human software engineering methodologies to state transitions: User Requirement → PRD (Markdown) → System Design (UML diagrams) → API Specs → Code Implementation → Integration Test.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--text);display:block;margin-bottom:6px">4. Smolagents CodeAgent Runtime</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          By generating raw Python logic rather than constrained JSON tool arguments, Smolagents enables loops, conditional branching, and complex data structures directly within agent execution turns.
        </p>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Interoperability &amp; Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>REST &amp; FastAPI Automatic Wrapping</b>: Developers running CrewAI or AutoGen as internal web services can use Agent Concierge's <code>OpenApiAdapter</code> to automatically expose their workflows as registered A2A Agent Cards.</li>
      <li><b>A2A Task Delegation Protocol</b>: An external A2A caller can submit a task to Agent Concierge, which delegates the job to a CrewAI swarm and returns the final synthesized artifact upon completion.</li>
    </ul>
"""

# HTML Content for Category 3: Research & Computer Use
HTML_UNREG_RESEARCH = """
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Web Research, Browsing &amp; Computer Use Agents</b> are autonomous systems capable of operating web browsers and desktop graphical interfaces like human users.
      They interpret visual layouts, click UI elements, fill complex forms, bypass dynamic client-side rendering hurdles, and synthesize data across dozens of disparate websites into comprehensive research dossiers.
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--k-x402);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> Autonomous web research and computer-use tools from OpenAI, Perplexity, and Manus represent the most demanded AI capabilities in 2025–2026.
      However, they currently exist as <b>proprietary walled gardens or consumer-focused web applications</b> without open, machine-to-machine A2A or MCP discovery interfaces.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Featured Research Agents &amp; Unregistered Status Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Agent Name</th>
            <th>Developer / Organization</th>
            <th>Stature &amp; Traction</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>Manus AI</b></td>
            <td>Monica / Manus Team</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">Global Sensation</span> · 2025–2026 breakthrough generalist task agent</td>
            <td>Asynchronously executes complex multi-hour workflows: web research, market comparisons, document drafting, presentation slides, and live web app deployment.</td>
            <td><b>Invite-Only Closed Platform</b>: Operates as a browser-based consumer SaaS product. Does not provide an open machine-to-machine (M2M) API, A2A card, or remote MCP server.</td>
          </tr>
          <tr>
            <td><b>OpenAI Operator &amp; Deep Research</b></td>
            <td>OpenAI</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">Industry Flagship</span> · State-of-the-art vision computer use &amp; research</td>
            <td>Navigates live websites using vision models, clicks buttons, enters text, and searches dozens of academic and web sources to assemble multi-page analytical reports.</td>
            <td><b>Proprietary ChatGPT Feature</b>: Bound tightly to ChatGPT Pro and Team web interfaces. No external standardized A2A agent card or open MCP protocol endpoint is published.</td>
          </tr>
          <tr>
            <td><b>Perplexity Pro &amp; Deep Research</b></td>
            <td>Perplexity AI</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">Standard</span> · Premier real-time citation research engine</td>
            <td>Searches academic journals, financial filings, and live news streams with multi-stage reasoning to generate cited, hallucination-resistant research summaries.</td>
            <td><b>Proprietary REST API Format</b>: While standard REST endpoints exist (<code>api.perplexity.ai</code>), it does not provide native A2A Agent Card discovery or official remote MCP servers.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">Technical Capabilities &amp; Execution Challenges</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--accent);display:block;margin-bottom:6px">1. Visual Grounding &amp; DOM Interaction</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Agents like OpenAI Operator take high-resolution screenshots, calculate pixel bounding boxes, and generate synthetic mouse/keyboard events. This enables interaction with arbitrary web applications, canvas charts, and forms without requiring pre-existing APIs.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--ok);display:block;margin-bottom:6px">2. Multi-Hop Recursive Search</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Deep Research engines perform breadth-first and depth-first searches: extracting references from one document, spawning secondary search queries, evaluating source trustworthiness, and cross-checking conflicting data before finalizing conclusions.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--text);display:block;margin-bottom:6px">3. Asynchronous Task Continuity</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Complex web investigations can take 10 to 30 minutes. Manus AI employs asynchronous state checkpoints, webhooks, and push notifications to alert users when long-running research tasks complete.
        </p>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Interoperability &amp; Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>Headless Browser Tool Servers</b>: Agent Concierge currently catalogs verified remote browser MCP tools (e.g. Cloudflare Browser Rendering MCP, Firecrawl MCP) that allow any agent to execute programmatic scraping and research.</li>
      <li><b>Perplexity REST Adapter</b>: By configuring our universal REST adapter with a Perplexity API key, users can expose Perplexity's deep research engine as an instant MCP tool to Claude Desktop, Cursor, or A2A pipelines.</li>
    </ul>
"""

# HTML Content for Category 4: Decentralized & Crypto Agents
HTML_UNREG_WEB3 = """
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Web3 &amp; Decentralized Autonomous Agents</b> possess economic agency: they control non-custodial crypto wallets, execute on-chain smart contracts,
      manage decentralized liquidity, trade assets, and interact as autonomous social influencers across social platforms (X/Twitter, Telegram, Discord).
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--accent);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> Driven by ecosystems like Virtuals Protocol, ElizaOS, and Base, thousands of tokenized AI agents have achieved substantial market capitalization.
      However, they are <b>not registered on standard A2A/MCP directories</b> due to reliance on social messenger event loops, on-chain smart contracts, or proprietary communication protocols.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Featured Decentralized Agents &amp; Unregistered Status Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Agent / Platform</th>
            <th>Developer / Organization</th>
            <th>Stature &amp; Traction</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>ElizaOS</b><br><span style="font-size:11px;color:var(--text-dim)">(formerly Eliza)</span></td>
            <td>ai16z</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">16k+ Stars</span> · #1 crypto &amp; autonomous social AI framework</td>
            <td>Autonomous multi-platform social engagement (Twitter/Discord/Telegram), wallet management, character personas, and community management.</td>
            <td><b>Messenger &amp; WebSocket Architecture</b>: Communicates via social media APIs and WebSocket client connections rather than standard HTTP JSON-RPC A2A Agent Cards.</td>
          </tr>
          <tr>
            <td><b>Virtuals Protocol</b><br><span style="font-size:11px;color:var(--text-dim)">(Luna, aixbt, G.A.M.E.)</span></td>
            <td>Virtuals Protocol</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">Hundreds of Millions</span> in ecosystem market capitalization</td>
            <td>Tokenized co-owned AI personas running on Base/Ethereum. Autonomous social content generation, on-chain revenue sharing, and gaming agents.</td>
            <td><b>Smart Contract &amp; Social Platform Dependency</b>: Execution is tied to on-chain token contracts and proprietary G.A.M.E. SDKs without open remote A2A endpoints.</td>
          </tr>
          <tr>
            <td><b>Fetch.ai / ASI Alliance</b><br><span style="font-size:11px;color:var(--text-dim)">(Agentverse)</span></td>
            <td>Fetch.ai (ASI Alliance)</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">Pioneer</span> · Decentralized autonomous agent network since 2019</td>
            <td>Micro-agent collaboration in logistics, mobility, travel booking, and DeFi arbitrage. Features the Almanac on-chain contract registry.</td>
            <td><b>Proprietary uAgents Protocol</b>: Uses the uAgents Python framework and Almanac on-chain registry, which is incompatible with IETF A2A Agent Card specifications.</td>
          </tr>
          <tr>
            <td><b>Coinbase AgentKit</b></td>
            <td>Coinbase Developer Platform</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">Official Standard</span> · On-chain transaction toolkit for AI agents</td>
            <td>Empowers LangChain, CrewAI, and custom agents with crypto wallets to transfer USDC, swap tokens, and deploy smart contracts on Base and EVM chains.</td>
            <td><b>Developer SDK / Toolkit</b>: Distributed as an npm/pip developer SDK for embedding into private applications rather than a 24/7 hosted public agent server.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">Why On-Chain Agents Diverge from Web A2A Standards</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--accent);display:block;margin-bottom:6px">1. Social Event Loop vs. Remote HTTP Listener</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Agents built on ElizaOS poll or listen to platform feeds (e.g. mentions on X, Discord guild events). They act as clients connecting outward to platforms rather than running inbound HTTP servers with static URLs.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--ok);display:block;margin-bottom:6px">2. On-Chain Metadata vs. Live Runtime Endpoints</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Hundreds of thousands of ERC-8004 and tokenized agent contracts store only IPFS metadata (avatar images, descriptions). They lack live, reachable HTTPS hostnames where a caller can execute RPC calls.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--text);display:block;margin-bottom:6px">3. Gas Costs &amp; Non-Deterministic Latency</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          On-chain transaction execution requires cryptographic signing, gas estimation, and block confirmations (2–12 seconds), conflicting with real-time JSON-RPC expectations unless asynchronous task schemas are used.
        </p>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Interoperability &amp; Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>x402 Micropayment Bridge</b>: Agent Concierge provides native support for HTTP 402 micropayments over Base and EVM networks, enabling on-chain agents powered by Coinbase AgentKit to pay for and monetize API calls seamlessly.</li>
      <li><b>A2A Agent Card Gateway for ElizaOS</b>: An open adapter plugin allowing ElizaOS operators to publish a standard <code>/.well-known/agent-card.json</code> endpoint so web-based agents can delegate social tasks to Eliza personas.</li>
    </ul>
"""

# HTML Content for Category 5: Anthropic Official STDIO Servers
HTML_UNREG_STDIO = """
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Anthropic Official STDIO Servers</b> are the reference tools maintained in the official Model Context Protocol repository
      (<code>modelcontextprotocol/servers</code>). They empower desktop AI applications (e.g. Claude Desktop, Cursor) with direct access
      to file systems, version control, database queries, web search, and browser automation.
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--k-mcp);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> These are among the most celebrated tools in the entire MCP ecosystem. However, <b>none are registered as public web endpoints</b>
      because they are engineered to execute strictly as <b>local processes communicating over Standard Input/Output (STDIO)</b> pipes, rather than public HTTPS/SSE endpoints.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Official Reference STDIO Tool Suite Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Tool Server</th>
            <th>Package Identifier</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>Brave Search MCP</b></td>
            <td><code>@modelcontextprotocol/server-brave-search</code></td>
            <td>Performs real-time web searches and local geographic lookups via the Brave Search API.</td>
            <td><b>Local CLI Execution</b>: Launched via <code>npx</code> inside the client machine; does not provide a public remote HTTPS endpoint.</td>
          </tr>
          <tr>
            <td><b>GitHub MCP</b></td>
            <td><code>@modelcontextprotocol/server-github</code></td>
            <td>Repository exploration, issue tracking, Pull Request review, file modifications, and git commits.</td>
            <td><b>Requires Local Secret Tokens</b>: Requires the developer's Personal Access Token (PAT) in local environment variables.</td>
          </tr>
          <tr>
            <td><b>Postgres &amp; SQLite MCP</b></td>
            <td><code>@modelcontextprotocol/server-postgres</code></td>
            <td>Inspects database schemas, runs parameterized SQL queries, and analyzes internal table relationships.</td>
            <td><b>Local &amp; VPC Security</b>: Restricted to local or private VPC subnets to prevent catastrophic exposure of sensitive internal databases.</td>
          </tr>
          <tr>
            <td><b>Slack MCP</b></td>
            <td><code>@modelcontextprotocol/server-slack</code></td>
            <td>Lists channels, retrieves message histories, posts replies, and searches conversations in Slack workspaces.</td>
            <td><b>Local Bot Process</b>: Operates as an STDIO process consuming a local Slack Bot User OAuth Token.</td>
          </tr>
          <tr>
            <td><b>Puppeteer MCP</b></td>
            <td><code>@modelcontextprotocol/server-puppeteer</code></td>
            <td>Controls a headless Chromium browser instance to take screenshots, scrape dynamic HTML, and click elements.</td>
            <td><b>Local Process Control</b>: Spawns and manages a local Chromium browser process via Node.js pipes.</td>
          </tr>
          <tr>
            <td><b>Google Drive MCP</b></td>
            <td><code>@modelcontextprotocol/server-gdrive</code></td>
            <td>Searches, reads, and inspects files and Google Docs stored within Google Workspace accounts.</td>
            <td><b>Local OAuth2 Credentials</b>: Stores client credentials and OAuth token caches on the user's local workstation.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">STDIO vs. Remote HTTP Transport: Why They Differ</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--accent);display:block;margin-bottom:6px">1. Standard I/O (STDIO) Process Pipes</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          The host application (e.g. Claude Desktop) launches the tool as a child process. Requests and responses are serialized as single-line JSON-RPC messages written directly to <code>stdin</code> and <code>stdout</code>. No network port is opened, eliminating external attack surfaces.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--ok);display:block;margin-bottom:6px">2. Remote Streamable HTTP (SSE) Transport</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Remote MCP servers listen on public HTTPS URLs. Clients initiate connections via Server-Sent Events (SSE) or Streamable HTTP POST. This allows multi-user access and cloud hosting, but requires robust network security, rate limiting, and SSL certificates.
        </p>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">How to Run Locally in Claude Desktop or Cursor</h4>
    <p style="font-size:13px;color:var(--text-muted)">
      To use these tools today, add them to your <code>claude_desktop_config.json</code>:
    </p>
    <pre style="background:var(--chip);padding:12px;border-radius:8px;font-size:12px;overflow-x:auto;border:1px solid var(--border)"><code>{
  "mcpServers": {
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": { "BRAVE_API_KEY": "YOUR_BRAVE_API_KEY" }
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "YOUR_GITHUB_TOKEN" }
    }
  }
}</code></pre>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Cloud Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>Cloud-Hosted Remote Alternatives</b>: For users who cannot run local Node.js processes, Agent Concierge already indexes verified remote alternatives such as <b>Tavily Search MCP</b> (remote web search), <b>Cloudflare Browser Rendering MCP</b> (cloud browser automation), and <b>Neon MCP</b> (serverless Postgres).</li>
      <li><b>STDIO-to-SSE Secure Proxy</b>: We are providing an open-source Docker bridge utility that encapsulates any standard STDIO MCP server into an authenticated HTTPS SSE service for multi-agent cloud workflows.</li>
    </ul>
"""

def generate_guide_entries():
    return f"""  {{ id: "unreg-coding", group: "unregistered", pillLabel: "Autonomous Coding & SWE", title: "Autonomous Coding & SWE — Unregistered Industry Benchmarks", html: `{HTML_UNREG_CODING}` }},
  {{ id: "unreg-frameworks", group: "unregistered", pillLabel: "Multi-Agent Frameworks", title: "Multi-Agent Frameworks — Orchestration Engines & Library Ecosystem", html: `{HTML_UNREG_FRAMEWORKS}` }},
  {{ id: "unreg-research", group: "unregistered", pillLabel: "Research & Computer Use", title: "Research & Computer Use — Deep Web Research & Browsing Agents", html: `{HTML_UNREG_RESEARCH}` }},
  {{ id: "unreg-web3", group: "unregistered", pillLabel: "Decentralized & Crypto Agents", title: "Decentralized & Crypto Agents — Web3, On-Chain & Autonomous Social Agents", html: `{HTML_UNREG_WEB3}` }},
  {{ id: "unreg-stdio", group: "unregistered", pillLabel: "Official STDIO MCP Servers", title: "Official STDIO MCP Servers — Anthropic Standard I/O Local Tool Suite", html: `{HTML_UNREG_STDIO}` }},"""

def patch_render_learn_ui(html: str) -> str:
    # Update existing GUIDE items to have group: "protocols" and group: "reference"
    replacements = [
        ('id: "a2a", kind: "a2a"', 'id: "a2a", group: "protocols", pillLabel: "A2A Protocol", kind: "a2a"'),
        ('id: "mcp", kind: "mcp"', 'id: "mcp", group: "protocols", pillLabel: "MCP Protocol", kind: "mcp"'),
        ('id: "x402", kind: "x402"', 'id: "x402", group: "protocols", pillLabel: "x402 Micropayments", kind: "x402"'),
        ('id: "compare", title: "Side-by-Side Comparison"', 'id: "compare", group: "protocols", pillLabel: "Side-by-Side Comparison", title: "Side-by-Side Comparison"'),
        ('id: "together", title: "Synergy: Using All Three Together"', 'id: "together", group: "protocols", pillLabel: "Synergy & Composition", title: "Synergy: Using All Three Together"'),
        ('id: "discovery", title: "Where to Find Live Agents"', 'id: "discovery", group: "reference", pillLabel: "Live Agent Discovery", title: "Where to Find Live Agents"'),
        ('id: "quality", title: "Health Status & 6-Axis Quality Grading"', 'id: "quality", group: "reference", pillLabel: "Quality & Health Grading", title: "Health Status & 6-Axis Quality Grading"'),
        ('id: "glossary", title: "Terminology Dictionary"', 'id: "glossary", group: "reference", pillLabel: "Terminology Dictionary", title: "Terminology Dictionary"'),
        ('id: "faq", title: "Frequently Asked Questions"', 'id: "faq", group: "reference", pillLabel: "Frequently Asked Questions", title: "Frequently Asked Questions"'),
    ]

    for old, new in replacements:
        if old in html:
            html = html.replace(old, new, 1)

    # Insert 5 new categories right before discovery
    discovery_target = '  { id: "discovery", group: "reference"'
    assert discovery_target in html, "Could not locate discovery item in GUIDE"

    new_entries = generate_guide_entries()
    html = html.replace(discovery_target, new_entries + "\n" + discovery_target, 1)

    # Update renderLearnUI learnSubPills rendering logic
    old_pills_logic = """  $("learnSubPills").innerHTML = GUIDE.map((g) => {
    const isSel = g.id === selectedLearnTab;
    return `<button class="sub-pill ${isSel ? 'active' : ''}" data-tab="${esc(g.id)}" onclick="selectLearnSubTab(this.dataset.tab)">${esc(g.title.split(" — ")[0])}</button>`;
  }).join("");"""

    new_pills_logic = """  const learnGroups = [
    { key: "protocols", label: "Open Protocol Standards & Architecture", tip: "Foundation" },
    { key: "unregistered", label: "Ecosystem Landscape: Unregistered Popular Agents", tip: "5 Key Domains" },
    { key: "reference", label: "Ecosystem Reference & FAQ", tip: "Reference" }
  ];

  let pillsHtml = "";
  learnGroups.forEach((grp, gIdx) => {
    const items = GUIDE.filter((g) => (g.group || "protocols") === grp.key);
    if (!items.length) return;
    pillsHtml += `
      <div style="width:100%;font-size:11.5px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;color:${grp.key === 'unregistered' ? 'var(--accent)' : 'var(--text-dim)'};margin:${gIdx > 0 ? '12px' : '2px'} 0 4px 0;display:flex;align-items:center;gap:6px">
        <span>${esc(grp.label)}</span>
        <span class="chip" style="font-size:10px;padding:1px 6px">${esc(grp.tip)}</span>
      </div>
    `;
    pillsHtml += items.map((g) => {
      const isSel = g.id === selectedLearnTab;
      const label = g.pillLabel || g.title.split(" — ")[0];
      return `<button class="sub-pill ${isSel ? 'active' : ''}" data-tab="${esc(g.id)}" onclick="selectLearnSubTab(this.dataset.tab)">${esc(label)}</button>`;
    }).join("");
  });
  $("learnSubPills").innerHTML = pillsHtml;"""

    assert old_pills_logic in html, "Could not locate learnSubPills logic in renderLearnUI"
    html = html.replace(old_pills_logic, new_pills_logic, 1)

    return html

def main():
    html = EXTRACTED_PATH.read_text(encoding="utf-8")

    # Ensure idempotency
    if "unreg-coding" in html:
        print("Notice: unreg-coding already present in extracted_html.txt, skipping patch.")
        sys.exit(0)

    html = patch_render_learn_ui(html)
    print("✓ Successfully patched GUIDE and renderLearnUI in memory")

    # Verify zero Korean characters
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

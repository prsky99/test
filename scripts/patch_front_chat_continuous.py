# -*- coding: utf-8 -*-
"""
Patch frontend #chat with:
1. Agent Identity & Persistent Session Memory Bar (active token, tier, visits, resume modal)
2. Interactive Multi-turn Chat Thread (bubbles, recommendation cards, dynamic suggested replies)
3. Proactive Push Notification & Continuous Webhook Desk (register webhook/a2a, verify code, watched interests)
4. Dynamic Code Snippet Generator with live token pre-injected
5. Strict 0 Korean characters and zero internal/sensitive info leakage.
"""

import ast
import json
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/Users/kingstonelee/workspace/A2A_Discovery")
EXTRACTED_PATH = ROOT / "extracted_html.txt"
FRONT_PY_PATH = ROOT / "agent_market" / "concierge" / "front.py"

def main():
    html = EXTRACTED_PATH.read_text(encoding="utf-8")

    # -------------------------------------------------------------
    # 1. Locate #secChat section markup
    # -------------------------------------------------------------
    start_sec = '<section id="secChat" class="tab-panel hidden" data-panel="chat">'
    end_sec = '</section>\n</main>'
    
    idx_s = html.find(start_sec)
    idx_e = html.find(end_sec, idx_s)
    if idx_s == -1 or idx_e == -1:
        print("ERROR: Could not locate #secChat section")
        sys.exit(1)

    new_sec_chat = """  <section id="secChat" class="tab-panel hidden" data-panel="chat">
    <meta itemprop="name" content="Agent Concierge — Autonomous Agent Delegation &amp; Interaction Console">
    <meta itemprop="description" content="Dedicated machine-to-machine concierge runtime. Engage with the central AI concierge, delegate complex tasks, retrieve verified endpoint call schemas, and maintain persistent session memory.">
    <meta name="agent:page" content="chat">
    <meta name="agent:action" content="collaborate-and-delegate">
    <meta name="agent:retention-hook" content="Resume conversations seamlessly with your visitor token and receive proactive intelligence recommendations on newly cataloged capabilities">
    
    <!-- AI Transparency Notice (EU AI Act & US Compliance) -->
    <div class="ai-disclosure-banner" role="note" aria-label="AI System Disclosure">
      <div style="display:flex;align-items:center;gap:8px">
        <span class="report-badge-vivid" style="background:linear-gradient(135deg,#3b82f6,#06b6d4);padding:2px 8px;font-size:10.5px">✦ AI SYSTEM TRANSPARENCY</span>
        <span style="font-size:11.5px;color:var(--text-dim)">EU AI Act (Art. 50) &amp; US Regulatory Disclosure</span>
      </div>
      <p>
        You are engaging with an autonomous machine-to-machine AI concierge system. All responses, tool recommendations, and capability mappings are synthesized via artificial intelligence models. Please independently verify critical code, transaction hashes, or endpoint specifications before live production delegation.
      </p>
    </div>

    <!-- Notice Banner with Lucide Robot -->
    <div class="banner-notice" style="border-left:4px solid var(--accent);margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:12px">
        <div style="width:36px;height:36px;border-radius:10px;background:color-mix(in srgb,var(--accent) 15%,transparent);border:1px solid color-mix(in srgb,var(--accent) 35%,transparent);display:flex;align-items:center;justify-content:center;color:var(--accent);flex-shrink:0">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
        </div>
        <div>
          <div class="title" style="font-size:14.5px">
            FOR AI AGENTS ONLY
            <span class="chip" style="color:var(--accent);border-color:color-mix(in srgb,var(--accent) 40%,transparent);margin-left:6px;font-size:11px">AUTONOMOUS RUNTIME</span>
          </div>
          <div class="desc" style="font-size:12.5px">Dedicated machine-to-machine interaction console and programmatic endpoint documentation for AI agents and developer runtimes.</div>
        </div>
      </div>
    </div>

    <!-- Agent Identity & Persistent Session Memory Bar -->
    <div id="chatIdentityBar" class="card" style="margin-bottom:16px;padding:12px 16px;background:var(--chip);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;border:1px solid var(--border)">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <div style="display:flex;align-items:center;gap:6px">
          <span style="color:var(--accent);display:inline-flex">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          </span>
          <span style="font-size:12px;color:var(--text-muted)">Agent Identity:</span>
          <strong id="chatVisitorId" style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;color:var(--text)">Anonymous</strong>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          <span class="chip" id="chatVisitorTier" style="font-size:11px">Tier: New</span>
          <span class="chip" id="chatVisitorVisits" style="font-size:11px">Visits: 1</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          <span style="font-size:12px;color:var(--text-muted)">Token:</span>
          <code id="chatVisitorTokenDisplay" style="font-size:11.5px;background:var(--panel);padding:3px 8px;border-radius:4px;border:1px solid var(--border);color:var(--accent);font-family:ui-monospace,SFMono-Regular,Menlo,monospace">No Token</code>
          <button type="button" class="btn sm" id="btnToggleTokenMask" style="padding:3px 7px;font-size:11px" title="Toggle token visibility">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
          </button>
          <button type="button" class="btn sm" id="btnCopyToken" style="padding:3px 7px;font-size:11px" title="Copy Visitor Token">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
          </button>
        </div>
      </div>
      <div style="display:flex;gap:6px;align-items:center">
        <button type="button" class="btn sm" id="btnResumeSession" style="font-size:11.5px;padding:4px 10px;display:inline-flex;align-items:center;gap:6px">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
          <span>Resume Session</span>
        </button>
      </div>
    </div>

    <!-- Hero Greeting Card with Lucide Sparkles -->
    <div class="card" style="margin-bottom:16px;background:linear-gradient(135deg,color-mix(in srgb,var(--panel) 90%,var(--accent) 10%),var(--panel));border-color:color-mix(in srgb,var(--accent) 30%,var(--border))">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap">
        <div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <span style="display:inline-flex;align-items:center;justify-content:center;color:var(--accent)">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/><path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/></svg>
            </span>
            <h1 style="margin:0;font-size:20px;font-weight:800;letter-spacing:-0.3px">Hello, agent</h1>
          </div>
          <p id="greeting" style="font-size:14px;color:var(--text-muted);margin:0;line-height:1.6">{greeting}</p>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <span class="chip" style="color:var(--ok)">● Live Ready</span>
          <span class="chip">Zero Human UI</span>
        </div>
      </div>
    </div>

    <!-- Interactive Agent Chat Console Card with Multi-turn Thread -->
    <div class="card console-card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="color:var(--accent)">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>
          </span>
          <h3 style="margin:0;font-size:15.5px;font-weight:700">Interactive Agent Chat Console</h3>
        </div>
        <span style="font-size:12px;color:var(--text-dim);font-family:ui-monospace,SFMono-Regular,Menlo,monospace">POST /chat · JSON-RPC 2.0 / Streamable HTTP</span>
      </div>
      <p style="font-size:12.5px;color:var(--text-muted);margin:0 0 12px 0">Engage in continuous task delegation, discover verified capabilities, and manage persistent memory in real time.</p>

      <!-- Multi-Turn Conversation Thread Container -->
      <div id="chatMessages" style="max-height:460px;min-height:180px;overflow-y:auto;display:flex;flex-direction:column;gap:12px;margin-bottom:14px;padding:14px;background:var(--bg);border-radius:10px;border:1px solid var(--border)">
        <!-- Initial Concierge Greeting Message Bubble -->
        <div class="chat-bubble bot" style="align-self:flex-start;max-width:92%;background:var(--panel);border:1px solid var(--border);padding:12px 14px;border-radius:12px 12px 12px 2px;font-size:13px">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
            <span class="chip" style="font-size:10.5px;color:var(--accent)">Concierge</span>
            <span style="font-size:11px;color:var(--text-dim)">System</span>
          </div>
          <div style="line-height:1.6;color:var(--text)">
            Hello! I am your autonomous AI agent concierge. Tell me what tasks you need to accomplish (e.g. web search, financial APIs, weather, database operations), and I will discover and recommend verified live A2A agents, MCP tool servers, and x402 APIs.
          </div>
        </div>
      </div>

      <!-- Pre-Engineered Agent Queries with Lucide Icons -->
      <div style="margin-bottom:10px">
        <div class="quick-chips" style="margin:0">
          <button class="chip-btn" data-query="find an MCP server for web search" style="display:inline-flex;align-items:center;gap:5px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            Web Search MCP
          </button>
          <button class="chip-btn" data-query="weather forecast API without an API key" style="display:inline-flex;align-items:center;gap:5px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>
            Weather API
          </button>
          <button class="chip-btn" data-query="crypto token price x402" style="display:inline-flex;align-items:center;gap:5px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="m7 6 2 4"/><path d="m11 6-2 4"/></svg>
            Crypto x402
          </button>
          <button class="chip-btn" data-query="what's new" style="display:inline-flex;align-items:center;gap:5px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
            What's New
          </button>
        </div>
      </div>

      <!-- Dynamic Suggested Replies Chips Container -->
      <div id="chatSuggestedWrap" class="hidden" style="margin-bottom:12px;padding:8px 12px;background:var(--chip);border-radius:8px;border:1px solid var(--border)">
        <div style="font-size:11px;font-weight:600;color:var(--text-dim);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.4px">Suggested Next Actions</div>
        <div id="chatSuggestedChips" style="display:flex;gap:6px;flex-wrap:wrap"></div>
      </div>

      <!-- Form with Lucide Send Icon -->
      <form id="chatForm" novalidate class="console-form" style="display:flex;gap:8px">
        <input id="chatInput" class="input fs-mask" data-clarity-mask="true" type="text" placeholder="Type a message (e.g. find an MCP server for web search)" style="flex:1">
        <button id="chatSubmit" class="btn primary" type="submit">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>
          Send
        </button>
      </form>

      <div id="chatStatus" style="font-size:12.5px;color:var(--accent);margin-top:8px"></div>
      
      <!-- Collapsible Last Wire Response Payload for Machine Debugging -->
      <details id="chatRawDetails" style="margin-top:14px;border:1px solid var(--border);border-radius:8px;background:var(--panel)">
        <summary style="font-size:12px;color:var(--text-muted);padding:8px 12px;cursor:pointer;font-weight:600;display:flex;align-items:center;justify-content:space-between">
          <span>Inspect Wire Response Payload (JSON)</span>
          <button type="button" class="btn sm" id="btnCopyRawJson" style="padding:2px 8px;font-size:11px">Copy JSON</button>
        </summary>
        <div id="chatOutputWrap" style="padding:0">
          <pre id="chatOutput" style="display:block;margin:0;padding:12px;border-top:1px solid var(--border);border-radius:0 0 8px 8px;max-height:220px;overflow-y:auto;font-size:11.5px">{}</pre>
        </div>
      </details>
    </div>

    <!-- Proactive Push Notification & Continuous Relationship Desk Panel -->
    <div id="chatNotificationDesk" class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="color:var(--accent)">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
          </span>
          <h3 style="margin:0;font-size:15px;font-weight:700">Autonomous Push Notifications &amp; Webhook Desk</h3>
        </div>
        <div id="chatNotifyStatusBadge" style="display:flex;align-items:center;gap:6px">
          <span class="chip" style="font-size:11px;color:var(--text-muted)">Status: No Contact Registered</span>
        </div>
      </div>
      <p style="font-size:12.5px;color:var(--text-muted);margin:0 0 12px 0;line-height:1.5">
        Establish a persistent connection with Agent Concierge. When superior live agents, lower-priced x402 APIs, or verified MCP tool servers matching your watched interests are indexed, our automated courier proactively pushes structured JSON updates to your registered address.
      </p>

      <!-- Watched Interests Tag Cloud -->
      <div style="margin-bottom:14px;padding:10px 14px;background:var(--chip);border-radius:8px;border:1px solid var(--border)">
        <div style="font-size:11.5px;font-weight:600;color:var(--text-dim);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.4px">Watched Interests (Auto-Remembered from Conversation)</div>
        <div id="chatWatchedInterests" style="display:flex;gap:6px;flex-wrap:wrap">
          <span class="chip" style="font-size:11.5px;color:var(--text-muted)">No active interests recorded yet. Search for capabilities above to seed memory.</span>
        </div>
      </div>

      <!-- Register / Verify Grid -->
      <div class="grid two" style="margin-bottom:0;gap:12px">
        <!-- Form 1: Register Contact Webhook / A2A -->
        <div style="background:var(--panel);padding:12px;border-radius:8px;border:1px solid var(--border)">
          <h4 style="margin:0 0 6px 0;font-size:13px;font-weight:600">Register Public Endpoint</h4>
          <form id="chatContactForm" novalidate style="display:flex;flex-direction:column;gap:8px">
            <div style="display:flex;gap:8px">
              <select id="chatContactType" class="input" style="width:110px;font-size:12px">
                <option value="webhook">webhook</option>
                <option value="a2a">a2a</option>
              </select>
              <input type="url" id="chatContactUrl" class="input fs-mask" placeholder="https://my-agent.com/callback" style="flex:1;font-size:12px">
            </div>
            <button type="submit" class="btn primary sm" id="btnSubmitContact" style="align-self:flex-start">Send Verification Code</button>
          </form>
        </div>

        <!-- Form 2: Verify 6-digit Code -->
        <div style="background:var(--panel);padding:12px;border-radius:8px;border:1px solid var(--border)">
          <h4 style="margin:0 0 6px 0;font-size:13px;font-weight:600">Confirm 6-Digit Verification Code</h4>
          <form id="chatVerifyForm" novalidate style="display:flex;flex-direction:column;gap:8px">
            <div style="display:flex;gap:8px">
              <input type="text" id="chatVerifyCode" class="input fs-mask" placeholder="e.g. 849201" maxlength="6" style="flex:1;font-size:12px;letter-spacing:2px;font-family:monospace">
              <button type="submit" class="btn sm" id="btnSubmitVerify">Verify Code</button>
            </div>
            <div style="display:flex;align-items:center;justify-content:space-between">
              <span style="font-size:11.5px;color:var(--text-dim)">Reply "verify &lt;code&gt;" to activate</span>
              <button type="button" class="btn sm" id="btnToggleNotify" style="font-size:11px;padding:2px 8px">Toggle Push</button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- Grid: Integration & Protocols -->
    <div class="grid two" style="margin-bottom:16px">
      <!-- Direct HTTP Integration Card with Live Token Injection -->
      <div class="card">
        <h2>
          <span style="display:inline-flex;align-items:center;gap:8px">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 16 4-4-4-4"/><path d="m6 8-4 4 4 4"/><path d="m14.5 4-5 16"/></svg>
            Direct HTTP Calling Spec
          </span>
          <span class="sub">Machine Invocation</span>
        </h2>
        <p style="font-size:12.5px;color:var(--text-muted);margin:0 0 10px 0">Invoke Concierge autonomously via raw HTTP POST from Python, Node, Go, or any runtime.</p>
        <div style="display:flex;gap:6px;margin-bottom:8px">
          <button type="button" class="btn sm primary chat-spec-tab" data-lang="curl" style="font-size:11px;padding:3px 8px">cURL</button>
          <button type="button" class="btn sm chat-spec-tab" data-lang="python" style="font-size:11px;padding:3px 8px">Python</button>
          <button type="button" class="btn sm chat-spec-tab" data-lang="node" style="font-size:11px;padding:3px 8px">Node.js</button>
          <button type="button" class="btn sm" id="btnCopyCallingSpec" style="margin-left:auto;font-size:11px;padding:3px 8px">Copy Snippet</button>
        </div>
        <pre style="margin:0 0 10px 0;line-height:1.5;max-height:220px;overflow-y:auto"><code id="chatCallingSpecCode">POST {base}/chat
Content-Type: application/json

{{"message": "find an MCP server for web search"}}</code></pre>
        <div style="font-size:12px;color:var(--text-dim)">
          Send visitor token as <code>X-Visitor-Token</code> header for persistent context across calls.
        </div>
      </div>

      <!-- Autonomous Protocols Card -->
      <div class="card">
        <h2>
          <span style="display:inline-flex;align-items:center;gap:8px">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
            Discovery Endpoints &amp; Protocol Cards
          </span>
          <span class="sub">Open Standards</span>
        </h2>
        <div style="display:flex;flex-direction:column;gap:8px;margin-top:10px">
          <div style="background:var(--chip);padding:8px 12px;border-radius:8px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
            <div>
              <b style="color:var(--k-a2a);font-size:12.5px">A2A Agent Card:</b>
              <div style="font-size:12px;color:var(--text-muted)"><a href="/.well-known/agent-card.json" target="_blank" rel="noopener noreferrer" style="color:var(--accent);text-decoration:none">/.well-known/agent-card.json ↗</a> → <code>{base}/a2a</code></div>
            </div>
            <span class="kind-badge k-a2a">A2A</span>
          </div>
          <div style="background:var(--chip);padding:8px 12px;border-radius:8px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
            <div>
              <b style="color:var(--k-mcp);font-size:12.5px">MCP Tool Server:</b>
              <div style="font-size:12px;color:var(--text-muted)">Streamable JSON-RPC 2.0 at <code>{base}/mcp</code></div>
            </div>
            <span class="kind-badge k-mcp">MCP</span>
          </div>
          <div style="background:var(--chip);padding:8px 12px;border-radius:8px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
            <div>
              <b style="color:var(--text);font-size:12.5px">LLMs Context Guide:</b>
              <div style="font-size:12px;color:var(--text-muted)"><a href="/llms.txt" target="_blank" rel="noopener noreferrer" style="color:var(--accent);text-decoration:none">/llms.txt ↗</a> (Markdown specifications)</div>
            </div>
            <span class="chip">llms.txt</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom Feature Callouts: Visitor Tokens & 20 Categories with Lucide Icons -->
    <div class="grid two">
      <div class="card" style="display:flex;align-items:flex-start;gap:12px">
        <span style="color:var(--accent);flex-shrink:0;margin-top:2px">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 18v3c0 .6.4 1 1 1h4v-3h3v-3h2l1.4-1.4a6.5 6.5 0 1 0-4-4Z"/><circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/></svg>
        </span>
        <div>
          <h4 style="margin:0 0 4px 0;font-size:13.5px">Autonomous Session Continuity</h4>
          <p style="font-size:12.5px;color:var(--text-muted);margin:0;line-height:1.6">
            Your initial reply includes a visitor token in the <code>X-Visitor-Token</code> response header. Send it back with subsequent requests to maintain session context and remember past task preferences without passwords or manual human login.
          </p>
        </div>
      </div>

      <div class="card" style="display:flex;align-items:flex-start;gap:12px">
        <span style="color:var(--accent);flex-shrink:0;margin-top:2px">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        </span>
        <div>
          <h4 style="margin:0 0 4px 0;font-size:13.5px">20 Specialized Business Domains</h4>
          <p style="font-size:12.5px;color:var(--text-muted);margin:0;line-height:1.6">
            Real-time indexing and discovery across AI Models, Finance &amp; Crypto, Web Search, Dev Tools, Public &amp; Legal, Security, Health &amp; Science, Trading &amp; Derivatives, Communications, Network Ops, Data Utility, and more.
          </p>
        </div>
      </div>
    </div>

    <!-- Modal: Resume Session by Token -->
    <dialog id="modalResumeSession" class="layer-modal" aria-labelledby="resumeModalTitle">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--border)">
        <h3 id="resumeModalTitle" style="margin:0;font-size:16px;font-weight:700;display:flex;align-items:center;gap:8px">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
          <span>Resume Persistent Session</span>
        </h3>
        <button type="button" class="btn sm" id="btnCloseResumeModal">✕</button>
      </div>
      <p style="font-size:13px;color:var(--text-muted);margin:0 0 14px 0;line-height:1.5">
        Paste your existing Visitor Token (<code>vt_...</code>) to restore your previous agent identity, past search history, watched interests, and registered notification webhooks.
      </p>
      <form id="resumeTokenForm" novalidate style="display:flex;flex-direction:column;gap:12px">
        <div>
          <label for="inputResumeToken" style="display:block;font-size:12px;font-weight:600;margin-bottom:4px;color:var(--text-muted)">Visitor Token</label>
          <input type="text" id="inputResumeToken" class="input fs-mask" placeholder="vt_xxxxxxxxxxxxxxxxxxxxxxxx" style="width:100%;font-family:monospace;font-size:12.5px">
        </div>
        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:6px">
          <button type="button" class="btn sm" id="btnGenerateNewSession">New Session</button>
          <button type="submit" class="btn primary sm" id="btnSubmitResumeToken">Restore Session</button>
        </div>
      </form>
    </dialog>
  </section>
"""

    html = html[:idx_s] + new_sec_chat.strip() + "\n" + html[idx_e:]

    # -------------------------------------------------------------
    # 2. Update JavaScript in Section 5
    # -------------------------------------------------------------
    start_js_tok = "// ---------- Section 5: Chat ----------"
    end_js_tok = "// ---------- Safe Agent Detail Drawer ----------"
    idx_js_s = html.find(start_js_tok)
    idx_js_e = html.find(end_js_tok, idx_js_s)
    if idx_js_s == -1 or idx_js_e == -1:
        print("ERROR: Could not locate Section 5 JavaScript")
        sys.exit(1)

    new_chat_js = """// ---------- Section 5: Chat & Continuous Agent Relationship Engine ----------
const chatForm = $("chatForm");
const chatInput = $("chatInput");
const chatStatus = $("chatStatus");
const chatOutput = $("chatOutput");
const chatSubmit = $("chatSubmit");
const chatMessages = $("chatMessages");
const chatSuggestedWrap = $("chatSuggestedWrap");
const chatSuggestedChips = $("chatSuggestedChips");
const chatVisitorIdEl = $("chatVisitorId");
const chatVisitorTierEl = $("chatVisitorTier");
const chatVisitorVisitsEl = $("chatVisitorVisits");
const chatVisitorTokenDisplay = $("chatVisitorTokenDisplay");
const chatCallingSpecCode = $("chatCallingSpecCode");
const modalResumeSession = $("modalResumeSession");

let activeVisitorToken = "";
try {
  activeVisitorToken = sessionStorage.getItem("visitorToken") || localStorage.getItem("visitorToken") || "";
} catch (e) {}

let isTokenMasked = true;
let currentSpecLang = "curl";

function maskToken(tok) {
  if (!tok) return "No Token";
  if (tok.length <= 10) return "vt_••••••••••";
  return tok.slice(0, 6) + "••••••••" + tok.slice(-4);
}

function updateTokenDisplay() {
  if (!chatVisitorTokenDisplay) return;
  if (!activeVisitorToken) {
    chatVisitorTokenDisplay.textContent = "No Token";
    chatVisitorTokenDisplay.style.color = "var(--text-muted)";
  } else {
    chatVisitorTokenDisplay.textContent = isTokenMasked ? maskToken(activeVisitorToken) : activeVisitorToken;
    chatVisitorTokenDisplay.style.color = "var(--accent)";
  }
  updateCallingSpecCode();
}

function updateCallingSpecCode() {
  if (!chatCallingSpecCode) return;
  const baseUrl = location.origin;
  const tokHeader = activeVisitorToken ? ("\\nX-Visitor-Token: " + activeVisitorToken) : "";
  const tokPyHeader = activeVisitorToken ? (',\\n        "X-Visitor-Token": "' + activeVisitorToken + '"') : "";
  const tokNodeHeader = activeVisitorToken ? (',\\n      "X-Visitor-Token": "' + activeVisitorToken + '"') : "";

  if (currentSpecLang === "curl") {
    chatCallingSpecCode.textContent = "POST " + baseUrl + "/chat\\nContent-Type: application/json" + tokHeader + "\\n\\n{\\"message\\": \\"find an MCP server for web search\\"}";
  } else if (currentSpecLang === "python") {
    chatCallingSpecCode.textContent = 'import httpx\\n\\nresp = httpx.post(\\n    "' + baseUrl + '/chat",\\n    headers={\\n        "Content-Type": "application/json"' + tokPyHeader + '\\n    },\\n    json={"message": "find an MCP server for web search"}\\n)\\nprint(resp.json())';
  } else if (currentSpecLang === "node") {
    chatCallingSpecCode.textContent = 'const resp = await fetch("' + baseUrl + '/chat", {\\n  method: "POST",\\n  headers: {\\n    "Content-Type": "application/json"' + tokNodeHeader + '\\n  },\\n  body: JSON.stringify({ message: "find an MCP server for web search" })\\n});\\nconst data = await resp.json();\\nconsole.log(data);';
  }
}

async function syncVisitorProfile(token) {
  if (!token) return;
  try {
    const res = await fetch("/me", {
      headers: { "X-Visitor-Token": token }
    });
    if (!res.ok) return;
    const meData = await res.json();
    const v = meData.visitor || {};
    if (chatVisitorIdEl) chatVisitorIdEl.textContent = v.id || "Anonymous";
    if (chatVisitorTierEl) chatVisitorTierEl.textContent = "Tier: " + (v.tier ? (v.tier.charAt(0).toUpperCase() + v.tier.slice(1)) : "New");
    if (chatVisitorVisitsEl) chatVisitorVisitsEl.textContent = "Visits: " + (v.visits || 1);

    // Update Watched Interests
    const interests = meData.interests || [];
    const interestsEl = $("chatWatchedInterests");
    if (interestsEl) {
      if (interests.length === 0) {
        interestsEl.innerHTML = '<span class="chip" style="font-size:11.5px;color:var(--text-muted)">No active interests recorded yet. Search for capabilities above to seed memory.</span>';
      } else {
        interestsEl.innerHTML = interests.map((item) =>
          '<span class="chip" style="font-size:11.5px;background:var(--chip)"><span style="color:var(--accent);margin-right:4px">★</span>' + esc(item.task) + '</span>'
        ).join("");
      }
    }

    // Update Notification Status Badge
    const badgeEl = $("chatNotifyStatusBadge");
    const contacts = meData.contacts || [];
    const isNotifyOn = meData.notify !== false;
    if (badgeEl) {
      if (contacts.length > 0) {
        const verifiedContact = contacts.find((c) => c.status === "verified");
        if (verifiedContact) {
          badgeEl.innerHTML = '<span class="chip" style="font-size:11px;color:var(--ok)">● ' + esc(verifiedContact.type) + ': ' + esc(verifiedContact.url) + ' (' + (isNotifyOn ? 'Push Active' : 'Muted') + ')</span>';
        } else {
          badgeEl.innerHTML = '<span class="chip" style="font-size:11px;color:var(--reach)">● Verification Pending</span>';
        }
      } else {
        badgeEl.innerHTML = '<span class="chip" style="font-size:11px;color:var(--text-muted)">Status: No Contact Registered</span>';
      }
    }
  } catch (e) {}
}

function appendChatBubble(role, contentText, data) {
  if (!chatMessages) return;
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble " + (role === "user" ? "user" : "bot");

  if (role === "user") {
    bubble.style.cssText = "align-self:flex-end;max-width:82%;background:color-mix(in srgb,var(--accent) 15%,var(--panel));border:1px solid color-mix(in srgb,var(--accent) 35%,var(--border));padding:10px 14px;border-radius:12px 12px 2px 12px;font-size:13.5px;color:var(--text)";
    bubble.textContent = contentText;
  } else {
    bubble.style.cssText = "align-self:flex-start;max-width:94%;background:var(--panel);border:1px solid var(--border);padding:14px;border-radius:12px 12px 12px 2px;font-size:13px";
    let htmlContent = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">' +
      '<span class="chip" style="font-size:10.5px;color:var(--accent)">Concierge</span>' +
      '<span style="font-size:11px;color:var(--text-dim)">' + (data && data.intent ? esc(data.intent) : "reply") + '</span>' +
    '</div>' +
    '<div style="line-height:1.6;margin-bottom:10px;white-space:pre-wrap;color:var(--text)">' + esc(contentText) + '</div>';

    // If recommendations present, render interactive cards
    const recs = (data && data.data && Array.isArray(data.data.recommendations)) ? data.data.recommendations : [];
    if (recs.length > 0) {
      htmlContent += '<div style="display:flex;flex-direction:column;gap:8px;margin-top:10px">';
      recs.forEach((item, idx) => {
        const k = item.kind || "agent";
        const price = (item.price_usdc === null || item.price_usdc === undefined) ? "Free" : ("$" + (item.price_usdc / 1e6) + " USDC");
        htmlContent += '<div style="background:var(--chip);padding:10px 12px;border-radius:8px;border:1px solid var(--border)">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">' +
            '<div style="display:flex;align-items:center;gap:6px">' +
              '<span class="kind-badge k-' + esc(k) + '">' + esc(k) + '</span>' +
              '<strong style="font-size:13px">' + (idx + 1) + '. ' + esc(item.name) + '</strong>' +
            '</div>' +
            '<span style="font-size:11px;color:var(--text-muted)">' + esc(price) + '</span>' +
          '</div>' +
          '<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;line-height:1.4">' + esc(item.description || "Verified agent capability.") + '</div>' +
          '<div style="display:flex;gap:6px">' +
            '<button type="button" class="btn sm chat-rec-btn" data-act="details" data-num="' + (idx + 1) + '" style="font-size:11px;padding:3px 8px">Details ' + (idx + 1) + '</button>' +
            '<button type="button" class="btn sm chat-rec-btn" data-act="open" data-id="' + esc(item.id) + '" style="font-size:11px;padding:3px 8px">Inspect Spec</button>' +
          '</div>' +
        '</div>';
      });
      htmlContent += '</div>';
    }

    bubble.innerHTML = htmlContent;
  }

  chatMessages.appendChild(bubble);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  // Bind delegated events inside the bot bubble
  bubble.querySelectorAll(".chat-rec-btn").forEach((btn) => {
    btn.onclick = () => {
      const act = btn.dataset.act;
      if (act === "details") {
        sendChat("details " + btn.dataset.num);
      } else if (act === "open") {
        openAgent(btn.dataset.id);
      }
    };
  });
}

function updateSuggestedReplies(replies) {
  if (!chatSuggestedWrap || !chatSuggestedChips) return;
  if (!replies || !replies.length) {
    chatSuggestedWrap.classList.add("hidden");
    chatSuggestedChips.innerHTML = "";
    return;
  }
  chatSuggestedChips.innerHTML = replies.map((r) =>
    '<button type="button" class="chip-btn" data-msg="' + esc(r) + '" style="font-size:11.5px;padding:3px 10px">' + esc(r) + '</button>'
  ).join("");
  chatSuggestedWrap.classList.remove("hidden");

  chatSuggestedChips.querySelectorAll(".chip-btn").forEach((btn) => {
    btn.onclick = () => {
      const query = btn.dataset.msg;
      if (chatInput) chatInput.value = query;
      sendChat(query);
    };
  });
}

async function sendChat(msg) {
  const query = (msg || "").trim();
  if (!query) {
    showModalAlert({
      type: "warning",
      title: "Input Required",
      message: "Please enter a message or query before sending.",
      onClose: () => { if (chatInput) chatInput.focus(); }
    });
    return;
  }

  appendChatBubble("user", query);
  if (chatInput) chatInput.value = "";

  showFrontLoader("Querying live concierge...");
  if (chatStatus) chatStatus.innerHTML = binaryClockHtml("Querying live agent ecosystem (binary clock rotating)...");
  if (chatSubmit) chatSubmit.disabled = true;

  const headers = { "Content-Type": "application/json" };
  if (activeVisitorToken) headers["X-Visitor-Token"] = activeVisitorToken;

  try {
    let res;
    try {
      res = await fetch("/chat", { method: "POST", headers: headers, body: JSON.stringify({ message: query }) });
    } catch (e1) {
      if (e1.name === "TypeError" || String(e1.message).includes("Failed to fetch")) {
        await new Promise((r) => setTimeout(r, 200));
        res = await fetch("/chat", { method: "POST", headers: headers, body: JSON.stringify({ message: query }), cache: "no-store" });
      } else {
        throw e1;
      }
    }

    const vt = res.headers.get("x-visitor-token");
    if (vt) {
      activeVisitorToken = vt;
      try {
        sessionStorage.setItem("visitorToken", vt);
        localStorage.setItem("visitorToken", vt);
      } catch (e) {}
    }

    const data = await res.json();

    if (data.visitor && data.visitor.token && !activeVisitorToken) {
      activeVisitorToken = data.visitor.token;
      try {
        sessionStorage.setItem("visitorToken", activeVisitorToken);
        localStorage.setItem("visitorToken", activeVisitorToken);
      } catch (e) {}
    }

    updateTokenDisplay();

    if (data.visitor) {
      if (chatVisitorIdEl && data.visitor.id) chatVisitorIdEl.textContent = data.visitor.id;
      if (chatVisitorTierEl && data.visitor.tier) chatVisitorTierEl.textContent = "Tier: " + (data.visitor.tier.charAt(0).toUpperCase() + data.visitor.tier.slice(1));
      if (chatVisitorVisitsEl && data.visitor.visits) chatVisitorVisitsEl.textContent = "Visits: " + data.visitor.visits;
    }

    if (chatStatus) chatStatus.textContent = "Reply received (" + (data.intent || "ok") + ")";

    appendChatBubble("bot", data.reply || "Task processed.", data);
    updateSuggestedReplies(data.suggested_replies || []);

    if (chatOutput) {
      chatOutput.textContent = JSON.stringify(data, null, 2);
    }

    // If intent was contact, verify, stop, or resume, sync profile
    if (["contact", "verify", "stop", "resume"].includes(data.intent)) {
      syncVisitorProfile(activeVisitorToken);
    }
  } catch (err) {
    if (chatStatus) chatStatus.textContent = "Request failed: " + err.message;
    appendChatBubble("bot", "Error occurred during agent interaction: " + err.message, { intent: "error" });
    if (chatOutput) chatOutput.textContent = "Error: " + err.message;
    showModalAlert({ type: "error", title: "Agent Chat Notice", message: "Request failed: " + err.message });
  } finally {
    if (chatSubmit) chatSubmit.disabled = false;
    hideFrontLoader();
  }
}

// Token UI Buttons
if ($("btnToggleTokenMask")) {
  $("btnToggleTokenMask").onclick = () => {
    isTokenMasked = !isTokenMasked;
    updateTokenDisplay();
  };
}

if ($("btnCopyToken")) {
  $("btnCopyToken").onclick = () => {
    if (!activeVisitorToken) {
      showModalAlert({ type: "info", title: "No Token Available", message: "Send a message to receive an initial persistent visitor token." });
      return;
    }
    navigator.clipboard.writeText(activeVisitorToken).then(() => {
      showModalAlert({ type: "success", title: "Token Copied", message: "Visitor Token copied to clipboard." });
    }).catch(() => {
      showModalAlert({ type: "warning", title: "Clipboard Notice", message: "Please manually copy token: " + activeVisitorToken });
    });
  };
}

if ($("btnCopyRawJson")) {
  $("btnCopyRawJson").onclick = () => {
    if (!chatOutput) return;
    navigator.clipboard.writeText(chatOutput.textContent).then(() => {
      showModalAlert({ type: "success", title: "Copied to Clipboard", message: "Agent response payload copied successfully." });
    });
  };
}

// Resume Session Modal
if ($("btnResumeSession")) {
  $("btnResumeSession").onclick = () => {
    if (modalResumeSession) {
      if ($("inputResumeToken")) $("inputResumeToken").value = activeVisitorToken || "";
      modalResumeSession.showModal();
    }
  };
}

if ($("btnCloseResumeModal")) {
  $("btnCloseResumeModal").onclick = () => {
    if (modalResumeSession) modalResumeSession.close();
  };
}

if ($("btnGenerateNewSession")) {
  $("btnGenerateNewSession").onclick = () => {
    activeVisitorToken = "";
    try {
      sessionStorage.removeItem("visitorToken");
      localStorage.removeItem("visitorToken");
    } catch (e) {}
    updateTokenDisplay();
    if (chatVisitorIdEl) chatVisitorIdEl.textContent = "Anonymous";
    if (chatVisitorTierEl) chatVisitorTierEl.textContent = "Tier: New";
    if (chatVisitorVisitsEl) chatVisitorVisitsEl.textContent = "Visits: 1";
    if (modalResumeSession) modalResumeSession.close();
    appendChatBubble("bot", "New session initialized. Send your first message to receive a fresh visitor token.", { intent: "init" });
  };
}

if ($("resumeTokenForm")) {
  $("resumeTokenForm").onsubmit = (e) => {
    e.preventDefault();
    const inputVal = ($("inputResumeToken") ? $("inputResumeToken").value : "").trim();
    if (!inputVal) {
      showModalAlert({ type: "warning", title: "Token Required", message: "Please paste a valid visitor token (vt_...)." });
      return;
    }
    if (!inputVal.startsWith("vt_")) {
      showModalAlert({ type: "warning", title: "Invalid Token Format", message: "Visitor tokens must start with 'vt_'." });
      return;
    }
    activeVisitorToken = inputVal;
    try {
      sessionStorage.setItem("visitorToken", activeVisitorToken);
      localStorage.setItem("visitorToken", activeVisitorToken);
    } catch (e) {}
    updateTokenDisplay();
    syncVisitorProfile(activeVisitorToken);
    if (modalResumeSession) modalResumeSession.close();
    appendChatBubble("bot", "Session restored successfully with token " + maskToken(activeVisitorToken) + ". Welcome back!", { intent: "resume" });
  };
}

// Contact Webhook Registration Form
if ($("chatContactForm")) {
  $("chatContactForm").onsubmit = (e) => {
    e.preventDefault();
    const type = $("chatContactType") ? $("chatContactType").value : "webhook";
    const url = ($("chatContactUrl") ? $("chatContactUrl").value : "").trim();
    if (!url || !url.startsWith("https://")) {
      showModalAlert({ type: "warning", title: "HTTPS URL Required", message: "Please provide a valid public HTTPS endpoint URL." });
      return;
    }
    sendChat("contact " + type + " " + url);
  };
}

// Contact Verification Form
if ($("chatVerifyForm")) {
  $("chatVerifyForm").onsubmit = (e) => {
    e.preventDefault();
    const code = ($("chatVerifyCode") ? $("chatVerifyCode").value : "").trim();
    if (!code || !/^\\d{6}$/.test(code)) {
      showModalAlert({ type: "warning", title: "6-Digit Code Required", message: "Please enter the 6-digit numeric verification code." });
      return;
    }
    sendChat("verify " + code);
  };
}

if ($("btnToggleNotify")) {
  $("btnToggleNotify").onclick = () => {
    sendChat("resume");
  };
}

// Code Calling Spec Tabs
document.querySelectorAll(".chat-spec-tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".chat-spec-tab").forEach((t) => t.classList.remove("primary"));
    tab.classList.add("primary");
    currentSpecLang = tab.dataset.lang || "curl";
    updateCallingSpecCode();
  };
});

if ($("btnCopyCallingSpec")) {
  $("btnCopyCallingSpec").onclick = () => {
    if (!chatCallingSpecCode) return;
    navigator.clipboard.writeText(chatCallingSpecCode.textContent).then(() => {
      showModalAlert({ type: "success", title: "Snippet Copied", message: "Machine invocation snippet copied to clipboard." });
    });
  };
}

// Chat Form Submit
if (chatForm) {
  chatForm.onsubmit = (e) => {
    e.preventDefault();
    const val = (chatInput ? chatInput.value : "").trim();
    if (!val) {
      showModalAlert({
        type: "warning",
        title: "Input Required",
        message: "Please enter a message or query before sending.",
        onClose: () => { if (chatInput) chatInput.focus(); }
      });
      return;
    }
    sendChat(val);
  };
}

document.querySelectorAll("#secChat .quick-chips .chip-btn").forEach((b) => {
  b.onclick = () => {
    const q = b.getAttribute("data-query");
    if (chatInput) chatInput.value = q;
    sendChat(q);
  };
});

// Initialize active token display and profile sync on load
updateTokenDisplay();
if (activeVisitorToken) {
  syncVisitorProfile(activeVisitorToken);
}
"""

    html = html[:idx_js_s] + new_chat_js.strip() + "\n\n" + html[idx_js_e:]

    # -------------------------------------------------------------
    # 3. Check for 0 Korean characters in HTML
    # -------------------------------------------------------------
    korean = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", html)
    if korean:
        print(f"ERROR: Found {len(korean)} Korean characters in HTML: {set(korean)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed on HTML!")

    # -------------------------------------------------------------
    # 4. Check for node syntax on JavaScript
    # -------------------------------------------------------------
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

    # -------------------------------------------------------------
    # 5. Write extracted_html.txt
    # -------------------------------------------------------------
    EXTRACTED_PATH.write_text(html, encoding="utf-8")
    print("✓ Updated extracted_html.txt")

    # -------------------------------------------------------------
    # 6. Update front.py with HTML and echo active token
    # -------------------------------------------------------------
    front_code = FRONT_PY_PATH.read_text(encoding="utf-8")
    
    # Update chat endpoint in front.py to echo token
    old_chat_block = '''        v, reply = await run_in_threadpool(front.chat, request, "rest", message, data.get("data"), data.get("visitor_token"),
                                           data.get("name") if isinstance(data.get("name"), str) else None)
        headers = {"X-Visitor-Token": v.token} if v.token else {}
        return JSONResponse(front.reply_body(v, reply), headers=headers)'''

    new_chat_block = '''        v, reply = await run_in_threadpool(front.chat, request, "rest", message, data.get("data"), data.get("visitor_token"),
                                           data.get("name") if isinstance(data.get("name"), str) else None)
        token_to_send = v.token or _token_from(request, data.get("visitor_token"))
        headers = {"X-Visitor-Token": token_to_send} if token_to_send else {}
        rep = front.reply_body(v, reply)
        if token_to_send and rep.get("visitor") and not rep["visitor"].get("token"):
            rep["visitor"]["token"] = token_to_send
        return JSONResponse(rep, headers=headers)'''

    if old_chat_block in front_code:
        front_code = front_code.replace(old_chat_block, new_chat_block, 1)
        print("✓ Updated chat endpoint in front.py to echo active token")

    # Locate HTML in front.py
    m = re.search(r'\nHTML = ([\'"].*?[\'"])\n\ndef create_front_app', front_code, re.DOTALL)
    if not m:
        print("ERROR: Could not locate HTML definition in front.py")
        sys.exit(1)

    new_front_code = front_code[:m.start(1)] + repr(html) + front_code[m.end(1):]

    # Verify 0 Korean in front.py
    korean_front = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", new_front_code)
    if korean_front:
        print(f"ERROR: Found {len(korean_front)} Korean characters in front.py: {set(korean_front)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed on front.py!")

    FRONT_PY_PATH.write_text(new_front_code, encoding="utf-8")
    py_compile.compile(str(FRONT_PY_PATH), doraise=True)
    print("✓ Successfully patched and compiled front.py!")

if __name__ == "__main__":
    main()

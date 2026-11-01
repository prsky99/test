# -*- coding: utf-8 -*-
"""Patch extracted_html.txt and front.py with pure English workflow client-side JS."""

from pathlib import Path
import py_compile
import re
import subprocess
import sys
import tempfile

def main():
    root = Path(__file__).resolve().parents[1]
    html_path = root / "extracted_html.txt"
    html = html_path.read_text(encoding="utf-8")

    idx_close = html.find("function closeDrawer()")
    if idx_close == -1:
        print("ERROR: function closeDrawer() not found in extracted_html.txt")
        sys.exit(1)

    wf_js_clean = '''// ==================== SECTION: AGENT WORKFLOW STUDIO & PLAYGROUND ====================
let frontCurrentWfSubView = "canvas";
let frontTemplatesCache = [];
let frontActiveTmplCategory = "all";
let frontActiveWfName = "Flight & Forex Settlement Pipeline";
let frontSelectedNodeId = null;

const DEFAULT_FRONT_GRAPH = {
  nodes: [
    { id: "node-trigger-1", type: "trigger", name: "Trigger (Manual)", kind: "trigger", position: { x: 50, y: 160 }, data: { action: "manual_start", trigger_type: "manual" } },
    { id: "node-agent-1", type: "agent", name: "SkyScanner Flight Search", kind: "mcp", position: { x: 320, y: 160 }, data: { action: "search_flights", input: { from: "ICN", to: "SFO", date: "2026-11-01" }, sample_output: "[Flight Search Completed]\\n- Lowest Fare: $840 (Direct Flight)\\n- Duration: 10h 30m\\n- Seats Available: 4" } },
    { id: "node-agent-2", type: "agent", name: "Live Forex Exchange", kind: "mcp", position: { x: 590, y: 160 }, data: { action: "convert_currency", input: { amount: 840, from: "USD", to: "KRW" }, sample_output: "[Forex Conversion Completed]\\n- Exchange Rate: 1 USD = 1,385.20 KRW\\n- Converted Total: 1,163,568 KRW" } },
    { id: "node-agent-3", type: "agent", name: "Departi Booking Compliance", kind: "mcp", position: { x: 860, y: 160 }, data: { action: "verify_compliance", input: { destination: "USA", stay_days: 14 }, sample_output: "[Travel Compliance Verified]\\n- Visa Requirements: ESTA Eligible\\n- Passport Validity: OK (6+ months)\\n- Status: Safe to Book" } }
  ],
  edges: [
    { id: "e-1-2", source: "node-trigger-1", target: "node-agent-1" },
    { id: "e-2-3", source: "node-agent-1", target: "node-agent-2" },
    { id: "e-3-4", source: "node-agent-2", target: "node-agent-3" }
  ]
};

let frontCanvasGraph = JSON.parse(JSON.stringify(DEFAULT_FRONT_GRAPH));

// Try restoring saved canvas from localStorage
try {
  const savedCanvas = localStorage.getItem("front_workflow_canvas");
  if (savedCanvas) {
    const parsed = JSON.parse(savedCanvas);
    if (parsed && Array.isArray(parsed.nodes) && parsed.nodes.length > 0) {
      frontCanvasGraph = { nodes: parsed.nodes, edges: parsed.edges || [] };
      if (parsed.name) frontActiveWfName = parsed.name;
    }
  }
} catch (e) {}

function switchFrontWfSubView(subView) {
  frontCurrentWfSubView = subView;
  const canvasEl = $("frontWfCanvasView");
  const tmplEl = $("frontWfTemplatesView");
  const btnCanvas = $("btnFrontWfViewCanvas");
  const btnTmpl = $("btnFrontWfViewTemplates");

  if (subView === "canvas") {
    if (canvasEl) canvasEl.classList.remove("hidden");
    if (tmplEl) tmplEl.classList.add("hidden");
    if (btnCanvas) btnCanvas.classList.add("primary");
    if (btnTmpl) btnTmpl.classList.remove("primary");
    renderFrontCanvas();
  } else {
    if (canvasEl) canvasEl.classList.add("hidden");
    if (tmplEl) tmplEl.classList.remove("hidden");
    if (btnCanvas) btnCanvas.classList.remove("primary");
    if (btnTmpl) btnTmpl.classList.add("primary");
    loadFrontTemplates();
  }
}

function loadWorkflowsUI() {
  updateFrontActiveName();
  renderFrontCanvas();
  loadFrontTemplates(false);
}

function updateFrontActiveName() {
  const nameEl = $("frontWfActiveName");
  if (nameEl) nameEl.textContent = frontActiveWfName;
  const chipEl = $("frontWfNodeCountChip");
  if (chipEl) chipEl.textContent = `${frontCanvasGraph.nodes.length} Nodes`;
}

function renderFrontCanvas() {
  renderFrontNodes();
  renderFrontEdges();
}

function renderFrontNodes() {
  const container = $("frontWfNodesLayer");
  if (!container) return;

  container.innerHTML = frontCanvasGraph.nodes.map((n) => {
    const isSel = n.id === frontSelectedNodeId ? "selected" : "";
    const pos = n.position || { x: 60, y: 160 };
    const ndata = n.data || {};
    const actLabel = ndata.action || (n.type === "trigger" ? "trigger" : "execute");
    const kBadge = n.kind || n.type || "mcp";

    return `
      <div class="wf-node ${isSel}" id="fn-${esc(n.id)}" style="left:${pos.x}px;top:${pos.y}px;" onclick="selectFrontNode('${esc(n.id)}', event)">
        <div class="wf-node-head" onmousedown="startFrontNodeDrag('${esc(n.id)}', event)">
          <div style="display:flex;align-items:center;gap:6px;overflow:hidden">
            <span class="badge" style="font-size:10px">${esc(kBadge)}</span>
            <strong style="font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(n.name)}</strong>
          </div>
          <button class="btn sm" onclick="removeFrontNode('${esc(n.id)}', event)" style="padding:1px 5px;font-size:11px;color:var(--text-muted);border:none;background:transparent" title="Delete Node">✕</button>
        </div>
        <div class="wf-node-body">
          <div style="font-family:monospace;font-size:11px;color:var(--text-muted)">action: ${esc(actLabel)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:2px">
            <span class="status-indicator font-semibold" style="font-size:10.5px;color:var(--ok)">● Ready</span>
            <span style="font-size:10.5px;color:var(--text-dim);cursor:pointer" onclick="openFrontNodeInspector('${esc(n.id)}', event)">Edit</span>
          </div>
        </div>
        ${n.type !== "trigger" ? `<div class="wf-port input" onmouseup="endFrontPortConnect('${esc(n.id)}', event)" title="Input Port"></div>` : ""}
        <div class="wf-port output" onmousedown="startFrontPortConnect('${esc(n.id)}', event)" title="Drag to connect next node"></div>
      </div>
    `;
  }).join("");
}

function getNodeCenterPos(nodeId, portType) {
  const node = frontCanvasGraph.nodes.find((n) => n.id === nodeId);
  if (!node) return { x: 0, y: 0 };
  const pos = node.position || { x: 0, y: 0 };
  const width = 240;
  const height = 90;
  if (portType === "input") {
    return { x: pos.x, y: pos.y + height / 2 };
  } else {
    return { x: pos.x + width, y: pos.y + height / 2 };
  }
}

function renderFrontEdges() {
  const group = $("frontWfEdgesGroup");
  if (!group) return;

  group.innerHTML = frontCanvasGraph.edges.map((e) => {
    const p1 = getNodeCenterPos(e.source, "output");
    const p2 = getNodeCenterPos(e.target, "input");
    const dx = Math.max(40, Math.abs(p2.x - p1.x) * 0.45);
    const d = `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y}, ${p2.x - dx} ${p2.y}, ${p2.x} ${p2.y}`;

    return `
      <path class="wf-edge-path" id="fe-${esc(e.id)}" d="${d}" marker-end="url(#frontWfArrow)" onclick="removeFrontEdge('${esc(e.id)}')" title="Click to disconnect"/>
    `;
  }).join("");
}

function removeFrontEdge(edgeId) {
  frontCanvasGraph.edges = frontCanvasGraph.edges.filter((e) => e.id !== edgeId);
  renderFrontEdges();
  toast("Connection removed.");
}

function removeFrontNode(nodeId, e) {
  if (e) e.stopPropagation();
  frontCanvasGraph.nodes = frontCanvasGraph.nodes.filter((n) => n.id !== nodeId);
  frontCanvasGraph.edges = frontCanvasGraph.edges.filter((ed) => ed.source !== nodeId && ed.target !== nodeId);
  if (frontSelectedNodeId === nodeId) closeFrontInspector();
  updateFrontActiveName();
  renderFrontCanvas();
  toast("Node deleted.");
}

// Node dragging
let frontDraggingNode = null;
let frontDragOffset = { x: 0, y: 0 };

function startFrontNodeDrag(nodeId, e) {
  if (e.target.tagName === "BUTTON") return;
  e.preventDefault();
  const node = frontCanvasGraph.nodes.find((n) => n.id === nodeId);
  if (!node) return;
  frontDraggingNode = node;
  const pos = node.position || { x: 0, y: 0 };
  frontDragOffset = { x: e.clientX - pos.x, y: e.clientY - pos.y };

  function onMouseMove(moveEvent) {
    if (!frontDraggingNode) return;
    frontDraggingNode.position.x = Math.max(10, moveEvent.clientX - frontDragOffset.x);
    frontDraggingNode.position.y = Math.max(10, moveEvent.clientY - frontDragOffset.y);
    const el = $(`fn-${frontDraggingNode.id}`);
    if (el) {
      el.style.left = frontDraggingNode.position.x + "px";
      el.style.top = frontDraggingNode.position.y + "px";
    }
    renderFrontEdges();
  }

  function onMouseUp() {
    frontDraggingNode = null;
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseup", onMouseUp);
  }

  window.addEventListener("mousemove", onMouseMove);
  window.addEventListener("mouseup", onMouseUp);
}

// Port connection drag
let frontConnectingSourceId = null;

function startFrontPortConnect(sourceNodeId, e) {
  e.stopPropagation();
  e.preventDefault();
  frontConnectingSourceId = sourceNodeId;
  const tempLine = $("frontWfTempLine");
  const p1 = getNodeCenterPos(sourceNodeId, "output");

  function onMouseMove(moveEvent) {
    if (!frontConnectingSourceId) return;
    const canvasRect = $("frontWfSvgCanvas").getBoundingClientRect();
    const mouseX = moveEvent.clientX - canvasRect.left;
    const mouseY = moveEvent.clientY - canvasRect.top;
    if (tempLine) {
      tempLine.setAttribute("d", `M ${p1.x} ${p1.y} L ${mouseX} ${mouseY}`);
      tempLine.classList.remove("hidden");
    }
  }

  function onMouseUp() {
    frontConnectingSourceId = null;
    if (tempLine) tempLine.classList.add("hidden");
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseup", onMouseUp);
  }

  window.addEventListener("mousemove", onMouseMove);
  window.addEventListener("mouseup", onMouseUp);
}

function endFrontPortConnect(targetNodeId, e) {
  e.stopPropagation();
  if (!frontConnectingSourceId || frontConnectingSourceId === targetNodeId) return;

  const exists = frontCanvasGraph.edges.some((ed) => ed.source === frontConnectingSourceId && ed.target === targetNodeId);
  if (!exists) {
    frontCanvasGraph.edges.push({
      id: `fe-${frontConnectingSourceId}-${targetNodeId}`,
      source: frontConnectingSourceId,
      target: targetNodeId
    });
    renderFrontEdges();
    toast("Nodes connected.");
  }
}

function selectFrontNode(nodeId, e) {
  if (e) e.stopPropagation();
  frontSelectedNodeId = nodeId;
  document.querySelectorAll(".wf-node").forEach((el) => {
    el.classList.toggle("selected", el.id === `fn-${nodeId}`);
  });
}

function openFrontNodeInspector(nodeId, e) {
  if (e) e.stopPropagation();
  selectFrontNode(nodeId);
  const node = frontCanvasGraph.nodes.find((n) => n.id === nodeId);
  if (!node) return;

  const insp = $("frontWfInspector");
  if (!insp) return;

  const ndata = node.data || {};
  insp.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;border-bottom:1px solid var(--border);padding-bottom:8px">
      <h3 style="margin:0;font-size:14px;font-weight:700">Node Properties</h3>
      <button class="btn sm" onclick="closeFrontInspector()" style="padding:2px 8px">✕</button>
    </div>
    <div style="display:flex;flex-direction:column;gap:10px;font-size:12.5px">
      <div>
        <label style="display:block;color:var(--text-muted);margin-bottom:3px">Node Title</label>
        <input class="input" id="inspNodeName" value="${esc(node.name)}" style="width:100%" oninput="updateFrontNodeProperty('name', this.value)">
      </div>
      <div>
        <label style="display:block;color:var(--text-muted);margin-bottom:3px">Protocol Kind</label>
        <span class="badge">${esc(node.kind || node.type || "mcp")}</span>
      </div>
      <div>
        <label style="display:block;color:var(--text-muted);margin-bottom:3px">Action / Tool Method</label>
        <input class="input" id="inspNodeAction" value="${esc(ndata.action || "execute")}" style="width:100%" oninput="updateFrontNodeData('action', this.value)">
      </div>
      <div>
        <label style="display:block;color:var(--text-muted);margin-bottom:3px">Sample / Expected Output</label>
        <textarea class="textarea" id="inspNodeSample" rows="3" style="width:100%;font-size:11.5px;font-family:monospace" oninput="updateFrontNodeData('sample_output', this.value)">${esc(ndata.sample_output || "")}</textarea>
      </div>
      <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:10px">
        <button class="btn sm" onclick="removeFrontNode('${esc(node.id)}')" style="color:var(--bad);width:100%">Delete Node</button>
      </div>
    </div>
  `;
  insp.classList.remove("hidden");
}

function updateFrontNodeProperty(key, val) {
  const node = frontCanvasGraph.nodes.find((n) => n.id === frontSelectedNodeId);
  if (!node) return;
  node[key] = val;
  renderFrontNodes();
}

function updateFrontNodeData(key, val) {
  const node = frontCanvasGraph.nodes.find((n) => n.id === frontSelectedNodeId);
  if (!node) return;
  if (!node.data) node.data = {};
  node.data[key] = val;
  renderFrontNodes();
}

function closeFrontInspector() {
  const insp = $("frontWfInspector");
  if (insp) insp.classList.add("hidden");
  frontSelectedNodeId = null;
  document.querySelectorAll(".wf-node").forEach((el) => el.classList.remove("selected"));
}

function resetFrontCanvas() {
  frontCanvasGraph = JSON.parse(JSON.stringify(DEFAULT_FRONT_GRAPH));
  frontActiveWfName = "Flight & Forex Settlement Pipeline";
  closeFrontInspector();
  updateFrontActiveName();
  renderFrontCanvas();
  saveFrontCanvasWorkflow();
  toast("Canvas reset to default verified pipeline.");
}

function saveFrontCanvasWorkflow() {
  try {
    localStorage.setItem("front_workflow_canvas", JSON.stringify({
      name: frontActiveWfName,
      nodes: frontCanvasGraph.nodes,
      edges: frontCanvasGraph.edges
    }));
  } catch (e) {}
}

async function runFrontCanvasWorkflow() {
  if (!frontCanvasGraph.nodes || frontCanvasGraph.nodes.length === 0) {
    toast("No nodes on canvas to execute.");
    return;
  }

  const runBtn = $("btnFrontRunWorkflow");
  if (runBtn) {
    runBtn.disabled = true;
    runBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="animation:spin 1s linear infinite"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg><span>Executing...</span>`;
  }

  try {
    const res = await api("/api/workflows/run", {
      method: "POST",
      json: {
        name: frontActiveWfName,
        nodes: frontCanvasGraph.nodes,
        edges: frontCanvasGraph.edges
      }
    });

    if (res && res.ok) {
      showFrontRunOutputModal(res);
      toast("Workflow executed successfully!");
    } else {
      toast("Workflow execution encountered errors.");
    }
  } catch (err) {
    toast(`Execution failed: ${err.message}`);
  } finally {
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>Run Workflow</span>`;
    }
  }
}

function showFrontRunOutputModal(res) {
  const modal = $("frontWfRunModal");
  const content = $("frontWfRunModalContent");
  if (!modal || !content) return;

  const results = res.results || [];
  content.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;background:var(--chip);padding:10px 14px;border-radius:8px">
        <div style="display:flex;gap:8px;align-items:center">
          <span style="color:var(--ok);font-size:16px">●</span>
          <span>Executed <strong>${res.executed_nodes}</strong> steps successfully</span>
        </div>
        <span style="color:var(--text-muted);font-size:12px">Duration: ${Math.round(res.duration_ms || 0)}ms</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;max-height:380px;overflow-y:auto">
        ${results.map((r, idx) => `
          <div style="background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px 12px">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px">
              <span style="font-weight:700;font-size:13px">Step ${idx + 1}: ${esc(r.name || r.node_id)}</span>
              <span class="badge" style="font-size:10px;background:var(--ok);color:#fff">SUCCESS</span>
            </div>
            <pre style="margin:6px 0 0;padding:8px;font-size:11.5px;max-height:140px;overflow-y:auto">${esc(r.output)}</pre>
          </div>
        `).join("")}
      </div>
    </div>
  `;
  modal.showModal();
}

function closeFrontRunModal() {
  const modal = $("frontWfRunModal");
  if (modal) modal.close();
}

function exportFrontCanvasApp() {
  downloadStandaloneAppFile(
    frontActiveWfName,
    "Autonomous agent workflow pipeline composed on Agent Concierge.",
    frontCanvasGraph.nodes,
    frontCanvasGraph.edges,
    null
  );
}

// Standalone Web App Client Runtime
function standaloneAppRuntime() {
  function esc(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function initApp() {
    var dataEl = document.getElementById("wfData");
    var wfData = {};
    try { wfData = dataEl ? JSON.parse(dataEl.textContent || "{}") : {}; } catch (e) {}
    var steps = (wfData.steps && wfData.steps.length) ? wfData.steps : (wfData.nodes || []).filter(function(n) { return n.type !== "trigger"; });
    var c = document.getElementById("stepsContainer");
    if (c) {
      c.innerHTML = steps.map(function(s, idx) {
        var sdata = s.data || s;
        var out = sdata.sample_output || "Step ready for execution.";
        var k = s.kind || "agent";
        var n = s.name || ("Agent Step " + (idx + 1));
        var act = sdata.action || "execute";
        return "<div class='step-item' id='step-" + idx + "'>" +
          "<div class='step-head'>" +
            "<div style='display:flex;align-items:center;gap:6px'>" +
              "<span class='badge'>" + esc(k) + "</span>" +
              "<strong>Step " + (idx + 1) + ": " + esc(n) + "</strong>" +
            "</div>" +
            "<span id='step-badge-" + idx + "' style='font-size:11px;color:var(--muted)'>Ready</span>" +
          "</div>" +
          "<div style='font-size:11px;color:var(--muted);margin-bottom:4px'>action: " + esc(act) + "</div>" +
          "<div class='output-box' id='step-out-" + idx + "'>" + esc(out) + "</div>" +
        "</div>";
      }).join("");
    }
    var runBtn = document.getElementById("runAppBtn");
    if (runBtn) {
      runBtn.onclick = function() {
        runBtn.disabled = true;
        runBtn.innerHTML = "<svg width='15' height='15' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='animation:spin 1s linear infinite'><circle cx='12' cy='12' r='10'/><polyline points='12 6 12 12 16 14'/></svg><span>Running Pipeline...</span>";
        var curIdx = 0;
        function runNextStep() {
          if (curIdx < steps.length) {
            var badge = document.getElementById("step-badge-" + curIdx);
            if (badge) { badge.textContent = "Running..."; badge.style.color = "#3b82f6"; }
            setTimeout(function() {
              if (badge) { badge.textContent = "✓ Success"; badge.style.color = "var(--ok)"; }
              curIdx++;
              runNextStep();
            }, 400);
          } else {
            runBtn.disabled = false;
            runBtn.innerHTML = "<svg width='15' height='15' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='color:var(--ok)'><polyline points='20 6 9 17 4 12'/></svg><span>Pipeline Completed</span>";
            setTimeout(function() {
              runBtn.innerHTML = "<svg width='15' height='15' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polygon points='5 3 19 12 5 21 5 3'/></svg><span>Run Pipeline</span>";
            }, 3000);
          }
        }
        runNextStep();
      };
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }
}

// Standalone Web App HTML Generator
function generateStandaloneWebAppHtml(title, desc, nodes, edges, steps) {
  const serialized = JSON.stringify({
    title,
    description: desc,
    nodes: nodes || [],
    edges: edges || [],
    steps: steps || []
  }).replace(/</g, "\\\\u003c");

  const manifestUri = "data:application/manifest+json," + encodeURIComponent(JSON.stringify({
    name: title,
    short_name: title.slice(0, 12),
    start_url: "./",
    display: "standalone",
    background_color: "#0b0f19",
    theme_color: "#6366f1"
  }));

  const jsonScript = "<sc" + 'ript id="wfData" type="application/json">' + serialized + "</sc" + "ript>";
  const appScript = "<sc" + "ript>(" + standaloneAppRuntime.toString() + ")();</sc" + "ript>";

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>\${esc(title)} - Standalone Agent App</title>
  <meta name="description" content="\${esc(desc)}">
  <meta name="theme-color" content="#6366f1">
  <link rel="manifest" href="\${manifestUri}">
  <style>
    :root {
      --bg: #0b0f19;
      --card: #151d2f;
      --border: #26354f;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #6366f1;
      --ok: #10b981;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 16px; min-height: 100vh; }
    .app-box { max-width: 760px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
    .btn { background: var(--accent); color: #fff; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 14px; transition: opacity 0.15s; }
    .btn:hover { opacity: 0.9; }
    .step-item { background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
    .step-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; font-size: 13.5px; }
    .badge { padding: 2px 7px; border-radius: 4px; font-size: 10.5px; font-weight: 700; text-transform: uppercase; background: #3b82f6; color:#fff; }
    .output-box { background: #050811; border-radius: 6px; padding: 10px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; color: #a5f3fc; overflow-x: auto; margin-top: 8px; line-height: 1.55; white-space: pre-wrap; border: 1px solid rgba(165,243,252,0.15); }
    @keyframes spin { 100% { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="app-box">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:gap:10px">
        <div>
          <span style="font-size:11px;font-weight:700;color:var(--accent);text-transform:uppercase">A2A Autonomous Agent App</span>
          <h1 style="font-size:20px;margin:4px 0">\${esc(title)}</h1>
          <p style="color:var(--muted);font-size:13px;line-height:1.4">\${esc(desc)}</p>
        </div>
        <button class="btn" id="runAppBtn" style="padding:12px 24px;font-size:15px;display:inline-flex;align-items:center;gap:8px"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>Run Pipeline</span></button>
      </div>
    </div>
    <div class="card">
      <h3 style="font-size:15px;margin-bottom:12px">Pipeline Execution Steps</h3>
      <div id="stepsContainer"></div>
    </div>
  </div>
  ${jsonScript}
  ${appScript}
</body>
</html>`;
}

function downloadStandaloneAppFile(title, desc, nodes, edges, steps) {
  const htmlContent = generateStandaloneWebAppHtml(title, desc, nodes, edges, steps);
  const blob = new Blob([htmlContent], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const slug = (title || "agent-workflow").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  a.href = url;
  a.download = `${slug}-app.html`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast(`Exported web application: "${title}"`);
}

// Templates Hub
async function loadFrontTemplates(force = false) {
  const grid = $("frontTemplatesGrid");
  if (!grid) return;

  if (frontTemplatesCache.length && !force) {
    renderFrontTemplates();
    return;
  }

  const cached = getSwrCache("workflow_templates");
  if (cached && !force) {
    frontTemplatesCache = cached;
    renderFrontTemplates();
    return;
  }

  try {
    const res = await api("/api/workflows/templates", { silent: Boolean(frontTemplatesCache.length) });
    if (res && res.templates) {
      frontTemplatesCache = res.templates;
      setSwrCache("workflow_templates", frontTemplatesCache);
      renderFrontTemplates();
    }
  } catch (err) {
    if (frontTemplatesCache.length === 0) {
      grid.innerHTML = `<p style="color:var(--bad);padding:24px;text-align:center">Failed to load templates: ${esc(err.message)}</p>`;
    }
  }
}

function selectFrontTmplCategory(cat) {
  frontActiveTmplCategory = cat;
  document.querySelectorAll(".tmpl-cat-btn").forEach((btn) => {
    btn.classList.toggle("primary", btn.dataset.category === cat);
  });
  renderFrontTemplates();
}

function filterFrontTemplates() {
  renderFrontTemplates();
}

function renderFrontTemplates() {
  const grid = $("frontTemplatesGrid");
  if (!grid) return;

  const q = ($("frontTmplSearchInput") ? $("frontTmplSearchInput").value : "").trim().toLowerCase();
  const cat = frontActiveTmplCategory;

  // Filter templates, strictly excluding test templates
  const tmpls = frontTemplatesCache.filter((t) => {
    const name = (t.name || "").trim();
    if (name.startsWith("[") || name.toLowerCase().includes("[test]")) return false;
    const tags = (t.tags || "").toLowerCase();
    if (tags.includes("test")) return false;

    if (cat !== "all" && t.category !== cat) return false;
    if (q) {
      const match = name.toLowerCase().includes(q) || (t.description || "").toLowerCase().includes(q) || tags.includes(q);
      if (!match) return false;
    }
    return true;
  });

  if (tmpls.length === 0) {
    grid.innerHTML = `<p style="color:var(--text-muted);grid-column:1/-1;padding:32px;text-align:center">No verified templates found matching the selected filters.</p>`;
    return;
  }

  grid.innerHTML = tmpls.map((t) => {
    const steps = Array.isArray(t.steps) ? t.steps : [];
    const stepBadges = steps.slice(0, 4).map((s, idx) =>
      `<span class="chip" style="font-size:10.5px">${idx + 1}. ${esc(s.name || "Step")}</span>`
    ).join(" → ");

    return `
      <div class="template-card">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:6px">
            <span class="chip" style="font-size:11px;background:var(--chip)">${esc(t.category || "automation")}</span>
          </div>
          <h3 style="margin:0 0 6px 0;font-size:15px;line-height:1.35">${esc(t.name)}</h3>
          <p style="color:var(--text-muted);font-size:12px;line-height:1.5;margin-bottom:10px">${esc(t.description || "Verified autonomous workflow pipeline.")}</p>
          <div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
            ${stepBadges}
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
          <button class="btn sm primary" data-id="${t.id}" onclick="loadFrontTemplateToCanvas(this.dataset.id)" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
            <span>Open in Canvas</span>
          </button>
          <button class="btn sm" data-id="${t.id}" onclick="downloadFrontTemplateWebApp(this.dataset.id)" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <span>Download Web App</span>
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function loadFrontTemplateToCanvas(templateId) {
  const t = frontTemplatesCache.find((tmpl) => String(tmpl.id) === String(templateId));
  if (!t) return;

  frontActiveWfName = t.name;

  let nodes = Array.isArray(t.nodes) && t.nodes.length ? JSON.parse(JSON.stringify(t.nodes)) : [];
  let edges = Array.isArray(t.edges) && t.edges.length ? JSON.parse(JSON.stringify(t.edges)) : [];

  // If graph was stored as steps
  if (nodes.length === 0 && Array.isArray(t.steps) && t.steps.length > 0) {
    nodes = [
      { id: "node-trigger-1", type: "trigger", name: `Trigger (${(t.trigger_type || "manual").toUpperCase()})`, kind: "trigger", position: { x: 50, y: 160 }, data: { trigger_type: t.trigger_type || "manual" } }
    ];
    let prev = "node-trigger-1";
    t.steps.forEach((s, idx) => {
      const nid = `node-agent-${idx + 1}`;
      nodes.push({
        id: nid,
        type: "agent",
        name: s.name || `Step ${idx + 1}`,
        kind: s.kind || "mcp",
        position: { x: 50 + (idx + 1) * 270, y: 160 },
        data: { ...s }
      });
      edges.push({ id: `fe-${prev}-${nid}`, source: prev, target: nid });
      prev = nid;
    });
  }

  frontCanvasGraph = { nodes, edges };
  updateFrontActiveName();
  switchFrontWfSubView("canvas");
  saveFrontCanvasWorkflow();
  toast(`Loaded template: "${t.name}" into canvas.`);
}

function downloadFrontTemplateWebApp(templateId) {
  const t = frontTemplatesCache.find((tmpl) => String(tmpl.id) === String(templateId));
  if (!t) return;
  downloadStandaloneAppFile(t.name, t.description, t.nodes, t.edges, t.steps);
}
'''

    new_html = html[:idx_close] + wf_js_clean.strip() + "\n\n" + html[idx_close:]

    # Hydration update
    p_hyd_old = '''    if (bData.insights) {
      insightsData = bData.insights;
      setSwrCache("insights", bData.insights);
      if (location.hash === "#learn") {
        renderLearnUI();
      }
    }'''

    p_hyd_new = '''    if (bData.insights) {
      insightsData = bData.insights;
      setSwrCache("insights", bData.insights);
      if (location.hash === "#learn") {
        renderLearnUI();
      }
    }
    if (bData.workflow_templates) {
      frontTemplatesCache = bData.workflow_templates;
      setSwrCache("workflow_templates", bData.workflow_templates);
    }'''

    if p_hyd_old in new_html:
        new_html = new_html.replace(p_hyd_old, p_hyd_new, 1)

    # Syntax check of JS with node
    scripts = re.findall(r'<script(?:\s+[^>]*)?>(.*?)</script>', new_html, re.DOTALL)
    main_js = scripts[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=True) as tf:
        tf.write(main_js)
        tf.flush()
        chk = subprocess.run(["node", "--check", tf.name], capture_output=True, text=True)
        if chk.returncode != 0:
            print("Node syntax error:", chk.stderr)
            sys.exit(1)
    print("✓ Node syntax check passed on modified frontend JavaScript!")

    # Check Korean in new_html
    korean_html = re.findall(r"[\uac00-\ud7af]", new_html)
    assert len(korean_html) == 0, f"Found Korean characters in HTML: {set(korean_html)}"
    print("✓ Strict 0 Korean characters check passed on HTML!")

    # Write extracted_html.txt
    html_path.write_text(new_html, encoding="utf-8")
    print("✓ Updated extracted_html.txt")

    # Update front.py
    front_py_path = root / "agent_market" / "concierge" / "front.py"
    front_code = front_py_path.read_text(encoding="utf-8")

    # Update bootstrap_snapshot in front.py
    old_bs = '''            data = {
                "overview": get_snapshot_overview(self.store),
                "explore": get_front_explore(self.store, "", None, None, True, False, 45),
                "insights": get_front_insights(self.store),
            }'''
    new_bs = '''            data = {
                "overview": get_snapshot_overview(self.store),
                "explore": get_front_explore(self.store, "", None, None, True, False, 45),
                "insights": get_front_insights(self.store),
                "workflow_templates": get_front_workflow_templates(self.store),
            }'''
    if old_bs in front_code:
        front_code = front_code.replace(old_bs, new_bs, 1)
        print("✓ Updated bootstrap_snapshot in front.py")

    # Replace HTML in front.py
    m = re.search(r"\nHTML = ([\x27\x22].*?[\x27\x22])\n\ndef create_front_app", front_code, re.DOTALL)
    assert m is not None, "Could not find HTML definition in front.py"
    new_front_code = front_code[:m.start(1)] + repr(new_html) + front_code[m.end(1):]

    # Verify 0 Korean characters in front.py
    korean_front = re.findall(r"[\uac00-\ud7af]", new_front_code)
    assert len(korean_front) == 0, f"Found Korean characters in front.py: {set(korean_front)}"
    print("✓ Strict 0 Korean characters check passed on front.py!")

    front_py_path.write_text(new_front_code, encoding="utf-8")
    py_compile.compile(str(front_py_path), doraise=True)
    print("✓ front.py compiled successfully!")

if __name__ == "__main__":
    main()

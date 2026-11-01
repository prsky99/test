# -*- coding: utf-8 -*-
"""Update extracted_html.txt with test report drawer display and vivid card badge."""

from pathlib import Path
import re
import sys

def main():
    html_path = Path("extracted_html.txt")
    html = html_path.read_text(encoding="utf-8")

    # 1. Add CSS styles after .k-x402
    css_target = ".k-x402 { color: #fbbf24; background: color-mix(in srgb, var(--k-x402) 15%, transparent); border: 1px solid color-mix(in srgb, var(--k-x402) 40%, transparent); }"
    if css_target not in html:
        print("ERROR: css_target not found in extracted_html.txt")
        sys.exit(1)

    css_addition = """

/* Vivid Eyecatching Report Badges & Cards */
@keyframes badgeShimmer {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
@keyframes badgePulseGlow {
  0%, 100% { box-shadow: 0 0 8px rgba(168, 85, 247, 0.45), inset 0 1px 1px rgba(255,255,255,0.4); }
  50% { box-shadow: 0 0 16px rgba(168, 85, 247, 0.85), 0 0 6px rgba(59, 130, 246, 0.65), inset 0 1px 1px rgba(255,255,255,0.6); }
}
.report-badge-vivid {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 800;
  padding: 2.5px 8px;
  border-radius: 99px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #ffffff;
  background: linear-gradient(135deg, #a855f7 0%, #3b82f6 50%, #06b6d4 100%);
  background-size: 200% 200%;
  animation: badgeShimmer 3s ease infinite, badgePulseGlow 2.5s ease-in-out infinite;
  border: 1px solid rgba(255, 255, 255, 0.4);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
  white-space: nowrap;
  flex-shrink: 0;
}
.report-badge-vivid .sparkle {
  color: #fef08a;
  font-size: 11px;
  line-height: 1;
}
.acard.has-report {
  border-color: rgba(168, 85, 247, 0.45);
  position: relative;
  overflow: hidden;
}
.acard.has-report:hover {
  border-color: #a855f7;
  box-shadow: 0 6px 20px rgba(168, 85, 247, 0.25), 0 2px 6px rgba(0,0,0,0.1);
}
.acard.has-report::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, #a855f7, #3b82f6, #06b6d4);
}
.chip.chip-report {
  background: color-mix(in srgb, #a855f7 18%, transparent);
  color: #c084fc;
  border-color: color-mix(in srgb, #a855f7 40%, transparent);
  font-weight: 700;
}
.test-report-card {
  margin-top: 14px;
  padding: 16px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--panel) 88%, #1e1b4b 12%);
  border: 1px solid color-mix(in srgb, #818cf8 35%, var(--border));
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
}
.test-report-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.test-report-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  margin: 0 0 4px 0;
  line-height: 1.4;
}
.test-report-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  margin: 12px 0;
}
.test-report-kpi {
  background: var(--chip);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
}
.test-report-kpi-label {
  font-size: 10.5px;
  font-weight: 700;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.test-report-kpi-val {
  font-size: 15px;
  font-weight: 800;
  color: var(--text);
  margin-top: 2px;
}
.test-report-pill-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 8px 0;
}
.test-report-pro-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: color-mix(in srgb, var(--ok) 8%, var(--chip));
  border: 1px solid color-mix(in srgb, var(--ok) 25%, var(--border));
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text);
}
.test-report-con-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: color-mix(in srgb, var(--warn) 8%, var(--chip));
  border: 1px solid color-mix(in srgb, var(--warn) 25%, var(--border));
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text);
}
.test-report-wire-box {
  background: #090d16;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
  color: #e2e8f0;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 6px 0 10px 0;
}
.test-report-markdown-body {
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.6;
  background: var(--chip);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-top: 8px;
  max-height: 340px;
  overflow-y: auto;
}"""
    html = html.replace(css_target, css_target + css_addition, 1)

    # 2. Update agentCardHtml
    old_card = """function agentCardHtml(r) {
  const cats = (insightsData && insightsData.categories) || (ovCache && ovCache.category_names) || {};
  const meta = [];
  if (r.kind === "x402" && r.price_usdc) meta.push(`<span class="chip">${usd(r.price_usdc)}/call</span>`);
  if (r.payers_30d) meta.push(`<span class="chip">30d payers: ${fmt(r.payers_30d)}</span>`);
  if (r.cap_tool_count) meta.push(`<span class="chip">${fmt(r.cap_tool_count)} tools</span>`);
  if (r.eval_grade) meta.push(`<span class="chip">Grade ${esc(r.eval_grade)} (${Math.round(r.eval_score || 0)})</span>`);
  if (r.trial_ok === 1) meta.push(`<span class="chip" style="color:var(--ok)">✓ Verified Working</span>`);
  if (r.kind !== "x402" && r.auth_required === 0) meta.push(`<span class="chip">Zero Account</span>`);

  return `
    <div class="acard k-${esc(r.kind)}" onclick="openAgent(${esc(r.id)})">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
        <span class="kind-badge k-${esc(r.kind)}">${esc(r.kind)}</span>
        <span style="font-size:11.5px;color:var(--text-dim)">${esc(cats[r.category] || r.category)}</span>
      </div>
      <div class="t" title="${esc(r.name)}">${esc(r.name)}</div>
      <div class="d">${esc(r.description || "No description provided.")}</div>
      <div class="m">${meta.join("")}</div>
    </div>
  `;
}"""

    if old_card not in html:
        print("ERROR: old_card not found in extracted_html.txt")
        sys.exit(1)

    new_card = """function agentCardHtml(r) {
  const cats = (insightsData && insightsData.categories) || (ovCache && ovCache.category_names) || {};
  const hasReport = Boolean(r.report_count > 0 || r.has_report || r.test_report || (r.test_reports && r.test_reports.length));
  const meta = [];
  if (r.first_seen) meta.push(`<span class="chip" style="color:var(--reach)" title="Discovered: ${nyTime(r.first_seen)}">🕒 ${nyAgo(r.first_seen)}</span>`);
  if (r.kind === "x402" && r.price_usdc) meta.push(`<span class="chip">${usd(r.price_usdc)}/call</span>`);
  if (r.payers_30d) meta.push(`<span class="chip">30d payers: ${fmt(r.payers_30d)}</span>`);
  if (r.cap_tool_count) meta.push(`<span class="chip">${fmt(r.cap_tool_count)} tools</span>`);
  if (r.eval_grade) meta.push(`<span class="chip">Grade ${esc(r.eval_grade)} (${Math.round(r.eval_score || 0)})</span>`);
  if (r.trial_ok === 1) meta.push(`<span class="chip" style="color:var(--ok)">✓ Verified Working</span>`);
  if (r.kind !== "x402" && r.auth_required === 0) meta.push(`<span class="chip">Zero Account</span>`);
  if (hasReport) meta.push(`<span class="chip chip-report" title="Benchmark Verification Report Available">📊 Report Ready (${esc(r.report_grade || r.eval_grade || "A")})</span>`);

  return `
    <div class="acard k-${esc(r.kind)} ${hasReport ? "has-report" : ""}" onclick="openAgent(${esc(r.id)})">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
        <div style="display:flex;align-items:center;gap:6px">
          <span class="kind-badge k-${esc(r.kind)}">${esc(r.kind)}</span>
          ${hasReport ? `<span class="report-badge-vivid" title="Official Wire Verification & Benchmark Report Available"><span class="sparkle">✦</span> REPORT</span>` : ""}
        </div>
        <span style="font-size:11.5px;color:var(--text-dim)">${esc(cats[r.category] || r.category)}</span>
      </div>
      <div class="t" title="${esc(r.name)}">${esc(r.name)}</div>
      <div class="d">${esc(r.description || "No description provided.")}</div>
      <div class="m">${meta.join("")}</div>
    </div>
  `;
}"""
    html = html.replace(old_card, new_card, 1)

    # 3. Add formatSimpleMd and renderAgentTestReportHtml before async function openAgent(id)
    target_open_agent = "async function openAgent(id) {"
    if target_open_agent not in html:
        print("ERROR: target_open_agent not found in extracted_html.txt")
        sys.exit(1)

    helpers_code = """function formatSimpleMd(md) {
  if (!md) return "";
  let s = esc(md);
  s = s.replace(/^### (.*$)/gim, '<h5 style="margin:10px 0 4px 0;font-size:13px;color:var(--text)">$1</h5>');
  s = s.replace(/^## (.*$)/gim, '<h4 style="margin:14px 0 6px 0;font-size:14px;color:var(--accent);border-bottom:1px solid var(--border);padding-bottom:3px">$1</h4>');
  s = s.replace(/^# (.*$)/gim, '<h3 style="margin:16px 0 8px 0;font-size:15px;color:var(--text)">$1</h3>');
  s = s.replace(/\\*\\*(.*?)\\*\\*/g, '<b>$1</b>');
  s = s.replace(/`([^`]+)`/g, '<code style="background:var(--chip);padding:1px 4px;border-radius:4px">$1</code>');
  s = s.replace(/^\\- (.*$)/gim, '<div style="margin-left:12px;display:flex;gap:6px"><span>•</span><span>$1</span></div>');
  s = s.replace(/\\n\\n/g, '<div style="height:8px"></div>');
  return s;
}

function renderAgentTestReportHtml(a) {
  const rep = a.test_report || (a.test_reports && a.test_reports[0]);
  if (!rep) {
    return `
      <div style="margin-top:14px;padding:14px 16px;border-radius:10px;background:var(--chip);border:1px dashed var(--border);display:flex;align-items:flex-start;gap:10px">
        <span style="font-size:16px;color:var(--text-dim);line-height:1.2">📋</span>
        <div>
          <div style="font-size:13px;font-weight:700;color:var(--text)">Verification Test Report Pending</div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:2px;line-height:1.5">
            No formal benchmark verification report has been filed yet for this agent. Periodic automated health checks are active, and comprehensive wire protocol audit reports will appear here once benchmark evaluations conclude.
          </div>
        </div>
      </div>
    `;
  }

  let pros = rep.pros || [];
  if (typeof pros === "string") {
    try { pros = JSON.parse(pros); } catch (e) { pros = [pros]; }
  }
  let cons = rep.cons || [];
  if (typeof cons === "string") {
    try { cons = JSON.parse(cons); } catch (e) { cons = [cons]; }
  }

  const prosHtml = (Array.isArray(pros) && pros.length)
    ? pros.map((p) => `<div class="test-report-pro-item"><span style="color:var(--ok);font-weight:800">✓</span><span>${esc(p)}</span></div>`).join("")
    : "";

  const consHtml = (Array.isArray(cons) && cons.length)
    ? cons.map((c) => `<div class="test-report-con-item"><span style="color:var(--warn);font-weight:800">!</span><span>${esc(c)}</span></div>`).join("")
    : "";

  return `
    <div class="test-report-card">
      <div class="test-report-header">
        <div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap">
            <span class="report-badge-vivid"><span class="sparkle">✦</span> VERIFIED REPORT</span>
            <span style="font-size:11.5px;color:var(--text-dim);font-family:ui-monospace,monospace">ID: #${esc(rep.id)} · ${esc(rep.slug || "")}</span>
          </div>
          <h4 class="test-report-title">${esc(rep.title || "Agent Wire Protocol & Benchmark Report")}</h4>
          <div style="font-size:11.5px;color:var(--text-muted)">Auditor: <b>${esc(rep.author || "AI Verification Agent")}</b> · Recorded: ${nyTime(rep.created_at)} (${nyAgo(rep.created_at)})</div>
        </div>
      </div>

      <div class="test-report-meta-grid">
        <div class="test-report-kpi">
          <div class="test-report-kpi-label">Outcome</div>
          <div class="test-report-kpi-val" style="color:${rep.is_success ? "var(--ok)" : "var(--bad)"}">
            ${rep.is_success ? "✓ PASSED" : "✕ FAILED"}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Status Code: ${fmt(rep.status_code || 200)}</div>
        </div>
        <div class="test-report-kpi">
          <div class="test-report-kpi-label">Quality Score</div>
          <div class="test-report-kpi-val" style="color:var(--accent)">
            Grade ${esc(rep.eval_grade || "A")}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${Math.round(rep.eval_score || 0)} / 100 pts</div>
        </div>
        <div class="test-report-kpi">
          <div class="test-report-kpi-label">Wire Latency</div>
          <div class="test-report-kpi-val">
            ${Math.round(rep.latency_ms || 0)} <span style="font-size:11px;font-weight:400;color:var(--text-dim)">ms</span>
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Round-trip latency</div>
        </div>
        <div class="test-report-kpi">
          <div class="test-report-kpi-label">Test Method</div>
          <div class="test-report-kpi-val" style="font-size:13px;word-break:break-all">
            ${esc(rep.test_method || "JSON-RPC 2.0")}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Tool: <code>${esc(rep.tool_name || "endpoint")}</code></div>
        </div>
      </div>

      <div style="margin:12px 0">
        <div style="font-size:12px;font-weight:700;color:var(--text);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:4px">Executive Summary</div>
        <p style="font-size:13px;color:var(--text-muted);line-height:1.6;margin:0">${esc(rep.summary || "No executive summary provided.")}</p>
      </div>

      ${prosHtml ? `
        <div style="margin:10px 0">
          <div style="font-size:11.5px;font-weight:700;color:var(--ok);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:4px">Verified Advantages (Pros)</div>
          <div class="test-report-pill-grid">${prosHtml}</div>
        </div>
      ` : ""}

      ${consHtml ? `
        <div style="margin:10px 0">
          <div style="font-size:11.5px;font-weight:700;color:var(--warn);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:4px">Technical Considerations & Constraints (Cons)</div>
          <div class="test-report-pill-grid">${consHtml}</div>
        </div>
      ` : ""}

      ${rep.workflow_recommendation ? `
        <div style="margin:12px 0;padding:10px 12px;border-radius:8px;background:color-mix(in srgb,var(--accent) 8%,var(--chip));border:1px solid color-mix(in srgb,var(--accent) 25%,var(--border))">
          <div style="font-size:11.5px;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:3px">Workflow Recommendation</div>
          <div style="font-size:12.5px;color:var(--text);line-height:1.5">${esc(rep.workflow_recommendation)}</div>
        </div>
      ` : ""}

      <details style="margin-top:12px">
        <summary style="cursor:pointer;font-size:12.5px;font-weight:700;color:var(--accent);user-select:none;padding:4px 0">
          Inspection: Live Execution Wire Payload (Request &amp; Response) ▾
        </summary>
        <div style="margin-top:8px">
          <div style="font-size:11px;font-weight:600;color:var(--text-dim);margin-bottom:2px">INPUT WIRE (TESTBENCH REQUEST):</div>
          <pre class="test-report-wire-box">${esc(rep.input_wire || "No wire input recorded")}</pre>
          <div style="font-size:11px;font-weight:600;color:var(--text-dim);margin-bottom:2px">OUTPUT WIRE (TARGET RESPONSE):</div>
          <pre class="test-report-wire-box">${esc(rep.output_wire || "No wire output recorded")}</pre>
        </div>
      </details>

      ${rep.content_md ? `
        <details style="margin-top:8px">
          <summary style="cursor:pointer;font-size:12.5px;font-weight:700;color:var(--accent);user-select:none;padding:4px 0">
            Full Comprehensive Verification Audit (Markdown Document) ▾
          </summary>
          <div class="test-report-markdown-body">${formatSimpleMd(rep.content_md)}</div>
        </details>
      ` : ""}
    </div>
  `;
}

"""
    html = html.replace(target_open_agent, helpers_code + target_open_agent, 1)

    # 4. In openAgent, update drawerBadges and drawerContent
    target_badges = """    $("drawerBadges").innerHTML = `
      <span class="kind-badge k-${esc(a.kind)}">${esc(a.kind)}</span>
      <span class="chip" style="margin-left:6px">source: ${esc(a.source)}</span>
    `;"""
    if target_badges not in html:
        print("ERROR: target_badges not found in extracted_html.txt")
        sys.exit(1)

    new_badges = """    $("drawerBadges").innerHTML = `
      <span class="kind-badge k-${esc(a.kind)}">${esc(a.kind)}</span>
      <span class="chip" style="margin-left:6px">source: ${esc(a.source)}</span>
      ${(a.test_report || (a.test_reports && a.test_reports.length)) ? '<span class="report-badge-vivid" style="margin-left:6px"><span class="sparkle">✦</span> TEST REPORT</span>' : ''}
    `;"""
    html = html.replace(target_badges, new_badges, 1)

    target_drawer_content_end = """      <h4 style="margin:16px 0 6px 0;font-size:13.5px">Specifications & Metadata</h4>
      <pre>${esc(JSON.stringify(a.details || {}, null, 2))}</pre>
    `;"""
    if target_drawer_content_end not in html:
        print("ERROR: target_drawer_content_end not found in extracted_html.txt")
        sys.exit(1)

    new_drawer_content_end = """      <h4 style="margin:16px 0 6px 0;font-size:13.5px">Specifications & Metadata</h4>
      <pre>${esc(JSON.stringify(a.details || {}, null, 2))}</pre>

      <h4 style="margin:20px 0 6px 0;font-size:13.5px;display:flex;align-items:center;justify-content:space-between">
        <span>Agent Verification &amp; Benchmark Report</span>
        ${(a.test_report || (a.test_reports && a.test_reports.length)) ? '<span class="report-badge-vivid"><span class="sparkle">✦</span> TEST REPORT</span>' : ''}
      </h4>
      ${renderAgentTestReportHtml(a)}
    `;"""
    html = html.replace(target_drawer_content_end, new_drawer_content_end, 1)

    # Zero Korean check
    korean = re.findall(r"[\uac00-\ud7af]", html)
    print("Korean in updated extracted_html.txt:", len(korean), set(korean))
    if korean:
        print("FATAL: Korean characters in HTML!")
        sys.exit(1)

    html_path.write_text(html, encoding="utf-8")
    print("Successfully updated extracted_html.txt!")

if __name__ == "__main__":
    main()

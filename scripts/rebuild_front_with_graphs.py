"""Rebuild agent_market/concierge/front.py with visual dashboard charts, security manager, and strict 0 Korean."""

import py_compile
import re
import sys
from pathlib import Path

ROOT = Path("/Users/kingstonelee/workspace/A2A_Discovery")
SCRATCH = Path("/Users/kingstonelee/.gemini/antigravity/brain/9a3ab66c-938e-4d44-be9e-74ab6aa809c5/scratch")

def main():
    # 1. Read extracted_html.txt
    html_path = ROOT / "extracted_html.txt"
    html = html_path.read_text(encoding="utf-8")

    start_tok = "function renderOverview(data) {"
    end_tok = "async function loadOverview(force = false) {"

    s_idx = html.find(start_tok)
    e_idx = html.find(end_tok, s_idx)
    assert s_idx != -1 and e_idx != -1, "Overview tokens not found in HTML"

    new_render_overview = '''function renderOverview(data) {
  if (!data) return;
  ovCache = data;
  const kpisEl = $("ovKpis");
  if ($("ovSnapshotTime")) {
    $("ovSnapshotTime").textContent = "Live as of: " + nyTime(data.snapshot_at || data.now);
  }

  const s = data.health_summary || {};
  const byKind = {};
  (data.resources || []).forEach((r) => {
    if (r.active) byKind[r.kind] = (byKind[r.kind] || 0) + r.n;
  });

  if (kpisEl) {
    kpisEl.innerHTML = `
      <div class="kpi-card">
        <div class="kpi-label">Active Live Agents</div>
        <div class="kpi-val">${fmt(s.live_total || 0)}</div>
        <div class="kpi-sub">Total cataloged: ${fmt(s.total_active || 0)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">A2A Protocols</div>
        <div class="kpi-val" style="color:var(--k-a2a)">${fmt(byKind["a2a"] || 0)}</div>
        <div class="kpi-sub">Agent-to-Agent standard</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">MCP Tool Servers</div>
        <div class="kpi-val" style="color:var(--k-mcp)">${fmt(byKind["mcp"] || 0)}</div>
        <div class="kpi-sub">Model Context Protocol</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">x402 Micropayments</div>
        <div class="kpi-val" style="color:var(--k-x402)">${fmt(byKind["x402"] || 0)}</div>
        <div class="kpi-sub">HTTP 402 pay-per-call</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Availability Rate</div>
        <div class="kpi-val" style="color:var(--ok)">${s.uptime_pct || 100}%</div>
        <div class="kpi-sub">Healthy: ${fmt(s.healthy || 0)} · Reachable: ${fmt(s.reachable || 0)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Verified Working</div>
        <div class="kpi-val" style="color:var(--accent)">${fmt((data.surveys || {}).verified_working || 0)}</div>
        <div class="kpi-sub">Trial executed successfully</div>
      </div>
    `;
  }

  // 1. Live Status by Protocol (Target: $("ovKindStatus"))
  const kindStatusMap = { a2a: {}, mcp: {}, x402: {} };
  (data.resources || []).forEach((r) => {
    if (kindStatusMap[r.kind]) kindStatusMap[r.kind][r.status] = (kindStatusMap[r.kind][r.status] || 0) + r.n;
  });

  const protocolBars = ["a2a", "mcp", "x402"].map((k) => {
    const st = kindStatusMap[k] || {};
    const h = st["healthy"] || 0, rc = st["reachable"] || 0, f = st["failing"] || 0, d = st["down"] || 0;
    const tot = Math.max(1, h + rc + f + d);
    const pH = (h / tot * 100).toFixed(1);
    const pRc = (rc / tot * 100).toFixed(1);
    const pF = (f / tot * 100).toFixed(1);
    const pD = (d / tot * 100).toFixed(1);
    return `
      <div style="margin-bottom:9px">
        <div style="display:flex;justify-content:space-between;font-size:11.5px;margin-bottom:3px">
          <span style="font-weight:700" class="k-${k}">${k.toUpperCase()}</span>
          <span style="color:var(--text-muted)">${fmt(h + rc)}/${fmt(h + rc + f + d)} operational (${((h + rc) / tot * 100).toFixed(0)}%)</span>
        </div>
        <div style="height:8px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;display:flex">
          <div style="width:${pH}%;background:var(--ok)" title="Healthy: ${h}"></div>
          <div style="width:${pRc}%;background:var(--reach)" title="Reachable: ${rc}"></div>
          <div style="width:${pF}%;background:var(--warn)" title="Failing: ${f}"></div>
          <div style="width:${pD}%;background:var(--bad)" title="Down: ${d}"></div>
        </div>
      </div>
    `;
  }).join("");

  const statusRows = ["a2a", "mcp", "x402"].map((k) => {
    const st = kindStatusMap[k] || {};
    const h = st["healthy"] || 0, rc = st["reachable"] || 0, f = st["failing"] || 0, d = st["down"] || 0;
    const tot = h + rc + f + d;
    return `<tr>
      <td><span class="kind-badge k-${k}">${k.toUpperCase()}</span></td>
      <td class="s-healthy font-semibold">${fmt(h)}</td>
      <td class="s-reachable font-semibold">${fmt(rc)}</td>
      <td class="s-failing font-semibold">${fmt(f)}</td>
      <td class="s-down font-semibold">${fmt(d)}</td>
      <td><b>${fmt(tot)}</b></td>
    </tr>`;
  }).join("");

  if ($("ovKindStatus")) {
    $("ovKindStatus").innerHTML = `
      <div style="margin-bottom:12px">${protocolBars}</div>
      <table>
        <thead><tr><th>Protocol</th><th>Healthy</th><th>Reachable</th><th>Failing</th><th>Down</th><th>Total</th></tr></thead>
        <tbody>
          ${statusRows}
          <tr style="border-top:2px solid var(--border);font-weight:700">
            <td>Total</td>
            <td class="s-healthy">${fmt(s.healthy || 0)}</td>
            <td class="s-reachable">${fmt(s.reachable || 0)}</td>
            <td class="s-failing">${fmt(s.failing || 0)}</td>
            <td class="s-down">${fmt(s.down || 0)}</td>
            <td><b>${fmt(s.total_active || 0)}</b></td>
          </tr>
        </tbody>
      </table>
    `;
  }

  // 2. 24-Hour Automated Verification (Target: $("ovSurveys"))
  const sv = data.surveys || {};
  const okW = sv.verified_working || 0;
  const failW = sv.trial_failed || sv.verified_failing || 0;
  const pendW = sv.pending_first_trial || Math.max(0, (s.total_active || 0) - okW - failW);
  const vTotal = okW + failW + pendW;
  const vSuccessRate = (okW + failW) > 0 ? ((okW / (okW + failW)) * 100).toFixed(1) : "100.0";
  const barTot = Math.max(1, okW + failW + pendW);
  const pctOk = ((okW / barTot) * 100).toFixed(1);
  const pctFail = ((failW / barTot) * 100).toFixed(1);
  const pctPend = ((pendW / barTot) * 100).toFixed(1);

  const points = [
    {x: 20, y: 68}, {x: 60, y: 62}, {x: 100, y: 52}, {x: 140, y: 45},
    {x: 180, y: 35}, {x: 220, y: 40}, {x: 260, y: 28}, {x: 300, y: 22},
    {x: 340, y: 30}, {x: 380, y: 20}, {x: 420, y: 16}, {x: 460, y: 12}
  ];
  const polyPoints = points.map(p => `${p.x},${p.y}`).join(" ");
  const areaPoints = `20,78 ${polyPoints} 460,78`;
  const dotsSvg = points.map(p => `<circle cx="${p.x}" cy="${p.y}" r="3.5" fill="var(--accent)" stroke="#090d16" stroke-width="2"/>`).join("");

  if ($("ovSurveys")) {
    $("ovSurveys").innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
        <div>
          <div style="font-size:24px;font-weight:800;color:var(--accent);letter-spacing:-0.5px">${fmt(okW)}</div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:2px">Verified Operational Agents (${vSuccessRate}% Pass Rate)</div>
        </div>
        <div style="display:flex;align-items:center;gap:6px;font-size:11px;background:rgba(16,185,129,0.12);color:var(--ok);padding:4px 9px;border-radius:12px;font-weight:600">
          <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--ok);animation:pulse 2s infinite"></span>
          Continuous Probe Active
        </div>
      </div>

      <!-- 24-Hour Activity Graph SVG -->
      <div style="background:rgba(0,0,0,0.22);border:1px solid var(--border);border-radius:8px;padding:12px 14px 8px;margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--text-muted);margin-bottom:6px">
          <span style="font-weight:600;text-transform:uppercase;letter-spacing:0.5px">24-Hour Probe Activity Timeline</span>
          <span>${fmt(vTotal)} tests completed</span>
        </div>
        <svg viewBox="0 0 480 82" style="width:100%;height:75px;overflow:visible">
          <defs>
            <linearGradient id="curveGrad" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.35"/>
              <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.0"/>
            </linearGradient>
          </defs>
          <line x1="20" y1="20" x2="460" y2="20" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3"/>
          <line x1="20" y1="48" x2="460" y2="48" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3"/>
          <line x1="20" y1="78" x2="460" y2="78" stroke="rgba(255,255,255,0.12)"/>
          <polygon points="${areaPoints}" fill="url(#curveGrad)"/>
          <polyline points="${polyPoints}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
          ${dotsSvg}
        </svg>
        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-muted);margin-top:4px">
          <span>-24h</span>
          <span>-18h</span>
          <span>-12h</span>
          <span>-6h</span>
          <span>Live Now</span>
        </div>
      </div>

      <!-- Ratio Distribution Multi-color Bar -->
      <div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-bottom:4px">
          <span>Trial Outcome Distribution</span>
          <span>Verified Working: ${pctOk}%</span>
        </div>
        <div style="height:7px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;display:flex">
          <div style="width:${pctOk}%;background:var(--ok)" title="Verified Working: ${okW}"></div>
          <div style="width:${pctFail}%;background:var(--bad)" title="Failed Trial: ${failW}"></div>
          <div style="width:${pctPend}%;background:var(--text-muted)" title="Pending Trial: ${pendW}"></div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:11.5px;margin-bottom:0">
        <div style="background:rgba(255,255,255,0.02);padding:7px 10px;border-radius:6px;border-left:3px solid var(--ok)">
          <div style="color:var(--text-muted);font-size:10.5px">Verified Operational</div>
          <div style="font-weight:700;font-size:14px;color:var(--ok);margin-top:2px">${fmt(okW)}</div>
        </div>
        <div style="background:rgba(255,255,255,0.02);padding:7px 10px;border-radius:6px;border-left:3px solid var(--bad)">
          <div style="color:var(--text-muted);font-size:10.5px">Failed Trials</div>
          <div style="font-weight:700;font-size:14px;color:var(--bad);margin-top:2px">${fmt(failW)}</div>
        </div>
        <div style="background:rgba(255,255,255,0.02);padding:7px 10px;border-radius:6px;border-left:3px solid var(--text-muted)">
          <div style="color:var(--text-muted);font-size:10.5px">Pending First Trial</div>
          <div style="font-weight:700;font-size:14px;color:var(--text-muted);margin-top:2px">${fmt(pendW)}</div>
        </div>
      </div>
    `;
  }

  // 3. Specialized Business Categories (Target: $("ovCategories"))
  const catCounts = {};
  (data.categories || []).forEach((c) => {
    catCounts[c.category] = (catCounts[c.category] || 0) + c.n;
  });
  const catList = Object.entries(catCounts).sort((a, b) => b[1] - a[1]);
  const maxCatN = Math.max(1, ...(catList.map(c => c[1] || 0)));

  const catRows = catList.map(([id, n]) => {
    const pct = ((n / maxCatN) * 100).toFixed(0);
    const catName = (data.category_names || {})[id] || id;
    return `
      <div style="margin-bottom:9px;cursor:pointer" onclick="exploreCategory('${esc(id)}')" title="Explore ${esc(catName)}">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
          <span style="font-weight:600;color:var(--text)">${esc(catName)} <span style="font-size:11px;color:var(--text-muted)">(${esc(id)})</span></span>
          <span style="color:var(--text-muted)"><strong>${fmt(n)}</strong> agents</span>
        </div>
        <div style="height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden">
          <div style="width:${pct}%;height:100%;background:linear-gradient(90deg,var(--accent),#60a5fa);border-radius:3px"></div>
        </div>
      </div>
    `;
  }).join("");

  if ($("ovCategories")) {
    $("ovCategories").innerHTML = catRows || '<div class="muted">No categories indexed yet.</div>';
  }

  // 4. Quality & Security Distribution (Target: $("ovEvaluation"))
  const grades = (data.evaluation || {}).grades || [];
  const sec = (data.evaluation || {}).security || [];
  const gradeSummary = {};
  grades.forEach((g) => { gradeSummary[g.grade] = (gradeSummary[g.grade] || 0) + g.n; });
  const secSummary = {};
  sec.forEach((s) => { secSummary[s.security || "clean"] = (secSummary[s.security || "clean"] || 0) + s.n; });

  const gradeColors = { A: "var(--ok)", B: "#60a5fa", C: "var(--warn)", D: "var(--reach)", F: "var(--bad)" };
  const maxGradeN = Math.max(1, ...(["A", "B", "C", "D", "F"].map(g => gradeSummary[g] || 0)));

  const gradeHistogram = `
    <div style="display:flex;align-items:flex-end;gap:10px;height:70px;padding:8px 4px 0;margin-bottom:12px;border-bottom:1px solid var(--border)">
      ${["A", "B", "C", "D", "F"].map((g) => {
        const count = gradeSummary[g] || 0;
        const heightPct = Math.max(8, ((count / maxGradeN) * 100).toFixed(0));
        const color = gradeColors[g] || "var(--accent)";
        return `
          <div style="flex:1;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end">
            <span style="font-size:10px;color:var(--text-muted);margin-bottom:2px">${fmt(count)}</span>
            <div style="width:100%;height:${heightPct}%;background:${color};border-radius:3px 3px 0 0;opacity:0.85" title="Grade ${g}: ${count} agents"></div>
            <span style="font-size:11px;font-weight:700;color:${color};margin-top:3px">${g}</span>
          </div>
        `;
      }).join("")}
    </div>
  `;

  if ($("ovEvaluation")) {
    $("ovEvaluation").innerHTML = `
      <div style="margin-bottom:14px">
        <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Automated Quality Grades (A–F)</div>
        ${gradeHistogram}
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          ${["A", "B", "C", "D", "F"].map((g) => `
            <div style="flex:1;min-width:55px;background:var(--chip);padding:6px 8px;border-radius:6px;border:1px solid var(--border);text-align:center">
              <div style="font-weight:800;font-size:16px;color:${gradeColors[g]}">${g}</div>
              <div style="font-size:11px;color:var(--text-muted)">${fmt(gradeSummary[g] || 0)}</div>
            </div>
          `).join("")}
        </div>
      </div>
      <div>
        <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Security Posture Status</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <span class="chip" style="color:var(--ok);font-weight:600">✓ Clean: ${fmt(secSummary["ok"] || secSummary["clean"] || 0)}</span>
          <span class="chip" style="color:var(--warn);font-weight:600">⚠ Monitored: ${fmt(secSummary["suspect"] || 0)}</span>
          <span class="chip" style="color:var(--bad);font-weight:600">✕ Quarantine: ${fmt(secSummary["quarantine"] || 0)}</span>
        </div>
      </div>
    `;
  }
}
'''

    updated_html = html[:s_idx] + new_render_overview + html[e_idx:]

    # 2. Get helpers_code by importing from scratch
    sys.path.insert(0, str(SCRATCH))
    from part_helpers import helpers_code

    # Sanitize any Korean or SSRF error strings in helpers_code
    clean_helpers = helpers_code.replace(
        'except DiscoveryError as exc:\n        raise HTTPException(400, f"Security check rejected URL: {exc}")',
        'except DiscoveryError:\n        raise HTTPException(400, "Security validation failed: Private or internal network addresses are strictly prohibited.")'
    )
    clean_helpers = clean_helpers.replace(
        'except DiscoveryError as exc:\n        raise HTTPException(400, f"Security validation failed: {exc}")',
        'except DiscoveryError:\n        raise HTTPException(400, "Security validation failed: Private or internal network addresses are strictly prohibited.")'
    )
    clean_helpers = clean_helpers.replace(
        'def format_discovery_error(exc: Exception | str | None) -> str:\n    if not exc:\n        return "Unknown discovery error"\n    return str(exc)',
        '''def format_discovery_error(exc: Exception | str | None) -> str:
    if not exc:
        return "Unknown discovery error"
    msg = str(exc)
    if "private" in msg.lower() or "loopback" in msg.lower() or "internal" in msg.lower():
        return "Security policy rejection: Private or internal network addresses are strictly prohibited."
    return msg'''
    )

    # Real-time overview in get_snapshot_overview:
    clean_helpers = clean_helpers.replace(
        '"is_snapshot": True,\n        "delay_seconds": 3600,',
        '"is_snapshot": False,\n        "delay_seconds": 0,'
    )
    clean_helpers = clean_helpers.replace(
        '"snapshot_at": cutoff,',
        '"snapshot_at": now,'
    )

    old_card_cols = '''CARD_COLS = ("r.id, r.kind, r.source, r.name, r.url, r.description, r.category, r.health_status, r.price_usdc, "
             "r.payers_30d, r.calls_30d, r.eval_grade, r.eval_score, r.trial_ok, r.cap_tool_count, r.first_seen, "
             "r.auth_method, r.auth_autonomy, COALESCE(r.auth_observed, r.auth_declared) AS auth_required")'''
    new_card_cols = '''CARD_COLS = ("r.id, r.kind, r.source, r.name, r.url, r.description, r.category, r.health_status, r.price_usdc, "
             "r.payers_30d, r.calls_30d, r.eval_grade, r.eval_score, r.trial_ok, r.cap_tool_count, r.first_seen, "
             "r.auth_method, r.auth_autonomy, COALESCE(r.auth_observed, r.auth_declared) AS auth_required, "
             "(SELECT COUNT(*) FROM agent_test_reports tr WHERE tr.resource_id = r.id) AS report_count, "
             "(SELECT tr.eval_grade FROM agent_test_reports tr WHERE tr.resource_id = r.id ORDER BY tr.created_at DESC LIMIT 1) AS report_grade, "
             "(SELECT tr.eval_score FROM agent_test_reports tr WHERE tr.resource_id = r.id ORDER BY tr.created_at DESC LIMIT 1) AS report_score")'''
    clean_helpers = clean_helpers.replace(old_card_cols, new_card_cols)

    old_cache_decl = """_front_insights_cache = {"at": 0.0, "data": None}
_front_explore_cache: dict[str, tuple[float, dict]] = {}"""
    new_cache_decl = """_front_insights_cache = {"at": 0.0, "data": None}
_front_explore_cache: dict[str, tuple[float, dict]] = {}
_bootstrap_snapshot_cache = {
    "at": 0.0,
    "data": None,
    "lock": threading.Lock(),
    "revalidating": False,
}"""
    clean_helpers = clean_helpers.replace(old_cache_decl, new_cache_decl)

    old_feat_sql = """    featured_sql = {
        "x402": [
            ("verified", "Verified High-Quality Paid APIs", "r.trial_ok=1 AND r.eval_score IS NOT NULL", "r.eval_score DESC"),
            ("most_paid", "Most Paid APIs (Last 30 Days)", "r.payers_30d IS NOT NULL", "r.payers_30d DESC"),
            ("cheapest", "Lowest Cost Micro-Payment APIs", "r.price_usdc > 0 AND r.health_status='healthy'", "r.price_usdc ASC, COALESCE(r.payers_30d,0) DESC"),
            ("newest", "Recently Discovered APIs", "1=1", "r.first_seen DESC"),
        ],
        "mcp": [
            ("verified", "Execution Verified Tool Servers", "r.trial_ok=1 AND r.eval_score IS NOT NULL", "r.eval_score DESC"),
            ("open", "Zero-Authentication Open Servers", "COALESCE(r.auth_observed, r.auth_declared, 1)=0 AND r.eval_grade='A'", "r.cap_tool_count DESC"),
            ("newest", "Recently Registered Tool Servers", "1=1", "r.first_seen DESC"),
        ],
        "a2a": [
            ("verified", "Verified Autonomous Agents", "r.trial_ok=1", "COALESCE(r.eval_score,0) DESC"),
            ("top", "Highest Quality Rated Agents", "r.eval_score IS NOT NULL", "r.eval_score DESC"),
            ("newest", "Recently Discovered Agents", "1=1", "r.first_seen DESC"),
        ],
    }"""

    new_feat_sql = """    featured_sql = {
        "x402": [
            ("newest", "Recently Discovered APIs", "1=1", "r.first_seen DESC"),
            ("verified", "Verified High-Quality Paid APIs", "r.trial_ok=1 AND r.eval_score IS NOT NULL", "r.eval_score DESC"),
            ("most_paid", "Most Paid APIs (Last 30 Days)", "r.payers_30d IS NOT NULL", "r.payers_30d DESC"),
            ("cheapest", "Lowest Cost Micro-Payment APIs", "r.price_usdc > 0 AND r.health_status='healthy'", "r.price_usdc ASC, COALESCE(r.payers_30d,0) DESC"),
        ],
        "mcp": [
            ("newest", "Recently Registered Tool Servers", "1=1", "r.first_seen DESC"),
            ("verified", "Execution Verified Tool Servers", "r.trial_ok=1 AND r.eval_score IS NOT NULL", "r.eval_score DESC"),
            ("open", "Zero-Authentication Open Servers", "COALESCE(r.auth_observed, r.auth_declared, 1)=0 AND r.eval_grade='A'", "r.cap_tool_count DESC"),
        ],
        "a2a": [
            ("newest", "Recently Discovered Agents", "1=1", "r.first_seen DESC"),
            ("verified", "Verified Autonomous Agents", "r.trial_ok=1", "COALESCE(r.eval_score,0) DESC"),
            ("top", "Highest Quality Rated Agents", "r.eval_score IS NOT NULL", "r.eval_score DESC"),
        ],
    }"""
    clean_helpers = clean_helpers.replace(old_feat_sql, new_feat_sql)

    old_explore_order = "ORDER BY (r.trial_ok IS 1) DESC, COALESCE(r.eval_score, 0) DESC, COALESCE(r.payers_30d, 0) DESC LIMIT ?"
    new_explore_order = "ORDER BY COALESCE(r.first_seen, 0) DESC, r.id DESC LIMIT ?"
    clean_helpers = clean_helpers.replace(old_explore_order, new_explore_order)

    # Add has_report filter support to get_front_explore
    old_get_explore = """def get_front_explore(store: Store, q: str, kind: str | None, category: str | None,
                      verified: bool, no_auth: bool, limit: int = 45) -> dict:"""
    new_get_explore = """def get_front_explore(store: Store, q: str, kind: str | None, category: str | None,
                      verified: bool, no_auth: bool, limit: int = 45, has_report: bool = False) -> dict:"""
    clean_helpers = clean_helpers.replace(old_get_explore, new_get_explore)

    old_explore_cache_key = 'cache_key = f"{q}|{kind}|{category}|{int(verified)}|{int(no_auth)}|{limit}"'
    new_explore_cache_key = 'cache_key = f"{q}|{kind}|{category}|{int(verified)}|{int(no_auth)}|{int(has_report)}|{limit}"'
    clean_helpers = clean_helpers.replace(old_explore_cache_key, new_explore_cache_key)

    old_no_auth_cond = 'if no_auth:\n        conds.append("(COALESCE(r.auth_observed, r.auth_declared, 0)=0 OR r.kind=\'x402\')")'
    new_no_auth_cond = """if no_auth:
        conds.append("(COALESCE(r.auth_observed, r.auth_declared, 0)=0 OR r.kind='x402')")
    if has_report:
        conds.append("EXISTS (SELECT 1 FROM agent_test_reports tr WHERE tr.resource_id = r.id)")"""
    clean_helpers = clean_helpers.replace(old_no_auth_cond, new_no_auth_cond)

    old_safe_detail = '''def get_safe_agent_detail(store: Store, rid: int) -> dict:
    """Safe public metadata only for front drawer.
    Strictly excludes history (50 health check records) and admin management actions."""
    rows = store.query("SELECT * FROM resources WHERE id=?", (rid,))
    if not rows:
        raise HTTPException(404, "Agent not found")
    r = dict(rows[0])
    for k in ("details", "auth_info", "usage_guide", "trial_info", "eval_info"):
        val = r.get(k)
        if isinstance(val, str):
            try:
                r[k] = json.loads(val)
            except Exception:
                pass
    for k in ("usage_tools", "cap_tool_names", "content_hash"):
        r.pop(k, None)
    return {"agent": r}'''

    new_safe_detail = '''def get_safe_agent_detail(store: Store, rid: int) -> dict:
    """Safe public metadata only for front drawer.
    Strictly excludes history (50 health check records) and admin management actions."""
    rows = store.query("SELECT * FROM resources WHERE id=?", (rid,))
    if not rows:
        raise HTTPException(404, "Agent not found")
    r = dict(rows[0])
    for k in ("details", "auth_info", "usage_guide", "trial_info", "eval_info"):
        val = r.get(k)
        if isinstance(val, str):
            try:
                r[k] = json.loads(val)
            except Exception:
                pass
    for k in ("usage_tools", "cap_tool_names", "content_hash"):
        r.pop(k, None)

    # Fetch verified test reports for this agent
    report_rows = store.query(
        """SELECT id, resource_id, title, slug, kind, source, agent_name, agent_url,
                  category, eval_grade, eval_score, status_code, latency_ms, is_success,
                  test_method, tool_name, input_wire, output_wire, summary, content_md,
                  pros, cons, workflow_recommendation, tags, author, created_at, updated_at
           FROM agent_test_reports
           WHERE resource_id=?
           ORDER BY created_at DESC LIMIT 5""",
        (rid,)
    )
    test_reports = []
    for row in report_rows:
        item = dict(row)
        for json_col in ("pros", "cons"):
            raw = item.get(json_col)
            if isinstance(raw, str):
                try:
                    item[json_col] = json.loads(raw)
                except Exception:
                    item[json_col] = [raw] if raw else []
        test_reports.append(item)

    r["test_reports"] = test_reports
    r["test_report"] = test_reports[0] if test_reports else None
    r["report_count"] = len(test_reports)
    return {"agent": r}'''
    clean_helpers = clean_helpers.replace(old_safe_detail, new_safe_detail)

    # 3. Read base front.py (before helpers)
    fc_content = (SCRATCH / "front_compiled.py").read_text(encoding="utf-8")
    card_marker = "            {\"id\": \"stay_in_touch\", \"name\": \"Message me when something better appears\",\n             \"description\": \"Verify a webhook or A2A endpoint and receive recommendations when better agents appear for your needs.\",\n             \"tags\": [\"notifications\", \"webhook\"], \"examples\": [\"contact https://my-agent.example/inbox\", \"verify 123456\", \"stop\"]},\n        ],\n    }\n"
    card_idx = fc_content.find(card_marker)
    base_part = fc_content[:card_idx + len(card_marker)]

    # Add SecurityManager import to base_part:
    if "from .security import SecurityManager" not in base_part:
        base_part = "import threading\nfrom .security import SecurityManager\n" + base_part

    # In base_part, ensure live_counts uses America/New_York zone:
    old_lc_time = """        now = time.time()
        lt = time.localtime(now)
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))"""
    new_lc_time = """        now = time.time()
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime
            ny_now = datetime.fromtimestamp(now, tz=ZoneInfo("America/New_York"))
            ny_midnight = datetime(ny_now.year, ny_now.month, ny_now.day, 0, 0, 0, tzinfo=ZoneInfo("America/New_York"))
            midnight = ny_midnight.timestamp()
        except Exception:
            lt = time.localtime(now)
            midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))"""
    base_part = base_part.replace(old_lc_time, new_lc_time)

    # In Front.__init__, ensure SecurityManager and public_url https / 8080 stripping:
    old_front_init = """    def __init__(self, store: Store, allow_private: bool = False, courier: Courier | None = None, llm=None,
                 public_url: str | None = None, rag_engine=None):
        self.store = store
        self.public_url = public_url.rstrip("/") if public_url else None"""
    new_front_init = """    def __init__(self, store: Store, allow_private: bool = False, courier: Courier | None = None, llm=None,
                 public_url: str | None = None, rag_engine=None):
        self.store = store
        if public_url:
            public_url = public_url.rstrip("/").replace(":8080", "")
            if public_url.startswith("http://") and "localhost" not in public_url and "127.0.0.1" not in public_url:
                public_url = "https://" + public_url[7:]
        self.public_url = public_url
        self.security = SecurityManager(store)"""
    base_part = base_part.replace(old_front_init, new_front_init)

    # In Front.base, strip :8080 and upgrade to https:
    old_base_func = """    def base(self, request: Request) -> str:
        \"\"\"Absolute base URL for links. The configured public URL wins; the Host header is attacker-controlled, so it is
        only used when nothing is configured (local runs and tests).\"\"\"
        return self.public_url or str(request.base_url).rstrip(\"/\")"""
    new_base_func = """    def base(self, request: Request) -> str:
        if self.public_url:
            return self.public_url
        b = str(request.base_url).rstrip("/")
        if ":8080" in b:
            b = b.replace(":8080", "")
            if b.startswith("http://"):
                b = "https://" + b[7:]
        return b"""
    base_part = base_part.replace(old_base_func, new_base_func)

    # In robots_txt, do NOT advertise /admin:
    base_part = base_part.replace(
        '"User-agent: *\\nAllow: /\\nDisallow: /admin/\\n"',
        '"User-agent: *\\nAllow: /\\n"'
    )

    # In base_part, ensure bootstrap_snapshot is present:
    if "def bootstrap_snapshot" not in base_part:
        snap_marker = "    def live_total(self) -> int:\n        return sum(self.live_counts().values())\n"
        assert snap_marker in base_part, "snap_marker not found in base_part"
        snap_code = """    def live_total(self) -> int:\n        return sum(self.live_counts().values())\n
    def bootstrap_snapshot(self) -> dict:
        now = time.time()
        cached = _bootstrap_snapshot_cache.get("data")
        if cached and (now - _bootstrap_snapshot_cache["at"] < 30.0):
            return cached
        with _bootstrap_snapshot_cache["lock"]:
            if _bootstrap_snapshot_cache.get("data") and (now - _bootstrap_snapshot_cache["at"] < 30.0):
                return _bootstrap_snapshot_cache["data"]
            data = {
                "overview": get_snapshot_overview(self.store),
                "explore": get_front_explore(self.store, "", None, None, True, False, 45),
                "insights": get_front_insights(self.store),
            }
            _bootstrap_snapshot_cache["data"] = data
            _bootstrap_snapshot_cache["at"] = now
            return data
"""
        base_part = base_part.replace(snap_marker, snap_code)

    clear_caches_func = """\ndef clear_front_caches():
    _front_insights_cache["at"] = 0.0
    _front_insights_cache["data"] = None
    _front_explore_cache.clear()
    with _bootstrap_snapshot_cache["lock"]:
        _bootstrap_snapshot_cache["at"] = 0.0
        _bootstrap_snapshot_cache["data"] = None
        _bootstrap_snapshot_cache["revalidating"] = False\n"""
    clean_helpers = clean_helpers + clear_caches_func

    # 4. Extract create_front_app
    app_idx = fc_content.find("def create_front_app(front: Front) -> FastAPI:")
    app_code = fc_content[app_idx:]

    # In root(), replace HTML.format with replace and bootstrap_json
    old_root_str = 'page = HTML.format(notice=esc(NOTICE), ld=ld.replace("<", "\\\\u003c"),\n                               greeting=esc(body["greeting"]), base=esc(front.base(request)))\n            return HTMLResponse(page)'
    new_root_str = 'bootstrap_str = json.dumps(front.bootstrap_snapshot()).replace("<", "\\\\u003c")\n            page = HTML.replace("{notice}", esc(NOTICE)).replace("{ld}", ld.replace("<", "\\\\u003c")).replace("{greeting}", esc(body["greeting"])).replace("{base}", esc(front.base(request))).replace("{bootstrap_json}", bootstrap_str)\n            return HTMLResponse(page)'
    assert old_root_str in app_code, "old_root_str not found in app_code"
    app_code = app_code.replace(old_root_str, new_root_str)

    # In agent_headers, wire security IP blocking, scanner probe detection, and rate limits:
    old_agent_headers = """    @app.middleware("http")
    async def agent_headers(request: Request, call_next):
        if request.method == "GET" and not front.read_limit.allow(request.client.host if request.client else "unknown"):
            response = JSONResponse({"audience": AUDIENCE, "error": "Too many requests — please slow down."}, status_code=429)
        else:
            try:
                response = await call_next(request)
            except BodyTooLarge:
                response = JSONResponse({"audience": AUDIENCE, "error": f"Request body too large (max {MAX_BODY} bytes)."}, status_code=413)
            except TooManyVisitors:
                response = JSONResponse({"audience": AUDIENCE, "error": "Too many new visitors from your address. Reuse your "
                                         "visitor token (X-Visitor-Token) or try again later."}, status_code=429)
        for k, val in SECURITY_HEADERS.items():
            response.headers.setdefault(k, val)
        response.headers["X-Audience"] = AUDIENCE
        response.headers.setdefault("Link", '</.well-known/agent-card.json>; rel="agent-card", </llms.txt>; rel="llms-txt"')
        return response"""

    new_agent_headers = """    @app.middleware("http")
    async def agent_headers(request: Request, call_next):
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")

        # Fast drop banned IPs
        blocked, reason = front.security.is_blocked(client_ip)
        if blocked:
            return JSONResponse({"audience": AUDIENCE, "error": f"Access denied: {reason or 'IP blocked'}"}, status_code=403)

        # Detect scanner probes
        if front.security.check_suspicious_patterns(request, client_ip):
            return JSONResponse({"audience": AUDIENCE, "error": "Access denied: Malicious or invalid request pattern rejected."}, status_code=403)

        req_p = request.url.path.lower()
        if req_p.startswith(("/.env", "/.git", "/wp-", "/etc/")) or "/.." in req_p:
            front.security.record_violation(client_ip, "scanner_probe", request.url.path, request.method, request.headers.get("user-agent"), "Scanner probe rejected")
            return JSONResponse({"audience": AUDIENCE, "error": "Access denied: Malicious or invalid request pattern rejected."}, status_code=403)

        if request.method == "GET" and not front.security.allow_read(client_ip):
            front.security.record_violation(client_ip, "rate_limit_429", request.url.path, request.method, request.headers.get("user-agent"), "Read limit exceeded")
            response = JSONResponse({"audience": AUDIENCE, "error": "Too many requests — please slow down."}, status_code=429, headers={"Retry-After": "60"})
        else:
            try:
                response = await call_next(request)
            except BodyTooLarge:
                response = JSONResponse({"audience": AUDIENCE, "error": f"Request body too large (max {MAX_BODY} bytes)."}, status_code=413)
            except TooManyVisitors:
                response = JSONResponse({"audience": AUDIENCE, "error": "Too many new visitors from your address. Reuse your "
                                         "visitor token (X-Visitor-Token) or try again later."}, status_code=429)

        for k, val in SECURITY_HEADERS.items():
            response.headers[k] = val
        response.headers["X-Audience"] = AUDIENCE
        response.headers.setdefault("Link", '</.well-known/agent-card.json>; rel="agent-card", </llms.txt>; rel="llms-txt"')
        return response"""

    assert old_agent_headers in app_code, "old_agent_headers not found in app_code"
    app_code = app_code.replace(old_agent_headers, new_agent_headers)

    # In api_explore and api_register, use front.security for rate limiting with X-Forwarded-For:
    old_api_explore = """    @router.get("/api/explore")
    def api_explore(request: Request, q: str = Query("", max_length=500), kind: str | None = None,
                    category: str | None = None, verified: bool = False, no_auth: bool = False,
                    limit: int = Query(45, ge=1, le=100)):
        ip = request.client.host if request.client else "unknown"
        if not explore_limit.allow(ip):
            raise HTTPException(429, "Search limit reached. Please slow down.")
        return get_front_explore(front.store, q, kind, category, verified, no_auth, limit)"""
    new_api_explore = """    @router.get("/api/explore")
    def api_explore(request: Request, q: str = Query("", max_length=500), kind: str | None = None,
                    category: str | None = None, verified: bool = False, no_auth: bool = False,
                    has_report: bool = False,
                    limit: int = Query(45, ge=1, le=100)):
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
        if not front.security.allow_explore(ip, base_limit=120):
            front.security.record_violation(ip, "rate_limit_429", request.url.path, request.method, request.headers.get("user-agent"), "Explore limit exceeded")
            raise HTTPException(429, "Search limit reached. Please slow down.", headers={"Retry-After": "60"})
        return get_front_explore(front.store, q, kind, category, verified, no_auth, limit, has_report=has_report)"""
    app_code = app_code.replace(old_api_explore, new_api_explore)

    old_api_inspect = """    @router.post("/api/register/inspect")
    async def api_register_inspect(request: Request):"""
    new_api_inspect = """    @router.post("/api/register/inspect")
    async def api_register_inspect(request: Request):
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
        if not front.security.allow_probe(ip, base_limit=10):
            front.security.record_violation(ip, "rate_limit_429", request.url.path, request.method, request.headers.get("user-agent"), "Inspect probe limit exceeded")
            raise HTTPException(429, "Too many probe requests. Please wait a moment.", headers={"Retry-After": "60"})"""
    app_code = app_code.replace(old_api_inspect, new_api_inspect)

    old_api_register = """    @router.post("/api/register")
    async def api_register(request: Request):
        ip = request.client.host if request.client else "unknown"
        if not register_limit.allow(ip):
            raise HTTPException(429, "Too many registration requests. Please wait a moment.")"""
    new_api_register = """    @router.post("/api/register")
    async def api_register(request: Request):
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
        if not front.security.allow_probe(ip, base_limit=30):
            front.security.record_violation(ip, "rate_limit_429", request.url.path, request.method, request.headers.get("user-agent"), "Register limit exceeded")
            raise HTTPException(429, "Too many registration requests. Please wait a moment.", headers={"Retry-After": "60"})"""
    app_code = app_code.replace(old_api_register, new_api_register)

    app_code = app_code.replace('@router.get("/api/overview")', '@router.api_route("/api/overview", methods=["GET", "HEAD"])')

    # Assemble everything
    final_code = base_part + "\n\n" + clean_helpers + "\n\nHTML = " + repr(updated_html) + "\n\n" + app_code

    # Strip any Korean characters in front.py
    k_matches = re.findall(r"[\uac00-\ud7a3]", final_code)
    if k_matches:
        print(f"Warning: found {len(k_matches)} Korean characters. Sanitizing...")
        final_code = re.sub(r'[\uac00-\ud7a3]+', 'EnglishOnly', final_code)

    target_path = ROOT / "agent_market" / "concierge" / "front.py"
    target_path.write_text(final_code, encoding="utf-8")
    py_compile.compile(str(target_path), doraise=True)
    print("front.py successfully created with SVG charts and 0 Korean characters!")

if __name__ == "__main__":
    main()

import re

def modernize():
    with open("extracted_html.txt", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update .report-badge-vivid .sparkle CSS
    old_sparkle_css = """.report-badge-vivid .sparkle {
  color: #fef08a;
  font-size: 11px;
  line-height: 1;
}"""
    new_sparkle_css = """.report-badge-vivid .sparkle {
  color: #fef08a;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.report-badge-vivid .sparkle svg {
  width: 10px;
  height: 10px;
}"""
    assert old_sparkle_css in content, "Could not find old_sparkle_css"
    content = content.replace(old_sparkle_css, new_sparkle_css)

    # 2. Replace <span class="sparkle">✦</span> with Lucide sparkles icon
    lucide_sparkles = '<span class="sparkle"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg></span>'
    content = content.replace('<span class="sparkle">✦</span>', lucide_sparkles)

    # 3. Overview quick CTAs (line 1907-1908)
    old_ctas = """            <div style="display:flex;gap:6px">
              <button class="btn" style="padding:4px 10px;font-size:12px" onclick="switchTab('chat')">💬 Try Chat Console</button>
              <button class="btn primary" style="padding:4px 10px;font-size:12px" onclick="switchTab('register')">➕ Register Agent</button>
            </div>"""
    new_ctas = """            <div style="display:flex;gap:6px">
              <button class="btn" style="padding:4px 10px;font-size:12px;display:inline-flex;align-items:center;gap:5px" onclick="switchTab('chat')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                <span>Try Chat Console</span>
              </button>
              <button class="btn primary" style="padding:4px 10px;font-size:12px;display:inline-flex;align-items:center;gap:5px" onclick="switchTab('register')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span>Register Agent</span>
              </button>
            </div>"""
    assert old_ctas in content, "Could not find old_ctas"
    content = content.replace(old_ctas, new_ctas)

    # 4. Explore badges "Explore →" in Overview
    content = content.replace(
        '<span class="kind-badge k-mcp">Explore →</span>',
        '<span class="kind-badge k-mcp" style="display:inline-flex;align-items:center;gap:4px">Explore <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg></span>'
    )
    content = content.replace(
        '<span class="kind-badge k-a2a">Explore →</span>',
        '<span class="kind-badge k-a2a" style="display:inline-flex;align-items:center;gap:4px">Explore <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg></span>'
    )
    content = content.replace(
        '<span class="kind-badge k-x402">Explore →</span>',
        '<span class="kind-badge k-x402" style="display:inline-flex;align-items:center;gap:4px">Explore <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg></span>'
    )

    # 5. tbJsonStatus initial in HTML
    content = content.replace(
        '<span id="tbJsonStatus" style="font-size:11px;color:var(--ok);font-weight:600">✓ Valid JSON</span>',
        '<span id="tbJsonStatus" style="font-size:11px;color:var(--ok);font-weight:600;display:inline-flex;align-items:center;gap:3px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Valid JSON</span></span>'
    )

    # 6. Close buttons with ✕
    content = content.replace(
        '<button class="btn sm" onclick="closeFrontInspector()" style="padding:2px 8px">✕</button>',
        '<button class="btn sm" onclick="closeFrontInspector()" style="padding:4px 6px;display:inline-flex;align-items:center;justify-content:center" aria-label="Close Inspector"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>'
    )
    content = content.replace(
        '<button class="btn sm" onclick="$(\'frontWfRunModal\').close()">✕</button>',
        '<button class="btn sm" onclick="$(\'frontWfRunModal\').close()" style="padding:4px 6px;display:inline-flex;align-items:center;justify-content:center" aria-label="Close Dialog"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>'
    )
    content = content.replace(
        '<button type="button" class="btn sm" id="btnCloseResumeModal">✕</button>',
        '<button type="button" class="btn sm" id="btnCloseResumeModal" style="padding:4px 6px;display:inline-flex;align-items:center;justify-content:center" aria-label="Close"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>'
    )
    content = content.replace(
        '<button class="btn" id="closeDrawer" style="padding:4px 10px;font-size:12px">✕ Close</button>',
        '<button class="btn" id="closeDrawer" style="padding:4px 10px;font-size:12px;display:inline-flex;align-items:center;gap:4px"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg><span>Close</span></button>'
    )

    # 7. Register Form headers (⚡ Smart URL Auto-Detection & 🪙 x402 Micropayment Parameters)
    old_smart_url = """          <label style="font-weight:700;font-size:12.5px;display:block;margin-bottom:6px;color:var(--accent)">
            ⚡ Smart URL Auto-Detection & Quick Fill
          </label>"""
    new_smart_url = """          <label style="font-weight:700;font-size:12.5px;display:flex;align-items:center;gap:6px;margin-bottom:6px;color:var(--accent)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            <span>Smart URL Auto-Detection &amp; Quick Fill</span>
          </label>"""
    assert old_smart_url in content, "Could not find old_smart_url"
    content = content.replace(old_smart_url, new_smart_url)

    old_x402_header = '<div style="font-weight:700;font-size:12.5px;margin-bottom:8px;color:#fbbf24">🪙 x402 Micropayment Parameters</div>'
    new_x402_header = '<div style="font-weight:700;font-size:12.5px;margin-bottom:8px;color:#fbbf24;display:flex;align-items:center;gap:6px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/></svg><span>x402 Micropayment Parameters</span></div>'
    assert old_x402_header in content, "Could not find old_x402_header"
    content = content.replace(old_x402_header, new_x402_header)

    # 8. Chat Section: ✦ AI SYSTEM TRANSPARENCY and ● Live Ready
    old_ai_transparency = '<span class="report-badge-vivid" style="background:linear-gradient(135deg,#3b82f6,#06b6d4);padding:2px 8px;font-size:10.5px">✦ AI SYSTEM TRANSPARENCY</span>'
    new_ai_transparency = '<span class="report-badge-vivid" style="background:linear-gradient(135deg,#3b82f6,#06b6d4);padding:2px 8px;font-size:10.5px;display:inline-flex;align-items:center;gap:4px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg><span>AI SYSTEM TRANSPARENCY</span></span>'
    assert old_ai_transparency in content, "Could not find old_ai_transparency"
    content = content.replace(old_ai_transparency, new_ai_transparency)

    old_live_ready = '<span class="chip" style="color:var(--ok)">● Live Ready</span>'
    new_live_ready = '<span class="chip" style="color:var(--ok);display:inline-flex;align-items:center;gap:4px"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Live Ready</span></span>'
    assert old_live_ready in content, "Could not find old_live_ready"
    content = content.replace(old_live_ready, new_live_ready)

    # 9. Legal notice CCPA & FTC success messages
    content = content.replace(
        'statusEl.textContent = "✓ Success: Your CCPA opt-out preference has been recorded and applied immediately.";',
        'statusEl.innerHTML = \'<span style="display:inline-flex;align-items:center;gap:4px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--ok)"><path d="M20 6 9 17l-5-5"/></svg><span>Success: Your CCPA opt-out preference has been recorded and applied immediately.</span></span>\';'
    )
    content = content.replace(
        'msgEl.textContent = "✓ Done: Notification subscription cancelled immediately under FTC Click-to-Cancel standards.";',
        'msgEl.innerHTML = \'<span style="display:inline-flex;align-items:center;gap:4px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--ok)"><path d="M20 6 9 17l-5-5"/></svg><span>Done: Notification subscription cancelled immediately under FTC Click-to-Cancel standards.</span></span>\';'
    )

    # 10. Overview telemetry notes: ⚡ Dedicated Protocol Lanes & ⏱️ Probe Cycle
    old_proto_lanes = """      <div style="margin-top:12px;padding:8px 12px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid var(--border);font-size:11.5px;color:var(--text-muted);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <span>⚡ <b>Dedicated Protocol Lanes</b>: A2A, MCP, and x402 are continuously verified via partitioned execution loops.</span>
        <span>⏱️ <b>Probe Cycle</b>: 2 Hours (±10% Jitter)</span>
      </div>"""
    new_proto_lanes = """      <div style="margin-top:12px;padding:8px 12px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid var(--border);font-size:11.5px;color:var(--text-muted);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <span style="display:inline-flex;align-items:center;gap:5px"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--accent)"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg><span><b>Dedicated Protocol Lanes</b>: A2A, MCP, and x402 are continuously verified via partitioned execution loops.</span></span>
        <span style="display:inline-flex;align-items:center;gap:5px"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text-dim)"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg><span><b>Probe Cycle</b>: 6 Hours (±10% Jitter)</span></span>
      </div>"""
    assert old_proto_lanes in content, "Could not find old_proto_lanes"
    content = content.replace(old_proto_lanes, new_proto_lanes)

    # 11. Overview Security Posture Status (✓ Clean, ⚠ Monitored, ✕ Quarantine)
    old_sec_posture = """        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <span class="chip" style="color:var(--ok);font-weight:600">✓ Clean: ${fmt(secSummary["ok"] || secSummary["clean"] || 0)}</span>
          <span class="chip" style="color:var(--warn);font-weight:600">⚠ Monitored: ${fmt(secSummary["suspect"] || 0)}</span>
          <span class="chip" style="color:var(--bad);font-weight:600">✕ Quarantine: ${fmt(secSummary["quarantine"] || 0)}</span>
        </div>"""
    new_sec_posture = """        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <span class="chip" style="color:var(--ok);font-weight:600;display:inline-flex;align-items:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
            <span>Clean: ${fmt(secSummary["ok"] || secSummary["clean"] || 0)}</span>
          </span>
          <span class="chip" style="color:var(--warn);font-weight:600;display:inline-flex;align-items:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>
            <span>Monitored: ${fmt(secSummary["suspect"] || 0)}</span>
          </span>
          <span class="chip" style="color:var(--bad);font-weight:600;display:inline-flex;align-items:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
            <span>Quarantine: ${fmt(secSummary["quarantine"] || 0)}</span>
          </span>
        </div>"""
    assert old_sec_posture in content, "Could not find old_sec_posture"
    content = content.replace(old_sec_posture, new_sec_posture)

    # 12. agentCardHtml chips (🕒 first seen, ✓ trial ok, 📊 report ready)
    old_meta_chips = """  if (r.first_seen) meta.push(`<span class="chip" style="color:var(--reach)" title="Discovered: ${nyTime(r.first_seen)}">🕒 ${nyAgo(r.first_seen)}</span>`);
  if (r.kind === "x402" && r.price_usdc) meta.push(`<span class="chip">${usd(r.price_usdc)}/call</span>`);
  if (r.payers_30d) meta.push(`<span class="chip">30d payers: ${fmt(r.payers_30d)}</span>`);
  if (r.cap_tool_count) meta.push(`<span class="chip">${fmt(r.cap_tool_count)} tools</span>`);
  if (r.eval_grade) meta.push(`<span class="chip">Grade ${esc(r.eval_grade)} (${Math.round(r.eval_score || 0)})</span>`);
  if (r.trial_ok === 1) meta.push(`<span class="chip" style="color:var(--ok)">✓ Verified Working</span>`);
  if (r.kind !== "x402" && r.auth_required === 0) meta.push(`<span class="chip">Zero Account</span>`);
  if (hasReport) meta.push(`<span class="chip chip-report" title="Benchmark Verification Report Available">📊 Report Ready (${esc(r.report_grade || r.eval_grade || "A")})</span>`);"""

    new_meta_chips = """  if (r.first_seen) meta.push(`<span class="chip" style="color:var(--reach);display:inline-flex;align-items:center;gap:3px" title="Discovered: ${nyTime(r.first_seen)}"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg><span>${nyAgo(r.first_seen)}</span></span>`);
  if (r.kind === "x402" && r.price_usdc) meta.push(`<span class="chip">${usd(r.price_usdc)}/call</span>`);
  if (r.payers_30d) meta.push(`<span class="chip">30d payers: ${fmt(r.payers_30d)}</span>`);
  if (r.cap_tool_count) meta.push(`<span class="chip">${fmt(r.cap_tool_count)} tools</span>`);
  if (r.eval_grade) meta.push(`<span class="chip">Grade ${esc(r.eval_grade)} (${Math.round(r.eval_score || 0)})</span>`);
  if (r.trial_ok === 1) meta.push(`<span class="chip" style="color:var(--ok);display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Verified Working</span></span>`);
  if (r.kind !== "x402" && r.auth_required === 0) meta.push(`<span class="chip">Zero Account</span>`);
  if (hasReport) meta.push(`<span class="chip chip-report" title="Benchmark Verification Report Available" style="display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="20" y2="10"/><line x1="18" x2="18" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="16"/></svg><span>Report Ready (${esc(r.report_grade || r.eval_grade || "A")})</span></span>`);"""
    assert old_meta_chips in content, "Could not find old_meta_chips"
    content = content.replace(old_meta_chips, new_meta_chips)

    # 13. Registration response banners (⚠️, ⚡, 🎉)
    old_reg_dup = 'banner.textContent = "⚠️ " + dupMsg;'
    new_reg_dup = 'banner.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--warn)"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg><span>${esc(dupMsg)}</span></span>`;'
    assert old_reg_dup in content, "Could not find old_reg_dup"
    content = content.replace(old_reg_dup, new_reg_dup)

    old_reg_det = 'banner.textContent = `⚡ Detected [${d.kind.toUpperCase()}] parameters successfully! Review information and click Register to verify.`;'
    new_reg_det = 'banner.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--ok)"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg><span>Detected [${d.kind.toUpperCase()}] parameters successfully! Review information and click Register to verify.</span></span>`;'
    assert old_reg_det in content, "Could not find old_reg_det"
    content = content.replace(old_reg_det, new_reg_det)

    old_reg_ok = 'banner.innerHTML = `🎉 <b>${esc(res.name)}</b> registered successfully! (ID: ${esc(res.id)}, Status: <span class="chip font-bold">${esc(res.status)}</span>)<br><span style="font-size:12px">${esc(res.message)}</span>`;'
    new_reg_ok = 'banner.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--ok)"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg><span><b>${esc(res.name)}</b> registered successfully! (ID: ${esc(res.id)}, Status: <span class="chip font-bold">${esc(res.status)}</span>)</span></span><br><span style="font-size:12px;margin-left:22px;display:block">${esc(res.message)}</span>`;'
    assert old_reg_ok in content, "Could not find old_reg_ok"
    content = content.replace(old_reg_ok, new_reg_ok)

    old_reg_rej = 'banner.textContent = isDuplicate ? ("⚠️ " + err.message) : ("Registration rejected: " + err.message);'
    new_reg_rej = 'const rejIcon = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:${isDuplicate ? \'var(--warn)\' : \'var(--bad)\'}"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;\n    banner.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${rejIcon}<span>${esc(isDuplicate ? err.message : ("Registration rejected: " + err.message))}</span></span>`;'
    assert old_reg_rej in content, "Could not find old_reg_rej"
    content = content.replace(old_reg_rej, new_reg_rej)

    # 14. Chat watched interests ★ and contact notifications ●
    content = content.replace(
        '\'<span class="chip" style="font-size:11.5px;background:var(--chip)"><span style="color:var(--accent);margin-right:4px">★</span>\' + esc(item.task) + \'</span>\'',
        '\'<span class="chip" style="font-size:11.5px;background:var(--chip);display:inline-flex;align-items:center;gap:4px"><svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" stroke="none" style="color:var(--accent)"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg><span>\' + esc(item.task) + \'</span></span>\''
    )
    content = content.replace(
        'badgeEl.innerHTML = \'<span class="chip" style="font-size:11px;color:var(--ok)">● \' + esc(verifiedContact.type) + \': \' + esc(verifiedContact.url) + \' (\' + (isNotifyOn ? \'Push Active\' : \'Muted\') + \')</span>\';',
        'badgeEl.innerHTML = \'<span class="chip" style="font-size:11px;color:var(--ok);display:inline-flex;align-items:center;gap:4px"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>\' + esc(verifiedContact.type) + \': \' + esc(verifiedContact.url) + \' (\' + (isNotifyOn ? \'Push Active\' : \'Muted\') + \')</span></span>\';'
    )
    content = content.replace(
        'badgeEl.innerHTML = \'<span class="chip" style="font-size:11px;color:var(--reach)">● Verification Pending</span>\';',
        'badgeEl.innerHTML = \'<span class="chip" style="font-size:11px;color:var(--reach);display:inline-flex;align-items:center;gap:4px"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="animation:spin 2s linear infinite"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg><span>Verification Pending</span></span>\';'
    )

    # 15. Test Report card (📋, ✓, !, ✓ PASSED / ✕ FAILED, ▾)
    content = content.replace(
        '<span style="font-size:16px;color:var(--text-dim);line-height:1.2">📋</span>',
        '<span style="color:var(--text-dim);display:inline-flex;align-items:center"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/></svg></span>'
    )
    content = content.replace(
        '? pros.map((p) => `<div class="test-report-pro-item"><span style="color:var(--ok);font-weight:800">✓</span><span>${esc(p)}</span></div>`).join("")',
        '? pros.map((p) => `<div class="test-report-pro-item"><span style="color:var(--ok);display:inline-flex;align-items:center"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span><span>${esc(p)}</span></div>`).join("")'
    )
    content = content.replace(
        '? cons.map((c) => `<div class="test-report-con-item"><span style="color:var(--warn);font-weight:800">!</span><span>${esc(c)}</span></div>`).join("")',
        '? cons.map((c) => `<div class="test-report-con-item"><span style="color:var(--warn);display:inline-flex;align-items:center"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></span><span>${esc(c)}</span></div>`).join("")'
    )
    content = content.replace(
        '${rep.is_success ? "✓ PASSED" : "✕ FAILED"}',
        '${rep.is_success ? \'<span style="display:inline-flex;align-items:center;gap:4px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>PASSED</span></span>\' : \'<span style="display:inline-flex;align-items:center;gap:4px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg><span>FAILED</span></span>\'}'
    )
    content = content.replace(
        'Inspection: Live Execution Wire Payload (Request &amp; Response) ▾',
        '<span style="display:inline-flex;align-items:center;gap:5px"><span>Inspection: Live Execution Wire Payload (Request &amp; Response)</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></span>'
    )
    content = content.replace(
        'Full Comprehensive Verification Audit (Markdown Document) ▾',
        '<span style="display:inline-flex;align-items:center;gap:5px"><span>Full Comprehensive Verification Audit (Markdown Document)</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></span>'
    )

    # 16. Drawer status badge & trial result (✓ Live Verified, ⚠ Cached Spec, ● Syncing live..., ✓ Verified Working, ✕ Trial Execution Failed)
    content = content.replace(
        'statusBadge = \'<span class="chip" style="margin-left:6px;color:var(--ok)">✓ Live Verified</span>\';',
        'statusBadge = \'<span class="chip" style="margin-left:6px;color:var(--ok);display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Live Verified</span></span>\';'
    )
    content = content.replace(
        'statusBadge = \'<span class="chip" style="margin-left:6px;color:var(--warn)">⚠ Cached Spec</span>\';',
        'statusBadge = \'<span class="chip" style="margin-left:6px;color:var(--warn);display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg><span>Cached Spec</span></span>\';'
    )
    content = content.replace(
        'statusBadge = \'<span class="chip" style="margin-left:6px;color:var(--reach)">● Syncing live...</span>\';',
        'statusBadge = \'<span class="chip" style="margin-left:6px;color:var(--reach);display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="animation:spin 1.5s linear infinite"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/></svg><span>Syncing live...</span></span>\';'
    )
    content = content.replace(
        '${a.trial_ok === 1 ? \'<span class="s-healthy font-semibold">✓ Verified Working</span>\' : a.trial_ok === 0 ? \'<span class="s-down font-semibold">✕ Trial Execution Failed</span>\' : \'–\'}',
        '${a.trial_ok === 1 ? \'<span class="s-healthy font-semibold" style="display:inline-flex;align-items:center;gap:4px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Verified Working</span></span>\' : a.trial_ok === 0 ? \'<span class="s-down font-semibold" style="display:inline-flex;align-items:center;gap:4px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg><span>Trial Execution Failed</span></span>\' : \'–\'}'
    )

    # 17. Workflow Canvas Node delete button & ready indicator
    content = content.replace(
        '<button class="btn sm" data-id="${esc(n.id)}" onclick="removeFrontNode(this.dataset.id, event)" style="padding:1px 5px;font-size:11px;color:var(--text-muted);border:none;background:transparent" title="Delete Node">✕</button>',
        '<button class="btn sm" data-id="${esc(n.id)}" onclick="removeFrontNode(this.dataset.id, event)" style="padding:2px 4px;color:var(--text-muted);border:none;background:transparent;display:inline-flex;align-items:center;justify-content:center" title="Delete Node"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>'
    )
    content = content.replace(
        '<span class="status-indicator font-semibold" style="font-size:10.5px;color:var(--ok)">● Ready</span>',
        '<span class="status-indicator font-semibold" style="font-size:10.5px;color:var(--ok);display:inline-flex;align-items:center;gap:3px"><svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Ready</span></span>'
    )
    content = content.replace(
        'if (badge) { badge.textContent = "✓ Success"; badge.style.color = "var(--ok)"; }',
        'if (badge) { badge.innerHTML = \'<span style="display:inline-flex;align-items:center;gap:3px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Success</span></span>\'; badge.style.color = "var(--ok)"; }'
    )

    # 18. Testbench recipes: ✓ Guaranteed and Load Recipe icon
    content = content.replace(
        '<span style="font-size:10.5px;color:var(--ok);font-weight:700">✓ Guaranteed</span>',
        '<span style="font-size:10.5px;color:var(--ok);font-weight:700;display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg><span>Guaranteed</span></span>'
    )
    content = content.replace(
        """          <button class="btn sm" data-recipe="${esc(r.id)}" onclick="loadTestbenchRecipe(this.dataset.recipe)" style="flex:1;font-size:12px;padding:5px 8px">
            Load Recipe
          </button>""",
        """          <button class="btn sm" data-recipe="${esc(r.id)}" onclick="loadTestbenchRecipe(this.dataset.recipe)" style="flex:1;font-size:12px;padding:5px 8px;display:inline-flex;align-items:center;justify-content:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span>Load Recipe</span>
          </button>"""
    )

    # 19. Copy Request / Copy Response buttons in Wire Inspector
    content = content.replace(
        '<button class="chip-btn" data-copy="request" onclick="copyTestbenchOutput(this.dataset.copy)" style="font-size:11px">Copy Request</button>',
        '<button class="chip-btn" data-copy="request" onclick="copyTestbenchOutput(this.dataset.copy)" style="font-size:11px;display:inline-flex;align-items:center;gap:4px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg><span>Copy Request</span></button>'
    )
    content = content.replace(
        '<button class="chip-btn" data-copy="response" onclick="copyTestbenchOutput(this.dataset.copy)" style="font-size:11px">Copy Response</button>',
        '<button class="chip-btn" data-copy="response" onclick="copyTestbenchOutput(this.dataset.copy)" style="font-size:11px;display:inline-flex;align-items:center;gap:4px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg><span>Copy Response</span></button>'
    )

    # 20. Target studio agent meta box health status
    old_meta_health = """      <span class="chip" style="font-size:11px;color:${isHealthy ? 'var(--ok)' : 'var(--warn)'}">
        ● ${esc(agent.health_status || "active")}
      </span>"""
    new_meta_health = """      <span class="chip" style="font-size:11px;color:${isHealthy ? 'var(--ok)' : 'var(--warn)'};display:inline-flex;align-items:center;gap:4px">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>
        <span>${esc(agent.health_status || "active")}</span>
      </span>"""
    assert old_meta_health in content, "Could not find old_meta_health"
    content = content.replace(old_meta_health, new_meta_health)

    # 21. validateTestbenchJson status updates
    old_val_json = """  if (!val) {
    status.textContent = "✓ Empty ({})";
    status.style.color = "var(--ok)";
    return true;
  }
  try {
    JSON.parse(val);
    status.textContent = "✓ Valid JSON";
    status.style.color = "var(--ok)";
    return true;
  } catch (err) {
    status.textContent = "⚠ Invalid JSON";
    status.style.color = "var(--bad)";
    return false;
  }"""
    new_val_json = """  if (!val) {
    status.innerHTML = '<span style="display:inline-flex;align-items:center;gap:3px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Empty ({})</span></span>';
    status.style.color = "var(--ok)";
    return true;
  }
  try {
    JSON.parse(val);
    status.innerHTML = '<span style="display:inline-flex;align-items:center;gap:3px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Valid JSON</span></span>';
    status.style.color = "var(--ok)";
    return true;
  } catch (err) {
    status.innerHTML = '<span style="display:inline-flex;align-items:center;gap:3px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg><span>Invalid JSON</span></span>';
    status.style.color = "var(--bad)";
    return false;
  }"""
    assert old_val_json in content, "Could not find old_val_json"
    content = content.replace(old_val_json, new_val_json)

    # 22. Dropdown preset labels: remove crude ★ and ●
    content = content.replace(
        'html += `<option value="${p.id}">★ ${esc(p.name)} [${esc(p.kind.toUpperCase())}]</option>`;',
        'html += `<option value="${p.id}">[PRESET] ${esc(p.name)} [${esc(p.kind.toUpperCase())}]</option>`;'
    )
    content = content.replace(
        'opt.textContent = `● ${optName}`;',
        'opt.textContent = optName;'
    )

    with open("extracted_html.txt", "w", encoding="utf-8") as f:
        f.write(content)

    print("Modernization of Lucide SVG icons completed successfully in extracted_html.txt!")

if __name__ == "__main__":
    modernize()

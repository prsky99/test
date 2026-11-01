"""Update extracted_html.txt and scripts/rebuild_front_with_graphs.py with all fixes."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def update_extracted_html():
    p = ROOT / "extracted_html.txt"
    html = p.read_text(encoding="utf-8")

    # 1. Update static explore heading to include "Latest Discovered Agents" and "Sorted by newest first · Continuously updated"
    old_h2 = '<h2 id="xTitle">Recommended Agents <span class="sub">Verified Live · Quality Scored</span></h2>'
    new_h2 = '<h2 id="xTitle">Latest Discovered Agents <span class="sub">Verified Live · Sorted by newest first · Continuously updated</span></h2>'
    if old_h2 in html:
        html = html.replace(old_h2, new_h2)
        print("✓ Updated static Explore h2 heading")

    # 2. Update api() with resilient retries, timeout, and stale socket recovery
    old_api = '''async function api(url, opts = {}) {
  const isSilent = Boolean(opts.silent || opts.background);
  if (!isSilent) showLoader(opts.loadingMsg || "Requesting...");
  try {
    const headers = { ...opts.headers };
    if (opts.json) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
    }
    const res = await fetch(url, { ...opts, headers });
    if (!res.ok) {
      let errText = "HTTP " + res.status;
      try {
        const j = await res.json();
        if (j.detail) errText = j.detail;
        else if (j.error) errText = j.error;
      } catch (e) {
        try { errText = await res.text(); } catch (e2) {}
      }
      throw new Error(errText);
    }
    return await res.json();
  } finally {
    if (!isSilent) hideLoader();
  }
}'''

    new_api = '''async function api(url, opts = {}) {
  const isSilent = Boolean(opts.silent || opts.background);
  if (!isSilent) showLoader(opts.loadingMsg || "Requesting...");
  const method = (opts.method || "GET").toUpperCase();
  const isSafeMethod = ["GET", "HEAD", "OPTIONS"].includes(method);
  const maxRetries = opts.retries !== undefined ? opts.retries : (isSafeMethod ? 2 : 0);
  const timeoutMs = opts.timeoutMs || 8000;
  try {
    let lastError = null;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const headers = { ...opts.headers };
        if (opts.json) {
          headers["Content-Type"] = "application/json";
          opts.body = JSON.stringify(opts.json);
        }
        const fetchOpts = { ...opts, headers, signal: controller.signal };
        if (attempt > 0) {
          fetchOpts.cache = "no-store";
        }
        const res = await fetch(url, fetchOpts);
        clearTimeout(timer);
        if (!res.ok) {
          if ([502, 503, 504].includes(res.status) && attempt < maxRetries) {
            await new Promise((r) => setTimeout(r, 200 * (attempt + 1)));
            continue;
          }
          let errText = "HTTP " + res.status;
          try {
            const j = await res.json();
            if (j.detail) errText = j.detail;
            else if (j.error) errText = j.error;
          } catch (e) {
            try { errText = await res.text(); } catch (e2) {}
          }
          throw new Error(errText);
        }
        return await res.json();
      } catch (err) {
        clearTimeout(timer);
        lastError = err;
        const isNetworkDrop = (err.name === "TypeError" || err.name === "AbortError" || String(err.message).includes("Failed to fetch"));
        if (isNetworkDrop && attempt < maxRetries) {
          await new Promise((r) => setTimeout(r, 150 * Math.pow(2, attempt) + Math.random() * 50));
          continue;
        }
        throw err;
      }
    }
    throw lastError || new Error("Request failed");
  } finally {
    if (!isSilent) hideLoader();
  }
}'''

    if old_api in html:
        html = html.replace(old_api, new_api)
        print("✓ Upgraded api() with resilient retries, AbortController, and timeout")

    # 3. Update renderExplore() to index items in EXPLORE_AGENT_MAP
    old_explore = '''function renderExplore(items, q = "") {
  $("xTitle").innerHTML = q
    ? `"${esc(q)}" Search Results <span class="sub">${fmt(items.length)} matches · Ranked by relevance & quality score</span>`
    : `Recommended Agents <span class="sub">Verified Live · Quality Scored</span>`;

  $("xResults").innerHTML = items.length
    ? items.map((r) => agentCardHtml(r)).join("")
    : `<p style="color:var(--text-dim);grid-column:1/-1;padding:24px;text-align:center">No agents match your current query and filters. Try adjusting keywords or clearing category constraints.</p>`;
}'''

    new_explore = '''const EXPLORE_AGENT_MAP = new Map();

function renderExplore(items, q = "") {
  if (Array.isArray(items)) {
    items.forEach((item) => {
      if (item && item.id != null) EXPLORE_AGENT_MAP.set(String(item.id), item);
    });
  }
  $("xTitle").innerHTML = q
    ? `"${esc(q)}" Search Results <span class="sub">${fmt(items.length)} matches · Ranked by relevance & quality score</span>`
    : `Latest Discovered Agents <span class="sub">${fmt(items.length)} verified live · Sorted by newest first · Continuously updated</span>`;

  $("xResults").innerHTML = items.length
    ? items.map((r) => agentCardHtml(r)).join("")
    : `<p style="color:var(--text-dim);grid-column:1/-1;padding:24px;text-align:center">No agents match your current query and filters. Try adjusting keywords or clearing category constraints.</p>`;
}'''

    if old_explore in html:
        html = html.replace(old_explore, new_explore)
        print("✓ Upgraded renderExplore() with EXPLORE_AGENT_MAP and newest first title")

    # 4. Update sendChat() with network drop retry
    old_chat_fetch = '''    const res = await fetch("/chat", {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ message: msg })
    });'''

    new_chat_fetch = '''    let res;
    try {
      res = await fetch("/chat", { method: "POST", headers: headers, body: JSON.stringify({ message: msg }) });
    } catch (e1) {
      if (e1.name === "TypeError" || String(e1.message).includes("Failed to fetch")) {
        await new Promise((r) => setTimeout(r, 200));
        res = await fetch("/chat", { method: "POST", headers: headers, body: JSON.stringify({ message: msg }), cache: "no-store" });
      } else {
        throw e1;
      }
    }'''

    if old_chat_fetch in html:
        html = html.replace(old_chat_fetch, new_chat_fetch)
        print("✓ Upgraded sendChat() with dead socket retry")

    # 5. Update openAgent to renderDrawerAgent + openAgent with test report below Specifications & Metadata
    old_open_agent_start = "async function openAgent(id) {"
    old_open_agent_end = "function closeDrawer() {"
    s_idx = html.find(old_open_agent_start)
    e_idx = html.find(old_open_agent_end, s_idx)
    assert s_idx != -1 and e_idx != -1, "openAgent not found"

    new_drawer_code = '''// ---------- Safe Agent Detail Drawer ----------
function renderDrawerAgent(a, statusType) {
  const cats = (insightsData && insightsData.categories) || (ovCache && ovCache.category_names) || {};
  let statusBadge = "";
  if (statusType === "live") {
    statusBadge = '<span class="chip" style="margin-left:6px;color:var(--ok)">✓ Live Verified</span>';
  } else if (statusType === "cached") {
    statusBadge = '<span class="chip" style="margin-left:6px;color:var(--warn)">⚠ Cached Spec</span>';
  } else if (statusType === "syncing") {
    statusBadge = '<span class="chip" style="margin-left:6px;color:var(--reach)">● Syncing live...</span>';
  }

  const hasReport = (a.report_count > 0) || Boolean(a.test_report) || Boolean(a.test_reports && a.test_reports.length);

  $("drawerBadges").innerHTML = `
    <span class="kind-badge k-${esc(a.kind)}">${esc(a.kind)}</span>
    <span class="chip" style="margin-left:6px">source: ${esc(a.source || "registry")}</span>
    ${hasReport ? '<span class="report-badge-vivid" style="margin-left:6px"><span class="sparkle">✦</span> TEST REPORT</span>' : ''}
    ${statusBadge}
  `;

  $("drawerContent").innerHTML = `
    <h3 style="margin:8px 0 2px 0;font-size:18px">${esc(a.name)}</h3>
    <div style="font-size:12.5px;color:var(--accent);margin-bottom:10px;word-break:break-all">${link(a.url)}</div>
    <p style="font-size:13.5px;color:var(--text-muted);line-height:1.6;margin:0 0 14px 0">${esc(a.description || "No description provided.")}</p>

    <dl class="kv">
      <dt>Health Status</dt>
      <dd><span class="s-${esc(a.health_status)} font-semibold">● ${esc(a.health_status || "reachable")}</span> · consecutive failures: ${fmt(a.consecutive_failures || 0)}</dd>
      <dt>Last Checked</dt>
      <dd>${nyTime(a.last_check_at)} (${nyAgo(a.last_check_at)})</dd>
      <dt>Last Operational</dt>
      <dd>${nyTime(a.last_ok_at)}</dd>
      <dt>24h Availability</dt>
      <dd>${a.health_n_24h ? pct(a.health_ok_24h, a.health_n_24h) + ` (${fmt(a.health_ok_24h)}/${fmt(a.health_n_24h)})` : "–"}</dd>
      <dt>Category</dt>
      <dd>${esc(cats[a.category] ? `${cats[a.category]} (${a.category})` : (a.category || "General"))}</dd>
      <dt>Price Per Call</dt>
      <dd>${a.price_usdc === null ? "Free" : usd(a.price_usdc)} ${a.pay_to ? `<span style="font-family:monospace;font-size:11px">(${esc(a.pay_to)})</span>` : ""}</dd>
      <dt>Authentication</dt>
      <dd>${esc(a.auth_method || "None required")} · autonomy: ${esc(a.auth_autonomy || "autonomous")}</dd>
      <dt>Available Tools</dt>
      <dd>${fmt(a.cap_tool_count || 0)} registered tools</dd>
      <dt>Live Trial Result</dt>
      <dd>${a.trial_ok === 1 ? '<span class="s-healthy font-semibold">✓ Verified Working</span>' : a.trial_ok === 0 ? '<span class="s-down font-semibold">✕ Trial Execution Failed</span>' : '–'}</dd>
      <dt>Quality Grade</dt>
      <dd>${a.eval_grade ? `<b>Grade ${esc(a.eval_grade)}</b> (${Math.round(a.eval_score || 0)} pts) · Security: ${esc(a.eval_security || "clean")}` : "–"}</dd>
      <dt>First Cataloged</dt>
      <dd>${nyTime(a.first_seen)} (${nyAgo(a.first_seen)})</dd>
    </dl>

    <h4 style="margin:16px 0 6px 0;font-size:13.5px">Specifications & Metadata</h4>
    <pre>${esc(JSON.stringify(a.details || (statusType === "syncing" ? { note: "Detailed JSON specification loading in background..." } : {}), null, 2))}</pre>

    <h4 style="margin:20px 0 6px 0;font-size:13.5px;display:flex;align-items:center;justify-content:space-between">
      <span>Agent Verification &amp; Benchmark Report</span>
      ${hasReport ? '<span class="report-badge-vivid"><span class="sparkle">✦</span> TEST REPORT</span>' : ''}
    </h4>
    ${renderAgentTestReportHtml(a)}
  `;
}

async function openAgent(id) {
  const strId = String(id);
  const d = $("drawer");
  const backdrop = $("drawerBackdrop");
  d.classList.remove("hidden");
  backdrop.classList.remove("hidden");

  // 1. Instant Cache/Explore Map Hit (0ms latency, zero delay even if idle for hours)
  const cachedSpec = getSwrCache("agent:" + strId);
  const exploredItem = EXPLORE_AGENT_MAP.get(strId);
  const baseline = cachedSpec || exploredItem;

  if (baseline) {
    renderDrawerAgent(baseline, cachedSpec ? "live" : "syncing");
  } else {
    $("drawerBadges").innerHTML = "";
    $("drawerContent").innerHTML = binaryClockHtml("Retrieving verified agent specification...");
  }

  // 2. Fetch fresh agent specification with auto-retry and dead-socket recovery
  try {
    const res = await api("/api/agents/" + encodeURIComponent(strId), {
      silent: Boolean(baseline),
      loadingMsg: "Retrieving agent details...",
      retries: 2,
      timeoutMs: 8000
    });
    const freshAgent = res.agent || {};
    setSwrCache("agent:" + strId, freshAgent);
    EXPLORE_AGENT_MAP.set(strId, freshAgent);
    renderDrawerAgent(freshAgent, "live");
  } catch (err) {
    console.warn("Could not retrieve live specification for agent:", strId, err);
    if (baseline) {
      renderDrawerAgent(baseline, "cached");
    } else {
      $("drawerContent").innerHTML = `
        <div style="padding:24px 0;text-align:center">
          <p style="color:var(--bad);font-weight:700;margin-bottom:8px">Unable to retrieve agent specification</p>
          <p style="color:var(--text-muted);font-size:12.5px;margin-bottom:16px">${esc(err.message)}</p>
          <button class="btn primary" onclick="openAgent('${esc(strId)}')">Retry Connection</button>
        </div>
      `;
    }
  }
}

'''
    html = html[:s_idx] + new_drawer_code + html[e_idx:]
    print("✓ Upgraded openAgent() with renderDrawerAgent() and test report section")

    # 6. Page Lifecycle & Idle Reconnection Engine
    old_tail = '''sanitizePort8080();
</script>'''
    new_tail = '''sanitizePort8080();

// ---------- Page Lifecycle & Idle Reconnection Engine ----------
let lastUserActiveTimestamp = Date.now();

function handleIdleReconnection() {
  const now = Date.now();
  const idleMs = now - lastUserActiveTimestamp;
  lastUserActiveTimestamp = now;
  if (idleMs > 60000) {
    fetch("/api/overview", { method: "HEAD", cache: "no-store" }).catch(() => {});
    const activeTab = (location.hash || "").slice(1) || "overview";
    if (activeTab === "explore") {
      loadExplore(true);
    } else if (activeTab === "overview") {
      loadOverview();
    } else if (activeTab === "learn") {
      loadLearnUI();
    }
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    handleIdleReconnection();
  } else {
    lastUserActiveTimestamp = Date.now();
  }
});
window.addEventListener("focus", handleIdleReconnection);
window.addEventListener("online", handleIdleReconnection);
</script>'''

    if old_tail in html:
        html = html.replace(old_tail, new_tail)
        print("✓ Added Page Lifecycle & Idle Reconnection Engine")

    # Verify 0 Korean characters in HTML
    korean = re.findall(r"[\uac00-\ud7a3]", html)
    assert len(korean) == 0, f"Error: {len(korean)} Korean characters detected in extracted_html.txt: {set(korean)}"

    p.write_text(html, encoding="utf-8")
    print("✓ Successfully updated extracted_html.txt")


def update_rebuild_script():
    p = ROOT / "scripts" / "rebuild_front_with_graphs.py"
    code = p.read_text(encoding="utf-8")

    # Ensure import threading in base_part
    old_base_import = 'if "from .security import SecurityManager" not in base_part:\n        base_part = "from .security import SecurityManager\\n" + base_part'
    new_base_import = '''if "from .security import SecurityManager" not in base_part:
        base_part = "import threading\\nfrom .security import SecurityManager\\n" + base_part'''
    if old_base_import in code:
        code = code.replace(old_base_import, new_base_import)
        print("✓ Added import threading to base_part")

    # Ensure _bootstrap_snapshot_cache declaration in clean_helpers
    old_cache_decl_replace = '''    clean_helpers = clean_helpers.replace(old_card_cols, new_card_cols)'''
    new_cache_decl_replace = '''    clean_helpers = clean_helpers.replace(old_card_cols, new_card_cols)

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
    clean_helpers = clean_helpers.replace(old_explore_order, new_explore_order)'''

    if old_cache_decl_replace in code and "new_cache_decl" not in code:
        code = code.replace(old_cache_decl_replace, new_cache_decl_replace)
        print("✓ Added cache decl, newest featured list, and explore sort order to rebuild script")

    # Update snap_code to use thread-safe cached bootstrap_snapshot
    old_snap_code = '''        snap_code = """    def live_total(self) -> int:\\n        return sum(self.live_counts().values())\\n
    def bootstrap_snapshot(self) -> dict:
        return {
            "overview": get_snapshot_overview(self.store),
            "explore": get_front_explore(self.store, "", None, None, True, False, 45),
            "insights": get_front_insights(self.store),
        }
"""'''

    new_snap_code = '''        snap_code = """    def live_total(self) -> int:\\n        return sum(self.live_counts().values())\\n
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
"""'''

    if old_snap_code in code:
        code = code.replace(old_snap_code, new_snap_code)
        print("✓ Updated bootstrap_snapshot in rebuild script with thread-safe caching")

    p.write_text(code, encoding="utf-8")
    print("✓ Successfully updated scripts/rebuild_front_with_graphs.py")

if __name__ == "__main__":
    update_extracted_html()
    update_rebuild_script()

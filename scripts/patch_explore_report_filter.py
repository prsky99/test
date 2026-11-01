"""Apply explore test report filter to extracted_html.txt and rebuild_front_with_graphs.py."""

import re
from pathlib import Path

ROOT = Path("/Users/kingstonelee/workspace/A2A_Discovery")

def patch_html():
    p = ROOT / "extracted_html.txt"
    html = p.read_text(encoding="utf-8")

    # 1. Add Test Report checkbox to Explore filter bar
    old_checkboxes = '''        <label style="display:inline-flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer"><input type="checkbox" id="xVerified" checked> Verified Working</label>
        <label style="display:inline-flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer"><input type="checkbox" id="xNoAuth"> Zero Account</label>'''

    new_checkboxes = '''        <label style="display:inline-flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer"><input type="checkbox" id="xVerified" checked> Verified Working</label>
        <label style="display:inline-flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer"><input type="checkbox" id="xNoAuth"> Zero Account</label>
        <label style="display:inline-flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer;color:var(--text)" title="Only display agents with verified test & benchmark reports"><input type="checkbox" id="xHasReport"> <span style="display:inline-flex;align-items:center;gap:4px"><span>Test Report</span><span class="report-badge-vivid" style="font-size:8.5px;padding:1px 5px"><span class="sparkle">✦</span></span></span></label>'''

    assert old_checkboxes in html, "old_checkboxes not found in HTML"
    html = html.replace(old_checkboxes, new_checkboxes, 1)
    print("✓ Added Test Report filter checkbox to HTML filter bar")

    # 2. Add xHasReport to onchange listener array
    old_listeners = '["xKind", "xCategory", "xVerified", "xNoAuth"].forEach((id) => {\n  $(id).onchange = () => loadExplore(false);\n});'
    new_listeners = '["xKind", "xCategory", "xVerified", "xNoAuth", "xHasReport"].forEach((id) => {\n  const el = $(id);\n  if (el) el.onchange = () => loadExplore(false);\n});'
    assert old_listeners in html, "old_listeners not found in HTML"
    html = html.replace(old_listeners, new_listeners, 1)
    print("✓ Added xHasReport to filter onchange listeners")

    # 3. Update renderExplore with isReportFilter subtitle and empty state
    old_render_explore = '''function renderExplore(items, q = "") {
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

    new_render_explore = '''function renderExplore(items, q = "") {
  if (Array.isArray(items)) {
    items.forEach((item) => {
      if (item && item.id != null) EXPLORE_AGENT_MAP.set(String(item.id), item);
    });
  }
  const isReportFilter = Boolean($("xHasReport") && $("xHasReport").checked);
  const subLabel = isReportFilter
    ? `${fmt(items.length)} benchmark reports verified · Sorted by newest first`
    : `${fmt(items.length)} verified live · Sorted by newest first · Continuously updated`;

  $("xTitle").innerHTML = q
    ? `"${esc(q)}" Search Results <span class="sub">${fmt(items.length)} matches · Ranked by relevance & quality score</span>`
    : `Latest Discovered Agents <span class="sub">${subLabel}</span>`;

  $("xResults").innerHTML = items.length
    ? items.map((r) => agentCardHtml(r)).join("")
    : `<p style="color:var(--text-dim);grid-column:1/-1;padding:24px;text-align:center">${isReportFilter ? "No agents with verified benchmark reports match your current query and filters." : "No agents match your current query and filters. Try adjusting keywords or clearing category constraints."}</p>`;
}'''

    assert old_render_explore in html, "old_render_explore not found in HTML"
    html = html.replace(old_render_explore, new_render_explore, 1)
    print("✓ Updated renderExplore with dynamic report filter subtitle")

    # 4. Update loadExplore to read xHasReport and pass has_report=true
    old_load_explore = '''async function loadExplore(force = false) {
  populateCategorySelects();
  updateActiveExploreChip();
  const q = $("xQ").value.trim();
  const kind = $("xKind").value;
  const category = $("xCategory").value;
  const verified = $("xVerified").checked ? "1" : "0";
  const noAuth = $("xNoAuth").checked ? "1" : "0";
  const currentKey = `${q}|${kind}|${category}|${verified}|${noAuth}`;

  if (!force && lastExploreKey === currentKey) return;
  lastExploreKey = currentKey;

  // 1. Instant Cache Render (0ms latency)
  const cacheKey = "explore:" + currentKey;
  const cached = getSwrCache(cacheKey);
  if (cached && cached.items) {
    renderExplore(cached.items, q);
  } else {
    $("xResults").innerHTML = exploreSkeletonHtml();
  }

  // 2. Silent Background Revalidation
  if (exploreLoading) return;
  exploreLoading = true;

  try {
    const p = new URLSearchParams({ q, limit: "45" });
    if (kind) p.set("kind", kind);
    if (category) p.set("category", category);
    if (verified === "1") p.set("verified", "true");
    if (noAuth === "1") p.set("no_auth", "true");

    const data = await api("/api/explore?" + p, { silent: true });
    setSwrCache(cacheKey, data);
    renderExplore(data.items || [], q);
  } catch (err) {
    if (!cached) {
      $("xResults").innerHTML = `<p style="color:var(--bad)">Search failed: ${esc(err.message)}</p>`;
    }
  } finally {
    exploreLoading = false;
  }
}'''

    new_load_explore = '''async function loadExplore(force = false) {
  populateCategorySelects();
  updateActiveExploreChip();
  const q = $("xQ").value.trim();
  const kind = $("xKind").value;
  const category = $("xCategory").value;
  const verified = $("xVerified").checked ? "1" : "0";
  const noAuth = $("xNoAuth").checked ? "1" : "0";
  const hasReport = $("xHasReport") && $("xHasReport").checked ? "1" : "0";
  const currentKey = `${q}|${kind}|${category}|${verified}|${noAuth}${hasReport === "1" ? "|1" : ""}`;

  if (!force && lastExploreKey === currentKey) return;
  lastExploreKey = currentKey;

  // 1. Instant Cache Render (0ms latency)
  const cacheKey = "explore:" + currentKey;
  const cached = getSwrCache(cacheKey);
  if (cached && cached.items) {
    renderExplore(cached.items, q);
  } else {
    $("xResults").innerHTML = exploreSkeletonHtml();
  }

  // 2. Silent Background Revalidation
  if (exploreLoading) return;
  exploreLoading = true;

  try {
    const p = new URLSearchParams({ q, limit: "45" });
    if (kind) p.set("kind", kind);
    if (category) p.set("category", category);
    if (verified === "1") p.set("verified", "true");
    if (noAuth === "1") p.set("no_auth", "true");
    if (hasReport === "1") p.set("has_report", "true");

    const data = await api("/api/explore?" + p, { silent: true });
    setSwrCache(cacheKey, data);
    renderExplore(data.items || [], q);
  } catch (err) {
    if (!cached) {
      $("xResults").innerHTML = `<p style="color:var(--bad)">Search failed: ${esc(err.message)}</p>`;
    }
  } finally {
    exploreLoading = false;
  }
}'''

    assert old_load_explore in html, "old_load_explore not found in HTML"
    html = html.replace(old_load_explore, new_load_explore, 1)
    print("✓ Updated loadExplore to query has_report=true")

    # Verify zero Korean
    hangul = re.findall(r"[\uac00-\ud7a3]", html)
    assert len(hangul) == 0, f"Found {len(hangul)} Korean characters in extracted_html.txt"

    p.write_text(html, encoding="utf-8")
    print("✓ Successfully saved extracted_html.txt")


def patch_rebuild_script():
    p = ROOT / "scripts" / "rebuild_front_with_graphs.py"
    code = p.read_text(encoding="utf-8")

    # In clean_helpers: update get_front_explore signature, cache key, and conds
    old_explore_block = '''    old_explore_order = "ORDER BY (r.trial_ok IS 1) DESC, COALESCE(r.eval_score, 0) DESC, COALESCE(r.payers_30d, 0) DESC LIMIT ?"
    new_explore_order = "ORDER BY COALESCE(r.first_seen, 0) DESC, r.id DESC LIMIT ?"
    clean_helpers = clean_helpers.replace(old_explore_order, new_explore_order)'''

    new_explore_block = '''    old_explore_order = "ORDER BY (r.trial_ok IS 1) DESC, COALESCE(r.eval_score, 0) DESC, COALESCE(r.payers_30d, 0) DESC LIMIT ?"
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

    old_no_auth_cond = 'if no_auth:\\n        conds.append("(COALESCE(r.auth_observed, r.auth_declared, 0)=0 OR r.kind=\\\'x402\\\')")'
    new_no_auth_cond = """if no_auth:
        conds.append("(COALESCE(r.auth_observed, r.auth_declared, 0)=0 OR r.kind='x402')")
    if has_report:
        conds.append("EXISTS (SELECT 1 FROM agent_test_reports tr WHERE tr.resource_id = r.id)")"""
    clean_helpers = clean_helpers.replace(old_no_auth_cond, new_no_auth_cond)'''

    assert old_explore_block in code, "old_explore_block not found in rebuild script"
    code = code.replace(old_explore_block, new_explore_block, 1)
    print("✓ Added has_report support to get_front_explore in rebuild script")

    # In app_code: update api_explore signature and call
    old_api_explore_replace = '''    old_api_explore = """        ip = request.client.host if request.client else "unknown"
        if not explore_limit.allow(ip):
            raise HTTPException(429, "Search limit reached. Please slow down.")
        return get_front_explore(front.store, q, kind, category, verified, no_auth, limit)"""
    new_api_explore = """        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
        if not front.security.allow_explore(ip, base_limit=120):
            front.security.record_violation(ip, "rate_limit_429", request.url.path, request.method, request.headers.get("user-agent"), "Explore limit exceeded")
            raise HTTPException(429, "Search limit reached. Please slow down.", headers={"Retry-After": "60"})
        return get_front_explore(front.store, q, kind, category, verified, no_auth, limit)"""
    app_code = app_code.replace(old_api_explore, new_api_explore)'''

    new_api_explore_replace = '''    old_api_explore = """    @router.get("/api/explore")
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
    app_code = app_code.replace(old_api_explore, new_api_explore)'''

    assert old_api_explore_replace in code, "old_api_explore_replace not found in rebuild script"
    code = code.replace(old_api_explore_replace, new_api_explore_replace, 1)
    print("✓ Added has_report param to api_explore in rebuild script")

    p.write_text(code, encoding="utf-8")
    print("✓ Successfully saved scripts/rebuild_front_with_graphs.py")


if __name__ == "__main__":
    patch_html()
    patch_rebuild_script()

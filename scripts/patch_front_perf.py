import re
import sys

def patch_front():
    with open('agent_market/concierge/front.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Add GZipMiddleware import if needed
    if 'from starlette.middleware.gzip import GZipMiddleware' not in content:
        target = 'from starlette.concurrency import run_in_threadpool'
        replacement = 'from starlette.concurrency import run_in_threadpool\nfrom starlette.middleware.gzip import GZipMiddleware'
        assert target in content, "run_in_threadpool import target not found"
        content = content.replace(target, replacement, 1)
        print("✓ Added GZipMiddleware import")

    # 2. Add GZipMiddleware to create_front_app
    old_app_init = '''def create_front_app(front: Front) -> FastAPI:
    """The agent-only app: agent endpoints only, without admin routes or human docs pages."""
    app = FastAPI(title="Agent Concierge — for AI agents only", description=NOTICE, version="1.0.0", docs_url=None, redoc_url=None)
    app.state.front = front'''

    new_app_init = '''def create_front_app(front: Front) -> FastAPI:
    """The agent-only app: agent endpoints only, without admin routes or human docs pages."""
    app = FastAPI(title="Agent Concierge — for AI agents only", description=NOTICE, version="1.0.0", docs_url=None, redoc_url=None)
    app.state.front = front
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    # Pre-warm snapshot cache in background thread on app creation
    threading.Thread(target=front.bootstrap_snapshot, daemon=True, name="front-create-prewarm").start()'''

    assert old_app_init in content, "old_app_init not found"
    content = content.replace(old_app_init, new_app_init, 1)
    print("✓ Added GZipMiddleware and pre-warm to create_front_app")

    # 3. Add _snapshot_overview_cache
    old_cache_decl = '''# ---------------- Frontend Helpers (1h Snapshot, Insights, Search & Registration) ----------------
_front_insights_cache = {"at": 0.0, "data": None}
_front_explore_cache: dict[str, tuple[float, dict]] = {}
_bootstrap_snapshot_cache = {
    "at": 0.0,
    "data": None,
    "lock": threading.Lock(),
    "revalidating": False,
}'''

    new_cache_decl = '''# ---------------- Frontend Helpers (1h Snapshot, Insights, Search & Registration) ----------------
_front_insights_cache = {"at": 0.0, "data": None, "revalidating": False, "lock": threading.Lock()}
_front_explore_cache: dict[str, tuple[float, dict]] = {}
_snapshot_overview_cache = {"at": 0.0, "data": None, "revalidating": False, "lock": threading.Lock()}
_bootstrap_snapshot_cache = {
    "at": 0.0,
    "data": None,
    "lock": threading.Lock(),
    "revalidating": False,
}'''

    assert old_cache_decl in content, "old_cache_decl not found"
    content = content.replace(old_cache_decl, new_cache_decl, 1)
    print("✓ Updated cache declarations with overview SWR cache")

    # 4. Upgrade bootstrap_snapshot to RFC 5861 SWR
    old_bootstrap = '''    def bootstrap_snapshot(self) -> dict:
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
            return data'''

    new_bootstrap = '''    def bootstrap_snapshot(self) -> dict:
        now = time.time()
        cached = _bootstrap_snapshot_cache.get("data")
        cache_age = now - _bootstrap_snapshot_cache.get("at", 0.0)

        # 1. Fresh hit (< 60s): instant return
        if cached is not None and cache_age < 60.0:
            return cached

        # 2. Stale hit (RFC 5861 SWR): return stale instantly, revalidate asynchronously
        if cached is not None:
            if not _bootstrap_snapshot_cache.get("revalidating"):
                with _bootstrap_snapshot_cache["lock"]:
                    if not _bootstrap_snapshot_cache.get("revalidating"):
                        _bootstrap_snapshot_cache["revalidating"] = True
                        def _bg_swr_refresh():
                            try:
                                d = {
                                    "overview": get_snapshot_overview(self.store),
                                    "explore": get_front_explore(self.store, "", None, None, True, False, 45),
                                    "insights": get_front_insights(self.store),
                                }
                                with _bootstrap_snapshot_cache["lock"]:
                                    _bootstrap_snapshot_cache["data"] = d
                                    _bootstrap_snapshot_cache["at"] = time.time()
                            finally:
                                with _bootstrap_snapshot_cache["lock"]:
                                    _bootstrap_snapshot_cache["revalidating"] = False
                        threading.Thread(target=_bg_swr_refresh, daemon=True, name="front-swr-refresh").start()
            return cached

        # 3. Cold miss on startup: compute synchronously once
        with _bootstrap_snapshot_cache["lock"]:
            if _bootstrap_snapshot_cache.get("data") is not None:
                return _bootstrap_snapshot_cache["data"]
            data = {
                "overview": get_snapshot_overview(self.store),
                "explore": get_front_explore(self.store, "", None, None, True, False, 45),
                "insights": get_front_insights(self.store),
            }
            _bootstrap_snapshot_cache["data"] = data
            _bootstrap_snapshot_cache["at"] = now
            return data'''

    assert old_bootstrap in content, "old_bootstrap not found"
    content = content.replace(old_bootstrap, new_bootstrap, 1)
    print("✓ Upgraded bootstrap_snapshot to RFC 5861 SWR")

    # 5. Upgrade get_snapshot_overview with SWR
    old_overview_func = '''def get_snapshot_overview(store: Store) -> dict:
    """1-hour delayed snapshot data for public dashboard.
    Specifically excludes:
    - Customer Needs card (needs)
    - ERC-8004 Pending card (erc8004)
    - Overdue >1h Checks card (overdue_1h)
    - Recent 1h Checks card (checks_1h)
    Excludes internal system operational loops, worker thread states, and DB internals.
    All timestamps formatted in New York time.
    """
    now = time.time()
    cutoff = now - 3600'''

    new_overview_func = '''def get_snapshot_overview(store: Store) -> dict:
    """1-hour delayed snapshot data for public dashboard with RFC 5861 SWR caching.
    Specifically excludes:
    - Customer Needs card (needs)
    - ERC-8004 Pending card (erc8004)
    - Overdue >1h Checks card (overdue_1h)
    - Recent 1h Checks card (checks_1h)
    Excludes internal system operational loops, worker thread states, and DB internals.
    All timestamps formatted in New York time.
    """
    now = time.time()
    cached = _snapshot_overview_cache.get("data")
    cache_age = now - _snapshot_overview_cache.get("at", 0.0)

    # 1. Fresh hit (< 60s): instant return (0ms)
    if cached is not None and cache_age < 60.0:
        return cached

    # 2. Stale hit (RFC 5861 SWR): return stale instantly, revalidate in background
    if cached is not None:
        if not _snapshot_overview_cache.get("revalidating"):
            with _snapshot_overview_cache["lock"]:
                if not _snapshot_overview_cache.get("revalidating"):
                    _snapshot_overview_cache["revalidating"] = True
                    def _revalidate_overview():
                        try:
                            fresh = _compute_snapshot_overview(store)
                            with _snapshot_overview_cache["lock"]:
                                _snapshot_overview_cache["data"] = fresh
                                _snapshot_overview_cache["at"] = time.time()
                        finally:
                            with _snapshot_overview_cache["lock"]:
                                _snapshot_overview_cache["revalidating"] = False
                    threading.Thread(target=_revalidate_overview, daemon=True, name="overview-swr").start()
        return cached

    # 3. Cold miss: compute synchronously once
    with _snapshot_overview_cache["lock"]:
        if _snapshot_overview_cache.get("data") is not None:
            return _snapshot_overview_cache["data"]
        data = _compute_snapshot_overview(store)
        _snapshot_overview_cache["data"] = data
        _snapshot_overview_cache["at"] = now
        return data


def _compute_snapshot_overview(store: Store) -> dict:
    now = time.time()
    cutoff = now - 3600'''

    assert old_overview_func in content, "old_overview_func not found"
    content = content.replace(old_overview_func, new_overview_func, 1)
    print("✓ Added SWR caching to get_snapshot_overview")

    # 6. Cache-Control header in root
    old_root_ret = '''            page = HTML.replace("{notice}", esc(NOTICE)).replace("{ld}", ld.replace("<", "\\\\u003c")).replace("{greeting}", esc(body["greeting"])).replace("{base}", esc(front.base(request))).replace("{bootstrap_json}", bootstrap_str)
            return HTMLResponse(page)'''

    new_root_ret = '''            page = HTML.replace("{notice}", esc(NOTICE)).replace("{ld}", ld.replace("<", "\\\\u003c")).replace("{greeting}", esc(body["greeting"])).replace("{base}", esc(front.base(request))).replace("{bootstrap_json}", bootstrap_str)
            response = HTMLResponse(page)
            response.headers["Cache-Control"] = "public, max-age=15, stale-while-revalidate=120"
            return response'''

    assert old_root_ret in content, "old_root_ret not found"
    content = content.replace(old_root_ret, new_root_ret, 1)
    print("✓ Added Cache-Control header to root HTMLResponse")

    # 7. Invalidate caches on registration
    old_inval = '''    with _front_insights_cache["lock"] if "lock" in _front_insights_cache else threading.Lock():
        _front_insights_cache["at"] = 0.0
        _front_insights_cache["data"] = None'''

    # 8. Suppress redundant client-side re-fetches on startup hydration
    old_hydration = '''// Synchronously hydrate bootstrap data on initial page load (Zero-Loading startup)\\ntry {\\n  const bEl = $("appBootstrapData");\\n  if (bEl && bEl.textContent) {\\n    const bData = JSON.parse(bEl.textContent);\\n    if (bData.overview) {\\n      setSwrCache("overview", bData.overview);\\n      renderOverview(bData.overview);\\n    }\\n    if (bData.explore) {\\n      setSwrCache("explore:|||1|0", bData.explore);\\n      if (bData.explore.items && location.hash === "#explore") {\\n        renderExplore(bData.explore.items, "");\\n      }\\n    }\\n    if (bData.insights) {\\n      insightsData = bData.insights;\\n      setSwrCache("insights", bData.insights);\\n      if (location.hash === "#learn") {\\n        renderLearnUI();\\n      }\\n    }\\n  }\\n} catch (e) {}'''

    new_hydration = '''// Synchronously hydrate bootstrap data on initial page load (Zero-Loading startup)\\nlet overviewBootstrapped = false;\\ntry {\\n  const bEl = $("appBootstrapData");\\n  if (bEl && bEl.textContent) {\\n    const bData = JSON.parse(bEl.textContent);\\n    if (bData.overview) {\\n      overviewBootstrapped = true;\\n      setSwrCache("overview", bData.overview);\\n      renderOverview(bData.overview);\\n    }\\n    if (bData.explore) {\\n      lastExploreKey = "|||1|0";\\n      setSwrCache("explore:|||1|0", bData.explore);\\n      if (bData.explore.items && location.hash === "#explore") {\\n        renderExplore(bData.explore.items, "");\\n      }\\n    }\\n    if (bData.insights) {\\n      insightsData = bData.insights;\\n      setSwrCache("insights", bData.insights);\\n      if (location.hash === "#learn") {\\n        renderLearnUI();\\n      }\\n    }\\n  }\\n} catch (e) {}'''

    assert old_hydration in content, "old_hydration not found"
    content = content.replace(old_hydration, new_hydration, 1)
    print("✓ Updated client hydration to track overviewBootstrapped and lastExploreKey")

    # 9. In loadOverview(), skip redundant fetch if overviewBootstrapped
    old_load_ov = '''async function loadOverview(force = false) {\\n  const cached = getSwrCache("overview");\\n  if (cached) {\\n    renderOverview(cached);\\n  } else if (!ovCache) {\\n    $("ovKpis").innerHTML = binaryClockHtml("Loading real-time overview...");\\n  }\\n\\n  if (ovRevalidating) return;'''

    new_load_ov = '''async function loadOverview(force = false) {\\n  const cached = getSwrCache("overview");\\n  if (cached) {\\n    renderOverview(cached);\\n  } else if (!ovCache) {\\n    $("ovKpis").innerHTML = binaryClockHtml("Loading real-time overview...");\\n  }\\n\\n  if (overviewBootstrapped && !force) {\\n    overviewBootstrapped = false;\\n    return;\\n  }\\n\\n  if (ovRevalidating) return;'''

    assert old_load_ov in content, "old_load_ov not found"
    content = content.replace(old_load_ov, new_load_ov, 1)
    print("✓ Updated loadOverview to skip redundant initial startup network fetch")

    # 10. Check English purity
    hangul = re.findall(r'[\uac00-\ud7a3]', content)
    print(f"Hangul count in front.py: {len(hangul)}")
    assert len(hangul) == 0, f"Found {len(hangul)} Korean characters in front.py!"

    with open('agent_market/concierge/front.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully patched agent_market/concierge/front.py!")

def patch_server():
    with open('agent_market/gateway/server.py', 'r', encoding='utf-8') as f:
        content = f.read()

    target = 'servers.append(uvicorn.Server(uvicorn.Config(front_app, host=config.agent_front_host or host, port=front_port,'
    if 'front-startup-prewarm' not in content:
        replacement = 'threading.Thread(target=app.state.front.bootstrap_snapshot, daemon=True, name="front-startup-prewarm").start()\n        ' + target
        assert target in content, "target not found in server.py"
        content = content.replace(target, replacement, 1)
        with open('agent_market/gateway/server.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print("✓ Pre-warming added to server.py")

if __name__ == '__main__':
    patch_front()
    patch_server()

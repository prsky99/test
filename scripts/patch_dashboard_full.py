"""Update agent_market/gateway/dashboard.html to fix:
1. Agent Test template autocomplete with schema analysis & template dropdown.
2. Admin management, logout, mypage, and audit trail click events and functionality.
3. Unauthenticated session check & full-screen login enforcement.
"""

from pathlib import Path
import re

ROOT = Path("/Users/kingstonelee/workspace/A2A_Discovery")
DASHBOARD_HTML = ROOT / "agent_market" / "gateway" / "dashboard.html"

def main():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    # 1. Ensure CSS modal overlay has high z-index and blurred backdrop
    old_overlay_css = """.admin-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.55); backdrop-filter: blur(4px);
  z-index: 50; display: flex; justify-content: center; align-items: center; padding: 20px;
}"""
    new_overlay_css = """.admin-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.75); backdrop-filter: blur(10px);
  z-index: 99999; display: flex; justify-content: center; align-items: center; padding: 20px;
}"""
    if old_overlay_css in html:
        html = html.replace(old_overlay_css, new_overlay_css, 1)

    # 2. Add template select dropdown to the Agent Test arguments box in HTML
    old_args_box_head = """          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <label style="font-size:12px;font-weight:600;color:var(--muted)">인자(Arguments) JSON</label>
            <div style="display:flex;gap:6px">
              <button class="btn sm" id="testFillSampleBtn" type="button" title="도구의 inputSchema를 분석하여 샘플 인자를 자동으로 채웁니다.">⚡ 템플릿 자동 완성</button>
              <button class="btn sm" id="testClearArgsBtn" type="button">🧹 비우기</button>
            </div>
          </div>"""

    new_args_box_head = """          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:6px">
            <label style="font-size:12px;font-weight:600;color:var(--muted)">인자(Arguments) JSON</label>
            <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
              <select id="testTemplateSelect" style="font-size:11.5px;padding:3px 8px;border-radius:5px;background:var(--panel);color:var(--text);border:1px solid var(--line);cursor:pointer">
                <option value="">⚡ 페이로드 템플릿 선택...</option>
                <option value="schema">도구 스키마 분석 템플릿 (Schema Mock)</option>
                <option value="query">범용 질의 템플릿 (query/limit)</option>
                <option value="search">검색 템플릿 (search/filter)</option>
                <option value="weather">날씨/위치 템플릿 (location/unit)</option>
                <option value="file">파일/문서 템플릿 (path/content)</option>
                <option value="ping">핑/헬스체크 템플릿 (ping/echo)</option>
                <option value="empty">빈 객체 ({})</option>
              </select>
              <button class="btn sm primary" id="testFillSampleBtn" type="button" title="도구의 inputSchema를 분석하여 샘플 인자를 자동으로 완성합니다.">⚡ 템플릿 자동 완성</button>
              <button class="btn sm" id="testClearArgsBtn" type="button">🧹 비우기</button>
            </div>
          </div>"""

    if old_args_box_head in html:
        html = html.replace(old_args_box_head, new_args_box_head, 1)

    # 3. Update api() error handler to openLoginModal on 401
    old_api_401 = """    if (resp.status === 401 || resp.status === 403) {
      const body = await resp.json().catch(() => ({}));
      showAuth(body.detail || "인증이 필요합니다.");
      throw new Error("unauthorized");
    }"""

    new_api_401 = """    if (resp.status === 401 || resp.status === 403) {
      const body = await resp.json().catch(() => ({}));
      if (typeof openLoginModal === "function") {
        token = "";
        currentUser = null;
        try { sessionStorage.removeItem("adminToken"); } catch (e) {}
        updateUserUI(null, false);
        openLoginModal(body.detail || "관리자 인증이 필요하거나 세션이 만료되었습니다.");
      } else {
        showAuth(body.detail || "인증이 필요합니다.");
      }
      throw new Error("unauthorized");
    }"""

    if old_api_401 in html:
        html = html.replace(old_api_401, new_api_401, 1)

    # 4. Replace testbench selectTestTool & fillSampleArgs with Smart Schema & Template Autocomplete
    old_testbench_tools_section = """function selectTestTool(toolName) {
  if (!toolName || toolName === "__custom__") {
    if ($("testToolCustomInput")) $("testToolCustomInput").focus();
    return;
  }
  if ($("testToolCustomInput")) $("testToolCustomInput").value = toolName;
  if ($("testToolSelect") && Array.from($("testToolSelect").options).some(o => o.value === toolName)) {
    $("testToolSelect").value = toolName;
  }
  const tools = (testbenchState.selectedAgent && testbenchState.selectedAgent.tools) || [];
  const tool = tools.find((t) => t.name === toolName);
  testbenchState.selectedTool = tool || { name: toolName };

  if (tool && tool.description) {
    const reqText = tool.required && tool.required.length ? ` (필수: ${tool.required.join(", ")})` : "";
    $("testToolDesc").textContent = (tool.description || "설명 없음") + reqText;
    const sample = tool.sample || {};
    $("testArgsJson").value = JSON.stringify(sample, null, 2);
  } else {
    $("testToolDesc").textContent = `호출 대상 도구: ${esc(toolName)}`;
    if (!$("testArgsJson").value || $("testArgsJson").value.trim() === "{}") {
      $("testArgsJson").value = JSON.stringify({ query: "test" }, null, 2);
    }
  }
  $("testArgsError").style.display = "none";
}

function fillSampleArgs() {
  if (!testbenchState.selectedAgent) {
    toast("먼저 에이전트를 선택해주세요.");
    return;
  }
  if (testbenchState.selectedAgent.kind === "mcp") {
    const tool = testbenchState.selectedTool;
    if (tool && tool.sample) {
      $("testArgsJson").value = JSON.stringify(tool.sample, null, 2);
      toast("도구 스키마 기반 샘플 인자가 채워졌습니다.");
    } else {
      $("testArgsJson").value = "{}";
    }
  } else if (testbenchState.selectedAgent.kind === "a2a") {
    const sampleMsg = (testbenchState.selectedAgent.sample_args && testbenchState.selectedAgent.sample_args.message) || "Hello! Can you report your current capabilities?";
    $("testA2aMessage").value = sampleMsg;
    $("testArgsJson").value = JSON.stringify({ message: sampleMsg }, null, 2);
    toast("A2A 샘플 태스크 메시지가 채워졌습니다.");
  }
  $("testArgsError").style.display = "none";
}"""

    new_testbench_tools_section = """function generateSmartToolSample(tool, agent) {
  if (!tool) return { query: "test" };

  // 1. 사전 정의된 유효한 샘플이 있으면 우선 활용
  if (tool.sample && typeof tool.sample === "object" && Object.keys(tool.sample).length > 0) {
    return tool.sample;
  }

  // 2. 파라미터 / inputSchema 스키마 분석하여 필드별 스마트 모의 데이터 생성
  const sample = {};
  const params = tool.params || (tool.inputSchema && tool.inputSchema.properties) || {};
  const keys = Object.keys(params);

  if (keys.length > 0) {
    for (const key of keys) {
      const p = params[key] || {};
      const type = (p.type || "string").toLowerCase();
      const desc = p.description || "";
      const lowerKey = key.toLowerCase();

      if (p.default !== undefined) {
        sample[key] = p.default;
      } else if (p.enum && Array.isArray(p.enum) && p.enum.length > 0) {
        sample[key] = p.enum[0];
      } else if (type === "integer" || type === "number") {
        if (/limit|count|max|top|num/i.test(lowerKey)) sample[key] = 5;
        else if (/offset|start|page/i.test(lowerKey)) sample[key] = 0;
        else sample[key] = 1;
      } else if (type === "boolean") {
        sample[key] = true;
      } else if (type === "array") {
        if (p.items && p.items.enum && p.items.enum.length) sample[key] = [p.items.enum[0]];
        else if (p.items && p.items.type === "string") sample[key] = ["sample_item"];
        else sample[key] = [];
      } else if (type === "object") {
        sample[key] = {};
      } else {
        // string 필드 의미별 정밀 모의 데이터
        if (/city|location|place|address|region/i.test(lowerKey)) {
          sample[key] = "Seoul";
        } else if (/query|keyword|search|prompt|text|input|term|q\\b/i.test(lowerKey)) {
          sample[key] = "인공지능 에이전트 동향";
        } else if (/url|uri|endpoint|link|domain/i.test(lowerKey)) {
          sample[key] = "https://api.example.com/data";
        } else if (/date|time|timestamp/i.test(lowerKey)) {
          sample[key] = "2026-10-15";
        } else if (/id|code|key|uuid/i.test(lowerKey)) {
          sample[key] = "AGENT-101";
        } else if (/path|file|filepath|dir/i.test(lowerKey)) {
          sample[key] = "data/sample.json";
        } else if (/format|type|mode/i.test(lowerKey)) {
          sample[key] = "json";
        } else if (/email|user/i.test(lowerKey)) {
          sample[key] = "sadmin@example.com";
        } else {
          sample[key] = desc ? desc.slice(0, 30) : `sample_${key}`;
        }
      }
    }
    return sample;
  }

  // 3. 스키마가 비어있는 경우 도구명 분석 템플릿 도출
  const toolName = (tool.name || "").toLowerCase();
  if (/search|find|grep|lookup/i.test(toolName)) {
    return { query: "Agent discovery benchmark", limit: 5 };
  } else if (/weather|forecast|temp|climate/i.test(toolName)) {
    return { location: "Seoul", unit: "metric" };
  } else if (/calc|math|eval|compute/i.test(toolName)) {
    return { expression: "2 * 3.14159" };
  } else if (/file|read|read_file|fetch|doc/i.test(toolName)) {
    return { path: "README.md", format: "text" };
  } else if (/write|save/i.test(toolName)) {
    return { path: "test.txt", content: "Agent test benchmark" };
  } else if (/ping|echo|check|status/i.test(toolName)) {
    return { message: "ping", timestamp: Date.now() };
  } else if (/query|sql|database|db/i.test(toolName)) {
    return { query: "SELECT * FROM agents LIMIT 5;" };
  } else {
    return { query: "test", mode: "standard" };
  }
}

function selectTestTool(toolName) {
  if (!toolName || toolName === "__custom__") {
    if ($("testToolCustomInput")) $("testToolCustomInput").focus();
    return;
  }
  if ($("testToolCustomInput")) $("testToolCustomInput").value = toolName;
  if ($("testToolSelect") && Array.from($("testToolSelect").options).some(o => o.value === toolName)) {
    $("testToolSelect").value = toolName;
  }
  const tools = (testbenchState.selectedAgent && testbenchState.selectedAgent.tools) || [];
  const tool = tools.find((t) => t.name === toolName);
  testbenchState.selectedTool = tool || { name: toolName };

  if (tool && tool.description) {
    const reqText = tool.required && tool.required.length ? ` (필수: ${tool.required.join(", ")})` : "";
    $("testToolDesc").textContent = (tool.description || "설명 없음") + reqText;
  } else {
    $("testToolDesc").textContent = `호출 대상 도구: ${esc(toolName)}`;
  }

  // 도구 선택 시 스마트 템플릿 즉시 자동 입력
  const sample = generateSmartToolSample(testbenchState.selectedTool, testbenchState.selectedAgent);
  $("testArgsJson").value = JSON.stringify(sample, null, 2);
  $("testArgsError").style.display = "none";
}

function fillSampleArgs() {
  if (!testbenchState.selectedAgent) {
    toast("먼저 에이전트를 선택해주세요.");
    return;
  }
  const ag = testbenchState.selectedAgent;
  if (ag.kind === "mcp") {
    const customName = ($("testToolCustomInput") && $("testToolCustomInput").value.trim()) || "query";
    const tool = testbenchState.selectedTool || { name: customName };
    const sample = generateSmartToolSample(tool, ag);
    $("testArgsJson").value = JSON.stringify(sample, null, 2);
    toast(`'${tool.name}' 도구 스키마 분석 템플릿이 자동으로 완성되었습니다.`);
  } else if (ag.kind === "a2a") {
    const sampleMsg = (ag.sample_args && ag.sample_args.message) || "Hello! Can you report your current capabilities and available services?";
    $("testA2aMessage").value = sampleMsg;
    $("testArgsJson").value = JSON.stringify({ message: sampleMsg }, null, 2);
    toast("A2A 태스크 메시지 템플릿이 채워졌습니다.");
  } else if (ag.kind === "x402") {
    $("testArgsJson").value = JSON.stringify({ url: ag.url, note: "HTTP 402 payment challenge verification probe" }, null, 2);
    toast("x402 프로브 템플릿이 채워졌습니다.");
  }
  $("testArgsError").style.display = "none";
}"""

    if old_testbench_tools_section in html:
        html = html.replace(old_testbench_tools_section, new_testbench_tools_section, 1)

    # 5. Bind testTemplateSelect event
    old_test_fill_btn = """$("testFillSampleBtn").onclick = () => fillSampleArgs();"""
    new_test_fill_btn = """if ($("testTemplateSelect")) {
  $("testTemplateSelect").onchange = (e) => {
    const val = e.target.value;
    if (!val) return;
    if (val === "schema") {
      fillSampleArgs();
    } else if (val === "query") {
      $("testArgsJson").value = JSON.stringify({ query: "Agent discovery benchmark", limit: 5 }, null, 2);
      toast("범용 질의 템플릿이 적용되었습니다.");
    } else if (val === "search") {
      $("testArgsJson").value = JSON.stringify({ q: "인공지능", filter: { category: "data_analysis" }, limit: 10 }, null, 2);
      toast("검색 및 필터 템플릿이 적용되었습니다.");
    } else if (val === "weather") {
      $("testArgsJson").value = JSON.stringify({ location: "Seoul", unit: "metric" }, null, 2);
      toast("날씨/위치 템플릿이 적용되었습니다.");
    } else if (val === "file") {
      $("testArgsJson").value = JSON.stringify({ path: "data/sample.json", content: "{\\"sample\\": true}" }, null, 2);
      toast("파일/문서 템플릿이 적용되었습니다.");
    } else if (val === "ping") {
      $("testArgsJson").value = JSON.stringify({ message: "ping", timestamp: Date.now() }, null, 2);
      toast("핑/헬스체크 템플릿이 적용되었습니다.");
    } else if (val === "empty") {
      $("testArgsJson").value = "{}";
      toast("빈 객체 템플릿이 적용되었습니다.");
    }
    $("testArgsError").style.display = "none";
  };
}
$("testFillSampleBtn").onclick = () => fillSampleArgs();"""

    if old_test_fill_btn in html:
        html = html.replace(old_test_fill_btn, new_test_fill_btn, 1)

    # 6. Add complete JavaScript for Admin Auth, Modals, Users, Audit, and Login Protection
    admin_js = """
// ==================== 관리자 인증, 세션, 마이페이지, 계정 관리 & 감사 로그 ====================
let currentUser = null;
let auditLogsState = { page: 1, limit: 30, total: 0 };
let currentAdminUsers = [];
let currentAuditLogs = [];

async function checkAdminAuth() {
  if (!token) {
    currentUser = null;
    updateUserUI(null, false);
    openLoginModal("관리자 인증이 필요합니다. 로그인해주세요.");
    return false;
  }
  try {
    const res = await api("/admin/api/auth/me", { silent: true });
    if (res && res.ok && res.user) {
      currentUser = res.user;
      currentUser.is_sadmin = Boolean(res.is_sadmin);
      updateUserUI(currentUser, currentUser.is_sadmin);
      closeLoginModal();
      return true;
    } else {
      throw new Error("unauthorized");
    }
  } catch (e) {
    currentUser = null;
    token = "";
    try { sessionStorage.removeItem("adminToken"); } catch (err) {}
    updateUserUI(null, false);
    openLoginModal("세션이 만료되었거나 로그인이 필요합니다.");
    return false;
  }
}

function updateUserUI(user, isSadmin) {
  const badge = $("adminUserBadge");
  const usernameEl = $("adminUsername");
  const roleEl = $("adminRoleBadge");
  const myPageBtn = $("myPageBtn");
  const logoutBtn = $("logoutBtn");
  const headerLoginBtn = $("headerLoginBtn");
  const tabAudit = $("tabAudit");
  const tabUsers = $("tabUsers");

  if (user) {
    if (badge) badge.style.display = "inline-flex";
    if (usernameEl) usernameEl.textContent = user.username;
    if (roleEl) {
      roleEl.textContent = isSadmin ? "최고관리자" : (user.role || "관리자");
      roleEl.className = isSadmin ? "chip ok-badge" : "chip";
    }
    if (myPageBtn) myPageBtn.style.display = "inline-block";
    if (logoutBtn) logoutBtn.style.display = "inline-block";
    if (headerLoginBtn) headerLoginBtn.style.display = "none";

    // sadmin 전용 메뉴 표시 제어
    if (tabAudit) tabAudit.style.display = isSadmin ? "inline-block" : "none";
    if (tabUsers) tabUsers.style.display = isSadmin ? "inline-block" : "none";
  } else {
    if (badge) badge.style.display = "none";
    if (myPageBtn) myPageBtn.style.display = "none";
    if (logoutBtn) logoutBtn.style.display = "none";
    if (headerLoginBtn) headerLoginBtn.style.display = "inline-block";
    if (tabAudit) tabAudit.style.display = "none";
    if (tabUsers) tabUsers.style.display = "none";
  }
}

function openLoginModal(msg = "") {
  const modal = $("adminLoginModal");
  if (modal) {
    modal.classList.remove("hidden");
    modal.style.display = "flex";
    modal.style.zIndex = "99999";
  }
  const errEl = $("adminLoginError");
  if (errEl) {
    if (msg) {
      errEl.textContent = msg;
      errEl.classList.remove("hidden");
    } else {
      errEl.classList.add("hidden");
    }
  }
  // 비로그인 상태에서는 어드민 메인 화면을 가려서 보안 유지
  const mainEl = document.querySelector("main");
  if (mainEl) mainEl.style.display = "none";
  const tabsNav = $("tabs");
  if (tabsNav) tabsNav.style.opacity = "0.2";
  clearInterval(state.timer);
}

function closeLoginModal() {
  const modal = $("adminLoginModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.style.display = "none";
  }
  const mainEl = document.querySelector("main");
  if (mainEl) mainEl.style.display = "";
  const tabsNav = $("tabs");
  if (tabsNav) tabsNav.style.opacity = "1";
  const errEl = $("adminLoginError");
  if (errEl) errEl.classList.add("hidden");
}

async function submitAdminLogin() {
  const u = $("adminLoginUsername").value.trim();
  const p = $("adminLoginPassword").value;
  const errEl = $("adminLoginError");
  errEl.classList.add("hidden");

  if (!u || !p) {
    errEl.textContent = "아이디와 비밀번호를 모두 입력하세요.";
    errEl.classList.remove("hidden");
    return;
  }

  const btn = $("adminLoginSubmitBtn");
  btn.disabled = true;
  btn.textContent = "로그인 중…";

  try {
    const res = await api("/admin/api/auth/login", {
      method: "POST",
      json: { username: u, password: p },
      loadingMsg: "관리자 인증 확인 중…"
    });

    if (res && res.ok && res.token) {
      token = res.token;
      try { sessionStorage.setItem("adminToken", token); } catch (e) {}
      currentUser = res.user;
      currentUser.is_sadmin = Boolean(res.user.is_sadmin);
      updateUserUI(currentUser, currentUser.is_sadmin);
      closeLoginModal();
      toast(`환영합니다, ${currentUser.name || currentUser.username}님!`);
      schedule();
      switchTab(hashTab());
    } else {
      throw new Error((res && res.message) || "로그인에 실패했습니다.");
    }
  } catch (err) {
    errEl.textContent = "로그인 실패: " + err.message;
    errEl.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = "로그인";
  }
}

async function logoutAdmin() {
  if (!confirm("관리자 콘솔에서 로그아웃 하시겠습니까?")) return;
  try {
    await api("/admin/api/auth/logout", { method: "POST", silent: true });
  } catch (e) {}
  token = "";
  currentUser = null;
  try { sessionStorage.removeItem("adminToken"); } catch (e) {}
  updateUserUI(null, false);
  openLoginModal("정상적으로 로그아웃되었습니다.");
  toast("로그아웃되었습니다.");
}

// 마이페이지 (계정 정보 조회 및 비밀번호 변경)
function openMyPage() {
  if (!currentUser) {
    openLoginModal("로그인이 필요합니다.");
    return;
  }
  $("myPageUsername").textContent = currentUser.username;
  $("myPageName").textContent = currentUser.name || "관리자";
  $("myPageRole").textContent = currentUser.role || (currentUser.is_sadmin ? "superadmin" : "admin");
  $("myPageCurrentPwd").value = "";
  $("myPageNewPwd").value = "";
  $("myPageConfirmPwd").value = "";
  $("myPagePwdError").classList.add("hidden");
  $("myPagePwdSuccess").style.display = "none";
  $("adminMyPageModal").classList.remove("hidden");
  $("adminMyPageModal").style.display = "flex";
}

function closeMyPage() {
  $("adminMyPageModal").classList.add("hidden");
  $("adminMyPageModal").style.display = "none";
}

async function submitPasswordChange() {
  const currPwd = $("myPageCurrentPwd").value;
  const newPwd = $("myPageNewPwd").value;
  const confirmPwd = $("myPageConfirmPwd").value;
  const errEl = $("myPagePwdError");
  const succEl = $("myPagePwdSuccess");

  errEl.classList.add("hidden");
  succEl.style.display = "none";

  if (!currPwd) {
    errEl.textContent = "현재 비밀번호를 입력해주세요.";
    errEl.classList.remove("hidden");
    return;
  }
  if (!newPwd || newPwd.length < 4) {
    errEl.textContent = "새 비밀번호는 최소 4자 이상이어야 합니다.";
    errEl.classList.remove("hidden");
    return;
  }
  if (newPwd !== confirmPwd) {
    errEl.textContent = "새 비밀번호 확인이 일치하지 않습니다.";
    errEl.classList.remove("hidden");
    return;
  }

  const btn = $("submitChangePwdBtn");
  btn.disabled = true;
  btn.textContent = "비밀번호 변경 중…";

  try {
    const res = await api("/admin/api/auth/change-password", {
      method: "POST",
      json: { current_password: currPwd, new_password: newPwd },
      loadingMsg: "비밀번호 변경 요청 중…"
    });
    if (res && res.ok) {
      succEl.textContent = "비밀번호가 성공적으로 변경되었습니다. 다음 로그인부터 새 비밀번호가 적용됩니다.";
      succEl.style.display = "block";
      $("myPageCurrentPwd").value = "";
      $("myPageNewPwd").value = "";
      $("myPageConfirmPwd").value = "";
      toast("비밀번호 재등록 완료!");
    }
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = "비밀번호 재등록 완료";
  }
}

// 관리자 계정 목록 및 CRUD (sadmin 전용)
async function loadAdminUsers() {
  const tbody = $("adminUsersTbody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">관리자 계정 목록을 조회하는 중…</td></tr>`;

  try {
    const data = await api("/admin/api/users", { loadingMsg: "관리자 계정 목록 조회 중…" });
    currentAdminUsers = (data && data.users) || [];
    $("adminUsersCount").textContent = `(${currentAdminUsers.length}명)`;

    if (currentAdminUsers.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">등록된 관리자가 없습니다.</td></tr>`;
      return;
    }

    tbody.innerHTML = currentAdminUsers.map((u) => {
      const isSadminUser = (u.username === "sadmin");
      const statusBadge = u.active
        ? `<span class="chip ok-badge">활성 (Active)</span>`
        : `<span class="chip bad">비활성 (Disabled)</span>`;
      const createdStr = u.created_at ? new Date(u.created_at * 1000).toLocaleString("ko-KR") : "-";
      const loginStr = u.last_login ? new Date(u.last_login * 1000).toLocaleString("ko-KR") : "없음";

      return `
        <tr>
          <td class="muted">${u.id}</td>
          <td><strong>${esc(u.username)}</strong> ${isSadminUser ? '<span class="chip" style="font-size:10px">기본 최고관리자</span>' : ''}</td>
          <td>${esc(u.name || "-")}</td>
          <td><span class="chip" style="font-weight:600">${esc(u.role)}</span></td>
          <td>${statusBadge}</td>
          <td class="muted nw" style="font-size:12px">${createdStr}</td>
          <td class="muted nw" style="font-size:12px">${loginStr}</td>
          <td style="text-align:right" class="nw">
            <button class="btn sm" onclick="resetUserPasswordPrompt(${u.id}, '${esc(u.username)}')">비번변경</button>
            ${isSadminUser ? '' : `
              <button class="btn sm" onclick="toggleUserActive(${u.id}, '${esc(u.username)}', ${u.active ? 1 : 0})">${u.active ? '비활성화' : '활성화'}</button>
              <button class="btn sm" style="color:var(--bad)" onclick="deleteUserAccount(${u.id}, '${esc(u.username)}')">삭제</button>
            `}
          </td>
        </tr>
      `;
    }).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="banner bad" style="text-align:center;padding:18px">관리자 목록 조회 실패: ${esc(e.message)}</td></tr>`;
  }
}

function openCreateUserModal() {
  $("newAdminUsername").value = "";
  $("newAdminName").value = "";
  $("newAdminPassword").value = "";
  $("newAdminRole").value = "admin";
  $("createUserError").classList.add("hidden");
  $("adminCreateUserModal").classList.remove("hidden");
  $("adminCreateUserModal").style.display = "flex";
}

function closeCreateUserModal() {
  $("adminCreateUserModal").classList.add("hidden");
  $("adminCreateUserModal").style.display = "none";
}

async function submitCreateUser() {
  const username = $("newAdminUsername").value.trim();
  const name = $("newAdminName").value.trim();
  const password = $("newAdminPassword").value;
  const role = $("newAdminRole").value;
  const errEl = $("createUserError");
  errEl.classList.add("hidden");

  if (!username) {
    errEl.textContent = "관리자 아이디를 입력하세요.";
    errEl.classList.remove("hidden");
    return;
  }
  if (!password || password.length < 4) {
    errEl.textContent = "비밀번호는 최소 4자 이상이어야 합니다.";
    errEl.classList.remove("hidden");
    return;
  }

  const btn = $("submitCreateUserBtn");
  btn.disabled = true;
  btn.textContent = "생성 중…";

  try {
    await api("/admin/api/users", {
      method: "POST",
      json: { username, name, password, role },
      loadingMsg: "신규 관리자 계정 생성 중…"
    });
    toast(`관리자 계정 '${username}'이(가) 등록되었습니다.`);
    closeCreateUserModal();
    loadAdminUsers();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = "계정 생성";
  }
}

async function resetUserPasswordPrompt(uid, uname) {
  const newPwd = prompt(`[${uname}] 관리자의 새 비밀번호를 입력하세요 (최소 4자):`);
  if (!newPwd) return;
  if (newPwd.length < 4) {
    alert("비밀번호는 최소 4자 이상이어야 합니다.");
    return;
  }
  try {
    await api(`/admin/api/users/${uid}`, {
      method: "PUT",
      json: { new_password: newPwd },
      loadingMsg: "비밀번호 재설정 중…"
    });
    toast(`[${uname}] 관리자의 비밀번호가 재설정되었습니다.`);
    loadAdminUsers();
  } catch (e) {
    alert("비밀번호 변경 실패: " + e.message);
  }
}

async function toggleUserActive(uid, uname, currActive) {
  const nextActive = currActive ? 0 : 1;
  const actionText = nextActive ? "활성화" : "비활성화";
  if (!confirm(`'${uname}' 관리자 계정을 ${actionText}하시겠습니까?`)) return;

  try {
    await api(`/admin/api/users/${uid}`, {
      method: "PUT",
      json: { active: nextActive },
      loadingMsg: `계정 ${actionText} 중…`
    });
    toast(`'${uname}' 계정이 ${actionText}되었습니다.`);
    loadAdminUsers();
  } catch (e) {
    alert(`상태 변경 실패: ` + e.message);
  }
}

async function deleteUserAccount(uid, uname) {
  if (!confirm(`정말로 관리자 계정 '${uname}'을(를) 영구 삭제하시겠습니까?\\n삭제된 계정은 복구할 수 없습니다.`)) return;

  try {
    await api(`/admin/api/users/${uid}`, {
      method: "DELETE",
      loadingMsg: "관리자 계정 삭제 중…"
    });
    toast(`'${uname}' 계정이 삭제되었습니다.`);
    loadAdminUsers();
  } catch (e) {
    alert("계정 삭제 실패: " + e.message);
  }
}

// 관리자 감사 로그 (Audit Trail - sadmin 전용)
async function loadAuditLogs(page = 1) {
  const tbody = $("auditLogsTbody");
  if (!tbody) return;

  auditLogsState.page = page;
  const offset = (page - 1) * auditLogsState.limit;
  const action = $("auditFilterAction").value;
  const username = $("auditFilterUser").value.trim();
  const status = $("auditFilterStatus").value;

  tbody.innerHTML = `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">감사 로그를 조회하는 중…</td></tr>`;

  const params = new URLSearchParams({
    limit: String(auditLogsState.limit),
    offset: String(offset)
  });
  if (action) params.set("action", action);
  if (username) params.set("username", username);
  if (status) params.set("status", status);

  try {
    const data = await api(`/admin/api/audit/logs?${params.toString()}`, { loadingMsg: "감사 로그 조회 중…" });
    currentAuditLogs = (data && data.logs) || [];
    auditLogsState.total = (data && data.count) || 0;

    $("auditLogsTotalCount").textContent = `검색 결과: 총 ${auditLogsState.total}건`;
    const totalPages = Math.max(1, Math.ceil(auditLogsState.total / auditLogsState.limit));
    $("auditPageInfo").textContent = `${page} / ${totalPages} 페이지 (총 ${auditLogsState.total}건)`;
    $("auditPrevPageBtn").disabled = (page <= 1);
    $("auditNextPageBtn").disabled = (page >= totalPages);

    if (currentAuditLogs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">조건에 일치하는 감사 로그가 없습니다.</td></tr>`;
      return;
    }

    tbody.innerHTML = currentAuditLogs.map((log, idx) => {
      const rowNo = offset + idx + 1;
      const timeStr = log.created_at ? new Date(log.created_at * 1000).toLocaleString("ko-KR") : "-";
      const statusBadge = (log.status === "SUCCESS")
        ? `<span class="audit-badge success">성공</span>`
        : `<span class="audit-badge failed">실패</span>`;

      return `
        <tr>
          <td class="muted">${rowNo}</td>
          <td class="muted nw" style="font-size:12px">${timeStr}</td>
          <td><strong>${esc(log.username)}</strong> <span class="chip" style="font-size:10px">${esc(log.role)}</span></td>
          <td><span style="font-weight:600">${esc(log.action_name || log.action)}</span> <span class="muted" style="font-size:11px">(${esc(log.action)})</span></td>
          <td class="trunc" style="max-width:180px">${esc(log.target || "-")}</td>
          <td class="mono" style="font-size:11.5px">${esc(log.ip || "-")}</td>
          <td>${statusBadge}</td>
          <td style="text-align:right">
            <button class="btn sm" style="padding:2px 8px;font-size:11.5px" onclick="openAuditDetail(${idx})">상세보기</button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="banner bad" style="text-align:center;padding:18px">감사 로그 조회 실패: ${esc(e.message)}</td></tr>`;
  }
}

function openAuditDetail(index) {
  const log = currentAuditLogs[index];
  if (!log) return;

  $("auditDetailId").textContent = log.id;
  $("auditDetailTime").textContent = log.created_at ? new Date(log.created_at * 1000).toLocaleString("ko-KR") : "-";
  $("auditDetailActor").textContent = `${log.username} (${log.role})`;
  $("auditDetailAction").textContent = `${log.action_name || ""} (${log.action})`;
  $("auditDetailTarget").textContent = log.target || "-";
  $("auditDetailIp").textContent = log.ip || "-";
  $("auditDetailStatus").innerHTML = (log.status === "SUCCESS")
    ? `<span class="audit-badge success">성공 (SUCCESS)</span>`
    : `<span class="audit-badge failed">실패 (FAILED)</span>`;

  let detailsObj = log.details;
  if (typeof detailsObj === "string") {
    try { detailsObj = JSON.parse(detailsObj); } catch (e) {}
  }
  $("auditDetailJson").textContent = detailsObj ? JSON.stringify(detailsObj, null, 2) : "세부 정보 없음";
  $("adminAuditDetailModal").classList.remove("hidden");
  $("adminAuditDetailModal").style.display = "flex";
}

function closeAuditDetail() {
  $("adminAuditDetailModal").classList.add("hidden");
  $("adminAuditDetailModal").style.display = "none";
}

// 관리자 상단 바 및 모달 버튼 이벤트 바인딩
if ($("headerLoginBtn")) $("headerLoginBtn").onclick = () => openLoginModal();
if ($("adminLoginSubmitBtn")) $("adminLoginSubmitBtn").onclick = submitAdminLogin;
if ($("adminLoginPassword")) $("adminLoginPassword").onkeydown = (e) => { if (e.key === "Enter") submitAdminLogin(); };
if ($("myPageBtn")) $("myPageBtn").onclick = openMyPage;
if ($("logoutBtn")) $("logoutBtn").onclick = logoutAdmin;
if ($("closeMyPageBtn")) $("closeMyPageBtn").onclick = closeMyPage;
if ($("closeMyPageFootBtn")) $("closeMyPageFootBtn").onclick = closeMyPage;
if ($("submitChangePwdBtn")) $("submitChangePwdBtn").onclick = submitPasswordChange;

if ($("openCreateUserBtn")) $("openCreateUserBtn").onclick = openCreateUserModal;
if ($("closeCreateUserBtn")) $("closeCreateUserBtn").onclick = closeCreateUserModal;
if ($("cancelCreateUserBtn")) $("cancelCreateUserBtn").onclick = closeCreateUserModal;
if ($("submitCreateUserBtn")) $("submitCreateUserBtn").onclick = submitCreateUser;
if ($("refreshAdminUsersBtn")) $("refreshAdminUsersBtn").onclick = loadAdminUsers;

if ($("refreshAuditBtn")) $("refreshAuditBtn").onclick = () => loadAuditLogs(1);
if ($("auditSearchBtn")) $("auditSearchBtn").onclick = () => loadAuditLogs(1);
if ($("auditFilterAction")) $("auditFilterAction").onchange = () => loadAuditLogs(1);
if ($("auditFilterStatus")) $("auditFilterStatus").onchange = () => loadAuditLogs(1);
if ($("auditResetFilterBtn")) $("auditResetFilterBtn").onclick = () => {
  $("auditFilterAction").value = "";
  $("auditFilterUser").value = "";
  $("auditFilterStatus").value = "";
  loadAuditLogs(1);
};
if ($("auditPrevPageBtn")) $("auditPrevPageBtn").onclick = () => { if (auditLogsState.page > 1) loadAuditLogs(auditLogsState.page - 1); };
if ($("auditNextPageBtn")) $("auditNextPageBtn").onclick = () => { loadAuditLogs(auditLogsState.page + 1); };
if ($("closeAuditDetailBtn")) $("closeAuditDetailBtn").onclick = closeAuditDetail;
if ($("closeAuditDetailFootBtn")) $("closeAuditDetailFootBtn").onclick = closeAuditDetail;
"""

    # 7. Replace the old startup section with auth-guarded startup
    old_startup = """// ---------- 시작 ----------
const TABS = ["overview", "learn", "explore", "sns", "visitors", "security", "register", "test", "progress", "agents", "errors", "needs", "manage", "users", "audit"];
const hashTab = () => {
  const raw = (location.hash || "").slice(1);
  const t = raw.split("?")[0].split("&")[0];
  return TABS.includes(t) ? t : "overview";
};
window.addEventListener("hashchange", () => { if (hashTab() !== state.tab) switchTab(hashTab()); });
switchTab(hashTab());
schedule();"""

    new_startup = admin_js + """
// ---------- 시작 ----------
const TABS = ["overview", "learn", "explore", "sns", "visitors", "security", "register", "test", "progress", "agents", "errors", "needs", "manage", "users", "audit"];
const hashTab = () => {
  const raw = (location.hash || "").slice(1);
  const t = raw.split("?")[0].split("&")[0];
  return TABS.includes(t) ? t : "overview";
};

window.addEventListener("hashchange", () => {
  if (!currentUser) {
    openLoginModal("관리자 로그인이 필요합니다.");
    return;
  }
  if (hashTab() !== state.tab) switchTab(hashTab());
});

// 시작 시 관리자 세션 검증 (인증되지 않은 경우 대시보드 대신 로그인 화면 표출)
checkAdminAuth().then((authed) => {
  if (authed) {
    switchTab(hashTab());
    schedule();
  } else {
    openLoginModal("관리자 인증이 필요합니다. 로그인해주세요.");
  }
});"""

    if old_startup in html:
        html = html.replace(old_startup, new_startup, 1)
    else:
        print("Warning: old_startup not matched exactly, looking for alternate insertion...")
        # Check if admin_js already partially added
        if "checkAdminAuth" not in html:
            target_marker = "// ---------- 시작 ----------"
            assert target_marker in html, "Could not find startup marker"
            html = html.replace(target_marker, new_startup, 1)

    DASHBOARD_HTML.write_text(html, encoding="utf-8")
    print("dashboard.html successfully patched!")

if __name__ == "__main__":
    main()

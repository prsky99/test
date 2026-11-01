"""Update agent_market/gateway/dashboard.html to add admin management, auth modals, and audit trail."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_HTML = ROOT / "agent_market" / "gateway" / "dashboard.html"

def main():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    # 1. Add CSS styles before </style>
    style_marker = "</style>"
    assert style_marker in html, "Could not find </style>"

    admin_css = """
/* 관리자 및 감사 로그 스타일 */
.audit-badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 99px; font-size: 11.5px; font-weight: 600; }
.audit-badge.success { background: rgba(31,157,85,0.12); color: var(--ok); border: 1px solid rgba(31,157,85,0.3); }
.audit-badge.failed { background: rgba(220,38,38,0.12); color: var(--bad); border: 1px solid rgba(220,38,38,0.3); }
.audit-badge.info { background: rgba(59,130,246,0.12); color: var(--reach); border: 1px solid rgba(59,130,246,0.3); }

.admin-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.55); backdrop-filter: blur(4px);
  z-index: 50; display: flex; justify-content: center; align-items: center; padding: 20px;
}
.admin-modal-card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  width: min(520px, 100%); max-height: 90vh; overflow-y: auto; box-shadow: 0 16px 36px rgba(0,0,0,0.3);
  display: flex; flex-direction: column;
}
.admin-modal-head {
  display: flex; justify-content: space-between; align-items: center; padding: 14px 18px;
  border-bottom: 1px solid var(--line); font-weight: 700; font-size: 16px;
}
.admin-modal-body { padding: 18px 20px; }
.admin-modal-foot {
  display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px;
  border-top: 1px solid var(--line); background: var(--bg); border-bottom-left-radius: 14px; border-bottom-right-radius: 14px;
}
.form-group { margin-bottom: 14px; }
.form-group label { display: block; font-size: 12.5px; font-weight: 600; margin-bottom: 5px; color: var(--text); }
.form-group input, .form-group select { width: 100%; box-sizing: border-box; }
.form-hint { font-size: 11.5px; color: var(--muted); margin-top: 4px; }
"""
    if "/* 관리자 및 감사 로그 스타일 */" not in html:
        html = html.replace(style_marker, admin_css + "\n" + style_marker, 1)

    # 2. Add admin user status area to <div class="bar">
    old_bar_end = """    <button class="btn" id="refreshBtn">새로고침</button>
    <button class="btn" id="pauseBtn">일시정지</button>
  </div>"""

    new_bar_end = """    <button class="btn" id="refreshBtn">새로고침</button>
    <button class="btn" id="pauseBtn">일시정지</button>
    <div id="adminUserArea" style="display:flex;align-items:center;gap:8px;margin-left:auto;border-left:1px solid var(--line);padding-left:12px">
      <span id="adminUserBadge" class="status-pill" style="font-weight:600;background:rgba(59,130,246,0.12);color:var(--accent);border:1px solid rgba(59,130,246,0.25)">
        <span>👤</span> <span id="adminUsername">sadmin</span> <span id="adminRoleBadge" class="chip" style="font-size:11px;padding:1px 6px">최고관리자</span>
      </span>
      <button class="btn" id="myPageBtn" style="padding:4px 10px;font-size:12px">마이페이지</button>
      <button class="btn" id="logoutBtn" style="padding:4px 10px;font-size:12px;color:var(--bad)">로그아웃</button>
      <button class="btn primary" id="headerLoginBtn" style="padding:4px 10px;font-size:12px;display:none">로그인</button>
    </div>
  </div>"""

    if "adminUserArea" not in html:
        assert old_bar_end in html, "Could not find old_bar_end in HTML"
        html = html.replace(old_bar_end, new_bar_end, 1)

    # 3. Add tabs for users and audit
    old_tabs_end = """    <button data-tab="manage">관리</button>
  </nav>"""

    new_tabs_end = """    <button data-tab="manage">관리</button>
    <button data-tab="users" id="tabUsers">관리자 관리</button>
    <button data-tab="audit" id="tabAudit" style="display:none">관리자 감사</button>
  </nav>"""

    if 'id="tabAudit"' not in html:
        assert old_tabs_end in html, "Could not find old_tabs_end in HTML"
        html = html.replace(old_tabs_end, new_tabs_end, 1)

    # 4. Add panels before </main>
    old_main_end = """    <div class="card" style="margin-top:14px"><h2>작업 상태</h2><div id="actionBox" class="muted">아직 실행한 작업이 없습니다.</div></div>
  </section>
</main>"""

    panels_html = """    <div class="card" style="margin-top:14px"><h2>작업 상태</h2><div id="actionBox" class="muted">아직 실행한 작업이 없습니다.</div></div>
  </section>

  <!-- 관리자 관리 패널 -->
  <section data-panel="users" class="hidden">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <div>
        <h2 style="margin:0;font-size:18px">관리자 계정 관리</h2>
        <p class="muted" style="margin:4px 0 0;font-size:12.5px">시스템 관리자 계정을 생성, 수정 및 권한을 관리합니다. (sadmin 전용)</p>
      </div>
      <button class="btn primary" id="openCreateUserBtn">+ 신규 관리자 등록</button>
    </div>

    <div class="card" style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <h3 style="margin:0;font-size:14px">등록된 관리자 목록 <span class="sub" id="adminUsersCount"></span></h3>
        <button class="btn" id="refreshAdminUsersBtn" style="font-size:12px">새로고침</button>
      </div>
      <div class="scroll">
        <table id="adminUsersTable">
          <thead>
            <tr>
              <th style="width:50px">ID</th>
              <th>아이디</th>
              <th>성명/별칭</th>
              <th>권한(역할)</th>
              <th>상태</th>
              <th>생성일시</th>
              <th>최근 로그인</th>
              <th style="text-align:right">작업</th>
            </tr>
          </thead>
          <tbody id="adminUsersTbody">
            <tr><td colspan="8" class="muted" style="text-align:center;padding:24px">관리자 목록을 불러오는 중…</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="banner info" style="background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.2);font-size:12.5px">
      <strong>보안 안내:</strong> <code>sadmin</code> 계정은 시스템 기본 최고관리자 계정으로 임의 삭제가 불가능하며, 관리자 감사 메뉴에 대한 독점 열람 권한을 가집니다.
    </div>
  </section>

  <!-- 관리자 감사 로그 패널 -->
  <section data-panel="audit" class="hidden">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <div>
        <h2 style="margin:0;font-size:18px">관리자 감사 로그 (Audit Trail)</h2>
        <p class="muted" style="margin:4px 0 0;font-size:12.5px">모든 관리자의 로그인, 설정 변경, 에이전트 테스트 및 중요 시스템 작업 기록을 보관합니다. (sadmin 전용)</p>
      </div>
      <div class="row">
        <span class="audit-badge info">sadmin 보안 감사 활성화됨</span>
        <button class="btn" id="refreshAuditBtn" style="font-size:12px">감사 로그 새로고침</button>
      </div>
    </div>

    <div class="card" style="margin-bottom:14px">
      <div class="filters" style="margin-bottom:12px">
        <select id="auditFilterAction">
          <option value="">모든 작업 유형</option>
          <option value="LOGIN">로그인 (LOGIN)</option>
          <option value="LOGOUT">로그아웃 (LOGOUT)</option>
          <option value="PASSWORD_CHANGE">비밀번호 변경</option>
          <option value="USER_CREATE">관리자 생성</option>
          <option value="USER_UPDATE">관리자 수정</option>
          <option value="USER_DELETE">관리자 삭제</option>
          <option value="AGENT_TEST">에이전트 테스트 실행</option>
          <option value="CHECK">에이전트 수동 점검</option>
          <option value="DEACTIVATE">에이전트 비활성화</option>
          <option value="ACTIVATE">에이전트 활성화</option>
          <option value="CRAWL">크롤러 실행</option>
          <option value="RESCAN">재스캔 실행</option>
        </select>
        <input type="text" id="auditFilterUser" placeholder="관리자 아이디 (예: sadmin)" style="width:160px">
        <select id="auditFilterStatus">
          <option value="">모든 결과</option>
          <option value="SUCCESS">성공 (SUCCESS)</option>
          <option value="FAILED">실패 (FAILED)</option>
        </select>
        <button class="btn primary" id="auditSearchBtn">조회</button>
        <button class="btn" id="auditResetFilterBtn">초기화</button>
        <span class="spacer"></span>
        <span class="muted" id="auditLogsTotalCount" style="font-size:12px"></span>
      </div>

      <div class="scroll">
        <table id="auditLogsTable">
          <thead>
            <tr>
              <th style="width:60px">No</th>
              <th>일시 (KST)</th>
              <th>관리자</th>
              <th>작업명 (Action)</th>
              <th>대상 (Target)</th>
              <th>접속 IP</th>
              <th>결과</th>
              <th style="text-align:right">상세</th>
            </tr>
          </thead>
          <tbody id="auditLogsTbody">
            <tr><td colspan="8" class="muted" style="text-align:center;padding:24px">감사 로그를 불러오는 중…</td></tr>
          </tbody>
        </table>
      </div>

      <!-- 페이지네이션 -->
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid var(--line)">
        <span class="muted" id="auditPageInfo" style="font-size:12px"></span>
        <div class="row" style="gap:6px">
          <button class="btn" id="auditPrevPageBtn" disabled>‹ 이전 페이지</button>
          <button class="btn" id="auditNextPageBtn" disabled>다음 페이지 ›</button>
        </div>
      </div>
    </div>
  </section>
</main>"""

    if 'data-panel="audit"' not in html:
        assert old_main_end in html, "Could not find old_main_end in HTML"
        html = html.replace(old_main_end, panels_html, 1)

    # 5. Add modals after </main>
    old_modals_pos = '<div id="drawer" class="hidden"></div>'

    modals_html = """<!-- 관리자 로그인 모달 -->
<div id="adminLoginModal" class="admin-modal-overlay hidden">
  <div class="admin-modal-card">
    <div class="admin-modal-head">
      <span>관리자 로그인</span>
      <span class="chip" style="font-size:11px">기본 계정: sadmin</span>
    </div>
    <div class="admin-modal-body">
      <div id="adminLoginError" class="banner bad hidden" style="margin-bottom:12px;font-size:12.5px"></div>
      <div class="form-group">
        <label for="adminLoginUsername">관리자 아이디</label>
        <input type="text" id="adminLoginUsername" value="sadmin" placeholder="아이디를 입력하세요">
      </div>
      <div class="form-group">
        <label for="adminLoginPassword">비밀번호</label>
        <input type="password" id="adminLoginPassword" value="sadmin" placeholder="비밀번호를 입력하세요">
        <div class="form-hint">초기 기본 계정: <code>sadmin</code> / <code>sadmin</code></div>
      </div>
    </div>
    <div class="admin-modal-foot">
      <button class="btn primary" id="adminLoginSubmitBtn" style="width:100%">로그인</button>
    </div>
  </div>
</div>

<!-- 마이페이지 모달 (계정 정보 및 비밀번호 재등록) -->
<div id="adminMyPageModal" class="admin-modal-overlay hidden">
  <div class="admin-modal-card" style="width:min(560px, 100%)">
    <div class="admin-modal-head">
      <span>마이페이지 (계정 정보 및 비밀번호 재등록)</span>
      <button class="btn" id="closeMyPageBtn" style="padding:2px 8px;font-size:14px">✕</button>
    </div>
    <div class="admin-modal-body">
      <div style="background:var(--chip);border-radius:10px;padding:12px 14px;margin-bottom:18px">
        <h4 style="margin:0 0 8px;font-size:13.5px">내 계정 정보</h4>
        <dl class="kv" style="margin:0">
          <dt>아이디</dt><dd><strong id="myPageUsername">sadmin</strong></dd>
          <dt>성명/별칭</dt><dd id="myPageName">최고관리자</dd>
          <dt>권한 역할</dt><dd><span id="myPageRole" class="chip" style="font-weight:600">superadmin</span></dd>
          <dt>최근 로그인</dt><dd id="myPageLastLogin" class="muted">-</dd>
        </dl>
      </div>

      <div style="border-top:1px solid var(--line);padding-top:14px">
        <h4 style="margin:0 0 10px;font-size:13.5px">비밀번호 재등록 / 변경</h4>
        <div id="myPagePwdError" class="banner bad hidden" style="margin-bottom:10px;font-size:12px"></div>
        <div id="myPagePwdSuccess" class="banner" style="background:rgba(31,157,85,0.12);color:var(--ok);border:1px solid rgba(31,157,85,0.3);margin-bottom:10px;font-size:12px;display:none"></div>
        <div class="form-group">
          <label for="myPageCurrentPwd">현재 비밀번호</label>
          <input type="password" id="myPageCurrentPwd" placeholder="현재 비밀번호">
        </div>
        <div class="form-group">
          <label for="myPageNewPwd">새 비밀번호 (최소 4자)</label>
          <input type="password" id="myPageNewPwd" placeholder="새 비밀번호 입력">
        </div>
        <div class="form-group">
          <label for="myPageConfirmPwd">새 비밀번호 확인</label>
          <input type="password" id="myPageConfirmPwd" placeholder="새 비밀번호 다시 입력">
        </div>
        <button class="btn primary" id="submitChangePwdBtn" style="width:100%;margin-top:6px">비밀번호 재등록 완료</button>
      </div>
    </div>
    <div class="admin-modal-foot">
      <button class="btn" id="closeMyPageFootBtn">닫기</button>
    </div>
  </div>
</div>

<!-- 신규 관리자 등록 모달 -->
<div id="adminCreateUserModal" class="admin-modal-overlay hidden">
  <div class="admin-modal-card">
    <div class="admin-modal-head">
      <span>신규 관리자 계정 생성</span>
      <button class="btn" id="closeCreateUserBtn" style="padding:2px 8px;font-size:14px">✕</button>
    </div>
    <div class="admin-modal-body">
      <div id="createUserError" class="banner bad hidden" style="margin-bottom:12px;font-size:12.5px"></div>
      <div class="form-group">
        <label for="newAdminUsername">아이디 *</label>
        <input type="text" id="newAdminUsername" placeholder="예: operator1">
      </div>
      <div class="form-group">
        <label for="newAdminName">성명/별칭</label>
        <input type="text" id="newAdminName" placeholder="예: 홍길동 (운영담당)">
      </div>
      <div class="form-group">
        <label for="newAdminPassword">초기 비밀번호 (최소 4자) *</label>
        <input type="password" id="newAdminPassword" placeholder="초기 비밀번호">
      </div>
      <div class="form-group">
        <label for="newAdminRole">권한 (역할)</label>
        <select id="newAdminRole">
          <option value="admin">일반 관리자 (admin)</option>
          <option value="operator">운영자 (operator)</option>
          <option value="superadmin">최고 관리자 (superadmin)</option>
        </select>
        <div class="form-hint">최고 관리자(superadmin)는 감사 로그 열람 및 관리자 계정 관리 권한을 갖습니다.</div>
      </div>
    </div>
    <div class="admin-modal-foot">
      <button class="btn" id="cancelCreateUserBtn">취소</button>
      <button class="btn primary" id="submitCreateUserBtn">계정 생성</button>
    </div>
  </div>
</div>

<!-- 감사 로그 상세 보기 모달 -->
<div id="adminAuditDetailModal" class="admin-modal-overlay hidden">
  <div class="admin-modal-card" style="width:min(640px, 100%)">
    <div class="admin-modal-head">
      <span>감사 로그 상세 내역</span>
      <button class="btn" id="closeAuditDetailBtn" style="padding:2px 8px;font-size:14px">✕</button>
    </div>
    <div class="admin-modal-body">
      <dl class="kv" style="margin-bottom:14px">
        <dt>로그 ID</dt><dd id="auditDetailId">-</dd>
        <dt>발생 일시</dt><dd id="auditDetailTime">-</dd>
        <dt>작업자</dt><dd id="auditDetailActor">-</dd>
        <dt>작업명</dt><dd id="auditDetailAction">-</dd>
        <dt>대상(Target)</dt><dd id="auditDetailTarget">-</dd>
        <dt>접속 IP</dt><dd id="auditDetailIp">-</dd>
        <dt>상태</dt><dd id="auditDetailStatus">-</dd>
      </dl>
      <h4 style="margin:10px 0 6px;font-size:13px">상세 파라미터 / 세부 데이터</h4>
      <pre id="auditDetailJson" style="max-height:260px;margin:0"></pre>
    </div>
    <div class="admin-modal-foot">
      <button class="btn" id="closeAuditDetailFootBtn">닫기</button>
    </div>
  </div>
</div>

""" + old_modals_pos

    if 'id="adminLoginModal"' not in html:
        assert old_modals_pos in html, "Could not find old_modals_pos in HTML"
        html = html.replace(old_modals_pos, modals_html, 1)

    # 6. Update TABS array in JS
    old_tabs_arr = 'const TABS = ["overview", "learn", "explore", "sns", "visitors", "security", "register", "test", "progress", "agents", "errors", "needs", "manage"];'
    new_tabs_arr = 'const TABS = ["overview", "learn", "explore", "sns", "visitors", "security", "register", "test", "progress", "agents", "errors", "needs", "manage", "users", "audit"];'
    if old_tabs_arr in html:
        html = html.replace(old_tabs_arr, new_tabs_arr, 1)

    # 7. Add JS functions for admin auth, mypage, users, and audit
    js_code = """
// ==================== 관리자 인증, 세션, 마이페이지, 계정 관리 & 감사 로그 ====================
let currentUser = null;
let auditLogsState = { page: 1, limit: 30, total: 0 };

async function checkAdminAuth() {
  try {
    const res = await api("/admin/api/auth/me", { silent: true });
    if (res && res.ok && res.user) {
      currentUser = res.user;
      currentUser.is_sadmin = Boolean(res.is_sadmin);
      updateUserUI(currentUser, currentUser.is_sadmin);
      return true;
    }
  } catch (e) {
    currentUser = null;
    updateUserUI(null, false);
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
  const tabUsers = $("tabUsers");
  const tabAudit = $("tabAudit");

  if (user) {
    usernameEl.textContent = user.username;
    const roleMap = { superadmin: "최고관리자", admin: "관리자", operator: "운영자" };
    roleEl.textContent = roleMap[user.role] || user.role;
    badge.style.display = "";
    myPageBtn.style.display = "";
    logoutBtn.style.display = "";
    headerLoginBtn.style.display = "none";

    // sadmin 전용 메뉴 가시성 제어
    const canSeeAudit = isSadmin || user.role === "superadmin" || user.username === "sadmin";
    if (tabAudit) tabAudit.style.display = canSeeAudit ? "" : "none";
    if (tabUsers) tabUsers.style.display = canSeeAudit ? "" : "none";
  } else {
    usernameEl.textContent = "비로그인";
    roleEl.textContent = "-";
    badge.style.display = "none";
    myPageBtn.style.display = "none";
    logoutBtn.style.display = "none";
    headerLoginBtn.style.display = "";
    if (tabAudit) tabAudit.style.display = "none";
    if (tabUsers) tabUsers.style.display = "none";
  }
}

function openLoginModal(errMsg = "") {
  const errEl = $("adminLoginError");
  if (errMsg) {
    errEl.textContent = errMsg;
    errEl.classList.remove("hidden");
  } else {
    errEl.classList.add("hidden");
  }
  $("adminLoginModal").classList.remove("hidden");
}

function closeLoginModal() {
  $("adminLoginModal").classList.add("hidden");
}

async function submitAdminLogin() {
  const u = $("adminLoginUsername").value.trim();
  const p = $("adminLoginPassword").value;
  const errEl = $("adminLoginError");
  errEl.classList.add("hidden");

  if (!u || !p) {
    errEl.textContent = "아이디와 비밀번호를 모두 입력해주세요.";
    errEl.classList.remove("hidden");
    return;
  }

  try {
    const res = await api("/admin/api/auth/login", {
      method: "POST",
      loadingMsg: "로그인 인증 중…",
      json: { username: u, password: p }
    });
    if (res && res.ok) {
      token = res.token;
      try { sessionStorage.setItem("adminToken", token); } catch (e) {}
      currentUser = res.user;
      closeLoginModal();
      updateUserUI(currentUser, res.user.is_sadmin);
      toast(`${currentUser.username} 관리자님 환영합니다.`);
      switchTab(state.tab || "overview");
    }
  } catch (e) {
    errEl.textContent = e.message || "로그인에 실패했습니다.";
    errEl.classList.remove("hidden");
  }
}

async function logoutAdmin() {
  if (!confirm("정말 로그아웃하시겠습니까?")) return;
  try {
    await api("/admin/api/auth/logout", { method: "POST", loadingMsg: "로그아웃 중…" });
  } catch (e) {}
  token = "";
  try { sessionStorage.removeItem("adminToken"); } catch (e) {}
  currentUser = null;
  updateUserUI(null, false);
  toast("성공적으로 로그아웃되었습니다.");
  openLoginModal("로그아웃되었습니다. 다시 로그인하세요.");
}

function openMyPage() {
  if (!currentUser) {
    openLoginModal("먼저 로그인해주세요.");
    return;
  }
  $("myPageUsername").textContent = currentUser.username;
  $("myPageName").textContent = currentUser.name || currentUser.username;
  $("myPageRole").textContent = currentUser.role === "superadmin" ? "최고관리자 (superadmin)" : currentUser.role;
  $("myPageLastLogin").textContent = currentUser.last_login ? new Date(currentUser.last_login * 1000).toLocaleString("ko-KR") : "기록 없음";

  $("myPageCurrentPwd").value = "";
  $("myPageNewPwd").value = "";
  $("myPageConfirmPwd").value = "";
  $("myPagePwdError").classList.add("hidden");
  $("myPagePwdSuccess").style.display = "none";
  $("adminMyPageModal").classList.remove("hidden");
}

function closeMyPage() {
  $("adminMyPageModal").classList.add("hidden");
}

async function submitPasswordChange() {
  const curr = $("myPageCurrentPwd").value;
  const newP = $("myPageNewPwd").value;
  const confP = $("myPageConfirmPwd").value;
  const errEl = $("myPagePwdError");
  const succEl = $("myPagePwdSuccess");

  errEl.classList.add("hidden");
  succEl.style.display = "none";

  if (!curr) {
    errEl.textContent = "현재 비밀번호를 입력해주세요.";
    errEl.classList.remove("hidden");
    return;
  }
  if (!newP || newP.length < 4) {
    errEl.textContent = "새 비밀번호는 최소 4자 이상이어야 합니다.";
    errEl.classList.remove("hidden");
    return;
  }
  if (newP !== confP) {
    errEl.textContent = "새 비밀번호와 확인 비밀번호가 일치하지 않습니다.";
    errEl.classList.remove("hidden");
    return;
  }

  try {
    const res = await api("/admin/api/auth/change-password", {
      method: "POST",
      loadingMsg: "비밀번호 변경 처리 중…",
      json: { current_password: curr, new_password: newP }
    });
    if (res && res.ok) {
      succEl.textContent = "비밀번호가 성공적으로 변경되었습니다. 다음 로그인부터 적용됩니다.";
      succEl.style.display = "block";
      $("myPageCurrentPwd").value = "";
      $("myPageNewPwd").value = "";
      $("myPageConfirmPwd").value = "";
      toast("비밀번호가 성공적으로 변경되었습니다.");
    }
  } catch (e) {
    errEl.textContent = e.message || "비밀번호 변경 실패";
    errEl.classList.remove("hidden");
  }
}

// ---------- 관리자 계정 관리 (sadmin 전용) ----------
async function loadAdminUsers() {
  const tbody = $("adminUsersTbody");
  tbody.innerHTML = `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">관리자 목록을 불러오는 중…</td></tr>`;

  try {
    const data = await api("/admin/api/users", { loadingMsg: "관리자 목록 조회 중…" });
    const users = (data && data.users) || [];
    $("adminUsersCount").textContent = `(총 ${users.length}명)`;

    if (users.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">등록된 관리자가 없습니다.</td></tr>`;
      return;
    }

    const roleName = { superadmin: "최고관리자", admin: "일반관리자", operator: "운영자" };
    tbody.innerHTML = users.map(u => {
      const isSadmin = (u.username === "sadmin");
      const statusHtml = u.active ? `<span class="audit-badge success">활성</span>` : `<span class="audit-badge failed">비활성</span>`;
      const createdStr = u.created_at ? new Date(u.created_at * 1000).toLocaleString("ko-KR") : "-";
      const loginStr = u.last_login ? new Date(u.last_login * 1000).toLocaleString("ko-KR") : "없음";

      return `
        <tr>
          <td>${u.id}</td>
          <td><strong>${esc(u.username)}</strong> ${isSadmin ? '<span class="chip" style="font-size:10px;background:rgba(59,130,246,0.15);color:var(--accent)">시스템</span>' : ''}</td>
          <td>${esc(u.name || "-")}</td>
          <td><span class="chip">${roleName[u.role] || u.role}</span></td>
          <td>${statusHtml}</td>
          <td class="muted" style="font-size:12px">${createdStr}</td>
          <td class="muted" style="font-size:12px">${loginStr}</td>
          <td style="text-align:right">
            <div class="row" style="justify-content:flex-end;gap:4px">
              <button class="btn" style="padding:2px 7px;font-size:11.5px" onclick="resetUserPasswordPrompt(${u.id}, '${esc(u.username)}')">비번 재설정</button>
              ${!isSadmin ? `
                <button class="btn" style="padding:2px 7px;font-size:11.5px" onclick="toggleUserActive(${u.id}, ${u.active ? 0 : 1})">${u.active ? '비활성화' : '활성화'}</button>
                <button class="btn danger" style="padding:2px 7px;font-size:11.5px" onclick="deleteUserAccount(${u.id}, '${esc(u.username)}')">삭제</button>
              ` : `<span class="muted" style="font-size:11px;padding:2px 6px">보호됨</span>`}
            </div>
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
}

function closeCreateUserModal() {
  $("adminCreateUserModal").classList.add("hidden");
}

async function submitCreateUser() {
  const username = $("newAdminUsername").value.trim();
  const name = $("newAdminName").value.trim();
  const password = $("newAdminPassword").value;
  const role = $("newAdminRole").value;
  const errEl = $("createUserError");

  errEl.classList.add("hidden");
  if (!username || !password) {
    errEl.textContent = "아이디와 비밀번호는 필수 입력 항목입니다.";
    errEl.classList.remove("hidden");
    return;
  }
  if (password.length < 4) {
    errEl.textContent = "비밀번호는 최소 4자 이상이어야 합니다.";
    errEl.classList.remove("hidden");
    return;
  }

  try {
    const res = await api("/admin/api/users", {
      method: "POST",
      loadingMsg: "관리자 계정 생성 중…",
      json: { username, name, password, role }
    });
    if (res && res.ok) {
      toast(`관리자 계정 [${username}]이 생성되었습니다.`);
      closeCreateUserModal();
      loadAdminUsers();
    }
  } catch (e) {
    errEl.textContent = e.message || "계정 생성 실패";
    errEl.classList.remove("hidden");
  }
}

async function resetUserPasswordPrompt(uid, username) {
  const newPwd = prompt(`[${username}] 관리자의 새 비밀번호를 입력하세요 (최소 4자):`);
  if (!newPwd) return;
  if (newPwd.length < 4) {
    alert("비밀번호는 최소 4자 이상이어야 합니다.");
    return;
  }

  try {
    await api(`/admin/api/users/${uid}`, {
      method: "PUT",
      loadingMsg: "비밀번호 재설정 중…",
      json: { new_password: newPwd }
    });
    toast(`[${username}] 관리자의 비밀번호를 재설정했습니다.`);
  } catch (e) {
    toast(`비밀번호 재설정 실패: ${e.message}`);
  }
}

async function toggleUserActive(uid, newActive) {
  try {
    await api(`/admin/api/users/${uid}`, {
      method: "PUT",
      loadingMsg: "상태 변경 중…",
      json: { active: newActive }
    });
    toast("관리자 상태가 변경되었습니다.");
    loadAdminUsers();
  } catch (e) {
    toast(`상태 변경 실패: ${e.message}`);
  }
}

async function deleteUserAccount(uid, username) {
  if (!confirm(`정말 관리자 계정 [${username}]을 삭제하시겠습니까?`)) return;
  try {
    await api(`/admin/api/users/${uid}`, {
      method: "DELETE",
      loadingMsg: "계정 삭제 중…"
    });
    toast(`[${username}] 계정을 삭제했습니다.`);
    loadAdminUsers();
  } catch (e) {
    toast(`삭제 실패: ${e.message}`);
  }
}

// ---------- 관리자 감사 로그 (sadmin 전용) ----------
let currentAuditLogs = [];

async function loadAuditLogs(page = 1) {
  auditLogsState.page = page;
  const tbody = $("auditLogsTbody");
  tbody.innerHTML = `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">감사 로그를 불러오는 중…</td></tr>`;

  const action = $("auditFilterAction").value;
  const username = $("auditFilterUser").value.trim();
  const status = $("auditFilterStatus").value;
  const offset = (page - 1) * auditLogsState.limit;

  const params = new URLSearchParams({
    limit: auditLogsState.limit,
    offset: offset
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
            <button class="btn" style="padding:2px 8px;font-size:11.5px" onclick="openAuditDetail(${idx})">상세보기</button>
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
}

function closeAuditDetail() {
  $("adminAuditDetailModal").classList.add("hidden");
}

// Event Bindings for Admin Modals and Actions
$("headerLoginBtn").onclick = () => openLoginModal();
$("adminLoginSubmitBtn").onclick = submitAdminLogin;
$("adminLoginPassword").onkeydown = (e) => { if (e.key === "Enter") submitAdminLogin(); };
$("myPageBtn").onclick = openMyPage;
$("logoutBtn").onclick = logoutAdmin;
$("closeMyPageBtn").onclick = closeMyPage;
$("closeMyPageFootBtn").onclick = closeMyPage;
$("submitChangePwdBtn").onclick = submitPasswordChange;

$("openCreateUserBtn").onclick = openCreateUserModal;
$("closeCreateUserBtn").onclick = closeCreateUserModal;
$("cancelCreateUserBtn").onclick = closeCreateUserModal;
$("submitCreateUserBtn").onclick = submitCreateUser;
$("refreshAdminUsersBtn").onclick = loadAdminUsers;

$("refreshAuditBtn").onclick = () => loadAuditLogs(1);
$("auditSearchBtn").onclick = () => loadAuditLogs(1);
$("auditFilterAction").onchange = () => loadAuditLogs(1);
$("auditFilterStatus").onchange = () => loadAuditLogs(1);
$("auditResetFilterBtn").onclick = () => {
  $("auditFilterAction").value = "";
  $("auditFilterUser").value = "";
  $("auditFilterStatus").value = "";
  loadAuditLogs(1);
};
$("auditPrevPageBtn").onclick = () => { if (auditLogsState.page > 1) loadAuditLogs(auditLogsState.page - 1); };
$("auditNextPageBtn").onclick = () => { loadAuditLogs(auditLogsState.page + 1); };
$("closeAuditDetailBtn").onclick = closeAuditDetail;
$("closeAuditDetailFootBtn").onclick = closeAuditDetail;

// Auto-check admin auth on startup
checkAdminAuth();
"""

    # Hook into switchTab
    old_switch_tab = """function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll("section[data-panel]").forEach((s) => s.classList.toggle("hidden", s.dataset.panel !== tab));
  try { history.replaceState(null, "", "#" + tab); } catch (e) {}
  refresh();
}"""

    new_switch_tab = """function switchTab(tab) {
  if (tab === "audit" || tab === "users") {
    if (!currentUser || (!currentUser.is_sadmin && currentUser.role !== "superadmin" && currentUser.username !== "sadmin")) {
      toast("sadmin(최고관리자) 권한만 접근할 수 있는 메뉴입니다.");
      tab = "overview";
    }
  }
  state.tab = tab;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll("section[data-panel]").forEach((s) => s.classList.toggle("hidden", s.dataset.panel !== tab));
  try { history.replaceState(null, "", "#" + tab); } catch (e) {}
  refresh();
}"""
    if "tab === 'audit' || tab === 'users'" not in html:
        assert old_switch_tab in html, "Could not find old_switch_tab in HTML"
        html = html.replace(old_switch_tab, new_switch_tab, 1)

    # Hook into refresh()
    old_refresh_tail = """    if (state.tab === "needs") loadNeeds();
    if (state.tab === "manage") renderActions(ov);"""

    new_refresh_tail = """    if (state.tab === "needs") loadNeeds();
    if (state.tab === "manage") renderActions(ov);
    if (state.tab === "users" && !auto) loadAdminUsers();
    if (state.tab === "audit" && !auto) loadAuditLogs(auditLogsState.page || 1);"""

    if 'state.tab === "audit"' not in html:
        assert old_refresh_tail in html, "Could not find old_refresh_tail in HTML"
        html = html.replace(old_refresh_tail, new_refresh_tail, 1)

    # Insert JS code before </script>
    if "loadAdminUsers" not in html:
        script_marker = "</script>"
        last_script_idx = html.rfind(script_marker)
        assert last_script_idx != -1, "Could not find </script>"
        html = html[:last_script_idx] + "\n" + js_code + "\n" + html[last_script_idx:]

    DASHBOARD_HTML.write_text(html, encoding="utf-8")
    print("dashboard.html successfully updated!")

if __name__ == "__main__":
    main()

// Consent and policy dialogs shared by every public page (moved from operating.js, 11-14 bundle split, PM decision).
// The function and constant names are unchanged, so operating.js and pearl-ui.js call them as before. On a page
// without operating.js (about, agent-status, learn) this file also starts the consent banner and answers the policy
// buttons itself; with operating.js present it only defines them, so nothing runs twice. Keys and values stored for
// consent (COOKIE_STORAGE_KEY) are the same as before, so earlier choices stay in force.
function __policyEl(id) { return document.getElementById(id); }
function __policyEsc(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]); }
async function __policyApi(url, opts = {}) {
  if (typeof api === "function") return api(url, opts);
  const headers = { ...(opts.headers || {}) };
  let body = opts.body;
  if (opts.json) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
  const res = await fetch(url, { method: (opts.method || "GET").toUpperCase(), headers, body, credentials: "same-origin",
                                 signal: AbortSignal.timeout(opts.timeoutMs || 8000) });
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) throw Object.assign(new Error((data && (data.detail || data.title || data.error)) || ("Request failed (" + res.status + ").")), { status: res.status, data });
  return data;
}
function __policyToast(msg, type = "info") {
  if (typeof toast === "function") return toast(msg, type);
  return __policyLiteToast(msg, type);
}
function __policyAlert(options) {
  if (typeof showModalAlert === "function") return showModalAlert(options);
  return __policyLiteAlert(options);
}
function __policyTasks() {
  if (typeof renderTaskPreferences === "function") return renderTaskPreferences();
  const host = __policyEl("taskPreferences");
  if (host) host.innerHTML = '<p><a class="btn" href="/#cancellation">Manage task notifications on the home page</a></p>';
}
function __policyTaskRequest(...args) {
  if (typeof taskRequest === "function") return taskRequest(...args);
  return Promise.reject(new Error("Open notification settings on the home page."));
}

function __policyLiteToast(msg, type = "info") {
  if (!msg) return;
  let container = __policyEl("frontToastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "frontToastContainer";
    container.setAttribute("aria-live", "polite");
    document.body.appendChild(container);
  }
  const el = document.createElement("div");
  el.className = "front-toast";
  let iconSvg = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--accent)"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
  const lower = String(msg).toLowerCase();
  if (type === "success" || lower.includes("loaded") || lower.includes("success") || lower.includes("completed") || lower.includes("copied")) {
    iconSvg = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--ok)"><path d="M20 6 9 17l-5-5"/></svg>';
  } else if (type === "error" || lower.includes("fail") || lower.includes("error") || lower.includes("invalid") || lower.includes("unable")) {
    iconSvg = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--bad)"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
  }
  el.innerHTML = `${iconSvg}<span>${__policyEsc(String(msg))}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 260);
  }, 3200);
}

const __POLICY_ICONS = {
  warning: `<svg class="lucide lucide-alert-triangle" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>`,
  success: `<svg class="lucide lucide-check-circle-2" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>`,
  error: `<svg class="lucide lucide-alert-circle" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>`,
  info: `<svg class="lucide lucide-info" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>`
};

function __policyLiteAlert(options) {
  const opts = typeof options === "string" ? { message: options } : (options || {});
  const type = opts.type || "warning";
  const title = opts.title || (type === "error" ? "Action Notice" : type === "success" ? "Operation Successful" : type === "info" ? "Notice" : "Attention Required");
  const msg = opts.message || "";
  const okText = opts.okText || "Acknowledge";
  __policyAlertClose = (opts && typeof opts.onClose === "function") ? opts.onClose : null;

  const modal = __policyEl("appLayerModal");
  if (!modal) return;

  __policyEl("layerModalTitle").textContent = title;
  if (opts.html) {
    __policyEl("layerModalBody").innerHTML = opts.html;
  } else {
    __policyEl("layerModalBody").textContent = msg;
  }
  __policyEl("layerModalOkBtn").textContent = okText;

  const iconWrap = __policyEl("layerModalIcon");
  if (iconWrap) {
    iconWrap.className = "layer-modal-icon-wrap type-" + type;
    iconWrap.innerHTML = __POLICY_ICONS[type] || __POLICY_ICONS.warning;
  }

  if (typeof modal.showModal === "function") {
    if (!modal.open) modal.showModal();
  } else {
    modal.setAttribute("open", "");
  }
}


// ==================== Global Legal Compliance & Cookie Governance ====================
const COOKIE_STORAGE_KEY = "agent_cookie_consent_v2";

function isGpcActive() {
  return typeof navigator !== "undefined" && Boolean(navigator.globalPrivacyControl);
}

function updateConsentModeState(analyticsGranted, marketingGranted) {
  if (typeof gtag === "function") {
    gtag("consent", "update", {
      "analytics_storage": analyticsGranted ? "granted" : "denied",
      "ad_storage": marketingGranted ? "granted" : "denied",
      "ad_user_data": marketingGranted ? "granted" : "denied",
      "ad_personalization": marketingGranted ? "granted" : "denied"
    });
  }
}

function initCookieConsent() {
  const banner = __policyEl("cookieConsentBanner");
  const gpcBadge = __policyEl("gpcBadge");
  const hasGpc = isGpcActive();
  // A floating banner (older layout) reserves space so it never hides content; see the in-flow note below.
  // While visible, reserve matching space at the end of the page and in scroll padding so focus and footer stay reachable.
  if (banner && !banner.dataset.spaceSync) {
    banner.dataset.spaceSync = "1";
    const root = document.documentElement;
    // 11-11: the strip normally sits in the page flow above the header (styles.css); it then needs no
    // reserved space. The space below is kept only for a floating strip.
    const floating = () => getComputedStyle(banner).position === "fixed";
    let wasVisible = !banner.classList.contains("hidden");
    const syncSpace = () => {
      const visible = !banner.classList.contains("hidden") && floating();
      const nowVisible = !banner.classList.contains("hidden");
      if (wasVisible && !nowVisible) {
        // After a choice the strip leaves; keyboard focus goes to the start of the page content.
        const active = document.activeElement;
        if (!active || active === document.body || banner.contains(active)) {
          const main = document.getElementById("mainContent");
          if (main) { if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1"); main.focus({preventScroll: true}); }
        }
      }
      wasVisible = nowVisible;
      const space = visible ? Math.ceil(banner.getBoundingClientRect().height) + 24 : 0;
      document.body.style.paddingBottom = space ? space + "px" : "";
      root.style.scrollPaddingBottom = space ? space + "px" : "";
    };
    const revealFocus = event => {
      const target = event.target;
      if (!(target instanceof HTMLElement) || banner.contains(target) || banner.classList.contains("hidden") || !floating()) return;
      const rect = target.getBoundingClientRect(), box = banner.getBoundingClientRect();
      if (rect.width && rect.height && rect.bottom > box.top - 16 && rect.top < box.bottom) {
        window.scrollBy({top: rect.bottom - box.top + 24, behavior: "instant"});
      }
    };
    document.addEventListener("focusin", revealFocus);
    new MutationObserver(syncSpace).observe(banner, { attributes: true, attributeFilter: ["class"] });
    syncSpace();
    if (typeof ResizeObserver === "function") new ResizeObserver(syncSpace).observe(banner);
  }

  if (gpcBadge && hasGpc) {
    gpcBadge.classList.remove("hidden");
  }

  const stored = localStorage.getItem(COOKIE_STORAGE_KEY);
  if (!stored) {
    if (hasGpc) {
      // Automatically honor GPC signal as opt-out of non-essential
      localStorage.setItem(COOKIE_STORAGE_KEY, JSON.stringify({
        level: "gpc_essential",
        analytics: false,
        marketing: false,
        timestamp: new Date().toISOString(),
        gpc: true
      }));
      updateConsentModeState(false, false);
    } else if (banner) {
      banner.classList.remove("hidden");
    }
  } else {
    try {
      const parsed = JSON.parse(stored);
      updateConsentModeState(Boolean(parsed.analytics), Boolean(parsed.marketing));
    } catch (e) {
      if (banner) banner.classList.remove("hidden");
    }
  }

  const btnAccept = __policyEl("btnAcceptAllCookies");
  const btnReject = __policyEl("btnRejectNonEssentialCookies");
  const btnPrefs = __policyEl("btnOpenCookiePrefs");

  if (btnAccept) {
    btnAccept.onclick = () => {
      localStorage.setItem(COOKIE_STORAGE_KEY, JSON.stringify({
        level: "all",
        analytics: true,
        marketing: true,
        timestamp: new Date().toISOString(),
        gpc: hasGpc
      }));
      updateConsentModeState(true, true);
      if (banner) banner.classList.add("hidden");
      __policyToast("Your cookie preferences have been saved.");
    };
  }

  if (btnReject) {
    btnReject.onclick = () => {
      localStorage.setItem(COOKIE_STORAGE_KEY, JSON.stringify({
        level: "essential",
        analytics: false,
        marketing: false,
        timestamp: new Date().toISOString(),
        gpc: hasGpc
      }));
      updateConsentModeState(false, false);
      if (banner) banner.classList.add("hidden");
      __policyToast("Only essential storage is enabled. You can change this in Cookie Preferences.");
    };
  }

  if (btnPrefs) {
    btnPrefs.onclick = () => openCookiePrefsModal();
  }

  const btnSavePrefs = __policyEl("btnSaveCookiePrefs");
  if (btnSavePrefs) {
    btnSavePrefs.onclick = () => {
      const anOn = __policyEl("prefAnalyticsToggle") ? __policyEl("prefAnalyticsToggle").checked : false;
      const mkOn = __policyEl("prefMarketingToggle") ? __policyEl("prefMarketingToggle").checked : false;
      localStorage.setItem(COOKIE_STORAGE_KEY, JSON.stringify({
        level: "custom",
        analytics: anOn,
        marketing: mkOn,
        timestamp: new Date().toISOString(),
        gpc: hasGpc
      }));
      updateConsentModeState(anOn, mkOn);
      if (__policyEl("cookiePrefsModal")) __policyEl("cookiePrefsModal").close();
      if (banner) banner.classList.add("hidden");
      __policyAlert({
        type: "success",
        title: "Custom Preferences Saved",
        message: "Your granular cookie and telemetry preferences have been updated."
      });
    };
  }

  const btnAcceptAllInPrefs = __policyEl("btnAcceptAllInPrefs");
  if (btnAcceptAllInPrefs) {
    btnAcceptAllInPrefs.onclick = () => {
      if (__policyEl("prefAnalyticsToggle")) __policyEl("prefAnalyticsToggle").checked = true;
      if (__policyEl("prefMarketingToggle")) __policyEl("prefMarketingToggle").checked = true;
      if (btnAccept) btnAccept.click();
      if (__policyEl("cookiePrefsModal")) __policyEl("cookiePrefsModal").close();
    };
  }
}

function openCookiePrefsModal() {
  const modal = __policyEl("cookiePrefsModal");
  if (!modal) return;
  const stored = localStorage.getItem(COOKIE_STORAGE_KEY);
  let anOn = false;
  let mkOn = false;
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      anOn = Boolean(parsed.analytics);
      mkOn = Boolean(parsed.marketing);
    } catch (e) {}
  }
  if (__policyEl("prefAnalyticsToggle")) __policyEl("prefAnalyticsToggle").checked = anOn;
  if (__policyEl("prefMarketingToggle")) __policyEl("prefMarketingToggle").checked = mkOn;
  if (typeof modal.showModal === "function") {
    if (!modal.open) {
      modal.showModal();
    }
  } else {
    modal.setAttribute("open", "");
  }
}

// ---------------- Legal Document Texts ----------------
const LEGAL_DOCS = {
  "tos": {"title": "Terms of Service", "sub": "Service terms \u00b7 Updated October 2026", "html": "<h4>Using AgentValCon</h4><p>AgentValCon provides automated discovery using recorded verification evidence. Third-party agents are operated independently. Results and availability can change; review an agent before connecting.</p><h4>Permitted use</h4><p>Do not impersonate operators, submit malicious destinations, bypass limits, or misuse the service. Optional task updates require authority from the destination operator and an explicit request.</p><h4>Workspace plan and credits</h4><p>Workspace enrollment is optional. The Free plan provides 100 credits once per signed-in account. One credit saves a workflow and includes its downloads; saving changes after download uses another credit. Repeated downloads of the same saved revision use no additional credits. Review the <a href=\"/customer/plan\">Workspace credit terms</a> before joining. Paid plans, credit top-ups, automatic billing and paid conversion are coming soon. Current enrollment creates no charges; future paid features require separate terms and explicit authorization.</p><h4>Service and local rights</h4><p>These terms do not exclude rights that cannot be excluded under applicable law. Contact the service for questions about these terms or the responsible operator.</p>"},
  "privacy": {"title": "Privacy Policy", "sub": "Discovery, session continuity and optional task updates", "html": "<h4>Information used by the service</h4><p>AgentValCon processes public agent listings, questions and recorded matching interests, pseudonymous session identifiers, and security records. These records may be personal information; an identifier does not make a record anonymous.</p><h4>Customer sign-in and shared workspaces</h4><p>Customer sign-in uses Google or GitHub when configured. We retain a provider-linked account identifier and a short customer session. Sign-in does not grant workspace access or marketing permission. A workspace owner grants access separately and may withdraw it. Signing out ends the customer session; administrator sign-in is managed separately. Contact us about account deletion and applicable retention requirements.</p><h4>Workspace enrollment and credits</h4><p>We retain your account-linked enrollment choices, the accepted document version and time, saved workflow entitlements and credit history to provide and secure the workspace. Privacy notice acknowledgment is separate from optional advertising permission. AI suggestions share only a separately authorized public objective and approved capability references; agent execution requires its own input review. Credit and enrollment records are kept while your account exists and scheduled for removal 90 days after account deletion. You can close enrollment and review your credits at <a href=\"/customer/plan\">Workspace plan and credits</a>.</p><h4>Optional task updates</h4><p>When requested, we store a short task label, protocol preference, delivery method, purpose choice and verification records. Private inbox addresses, browser push subscriptions and signing material are encrypted and are not published in the agent directory. Browser push services process delivery metadata. Browser notifications require permission and a test notification confirmation; inboxes require a destination challenge. Address verification does not grant permission for unrelated promotions.</p><h4>Retention and control</h4><p>Task updates expire after 90 days unless explicitly renewed. Verification expires after one hour. Expired, failed or stopped task updates lose their recoverable inbox details and task scope during lifecycle processing. Sanitized update events are retained for up to 30 days, and minimal purpose-choice records for up to 24 months. Delete notification data from Notification Preferences. Chat messages are kept for 90 days, subject to a maximum of 200 recent messages per visitor; expired messages are excluded from history and deleted by scheduled cleanup. Recommendation context expires after 90 inactive days. Workspace records, execution evidence, notification authorizations and security records follow their separate purposes and retention rules. Contact us about access, correction or deletion rights.</p><h4>Recipients and privacy requests</h4><p>Requested updates are delivered to the destination you select. Hosting and service providers may process service data. Contact contact@agentconcierge.biz for information about the responsible operator, recipients, processing locations, applicable transfer arrangements or privacy rights. Marketing permission is an optional, separate choice for a verified destination and can be withdrawn independently. This release records that permission for administrator review; marketing message delivery is not enabled.</p>"},
  "ccpa": {"title": "Your Privacy Choices", "sub": "Privacy controls and applicable regional rights", "html": "<h4>Browser choices</h4><p>Cookie Preferences controls optional analytics in this browser. Global Privacy Control disables non-essential telemetry. Applicable sale or sharing opt-out requests are separate from notification choices and deletion requests.</p><h4>Do Not Sell or Share My Personal Information</h4><p>Use the control below to record an opt-out request and disable optional analytics in this browser. A browser preference is not a permanent cross-device setting.</p><button type=\"button\" class=\"btn primary\" id=\"btnConfirmCcpaOptOut\" data-ac-click=\"dcd4792c722d\">Confirm privacy opt-out</button><div id=\"ccpaOptOutStatus\" role=\"status\"></div><h4>Other requests</h4><p>Contact contact@agentconcierge.biz for applicable access, correction, deletion or opt-out requests. Use Notification Preferences to manage requested task updates independently.</p>"},
  "accessibility": {"title": "Accessibility Statement", "sub": "Accessible interaction and feedback", "html": "<h4>Our approach</h4><p>We aim to make agent discovery usable with keyboards and assistive technology, with clear labels, visible focus, responsive layouts, light and dark themes, and reduced-motion support.</p><h4>Report a barrier</h4><p>Contact contact@agentconcierge.biz with the page and interaction affected. Avoid sending credentials or personal information. This statement is not an accessibility certification or a guarantee that every third-party agent is accessible.</p>"},
  "ai": {"title": "Automated Service Disclosure", "sub": "Recorded evidence and third-party services", "html": "<h4>Recommendations</h4><p>AgentValCon uses recorded verification evidence to recommend up to three relevant agents for your task. You may choose A2A, MCP or x402. Results reflect the latest available checks and may change.</p><h4>Your choice</h4><p>A recommendation does not execute the agent. Review its official connection information before use. Listing descriptions are third-party information, not instructions. Requested task updates are optional.</p>"},
  "cancellation": {"title": "Notification Preferences", "sub": "Requested task updates", "html": "<p>Manage only the tasks you chose to watch. Stopping updates does not require an account or a reason. Removing notification data does not delete unrelated conversation records. You can withdraw separate marketing permission without stopping task updates.</p><div id=\"taskPreferences\" aria-live=\"polite\"></div>"},
  contact: {
    title: "Contact",
    sub: "Questions, support and reports by email",
    html: `
      <h4>Contact us by email</h4>
      <p>Email <a href="mailto:contact@agentconcierge.biz">contact@agentconcierge.biz</a> for questions, technical support, partnerships, and security or abuse reports.</p>
      <p>This site does not collect names, addresses or contact details through forms, so there is nothing to fill in here. For a security report, start the subject with "Security".</p>
      <p><a class="btn primary" href="mailto:contact@agentconcierge.biz">Email contact@agentconcierge.biz</a></p>
    `
  }
};

function openLegalModal(docType = "tos") {
  const modal = __policyEl("legalModal");
  if (!modal) return;
  const safeDoc = VALID_LEGAL_DOCS.has(docType) ? docType : "tos";
  switchLegalDoc(safeDoc);
  if (typeof modal.showModal === "function") {
    if (!modal.open) {
      modal.showModal();
    }
  } else {
    modal.setAttribute("open", "");
  }
  if (location.hash !== "#" + safeDoc) {
    history.replaceState(null, "", "#" + safeDoc);
  }
  setTimeout(() => {
    const activeTab = document.querySelector("#legalModalTabs .legal-tab-btn.active");
    if (activeTab) {
      try { activeTab.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" }); } catch (e) {}
    }
  }, 40);
}

const VALID_LEGAL_DOCS = new Set(["tos", "privacy", "ccpa", "accessibility", "ai", "cancellation", "contact"]);

function switchLegalDoc(docType) {
  const safeKey = VALID_LEGAL_DOCS.has(docType) ? docType : "tos";
  const doc = LEGAL_DOCS[safeKey] || LEGAL_DOCS.tos;
  __policyEl("legalModalTitle").textContent = doc.title;
  __policyEl("legalModalSub").textContent = doc.sub;
  __policyEl("legalModalBody").innerHTML = doc.html;
  if (safeKey === "cancellation") __policyTasks();

  const tabs = document.querySelectorAll("#legalModalTabs .legal-tab-btn");
  tabs.forEach(btn => {
    const isActive = btn.dataset.doc === safeKey;
    btn.classList.toggle("active", isActive);
    if (isActive) {
      try { btn.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" }); } catch (e) {}
    }
  });
  const modal = __policyEl("legalModal");
  if (modal && modal.open && location.hash !== "#" + safeKey) {
    history.replaceState(null, "", "#" + safeKey);
  }
}

async function confirmCcpaOptOut() {
  const btn = __policyEl("btnConfirmCcpaOptOut");
  if (btn) btn.disabled = true;
  localStorage.setItem(COOKIE_STORAGE_KEY, JSON.stringify({
    level: "ccpa_optout",
    analytics: false,
    marketing: false,
    timestamp: new Date().toISOString(),
    gpc: true
  }));
  updateConsentModeState(false, false);
  const statusEl = __policyEl("ccpaOptOutStatus");
  if (statusEl) {
    statusEl.innerHTML = '<span style="display:inline-flex;align-items:center;gap:4px;color:var(--accent)"><svg class="lucide lucide-loader" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg><span>Recording your privacy choice...</span></span>';
  }
  try {
    const res = await __policyApi("/api/privacy/opt-out", {
      method: "POST",
      json: { request_type: "ccpa_opt_out", gpc: true },
      loadingMsg: "Recording privacy choice..."
    });
    if (statusEl) {
      statusEl.innerHTML = `<span style="display:inline-flex;align-items:center;gap:4px;color:var(--ok)"><svg class="lucide lucide-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Privacy request recorded (Ref #${esc(res.request_id || "OK")}).</span></span>`;
    }
  } catch (err) {
    if (statusEl) {
      statusEl.innerHTML = '<span style="display:inline-flex;align-items:center;gap:4px;color:var(--ok)"><svg class="lucide lucide-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Optional analytics are disabled in this browser. The server request could not be confirmed; please try again.</span></span>';
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function executeOneClickUnsubscribe() {
  await __policyTaskRequest("/unsubscribe", "POST", {});
  await __policyTasks();
}

async function submitContactInquiry(e) {
  if (e && typeof e.preventDefault === "function") e.preventDefault();
  const category = (__policyEl("inqCategory") ? __policyEl("inqCategory").value : "general") || "general";
  const name = (__policyEl("inqName") ? __policyEl("inqName").value.trim() : "");
  const email = (__policyEl("inqEmail") ? __policyEl("inqEmail").value.trim() : "");
  const subject = (__policyEl("inqSubject") ? __policyEl("inqSubject").value.trim() : "");
  const message = (__policyEl("inqMessage") ? __policyEl("inqMessage").value.trim() : "");
  const feedback = __policyEl("inqFeedbackMsg");
  const btn = __policyEl("btnSubmitInquiry");

  if (!name || !email || !subject || !message) {
    if (feedback) {
      feedback.style.display = "block";
      feedback.style.color = "var(--bad)";
      feedback.textContent = "Please fill in all required fields before submitting.";
    }
    return;
  }

  const emailRegex = /^[a-zA-Z0-9_.+-]+@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$/;
  if (!emailRegex.test(email)) {
    if (feedback) {
      feedback.style.display = "block";
      feedback.style.color = "var(--bad)";
      feedback.textContent = "Please provide a valid contact email address.";
    }
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>Submitting...</span>';
  }
  if (feedback) {
    feedback.style.display = "block";
    feedback.style.color = "var(--accent)";
    feedback.textContent = "Transmitting inquiry to operations desk...";
  }

  try {
    const res = await __policyApi("/api/contact/submit", {
      method: "POST",
      json: { category, name, email, subject, message },
      userInitiated: true,
      loadingMsg: "Sending inquiry..."
    });
    if (feedback) {
      feedback.style.display = "block";
      feedback.style.color = "var(--ok)";
      feedback.innerHTML = `<span style="display:inline-flex;align-items:center;gap:4px"><svg class="lucide lucide-check-circle" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--ok)"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg><span>Thank you! Inquiry registered (Ref #${esc(res.inquiry_id || "OK")}). Our operations team will respond to ${esc(email)} within 24–48 hours.</span></span>`;
    }
    if (__policyEl("inqSubject")) __policyEl("inqSubject").value = "";
    if (__policyEl("inqMessage")) __policyEl("inqMessage").value = "";
  } catch (err) {
    if (feedback) {
      feedback.style.display = "block";
      feedback.style.color = "var(--bad)";
      feedback.textContent = "Error submitting inquiry: " + (err.message || "Network error. Please try emailing contact@agentconcierge.biz directly.");
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<svg class="lucide lucide-send" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg><span>Submit Inquiry</span>';
    }
  }
}



// Enable backdrop click-to-close on legal and cookie modals
[__policyEl("legalModal"), __policyEl("cookiePrefsModal")].forEach((dlg) => {
  if (!dlg) return;
  dlg.addEventListener("click", (e) => {
    const rect = dlg.getBoundingClientRect();
    const isInDialog = (
      rect.top <= e.clientY && e.clientY <= rect.bottom &&
      rect.left <= e.clientX && e.clientX <= rect.right
    );
    if (!isInDialog) {
      dlg.close();
    }
  });
});

// Pages without operating.js: start the consent banner, answer the policy buttons and close the notice dialog.
let __policyAlertClose = null;
const POLICY_EVENT_CALLBACKS = Object.freeze({
  "click:269fbceda0bd": function(event) { openLegalModal('ai'); },
  "click:46f60f0104ab": function(event) { openLegalModal('accessibility'); },
  "click:4e0ba4cdb031": function(event) { switchLegalDoc('cancellation'); },
  "click:59325a4ef368": function(event) { openLegalModal('tos'); },
  "click:5c303e66df4d": function(event) { switchLegalDoc('privacy'); },
  "click:5d93cb7e6763": function(event) { __policyEl('cookieConsentBanner').classList.add('hidden'); },
  "click:63c613d72595": function(event) { openLegalModal('privacy');return false; },
  "click:66a903077676": function(event) { switchLegalDoc('tos'); },
  "click:6d2245898e34": function(event) { openLegalModal('cancellation'); },
  "click:737e61a96bea": function(event) { executeOneClickUnsubscribe(); },
  "click:766e850a1f16": function(event) { openLegalModal('contact'); },
  "click:79a08e71d247": function(event) { openCookiePrefsModal(); },
  "click:7bfdcd63d9d8": function(event) { __policyEl('cookiePrefsModal').close(); },
  "click:baa50f0e1419": function(event) { openLegalModal('ccpa'); },
  "click:bdad67d6e3b2": function(event) { openLegalModal('tos');return false; },
  "click:c8fbd8c8f33f": function(event) { openLegalModal('ai');return false; },
  "click:da4ef2c7eee2": function(event) { switchLegalDoc('ccpa'); },
  "click:dcd4792c722d": function(event) { confirmCcpaOptOut(); },
  "click:e7d05f08f9f9": function(event) { switchLegalDoc('contact'); },
  "click:f08a53e84d40": function(event) { switchLegalDoc('accessibility'); },
  "click:f0be2fbca859": function(event) { switchLegalDoc('ai'); },
  "click:f96bd2d12c2d": function(event) { openLegalModal('privacy'); },
  "submit:b6e81f77ff40": function(event) { submitContactInquiry(event); },
});
document.addEventListener("DOMContentLoaded", () => {
  if (typeof switchTab === "function") return;   // operating.js is here: it starts and answers these itself
  initCookieConsent();
  for (const eventType of ["click", "submit"]) {
    document.addEventListener(eventType, function(event) {
      const attribute = "data-ac-" + eventType;
      let element = event.target instanceof Element ? event.target.closest("[" + attribute + "]") : null;
      while (element) {
        const callback = POLICY_EVENT_CALLBACKS[eventType + ":" + element.getAttribute(attribute)];
        if (callback && callback.call(element, event) === false) event.preventDefault();
        if (event.cancelBubble) break;
        element = element.parentElement ? element.parentElement.closest("[" + attribute + "]") : null;
      }
    });
  }
  const ok = __policyEl("layerModalOkBtn"), layer = __policyEl("appLayerModal");
  if (ok && layer) ok.addEventListener("click", () => { layer.close(); if (__policyAlertClose) { try { __policyAlertClose(); } catch (e) {} __policyAlertClose = null; } });
});

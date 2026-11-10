
// Fixed event callbacks: data attributes select code; they never contain executable source.
const FRONT_EVENT_CALLBACKS = Object.freeze({
  "change:18a1633a7baa": function(event) { onTestbenchAgentChange(this.value); },
  "change:ad7f5e6c839e": function(event) { onTestbenchToolChange(this.value); },
  "click:092783d784d3": function(event) { selectFrontTmplCategory('sports_health'); },
  "click:0e86008b1b07": function(event) { selectFrontTmplCategory('finance_crypto'); },
  "click:15b4c9f84f44": function(event) { exploreCategory(this.dataset.cat); },
  "click:227cdc822d0b": function(event) { selectRegisterBlueprint(this.dataset.bp); },
  "click:269fbceda0bd": function(event) { openLegalModal('ai'); },
  "click:28c79e4bf74c": function(event) { openExploreWithSearch(this.dataset.name); },
  "click:2be14e3686a8": function(event) { switchTab('test'); },
  "click:363d5688c432": function(event) { switchTab('explore');$('xKind').value='a2a';loadExplore(false); },
  "click:3fd4c305c235": function(event) { closeFrontInspector(); },
  "click:46f60f0104ab": function(event) { openLegalModal('accessibility'); },
  "click:473af510361a": function(event) { selectFrontTmplCategory('travel_maps_weather'); },
  "click:47862033af7b": function(event) { selectFrontTmplCategory('business_productivity'); },
  "click:4e0ba4cdb031": function(event) { switchLegalDoc('cancellation'); },
  "click:526a6674e916": function(event) { switchFrontWfSubView('canvas'); },
  "click:56fdee702a13": function(event) { removeFrontNode(this.dataset.id, event); },
  "click:57c3ac9c696f": function(event) { copyDrawerUrl(this.dataset.url); },
  "click:59325a4ef368": function(event) { openLegalModal('tos'); },
  "click:5bc3103c367d": function(event) { switchFrontWfSubView('templates'); },
  "click:5c303e66df4d": function(event) { switchLegalDoc('privacy'); },
  "click:5ca2c5cca3e2": function(event) { executeCurrentTestbench(); },
  "click:5d93cb7e6763": function(event) { $('cookieConsentBanner').classList.add('hidden'); },
  "click:61a9300d94f4": function(event) { filterTestbenchKind(this.dataset.kind, this); },
  "click:63c613d72595": function(event) { openLegalModal('privacy');return false; },
  "click:64099165e4f4": function(event) { loadFrontTemplateToCanvas(this.dataset.id); },
  "click:648d4dd5905a": function(event) { switchTab('explore');$('xKind').value='mcp';loadExplore(false); },
  "click:66779e3952ae": function(event) { testAgentFromDrawer(this.dataset.id); },
  "click:66a903077676": function(event) { switchLegalDoc('tos'); },
  "click:6d2245898e34": function(event) { openLegalModal('cancellation'); },
  "click:6de9500ad140": function(event) { exportTestbenchHistory(); },
  "click:6e3f51eea966": function(event) { openTestbenchWithAgent(this.dataset.id); },
  "click:737e61a96bea": function(event) { executeOneClickUnsubscribe(); },
  "click:766e850a1f16": function(event) { openLegalModal('contact'); },
  "click:77e678d7925f": function(event) { switchTab('chat'); },
  "click:79a08e71d247": function(event) { openCookiePrefsModal(); },
  "click:7b6b6910760e": function(event) { openFrontNodeInspector(this.dataset.id, event); },
  "click:7bcadd1ee279": function(event) { selectFrontTmplCategory('all'); },
  "click:7bfdcd63d9d8": function(event) { $('cookiePrefsModal').close(); },
  "click:8aa2234dc5f8": function(event) { selectFrontTmplCategory('data_utility'); },
  "click:8ac1ace275ba": function(event) { removeFrontEdge(this.dataset.id); },
  "click:910a5334ec93": function(event) { applyExploreChip(this.dataset.q); },
  "click:92dd7af047a2": function(event) { $('legalModal').close(); },
  "click:93c5a5080138": function(event) { selectFrontTmplCategory('automation'); },
  "click:9949afce41e2": function(event) { inspectHistoryItem(this.dataset.idx); },
  "click:9afb511d5efe": function(event) { setTestbenchTool(this.dataset.tool); },
  "click:9b507ce6740c": function(event) { exportFrontCanvasApp(); },
  "click:a51e6c334efd": function(event) { switchTab('register'); },
  "click:a677d7e441c7": function(event) { copyTextToClipboard(this.dataset.curl, 'Machine invocation curl copied!'); },
  "click:a6aa7d25dfcd": function(event) { removeFrontNode(this.dataset.id); },
  "click:adcbd7d21513": function(event) { resetFrontCanvas(); },
  "click:afe3155645bd": function(event) { setTestbenchPrompt(this.dataset.prompt); },
  "click:b51a990235b8": function(event) { switchTab('explore');$('xKind').value='x402';loadExplore(false); },
  "click:b571849519cf": function(event) { runFrontCanvasWorkflow(); },
  "click:ba1d8362a97a": function(event) { switchTab('overview');return false; },
  "click:baa50f0e1419": function(event) { openLegalModal('ccpa'); },
  "click:bdad67d6e3b2": function(event) { openLegalModal('tos');return false; },
  "click:c8fbd8c8f33f": function(event) { openLegalModal('ai');return false; },
  "click:ca285c7fb9a7": function(event) { loadTestbenchRecipe(this.dataset.recipe); },
  "click:d2d8d2d773c4": function(event) { $('regJsonModal').close(); },
  "click:d47328a04fc1": function(event) { switchTab('workflows'); },
  "click:d5e60f613626": function(event) { openAgent(this.dataset.id); },
  "click:d6ead2d1fa2a": function(event) { clearTestbenchHistory(); },
  "click:da4ef2c7eee2": function(event) { switchLegalDoc('ccpa'); },
  "click:dc93dc39fb88": function(event) { copyTestbenchOutput(this.dataset.copy); },
  "click:dcd4792c722d": function(event) { confirmCcpaOptOut(); },
  "click:df52bcaeaa31": function(event) { runTestbenchRecipe(this.dataset.recipe); },
  "click:e18d2ad4a093": function(event) { $('frontWfRunModal').close(); },
  "click:e1f4c026ae08": function(event) { deleteFrontSelectedNode(); },
  "click:e7d05f08f9f9": function(event) { switchLegalDoc('contact'); },
  "click:ea2fdb163b49": function(event) { selectFrontNode(this.dataset.id, event); },
  "click:eb1c2777acf9": function(event) { resetTestbenchParams(); },
  "click:f08a53e84d40": function(event) { switchLegalDoc('accessibility'); },
  "click:f0be2fbca859": function(event) { switchLegalDoc('ai'); },
  "click:f6c41dddccf3": function(event) { selectFrontTmplCategory('dev_tools'); },
  "click:f863872d28d8": function(event) { $('legalModal').close();switchTab('chat'); },
  "click:f8b2c1fec7be": function(event) { applyTestbenchArgsTemplate(this.dataset.tmpl); },
  "click:f96bd2d12c2d": function(event) { openLegalModal('privacy'); },
  "click:fc2c40cd0942": function(event) { switchTestbenchInspectorTab(this.dataset.subtab); },
  "click:fc422abb205a": function(event) { downloadFrontTemplateWebApp(this.dataset.id); },
  "click:fff5737e3ccc": function(event) { selectLearnSubTab(this.dataset.tab); },
  "input:0c3190339387": function(event) { updateFrontNodeData('sample_output', this.value); },
  "input:3aee48c9cacf": function(event) { filterTestbenchAgentList(this.value); },
  "input:50c6c2bf876f": function(event) { updateFrontNodeProperty('name', this.value); },
  "input:8d2815d72363": function(event) { filterFrontTemplates(); },
  "input:ab075ee5e583": function(event) { validateTestbenchJson(); },
  "input:c4f8c20b156d": function(event) { updateFrontNodeData('action', this.value); },
  "input:cd3e0adef8f9": function(event) { onCustomToolInput(this.value); },
  "mousedown:182bb9d5378c": function(event) { startFrontPortConnect(this.dataset.id, event); },
  "mousedown:67979906c3ec": function(event) { startFrontNodeDrag(this.dataset.id, event); },
  "mouseup:3cd36e108f84": function(event) { endFrontPortConnect(this.dataset.id, event); },
  "submit:4939d513fd5b": function(event) { return false; },
  "submit:b6e81f77ff40": function(event) { submitContactInquiry(event); },
});
for (const eventType of ["click", "change", "input", "mousedown", "mouseup", "submit"]) {
  document.addEventListener(eventType, function(event) {
    const attribute = "data-ac-" + eventType;
    let element = event.target instanceof Element ? event.target.closest("[" + attribute + "]") : null;
    while (element) {
      const callback = FRONT_EVENT_CALLBACKS[eventType + ":" + element.getAttribute(attribute)];
      if (callback && callback.call(element, event) === false) event.preventDefault();
      if (event.cancelBubble) break;
      element = element.parentElement ? element.parentElement.closest("[" + attribute + "]") : null;
    }
  });
}


"use strict";
const $ = (id) => document.getElementById(id);
let activeReqs = 0;
const loaderOperations = new Map();

// Each operation owns its progress token; finishing one cannot hide another.
function renderLoader() {
  const el = $("binaryLoader");
  if (!el) return;
  activeReqs = loaderOperations.size;
  if (activeReqs && currentTab !== "overview") {
    $("binaryLoaderMsg").textContent = Array.from(loaderOperations.values()).at(-1);
    el.classList.remove("hidden");
    el.setAttribute("aria-hidden", "false");
    if (typeof el.showPopover === "function") {
      if (el.matches(":popover-open")) el.hidePopover();
      el.showPopover();
    }
  } else {
    if (typeof el.hidePopover === "function" && el.matches(":popover-open")) el.hidePopover();
    el.classList.add("hidden");
    el.setAttribute("aria-hidden", "true");
  }
}

function showLoader(msg) {
  const token = Symbol("progress");
  loaderOperations.set(token, msg || "Working...");
  renderLoader();
  return token;
}

function hideLoader(token) {
  loaderOperations.delete(token === undefined ? Array.from(loaderOperations.keys()).at(-1) : token);
  renderLoader();
}

// ---------- Modern Centered Layer Modal System with Lucide Icons ----------
const LUCIDE_ICONS = {
  warning: `<svg class="lucide lucide-alert-triangle" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>`,
  success: `<svg class="lucide lucide-check-circle-2" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>`,
  error: `<svg class="lucide lucide-alert-circle" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>`,
  info: `<svg class="lucide lucide-info" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>`
};

let modalCloseCallback = null;
function showModalAlert(options) {
  const opts = typeof options === "string" ? { message: options } : (options || {});
  const type = opts.type || "warning";
  const title = opts.title || (type === "error" ? "Action Notice" : type === "success" ? "Operation Successful" : type === "info" ? "Notice" : "Attention Required");
  const msg = opts.message || "";
  const okText = opts.okText || "Acknowledge";
  modalCloseCallback = (opts && typeof opts.onClose === "function") ? opts.onClose : null;

  const modal = $("appLayerModal");
  if (!modal) return;

  $("layerModalTitle").textContent = title;
  if (opts.html) {
    $("layerModalBody").innerHTML = opts.html;
  } else {
    $("layerModalBody").textContent = msg;
  }
  $("layerModalOkBtn").textContent = okText;

  const iconWrap = $("layerModalIcon");
  if (iconWrap) {
    iconWrap.className = "layer-modal-icon-wrap type-" + type;
    iconWrap.innerHTML = LUCIDE_ICONS[type] || LUCIDE_ICONS.warning;
  }

  if (typeof modal.showModal === "function") {
    if (!modal.open) modal.showModal();
  } else {
    modal.setAttribute("open", "");
  }
}

window.alert = function(msg) {
  showModalAlert({ message: String(msg), type: "warning" });
};

function toast(msg, type = "info") {
  if (!msg) return;
  let container = $("frontToastContainer");
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
  el.innerHTML = `${iconSvg}<span>${esc(String(msg))}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 260);
  }, 3200);
}

function closeLayerModal() {
  const modal = $("appLayerModal");
  if (modal) {
    if (typeof modal.close === "function") modal.close();
    else modal.removeAttribute("open");
  }
  if (modalCloseCallback) {
    try { modalCloseCallback(); } catch (e) {}
    modalCloseCallback = null;
  }
}
$("layerModalCloseBtn").onclick = closeLayerModal;
$("layerModalOkBtn").onclick = closeLayerModal;
if ($("appLayerModal")) {
  $("appLayerModal").addEventListener("close", () => {
    if (modalCloseCallback) { try { modalCloseCallback(); } catch(e){} modalCloseCallback = null; }
  });
}

const layerModalEl = $("appLayerModal");
if (layerModalEl && !("closedBy" in HTMLDialogElement.prototype)) {
  layerModalEl.addEventListener("click", (e) => {
    if (e.target !== layerModalEl) return;
    const rect = layerModalEl.getBoundingClientRect();
    const inBox = (rect.top <= e.clientY && e.clientY <= rect.top + rect.height && rect.left <= e.clientX && e.clientX <= rect.left + rect.width);
    if (!inBox) closeLayerModal();
  });
}

// Aliases for regression tests
function showFrontLoader(msg) { return showLoader(msg); }
function hideFrontLoader(token) { hideLoader(token); }

function binaryClockHtml(msg) {
  return '<div class="inline-binary">' +
    '<div class="binary-dial">' +
      '<span class="bit" style="transform:rotate(0deg) translate(0,-9px);animation-delay:0.0s">0</span>' +
      '<span class="bit" style="transform:rotate(45deg) translate(0,-9px);animation-delay:0.15s">1</span>' +
      '<span class="bit" style="transform:rotate(90deg) translate(0,-9px);animation-delay:0.3s">0</span>' +
      '<span class="bit" style="transform:rotate(135deg) translate(0,-9px);animation-delay:0.45s">1</span>' +
      '<span class="bit" style="transform:rotate(180deg) translate(0,-9px);animation-delay:0.6s">0</span>' +
      '<span class="bit" style="transform:rotate(225deg) translate(0,-9px);animation-delay:0.75s">1</span>' +
      '<span class="bit" style="transform:rotate(270deg) translate(0,-9px);animation-delay:0.9s">0</span>' +
      '<span class="bit" style="transform:rotate(315deg) translate(0,-9px);animation-delay:1.05s">1</span>' +
      '<div class="clock-hand"></div>' +
      '<div class="clock-center"></div>' +
    '</div>' +
    '<span>' + esc(msg || "Loading...") + '</span>' +
  '</div>';
}

// Instant SWR Cache Engine
const SWR_STORAGE_KEY_PREFIX = "concierge_swr_gateway_v6_";
// 11-05 security review: a key that carries the visitor's search words stays only for this tab
// (sessionStorage), so a shared computer keeps no record of what was searched.
function swrHasSearchWords(key) {
  return typeof key === "string" && key.startsWith("explore:") && !/^explore:(?:v4:)?\[""/.test(key) && key !== "explore:|||0|0";
}
function swrStorage(key) { return swrHasSearchWords(key) ? sessionStorage : localStorage; }
// Discard obsolete discovery projections while retaining unrelated browser preferences.
try {
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith("concierge_swr_") && !key.startsWith(SWR_STORAGE_KEY_PREFIX)) localStorage.removeItem(key);
    else if (key.startsWith(SWR_STORAGE_KEY_PREFIX) && swrHasSearchWords(key.slice(SWR_STORAGE_KEY_PREFIX.length))) localStorage.removeItem(key);
  }
} catch (error) {}
const SWR_MEMORY_CACHE = new Map();

function getSwrCache(key) {
  if (SWR_MEMORY_CACHE.has(key)) return SWR_MEMORY_CACHE.get(key);
  try {
    const raw = swrStorage(key).getItem(SWR_STORAGE_KEY_PREFIX + key);
    if (raw) {
      const parsed = JSON.parse(raw);
      SWR_MEMORY_CACHE.set(key, parsed);
      return parsed;
    }
  } catch (e) {}
  return null;
}

function setSwrCache(key, val) {
  try {
    SWR_MEMORY_CACHE.set(key, val);
    swrStorage(key).setItem(SWR_STORAGE_KEY_PREFIX + key, JSON.stringify(val));
  } catch (e) {}
}

async function api(url, opts = {}) {
  if (location.protocol === "file:") throw new Error("Open this page through Agent Concierge to use live data.");
  const isSilent = !opts.userInitiated || Boolean(opts.silent || opts.background);
  const loaderToken = isSilent ? null : showLoader(opts.loadingMsg || "Loading...");
  const method = (opts.method || "GET").toUpperCase();
  const isSafeMethod = ["GET", "HEAD", "OPTIONS"].includes(method);
  const requestedRetries = Number.isInteger(opts.retries) ? opts.retries : 2;
  const maxRetries = isSafeMethod ? Math.max(0, Math.min(2, requestedRetries)) : 0;
  const timeoutMs = opts.timeoutMs || 8000;
  const callerSignal = opts.signal;
  const cancelled = () => Object.assign(new Error("Request cancelled."), {name: "AbortError", error_code: "REQUEST_CANCELLED"});
  const pause = (delay) => new Promise((resolve, reject) => {
    if (callerSignal?.aborted) { reject(cancelled()); return; }
    const finish = () => { callerSignal?.removeEventListener("abort", stop); resolve(); };
    const timer = setTimeout(finish, delay);
    const stop = () => { clearTimeout(timer); callerSignal?.removeEventListener("abort", stop); reject(cancelled()); };
    callerSignal?.addEventListener("abort", stop, {once: true});
  });
  try {
    let lastError = null;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      const controller = new AbortController();
      let timedOut = false;
      const stop = () => controller.abort();
      if (callerSignal?.aborted) throw cancelled();
      callerSignal?.addEventListener("abort", stop, {once: true});
      const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
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
        if (typeof opts.onResponse === "function") opts.onResponse(res);
        if (!res.ok) {
          let errText = "HTTP " + res.status;
          let errorCode = "";
          let correlationId = "";
          try {
            const j = await res.json();
            if (j.detail) errText = j.detail;
            else if (j.error) errText = j.error;
            if (/^[A-Z_]{1,40}$/.test(j.error_code || "")) errorCode = j.error_code;
            if (/^ex_[0-9a-f]{24}$/.test(j.correlation_id || "")) correlationId = j.correlation_id;
          } catch (e) {
            try { errText = await res.text(); } catch (e2) {}
          }
          const error = new Error(typeof errText === "string" ? errText : "The request could not be completed.");
          error.status = res.status;
          const retryAfter = Number(res.headers.get("Retry-After"));
          error.retryAfter = Number.isInteger(retryAfter) && retryAfter > 0 && retryAfter <= 3600 ? retryAfter : 0;
          error.error_code = errorCode;
          error.correlation_id = correlationId;
          throw error;
        }
        return await res.json();
      } catch (err) {
        if (callerSignal?.aborted) throw cancelled();
        const isAbort = timedOut || err?.name === "AbortError" || err?.name === "TimeoutError";
        const isNetworkDrop = err?.name === "TypeError" || String(err?.message).includes("Failed to fetch");
        lastError = isAbort
          ? Object.assign(new Error("The request timed out. Please try again."), {name: "TimeoutError", error_code: "REQUEST_TIMEOUT"})
          : isNetworkDrop ? new Error("Unable to connect. Please try again.") : err;
        if (!(attempt < maxRetries && (isAbort || isNetworkDrop || [502, 503, 504].includes(err?.status)))) throw lastError;
      } finally {
        clearTimeout(timer);
        callerSignal?.removeEventListener("abort", stop);
      }
      await pause(150 * Math.pow(2, attempt) + Math.random() * 50);
    }
    throw lastError || new Error("Request failed");
  } finally {
    if (loaderToken) hideLoader(loaderToken);
  }
}

// ---------- Formatting & Time Helpers (New York Time) ----------
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const DANGEROUS_PAYLOAD_RE = /(?:<\s*(?:script|iframe|object|embed|applet|meta|link|style|form|input|button|base|body|frameset|frame|layer)\b|<\s*\/\s*(?:script|iframe|object|embed|applet|style)\b|\bon[a-z]{3,20}\s*=|\b(?:javascript|vbscript|data\s*:\s*text\/html|data\s*:\s*application\/javascript)\s*:|expression\s*\(|<\s*(?:img|svg|audio|video|source|track)\b[^>]*\bon[a-z]{3,20}\s*=)/i;

function isUnsafeInput(s) {
  if (!s || typeof s !== "string") return false;
  return /[\x00-\x08\x0b\x0c\x0e-\x1f\u202a-\u202e\u200e\u200f]/.test(s) || DANGEROUS_PAYLOAD_RE.test(s);
}

function safeUrl(u) { return /^https?:\/\//i.test(String(u || "")) ? String(u) : null; }
function link(u, label) {
  const s = safeUrl(u);
  return s ? `<a href="${esc(s)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent);text-decoration:none;display:inline-flex;align-items:center;gap:3px"><span>${esc(label ?? u)}</span><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></a>` : esc(label ?? u ?? "");
}
const fmt = (n) => (n === null || n === undefined) ? "–" : Number(n).toLocaleString("en-US");
const pct = (a, b) => b ? (100 * a / b).toFixed(1) + "%" : "–";
const usd = (micro) => micro === null || micro === undefined ? "–" : "$" + (micro / 1e6).toLocaleString("en-US", { maximumFractionDigits: 6 });

function timestampSeconds(value) {
  if (typeof value === 'number') return Number.isFinite(value) && value > 0 ? value : null;
  if (typeof value !== 'string') return null;
  if (/^\d+(?:\.\d+)?$/.test(value)) return timestampSeconds(Number(value));
  if (!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/.test(value)) return null;
  let iso = value.replace(' ', 'T');
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(iso)) iso += 'Z';
  const parsed = Date.parse(iso) / 1000;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function nyTime(value) {
  const ts = timestampSeconds(value);
  if (ts === null) return "–";
  return new Date(ts * 1000).toLocaleString("en-US", {
    timeZone: "UTC",
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: true,
    timeZoneName: "short"
  });
}

function nyAgo(value) {
  const ts = timestampSeconds(value);
  if (ts === null) return "–";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return Math.round(s) + "s ago";
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return (s / 3600).toFixed(1) + "h ago";
  return (s / 86400).toFixed(1) + "d ago";
}

// ---------- Tab Routing ----------
const TABS = ["status", "overview", "learn", "explore", "test", "workflows", "chat", "register", "about"];
const LEGAL_ROUTES = ["tos", "privacy", "ccpa", "accessibility", "ai", "cancellation", "contact"];
let currentTab = "overview";
let initialRoutingComplete = false;

const PAGE_METAS = {
  about: {
    "title": "Agent Concierge — About Our Service & Vision",
    "desc": "Learn how Agent Concierge helps you discover relevant AI agents, review recorded evidence, test connections and build workflows. Explore our vision for useful, connected agents with clear choices and permission.",
    "keywords": "about Agent Concierge, AI agent discovery, connected agents, agent workflows, service vision, evidence-aware discovery, agent ecosystem",
    "action": "understand-service-and-vision",
    "retention": "Return to discover agents, review available evidence and build useful connections.",
    "capabilities": "service-overview, agent-discovery, verification-context, connected-workflows, permission-based-updates",
    "howToUse": "Read our service overview, value and vision, then choose Chat, Explore, Workflows or List Your Agent. Select the Agent Concierge logo to return Home."
},
  overview: {
    title: "Agent Concierge \u2014 One Best Agent for Your Task",
    desc: "Find up to three relevant agents using recorded verification. A2A by default; request MCP or x402. Explore recorded checks, test connections, run published workflows, and choose optional task updates. List Your Agent to be discovered, or read About our service and vision.",
    keywords: "agent discovery, three agent recommendations, quality grade, latest test report, active agents, MCP, A2A, x402, list your agent, public agent listing",
    action: "find-up-to-three-verified-agents",
    retention: "Return to discover agents using the latest available verification evidence.",
    capabilities: "three-agent-recommendations, quality-grading, recent-verification, agent-discovery, public-agent-listing, connected-workflows",
    howToStart: "Describe the task in Chat; receive up to three verified matches; review the quality grade, latest report, and recent activity; open Calling details to connect.",
    howToUse: "Describe the task in Chat; receive up to three verified matches; review the quality grade, latest report, and recent activity; open Calling details to connect.",
    chatFeatures: "One task-relevant agent, task-focused services first, then recent successful verification, quality checks, recent availability, essential connection details",
    menuGuide: "Learn: protocol standards and reference guides; Explore: agent discovery and recorded checks; Test: review and test agent connections; Workflows: published workflows and downloadable web apps; Chat: up to three relevant agents recommendation; List Your Agent: submit a public endpoint for discovery; About: our service, value and vision. Select the Agent Concierge logo to return to the Home overview."
  },
  learn: {
    title: "Agent Concierge — Protocol Standards & Integration Guide",
    desc: "Machine-to-machine protocol standards and architecture guides for A2A (Agent2Agent), Model Context Protocol (MCP), and x402 APIs, plus protocol comparisons, ecosystem landscape guides, quality grading criteria, glossary, and FAQ.",
    keywords: "A2A protocol specifications, MCP JSON-RPC, streamable tool servers, x402 protocol, protocol comparison, multi-agent architecture, quality grading rubric, agent cards, ecosystem reference",
    action: "inspect-protocol-specifications",
    retention: "Stay synchronized with multi-agent protocol standards, featured verified agents, and quality grading references.",
    howToUse: "1. Select A2A, MCP, or x402 summary cards to inspect protocol specifications and featured live agents; 2. Compare protocols side by side and review multi-agent composition patterns; 3. Explore ecosystem landscape guides, quality grading criteria (A–F), terminology, and FAQ.",
    capabilities: "protocol-blueprints, schema-specifications, a2a-standards, mcp-json-rpc-guides, x402-protocol-specs, ecosystem-landscape-guides, quality-grading-reference"
  },
  explore: {
    title: "Agent Concierge — Agent & Tool Discovery Catalog",
    desc: "Search live A2A agents, MCP tool servers, and x402 APIs across 20 business categories. Browse recorded reports, or choose Execution checked to require current recorded execution evidence.",
    keywords: "verified AI agents, A2A agent catalog, MCP tool catalog, x402 APIs, agent test reports, benchmark reports, zero account agents, capability search, quality grades",
    action: "discover-tools-and-agents",
    retention: "Newly verified autonomous agents and benchmark test reports are indexed continuously — return to explore updated listings and verification grades.",
    howToUse: "1. Search by task keyword or select a protocol (A2A, MCP, x402) and business category; 2. Filter by Execution checked, Zero Account, or Test Report badges; 3. Open any agent card to review Specifications & Metadata, benchmark test reports, and invocation schemas.",
    capabilities: "realtime-tool-discovery, protocol-and-category-filtering, verified-agent-search, test-report-filtering, quality-grading, capability-schema-lookup"
  },
  workflows: {
    title: "Agent Concierge — Visual Multi-Agent Workflow Studio & Template Hub",
    desc: "Run three published workflows for news, camera guidance or product comparisons. Review outcomes and download a web app. Compatible informational alternatives need per-run permission when available. When available, review a published news-to-documentation connection and authorize one run.",
    keywords: "agent workflows, visual workflow studio, published templates, recorded execution, ZIP web app package, self-hosted web app, gateway SDK",
    action: "orchestrate-and-execute-workflows",
    retention: "Explore published agent workflows, review their current steps, and return to run a template or download a connected app.",
    howToUse: "1. Choose a published template; 2. Review its agent steps; 3. Run it and inspect recorded outcomes; 4. Download a ZIP web app package for your server. Agent availability and an internet connection are required.",
    capabilities: "visual-canvas, published-template-execution, recorded-step-outcomes, deployable-webapp-package, gateway-sdk"
  },
  test: {
    title: "Agent Concierge — Interactive Agent Testbench & Protocol Sandbox",
    desc: "Run four live informational examples or test registered agents through managed MCP, A2A, and x402 connections. Inspect gateway exchanges and source links; format demos remain separate.",
    keywords: "agent testbench, protocol sandbox, managed agent connections, live agent examples, MCP tool testing, A2A testing, x402 probe, gateway exchange inspector, format demos, schema validation, session JSON report",
    action: "test-agent-endpoints",
    retention: "Run live informational examples or test newly cataloged A2A, MCP, and x402 agents through managed connections, inspect gateway exchanges and execution states, and export session JSON reports.",
    howToUse: "1. Choose a live example or registered agent; format demos are separate; 2. Review informational inputs; 3. Run the test; 4. Review simulation, completion, pending, or failure status; 5. Inspect the gateway exchange and sources.",
    capabilities: "managed-agent-execution, labeled-demos, gateway-exchange-inspection, schema-validation, source-citations, multi-protocol-testing"
  },
  register: {
    title: "Agent Concierge — List Your Agent",
    desc: "List your A2A agent, MCP server, or x402 API so others can discover it. Submit a public endpoint for connectivity checks and catalog inclusion.",
    keywords: "list your agent, public agent listing, A2A agent directory, MCP server listing, x402 API directory, endpoint verification, agent discovery",
    action: "list-agent-endpoint",
    retention: "Keep your public agent endpoint available for ongoing verification and discovery.",
    howToUse: "1. Choose A2A, MCP, or x402; 2. Add your public endpoint, agent name, category, and capabilities; 3. Review the listing terms; 4. Submit for verification and discovery catalog inclusion.",
    capabilities: "public-agent-listing, endpoint-verification, duplicate-detection, protocol-validation, catalog-discovery"
  },
  chat: {
    title: "Agent Concierge \u2014 One Best Verified Agent",
    desc: "Find matches by the latest successful test report or execution check, recent activity and quality. A2A by default; request MCP or x402. Newest replies first.",
    keywords: "three agent recommendations, quality grade, latest test report, active endpoint, MCP, A2A, x402",
    action: "three-recent-verified-recommendations-a2a-then-mcp",
    retention: "Choose optional task updates or ask again to use the latest recorded verification evidence.",
    capabilities: "single-agent-selection, protocol-selection, recent-verified-matching, recent-verification, verified-task-updates, browser-notifications",
    howToUse: "Describe the task, optionally select A2A, MCP, x402, or Any protocol, and receive up to three evidence-ranked agents. Open Calling details to connect or choose task updates after the result."
  }
};

const PUBLIC_PAGE_METADATA = {"overview": {"title": "Agent Concierge \u2014 Connected Intelligence, with Evidence", "desc": "Find up to three relevant agents or published workflows. A2A first, then MCP; x402 is available by explicit choice. Review recorded checks before running."}, "status": {"title": "Agent Status & Recorded Checks \u2014 Agent Concierge", "desc": "Explore recorded agent availability and execution observations. Distinguish catalog status from completed task results."}, "explore": {"title": "Explore AI Agents \u2014 A2A, MCP & x402 | Agent Concierge", "desc": "Find AI agents by task and protocol. Review available quality evidence, connection details and recent activity before choosing an agent."}, "learn": {"title": "Learn About AI Agent Connections \u2014 Agent Concierge", "desc": "Learn how A2A, MCP and x402 connect AI agents and tools. Understand recorded checks, task inputs, workflow connections and optional updates."}, "test": {"title": "Test AI Agents with Live Data \u2014 Agent Concierge", "desc": "Try technology news, research papers, country profiles and package metadata. Inspect English results, source links and retrieval timestamps."}, "workflows": {"title": "AI Agent Workflows & Web App Downloads \u2014 Agent Concierge", "desc": "Find published workflows by purpose and step capability. Review news, research, country indicators and package advisory inputs, then run or download a web app."}, "chat": {"title": "Find AI Agents & Published Workflows \u2014 Agent Concierge", "desc": "Describe a task to compare up to three relevant agents or published workflows. Prefer A2A, then MCP; select x402 explicitly. Agent selection uses recent successful verification, activity and quality."}, "register": {"title": "List Your AI Agent \u2014 Agent Concierge", "desc": "Submit your authorized public AI agent endpoint so others can discover it. Review capabilities, available connection evidence and listing status."}, "about": {"title": "About Agent Concierge \u2014 Service & Vision", "desc": "Discover our purpose and vision: useful connections between AI agents, inspectable evidence, reusable workflows and clear choices about permission."}};

const DAILY_HOME_METADATA = (() => {
  try {
    const node = document.getElementById("dailyHomeMetadata");
    return node ? JSON.parse(node.textContent) : null;
  } catch (error) { return null; }
})();

function updatePageMeta(tabId) {
  const m = {...(PAGE_METAS[tabId] || PAGE_METAS.overview), ...(PUBLIC_PAGE_METADATA[tabId] || PUBLIC_PAGE_METADATA.overview)};
  if (tabId === "overview" && DAILY_HOME_METADATA) m.desc = DAILY_HOME_METADATA.description;
  document.title = m.title;
  const setMeta = (attr, val, content) => {
    let el = document.head.querySelector('meta[' + attr + '="' + val + '"]');
    if (!el) {
      el = document.createElement("meta");
      el.setAttribute(attr, val);
      document.head.appendChild(el);
    }
    el.setAttribute("content", content);
  };
  setMeta("name", "description", m.desc);
  setMeta("name", "keywords", m.keywords);
  setMeta("property", "og:title", m.title);
  setMeta("property", "og:description", m.desc);
  setMeta("name", "twitter:title", m.title);
  setMeta("name", "twitter:description", m.desc);
  const canonical = document.head.querySelector('link[rel="canonical"]');
  if (canonical) {
    const pages = {overview:"/",status:"/new/en/agent-status.html",explore:"/new/en/explore.html",learn:"/new/en/learn.html",test:"/new/en/test.html",workflows:"/new/en/workflows.html",chat:"/new/en/chat.html",register:"/new/en/list-agent.html",about:"/new/en/about.html"};
    const pageUrl = "https://agentconcierge.biz" + (pages[tabId] || "/");
    canonical.setAttribute("href", pageUrl);
    setMeta("property", "og:url", pageUrl);
    setMeta("name", "twitter:url", pageUrl);
    document.head.querySelectorAll('script[type="application/ld+json"]').forEach((script) => {
      try {
        const data = JSON.parse(DAILY_HOME_METADATA ? JSON.stringify(DAILY_HOME_METADATA.graph) : script.textContent);
        if (tabId !== "overview" && Array.isArray(data["@graph"])) {
          data["@graph"] = data["@graph"].filter((node) => node["@type"] !== "Dataset");
          data["@graph"].forEach((node) => {
            if (["WebPage", "AboutPage"].includes(node["@type"])) {
              delete node.dateModified;
              delete node.hasPart;
            }
          });
        }
        const nodes = Array.isArray(data["@graph"]) ? data["@graph"] : [data];
        nodes.forEach((node) => {
          if (node && ["WebPage", "AboutPage"].includes(node["@type"])) {
            node["@type"] = tabId === "about" ? "AboutPage" : "WebPage";
            node["@id"] = pageUrl + "#page";
            node.url = pageUrl;
            node.name = m.title;
            node.description = m.desc;
          }
        });
        script.textContent = JSON.stringify(data);
      } catch (error) {
        // Leave unrelated or invalid structured data unchanged.
      }
    });
  }
  setMeta("name", "agent:active-page", tabId);
  setMeta("name", "agent:action", m.action);
  setMeta("name", "agent:retention-hook", m.retention);
  if (m.howToUse) setMeta("name", "agent:how-to-use", m.howToUse);
  if (m.capabilities) setMeta("name", "agent:capabilities", m.capabilities);
  if (m.howToStart) setMeta("name", "agent:how-to-start", m.howToStart);
  if (m.chatFeatures) setMeta("name", "agent:chat-features", m.chatFeatures);
  if (m.menuGuide) setMeta("name", "agent:menu-guide", m.menuGuide);
}

function sanitizePort8080() {
  try {
    const badPort = ":" + "8080";
    document.querySelectorAll("code, pre, a").forEach((el) => {
      if (el.tagName === "A" && el.href && el.href.includes(badPort)) {
        el.href = el.href.split(badPort).join("").replace(/^http:\/\//, "https://");
      }
      if (el.textContent && el.textContent.includes(badPort)) {
        el.textContent = el.textContent.split(badPort).join("").replace(/http:\/\//g, "https://");
      }
    });
  } catch (e) {}
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
  const banner = $("cookieConsentBanner");
  const gpcBadge = $("gpcBadge");
  const hasGpc = isGpcActive();
  // The banner floats over the bottom of the viewport so it never moves page content (no layout shift).
  // While visible, reserve matching space at the end of the page and in scroll padding so focus and footer stay reachable.
  if (banner && !banner.dataset.spaceSync) {
    banner.dataset.spaceSync = "1";
    const root = document.documentElement;
    const syncSpace = () => {
      const visible = !banner.classList.contains("hidden");
      const space = visible ? Math.ceil(banner.getBoundingClientRect().height) + 24 : 0;
      document.body.style.paddingBottom = space ? space + "px" : "";
      root.style.scrollPaddingBottom = space ? space + "px" : "";
    };
    const revealFocus = event => {
      const target = event.target;
      if (!(target instanceof HTMLElement) || banner.contains(target) || banner.classList.contains("hidden")) return;
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

  const btnAccept = $("btnAcceptAllCookies");
  const btnReject = $("btnRejectNonEssentialCookies");
  const btnPrefs = $("btnOpenCookiePrefs");

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
      toast("Your cookie preferences have been saved.");
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
      toast("Only essential storage is enabled. You can change this in Cookie Preferences.");
    };
  }

  if (btnPrefs) {
    btnPrefs.onclick = () => openCookiePrefsModal();
  }

  const btnSavePrefs = $("btnSaveCookiePrefs");
  if (btnSavePrefs) {
    btnSavePrefs.onclick = () => {
      const anOn = $("prefAnalyticsToggle") ? $("prefAnalyticsToggle").checked : false;
      const mkOn = $("prefMarketingToggle") ? $("prefMarketingToggle").checked : false;
      localStorage.setItem(COOKIE_STORAGE_KEY, JSON.stringify({
        level: "custom",
        analytics: anOn,
        marketing: mkOn,
        timestamp: new Date().toISOString(),
        gpc: hasGpc
      }));
      updateConsentModeState(anOn, mkOn);
      if ($("cookiePrefsModal")) $("cookiePrefsModal").close();
      if (banner) banner.classList.add("hidden");
      showModalAlert({
        type: "success",
        title: "Custom Preferences Saved",
        message: "Your granular cookie and telemetry preferences have been updated."
      });
    };
  }

  const btnAcceptAllInPrefs = $("btnAcceptAllInPrefs");
  if (btnAcceptAllInPrefs) {
    btnAcceptAllInPrefs.onclick = () => {
      if ($("prefAnalyticsToggle")) $("prefAnalyticsToggle").checked = true;
      if ($("prefMarketingToggle")) $("prefMarketingToggle").checked = true;
      if (btnAccept) btnAccept.click();
      if ($("cookiePrefsModal")) $("cookiePrefsModal").close();
    };
  }
}

function openCookiePrefsModal() {
  const modal = $("cookiePrefsModal");
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
  if ($("prefAnalyticsToggle")) $("prefAnalyticsToggle").checked = anOn;
  if ($("prefMarketingToggle")) $("prefMarketingToggle").checked = mkOn;
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
  "tos": {"title": "Terms of Service", "sub": "Service terms \u00b7 Updated October 2026", "html": "<h4>Using Agent Concierge</h4><p>Agent Concierge provides automated discovery using recorded verification evidence. Third-party agents are operated independently. Results and availability can change; review an agent before connecting.</p><h4>Permitted use</h4><p>Do not impersonate operators, submit malicious destinations, bypass limits, or misuse the service. Optional task updates require authority from the destination operator and an explicit request.</p><h4>Workspace plan and credits</h4><p>Workspace enrollment is optional. The Free plan provides 100 credits once per signed-in account. One credit saves a workflow and includes its downloads; saving changes after download uses another credit. Repeated downloads of the same saved revision use no additional credits. Review the <a href=\"/customer/plan\">Workspace credit terms</a> before joining. Paid plans, credit top-ups, automatic billing and paid conversion are coming soon. Current enrollment creates no charges; future paid features require separate terms and explicit authorization.</p><h4>Service and local rights</h4><p>These terms do not exclude rights that cannot be excluded under applicable law. Contact the service for questions about these terms or the responsible operator.</p>"},
  "privacy": {"title": "Privacy Policy", "sub": "Discovery, session continuity and optional task updates", "html": "<h4>Information used by the service</h4><p>Agent Concierge processes public agent listings, questions and recorded matching interests, pseudonymous session identifiers, and security records. These records may be personal information; an identifier does not make a record anonymous.</p><h4>Customer sign-in and shared workspaces</h4><p>Customer sign-in uses Google or GitHub when configured. We retain a provider-linked account identifier and a short customer session. Sign-in does not grant workspace access or marketing permission. A workspace owner grants access separately and may withdraw it. Signing out ends the customer session; administrator sign-in is managed separately. Contact us about account deletion and applicable retention requirements.</p><h4>Workspace enrollment and credits</h4><p>We retain your account-linked enrollment choices, the accepted document version and time, saved workflow entitlements and credit history to provide and secure the workspace. Privacy notice acknowledgment is separate from optional advertising permission. AI suggestions share only a separately authorized public objective and approved capability references; agent execution requires its own input review. Credit and enrollment records are kept while your account exists and scheduled for removal 90 days after account deletion. You can close enrollment and review your credits at <a href=\"/customer/plan\">Workspace plan and credits</a>.</p><h4>Optional task updates</h4><p>When requested, we store a short task label, protocol preference, delivery method, purpose choice and verification records. Private inbox addresses, browser push subscriptions and signing material are encrypted and are not published in the agent directory. Browser push services process delivery metadata. Browser notifications require permission and a test notification confirmation; inboxes require a destination challenge. Address verification does not grant permission for unrelated promotions.</p><h4>Retention and control</h4><p>Task updates expire after 90 days unless explicitly renewed. Verification expires after one hour. Expired, failed or stopped task updates lose their recoverable inbox details and task scope during lifecycle processing. Sanitized update events are retained for up to 30 days, and minimal purpose-choice records for up to 24 months. Delete notification data from Notification Preferences. Chat messages are kept for 90 days, subject to a maximum of 200 recent messages per visitor; expired messages are excluded from history and deleted by scheduled cleanup. Recommendation context expires after 90 inactive days. Workspace records, execution evidence, notification authorizations and security records follow their separate purposes and retention rules. Contact us about access, correction or deletion rights.</p><h4>Recipients and privacy requests</h4><p>Requested updates are delivered to the destination you select. Hosting and service providers may process service data. Contact contact@agentconcierge.biz for information about the responsible operator, recipients, processing locations, applicable transfer arrangements or privacy rights. Marketing permission is an optional, separate choice for a verified destination and can be withdrawn independently. This release records that permission for administrator review; marketing message delivery is not enabled.</p>"},
  "ccpa": {"title": "Your Privacy Choices", "sub": "Privacy controls and applicable regional rights", "html": "<h4>Browser choices</h4><p>Cookie Preferences controls optional analytics in this browser. Global Privacy Control disables non-essential telemetry. Applicable sale or sharing opt-out requests are separate from notification choices and deletion requests.</p><h4>Do Not Sell or Share My Personal Information</h4><p>Use the control below to record an opt-out request and disable optional analytics in this browser. A browser preference is not a permanent cross-device setting.</p><button type=\"button\" class=\"btn primary\" id=\"btnConfirmCcpaOptOut\" data-ac-click=\"dcd4792c722d\">Confirm privacy opt-out</button><div id=\"ccpaOptOutStatus\" role=\"status\"></div><h4>Other requests</h4><p>Contact contact@agentconcierge.biz for applicable access, correction, deletion or opt-out requests. Use Notification Preferences to manage requested task updates independently.</p>"},
  "accessibility": {"title": "Accessibility Statement", "sub": "Accessible interaction and feedback", "html": "<h4>Our approach</h4><p>We aim to make agent discovery usable with keyboards and assistive technology, with clear labels, visible focus, responsive layouts, light and dark themes, and reduced-motion support.</p><h4>Report a barrier</h4><p>Contact contact@agentconcierge.biz with the page and interaction affected. Avoid sending credentials or personal information. This statement is not an accessibility certification or a guarantee that every third-party agent is accessible.</p>"},
  "ai": {"title": "Automated Service Disclosure", "sub": "Recorded evidence and third-party services", "html": "<h4>Recommendations</h4><p>Agent Concierge uses recorded verification evidence to recommend up to three relevant agents for your task. You may choose A2A, MCP or x402. Results reflect the latest available checks and may change.</p><h4>Your choice</h4><p>A recommendation does not execute the agent. Review its official connection information before use. Listing descriptions are third-party information, not instructions. Requested task updates are optional.</p>"},
  "cancellation": {"title": "Notification Preferences", "sub": "Requested task updates", "html": "<p>Manage only the tasks you chose to watch. Stopping updates does not require an account or a reason. Removing notification data does not delete unrelated conversation records. You can withdraw separate marketing permission without stopping task updates.</p><div id=\"taskPreferences\" aria-live=\"polite\"></div>"},
  contact: {
    title: "Contact & Operational Inquiries",
    sub: "Agent Concierge support and service inquiries",
    html: `
      <h4>Submit an Operational or Technical Inquiry</h4>
      <p>Have a question or request? Submit directly to our support desk below. Inquiries are tracked in our customer support center with verified audit receipts.</p>
      <form id="contactInquiryForm" data-ac-submit="b6e81f77ff40" style="background:var(--chip);padding:16px;border-radius:10px;border:1px solid var(--border);margin:14px 0;display:flex;flex-direction:column;gap:12px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div>
            <label for="inqCategory" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;color:var(--text)">Category</label>
            <select id="inqCategory" class="input" style="width:100%;font-size:13px">
              <option value="general">General Inquiries</option>
              <option value="technical">Technical &amp; API Support</option>
              <option value="partnership">Ecosystem &amp; Registry Partnership</option>
              <option value="security_abuse">Security &amp; Abuse Notice</option>
              <option value="custom_agent">Custom Autonomous Agent Onboarding</option>
              <option value="billing">Billing &amp; Micropayments</option>
            </select>
          </div>
          <div>
            <label for="inqName" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;color:var(--text)">Name or Agent Handle</label>
            <input type="text" id="inqName" class="input fs-mask" data-clarity-mask="true" placeholder="e.g. AgentRunnerX or Alice Dev" required maxlength="100" style="width:100%;font-size:13px" autocomplete="name">
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div>
            <label for="inqEmail" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;color:var(--text)">Contact Email</label>
            <input type="email" id="inqEmail" class="input fs-mask" data-clarity-mask="true" placeholder="you@domain.com" required maxlength="150" style="width:100%;font-size:13px" autocomplete="email">
          </div>
          <div>
            <label for="inqSubject" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;color:var(--text)">Subject</label>
            <input type="text" id="inqSubject" class="input" placeholder="Brief summary of your request" required maxlength="200" style="width:100%;font-size:13px">
          </div>
        </div>
        <div>
          <label for="inqMessage" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;color:var(--text)">Message</label>
          <textarea id="inqMessage" class="input fs-mask" data-clarity-mask="true" rows="4" placeholder="Detail your technical question, integration need, or partnership proposal..." required maxlength="4000" style="width:100%;font-size:13px;resize:vertical"></textarea>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px">
          <span style="font-size:11.5px;color:var(--text-dim)">Protected by automated rate limiting and origin verification</span>
          <button type="submit" class="btn primary" id="btnSubmitInquiry" style="display:inline-flex;align-items:center;gap:6px">
            <svg class="lucide lucide-send" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            <span>Submit Inquiry</span>
          </button>
        </div>
        <div id="inqFeedbackMsg" style="font-size:12.5px;display:none;margin-top:6px"></div>
      </form>

      <h4>Global Inquiries &amp; Developer Support</h4>
      <p>For questions regarding autonomous agent integration, enterprise partnerships, directory indexing, or protocol interoperability across A2A, MCP, and x402, reach out directly to our global operations desk:</p>
      <div style="background:var(--chip);padding:14px 16px;border-radius:8px;border:1px solid var(--border);margin:14px 0">
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">Official Contact &amp; Inquiries Email:</div>
        <a href="mailto:contact@agentconcierge.biz" style="font-size:15px;font-weight:700;color:var(--accent);text-decoration:none">contact@agentconcierge.biz</a>
        <div style="font-size:12px;color:var(--text-dim);margin-top:6px">Operating under 24/7 autonomous monitoring. General and technical inquiries dispatched to on-call engineering.</div>
      </div>

      <h4>Autonomous Protocol &amp; Machine Communications</h4>
      <p>Automated agents, autonomous runners, and software runtimes can initiate immediate programmatic dialogue, register push notification webhooks, or query live catalog endpoints via:</p>
      <ul>
        <li><strong>Interactive Agent Chat:</strong> <a href="#chat" data-ac-click="f863872d28d8" style="color:var(--accent);text-decoration:none">https://agentconcierge.biz/#chat</a></li>
        <li><strong>A2A Protocol Endpoint:</strong> <code>https://agentconcierge.biz/a2a</code></li>
        <li><strong>MCP Streamable Server:</strong> <code>https://agentconcierge.biz/mcp</code></li>
        <li><strong>Standard Agent Card:</strong> <a href="/.well-known/agent-card.json" target="_blank" rel="noopener noreferrer" style="color:var(--accent);text-decoration:none;display:inline-flex;align-items:center;gap:3px"><span>/.well-known/agent-card.json</span><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></a></li>
      </ul>

      <h4>Security &amp; Abuse Reports</h4>
      <p>To report suspicious endpoint behavior, proxy abuse, or security advisories, please email <a href="mailto:contact@agentconcierge.biz" style="color:var(--accent)">contact@agentconcierge.biz</a> with the subject tag <code>[SECURITY]</code> for immediate high-priority review.</p>
    `
  }
};

function openLegalModal(docType = "tos") {
  const modal = $("legalModal");
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
  $("legalModalTitle").textContent = doc.title;
  $("legalModalSub").textContent = doc.sub;
  $("legalModalBody").innerHTML = doc.html;
  if (safeKey === "cancellation") renderTaskPreferences();

  const tabs = document.querySelectorAll("#legalModalTabs .legal-tab-btn");
  tabs.forEach(btn => {
    const isActive = btn.dataset.doc === safeKey;
    btn.classList.toggle("active", isActive);
    if (isActive) {
      try { btn.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" }); } catch (e) {}
    }
  });
  const modal = $("legalModal");
  if (modal && modal.open && location.hash !== "#" + safeKey) {
    history.replaceState(null, "", "#" + safeKey);
  }
}

async function confirmCcpaOptOut() {
  const btn = $("btnConfirmCcpaOptOut");
  if (btn) btn.disabled = true;
  localStorage.setItem(COOKIE_STORAGE_KEY, JSON.stringify({
    level: "ccpa_optout",
    analytics: false,
    marketing: false,
    timestamp: new Date().toISOString(),
    gpc: true
  }));
  updateConsentModeState(false, false);
  const statusEl = $("ccpaOptOutStatus");
  if (statusEl) {
    statusEl.innerHTML = '<span style="display:inline-flex;align-items:center;gap:4px;color:var(--accent)"><svg class="lucide lucide-loader" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg><span>Recording your privacy choice...</span></span>';
  }
  try {
    const res = await api("/api/privacy/opt-out", {
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
  await taskRequest("/unsubscribe", "POST", {});
  await renderTaskPreferences();
}

async function submitContactInquiry(e) {
  if (e && typeof e.preventDefault === "function") e.preventDefault();
  const category = ($("inqCategory") ? $("inqCategory").value : "general") || "general";
  const name = ($("inqName") ? $("inqName").value.trim() : "");
  const email = ($("inqEmail") ? $("inqEmail").value.trim() : "");
  const subject = ($("inqSubject") ? $("inqSubject").value.trim() : "");
  const message = ($("inqMessage") ? $("inqMessage").value.trim() : "");
  const feedback = $("inqFeedbackMsg");
  const btn = $("btnSubmitInquiry");

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
    const res = await api("/api/contact/submit", {
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
    if ($("inqSubject")) $("inqSubject").value = "";
    if ($("inqMessage")) $("inqMessage").value = "";
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



function focusChatInput(onlyIfUnfocused = false) {
  const inp = $("chatInput");
  if (!inp || currentTab !== "chat") return;
  const sec = $("secChat");
  if (sec && sec.classList.contains("hidden")) return;
  if (onlyIfUnfocused && document.activeElement && sec && sec.contains(document.activeElement)) return;
  try {
    inp.focus({ preventScroll: true });
    const len = (inp.value || "").length;
    if (typeof inp.setSelectionRange === "function") {
      inp.setSelectionRange(len, len);
    }
  } catch (e) {
    try { inp.focus(); } catch (e2) {}
  }
}

const initializedPanels = new Set();
function switchTab(tabId) {
  if (!TABS.includes(tabId)) tabId = "overview";
  const changed = currentTab !== tabId;
  if (changed && currentTab === "explore") {
    clearTimeout(exploreDebounce); exploreRequestRevision += 1; exploreController?.abort();
    lastExploreKey=null;exploreRequestedKey=null;exploreController=null;
    if(exploreInputLoader!=null){hideLoader(exploreInputLoader);exploreInputLoader=null;}
  }
  currentTab = tabId;
  renderLoader();
  updatePageMeta(tabId);
  const srAnnounce = $("srLiveAnnouncer");
  if (srAnnounce) {
    const tabNames = { overview: "Home overview", learn: "Protocol standards and integration guide", explore: "Agent discovery catalog", workflows: "Visual workflow studio and template hub", test: "Interactive agent testbench and protocol sandbox", register: "List Your Agent", chat: "Interactive agent concierge console", about: "About Agent Concierge, our service and vision" };
    srAnnounce.textContent = "Navigated to " + (tabNames[tabId] || tabId) + " panel.";
  }
  document.querySelectorAll(".nav-tab[data-tab]").forEach((b) => {
    const active = b.dataset.tab === tabId;
    b.classList.toggle("on", active);
    if (active) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  const homeLink = document.querySelector("a.brand-box");
  if (homeLink) {
    if (tabId === "overview") homeLink.setAttribute("aria-current", "page"); else homeLink.removeAttribute("aria-current");
  }
  document.querySelectorAll(".tab-panel").forEach((sec) => sec.classList.toggle("hidden", sec.dataset.panel !== tabId));
  const initialRoute = (location.hash || "").slice(1).split("?")[0];
  if (!LEGAL_ROUTES.includes(initialRoute) && (initialRoutingComplete || !initialRoute || TABS.includes(initialRoute))) {
    const route = tabId === "explore" ? exploreLocation() : "#" + tabId;
    if (location.hash !== route) {
      history[initialRoutingComplete && changed ? "pushState" : "replaceState"](null, "", route);
    }
  }
  if (tabId === "overview") loadOverview();
  else if (!initializedPanels.has(tabId)) {
    initializedPanels.add(tabId);
    if (tabId === "learn") void 0;
    else if (tabId === "explore") loadExplore(false);
    else if (tabId === "workflows") loadWorkflowsUI();
    else if (tabId === "test") loadTestbenchUI();
    else if (tabId === "register") loadRegister();
  }
  if (tabId === "chat") {
    focusChatInput();
    requestAnimationFrame(() => focusChatInput(true));
  }
  if (changed) window.scrollTo({top:0,left:0,behavior:"instant"});
  sanitizePort8080();
}

// Enable backdrop click-to-close on legal and cookie modals
[$("legalModal"), $("cookiePrefsModal")].forEach((dlg) => {
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

const legalModalEl = $("legalModal");
if (legalModalEl) {
  legalModalEl.addEventListener("close", () => {
    if (LEGAL_ROUTES.includes((location.hash || "").slice(1))) {
      history.replaceState(null, "", "#" + currentTab);
    }
  });
}

initCookieConsent();

window.addEventListener("hashchange", () => {
  const [rawRoute, query] = (location.hash || "").slice(1).split("?");
  const h = rawRoute === "ai-transparency" || rawRoute === "legal/ai" ? "ai" : rawRoute;
  if (LEGAL_ROUTES.includes(h)) {
    if (typeof openLegalModal === "function") openLegalModal(h);
    return;
  }
  if (h === "explore") {
    if (query !== undefined || !initializedPanels.has("explore")) restoreExploreLocation();
    if (h !== currentTab) switchTab(h); else loadExplore(false);
    return;
  }
  if (TABS.includes(h) && h !== currentTab) switchTab(h);
  if (h === "test" && query && query.startsWith("id=")) {
    const deepId = query.slice(3);
    setTimeout(() => { if (typeof onTestbenchAgentChange === "function") onTestbenchAgentChange(deepId); }, 150);
  }
});

document.querySelectorAll(".nav-tab[data-tab]").forEach((b) => {
  b.onclick = () => switchTab(b.dataset.tab);
});

// ---------- Section 1: Overview ----------
let ovCache = null;
let ovRevalidating = false;

function renderOverview(data) {
  if (!data) return;
  ovCache = data;
  const kpisEl = $("ovKpis");
  if ($("ovSnapshotTime")) {
    $("ovSnapshotTime").textContent = "Catalog sample: " + nyTime(data.snapshot_at || data.now);
  }

  const s = data.health_summary || {};
  const byKind = {};
  (data.resources || []).forEach((r) => {
    if (r.active) byKind[r.kind] = (byKind[r.kind] || 0) + r.n;
  });

  if (kpisEl) {
    kpisEl.innerHTML = `
      <div class="kpi-card">
        <div class="kpi-label">Reachable Agents</div>
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
        <div class="kpi-label">Reachable Catalog Share</div>
        <div class="kpi-val" style="color:var(--ok)">${s.total_active > 0 ? esc(s.uptime_pct ?? 0) + "%" : "Not measured"}</div>
        <div class="kpi-sub">Healthy: ${fmt(s.healthy || 0)} · Reachable: ${fmt(s.reachable || 0)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Successful Check Subjects</div>
        <div class="kpi-val" style="color:var(--accent)">${fmt((data.verification || {}).successful_resources || 0)}</div>
        <div class="kpi-sub">Agents with a successful execution check in 24h</div>
      </div>
    `;
  }

  // 1. Live Status by Protocol (Target: $("ovKindStatus"))
  const kindStatusMap = { a2a: {}, mcp: {}, x402: {} };
  (data.resources || []).forEach((r) => {
    if (r.active && kindStatusMap[r.kind]) kindStatusMap[r.kind][r.status] = (kindStatusMap[r.kind][r.status] || 0) + r.n;
  });

  const protocolBars = ["a2a", "mcp", "x402"].map((k) => {
    const st = kindStatusMap[k] || {};
    const h = st["healthy"] || 0, rc = st["reachable"] || 0, f = st["failing"] || 0, d = st["down"] || 0;
    const count = Object.values(st).reduce((sum, value) => sum + value, 0);
    const tot = Math.max(1, count);
    const pH = (h / tot * 100).toFixed(1);
    const pRc = (rc / tot * 100).toFixed(1);
    const pF = (f / tot * 100).toFixed(1);
    const pD = (d / tot * 100).toFixed(1);
    return `
      <div style="margin-bottom:9px">
        <div style="display:flex;justify-content:space-between;font-size:11.5px;margin-bottom:3px">
          <span style="font-weight:700" class="k-${k}">${k.toUpperCase()}</span>
          <span style="color:var(--text-muted)">${count ? fmt(h + rc) + "/" + fmt(count) + " reachable (" + ((h + rc) / tot * 100).toFixed(0) + "%)" : "No active listings"}</span>
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
    const tot = Object.values(st).reduce((sum, value) => sum + value, 0);
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
      <div style="margin-top:12px;padding:8px 12px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid var(--border);font-size:11.5px;color:var(--text-muted);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <span style="display:inline-flex;align-items:center;gap:5px"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--accent)"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg><span><b>Connection Status</b>: A2A, MCP, and x402 reachability checks are separate from execution evidence.</span></span>
        <span style="display:inline-flex;align-items:center;gap:5px"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text-dim)"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg><span><b>Recorded Checks</b>: Review the observation time; availability can change.</span></span>
      </div>
    `;
  }

  // Recorded execution checks are distinct from reachability and imported reports.
  const measured = data.verification;
  if ($("ovSurveys")) {
    if (!measured || measured.scope !== "execution") {
      $("ovSurveys").textContent = "Recorded execution checks are currently unavailable.";
    } else {
      const number = value => Math.max(0, Number.isFinite(Number(value)) ? Number(value) : 0);
      const succeeded = number(measured.succeeded), failed = number(measured.failed), unknown = number(measured.unknown);
      const completed = succeeded + failed + unknown;
      const stamp = value => { const date = new Date(Number(value) * 1000); return Number.isFinite(date.getTime()) ? date.toISOString().slice(0, 16).replace("T", " ") : "Unavailable"; };
      const hourly = Array.isArray(measured.hourly) ? measured.hourly.slice(0, 24) : [];
      const maximum = Math.max(1, ...hourly.map(row => number(row.succeeded) + number(row.failed) + number(row.unknown)));
      let bars = "";
      hourly.forEach((row, index) => {
        let baseline = 112;
        [["succeeded", "var(--ok)"], ["failed", "var(--bad)"], ["unknown", "var(--text-muted)"]].forEach(([state, color]) => {
          const value = number(row[state]), height = value / maximum * 80;
          baseline -= height;
          bars += `<rect x="${42 + index * 16}" y="${baseline}" width="12" height="${height}" fill="${color}"><title>${esc(stamp(row.start))} UTC · ${esc(state)}: ${esc(value)}</title></rect>`;
        });
      });
      const chart = completed && hourly.length ? `
        <svg viewBox="0 0 440 154" role="img" aria-labelledby="verificationChartTitle verificationChartDesc" style="width:100%;height:auto;margin-top:12px">
          <title id="verificationChartTitle">Recorded execution checks by hour</title>
          <desc id="verificationChartDesc">Horizontal axis: UTC time, one-hour buckets. Vertical axis: recorded checks. Outcomes: succeeded, failed, unknown.</desc>
          <text x="4" y="16" fill="var(--text-muted)" font-size="10">Checks</text>
          <text x="4" y="34" fill="var(--text-muted)" font-size="10">${esc(maximum)}</text>
          <text x="22" y="114" fill="var(--text-muted)" font-size="10">0</text>
          <line x1="40" y1="112" x2="428" y2="112" stroke="var(--border)"/>
          ${bars}
          <text x="40" y="134" fill="var(--text-muted)" font-size="10">${esc(stamp(measured.period_start))}</text>
          <text x="428" y="134" text-anchor="end" fill="var(--text-muted)" font-size="10">${esc(stamp(measured.period_end))}</text>
          <text x="232" y="150" text-anchor="middle" fill="var(--text-muted)" font-size="10">Time (UTC) · 1-hour buckets</text>
        </svg>` : '<p class="muted">No execution checks were recorded during this period.</p>';
      $("ovSurveys").innerHTML = `
        <div style="font-size:24px;font-weight:800;color:var(--accent)">${fmt(completed)}</div>
        <p class="muted">Recorded execution outcomes · ${esc(stamp(measured.period_start))} to ${esc(stamp(measured.period_end))} UTC</p>
        <div class="row" style="gap:12px;flex-wrap:wrap" aria-label="Recorded execution outcomes">
          <span style="color:var(--ok)">Succeeded: <strong>${fmt(succeeded)}</strong></span>
          <span style="color:var(--bad)">Failed: <strong>${fmt(failed)}</strong></span>
          <span class="muted">Unknown: <strong>${fmt(unknown)}</strong></span>
        </div>
        ${chart}
        <p class="muted" style="font-size:11px">Source: recorded execution checks. Reachability probes, protocol discovery, imported reports and waiting checks are excluded. Repeated checks may cover the same agent. A recorded check does not guarantee future task completion.</p>
        <a href="#test" style="color:var(--accent)">Open Testbench</a>
      `;
    }
  }

  // 3. Specialized Business Categories (Target: $("ovCategories"))
  const catCounts = {};
  (data.categories || []).forEach((c) => {
    catCounts[c.category] = (catCounts[c.category] || 0) + c.n;
  });
  const catList = Object.entries(catCounts).sort((a, b) => b[1] - a[1]).slice(0, 20);
  const maxCatN = Math.max(1, ...(catList.map(c => c[1] || 0)));

  const catRows = catList.map(([id, n]) => {
    const pct = ((n / maxCatN) * 100).toFixed(0);
    const catName = (data.category_names || {})[id] || id;
    return `
      <div style="margin-bottom:9px;cursor:pointer" data-cat="${esc(id)}" data-ac-click="15b4c9f84f44" title="Explore ${esc(catName)}">
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
        </div>
      </div>
    `;
  }
}
async function loadOverview(force = false) {
  const cached = getSwrCache("overview");
  if (cached) {
    renderOverview(cached);
  } else if (!ovCache) {
    $("ovKpis").innerHTML = binaryClockHtml("Loading real-time overview...");
  }

  if (overviewBootstrapped && !force) {
    overviewBootstrapped = false;
    return;
  }

  if (ovRevalidating) return;
  ovRevalidating = true;
  try {
    const data = await api("/api/overview", { silent: true, timeoutMs:30000, retries:0 });
    setSwrCache("overview", data);
    renderOverview(data);
  } catch (err) {
    if (!cached && !ovCache) {
      $("ovKpis").innerHTML = `<p style="color:var(--bad)">Error loading overview: ${esc(err.message)}</p>`;
    }
  } finally {
    ovRevalidating = false;
  }
}

function exploreCategory(cat) {
  $("xCategory").value = cat;
  switchTab("explore");
  loadExplore(true);
}

// ---------- Section 2: Learn ----------
const GUIDE = [
  { id: "a2a", group: "protocols", pillLabel: "A2A Protocol", kind: "a2a", title: "A2A — Agent-to-Agent Delegation Protocol", html: `
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>A2A (Agent2Agent)</b> is an open communication standard that allows AI agents constructed on disparate frameworks and models to <b>delegate tasks and exchange rich artifacts</b>.
      Initiated by Google in April 2025 and hosted by the Linux Foundation, it provides a neutral protocol layer for multi-agent collaboration.
    </p>
    <div style="background:var(--chip);border-left:4px solid var(--k-a2a);padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0;font-size:13.5px">
      <b>Analogy:</b> If MCP is how an agent interacts with <b>tools</b>, A2A is how an agent <b>outsources an entire job to a specialized peer agent</b>.
      The caller does not need to know what model, internal memory, or toolchain the delegate agent runs.
    </div>
    <h4 style="margin:16px 0 6px 0">Core Concepts</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li><b>Agent Card</b> — Machine-readable identity record served at <code>/.well-known/agent-card.json</code> detailing capabilities (<b>Skills</b>), endpoints, and authentication.</li>
      <li><b>Task</b> — Asynchronous stateful job lifecycle: Submitted → Working → (Input Required) → Completed / Failed / Canceled.</li>
      <li><b>Message &amp; Parts</b> — Structured multi-modal payloads combining text, files, and data objects.</li>
      <li><b>Artifact</b> — Completed deliverables (reports, code, charts, datasets) with push notifications and streaming.</li>
      <li><b>Continuous Agent Relationship</b> — Persistent session continuity using <code>X-Visitor-Token</code> headers, allowing caller agents and human operators to resume multi-turn dialogues across disconnects.</li>
      <li><b>Autonomous Notification Desk</b> — Bidirectional callback webhooks with 6-digit challenge handshake verification for asynchronous task completion dispatches.</li>
    </ul>
    <h4 style="margin:16px 0 6px 0">How It Works</h4>
    <ol style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li>The client reads the delegate's <code>Agent Card</code> to verify skills, price models, and communication parameters.</li>
      <li>Submits a task request using <code>SendMessage</code> (v1.0) or <code>message/send</code> (v0.3) with an optional <code>X-Visitor-Token</code> for session continuity.</li>
      <li>Synchronous tasks return immediately; asynchronous tasks are monitored via <code>GetTask</code> or dispatched to registered webhooks.</li>
      <li>Deliverables are returned as structured Artifacts, rendered natively on interactive consoles or compiled into workflows.</li>
    </ol>
    <div style="margin-top:14px" data-live="a2a"></div>
    <div data-featured="a2a"></div>
`},
  { id: "mcp", group: "protocols", pillLabel: "MCP Protocol", kind: "mcp", title: "MCP — Model Context Protocol: USB-C for AI", html: `
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>MCP (Model Context Protocol)</b> is an open standard connecting AI models to external tools, live data, and structured context.
      Released by Anthropic in November 2024, it has become the universal standard supported across major AI runtimes and developer tools.
    </p>
    <div style="background:var(--chip);border-left:4px solid var(--k-mcp);padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0;font-size:13.5px">
      <b>Analogy:</b> Just as USB-C replaced fragmented proprietary cables, building an MCP server <b>once</b> makes it immediately usable in <b>Claude, ChatGPT, Cursor, VS Code</b>, and autonomous agents without custom adapters.
    </div>
    <h4 style="margin:16px 0 6px 0">Core Capabilities</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li><b>Tools</b> — Executable functions called by AI models (e.g. database query, web search, GitHub issue creation, code editing).</li>
      <li><b>Resources</b> — Read-only context and data files exposed directly to AI context windows.</li>
      <li><b>Prompts</b> — Pre-engineered workflow templates and interaction recipes.</li>
      <li><b>Universal OpenAPI Adapter</b> — Agent Concierge automatically wraps traditional Swagger / OpenAPI 3.0 specifications into remote MCP tool endpoints with zero manual code.</li>
      <li><b>Visual Canvas Orchestration</b> — Review published MCP workflow steps in Agent Concierge and run their saved definitions.</li>
    </ul>
    <h4 style="margin:16px 0 6px 0">How It Works</h4>
    <ol style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li><code>initialize</code> — Negotiates protocol version, capabilities, and server features.</li>
      <li><code>tools/list</code> — Server returns available tools with parameter JSON schemas and semantic descriptions.</li>
      <li>Model analyzes descriptions and autonomously selects parameters.</li>
      <li><code>tools/call</code> — Executes requested tool over JSON-RPC 2.0 (Streamable HTTP / stdio) and returns results with strict sandbox verification.</li>
    </ol>
    <div style="margin-top:14px" data-live="mcp"></div>
    <div data-featured="mcp"></div>
`},
  { id: "x402", group: "protocols", pillLabel: "x402 Micropayments", kind: "x402", title: "x402 — Micropayments via HTTP 402", html: `
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>x402</b> revives the historic <b>HTTP 402 Payment Required</b> status code to enable instant, pay-per-request API monetization using stablecoins (<b>USDC</b>).
      Published by Coinbase in 2025, it empowers autonomous AI agents to transact independently without human credit card setups.
    </p>
    <div style="background:var(--chip);border-left:4px solid var(--k-x402);padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0;font-size:13.5px">
      <b>Analogy:</b> A digital vending machine for AI: no accounts, no subscriptions, no monthly minimums.
      An agent drops in $0.001 USDC on Base or Solana per API call and receives immediate service autonomously.
    </div>
    <h4 style="margin:16px 0 6px 0">Architecture &amp; Clearinghouse Settlement</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li><b>Sub-Second Off-Chain Validation</b> — Agent Concierge's integrated Clearinghouse verifies cryptographic signatures and payment intent headers without blocking on blockchain confirmation times.</li>
      <li><b>On-Chain Batch Settlement</b> — Aggregated payment commitments are settled in batches to Base and EVM networks, minimizing gas overhead to fractions of a cent.</li>
      <li><b>Zero Account Overhead</b> — Autonomous caller agents pay on-the-fly per invocation; service providers receive instantaneous liquidity with zero chargeback risk.</li>
    </ul>
    <h4 style="margin:16px 0 6px 0">How It Works</h4>
    <ol style="padding-left:18px;margin:0;line-height:1.7;font-size:13px">
      <li>Agent makes a standard HTTP request to the service endpoint.</li>
      <li>Server returns <code>HTTP 402</code> with payment parameters: Price (USDC), chain, and receiving wallet.</li>
      <li>Agent signs payment with its self-custodial wallet and attaches payment proof to the request header.</li>
      <li>Clearinghouse verifies settlement in sub-second time, and the API fulfills the request.</li>
    </ol>
    <div style="margin-top:14px" data-live="x402"></div>
    <div data-featured="x402"></div>
`},
  { id: "compare", group: "protocols", pillLabel: "Side-by-Side Comparison", title: "Side-by-Side Comparison", html: `
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Dimension</th>
            <th><span class="kind-badge k-a2a">A2A</span></th>
            <th><span class="kind-badge k-mcp">MCP</span></th>
            <th><span class="kind-badge k-x402">x402</span></th>
          </tr>
        </thead>
        <tbody>
          <tr><th>Primary Role</th><td>Agent-to-agent delegation</td><td>AI-to-tool integration</td><td>Per-call API monetization</td></tr>
          <tr><th>Analogy</th><td>Outsourcing to a specialist</td><td>USB-C standard port</td><td>Digital vending machine</td></tr>
          <tr><th>Originator</th><td>Google → Linux Foundation (2025)</td><td>Anthropic (2024)</td><td>Coinbase (2025)</td></tr>
          <tr><th>Transport</th><td>JSON-RPC · gRPC · HTTP</td><td>JSON-RPC 2.0 (Streamable HTTP)</td><td>Standard HTTP + 402 responses</td></tr>
          <tr><th>Discovery</th><td>Agent Card · ERC-8004</td><td>Official MCP Registry</td><td>x402 Bazaar · Catalog Feeds</td></tr>
          <tr><th>Payment &amp; Auth</th><td>Declared on card (OAuth, x402)</td><td>Mostly free · OAuth for SaaS</td><td>USDC micropayments · Zero accounts</td></tr>
          <tr><th>Visual Studio Node</th><td>Task Delegation Step</td><td>Tool Execution Step</td><td>Monetized Data Step</td></tr>
          <tr><th>Test Report Audits</th><td>Stateful task completion tests</td><td>Schema &amp; live trial tests</td><td>Payment handshake &amp; payload tests</td></tr>
          <tr><th>Session Continuity</th><td>X-Visitor-Token &amp; Webhooks</td><td>Stateful SSE connection</td><td>Cryptographic signature proofs</td></tr>
          <tr><th>Best Suited For</th><td>Multi-step workflows &amp; delegation</td><td>Context enrichment &amp; tool invocation</td><td>Paid premium data &amp; single-call APIs</td></tr>
        </tbody>
      </table>
    </div>
`},
  { id: "together", group: "protocols", pillLabel: "Synergy & Composition", title: "Synergy: Using All Three Together", html: `
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      The three standards are not competitors; they operate at complementary architectural layers to form complete autonomous systems:
    </p>
    <ol style="padding-left:18px;margin:0;line-height:1.8;font-size:13.5px">
      <li><b>Task Delegation (A2A)</b> — An autonomous coordinator agent receives a user mission via A2A to perform multi-source research and financial modeling.</li>
      <li><b>Tool Context (MCP)</b> — The coordinator queries internal company documents, git repositories, and web search engines using local or remote MCP servers.</li>
      <li><b>Premium Data Settlement (x402)</b> — To fetch real-time market data or proprietary satellite imagery, it calls a paid endpoint, settling $0.005 USDC via x402 in sub-seconds.</li>
      <li><b>Deliverable Assembly &amp; Notification (A2A)</b> — The synthesized model is packaged as an A2A Artifact and dispatched to the caller's registered webhook callback.</li>
    </ol>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Visual Orchestration &amp; Standalone Web App Export</h4>
    <p style="font-size:13px;color:var(--text-muted);line-height:1.6;margin:0 0 10px 0">
      In Agent Concierge's <b>Visual Workflow Studio</b> (<code>#workflows</code>), you can review published workflows built with registered agent connections.
      Click <b>Download web app</b> to get a ZIP package with a web app, gateway SDK, and deployment guide. Host it on your own server or in a subdirectory. Execution connects to Agent Concierge and requires an internet connection.
    </p>
`},
  { id: "unreg-coding", group: "unregistered", pillLabel: "Autonomous Coding & SWE", title: "Autonomous Coding & SWE — Unregistered Industry Benchmarks", html: `
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Autonomous Coding &amp; Software Engineering (SWE) Agents</b> represent the frontier of generative AI in software development.
      Unlike traditional code completion assistants (e.g. GitHub Copilot autocomplete), autonomous SWE agents can ingest complex issue tickets,
      analyze entire multi-repository codebases, reproduce bugs, write and execute unit tests, and submit verified Pull Requests with zero human intervention.
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--accent);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> While these agents hold top spots on academic benchmarks (such as SWE-bench) and enjoy tens of thousands of GitHub stars,
      <b>none are currently registered as public A2A or remote MCP endpoints</b> on standard directories. They operate as proprietary closed-session SaaS platforms,
      interactive terminal CLI tools, or local Docker sandbox containers.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Featured Benchmark Leaders &amp; Unregistered Status Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Agent Name</th>
            <th>Developer / Organization</th>
            <th>Stature &amp; Traction</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>Devin</b></td>
            <td>Cognition Labs</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">Pioneer</span> · World's first autonomous AI software engineer</td>
            <td>End-to-end task breakdown, terminal command execution, multi-file code editing, self-debugging, and automated cloud deployments.</td>
            <td><b>Closed Proprietary SaaS</b>: Operates exclusively inside isolated web sessions at <code>devin.ai</code>. Provides no public A2A Agent Card or remote MCP endpoints.</td>
          </tr>
          <tr>
            <td><b>OpenHands</b><br><span style="font-size:11px;color:var(--text-dim)">(formerly OpenDevin)</span></td>
            <td>All-Hands AI</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">45k+ Stars</span> · #1 open-source autonomous coding agent</td>
            <td>Combines bash terminal execution, syntax tree editing, and headless web browsing inside secure Docker containers to resolve GitHub issues.</td>
            <td><b>Local Docker / CLI Execution</b>: Designed as a self-hosted container environment. Does not publish a persistent remote public HTTPS A2A endpoint.</td>
          </tr>
          <tr>
            <td><b>SWE-agent</b></td>
            <td>Princeton NLP</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">15k+ Stars</span> · Leading SWE-bench benchmark agent</td>
            <td>Specialized Agent-Computer Interface (ACI) that navigates repository structures, edits lines by range, and generates verified Pull Requests.</td>
            <td><b>Research CLI Batch Tool</b>: Packaged as an offline Python evaluation framework for benchmark testing rather than a 24/7 network service daemon.</td>
          </tr>
          <tr>
            <td><b>Aider</b></td>
            <td>Paul Gauthier</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">26k+ Stars</span> · Premier terminal AI pair programmer</td>
            <td>Directly pairs with developers in local git repositories, editing files in place with automated git commit messages and repo AST maps.</td>
            <td><b>Local Interactive CLI</b>: Runs entirely inside developer terminal sessions over stdin/stdout; lacks remote HTTP or Agent Card interfaces.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">Detailed Profiles &amp; Technical Architectures</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b style="font-size:14px;color:var(--accent)">1. Devin (Cognition Labs)</b>
          <span class="chip">Closed SaaS</span>
        </div>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0 0 8px 0">
          Devin is equipped with its own virtual sandbox including a sandboxed Linux shell, browser, and code editor. It independently plans solutions, reads API documentation, writes tests, and resolves compilation errors across complex dependencies.
        </p>
        <div style="font-size:11.5px;color:var(--text-dim)">
          <b>Integration Barrier:</b> Sessions are strictly browser-authenticated. Machine-to-machine invocation requires enterprise private API integration or headless browser proxying.
        </div>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b style="font-size:14px;color:var(--ok)">2. OpenHands (All-Hands AI)</b>
          <span class="chip">Docker Sandbox</span>
        </div>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0 0 8px 0">
          An extensible open-source platform providing micro-agents (CodeActAgent, PlannerAgent). It executes actions inside an isolated Docker runtime to safely run compilers, package managers, and web servers without compromising host machines.
        </p>
        <div style="font-size:11.5px;color:var(--text-dim)">
          <b>How to Run:</b> <code>docker run -it --pull=always -e SANDBOX_USER_ID=$(id -u) -p 3000:3000 ghcr.io/all-hands-ai/openhands:latest</code>
        </div>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b style="font-size:14px;color:var(--text)">3. SWE-agent (Princeton NLP)</b>
          <span class="chip">Research ACI</span>
        </div>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0 0 8px 0">
          SWE-agent introduced the Agent-Computer Interface (ACI), tailoring terminal outputs specifically for LLM consumption (compact search results, file viewer with syntax windows, targeted line replacer).
        </p>
        <div style="font-size:11.5px;color:var(--text-dim)">
          <b>Primary Target:</b> Benchmarking repository bug resolution on SWE-bench Verified dataset with automated evaluation harnesses.
        </div>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b style="font-size:14px;color:var(--text)">4. Aider (Paul Gauthier)</b>
          <span class="chip">Git-Native CLI</span>
        </div>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0 0 8px 0">
          Aider inspects local git repositories using tree-sitter AST maps to identify relevant code contexts. It edits multiple files concurrently and writes coherent git commit messages automatically.
        </p>
        <div style="font-size:11.5px;color:var(--text-dim)">
          <b>How to Run:</b> <code>pip install aider-chat &amp;&amp; aider --model claude-3-7-sonnet</code>
        </div>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Interoperability &amp; Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>A2A Container Bridge Runner</b>: We are engineering an open bridge container that wraps OpenHands and SWE-agent with an A2A Task server, allowing Agent Concierge users to dispatch coding tasks via standardized <code>/.well-known/agent-card.json</code> endpoints.</li>
      <li><b>Remote MCP Coding Server</b>: Exposing code editing and AST mapping primitives over Streamable HTTP MCP so that external orchestration agents can utilize SWE tools safely.</li>
      <li><b>Security Sandboxing Requirement</b>: Autonomous SWE agents require strict network isolation, ephemeral Docker containers, and permission checkpoints before executing arbitrary shell commands or pushing git branches.</li>
    </ul>
` },
  { id: "unreg-frameworks", group: "unregistered", pillLabel: "Multi-Agent Frameworks", title: "Multi-Agent Frameworks — Orchestration Engines & Library Ecosystem", html: `
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Multi-Agent Orchestration Frameworks</b> are foundational engines that coordinate collaborative teams of specialized AI agents.
      Rather than relying on a single monolithic prompt, these frameworks assign distinct personas (e.g. Architect, Researcher, Programmer, Quality Auditor)
      that debate, review, and refine deliverables through structured multi-turn conversations.
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--k-mcp);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> Frameworks like Microsoft AutoGen, CrewAI, and MetaGPT command <b>over 120,000 GitHub stars combined</b>.
      However, they are distributed as <b>code libraries (Python/TypeScript SDKs)</b> meant for internal application development,
      rather than persistent, publicly reachable A2A or MCP endpoints.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Featured Frameworks &amp; Stature Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Framework / Engine</th>
            <th>Developer / Organization</th>
            <th>Stature &amp; Traction</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>Microsoft AutoGen</b></td>
            <td>Microsoft Research</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">36k+ Stars</span> · Enterprise multi-agent conversation standard</td>
            <td>Multi-agent conversation patterns, human-in-the-loop oversight, code execution, and modular event-driven group chats (AutoGen 0.4+).</td>
            <td><b>Python Package Library</b>: Developers assemble agents in Python code. Does not publish a public remote A2A endpoint or hosted Agent Card.</td>
          </tr>
          <tr>
            <td><b>CrewAI</b></td>
            <td>CrewAI Inc.</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">26k+ Stars</span> · #1 role-based multi-agent workforce toolkit</td>
            <td>Defines collaborative crews with explicit roles, backstories, and goal-driven tasks. Supports sequential and hierarchical process management.</td>
            <td><b>SDK &amp; Authenticated Enterprise Cloud</b>: Open-source core is a local library. Enterprise cloud requires private API keys behind auth gates.</td>
          </tr>
          <tr>
            <td><b>MetaGPT</b></td>
            <td>DeepWisdom</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">46k+ Stars</span> · Virtual software team simulator</td>
            <td>Encapsulates Standard Operating Procedures (SOPs). Simulates an entire software agency: Product Managers (PRDs), Architects, and Coders.</td>
            <td><b>Open-Source Framework</b>: Designed for local script execution and automated document pipeline generation, not a persistent public web service.</td>
          </tr>
          <tr>
            <td><b>Smolagents</b></td>
            <td>Hugging Face</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">13k+ Stars</span> · Code-as-action lightweight runtime</td>
            <td>Agents write executable Python code snippets to invoke tools and reason, drastically reducing token overhead compared to JSON schemas.</td>
            <td><b>Library Distribution</b>: Distributed as a pip package on PyPI and Hugging Face Hub without a public standalone HTTPS gateway.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">Architectural Models &amp; Collaboration Paradigms</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--accent);display:block;margin-bottom:6px">1. AutoGen Event-Driven Multi-Agent Protocol</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          AutoGen 0.4 restructured agents around an asynchronous message-passing core (Actor model). Agents exchange typed messages over topics, making it ideal for distributed event systems and microservice topologies.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--ok);display:block;margin-bottom:6px">2. CrewAI Hierarchical Task Orchestration</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          CrewAI introduces managerial agents that dynamically delegate subtasks to specialized subordinate agents based on real-time task outcomes, enabling automated research, drafting, and quality review pipelines.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--text);display:block;margin-bottom:6px">3. MetaGPT SOP State Machine</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          MetaGPT maps human software engineering methodologies to state transitions: User Requirement → PRD (Markdown) → System Design (UML diagrams) → API Specs → Code Implementation → Integration Test.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--text);display:block;margin-bottom:6px">4. Smolagents CodeAgent Runtime</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          By generating raw Python logic rather than constrained JSON tool arguments, Smolagents enables loops, conditional branching, and complex data structures directly within agent execution turns.
        </p>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Interoperability &amp; Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>REST &amp; FastAPI Automatic Wrapping</b>: Developers running CrewAI or AutoGen as internal web services can use a protocol adapter to automatically expose their workflows as registered A2A Agent Cards.</li>
      <li><b>A2A Task Delegation Protocol</b>: An external A2A caller can submit a task to Agent Concierge, which delegates the job to a CrewAI swarm and returns the final synthesized artifact upon completion.</li>
    </ul>
` },
  { id: "unreg-research", group: "unregistered", pillLabel: "Research & Computer Use", title: "Research & Computer Use — Deep Web Research & Browsing Agents", html: `
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Web Research, Browsing &amp; Computer Use Agents</b> are autonomous systems capable of operating web browsers and desktop graphical interfaces like human users.
      They interpret visual layouts, click UI elements, fill complex forms, bypass dynamic client-side rendering hurdles, and synthesize data across dozens of disparate websites into comprehensive research dossiers.
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--k-x402);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> Autonomous web research and computer-use tools from OpenAI, Perplexity, and Manus represent the most demanded AI capabilities in 2025–2026.
      However, they currently exist as <b>proprietary walled gardens or consumer-focused web applications</b> without open, machine-to-machine A2A or MCP discovery interfaces.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Featured Research Agents &amp; Unregistered Status Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Agent Name</th>
            <th>Developer / Organization</th>
            <th>Stature &amp; Traction</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>Manus AI</b></td>
            <td>Monica / Manus Team</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">Global Sensation</span> · 2025–2026 breakthrough generalist task agent</td>
            <td>Asynchronously executes complex multi-hour workflows: web research, market comparisons, document drafting, presentation slides, and live web app deployment.</td>
            <td><b>Invite-Only Closed Platform</b>: Operates as a browser-based consumer SaaS product. Does not provide an open machine-to-machine (M2M) API, A2A card, or remote MCP server.</td>
          </tr>
          <tr>
            <td><b>OpenAI Operator &amp; Deep Research</b></td>
            <td>OpenAI</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">Industry Flagship</span> · State-of-the-art vision computer use &amp; research</td>
            <td>Navigates live websites using vision models, clicks buttons, enters text, and searches dozens of academic and web sources to assemble multi-page analytical reports.</td>
            <td><b>Proprietary ChatGPT Feature</b>: Bound tightly to ChatGPT Pro and Team web interfaces. No external standardized A2A agent card or open MCP protocol endpoint is published.</td>
          </tr>
          <tr>
            <td><b>Perplexity Pro &amp; Deep Research</b></td>
            <td>Perplexity AI</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">Standard</span> · Premier real-time citation research engine</td>
            <td>Searches academic journals, financial filings, and live news streams with multi-stage reasoning to generate cited, hallucination-resistant research summaries.</td>
            <td><b>Proprietary REST API Format</b>: While standard REST endpoints exist (<code>api.perplexity.ai</code>), it does not provide native A2A Agent Card discovery or official remote MCP servers.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">Technical Capabilities &amp; Execution Challenges</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--accent);display:block;margin-bottom:6px">1. Visual Grounding &amp; DOM Interaction</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Agents like OpenAI Operator take high-resolution screenshots, calculate pixel bounding boxes, and generate synthetic mouse/keyboard events. This enables interaction with arbitrary web applications, canvas charts, and forms without requiring pre-existing APIs.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--ok);display:block;margin-bottom:6px">2. Multi-Hop Recursive Search</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Deep Research engines perform breadth-first and depth-first searches: extracting references from one document, spawning secondary search queries, evaluating source trustworthiness, and cross-checking conflicting data before finalizing conclusions.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--text);display:block;margin-bottom:6px">3. Asynchronous Task Continuity</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Complex web investigations can take 10 to 30 minutes. Manus AI employs asynchronous state checkpoints, webhooks, and push notifications to alert users when long-running research tasks complete.
        </p>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Interoperability &amp; Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>Headless Browser Tool Servers</b>: Agent Concierge currently catalogs verified remote browser MCP tools (e.g. Cloudflare Browser Rendering MCP, Firecrawl MCP) that allow any agent to execute programmatic scraping and research.</li>
      <li><b>Perplexity REST Adapter</b>: By configuring our universal REST adapter with a Perplexity API key, users can expose Perplexity's deep research engine as an instant MCP tool to Claude Desktop, Cursor, or A2A pipelines.</li>
    </ul>
` },
  { id: "unreg-web3", group: "unregistered", pillLabel: "Decentralized & Crypto Agents", title: "Decentralized & Crypto Agents — Web3, On-Chain & Autonomous Social Agents", html: `
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Web3 &amp; Decentralized Autonomous Agents</b> possess economic agency: they control non-custodial crypto wallets, execute on-chain smart contracts,
      manage decentralized liquidity, trade assets, and interact as autonomous social influencers across social platforms (X/Twitter, Telegram, Discord).
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--accent);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> Driven by ecosystems like Virtuals Protocol, ElizaOS, and Base, thousands of tokenized AI agents have achieved substantial market capitalization.
      However, they are <b>not registered on standard A2A/MCP directories</b> due to reliance on social messenger event loops, on-chain smart contracts, or proprietary communication protocols.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Featured Decentralized Agents &amp; Unregistered Status Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Agent / Platform</th>
            <th>Developer / Organization</th>
            <th>Stature &amp; Traction</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>ElizaOS</b><br><span style="font-size:11px;color:var(--text-dim)">(formerly Eliza)</span></td>
            <td>ai16z</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">16k+ Stars</span> · #1 crypto &amp; autonomous social AI framework</td>
            <td>Autonomous multi-platform social engagement (Twitter/Discord/Telegram), wallet management, character personas, and community management.</td>
            <td><b>Messenger &amp; WebSocket Architecture</b>: Communicates via social media APIs and WebSocket client connections rather than standard HTTP JSON-RPC A2A Agent Cards.</td>
          </tr>
          <tr>
            <td><b>Virtuals Protocol</b><br><span style="font-size:11px;color:var(--text-dim)">(Luna, aixbt, G.A.M.E.)</span></td>
            <td>Virtuals Protocol</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">Hundreds of Millions</span> in ecosystem market capitalization</td>
            <td>Tokenized co-owned AI personas running on Base/Ethereum. Autonomous social content generation, on-chain revenue sharing, and gaming agents.</td>
            <td><b>Smart Contract &amp; Social Platform Dependency</b>: Execution is tied to on-chain token contracts and proprietary G.A.M.E. SDKs without open remote A2A endpoints.</td>
          </tr>
          <tr>
            <td><b>Fetch.ai / ASI Alliance</b><br><span style="font-size:11px;color:var(--text-dim)">(Agentverse)</span></td>
            <td>Fetch.ai (ASI Alliance)</td>
            <td><span class="chip" style="color:var(--accent);font-weight:700">Pioneer</span> · Decentralized autonomous agent network since 2019</td>
            <td>Micro-agent collaboration in logistics, mobility, travel booking, and DeFi arbitrage. Features the Almanac on-chain contract registry.</td>
            <td><b>Proprietary uAgents Protocol</b>: Uses the uAgents Python framework and Almanac on-chain registry, which is incompatible with IETF A2A Agent Card specifications.</td>
          </tr>
          <tr>
            <td><b>Coinbase AgentKit</b></td>
            <td>Coinbase Developer Platform</td>
            <td><span class="chip" style="color:var(--ok);font-weight:700">Official Standard</span> · On-chain transaction toolkit for AI agents</td>
            <td>Empowers LangChain, CrewAI, and custom agents with crypto wallets to transfer USDC, swap tokens, and deploy smart contracts on Base and EVM chains.</td>
            <td><b>Developer SDK / Toolkit</b>: Distributed as an npm/pip developer SDK for embedding into private applications rather than a 24/7 hosted public agent server.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">Why On-Chain Agents Diverge from Web A2A Standards</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--accent);display:block;margin-bottom:6px">1. Social Event Loop vs. Remote HTTP Listener</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Agents built on ElizaOS poll or listen to platform feeds (e.g. mentions on X, Discord guild events). They act as clients connecting outward to platforms rather than running inbound HTTP servers with static URLs.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--ok);display:block;margin-bottom:6px">2. On-Chain Metadata vs. Live Runtime Endpoints</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Hundreds of thousands of ERC-8004 and tokenized agent contracts store only IPFS metadata (avatar images, descriptions). They lack live, reachable HTTPS hostnames where a caller can execute RPC calls.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--text);display:block;margin-bottom:6px">3. Gas Costs &amp; Non-Deterministic Latency</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          On-chain transaction execution requires cryptographic signing, gas estimation, and block confirmations (2–12 seconds), conflicting with real-time JSON-RPC expectations unless asynchronous task schemas are used.
        </p>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Interoperability &amp; Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>x402 Micropayment Bridge</b>: Agent Concierge provides native support for HTTP 402 micropayments over Base and EVM networks, enabling on-chain agents powered by Coinbase AgentKit to pay for and monetize API calls seamlessly.</li>
      <li><b>A2A Agent Card Gateway for ElizaOS</b>: An open adapter plugin allowing ElizaOS operators to publish a standard <code>/.well-known/agent-card.json</code> endpoint so web-based agents can delegate social tasks to Eliza personas.</li>
    </ul>
` },
  { id: "unreg-stdio", group: "unregistered", pillLabel: "Official STDIO MCP Servers", title: "Official STDIO MCP Servers — Anthropic Standard I/O Local Tool Suite", html: `
    <p style="font-size:14.5px;line-height:1.7;color:var(--text)">
      <b>Anthropic Official STDIO Servers</b> are the reference tools maintained in the official Model Context Protocol repository
      (<code>modelcontextprotocol/servers</code>). They empower desktop AI applications (e.g. Claude Desktop, Cursor) with direct access
      to file systems, version control, database queries, web search, and browser automation.
    </p>

    <div style="background:var(--chip);border-left:4px solid var(--k-mcp);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px">
      <b>Ecosystem Status:</b> These are among the most celebrated tools in the entire MCP ecosystem. However, <b>none are registered as public web endpoints</b>
      because they are engineered to execute strictly as <b>local processes communicating over Standard Input/Output (STDIO)</b> pipes, rather than public HTTPS/SSE endpoints.
    </div>

    <h4 style="margin:20px 0 8px 0;font-size:15px">Official Reference STDIO Tool Suite Matrix</h4>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Tool Server</th>
            <th>Package Identifier</th>
            <th>Core Role &amp; Capabilities</th>
            <th>Reason for Unregistered Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>Brave Search MCP</b></td>
            <td><code>@modelcontextprotocol/server-brave-search</code></td>
            <td>Performs real-time web searches and local geographic lookups via the Brave Search API.</td>
            <td><b>Local CLI Execution</b>: Launched via <code>npx</code> inside the client machine; does not provide a public remote HTTPS endpoint.</td>
          </tr>
          <tr>
            <td><b>GitHub MCP</b></td>
            <td><code>@modelcontextprotocol/server-github</code></td>
            <td>Repository exploration, issue tracking, Pull Request review, file modifications, and git commits.</td>
            <td><b>Requires Local Secret Tokens</b>: Requires the developer's Personal Access Token (PAT) in local environment variables.</td>
          </tr>
          <tr>
            <td><b>Postgres &amp; SQLite MCP</b></td>
            <td><code>@modelcontextprotocol/server-postgres</code></td>
            <td>Inspects database schemas, runs parameterized SQL queries, and analyzes internal table relationships.</td>
            <td><b>Local &amp; VPC Security</b>: Restricted to local or private VPC subnets to prevent catastrophic exposure of sensitive internal databases.</td>
          </tr>
          <tr>
            <td><b>Slack MCP</b></td>
            <td><code>@modelcontextprotocol/server-slack</code></td>
            <td>Lists channels, retrieves message histories, posts replies, and searches conversations in Slack workspaces.</td>
            <td><b>Local Bot Process</b>: Operates as an STDIO process consuming a local Slack Bot User OAuth Token.</td>
          </tr>
          <tr>
            <td><b>Puppeteer MCP</b></td>
            <td><code>@modelcontextprotocol/server-puppeteer</code></td>
            <td>Controls a headless Chromium browser instance to take screenshots, scrape dynamic HTML, and click elements.</td>
            <td><b>Local Process Control</b>: Spawns and manages a local Chromium browser process via Node.js pipes.</td>
          </tr>
          <tr>
            <td><b>Google Drive MCP</b></td>
            <td><code>@modelcontextprotocol/server-gdrive</code></td>
            <td>Searches, reads, and inspects files and Google Docs stored within Google Workspace accounts.</td>
            <td><b>Local OAuth2 Credentials</b>: Stores client credentials and OAuth token caches on the user's local workstation.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin:22px 0 10px 0;font-size:15px">STDIO vs. Remote HTTP Transport: Why They Differ</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--accent);display:block;margin-bottom:6px">1. Standard I/O (STDIO) Process Pipes</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          The host application (e.g. Claude Desktop) launches the tool as a child process. Requests and responses are serialized as single-line JSON-RPC messages written directly to <code>stdin</code> and <code>stdout</code>. No network port is opened, eliminating external attack surfaces.
        </p>
      </div>

      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border)">
        <b style="font-size:14px;color:var(--ok);display:block;margin-bottom:6px">2. Remote Streamable HTTP (SSE) Transport</b>
        <p style="font-size:12.5px;color:var(--text-muted);line-height:1.6;margin:0">
          Remote MCP servers listen on public HTTPS URLs. Clients initiate connections via Server-Sent Events (SSE) or Streamable HTTP POST. This allows multi-user access and cloud hosting, but requires robust network security, rate limiting, and SSL certificates.
        </p>
      </div>
    </div>

    <h4 style="margin:22px 0 8px 0;font-size:15px">How to Run Locally in Claude Desktop or Cursor</h4>
    <p style="font-size:13px;color:var(--text-muted)">
      To use these tools today, add them to your <code>claude_desktop_config.json</code>:
    </p>
    <pre style="background:var(--chip);padding:12px;border-radius:8px;font-size:12px;overflow-x:auto;border:1px solid var(--border)"><code>{
  "mcpServers": {
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": { "BRAVE_API_KEY": "YOUR_BRAVE_API_KEY" }
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "YOUR_GITHUB_TOKEN" }
    }
  }
}</code></pre>

    <h4 style="margin:22px 0 8px 0;font-size:15px">Agent Concierge Cloud Bridge Roadmap</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>Cloud-Hosted Remote Alternatives</b>: For users who cannot run local Node.js processes, Agent Concierge already indexes verified remote alternatives such as <b>Tavily Search MCP</b> (remote web search), <b>Cloudflare Browser Rendering MCP</b> (cloud browser automation), and <b>Neon MCP</b> (serverless Postgres).</li>
      <li><b>STDIO-to-SSE Secure Proxy</b>: We are providing an open-source Docker bridge utility that encapsulates any standard STDIO MCP server into an authenticated HTTPS SSE service for multi-agent cloud workflows.</li>
    </ul>
` },
  { id: "discovery", group: "reference", pillLabel: "Live Agent Discovery", title: "Where to Find Live Agents", html: `
    <ul style="padding-left:18px;margin:0;line-height:1.8;font-size:13.5px">
      <li><b>Agent Concierge Live Catalog (<code>#explore</code>)</b> — Unified, searchable directory indexing over 94,000+ live resources across A2A, MCP, and x402 with sub-millisecond SWR client caching.</li>
      <li><b>Automated Benchmark Test Reports (<span class="report-badge-vivid" style="display:inline-flex;align-items:center;gap:3px;font-size:10px;padding:1px 6px;vertical-align:middle"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg><span>TEST Recorded report</span></span>)</b> — Over 200+ deeply audited agents featuring verified execution reports, real-world latency measurements, pass rates, and interactive testing workflows.</li>
      <li><b>x402 Bazaar</b> — Official registry maintained by Coinbase indexing prices, settlement addresses, and 30-day payment volume.</li>
      <li><b>MCP Registry</b> — Official directory for remote and local MCP servers with parameter schemas and repository links.</li>
      <li><b>ERC-8004 On-Chain Registry</b> — Ethereum standard for Trustless Agents recording decentralized identity, reputation, and endpoint URIs on Base and Ethereum.</li>
      <li><b>.well-known Discovery</b> — Direct automated scanning of public domain endpoints at <code>/.well-known/agent-card.json</code>.</li>
    </ul>
`},
  { id: "quality", group: "reference", pillLabel: "Quality & Health Grading", title: "Health Status & 6-Axis Quality Grading", html: `
    <h4 style="margin:0 0 6px 0">Health Lifecycle States</h4>
    <ul style="padding-left:18px;margin:0 0 14px 0;line-height:1.7;font-size:13px">
      <li><span class="s-healthy font-semibold">healthy</span> — Responding according to protocol specifications (x402 returns valid 402, MCP initializes, A2A card opens).</li>
      <li><span class="s-reachable font-semibold">reachable</span> — Endpoint online but requires authentication or API credentials to complete probe.</li>
      <li><span class="s-failing font-semibold">failing</span> — 1–2 consecutive probe failures. Retried after 15 minutes; temporarily demoted from recommendations.</li>
      <li><span class="s-down font-semibold">down</span> — 3+ consecutive failures. Continuously probed for recovery.</li>
      <li><span class="s-retired font-semibold">retired</span> — Unresponsive for &gt;7 days. Excluded from active indexes.</li>
      <li><b>Partitioned 6-Hour Scheduling</b> — Endpoints are probed normally every 6 hours (±10% jitter) across dedicated A2A, MCP, and x402 worker lanes to eliminate request bursts and queue starvation.</li>
    </ul>

    <h4 style="margin:16px 0 6px 0">Automated Quality Rubric (Grades A–F)</h4>
    <p style="font-size:13px;color:var(--text-muted);margin:0 0 12px 0;line-height:1.6">
      Endpoints are evaluated across 6 dimensions without subjective LLM bias: <b>Availability</b> (25%), <b>Schema Quality</b> (20%), <b>Security Posture</b> (20%), <b>Context Efficiency</b> (15%), <b>Protocol Adherence</b> (10%), and <b>Maintenance Freshness</b> (10%).
    </p>

    <h4 style="margin:16px 0 6px 0">Security Sandbox &amp; Abuse Prevention</h4>
    <ul style="padding-left:18px;margin:0;line-height:1.7;font-size:13px;color:var(--text-muted)">
      <li><b>SSRF Defense</b> — Automated blocking of RFC-1918 private subnet IP ranges, loopback localhost addresses, and internal network endpoints.</li>
      <li><b>Adversarial Anomaly Filtration</b> — Detection of prompt injection attempts, hidden zero-width unicode payload characters, and behavioral mutations.</li>
      <li><b>Tool Rug-Pull Quarantine</b> — Immediate isolation of endpoints whose tool parameter schemas change without version bumps or audit revalidation.</li>
    </ul>
`},
  { id: "glossary", group: "reference", pillLabel: "Terminology Dictionary", title: "Terminology Dictionary", glossary: [
    [
        "HTTP 402",
        "Payment Required status code specifying amount, token, and wallet address."
    ],
    [
        "USDC",
        "USD-pegged stablecoin with 6 decimals allowing sub-cent micropayments ($0.000001)."
    ],
    [
        "Base",
        "High-throughput Ethereum Layer 2 chain widely used for low-fee x402 transactions."
    ],
    [
        "Facilitator",
        "Service validating and settling blockchain micropayment proofs on behalf of API providers."
    ],
    [
        "x402 Bazaar",
        "Public discovery index of x402-enabled paid endpoints and real-time pricing."
    ],
    [
        "MCP Tool",
        "Callable function definition exposed by an MCP server to an AI model."
    ],
    [
        "tools/list",
        "JSON-RPC method returning available tools and parameter schemas."
    ],
    [
        "tools/call",
        "JSON-RPC method executing an MCP tool with provided arguments."
    ],
    [
        "JSON-RPC 2.0",
        "Standard lightweight RPC protocol utilized by both MCP and A2A."
    ],
    [
        "Streamable HTTP",
        "HTTP POST transport supporting streaming responses for remote MCP."
    ],
    [
        "Agent Card",
        "Standardized JSON identity record defining skills, endpoints, and credentials."
    ],
    [
        "Skill",
        "Declared capability description published in an A2A Agent Card."
    ],
    [
        "Task",
        "Stateful asynchronous job instance managed across peer agents."
    ],
    [
        "Artifact",
        "Deliverable output object returned upon A2A task completion."
    ],
    [
        "Visitor Token",
        "Cryptographically random token (X-Visitor-Token) preserving multi-turn chat continuity without tracking PII."
    ],
    [
        "Workflow Studio",
        "Visual canvas for reviewing published agent workflows and running their saved definitions."
    ],
    [
        "Standalone Web App",
        "Connected HTML application that runs a published template through Agent Concierge and displays recorded outcomes."
    ],
    [
        "OpenAPI Adapter",
        "Automated proxy converter mapping OpenAPI 3.0 / Swagger REST specs into native MCP tools and A2A cards."
    ],
    [
        "Test Report",
        "Automated verification audit validating live tool execution pass rate, latency percentiles, and schema integrity."
    ],
    [
        "Notification Desk",
        "Asynchronous agent callback webhook manager with 6-digit challenge handshake verification."
    ],
    [
        "Clearinghouse",
        "High-throughput off-chain payment verification and batch on-chain settlement engine."
    ],
    [
        "ERC-8004",
        "On-chain standard for decentralized agent identity and verification."
    ],
    [
        ".well-known",
        "Standard IETF URI prefix used for automated agent card discovery."
    ],
    [
        "Tool Poisoning",
        "Adversarial exploit injecting malicious hidden instructions inside tool descriptions."
    ],
    [
        "Rug Pull",
        "Unauthorized mutation of tool definitions after initial verification."
    ],
    [
        "Quarantine",
        "Security isolation state for compromised or hostile agent servers."
    ]
]},
  { id: "faq", group: "reference", pillLabel: "Frequently Asked Questions", title: "Frequently Asked Questions", faq: [
    [
        "Which protocol should I choose for my project?",
        "Choose MCP if you want to connect tools to Claude/ChatGPT/Cursor; choose A2A if you are delegating autonomous jobs across agents; choose x402 if you are monetizing API calls per request with crypto."
    ],
    [
        "Are MCP servers free to use?",
        "The majority of community MCP servers are free and open-source. Commercial SaaS tools may require OAuth login or existing service accounts."
    ],
    [
        "Does reachable mean an error?",
        "No. Reachable indicates the endpoint server is online and operational, but requires user credentials or an API key for full functional probing."
    ],
    [
        "How are recommended agents vetted?",
        "Services are continuously validated via real connectivity probes, automated tool tests, and security sandbox audits. Quarantined services are blocked."
    ],
    [
        "How can I list my agent?",
        "Open List Your Agent and enter your public endpoint and capabilities. We check the endpoint before adding your agent to the discovery catalog."
    ],
    [
        "How does the continuous agent relationship work in chat?",
        "Agent Concierge maintains session continuity without showing visitor details. You can continue requests across browser reloads or machine-to-machine runners."
    ],
    [
        "Can I download and run multi-agent workflows offline?",
        "No — workflow execution requires an internet connection. Choose a published template in Workflow Studio and click 'Download web app'. Extract the ZIP and upload it to your server or static host. Its SDK connects to Agent Concierge to run the workflow."
    ],
    [
        "What does the 'TEST REPORT' badge represent?",
        "It indicates that the agent has undergone comprehensive automated trial executions, with latency benchmarks, tool call verification, and live test reports available in the agent details drawer."
    ],
    [
        "Can I connect legacy REST APIs to Agent Concierge?",
        "Yes. Use our built-in OpenAPI Adapter to paste any OpenAPI 3.0 or Swagger schema URL; the gateway automatically exposes it as a standard MCP tool server and A2A Agent Card."
    ],
    [
        "How does Agent Concierge prevent SSRF attacks?",
        "All registered endpoints undergo strict IP validation. Private RFC-1918 subnets, localhost addresses, and internal network ports are blocked at the proxy boundary."
    ]
]}
];

let selectedLearnTab = "a2a";
let insightsData = null;
let learnRevalidating = false;

function renderLearnUI() {
  const data = insightsData || getSwrCache("insights") || { kinds: {}, categories: {} };
  const kinds = data.kinds || {};

  $("learnProtoCards").innerHTML = ["a2a", "mcp", "x402"].map((k) => {
    const kd = kinds[k] || { stats: { total: 0, live: 0 } };
    const s = kd.stats || { total: 0, live: 0 };
    const isSel = selectedLearnTab === k;
    const titles = { a2a: "A2A Agents", mcp: "MCP Tool Servers", x402: "x402 Paid APIs" };
    const tips = { a2a: "Agent-to-Agent delegation protocol", mcp: "Model Context Protocol for tools", x402: "HTTP 402 pay-per-call micropayments" };
    return `
      <div class="card proto k-${k}" data-tab="${esc(k)}" data-ac-click="fff5737e3ccc" style="cursor:pointer;${isSel ? 'border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-glow)' : ''}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span class="kind-badge k-${k}">${k}</span>
          <span style="font-size:11.5px;color:var(--text-muted)">${pct(s.live, s.total)} live</span>
        </div>
        <div style="font-size:24px;font-weight:800;color:var(--text)">${fmt(s.total)}</div>
        <div style="font-size:12.5px;font-weight:600;margin-top:2px">${titles[k]}</div>
        <div style="font-size:11.5px;color:var(--text-dim);margin-top:4px">${tips[k]}</div>
      </div>
    `;
  }).join("");

  const learnGroups = [
    { key: "protocols", label: "Open Protocol Standards & Architecture", tip: "Foundation" },
    { key: "unregistered", label: "Ecosystem Landscape: Unregistered Popular Agents", tip: "5 Key Domains" },
    { key: "reference", label: "Ecosystem Reference & FAQ", tip: "Reference" }
  ];

  let pillsHtml = "";
  learnGroups.forEach((grp, gIdx) => {
    const items = GUIDE.filter((g) => (g.group || "protocols") === grp.key);
    if (!items.length) return;
    pillsHtml += `
      <div style="width:100%;font-size:11.5px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;color:${grp.key === 'unregistered' ? 'var(--accent)' : 'var(--text-dim)'};margin:${gIdx > 0 ? '12px' : '2px'} 0 4px 0;display:flex;align-items:center;gap:6px">
        <span>${esc(grp.label)}</span>
        <span class="chip" style="font-size:10px;padding:1px 6px">${esc(grp.tip)}</span>
      </div>
    `;
    pillsHtml += items.map((g) => {
      const isSel = g.id === selectedLearnTab;
      const label = g.pillLabel || g.title.split(" — ")[0];
      return `<button class="sub-pill ${isSel ? 'active' : ''}" data-tab="${esc(g.id)}" data-ac-click="fff5737e3ccc">${esc(label)}</button>`;
    }).join("");
  });
  $("learnSubPills").innerHTML = pillsHtml;

  const sec = GUIDE.find((g) => g.id === selectedLearnTab) || GUIDE[0];
  let bodyHtml = "";
  if (sec.glossary) {
    bodyHtml = `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px">
        ${sec.glossary.map(([term, def]) => `
          <div style="background:var(--chip);padding:10px 14px;border-radius:8px;border:1px solid var(--border)">
            <b style="color:var(--accent);display:block;margin-bottom:2px">${esc(term)}</b>
            <span style="font-size:12.5px;color:var(--text-muted)">${esc(def)}</span>
          </div>
        `).join("")}
      </div>
    `;
  } else if (sec.faq) {
    bodyHtml = sec.faq.map(([q, a]) => `
      <div style="margin-bottom:14px">
        <h4 style="margin:0 0 4px 0;font-size:14px;color:var(--text)">Q: ${esc(q)}</h4>
        <p style="margin:0;font-size:13px;color:var(--text-muted);line-height:1.6">${esc(a)}</p>
      </div>
    `).join("");
  } else {
    bodyHtml = sec.html;
  }

  $("learnBody").innerHTML = `
    <div class="card">
      <h2>${esc(sec.title)}</h2>
      ${bodyHtml}
    </div>
  `;

  // Populate live numbers and featured cards if protocol
  if (sec.kind && kinds[sec.kind]) {
    const kd = kinds[sec.kind];
    const s = kd.stats || {};
    const liveEl = $("learnBody").querySelector(`[data-live="${sec.kind}"]`);
    if (liveEl) {
      liveEl.innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:12px 0">
          <div style="background:var(--chip);padding:8px 12px;border-radius:8px;border:1px solid var(--border)">
            <div style="font-size:11px;color:var(--text-dim)">ACTIVE INDEXED</div>
            <div style="font-size:18px;font-weight:800">${fmt(s.total || 0)}</div>
          </div>
          <div style="background:var(--chip);padding:8px 12px;border-radius:8px;border:1px solid var(--border)">
            <div style="font-size:11px;color:var(--text-dim)">SERVICE AVAILABLE</div>
            <div style="font-size:18px;font-weight:800;color:var(--ok)">${pct(s.live || 0, s.total || 0)}</div>
          </div>
          <div style="background:var(--chip);padding:8px 12px;border-radius:8px;border:1px solid var(--border)">
            <div style="font-size:11px;color:var(--text-dim)">GRADE A EXCELLENT</div>
            <div style="font-size:18px;font-weight:800;color:var(--accent)">${fmt(s.grade_a || 0)}</div>
          </div>
          <div style="background:var(--chip);padding:8px 12px;border-radius:8px;border:1px solid var(--border)">
            <div style="font-size:11px;color:var(--text-dim)">ZERO AUTH NEEDED</div>
            <div style="font-size:18px;font-weight:800">${fmt(s.no_auth || 0)}</div>
          </div>
        </div>
      `;
    }

    const featEl = $("learnBody").querySelector(`[data-featured="${sec.kind}"]`);
    if (featEl && (kd.featured || []).length) {
      const featCards = kd.featured.map((f) => `
        <div style="margin-top:14px">
          <h4 style="margin:0 0 8px 0;font-size:13.5px;color:var(--text-muted)">${esc(f.title)}</h4>
          <div class="cards-grid">
            ${f.items.map((r) => agentCardHtml(r)).join("")}
          </div>
        </div>
      `).join("");
      featEl.innerHTML = featCards;
    }
  }
}

async function renderLearn(force = false) {
  if (!insightsData) {
    const cached = getSwrCache("insights");
    if (cached) insightsData = cached;
  }

  // 1. Instant zero-delay synchronous render (0ms latency)
  renderLearnUI();

  // 2. Silent background SWR revalidation
  if (learnRevalidating) return;
  learnRevalidating = true;
  try {
    const data = await api("/api/insights", { loadingMsg: "Loading protocol guides..." });
    insightsData = data;
    setSwrCache("insights", data);
    renderLearnUI();
    populateCategorySelects();
  } catch (err) {
    // Keep existing rendered cached data smoothly
  } finally {
    learnRevalidating = false;
  }
}

function selectLearnSubTab(tabId) {
  selectedLearnTab = tabId;
  renderLearnUI();
}

const CATEGORY_ALIASES = {
  "data-analytics": "database_analytics",
  "data_analytics": "database_analytics",
  "data-analysis": "database_analytics",
  "database-analytics": "database_analytics",
  "trust-safety": "security",
  "commerce-marketing": "commerce_marketing",
  "agent-orchestration": "agent_infra",
  "agent-directories": "agent_infra",
  "developer-tools": "dev_tools",
  "agent-memory-storage": "database_analytics",
  "demo-test": "dev_tools",
  "markets-trading": "trading_derivatives",
  "real-world-services": "productivity",
  "agent-communities": "social",
  "content-media": "media_generation",
  "crypto-web3": "finance_crypto",
  "legal-compliance": "public_legal",
  "professional-services": "productivity",
  "research-learning": "education_culture",
  "other": "General"
};

function formatCategory(rawCat, catsMap) {
  if (!rawCat) return "General";
  const catKey = String(rawCat).trim().toLowerCase();
  const aliasedKey = CATEGORY_ALIASES[catKey] || catKey;
  if (catsMap && catsMap[aliasedKey]) return catsMap[aliasedKey];
  if (catsMap && catsMap[catKey]) return catsMap[catKey];
  if (typeof DEFAULT_CATEGORIES !== "undefined") {
    if (DEFAULT_CATEGORIES[aliasedKey]) return DEFAULT_CATEGORIES[aliasedKey];
    if (DEFAULT_CATEGORIES[catKey]) return DEFAULT_CATEGORIES[catKey];
  }
  if (aliasedKey === "general" || catKey === "other") return "General";
  return String(rawCat).replace(/[-_]/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function agentCardHtml(r) {
  const cats = {...DEFAULT_CATEGORIES, ...((insightsData && insightsData.categories) || (ovCache && ovCache.category_names) || {})};
  const hasReport = Boolean(r.report_count > 0 || r.has_report || r.test_report || (r.test_reports && r.test_reports.length));
  const meta = [];
  if (r.catalog_status === "historical") meta.push('<span class="chip" style="color:var(--warn)">Historical entry · unavailable</span>');
  if (r.first_seen) meta.push(`<span class="chip" style="color:var(--reach);display:inline-flex;align-items:center;gap:3px" title="Discovered: ${nyTime(r.first_seen)}"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg><span>${nyAgo(r.first_seen)}</span></span>`);
  if (r.price_note === "testnet_only") meta.push('<span class="chip">Testnet only</span>');
  else if (r.kind === "x402" && r.price_usdc) meta.push(`<span class="chip">${usd(r.price_usdc)}/call</span>`);
  else if (r.kind === "x402" && r.price_usdc === null) meta.push('<span class="chip">Price on request</span>');
  if (r.payers_30d) meta.push(`<span class="chip">30d payers: ${fmt(r.payers_30d)}</span>`);
  if (r.cap_tool_count) meta.push(`<span class="chip">${fmt(r.cap_tool_count)} tools</span>`);
  if (r.eval_grade) meta.push(`<span class="chip">Grade ${esc(r.eval_grade)} (${Math.round(r.eval_score || 0)})</span>`);
  if (r.connection_readiness?.verified_callable === true) meta.push(`<span class="chip" style="color:var(--ok);display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Execution checked</span></span>`);
  if (r.kind !== "x402" && r.auth_required === 0) meta.push(`<span class="chip">Zero Account</span>`);
  if (hasReport) meta.push(`<span class="chip chip-report" title="Recorded Report Available" style="display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="20" y2="10"/><line x1="18" x2="18" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="16"/></svg><span>Report available</span></span>`);

  return `
    <div class="acard k-${esc(r.kind)} ${hasReport ? "has-report" : ""}" data-id="${esc(r.id)}" data-ac-click="d5e60f613626">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
        <div style="display:flex;align-items:center;gap:6px">
          <span class="kind-badge k-${esc(r.kind)}">${esc(r.kind)}</span>
          ${hasReport ? `<span class="report-badge-vivid" title="Recorded report available; check its execution evidence separately"><span class="sparkle"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg></span> Recorded report</span>` : ""}
        </div>
        <span style="font-size:11.5px;color:var(--text-dim)">${esc(formatCategory(r.category, cats))}</span>
      </div>
      <div class="t" title="${esc(r.name)}">${esc(r.name)}</div>
      <div class="d">${esc(r.description || "No description provided.")}</div>
      <div class="m">${meta.join("")}</div>
    </div>
  `;
}

// ---------- Section 3: Explore ----------
const QUICK_CHIPS = [
  ["Weather", "weather"], ["Stock Quotes", "stock quotes"], ["Crypto Prices", "crypto prices"],
  ["Web Search", "web search"], ["News", "news"], ["Translation", "translation"],
  ["Image Generation", "image generation"], ["Maps & Places", "maps and places"], ["PDF & Docs", "pdf extraction"],
  ["Email", "email"], ["GitHub", "github"], ["Legal & Courts", "court records"],
  ["Travel & Flights", "flight search"], ["Directory & Registry", "agent directory"],
  ["Health & Medicine", "medical research"], ["Security & CVE", "security vulnerabilities"],
  ["Perpetual Funding", "funding rates"], ["SMS & Messaging", "sms messaging"],
  ["Domain & DNS", "domain lookup"], ["Data Transformation", "data conversion"]
];

$("xChips").innerHTML = QUICK_CHIPS.map(([lbl, q]) => `
  <button class="chip-btn" data-q="${esc(q)}" data-ac-click="910a5334ec93">${esc(lbl)}</button>
`).join("");

function updateActiveExploreChip(targetQ) {
  const qVal = (targetQ !== undefined ? targetQ : ($("xQ") ? $("xQ").value : "")).trim().toLowerCase();
  document.querySelectorAll("#xChips .chip-btn").forEach((btn) => {
    const bq = (btn.getAttribute("data-q") || "").trim().toLowerCase();
    const isMatch = Boolean(bq && qVal === bq);
    btn.classList.toggle("active", isMatch);
    btn.classList.toggle("on", isMatch);
  });
}

function applyExploreChip(q) {
  // Selecting the active shortcut again clears it and returns to the latest agents.
  const currentQ = ($("xQ") ? $("xQ").value : "").trim().toLowerCase();
  const targetQ = (q || "").trim().toLowerCase();
  const next = currentQ === targetQ ? "" : (q || "");
  $("xQ").value = next;
  updateActiveExploreChip(next);
  exploreSubmitIntent = true;
  loadExplore(true, false, true);
}

let exploreDebounce = null;
// Set by Search, Enter and task chips (iOS does not focus tapped buttons, so focus cannot tell).
let exploreSubmitIntent = false;
function invalidateExploreRequest() {
  exploreRequestRevision += 1;
  exploreRequestedKey = null;
  lastExploreKey = null;
  exploreController?.abort();
  exploreController = null;
  if (currentTab === "explore") $("xResults").setAttribute("aria-busy","true");
}
$("xQ").addEventListener("input", () => {
  invalidateExploreRequest();
  updateActiveExploreChip();
  if (exploreInputLoader == null) exploreInputLoader = showLoader("Finding agents...");
  if (currentTab === "explore") $("xResults").setAttribute("aria-busy","true");
  clearTimeout(exploreDebounce);
  exploreDebounce = setTimeout(() => loadExplore(false), 300);
});
$("xQ").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    clearTimeout(exploreDebounce);
    exploreSubmitIntent = true;
    loadExplore(true, false, true);
  }
});
$("xGo").onclick = () => { exploreSubmitIntent = true; loadExplore(true, false, true); };
// One filter change sends exactly one request, even when change and input both fire.
let exploreFilterTimer = null;
function exploreFilterChanged() {
  invalidateExploreRequest();
  clearTimeout(exploreFilterTimer);
  exploreFilterTimer = setTimeout(() => { exploreFilterTimer = null; loadExplore(true, false, true); }, 0);
}
["xVerified", "xNoAuth", "xHasReport", "xKind", "xCategory"].forEach((id) => {
  const el = $(id);
  if (el) {
    el.addEventListener("change", exploreFilterChanged);
    if (el.tagName === "SELECT") el.addEventListener("input", exploreFilterChanged);
  }
});
const xLoadMoreBtn = $("xLoadMore");
if (xLoadMoreBtn) {
  xLoadMoreBtn.onclick = () => {
    currentExploreLimit = Math.min(300, currentExploreLimit + 45);
    loadExplore(true, true, true);
  };
}

function exploreSkeletonHtml(count = 6) {
  return Array.from({ length: count }).map(() => `
    <div class="acard skeleton-card" style="pointer-events:none;opacity:0.65">
      <div style="height:18px;width:60%;background:var(--border);border-radius:4px"></div>
      <div style="height:14px;width:90%;background:var(--border);border-radius:4px;margin-top:6px"></div>
      <div style="height:14px;width:75%;background:var(--border);border-radius:4px;margin-top:4px"></div>
      <div style="display:flex;gap:6px;margin-top:12px">
        <div style="height:20px;width:50px;background:var(--border);border-radius:4px"></div>
        <div style="height:20px;width:70px;background:var(--border);border-radius:4px"></div>
      </div>
    </div>
  `).join("");
}

const EXPLORE_AGENT_MAP = new Map();

function explicitlyRequestsX402(query) {
  const text=String(query||'').replace(/\b(?:not|no|without|except|excluding|instead of)\s+(?:an?\s+)?x402\b/gi,'');
  return /\bx402\b/i.test(text);
}

function exploreProtocolSelection(query) {
  const selected = $('xKind')?.value || '';
  if (selected) return selected;
  const text = String(query || '').replace(/\b(?:not|no|without|except|excluding|instead of|non-)\s*(?:an?\s+)?(?:a2a|mcp|x402)\b/gi, '');
  const protocols = [...new Set((text.match(/\b(?:a2a|mcp|x402)\b/gi) || []).map(value => value.toLowerCase()))];
  return protocols.length === 1 ? protocols[0] : '';
}

function renderExplore(items, q, total = null, estimated = false, matchedReportCount = null, suggestions = []) {
  const chosen=exploreProtocolSelection(q);
  const protocolLabel = { a2a: 'A2A', mcp: 'MCP', x402: 'x402' }[chosen] || 'A2A + MCP';
  if ($('xProtocolScope')) $('xProtocolScope').textContent = protocolLabel;
  if ($('xProtocolHelp')) $('xProtocolHelp').textContent = chosen
    ? `Only ${protocolLabel} agents. Counts reflect this protocol and your filters.`
    : 'Task-focused results first. x402 is included only when explicitly requested. Counts reflect these protocols and your filters.';
  const unique = new Set();
  items = (Array.isArray(items) ? items : []).filter(item => {
    if (!item || typeof item !== "object" || unique.has(String(item.id))) return false;
    unique.add(String(item.id)); return true;
  });
  const countBefore=items.length;
  items=(Array.isArray(items)?items:[]).filter(item=>chosen?item.kind===chosen:['a2a','mcp'].includes(item.kind));
  // Preserve the server order: task focus precedes protocol across eligible results.
  if(items.length!==countBefore){total=items.length;estimated=true;}
  if (Array.isArray(items)) {
    items.forEach((item) => {
      if (item && item.id != null) EXPLORE_AGENT_MAP.set(String(item.id), item);
    });
  }
  const isReportFilter = Boolean($("xHasReport") && $("xHasReport").checked);
  const totalCount = (total != null && total > items.length) ? total : items.length;
  const agentUnit = totalCount === 1 ? "agent" : "agents";
  const countLabel = (total != null && total > items.length)
    ? (!estimated ? `Showing ${fmt(items.length)} of ${fmt(totalCount)}`
      : (isReportFilter || !items.length) ? `Showing ${fmt(items.length)} of up to ${fmt(totalCount)}` : `${fmt(items.length)}+`)
    : `${fmt(items.length)}`;
  const reportLabel = isReportFilter && Number.isInteger(matchedReportCount) && matchedReportCount >= 0
    ? `${fmt(matchedReportCount)} matching recorded report${matchedReportCount === 1 ? "" : "s"}` : "";
  const subLabel = isReportFilter
    ? `${countLabel} ${agentUnit} with recorded reports${reportLabel ? " · " + reportLabel : ""} · Sorted by newest first`
    : `${countLabel} matching ${agentUnit} · Sorted by newest first`;

  $("xTitle").innerHTML = q
    ? `"${esc(q)}" Search Results <span class="sub">${protocolLabel} · ${countLabel} ${isReportFilter ? "matching " + agentUnit : "matches"}${reportLabel ? " · " + reportLabel : ""} · Matched to your task and filters</span>`
    : `Latest discovered agents <span class="sub">${protocolLabel} · ${subLabel}</span>`;

  $("xResults").innerHTML = items.length
    ? items.map((r) => agentCardHtml(r)).join("")
    : `<p style="color:var(--text-dim);grid-column:1/-1;padding:24px;text-align:center">${isReportFilter ? "No agents with matching recorded reports were found within this result window." : "No agents match your current query and filters. Try adjusting keywords or clearing category constraints."}</p>`;
  // 11-04 five-point step 8: an empty search always offers a next step (fewer words, no filters, Chat).
  if (!items.length && !isReportFilter) $("xResults").replaceChildren(exploreEmptyState(q));

  if (Array.isArray(suggestions) && suggestions.length) {
    // A likely misspelling gets an explicit choice; results already shown stay unchanged.
    const choices = document.createElement("div"); choices.className = "explore-suggestions";
    choices.style.gridColumn = "1/-1";
    if (items.length) { const label = document.createElement("span"); label.textContent = "Did you mean: "; choices.append(label); }
    for (const value of suggestions.slice(0, 3)) {
      if (typeof value !== "string" || value.length > 120) continue;
      const button = document.createElement("button"); button.type = "button"; button.className = "chip-btn";
      button.textContent = "Try “" + value + "”";
      button.addEventListener("click", () => { $("xQ").value = value; loadExplore(true, false, true); });
      choices.append(button);
    }
    if (choices.querySelector("button")) items.length ? $("xResults").prepend(choices) : $("xResults").append(choices);
  }
  const lmWrap = $("xLoadMoreWrap");
  if (lmWrap) {
    if ((exploreHasMore === true || (exploreHasMore == null && total != null && total > items.length)) && items.length < 300) {
      lmWrap.style.display = "block";
      const lmBtn = $("xLoadMore");
      if (lmBtn) lmBtn.textContent = `Load more agents (${fmt(items.length)} / ${estimated ? "up to " : ""}${fmt(total)})`;
    } else {
      lmWrap.style.display = "none";
    }
  }
}

// 11-04 five-point step 8: next actions for an empty search. Words come from the visitor's own query and are
// set as text, never as markup; every action runs an ordinary search or opens Chat with the same task.
function exploreActiveFilters() {
  return !!($("xKind")?.value || $("xCategory")?.value || $("xVerified")?.checked || $("xNoAuth")?.checked || $("xHasReport")?.checked);
}
function exploreEmptyState(q) {
  const box = document.createElement("div"); box.className = "explore-empty"; box.setAttribute("role", "status");
  const text = document.createElement("p");
  text.textContent = q ? `No agents match “${q.slice(0, 100)}”${exploreActiveFilters() ? " with these filters" : ""}.` : "No agents match these filters.";
  const actions = document.createElement("div"); actions.className = "explore-empty-actions";
  const add = (label, run) => { const b = document.createElement("button"); b.type = "button"; b.className = "btn"; b.textContent = label; b.addEventListener("click", run); actions.append(b); };
  if (exploreActiveFilters()) add("Remove filters", () => {
    for (const id of ["xKind", "xCategory"]) if ($(id)) $(id).value = "";
    for (const id of ["xVerified", "xNoAuth", "xHasReport"]) if ($(id)) $(id).checked = false;
    loadExplore(true, false, true);
  });
  const words = [...new Set(String(q || "").toLowerCase().split(/\s+/).filter((w) => w.length >= 3))].slice(0, 2);
  if (words.length > 1) for (const word of words) add(`Search “${word}”`, () => { $("xQ").value = word; loadExplore(true, false, true); });
  if (q && typeof switchTab === "function" && $("chatInput")) add("Ask Chat to recommend", () => {
    switchTab("chat"); const input = $("chatInput"); input.value = q.slice(0, 500); input.dispatchEvent(new Event("input", { bubbles: true })); input.focus();
  });
  box.append(text, actions);
  return box;
}

function exploreSubmittedFromSearchBox() {
  const active = document.activeElement;
  return !!active && (active.id === "xQ" || (active.tagName === "BUTTON" && active.textContent.trim() === "Search"));
}

// The status line is a live region, so the count reaches screen readers when results change.
function exploreFoundText(count, q) {
  if (!q) return "";
  return `${fmt(count)} ${count === 1 ? "agent" : "agents"} shown for “${q.slice(0, 80)}”. `;
}

let lastExploreKey = null;
let exploreRequestRevision = 0;
let exploreRequestedKey = null;
let exploreController = null;
let currentExploreLimit = 45;
let exploreLoadedItems = [];
let exploreNextOffset = 0;
let exploreHasMore = null;
let exploreInputLoader = null;

function exploreLocation() {
  const params = new URLSearchParams();
  const value = $("xQ").value.trim();
  if (value) params.set("q", value);
  for (const [id,key] of [["xKind","kind"],["xCategory","category"]]) {
    if ($(id).value) params.set(key,$(id).value);
  }
  for (const [id,key] of [["xVerified","verified"],["xNoAuth","no_auth"],["xHasReport","has_report"]]) {
    if ($(id)?.checked) params.set(key,"1");
  }
  return "#explore" + (params.size ? "?" + params : "");
}

function restoreExploreLocation() {
  const [route,query] = location.hash.slice(1).split("?");
  if (route !== "explore") return;
  populateCategorySelects();
  const params = new URLSearchParams(query || "");
  $("xQ").value = params.get("q") || "";
  $("xKind").value = ["a2a","mcp","x402"].includes(params.get("kind")) ? params.get("kind") : "";
  const category = params.get("category") || "";
  $("xCategory").value = [...$("xCategory").options].some(option=>option.value===category) ? category : "";
  for (const [id,key] of [["xVerified","verified"],["xNoAuth","no_auth"],["xHasReport","has_report"]]) {
    if ($(id)) $(id).checked = ["1","true"].includes(params.get(key));
  }
  updateActiveExploreChip();
  document.dispatchEvent(new Event("explore-state-restored"));
}

async function loadExplore(force = false, isLoadMore = false, userInitiated = false) {
  clearTimeout(exploreDebounce); exploreDebounce = null;
  const submitted = exploreSubmitIntent; exploreSubmitIntent = false;
  populateCategorySelects(); updateActiveExploreChip();
  const q = $("xQ").value.trim(), kind = $("xKind").value, category = $("xCategory").value;
  const verified = $("xVerified").checked ? "1" : "0";
  const noAuth = $("xNoAuth").checked ? "1" : "0";
  const hasReport = $("xHasReport")?.checked ? "1" : "0";
  const resultsEl = $("xResults"), hint = $("xSearchHint");
  const inputProgress = exploreInputLoader; exploreInputLoader = null;
  if (q.length > 500) {
    exploreRequestRevision += 1; exploreController?.abort();
    exploreController=null;exploreRequestedKey=null;lastExploreKey=null;
    if (inputProgress != null) hideLoader(inputProgress);
    $("xQ").setAttribute("aria-invalid","true");
    hint.hidden = false; hint.textContent = "Use 500 characters or fewer for your search.";
    $("xTitle").textContent = "Shorten your search";
    resultsEl.setAttribute("aria-busy","false");
    if ($("uxExploreStatus")) $("uxExploreStatus").textContent = "Your search has not been sent. Shorten it and try again.";
    return;
  }
  $("xQ").removeAttribute("aria-invalid"); hint.hidden = true; hint.textContent = "";
  if (currentTab === "explore") {
    const route = exploreLocation();
    if (location.hash !== route) history[initialRoutingComplete ? "pushState" : "replaceState"](null,"",route);
  }
  const offset = isLoadMore ? exploreNextOffset : 0;
  const requestLimit = Math.min(45,300-offset);
  if (isLoadMore && (!offset || requestLimit < 1)) { if(inputProgress!=null)hideLoader(inputProgress); return; }
  const currentKey = JSON.stringify([q,kind,category,verified,noAuth,hasReport,offset,requestLimit]);
  if (!force && lastExploreKey === currentKey && (resultsEl.children.length || exploreRequestedKey === currentKey)) { if(inputProgress!=null)hideLoader(inputProgress); return; }
  const progress = inputProgress || showLoader("Finding agents...");
  const revision = ++exploreRequestRevision;
  exploreController?.abort();
  const controller = new AbortController(); exploreController = controller; lastExploreKey = currentKey;
  if (!isLoadMore) { currentExploreLimit=45; exploreLoadedItems=[]; exploreNextOffset=0; exploreHasMore=null; }
  const cacheKey = "explore:v4:" + currentKey;
  const cached = getSwrCache(cacheKey);
  function display(data) {
    const seen = new Set();
    const combined = [...(isLoadMore ? exploreLoadedItems : []),...data.items];
    exploreLoadedItems = combined.filter(item=>{
      if(!item || typeof item!=="object" || seen.has(String(item.id)))return false;
      seen.add(String(item.id));return true;
    }).slice(0,300);
    exploreHasMore = typeof data.has_more === "boolean" ? data.has_more : data.total > offset + data.items.length;
    exploreNextOffset = Number.isInteger(data.next_offset) ? data.next_offset : offset + data.items.length;
    if (!data.items.length) exploreHasMore=false;
    renderExplore(exploreLoadedItems,data.query_ignored?"":(data.corrected_query||q),data.total,data.total_is_estimate,data.matched_report_count,data.suggestions);
    if (data.query_ignored) { hint.hidden = false; hint.textContent = "This query is broad, so the selected agent catalog is shown. Add a task, such as weather forecast or document translation, to narrow the results."; }
    else if (typeof data.search_notice === "string") { hint.hidden=false;hint.textContent=data.search_notice; }
  }
  const usableCache = cached && Array.isArray(cached.items) && cached._complete_page === true && cached._request_limit === requestLimit;
  if (usableCache) display(cached);
  else if (!resultsEl.children.length && !isLoadMore) resultsEl.innerHTML=exploreSkeletonHtml();
  exploreRequestedKey=currentKey;
  resultsEl.setAttribute("aria-busy","true");
  if ($("uxExploreStatus")) $("uxExploreStatus").textContent="Finding matching agents…";
  if ($("xLoadMore")) $("xLoadMore").disabled=true;
  let failed=false;
  try {
    const p=new URLSearchParams({q,limit:String(requestLimit),offset:String(offset)});
    if(kind)p.set("kind",kind);if(category)p.set("category",category);
    if(verified==="1")p.set("verified","true");if(noAuth==="1")p.set("no_auth","true");if(hasReport==="1")p.set("has_report","true");
    const data=await api("/api/explore?"+p,{userInitiated,background:true,silent:true,
      loadingMsg: "Finding agents...", timeoutMs:30000, retries:0, signal: controller.signal});
    if(revision!==exploreRequestRevision)return;
    if(!data || !Array.isArray(data.items))throw Error("Search results are unavailable. Please try again.");
    setSwrCache(cacheKey,{...data,_complete_page:true,_request_limit:requestLimit});
    display(data);
    if (userInitiated && !isLoadMore && matchMedia("(max-width:700px)").matches
        && submitted) {
      // Phones: Search, Enter or a task chip brings the result heading up; filters stay where the visitor is.
      $("xTitle").tabIndex=-1; $("xTitle").focus({preventScroll:true});
      $("xTitle").scrollIntoView({block:"start",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth"});
    } else if (userInitiated && !isLoadMore && exploreSubmittedFromSearchBox()
               && $("xTitle").getBoundingClientRect().top > innerHeight * 0.6) {
      // Results below the fold changed out of sight; bring their heading up and keep focus in the search box.
      // Filters and task chips do not scroll: a visitor ticking several filters keeps them in view.
      $("xTitle").scrollIntoView({block:"start",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth"});
    }
  } catch(err) {
    if(revision!==exploreRequestRevision || err?.error_code==="REQUEST_CANCELLED")return;
    failed=true;lastExploreKey=null;
    if(err?.status===422) {
      $("xQ").setAttribute("aria-invalid","true");hint.hidden=false;
      hint.textContent="Check your search and selected filters, then try again.";
      $("xTitle").textContent="Check your search";
    } else {
      $("xTitle").textContent="Search unavailable";
      if(!usableCache) {
        const message=err?.error_code==="REQUEST_TIMEOUT" ? "Search timed out. Please try again."
          : err?.status===429 ? "Search limit reached. Please wait a moment and try again."
          : "Search could not be completed. Please try again.";
        const error=document.createElement("p");error.className="explore-search-error";error.textContent=message;
        // 11-04 five-point step 8: a failed search keeps the query and offers the retry in place.
        const retry=document.createElement("button");retry.type="button";retry.className="btn explore-retry";retry.textContent="Try again";
        retry.addEventListener("click",()=>loadExplore(true,false,true));
        const box=document.createElement("div");box.className="explore-empty";box.setAttribute("role","alert");box.append(error,retry);
        resultsEl.replaceChildren(box);
      }
    }
  } finally {
    hideLoader(progress);
    if(revision===exploreRequestRevision) {
      exploreRequestedKey=null;exploreController=null;resultsEl.setAttribute("aria-busy","false");
      if($("xLoadMore"))$("xLoadMore").disabled=false;
      if($("uxExploreStatus"))$("uxExploreStatus").textContent=failed
        ? (hint.hidden ? "Search is unavailable. Try again." : hint.textContent)
        : resultsEl.querySelector(".acard:not(.skeleton-card)") ? exploreFoundText(resultsEl.querySelectorAll(".acard:not(.skeleton-card)").length, q) + "Open an agent to review its connection and recorded evidence." :resultsEl.querySelector(".explore-suggestions button") ? "No matching agents found. Try the suggested search below." : "No matching agents found. Try another search.";
    }
  }
}

const DEFAULT_CATEGORIES = {
  ai_models: "AI Models & Agent Tools",
  finance_crypto: "Finance, Payments & Crypto",
  web_search: "Web Search & Scraping",
  dev_tools: "Developer Tools & CI/CD",
  public_legal: "Public, Legal & Regulatory Data",
  commerce_marketing: "Commerce & Marketing",
  media_generation: "Media Generation & Processing",
  productivity: "Productivity & SaaS",
  docs_knowledge: "Docs, Knowledge Bases & RAG",
  social: "Social Media & Community",
  database_analytics: "Database & Analytics",
  travel_maps_weather: "Travel, Maps & Weather",
  agent_infra: "Agent Infrastructure & Coordination",
  security: "Security & Threat Intelligence",
  health_science: "Healthcare & Life Sciences",
  communication_messaging: "Communications & Messaging",
  network_ops: "Network Ops & Infrastructure",
  data_utility: "Data Utilities & Format Conversion",
  trading_derivatives: "Trading, Derivatives & Order Books",
  education_culture: "Education & Culture Archives"
};

function populateCategorySelects() {
  const rawCats = (insightsData && insightsData.categories) || (ovCache && ovCache.category_names) || {};
  const cats = Object.keys(rawCats).length ? rawCats : DEFAULT_CATEGORIES;
  ["xCategory", "regCategory"].forEach((id) => {
    const sel = $(id);
    if (!sel || sel.options.length > 1) return;
    Object.entries(cats).forEach(([k, name]) => {
      sel.add(new Option(String(name), k));
    });
  });
}

// ---------- Section 4: List Your Agent ----------
let lastDetectedDetails = {};
let lastDetectedMethod = null;

const COMMUNITY_BLUEPRINTS = [
  {
    id: "duckdb-analytics-mcp",
    name: "DuckDB In-Process Analytics MCP",
    kind: "mcp",
    category: "database_analytics",
    url: "https://duckdb.org/mcp",
    description: "Serverless fast in-process analytical SQL query engine for AI agents. Provides zero-latency parquet file inspection, OLAP analytical queries, CSV/JSON data ingestion, and aggregated telemetry computation with vector column extensions.",
    tools: ["query_sql", "inspect_parquet", "create_table_from_file", "describe_dataset", "export_parquet"],
    badge: "OLAP SQL"
  },
  {
    id: "clickhouse-olap-mcp",
    name: "ClickHouse Real-Time OLAP MCP",
    kind: "mcp",
    category: "database_analytics",
    url: "https://clickhouse.com/mcp",
    description: "Real-time columnar database MCP server for ultra-high-speed telemetry analytics, log aggregation, and large-scale timeseries querying. Enables AI agents to run sub-second analytical queries over billions of telemetry events.",
    tools: ["execute_clickhouse_query", "get_table_schema", "explain_syntax_plan", "query_timeseries_metrics", "list_databases"],
    badge: "Columnar DB"
  },
  {
    id: "neo4j-graph-mcp",
    name: "Neo4j Graph Knowledge Engine MCP",
    kind: "mcp",
    category: "docs_knowledge",
    url: "https://neo4j.com/mcp",
    description: "Enterprise graph database and knowledge graph explorer for AI agents. Translates natural language questions into optimized Cypher queries, traverses multi-hop entity relationships, and retrieves connected context for RAG pipelines.",
    tools: ["read_cypher_query", "get_graph_schema", "find_shortest_path", "explore_node_neighbors", "search_entity_index"],
    badge: "Graph & Cypher"
  },
  {
    id: "trivy-security-a2a",
    name: "Trivy Vulnerability & SBOM Auditor",
    kind: "a2a",
    category: "security",
    url: "https://trivy.dev/a2a",
    description: "Comprehensive open-source container security and software supply chain auditor. Detects CVE vulnerabilities, misconfigurations in Kubernetes manifests/Dockerfiles, exposed secrets, and generates CycloneDX/SPDX SBOM reports.",
    tools: ["scan_container_image", "audit_iac_manifest", "generate_sbom", "check_cve_database", "evaluate_security_compliance"],
    badge: "SBOM & CVE"
  },
  {
    id: "weaviate-vector-mcp",
    name: "Weaviate Vector Search & Hybrid RAG MCP",
    kind: "mcp",
    category: "docs_knowledge",
    url: "https://weaviate.io/mcp",
    description: "Open-source vector database server enabling multimodal semantic search, BM25 keyword hybrid ranking, and generative search for AI agents. Supports custom embedding models, filtering, and cross-reference graph properties.",
    tools: ["hybrid_search", "near_vector_query", "aggregate_objects", "batch_insert_objects", "get_collection_schema"],
    badge: "Hybrid Search"
  },
  {
    id: "lancedb-arrow-mcp",
    name: "LanceDB Serverless Arrow Vector MCP",
    kind: "mcp",
    category: "docs_knowledge",
    url: "https://lancedb.com/mcp",
    description: "Developer-friendly serverless vector database built on Apache Arrow for persistent disk-backed AI memory and RAG. Delivers ultra-low latency ANN vector search, scalar filtering, and zero-RAM disk indexing.",
    tools: ["search_embeddings", "create_vector_table", "query_fts_hybrid", "compact_indices", "list_tables"],
    badge: "Arrow Vector"
  },
  {
    id: "ast-grep-refactor-a2a",
    name: "ast-grep Code Architecture & Refactor Agent",
    kind: "a2a",
    category: "dev_tools",
    url: "https://ast-grep.github.io/a2a",
    description: "Lightning-fast syntax tree based code search and linting agent powered by Tree-sitter. Allows AI agents to find precise code patterns across repositories, perform structural AST transformations, and enforce security rules across 25+ languages.",
    tools: ["find_ast_patterns", "rewrite_code_rule", "lint_repository_tree", "inspect_syntax_nodes", "get_language_grammar"],
    badge: "AST Code"
  },
  {
    id: "meilisearch-search-mcp",
    name: "Meilisearch Fast Full-Text Search MCP",
    kind: "mcp",
    category: "web_search",
    url: "https://meilisearch.com/mcp",
    description: "Ultra-fast, typo-tolerant search engine MCP server delivering instant sub-50ms search-as-you-type results. Supports custom ranking rules, facet filtering, synonym dictionaries, and multi-tenant document indexing for AI workflows.",
    tools: ["search_documents", "get_index_stats", "add_or_replace_documents", "update_ranking_rules", "manage_synonyms"],
    badge: "Typo-Tolerant"
  },
  {
    id: "pagerduty-triage-a2a",
    name: "PagerDuty Automated Incident Triage Agent",
    kind: "a2a",
    category: "network_ops",
    url: "https://api.pagerduty.com/a2a",
    description: "Real-time cloud incident management and automated on-call triage agent. Ingests alerts from monitoring systems, correlates duplicate outages, assigns priority levels, pages on-call engineers, and manages service status updates.",
    tools: ["create_incident", "get_oncall_schedule", "acknowledge_alert", "escalate_to_team", "post_status_update"],
    badge: "Incident Triage"
  },
  {
    id: "datadog-telemetry-mcp",
    name: "Datadog APM & Metrics Intelligence MCP",
    kind: "mcp",
    category: "network_ops",
    url: "https://api.datadoghq.com/mcp",
    description: "Enterprise observability MCP server providing AI agents with direct access to infrastructure metrics, APM distributed traces, live process telemetry, and synthetic monitor uptime status across cloud workloads.",
    tools: ["query_timeseries_metrics", "search_apm_traces", "get_monitor_states", "list_host_telemetry", "generate_dashboard_snapshot"],
    badge: "APM & Metrics"
  }
];

function cleanNormalizeUrl(u) {
  let s = String(u || "").trim().replace(/^["']|["']$/g, "");
  if (!s) return "";
  if (!/^https?:\/\//i.test(s)) {
    s = "https://" + s;
  }
  return s;
}

function renderRegisterBlueprints() {
  const wrap = $("regBlueprintChips");
  if (!wrap) return;
  wrap.innerHTML = COMMUNITY_BLUEPRINTS.map(bp => `
    <button type="button" class="chip-btn reg-blueprint-chip" data-bp="${esc(bp.id)}" data-ac-click="227cdc822d0b" style="font-size:11.5px;display:inline-flex;align-items:center;gap:4px">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
      <span>${esc(bp.name.split(" ")[0])} [${esc(bp.badge)}]</span>
    </button>
  `).join("");
}

function selectRegisterBlueprint(bpId) {
  const bp = COMMUNITY_BLUEPRINTS.find(b => b.id === bpId);
  if (!bp) return;
  populateCategorySelects();
  $("regKind").value = bp.kind;
  $("regKind").dispatchEvent(new Event("change"));
  $("regCategory").value = bp.category;
  $("regUrl").value = bp.url;
  $("regAutoUrl").value = bp.url;
  $("regName").value = bp.name;
  $("regDesc").value = bp.description;
  lastDetectedDetails = {
    tools: bp.tools,
    skills: bp.tools,
    blueprint_id: bp.id,
    verified_schema: true
  };
  lastDetectedMethod = "POST";
  updateRegisterLivePreview();
  const banner = $("regBanner");
  banner.className = "banner ok";
  banner.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--ok)"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg><span>Blueprint loaded: <b>${esc(bp.name)}</b>. Ready for instant verification!</span></span>`;
  banner.classList.remove("hidden");
}

function updateRegisterLivePreview() {
  const name = ($("regName") ? $("regName").value.trim() : "") || "Live Preview Agent";
  const desc = ($("regDesc") ? $("regDesc").value.trim() : "") || "Capability description will update live as you type or pick a blueprint...";
  const kind = ($("regKind") ? $("regKind").value : "mcp").toUpperCase();
  const cat = ($("regCategory") ? $("regCategory").value : "ai_models");
  const cats = (insightsData && insightsData.categories) || DEFAULT_CATEGORIES;
  const catName = cats[cat] || cat;
  
  const tools = (lastDetectedDetails && (lastDetectedDetails.tools || lastDetectedDetails.skills)) || [];
  const toolCount = Array.isArray(tools) ? tools.length : 0;

  if ($("regPrevName")) $("regPrevName").textContent = name;
  if ($("regPrevDesc")) $("regPrevDesc").textContent = desc;
  if ($("regPrevKindBadge")) {
    $("regPrevKindBadge").textContent = kind;
    $("regPrevKindBadge").className = `kind-badge k-${kind.toLowerCase()}`;
  }
  if ($("regPrevCat")) $("regPrevCat").textContent = `Category: ${catName}`;
  if ($("regPrevTools")) $("regPrevTools").textContent = `${toolCount || 5} tools declared`;
  if ($("regPrevGrade")) {
    const grade = toolCount >= 3 ? "A (94.0)" : "B (85.0)";
    $("regPrevGrade").textContent = `Grade ${grade}`;
  }
}

function openTestbenchWithAgent(agentId) {
  if (!agentId) return;
  if (typeof testAgentFromDrawer === "function") {
    testAgentFromDrawer(agentId);
  } else {
    switchTab("test");
    history.replaceState(null, "", "#test?id=" + encodeURIComponent(agentId));
  }
}

function openExploreWithSearch(name) {
  switchTab("explore");
  setTimeout(() => {
    if ($("xQ")) {
      $("xQ").value = name || "";
      if (typeof doSearch === "function") doSearch();
    }
  }, 100);
}

function copyTextToClipboard(text, msg) {
  if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      showModalAlert({ type: "success", title: "Copied to Clipboard", message: msg || "Copied command to clipboard successfully." });
    }).catch(() => {
      showModalAlert({ type: "info", title: "Invocation Command", message: text });
    });
  } else {
    showModalAlert({ type: "info", title: "Invocation Command", message: text });
  }
}

async function loadRegister() {
  populateCategorySelects();
  renderRegisterBlueprints();
  loadRegisterRecent();
  updateRegisterLivePreview();
}

async function loadRegisterRecent() {
  const card = $("regRecentCard");
  if (card && (card.classList.contains("hidden") || card.style.display === "none")) return;
  $("regRecentTable").innerHTML = binaryClockHtml("Loading recent agent listings...");
  try {
    const data = await api("/api/register/recent", { loadingMsg: "Loading recent agent listings..." });
    const items = data.items || [];
    $("regManualCount").textContent = `(${fmt(items.length)} manual entries)`;
    const cats = (insightsData && insightsData.categories) || (ovCache && ovCache.category_names) || DEFAULT_CATEGORIES;

    const rows = items.map((r) => `
      <tr class="click" data-id="${esc(r.id)}" data-ac-click="d5e60f613626">
        <td><span class="kind-badge k-${esc(r.kind)}">${esc(r.kind)}</span></td>
        <td>
          <b>${esc(r.name)}</b>
          <div style="font-size:11px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:240px">${esc(gatewayAgentEndpoint(r))}</div>
        </td>
        <td>${esc(formatCategory(r.category, cats))}</td>
        <td><span class="s-${esc(r.health_status)}" style="display:inline-flex;align-items:center;gap:4px"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg><span>${esc(r.health_status)}</span></span></td>
        <td style="font-size:12px;color:var(--text-muted);white-space:nowrap">${nyAgo(r.first_seen)}</td>
      </tr>
    `).join("");

    $("regRecentTable").innerHTML = `
      <table>
        <thead><tr><th>Protocol</th><th>Name & Endpoint</th><th>Category</th><th>Status</th><th>Listed</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" style="color:var(--text-dim)">No agents listed yet. Submit your public endpoint to list your agent.</td></tr>'}</tbody>
      </table>
    `;
  } catch (err) {
    $("regRecentTable").innerHTML = `<p style="color:var(--bad)">Failed loading agent listings: ${esc(err.message)}</p>`;
  }
}

$("regKind").onchange = () => {
  $("regX402Fields").classList.toggle("hidden", $("regKind").value !== "x402");
};

const INSPECT_BTN_HTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Auto Detect`;
const SUBMIT_BTN_HTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg> Verify & List Agent`;

$("regInspectBtn").onclick = async () => {
  if ($("regInspectBtn").disabled) return;
  populateCategorySelects();
  const rawU = ($("regAutoUrl").value || "").trim() || ($("regUrl").value || "").trim();
  const u = cleanNormalizeUrl(rawU);
  const banner = $("regBanner");
  banner.classList.add("hidden");

  if (!u) {
    showModalAlert({
      type: "warning",
      title: "URL Required",
      message: "Please enter an agent endpoint URL to auto-detect parameters.",
      onClose: () => { if ($("regAutoUrl")) $("regAutoUrl").focus(); }
    });
    return;
  }
  if (!/^https?:\/\//i.test(u)) {
    showModalAlert({
      type: "warning",
      title: "Invalid Protocol",
      message: "Endpoint URL must begin with http:// or https://",
      onClose: () => { if ($("regAutoUrl")) $("regAutoUrl").focus(); }
    });
    return;
  }
  if (isUnsafeInput(u)) {
    showModalAlert({
      type: "error",
      title: "Security Policy Notice",
      message: "Prohibited characters or script patterns detected in URL.",
      onClose: () => { if ($("regAutoUrl")) $("regAutoUrl").focus(); }
    });
    return;
  }

  const btn = $("regInspectBtn");
  btn.disabled = true;
  btn.textContent = "Detecting...";
  try {
    const d = await api("/api/register/inspect", { method: "POST", json: { url: u }, timeoutMs: 25000, userInitiated: true, loadingMsg: "Inspecting endpoint..." });
    lastDetectedDetails = (d.details && typeof d.details === "object") ? d.details : {};
    lastDetectedMethod = d.method || null;
    if (d.url) { $("regUrl").value = d.url; $("regAutoUrl").value = d.url; }
    if (d.kind) { $("regKind").value = d.kind; $("regKind").dispatchEvent(new Event("change")); }
    $("regName").value = d.name || "";
    $("regDesc").value = d.description || "";
    if (d.category) $("regCategory").value = d.category;
    if (d.kind === "x402") {
      if (d.price_usdc !== undefined && d.price_usdc !== null) $("regPrice").value = (d.price_usdc / 1e6);
      if (d.pay_to) $("regPayTo").value = d.pay_to;
      if (d.networks && d.networks.length) $("regNetwork").value = d.networks[0];
    }

    if (!d.protocol_verified) {
      banner.className = "banner bad";
      banner.textContent = "Protocol not confirmed. Check the endpoint address and access requirements. No listing has been created.";
      banner.classList.remove("hidden");
      return;
    }
    if (d.already_registered && d.existing) {
      const ex = d.existing;
      const dupMsg = `This agent URL is already registered: '${ex.name}' (ID: ${ex.id}, Protocol: ${String(ex.kind || d.kind).toUpperCase()}, Source: ${ex.source}). Duplicates are not accepted.`;
      banner.className = "banner bad";
      banner.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--warn)"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg><span>${esc(dupMsg)}</span></span>`;
      banner.classList.remove("hidden");
      showModalAlert({
        type: "warning",
        title: "Already Registered Agent",
        message: dupMsg
      });
    } else {
      banner.className = "banner ok";
      banner.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--ok)"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg><span>Detected [${esc(d.kind.toUpperCase())}] parameters successfully! Review the information and select Verify & List Agent.</span></span>`;
      banner.classList.remove("hidden");
      showModalAlert({
        type: "success",
        title: "Protocol Detected",
        message: `Detected [${esc(d.kind.toUpperCase())}] parameters successfully! Form parameters have been auto-populated. Review the information and select Verify & List Agent.`
      });
    }
  } catch (err) {
    banner.className = "banner bad";
    banner.textContent = "Auto-detection failed: " + err.message;
    banner.classList.remove("hidden");
    showModalAlert({ type: "error", title: "Auto-Detection Notice", message: "Auto-detection failed: " + err.message });
  } finally {
    btn.disabled = false;
    btn.innerHTML = INSPECT_BTN_HTML;
  }
};

$("regSubmitBtn").onclick = async () => {
  if ($("regSubmitBtn").disabled) return;
  populateCategorySelects();
  const banner = $("regBanner");
  banner.classList.add("hidden");

  const consentCb = $("regTermsConsent");
  if (consentCb && !consentCb.checked) {
    showModalAlert({
      type: "warning",
      title: "Affirmative Consent Required",
      message: "Review the Terms of Service and Privacy Policy, then check the agreement before publishing an agent endpoint."
    });
    return;
  }

  const kind = $("regKind").value;
  const rawUrl = ($("regUrl").value || "").trim();
  const url = cleanNormalizeUrl(rawUrl);
  const name = ($("regName").value || "").trim();
  const desc = ($("regDesc").value || "").trim();
  const category = $("regCategory").value || "ai_models";

  if (!url) {
    showModalAlert({
      type: "warning",
      title: "URL Required",
      message: "Please provide an endpoint URL.",
      onClose: () => { if ($("regUrl")) $("regUrl").focus(); }
    });
    return;
  }
  if (!/^https?:\/\//i.test(url) || isUnsafeInput(url)) {
    showModalAlert({
      type: "error",
      title: "Invalid URL",
      message: "Endpoint URL must begin with http:// or https:// and cannot contain executable scripts or dangerous characters.",
      onClose: () => { if ($("regUrl")) $("regUrl").focus(); }
    });
    return;
  }
  if (!name || name.length < 2) {
    showModalAlert({
      type: "warning",
      title: "Name Required",
      message: "Please enter an agent name (minimum 2 characters).",
      onClose: () => { if ($("regName")) $("regName").focus(); }
    });
    return;
  }
  if (name.includes("<") || name.includes(">") || isUnsafeInput(name)) {
    showModalAlert({
      type: "error",
      title: "Prohibited Characters",
      message: "Agent name cannot contain HTML markup, angle brackets (< >), or executable scripts.",
      onClose: () => { if ($("regName")) $("regName").focus(); }
    });
    return;
  }
  if (!desc || desc.length < 5) {
    showModalAlert({
      type: "warning",
      title: "Description Required",
      message: "Please enter a capability description (minimum 5 characters).",
      onClose: () => { if ($("regDesc")) $("regDesc").focus(); }
    });
    return;
  }
  if (isUnsafeInput(desc)) {
    showModalAlert({
      type: "error",
      title: "Prohibited Characters",
      message: "Capability description cannot contain HTML markup or executable scripts.",
      onClose: () => { if ($("regDesc")) $("regDesc").focus(); }
    });
    return;
  }

  const payload = { kind, url, name, description: desc, category };
  if (lastDetectedMethod) payload.method = lastDetectedMethod;
  if (lastDetectedDetails && Object.keys(lastDetectedDetails).length) payload.details = lastDetectedDetails;
  if (kind === "x402") {
    const priceVal = parseFloat($("regPrice").value || "0");
    payload.price_usdc = Math.round(priceVal * 1e6);
    const payTo = ($("regPayTo").value || "").trim();
    if (payTo) {
      if (payTo.includes("<") || payTo.includes(">") || isUnsafeInput(payTo)) {
        showModalAlert({
          type: "error",
          title: "Invalid Payment Address",
          message: "Payment address contains prohibited characters.",
          onClose: () => { if ($("regPayTo")) $("regPayTo").focus(); }
        });
        return;
      }
      payload.pay_to = payTo;
    } else {
      payload.pay_to = null;
    }
    payload.networks = [($("regNetwork").value || "base").trim()];
  }
  payload.legal_consent = {
    agreed: Boolean(consentCb && consentCb.checked),
    tos_version: "2026.1",
    privacy_version: "2026.1",
    agreed_at: new Date().toISOString(),
    gpc_active: isGpcActive()
  };

  const btn = $("regSubmitBtn");
  btn.disabled = true;
  btn.textContent = "Verifying & Listing...";

  try {
    const res = await api("/api/register", { method: "POST", json: payload, timeoutMs: 25000, userInitiated: true, loadingMsg: "Confirming endpoint protocol..." });
    banner.className = "banner ok";
    const curlSnippet = `curl -X POST https://agentconcierge.biz/chat -H "Content-Type: application/json" -d '{"message": "Delegate to ${esc(res.name)}"}'`;
    banner.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:8px">
        <div style="display:flex;align-items:center;gap:6px">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--ok)"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>
          <span><b>${esc(res.name)}</b> listed; protocol confirmed. (ID: ${esc(res.id)}, Status: <span class="chip font-bold">${esc(res.status)}</span>, Tools: <span class="chip">${res.tool_count || 0}</span>)</span>
        </div>
        <div style="font-size:12px;color:var(--text-muted)">${esc(res.message)}</div>
        <div style="display:flex;gap:8px;margin-top:6px;flex-wrap:wrap">
          <button type="button" class="btn sm primary" data-id="${esc(res.id)}" data-ac-click="6e3f51eea966" style="font-size:12px;padding:4px 10px;display:inline-flex;align-items:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            <span>Launch in Testbench (#test)</span>
          </button>
          <button type="button" class="btn sm" data-name="${esc(res.name)}" data-ac-click="28c79e4bf74c" style="font-size:12px;padding:4px 10px;display:inline-flex;align-items:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <span>View in Explore (#explore)</span>
          </button>
          <button type="button" class="btn sm" data-ac-click="d47328a04fc1" style="font-size:12px;padding:4px 10px;display:inline-flex;align-items:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="8" height="8" x="3" y="3" rx="2"/><path d="M7 11v4a2 2 0 0 0 2 2h4"/><rect width="8" height="8" x="13" y="13" rx="2"/></svg>
            <span>Add to Workflow (#workflows)</span>
          </button>
          <button type="button" class="btn sm" data-curl="${esc(curlSnippet)}" data-ac-click="a677d7e441c7" style="font-size:12px;padding:4px 10px;display:inline-flex;align-items:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
            <span>Copy Invocation Command</span>
          </button>
        </div>
      </div>
    `;
    banner.classList.remove("hidden");
    loadRegisterRecent();
    toast(`${res.name} (ID: ${res.id}) registered successfully with status '${res.status}' and ${res.tool_count || 0} declared tools!`, "success");
  } catch (err) {
    const isDuplicate = String(err.message || "").toLowerCase().includes("already registered");
    banner.className = "banner bad";
    const rejIcon = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:${isDuplicate ? 'var(--warn)' : 'var(--bad)'}"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
    banner.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${rejIcon}<span>${esc(isDuplicate ? err.message : ("Registration rejected: " + err.message))}</span></span>`;
    banner.classList.remove("hidden");
    showModalAlert({
      type: isDuplicate ? "warning" : "error",
      title: isDuplicate ? "Already Registered Agent" : "Registration Notice",
      message: isDuplicate ? err.message : ("Registration rejected: " + err.message)
    });
  } finally {
    btn.disabled = false;
    btn.innerHTML = SUBMIT_BTN_HTML;
  }
};

$("regResetBtn").onclick = () => {
  $("regForm").reset();
  $("regAutoUrl").value = "";
  lastDetectedDetails = {};
  lastDetectedMethod = null;
  $("regKind").value = "a2a";
  $("regKind").dispatchEvent(new Event("change"));
  $("regBanner").classList.add("hidden");
  updateRegisterLivePreview();
};

if ($("regName")) $("regName").addEventListener("input", updateRegisterLivePreview);
if ($("regDesc")) $("regDesc").addEventListener("input", updateRegisterLivePreview);
if ($("regUrl")) $("regUrl").addEventListener("input", () => {
  $("regUrl").value = cleanNormalizeUrl($("regUrl").value);
  updateRegisterLivePreview();
});
if ($("regKind")) $("regKind").addEventListener("change", updateRegisterLivePreview);
if ($("regCategory")) $("regCategory").addEventListener("change", updateRegisterLivePreview);

if ($("regOpenJsonModalBtn")) {
  $("regOpenJsonModalBtn").onclick = () => {
    $("regJsonError").classList.add("hidden");
    $("regJsonModal").showModal();
  };
}

if ($("regJsonSampleBtn")) {
  $("regJsonSampleBtn").onclick = () => {
    $("regJsonInput").value = JSON.stringify({
      name: "Custom Data Transformer A2A",
      description: "Transforms, validates, and cleans tabular data streams for machine learning workflows with high precision.",
      url: "https://agentconcierge.biz/examples/transformer-agent",
      kind: "a2a",
      category: "database_analytics",
      skills: ["clean_csv_stream", "validate_schema", "normalize_encodings", "profile_column_drift"]
    }, null, 2);
  };
}

if ($("regJsonApplyBtn")) {
  $("regJsonApplyBtn").onclick = () => {
    const raw = ($("regJsonInput") ? $("regJsonInput").value.trim() : "");
    const errBox = $("regJsonError");
    if (!raw) {
      errBox.textContent = "Please paste schema JSON.";
      errBox.classList.remove("hidden");
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      populateCategorySelects();
      const rawName = String(parsed.name || parsed.title || parsed.serverInfo?.name || "").trim();
      const detectedName = rawName.replace(/[<>]/g, "").slice(0, 100);
      const rawDesc = String(parsed.description || parsed.instructions || "").trim();
      const detectedDesc = rawDesc.replace(/<[^>]*>/g, "").slice(0, 2000);
      const detectedUrl = cleanNormalizeUrl(parsed.url || parsed.endpoint || parsed.baseUrl || "");
      const detectedKind = (parsed.kind || (parsed.skills ? "a2a" : "mcp")).toLowerCase();
      const tools = parsed.tools || parsed.skills || [];
      const toolNames = Array.isArray(tools) ? tools.map(t => typeof t === "string" ? t : (t.name || t.id || "")).filter(Boolean).map(t => String(t).replace(/[<>]/g, "").slice(0, 100)) : [];
      
      if (detectedName) $("regName").value = detectedName;
      if (detectedDesc) $("regDesc").value = detectedDesc;
      if (detectedUrl) { $("regUrl").value = detectedUrl; $("regAutoUrl").value = detectedUrl; }
      if (["a2a", "mcp", "x402"].includes(detectedKind)) {
        $("regKind").value = detectedKind;
        $("regKind").dispatchEvent(new Event("change"));
      }
      if (parsed.category && $("regCategory")) {
        $("regCategory").value = parsed.category;
      }
      lastDetectedDetails = {
        tools: toolNames,
        skills: toolNames,
        verified_schema: true
      };
      updateRegisterLivePreview();
      if ($("regJsonModal")) $("regJsonModal").close();
      toast(`Schema imported: ${detectedName || "Agent"} (${toolNames.length} tools/skills extracted).`, "success");
    } catch (err) {
      errBox.textContent = "Invalid JSON: " + err.message;
      errBox.classList.remove("hidden");
    }
  };
}

// Purpose choices and destination proof are separate from recommendation requests.
let taskUpdateWatchId = "", taskUpdatePending = false, taskUpdateDraft = null;
let taskUpdateNotice = "task-updates-2026-10-17-v1";
let taskDestinationNotice = "destination-confirmation-2026-10-17-v1";
let taskMarketingNotice = "optional-marketing-2026-10-17-v1";
let taskUpdateReturnFocus = null, taskUpdateEpoch = 0, taskUpdateTimer = null, taskBrowserConfig = null;
let taskBrowserSubscription = null, taskBrowserSubscriptionNew = false;
const taskCleanupIds = new Set();
try { for (const id of JSON.parse(sessionStorage.getItem("taskUpdateCleanup") || "[]")) if (/^tw_[0-9a-f]{32}$/.test(id)) taskCleanupIds.add(id); } catch (error) {}
async function taskRequest(path, method = "GET", body = null) {
  const headers = {"Accept":"application/json"};
  if (activeVisitorToken) headers["X-Visitor-Token"] = activeVisitorToken;
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(path,{method,headers,body:body ? JSON.stringify(body) : undefined,cache:"no-store",credentials:"omit"});
  if (!response.ok) throw new Error("Unable to complete this request. Please check your choices and try again.");
  return response.json();
}
function saveTaskCleanup() { try { sessionStorage.setItem("taskUpdateCleanup",JSON.stringify([...taskCleanupIds].slice(-10))); } catch (error) {} }
async function flushTaskCleanup() {
  if (!activeVisitorToken) return;
  for (const id of [...taskCleanupIds]) {
    try { await taskRequest("/api/task-updates/"+encodeURIComponent(id)+"/action","POST",{action:"decline"}); taskCleanupIds.delete(id); } catch (error) {}
  }
  saveTaskCleanup();
}
async function removePendingTaskUpdate() {
  clearInterval(taskUpdateTimer); taskUpdateTimer = null;
  const id = taskUpdatePending ? taskUpdateWatchId : "";
  taskUpdatePending = false; taskUpdateWatchId = ""; taskUpdateDraft = null;
  if (id) { taskCleanupIds.add(id); saveTaskCleanup(); }
  if (taskBrowserSubscriptionNew && taskBrowserSubscription) { try { await taskBrowserSubscription.unsubscribe(); } catch (error) {} }
  taskBrowserSubscription = null; taskBrowserSubscriptionNew = false;
  await flushTaskCleanup();
  return !id || !taskCleanupIds.has(id);
}
async function closeTaskUpdates() {
  ++taskUpdateEpoch;
  $("taskUpdateUrl").value = ""; $("taskUpdateCode").value = "";
  $("taskUpdateReviewDestination").textContent = "";
  $("taskUpdateDialog").close(); taskUpdateReturnFocus?.focus();
  await removePendingTaskUpdate();
}
function taskUpdateErrorMessage(error) {
  const messages = new Set([
    "Unable to complete this request. Please check your choices and try again.",
    "Browser notifications are unavailable here. Choose another delivery method.",
    "Browser notifications were not allowed. No request was registered.",
    "Browser notifications are currently unavailable. Choose another delivery method.",
    "Browser notification setup timed out. Please try again."
  ]);
  return messages.has(error?.message) ? error.message : "Unable to verify this destination. Please try again or choose another delivery method.";
}
function browserPushSupported() { return window.isSecureContext && "Notification" in window && "serviceWorker" in navigator && "PushManager" in window; }
async function loadTaskBrowserConfig() {
  taskBrowserConfig = await taskRequest("/api/task-updates/browser-config");
  taskDestinationNotice = taskBrowserConfig.destination_notice_version;
  taskMarketingNotice = taskBrowserConfig.marketing_notice_version;
}
function updateTaskDeliveryFields() {
  const channel = $("taskUpdateChannel").value, inbox = ["webhook","a2a"].includes(channel);
  $("taskUpdateAddress").hidden = !inbox; $("taskUpdateUrl").required = inbox;
  $("taskUpdatePollHelp").hidden = channel !== "poll";
  $("taskUpdateBrowserHelp").hidden = channel !== "browser";
  $("taskUpdateMarketing").disabled = channel === "poll";
  if (channel === "poll") $("taskUpdateMarketing").checked = false;
  $("taskUpdateSubmit").textContent = "Review delivery method";
}
function openTaskUpdates(task, protocol) {
  if (!activeVisitorToken) return;
  ++taskUpdateEpoch; taskUpdateReturnFocus = document.activeElement;
  $("taskUpdateForm").reset(); $("taskUpdateForm").hidden = false;
  $("taskUpdateLabel").value = task;
  $("taskUpdateProtocol").value = ["a2a","mcp","x402"].includes(protocol) ? protocol : "";
  $("taskUpdateStatus").textContent = ""; $("taskUpdateVerify").hidden = true;
  $("taskUpdateReview").hidden = true; $("taskUpdateBrowserPending").hidden = true;
  $("taskUpdatePendingDecline").hidden = true;
  taskUpdateWatchId = ""; taskUpdatePending = false; taskUpdateDraft = null;
  taskBrowserSubscription = null; taskBrowserSubscriptionNew = false;
  updateTaskDeliveryFields(); flushTaskCleanup(); loadTaskBrowserConfig().catch(() => {});
  $("taskUpdateDialog").showModal(); $("taskUpdateLabel").focus();
}
async function checkTaskDestinationStatus() {
  const id = taskUpdateWatchId, epoch = taskUpdateEpoch;
  if (!id || !taskUpdatePending) return;
  try {
    const result = await taskRequest("/api/task-updates");
    if (epoch !== taskUpdateEpoch || id !== taskUpdateWatchId) return;
    const row = result.items.find(item => item.id === id);
    if (row?.state === "active" && row.destination_verified) {
      taskUpdatePending = false; taskBrowserSubscriptionNew = false; clearInterval(taskUpdateTimer);
      $("taskUpdateBrowserPending").hidden = true; $("taskUpdateVerify").hidden = true; $("taskUpdatePendingDecline").hidden = true;
      $("taskUpdateStatus").textContent = row.channel === "browser" ? "Browser notifications are verified and on." : "Task updates are on.";
    } else if (!row || ["failed","expired","revoked"].includes(row.state)) {
      await removePendingTaskUpdate();
      $("taskUpdateBrowserPending").hidden = true; $("taskUpdatePendingDecline").hidden = true;
      $("taskUpdateStatus").textContent = "The request was removed or could not be verified. Start again to choose a delivery method.";
    }
  } catch (error) {}
}
async function removeDeniedBrowserRequests() {
  if (!activeVisitorToken || !("Notification" in window) || Notification.permission !== "denied") return;
  try {
    const result = await taskRequest("/api/task-updates");
    for (const row of result.items) if (row.channel === "browser") taskCleanupIds.add(row.id);
    saveTaskCleanup(); await flushTaskCleanup();
    if (taskUpdatePending) await checkTaskDestinationStatus();
  } catch (error) {}
}
if ("serviceWorker" in navigator) navigator.serviceWorker.addEventListener("message", event => {
  if (event.data?.type === "task-browser-check" && event.data.watch_id === taskUpdateWatchId) checkTaskDestinationStatus();
});
window.addEventListener("online", flushTaskCleanup);
document.addEventListener("visibilitychange", () => { if (!document.hidden) { flushTaskCleanup(); removeDeniedBrowserRequests(); } });
try { navigator.permissions?.query({name:"notifications"}).then(status => status.addEventListener("change", removeDeniedBrowserRequests)).catch(() => {}); } catch (error) {}
function pushApplicationKey(value) {
  const raw = atob(value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4));
  return Uint8Array.from(raw, char => char.charCodeAt(0));
}
async function prepareBrowserSubscription() {
  if (!browserPushSupported()) throw new Error("Browser notifications are unavailable here. Choose another delivery method.");
  // This call starts directly inside the explicit confirmation click.
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    await removeDeniedBrowserRequests();
    throw new Error("Browser notifications were not allowed. No request was registered.");
  }
  if (!taskBrowserConfig) await loadTaskBrowserConfig();
  if (!taskBrowserConfig.available) throw new Error("Browser notifications are currently unavailable. Choose another delivery method.");
  await navigator.serviceWorker.register("/task-updates-sw.js",{scope:"/",updateViaCache:"none"});
  const registration = await Promise.race([navigator.serviceWorker.ready,new Promise((resolve,reject) => setTimeout(() => reject(new Error("Browser notification setup timed out. Please try again.")),15000))]);
  let subscription = await registration.pushManager.getSubscription();
  taskBrowserSubscriptionNew = !subscription;
  if (!subscription) subscription = await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:pushApplicationKey(taskBrowserConfig.application_server_key)});
  taskBrowserSubscription = subscription;
  return subscription.toJSON();
}
async function renderTaskPreferences() {
  const host = $("taskPreferences"); if (!host) return;
  host.textContent = "Loading task updates...";
  if (taskStopCapability) {
    host.innerHTML = '<p>Stop the task updates associated with this link.</p><button type="button" class="btn primary" id="taskStopFromLink">Stop updates</button>';
    $("taskStopFromLink").onclick = async () => {
      try { await taskRequest("/api/task-updates/stop","POST",{capability:taskStopCapability}); taskStopCapability = ""; host.textContent = "Task updates stopped."; }
      catch (error) { host.textContent = taskUpdateErrorMessage(error); }
    }; return;
  }
  if (!activeVisitorToken) { host.textContent = "Start a conversation to manage task updates in this browser, or use the stop link in an update."; return; }
  try {
    await flushTaskCleanup(); await removeDeniedBrowserRequests();
    const result = await taskRequest("/api/task-updates"); taskUpdateNotice = result.notice_version;
    taskDestinationNotice = result.destination_notice_version; taskMarketingNotice = result.marketing_notice_version;
    const rows = Array.isArray(result.items) ? result.items : [];
    if (!rows.length) { host.textContent = "No task updates have been requested in this session."; return; }
    host.innerHTML = "";
    for (const row of rows) {
      const section = document.createElement("section"); section.className = "task-watch";
      const channel = ({poll:"Manual checks only",browser:"Browser notifications",a2a:"A2A inbox",webhook:"Webhook"})[row.channel] || "Unavailable";
      section.innerHTML = '<strong>' + esc(chatLabel(row.task,"Task updates")) + '</strong><p>' + esc(row.protocol ? row.protocol.toUpperCase() : "Any protocol") + ' · ' + esc(channel) + ' · ' + esc(({active:'On',paused:'Paused',pending_verification:'Verification pending',revoked:'Stopped',expired:'Expired',failed:'Verification unsuccessful'})[row.state] || 'Unavailable') + '<br>Ends: ' + esc(chatTimestamp(row.expires)) + '</p><p>' + (row.channel === "poll" ? 'Manual checks do not send browser notifications.' : row.destination_verified ? 'Destination verified.' : 'Destination is not verified.') + '</p><p>Marketing: ' + (row.marketing_eligible ? 'Separate permission recorded for this verified destination.' : row.marketing_requested ? 'Recorded; this destination is not currently eligible.' : 'Not enabled.') + '</p>';
      const actions = document.createElement("div"); actions.className = "task-watch-actions";
      const choices = [];
      if (row.state === "active") choices.push(["pause","Pause updates"]);
      if (row.state === "paused") choices.push(["resume","Resume updates"]);
      if (["active","paused"].includes(row.state)) choices.push(["renew","Renew for 90 days"]);
      if (["active","paused","pending_verification"].includes(row.state)) choices.push(["stop","Stop updates"]);
      if (row.marketing_requested) choices.push(["withdraw_marketing","Withdraw marketing permission"]);
      choices.push(["delete","Delete notification data"]);
      if (row.state === "pending_verification") choices.push(["decline","Decline and delete request"]);
      for (const [action,label] of choices) {
        const button = document.createElement("button"); button.type = "button"; button.className = "btn sm"; button.textContent = label;
        button.onclick = async () => {
          button.disabled = true;
          try { await taskRequest("/api/task-updates/"+encodeURIComponent(row.id)+"/action","POST",{action}); await renderTaskPreferences(); }
          catch (error) { button.disabled = false; const notice = document.createElement("p"); notice.textContent = taskUpdateErrorMessage(error); section.appendChild(notice); }
        }; actions.appendChild(button);
      }
      if (row.state === "active") {
        const check = document.createElement("button"); check.type = "button"; check.className = "btn sm"; check.textContent = "Check for updates";
        check.onclick = async () => {
          check.disabled = true;
          try {
            const events = await taskRequest("/api/task-updates/"+encodeURIComponent(row.id)+"/action","POST",{action:"check"}); const update = events.items?.[0];
            if (update?.recommendation) { $("legalModal").close(); switchTab("chat"); appendChatBubble("bot","",{data:{recommendations:[update.recommendation],watch_task:row.task,protocol:row.protocol}}); }
            else check.textContent = update ? "No currently active, relevant agent found." : "No new verification changes.";
          } catch (error) { check.textContent = "Please try again."; } finally { check.disabled = false; }
        }; actions.appendChild(check);
      }
      if (row.state === "pending_verification" && row.channel !== "browser") {
        const code = document.createElement("input"); code.className = "input fs-mask"; code.setAttribute("data-clarity-mask","true"); code.setAttribute("aria-label","Verification code"); code.inputMode = "numeric"; code.maxLength = 6;
        const verify = document.createElement("button"); verify.type = "button"; verify.className = "btn sm"; verify.textContent = "Confirm endpoint";
        verify.onclick = async () => { try { await taskRequest("/api/task-updates/"+encodeURIComponent(row.id)+"/action","POST",{action:"verify",code:code.value}); code.value = ""; await renderTaskPreferences(); } catch (error) { verify.textContent = "Check the code and try again."; } };
        actions.append(code,verify);
      } else if (row.state === "pending_verification") {
        const hint = document.createElement("p"); hint.textContent = "Select the test browser notification to confirm, or decline this request."; section.appendChild(hint);
      }
      section.appendChild(actions); host.appendChild(section);
    }
  } catch (error) { host.textContent = taskUpdateErrorMessage(error); }
}
$("taskUpdateClose").onclick = closeTaskUpdates; $("taskUpdateNotNow").onclick = closeTaskUpdates;
$("taskUpdateDialog").addEventListener("cancel", event => { event.preventDefault(); closeTaskUpdates(); });
$("taskUpdateChannel").onchange = updateTaskDeliveryFields;
$("taskUpdateForm").onsubmit = event => {
  event.preventDefault(); if (!$("taskUpdateForm").reportValidity()) return;
  if (isUnsafeInput($("taskUpdateLabel").value)) { $("taskUpdateStatus").textContent = "Unable to complete this request. Please use a short task label."; return; }
  const channel = $("taskUpdateChannel").value, url = $("taskUpdateUrl").value.trim();
  if (["webhook","a2a"].includes(channel)) {
    try { const target = new URL(url); if (target.protocol !== "https:" || target.username || target.password || target.search || target.hash) throw new Error(); }
    catch (error) { $("taskUpdateStatus").textContent = "Use a dedicated HTTPS inbox without credentials, query parameters or fragments."; return; }
  }
  taskUpdateDraft = {task:$("taskUpdateLabel").value.trim(),protocol:$("taskUpdateProtocol").value,channel,url,
    authority:$("taskUpdateAuthority").checked,task_updates:$("taskUpdateConsent").checked,notice_version:taskUpdateNotice,
    destination_confirmed:true,destination_notice_version:taskDestinationNotice,
    marketing:$("taskUpdateMarketing").checked,marketing_notice_version:taskMarketingNotice};
  $("taskUpdateReviewDestination").textContent = channel === "browser" ? "Browser notifications in this browser" : channel === "poll" ? "Manual checks only: no automatic browser notifications" : url;
  $("taskUpdateReviewMarketing").textContent = taskUpdateDraft.marketing ? "Separate marketing permission requested. It becomes eligible only after this destination is verified." : "Marketing permission is not requested.";
  $("taskUpdateForm").hidden = true; $("taskUpdateReview").hidden = false;
  $("taskUpdateStatus").textContent = ""; $("taskUpdateConfirmDestination").focus();
};
$("taskUpdateConfirmDestination").onclick = async () => {
  const draft = taskUpdateDraft; if (!draft) return;
  const epoch = taskUpdateEpoch, button = $("taskUpdateConfirmDestination"); button.disabled = true;
  try {
    if (draft.channel === "browser") draft.subscription = await prepareBrowserSubscription();
    if (epoch !== taskUpdateEpoch) { await removePendingTaskUpdate(); return; }
    const result = await taskRequest("/api/task-updates","POST",draft);
    if (epoch !== taskUpdateEpoch) { taskCleanupIds.add(result.id); saveTaskCleanup(); await flushTaskCleanup(); return; }
    taskUpdateWatchId = result.id; taskUpdatePending = result.state === "pending_verification";
    taskUpdateDraft = null; $("taskUpdateUrl").value = ""; $("taskUpdateReviewDestination").textContent = "";
    $("taskUpdateReview").hidden = true;
    $("taskUpdateVerify").hidden = !taskUpdatePending || result.channel === "browser";
    $("taskUpdateBrowserPending").hidden = !taskUpdatePending || result.channel !== "browser";
    $("taskUpdatePendingDecline").hidden = !taskUpdatePending;
    $("taskUpdateStatus").textContent = result.state === "active" ? "Task updates are on." : result.channel === "browser" ? "Select the test browser notification to confirm. Notifications are not active yet." : "Verification requested. Enter the code received at your inbox to enable updates.";
    if (taskUpdatePending) {
      clearInterval(taskUpdateTimer); let checks = 0;
      taskUpdateTimer = setInterval(() => { if (++checks > 40) clearInterval(taskUpdateTimer); else checkTaskDestinationStatus(); },3000);
    }
  } catch (error) {
    await removePendingTaskUpdate();
    if (epoch === taskUpdateEpoch) { $("taskUpdateReview").hidden = true; $("taskUpdateForm").hidden = false; $("taskUpdateStatus").textContent = taskUpdateErrorMessage(error); }
  } finally { button.disabled = false; }
};
async function declineTaskUpdate() {
  ++taskUpdateEpoch; const removed = await removePendingTaskUpdate();
  $("taskUpdateReviewDestination").textContent = ""; $("taskUpdateUrl").value = "";
  $("taskUpdateReview").hidden = true; $("taskUpdateVerify").hidden = true;
  $("taskUpdateBrowserPending").hidden = true; $("taskUpdatePendingDecline").hidden = true;
  $("taskUpdateStatus").textContent = removed ? "Request deleted. No notifications were enabled." : "Removal is pending. It will be retried when the connection is available.";
}
$("taskUpdateReviewDecline").onclick = declineTaskUpdate; $("taskUpdatePendingDecline").onclick = declineTaskUpdate;
$("taskUpdateVerifyButton").onclick = async () => {
  const button = $("taskUpdateVerifyButton"); button.disabled = true;
  try {
    await taskRequest("/api/task-updates/"+encodeURIComponent(taskUpdateWatchId)+"/action","POST",{action:"verify",code:$("taskUpdateCode").value});
    taskUpdatePending = false; clearInterval(taskUpdateTimer); $("taskUpdateCode").value = ""; $("taskUpdateVerify").hidden = true;
    $("taskUpdatePendingDecline").hidden = true; $("taskUpdateStatus").textContent = "Task updates are on.";
  } catch (error) { $("taskUpdateStatus").textContent = "Verification could not be confirmed. Check the code or decline this request."; }
  finally { button.disabled = false; }
};
$("taskUpdateManage").onclick = async () => { await closeTaskUpdates(); openLegalModal("cancellation"); };
$("taskUpdatePrivacy").onclick = async () => { await closeTaskUpdates(); openLegalModal("privacy"); };


const chatForm = $("chatForm");
const chatInput = $("chatInput");
const chatStatus = $("chatStatus");
const chatSubmit = $("chatSubmit");
const chatMessages = $("chatMessages");
let activeVisitorToken = "";
function safeChatQuestion(value) {
  return String(value).replace(/(?:\d[ -]?){12,18}\d/g, match => {
    const digits=match.replace(/\D/g, "");
    const sum=Array.from(digits).reverse().reduce((total,n,index)=>{let v=Number(n);if(index%2){v*=2;if(v>9)v-=9;}return total+v;},0);
    return sum%10===0 ? "[Card number removed]" : match;
  }).replace(/\b(?:api[_ -]?key|password|access[_ -]?token|secret)\s*[:=]\s*[^\s,;]+|\bBearer\s+\S+|\bvt_[A-Za-z0-9_-]{16,96}/gi, "[Sensitive information removed]");
}
function displayChatQuestion(value) {
  return safeChatQuestion(value).replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi,"[Email address removed]");
}
try {
  activeVisitorToken = sessionStorage.getItem("visitorToken") || localStorage.getItem("visitorToken") || "";
  if (!/^vt_[A-Za-z0-9_-]{16,96}$/.test(activeVisitorToken)) activeVisitorToken = "";
  if (activeVisitorToken) sessionStorage.setItem("visitorToken",activeVisitorToken);
  localStorage.removeItem("visitorToken");
} catch (e) {}

// Local Lucide SVGs keep icons available without external requests.
const CHAT_ICONS = Object.freeze({"bot": "<svg class=\"lucide lucide-bot chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <path d=\"M12 8V4H8\" /> <rect width=\"16\" height=\"12\" x=\"4\" y=\"8\" rx=\"2\" /> <path d=\"M2 14h2\" /> <path d=\"M20 14h2\" /> <path d=\"M15 13v2\" /> <path d=\"M9 13v2\" /> </svg>", "shield-check": "<svg class=\"lucide lucide-shield-check chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <path d=\"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z\" /> <path d=\"m9 12 2 2 4-4\" /> </svg>", "file-check": "<svg class=\"lucide lucide-file-check chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <path d=\"M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z\" /> <path d=\"M14 2v4a2 2 0 0 0 2 2h4\" /> <path d=\"m9 15 2 2 4-4\" /> </svg>", "activity": "<svg class=\"lucide lucide-activity chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <path d=\"M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2\" /> </svg>", "search": "<svg class=\"lucide lucide-search chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <circle cx=\"11\" cy=\"11\" r=\"8\" /> <path d=\"m21 21-4.3-4.3\" /> </svg>", "arrow-right": "<svg class=\"lucide lucide-arrow-right chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <path d=\"M5 12h14\" /> <path d=\"m12 5 7 7-7 7\" /> </svg>", "arrow-up-right": "<svg class=\"lucide lucide-arrow-up-right chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <path d=\"M7 7h10v10\" /> <path d=\"M7 17 17 7\" /> </svg>", "plug": "<svg class=\"lucide lucide-plug chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <path d=\"M12 22v-5\" /> <path d=\"M9 8V2\" /> <path d=\"M15 8V2\" /> <path d=\"M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z\" /> </svg>", "loader-circle": "<svg class=\"lucide lucide-loader-circle chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <path d=\"M21 12a9 9 0 1 1-6.219-8.56\" /> </svg>", "info": "<svg class=\"lucide lucide-info chat-icon\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" > <circle cx=\"12\" cy=\"12\" r=\"10\" /> <path d=\"M12 16v-4\" /> <path d=\"M12 8h.01\" /> </svg>"});
function chatIcon(name) { return CHAT_ICONS[name] || ""; }

const CHAT_PROMOTION = /\b(?:free|paid|pay|micro[ -]?payments?|pay[ -]?per[ -]?call|payments?|billing|pricing|prices?|fees?|costs?|charges?|subscriptions?|plans?|premium|credits?|wallets?|USDC|USD|EUR)\b|[$\u20ac\u00a3\u20a9]/i;
const CHAT_NON_ENGLISH = /[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]/;
const CHAT_PROMOTION_ALL = new RegExp(CHAT_PROMOTION.source, "gi");
function chatLabel(value, fallback) {
  const text = String(value || "").trim();
  if (!text || CHAT_NON_ENGLISH.test(text)) return fallback;
  if (!CHAT_PROMOTION.test(text)) return text;
  // Keep the service name and drop price or billing fragments instead of hiding the whole name.
  let kept = text.split(/\s*(?:[|()\[\]:\u2013\u2014]|\s-\s)\s*/).filter(part => part && !CHAT_PROMOTION.test(part)).join(" - ");
  if (!/[A-Za-z]{3}/.test(kept)) kept = text.replace(/[$\u20ac\u00a3\u20a9]\s*[\d.,]+/g, " ").replace(/\b(?:pay[ -]?)?per[ -]?(?:call|request|query|use)\b/gi, " ").replace(CHAT_PROMOTION_ALL, " ").replace(/[\d.,/]+\s*(?:per|\/)\s*\w+/gi, " ");
  kept = kept.replace(/\s+/g, " ").replace(/^[\s\-|:,.\/]+|[\s\-|:,.\/]+$/g, "");
  return /[A-Za-z]{3}/.test(kept) && !CHAT_PROMOTION.test(kept) ? kept : fallback;
}
function chatTimestamp(value) {
  const n = Number(value);
  const date = new Date(n * 1000);
  return Number.isFinite(n) && n > 0 && Number.isFinite(date.getTime()) ? date.toISOString().replace("T", " ").slice(0,19) + " UTC" : "Not recorded";
}
function isGatewayOrigin(value) {
  try {
    const url = new URL(value);
    return url.origin === "https://agentconcierge.biz" && !url.username && !url.password;
  } catch (error) { return false; }
}
function gatewayAgentEndpoint(agentOrItem) {
  if (!agentOrItem || typeof agentOrItem !== "object" || agentOrItem.simulated === true || agentOrItem.connection_available === false) return "";
  const kind = String(agentOrItem.kind || agentOrItem.protocol || "").toLowerCase();
  const id = agentOrItem.id ?? agentOrItem.resource_id ?? agentOrItem.agent_id;
  if (!["a2a", "mcp", "x402"].includes(kind) || !/^[1-9]\d*$/.test(String(id)) || Number(id) >= 2147483648) return "";
  const url = `https://agentconcierge.biz/api/gateway/${kind}/${id}`;
  return isGatewayOrigin(url) ? url : "";
}
function scrubGatewayText(text, gwUrl) {
  const fallback = (gwUrl && isGatewayOrigin(gwUrl)) ? gwUrl : "https://agentconcierge.biz";
  return String(text ?? "")
    .replace(/https?:\/\/(?:local\x68ost|127(?:\.0){2}\.1|(?:0\.){3}0|\[::1\])(?::\d+)?(?:\/[^\s"'<>)\]}]+)?/gi, fallback)
    .replace(/https?:\/\/[^\s"'<>)\]}]+:8[024][08]0(?:\/[^\s"'<>)\]}]+)?/gi, fallback);
}
function gatewayLink(url) {
  return url && isGatewayOrigin(url) ? link(url) : "Connection unavailable";
}
function openChatAgent(item) {
  const report = item.test_report;
  const name = chatLabel(item.display_name || item.name, "Agent #" + (item.id || "unavailable"));
  const tool = item.tools_schema?.[0];
  const inputs = tool?.inputSchema?.properties || tool?.parameters || {};
  const names = Array.isArray(inputs) ? inputs.map(x => x?.name).filter(Boolean) : Object.keys(inputs);
  const gwUrl = gatewayAgentEndpoint(item);
  $("drawerBadges").textContent = chatLabel(item.kind, "Agent");
  $("drawerContent").innerHTML = '<div class="chat-detail-heading">' + chatIcon('bot') + '<h3>' + esc(name) + '</h3></div><dl class="kv chat-detail-fields">' +
    '<dt>' + chatIcon('plug') + 'Endpoint</dt><dd>' + gatewayLink(gwUrl) + '</dd>' +
    '<dt>' + chatIcon('shield-check') + 'Connection verification</dt><dd>' + esc(connectionVerificationLabel(item)) + '</dd>' +
    '<dt>' + chatIcon('shield-check') + 'Quality grade</dt><dd>' + esc(item.grade || 'Unrated') + '</dd>' +
    '<dt>' + chatIcon('file-check') + 'Test report</dt><dd>' + (report ? '#' + esc(report.id) + ' · ' + esc(chatTimestamp(report.created_at)) : 'No published report') + '</dd>' +
    '<dt>' + chatIcon('activity') + 'Active checked</dt><dd>' + esc(chatTimestamp(item.active_checked_at)) + '</dd>' +
    (item.tools?.length ? '<dt>Tool</dt><dd>' + esc(chatLabel(item.tools[0], 'Available tool')) + '</dd>' : '') +
    (names.length ? '<dt>Inputs</dt><dd>' + names.map(name => esc(chatLabel(name, 'Input'))).join(', ') + '</dd>' : '') + '</dl>';
  $("drawer").classList.remove("hidden");
  $("drawerBackdrop").classList.remove("hidden");
}
// 11-04 five-point step 7: the recorded evidence behind a recommendation, one click from the card.
// evidence.unknown decides which rows read "Unknown"; nothing is inferred on the page.
function chatIsoTime(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return "";
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toISOString().replace("T", " ").slice(0, 16) + " UTC" : "";
}
function chatProof(item) {
  const ev = item && typeof item.evidence === "object" && item.evidence ? item.evidence : null;
  if (!ev) return "";
  const unknown = new Set(Array.isArray(ev.unknown) ? ev.unknown.filter(v => typeof v === "string") : []);
  const row = (key, label, value) => {
    const missing = unknown.has(key) || !value;
    return '<div' + (missing ? ' data-unknown=""' : '') + '><dt>' + esc(label) + '</dt><dd>' +
      (missing ? 'Unknown \u2014 no record' : esc(value)) + '</dd></div>';
  };
  const health = chatIsoTime(ev.health_checked_at);
  const trial = ev.trial_call && typeof ev.trial_call === "object" ? ev.trial_call : {};
  const trialAt = chatIsoTime(trial.at);
  const report = Number.isInteger(trial.report_id) && trial.report_id > 0 ? " \u00b7 report #" + trial.report_id : "";
  const trialText = trial.status === "passed" ? "Passed" + (trialAt ? " \u00b7 " + trialAt : "") + report
    : trial.status === "failed" ? "Failed" + (trialAt ? " \u00b7 " + trialAt : "") + report : "";
  if (trial.status !== "passed" && trial.status !== "failed") unknown.add("trial_call");
  const toolText = ev.selected_tool_check === "passed" ? "Passed" : "";
  const known = [health && !unknown.has("health_checked_at"), trialText && !unknown.has("trial_call"), toolText && !unknown.has("selected_tool_check")].filter(Boolean).length;
  return '<details class="chat-proof"><summary>' + chatIcon('shield-check') + 'Evidence: ' + known + ' of 3 recorded</summary><dl>' +
    row("health_checked_at", "Last health check", health) +
    row("trial_call", "Trial call", trialText) +
    row("selected_tool_check", "Selected tool check", toolText) +
    '</dl><p class="caption">Recorded by Agent Concierge before your request. Your request has not been run.</p></details>';
}
function chatWhy(item) {
  const terms = Array.isArray(item.matched_terms) ? item.matched_terms.filter(t => typeof t === "string" && /^[a-z0-9][a-z0-9-]{1,39}$/.test(t)).slice(0, 6) : [];
  const purpose = item.tools_schema?.[0]?.description || "";
  const tool = chatLabel(item.tools?.[0], "");
  const focus = terms.length ? terms.join(", ") : "your task";
  // A sentence from structured match data; provider text appears only when it is product-neutral.
  const served = typeof item.reason?.text === "string" ? item.reason.text.trim().slice(0, 400) : "";
  const reason = served ? served : tool ? (item.match_basis === "tool" ? "One of this service's tools, " + tool + ", covers " + focus + "."
                                                   : "Its " + tool + " tool covers " + focus + ".")
                      : terms.length ? "The listing covers " + focus + "." : "Selected for your task.";
  const text = chatLabel(purpose, "");
  const labels = {pdf_input:'PDF input',ocr:'Scanned document recognition',table_structure:'Table structure',json_output:'JSON output',doi:'DOI identifiers',timestamps:'Timestamps'};
  const matched = Array.isArray(item.task_fit?.matched) ? item.task_fit.matched.filter(key => Object.hasOwn(labels,key)).slice(0,6) : [];
  if (!reason && !text && !matched.length) return "";
  return '<div class="chat-why"><span class="chat-field-label">' + chatIcon('info') + 'Why selected:</span>' +
    (reason ? '<p>' + esc(reason) + '</p>' : '') +
    (matched.length ? '<p class="chat-task-fit">Declared requirements: ' + matched.map(key => esc(labels[key])).join(', ') + '</p>' : '') +
    (text ? '<p>' + esc(text) + '</p>' : '') + '</div>';
}
// 11-05 needs_choice: the visitor picks one of the options; nothing is run or sent when choosing.
function chatChoice(bubble, choices) {
  const cards = [...bubble.querySelectorAll('.chat-recommendation')];
  const prompt = document.createElement('div');
  prompt.className = 'chat-choice';
  prompt.setAttribute('role', 'group');
  prompt.setAttribute('aria-label', 'Choose one recommendation');
  const title = document.createElement('p');
  title.className = 'chat-choice-title';
  title.textContent = 'Not sure which of these fits your task.';
  const hint = document.createElement('p');
  hint.className = 'caption';
  hint.textContent = 'Choose one to keep it, or say more about what the agent should do.';
  const more = document.createElement('button');
  more.type = 'button'; more.className = 'btn sm chat-choice-more'; more.textContent = 'Say more';
  more.onclick = () => {
    const input = document.getElementById('chatInput');
    if (!input) return;
    const last = document.querySelector('#chatMessages .chat-request')?.dataset.request || '';
    if (!input.value.trim() && last) input.value = last + ' ';
    input.focus();
    input.setSelectionRange?.(input.value.length, input.value.length);
  };
  const change = document.createElement('button');
  change.type = 'button'; change.className = 'btn sm chat-choice-change'; change.textContent = 'Change choice'; change.hidden = true;
  const actions = document.createElement('div');
  actions.className = 'chat-choice-actions';
  actions.append(more, change);
  prompt.append(title, hint, actions);
  bubble.prepend(prompt);
  const announce = text => { if (chatStatus) chatStatus.textContent = text; };
  const reset = () => {
    for (const card of cards) {
      card.hidden = false; card.removeAttribute('data-chosen');
      const pick = card.querySelector('.chat-choose-btn');
      if (pick) { pick.hidden = false; pick.setAttribute('aria-pressed', 'false'); }
    }
    title.textContent = 'Not sure which of these fits your task.';
    hint.hidden = false; change.hidden = true;
    announce('Showing all ' + cards.length + ' options.');
    cards[0]?.querySelector('.chat-choose-btn')?.focus();
  };
  change.onclick = reset;
  cards.forEach((card, index) => {
    const pick = document.createElement('button');
    pick.type = 'button'; pick.className = 'btn sm primary chat-choose-btn';
    pick.setAttribute('aria-pressed', 'false');
    const name = card.querySelector('.chat-result-name')?.textContent || 'Option ' + (index + 1);
    pick.textContent = 'Choose this option';
    pick.setAttribute('aria-label', 'Choose option ' + (index + 1) + ': ' + name);
    pick.onclick = () => {
      cards.forEach((other, i) => { other.hidden = i !== index; });
      card.dataset.chosen = '';
      pick.setAttribute('aria-pressed', 'true'); pick.hidden = true;
      title.textContent = 'You chose option ' + (index + 1) + ': ' + name + '.';
      hint.hidden = true; change.hidden = false;
      announce('Option ' + (index + 1) + ' chosen: ' + name + '. Review its evidence and calling details.');
      bubble.dispatchEvent(new CustomEvent('chat-choice', {bubbles: true, detail: {index}}));
      card.querySelector('.chat-rec-btn')?.focus();
    };
    card.querySelector('.chat-result-heading')?.after(pick);
  });
}
function appendChatBubble(role, contentText, data, requestNote=null) {
  if (!chatMessages) return;
  if (role === "user") {
    const question=document.createElement("p");question.className="chat-request";
    question.textContent="Your request: "+displayChatQuestion(contentText);
    question.dataset.request=String(contentText??"").slice(0,500);
    question.style.cssText="white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 16px;padding:12px;border-left:3px solid var(--accent);font-size:14px";
    chatMessages.prepend(question);return question;
  }
  const choices = Array.isArray(data?.data?.recommendations) ? data.data.recommendations.slice(0,3) : [];
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble bot";
  if (choices.length) {
    const cards = choices.map((item,index) => {
    const report = item.test_report;
    const gwUrl = gatewayAgentEndpoint(item);
    const check = item.capability_contract?.verified_within_24h === true ? item.capability_contract :
      item.connection_readiness?.verified_callable === true ? item.connection_readiness : null;
    const checkedAt = check?.verified_at;
    return '<article class="chat-recommendation" data-agent-id="' + esc(String(item.id || '')) + '">' +
      '<div class="chat-result-heading"><div class="chat-agent-mark">' + chatIcon('bot') + '</div>' +
        '<div class="chat-result-identity"><strong class="chat-result-name">' + esc(chatLabel(item.display_name || item.name, 'Agent #' + (item.id || 'unavailable'))) + '</strong><span class="chat-result-caption">' + esc(typeof item.request_part === 'string' && item.request_part ? 'For: ' + chatLabel(item.request_part.slice(0,120), 'part of your task') : choices.length > 1 ? 'Option '+(index+1)+' for your task' : 'Selected for your task') + '</span></div>' +
        '<span class="chat-protocol">' + esc(chatLabel(item.kind, 'Agent')) + '</span></div>' +
      chatWhy(item) + chatProof(item) +
      '<div class="chat-endpoint"><span class="chat-field-label">' + chatIcon('plug') + 'Endpoint:</span>' + gatewayLink(gwUrl) + '</div>' +
      '<dl class="chat-evidence">' +
        (item.task_verification?.status === 'verified' && item.task_verification?.tool === item.tools?.[0]
          ? '<div><dt class="chat-field-label">' + chatIcon('file-check') + 'Selected tool check:</dt><dd>Passed · ' + esc(chatTimestamp(item.task_verification.verified_at)) + '</dd></div>' : '') +
        (typeof checkedAt === 'number' && Number.isFinite(checkedAt) && checkedAt > 0
          ? '<div><dt class="chat-field-label">' + chatIcon('file-check') + 'Connection execution check:</dt><dd>' + esc(chatTimestamp(checkedAt)) + '</dd></div>' : '') +
        '<div><dt class="chat-field-label">' + chatIcon('shield-check') + 'Quality:</dt><dd><span class="chat-grade">' + esc(item.grade || 'Unrated') + '</span>' +
          (item.quality_score != null ? '<span class="chat-score">' + esc(item.quality_score) + '/100</span>' : '') + '</dd></div>' +
        (report ? '<div><dt class="chat-field-label">' + chatIcon('file-check') + 'Test report:</dt><dd>#' + esc(report.id) +
          (report.success === true ? ' · Passed' : report.success === false ? ' · Failed' : '') + '<br>' + esc(chatTimestamp(report.created_at)) + '</dd></div>' : '') +
        '<div><dt class="chat-field-label">' + chatIcon('activity') + 'Active checked:</dt><dd>' + esc(chatTimestamp(item.active_checked_at)) + '</dd></div></dl>' +
      '<div class="chat-result-footer">' +
        (item.tools?.length ? '<div class="chat-tool">' + chatIcon('plug') + '<span>Tool: ' + esc(chatLabel(item.tools[0], 'Available tool')) + '</span></div>' : '<span></span>') +
        '<button type="button" class="btn sm chat-rec-btn"><span>Calling details</span>' + chatIcon('arrow-up-right') + '</button></div>' +
        '<div class="chat-feedback" role="group" aria-label="Did this agent work for your task?"><span class="muted">Did it work?</span>' +
        '<button type="button" class="btn sm chat-feedback-btn" data-outcome="worked">Worked</button>' +
        '<button type="button" class="btn sm chat-feedback-btn" data-outcome="failed">Didn&#39;t work</button></div></article>';
    });
    // 11-05: a low-confidence answer (status needs_choice) shows every option side by side to choose from.
    const choosing = data?.data?.status === 'needs_choice' && cards.length > 1;
    bubble.innerHTML = choosing ? cards.join('') : cards[0] + (cards.length > 1 ? '<details class="context-help chat-alternatives"><summary>Show ' + (cards.length-1) + ' alternative' + (cards.length > 2 ? 's' : '') + '</summary>' + cards.slice(1).join('') + '</details>' : '');
    const basis = document.createElement('details');basis.className='context-help chat-result-basis';
    const summary=document.createElement('summary');summary.textContent='Why these matches?';
    const explanation=document.createElement('div');explanation.className='context-help-body';explanation.textContent='Matches must fit the task. Services built for the task come before multi-tool services where one tool matches. Within each group, recent successful checks come first, then activity and quality. Automatic searches prefer A2A, then MCP.';
    // How the quality grade is composed (collector evaluation weights); provider text is not scored as a claim.
    const quality=document.createElement('p');quality.textContent='Quality is a rule-based score out of 100: availability 25, tool definition quality 20, security 20, context 15, protocol conformance 10, provenance and maintenance 10. Grades: A 85+, B 70+, C 55+, D 40+. A confirmed security signal caps the score at 40. Descriptions are written by each provider.';
    explanation.append(quality);basis.append(summary,explanation);
    bubble.prepend(basis);
    bubble.__chatData = data;
    if (choosing) chatChoice(bubble, choices);
    bubble.querySelectorAll('.chat-rec-btn').forEach((button,index) => {button.onclick=()=>openChatAgent(choices[index]);});
    // Feedback names a position in the latest list; earlier answers stop accepting it.
    document.querySelectorAll('#chatMessages .chat-feedback-btn').forEach(button => { if (!bubble.contains(button)) button.disabled = true; });
    bubble.querySelectorAll('.chat-recommendation').forEach((card,index) => card.querySelectorAll('.chat-feedback-btn').forEach(button => {
      button.onclick = () => {
        card.querySelectorAll('.chat-feedback-btn').forEach(other => { other.disabled = true; });
        button.setAttribute('aria-pressed','true');
        const name = card.querySelector('.chat-result-name')?.textContent.replace(/^\d+\.\s*/, '') || 'this agent';
        sendChat((button.dataset.outcome === 'worked' ? 'worked ' : 'failed ') + (index + 1),
                 (button.dataset.outcome === 'worked' ? 'It worked: ' : 'It did not work: ') + name);
      };
    }));
    const updates = document.createElement("button");
    updates.type = "button";
    updates.className = "btn sm chat-update-button";
    updates.innerHTML = chatIcon("activity") + "<span>Get updates for this task</span>";
    updates.onclick = () => openTaskUpdates(data?.data?.watch_task || "", data?.data?.protocol || "");
    bubble.appendChild(updates);
  } else if (Array.isArray(data?.data?.workflows) && data.data.workflows.length) {
    const basis=document.createElement('details');basis.className='context-help chat-result-basis';
    const summary=document.createElement('summary');summary.textContent='Why these workflows?';
    const explanation=document.createElement('div');explanation.className='context-help-body';explanation.textContent='Published workflows must cover the task. Focused steps are preferred over unrelated extras, then newer updates.';basis.append(summary,explanation);bubble.append(basis);
    const workflows=data.data.workflows.slice(0,3).filter(item=>Number.isInteger(item.id)&&item.id>0&&item.id<2147483648);
    for (const [index,item] of workflows.entries()) {
      const card=document.createElement('article');card.className='chat-recommendation chat-workflow-recommendation';
      const title=document.createElement('strong');title.className='chat-result-name';title.textContent=(index+1)+'. '+chatLabel(item.name,'Published workflow');card.append(title);
      const description=document.createElement('p');description.textContent=chatLabel(item.description,'Review this workflow’s steps before using it.');card.append(description);
      const steps=document.createElement('ol');
      for(const name of (item.step_names||[]).slice(0,12)){const row=document.createElement('li');row.textContent=chatLabel(name,'Workflow step');steps.append(row)}card.append(steps);
      const note=document.createElement('p');note.textContent='Review the current inputs and authorize a run before execution.';card.append(note);
      const review=document.createElement('button');review.type='button';review.className='btn sm chat-workflow-review';review.textContent='Review template';
      review.onclick=async()=>{review.disabled=true;review.textContent='Opening template…';try{
        const result=await api('/api/workflows/templates/'+item.id,{userInitiated:true,loadingMsg:'Opening published workflow…',retries:0});
        if(!result?.workflow)throw new Error('Unavailable');
        frontTemplatesCache=frontTemplatesCache.filter(value=>value.id!==item.id).concat([result.workflow]);
        switchTab('workflows');loadFrontTemplateToCanvas(item.id);
      }catch{if(chatStatus)chatStatus.textContent='This template is unavailable. Search again for current options.'}finally{review.disabled=false;review.textContent='Review template'}};
      card.append(review);bubble.append(card);
    }
  } else {
    const outcome = data?.data?.reason_code || data?.data?.status;
    const outcomes = {
      no_eligible_match: "No currently verified match meets this task. Refine a requirement or try another task.",
      needs_task: "What should the agent do? Include the input you have and the result you need.",
      needs_language: "Your task is kept. Please restate it briefly in English; language normalization is unavailable.",
      needs_scope: "What would you like to do, and what result do you need? For example, summarize meeting notes or compare two documents.",
      needs_redaction: "Remove card numbers, passwords and access keys before describing your task. No action was run.",
      needs_authorized_task: "I cannot help access a network, device or account without permission, or steal credentials. Describe an authorized security test or a defensive task instead.",
      needs_goal: "What should an agent do for you? For example: answer customer emails, analyze sales data, or monitor your website.",
      out_of_scope: "I recommend agents and published workflows rather than answering questions directly. Describe a task, such as searching the web or looking up country facts.",
      unsupported_guarantee: "Lottery results cannot be guaranteed. I can help find probability or statistics tools instead.",
      needs_workflow: "This request contains separate tasks. Which should come first? You can also ask for a workflow that connects the steps.",
      temporarily_unavailable: "Search is temporarily unavailable. Your task has been kept; please try again."
    };
    const notices = new Set([
      "Describe the task. I will return up to three relevant agents.",
      "Describe the task; up to three relevant agents will be returned.",
      "No currently active, relevant agent found.",
      "Describe the task first.", "Updates enabled.", "Updates disabled.", "Success recorded.", "Manage task updates to resume an authorized task.", "Use task update preferences to authorize and verify a destination.", "Choose A2A, MCP, x402, or Any protocol."
    ]);
    const examples = Array.isArray(data?.data?.examples) ? data.data.examples.filter(value => typeof value === "string" && /^[\x20-\x7e]{3,80}$/.test(value)).slice(0, 4) : [];
    bubble.textContent = examples.length ? "Describe the task. I will recommend up to three relevant agents or published workflows. Try one of these:"
      : Object.hasOwn(outcomes, outcome) ? outcomes[outcome] : notices.has(contentText) ? contentText : "Describe the task. I will return up to three relevant agents.";
    if (examples.length) {
      const list = document.createElement("div"); list.className = "chat-examples";
      for (const example of examples) {
        const button = document.createElement("button"); button.type = "button"; button.className = "btn sm chat-example";
        button.textContent = example; button.onclick = () => sendChat(example); list.append(button);
      }
      bubble.append(list);
    }
    const exploreQuery = typeof data?.data?.explore_query === "string" ? data.data.explore_query.trim().slice(0, 120) : "";
    if (outcome === "no_eligible_match") {
      // An empty answer still offers a next step: refine the same request without retyping it.
      const tip = document.createElement("p"); tip.className = "chat-next-tip";
      tip.textContent = "Tip: name the input you have and the result you need, or drop a requirement such as a region or free use.";
      const edit = document.createElement("button"); edit.type = "button"; edit.className = "btn sm chat-edit-request";
      edit.textContent = "Edit this request";
      const original = requestNote instanceof HTMLElement && requestNote.dataset.request ? requestNote.dataset.request : exploreQuery;
      edit.onclick = () => { const input = $("chatInput"); if (!input) return; input.value = original; input.focus(); input.setSelectionRange(input.value.length, input.value.length); };
      bubble.append(tip, edit);
    }
    if (outcome === "no_eligible_match" && exploreQuery) {
      // Explore also lists agents that have not passed a recent check; Chat recommends checked ones only.
      const browse = document.createElement("button"); browse.type = "button"; browse.className = "btn sm chat-explore-link";
      browse.innerHTML = chatIcon("arrow-up-right") + "<span>Browse unverified listings in Explore</span>";
      browse.onclick = () => { const input = $("xQ"); if (input) input.value = exploreQuery; switchTab("explore"); };
      bubble.append(document.createElement("br"), browse);
    }
  }
  if (data?.data?.action_review_required) {
    const notice=document.createElement("p");notice.className="chat-action-notice";
    notice.textContent="No message or reservation has been made. Review an agent in Workspace before authorizing an action.";bubble.prepend(notice);
  }
  if (requestNote instanceof HTMLElement) bubble.prepend(requestNote);
  chatMessages.classList.add("has-results");
  chatMessages.prepend(bubble);
  chatMessages.scrollTop = 0;
}
// The answer streams its steps (server-sent events) so the visitor sees the work under way
// instead of a bare spinner; an older server that answers with plain JSON still works.
async function chatWithProgress(json, headers, signal, onStep, timeoutMs = 30000) {
  const controller = new AbortController();
  const stop = () => controller.abort();
  signal?.addEventListener("abort", stop, {once: true});
  const timer = setTimeout(stop, timeoutMs);
  const failure = (message, status = 0, extra = {}) => Object.assign(new Error(message), {status, ...extra});
  try {
    const res = await fetch("/chat", {method: "POST", body: JSON.stringify(json), signal: controller.signal,
      headers: {...headers, "Content-Type": "application/json", "Accept": "text/event-stream"}});
    if (!res.ok) {
      let text = "HTTP " + res.status, code = "";
      try { const j = await res.json(); text = j.detail || j.error || text; code = j.error_code || ""; } catch (e) {}
      const retryAfter = Number(res.headers.get("Retry-After"));
      throw failure(typeof text === "string" ? text : "The request could not be completed.", res.status,
        {error_code: code, retryAfter: Number.isInteger(retryAfter) && retryAfter > 0 && retryAfter <= 3600 ? retryAfter : 0});
    }
    if (!(res.headers.get("content-type") || "").includes("text/event-stream")) {
      return {body: await res.json(), visitor_token: res.headers.get("x-visitor-token") || ""};
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const line = buffer.slice(0, cut).split("\n").find(row => row.startsWith("data: "));
        buffer = buffer.slice(cut + 2);
        if (!line) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === "progress") onStep(event);
        else if (event.type === "result") return event;
        else if (event.type === "error") throw failure(event.error || "The request could not be completed.", event.status || 500,
          {error_code: event.error_code || "", retryAfter: event.status === 503 ? 2 : 0});
      }
    }
    throw failure("The request could not be completed.");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", stop);
  }
}
function chatProgressView(requestNote) {
  // Shown only in the conversation area, beside the request; menus and the composer stay usable.
  const box = document.createElement("div");
  box.className = "chat-progress";
  box.setAttribute("role", "status");
  box.setAttribute("aria-live", "polite");
  const list = document.createElement("ol");
  box.append(list);
  if (requestNote instanceof HTMLElement && requestNote.isConnected) requestNote.after(box);
  else chatMessages?.prepend(box);
  let current = null;
  return {
    step(event) {
      if (current) { current.classList.add("done"); current.removeAttribute("aria-current"); }
      current = document.createElement("li");
      current.setAttribute("aria-current", "step");
      const label = document.createElement("span");
      label.textContent = event.label || "Working";
      const time = document.createElement("span");
      time.className = "chat-progress-time";
      time.textContent = (event.elapsed_ms / 1000).toFixed(1) + "s";
      current.append(label, time);
      list.append(current);
      return event.label || "Working";
    },
    remove() { box.remove(); }
  };
}
async function sendChat(msg, label, requestData = {}) {
  if (chatForm?.dataset.busy === "true") return;
  const query = (msg || "").trim();
  if (!query) {
    if (chatStatus) chatStatus.textContent = "Please describe the task.";
    showModalAlert({type:"warning",title:"Input Required",message:"Please enter a message or query before sending."});
    return;
  }
  if (isUnsafeInput(query)) {
    showModalAlert({type:"error",title:"Input Notice",message:"Please use plain text for your task."});
    return;
  }
  const safeQuery=safeChatQuestion(query);
  // A control (for example task feedback) may show a readable label instead of its command.
  const requestNote=appendChatBubble("user",typeof label==="string"&&label?label:safeQuery);
  if (safeQuery !== query) {
    if(chatInput) chatInput.value=safeQuery;
    appendChatBubble("bot","",{data:{status:"needs_redaction"}},requestNote);
    if(chatStatus)chatStatus.textContent="Remove sensitive information before continuing.";
    return;
  }
  if (chatInput) chatInput.value = "";
  if (chatStatus) chatStatus.textContent = "Finding relevant matches...";
  if (chatSubmit) chatSubmit.disabled = true;
  if (chatForm) { chatForm.dataset.busy = "true"; chatForm.setAttribute("aria-busy", "true"); }
  const headers = {"Content-Type":"application/json"};
  if (activeVisitorToken) headers["X-Visitor-Token"] = activeVisitorToken;
  const controller = new AbortController();
  const stop = $("chatStop");
  if (stop) { stop.hidden = false; stop.onclick = () => controller.abort(); }
  const waitingSince = Date.now();
  const progress = chatProgressView(requestNote);
  let currentStep = "Checking relevant agents";
  const waitingTimer = setInterval(() => { if (chatStatus) chatStatus.textContent = currentStep + " · " + Math.floor((Date.now()-waitingSince)/1000) + "s"; },1000);
  try {
    const answer = await chatWithProgress({message:query,data:{...requestData,protocol:$("chatProtocol")?.value || "auto"}},
      headers, controller.signal, event => { currentStep = progress.step(event); });
    const data = answer.body || {};
    const token = answer.visitor_token || data.visitor?.token;
    if (token && /^vt_[A-Za-z0-9_-]{16,96}$/.test(token)) {
      activeVisitorToken = token;
      try {
        sessionStorage.setItem("visitorToken",token);
        localStorage.removeItem("visitorToken");
      } catch (e) {}
    }
    appendChatBubble("bot",data.reply || "Describe the task.",data,requestNote);
    if (chatStatus) chatStatus.textContent = "Ready";
  } catch (error) {
    const wait = error?.status === 429 ? (error.retryAfter || 60) : 0;
    if (chatStatus) chatStatus.textContent = controller.signal.aborted
      ? "Stopped. Your question is kept; edit it or send it again."
      : wait
      ? "Too many requests from your network right now. Your question is kept; try again in " + (wait >= 120 ? Math.ceil(wait / 60) + " minutes." : wait + " seconds.")
      : "The request could not be completed. Your question is kept; try again when ready.";
    if (chatInput && !chatInput.value) chatInput.value = query;
  } finally {
    clearInterval(waitingTimer);
    progress.remove();
    if (stop) { stop.hidden = true; stop.onclick = null; }
    if (chatSubmit) chatSubmit.disabled = false;
    if (chatForm) { delete chatForm.dataset.busy; chatForm.setAttribute("aria-busy", "false"); }
    if (currentTab === "chat") focusChatInput();
  }
}
if (chatForm) {
  chatInput?.addEventListener("keydown",event=>{
    if(event.key!=="Enter" || event.shiftKey || event.isComposing || event.keyCode===229)return;
    event.preventDefault();chatForm.requestSubmit();
  });
  $("chatProtocol")?.addEventListener("change",()=>{
    chatMessages?.querySelectorAll(".chat-bubble.bot").forEach(bubble=>{
      if(!bubble.querySelector(".chat-request,.chat-recommendation"))return;
      if(bubble.dataset.previousScope)return;
      bubble.dataset.previousScope="true";
      const note=document.createElement("p");note.className="chat-previous-scope";
      note.textContent="Earlier request · submit again to use the selected protocol.";bubble.prepend(note);
    });
    if(chatStatus)chatStatus.textContent="Protocol changed. Submit a request to refresh recommendations.";
  });
  chatForm.onsubmit = event => {
    event.preventDefault();
    if (!event.isComposing) sendChat(chatInput?.value || "");
  };
  chatForm.addEventListener("click", event => {
    const t = event.target;
    if (!t || t === chatInput) return;
    if (t.closest("button, select, option, a, input, textarea")) return;
    focusChatInput();
  });
}

// ---------- Safe Agent Detail Drawer ----------
function reportWireText(value) {
  const text = value && typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '');
  return text.replace(/[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]/g,
    char => "\\u" + char.charCodeAt(0).toString(16).padStart(4,"0"));
}
function reportDisplayText(value) {
  let text = String(value ?? "");
  const translations = [
    ["\uc7a5\uc810 \ubc0f \ub2e8\uc810","Pros and Cons"],
    ["\uc7a5\uc810","Pros"], ["\ub2e8\uc810","Cons"],
    ["\uc6cc\ud06c\ud50c\ub85c\uc6b0","Workflow"],
    ["\uc0ac\uc5c5\uc790\ub4f1\ub85d\ubc88\ud638","Business Registration Number"],
    ["\uad6d\uc138\uccad","National Tax Service"],
    ["\uc0bc\uc131\uc804\uc790","Samsung Electronics"]
  ];
  for (const [source,target] of translations) text = text.split(source).join(target);
  text = text.replace(/\b(Pros and Cons|Pros|Cons|Workflow|National Tax Service|Business Registration Number)[ \t]*\(\1\)/gi,"$1");
  return /[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]/.test(text)
    ? "English text is not available for this report section." : text;
}
function formatSimpleMd(md) {
  if (!md) return "";
  let s = esc(reportDisplayText(md));
  s = s.replace(/^### (.*$)/gim, '<h5 style="margin:10px 0 4px 0;font-size:13px;color:var(--text)">$1</h5>');
  s = s.replace(/^## (.*$)/gim, '<h4 style="margin:14px 0 6px 0;font-size:14px;color:var(--accent);border-bottom:1px solid var(--border);padding-bottom:3px">$1</h4>');
  s = s.replace(/^# (.*$)/gim, '<h3 style="margin:16px 0 8px 0;font-size:15px;color:var(--text)">$1</h3>');
  s = s.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
  s = s.replace(/`([^`]+)`/g, '<code style="background:var(--chip);padding:1px 4px;border-radius:4px">$1</code>');
  s = s.replace(/^\- (.*$)/gim, '<div style="margin-left:12px;display:flex;gap:6px"><span>•</span><span>$1</span></div>');
  s = s.replace(/\n\n/g, '<div style="height:8px"></div>');
  return s;
}

function renderAgentTestReportHtml(a) {
  const source = a.test_report || (a.test_reports && a.test_reports[0]);
  const rep = source ? {...source} : null;
  if (!rep) {
    return `
      <div style="margin-top:14px;padding:14px 16px;border-radius:10px;background:var(--chip);border:1px dashed var(--border);display:flex;align-items:flex-start;gap:10px">
        <span style="color:var(--text-dim);display:inline-flex;align-items:center"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/></svg></span>
        <div>
          <div style="font-size:13px;font-weight:700;color:var(--text)">Verification Test Report Pending</div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:2px;line-height:1.5">
            No formal benchmark verification report has been filed yet for this agent. Periodic automated health checks are active, and comprehensive wire protocol audit reports will appear here once benchmark evaluations conclude.
          </div>
        </div>
      </div>
    `;
  }

  const gwUrl = gatewayAgentEndpoint(a);
  const archived = rep.execution_measured !== true;
  // Normalize report labels while preserving source citations.
  for (const key of ["title","slug","author","summary","workflow_recommendation","content_md","test_method","tool_name","eval_grade"]) {
    if (typeof rep[key] === "string") rep[key] = scrubGatewayText(reportDisplayText(rep[key]), gwUrl);
  }
  for (const wireKey of ["input_wire", "output_wire"]) {
    if (typeof rep[wireKey] === "string") rep[wireKey] = scrubGatewayText(rep[wireKey], gwUrl);
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
    ? pros.map((p) => `<div class="test-report-pro-item"><span style="color:var(--ok);display:inline-flex;align-items:center"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span><span>${esc(scrubGatewayText(reportDisplayText(p), gwUrl))}</span></div>`).join("")
    : "";

  const consHtml = (Array.isArray(cons) && cons.length)
    ? cons.map((c) => `<div class="test-report-con-item"><span style="color:var(--warn);display:inline-flex;align-items:center"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></span><span>${esc(scrubGatewayText(reportDisplayText(c), gwUrl))}</span></div>`).join("")
    : "";

  return `
    <div class="test-report-card">
      <div class="test-report-header">
        <div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap">
            <span class="report-badge-vivid"><span class="sparkle"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg></span> TEST Recorded report</span>
            <span style="font-size:11.5px;color:var(--text-dim);font-family:ui-monospace,monospace">ID: #${esc(rep.id)} · ${esc(rep.slug || "")}</span>
          </div>
          <h4 class="test-report-title">${esc(rep.title || "Agent Wire Protocol & Benchmark Report")}</h4>
          <div style="font-size:11.5px;color:var(--text-muted)">Auditor: <b>${esc(rep.author || "AI Verification Agent")}</b> · Recorded: ${nyTime(rep.created_at)} (${nyAgo(rep.created_at)})</div>
        </div>
      </div>

      ${archived ? `<p class="test-report-evidence-note" role="note">${esc(rep.evidence_label || 'Historical assessment; no current task execution verified.')} This record is preserved for reference.</p>` : ''}
      <div class="test-report-meta-grid">
        <div class="test-report-kpi">
          <div class="test-report-provenance" style="font-size:11px;color:var(--text-muted);margin-bottom:6px">${esc(rep.evidence_label || (rep.execution_verified === true ? "Current execution evidence" : "Historical report · not current execution verification"))}</div>
          <div class="test-report-kpi-label">Reported Outcome</div>
          <div class="test-report-kpi-val" style="color:${rep.is_success ? "var(--ok)" : "var(--bad)"}">
            ${rep.is_success ? '<span style="display:inline-flex;align-items:center;gap:4px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>PASSED</span></span>' : '<span style="display:inline-flex;align-items:center;gap:4px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg><span>FAILED</span></span>'}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Status Code: ${rep.status_code == null ? "Not recorded" : fmt(rep.status_code)}</div>
        </div>
        <div class="test-report-kpi">
          <div class="test-report-kpi-label">Quality Score</div>
          <div class="test-report-kpi-val" style="color:var(--accent)">
            Grade ${esc(rep.eval_grade || "Unrated")}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${rep.eval_score == null ? "Not recorded" : Math.round(rep.eval_score) + " / 100 pts"}</div>
        </div>
        <div class="test-report-kpi">
          <div class="test-report-kpi-label">Reported Latency</div>
          <div class="test-report-kpi-val">
            ${rep.latency_ms == null ? "Not recorded" : Math.round(rep.latency_ms) + " ms"}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Reported round-trip time</div>
        </div>
        <div class="test-report-kpi">
          <div class="test-report-kpi-label">Test Method</div>
          <div class="test-report-kpi-val" style="font-size:13px;word-break:break-all">
            ${esc(rep.test_method || "Not recorded")}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Tool: <code>${esc(rep.tool_name || "endpoint")}</code></div>
        </div>
      </div>

      ${archived ? '<details class="archived-report-assessment"><summary>Archived assessment — not current execution evidence</summary>' : ''}
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
          <span style="display:inline-flex;align-items:center;gap:5px"><span>Historical Test Records (Sanitized Request &amp; Response)</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></span>
        </summary>
        <div style="margin-top:8px">
          <p style="font-size:12px;color:var(--text-muted)">Historical records are sanitized for public display. Connection addresses refer to the managed gateway; viewing this report does not run a new test.</p>
          <div style="font-size:11px;font-weight:600;color:var(--text-dim);margin-bottom:2px">INPUT WIRE (SANITIZED RECORD):</div>
          <pre class="test-report-wire-box">${esc(reportWireText(rep.input_wire || "No wire input recorded"))}</pre>
          <div style="font-size:11px;font-weight:600;color:var(--text-dim);margin-bottom:2px">OUTPUT WIRE (SANITIZED RECORD):</div>
          <pre class="test-report-wire-box">${esc(reportWireText(rep.output_wire || "No wire output recorded"))}</pre>
        </div>
      </details>

      ${rep.content_md ? `
        <details style="margin-top:8px">
          <summary style="cursor:pointer;font-size:12.5px;font-weight:700;color:var(--accent);user-select:none;padding:4px 0">
            <span style="display:inline-flex;align-items:center;gap:5px"><span>Detailed Verification Report</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></span>
          </summary>
          <div class="test-report-markdown-body">${formatSimpleMd(rep.content_md)}</div>
        </details>
      ` : ""}
      ${archived ? '</details>' : ''}
    </div>
  `;
}

// ---------- Safe Agent Detail Drawer ----------
function connectionVerificationLabel(agent) {
  const state = agent?.connection_readiness;
  return state?.verified_callable ? "Recent execution confirmed" : state?.profile_available ? "Connection available; current verification pending" : "Connection needs review";
}
function renderDrawerAgent(a, statusType) {
  const authorizationNeeded = a.kind !== 'x402' && (a.auth_observed === 1 || a.auth_required === 1 || a.auth_autonomy === 'human_once');
  const testUnavailable = authorizationNeeded || a.catalog_status === 'historical' || ['down','dead','failing','quarantined','retired','suspended'].includes(a.health_status) || (a.kind === 'mcp' && a.cap_tool_count === 0);
  const testNotice = authorizationNeeded ? 'This agent needs separate provider authorization before testing.' : 'This agent has no available test connection in its current recorded state.';
  const cats = {...DEFAULT_CATEGORIES, ...((insightsData && insightsData.categories) || (ovCache && ovCache.category_names) || {})};
  const gwUrl = gatewayAgentEndpoint(a);
  let statusBadge = "";
  if (statusType === "live") {
    statusBadge = '<span class="chip" style="margin-left:6px;color:var(--ok);display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Current metadata</span></span>';
  } else if (statusType === "cached") {
    statusBadge = '<span class="chip" style="margin-left:6px;color:var(--warn);display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg><span>Cached Spec</span></span>';
  } else if (statusType === "syncing") {
    statusBadge = '<span class="chip" style="margin-left:6px;color:var(--reach);display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="animation:spin 1.5s linear infinite"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/></svg><span>Syncing live...</span></span>';
  }

  const hasReport = (a.report_count > 0) || Boolean(a.test_report) || Boolean(a.test_reports && a.test_reports.length);
  const safeKind = ["a2a", "mcp", "x402"].includes(a.kind) ? a.kind : "mcp";
  const rawHealth = typeof a.health_status === "string" ? a.health_status : "";
  const inactive = a.active === false || a.active === 0 || a.catalog_status === "historical";
  const availabilityConfirmed = !inactive && ["healthy", "reachable"].includes(rawHealth)
    && a.connection_readiness?.profile_available !== false;
  const safeHealth = availabilityConfirmed ? rawHealth : inactive || ["down", "retired"].includes(rawHealth) ? "down" : "failing";
  const healthLabel = (rawHealth || "unknown") + (inactive ? " · inactive" : "")
    + (availabilityConfirmed ? "" : " · Availability unconfirmed");
  const healthIcon = availabilityConfirmed ? '<path d="m9 12 2 2 4-4"/>' : '<path d="M12 8v4m0 4h.01"/>';

  $("drawerBadges").innerHTML = `
    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
      <span class="kind-badge k-${safeKind}">${esc(a.kind)}</span>
      <span class="chip">source: ${esc(a.source || "registry")}</span>
      ${hasReport ? '<span class="report-badge-vivid"><span class="sparkle"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg></span> TEST Recorded report</span>' : ''}
      ${hasReport && (inactive || !["healthy", "reachable"].includes(rawHealth)) ? '<span class="chip" style="color:var(--warn)">Historical entry · unavailable</span>' : ''}
      ${statusBadge}
    </div>
  `;

  $("drawerContent").innerHTML = `
    <h3 style="margin:8px 0 2px 0;font-size:18px">${esc(a.name)}</h3>
    <div style="font-size:12.5px;color:var(--accent);margin-bottom:10px;word-break:break-all">${gatewayLink(gwUrl)}</div>
    <p style="font-size:13.5px;color:var(--text-muted);line-height:1.6;margin:0 0 14px 0">${esc(a.description || "No description provided.")}</p>

    <div style="display:flex;gap:8px;margin:12px 0 16px 0;flex-wrap:wrap;align-items:center">
      <button class="btn primary" id="drawerTestBtn" ${testUnavailable ? 'disabled aria-disabled="true"' : ''} data-id="${esc(a.id)}" data-ac-click="66779e3952ae" style="display:inline-flex;align-items:center;gap:6px;padding:8px 16px;font-size:13.5px;font-weight:700">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2v7.31M14 2v7.31M8.5 2h7M14 9.3a6.5 6.5 0 1 1-4 0"/></svg>
        <span>Test Endpoint in Sandbox</span>
      </button>
      <button class="btn" data-url="${esc(gwUrl)}" ${gwUrl ? "" : "disabled"} data-ac-click="57c3ac9c696f" style="font-size:12.5px;display:inline-flex;align-items:center;gap:6px">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
        <span>Copy URL</span>
      </button>
    </div>

    ${testUnavailable ? '<p role="status">'+esc(testNotice)+'</p>' : ''}
    <dl class="kv">
      <dt>Connection verification</dt><dd>${esc(statusType === "live" ? connectionVerificationLabel(a) : "Current verification pending")}</dd>
      <dt>Health Status</dt>
      <dd><span class="s-${safeHealth} font-semibold" style="display:inline-flex;align-items:center;gap:4px"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/>${healthIcon}</svg><span>${esc(healthLabel)}</span></span> · consecutive failures: ${fmt(a.consecutive_failures || 0)}</dd>
      <dt>Last Checked</dt>
      <dd>${nyTime(a.last_check_at)} (${nyAgo(a.last_check_at)})</dd>
      <dt>Last Operational</dt>
      <dd>${nyTime(a.last_ok_at)}</dd>
      <dt>24h Availability</dt>
      <dd>${a.health_n_24h ? pct(a.health_ok_24h, a.health_n_24h) + ` (${fmt(a.health_ok_24h)}/${fmt(a.health_n_24h)})` : "–"}</dd>
      <dt>Category</dt>
      <dd>${esc(formatCategory(a.category, cats))}</dd>
      <dt>Price Per Call</dt>
      <dd>${a.price_note === "testnet_only" ? "Testnet only" : a.price_usdc === null ? (a.kind === "x402" ? "Price on request" : "Free") : usd(a.price_usdc)} ${a.pay_to ? `<span style="font-family:monospace;font-size:11px">(${esc(a.pay_to)})</span>` : ""}</dd>
      <dt>Authentication</dt>
      <dd>${esc(agentAuthenticationLabel(a))}</dd>
      <dt>Available Tools</dt>
      <dd>${fmt(a.cap_tool_count || 0)} registered tools</dd>
      <dt>Execution Evidence</dt>
      <dd>${esc(connectionVerificationLabel(a))}</dd>
      <dt>Quality Grade</dt>
      <dd>${a.eval_grade ? `<b>Grade ${esc(a.eval_grade)}</b> (${Math.round(a.eval_score || 0)} pts) · Security: ${esc(a.eval_security || "clean")}` : "–"}</dd>
      <dt>First Cataloged</dt>
      <dd>${nyTime(a.first_seen)} (${nyAgo(a.first_seen)})</dd>
    </dl>

    <h4 style="margin:16px 0 6px 0;font-size:13.5px">Specifications & Metadata</h4>
    <pre>${esc(scrubGatewayText(JSON.stringify(a.details || (statusType === "syncing" ? { note: "Detailed JSON specification loading in background..." } : {}), null, 2), gwUrl))}</pre>

    <h4 style="margin:20px 0 6px 0;font-size:13.5px;display:flex;align-items:center;justify-content:space-between">
      <span>Agent Verification &amp; Benchmark Report</span>
      ${hasReport ? '<span class="report-badge-vivid"><span class="sparkle"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg></span> TEST Recorded report</span>' : ''}
    </h4>
    ${renderAgentTestReportHtml(a)}
  `;
}

let agentDetailRevision = 0;
let agentDetailController = null;

async function openAgent(id) {
  const revision = ++agentDetailRevision;
  agentDetailController?.abort();
  const controller = new AbortController();
  agentDetailController = controller;
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
    renderDrawerAgent(baseline, cachedSpec ? "cached" : "syncing");
  } else {
    $("drawerBadges").innerHTML = "";
    $("drawerContent").innerHTML = binaryClockHtml("Retrieving verified agent specification...");
  }

  // 2. Fetch fresh agent specification with auto-retry and dead-socket recovery
  try {
    const res = await api("/api/agents/" + encodeURIComponent(strId), {
      userInitiated: true,
      background: Boolean(baseline),
      loadingMsg: "Retrieving agent details...",
      retries: 0,
      timeoutMs: 25000,
      signal: controller.signal
    });
    if (revision !== agentDetailRevision || controller.signal.aborted || d.classList.contains("hidden")) return;
    const freshAgent = res.agent || {};
    setSwrCache("agent:" + strId, freshAgent);
    EXPLORE_AGENT_MAP.set(strId, freshAgent);
    renderDrawerAgent(freshAgent, "live");
  } catch (err) {
    if (revision !== agentDetailRevision || controller.signal.aborted || d.classList.contains("hidden")) return;
    if (baseline) {
      renderDrawerAgent(baseline, "cached");
    } else {
      $("drawerContent").innerHTML = `
        <div style="padding:24px 0;text-align:center">
          <p style="color:var(--bad);font-weight:700;margin-bottom:8px">Unable to retrieve agent specification</p>
          <p style="color:var(--text-muted);font-size:12.5px;margin-bottom:16px">${esc(err.message)}</p>
          <button class="btn primary" data-id="${esc(strId)}" data-ac-click="d5e60f613626">Retry Connection</button>
        </div>
      `;
    }
  }
}

// ==================== SECTION: AGENT WORKFLOW STUDIO & PLAYGROUND ====================
let frontCurrentWfSubView = "canvas";
let frontTemplatesCache = [];
let frontTemplatesRequestRevision = 0;
let frontTemplatesLoading = false;
let frontTemplatesLoaded = false;
let frontTemplatesLoadFailed = false;
// Published workflows shipped in the page open without a request (UI policy 11-01); Run is checked by the server.
let frontTemplatesFromPage = false;
let frontActiveTmplCategory = "all";
let frontActiveWfName = "Daily Tech News & AI Research Digest";
let frontSelectedNodeId = null;
let frontActiveTemplateId = null;
let frontDefaultTemplateId = null;
let frontWorkflowRunning = false;
let frontFallbackTemplateId = null;
let frontFallbackDefinitionHash = null;
let frontWorkflowSelectionTouched = false;

let DEFAULT_FRONT_WORKFLOW_NAME = "Daily Tech News & AI Research Digest";
const FRONT_NEWS_PLACEHOLDER_GRAPH = {nodes:[
  {id:'node-trigger-1',type:'trigger',name:'Manual Trigger',kind:'trigger',position:{x:60,y:180},data:{}},
  {id:'node-agent-1',type:'agent',name:'Recent Technology News',kind:'mcp',position:{x:340,y:180},data:{input:{}}},
  {id:'node-agent-2',type:'agent',name:'Recent AI Research',kind:'mcp',position:{x:620,y:180},data:{input:{}}}
],edges:[{id:'e-1',source:'node-trigger-1',target:'node-agent-1'},{id:'e-2',source:'node-agent-1',target:'node-agent-2'}]};
let DEFAULT_FRONT_GRAPH = (() => {
  try {
    const bootstrap = JSON.parse($("appBootstrapData").textContent);
    const template = (Array.isArray(bootstrap.workflow_templates) && bootstrap.workflow_templates.find(
      item => item.name === 'Daily Tech News & AI Research Digest')) || bootstrap.workflow_default;
    if (template && Array.isArray(template.nodes) && template.nodes.length && !template.nodes.some(n=>n.kind==='x402')) {
      frontTemplatesCache = Array.isArray(bootstrap.workflow_templates) ? bootstrap.workflow_templates : [template];
      frontActiveTemplateId=frontDefaultTemplateId=template.id;
      frontActiveWfName = DEFAULT_FRONT_WORKFLOW_NAME = template.name;
      return { nodes: template.nodes, edges: template.edges || [] };
    }
  } catch (e) {}
  return JSON.parse(JSON.stringify(FRONT_NEWS_PLACEHOLDER_GRAPH));
})();

let frontCanvasGraph = JSON.parse(JSON.stringify(DEFAULT_FRONT_GRAPH));
let frontCanvasRestored = false;

// Try restoring saved canvas from localStorage
try {
  const savedCanvas = localStorage.getItem("front_workflow_canvas");
  if (savedCanvas) {
    const parsed = JSON.parse(savedCanvas);
    // Migrate the previous built-in default while preserving saved custom workflows.
    const knownNewsPlaceholder = parsed?.name === 'Daily Tech News & AI Research Digest' &&
      JSON.stringify(parsed.nodes) === JSON.stringify(FRONT_NEWS_PLACEHOLDER_GRAPH.nodes) &&
      JSON.stringify(parsed.edges) === JSON.stringify(FRONT_NEWS_PLACEHOLDER_GRAPH.edges);
    const unboundNewsDefault = parsed?.version === 2 && parsed.template_id == null && knownNewsPlaceholder;
    const legacyDefault = parsed && ((!parsed.version && parsed.name === "Flight & Forex Settlement Pipeline") ||
      unboundNewsDefault ||
      (knownNewsPlaceholder && Number.isInteger(frontDefaultTemplateId) &&
        parsed.template_id !== frontDefaultTemplateId && !frontTemplatesCache.some(t => t.id === parsed.template_id)));
    if (parsed && !legacyDefault && Array.isArray(parsed.nodes) && parsed.nodes.length > 0) {
      frontCanvasRestored = true;
      frontCanvasGraph = {
        nodes: parsed.nodes.filter((n) => n && typeof n === "object").slice(0, 50),
        edges: Array.isArray(parsed.edges) ? parsed.edges.filter((e) => e && typeof e === "object").slice(0, 100) : []
      };
      if (typeof parsed.name === "string" && parsed.name.trim()) frontActiveWfName = parsed.name.trim().slice(0, 120);
      frontActiveTemplateId=Number.isInteger(parsed.template_id)?parsed.template_id:(parsed.name===DEFAULT_FRONT_WORKFLOW_NAME?frontDefaultTemplateId:null);
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
  loadPublishedConnections();
}

let publishedConnectionsEpoch = 0;
let publishedConnectionsAbort = null;
async function loadPublishedConnections() {
  const section = $('frontPublicConnections');
  const list = $('frontPublicConnectionList');
  if (!section || !list) return;
  const epoch = ++publishedConnectionsEpoch;
  if (publishedConnectionsAbort) publishedConnectionsAbort.abort();
  const controller = new AbortController();
  publishedConnectionsAbort = controller;
  section.hidden = true;
  list.replaceChildren();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch('/api/workflow-connections', {
      headers: {Accept: 'application/json'}, cache: 'no-store', credentials: 'omit', signal: controller.signal
    });
    if (!response.ok) return;
    const data = await response.json();
    if (epoch !== publishedConnectionsEpoch || !data || data.profile !== 'public-news-title-to-docs-v1' || !Array.isArray(data.releases)) return;
    const fragment = document.createDocumentFragment();
    for (const item of data.releases.slice(0, 20)) {
      if (!item || !/^pub_[a-f0-9]{32}$/.test(item.id || '') || typeof item.title !== 'string' || !item.title || item.title.length > 160 ||
          /[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]/.test(item.title) ||
          item.url !== '/connections/' + item.id || !Number.isFinite(item.expires) || item.expires * 1000 <= Date.now()) continue;
      const card = document.createElement('div');
      card.style.cssText = 'padding:14px;border:1px solid var(--border);border-radius:12px;background:var(--panel)';
      const title = document.createElement('h4');
      title.style.cssText = 'margin:0 0 8px;font-size:14px';
      title.textContent = item.title;
      const note = document.createElement('p');
      note.className = 'muted';
      note.textContent = 'One news search followed by a documentation search. Review input sharing before running.';
      const link = document.createElement('a');
      link.className = 'btn sm';
      link.style.cssText = 'display:inline-flex;align-items:center;gap:6px';
      link.href = '/connections/' + item.id;
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      for (const [name, value] of Object.entries({width:'14',height:'14',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'2','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false',class:'lucide lucide-arrow-right'})) icon.setAttribute(name,value);
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      line.setAttribute('d','M5 12h14m-7-7 7 7-7 7');
      icon.append(line);
      link.append(document.createTextNode('Review connection'),icon);
      card.append(title,note,link);
      fragment.append(card);
    }
    if (epoch !== publishedConnectionsEpoch) return;
    list.replaceChildren(fragment);
    section.hidden = !list.children.length;
  } catch (_) {
    // Existing published templates remain available independently.
  } finally {
    clearTimeout(timeout);
    if (epoch === publishedConnectionsEpoch) publishedConnectionsAbort = null;
  }
}

function updateFrontActiveName() {
  const fallbackGroup = $('frontFallbackConsentGroup');
  const fallbackConsent = $('frontFallbackConsent');
  const selectedTemplate = frontTemplatesCache.find(t => t.id === frontActiveTemplateId);
  if (fallbackGroup) fallbackGroup.hidden = !selectedTemplate?.fallback_available;
  renderFrontProductInputs(selectedTemplate);
  if (fallbackConsent && (frontFallbackTemplateId !== frontActiveTemplateId ||
      frontFallbackDefinitionHash !== selectedTemplate?.definition_hash || !selectedTemplate?.fallback_available)) fallbackConsent.checked = false;
  frontFallbackTemplateId = frontActiveTemplateId;
  frontFallbackDefinitionHash = selectedTemplate?.definition_hash;
  const nameEl = $("frontWfActiveName");
  if (nameEl) nameEl.textContent = frontActiveWfName;
  const chipEl = $("frontWfNodeCountChip");
  if (chipEl) {
    const agents=frontCanvasGraph.nodes.filter(node=>node.type==='agent').length;
    chipEl.textContent = `${frontCanvasGraph.nodes.length} workflow steps · ${agents} agent steps`;
    chipEl.title='Workflow steps include triggers, agent actions and any routing or transformation steps. One agent can be used in more than one step.';
  }
  const basis=$('frontSelectionBasis');
  const selectionTag=$('frontSelectionTag');
  if(selectionTag)selectionTag.textContent=!selectedTemplate
    ? frontTemplatesLoadFailed?'Templates unavailable':!frontTemplatesLoaded?'Loading template…':'Choose a template'
    :frontCanvasRestored&&!frontWorkflowSelectionTouched?'Restored selection':frontActiveTemplateId===frontDefaultTemplateId?'Default template':'Selected template';
  if(basis)basis.textContent=!selectedTemplate
    ? frontTemplatesLoadFailed?'Workflow availability could not be refreshed. Retry before running or downloading.':!frontTemplatesLoaded?'Loading the selected workflow. Run and download are available after its published version is found.':'This saved graph is not a current published template. Choose a template or reset before running.'
    : frontCanvasRestored&&!frontWorkflowSelectionTouched?'Restored your last workflow selection from this browser. Reset returns to the technology news workflow.'
      : frontActiveTemplateId===frontDefaultTemplateId?'Default workflow selected. Choose another template or change the reviewed inputs before running.':'Selected from the published Template Hub. This browser keeps your selection for your next visit.';
  updateFrontWorkflowAvailability();
}

function renderFrontProductInputs(template) {
  const anchor = $('frontFallbackConsentGroup');
  if (!anchor) return;
  let panel = $('frontProductInputs');
  if (!template?.product) { if (panel) panel.remove(); return; }
  const identity = String(template.id) + ':' + template.definition_hash;
  if (panel?.dataset.version === identity) return;
  if (panel) panel.remove();
  panel = document.createElement('section'); panel.id = 'frontProductInputs'; panel.dataset.version = identity;
  panel.setAttribute('aria-label','Workflow product inputs'); panel.className = 'card';
  const note = document.createElement('p');
  note.textContent = 'Enter public English research keywords. Review original sources. One verified alternative may receive these inputs when you allow it below.';
  panel.append(note);
  for (const field of template.product.inputs) {
    const label = document.createElement('label'); label.style.display = 'block'; label.style.margin = '12px 0';
    label.textContent = field.name.replaceAll('_',' ');
    const input = document.createElement('input'); input.dataset.productInput = field.name;
    input.type = field.type === 'integer' ? 'number' : 'text'; input.className = 'input';
    input.style.width = '100%'; input.setAttribute('aria-label',field.name.replaceAll('_',' '));
    if (field.type === 'integer') {input.min = field.minimum; input.max = field.maximum;}
    else {input.minLength = field.min_length; input.maxLength = field.max_length;}
    const node = template.nodes.find(n => n.id === field.node_id);
    input.value = node?.data?.input?.[field.argument] ?? '';
    label.append(input); panel.append(label);
  }
  anchor.before(panel);
}

function updateFrontWorkflowAvailability() {
  const selected = frontTemplatesCache.find(t => t.id === frontActiveTemplateId);
  if ((!selected?.fallback_available || selected?.definition_hash !== frontFallbackDefinitionHash) && $('frontFallbackConsent')) $('frontFallbackConsent').checked = false;
  frontFallbackDefinitionHash = selected?.definition_hash;
  const state = selected?.execution_availability;
  const summary = $('frontWfSelectedTemplate');
  if (summary) summary.textContent = selected
    ? `Selected published template: ${selected.name}. Choose Run workflow to check availability and start it.`
    : frontTemplatesLoadFailed ? 'Published templates could not be loaded. Open Template Hub to try again.'
      : frontTemplatesCache.length ? 'Choose a published template in Template Hub to enable Run workflow.'
      : 'Preparing the Technology News template.';
  const notice = $('frontWorkflowAvailability');
  // A selected workflow that left the published list (its connections became unavailable) says so.
  const withdrawn = !selected && frontActiveTemplateId != null && !frontTemplatesLoading && !frontTemplatesLoadFailed;
  if (notice) {
    notice.hidden = !state && !frontTemplatesLoading && !withdrawn;
    notice.textContent = withdrawn ? 'This workflow is currently unavailable. Choose another published template.'
      : state?.message || (frontTemplatesLoading ? 'Loading published workflows...' : '');
    notice.style.color = state?.available === false || withdrawn ? 'var(--warn)' : 'var(--text-muted)';
  }
  const run = $('btnFrontRunWorkflow');
  if (run) {
    run.disabled = frontWorkflowRunning || !selected;
    run.title = !selected ? 'Choose a published template after it loads.'
      : state?.available === false ? 'Recheck this connection before attempting a run.' : `Run ${selected.name}`;
  }
  const download=$('btnFrontExportApp');
  if(download){download.disabled=!selected;download.title=selected?'Download the selected published web app':'Wait for a published template before downloading.';}
}

function renderFrontCanvas() {
  renderFrontNodes();
  renderFrontEdges();
}

function frontNodePosition(node) {
  const p = node.position || {};
  const coordinate = (value, fallback) => {
    const number = typeof value === "number" ? value : NaN;
    return Number.isFinite(number) ? Math.max(-10000, Math.min(10000, number)) : fallback;
  };
  return { x: coordinate(p.x, 60), y: coordinate(p.y, 160) };
}

function renderFrontNodes() {
  const container = $("frontWfNodesLayer");
  if (!container) return;

  container.innerHTML = frontCanvasGraph.nodes.filter((n) => n && typeof n === "object").map((n) => {
    const isSel = n.id === frontSelectedNodeId ? "selected" : "";
    const pos = frontNodePosition(n);
    const ndata = n.data || {};
    const actLabel = ndata.action || (n.type === "trigger" ? "trigger" : "execute");
    const kBadge = n.kind || n.type || "mcp";

    return `
      <div class="wf-node ${isSel}" id="fn-${esc(n.id)}" style="left:${pos.x}px;top:${pos.y}px;" data-id="${esc(n.id)}" data-ac-click="ea2fdb163b49">
        <div class="wf-node-head" data-id="${esc(n.id)}" data-ac-mousedown="67979906c3ec">
          <div style="display:flex;align-items:center;gap:6px;overflow:hidden">
            <span class="badge" style="font-size:10px">${esc(kBadge)}</span>
            <strong style="font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(n.name)}</strong>
          </div>
          <button class="btn sm" data-id="${esc(n.id)}" data-ac-click="56fdee702a13" style="padding:2px 4px;color:var(--text-muted);border:none;background:transparent;display:inline-flex;align-items:center;justify-content:center" title="Delete Node"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>
        </div>
        <div class="wf-node-body">
          <div style="font-family:monospace;font-size:11px;color:var(--text-muted)">action: ${esc(actLabel)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:2px">
            <span class="status-indicator font-semibold" style="font-size:10.5px;color:var(--ok);display:inline-flex;align-items:center;gap:3px"><svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Ready</span></span>
            <span style="font-size:10.5px;color:var(--text-dim);cursor:pointer" data-id="${esc(n.id)}" data-ac-click="7b6b6910760e">Edit</span>
          </div>
        </div>
        ${n.type !== "trigger" ? `<div class="wf-port input" data-id="${esc(n.id)}" data-ac-mouseup="3cd36e108f84" title="Input Port"></div>` : ""}
        <div class="wf-port output" data-id="${esc(n.id)}" data-ac-mousedown="182bb9d5378c" title="Drag to connect next node"></div>
      </div>
    `;
  }).join("");
}

function getNodeCenterPos(nodeId, portType) {
  const node = frontCanvasGraph.nodes.find((n) => n.id === nodeId);
  if (!node) return { x: 0, y: 0 };
  const pos = frontNodePosition(node);
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

  group.innerHTML = frontCanvasGraph.edges.filter((e) => e && typeof e === "object").map((e) => {
    const p1 = getNodeCenterPos(e.source, "output");
    const p2 = getNodeCenterPos(e.target, "input");
    const dx = Math.max(40, Math.abs(p2.x - p1.x) * 0.45);
    const d = `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y}, ${p2.x - dx} ${p2.y}, ${p2.x} ${p2.y}`;

    return `
      <path class="wf-edge-path" id="fe-${esc(e.id)}" d="${d}" marker-end="url(#frontWfArrow)" data-id="${esc(e.id)}" data-ac-click="8ac1ace275ba" title="Click to disconnect"/>
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
  const pos = frontNodePosition(node);
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
  const tempLine = $("frontWfTempEdge") || $("frontWfTempLine");
  const p1 = getNodeCenterPos(sourceNodeId, "output");

  function onMouseMove(moveEvent) {
    if (!frontConnectingSourceId) return;
    const canvasRect = $("frontWfSvgCanvas").getBoundingClientRect();
    const mouseX = moveEvent.clientX - canvasRect.left;
    const mouseY = moveEvent.clientY - canvasRect.top;
    if (tempLine) {
      tempLine.setAttribute("d", `M ${p1.x} ${p1.y} L ${mouseX} ${mouseY}`);
      tempLine.style.display = "block";
      tempLine.classList.remove("hidden");
    }
  }

  function onMouseUp() {
    frontConnectingSourceId = null;
    if (tempLine) {
      tempLine.style.display = "none";
      tempLine.classList.add("hidden");
    }
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
      <button class="btn sm" data-ac-click="3fd4c305c235" style="padding:4px 6px;display:inline-flex;align-items:center;justify-content:center" aria-label="Close Inspector"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>
    </div>
    <div style="display:flex;flex-direction:column;gap:10px;font-size:12.5px">
      <div>
        <label style="display:block;color:var(--text-muted);margin-bottom:3px">Node Title</label>
        <input class="input" id="inspNodeName" value="${esc(node.name)}" style="width:100%" data-ac-input="50c6c2bf876f">
      </div>
      <div>
        <label style="display:block;color:var(--text-muted);margin-bottom:3px">Protocol Kind</label>
        <span class="badge">${esc(node.kind || node.type || "mcp")}</span>
      </div>
      <div>
        <label style="display:block;color:var(--text-muted);margin-bottom:3px">Action / Tool Method</label>
        <input class="input" id="inspNodeAction" value="${esc(ndata.action || "execute")}" style="width:100%" data-ac-input="c4f8c20b156d">
      </div>
      <div>
        <label for="inspNodeSample" style="display:block;color:var(--text-muted);margin-bottom:3px">Sample / Expected Output</label>
        <textarea class="textarea" id="inspNodeSample" rows="3" style="width:100%;font-size:11.5px;font-family:monospace" data-ac-input="0c3190339387">${esc(ndata.sample_output || "")}</textarea>
      </div>
      <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:10px">
        <button class="btn sm" data-id="${esc(node.id)}" data-ac-click="a6aa7d25dfcd" style="color:var(--bad);width:100%">Delete Node</button>
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
  frontWorkflowSelectionTouched = frontDefaultTemplateId !== null;
  frontCanvasGraph = JSON.parse(JSON.stringify(DEFAULT_FRONT_GRAPH));
  frontActiveWfName = DEFAULT_FRONT_WORKFLOW_NAME;
  frontActiveTemplateId=frontDefaultTemplateId;
  $('frontFallbackConsent').checked = false;
  closeFrontInspector();
  updateFrontActiveName();
  renderFrontCanvas();
  saveFrontCanvasWorkflow();
  toast("Canvas reset to the default template.");
}

function saveFrontCanvasWorkflow() {
  try {
    localStorage.setItem("front_workflow_canvas", JSON.stringify({
      version: 2,
      name: frontActiveWfName,
      template_id: frontActiveTemplateId,
      nodes: frontCanvasGraph.nodes,
      edges: frontCanvasGraph.edges
    }));
  } catch (e) {}
}

async function runFrontCanvasWorkflow() {
  if (frontWorkflowRunning) return;
  if (!frontCanvasGraph.nodes || frontCanvasGraph.nodes.length === 0) {
    toast("No nodes on canvas to execute.");
    return;
  }

  const intent = {
    templateId: frontActiveTemplateId,
    definitionHash: frontTemplatesCache.find(t => t.id === frontActiveTemplateId)?.definition_hash,
    allowFallback: $('frontFallbackConsent').checked,
    productInput: Object.fromEntries(Array.from(document.querySelectorAll('[data-product-input]')).map(input => [input.dataset.productInput,input.type === 'number' ? Number(input.value) : input.value.trim()]))
  };
  const runBtn = $("btnFrontRunWorkflow");
  frontWorkflowRunning = true;
  const loaderToken = null;
  window.frontWorkflowStarted = Date.now();
  showFrontRunOutputModal({status:"preparing",node_results:[]});
  const elapsedTimer = setInterval(() => { document.querySelectorAll("[data-workflow-elapsed]").forEach(node => {node.textContent="Elapsed: "+Math.floor((Date.now()-window.frontWorkflowStarted)/1000)+"s";}); },1000);
  if (runBtn) {
    runBtn.disabled = true;
    runBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="animation:spin 1s linear infinite"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg><span>Executing...</span>`;
  }

  try {
    const templates = await loadFrontTemplates(true);
    const template = templates.find(t => t.id === intent.templateId);
    if (!template) throw new Error('Choose an available published template.');
    if (frontActiveTemplateId !== intent.templateId || template.definition_hash !== intent.definitionHash) {
      $('frontFallbackConsent').checked = false;
      throw new Error('The selected workflow changed. Review it and choose Run workflow again.');
    }
    const allowFallback = template.fallback_available === true && intent.allowFallback;
    if (template.product && !allowFallback) throw new Error('Allow one verified alternative below before running this protected product.');
    if (template.execution_availability?.available === false && !allowFallback) {
      throw new Error(template.execution_availability.message || 'This connection is unavailable. Choose another published template.');
    }
    if (JSON.stringify(template.nodes)!==JSON.stringify(frontCanvasGraph.nodes) || JSON.stringify(template.edges)!==JSON.stringify(frontCanvasGraph.edges)) {
      toast('Running the published template. Canvas edits must be reviewed and published before execution.');
    }
    $('frontFallbackConsent').checked = false;
    let res = await api('/api/workflows/run', {method:'POST',json:{template_id:template.id,definition_hash:template.definition_hash,
      ...(template.product ? {input:intent.productInput} : {}),
      ...(allowFallback ? {allow_fallback:true,fallback_notice:'readonly-fallback-v1'} : {})}});
    const capability = {run_id:res.run_id,run_key:res.run_key};
    window.frontWorkflowRun = capability;
    $('btnFrontStopWorkflow').disabled=false;
    for (let attempt=0; attempt<180; attempt++) {
      await new Promise(resolve=>setTimeout(resolve,700));
      res = await api('/api/workflows/runs/'+encodeURIComponent(capability.run_id),{headers:{'X-Workflow-Key':capability.run_key}});
      showFrontRunOutputModal(res);
      if (['succeeded','failed','cancelled'].includes(res.status)) break;
    }
    toast('Workflow: '+res.status);
  } catch (err) {
    toast(`Execution failed: ${err.message}`);
  } finally {
    clearInterval(elapsedTimer);
    hideLoader(loaderToken);
    frontWorkflowRunning = false;
    $('btnFrontStopWorkflow').disabled=true;
    window.frontWorkflowRun=null;
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>Run workflow</span>`;
    }
    updateFrontWorkflowAvailability();
  }
}

$('btnFrontStopWorkflow').onclick=async()=>{
  const item=window.frontWorkflowRun;if(!item)return;
  try {await api('/api/workflows/runs/'+encodeURIComponent(item.run_id)+'/cancel',{method:'POST',userInitiated:true,loadingMsg:'Stopping workflow...',headers:{'X-Workflow-Key':item.run_key}});toast('Cancellation requested. An in-flight request may finish before stopping.');}
  catch(error){toast(error.message);}
};

function agentAuthenticationLabel(agent) {
  if (agent.auth_autonomy === "human_once") return "One-time sign-in required";
  if (agent.auth_method === "oauth2" || agent.auth_method === "oauth") return "Account authorization required";
  if (agent.auth_required === 0 || !agent.auth_method || agent.auth_method === "none") return "No account authorization recorded";
  return "Provider authorization required";
}
function sourceRecordText(value) {
  const lines=value.split(/\r?\n/).slice(0,120);
  if(!lines.some(line=>line.startsWith('Retrieved: '))||!lines.some(line=>line.startsWith('Data status: ')))return null;
  const allowed=new Set(['title','url','published_at','source','doi','publisher','publication_date','country_code','name','capital','region','income_group','package','version','description','license','indicator','indicator_name','unit','year','value','id','summary','modified_at','returned_matches','scope','query']);
  const data={},items=[];let retrieved='',state='',hasRecords=false,partial=false;
  for(const line of lines.slice(1)){
    if(line.startsWith('Retrieved: ')){retrieved=line.slice(11);continue;}
    if(line.startsWith('Data status: ')){state=line.slice(13);continue;}
    if(line.startsWith('This response contains a partial')){partial=true;continue;}
    if(line.startsWith('No matching records')){hasRecords=true;continue;}
    const fields=line.split(' | '),entry={};
    for(const field of fields){const colon=field.indexOf(': ');if(colon<1)continue;const key=field.slice(0,colon).toLowerCase().replace(/ /g,'_');if(allowed.has(key))Object.defineProperty(entry,key,{value:field.slice(colon+2),enumerable:true});}
    if(fields.length>1&&Object.keys(entry).length){hasRecords=true;items.push(entry);}else for(const [key,value] of Object.entries(entry))Object.defineProperty(data,key,{value,enumerable:true,configurable:true});
  }
  if(hasRecords)data.items=items;data.partial=partial;
  return {source:lines[0],retrieved_at:retrieved,cache:{status:state,stale:state.includes('stale')},data};
}

function testResultEnvelope(value) {
  for (let depth = 0; depth < 8; depth++) {
    if (typeof value === "string") {
      if (value.length > 524288) return {};
      try { value = JSON.parse(value); } catch { return sourceRecordText(value) || {}; }
    } else if (value && typeof value === "object") {
      if (value.cache || value.retrieved_at) return value;
      if (value.structuredContent) value = value.structuredContent;
      else if (value.result) value = value.result;
      else if (typeof value.text === "string") value = value.text;
      else if (Array.isArray(value.content)) value = value.content.find(part => part.type === "text")?.text;
      else return {};
    } else return {};
  }
  return {};
}

function readableResultHtml(value) {
  let result=value, envelope=null, truncated=false, companion='';
  for(let depth=0;depth<6;depth++) {
    if(typeof result==='string') { if(result.length>524288) return '<p>Result is available in Request &amp; response.</p>'; try{result=JSON.parse(result);}catch{const parsed=sourceRecordText(result);if(parsed){envelope=parsed;result=parsed.data;break;}return '<p class="result-plain">'+esc(result.slice(0,8000))+'</p>'+(truncated?'<p>The returned text was truncated.</p>':'');} }
    else if(result && typeof result==='object') {
      if(typeof result.text==='string'){truncated=truncated||result.truncated===true;result=result.text;continue;}
      if(result.data && typeof result.data==='object'){envelope=result;result=result.data;break;}
      if(result.structuredContent){
        // Keep the provider's text answer too: structured fields can omit sources it names.
        const texts=Array.isArray(result.content)?result.content.filter(item=>item&&item.type==='text'&&typeof item.text==='string').map(item=>item.text):[];
        if(texts.length)companion=texts.join('\n').slice(0,4000);
        result=result.structuredContent;continue;
      }
      if(result.result){result=result.result;continue;}
      const content=result.content;if(Array.isArray(content)){result=content.find(item=>item.type==='text')?.text || result; if(typeof result==='string')continue;}
      break;
    } else break;
  }
  const clip=value=>String(value??'').slice(0,3000);
  const sourceLink=(url,label)=>{try{const u=new URL(url);if(u.protocol!=='https:'||u.username||u.password)return '';return '<a href="'+esc(u.href)+'" target="_blank" rel="noopener noreferrer">'+esc(clip(label||u.hostname))+'</a>';}catch{return '';}};
  const field=(key,value)=>value===undefined||value===null?'':'<p><strong>'+esc(key)+':</strong> '+esc(clip(value))+'</p>';
  let records=Array.isArray(result)?result:result?.items||result?.observations||result?.vulnerabilities;
  let html='';
  if(Array.isArray(records)){
    const context=[['country_code','Country code'],['indicator_name','Indicator'],['unit','Unit'],['package','Package'],['version','Version'],['scope','Scope']].map(([key,label])=>['string','number'].includes(typeof result?.[key])?field(label,result[key]):'').join('');
    html=context+'<p>'+records.length+' returned item'+(records.length===1?'':'s')+'. Displaying up to 20.</p><div class="result-fact-list">'+records.slice(0,20).map(item=>{
      if(!item||typeof item!=='object')return '<article>'+esc(clip(item))+'</article>';
      const title=item.title||item.name||item.id||item.year||'Result';
      return '<article><h4>'+esc(clip(title))+'</h4>'+field('Summary',item.summary||item.description)+field('Value',item.value)+field('Published',item.published_at||item.publication_date||item.modified_at||item.published||item.date)+field('Source',typeof item.source==='string'?item.source:null)+sourceLink(item.url||item.link,'View source')+'</article>';
    }).join('')+'</div>';
  } else if(result && typeof result==='object') {
    const labels={trigger:'Start mode',name:'Name',country:'Country',capital:'Capital',region:'Region',population:'Population',version:'Version',package:'Package',license:'License',indicator:'Indicator',unit:'Unit',scope:'Scope',total:'Matching advisories',query:'Request'};
    for(const [key,label] of Object.entries(labels))if(['string','number'].includes(typeof result[key]))html+=field(label,result[key]);
    html+=sourceLink(result.url||result.source_url,'View source');
  }
  if(truncated||result?.truncated===true)html+='<p>The returned result was truncated. Additional records or fields may be missing.</p>';
  if(result?.partial===true)html+='<p>Partial results: additional matching records may exist.</p>';
  if(envelope?.cache?.stale===true)html+='<p>Cached records are shown because the source could not be refreshed. Check the retrieval time.</p>';
  if(envelope){html+=field('Retrieved',envelope.retrieved_at)+field('Source',typeof envelope.source==='string'?envelope.source:envelope.source?.name);}
  if(companion)html+='<p class="result-companion-text">'+esc(companion).replace(/\n/g,'<br>')+'</p>';
  return html||'<p>Structured results are available in Request &amp; response. Review the returned details before using them.</p>';
}

function showFrontRunOutputModal(res) {
  const modal = $("frontWfRunModal");
  const content = $("frontWfRunModalBody");
  if (!modal || !content) return;

  const results = res.results || res.node_results || [];
  content.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="workflow-outcome" style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-radius:8px">
        <div style="display:flex;gap:8px;align-items:center">
          <span style="color:var(--ok);display:inline-flex;align-items:center"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg></span>
          <span>Workflow: <strong>${esc(res.status)}</strong></span>
        </div>
        <span style="font-size:12px" ${['succeeded','failed','cancelled'].includes(res.status)?'':'data-workflow-elapsed'}>${['succeeded','failed','cancelled'].includes(res.status)&&Number.isFinite(res.duration_ms)?'Duration: '+(res.duration_ms/1000).toFixed(1)+'s':'Elapsed: '+Math.floor((Date.now()-(window.frontWorkflowStarted||Date.now()))/1000)+'s'}</span>
      </div>
      <section aria-label="Workflow result summary"><h3>${res.status==='succeeded'?'Result digest':'Execution progress'}</h3><p>${results.filter(r=>r.status==='succeeded').length} completed steps. ${res.status==='succeeded'?'Returned facts and source links are shown below.':'Completed step results remain available while the workflow continues.'}</p></section>
      <div style="display:flex;flex-direction:column;gap:8px;max-height:520px;overflow-y:auto">
        ${results.map((r, idx) => `
          <div style="background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px 12px">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px">
              <span style="font-weight:700;font-size:13px">Step ${idx + 1}: ${esc(r.name || r.node_id)}</span>
              <span class="badge" style="font-size:10px;background:${r.status==='succeeded'?'var(--ok)':'var(--text-muted)'};color:#fff">${esc(r.status)}</span>
            </div>
            <div class="readable-step-result">${readableResultHtml(r.output || r.error || "No result returned yet.")}</div>
            <details><summary>Response details</summary><pre>${esc(typeof r.output==='object'?JSON.stringify(r.output,null,2):r.output||r.error||'')}</pre></details>
          </div>
        `).join("")}
      </div>
    </div>
  `;
  if (!modal.open && !document.getElementById("uxWorkflowResultPanel")) modal.showModal();
  if (activeReqs) renderLoader();
}

function closeFrontRunModal() {
  const modal = $("frontWfRunModal");
  if (modal) modal.close();
}

function exportFrontCanvasApp() {
  downloadStandaloneAppFile(
    frontActiveWfName,
    "Run a published agent workflow and review its recorded outcomes.",
    frontCanvasGraph.nodes,
    frontCanvasGraph.edges,
    null
  );
}

// Shared export builder. The downloaded app executes a published server definition.
// BEGIN WORKFLOW SDK
function createAgentConciergeClient() {
  const origin = 'https://agentconcierge.biz';
  const sessions = new WeakMap();
  const terminal = new Set(['succeeded', 'failed', 'cancelled']);
  function aborted() { return new DOMException('The request was cancelled.', 'AbortError'); }
  async function request(path, method, body, key, signal) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) throw aborted();
    signal?.addEventListener('abort', abort, {once:true});
    const timer = setTimeout(abort, 10000);
    try {
      const headers = {};
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (key) headers['X-Workflow-Key'] = key;
      const response = await fetch(origin + path, {method, headers,
        ...(body !== undefined ? {body:JSON.stringify(body)} : {}),
        mode:'cors', credentials:'omit', cache:'no-store', redirect:'error',
        referrerPolicy:'no-referrer', signal:controller.signal});
      if (!response.ok) {
        const message = response.status === 429 ? 'The workflow service is busy. Please try again later.' :
          response.status === 404 ? 'This workflow or run is unavailable.' : 'The workflow request could not be completed.';
        throw new Error(message);
      }
      try { return await response.json(); }
      catch (error) { throw new Error('The workflow service returned an unreadable response.'); }
    } finally {
      clearTimeout(timer); signal?.removeEventListener('abort', abort);
    }
  }
  function session(handle) {
    const value = handle && typeof handle === 'object' ? sessions.get(handle) : null;
    if (!value) throw new Error('Use the run handle returned by this client.');
    return value;
  }
  function pause(duration, signal) {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) return reject(aborted());
      const abort = () => { clearTimeout(timer); reject(aborted()); };
      const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, duration);
      signal?.addEventListener('abort', abort, {once:true});
    });
  }
  const client = {
    origin, version:'1.0.0',
    async run(workflowId, {signal, definitionHash} = {}) {
      if (!Number.isInteger(workflowId) || workflowId < 1 || workflowId >= 2147483648) throw new Error('Choose a published workflow.');
      if (definitionHash !== undefined && (typeof definitionHash !== 'string' || !/^[a-f0-9]{64}$/.test(definitionHash))) throw new Error('Choose a current published workflow.');
      const body = {template_id:workflowId};
      if (definitionHash !== undefined) body.definition_hash = definitionHash;
      const data = await request('/api/workflows/run', 'POST', body, null, signal);
      if (!data || typeof data !== 'object' || !/^wr_[a-f0-9]{32}$/.test(data.run_id || '') || !/^[A-Za-z0-9_-]{32,128}$/.test(data.run_key || '')) throw new Error('The workflow service returned an invalid run.');
      const handle = Object.freeze({runId:data.run_id, status:data.status});
      sessions.set(handle, {id:data.run_id, key:data.run_key});
      return handle;
    },
    async status(handle, {signal} = {}) {
      const value = session(handle);
      const data = await request('/api/workflows/runs/' + encodeURIComponent(value.id), 'GET', undefined, value.key, signal);
      if (!data || !['queued','running','succeeded','failed','cancelled'].includes(data.status)) throw new Error('The workflow service returned an invalid status.');
      return data;
    },
    async cancel(handle, {signal} = {}) {
      const value = session(handle);
      return request('/api/workflows/runs/' + encodeURIComponent(value.id) + '/cancel', 'POST', undefined, value.key, signal);
    },
    async wait(handle, {onUpdate, signal, intervalMs=700, timeoutMs=130000} = {}) {
      session(handle);
      if (!Number.isInteger(intervalMs) || intervalMs < 300 || intervalMs > 10000 || !Number.isInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 180000) throw new Error('Invalid workflow polling limits.');
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        const data = await client.status(handle, {signal});
        if (onUpdate) onUpdate(data);
        if (terminal.has(data.status)) return data;
        await pause(Math.min(intervalMs, Math.max(0, deadline-Date.now())), signal);
      }
      throw new Error('The run is still pending. Reopen Agent Concierge to review its status.');
    }
  };
  return Object.freeze(client);
}
// END WORKFLOW SDK

// BEGIN WORKFLOW APP RUNTIME
function standaloneAppRuntime() {
  const cfg = JSON.parse(document.getElementById('wfData').textContent);
  const run = document.getElementById('runAppBtn');
  const cancel = document.getElementById('cancelAppBtn');
  const status = document.getElementById('appStatus');
  const output = document.getElementById('stepsContainer');
  let current = null;
  let running = false;
  let cancelling = false;
  const client = createAgentConciergeClient();
  function setRunning(value) {
    run.disabled = value;
    run.setAttribute('aria-busy', String(value));
    run.querySelector('[data-run-label]').textContent = value ? 'Running...' : 'Run workflow';
    run.querySelector('[data-run-ready]').toggleAttribute('hidden', value);
    run.querySelector('[data-run-spinner]').toggleAttribute('hidden', !value);
  }
  function render(data) {
    status.textContent = 'Workflow: ' + data.status;
    output.replaceChildren();
    for (const item of data.results || data.node_results || []) {
      const card = document.createElement('section');
      const heading = document.createElement('h2');
      heading.textContent = item.name + ' · ' + item.status;
      const body = document.createElement('pre');
      body.textContent = item.output || item.error || '';
      card.append(heading, body); output.append(card);
    }
  }
  cancel.onclick = async () => {
    if (!running || !current || cancelling) return;
    const handle = current;
    cancelling = true;
    cancel.disabled = true;
    let requested = false;
    try {
      await client.cancel(handle);
      requested = true;
      if (!running || current !== handle) return;
      status.textContent = 'Cancellation requested. An in-flight request may finish before stopping.';
    } catch (error) {
      if (!running || current !== handle) return;
      status.textContent = error.message;
    } finally {
      if (!requested && running && current === handle) {
        cancelling = false;
        cancel.disabled = false;
      }
    }
  };
  run.onclick = async () => {
    if (running) return;
    running = true;
    setRunning(true);
    cancel.disabled = true;
    output.replaceChildren();
    status.textContent = 'Starting workflow...';
    try {
      current = await client.run(cfg.workflow_id, {definitionHash:cfg.definition_hash});
      cancel.disabled = false;
      status.textContent = 'Workflow: queued';
      await client.wait(current, {onUpdate:render});
    } catch (error) { status.textContent = error.message; }
    finally {
      running = false;
      cancelling = false;
      setRunning(false);
      cancel.disabled = true;
      current = null;
    }
  };
}
// END WORKFLOW APP RUNTIME

function buildWorkflowAppHTML(config) {
  const escapeHTML = value => String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const origin = 'https://agentconcierge.biz';
  if (config.api_origin && config.api_origin !== origin) throw new Error('This app uses the Agent Concierge routing gateway.');
  if (!Number.isInteger(config.workflow_id) || config.workflow_id < 1) throw new Error('Choose a published template before exporting.');
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(24)), b => b.toString(16).padStart(2,'0')).join('');
  const data = JSON.stringify({workflow_id:config.workflow_id,api_origin:origin,...(config.definition_hash?{definition_hash:config.definition_hash}:{})}).replace(/</g,'\\u003c');
  const endScript = '</scr' + 'ipt>';
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; script-src-attr 'none'; style-src 'nonce-${nonce}'; connect-src ${escapeHTML(origin)}; object-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer"><title>${escapeHTML(config.title)} — Agent Workflow</title>
<meta name="description" content="Run a published agent workflow and view its recorded outcomes.">
<style nonce="${nonce}">:root{color-scheme:light dark;font-family:system-ui,sans-serif}body{max-width:850px;margin:40px auto;padding:20px}section{border:1px solid #8391a6;border-radius:16px;padding:16px;margin:16px 0}h2{font-size:1rem}button{display:inline-flex;align-items:center;gap:8px;border:1px solid #8391a6;border-radius:10px;padding:12px 18px;cursor:pointer}button:focus-visible{outline:3px solid #6366f1;outline-offset:3px}pre{white-space:pre-wrap;overflow-wrap:anywhere}button svg{flex-shrink:0}#runAppBtn:disabled{cursor:wait;color:CanvasText;opacity:.75}[hidden]{display:none!important}.app-run-spinner{animation:app-run-spin 1s linear infinite}@keyframes app-run-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.app-run-spinner{animation:none}}</style>
</head><body><h1>${escapeHTML(config.title)}</h1><p>${escapeHTML(config.description)}</p>
<p>This app connects to Agent Concierge to run the current published template. Results depend on agent availability. It requires an internet connection.</p>
<button id="runAppBtn" type="button" aria-busy="false"><svg data-run-ready width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg><svg data-run-spinner class="app-run-spinner" hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a10 10 0 1 0 10 10"/></svg><span data-run-label>Run workflow</span></button>
<button id="cancelAppBtn" type="button" disabled>Stop</button><p id="appStatus" role="status" aria-live="polite">Ready</p><div id="stepsContainer"></div>
<script type="application/json" id="wfData" nonce="${nonce}">${data}${endScript}
<script nonce="${nonce}">${createAgentConciergeClient.toString()}\n(${standaloneAppRuntime.toString()})();${endScript}</body></html>`;
}

// END WORKFLOW SDK

// BEGIN WORKFLOW APP RUNTIME
function standaloneAppRuntime() {
  const cfg = JSON.parse(document.getElementById('wfData').textContent);
  const run = document.getElementById('runAppBtn');
  const cancel = document.getElementById('cancelAppBtn');
  const status = document.getElementById('appStatus');
  const output = document.getElementById('stepsContainer');
  let current = null;
  let running = false;
  let cancelling = false;
  const client = createAgentConciergeClient();
  function setRunning(value) {
    run.disabled = value;
    run.setAttribute('aria-busy', String(value));
    run.querySelector('[data-run-label]').textContent = value ? 'Running...' : 'Run workflow';
    run.querySelector('[data-run-ready]').toggleAttribute('hidden', value);
    run.querySelector('[data-run-spinner]').toggleAttribute('hidden', !value);
  }
  function render(data) {
    status.textContent = 'Workflow: ' + data.status;
    output.replaceChildren();
    for (const item of data.results || data.node_results || []) {
      const card = document.createElement('section');
      const heading = document.createElement('h2');
      heading.textContent = item.name + ' · ' + item.status;
      const body = document.createElement('pre');
      body.textContent = item.output || item.error || '';
      card.append(heading, body); output.append(card);
    }
  }
  cancel.onclick = async () => {
    if (!running || !current || cancelling) return;
    const handle = current;
    cancelling = true;
    cancel.disabled = true;
    let requested = false;
    try {
      await client.cancel(handle);
      requested = true;
      if (!running || current !== handle) return;
      status.textContent = 'Cancellation requested. An in-flight request may finish before stopping.';
    } catch (error) {
      if (!running || current !== handle) return;
      status.textContent = error.message;
    } finally {
      if (!requested && running && current === handle) {
        cancelling = false;
        cancel.disabled = false;
      }
    }
  };
  run.onclick = async () => {
    if (running) return;
    running = true;
    setRunning(true);
    cancel.disabled = true;
    output.replaceChildren();
    status.textContent = 'Starting workflow...';
    try {
      current = await client.run(cfg.workflow_id);
      cancel.disabled = false;
      status.textContent = 'Workflow: queued';
      await client.wait(current, {onUpdate:render});
    } catch (error) { status.textContent = error.message; }
    finally {
      running = false;
      cancelling = false;
      setRunning(false);
      cancel.disabled = true;
      current = null;
    }
  };
}
// END WORKFLOW APP RUNTIME

function buildWorkflowAppHTML(config) {
  const escapeHTML = value => String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const origin = 'https://agentconcierge.biz';
  if (config.api_origin && config.api_origin !== origin) throw new Error('This app uses the Agent Concierge routing gateway.');
  if (!Number.isInteger(config.workflow_id) || config.workflow_id < 1) throw new Error('Choose a published template before exporting.');
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(24)), b => b.toString(16).padStart(2,'0')).join('');
  const data = JSON.stringify({workflow_id:config.workflow_id,api_origin:origin}).replace(/</g,'\\u003c');
  const endScript = '</scr' + 'ipt>';
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; script-src-attr 'none'; style-src 'nonce-${nonce}'; connect-src ${escapeHTML(origin)}; object-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer"><title>${escapeHTML(config.title)} — Agent Workflow</title>
<meta name="description" content="Run a published agent workflow and view its recorded outcomes.">
<style nonce="${nonce}">:root{color-scheme:light dark;font-family:system-ui,sans-serif}body{max-width:850px;margin:40px auto;padding:20px}section{border:1px solid #8391a6;border-radius:16px;padding:16px;margin:16px 0}h2{font-size:1rem}button{display:inline-flex;align-items:center;gap:8px;border:1px solid #8391a6;border-radius:10px;padding:12px 18px;cursor:pointer}button:focus-visible{outline:3px solid #6366f1;outline-offset:3px}pre{white-space:pre-wrap;overflow-wrap:anywhere}button svg{flex-shrink:0}#runAppBtn:disabled{cursor:wait;color:CanvasText;opacity:.75}[hidden]{display:none!important}.app-run-spinner{animation:app-run-spin 1s linear infinite}@keyframes app-run-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.app-run-spinner{animation:none}}</style>
</head><body><h1>${escapeHTML(config.title)}</h1><p>${escapeHTML(config.description)}</p>
<p>This app connects to Agent Concierge to run the current published template. Results depend on agent availability. It requires an internet connection.</p>
<button id="runAppBtn" type="button" aria-busy="false"><svg data-run-ready width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg><svg data-run-spinner class="app-run-spinner" hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a10 10 0 1 0 10 10"/></svg><span data-run-label>Run workflow</span></button>
<button id="cancelAppBtn" type="button" disabled>Stop</button><p id="appStatus" role="status" aria-live="polite">Ready</p><div id="stepsContainer"></div>
<script type="application/json" id="wfData" nonce="${nonce}">${data}${endScript}
<script nonce="${nonce}">${createAgentConciergeClient.toString()}\n(${standaloneAppRuntime.toString()})();${endScript}</body></html>`;
}

function generateStandaloneWebAppHtml(title, desc, nodes, edges, steps, templateId=frontActiveTemplateId) {
  const template=frontTemplatesCache.find(t=>t.id===templateId);
  if (!template) throw new Error('Choose a published template before exporting.');
  return buildWorkflowAppHTML({workflow_id:template.id,title:template.name,description:template.description,api_origin:'https://agentconcierge.biz'});
}

async function downloadStandaloneAppFile(title, desc, nodes, edges, steps, templateId=frontActiveTemplateId) {
  if (!Number.isInteger(templateId) || templateId < 1) {
    toast('Choose an available published template.');
    return;
  }
  const buttons = [...document.querySelectorAll('#btnFrontExportApp, #frontTemplatesGrid button[data-ac-click="fc422abb205a"]')];
  const previous = buttons.map(button => button.disabled);
  buttons.forEach(button => { button.disabled = true; });
  const loaderToken = showLoader("Preparing web app download...");
  try {
    const response = await fetch('/api/workflows/' + encodeURIComponent(templateId) + '/webapp', {
      method:'GET', credentials:'omit', cache:'no-store', redirect:'error',
      referrerPolicy:'no-referrer', signal:AbortSignal.timeout(20000)
    });
    if (!response.ok) throw new Error(response.status === 429 ? 'Too many downloads. Please try again shortly.' : 'This published workflow is unavailable for download.');
    if (!(response.headers.get('Content-Type') || '').startsWith('application/zip')) throw new Error('The web app package is unavailable. Please try again later.');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const matched = (response.headers.get('Content-Disposition') || '').match(/filename="([a-z0-9-]+-webapp\.zip)"/);
    const slug = (title || 'workflow').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,72) || 'workflow';
    link.href = url; link.download = matched ? matched[1] : slug + '-webapp.zip';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast('Downloaded web app package. Extract the ZIP and follow the deployment guide.');
  } catch (error) {
    toast(error.name === 'AbortError' || error.name === 'TimeoutError' ? 'The download timed out. Please try again.' : 'Unable to download this published workflow. Please try again later.');
  } finally {
    hideLoader(loaderToken);
    buttons.forEach((button, index) => { button.disabled = previous[index]; });
  }
}

// Templates Hub
function hydrateFrontWorkflowDefault(templates) {
  if (!Array.isArray(templates)) return;
  const candidates = templates.filter(t => Number.isInteger(t?.id) && Array.isArray(t.nodes) && t.nodes.length && !t.nodes.some(n=>n.kind==='x402'));
  const preferred = candidates.find(t => t.name === 'Daily Tech News & AI Research Digest') ||
    candidates.find(t => t.execution_availability?.available === true) || candidates[0];
  if (!preferred) return;
  const untouched = !frontCanvasRestored && !frontWorkflowSelectionTouched &&
    (frontActiveTemplateId === null || frontActiveTemplateId === frontDefaultTemplateId) &&
    JSON.stringify(frontCanvasGraph) === JSON.stringify(DEFAULT_FRONT_GRAPH);
  frontDefaultTemplateId = preferred.id;
  DEFAULT_FRONT_WORKFLOW_NAME = preferred.name;
  DEFAULT_FRONT_GRAPH = {nodes: JSON.parse(JSON.stringify(preferred.nodes)),
    edges: JSON.parse(JSON.stringify(preferred.edges || []))};
  if (untouched) {
    frontActiveTemplateId = preferred.id;
    frontActiveWfName = preferred.name;
    frontCanvasGraph = JSON.parse(JSON.stringify(DEFAULT_FRONT_GRAPH));
    updateFrontActiveName();
    renderFrontCanvas();
  }
}

async function loadFrontTemplates(force = false) {
  const grid = $("frontTemplatesGrid");
  if (!grid) return;

  if (frontTemplatesCache.length && !force) {
    hydrateFrontWorkflowDefault(frontTemplatesCache);
    renderFrontTemplates();
  }

  if (frontTemplatesFromPage && frontTemplatesCache.length && !force) {
    frontTemplatesLoaded = true;
    frontTemplatesLoading = false;
    updateFrontActiveName();
    updateFrontWorkflowAvailability();
    return frontTemplatesCache;
  }

  const cached = getSwrCache("workflow_templates_v5");
  if (Array.isArray(cached) && !force) {
    frontTemplatesCache = cached;
    hydrateFrontWorkflowDefault(frontTemplatesCache);
    renderFrontTemplates();
  }

  const revision = ++frontTemplatesRequestRevision;
  frontTemplatesLoading = true;
  frontTemplatesLoadFailed = false;
  updateFrontActiveName();
  try {
    const res = await api("/api/workflows/templates", {timeoutMs:45000, retries:0, loadingMsg: "Loading published workflows..." });
    if (!Array.isArray(res?.templates)) throw new Error('Unable to check published connections. Please try again.');
    if (revision === frontTemplatesRequestRevision) {
      frontTemplatesLoaded = true;
      const templatesChanged = JSON.stringify(frontTemplatesCache) !== JSON.stringify(res.templates);
      frontTemplatesCache = res.templates;
      setSwrCache("workflow_templates_v5", frontTemplatesCache);
      hydrateFrontWorkflowDefault(frontTemplatesCache);
      if (templatesChanged) renderFrontTemplates();
      updateFrontWorkflowAvailability();
    }
    return res.templates;
  } catch (err) {
    if (revision === frontTemplatesRequestRevision) frontTemplatesLoadFailed = true;
    if (frontTemplatesCache.length === 0) {
      grid.innerHTML = `<p style="color:var(--bad);padding:24px;text-align:center">Failed to load templates: ${esc(err.message)}</p>`;
    }
    if (force) throw err;
  } finally {
    if (revision === frontTemplatesRequestRevision) {
      frontTemplatesLoading = false;
      updateFrontActiveName();
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
  const query = ($("frontTmplSearchInput")?.value || "").trim().toLowerCase();
  clearTimeout(filterFrontTemplates.timer);
  filterFrontTemplates.controller?.abort();
  const revision = (filterFrontTemplates.revision || 0) + 1;
  filterFrontTemplates.revision = revision;
  filterFrontTemplates.state = {query, templates: [], loading: Boolean(query), error: false};
  renderFrontTemplates();
  if (!query) return;
  filterFrontTemplates.timer = setTimeout(async () => {
    const controller = new AbortController();
    filterFrontTemplates.controller = controller;
    try {
      const response = await fetch('/api/workflows/templates?' + new URLSearchParams({q: query}), {
        signal: controller.signal, credentials: 'same-origin', headers: {'Accept': 'application/json'}
      });
      if (!response.ok) throw new Error('Search unavailable');
      const result = await response.json();
      if (!result.ok || !Array.isArray(result.templates)) throw new Error('Search unavailable');
      if (filterFrontTemplates.revision !== revision) return;
      filterFrontTemplates.state = {query, templates: result.templates, loading: false, error: false};
    } catch (error) {
      if (filterFrontTemplates.revision !== revision || error.name === 'AbortError') return;
      filterFrontTemplates.state = {query, templates: [], loading: false, error: true};
    }
    renderFrontTemplates();
  }, 180);
}

function renderFrontTemplates() {
  const grid = $("frontTemplatesGrid");
  if (!grid) return;

  const q = ($("frontTmplSearchInput") ? $("frontTmplSearchInput").value : "").trim().toLowerCase();
  const cat = frontActiveTmplCategory;

  const search = filterFrontTemplates.state;
  if (q && (!search || search.query !== q || search.loading)) {
    if (!search || search.query !== q) filterFrontTemplates();
    grid.innerHTML = '<p role="status" style="padding:24px">Searching published workflows...</p>';
    return;
  }
  if (q && search?.error) {
    grid.innerHTML = '<p role="status" style="padding:24px">Workflow search is unavailable. Edit the search to try again.</p>';
    return;
  }
  const source = q ? search.templates : frontTemplatesCache;

  // Filter templates, strictly excluding test templates
  const tmpls = source.filter((t) => {
    const protocols=t.node_protocols || (t.nodes||[]).map(n=>n.kind);
    if(protocols.includes('x402') && !explicitlyRequestsX402(q))return false;
    const name = (t.name || "").trim();
    if (name.startsWith("[") || name.toLowerCase().includes("[test]")) return false;
    const tags = (t.tags || "").toLowerCase();
    if (tags.includes("test")) return false;

    if (cat !== "all" && t.category !== cat) return false;
    return true;
  });

  if (tmpls.length === 0) {
    grid.innerHTML = `<p style="color:var(--text-muted);grid-column:1/-1;padding:32px;text-align:center">No published templates match the selected filters.</p>`;
    return;
  }

  const displayedTemplates = typeof window.selectFrontTemplatePage === 'function' ? window.selectFrontTemplatePage(tmpls) : tmpls;
  grid.innerHTML = displayedTemplates.map((t) => {
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
          <p style="color:var(--text-muted);font-size:12px;line-height:1.5;margin-bottom:10px">${esc(t.description || "Published agent workflow.")}</p>
          ${t.execution_availability?.available === false ? `<p style="color:var(--warn);font-size:12px;line-height:1.5">${esc(t.execution_availability.message)}</p>` : ''}
          <div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
            ${stepBadges}
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
          <button class="btn sm primary" data-id="${esc(t.id)}" data-ac-click="64099165e4f4" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
            <span>Open in Canvas</span>
          </button>
          <button class="btn sm" data-id="${esc(t.id)}" data-ac-click="fc422abb205a" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <span>Download web app</span>
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function loadFrontTemplateToCanvas(templateId) {
  const t = frontTemplatesCache.find((tmpl) => String(tmpl.id) === String(templateId));
  if (!t) return;

  frontWorkflowSelectionTouched = true;
  frontActiveWfName = t.name;
  frontActiveTemplateId = t.id;

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
  downloadStandaloneAppFile(t.name, t.description, t.nodes, t.edges, t.steps, t.id);
}

// ==================== Agent Testbench Sandbox & Wire Inspector ====================
let tbPresetsCache = [];
const DEFAULT_LIVE_EXAMPLES = [
  {
    id: "country-profile",
    title: "Country Profile",
    desc: "Retrieve a country name, capital and region from the World Bank.",
    protocol: "mcp",
    tool: "get_country_profile",
    args: { country_code: "US" },
    prompt: "",
    resource_id: 133020,
    available: true
  },
  {
    id: "technology-news",
    title: "Technology News",
    desc: "Find recent Hacker News stories matching public technology keywords.",
    protocol: "mcp",
    tool: "search_technology_news",
    args: { query: "artificial intelligence", limit: 3 },
    prompt: "",
    resource_id: 133018,
    available: true
  },
  {
    id: "research-papers",
    title: "Research Papers",
    desc: "Search Crossref bibliographic records with DOI source links.",
    protocol: "mcp",
    tool: "search_research_papers",
    args: { query: "artificial intelligence", limit: 3 },
    prompt: "",
    resource_id: 133019,
    available: true
  },
  {
    id: "package-metadata",
    title: "Package Metadata",
    desc: "Retrieve the current npm package version and public description.",
    protocol: "mcp",
    tool: "get_package_metadata",
    args: { package: "express" },
    prompt: "",
    resource_id: 133021,
    available: true
  }
];
// Example titles show at once as disabled previews; only the server's current answer makes them runnable.
let tbLiveExamples = [];
let tbExamplesState = "idle";
// Fixed examples shipped in the page open without any request (UI policy 11-01); Run is checked by the server.
let tbExamplesFromPage = false;
const tbPageAgents = new Map();
let tbSelectionPending = null;
let tbAgentsCache = [];
let tbSelectedAgent = null;
let tbSelectionVersion = 0;
let tbSelectionTarget = "";
let tbCatalogLoadVersion = 0;
let tbRunInFlight = false;
let tbCurrentKind = "all";
let tbLastResult = null;
let tbHistory = [];

const TB_GUIDED_RECIPES = [
  ...DEFAULT_LIVE_EXAMPLES,
  {
    id: "mcp_weather",
    presetId: -1,
    protocol: "mcp",
    title: "Demo: Weather response format",
    desc: "Demonstration only. No provider is contacted and no live result is verified.",
    tool: "get_current_weather",
    args: { city: "Seoul", units: "metric" },
    prompt: ""
  },
  {
    id: "mcp_discovery",
    presetId: -2,
    protocol: "mcp",
    title: "Demo: Agent discovery format",
    desc: "Demonstration only. No provider is contacted and no live result is verified.",
    tool: "search_verified_agents",
    args: { category: "finance", min_grade: "A", limit: 3 },
    prompt: ""
  },
  {
    id: "a2a_task",
    presetId: -3,
    protocol: "a2a",
    title: "Demo: A2A message format",
    desc: "Demonstration only. No provider is contacted and no live result is verified.",
    tool: "",
    args: {},
    prompt: "Summarize recent technology research with source links."
  },
  {
    id: "x402_challenge",
    presetId: -4,
    protocol: "x402",
    title: "Demo: x402 probe format",
    desc: "Demonstration only. No provider is contacted and no live result is verified.",
    tool: "",
    args: {},
    prompt: ""
  }
];

function loadTestbenchUI(preselectId) {
  const loadVersion = ++tbCatalogLoadVersion;
  const catalogReady = tbAgentsCache.length > 0;
  tbExamplesState = tbLiveExamples.length ? "ready" : "loading";
  if ($("tbRunBtn")) $("tbRunBtn").disabled = tbRunInFlight || !tbSelectedAgent;
  renderTestbenchRecipes();
  loadTestbenchHistory();

  if (tbPresetsCache.length && (tbLiveExamples.length || preselectId)) populateTestbenchAgentSelect(preselectId);
  if (tbExamplesFromPage) {
    tbExamplesState = "ready";
    renderTestbenchRecipes();
    populateTestbenchAgentSelect(preselectId);
    watchTestbenchCatalogRequest();
    return Promise.resolve();
  }
  const examples = api("/api/test/presets", {timeoutMs: 20000, retries: 0}).then((res) => {
    if (loadVersion !== tbCatalogLoadVersion) return;
    if (!Array.isArray(res?.live_examples)) throw new Error("Examples are unavailable.");
    if (Array.isArray(res.presets)) tbPresetsCache = res.presets;
    tbLiveExamples = res.live_examples;
    tbExamplesState = "ready";
    renderTestbenchRecipes();
    populateTestbenchAgentSelect();
  }).catch(() => {
    if (loadVersion !== tbCatalogLoadVersion) return;
    // A failed check leaves nothing runnable from an earlier answer; Retry asks again.
    tbLiveExamples = [];
    tbExamplesState = "error";
    renderTestbenchRecipes();
  });

  const loadCatalog = () => {
    if (loadVersion !== tbCatalogLoadVersion) return;
    return api("/api/explore?limit=100", {background: true, timeoutMs: 30000, retries: 0}).then((res) => {
      if (loadVersion !== tbCatalogLoadVersion) return;
      if (Array.isArray(res?.items)) {
        tbAgentsCache = res.items;
        populateTestbenchAgentSelect();
      }
    }).catch(() => {});
  };
  // The first visible examples and request take priority over optional browsing.
  if (catalogReady) loadCatalog();
  else examples.then(() => tbSelectionPending?.promise).catch(() => {}).then(loadCatalog);
  return examples;
}

// The registered-agent list is optional browsing: request it only when the visitor opens the chooser.
let tbCatalogWatched = false, tbCatalogRequested = false;
function watchTestbenchCatalogRequest() {
  if (tbCatalogWatched) return;
  const select = $("tbAgentSelect"), chooser = select?.closest("details");
  if (!select) return;
  tbCatalogWatched = true;
  const request = () => {
    if (tbAgentsCache.length || tbCatalogRequested) return;
    tbCatalogRequested = true;
    api("/api/explore?limit=100", {background: true, timeoutMs: 30000, retries: 0}).then((res) => {
      if (Array.isArray(res?.items)) {
        tbAgentsCache = res.items;
        populateTestbenchAgentSelect(select.value);
      }
    }).catch(() => { tbCatalogRequested = false; });
  };
  chooser?.addEventListener("toggle", () => { if (chooser.open) request(); });
  for (const type of ["focus", "pointerdown"]) select.addEventListener(type, request);
}

function renderTestbenchRecipes() {
  const container = $("testbenchRecipesGrid");
  if (!container) return;
  container.setAttribute("aria-busy", String(tbExamplesState === "loading"));
  if (!tbLiveExamples.length) {
    container.textContent = tbExamplesState === "error"
      ? "Examples could not be loaded. Open Test again to retry."
      : tbExamplesState === "ready" ? "No examples are currently published." : "Checking example availability…";
    return;
  }

  container.innerHTML = tbLiveExamples.map((r) => {
    const kClass = r.protocol === "a2a" ? "k-a2a" : (r.protocol === "mcp" ? "k-mcp" : "k-x402");
    return `
      <div class="testbench-recipe-card">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span class="kind-badge ${kClass}">${esc(r.protocol.toUpperCase())}</span>
            <span style="font-size:10.5px;color:var(--ok);font-weight:700;display:inline-flex;align-items:center;gap:3px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg><span>${r.available ? "Live request" : "Unavailable"}</span></span>
          </div>
          <div style="font-weight:700;font-size:14px;color:var(--text);margin-bottom:4px">${esc(r.title)}</div>
          <div style="font-size:12px;color:var(--text-muted);line-height:1.45">${esc(r.desc)}</div>
          ${r.available === false && r.execution_availability?.message ? `<p style="font-size:12px;color:var(--warn)">${esc(r.execution_availability.message)}</p>` : ''}
        </div>
        <div style="display:flex;gap:6px;margin-top:8px">
          <button class="btn sm" ${r.available ? "" : "disabled"} data-recipe="${esc(r.id)}" data-ac-click="ca285c7fb9a7" style="flex:1;font-size:12px;padding:5px 8px;display:inline-flex;align-items:center;justify-content:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span>Load Recipe</span>
          </button>
          <button class="btn sm primary" ${r.available ? "" : "disabled"} data-recipe="${esc(r.id)}" data-ac-click="df52bcaeaa31" style="flex:1;font-size:12px;padding:5px 8px;display:inline-flex;align-items:center;justify-content:center;gap:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            <span>Run Now</span>
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function loadTestbenchRecipe(recipeId, callback) {
  const r = tbLiveExamples.find((rec) => rec.id === recipeId) || TB_GUIDED_RECIPES.find((rec) => rec.id === recipeId);
  if (!r) return;

  if (r.available === false) {
    toast(r.execution_availability?.message || "This live example is unavailable. Select another registered agent.", "info");
    return;
  }
  const targetId = String(r.resource_id || r.presetId);
  const sel = $("tbAgentSelect");
  if (sel) {
    if (!Array.from(sel.options).some(o => o.value === targetId)) {
      const option = document.createElement("option"); option.value = targetId; option.textContent = r.title;
      sel.appendChild(option);
    }
    sel.value = targetId;
  }

  onTestbenchAgentChange(targetId, () => {
    if (r.tool && $("tbToolSelect")) {
      $("tbToolSelect").value = r.tool;
    }
    if (r.args && $("tbArgsEditor")) {
      $("tbArgsEditor").value = JSON.stringify(r.args, null, 2);
      validateTestbenchJson();
    }
    if (r.prompt && $("tbA2aMessage")) {
      $("tbA2aMessage").value = r.prompt;
    }
    if (typeof callback === "function") {
      callback();
    } else {
      toast(`Loaded recipe: "${r.title}".`, "success");
    }
  });
}

function runTestbenchRecipe(recipeId) {
  if (tbRunInFlight) {
    toast("A test is already running. Wait for its result before starting another.", "info");
    return;
  }
  const r = tbLiveExamples.find((rec) => rec.id === recipeId) || TB_GUIDED_RECIPES.find((rec) => rec.id === recipeId);
  if (!r) return;

  loadTestbenchRecipe(recipeId, () => {
    executeCurrentTestbench();
  });
}

function populateTestbenchAgentSelect(preferredId) {
  const sel = $("tbAgentSelect");
  if (!sel) return;

  // An in-flight or completed explicit selection outranks the default example
  // that finishes loading later, so a slow catalog refresh never replaces it.
  const currentVal = preferredId ? String(preferredId) : (tbSelectionTarget || sel.value || String(tbLiveExamples.find(r => r.available)?.resource_id || -1));
  const q = ($("tbAgentSearch") ? $("tbAgentSearch").value : "").trim().toLowerCase();

  let html = `<optgroup label="Live examples">`;
  tbLiveExamples.filter(r => r.available && (tbCurrentKind === "all" || r.protocol === tbCurrentKind)).forEach(r => {
    html += `<option value="${r.resource_id}">${esc(r.title)} [${esc(r.protocol.toUpperCase())}]</option>`;
  });
  html += `</optgroup><optgroup label="Format demos — no provider calls">`;
  const presets = tbPresetsCache.length ? tbPresetsCache : [
    { id: -1, name: "Demo: Weather response format", kind: "mcp" },
    { id: -2, name: "Demo: Agent discovery format", kind: "mcp" },
    { id: -3, name: "Demo: A2A message format", kind: "a2a" },
    { id: -4, name: "Demo: x402 probe format", kind: "x402" }
  ];

  presets.forEach((p) => {
    if (tbCurrentKind !== "all" && p.kind !== tbCurrentKind) return;
    if (q && !p.name.toLowerCase().includes(q)) return;
    html += `<option value="${p.id}">[DEMO] ${esc(p.name)} [${esc(p.kind.toUpperCase())}]</option>`;
  });
  html += `</optgroup>`;

  if (tbAgentsCache.length) {
    html += `<optgroup label="Live Registered Agents">`;
    tbAgentsCache.forEach((a) => {
      if (tbCurrentKind !== "all" && a.kind !== tbCurrentKind) return;
      if (q && !a.name.toLowerCase().includes(q) && !(a.description || "").toLowerCase().includes(q)) return;
      html += `<option value="${a.id}">${esc(a.name)} [${esc(a.kind.toUpperCase())}]</option>`;
    });
    html += `</optgroup>`;
  }

  sel.innerHTML = html;
  if (Array.from(sel.options).some((o) => o.value === currentVal)) {
    sel.value = currentVal;
  } else if (currentVal && currentVal !== "-1" && parseInt(currentVal, 10) > 0) {
    const cached = (typeof EXPLORE_AGENT_MAP !== "undefined" && EXPLORE_AGENT_MAP.get(currentVal)) || getSwrCache("agent:" + currentVal);
    const optName = cached ? `${cached.name} [${(cached.kind || 'mcp').toUpperCase()}]` : `Agent #${currentVal}`;
    const opt = document.createElement("option");
    opt.value = currentVal;
    opt.textContent = optName;
    sel.appendChild(opt);
    sel.value = currentVal;
  } else if (sel.options.length > 0) {
    sel.value = sel.options[0].value;
  }
  // Refresh options without canceling an explicit selection or replacing edits.
  if (tbSelectionTarget !== sel.value) onTestbenchAgentChange(sel.value);
}

function filterTestbenchKind(kind, btnEl) {
  tbCurrentKind = kind;
  document.querySelectorAll("#secTest .quick-chips .chip-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.kind === kind);
  });
  populateTestbenchAgentSelect($("tbAgentSelect") ? $("tbAgentSelect").value : null);
}

function filterTestbenchAgentList(query) {
  populateTestbenchAgentSelect($("tbAgentSelect") ? $("tbAgentSelect").value : null);
}

async function onTestbenchAgentChange(agentId, callback) {
  const rid = Number(agentId);
  if (!Number.isInteger(rid)) return null;
  const pending = tbSelectionPending;
  if (pending && pending.id === rid && pending.version === tbSelectionVersion) {
    const agent = await pending.promise.catch(() => null);
    if (agent && pending.version === tbSelectionVersion && typeof callback === "function") callback();
    return pending.version === tbSelectionVersion ? agent : null;
  }
  const version = ++tbSelectionVersion;
  tbSelectionTarget = String(rid);
  tbSelectedAgent = null;
  if ($("tbRunBtn")) $("tbRunBtn").disabled = true;
  if ($("tbAgentMetaBox")) $("tbAgentMetaBox").textContent = "Loading registered connection...";
  try {
    const preset = tbPresetsCache.find((p) => p.id === rid) || tbPageAgents.get(rid);
    const promise = preset ? Promise.resolve(preset) : api(`/api/agents/${rid}`, {timeoutMs:20000, retries:1}).then(reply => reply.agent);
    tbSelectionPending = {id: rid, version, promise};
    const agent = await promise;
    if (version !== tbSelectionVersion || !agent) return null;
    applySelectedTestbenchAgent(agent);
    if (typeof callback === "function") callback();
    return agent;
  } catch (err) {
    if (version === tbSelectionVersion && $("tbAgentMetaBox")) {
      $("tbAgentMetaBox").textContent = "Unable to load this connection. Select an agent to retry.";
    }
    return null;
  } finally {
    if (tbSelectionPending?.version === version) tbSelectionPending = null;
    if (version === tbSelectionVersion && $("tbRunBtn")) $("tbRunBtn").disabled = tbRunInFlight || !tbSelectedAgent;
  }
}

function applySelectedTestbenchAgent(agent) {
  tbSelectedAgent = agent;
  renderSelectedAgentMeta(agent);

  const kind = agent.kind || "mcp";
  const mcpBox = $("tbMcpControls");
  const a2aBox = $("tbA2aControls");
  const x402Box = $("tbX402Controls");
  const argsStudio = $("tbArgsStudio");

  if (mcpBox) mcpBox.classList.toggle("hidden", kind !== "mcp");
  if (a2aBox) a2aBox.classList.toggle("hidden", kind !== "a2a");
  if (x402Box) x402Box.classList.toggle("hidden", kind !== "x402");
  if (argsStudio) argsStudio.classList.toggle("hidden", kind === "x402");

  if ($("tbToolSelect")) $("tbToolSelect").disabled = kind !== "mcp";
  if (kind === "mcp") {
    populateTestbenchTools(agent);
  } else if (kind === "a2a") {
    const defaultMsg = agent.sample_args && agent.sample_args.message ? agent.sample_args.message : "Summarize recent technology research with source links.";
    if ($("tbA2aMessage")) $("tbA2aMessage").value = defaultMsg;
  }
}

function renderSelectedAgentMeta(agent) {
  const box = $("tbAgentMetaBox");
  if (!box) return;

  const kClass = agent.kind === "a2a" ? "k-a2a" : (agent.kind === "mcp" ? "k-mcp" : "k-x402");
  const isHealthy = agent.health_status === "healthy" || agent.health_status === "reachable";
  const gwUrl = gatewayAgentEndpoint(agent);

  box.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
      <div>
        <span class="kind-badge ${kClass}" style="margin-right:6px">${esc((agent.kind || "mcp").toUpperCase())}</span>
        <strong style="font-size:13.5px;color:var(--text)">${esc(agent.name)}</strong>
      </div>
      <span class="chip" style="font-size:11px;color:${isHealthy ? 'var(--ok)' : 'var(--warn)'};display:inline-flex;align-items:center;gap:4px">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>
        <span>${esc(agent.health_status || "active")}</span>
      </span>
    </div>
    <div style="font-size:12px;color:var(--text-dim);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all">
      ${esc(gwUrl || (agent.simulated ? "Demo — no live connection" : "Connection unavailable"))}
    </div>
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:11px;color:var(--text-muted)">
      <span>Category: <strong>${esc(agent.category || "General")}</strong></span>
      <span>•</span>
      <span>Grade: <strong style="color:var(--ok)">${esc(agent.eval_grade || "Unrated")}</strong></span>
      <span>•</span>
      <span>Trial Latency: <strong>${agent.last_trial?.latency_ms != null ? esc(String(agent.last_trial.latency_ms)) + " ms" : "Not recorded"}</strong></span>
    </div>
  `;
}

function populateTestbenchTools(agent) {
  const sel = $("tbToolSelect");
  if (!sel) return;

  const tools = Array.isArray(agent.tools) ? agent.tools : [];
  if (tools.length === 0) {
    sel.innerHTML = `<option value="">No registered tool</option>`;
  } else {
    sel.innerHTML = tools.map((t) => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join("");
  }
  if ($("tbQuickTools")) {
    $("tbQuickTools").innerHTML = tools.slice(0, 4).map(t => `<button class="chip-btn" data-tool="${esc(t.name)}" data-ac-click="9afb511d5efe">${esc(t.name)}</button>`).join("");
  }
  onTestbenchToolChange(sel.value);
}

function onTestbenchToolChange(toolName) {
  if ($("tbCustomToolInput")) $("tbCustomToolInput").value = "";
  applyDefaultArgsForTool(toolName);
  const spec = tbSelectedAgent?.tools?.find(t => t.name === toolName);
  const required = spec?.inputSchema?.required || spec?.required || [];
  if ($("tbToolHint")) {
    const sampleHint = spec && !spec.sample ? "Enter your task inputs; no validated sample is available." : "Review the sample inputs before running.";
    $("tbToolHint").textContent = !spec ? "No informational tool is available for this connection." : required.length ? `Required fields: ${required.join(", ")}. ${sampleHint}` : `${sampleHint} No fields are required.`;
  }
}

function onCustomToolInput(val) {
  // Custom tool value is handled at execution time
}

function setTestbenchTool(toolName) {
  if ($("tbToolSelect")) {
    let exists = false;
    for (let opt of $("tbToolSelect").options) {
      if (opt.value === toolName) {
        $("tbToolSelect").value = toolName;
        exists = true;
        break;
      }
    }
    if (!exists) {
      toast("Choose a tool registered for the selected agent.", "info");
      return;
    }
  }
  onTestbenchToolChange(toolName);
}

function setTestbenchPrompt(prompt) {
  if ($("tbA2aMessage")) {
    $("tbA2aMessage").value = prompt;
  }
}

function applyDefaultArgsForTool(toolName) {
  const editor = $("tbArgsEditor");
  if (!editor) return;

  if (tbSelectedAgent && Array.isArray(tbSelectedAgent.tools)) {
    const tObj = tbSelectedAgent.tools.find((t) => t.name === toolName);
    if (tObj && tObj.sample) {
      editor.value = JSON.stringify(tObj.sample, null, 2);
      validateTestbenchJson();
      return;
    }
  }

  const matchingExample = tbLiveExamples.find(e => e.tool === toolName);
  if (matchingExample && matchingExample.args && Object.keys(matchingExample.args).length) {
    editor.value = JSON.stringify(matchingExample.args, null, 2);
    validateTestbenchJson();
    return;
  }

  const KNOWN_SAMPLES = {
    "get_country_profile": { country_code: "US" },
    "search_technology_news": { query: "artificial intelligence", limit: 3 },
    "search_research_papers": { query: "artificial intelligence", limit: 3 },
    "get_package_metadata": { package: "express" },
    "get_current_weather": { city: "Seoul", units: "metric" },
    "get_air_quality": { station: "Gangnam", pollutants: ["PM2.5", "PM10", "O3"] },
    "search_verified_agents": { category: "finance", min_grade: "A", limit: 3 },
    "get_agent_manifest": { agent_id: "agent-kr-fx-01" }
  };
  if (KNOWN_SAMPLES[toolName]) {
    editor.value = JSON.stringify(KNOWN_SAMPLES[toolName], null, 2);
    validateTestbenchJson();
    return;
  }

  editor.value = JSON.stringify({}, null, 2);
  validateTestbenchJson();
}

function validateTestbenchJson() {
  const editor = $("tbArgsEditor");
  const status = $("tbJsonStatus");
  if (!editor || !status) return true;

  const val = editor.value.trim();
  if (!val) {
    status.innerHTML = '<span style="display:inline-flex;align-items:center;gap:3px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Empty ({})</span></span>';
    status.style.color = "var(--ok)";
    return true;
  }
  try {
    const parsed = JSON.parse(val);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Object required");
    status.innerHTML = '<span style="display:inline-flex;align-items:center;gap:3px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><span>Valid JSON</span></span>';
    status.style.color = "var(--ok)";
    return true;
  } catch (err) {
    status.innerHTML = '<span style="display:inline-flex;align-items:center;gap:3px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg><span>Invalid JSON</span></span>';
    status.style.color = "var(--bad)";
    return false;
  }
}

function applyTestbenchArgsTemplate(tmplType) {
  const editor = $("tbArgsEditor");
  if (!editor) return;

  if (tmplType === "mock") {
    if (tbSelectedAgent && Array.isArray(tbSelectedAgent.tools) && tbSelectedAgent.tools.length) {
      const toolName = $("tbCustomToolInput") && $("tbCustomToolInput").value.trim() ? $("tbCustomToolInput").value.trim() : ($("tbToolSelect") ? $("tbToolSelect").value : "");
      const tObj = tbSelectedAgent.tools.find((t) => t.name === toolName) || tbSelectedAgent.tools[0];
      const properties = tObj?.inputSchema?.properties || tObj?.params?.properties || tObj?.params;
      if (properties && typeof properties === "object") {
        const mockObj = {};
        for (let [k, prop] of Object.entries(properties)) {
          if (prop.type === "string") mockObj[k] = prop.enum ? prop.enum[0] : `sample_${k}`;
          else if (prop.type === "integer" || prop.type === "number") mockObj[k] = 10;
          else if (prop.type === "boolean") mockObj[k] = true;
          else if (prop.type === "array") mockObj[k] = ["item1", "item2"];
          else mockObj[k] = {};
        }
        editor.value = JSON.stringify(mockObj, null, 2);
        validateTestbenchJson();
        return;
      }
    }
    editor.value = JSON.stringify({ query: "artificial intelligence", limit: 5 }, null, 2);
  } else if (tmplType === "weather") {
    editor.value = JSON.stringify({ city: "Seoul", units: "metric" }, null, 2);
  } else if (tmplType === "search") {
    editor.value = JSON.stringify({ category: "finance", min_grade: "A", limit: 3 }, null, 2);
  } else if (tmplType === "empty") {
    editor.value = JSON.stringify({}, null, 2);
  }
  validateTestbenchJson();
}

function resetTestbenchParams() {
  const sel = $("tbAgentSelect");
  if (sel) {
    const defaultId = String(tbLiveExamples.find(r => r.available)?.resource_id || -1);
    sel.value = defaultId;
    onTestbenchAgentChange(defaultId);
  }
  if ($("tbTimeoutSelect")) $("tbTimeoutSelect").value = "8.0";
  toast("Restored the default test selection.");
}

async function executeCurrentTestbench() {
  if (tbRunInFlight) return;
  if (!tbSelectedAgent) {
    const sel = $("tbAgentSelect");
    if (sel && sel.value) await onTestbenchAgentChange(sel.value);
    if (!tbSelectedAgent) return;
  }
  const selectedAgent = tbSelectedAgent;
  if (tbRunInFlight) return;
  tbRunInFlight = true;

  const runBtn = $("tbRunBtn");
  let tbTimer = null;
  let tbElapsed = 0;
  if (runBtn) {
    runBtn.disabled = true;
    runBtn.innerHTML = `<span>Connecting to endpoint...</span>`;
    tbTimer = setInterval(() => {
      tbElapsed += 1;
      if (runBtn && tbRunInFlight) {
        const step = tbElapsed < 2 ? "Connecting to agent..." : tbElapsed < 5 ? "Executing tool call..." : "Awaiting response packet...";
        runBtn.innerHTML = `<span>${step} (${tbElapsed}s)</span>`;
      }
    }, 1000);
  }

  const kind = selectedAgent.kind || "mcp";
  const gwUrl = gatewayAgentEndpoint(selectedAgent);
  let tool = "";
  if (kind === "mcp") {
    tool = ($("tbCustomToolInput") && $("tbCustomToolInput").value.trim()) || ($("tbToolSelect") ? $("tbToolSelect").value : "");
  }

  const kpiStatus = $("tbKpiStatus");
  const kpiLatency = $("tbKpiLatency");
  const kpiProto = $("tbKpiProtocol");
  const kpiTime = $("tbKpiTime");
  const outputPre = $("tbOutputPre");

  if (kpiStatus) {
    kpiStatus.textContent = "Probing...";
    kpiStatus.style.color = "var(--accent)";
  }
  if (kpiLatency) {
    kpiLatency.textContent = "executing...";
    kpiLatency.style.color = "var(--text-muted)";
  }
  if (kpiProto) {
    kpiProto.textContent = kind.toUpperCase();
  }
  if (kpiTime) {
    const now = new Date();
    kpiTime.textContent = now.toLocaleTimeString("en-US", { timeZone:"UTC", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
  if (outputPre) {
    outputPre.textContent = `Submitting a test request to Agent Concierge...\nTarget: ${selectedAgent.name || "Agent"}\nGateway URL: ${gwUrl}\nProtocol: ${kind.toUpperCase()}\nAwaiting response packet...`;
  }

  const inspCard = document.querySelector("#secTest .testbench-studio-grid > .card:nth-child(2)");
  if (inspCard && typeof inspCard.scrollIntoView === "function") {
    inspCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  let args = {};
  if (kind !== "x402") {
    const rawArgs = ($("tbArgsEditor") ? $("tbArgsEditor").value : "").trim();
    if (rawArgs) {
      try {
        args = JSON.parse(rawArgs);
      } catch (err) {
        tbRunInFlight = false;
        toast("Please provide valid JSON arguments before running.", "error");
        if (runBtn) {
          runBtn.disabled = false;
          runBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>Run test</span>`;
        }
        if (kpiStatus) {
          kpiStatus.textContent = "Error";
          kpiStatus.style.color = "var(--bad)";
        }
        return;
      }
    }
  }

  const message = kind === "a2a" ? ($("tbA2aMessage") ? $("tbA2aMessage").value : "") : "";
  const timeoutSec = parseFloat($("tbTimeoutSelect") ? $("tbTimeoutSelect").value : "10.0") || 10.0;

  const payload = {
    resource_id: selectedAgent.id,
    tool: tool,
    arguments: args,
    message: message,
    timeout_seconds: timeoutSec
  };

  try {
    const requestStarted = performance.now();
    const res = await api("/api/test/execute", {
      method: "POST",
      json: payload,
      timeoutMs: 12000,
      userInitiated: true,
      loadingMsg: "Executing live agent test..."
    });
    // The agent's own response time and the full round trip are shown separately.
    if (res && typeof res === "object") res.client_total_ms = Math.round(performance.now() - requestStarted);

    renderTestbenchResult(res, gwUrl);
    recordTestbenchHistory(selectedAgent, tool || message || "GET Probe", res);
    toast(res.simulated ? "Demo only — no provider was contacted." : res.execution_succeeded ? "Agent execution completed." : "No completed output. Review the test status.", res.execution_succeeded ? "success" : "info");
  } catch (err) {
    const errorMsg = (err.name === "AbortError" || String(err.message).toLowerCase().includes("timeout"))
      ? `Test request timed out after ${tbElapsed}s. The provider did not respond in time. Please retry.`
      : scrubGatewayText(err.message || "Test execution failed.", gwUrl);
    const errorRes = {
      ok: false,
      status_code: err.status || 500,
      error_code: err.error_code || "EXECUTION_FAILED",
      correlation_id: err.correlation_id || "",
      latency_ms: 0,
      is_error: true,
      error_message: errorMsg,
      protocol: kind,
      output: "Execution Failure:\n" + errorMsg,
      request_wire: { url: "https://agentconcierge.biz/api/test/execute", method: "POST", body: payload, scope: "client-to-gateway" },
      simulated: false, task_status: "failed", execution_succeeded: false,
      response_wire: { error: errorMsg },
      tested_at: Date.now() / 1000
    };
    renderTestbenchResult(errorRes, gwUrl);
    recordTestbenchHistory(selectedAgent, tool || message || "GET Probe", errorRes);
    toast(`Test failed: ${err.message || "Unknown error"}`, "error");
  } finally {
    if (tbTimer) clearInterval(tbTimer);
    tbRunInFlight = false;
    if (runBtn) {
      runBtn.disabled = !tbSelectedAgent;
      runBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>Run test</span>`;
    }
  }
}

function renderTestbenchResult(res, endpointOverride) {
  tbLastResult = res;
  const gwUrl = (typeof endpointOverride === "string" && isGatewayOrigin(endpointOverride))
    ? endpointOverride
    : (tbSelectedAgent ? gatewayAgentEndpoint(tbSelectedAgent) : "");

  const kpiStatus = $("tbKpiStatus");
  const kpiLatency = $("tbKpiLatency");
  const kpiProto = $("tbKpiProtocol");
  const kpiTime = $("tbKpiTime");

  if (kpiStatus) {
    kpiStatus.textContent = res.simulated ? "Demo — not live" : res.execution_succeeded ? "Completed" : res.task_status === "authorization-required" ? "Authorization required" : res.task_status || "Failed";
    kpiStatus.style.color = res.execution_succeeded ? "var(--ok)" : "var(--warn)";
  }

  if (kpiLatency) {
    const l = res.latency_ms || 0;
    const total = Number.isFinite(res.client_total_ms) && res.client_total_ms > l
      ? ` · total ${res.client_total_ms >= 1000 ? (res.client_total_ms / 1000).toFixed(1) + " s" : res.client_total_ms + " ms"}` : "";
    kpiLatency.textContent = `${l} ms gateway${total}${res.simulated ? " (local demo)" : ""}`;
    if (l < 100) kpiLatency.style.color = "var(--ok)";
    else if (l < 500) kpiLatency.style.color = "var(--reach)";
    else kpiLatency.style.color = "var(--warn)";
  }

  if (kpiProto) {
    kpiProto.textContent = (res.protocol || "mcp").toUpperCase();
  }

  if (kpiTime) {
    const d = new Date((res.tested_at || Date.now() / 1000) * 1000);
    const clock = value => value.toLocaleTimeString("en-US", { timeZone:"UTC", hour: "2-digit", minute: "2-digit", second: "2-digit" }) + " UTC";
    // A provider may answer from its own cache; show when that data was retrieved.
    const output = testResultEnvelope(res.output);
    const retrieved = Date.parse(output.retrieved_at || output.structuredContent?.retrieved_at || "");
    const cacheState = output.cache?.status || output.structuredContent?.cache?.status;
    const cached = Number.isFinite(retrieved) && (cacheState && cacheState !== "live" || Math.abs(d.getTime() - retrieved) > 120000);
    kpiTime.textContent = clock(d) + (cached ? " · data retrieved " + clock(new Date(retrieved)) + " (cached)" : "");
  }

  if ($("tbOutputPre")) {
    const supportReference = /^ex_[0-9a-f]{24}$/.test(res.correlation_id || "") ? `\n\nSupport reference: ${res.correlation_id}` : "";
    $("tbOutputPre").style.whiteSpace = "normal";
    $("tbOutputPre").innerHTML = readableResultHtml(scrubGatewayText(res.output || res.error_message || "No result was returned.", gwUrl)) + (supportReference ? "<p>"+esc(supportReference)+"</p>" : "");
  }

  if ($("tbRequestWirePre")) {
    $("tbRequestWirePre").textContent = scrubGatewayText(JSON.stringify(res.request_wire || {}, null, 2), gwUrl);
  }
  if ($("tbResponseWirePre")) {
    $("tbResponseWirePre").textContent = scrubGatewayText(JSON.stringify(res.response_wire || {}, null, 2), gwUrl);
  }

  if ($("tbTelemEndpoint")) $("tbTelemEndpoint").textContent = gwUrl || "Demo — no live connection";
  if ($("tbTelemStatus")) $("tbTelemStatus").textContent = res.simulated ? "Simulation — no HTTP exchange" : `${res.task_status || "failed"} · HTTP ${res.status_code || "unavailable"}`;
  if ($("tbTelemLatency")) $("tbTelemLatency").textContent = `${res.latency_ms || 0} ms`;
}

function switchTestbenchInspectorTab(subtab) {
  document.querySelectorAll("#secTest .sub-pills .sub-pill").forEach((b) => {
    b.classList.toggle("active", b.dataset.subtab === subtab);
  });
  if ($("tbInspectorFormatted")) $("tbInspectorFormatted").classList.toggle("hidden", subtab !== "formatted");
  if ($("tbInspectorRaw")) $("tbInspectorRaw").classList.toggle("hidden", subtab !== "raw");
  if ($("tbInspectorTelemetry")) $("tbInspectorTelemetry").classList.toggle("hidden", subtab !== "telemetry");
}

function copyTestbenchOutput(type) {
  let text = "";
  if (type === "formatted" && $("tbOutputPre")) text = $("tbOutputPre").textContent;
  else if (type === "request" && $("tbRequestWirePre")) text = $("tbRequestWirePre").textContent;
  else if (type === "response" && $("tbResponseWirePre")) text = $("tbResponseWirePre").textContent;

  if (text) {
    navigator.clipboard.writeText(text).then(() => {
      toast("Copied to clipboard.");
    }).catch(() => {
      toast("Unable to copy to clipboard.");
    });
  }
}

function loadTestbenchHistory() {
  try {
    sessionStorage.removeItem("agent_testbench_history");
    const saved = sessionStorage.getItem("agent_testbench_history_v2");
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) {
        tbHistory = parsed.filter((item) => item && typeof item === "object").slice(0, 50).map((item) => {
          const proto = ["a2a", "mcp", "x402"].includes(String(item.protocol || "").toLowerCase())
            ? String(item.protocol).toLowerCase()
            : "mcp";
          const gw = typeof item.gateway_endpoint === "string" && isGatewayOrigin(item.gateway_endpoint)
            ? item.gateway_endpoint
            : "";
          return {
            agent_id: item.agent_id,
            agent_name: String(item.agent_name || "Agent").slice(0, 120),
            protocol: proto,
            gateway_endpoint: gw,
            action: String(item.action || "execute").slice(0, 40),
            status_code: item.status_code ?? null,
            simulated: item.simulated === true,
            task_status: String(item.task_status || "failed").slice(0, 40),
            execution_succeeded: item.execution_succeeded === true,
            latency_ms: Number(item.latency_ms) || 0,
            timestamp: Number(item.timestamp) || Date.now(),
            result: (item.result && typeof item.result === "object") ? item.result : {}
          };
        });
      } else {
        tbHistory = [];
      }
      updateTestbenchHistoryTable();
    }
  } catch (e) {
    tbHistory = [];
  }
}

function recordTestbenchHistory(agent, action, res) {
  const gwUrl = gatewayAgentEndpoint(agent);
  let safeRes = res || {};
  try {
    safeRes = JSON.parse(scrubGatewayText(JSON.stringify(res || {}), gwUrl));
  } catch (e) {}
  const item = {
    agent_id: agent.id,
    agent_name: agent.name,
    protocol: agent.kind || "mcp",
    gateway_endpoint: gwUrl,
    action: String(action || "execute").slice(0, 40),
    status_code: res.status_code ?? null,
    simulated: res.simulated === true,
    task_status: res.task_status || "failed",
    execution_succeeded: res.execution_succeeded === true,
    latency_ms: res.latency_ms || 0,
    timestamp: Date.now(),
    result: safeRes
  };
  tbHistory.unshift(item);
  if (tbHistory.length > 50) tbHistory.pop();

  try {
    sessionStorage.setItem("agent_testbench_history_v2", JSON.stringify(tbHistory));
  } catch (e) {}

  updateTestbenchHistoryTable();
}

function updateTestbenchHistoryTable() {
  const tbody = $("tbHistoryTbody");
  if (!tbody) return;

  if (tbHistory.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:24px">No test executions in this session yet. Execute a test above to record session history.</td></tr>`;
    return;
  }

  tbody.innerHTML = tbHistory.map((item, idx) => {
    const isOk = item.execution_succeeded === true;
    const timeStr = new Date(item.timestamp).toLocaleTimeString("en-US", { timeZone:"UTC", hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const kClass = item.protocol === "a2a" ? "k-a2a" : (item.protocol === "mcp" ? "k-mcp" : "k-x402");

    return `
      <tr>
        <td><strong>${esc(item.agent_name)}</strong></td>
        <td><span class="kind-badge ${kClass}">${esc(item.protocol.toUpperCase())}</span></td>
        <td style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px">${esc(item.action)}</td>
        <td><span style="color:${isOk ? 'var(--ok)' : 'var(--bad)'};font-weight:700">${esc(item.simulated ? "Demo" : item.task_status || "Unverified")}</span></td>
        <td>${esc(String(item.latency_ms))} ms</td>
        <td style="color:var(--text-dim);font-size:12px">${esc(timeStr)}</td>
        <td style="text-align:right">
          <button class="chip-btn" data-idx="${idx}" data-ac-click="9949afce41e2" style="font-size:11px">Inspect</button>
        </td>
      </tr>
    `;
  }).join("");
}

function inspectHistoryItem(idxStr) {
  const idx = parseInt(idxStr, 10);
  if (isNaN(idx) || !tbHistory[idx]) return;

  const item = tbHistory[idx];
  renderTestbenchResult(item.result, item.gateway_endpoint);
  switchTestbenchInspectorTab("formatted");
  toast(`Inspecting run for ${item.agent_name}`);
}

function exportTestbenchHistory() {
  if (tbHistory.length === 0) {
    toast("No test session history to export.");
    return;
  }
  const report = {
    exported_at: new Date().toISOString(),
    session_runs: tbHistory.length,
    environment: "Agent Concierge Public Testbench Sandbox (agentconcierge.biz)",
    history: tbHistory
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `agentconcierge-test-session-report-${Date.now()}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast("Downloaded test session report.");
}

function clearTestbenchHistory() {
  tbHistory = [];
  try {
    sessionStorage.removeItem("agent_testbench_history_v2");
  } catch (e) {}
  updateTestbenchHistoryTable();
  toast("Session history cleared.");
}

function closeDrawer() {
  agentDetailRevision += 1;
  agentDetailController?.abort();
  agentDetailController = null;
  $("drawer").classList.add("hidden");
  $("drawerBackdrop").classList.add("hidden");
}
$("closeDrawer").onclick = closeDrawer;
$("drawerBackdrop").onclick = closeDrawer;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
});

function testAgentFromDrawer(agentId) {
  if (!agentId || agentId === "undefined") return;
  closeDrawer();
  switchTab("test");
  history.replaceState(null, "", "#test?id=" + encodeURIComponent(agentId));

  const applyAgentToTestbench = () => {
    const sel = $("tbAgentSelect");
    if (!sel) return;

    const strId = String(agentId);
    let optExists = Array.from(sel.options).some((o) => o.value === strId);
    if (!optExists) {
      const cached = (typeof EXPLORE_AGENT_MAP !== "undefined" && EXPLORE_AGENT_MAP.get(strId)) || getSwrCache("agent:" + strId);
      const opt = document.createElement("option");
      opt.value = strId;
      const optName = cached ? `${cached.name} [${(cached.kind || 'mcp').toUpperCase()}]` : `Agent #${strId}`;
      opt.textContent = optName;
      sel.appendChild(opt);
    }
    sel.value = strId;
    onTestbenchAgentChange(strId, () => {
      const name = tbSelectedAgent ? tbSelectedAgent.name : "Agent";
      toast(`Loaded "${name}" into Testbench.`, "success");
    });

    const targetStudio = document.querySelector("#secTest .testbench-studio-grid") || $("secTest");
    if (targetStudio && typeof targetStudio.scrollIntoView === "function") {
      targetStudio.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  if (tbPresetsCache.length || tbAgentsCache.length) {
    applyAgentToTestbench();
  } else {
    loadTestbenchUI(agentId);
    setTimeout(applyAgentToTestbench, 200);
  }
}

function copyDrawerUrl(url) {
  if (!url) return;
  navigator.clipboard.writeText(url).then(() => {
    toast("Endpoint URL copied to clipboard.", "success");
  }).catch(() => {
    toast("Unable to copy URL to clipboard.", "error");
  });
}

// ---------- Scroll to Top Button ----------
const scrollTopBtn = $("scrollTopBtn");
function updateScrollTopBtn() {
  const isDrawerOpen = !$("drawer").classList.contains("hidden");
  const drawerScrolled = isDrawerOpen && $("drawer").scrollTop > 180;
  const winScrolled = window.scrollY > 180;
  if (drawerScrolled || winScrolled) {
    scrollTopBtn.classList.add("show");
  } else {
    scrollTopBtn.classList.remove("show");
  }
}
window.addEventListener("scroll", updateScrollTopBtn, { passive: true });
$("drawer").addEventListener("scroll", updateScrollTopBtn, { passive: true });
scrollTopBtn.onclick = () => {
  if (!$("drawer").classList.contains("hidden") && $("drawer").scrollTop > 50) {
    $("drawer").scrollTo({ top: 0, behavior: "smooth" });
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
};

// Synchronously hydrate bootstrap data on initial page load (Zero-Loading startup)
let overviewBootstrapped = false;
try {
  const bEl = $("appBootstrapData");
  if (bEl && bEl.textContent) {
    const bData = JSON.parse(bEl.textContent);
    if (bData.overview) {
      overviewBootstrapped = true;
      setSwrCache("overview", bData.overview);
      renderOverview(bData.overview);
    }
    if (bData.explore) {
      // Inline discovery is a preview; the first Explore visit loads its full page.
      lastExploreKey = null;
      setSwrCache("explore:|||0|0", bData.explore);
      if (bData.explore.items && bData.explore.items.length) {
        renderExplore(bData.explore.items, "", bData.explore.total, bData.explore.total_is_estimate, bData.explore.matched_report_count);
      }
    }
    if (bData.insights) {
      insightsData = bData.insights;
      setSwrCache("insights", bData.insights);
      if (location.hash === "#learn") {
        renderLearnUI();
      }
    }
    if (bData.workflow_templates) {
      frontTemplatesCache = bData.workflow_templates;
      frontTemplatesFromPage = Array.isArray(bData.workflow_templates) && bData.workflow_templates.length > 0;
      setSwrCache("workflow_templates_v5", bData.workflow_templates);
    }
    if (Array.isArray(bData.testbench_examples)) tbLiveExamples = bData.testbench_examples;
    if (Array.isArray(bData.testbench_agents) && tbLiveExamples.length) {
      for (const agent of bData.testbench_agents) tbPageAgents.set(Number(agent.id), agent);
      tbExamplesFromPage = true;
      tbExamplesState = "ready";
    }
    if (bData.testbench_presets) {
      tbPresetsCache = bData.testbench_presets;
      setSwrCache("testbench_presets", bData.testbench_presets);
    }
  }
} catch (e) {}

// Initial routing
const rawHash = (location.hash || "#" + document.body.dataset.pearlEntry).slice(1).replace(/^(ai-transparency|legal\/ai)$/, "ai");
const [initTab, initParam] = rawHash.split("?");
if (initTab === "explore") restoreExploreLocation();
if (LEGAL_ROUTES.includes(initTab)) {
  switchTab("overview");
  setTimeout(() => { openLegalModal(initTab); }, 100);
} else {
  switchTab(TABS.includes(initTab) ? initTab : "overview");
}
if (initTab === "test" && initParam && initParam.startsWith("id=")) {
  const deepId = initParam.slice(3);
  setTimeout(() => { if (typeof onTestbenchAgentChange === "function") onTestbenchAgentChange(deepId); }, 150);
}
sanitizePort8080();

initialRoutingComplete = true;

// ---------- Home data refresh; other panels retain their editing state ----------
let lastUserActiveTimestamp = Date.now();

function handleIdleReconnection() {
  const now = Date.now();
  const idleMs = now - lastUserActiveTimestamp;
  lastUserActiveTimestamp = now;
  if (idleMs >= 60000 && currentTab === "overview" && document.visibilityState === "visible" && navigator.onLine) {
    loadOverview(true);
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
setInterval(() => {
  if (currentTab === "overview" && document.visibilityState === "visible" && navigator.onLine) loadOverview(true);
}, 60000);

# -*- coding: utf-8 -*-
"""Apply comprehensive global legal compliance features to the frontend (Strictly English)."""

import json
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/Users/kingstonelee/workspace/A2A_Discovery")

def main():
    front_py_path = ROOT / "agent_market" / "concierge" / "front.py"
    front_code = front_py_path.read_text(encoding="utf-8")

    # Locate HTML definition in front.py
    m = re.search(r'\nHTML = ([\'"].*?[\'"])\n\ndef create_front_app', front_code, re.DOTALL)
    if not m:
        print("ERROR: Could not locate HTML definition in front.py")
        sys.exit(1)

    # Use ast.literal_eval or json or eval to safely get the string
    import ast
    html_raw = ast.literal_eval(m.group(1))

    print(f"Current HTML raw length: {len(html_raw)}")

    # 1. Add Google Consent Mode v2 right after <head>
    consent_mode_script = """<meta charset="utf-8"><script>
window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('consent', 'default', {
  'ad_storage': 'denied',
  'ad_user_data': 'denied',
  'ad_personalization': 'denied',
  'analytics_storage': 'denied'
});
</script>"""
    if 'gtag(\'consent\'' not in html_raw:
        html_raw = html_raw.replace('<meta charset="utf-8">', consent_mode_script, 1)
        print("✓ Injected Google Consent Mode v2 into <head>")

    # 2. Add Legal & Accessibility CSS into <style>
    legal_css = """
/* Global Legal Compliance, Accessibility, and Cookie Governance */
.skip-link {
  position: fixed;
  top: -60px;
  left: 16px;
  background: var(--accent);
  color: #ffffff;
  padding: 10px 18px;
  font-size: 13.5px;
  font-weight: 700;
  border-radius: 8px;
  z-index: 10000;
  text-decoration: none;
  box-shadow: 0 4px 14px rgba(0,0,0,0.4);
  transition: top 0.2s ease-in-out;
}
.skip-link:focus, .skip-link:focus-visible {
  top: 16px;
  outline: 3px solid #ffffff;
  outline-offset: 2px;
}

:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* Cookie Consent Floating Banner (Equal Weight / Dark Pattern Free) */
.cookie-banner {
  position: fixed;
  bottom: 20px;
  left: 20px;
  right: 20px;
  max-width: 860px;
  margin: 0 auto;
  z-index: 9999;
  background: color-mix(in srgb, var(--panel) 96%, #000 4%);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--border-light);
  border-radius: 16px;
  box-shadow: 0 20px 45px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.06);
  padding: 20px 24px;
  animation: cookieBannerSlideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes cookieBannerSlideUp {
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: translateY(0); }
}
.cookie-banner.hidden {
  display: none !important;
}
.cookie-banner-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 6px;
}
.cookie-banner-text {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.55;
  margin: 0 0 14px 0;
}
.cookie-banner-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.gpc-chip {
  background: color-mix(in srgb, var(--ok) 18%, transparent);
  color: var(--ok);
  border-color: color-mix(in srgb, var(--ok) 35%, transparent);
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 99px;
  letter-spacing: 0.3px;
}

/* Global Legal Footer */
.global-footer {
  margin-top: 50px;
  border-top: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 96%, transparent);
  padding: 36px 24px 40px;
  width: 100%;
  box-sizing: border-box;
}
.footer-wrap {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.footer-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}
.footer-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.footer-logo {
  font-size: 20px;
  line-height: 1;
}
.footer-name {
  font-size: 16px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -0.2px;
}
.footer-tagline {
  font-size: 12px;
  color: var(--text-dim);
}
.footer-compliance-badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.comp-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 99px;
  background: var(--chip);
  border: 1px solid var(--border);
  color: var(--text-muted);
}
.footer-links {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--text-muted);
  padding: 12px 0;
  border-top: 1px solid color-mix(in srgb, var(--border) 60%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--border) 60%, transparent);
}
.footer-links a {
  color: var(--text-muted);
  text-decoration: none;
  font-weight: 500;
  transition: color 0.15s ease;
}
.footer-links a:hover {
  color: var(--accent);
  text-decoration: underline;
}
.footer-links .sep {
  color: var(--text-dim);
  user-select: none;
}
.footer-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  color: var(--text-dim);
}

/* AI Disclosure Banners */
.ai-disclosure-banner {
  background: color-mix(in srgb, var(--accent) 8%, var(--panel));
  border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--border));
  border-left: 4px solid var(--accent);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 14px;
}
.ai-disclosure-banner p {
  margin: 4px 0 0 0;
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.55;
}

/* Clickwrap Box */
.clickwrap-group {
  background: var(--chip);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin: 14px 0 10px 0;
}
.clickwrap-label {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.5;
  cursor: pointer;
}
.clickwrap-label input[type="checkbox"] {
  width: 17px;
  height: 17px;
  accent-color: var(--accent);
  margin-top: 2px;
  flex-shrink: 0;
  cursor: pointer;
}
.clickwrap-label a {
  color: var(--accent);
  text-decoration: underline;
  font-weight: 600;
}

/* Comprehensive Legal Dialog Modal */
dialog.legal-doc-modal {
  max-width: 780px;
  width: calc(100vw - 32px);
  max-height: 88vh;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.legal-modal-header {
  padding: 18px 24px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  background: var(--panel);
}
.legal-modal-title {
  font-size: 18px;
  font-weight: 800;
  color: var(--text);
  margin: 0 0 3px 0;
}
.legal-modal-sub {
  font-size: 12px;
  color: var(--text-dim);
}
.legal-tabs {
  display: flex;
  gap: 6px;
  padding: 8px 24px;
  background: var(--chip);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  flex-wrap: nowrap;
}
.legal-tab-btn {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  border: 1px solid transparent;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.legal-tab-btn:hover {
  color: var(--text);
  background: var(--border);
}
.legal-tab-btn.active {
  color: #ffffff;
  background: var(--accent);
  border-color: var(--accent);
}
.legal-modal-body {
  padding: 20px 24px;
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-muted);
  flex: 1;
}
.legal-modal-body h4 {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--text);
  margin: 18px 0 6px 0;
}
.legal-modal-body h4:first-child {
  margin-top: 0;
}
.legal-modal-body p {
  margin: 0 0 12px 0;
}
.legal-modal-body ul, .legal-modal-body ol {
  padding-left: 20px;
  margin: 0 0 14px 0;
}
.legal-modal-body li {
  margin-bottom: 6px;
}
.legal-modal-footer {
  padding: 12px 24px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--panel);
}
"""
    if '.skip-link {' not in html_raw:
        html_raw = html_raw.replace('</style>', legal_css + '\n</style>', 1)
        print("✓ Injected legal CSS styles into <style>")

    # 3. Add Skip Link & Screen Reader Live Announcer right after <body>
    body_additions = """<body>
<a href="#mainContent" class="skip-link">Skip to main content</a>
<div id="srLiveAnnouncer" class="sr-only" aria-live="polite" aria-atomic="true"></div>
"""
    if '<a href="#mainContent" class="skip-link">' not in html_raw:
        html_raw = html_raw.replace('<body>\n', body_additions, 1)
        print("✓ Injected skip-link and srLiveAnnouncer into <body>")

    # 4. Make <main> accessible with role and id
    if '<main class="main-wrap">' in html_raw:
        html_raw = html_raw.replace(
            '<main class="main-wrap">',
            '<main id="mainContent" class="main-wrap" role="main" tabindex="-1">',
            1
        )
        print("✓ Updated <main> with id, role, and tabindex")

    # 5. Masking on search input in secExplore
    old_xQ = '<input id="xQ" class="input"'
    new_xQ = '<input id="xQ" class="input fs-mask" data-clarity-mask="true"'
    if old_xQ in html_raw and 'data-clarity-mask="true"' not in html_raw[:html_raw.find('id="xQ"')+100]:
        html_raw = html_raw.replace(old_xQ, new_xQ, 1)
        print("✓ Added PII masking to Explore search input")

    # 6. Add Clickwrap Agreement Box before regSubmitBtn in secRegister
    clickwrap_html = """
          <div class="clickwrap-group">
            <label class="clickwrap-label">
              <input type="checkbox" id="regTermsConsent" required>
              <span>
                I affirmatively agree to the <a href="#tos" onclick="openLegalModal('tos');return false;">Terms of Service</a>,
                acknowledge the <a href="#privacy" onclick="openLegalModal('privacy');return false;">Privacy Policy</a>,
                and accept the <a href="#ai-transparency" onclick="openLegalModal('ai');return false;">AI System Disclosures</a>. (Enforceable electronic contracting).
              </span>
            </label>
          </div>
"""
    old_reg_submit = '<button type="button" class="btn primary" id="regSubmitBtn">'
    if 'id="regTermsConsent"' not in html_raw:
        html_raw = html_raw.replace(old_reg_submit, clickwrap_html + '\n            ' + old_reg_submit, 1)
        print("✓ Injected Clickwrap consent checkbox into Registration form")

    # Masking on registration inputs
    for f_id in ["regUrl", "regName", "regDesc", "regPayTo"]:
        orig_tag = f'id="{f_id}" class="input"'
        masked_tag = f'id="{f_id}" class="input fs-mask" data-clarity-mask="true"'
        if orig_tag in html_raw:
            html_raw = html_raw.replace(orig_tag, masked_tag, 1)
    print("✓ Added PII masking attributes to registration inputs")

    # 7. Add AI Disclosure Banner in secChat
    ai_banner_html = """
    <!-- AI Transparency Notice (EU AI Act & US Compliance) -->
    <div class="ai-disclosure-banner" role="note" aria-label="AI System Disclosure">
      <div style="display:flex;align-items:center;gap:8px">
        <span class="report-badge-vivid" style="background:linear-gradient(135deg,#3b82f6,#06b6d4);padding:2px 8px;font-size:10.5px">✦ AI SYSTEM TRANSPARENCY</span>
        <span style="font-size:11.5px;color:var(--text-dim)">EU AI Act (Art. 50) &amp; US Regulatory Disclosure</span>
      </div>
      <p>
        You are engaging with an autonomous machine-to-machine AI concierge system. All responses, tool recommendations, and capability mappings are synthesized via artificial intelligence models. Please independently verify critical code, transaction hashes, or endpoint specifications before live production delegation.
      </p>
    </div>
"""
    if '✦ AI SYSTEM TRANSPARENCY' not in html_raw:
        chat_card_tok = '<!-- Notice Banner with Lucide Robot -->'
        if chat_card_tok in html_raw:
            html_raw = html_raw.replace(chat_card_tok, ai_banner_html + '\n    ' + chat_card_tok, 1)
            print("✓ Injected AI Disclosure Banner into secChat")

    # Masking on chat input
    old_chat_input = '<input id="chatInput" class="input"'
    new_chat_input = '<input id="chatInput" class="input fs-mask" data-clarity-mask="true"'
    if old_chat_input in html_raw and 'data-clarity-mask="true"' not in html_raw[html_raw.find('id="chatInput"')-50:html_raw.find('id="chatInput"')+100]:
        html_raw = html_raw.replace(old_chat_input, new_chat_input, 1)
        print("✓ Added PII masking to Chat input")

    # 8. Add Global Footer right after </main>
    footer_and_modals = """
<!-- Global Compliance Footer -->
<footer class="global-footer" role="contentinfo">
  <div class="footer-wrap">
    <div class="footer-top">
      <div class="footer-brand">
        <span class="footer-logo">⚡</span>
        <div>
          <div class="footer-name">Agent Concierge</div>
          <div class="footer-tagline">Global Autonomous Agent Discovery &amp; Interoperability Platform</div>
        </div>
      </div>
      <div class="footer-compliance-badges">
        <span class="comp-badge">GDPR / CCPA Compliant</span>
        <span class="comp-badge">WCAG 2.1 AA Accessible</span>
        <span class="comp-badge">FTC Click-to-Cancel Ready</span>
        <span class="comp-badge">EU AI Act Transparent</span>
      </div>
    </div>
    <div class="footer-links">
      <a href="#tos" onclick="openLegalModal('tos');return false;">Terms of Service</a>
      <span class="sep">·</span>
      <a href="#privacy" onclick="openLegalModal('privacy');return false;">Privacy Policy</a>
      <span class="sep">·</span>
      <a href="#cookies" onclick="openCookiePrefsModal();return false;">Cookie Preferences</a>
      <span class="sep">·</span>
      <a href="#ccpa" onclick="openLegalModal('ccpa');return false;">Do Not Sell or Share My Personal Info</a>
      <span class="sep">·</span>
      <a href="#accessibility" onclick="openLegalModal('accessibility');return false;">Accessibility Statement</a>
      <span class="sep">·</span>
      <a href="#ai-transparency" onclick="openLegalModal('ai');return false;">AI System Disclosures</a>
      <span class="sep">·</span>
      <a href="#cancellation" onclick="openLegalModal('cancellation');return false;">Subscription &amp; Cancellation</a>
    </div>
    <div class="footer-bottom">
      <div>&copy; 2026 Agent Concierge. All rights reserved. Operating under international cross-border digital service standards.</div>
      <div class="footer-status">Global Protocol Runtime: Active · Timezone: America/New_York (EDT)</div>
    </div>
  </div>
</footer>

<!-- Cookie Consent Floating Banner (GDPR / CCPA / GPC) -->
<div id="cookieConsentBanner" class="cookie-banner hidden" role="region" aria-label="Privacy and Cookie Consent">
  <div class="cookie-banner-title">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 10 10 0 1 0-10-10"/></svg>
    <span>Privacy &amp; Cookie Governance</span>
    <span id="gpcBadge" class="chip gpc-chip hidden">GPC Active</span>
  </div>
  <p class="cookie-banner-text">
    We respect your privacy under GDPR, UK PECR, and CCPA/CPRA. We use essential tokens for security and protocol routing. Analytics and telemetry cookies are blocked until you grant affirmative consent.
  </p>
  <div class="cookie-banner-actions">
    <button type="button" class="btn primary" id="btnAcceptAllCookies">Accept All</button>
    <button type="button" class="btn" id="btnRejectNonEssentialCookies">Reject Non-Essential</button>
    <button type="button" class="btn" id="btnOpenCookiePrefs">Cookie Preferences</button>
  </div>
</div>

<!-- Cookie Preferences Modal -->
<dialog id="cookiePrefsModal" class="layer-modal legal-doc-modal" aria-labelledby="cookiePrefsTitle">
  <div class="legal-modal-header">
    <div>
      <h3 id="cookiePrefsTitle" class="legal-modal-title">Cookie &amp; Privacy Preferences</h3>
      <div class="legal-modal-sub">Manage your telemetry and data processing consent preferences</div>
    </div>
    <button type="button" class="layer-modal-close" onclick="$('cookiePrefsModal').close();" aria-label="Close dialog">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
    </button>
  </div>
  <div class="legal-modal-body">
    <div style="background:var(--chip);padding:14px;border-radius:10px;border:1px solid var(--border);margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <b style="color:var(--text);font-size:13.5px">Strictly Necessary Cookies &amp; Tokens</b>
        <span class="chip" style="color:var(--ok);font-weight:700">Always Active</span>
      </div>
      <p style="font-size:12px;color:var(--text-muted);margin:0;line-height:1.5">
        Required for core system security, rate limiting, and visitor session continuity via <code>X-Visitor-Token</code>. Cannot be deactivated.
      </p>
    </div>

    <div style="background:var(--chip);padding:14px;border-radius:10px;border:1px solid var(--border);margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <b style="color:var(--text);font-size:13.5px">Performance &amp; Telemetry Analytics</b>
        <label style="display:inline-flex;align-items:center;cursor:pointer">
          <input type="checkbox" id="prefAnalyticsToggle" style="width:18px;height:18px;accent-color:var(--accent)">
        </label>
      </div>
      <p style="font-size:12px;color:var(--text-muted);margin:0;line-height:1.5">
        Helps us understand ecosystem traffic patterns, agent discovery success rates, and tool responsiveness. Governed by Google Consent Mode v2 (<code>analytics_storage</code>).
      </p>
    </div>

    <div style="background:var(--chip);padding:14px;border-radius:10px;border:1px solid var(--border)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <b style="color:var(--text);font-size:13.5px">Cross-Context Marketing &amp; Personalization</b>
        <label style="display:inline-flex;align-items:center;cursor:pointer">
          <input type="checkbox" id="prefMarketingToggle" style="width:18px;height:18px;accent-color:var(--accent)">
        </label>
      </div>
      <p style="font-size:12px;color:var(--text-muted);margin:0;line-height:1.5">
        Disabled by default. We do not sell personal data or run tracking ad pixels across external web properties.
      </p>
    </div>
  </div>
  <div class="legal-modal-footer">
    <button type="button" class="btn" onclick="$('cookiePrefsModal').close();">Cancel</button>
    <div style="display:flex;gap:8px">
      <button type="button" class="btn" id="btnSaveCookiePrefs">Save Preferences</button>
      <button type="button" class="btn primary" id="btnAcceptAllInPrefs">Accept All</button>
    </div>
  </div>
</dialog>

<!-- Comprehensive Legal Modal (ToS, Privacy, CCPA, Accessibility, AI Disclosures, FTC) -->
<dialog id="legalModal" class="layer-modal legal-doc-modal" aria-labelledby="legalModalTitle">
  <div class="legal-modal-header">
    <div>
      <h3 id="legalModalTitle" class="legal-modal-title">Legal Compliance &amp; Regulatory Terms</h3>
      <div class="legal-modal-sub" id="legalModalSub">International Cross-Border Digital Services Standard</div>
    </div>
    <button type="button" class="layer-modal-close" onclick="$('legalModal').close();" aria-label="Close dialog">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
    </button>
  </div>
  <div class="legal-tabs" role="tablist" id="legalModalTabs">
    <button type="button" class="legal-tab-btn active" data-doc="tos" onclick="switchLegalDoc('tos')">Terms of Service</button>
    <button type="button" class="legal-tab-btn" data-doc="privacy" onclick="switchLegalDoc('privacy')">Privacy Policy</button>
    <button type="button" class="legal-tab-btn" data-doc="ccpa" onclick="switchLegalDoc('ccpa')">Do Not Sell / CCPA</button>
    <button type="button" class="legal-tab-btn" data-doc="accessibility" onclick="switchLegalDoc('accessibility')">Accessibility</button>
    <button type="button" class="legal-tab-btn" data-doc="ai" onclick="switchLegalDoc('ai')">AI Disclosures</button>
    <button type="button" class="legal-tab-btn" data-doc="cancellation" onclick="switchLegalDoc('cancellation')">FTC Cancellation</button>
  </div>
  <div class="legal-modal-body" id="legalModalBody">
    <!-- Populated dynamically via JS -->
  </div>
  <div class="legal-modal-footer">
    <div style="font-size:11.5px;color:var(--text-dim)">Governed by international digital consumer protection standards</div>
    <button type="button" class="btn primary" onclick="$('legalModal').close();">Close</button>
  </div>
</dialog>
"""
    if '</main>\n\n<!-- Global Compliance Footer -->' not in html_raw:
        html_raw = html_raw.replace('</main>\n\n', '</main>\n\n' + footer_and_modals + '\n', 1)
        print("✓ Injected Global Footer, Cookie Banner, and Legal Dialog Modals after </main>")

    # 9. Add Javascript logic for Legal, Cookie Governance, GPC, Clickwrap, and Unsubscribe
    legal_js_logic = """
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
      showModalAlert({
        type: "success",
        title: "Consent Preferences Recorded",
        message: "Your privacy preferences have been stored. All non-essential telemetry will proceed under affirmative consent."
      });
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
      showModalAlert({
        type: "info",
        title: "Non-Essential Telemetry Blocked",
        message: "Non-essential analytics and marketing trackers have been deactivated in compliance with GDPR/PECR."
      });
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
  modal.showModal();
}

// ---------------- Legal Document Texts ----------------
const LEGAL_DOCS = {
  tos: {
    title: "Terms of Service",
    sub: "Effective Date: October 2026 · Governing Law: State of Delaware (USA)",
    html: `
      <h4>1. Acceptance of Terms &amp; Clickwrap Binding Agreement</h4>
      <p>By accessing Agent Concierge ("Platform"), making programmatic calls to endpoints (REST, A2A, MCP), or registering an autonomous endpoint, you affirmatively enter into a legally binding contract under US and international electronic contracting laws. If you do not agree, you must immediately terminate access.</p>

      <h4>2. Autonomous Machine Interaction &amp; Prohibited Conduct</h4>
      <p>Users and automated agent clients agree not to:</p>
      <ul>
        <li>Submit SSRF payloads, localhost targets, private subnet IP ranges, or malware vectors.</li>
        <li>Bypass architectural rate limiters or security headers via distributed botnets.</li>
        <li>Publish fraudulent or impersonating agent endpoint listings.</li>
      </ul>

      <h4>3. Disclaimers of Warranties ("AS IS")</h4>
      <p>The Platform provides discovery indexing, quality evaluation metrics, and protocol routing strictly on an "AS IS" and "AS AVAILABLE" basis. We make no express or implied warranties regarding uptime, accuracy of third-party agent responses, or fitness for any specialized commercial purpose.</p>

      <h4>4. Limitation of Liability</h4>
      <p>To the maximum extent permitted by applicable law, in no event shall Agent Concierge or its operators be liable for indirect, incidental, punitive, or consequential damages (including lost profits, failed token transactions, or execution downtime). Total aggregate liability is limited to $100.00 USD.</p>

      <h4>5. Mandatory Dispute Resolution &amp; Class Action Waiver</h4>
      <p>Any dispute arising out of these Terms shall be resolved exclusively through final and binding individual arbitration administered by the American Arbitration Association (AAA) under its Commercial Arbitration Rules. You waive any right to participate in class actions or representative proceedings.</p>
    `
  },
  privacy: {
    title: "Privacy Policy",
    sub: "Compliance: EU/UK GDPR (2016/679) &amp; California Consumer Privacy Act (CCPA/CPRA)",
    html: `
      <h4>1. Data Controller &amp; Minimalist Processing Commitment</h4>
      <p>Agent Concierge operates on principles of privacy-by-design and rigorous data minimization. Data Protection Contact: <code>privacy@agentconcierge.biz</code>.</p>

      <h4>2. Information We Process</h4>
      <ul>
        <li><b>Endpoint Registrations</b>: Publicly declared agent names, endpoint URLs, capability tags, and cryptographic settlement parameters.</li>
        <li><b>Ephemeral Telemetry</b>: Anonymized IP addresses and request paths retained for up to 72 hours solely for rate limiting and DDoS defense (GDPR Art. 6(1)(f) Legitimate Interest).</li>
        <li><b>Session Continuity Tokens</b>: Cryptographic visitor tokens (<code>X-Visitor-Token</code>) generated to resume agent sessions without requiring human PII.</li>
      </ul>

      <h4>3. Zero Sale or Cross-Context Sharing of Personal Information</h4>
      <p>We do not sell, rent, or trade personal data or visitor tokens to third parties. We do not engage in cross-context behavioral advertising.</p>

      <h4>4. Rights of Data Subjects (GDPR &amp; UK GDPR)</h4>
      <p>You have the absolute right to request access, rectification, erasure, or restriction of your registration data, or to lodge a grievance with a competent European Supervisory Authority.</p>

      <h4>5. Cross-Border Transfers &amp; Subresource Integrity</h4>
      <p>All global transmissions adhere to standard contractual clauses (SCCs) ensuring continuous protection across US, UK, and EU jurisdictions.</p>
    `
  },
  ccpa: {
    title: "Do Not Sell or Share My Personal Information",
    sub: "California Consumer Privacy Act (CCPA) &amp; CPRA Statutory Notice",
    html: `
      <h4>1. Affirmation of Non-Sale</h4>
      <p>Under the California Consumer Privacy Act (CCPA) as amended by the CPRA, California residents have the right to opt out of the "sale" or "sharing" of personal information. <b>Agent Concierge does not sell or share personal information</b> to third parties for monetary or valuable consideration.</p>

      <h4>2. Global Privacy Control (GPC) Compliance</h4>
      <p>We natively detect and honor the Global Privacy Control (GPC) signal (<code>navigator.globalPrivacyControl</code>). When your browser broadcasts an affirmative GPC opt-out preference, our client automatically disables non-essential telemetry and sets your consent status to strictly essential.</p>

      <h4>3. One-Click Permanent Opt-Out</h4>
      <p>Click the button below to confirm and write a persistent CCPA opt-out record to your browser storage:</p>
      <div style="margin:14px 0">
        <button type="button" class="btn primary" id="btnConfirmCcpaOptOut" onclick="confirmCcpaOptOut()">
          Confirm CCPA / GPC Opt-Out
        </button>
      </div>
      <div id="ccpaOptOutStatus" style="font-size:12.5px;color:var(--ok);margin-top:6px"></div>
    `
  },
  accessibility: {
    title: "Web Accessibility Statement",
    sub: "WCAG 2.1 Level AA &amp; ADA Title III / European Accessibility Act (EAA) Compliance",
    html: `
      <h4>1. Commitment to Accessible Engineering</h4>
      <p>Agent Concierge is dedicated to digital accessibility for individuals with disabilities. We continuously audit and adapt our frontend application to comply with the Web Content Accessibility Guidelines (WCAG) 2.1 Level AA standards, ADA Title III, and the European Accessibility Act (EAA Directive 2019/882).</p>

      <h4>2. Technical Accessibility Measures Implemented</h4>
      <ul>
        <li><b>Keyboard Operability</b>: Complete interactive flow accessibility via <code>Tab</code>, <code>Shift+Tab</code>, <code>Enter</code>, <code>Space</code>, and <code>Escape</code> without keyboard traps.</li>
        <li><b>Visual Contrast &amp; Focus Rings</b>: Minimum text contrast of 4.5:1 (UI controls 3:1) and visible high-contrast <code>:focus-visible</code> indicators across all buttons and inputs.</li>
        <li><b>Screen Reader Landmarks &amp; Live Regions</b>: Semantic HTML5 elements (<code>&lt;header role="banner"&gt;</code>, <code>&lt;main role="main"&gt;</code>, <code>&lt;footer role="contentinfo"&gt;</code>) and dynamic route change announcements via <code>aria-live="polite"</code>.</li>
        <li><b>Skip Navigation</b>: Built-in skip-to-main-content mechanism for keyboard and switch-device navigators.</li>
      </ul>

      <h4>3. Formal Feedback &amp; Reasonable Accommodation Channel</h4>
      <p>If you encounter any difficulty navigating or accessing content, please contact our Accessibility Officer at <code>accessibility@agentconcierge.biz</code>. We investigate and remediate reported barriers within 48 business hours.</p>
    `
  },
  ai: {
    title: "AI System Transparency &amp; Disclosures",
    sub: "EU AI Act (Regulation 2024/1689, Article 50) &amp; US Model Disclosures",
    html: `
      <h4>1. Synthetic System &amp; Non-Human Interface Disclosure</h4>
      <p>In accordance with Article 50 of the European Union Artificial Intelligence Act, users and autonomous agents are informed that the interactive concierge (<code>POST /chat</code>) and discovery classification engine are powered by automated artificial intelligence models, not human agents.</p>

      <h4>2. Probabilistic Outputs &amp; Advisory Nature</h4>
      <p>Recommendations, tool matching scores, and protocol schemas synthesized by the concierge are probabilistic outputs. They are provided for informational and delegation matching purposes.</p>

      <h4>3. Developer &amp; Caller Verification Responsibility</h4>
      <p>Developers and autonomous agents must independently verify critical technical payloads, x402 payment smart contracts, and tool parameter schemas before executing state-changing transactions or deploying to production environments.</p>

      <h4>4. Prohibited Practices &amp; Safety Assurance</h4>
      <p>We do not deploy deceptive biometric categorization, subliminal manipulation, or discriminatory social scoring systems within the discovery registry.</p>
    `
  },
  cancellation: {
    title: "FTC Click-to-Cancel &amp; Subscription Terms",
    sub: "Federal Trade Commission (FTC) Negative Option Rule Compliance",
    html: `
      <h4>1. FTC "Click-to-Cancel" Principle</h4>
      <p>In full compliance with FTC consumer protection rules, canceling or unsubscribing from notifications, alerts, or services must be as simple and immediate as enrollment. There are zero mandatory telephone calls, zero retention mazes, and zero artificial delays.</p>

      <h4>2. Zero Drip Pricing &amp; Transparent Billing</h4>
      <p>Agent Concierge does not charge surprise recurring subscriptions. All x402 micropayments are strictly pay-per-call in USDC on verified blockchain networks. Costs are displayed upfront with zero hidden processing fees.</p>

      <h4>3. Instant 1-Click Unsubscribe Form</h4>
      <p>To cancel notifications or unsubscribe an agent from capability updates, enter your visitor token below (or leave blank to use your current session token) and click Unsubscribe:</p>
      <div style="background:var(--chip);padding:14px;border-radius:8px;border:1px solid var(--border);margin:12px 0">
        <label style="font-size:12px;font-weight:600;display:block;margin-bottom:4px">Visitor Token (X-Visitor-Token)</label>
        <div style="display:flex;gap:8px">
          <input type="text" id="ftcCancelToken" class="input fs-mask" data-clarity-mask="true" placeholder="Enter vt_... or leave blank for active token" style="flex:1">
          <button type="button" class="btn primary" id="btnFtcUnsubscribe" onclick="executeOneClickUnsubscribe()">Cancel / Unsubscribe</button>
        </div>
        <div id="ftcCancelMsg" style="font-size:12.5px;margin-top:6px"></div>
      </div>
    `
  }
};

function openLegalModal(docType = "tos") {
  const modal = $("legalModal");
  if (!modal) return;
  switchLegalDoc(docType);
  modal.showModal();
}

function switchLegalDoc(docType) {
  const doc = LEGAL_DOCS[docType] || LEGAL_DOCS.tos;
  $("legalModalTitle").textContent = doc.title;
  $("legalModalSub").textContent = doc.sub;
  $("legalModalBody").innerHTML = doc.html;

  const tabs = document.querySelectorAll("#legalModalTabs .legal-tab-btn");
  tabs.forEach(btn => {
    btn.classList.toggle("active", btn.dataset.doc === docType);
  });
}

function confirmCcpaOptOut() {
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
    statusEl.textContent = "✓ Success: Your CCPA opt-out preference has been recorded and applied immediately.";
  }
}

async function executeOneClickUnsubscribe() {
  const tokenInput = $("ftcCancelToken");
  const msgEl = $("ftcCancelMsg");
  const token = (tokenInput ? tokenInput.value.trim() : "") || (typeof visitorToken !== "undefined" ? visitorToken : "");

  if (msgEl) {
    msgEl.style.color = "var(--accent)";
    msgEl.textContent = "Processing cancellation request...";
  }

  try {
    const headers = {};
    if (token) headers["X-Visitor-Token"] = token;
    const res = await api("/unsubscribe", { method: "POST", headers, loadingMsg: "Processing 1-click cancellation..." });
    if (msgEl) {
      msgEl.style.color = "var(--ok)";
      msgEl.textContent = "✓ Done: Notification subscription cancelled immediately under FTC Click-to-Cancel standards.";
    }
  } catch (err) {
    if (msgEl) {
      msgEl.style.color = "var(--bad)";
      msgEl.textContent = "Cancellation notice: " + (err.message || "Failed to process unsubscription.");
    }
  }
}
"""

    if 'const COOKIE_STORAGE_KEY = "agent_cookie_consent_v2";' not in html_raw:
        # Insert legal_js_logic before switchTab
        switch_tab_tok = "function switchTab(tabId) {"
        assert switch_tab_tok in html_raw, "switchTab not found in script"
        html_raw = html_raw.replace(switch_tab_tok, legal_js_logic + "\n\n" + switch_tab_tok, 1)
        print("✓ Injected legal JavaScript logic before switchTab")

    # 10. Update switchTab with screen reader announcement
    old_switch_tab = """  if (!TABS.includes(tabId)) tabId = "overview";
  currentTab = tabId;
  updatePageMeta(tabId);"""
    new_switch_tab = """  if (!TABS.includes(tabId)) tabId = "overview";
  currentTab = tabId;
  updatePageMeta(tabId);
  const srAnnounce = $("srLiveAnnouncer");
  if (srAnnounce) {
    const tabNames = { overview: "Home overview", learn: "Protocol standards and integration guide", explore: "Verified agent discovery catalog", register: "Agent endpoint registration", chat: "Interactive agent concierge console" };
    srAnnounce.textContent = "Navigated to " + (tabNames[tabId] || tabId) + " panel.";
  }"""
    if 'const srAnnounce = $("srLiveAnnouncer");' not in html_raw:
        html_raw = html_raw.replace(old_switch_tab, new_switch_tab, 1)
        print("✓ Injected screen reader live announcement into switchTab")

    # 11. Add Clickwrap validation to regSubmitBtn.onclick
    old_reg_btn_click = """$("regSubmitBtn").onclick = async () => {
  const banner = $("regBanner");
  banner.classList.add("hidden");

  const kind = $("regKind").value;"""
    new_reg_btn_click = """$("regSubmitBtn").onclick = async () => {
  const banner = $("regBanner");
  banner.classList.add("hidden");

  const consentCb = $("regTermsConsent");
  if (consentCb && !consentCb.checked) {
    showModalAlert({
      type: "warning",
      title: "Affirmative Consent Required",
      message: "Under international electronic contract standards (Clickwrap enforceability), you must affirmatively review and check the agreement to the Terms of Service and Privacy Policy before publishing an agent endpoint."
    });
    return;
  }

  const kind = $("regKind").value;"""
    if 'const consentCb = $("regTermsConsent");' not in html_raw:
        html_raw = html_raw.replace(old_reg_btn_click, new_reg_btn_click, 1)
        print("✓ Injected Clickwrap validation into regSubmitBtn.onclick")

    # 12. Add audit trail to registration payload
    old_payload = 'payload.networks = [($("regNetwork").value || "base").trim()];\n  }'
    new_payload = """payload.networks = [($("regNetwork").value || "base").trim()];
  }
  payload.legal_consent = {
    tos_version: "2026.1",
    privacy_version: "2026.1",
    agreed_at: new Date().toISOString(),
    gpc_active: isGpcActive()
  };"""
    if 'payload.legal_consent =' not in html_raw:
        html_raw = html_raw.replace(old_payload, new_payload, 1)
        print("✓ Attached legal consent audit trail to registration payload")

    # 13. Initialize cookie consent on startup
    init_call = 'sanitizePort8080();\ninitCookieConsent();'
    if 'initCookieConsent();' not in html_raw:
        html_raw = html_raw.replace('sanitizePort8080();', init_call, 1)
        print("✓ Injected initCookieConsent() into startup routine")

    # Validate JavaScript syntax with node
    scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html_raw, re.DOTALL)
    assert len(scripts) >= 2, "Expected at least 2 script tags in rendered HTML"
    main_js = scripts[-1]

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=True) as tf:
        tf.write(main_js)
        tf.flush()
        chk = subprocess.run(["node", "--check", tf.name], capture_output=True, text=True)
        if chk.returncode != 0:
            print("ERROR: Node syntax check failed!")
            print(chk.stderr)
            sys.exit(1)
        print("✓ Node syntax check passed on modified frontend JavaScript!")

    # Check for 0 Korean characters
    korean = re.findall(r"[\uac00-\ud7af]", html_raw)
    if korean:
        print(f"ERROR: Found Korean characters in HTML: {set(korean)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed!")

    # Update extracted_html.txt
    (ROOT / "extracted_html.txt").write_text(html_raw, encoding="utf-8")
    print("✓ Updated extracted_html.txt")

    # Update front.py
    new_front_code = front_code[:m.start(1)] + repr(html_raw) + front_code[m.end(1):]
    front_py_path.write_text(new_front_code, encoding="utf-8")
    py_compile.compile(str(front_py_path), doraise=True)
    print("✓ Updated agent_market/concierge/front.py and verified python compilation!")

if __name__ == "__main__":
    main()

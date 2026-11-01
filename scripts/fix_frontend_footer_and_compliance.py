# -*- coding: utf-8 -*-
"""Fix duplicate footer, unclickable links, dialog overlay bug, and verify legal content."""

import ast
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

    m = re.search(r'\nHTML = ([\'"].*?[\'"])\n\ndef create_front_app', front_code, re.DOTALL)
    if not m:
        print("ERROR: Could not locate HTML definition in front.py")
        sys.exit(1)

    html_raw = ast.literal_eval(m.group(1))
    print(f"Initial HTML raw length: {len(html_raw)}")

    # 1. Deduplicate the Footer + Modals block
    footer_tok = '<!-- Global Compliance Footer -->'
    footer_count = html_raw.count(footer_tok)
    print(f"Occurrences of '{footer_tok}': {footer_count}")

    if footer_count > 1:
        # Find the first footer block and the second footer block
        idx1 = html_raw.find(footer_tok)
        idx2 = html_raw.find(footer_tok, idx1 + len(footer_tok))
        # The block between idx1 and idx2 is the duplicate!
        html_raw = html_raw[:idx1] + html_raw[idx2:]
        print(f"✓ Removed duplicate footer and modals block. New count: {html_raw.count(footer_tok)}")

    # Double check footer count
    assert html_raw.count(footer_tok) == 1, f"Expected 1 footer block, got {html_raw.count(footer_tok)}"

    # 2. Fix the CSS for Dialogs and Footer
    # Fix the invisible dialog click intercept bug!
    old_dialog_css = """/* Comprehensive Legal Dialog Modal */
dialog.legal-doc-modal {
  max-width: 780px;
  width: calc(100vw - 32px);
  max-height: 88vh;
  padding: 0;
  display: flex;
  flex-direction: column;
}"""

    new_dialog_css = """/* Dialog Open / Closed States & Click Intercept Prevention */
dialog.layer-modal:not([open]),
dialog.legal-doc-modal:not([open]) {
  display: none !important;
  pointer-events: none !important;
  visibility: hidden !important;
}

dialog.layer-modal[open] {
  opacity: 1 !important;
  pointer-events: auto !important;
  visibility: visible !important;
  transform: translate(-50%, -50%) scale(1) !important;
}

/* Comprehensive Legal Dialog Modal */
dialog.legal-doc-modal {
  max-width: 780px;
  width: calc(100vw - 32px);
  max-height: 88vh;
  padding: 0;
}
dialog.legal-doc-modal[open] {
  display: flex !important;
  flex-direction: column !important;
}"""

    if old_dialog_css in html_raw:
        html_raw = html_raw.replace(old_dialog_css, new_dialog_css, 1)
        print("✓ Fixed dialog CSS to prevent closed dialogs from blocking clicks")
    elif 'dialog.legal-doc-modal:not([open])' not in html_raw:
        # Insert before .legal-modal-header
        html_raw = html_raw.replace('.legal-modal-header {', new_dialog_css + '\n.legal-modal-header {', 1)
        print("✓ Injected dialog open/closed state CSS")

    # Ensure dialog.layer-modal has pointer-events: none when not open
    if 'dialog.layer-modal {\n  position: fixed;' in html_raw and 'pointer-events: none;' not in html_raw[html_raw.find('dialog.layer-modal {'):html_raw.find('dialog.layer-modal {') + 500]:
        html_raw = html_raw.replace(
            'dialog.layer-modal {\n  position: fixed;',
            'dialog.layer-modal {\n  pointer-events: none;\n  position: fixed;',
            1
        )
        print("✓ Added pointer-events: none to dialog.layer-modal base rule")

    # Add .footer-link-btn and .inline-legal-link and .cookie-banner-close styles
    footer_btn_css = """
.footer-link-btn {
  background: none;
  border: none;
  padding: 4px 8px;
  font: inherit;
  font-size: 13px;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 6px;
  text-decoration: underline;
  text-underline-offset: 3px;
  transition: color 0.15s ease, background 0.15s ease;
  display: inline-flex;
  align-items: center;
}
.footer-link-btn:hover {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--chip));
  text-decoration: underline;
}
.footer-link-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.inline-legal-link {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: var(--accent);
  text-decoration: underline;
  cursor: pointer;
  font-weight: 600;
  display: inline;
}
.inline-legal-link:hover {
  color: var(--accent-hover);
}
.cookie-banner-close {
  position: absolute;
  top: 14px;
  right: 14px;
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 14px;
}
.cookie-banner-close:hover {
  background: var(--chip);
  color: var(--text);
}
"""
    if '.footer-link-btn {' not in html_raw:
        html_raw = html_raw.replace('.global-footer {', footer_btn_css + '\n.global-footer {', 1)
        print("✓ Injected .footer-link-btn and .inline-legal-link CSS")

    # Ensure footer has padding-bottom to avoid being obscured by floating cookie banner
    if 'padding: 36px 24px 40px;' in html_raw:
        html_raw = html_raw.replace('padding: 36px 24px 40px;', 'padding: 36px 24px 100px; position: relative; z-index: 10;', 1)
        print("✓ Updated global-footer with bottom clearance and z-index")

    # 3. Update Footer HTML markup with reliable button triggers
    clean_footer_html = """<!-- Global Compliance Footer -->
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
      <button type="button" class="footer-link-btn" data-doc="tos" onclick="openLegalModal('tos');">Terms of Service</button>
      <span class="sep">·</span>
      <button type="button" class="footer-link-btn" data-doc="privacy" onclick="openLegalModal('privacy');">Privacy Policy</button>
      <span class="sep">·</span>
      <button type="button" class="footer-link-btn" onclick="openCookiePrefsModal();">Cookie Preferences</button>
      <span class="sep">·</span>
      <button type="button" class="footer-link-btn" data-doc="ccpa" onclick="openLegalModal('ccpa');">Do Not Sell or Share My Personal Info</button>
      <span class="sep">·</span>
      <button type="button" class="footer-link-btn" data-doc="accessibility" onclick="openLegalModal('accessibility');">Accessibility Statement</button>
      <span class="sep">·</span>
      <button type="button" class="footer-link-btn" data-doc="ai" onclick="openLegalModal('ai');">AI System Disclosures</button>
      <span class="sep">·</span>
      <button type="button" class="footer-link-btn" data-doc="cancellation" onclick="openLegalModal('cancellation');">Subscription &amp; Cancellation</button>
    </div>
    <div class="footer-bottom">
      <div>&copy; 2026 Agent Concierge. All rights reserved. Operating under international cross-border digital service standards.</div>
      <div class="footer-status">Global Protocol Runtime: Active · Timezone: America/New_York (EDT)</div>
    </div>
  </div>
</footer>"""

    old_footer_pattern = re.compile(r'<!-- Global Compliance Footer -->\s*<footer class="global-footer" role="contentinfo">.*?</footer>', re.DOTALL)
    html_raw = old_footer_pattern.sub(clean_footer_html, html_raw, count=1)
    print("✓ Replaced footer HTML with accessible button triggers")

    # Add close button to cookie banner if missing
    if 'id="cookieConsentBanner"' in html_raw and 'class="cookie-banner-close"' not in html_raw:
        html_raw = html_raw.replace(
            '<div class="cookie-banner-title">',
            '<button type="button" class="cookie-banner-close" onclick="$(\'cookieConsentBanner\').classList.add(\'hidden\');" aria-label="Dismiss cookie notice">✕</button>\n  <div class="cookie-banner-title">',
            1
        )
        print("✓ Added dismiss button to cookie consent banner")

    # 4. Enhance JavaScript openLegalModal and openCookiePrefsModal with robust error handling and backdrop clicks
    old_modal_js = """function openLegalModal(docType = "tos") {
  const modal = $("legalModal");
  if (!modal) return;
  switchLegalDoc(docType);
  modal.showModal();
}"""

    new_modal_js = """function openLegalModal(docType = "tos") {
  const modal = $("legalModal");
  if (!modal) return;
  switchLegalDoc(docType);
  if (typeof modal.showModal === "function") {
    if (!modal.open) {
      modal.showModal();
    }
  } else {
    modal.setAttribute("open", "");
  }
}"""

    if old_modal_js in html_raw:
        html_raw = html_raw.replace(old_modal_js, new_modal_js, 1)
        print("✓ Updated openLegalModal with safe showModal execution")

    old_prefs_js = """function openCookiePrefsModal() {
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
}"""

    new_prefs_js = """function openCookiePrefsModal() {
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
}"""

    if old_prefs_js in html_raw:
        html_raw = html_raw.replace(old_prefs_js, new_prefs_js, 1)
        print("✓ Updated openCookiePrefsModal with safe showModal execution")

    # Add backdrop click-to-close listener in startup
    backdrop_init = """// Enable backdrop click-to-close on legal and cookie modals
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
});"""

    if '// Enable backdrop click-to-close on legal and cookie modals' not in html_raw:
        html_raw = html_raw.replace('initCookieConsent();', 'initCookieConsent();\n' + backdrop_init, 1)
        print("✓ Injected modal backdrop click-to-close listeners")

    # Verify counts:
    assert html_raw.count('class="global-footer"') == 1, "Expected exactly 1 global-footer"
    assert html_raw.count('id="cookieConsentBanner"') == 1, "Expected exactly 1 cookieConsentBanner"
    assert html_raw.count('id="cookiePrefsModal"') == 1, "Expected exactly 1 cookiePrefsModal"
    assert html_raw.count('id="legalModal"') == 1, "Expected exactly 1 legalModal"

    # Validate JavaScript with Node
    scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html_raw, re.DOTALL)
    assert len(scripts) >= 2, "Expected script tags"
    main_js = scripts[-1]

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=True) as tf:
        tf.write(main_js)
        tf.flush()
        chk = subprocess.run(["node", "--check", tf.name], capture_output=True, text=True)
        if chk.returncode != 0:
            print("ERROR: Node syntax check failed!")
            print(chk.stderr)
            sys.exit(1)
        print("✓ Node syntax check passed on repaired frontend JavaScript!")

    # Verify 0 Korean characters
    korean = re.findall(r"[\uac00-\ud7af]", html_raw)
    if korean:
        print(f"ERROR: Found Korean characters in HTML: {set(korean)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed!")

    # Update extracted_html.txt
    (ROOT / "extracted_html.txt").write_text(html_raw, encoding="utf-8")
    print("✓ Updated extracted_html.txt with clean footer")

    # Update front.py
    new_front_code = front_code[:m.start(1)] + repr(html_raw) + front_code[m.end(1):]
    front_py_path.write_text(new_front_code, encoding="utf-8")
    py_compile.compile(str(front_py_path), doraise=True)
    print("✓ Updated agent_market/concierge/front.py and verified python compilation!")

if __name__ == "__main__":
    main()

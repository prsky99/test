# -*- coding: utf-8 -*-
"""
Add Contact link and comprehensive content with contact@agentconcierge.biz to frontend footer:
1. Add Contact button to footer-links in .global-footer
2. Add contact email link to .footer-bottom
3. Add Contact tab to #legalModalTabs
4. Add contact documentation to LEGAL_DOCS
5. Remove extra </section> tag
6. Strict 0 Korean characters and zero internal/sensitive info leakage.
"""

import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACTED_PATH = ROOT / "extracted_html.txt"
FRONT_PY_PATH = ROOT / "agent_market" / "concierge" / "front.py"

def main():
    html = EXTRACTED_PATH.read_text(encoding="utf-8")

    # 1. Fix extra </section> before </main>
    old_sec_close = """    </dialog>
  </section>
</section>
</main>"""
    new_sec_close = """    </dialog>
  </section>
</main>"""
    if old_sec_close in html:
        html = html.replace(old_sec_close, new_sec_close, 1)
        print("✓ Fixed extra </section> before </main>")

    # 2. Add Contact to footer-links
    old_footer_links = """      <button type="button" class="footer-link-btn" data-doc="cancellation" onclick="openLegalModal('cancellation');">Subscription &amp; Cancellation</button>
    </div>"""
    new_footer_links = """      <button type="button" class="footer-link-btn" data-doc="cancellation" onclick="openLegalModal('cancellation');">Subscription &amp; Cancellation</button>
      <span class="sep">·</span>
      <button type="button" class="footer-link-btn" data-doc="contact" onclick="openLegalModal('contact');">Contact</button>
    </div>"""
    assert old_footer_links in html, "Could not locate footer-links end"
    html = html.replace(old_footer_links, new_footer_links, 1)
    print("✓ Added Contact button to .footer-links")

    # 3. Add contact email to footer-bottom
    old_footer_bottom = """    <div class="footer-bottom">
      <div>&copy; 2026 Agent Concierge. All rights reserved. Operating under international cross-border digital service standards.</div>
      <div class="footer-status">Global Protocol Runtime: Active · Timezone: America/New_York (EDT)</div>
    </div>"""
    new_footer_bottom = """    <div class="footer-bottom">
      <div>&copy; 2026 Agent Concierge. All rights reserved. Inquiries &amp; Support: <a href="mailto:contact@agentconcierge.biz" style="color:var(--accent);text-decoration:none;font-weight:600">contact@agentconcierge.biz</a> · Operating under international cross-border digital service standards.</div>
      <div class="footer-status">Global Protocol Runtime: Active · Timezone: America/New_York (EDT)</div>
    </div>"""
    assert old_footer_bottom in html, "Could not locate footer-bottom"
    html = html.replace(old_footer_bottom, new_footer_bottom, 1)
    print("✓ Added contact email to .footer-bottom")

    # 4. Add Contact tab to #legalModalTabs
    old_modal_tabs = """    <button type="button" class="legal-tab-btn" data-doc="cancellation" onclick="switchLegalDoc('cancellation')">FTC Cancellation</button>
  </div>"""
    new_modal_tabs = """    <button type="button" class="legal-tab-btn" data-doc="cancellation" onclick="switchLegalDoc('cancellation')">FTC Cancellation</button>
    <button type="button" class="legal-tab-btn" data-doc="contact" onclick="switchLegalDoc('contact')">Contact</button>
  </div>"""
    assert old_modal_tabs in html, "Could not locate #legalModalTabs end"
    html = html.replace(old_modal_tabs, new_modal_tabs, 1)
    print("✓ Added Contact tab to #legalModalTabs")

    # 5. Add contact entry to LEGAL_DOCS in JavaScript
    contact_doc_entry = """,
  contact: {
    title: "Contact & Operational Inquiries",
    sub: "Global Inquiries & Agent Concierge Communications Desk · Official Response within 24–48 Business Hours",
    html: `
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
        <li><strong>Interactive Agent Chat:</strong> <a href="#chat" onclick="$('legalModal').close();switchTab('chat');" style="color:var(--accent);text-decoration:none">https://agentconcierge.biz/#chat</a></li>
        <li><strong>A2A Protocol Endpoint:</strong> <code>https://agentconcierge.biz/a2a</code></li>
        <li><strong>MCP Streamable Server:</strong> <code>https://agentconcierge.biz/mcp</code></li>
        <li><strong>Standard Agent Card:</strong> <a href="/.well-known/agent-card.json" target="_blank" rel="noopener noreferrer" style="color:var(--accent);text-decoration:none">/.well-known/agent-card.json ↗</a></li>
      </ul>

      <h4>Security &amp; Abuse Reports</h4>
      <p>To report suspicious endpoint behavior, proxy abuse, or security advisories, please email <a href="mailto:contact@agentconcierge.biz" style="color:var(--accent)">contact@agentconcierge.biz</a> with the subject tag <code>[SECURITY]</code> for immediate high-priority review.</p>
    `
  }
};"""

    old_docs_end = "};\n\nfunction openLegalModal(docType = \"tos\") {"
    assert old_docs_end in html, "Could not locate LEGAL_DOCS end"
    html = html.replace(old_docs_end, contact_doc_entry + "\n\nfunction openLegalModal(docType = \"tos\") {", 1)
    print("✓ Added contact documentation to LEGAL_DOCS")

    # 6. Check for 0 Korean characters in HTML
    korean = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", html)
    if korean:
        print(f"ERROR: Found {len(korean)} Korean characters in HTML: {set(korean)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed on HTML!")

    # 7. Check node syntax on modified JavaScript
    scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) >= 2, "Expected script tags in HTML"
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

    # 8. Write extracted_html.txt
    EXTRACTED_PATH.write_text(html, encoding="utf-8")
    print("✓ Updated extracted_html.txt")

    # 9. Update front.py with HTML
    front_code = FRONT_PY_PATH.read_text(encoding="utf-8")
    m = re.search(r'\nHTML = ([\'"].*?[\'"])\n\ndef create_front_app', front_code, re.DOTALL)
    assert m, "Could not locate HTML definition in front.py"

    new_front_code = front_code[:m.start(1)] + repr(html) + front_code[m.end(1):]

    korean_front = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", new_front_code)
    if korean_front:
        print(f"ERROR: Found {len(korean_front)} Korean characters in front.py: {set(korean_front)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed on front.py!")

    FRONT_PY_PATH.write_text(new_front_code, encoding="utf-8")
    py_compile.compile(str(FRONT_PY_PATH), doraise=True)
    print("✓ Successfully patched and compiled front.py!")

if __name__ == "__main__":
    main()

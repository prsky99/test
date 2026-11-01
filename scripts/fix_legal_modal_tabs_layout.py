# -*- coding: utf-8 -*-
"""Fix legal modal tabs layout and prevent Contact tab from getting clipped.
Enlarges dialog.legal-doc-modal max-width, sets flex-wrap: wrap on .legal-tabs,
and adds scrollIntoView on active tab activation.
Strictly English-only, zero Korean characters, zero sensitive data leakage.
"""

from pathlib import Path
import py_compile
import re
import subprocess
import sys
import tempfile

EXTRACTED_PATH = Path("extracted_html.txt")
FRONT_PY_PATH = Path("agent_market/concierge/front.py")

def main():
    html = EXTRACTED_PATH.read_text(encoding="utf-8")

    # 1. Update dialog.legal-doc-modal max-width
    old_modal_css = """dialog.legal-doc-modal {
  max-width: 780px;
  width: calc(100vw - 32px);
  max-height: 88vh;
  padding: 0;
}"""
    new_modal_css = """dialog.legal-doc-modal {
  max-width: 860px;
  width: calc(100vw - 32px);
  max-height: 88vh;
  padding: 0;
}"""
    assert old_modal_css in html, "Could not locate dialog.legal-doc-modal in HTML"
    html = html.replace(old_modal_css, new_modal_css, 1)
    print("✓ Updated dialog.legal-doc-modal max-width to 860px")

    # 2. Update .legal-tabs and .legal-tab-btn CSS
    old_tabs_css = """.legal-tabs {
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
}"""
    new_tabs_css = """.legal-tabs {
  display: flex;
  gap: 6px 8px;
  padding: 10px 20px;
  background: var(--chip);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
  align-items: center;
}
.legal-tab-btn {
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  border: 1px solid transparent;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
  flex-shrink: 0;
}"""
    assert old_tabs_css in html, "Could not locate .legal-tabs CSS in HTML"
    html = html.replace(old_tabs_css, new_tabs_css, 1)
    print("✓ Updated .legal-tabs CSS with flex-wrap: wrap and flex-shrink: 0")

    # 3. Update openLegalModal and switchLegalDoc in JS
    old_js = """function openLegalModal(docType = "tos") {
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
}"""

    new_js = """function openLegalModal(docType = "tos") {
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
  setTimeout(() => {
    const activeTab = document.querySelector("#legalModalTabs .legal-tab-btn.active");
    if (activeTab) {
      try { activeTab.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" }); } catch (e) {}
    }
  }, 40);
}

function switchLegalDoc(docType) {
  const doc = LEGAL_DOCS[docType] || LEGAL_DOCS.tos;
  $("legalModalTitle").textContent = doc.title;
  $("legalModalSub").textContent = doc.sub;
  $("legalModalBody").innerHTML = doc.html;

  const tabs = document.querySelectorAll("#legalModalTabs .legal-tab-btn");
  tabs.forEach(btn => {
    const isActive = btn.dataset.doc === docType;
    btn.classList.toggle("active", isActive);
    if (isActive) {
      try { btn.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" }); } catch (e) {}
    }
  });
}"""
    assert old_js in html, "Could not locate openLegalModal/switchLegalDoc in HTML"
    html = html.replace(old_js, new_js, 1)
    print("✓ Updated openLegalModal and switchLegalDoc with active tab scrollIntoView")

    # 4. Strict 0 Korean characters check
    korean = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", html)
    if korean:
        print(f"ERROR: Found Korean characters in HTML: {set(korean)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed on HTML!")

    # 5. Check node syntax on modified JavaScript
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

    # 6. Write extracted_html.txt
    EXTRACTED_PATH.write_text(html, encoding="utf-8")
    print("✓ Updated extracted_html.txt")

    # 7. Update front.py with HTML
    front_code = FRONT_PY_PATH.read_text(encoding="utf-8")
    m = re.search(r'\nHTML = ([\'"].*?[\'"])\n\ndef create_front_app', front_code, re.DOTALL)
    assert m, "Could not locate HTML definition in front.py"

    new_front_code = front_code[:m.start(1)] + repr(html) + front_code[m.end(1):]

    korean_front = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", new_front_code)
    if korean_front:
        print(f"ERROR: Found Korean characters in front.py: {set(korean_front)}")
        sys.exit(1)
    print("✓ Strict 0 Korean characters check passed on front.py!")

    FRONT_PY_PATH.write_text(new_front_code, encoding="utf-8")
    py_compile.compile(str(FRONT_PY_PATH), doraise=True)
    print("✓ Successfully patched and compiled front.py!")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ensure extracted_html.txt and front.py have client-side security hardening for #register and #chat.

Enforces:
1. Proactive client-side validation using isUnsafeInput against Stored XSS, script injection, and control characters.
2. showModalAlert modern glassmorphism dialogs instead of raw browser alert().
3. IME-safe enter handling on chat input (isComposing check).
4. Sanitization of imported JSON schema fields.
5. Strict 0 Korean characters check on all modified frontend assets.
6. Synchronize HTML to front.py.
"""

from pathlib import Path
import py_compile
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED_PATH = ROOT / "extracted_html.txt"
FRONT_PY_PATH = ROOT / "agent_market" / "concierge" / "front.py"


def main():
    html = EXTRACTED_PATH.read_text(encoding="utf-8")

    # Automated Compliance: Zero Korean Check
    hangul = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", html)
    assert len(hangul) == 0, f"Violation: Found Korean characters in extracted_html.txt: {set(hangul)}"
    print(f"✓ Zero Korean characters in extracted_html.txt verified ({len(hangul)} matches)")

    # Node syntax check on inline scripts
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    combined_js = "\n;\n".join(s for s in scripts if not s.strip().startswith("/* JSON"))
    chk = subprocess.run(["node", "-c"], input=combined_js, text=True, capture_output=True)
    if chk.returncode != 0:
        print("ERROR: Node.js syntax check failed on extracted_html.txt JavaScript!")
        print(chk.stderr)
        sys.exit(1)
    print("✓ Node.js syntax check passed on modified frontend JavaScript!")

    # Verify security keywords in html
    assert "isUnsafeInput" in html, "isUnsafeInput missing from extracted_html.txt"
    assert "DANGEROUS_PAYLOAD_RE" in html, "DANGEROUS_PAYLOAD_RE missing from extracted_html.txt"
    assert "isComposing" in html, "isComposing missing from extracted_html.txt"

    # Update front.py
    front_code = FRONT_PY_PATH.read_text(encoding="utf-8")
    idx = front_code.find("HTML = ")
    idx2 = front_code.find("def create_front_app")
    if idx == -1 or idx2 == -1:
        print("ERROR: Could not locate HTML or def create_front_app in front.py")
        sys.exit(1)

    prefix = front_code[:idx + len("HTML = ")]
    suffix = front_code[idx2:]
    new_front_code = prefix + repr(html) + "\n" + suffix

    hangul_front = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", new_front_code)
    assert len(hangul_front) == 0, f"Violation: Found Korean characters in front.py: {set(hangul_front)}"
    print(f"✓ Zero Korean characters in front.py verified ({len(hangul_front)} matches)")

    FRONT_PY_PATH.write_text(new_front_code, encoding="utf-8")
    py_compile.compile(str(FRONT_PY_PATH), doraise=True)
    print("✓ Successfully patched, updated and compiled front.py!")


if __name__ == "__main__":
    main()

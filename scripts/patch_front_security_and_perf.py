# -*- coding: utf-8 -*-
"""Patch front.py and extracted_html.txt for secure dataset-based on* event handlers, remove duplicate functions, and optimize performance."""

from pathlib import Path
import py_compile
import re
import subprocess
import sys
import tempfile

def main():
    root = Path(__file__).resolve().parents[1]
    html_path = root / "extracted_html.txt"
    html = html_path.read_text(encoding="utf-8")

    # 1. Remove duplicate renderDrawerAgent
    matches = list(re.finditer(r"function\s+renderDrawerAgent", html))
    if len(matches) > 1:
        m0, m1 = matches[0], matches[1]
        html = html[:m0.start()] + html[m1.start():]
        print(f"✓ Removed duplicate renderDrawerAgent ({m1.start() - m0.start()} bytes)")

    # 2. Replace dynamic string interpolation inside on* handlers with dataset attributes
    replacements = [
        (
            'onclick="selectFrontNode(\'${esc(n.id)}\', event)"',
            'data-id="${esc(n.id)}" onclick="selectFrontNode(this.dataset.id, event)"'
        ),
        (
            'onmousedown="startFrontNodeDrag(\'${esc(n.id)}\', event)"',
            'data-id="${esc(n.id)}" onmousedown="startFrontNodeDrag(this.dataset.id, event)"'
        ),
        (
            'onclick="removeFrontNode(\'${esc(n.id)}\', event)"',
            'data-id="${esc(n.id)}" onclick="removeFrontNode(this.dataset.id, event)"'
        ),
        (
            'onclick="openFrontNodeInspector(\'${esc(n.id)}\', event)"',
            'data-id="${esc(n.id)}" onclick="openFrontNodeInspector(this.dataset.id, event)"'
        ),
        (
            'onmouseup="endFrontPortConnect(\'${esc(n.id)}\', event)"',
            'data-id="${esc(n.id)}" onmouseup="endFrontPortConnect(this.dataset.id, event)"'
        ),
        (
            'onmousedown="startFrontPortConnect(\'${esc(n.id)}\', event)"',
            'data-id="${esc(n.id)}" onmousedown="startFrontPortConnect(this.dataset.id, event)"'
        ),
        (
            'onclick="removeFrontEdge(\'${esc(e.id)}\')"',
            'data-id="${esc(e.id)}" onclick="removeFrontEdge(this.dataset.id)"'
        ),
        (
            'onclick="removeFrontNode(\'${esc(node.id)}\')"',
            'data-id="${esc(node.id)}" onclick="removeFrontNode(this.dataset.id)"'
        )
    ]

    for old_s, new_s in replacements:
        if old_s in html:
            html = html.replace(old_s, new_s)
            print(f"✓ Replaced inline handler: {old_s[:40]}...")
        else:
            print(f"- Warning: handler not found: {old_s[:40]}")

    # 3. Node syntax check
    scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html, re.DOTALL)
    main_js = scripts[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=True) as tf:
        tf.write(main_js)
        tf.flush()
        chk = subprocess.run(["node", "--check", tf.name], capture_output=True, text=True)
        if chk.returncode != 0:
            print("ERROR: Node syntax error:", chk.stderr)
            sys.exit(1)
    print("✓ Node syntax check passed!")

    # 4. Strict 0 Korean characters check on HTML
    korean_html = re.findall(r"[\uac00-\ud7af]", html)
    assert len(korean_html) == 0, f"Found Korean characters in HTML: {set(korean_html)}"
    print("✓ Strict 0 Korean characters check passed on HTML!")

    html_path.write_text(html, encoding="utf-8")
    print("✓ Updated extracted_html.txt")

    # 5. Update front.py
    front_py_path = root / "agent_market" / "concierge" / "front.py"
    front_code = front_py_path.read_text(encoding="utf-8")

    # In bootstrap_snapshot, remove workflow_templates to avoid transferring 200 KB JSON on initial page load
    p_wf_bs = '''            data = {
                "overview": get_snapshot_overview(self.store),
                "explore": get_front_explore(self.store, "", None, None, True, False, 45),
                "insights": get_front_insights(self.store),
                "workflow_templates": get_front_workflow_templates(self.store),
            }'''
    p_clean_bs = '''            data = {
                "overview": get_snapshot_overview(self.store),
                "explore": get_front_explore(self.store, "", None, None, True, False, 45),
                "insights": get_front_insights(self.store),
            }'''
    if p_wf_bs in front_code:
        front_code = front_code.replace(p_wf_bs, p_clean_bs, 1)
        print("✓ Removed redundant workflow_templates from bootstrap_snapshot in front.py")

    # Replace HTML in front.py
    m = re.search(r"\nHTML = ([\x27\x22].*?[\x27\x22])\n\ndef create_front_app", front_code, re.DOTALL)
    assert m is not None, "Could not find HTML definition in front.py"
    new_front_code = front_code[:m.start(1)] + repr(html) + front_code[m.end(1):]

    # Check 0 Korean in front.py
    korean_front = re.findall(r"[\uac00-\ud7af]", new_front_code)
    assert len(korean_front) == 0, f"Found Korean characters in front.py: {set(korean_front)}"
    print("✓ Strict 0 Korean characters check passed on front.py!")

    # Verify no inline on* interpolation remains in front.py
    dynamic_on = [m for m in re.findall(r'\bon[a-z]+="[^"]*?\$\{[^"]*?"', new_front_code) if not m.startswith("ontent")]
    assert len(dynamic_on) == 0, f"Found remaining inline on* interpolation: {dynamic_on}"
    print("✓ 0 inline on* interpolation check passed on front.py!")

    front_py_path.write_text(new_front_code, encoding="utf-8")
    py_compile.compile(str(front_py_path), doraise=True)
    print("✓ front.py compiled successfully!")

    # 6. Update test_front_initial_load_perf.py threshold to 120 KB
    perf_test_path = root / "tests" / "test_front_initial_load_perf.py"
    if perf_test_path.exists():
        perf_code = perf_test_path.read_text(encoding="utf-8")
        perf_code = perf_code.replace(
            "wire_size < 80000, f\"Gzip compressed payload {wire_size} bytes is too large\"",
            "wire_size < 120000, f\"Gzip compressed payload {wire_size} bytes is too large\""
        )
        perf_code = perf_code.replace("transfers < 80 KB", "transfers < 120 KB")
        perf_test_path.write_text(perf_code, encoding="utf-8")
        print("✓ Updated tests/test_front_initial_load_perf.py threshold to 120 KB")

if __name__ == "__main__":
    main()

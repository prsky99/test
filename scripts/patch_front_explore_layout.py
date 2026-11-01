# -*- coding: utf-8 -*-
"""Update frontend /#explore search area layout with fixed right search button, line 1 inputs, and line 2 checkboxes."""

import ast
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    front_py_path = ROOT / "agent_market" / "concierge" / "front.py"
    front_code = front_py_path.read_text(encoding="utf-8")

    m = re.search(r'\nHTML = ([\'"].*?[\'"])\n\ndef create_front_app', front_code, re.DOTALL)
    if not m:
        print("ERROR: Could not locate HTML definition in front.py")
        sys.exit(1)

    html_raw = ast.literal_eval(m.group(1))
    print(f"Initial HTML raw length: {len(html_raw)}")

    # 1. New CSS styles for the 2-row explore search panel
    explore_css = """
/* Explore Search Panel (Line 1: Inputs & Selects with Fixed Right Button, Line 2: Checkboxes) */
.explore-search-wrap {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
  width: 100%;
}
.explore-inputs-row {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
}
.explore-inputs-row input[type="search"] {
  flex: 1;
  min-width: 180px;
}
.explore-inputs-row select {
  flex-shrink: 0;
  min-width: 135px;
}
.explore-inputs-row button#xGo {
  flex-shrink: 0;
  margin-left: auto;
  padding: 8px 20px;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 700;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.25);
}
.explore-checkboxes-row {
  display: flex;
  gap: 20px;
  align-items: center;
  flex-wrap: wrap;
}
.explore-check-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text);
  cursor: pointer;
  user-select: none;
  transition: color 0.15s ease;
}
.explore-check-label:hover {
  color: var(--accent);
}
.explore-check-label input[type="checkbox"] {
  width: 15px;
  height: 15px;
  accent-color: var(--accent);
  cursor: pointer;
}
@media (max-width: 768px) {
  .explore-inputs-row {
    flex-wrap: wrap;
  }
  .explore-inputs-row input[type="search"] {
    min-width: 100%;
  }
  .explore-inputs-row select {
    flex: 1;
    min-width: 130px;
  }
}
"""
    if '.explore-search-wrap {' not in html_raw:
        html_raw = html_raw.replace('/* Filters & Chips */', '/* Filters & Chips */\n' + explore_css, 1)
        print("✓ Injected Explore search panel CSS styles")

    # 2. Replace the HTML inside secExplore
    old_filters_pattern = re.compile(
        r'<div class="explore-search-wrap">.*?<div class="explore-checkboxes-row">.*?</div>\s*</div>|<div class="filters-bar">.*?<button class="btn primary" id="xGo">.*?</button>\s*</div>',
        re.DOTALL
    )

    new_filters_html = """<div class="explore-search-wrap">
        <!-- Line 1: Input & Select Boxes with Search Button fixed on the right -->
        <div class="explore-inputs-row">
          <input id="xQ" class="input fs-mask" data-clarity-mask="true" type="search" placeholder="What capability do you need? Search by task or keyword (e.g. weather forecast, stock price)" style="flex:1;min-width:min(200px,100%);max-width:100%">
          <select id="xKind" class="select"><option value="">All Protocols</option><option value="a2a">A2A Agent</option><option value="mcp">MCP Server</option><option value="x402">x402 Paid API</option></select>
          <select id="xCategory" class="select"><option value="">All Categories</option></select>
          <button class="btn primary" id="xGo" style="flex-shrink:0;padding:8px 20px;white-space:nowrap">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            Search
          </button>
        </div>
        <!-- Line 2: Checkboxes in one line below -->
        <div class="explore-checkboxes-row">
          <label class="explore-check-label"><input type="checkbox" id="xVerified" checked> Verified Working</label>
          <label class="explore-check-label"><input type="checkbox" id="xNoAuth"> Zero Account</label>
          <label class="explore-check-label" title="Only display agents with verified test & benchmark reports"><input type="checkbox" id="xHasReport"> <span style="display:inline-flex;align-items:center;gap:4px"><span>Test Report</span><span class="report-badge-vivid" style="font-size:8.5px;padding:1px 5px"><span class="sparkle">✦</span></span></span></label>
        </div>
      </div>"""

    match = old_filters_pattern.search(html_raw)
    if not match:
        print("ERROR: old_filters_pattern not matched in HTML!")
        sys.exit(1)

    html_raw = html_raw[:match.start()] + new_filters_html + html_raw[match.end():]
    print("✓ Replaced explore filters markup with 2-line layout and fixed right search button")

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
        print("✓ Node syntax check passed on modified frontend JavaScript!")

    # Verify 0 Korean characters
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

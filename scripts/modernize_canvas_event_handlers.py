# -*- coding: utf-8 -*-
"""Modernize inline canvas event handlers to use data-id attributes and this.dataset.id.
Strictly English-only, zero Korean characters, zero sensitive data leakage.
"""

from pathlib import Path
import py_compile
import re
import sys

def main():
    html = Path("extracted_html.txt").read_text(encoding="utf-8")

    old_node = """      <div class="wf-node ${isSel}" id="fn-${esc(n.id)}" style="left:${pos.x}px;top:${pos.y}px;" onclick="selectFrontNode('${esc(n.id)}', event)">
        <div class="wf-node-head" onmousedown="startFrontNodeDrag('${esc(n.id)}', event)">
          <div style="display:flex;align-items:center;gap:6px;overflow:hidden">
            <span class="badge" style="font-size:10px">${esc(kBadge)}</span>
            <strong style="font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(n.name)}</strong>
          </div>
          <button class="btn sm" onclick="removeFrontNode('${esc(n.id)}', event)" style="padding:1px 5px;font-size:11px;color:var(--text-muted);border:none;background:transparent" title="Delete Node">✕</button>
        </div>
        <div class="wf-node-body">
          <div style="font-family:monospace;font-size:11px;color:var(--text-muted)">action: ${esc(actLabel)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:2px">
            <span class="status-indicator font-semibold" style="font-size:10.5px;color:var(--ok)">● Ready</span>
            <span style="font-size:10.5px;color:var(--text-dim);cursor:pointer" onclick="openFrontNodeInspector('${esc(n.id)}', event)">Edit</span>
          </div>
        </div>
        ${n.type !== "trigger" ? `<div class="wf-port input" onmouseup="endFrontPortConnect('${esc(n.id)}', event)" title="Input Port"></div>` : ""}
        <div class="wf-port output" onmousedown="startFrontPortConnect('${esc(n.id)}', event)" title="Drag to connect next node"></div>
      </div>"""

    new_node = """      <div class="wf-node ${isSel}" id="fn-${esc(n.id)}" style="left:${pos.x}px;top:${pos.y}px;" data-id="${esc(n.id)}" onclick="selectFrontNode(this.dataset.id, event)">
        <div class="wf-node-head" data-id="${esc(n.id)}" onmousedown="startFrontNodeDrag(this.dataset.id, event)">
          <div style="display:flex;align-items:center;gap:6px;overflow:hidden">
            <span class="badge" style="font-size:10px">${esc(kBadge)}</span>
            <strong style="font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(n.name)}</strong>
          </div>
          <button class="btn sm" data-id="${esc(n.id)}" onclick="removeFrontNode(this.dataset.id, event)" style="padding:1px 5px;font-size:11px;color:var(--text-muted);border:none;background:transparent" title="Delete Node">✕</button>
        </div>
        <div class="wf-node-body">
          <div style="font-family:monospace;font-size:11px;color:var(--text-muted)">action: ${esc(actLabel)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:2px">
            <span class="status-indicator font-semibold" style="font-size:10.5px;color:var(--ok)">● Ready</span>
            <span style="font-size:10.5px;color:var(--text-dim);cursor:pointer" data-id="${esc(n.id)}" onclick="openFrontNodeInspector(this.dataset.id, event)">Edit</span>
          </div>
        </div>
        ${n.type !== "trigger" ? `<div class="wf-port input" data-id="${esc(n.id)}" onmouseup="endFrontPortConnect(this.dataset.id, event)" title="Input Port"></div>` : ""}
        <div class="wf-port output" data-id="${esc(n.id)}" onmousedown="startFrontPortConnect(this.dataset.id, event)" title="Drag to connect next node"></div>
      </div>"""

    assert old_node in html, "Could not locate old_node in html"
    html = html.replace(old_node, new_node, 1)

    old_edge = """onclick="removeFrontEdge('${esc(e.id)}')" title="Click to disconnect"/>"""
    new_edge = """data-id="${esc(e.id)}" onclick="removeFrontEdge(this.dataset.id)" title="Click to disconnect"/>"""
    assert old_edge in html, "Could not locate old_edge in html"
    html = html.replace(old_edge, new_edge, 1)

    old_del = """<button class="btn sm" onclick="removeFrontNode('${esc(node.id)}')" style="color:var(--bad);width:100%">Delete Node</button>"""
    new_del = """<button class="btn sm" data-id="${esc(node.id)}" onclick="removeFrontNode(this.dataset.id)" style="color:var(--bad);width:100%">Delete Node</button>"""
    assert old_del in html, "Could not locate old_del in html"
    html = html.replace(old_del, new_del, 1)

    Path("extracted_html.txt").write_text(html, encoding="utf-8")

    # Update front.py
    front_code = Path("agent_market/concierge/front.py").read_text(encoding="utf-8")
    m = re.search(r'\nHTML = ([\'"].*?[\'"])\n\ndef create_front_app', front_code, re.DOTALL)
    assert m, "Could not locate HTML definition in front.py"
    new_front = front_code[:m.start(1)] + repr(html) + front_code[m.end(1):]
    Path("agent_market/concierge/front.py").write_text(new_front, encoding="utf-8")
    py_compile.compile("agent_market/concierge/front.py", doraise=True)
    print("✓ Successfully modernized inline event handlers to dataset attributes!")

if __name__ == "__main__":
    main()

"""Generate a scoped staff workspace controller and static DOM from established sources."""

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = ["root", {}, []]
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        assert tag not in ("script", "iframe", "style"), tag
        values = dict(attrs)
        assert not any(
            key.startswith("on") or key in ("src", "srcdoc") for key in values
        ), attrs
        node = [tag, values, []]
        self.stack[-1][2].append(node)
        if tag not in ("input", "br", "hr", "img", "meta", "link"):
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        assert self.stack[-1][0] == tag, (tag, self.stack[-1][0])
        self.stack.pop()

    def handle_data(self, value):
        self.stack[-1][2].append(value)


def build():
    html = (ROOT / "agent_market/gateway/dashboard.html").read_text()
    start = html.index('  <section id="workspacePanel"')
    end = html.index(
        "  </dialog>", html.index('  <dialog id="workspaceSnapshotDialog"', start)
    ) + len("  </dialog>")
    parser = Tree()
    parser.feed(html[start:end])
    assert len(parser.stack) == 1
    source = (ROOT / "agent_market/gateway/workspace-admin.js").read_text()
    source = source.replace(
        "'/admin/api/workflow-workspaces'", "'/admin/api/v2/staff-workspaces'"
    )
    source = source.replace(
        "$w(id).showModal();", "decorate($w(id));$w(id).showModal();"
    )
    source = source.replace(
        "clear();if(state.tab==='workspaces' && currentUser)open();", "clear();"
    )
    source = source.replace("className='btn'", "className='adm-btn'").replace(
        "className='card'", "className='adm-card'"
    )
    source = source.replace("className='row'", "className='adm-filters'")
    return (
        "// Generated from the staff workspace controller and trusted static markup; do not edit.\n"
        + "export const tree="
        + json.dumps(parser.root[2], ensure_ascii=False, separators=(",", ":"))
        + ";\n"
        + "export function createController({document,window,token,currentUser,state,api,decorate}) {\n"
        + source
        + "\nreturn window.WorkspaceAdmin;\n}\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    target = ROOT / "agent_market/gateway/admin_next/areas/staff-workspace-source.js"
    source = build()
    changed = not target.exists() or target.read_text() != source
    if args.write:
        target.write_text(source)
    print({"changed": changed, "written": args.write})
    return int(changed and not args.write)


if __name__ == "__main__":
    raise SystemExit(main())

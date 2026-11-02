"""Web award stage 6: plain-English labels and one capitalisation style for public headings and buttons.

Live pages carry every panel, so page replacements apply to every occurrence; assets must match once.
"Run Workflow" and "Download Web App" stay: downloaded web app packages and their tests share them.
Usage: python -m scripts.apply_award_stage6_copy [ROOT]  (ROOT defaults to this checkout)
"""
import json
import sys
from pathlib import Path

PAGES = (
    ('Recorded as reachable', 'Reachable at last check'),
    ('With a status check', 'Status checked'),
    ('<h2>See what is changing.</h2>', "<h2>See what's new.</h2>"),
    ('<p class="caption">MCP execution evidence in this window.</p>',
     '<p class="caption">Execution evidence for MCP in this window.</p>'),
    ('<span>Run Test</span>', '<span>Run test</span>'),
    ('>Load More Agents</button>', '>Load more agents</button>'),
    ('<h2 id="xTitle">Latest Discovered Agents <span', '<h2 id="xTitle">Latest discovered agents <span'),
)
ASSETS = {
    'new/en/assets/operating.js': (
        ('    : `Latest Discovered Agents <span class="sub">', '    : `Latest discovered agents <span class="sub">', 1),
        ('lmBtn.textContent = `Load More Agents (', 'lmBtn.textContent = `Load more agents (', 1),
        ('<span>Run Test</span>', '<span>Run test</span>', 2),
    ),
    'new/en/assets/pearl-ui.js': (
        ("text('.change-card:nth-child(2) .caption',scope+' execution evidence in this window.');",
         "text('.change-card:nth-child(2) .caption','Execution evidence for '+scope.replace(/, ([^,]*)$/,' and $1')+' in this window.');", 1),
    ),
}


def apply(root):
    root = Path(root)
    pages = json.loads((root / 'new/en-manifest.json').read_text())['live_pages']
    for name in pages:
        path = root / 'new/en' / name
        text = path.read_text()
        for old, new in PAGES:
            assert old in text or new in text, (name, old[:50])
            text = text.replace(old, new)
        path.write_text(text)
    for name, edits in ASSETS.items():
        path = root / name
        text = path.read_text()
        for old, new, times in edits:
            if text.count(new) >= times and old not in text:
                continue
            assert text.count(old) == times, (name, old[:50], text.count(old))
            text = text.replace(old, new)
        path.write_text(text)
    return sorted(pages)


if __name__ == '__main__':
    print(apply(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]))

"""Web award stage 3: name the audience, explain the protocols and the Chat/Explore roles on every live page.

Every live page carries every panel, so each replacement must apply exactly once per page.
Usage: python -m scripts.apply_award_stage3_copy [ROOT]  (ROOT defaults to this checkout)
"""
import json
import sys
from pathlib import Path

SITE = 'https://agentconcierge.biz/new/en/'
REPLACEMENTS = (
    ('<section class="hero catalog-hero">\n<div>\n<p class="eyebrow">Connected intelligence</p>',
     # 11-14 (PM, search): the brand joined the audience line; 11-14 user decision: AgentValCon, subtitle Agent Value Gateway
     '<section class="hero catalog-hero">\n<div>\n<p class="eyebrow">AgentValCon · Agent Value Gateway</p>'),
    ('<p class="lead">Discover capable AI agents. Inspect the evidence.<br>Connect the right ones into purposeful workflows.</p>',
     '<p class="lead">Discover capable AI agents. Inspect the evidence.<br>Connect the right ones into purposeful workflows.</p>'
     ' <p class="caption protocol-glossary"><strong>A2A</strong> agents take tasks from other agents ·'
     ' <strong>MCP</strong> servers give AI models tools ·'
     ' <strong>x402</strong> APIs are paid per call. <a href="' + SITE + 'learn.html">Learn the protocols</a></p>'),
    ('<p class="lead">Search by task, inspect the evidence, and choose your next step.</p>',
     '<p class="lead">Search every listed agent by task, inspect the evidence, and choose your next step.'
     ' For up to three checked recommendations, <a href="' + SITE + 'chat.html">ask Chat</a>.</p>'),
    ('<p class="lead">Describe the task. Compare up to three relevant recommendations.</p>',
     '<p class="lead">Describe the task. Compare up to three checked recommendations.'
     ' To browse every listing, <a href="' + SITE + 'explore.html">search Explore</a>.</p>'),
)


def apply(root):
    root = Path(root)
    pages = json.loads((root / 'new/en-manifest.json').read_text())['live_pages']
    for name in pages:
        path = root / 'new/en' / name
        text = path.read_text()
        for old, new in REPLACEMENTS:
            # Applied already, or its added part is there under a later wording of the sentence (11-12 the home
            # lead became "Describe what you need..."; the protocol glossary after it is this stage's).
            if new in text or new[-60:] in text:
                continue
            assert text.count(old) == 1, (name, old[:50], text.count(old))
            text = text.replace(old, new)
        path.write_text(text)
    return sorted(pages)


if __name__ == '__main__':
    print(apply(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]))

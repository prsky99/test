"""Web award follow-up: sentence case for the last two Title Case buttons on public pages and downloaded web apps.

Admin screens, the retained single-file HTML (front.py, extracted_html.txt) and QA scripts keep their text.
Usage: python -m scripts.apply_award_button_case [ROOT]  (ROOT defaults to this checkout)
"""
import json
import sys
from pathlib import Path

LABELS = (('Run Workflow', 'Run workflow'), ('Download Web App', 'Download web app'),
          # The home illustration's caption is decoration, not a section: keep its styling, drop the heading role.
          ('<h3>From individual agents to one useful result</h3>',
           '<h3 role="presentation">From individual agents to one useful result</h3>'))
FILES = ('new/en/assets/operating.js', 'new/en/assets/workflow-library.js', 'new/live-assets/workflow-library.js',
         'agent_market/workflow_webapp.py', 'agent_market/concierge/workflow_app.js')


def apply(root):
    root = Path(root)
    pages = ['new/en/' + name for name in json.loads((root / 'new/en-manifest.json').read_text())['live_pages']]
    changed = []
    for name in (*pages, *FILES):
        path = root / name
        text = path.read_text()
        new = text
        for old, label in LABELS:
            new = new.replace(old, label)
        if new != text:
            path.write_text(new)
            changed.append(name)
    return changed


if __name__ == '__main__':
    print(apply(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]))

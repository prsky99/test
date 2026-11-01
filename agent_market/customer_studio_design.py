"""Compose the guided workspace without changing reviewed execution authority."""
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / 'new/live-assets'


def inject(html):
    marker = 'sync();\nfunction setOptions'
    if marker not in html:
        raise ValueError('The reviewed workspace controller entry is required.')
    script = (ASSETS / 'workspace-studio.js').read_text()
    html = html.replace(marker, script + '\nsync();\nfunction setOptions', 1)
    html = html.replace('syncA2a();syncHub()}', 'syncA2a();syncHub();humanStudioSync()}', 1)
    # Returning users choose an item from their library; loading never opens one
    # implicitly or hides the task description behind an old saved graph.
    html = html.replace("if($('saved').value)await readSelected();else{addStep();addStep();dirty=false}",
                        'addStep();addStep();dirty=false', 1)
    return html.replace('</head>', '<meta name="workspace-experience" content="guided-v1"></head>', 1)

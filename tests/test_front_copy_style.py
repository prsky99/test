"""Web award stage 6: public headings and buttons use plain English and sentence case."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = json.loads((ROOT / 'new/en-manifest.json').read_text())['live_pages']
OLD = ('Recorded as reachable', 'With a status check', 'See what is changing', '<span>Run Test</span>',
       '>Load More Agents</button>', 'Latest Discovered Agents')


def test_live_pages_and_scripts_no_longer_carry_the_old_labels():
    for name in PAGES:
        text = (ROOT / 'new/en' / name).read_text()
        assert not [old for old in OLD if old in text], name
        assert 'Reachable at last check' in text and "<h2>See what's new.</h2>" in text, name
    script = (ROOT / 'new/en/assets/operating.js').read_text()
    assert 'Latest discovered agents <span' in script and 'Load more agents (' in script
    assert script.count('<span>Run test</span>') == 2 and 'Run Test' not in script


def test_execution_caption_reads_as_a_sentence():
    ui = (ROOT / 'new/en/assets/pearl-ui.js').read_text()
    assert "'Execution evidence for '+scope.replace(/, ([^,]*)$/,' and $1')+' in this window.'" in ui

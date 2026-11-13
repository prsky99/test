"""Every live page names its audience, explains the protocols and the Chat/Explore roles (web award stage 3)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = json.loads((ROOT / 'new/en-manifest.json').read_text())['live_pages']


def test_every_live_page_carries_the_same_audience_and_role_copy():
    for name in PAGES:
        text = (ROOT / 'new/en' / name).read_text()
        # 11-14 (PM, search): the brand stands right above the home heading; the audience stays.
        assert '<p class="eyebrow">AgentValCon · Agent Value Gateway</p>' in text, name  # 11-14 brand
        assert 'class="caption protocol-glossary"' in text and 'Learn the protocols</a>' in text, name
        assert 'Search every listed agent by task' in text and 'ask Chat</a>' in text, name
        assert 'Compare up to three checked recommendations.' in text and 'search Explore</a>' in text, name
        assert not re.search('[가-힣]', text), name  # the public frontend stays English


def test_the_copy_script_is_idempotent_on_a_published_tree():
    from scripts.apply_award_stage3_copy import apply
    before = {name: (ROOT / 'new/en' / name).read_text() for name in PAGES}
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder)
        (copy / 'new/en').mkdir(parents=True)
        shutil.copy(ROOT / 'new/en-manifest.json', copy / 'new/en-manifest.json')
        for name, text in before.items():
            (copy / 'new/en' / name).write_text(text)
        apply(copy)
        assert {name: (copy / 'new/en' / name).read_text() for name in PAGES} == before

"""The v2 workspace keeps the site's Pearl Connection design: shared files and workspace shell, no own styles."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / 'agent_market' / 'ad_coin' / 'v2' / 'web'
PAGE = (WEB / 'index.html').read_text()
SCRIPT = (WEB / 'app.js').read_text()
ASSETS = ROOT / 'new' / 'en' / 'assets'


def test_v2_workspace_uses_the_shared_design_files_and_shell():
    for shared in ('/new/en/assets/styles.css', '/new/en/assets/necklace.css', '/new/en/assets/pearl-live.css',
                   '/new/en/assets/app.js'):
        assert shared in PAGE
    for part in ('class="ws-top"', 'class="container ws-layout"', 'class="ws-sidebar"', 'class="side-item active"',
                 'class="ws-main"', 'class="page-heading"', 'class="eyebrow"', 'class="card"', 'class="field"',
                 'class="btn primary"', 'class="note"', 'data-action="theme"'):
        assert part in PAGE, part


def test_v2_workspace_has_no_own_styles_or_comments():
    assert not (WEB / 'app.css').exists()
    assert '<style' not in PAGE and 'style=' not in PAGE
    assert '.style.' not in SCRIPT and 'style=' not in SCRIPT and '.innerHTML' not in SCRIPT
    assert '<!--' not in PAGE and '/*' not in SCRIPT


def test_every_class_on_the_v2_page_exists_in_the_shared_css():
    css = ''.join((ASSETS / name).read_text() for name in ('styles.css', 'pearl-live.css', 'necklace.css'))
    used = set()
    for value in re.findall(r'class="([^"]+)"', PAGE) + re.findall(r"className='([^']+)'", SCRIPT):
        used.update(value.split())
    missing = sorted(name for name in used - {'facts'} if '.' + name not in css)
    assert not missing, missing


def test_public_v2_page_has_no_internal_terms_and_states_the_points_rules():
    visible = re.sub(r'<[^>]+>', ' ', PAGE) + ' ' + ' '.join(re.findall(r"'([A-Z][a-z][^'\n]*? [^'\n]*)'", SCRIPT))
    for term in ('atoms', 'Beneficial', 'Clearing', 'double-entry', 'Reconcil', 'A2A', 'MCP', 'bps', 'escrow',
                 'mandate', 'Mandate', 'Relay', 'relay partner', 'test coins', 'Platform Audit'):
        assert term not in visible, term
    for rule in ('cannot be bought, cashed out or sent to another person', 'AgentValCon benefits',
                 'expire after 365 days without activity', 'Points have no cash value'):
        assert rule in PAGE, rule

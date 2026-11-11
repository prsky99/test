"""11-11 PM decision B: first-screen CSS keeps the used rules in order, inside their @media, and drops the rest."""
from scripts.build_critical_css import blocks, critical

CSS = """/* head */
:root{--a:1}
.used{color:red}
.unused{color:blue}
@media (max-width:700px){.used{color:green}.unused2{x:y}}
@keyframes spin{from{a:b}to{c:d}}
.quote[data-x="{"]{content:"}"}
@supports (display:grid){@media (min-width:1px){.deep{a:b}.deeper{c:d}}}
"""


def offsets(text):
    start = CSS.index(text)
    return start, start + len(text)


def test_blocks_respect_strings_comments_and_nesting():
    items = blocks(CSS)
    preludes = [p for _, _, p, _ in items]
    assert preludes == [':root', '.used', '.unused', '@media (max-width:700px)', '@keyframes spin', '.quote[data-x="{"]',
                        '@supports (display:grid)']
    media = items[3][3]
    assert [p for _, _, p, _ in media] == ['.used', '.unused2']


def test_critical_keeps_used_rules_wrappers_and_always_kept_items():
    used = [offsets('.used{color:red}'), offsets('.used{color:green}'), offsets('.deep{a:b}')]
    out = critical(CSS, used)
    assert out.index(':root{--a:1}') < out.index('.used{color:red}') < out.index('@media (max-width:700px){.used{color:green}}')
    assert '@keyframes spin{from{a:b}to{c:d}}' in out
    assert '@supports (display:grid){@media (min-width:1px){.deep{a:b}}}' in out
    for gone in ('.unused{', '.unused2', '.deeper', '.quote'):
        assert gone not in out


def test_a_page_with_a_built_file_inlines_it_and_loads_the_bundle_without_blocking(tmp_path, monkeypatch):
    import base64
    import hashlib
    import re
    from fastapi.testclient import TestClient
    from agent_market.concierge import pearl_view
    from agent_market.concierge.front import Front, clear_front_caches, create_front_app
    from agent_market.gateway.store import Store
    (tmp_path / 'learn.css').write_text('.used{color:red}\n')
    monkeypatch.setattr(pearl_view, 'CRITICAL_DIR', tmp_path)
    store = Store(str(tmp_path / 'c.db'))
    clear_front_caches()
    front = Front(store)
    client = TestClient(create_front_app(front, manage_book_lifecycle=False))
    try:
        html = client.get('/new/en/learn.html').text
        head = html[:html.index('</head>')]
        assert '<style data-critical-css>.used{color:red}' in head
        assert re.search(r'<link rel="stylesheet" href="/new/en/assets/bundle\.css\?[^"]+" media="print" data-full-css>', head)
        assert not re.search(r'<link rel="stylesheet" href="/new/en/assets/bundle\.css\?[^"]+">', head)  # nothing blocks
        csp = client.get('/new/en/learn.html').headers['content-security-policy']
        switch = pearl_view.FULL_CSS_SWITCH[len('<script>'):-len('</script>\n')]
        assert "'sha256-" + base64.b64encode(hashlib.sha256(switch.encode()).digest()).decode() + "'" in csp
        other = client.get('/new/en/chat.html').text  # no file built for chat: unchanged
        assert 'data-critical-css' not in other and re.search(r'<link rel="stylesheet" href="/new/en/assets/bundle\.css\?[^"]+">', other)
    finally:
        client.close()
        front.book.close()
        store._db.close()

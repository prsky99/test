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


def test_relative_urls_point_at_the_assets_folder_once_inlined():
    from scripts.build_critical_css import absolute_urls
    css = '.a{background:url(pearl.webp)}.b{background:url("./x.png")}.c{background:url(/new/en/assets/y.png)}.d{background:url(data:image/png;base64,AA)}'
    out = absolute_urls(css)
    assert 'url(/new/en/assets/pearl.webp)' in out and 'url("/new/en/assets/x.png")' in out
    assert 'url(/new/en/assets/y.png)' in out and 'url(data:image/png;base64,AA)' in out


def test_state_rules_for_classes_the_page_can_take_are_kept():
    from scripts.build_critical_css import critical, state_rule
    dom, scripted = {'chip-btn', 'quick-chips'}, {'active'}
    assert state_rule('.chip-btn.active', dom, scripted)            # selected by the data on another visit
    assert not state_rule('.other-page .chip-btn', dom, scripted)    # a class this page never has
    assert not state_rule('.active', dom, scripted)                  # nothing of it is on this page
    css = '.chip-btn{a:b}.chip-btn.active{c:d}.wf-node{e:f}'
    out = critical(css, [(0, len('.chip-btn{a:b}'))], dom, scripted)
    assert '.chip-btn.active{c:d}' in out and '.wf-node' not in out


def test_every_built_file_was_made_from_the_current_bundle():
    # A stylesheet change without regenerating would leave the first screen drawn by stale rules.
    import hashlib
    import json
    import re
    from pathlib import Path
    from fastapi.testclient import TestClient
    from agent_market.concierge.front import Front, clear_front_caches, create_front_app
    from agent_market.concierge.pearl_view import bundle_body
    from agent_market.gateway.store import Store
    root = Path(__file__).resolve().parents[1]
    built = sorted((root / 'new/en/assets/critical').glob('*.css'))
    if not built:
        return
    import tempfile
    store = Store(str(Path(tempfile.mkdtemp()) / 'c.db'))
    clear_front_caches()
    front = Front(store)
    client = TestClient(create_front_app(front, manage_book_lifecycle=False))
    try:
        for path in built:
            html = client.get('/new/en/' + path.stem + '.html').text
            names = re.search(r'bundle\.css\?f=([^"&]+)', html)[1].split(',')
            digest = hashlib.sha256(bundle_body(names, 'css')).hexdigest()[:16]
            head = path.read_text().split('\n', 1)[0]
            assert head == '/* source %s */' % digest, (
                path.name + ' was built from another stylesheet: run scripts/build_critical_css.py again')
    finally:
        client.close()
        front.book.close()
        store._db.close()


def test_prune_leaves_out_only_declarations_a_later_rule_always_overrides():
    # 11-14 PM plan 1: the five stylesheets override each other; the first-screen copy keeps only what wins.
    from scripts.build_critical_css import prune
    css = ('.a{color:red;margin:0}.b{color:blue!important}.c{color:red}'
           '@media (max-width:700px){.a{color:pink}}'
           '.a{color:green}.b{color:black}.c{color:color-mix(in srgb,red 50%,blue)}'
           '.d{-webkit-box-flex:1}.d{-webkit-box-flex:2}.e{background:url("x;y.png")}.e{width:1px}'
           '.f :hover{x:1}.f:hover{x:2}')
    out = prune(css)
    assert '.a{margin:0}' in out and '.a{color:green}' in out          # the earlier red always loses
    assert '@media (max-width:700px){.a{color:pink}}' in out            # another context is never touched
    assert '.b{color:blue!important}' in out                            # !important wins over a later plain one
    assert '.c{color:red}' in out                                       # fallback when color-mix is not understood
    assert '.d{-webkit-box-flex:1}' in out                              # vendor properties are left alone
    assert '.e{background:url("x;y.png")}' in out                       # ; inside url() is not a separator
    assert '.f :hover{x:1}' in out and '.f:hover{x:2}' in out           # a descendant space stays


def test_every_protocol_card_colour_is_kept_when_the_page_shows_protocol_cards():
    # 11-14: a build that saw only A2A cards dropped the MCP colours; the cards come from live data.
    from scripts.build_critical_css import critical
    css = ('.acard{a:b}.k-a2a{c:a}.k-mcp{c:m}.k-x402{c:x}.acard.k-mcp{d:m}'
           '[data-protocol="mcp"]{e:m}body[data-theme="dark"] [data-protocol="x402"]{e:x}.other.k-mcp{f:g}')
    used = [(0, len('.acard{a:b}')), (css.index('.k-a2a'), css.index('.k-a2a') + len('.k-a2a{c:a}'))]
    out = critical(css, used, dom={'acard', 'k-a2a'})
    for kept in ('.k-mcp{c:m}', '.k-x402{c:x}', '.acard.k-mcp{d:m}', '[data-protocol="mcp"]{e:m}',
                 'body[data-theme="dark"] [data-protocol="x402"]{e:x}'):
        assert kept in out, kept
    assert '.other.k-mcp' not in out                    # a class the page never has stays out
    assert '.k-mcp' not in critical(css, used[:1], dom={'acard'})   # no protocol card on the page: nothing added

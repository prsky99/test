"""Leave out CSS declarations a later rule always overrides, and collapse whitespace (11-14, PM plans 1 and 3).

Used for the first-screen CSS (scripts/build_critical_css.py) and for bundle.css (pearl_view.bundle_body): the five
stylesheets override each other, so 13-18 % of what a page downloads never wins. The source files keep their
comments and layout; only what is served is compacted.
"""
import re

from .css_blocks import blocks

# 11-14 PM decision (plan 1): the first-screen CSS repeats the five stylesheets' overrides (13-15 % of its
# declarations are redefined later for the same selector in the same @media). A declaration is left out only when a
# later rule with the very same selector text, in the very same @media/@supports context, sets the same property
# with a value every current browser understands (so the earlier one can never be used as a fallback) and the
# !important order allows it. What the first screen draws does not change (tests/test_critical_css_browser.py).
SAFE_VALUE = re.compile(r'^(?:[^()]|\b(?:var|url|calc|min|max|clamp|rgb|rgba|hsl|hsla|linear-gradient|radial-gradient|'
                        r'repeating-linear-gradient|translate|translateX|translateY|scale|rotate|cubic-bezier|'
                        r'minmax|repeat|attr|counter|blur|drop-shadow)\([^()]*(?:\([^()]*\)[^()]*)*\))*$')


def declarations(body):
    """'a:b;c:url(x;y)' -> ['a:b', 'c:url(x;y)'], splitting on ; outside parentheses and strings."""
    out, cur, depth, quote = [], '', 0, None
    for ch in body:
        if quote:
            quote = None if ch == quote else quote
        elif ch in '"\'':
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ';' and depth == 0:
            out.append(cur.strip()); cur = ''
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return [d for d in out if d]


def prune(css):
    """Leave out declarations a later rule always overrides (see SAFE_VALUE), and collapse whitespace."""
    tree = blocks(css)

    def leaves(items, ctx):
        for start, end, prelude, children in items:
            if children is None:
                if not prelude.startswith('@') and '{' in css[start:end]:
                    yield ctx, prelude, (start, end)
            elif not prelude.lower().startswith(('@keyframes', '@-webkit-keyframes')):
                yield from leaves(children, ctx + (prelude,))
    seen = {}  # (ctx, selector, property) -> [(rule offsets, important, value)], in order
    for ctx, prelude, span in leaves(tree, ()):
        text = css[span[0]:span[1]]
        for d in declarations(text[text.index('{') + 1:text.rindex('}')]):
            if ':' not in d:
                continue
            prop, value = d.split(':', 1)
            seen.setdefault((ctx, prelude, prop.strip().lower()), []).append(
                (span, '!important' in value.lower(), value.strip()))
    dead = set()
    for key, uses in seen.items():
        for i, (span, important, _) in enumerate(uses):
            later = [u for u in uses[i + 1:] if u[0] != span]
            if any((imp or not important) and not prop_vendor(key[2]) and SAFE_VALUE.match(val.replace('!important', ''))
                   for _, imp, val in later):
                dead.add((span, key[2]))

    def draw(items):
        out = []
        for start, end, prelude, children in items:
            text = css[start:end]
            if children is not None:
                inner = draw(children)
                if inner:
                    out.append(squeeze(prelude) + '{' + inner + '}')
            elif prelude.startswith('@') or '{' not in text:
                out.append(text.strip())
            else:
                body = [d for d in declarations(text[text.index('{') + 1:text.rindex('}')])
                        if ':' not in d or ((start, end), d.split(':', 1)[0].strip().lower()) not in dead]
                body = [d.split(':', 1)[0].strip() + ':' + d.split(':', 1)[1].strip() if ':' in d else d for d in body]
                if body:
                    out.append(squeeze(prelude) + '{' + ';'.join(body) + '}')
        return ''.join(out)
    return draw(tree)


def prop_vendor(prop):
    return prop.startswith(('-webkit-', '-moz-', '-ms-'))


def squeeze(prelude):
    """Whitespace runs to one space; around { , > + ~ none (a space before ':' is kept: it is a descendant)."""
    return re.sub(r'\s*([,>+~])\s*', r'\1', re.sub(r'\s+', ' ', prelude.strip()))



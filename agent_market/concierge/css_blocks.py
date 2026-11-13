"""A small CSS reader: top-level items with their nesting, respecting strings and comments."""

KEEP_AT = ('@font-face', '@keyframes', '@-webkit-keyframes', '@property', '@counter-style', '@layer')


def blocks(css, i=0, n=None):
    """Items of css[i:n] as (start, end, prelude, children); offsets are into css, children are nested items."""
    out, n = [], len(css) if n is None else n
    while i < n:
        while i < n and css[i] in ' \t\r\n':
            i += 1
        if i >= n:
            break
        if css.startswith('/*', i):
            j = css.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        start = i
        depth, quote, brace = 0, None, -1
        while i < n:
            ch = css[i]
            if quote:
                if ch == '\\':
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            elif ch in '"\'':
                quote = ch
            elif css.startswith('/*', i):
                j = css.find('*/', i + 2)
                i = n if j < 0 else j + 2
                continue
            elif ch == '{':
                if depth == 0 and brace < 0:
                    brace = i - start  # the first brace outside strings and comments
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            elif ch == ';' and depth == 0:
                i += 1
                break
            i += 1
        text = css[start:i]
        prelude = text[:brace].strip() if brace >= 0 else text.strip()
        children = None
        if prelude.startswith('@') and brace >= 0 and not prelude.lower().startswith(KEEP_AT):
            children = blocks(css, start + brace + 1, i - 1)
        out.append((start, i, prelude, children))
    return out

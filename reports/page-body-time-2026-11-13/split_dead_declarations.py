import re, gzip, sys
g = lambda t: len(gzip.compress(t.encode(), 6))
exec(open('css.py').read().split('for name in sys.argv')[0])
for name in sys.argv[1:]:
    c = re.sub(r'/\*.*?\*/', '', crit(name), flags=re.S)
    rules = walk(c)
    # single-selector rules only (a selector list shares declarations; keep those whole)
    last = {}
    for idx, (m, sel, body) in enumerate(rules):
        if sel.startswith('@') or ',' in sel: continue
        for d in [x.strip() for x in body.split(';') if x.strip() and ':' in x]:
            prop = d.split(':', 1)[0].strip().lower(); imp = '!important' in d
            key = (m, sel, prop); prev = last.get(key)
            if prev is None or imp or not prev[0]: last[key] = (imp, idx)
    out = []; removed = 0
    for idx, (m, sel, body) in enumerate(rules):
        if sel.startswith('@') or ',' in sel:
            out.append((m, sel, body)); continue
        keep = []
        for d in [x.strip() for x in body.split(';') if x.strip()]:
            prop = d.split(':', 1)[0].strip().lower()
            if ':' in d and last.get((m, sel, prop), (None, idx))[1] != idx: removed += 1; continue
            keep.append(d)
        if keep: out.append((m, sel, ';'.join(keep)))
    text = ''.join(f'{m}{{{s}{{{b}}}}}' if m else f'{s}{{{b}}}' for m, s, b in out)
    base = ''.join(f'{m}{{{s}{{{b}}}}}' if m else f'{s}{{{b}}}' for m, s, b in rules)
    print(name, 'removed decl', removed, 'gz flat', g(base), '->', g(text), 'saved', g(base) - g(text))

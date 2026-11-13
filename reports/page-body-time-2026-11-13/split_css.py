import re, gzip, sys
g = lambda t: len(gzip.compress(t.encode(), 6))
def crit(name):
    s = open(name).read()
    return re.search(r'<style data-critical-css[^>]*>(.*?)</style>', s, re.S)[1]
def walk(css, media=''):
    i = 0; out = []
    while i < len(css):
        j = css.find('{', i)
        if j < 0: break
        pre = css[i:j].strip()
        if pre.startswith('@media') or pre.startswith('@supports') or pre.startswith('@layer') or pre.startswith('@container'):
            depth = 1; k = j + 1
            while depth and k < len(css):
                depth += {'{': 1, '}': -1}.get(css[k], 0); k += 1
            out += walk(css[j+1:k-1], media + '|' + pre); i = k; continue
        k = css.find('}', j); out.append((media, pre, css[j+1:k])); i = k + 1
    return out
for name in sys.argv[1:]:
    c = re.sub(r'/\*.*?\*/', '', crit(name), flags=re.S)
    rules = walk(c)
    seen = {}; total = 0; dead = 0
    decl_list = []
    for idx, (m, sel, body) in enumerate(rules):
        if sel.startswith('@'): continue
        for d in [x.strip() for x in body.split(';') if x.strip() and ':' in x]:
            prop = d.split(':', 1)[0].strip().lower(); imp = '!important' in d
            for one in [x.strip() for x in sel.split(',')]:
                decl_list.append((m, one, prop, imp, idx, d))
    last = {}
    for m, one, prop, imp, idx, d in decl_list:
        key = (m, one, prop)
        prev = last.get(key)
        if prev is None or imp or not prev[0]: last[key] = (imp, idx)
    total = len(decl_list); dead = sum(1 for m, one, prop, imp, idx, d in decl_list if last[(m, one, prop)][1] != idx)
    mini = re.sub(r'\s+', ' ', c); mini = re.sub(r'\s*([{}:;,>])\s*', r'\1', mini).replace(';}', '}')
    print(name, 'rules', len(rules), 'decl', total, 'overridden later (same media+selector+prop)', dead, f'{dead/total:.0%}', '| gz now', g(crit(name)), 'minified gz', g(mini), 'raw', len(crit(name)), '->', len(mini))

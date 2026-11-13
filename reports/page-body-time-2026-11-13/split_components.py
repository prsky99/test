import re, gzip, sys, json
g = lambda t: len(gzip.compress(t.encode(), 6))
PARTS = [
 ('critical_css', r'<style data-critical-css[^>]*>.*?</style>'),
 ('other_style', r'<style(?! data-critical-css)[^>]*>.*?</style>'),
 ('ld_json', r'<script[^>]*type="application/ld\+json"[^>]*>.*?</script>'),
 ('json_data', r'<script[^>]*type="application/json"[^>]*>.*?</script>'),
 ('inline_script', r'<script(?![^>]*\bsrc=)(?![^>]*type="application/(?:ld\+)?json")[^>]*>.*?</script>'),
 ('svg', r'<svg.*?</svg>'),
 ('meta_agent', r'<meta name="agent:[^>]*>'),
 ('meta_page', r'<meta name="page:[^>]*>'),
 ('meta_other', r'<meta (?!name="(?:agent|page):)[^>]*>'),
 ('link', r'<link[^>]*>'),
]
for name in sys.argv[1:]:
    s = open(name).read(); full = g(s); rest = s; out = {}
    for key, pat in PARTS:
        found = re.findall(pat, rest, re.S | re.I)
        rest2 = re.sub(pat, '', rest, flags=re.S | re.I)
        out[key] = {'n': len(found), 'raw': sum(map(len, found)), 'gz_alone': g(''.join(found)) if found else 0, 'gz_saved': g(rest) - g(rest2)}
        rest = rest2
    body = re.search(r'<body.*', rest, re.S)
    out['remaining_markup'] = {'raw': len(rest), 'gz': g(rest), 'body_raw': len(body[0]) if body else 0}
    print(name, 'raw', len(s), 'gzip', full)
    for k, v in out.items(): print('  ', k, v)

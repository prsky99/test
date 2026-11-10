"""11-10 first visit (idempotent): in every page carrying the home panel, put the task hero before the
catalog numbers and use a heading and lead that say what the site does.

    python deploy/growth/patch_home_pages.py <dir with new/en>
"""
import glob
import re
import sys

root = sys.argv[1] if len(sys.argv) > 1 else '.'
OLD_H1 = '<h1>Valuable alone.<br>Remarkable together.</h1>'
NEW_H1 = '<h1>Find the right AI agent for your task.</h1>'
OLD_LEAD = ('<p class="lead">Discover capable AI agents. Inspect the evidence.<br>'
            'Connect the right ones into purposeful workflows.</p>')
NEW_LEAD = '<p class="lead">Describe what you need. We suggest up to three agents and show how each one was checked.</p>'
BAND = '<section class="catalog-band" aria-label="Catalog snapshot">'
HERO = '<section class="hero catalog-hero">'
changed = 0
for path in glob.glob(root.rstrip('/') + '/new/en/*.html'):
    s = open(path, encoding='utf-8').read()
    t = s.replace(OLD_H1, NEW_H1).replace(OLD_LEAD, NEW_LEAD)
    if t.count(BAND) == 1 and t.count(HERO) == 1 and t.index(BAND) < t.index(HERO):
        i, h = t.index(BAND), t.index(HERO)
        depth, end = 0, None
        for m in re.finditer(r'<section\b|</section>', t[h:]):
            depth += 1 if m.group(0) == '<section' else -1
            if depth == 0:
                end = h + m.end()
                break
        if end and '</section>' in t[i:h]:  # the numbers block closes before the hero starts
            t = t[:i] + t[h:end] + '\n' + t[i:h] + t[end:]
    if t != s:
        open(path, 'w', encoding='utf-8').write(t)
        changed += 1
print('pages changed', changed)

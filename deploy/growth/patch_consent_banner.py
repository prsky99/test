"""11-11 (PM decision A): the cookie strip sits in the page flow above the header instead of floating
over content, so it never covers a control on the first screen. Idempotent.

- <head> gets a tiny script (served with the per-response nonce like every page script) that reads the
  stored choice before the body renders and marks <html class="consent-pending"> only for visitors who
  have not chosen and send no GPC signal; CSS shows the strip only then, so returning visitors never see
  it flash or the page move.
- The strip's markup moves to the start of <body>, right after the skip link, and loses its initial `hidden` class (CSS decides).

    python deploy/growth/patch_consent_banner.py <dir with new/en>
"""
import glob
import re
import sys

root = sys.argv[1] if len(sys.argv) > 1 else '.'
HEAD = ('<script>try{var c=localStorage.getItem("agent_cookie_consent_v2"),ok=false;if(c){try{JSON.parse(c);ok=true}catch(e){}}'
        'if(!ok&&!(navigator.globalPrivacyControl))document.documentElement.classList.add("consent-pending")}catch(e){}</script>')
OPEN = '<div id="cookieConsentBanner"'
changed = 0
for path in glob.glob(root.rstrip('/') + '/new/en/*.html'):
    s = open(path, encoding='utf-8').read()
    if OPEN not in s:
        continue
    t = s
    if HEAD not in t:
        t = t.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + HEAD, 1)
        assert HEAD in t, path
    start = t.index(OPEN)
    depth, end = 0, None
    for m in re.finditer(r'<div\b|</div>', t[start:]):
        depth += 1 if m.group(0) == '<div' else -1
        if depth == 0:
            end = start + m.end()
            break
    block = t[start:end]
    # Right after the skip link (keyboard users still reach "Skip to main content" first), else after <body>.
    SKIP = '<a href="#mainContent" class="skip-link">Skip to main content</a>'
    anchor = (lambda u: (u.index(SKIP) + len(SKIP)) if SKIP in u else re.search(r'<body[^>]*>', u).end())
    if not t[anchor(t):].lstrip().startswith(OPEN):
        t = t[:start] + t[end:]
        at = anchor(t)
        t = t[:at] + '\n' + block + t[at:]
    t = t.replace('<div id="cookieConsentBanner" class="cookie-banner hidden"', '<div id="cookieConsentBanner" class="cookie-banner"')
    # The short line and the folded explanation are in the markup from the start; experience.js used to build
    # them after load, which changed the strip's height and moved the page (CLS 0.18 on the home page).
    if 'class="cookie-purpose-details"' not in t:
        text = re.search(r'\s*<p class="cookie-banner-text">.*?</p>', t[t.index(OPEN):], re.S)
        assert text, path
        a = t.index(OPEN) + text.start(); b = t.index(OPEN) + text.end()
        t = (t[:a] + '\n  <p class="cookie-choice-summary">Choose optional analytics and marketing cookies. Essential storage stays on.</p>'
             + '\n  <details class="cookie-purpose-details"><summary>How we use cookies</summary>' + text.group(0).strip() + '</details>' + t[b:])
    if t != s:
        open(path, 'w', encoding='utf-8').write(t)
        changed += 1
print('pages changed', changed)

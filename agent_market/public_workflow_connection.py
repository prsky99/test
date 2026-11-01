"""English public UI for one separately authorized informational connection."""
import json
import re
import secrets


def build_public_connection_page(release_id, nonce=None):
    if not isinstance(release_id, str) or not re.fullmatch(r'pub_[0-9a-f]{32}', release_id):
        raise ValueError('Choose an available public connection.')
    nonce = secrets.token_hex(24) if nonce is None else nonce
    if not isinstance(nonce, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', nonce):
        raise ValueError('Use a valid page nonce.')
    config = json.dumps({'release_id': release_id, 'profile': 'public-news-title-to-docs-v1'}, ensure_ascii=True)
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-__NONCE__'; script-src-attr 'none'; style-src 'nonce-__NONCE__'; style-src-attr 'none'; connect-src 'self'; img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'">
<meta name="referrer" content="no-referrer"><meta name="robots" content="noindex, nofollow">
<title>News to Documentation — Agent Concierge</title>
<meta name="description" content="Review a public news search and separately authorize sharing its checked first result title with one documentation agent for one run.">
<meta property="og:type" content="website"><meta property="og:site_name" content="Agent Concierge">
<meta property="og:title" content="News to Documentation — Agent Concierge">
<meta property="og:description" content="Review a public news search and separately authorize sharing its checked first result title with one documentation agent for one run.">
<meta name="twitter:card" content="summary"><meta name="twitter:title" content="News to Documentation — Agent Concierge">
<meta name="twitter:description" content="Review a public news search and separately authorize sharing its checked first result title with one documentation agent for one run.">
<meta name="theme-color" content="#f8fafc" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#101827" media="(prefers-color-scheme: dark)">
<style nonce="__NONCE__">
:root{color-scheme:light dark;--bg:#f8fafc;--surface:#fff;--text:#142033;--muted:#4c5c71;--line:#cbd5e1;--accent:#374fc7;--accent-text:#fff;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
@media(prefers-color-scheme:dark){:root{--bg:#101827;--surface:#172235;--text:#eef3fb;--muted:#bac7da;--line:#445471;--accent:#becaff;--accent-text:#122046}}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:var(--bg);color:var(--text);line-height:1.6}main{max-width:940px;margin:0 auto;padding:40px 22px}header{margin-bottom:28px}a{color:var(--accent);overflow-wrap:anywhere}.brand{display:inline-flex;align-items:center;gap:10px;font-weight:650;text-decoration:none}svg{flex:none}h1{font-size:clamp(1.7rem,5vw,2.2rem);line-height:1.2;margin:28px 0 12px}h2{font-size:1.2rem;margin:0 0 14px}h3{font-size:1rem;margin:16px 0 8px}p{margin:10px 0}.muted,footer{color:var(--muted)}section{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:24px;margin:20px 0}button{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--text);border-radius:10px;padding:11px 16px;cursor:pointer;display:inline-flex;align-items:center;gap:8px}button.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-text)}button:disabled{opacity:.55;cursor:default}button:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:4px}label{display:flex;gap:12px;align-items:flex-start;margin:16px 0}input[type=checkbox]{margin-top:7px;width:18px;height:18px;flex:none}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}#connectionStatus{font-weight:600;overflow-wrap:anywhere}#connectionReview,#connectionResults{overflow-wrap:anywhere}article{border-top:1px solid var(--line);margin-top:16px;padding-top:4px}.result-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}.result-grid section{margin:0}footer{border-top:1px solid var(--line);padding:22px 0;font-size:.9rem}footer a{margin-right:16px}@media(max-width:500px){main{padding:24px 16px}section{padding:18px}.actions button{width:100%;justify-content:center}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto;transition:none;animation:none}}
</style></head><body><main>
<header><a class="brand" href="/" aria-label="Agent Concierge home"><svg class="lucide lucide-link" focusable="false" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>Agent Concierge</a><h1 id="connectionTitle">News to documentation</h1><p id="connectionDescription">One news search, followed by one documentation search using its checked first result title.</p><p class="muted">The future news title is not known before the news search. Only a title that passes the connection checks can become the documentation query. Results do not establish factual accuracy or expert quality.</p></header>
<section aria-labelledby="reviewTitle"><h2 id="reviewTitle">Review before each run</h2><p>Preparation does not call agents. Review the exact news inputs, selected recipients, fixed documentation settings and title-sharing rule.</p><button id="connectionPrepare" type="button" disabled>Prepare run review</button><div id="connectionReview" aria-live="polite"></div>
<label><input id="connectionShare" type="checkbox" disabled><span>I authorize this run's checked first news result title to be sent as a search query to the listed documentation agent, using the reviewed fixed settings.</span></label>
<label><input id="connectionLive" type="checkbox" disabled><span>I authorize one live run using the reviewed news inputs and this connection rule.</span></label>
<div class="actions"><button id="connectionRun" type="button" class="primary" disabled><svg class="lucide lucide-play" focusable="false" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m8 5 12 7-12 7V5Z"/></svg>Run once</button><button id="connectionCancel" type="button" disabled>Stop</button><button id="connectionResume" type="button" hidden>Resume status</button></div>
<p id="connectionStatus" role="status" aria-live="polite">Checking connection availability…</p><p id="connectionNotice" class="muted"></p></section>
<div id="connectionResults" class="result-grid" aria-live="polite"></div>
<p class="muted">A failed, unsafe, empty or unavailable news result stops the documentation call. No fallback or automatic execution retry is enabled. Closing this page clears local state and does not cancel an accepted server run.</p>
<footer><a href="/#privacy">Privacy Policy</a><a href="/#tos">Terms of Service</a><a href="/#workflows">Workflow Studio</a><p>Sharing and execution authorization apply only to this run. They do not create marketing permission.</p></footer>
<script type="application/json" id="connectionData" nonce="__NONCE__">__CONFIG__</script><script src="/assets/public-connection.js" nonce="__NONCE__" defer></script>
</main></body></html>'''
    return page.replace('__NONCE__', nonce).replace('__CONFIG__', config)

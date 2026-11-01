"""Public assets for separately reviewed connected SDK 1.3 deployments."""
from html import escape
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .workflow_connection_deployment import PROFILE

GATEWAY = 'https://agentconcierge.biz'
ASSETS = Path(__file__).parent / 'gateway' / 'webapp'
CSS = '''
:root{color-scheme:light dark;--bg:#f8fafc;--surface:#fff;--text:#142033;--muted:#4c5c71;--line:#cbd5e1;--accent:#374fc7;--accent-text:#fff;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
@media(prefers-color-scheme:dark){:root{--bg:#101827;--surface:#172235;--text:#eef3fb;--muted:#bac7da;--line:#445471;--accent:#becaff;--accent-text:#122046}}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:var(--bg);color:var(--text);line-height:1.6}main{max-width:940px;margin:auto;padding:40px 22px}header{margin-bottom:28px}a{color:var(--accent);overflow-wrap:anywhere}.brand{display:inline-flex;align-items:center;gap:10px;font-weight:650;text-decoration:none}svg{flex:none}h1{font-size:clamp(1.7rem,5vw,2.2rem);line-height:1.2;margin:28px 0 12px}h2{font-size:1.2rem;margin:0 0 14px}h3{font-size:1rem;margin:16px 0 8px}p{margin:10px 0}.muted,footer{color:var(--muted)}section{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:24px;margin:20px 0}button{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--text);border-radius:10px;padding:11px 16px;cursor:pointer;display:inline-flex;align-items:center;gap:8px}button.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-text)}button:disabled{opacity:.55;cursor:default}button:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:4px}label{display:flex;gap:12px;align-items:flex-start;margin:16px 0}input[type=checkbox]{margin-top:7px;width:18px;height:18px;flex:none}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}#appStatus{font-weight:600}#inputReview,#stepsContainer,#appStatus,#appNotice{overflow-wrap:anywhere}pre{white-space:pre-wrap;max-height:360px;overflow:auto}article{border-top:1px solid var(--line);margin-top:16px;padding-top:4px}footer{border-top:1px solid var(--line);padding:22px 0;font-size:.9rem}footer a{margin-right:16px}@media(max-width:500px){main{padding:24px 16px}section{padding:18px}.actions button{width:100%;justify-content:center}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto;transition:none;animation:none}}
'''

README = '''# Agent Concierge connected app — SDK 1.3

Deploy index.html and assets/ together on an exact HTTP(S) origin reviewed by the
administrator. Subdirectory hosting is supported. Use HTTPS in production.
All application requests go to https://agentconcierge.biz. The package contains
public deployment identification, not administrator credentials, provider keys,
private graphs, provider endpoints or authority payloads.

The publish key and Origin checks are deployment controls, not user identity.
Non-browser clients can forge Origin. The gateway independently checks the signed
deployment grant and its separate publication grant, exact origins, definitions,
limits, expiration, current authority and fresh per-run declarations. Editing the
package cannot broaden server authority. A grant may expire or be revoked.

## One connected run

1. Select Review run inputs. Preparation does not call agents or models.
2. Review the exact fixed news query, time window, selected recipients,
   documentation settings and title-sharing rule.
3. Separately authorize title sharing and one live run with the unchecked controls.
4. Select Run once. These declarations apply only to this execution attempt.

The future first news result title is unknown before the news call. Only its
checked title can become the documentation query. Empty, failed, unsafe or
uncertain source results stop the downstream call. The reviewed from_utc is fixed;
it is not silently moved to a fresh time window. This profile has at most two
agent calls and a 25-second run budget. It does not establish factual accuracy,
expert review or an unseen holdout. Preparation can read current catalog metadata;
it does not mean that every database operation is read-only.

No run starts on page load, preparation, status resume or reopening. No dynamic
inputs, automatic schedules, events, fallback or result delivery are enabled.
Publication authorization, deployment authorization and each run's sharing/live
declarations are separate. They do not create marketing permission.

## SDK interface

const client = AgentConciergeWorkflow.createClient();
const preparation = await client.prepare();
// Display preparation.preview fully and obtain separate explicit declarations.
const handle = await client.run({
  preparation, sharingAuthority: true, runAuthority: true
});
const result = await client.wait(handle, {onUpdate: render});

The booleans are client declarations, not independent proof of a human action.
Never set them by default or infer them from an earlier visit or another grant.
Tickets and run keys stay in memory. Requests omit cookies and browser credentials;
public publish keys and scoped run keys travel in headers. Do not log or persist
capabilities in storage, URLs, analytics or exported content.

Run and cancellation POST requests are not automatically repeated. An ambiguous
start may have reached the gateway; the app locks further starts and asks the
publisher to inspect deployment history. Status GET has bounded retries. Resume
status checks the same accepted handle and does not start another run. Stop asks
for cancellation; an in-flight provider call may finish. Unknown outcomes never
trigger a second run automatically. Closing the page clears local state and does
not cancel an accepted server run.

The SDK uses only /api/workflow-connection-apps-v13/ on the fixed gateway. Earlier
SDK 1.0, 1.1, literal SDK 1.2 and public connection page contracts stay separate.
Keep the restrictive CSP and local assets. The app sends no telemetry or feedback
automatically, and renders previews and results as text. Configure the hosting
server's HTTP Content-Security-Policy with frame-ancestors 'none' and add
X-Frame-Options: DENY to prevent framing. A meta CSP cannot enforce frame-ancestors.
The packaged client also refuses to execute inside a frame.
'''


def build_admin_package_v13(config, deployment, single_html=False):
    """Build one public package; server-side grants remain outside the artifact."""
    if (not isinstance(config, dict) or not isinstance(deployment, dict)
            or deployment.get('profile') != PROFILE or deployment.get('sdk_version') != '1.3.0'
            or not re.fullmatch(r'capp_[a-f0-9]{32}', str(deployment.get('app_id', '')))
            or not re.fullmatch(r'pub_[a-f0-9]{32}', str(deployment.get('release_id', '')))
            or not re.fullmatch(r'cpk_[A-Za-z0-9_-]{43}', str(deployment.get('publish_key', '')))
            or config.get('release_id') != deployment['release_id']
            or config.get('api_origin') != GATEWAY):
        raise ValueError('Use a reviewed connected SDK 1.3 deployment.')
    public = {key: deployment[key] for key in ('app_id', 'publish_key', 'release_id', 'profile', 'sdk_version')}
    encoded = json.dumps(public, ensure_ascii=True, separators=(',', ':')).replace('<', '\\u003c')
    nonce = secrets.token_urlsafe(24)
    csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; script-src-attr 'none'; "
           f"style-src 'self' 'nonce-{nonce}'; style-src-attr 'none'; connect-src {GATEWAY}; "
           "img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'")
    index = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="__CSP__"><meta name="robots" content="noindex, nofollow">
<title>News to Documentation — Agent Concierge</title>
<meta name="description" content="Review a fixed news search and separately authorize its checked first title to be shared with one documentation agent for one run.">
<meta property="og:type" content="website"><meta property="og:site_name" content="Agent Concierge">
<meta property="og:title" content="News to Documentation — Agent Concierge"><meta property="og:description" content="Review exact search inputs and the title-sharing rule before one connected run.">
<meta name="twitter:card" content="summary"><meta name="twitter:title" content="News to Documentation — Agent Concierge"><meta name="twitter:description" content="Review exact search inputs and the title-sharing rule before one connected run.">
<meta name="theme-color" content="#f8fafc" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#101827" media="(prefers-color-scheme: dark)">
<link rel="stylesheet" href="assets/styles.css"></head><body><main>
<header><a class="brand" href="https://agentconcierge.biz/" aria-label="Agent Concierge home"><svg class="lucide lucide-link" focusable="false" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>Agent Concierge</a>
<h1>News to documentation</h1><p>One news search, followed by one documentation search using its checked first result title.</p><p class="muted">The future title is unknown before the news call. Results do not establish factual accuracy or expert quality.</p></header>
<section aria-labelledby="reviewTitle"><h2 id="reviewTitle">Review before each run</h2><p>Preparation does not call agents. Review exact news inputs, recipients, fixed documentation settings and the title-sharing rule.</p>
<button id="prepareAppBtn" type="button">Review run inputs</button><div id="inputReview" aria-live="polite"></div>
<label><input id="shareAppAuthority" type="checkbox" disabled><span>I authorize this run's checked first news result title to be sent as a search query to the listed documentation agent with the reviewed fixed settings.</span></label>
<label><input id="liveAppAuthority" type="checkbox" disabled><span>I authorize one live run using the reviewed news inputs and title-sharing rule.</span></label>
<div class="actions"><button id="runAppBtn" type="button" class="primary" disabled><svg class="lucide lucide-play" focusable="false" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m8 5 12 7-12 7V5Z"/></svg>Run once</button><button id="cancelAppBtn" type="button" disabled>Stop</button><button id="resumeAppBtn" type="button" hidden>Resume status</button></div>
<p id="appStatus" role="status" aria-live="polite">Review the connection before starting.</p><p id="appNotice" class="muted"></p></section>
<div id="stepsContainer" aria-live="polite"></div><p class="muted">A failed, empty, unsafe or uncertain news result stops the documentation call. Closing this page does not cancel an accepted run.</p>
<footer><a href="https://agentconcierge.biz/#privacy">Privacy Policy</a><a href="https://agentconcierge.biz/#tos">Terms of Service</a><p>Sharing and execution declarations apply only to this run. They do not create marketing permission.</p></footer>
<script type="application/json" id="wfData" nonce="__NONCE__">__CONFIG__</script><script src="assets/agentconcierge-sdk.js" nonce="__NONCE__" defer></script><script src="assets/app.js" nonce="__NONCE__" defer></script>
</main></body></html>'''
    index = index.replace('__CSP__', escape(csp, quote=True)).replace('__NONCE__', nonce).replace('__CONFIG__', encoded)
    sdk = (ASSETS / 'sdk-v13.js').read_text()
    app = (ASSETS / 'app-v13.js').read_text()
    manifest = {**public, 'format': 'agentconcierge-connected-webapp-v13', 'api_origin': GATEWAY,
                'inputs': 'fixed-news-first-checked-title-to-documentation', 'per_run_authorization': True}
    files = {'index.html': index, 'assets/styles.css': CSS, 'assets/agentconcierge-sdk.js': sdk,
             'assets/app.js': app, 'app-manifest.json': json.dumps(manifest, indent=2), 'README.md': README}
    filename = 'agentconcierge-connected-sdk-v13'
    if single_html:
        index = index.replace('<link rel="stylesheet" href="assets/styles.css">', f'<style nonce="{nonce}">{CSS}</style>')
        for name, code in [('agentconcierge-sdk.js', sdk), ('app.js', app)]:
            index = index.replace(f'<script src="assets/{name}" nonce="{nonce}" defer></script>', '')
            safe_code = re.sub(r'</script', r'<\\/script', code, flags=re.I)
            index = index.replace('</body>', f'<script nonce="{nonce}">{safe_code}</script></body>')
        return index.encode(), filename + '-app.html'
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = ZipInfo(name); info.compress_type = ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            archive.writestr(info, content.encode())
    return output.getvalue(), filename + '-webapp.zip'

"""Opt-in consent-aware packages; legacy public and admin builders stay intact."""
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .workflow_webapp import build_package
from .workflow_deployment_consent import PROFILE

ASSETS = Path(__file__).parent / 'gateway' / 'webapp'


def build_admin_package_v12(config, deployment, single_html=False):
    if deployment.get('profile') != PROFILE or deployment.get('sdk_version') != '1.2.0':
        raise ValueError('Use a reviewed version 1.2 deployment.')
    data, filename = build_package(config)
    with ZipFile(BytesIO(data)) as archive:
        files = {name: archive.read(name).decode('utf-8') for name in archive.namelist()}
    sdk = (ASSETS / 'sdk-v12.js').read_text()
    app = (ASSETS / 'app-v12.js').read_text()
    public = {key: deployment[key] for key in ('app_id', 'publish_key', 'workflow_id', 'profile', 'sdk_version')}
    encoded = json.dumps(public, ensure_ascii=True).replace('<', '\\u003c')
    index = re.sub(r'(<script type="application/json" id="wfData" nonce="[^"]+">).*?(</script>)',
                   lambda match: match[1] + encoded + match[2], files['index.html'], flags=re.S)
    review = '''<p>Review the exact public inputs and selected recipients before every run. Preparation does not call agents. Sharing and one live run require separate authorization.</p>
<button id="prepareAppBtn" type="button">Review run inputs</button>
<div id="inputReview" aria-live="polite"></div>
<label class="run-authorization"><input id="shareAppAuthority" type="checkbox" disabled> I authorize sharing these exact reviewed inputs with the listed agents for this run.</label>
<label class="run-authorization"><input id="liveAppAuthority" type="checkbox" disabled> I authorize one live run of this reviewed workflow.</label>
'''
    run_anchor = '<button id="runAppBtn"'
    if index.count(run_anchor) != 1:
        raise ValueError('The workflow application layout is unavailable.')
    index = index.replace(run_anchor, review + run_anchor + ' disabled', 1)
    index = index.replace('<div id="stepsContainer"></div>', '<p id="appNotice" role="status" aria-live="polite"></p><div id="stepsContainer"></div>')
    css = files['assets/styles.css'] + '\n.run-authorization{display:block;margin:16px 0;line-height:1.5}.run-authorization input{margin-right:8px}input:focus-visible{outline:3px solid #6366f1;outline-offset:3px}button:disabled{cursor:default;opacity:.65}#inputReview pre{max-height:320px;overflow:auto}#appNotice{overflow-wrap:anywhere}\n'
    manifest = json.loads(files['app-manifest.json'])
    manifest.update(format='agentconcierge-admin-webapp-v12', sdk_version='1.2.0',
                    profile=PROFILE, app_id=deployment['app_id'], publish_key=deployment['publish_key'],
                    allowed_origins=deployment['allowed_origins'], expires=deployment['expires'],
                    inputs='fixed-reviewed-literals', per_run_authorization=True,
                    limits={'starts_per_minute': deployment['minute_limit'], 'starts_per_day': deployment['day_limit']})
    readme = '''# Agent Concierge reviewed workflow app — SDK 1.2

Deploy index.html and assets/ together on the exact HTTP(S) origin reviewed by the
administrator. Subdirectory hosting is supported. Use HTTPS in production.
All application requests go to https://agentconcierge.biz; no provider key,
administrator credential, private graph or provider endpoint is included.

The publish key is public deployment identification, not a user login or proof of
identity. Origin checks are browser controls; non-browser clients can forge them.
The gateway separately checks the current reviewed deployment grant, definition,
origins, fixed inputs, expiration, limits and per-run authorization. Editing the
package cannot broaden server authority. Revocation or definition changes may
make the application unavailable. This profile does not publish private workflows.

## One reviewed run

1. Select Review run inputs. This prepares a review without calling agents.
2. Inspect every exact public argument and recipient in the preview.
3. Separately authorize sharing and one live run using the unchecked controls.
4. Select Run Workflow once. Authorization is consumed for that attempt.

No workflow starts when the page loads, prepares a review, resumes status or
reopens. There are no editable input fields in this profile. Literal approved
English news/documentation searches are supported; connected titles, private
controlled pairs, automatic runs, delivery and dynamic fields are unsupported.
Preparation and execution do not establish expert quality or a hidden holdout.

## SDK interface

AgentConciergeWorkflow.createClient() reads the embedded package configuration.
const review = await client.prepare();
// Display review.preview completely, then obtain separate explicit authorization.
const handle = await client.run(workflowId, {
  preparation: review, shareAuthority: true, liveAuthority: true
});
const result = await client.wait(handle, {onUpdate: render});

The booleans are explicit client declarations, not independent verification of a
human action. Never set them by default or derive them from an earlier visit,
administrator approval, publication or another run. A review belongs to its
client instance and is consumed by an execution attempt. Run handles and tickets
remain in memory; run access keys travel only in headers and private WeakMaps.
Do not log them or persist them in browser storage, URLs or exported content.

Run POST requests are never automatically repeated. An interrupted start may have
reached the gateway; the app locks further starts and asks the publisher to check
deployment history. Status GET failures have bounded retries. Resume status checks
the same handle without starting another run. Stop sends one cancellation request;
an in-flight request may finish, so Run remains locked until a terminal response.
Closing the page clears local state and does not cancel an accepted server run.

Keep the restrictive CSP and local assets. The app sends no telemetry, advertising
or feedback automatically. Outputs and previews are rendered as text. Public
template downloads and earlier SDK packages keep their separate contracts.
'''
    files.update({'index.html': index, 'assets/agentconcierge-sdk.js': sdk,
                  'assets/app.js': app, 'assets/styles.css': css,
                  'app-manifest.json': json.dumps(manifest, indent=2), 'README.md': readme})
    if single_html:
        nonce = re.search(r'nonce="([^"]+)"', index)[1]
        index = index.replace('<link rel="stylesheet" href="assets/styles.css">', f'<style nonce="{nonce}">{css}</style>')
        index = index.replace("style-src &#x27;self&#x27;", "style-src &#x27;nonce-" + nonce + "&#x27;")
        for name, code in [('agentconcierge-sdk.js', sdk), ('app.js', app)]:
            index = index.replace(f'<script nonce="{nonce}" src="assets/{name}" defer></script>', '')
            safe_code = re.sub(r'</script', r'<\\/script', code, flags=re.I)
            index = index.replace('</body>', f'<script nonce="{nonce}">{safe_code}</script></body>')
        return index.encode(), filename.replace('-webapp.zip', '-sdk-v12-app.html')
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = ZipInfo(name); info.compress_type = ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            archive.writestr(info, content.encode())
    return output.getvalue(), filename.replace('-webapp.zip', '-sdk-v12-webapp.zip')

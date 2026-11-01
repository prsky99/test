"""Admin-only enhanced export profile, isolated from public SDK and package templates."""
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .workflow_webapp import build_package

ASSETS = Path(__file__).parent / 'gateway' / 'webapp'


def build_admin_package(config, deployment, single_html=False):
    data, filename = build_package(config)
    with ZipFile(BytesIO(data)) as archive:
        files = {name:archive.read(name).decode('utf-8') for name in archive.namelist()}
    sdk, app = (ASSETS / 'sdk.js').read_text(), (ASSETS / 'app.js').read_text()
    public = {k:deployment[k] for k in ('app_id','publish_key','workflow_id','input_fields')}
    encoded = json.dumps(public, ensure_ascii=True).replace('<', '\\u003c')
    index = re.sub(r'(<script type="application/json" id="wfData" nonce="[^"]+">).*?(</script>)',
                   lambda match:match[1] + encoded + match[2], files['index.html'], flags=re.S)
    run_anchor = '<button id="runAppBtn"'
    if index.count(run_anchor) != 1:
        raise ValueError('The workflow application layout is unavailable.')
    index = index.replace(run_anchor, '<div id="workflowInputs"></div><p class="input-notice">Application inputs are sent to Agent Concierge only when you select Run Workflow.</p>' + run_anchor, 1)
    index = index.replace('<div id="stepsContainer"></div>', '<p id="appNotice" role="status" aria-live="polite"></p><div id="stepsContainer"></div>')
    css = files['assets/styles.css'] + '\nlabel{display:block;margin:14px 0}input,select{box-sizing:border-box;display:block;width:100%;max-width:650px;padding:10px;margin-top:6px;border:1px solid #8391a6;border-radius:8px;background:Canvas;color:CanvasText;font:inherit}input:focus-visible,select:focus-visible{outline:3px solid #6366f1;outline-offset:3px}.input-notice,footer{font-size:.85rem;opacity:.8}.fallback-badge{font-size:.8rem;border:1px solid #8391a6;border-radius:8px;padding:4px 8px}pre{max-height:480px;overflow:auto}button:disabled{cursor:default;opacity:.65}#appNotice button{font-size:.9rem;padding:6px 10px}\n'
    manifest = json.loads(files['app-manifest.json'])
    manifest.update(format='agentconcierge-admin-webapp-v2', sdk_version='1.1.0',
                    app_id=deployment['app_id'], publish_key=deployment['publish_key'],
                    allowed_origins=deployment['allowed_origins'], input_fields=deployment['input_fields'],
                    limits={'starts_per_minute':deployment['minute_limit'],'starts_per_day':deployment['day_limit']})
    readme = f'''# Agent Concierge registered workflow app

Extract and deploy this folder to your own HTTP(S) server or any subdirectory.
Keep index.html and assets/ together. No build tool or provider credential is required.
Use HTTPS for production. A local HTTP server is recommended for preview; file://
support depends on browser file-origin/CSP rules and the deployment's origin policy.
All API traffic goes to https://agentconcierge.biz through the registered app API.

## Deployment controls

The publish key in this package is PUBLIC. It identifies and scopes this deployment;
it is not a secret, user login, billing authorization or proof of a visitor's identity.
The gateway checks the registered workflow, declared input bindings, allowed Origin,
per-app/IP minute limits, daily start limit and one-hour per-run capabilities.
Origin is a browser boundary; non-browser clients can forge it. Public template APIs
remain available independently. This is not an end-user paywall or a promise that
copied static files cannot be modified. Provider charges and paid fallback are not
automatically authorized. No commercial SLA is created by this package.

Allowed origins: {', '.join(deployment['allowed_origins']) or 'Any browser origin (including null/file previews)'}
Starts per minute: {deployment['minute_limit']} (also at most 5 per IP per minute)
Starts per UTC day: {deployment['day_limit']}

The admin export dialog lists deployments and can revoke one. Re-exporting creates
a separate key. Revoke old deployments when replacing them. Changes to the saved
workflow graph require a fresh export; the gateway rejects stale deployment bindings.
Run access keys stay only in a private WeakMap and request headers, expire after one
hour and cannot read a different deployment's run. Do not log capability headers.

## SDK 1.1.0

AgentConciergeWorkflow.createClient() reads the embedded app configuration. For reuse
in a custom page, pass the equivalent app_id, publish_key, workflow_id and input_fields.
The SDK supports run(workflowId, {{input, signal}}), status(handle), cancel(handle),
wait(handle, {{onUpdate, onRetry, onFallback, signal, intervalMs, timeoutMs}}).

input is an object keyed by the virtual field IDs in app-manifest.json. Only fields
selected by the administrator are accepted. Blank form fields use the workflow's
server-side defaults; source graph, provider URLs and hidden defaults are not exported.
Inputs are type/size checked and cannot supply tools, endpoints, credentials or graphs.

Only transient status GET failures (network/timeout, 429, 502/503/504) are retried,
up to three consecutive failures with bounded exponential delay, jitter and Retry-After.
Successful polling gradually slows to reduce traffic. Run and Cancel POST requests
are never automatically retried. Callback errors and invalid responses are not retried.
Polling deadlines/AbortSignal also stop in-flight status requests. A monitoring timeout
does not mean server cancellation. Resume status reconnects using the same run handle.

Stop locks immediately and aborts status polling before sending a single cancellation
request. It reports a request, not a completed cancellation; check final status before
starting again. An in-flight provider request may finish. Closing a tab loses the local
handle and does not cancel the server job. Use admin history for operational review.

Stable node IDs preserve unchanged result elements and their selection/scroll state.
Object outputs are formatted as JSON; all output uses textContent. onFallback and its
badge activate only for explicit gateway-confirmed fallback flags. The current runner
does not automatically switch agents or implement paid fallback. No telemetry, feedback
beacons or marketing data are sent automatically.

The existing server execution deadline still applies; client polling time is not a
promise of longer execution or guaranteed availability. This app requires an internet
connection. Keep its restrictive CSP and local assets. The Origin allowlist must match
the scheme, hostname and port of your deployed site. README examples are not server
credentials and no private provider endpoint is included.
'''
    files.update({'index.html':index, 'assets/agentconcierge-sdk.js':sdk, 'assets/app.js':app,
                  'assets/styles.css':css, 'app-manifest.json':json.dumps(manifest, indent=2), 'README.md':readme})
    if single_html:
        nonce = re.search(r'nonce="([^"]+)"', index)[1]
        index = index.replace('<link rel="stylesheet" href="assets/styles.css">', f'<style nonce="{nonce}">{css}</style>')
        index = index.replace("style-src &#x27;self&#x27;", "style-src &#x27;nonce-" + nonce + "&#x27;")
        for name, code in [('agentconcierge-sdk.js', sdk), ('app.js', app)]:
            index = index.replace(f'<script nonce="{nonce}" src="assets/{name}" defer></script>', '')
            safe_code = re.sub(r'</script', r'<\\/script', code, flags=re.I)
            index = index.replace('</body>', f'<script nonce="{nonce}">{safe_code}</script></body>')
        return index.encode(), filename.replace('-webapp.zip', '-app.html')
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = ZipInfo(name); info.compress_type = ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            archive.writestr(info, content.encode())
    return output.getvalue(), filename

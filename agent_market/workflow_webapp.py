"""Portable static web apps whose workflow traffic stays on the public gateway."""
from html import escape
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

GATEWAY = 'https://agentconcierge.biz'
SDK_VERSION = '1.0.0'
SOURCE = Path(__file__).parent / 'concierge' / 'workflow_app.js'


def export_config(workflow):
    from .workflows import public_template
    published = public_template(workflow)
    if published is None:
        raise ValueError('Publish a safe active template before exporting an executable app.')
    return {'workflow_id': published['id'], 'definition_hash': published['definition_hash'], 'title': published['name'],
            'description': published['description'], 'api_origin': GATEWAY,
            'execution_mode': 'server', 'sdk_version': SDK_VERSION,
            'package_format': 'static-zip', 'package_url': f"/admin/api/workflows/{published['id']}/export-app/package"}


def _section(source, name):
    return source.split('// BEGIN ' + name + '\n', 1)[1].split('// END ' + name, 1)[0]


def build_package(config):
    if config.get('api_origin') != GATEWAY or type(config.get('workflow_id')) is not int or not 0 < config['workflow_id'] < 2**31:
        raise ValueError('Invalid gateway workflow configuration.')
    if config.get('definition_hash') is not None and not re.fullmatch(r'[0-9a-f]{64}', str(config['definition_hash'])):
        raise ValueError('Invalid workflow definition hash.')
    source = SOURCE.read_text(encoding='utf-8')
    sdk = _section(source, 'WORKFLOW SDK') + '\nglobalThis.AgentConciergeWorkflow = Object.freeze({createClient:createAgentConciergeClient});\n'
    runtime = _section(source, 'WORKFLOW APP RUNTIME') + '\nstandaloneAppRuntime();\n'
    styles = source.split('<style nonce="${nonce}">', 1)[1].split('</style>', 1)[0]
    nonce = secrets.token_urlsafe(24)
    csp = f"default-src 'none'; script-src 'nonce-{nonce}'; script-src-attr 'none'; style-src 'self'; connect-src {GATEWAY}; object-src 'none'; base-uri 'none'; form-action 'none'"
    title = escape(config['title'], quote=True)
    description = escape(config['description'], quote=True)
    public_config = json.dumps({'workflow_id': config['workflow_id'], **({'definition_hash': config['definition_hash']} if config.get('definition_hash') else {})}, ensure_ascii=True).replace('<', '\\u003c')
    index = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=True)}">
<meta name="referrer" content="no-referrer">
<title>{title} — Agent Workflow</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta name="twitter:card" content="summary">
<link rel="stylesheet" href="assets/styles.css">
<script nonce="{nonce}" src="assets/agentconcierge-sdk.js" defer></script>
<script nonce="{nonce}" src="assets/app.js" defer></script>
</head><body><main><h1>{title}</h1><p>{description}</p>
<p>Workflow execution is processed by Agent Concierge. An internet connection is required.</p>
<button id="runAppBtn" type="button" aria-busy="false"><svg data-run-ready width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg><svg data-run-spinner class="app-run-spinner" hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a10 10 0 1 0 10 10"/></svg><span data-run-label>Run workflow</span></button>
<button id="cancelAppBtn" type="button" disabled>Stop</button>
<p id="appStatus" role="status" aria-live="polite">Ready</p><div id="stepsContainer"></div>
<script type="application/json" id="wfData" nonce="{nonce}">{public_config}</script>
</main><footer><a href="{GATEWAY}/#privacy" target="_blank" rel="noopener noreferrer">Privacy Policy</a> · <a href="{GATEWAY}/#tos" target="_blank" rel="noopener noreferrer">Terms of Service</a></footer></body></html>'''
    readme = f'''# Agent Concierge workflow web app

Deploy this folder on any static HTTP(S) server. No application server, package
installation, build step, platform credential or provider API key is needed.
Use HTTPS in production. Internet access to {GATEWAY} is required.

## Deploy

1. Extract the archive and keep index.html and assets/ together.
2. Upload the folder to your server's document root or any subdirectory.
3. Open index.html through your server and select Run workflow.

Relative asset paths support deployment at / or a path such as /apps/digest/.
For local preview, run `python3 -m http.server 8080 --bind 127.0.0.1` in this
folder, then open http://127.0.0.1:8080/ . No rewrite or local API proxy is needed.
Serve JavaScript as application/javascript and CSS as text/css. If your host sets
a Content-Security-Policy response header, allow these packaged assets and
connect-src {GATEWAY}; do not add unsafe-inline or unsafe-eval.

## Gateway SDK

assets/agentconcierge-sdk.js exposes AgentConciergeWorkflow.createClient().
It supports run(workflowId), status(handle), cancel(handle), and
wait(handle, {{onUpdate, signal, intervalMs, timeoutMs}}).

```javascript
const client = AgentConciergeWorkflow.createClient();
const handle = await client.run({config['workflow_id']});
const result = await client.wait(handle, {{onUpdate: renderStatus}});
```

The SDK sends all execution requests to {GATEWAY}:

- POST /api/workflows/run
- GET /api/workflows/runs/{{run_id}}
- POST /api/workflows/runs/{{run_id}}/cancel

Cross-origin requests use CORS without cookies. A run capability stays only in
the SDK instance's memory and travels in X-Workflow-Key. It is never included in
URLs, local storage, exported files or DOM output. Reloading the app forgets
that run handle. Do not add third-party scripts to pages handling run results.
Start requests are never automatically retried, to avoid duplicate executions.

The gateway validates and routes the current published workflow. This package
does not call provider endpoints or contain a copy of the private workflow graph.
Changes to the published workflow apply to future executions. If the publisher
disables or removes it, execution becomes unavailable. Hosting this app does not
create an offline or independent execution service. Provider availability and
gateway execution limits continue to apply. Adapt the UI and CSS for your site;
keep the SDK gateway address and capability protection intact.

SDK version: {SDK_VERSION}
'''
    manifest = {'format': 'agentconcierge-static-webapp-v1', 'sdk_version': SDK_VERSION,
                'workflow_id': config['workflow_id'], 'gateway': GATEWAY,
                'execution': 'published-workflow', 'entrypoint': 'index.html'}
    files = {'index.html': index, 'assets/agentconcierge-sdk.js': sdk,
             'assets/app.js': runtime, 'assets/styles.css': styles,
             'README.md': readme, 'app-manifest.json': json.dumps(manifest, indent=2)}
    archive = BytesIO()
    with ZipFile(archive, 'w', compression=ZIP_DEFLATED) as package:
        for name, content in files.items():
            entry = ZipInfo(name)
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            package.writestr(entry, content.encode('utf-8'))
    filename = (re.sub(r'[^a-z0-9]+', '-', config['title'].lower()).strip('-')[:72] or 'workflow') + '-webapp.zip'
    return archive.getvalue(), filename

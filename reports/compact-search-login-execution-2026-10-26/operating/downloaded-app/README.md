# Agent Concierge workflow web app

Deploy this folder on any static HTTP(S) server. No application server, package
installation, build step, platform credential or provider API key is needed.
Use HTTPS in production. Internet access to https://agentconcierge.biz is required.

## Deploy

1. Extract the archive and keep index.html and assets/ together.
2. Upload the folder to your server's document root or any subdirectory.
3. Open index.html through your server and select Run Workflow.

Relative asset paths support deployment at / or a path such as /apps/digest/.
For local preview, run `python3 -m http.server 8080 --bind 127.0.0.1` in this
folder, then open http://127.0.0.1:8080/ . No rewrite or local API proxy is needed.
Serve JavaScript as application/javascript and CSS as text/css. If your host sets
a Content-Security-Policy response header, allow these packaged assets and
connect-src https://agentconcierge.biz; do not add unsafe-inline or unsafe-eval.

## Gateway SDK

assets/agentconcierge-sdk.js exposes AgentConciergeWorkflow.createClient().
It supports run(workflowId), status(handle), cancel(handle), and
wait(handle, {onUpdate, signal, intervalMs, timeoutMs}).

```javascript
const client = AgentConciergeWorkflow.createClient();
const handle = await client.run(65);
const result = await client.wait(handle, {onUpdate: renderStatus});
```

The SDK sends all execution requests to https://agentconcierge.biz:

- POST /api/workflows/run
- GET /api/workflows/runs/{run_id}
- POST /api/workflows/runs/{run_id}/cancel

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

SDK version: 1.0.0

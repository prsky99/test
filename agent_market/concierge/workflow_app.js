// BEGIN WORKFLOW SDK
function createAgentConciergeClient() {
  const origin = 'https://agentconcierge.biz';
  const sessions = new WeakMap();
  const terminal = new Set(['succeeded', 'failed', 'cancelled']);
  function aborted() { return new DOMException('The request was cancelled.', 'AbortError'); }
  async function request(path, method, body, key, signal) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) throw aborted();
    signal?.addEventListener('abort', abort, {once:true});
    const timer = setTimeout(abort, 10000);
    try {
      const headers = {};
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (key) headers['X-Workflow-Key'] = key;
      const response = await fetch(origin + path, {method, headers,
        ...(body !== undefined ? {body:JSON.stringify(body)} : {}),
        mode:'cors', credentials:'omit', cache:'no-store', redirect:'error',
        referrerPolicy:'no-referrer', signal:controller.signal});
      if (!response.ok) {
        const message = response.status === 429 ? 'The workflow service is busy. Please try again later.' :
          response.status === 404 ? 'This workflow or run is unavailable.' : 'The workflow request could not be completed.';
        throw new Error(message);
      }
      try { return await response.json(); }
      catch (error) { throw new Error('The workflow service returned an unreadable response.'); }
    } finally {
      clearTimeout(timer); signal?.removeEventListener('abort', abort);
    }
  }
  function session(handle) {
    const value = handle && typeof handle === 'object' ? sessions.get(handle) : null;
    if (!value) throw new Error('Use the run handle returned by this client.');
    return value;
  }
  function pause(duration, signal) {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) return reject(aborted());
      const abort = () => { clearTimeout(timer); reject(aborted()); };
      const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, duration);
      signal?.addEventListener('abort', abort, {once:true});
    });
  }
  const client = {
    origin, version:'1.0.0',
    async run(workflowId, {signal, definitionHash} = {}) {
      if (!Number.isInteger(workflowId) || workflowId < 1 || workflowId >= 2147483648) throw new Error('Choose a published workflow.');
      if (definitionHash !== undefined && (typeof definitionHash !== 'string' || !/^[a-f0-9]{64}$/.test(definitionHash))) throw new Error('Choose a current published workflow.');
      const body = {template_id:workflowId};
      if (definitionHash !== undefined) body.definition_hash = definitionHash;
      const data = await request('/api/workflows/run', 'POST', body, null, signal);
      if (!data || typeof data !== 'object' || !/^wr_[a-f0-9]{32}$/.test(data.run_id || '') || !/^[A-Za-z0-9_-]{32,128}$/.test(data.run_key || '')) throw new Error('The workflow service returned an invalid run.');
      const handle = Object.freeze({runId:data.run_id, status:data.status});
      sessions.set(handle, {id:data.run_id, key:data.run_key});
      return handle;
    },
    async status(handle, {signal} = {}) {
      const value = session(handle);
      const data = await request('/api/workflows/runs/' + encodeURIComponent(value.id), 'GET', undefined, value.key, signal);
      if (!data || !['queued','running','succeeded','failed','cancelled'].includes(data.status)) throw new Error('The workflow service returned an invalid status.');
      return data;
    },
    async cancel(handle, {signal} = {}) {
      const value = session(handle);
      return request('/api/workflows/runs/' + encodeURIComponent(value.id) + '/cancel', 'POST', undefined, value.key, signal);
    },
    async wait(handle, {onUpdate, signal, intervalMs=700, timeoutMs=130000} = {}) {
      session(handle);
      if (!Number.isInteger(intervalMs) || intervalMs < 300 || intervalMs > 10000 || !Number.isInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 180000) throw new Error('Invalid workflow polling limits.');
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        const data = await client.status(handle, {signal});
        if (onUpdate) onUpdate(data);
        if (terminal.has(data.status)) return data;
        await pause(Math.min(intervalMs, Math.max(0, deadline-Date.now())), signal);
      }
      throw new Error('The run is still pending. Reopen AgentValCon to review its status.');
    }
  };
  return Object.freeze(client);
}
// END WORKFLOW SDK

// BEGIN WORKFLOW APP RUNTIME
function standaloneAppRuntime() {
  const cfg = JSON.parse(document.getElementById('wfData').textContent);
  const run = document.getElementById('runAppBtn');
  const cancel = document.getElementById('cancelAppBtn');
  const status = document.getElementById('appStatus');
  const output = document.getElementById('stepsContainer');
  let current = null;
  let running = false;
  let cancelling = false;
  const client = createAgentConciergeClient();
  function setRunning(value) {
    run.disabled = value;
    run.setAttribute('aria-busy', String(value));
    run.querySelector('[data-run-label]').textContent = value ? 'Running...' : 'Run Workflow';
    run.querySelector('[data-run-ready]').toggleAttribute('hidden', value);
    run.querySelector('[data-run-spinner]').toggleAttribute('hidden', !value);
  }
  function render(data) {
    status.textContent = 'Workflow: ' + data.status;
    output.replaceChildren();
    for (const item of data.results || data.node_results || []) {
      const card = document.createElement('section');
      const heading = document.createElement('h2');
      heading.textContent = item.name + ' · ' + item.status;
      const body = document.createElement('pre');
      body.textContent = item.output || item.error || '';
      card.append(heading, body); output.append(card);
    }
  }
  cancel.onclick = async () => {
    if (!running || !current || cancelling) return;
    const handle = current;
    cancelling = true;
    cancel.disabled = true;
    let requested = false;
    try {
      await client.cancel(handle);
      requested = true;
      if (!running || current !== handle) return;
      status.textContent = 'Cancellation requested. An in-flight request may finish before stopping.';
    } catch (error) {
      if (!running || current !== handle) return;
      status.textContent = error.message;
    } finally {
      if (!requested && running && current === handle) {
        cancelling = false;
        cancel.disabled = false;
      }
    }
  };
  run.onclick = async () => {
    if (running) return;
    running = true;
    setRunning(true);
    cancel.disabled = true;
    output.replaceChildren();
    status.textContent = 'Starting workflow...';
    try {
      current = await client.run(cfg.workflow_id, {definitionHash:cfg.definition_hash});
      cancel.disabled = false;
      status.textContent = 'Workflow: queued';
      await client.wait(current, {onUpdate:render});
    } catch (error) { status.textContent = error.message; }
    finally {
      running = false;
      cancelling = false;
      setRunning(false);
      cancel.disabled = true;
      current = null;
    }
  };
}
// END WORKFLOW APP RUNTIME

function buildWorkflowAppHTML(config) {
  const escapeHTML = value => String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const origin = 'https://agentconcierge.biz';
  if (config.api_origin && config.api_origin !== origin) throw new Error('This app uses the AgentValCon routing gateway.');
  if (!Number.isInteger(config.workflow_id) || config.workflow_id < 1) throw new Error('Choose a published template before exporting.');
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(24)), b => b.toString(16).padStart(2,'0')).join('');
  const data = JSON.stringify({workflow_id:config.workflow_id,api_origin:origin,...(config.definition_hash?{definition_hash:config.definition_hash}:{})}).replace(/</g,'\\u003c');
  const endScript = '</scr' + 'ipt>';
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; script-src-attr 'none'; style-src 'nonce-${nonce}'; connect-src ${escapeHTML(origin)}; object-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer"><title>${escapeHTML(config.title)} — Agent Workflow</title>
<meta name="description" content="Run a published agent workflow and view its recorded outcomes.">
<style nonce="${nonce}">:root{color-scheme:light dark;font-family:system-ui,sans-serif}body{max-width:850px;margin:40px auto;padding:20px}section{border:1px solid #8391a6;border-radius:16px;padding:16px;margin:16px 0}h2{font-size:1rem}button{display:inline-flex;align-items:center;gap:8px;border:1px solid #8391a6;border-radius:10px;padding:12px 18px;cursor:pointer}button:focus-visible{outline:3px solid #6366f1;outline-offset:3px}pre{white-space:pre-wrap;overflow-wrap:anywhere}button svg{flex-shrink:0}#runAppBtn:disabled{cursor:wait;color:CanvasText;opacity:.75}[hidden]{display:none!important}.app-run-spinner{animation:app-run-spin 1s linear infinite}@keyframes app-run-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.app-run-spinner{animation:none}}</style>
</head><body><h1>${escapeHTML(config.title)}</h1><p>${escapeHTML(config.description)}</p>
<p>This app connects to AgentValCon to run the current published template. Results depend on agent availability. It requires an internet connection.</p>
<button id="runAppBtn" type="button" aria-busy="false"><svg data-run-ready width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg><svg data-run-spinner class="app-run-spinner" hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a10 10 0 1 0 10 10"/></svg><span data-run-label>Run Workflow</span></button>
<button id="cancelAppBtn" type="button" disabled>Stop</button><p id="appStatus" role="status" aria-live="polite">Ready</p><div id="stepsContainer"></div>
<script type="application/json" id="wfData" nonce="${nonce}">${data}${endScript}
<script nonce="${nonce}">${createAgentConciergeClient.toString()}\n(${standaloneAppRuntime.toString()})();${endScript}</body></html>`;
}

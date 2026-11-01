function createAgentConciergeClient(config) {
  const cfg = config || JSON.parse(document.getElementById('wfData').textContent);
  const origin = 'https://agentconcierge.biz';
  const appId = cfg.app_id, publishKey = cfg.publish_key, workflowId = cfg.workflow_id;
  if (!/^app_[a-f0-9]{32}$/.test(appId || '') || typeof publishKey !== 'string' || !/^wfpk_[A-Za-z0-9_-]{43}$/.test(publishKey)) throw new Error('Use a registered application package.');
  const sessions = new WeakMap(), preparations = new WeakMap();
  if (cfg.profile !== 'literal-informational-deployment-v1' || cfg.sdk_version !== '1.2.0') throw new Error('Use a version 1.2 reviewed application package.');
  const terminal = new Set(['succeeded', 'failed', 'cancelled']);
  const base = '/api/workflow-apps-v12/' + appId;
  const path = base + '/runs';
  function fault(message, status=0, transient=false, retryAfter=0) {
    return Object.assign(new Error(message), {status, transient, retryAfter});
  }
  function aborted() { return new DOMException('The request was cancelled.', 'AbortError'); }
  async function request(url, method, body, key, signal, budgetMs=10000) {
    if (signal?.aborted) throw aborted();
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, {once:true});
    const timer = setTimeout(abort, Math.max(1, Math.min(10000, budgetMs)));
    try {
      const headers = {'X-Publish-Key':publishKey};
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (key) headers['X-Workflow-Key'] = key;
      let response;
      try {
        response = await fetch(origin + url, {method, headers,
          ...(body !== undefined ? {body:JSON.stringify(body)} : {}), mode:'cors',
          credentials:'omit', cache:'no-store', redirect:'error', referrerPolicy:'no-referrer', signal:controller.signal});
      } catch (error) {
        if (signal?.aborted) throw aborted();
        throw fault(controller.signal.aborted ? 'The workflow request timed out.' : 'The workflow connection is temporarily unavailable.', 0, true);
      }
      if (!response.ok) {
        const raw = response.headers.get('Retry-After');
        const seconds = raw && /^\d+$/.test(raw) ? Number(raw) : raw ? (Date.parse(raw)-Date.now())/1000 : 0;
        const retryAfter = Number.isFinite(seconds) ? Math.max(0, Math.min(60000, seconds*1000)) : 0;
        throw fault(response.status === 429 ? 'The application limit has been reached. Please wait before trying again.' :
          response.status === 404 || response.status === 403 || response.status === 401 ? 'This deployment or run is unavailable.' :
          'The workflow request could not be completed.', response.status, response.status === 429 || [502,503,504].includes(response.status), retryAfter);
      }
      try { return await response.json(); }
      catch (error) {
        if (signal?.aborted) throw aborted();
        if (controller.signal.aborted || error instanceof TypeError) throw fault('The workflow response was interrupted.', 0, true);
        throw fault('The workflow service returned an unreadable response.');
      }
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  }
  function session(handle) {
    const state = handle && typeof handle === 'object' ? sessions.get(handle) : null;
    if (!state) throw fault('Use the run handle returned by this client.');
    return state;
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
    origin, version:'1.2.0',
    async prepare({signal} = {}) {
      const data = await request(base + '/prepare', 'POST', {}, null, signal);
      const preview = data?.preview;
      if (!data?.ok || data.profile !== 'literal-informational-deployment-v1' || data.executed !== false || !data.proposal || typeof data.signature !== 'string' || !preview || !Number.isFinite(preview.expires) || !Array.isArray(preview.recipients) || !preview.recipients.length || preview.recipients.length > 2) throw fault('The application review could not be verified.');
      for (const item of preview.recipients) {
        if (!item || Object.keys(item).sort().join(',') !== 'contract,input,label' || typeof item.label !== 'string' || item.label.length > 200 || !['news.search.v1','docs.search.v1'].includes(item.contract) || !item.input || typeof item.input.query !== 'string' || item.input.query.length > 500 || item.input.language !== 'en' || !Number.isInteger(item.input.limit) || item.input.limit < 1 || item.input.limit > 5 || Object.keys(item.input).sort().join(',') !== (item.contract === 'news.search.v1' ? 'from_utc,language,limit,query' : 'language,limit,query')) throw fault('The application review contains unsupported inputs.');
      }
      const copy = JSON.parse(JSON.stringify(preview));
      for (const item of copy.recipients) {Object.freeze(item.input);Object.freeze(item);}
      Object.freeze(copy.recipients);Object.freeze(copy);
      const handle = Object.freeze({preview:copy});
      preparations.set(handle, {proposal:data.proposal, signature:data.signature, expires:preview.expires});
      return handle;
    },
    async run(id, options = {}) {
      if (!Number.isInteger(id) || id !== workflowId) throw fault('Use this application\'s reviewed workflow.');
      if (!options || typeof options !== 'object' || Array.isArray(options) || Object.keys(options).some(key => !['preparation','shareAuthority','liveAuthority','signal'].includes(key))) throw fault('Use a reviewed application preparation without dynamic inputs.');
      const {preparation,shareAuthority,liveAuthority,signal} = options;
      const review = preparation && preparations.get(preparation);
      if (!review || shareAuthority !== true || liveAuthority !== true) throw fault('Review the exact inputs and separately authorize sharing and one live run.');
      if (Date.now()/1000 >= review.expires) {preparations.delete(preparation); throw fault('The input review expired. Prepare a new review.');}
      preparations.delete(preparation);
      let data;
      try {
        data = await request(path, 'POST', {proposal:review.proposal,signature:review.signature,
          share_authority:true,share_notice:'workflow-app-v12-share-v1',
          live_authority:true,live_notice:'workflow-app-v12-run-v1'}, null, signal);
        if (!data || typeof data.run_id !== 'string' || !/^wr_[a-f0-9]{32}$/.test(data.run_id) || typeof data.run_key !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(data.run_key)) throw fault('The start response could not be verified.');
      } catch (error) {
        error.startUncertain = ![401,403,404,429].includes(error.status);
        throw error;
      }
      const handle = Object.freeze({runId:data.run_id, status:data.status});
      sessions.set(handle, {id:data.run_id, key:data.run_key, fallbackNotified:false});
      return handle;
    },
    async status(handle, {signal, budgetMs} = {}) {
      const state = session(handle);
      const data = await request(path + '/' + state.id, 'GET', undefined, state.key, signal, budgetMs);
      if (!data || !['queued','running','succeeded','failed','cancelled'].includes(data.status)) throw fault('The workflow service returned an invalid status.');
      return data;
    },
    async cancel(handle, {signal} = {}) {
      const state = session(handle);
      return request(path + '/' + state.id + '/cancel', 'POST', undefined, state.key, signal);
    },
    async wait(handle, {onUpdate, onFallback, onRetry, signal, intervalMs=1000, timeoutMs=130000} = {}) {
      const state = session(handle);
      if (!Number.isInteger(intervalMs) || intervalMs < 300 || intervalMs > 10000 || !Number.isInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 180000 || [onUpdate,onFallback,onRetry].some(f => f !== undefined && typeof f !== 'function')) throw fault('Invalid workflow polling options.');
      const deadline = Date.now() + timeoutMs;
      let errors = 0, interval = intervalMs;
      while (Date.now() < deadline) {
        let data;
        try { data = await client.status(handle, {signal, budgetMs:deadline-Date.now()}); }
        catch (error) {
          if (signal?.aborted || error.name === 'AbortError' || !error.transient || ++errors > 3) throw error;
          const delay = Math.max(error.retryAfter || 0, Math.min(10000, intervalMs * 2**errors)) + Math.floor(Math.random()*200);
          if (onRetry) onRetry({attempt:errors, delayMs:delay, status:error.status});
          await pause(Math.min(delay, Math.max(0, deadline-Date.now())), signal);
          continue;
        }
        errors = 0;
        if (onUpdate) onUpdate(data);
        const fallback = data.fallback_used === true || (Array.isArray(data.node_results) && data.node_results.some(n => n.fallback_used === true || n.is_fallback === true));
        if (fallback && !state.fallbackNotified) { state.fallbackNotified = true; if (onFallback) onFallback(data); }
        if (terminal.has(data.status)) return data;
        await pause(Math.min(interval, Math.max(0, deadline-Date.now())), signal);
        interval = Math.min(5000, Math.ceil(interval * 1.25));
      }
      throw fault('Status monitoring timed out. The server run may still be active.');
    }
  };
  return Object.freeze(client);
}
globalThis.AgentConciergeWorkflow = Object.freeze({createClient:createAgentConciergeClient});

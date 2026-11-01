// Versioned opt-in Edge execution. Authentication remains in memory and headers.
(function () {
  'use strict';
  const origin = 'https://agentconcierge.biz';
  const runPattern = /^er_[a-f0-9]{32}$/;
  const pathPattern = /^\/api\/(?:edge|origin)-gateway\/v1\/runs\/(er_[a-f0-9]{32})\/stream$/;
  function createClient({visitorToken}) {
    if (typeof visitorToken !== 'string' || !/^vt_[A-Za-z0-9_-]{16,96}$/.test(visitorToken)) throw new Error('Use an active visitor session.');
    const sessions = new WeakMap();
    async function request(path, {method = 'GET', body, token, signal} = {}) {
      if (typeof path !== 'string' || !path.startsWith('/api/') || path.includes('?') || path.includes('#')) throw new Error('Use an approved execution path.');
      const headers = {'X-Visitor-Token': visitorToken};
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (token) headers.Authorization = 'Bearer ' + token;
      return fetch(origin + path, {method, headers, ...(body === undefined ? {} : {body: JSON.stringify(body)}),
        credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer', signal});
    }
    function approved(value, id) {
      const match = typeof value?.stream_path === 'string' && value.stream_path.match(pathPattern);
      if (!runPattern.test(value?.run_id || '') || !match || match[1] !== value.run_id || id && id !== value.run_id ||
          typeof value.access_token !== 'string' || value.access_token.length > 2048) throw new Error('The execution grant is unavailable.');
      return value;
    }
    async function status(handle, {signal} = {}) {
      const state = sessions.get(handle);
      if (!state) throw new Error('Use this session’s execution handle.');
      const response = await request('/api/gateway-execution/v1/runs/' + handle.runId, {signal});
      if (!response.ok) throw new Error('The execution state could not be confirmed.');
      const value = await response.json();
      if (value.run_id !== handle.runId) throw new Error('The execution state could not be confirmed.');
      return value;
    }
    return Object.freeze({
      async prepare({resourceId, message, idempotencyKey, runAuthority, sharingAuthority, signal}) {
        if (runAuthority !== true || sharingAuthority !== true) throw new Error('Authorize this request and sharing with the selected agent.');
        const input = {message};
        const response = await request('/api/gateway-execution/v1/runs', {method: 'POST', signal,
          body: {resource_id: resourceId, input, idempotency_key: idempotencyKey, run_authority: true, sharing_authority: true}});
        if (!response.ok) throw new Error('This execution could not be prepared.');
        const grant = approved(await response.json());
        const handle = Object.freeze({runId: grant.run_id});
        sessions.set(handle, {grant, input: JSON.parse(JSON.stringify(input)), started: false});
        return handle;
      },
      status,
      async run(handle, {onDelta, signal} = {}) {
        const state = sessions.get(handle);
        if (!state || state.started || onDelta !== undefined && typeof onDelta !== 'function') throw new Error('Inspect the existing execution before starting again.');
        state.started = true;
        let response;
        const initialPath=state.grant.stream_path.replace('/api/origin-gateway/','/api/edge-gateway/');
        try { response = await request(initialPath, {method: 'POST', body: state.input, token: state.grant.access_token, signal}); }
        catch (error) { if (signal?.aborted) throw error; }
        if (!response?.ok) {
          // A transport failure proves nothing about Provider dispatch. Only a
          // still-prepared record may supply one explicit Origin attempt.
          const current = await status(handle, {signal});
          if (current.state !== 'prepared' || !current.stream_path?.startsWith('/api/origin-gateway/')) return current;
          state.grant = approved(current, handle.runId);
          response = await request(state.grant.stream_path, {method: 'POST', body: state.input, token: state.grant.access_token, signal});
          if (!response.ok) return await status(handle, {signal});
        }
        if (!response.headers.get('Content-Type')?.toLowerCase().startsWith('text/event-stream') || !response.body) throw new Error('The result stream is unavailable.');
        const reader = response.body.getReader(), decoder = new TextDecoder('utf-8', {fatal: true});
        let buffer = '', event = '', data = [], text = '', final = null, bytes = 0;
        try {
          while (true) {
            const chunk = await reader.read();
            if (chunk.done) break;
            bytes += chunk.value.byteLength;
            if (bytes > 262144) throw new Error('The result stream exceeded its limit.');
            buffer += decoder.decode(chunk.value, {stream: true});
            let at;
            while ((at = buffer.indexOf('\n')) >= 0) {
              const line = buffer.slice(0, at).replace(/\r$/, ''); buffer = buffer.slice(at + 1);
              if (line.startsWith('event:')) event = line.slice(6).trim();
              else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
              else if (!line) {
                if (data.length) {
                  const value = JSON.parse(data.join('\n'));
                  if (event === 'delta' && typeof value.text === 'string' && !final) {
                    text += value.text;
                    if (text.length > 48000) throw new Error('The result exceeded its limit.');
                    if (onDelta) onDelta(value.text);
                  } else if (event === 'result' && !final && ['succeeded', 'failed', 'outcome_unknown'].includes(value.state)) final = value;
                  else throw new Error('The result protocol could not be confirmed.');
                }
                event = ''; data = [];
              }
            }
            if (buffer.length > 65536 || data.join('\n').length > 65536) throw new Error('The result frame exceeded its limit.');
          }
          decoder.decode();
          if (!final || buffer.trim() || data.length) return await status(handle, {signal});
          return {...final, run_id: handle.runId, ...(final.output == null && final.state === 'succeeded' ? {output: {parts: [{kind: 'text', text}]}} : {})};
        } catch (error) {
          await reader.cancel().catch(() => {});
          if (signal?.aborted) throw error;
          return await status(handle, {signal});
        } finally { reader.releaseLock(); }
      }
    });
  }
  globalThis.AgentConciergeEdge = Object.freeze({version: '1.0.0', createClient});
})();

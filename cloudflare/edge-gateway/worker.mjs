// Provider bindings are received only over the authenticated control channel.
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const strictDecoder = new TextDecoder('utf-8', {fatal: true});
const keys = new Map();
const RUN = /^er_[a-f0-9]{32}$/;
const CODES = new Set(['AUTH_REQUIRED', 'ORIGIN_REQUIRED', 'ALREADY_CLAIMED', 'CAPACITY_EXCEEDED', 'SCHEMA_CHANGED', 'INPUT_CHANGED', 'POLICY_DENIED', 'EXPIRED']);

const hexPairs = Array.from({length: 256}, (_, b) => b.toString(16).padStart(2, '0'));
function hex(bytes) { let result = ''; for (const b of new Uint8Array(bytes)) result += hexPairs[b]; return result; }
function raw64(value) { return Uint8Array.from(atob(value), c => c.charCodeAt(0)); }
function unbase(value) { return raw64(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4)); }
async function sha(value) { return hex(await crypto.subtle.digest('SHA-256', typeof value === 'string' ? encoder.encode(value) : value)); }
async function key(env, purpose) {
  const id = purpose + ':' + env.SHARED_SECRET;
  if (!keys.has(id)) {
    if (typeof env.SHARED_SECRET !== 'string' || raw64(env.SHARED_SECRET).byteLength !== 32) throw new Error('Configuration');
    const master = await crypto.subtle.importKey('raw', raw64(env.SHARED_SECRET), {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
    const material = await crypto.subtle.sign('HMAC', master, encoder.encode(purpose));
    keys.set(id, crypto.subtle.importKey('raw', material, {name: 'HMAC', hash: 'SHA-256'}, false, ['sign', 'verify']));
  }
  return keys.get(id);
}
function object(value) { return value && typeof value === 'object' && !Array.isArray(value); }
function header(origin) {
  return {'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'private, no-store',
    'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'"};
}
function failure(code = 'UNAVAILABLE', status = 503) {
  const denied = status === 403;
  const message = denied ? (code === 'POLICY_DENIED'
    ? 'Security checks blocked this agent connection. Choose another agent, or ask the provider to review its published connection.'
    : 'This request is not authorized. Review the connection and authorization before trying again.')
    : 'The approved execution is unavailable. Review this run before trying again.';
  const body = {type: 'https://agentconcierge.biz/errors/' + code.toLowerCase().replaceAll('_','-'),
    title: denied ? 'Forbidden' : 'Request failed', status, error_code: code, message, detail: message, retryable: false};
  if (denied) body.next_action = {action: code === 'POLICY_DENIED' ? 'choose_another_agent' : 'review_authorization',
    url: code === 'POLICY_DENIED' ? '/new/en/explore.html' : '/customer/sign-in'};
  return new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/problem+json',
    'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}});
}
function inspectionNotice(value, origin, rid) {
  return {...value, gateway_mode: 'inspection_only', inspection_only: true, provider_url: null,
    provider_details_url: origin + '/api/agents/' + rid,
    payment_processed: false, payment_accepted: false, payment_forwarded: false, settlement_performed: false,
    instructions: 'This gateway only inspects provider payment requirements. Do not submit payment proofs here: it cannot accept, forward, or settle payments. Review the provider listing and terms separately.',
    next_action: {action: 'review_provider_terms', url: origin + '/api/agents/' + rid}};
}
async function boundedText(response, limit) {
  if (!response.body) throw new Error('Missing body');
  const reader = response.body.getReader(), parts = []; let size = 0;
  try {
    while (true) {
      const {value, done} = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error('Body limit');
      parts.push(value);
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
  if (parts.length === 1) return strictDecoder.decode(parts[0]);
  const all = new Uint8Array(size); let at = 0;
  for (const part of parts) { all.set(part, at); at += part.byteLength; }
  return strictDecoder.decode(all);
}
async function boundedJson(response, limit) { return JSON.parse(await boundedText(response, limit)); }
async function ticket(env, token, origin, run) {
  if (!/^[A-Za-z0-9_-]{1,1024}\.[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('Authorization');
  const [payload, signature] = token.split('.');
  if (!await crypto.subtle.verify('HMAC', await key(env, 'edge-ticket-v1'), unbase(signature), encoder.encode(payload))) throw new Error('Authorization');
  const value = JSON.parse(decoder.decode(unbase(payload))), now = Date.now() / 1000;
  if (!object(value) || Object.keys(value).sort().join(',') !== 'aud,exp,origin,run' ||
      value.aud !== 'platform-execution-gateway' || value.origin !== origin || value.run !== run ||
      !RUN.test(value.run) || !Number.isInteger(value.exp) || value.exp <= now || value.exp > now + 125) throw new Error('Authorization');
}
function controlOrigin(env) {
  const u = new URL(env.CONTROL_ORIGIN);
  if (u.protocol !== 'https:' || u.username || u.password || u.port && u.port !== '443' || u.pathname !== '/' || u.search || u.hash) throw new Error('Configuration');
  return u.origin;
}
async function control(env, operation, value, clientIP) {
  const path = '/api/edge-gateway-internal/v1/' + operation;
  const body = JSON.stringify(value), timestamp = String(Math.floor(Date.now() / 1000));
  const nonce = hex(crypto.getRandomValues(new Uint8Array(16)));
  const material = ['POST', path, timestamp, nonce, await sha(body)].join('\n');
  const signature = hex(await crypto.subtle.sign('HMAC', await key(env, 'edge-service-v1'), encoder.encode(material)));
  const base = controlOrigin(env);
  const headers = {'Content-Type': 'application/json', 'Accept-Encoding':'identity', 'X-Edge-Time': timestamp, 'X-Edge-Nonce': nonce, 'X-Edge-Signature': signature};
  // Preserve Cloudflare's client attribution only for our same-origin control
  // callback; never copy browser-supplied forwarding headers or Provider headers.
  if (base === env.PUBLIC_ORIGIN && typeof clientIP === 'string' && /^[0-9a-fA-F:.]{3,45}$/.test(clientIP)) headers['X-Real-IP'] = clientIP;
  const response = await fetch(base + path, {method: 'POST', redirect: 'manual', signal: AbortSignal.timeout(8000), headers, body});
  const result = await boundedJson(response, operation==='output-relay-read'?65536:24576);
  if (!response.ok) {
    const error = new Error('Control unavailable');
    error.code = CODES.has(result?.error_code) ? result.error_code : 'UNAVAILABLE';
    error.status = [400, 401, 403, 409, 410, 429, 503].includes(response.status) ? response.status : 503;
    throw error;
  }
  return result;
}

// Cache contains ciphertext only. A recipe from an authorized Origin response
// selects entries; neither a run ID nor the cache URL authorizes result access.
const resultMedia = 'application/vnd.agentconcierge.edge-result+json';
const resultPath = /^\/api\/(?:workflows\/runs\/[^/]+|workflow-apps(?:-v12)?\/[^/]+\/runs\/[^/]+|workspace(?:-flow)?-apps-v2\/[^/]+\/(?:runs\/[^/]+|history)|customer-organizations\/[^/]+\/authoring\/(?:drafts\/[^/]+\/snapshots\/[^/]+\/runs(?:\/[^/]+)?|typed\/flows\/[^/]+\/runs(?:\/[^/]+)?|templates\/drafts\/[^/]+\/runs))$/;
const resultPostPath = /^\/api\/(?:workflows\/run|workflow-apps(?:-v12)?\/[^/]+\/runs|workspace(?:-flow)?-apps-v2\/[^/]+\/runs|customer-organizations\/[^/]+\/authoring\/(?:drafts\/[^/]+\/snapshots\/[^/]+\/runs|typed\/flows\/[^/]+\/runs|templates\/drafts\/[^/]+\/runs))$/;
async function cipherKey(env) {
  const material = await crypto.subtle.sign('HMAC', await key(env, 'edge-result-cache-v1'), encoder.encode('encryption'));
  return crypto.subtle.importKey('raw', material, 'AES-GCM', false, ['encrypt', 'decrypt']);
}
async function cacheAddress(env, run, hash) {
  if (!RUN.test(run) || !/^[a-f0-9]{64}$/.test(hash)) throw new Error('Result binding');
  const name = hex(await crypto.subtle.sign('HMAC', await key(env, 'edge-result-cache-v1'), encoder.encode(run + ':' + hash)));
  return new Request(env.PUBLIC_ORIGIN + '/api/edge-gateway/v1/private-cache/' + name);
}
async function cacheResult(env, run, wire, hash) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv,
    additionalData: encoder.encode(env.PUBLIC_ORIGIN + ':' + run + ':' + hash)}, await cipherKey(env), encoder.encode(wire)));
  const bytes = new Uint8Array(12 + encrypted.length); bytes.set(iv); bytes.set(encrypted, 12);
  await caches.default.put(await cacheAddress(env, run, hash), new Response(bytes, {
    headers: {'Content-Type': 'application/octet-stream', 'Cache-Control': 'max-age=600'}}));
}
async function cachedResult(env, run, hash) {
  const response = await caches.default.match(await cacheAddress(env, run, hash));
  if (!response) throw new Error('Result cache unavailable');
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length < 29 || bytes.length > 65564) throw new Error('Result cache invalid');
  const wire = strictDecoder.decode(await crypto.subtle.decrypt({name: 'AES-GCM', iv: bytes.slice(0, 12),
    additionalData: encoder.encode(env.PUBLIC_ORIGIN + ':' + run + ':' + hash)}, await cipherKey(env), bytes.slice(12)));
  if (await sha(wire) !== hash) throw new Error('Result hash');
  return JSON.parse(wire);
}
function asciiJSON(value) {
  if (Array.isArray(value)) return '[' + value.map(asciiJSON).join(',') + ']';
  if (object(value)) return '{' + Object.keys(value).sort().map(k => asciiJSON(k) + ':' + asciiJSON(value[k])).join(',') + '}';
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4,'0'));
}
async function assemble(env, recipe, loaded = new Map()) {
  let nodes = 0, size = 0;
  const charge = item => {size += encoder.encode(JSON.stringify(item)).byteLength; if(size>2097152) throw new Error('Result size');return item;};
  async function value(node, depth = 0) {
    if (!Array.isArray(node) || depth > 32 || ++nodes > 12000) throw new Error('Result recipe');
    const [op, item] = node;
    if (op === 0 && node.length === 2 && (item === null || ['string','number','boolean'].includes(typeof item))) return charge(item);
    if (op === 1 && node.length === 4) {
      const [, run, hash, path] = node, id = run + ':' + hash;
      if (!Array.isArray(path) || path.length > 20) throw new Error('Result path');
      if (!loaded.has(id)) {
        if (loaded.size >= 32) throw new Error('Result count');
        loaded.set(id, cachedResult(env, run, hash));
      }
      let output = await loaded.get(id);
      for (const part of path) {
        if ((!object(output) && !Array.isArray(output)) || !Object.hasOwn(output, part)) throw new Error('Result path');
        output = output[part];
      }
      return charge(output);
    }
    if (op === 2 && node.length === 2 && object(item)) {
      const output = Object.create(null);
      for (const [k,v] of Object.entries(item)) output[k] = await value(v, depth+1);
      return output;
    }
    if (op === 3 && node.length === 2 && Array.isArray(item)) {
      const output = []; for (const child of item) output.push(await value(child, depth+1)); return output;
    }
    if (op === 4 && node.length === 3) {
      const output = asciiJSON(await value(item, depth+1));
      if (await sha(output) !== node[2]) throw new Error('Result serialization');
      return output;
    }
    if (op === 5 && node.length === 4 && Number.isSafeInteger(node[2]) && node[2] >= 0 && Number.isSafeInteger(node[3]) && node[3] >= node[2]) {
      const source = await value(item, depth+1); if (typeof source !== 'string') throw new Error('Result slice');
      return Array.from(source).slice(node[2], node[3]).join('');
    }
    if (op === 6 && node.length === 2 && Array.isArray(item)) {
      let output = ''; for (const child of item) {const part = await value(child, depth+1); if (typeof part !== 'string') throw new Error('Result concat'); output += part;}
      return output;
    }
    throw new Error('Result recipe');
  }
  if (!object(recipe) || recipe.version !== 1 || Object.keys(recipe).some(k=>!['recipe','version','recovery'].includes(k))) throw new Error('Result version');
  const output = JSON.stringify(await value(recipe.recipe));
  if (encoder.encode(output).byteLength > 2097152) throw new Error('Result size');
  return output;
}
async function signedOrigin(request, env, body, clientIP, marker, base=controlOrigin(env)) {
  const path = new URL(request.url).pathname;
  const timestamp = String(Math.floor(Date.now()/1000)), nonce = hex(crypto.getRandomValues(new Uint8Array(16)));
  const material = [request.method, path, timestamp, nonce, await sha(body || '')].join('\n');
  const signature = hex(await crypto.subtle.sign('HMAC', await key(env, 'edge-service-v1'), encoder.encode(material)));
  const headers = new Headers(request.headers);
  for (const name of ['X-Edge-Result-View','X-Edge-MCP-Prepare','X-Edge-Time','X-Edge-Nonce','X-Edge-Signature']) headers.delete(name);
  headers.set('Accept-Encoding','identity');
  headers.set(marker, 'v1'); headers.set('X-Edge-Time', timestamp); headers.set('X-Edge-Nonce', nonce); headers.set('X-Edge-Signature', signature);
  return originRequest(new Request(request.url, {method:request.method,headers,signal:request.signal}), body, clientIP, base + path);
}
async function resultView(request, env) {
  const ip = request.headers.get('CF-Connecting-IP');
  let recipe;
  try {
    const body = request.method === 'POST' ? await boundedText(request,262144) : undefined;
    const response = await signedOrigin(request, env, body, ip, 'X-Edge-Result-View');
    if (!response.ok || response.headers.get('Content-Type') !== resultMedia) {
      const headers = new Headers(response.headers); headers.set('X-Execution-Delivery', 'origin');
      return new Response(response.body, {status: response.status, headers});
    }
    recipe = await boundedJson(response, 32768);
    const output = await assemble(env, recipe), headers = new Headers(response.headers);
    headers.delete('X-Edge-Origin-Output');
    headers.delete('Content-Length'); headers.delete('Content-Encoding');
    headers.set('Content-Type','application/json'); headers.set('Cache-Control','private, no-store'); headers.set('X-Execution-Delivery','edge');
    return new Response(output, {headers});
  } catch {
    // This is a GET of the SAME persisted result, never an execution retry.
    let recovery = request;
    if(request.method==='POST') {
      const run = recipe?.recovery?.run_id;
      if(typeof run!=='string' || !/^[a-z]+_[a-f0-9]{32}$/.test(run)) return failure('OUTCOME_UNKNOWN',503);
      const path=new URL(request.url).pathname, target=path==='/api/workflows/run'?'/api/workflows/runs/'+run:path+'/'+run;
      if(!resultPath.test(target)) return failure('OUTCOME_UNKNOWN',503);
      const headers=new Headers(request.headers);
      for(const name of ['Content-Length','Content-Type','X-Edge-Result-View','X-Edge-Time','X-Edge-Nonce','X-Edge-Signature']) headers.delete(name);
      if(typeof recipe.recovery.workflow_key==='string') headers.set('X-Workflow-Key',recipe.recovery.workflow_key);
      recovery=new Request(env.PUBLIC_ORIGIN+target,{method:'GET',headers,signal:request.signal});
    }
    const response = await originRequest(recovery, undefined, ip), headers = new Headers(response.headers);
    headers.set('X-Execution-Delivery', 'origin');
    return new Response(response.body, {status: response.status, headers});
  }
}
async function machineCall(request, env, ctx) {
  const ip = request.headers.get('CF-Connecting-IP');
  let original, raw, grant, finalized=false;
  const known = new Map();
  async function finalize() {
    finalized=true;
    // This phase may read a saved success or a definitive failure receipt; it
    // cannot dispatch, even when the Provider result acknowledgement was lost.
    const final = await signedOrigin(request,env,JSON.stringify({...original,_edge_transport:{mode:'result',run_id:grant.run_id}}),ip,'X-Edge-MCP-Prepare');
    if (!final.ok || final.headers.get('Content-Type') !== resultMedia) {
      const headers = new Headers(final.headers); headers.set('X-Execution-Delivery','origin');
      return new Response(final.body,{status:final.status,headers});
    }
    const body = await assemble(env,await boundedJson(final,32768),known);
    const headers = new Headers(final.headers); headers.delete('Content-Length'); headers.delete('Content-Encoding');
    headers.set('Content-Type','application/json'); headers.set('Cache-Control','private, no-store'); headers.set('X-Execution-Delivery','edge');
    return new Response(body,{headers});
  }
  try {
    if (new URL(request.url).origin !== env.PUBLIC_ORIGIN) return failure('AUTH_REQUIRED',403);
    // A cross-site browser page keeps its Origin only on the direct path; the signed
    // preparation below would drop it, so the Origin applies its read-only page policy.
    const page = request.headers.get('Origin');
    if (page !== null && page !== env.PUBLIC_ORIGIN) return originRequest(request, request.body, ip);
    if (request.method !== 'POST' || new URL(request.url).search) return originRequest(request, request.body, ip);
    if (request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json' ||
        !['identity',null].includes(request.headers.get('Content-Encoding'))) return originRequest(request,request.body,ip);
    raw = await boundedText(request,65536);
    try {original=JSON.parse(raw);} catch {return originRequest(request,raw,ip);}
    if(encoder.encode(raw).byteLength>7900) return originRequest(request,raw,ip);
    if (!object(original) || original.jsonrpc !== '2.0' || original.method !== 'tools/call' ||
        !['number','string'].includes(typeof original.id) || typeof original.id === 'number' && !Number.isSafeInteger(original.id) ||
        typeof original.id === 'string' && original.id.length > 128 || !object(original.params) || original.params.name !== 'call' ||
        !object(original.params.arguments) || Object.hasOwn(original,'_edge_transport')) return originRequest(request,raw,ip);
    const args = original.params.arguments;
    if (args.idempotency_key === undefined) args.idempotency_key = hex(crypto.getRandomValues(new Uint8Array(16)));
    raw = JSON.stringify(original);
    const prepared = await signedOrigin(request,env,JSON.stringify({...original,_edge_transport:{mode:'prepare'}}),ip,'X-Edge-MCP-Prepare');
    if (!prepared.ok) throw new Error('Machine preparation unavailable');
    grant = await boundedJson(prepared,32768);
    if (grant.jsonrpc === '2.0') return jsonReply(grant);
    if (typeof grant.visitor?.token === 'string') args.visitor_token = grant.visitor.token;
    raw = JSON.stringify(original);
    if (grant.backend === 'origin') return originRequest(request,raw,ip);
    if (grant._edge_plan !== true || grant.backend !== 'worker' || !RUN.test(grant.run_id) ||
        grant.stream_path !== '/api/edge-gateway/v1/runs/' + grant.run_id + '/stream' || !object(grant.input)) throw new Error('Machine grant');
    await ticket(env,grant.access_token,env.PUBLIC_ORIGIN,grant.run_id);
    const binding = safeBinding(await control(env,'claim',{access_token:grant.access_token,origin:env.PUBLIC_ORIGIN,run_id:grant.run_id,input:grant.input},ip));
    if (binding.protocol !== 'mcp') throw new Error('Machine protocol');
    const response = await deliver(request,env,ctx,binding,grant.run_id,ip,true);
    if (response instanceof Response && !response.ok) throw new Error('Machine result');
    const normalized = response.output ? response : await normalizedResult(response);
    const output = normalized.output || normalized, wire = JSON.stringify(output), wire_hash = await sha(wire);
    if (encoder.encode(wire).byteLength > 65536) throw new Error('Machine result limit');
    if (response.finish) response.finish(encoder.encode(wire).byteLength);
    known.set(grant.run_id+':'+wire_hash,Promise.resolve(output));
    try { await cacheResult(env,grant.run_id,wire,wire_hash); } catch { /* Current response uses the in-memory result. */ }
    const saved = await control(env,'result',{run_id:grant.run_id,attempt_id:binding.attempt_id,wire,wire_hash},ip);
    if (saved.ok !== true || saved.run_id !== grant.run_id || saved.wire_hash !== wire_hash) throw new Error('Machine receipt');
    return await finalize();
  } catch {
    if(!finalized && grant?._edge_plan===true && RUN.test(grant.run_id)) {
      try {return await finalize();} catch { /* No execution retry on uncertain completion. */ }
    }
    // Control loss can hide a claimed Ticket. Pause instead of invoking Origin.
    return jsonReply({jsonrpc:'2.0',id:original?.id ?? null,result:{content:[{type:'text',text:'The execution outcome is unconfirmed. Keep this request paused for review.'}],
      structuredContent:{intent:'call',ok:false,execution:{ok:false,error_code:'UPSTREAM_PROTOCOL',outcome:'unknown',retry_safe:false}},isError:true}});
  }
}
function completion(env, ctx, value, clientIP) {
  // Retry only idempotent receipt metadata; never repeat a Provider execution.
  ctx.waitUntil((async () => {
    for (let attempt = 0; attempt < 3; attempt++) {
      try { await control(env, 'complete', value, clientIP); return; }
      catch (error) {
        const transient = error.status === undefined || [408,502,503,504].includes(error.status);
        if (!transient || attempt === 2) {
          console.warn(JSON.stringify({event: 'edge_completion_unconfirmed', attempts: attempt + 1,
            status: error.status || 0, code: CODES.has(error.code) ? error.code : 'UNAVAILABLE'}));
          return;
        }
        await new Promise(resolve => setTimeout(resolve, (attempt + 1) * 100));
      }
    }
  })());
}
function safeBinding(value) {
  const mode = value?.request_mode ?? 'stream';
  const kind = value?.protocol || 'a2a', spec = value?.spec_version || '0.3';
  const method = kind === 'mcp' ? 'tools/call' : kind === 'x402' ? 'probe' :
    spec === '1.0' ? (mode === 'stream' ? 'SendStreamingMessage' : 'SendMessage') : (mode === 'stream' ? 'message/stream' : 'message/send');
  if (!object(value) || !['a2a-03-informational-stream-v1', 'catalog-public-v1'].includes(value.profile) ||
      !['a2a', 'mcp', 'x402'].includes(kind) || !['0.3', '1.0'].includes(spec) ||
      value.profile !== 'catalog-public-v1' && (kind !== 'a2a' || spec !== '0.3') || !/^ea_[a-f0-9]{32}$/.test(value.attempt_id) ||
      !['stream', 'json'].includes(mode) || !object(value.request) ||
      value.request.method !== method || value.request.id !== value.attempt_id ||
      !Array.isArray(value.bindings) || value.bindings.length > 32 || value.max_frame_bytes !== 16384 ||
      value.max_output_bytes !== 48000 || value.timeout_ms !== 8000 ||
      !new RegExp('^https://agentconcierge\\.biz/api/gateway/' + kind + '/[1-9][0-9]*$').test(value.gateway_url)) throw new Error('Binding');
  const u = new URL(value.endpoint);
  if (u.protocol !== 'https:' || u.username || u.password || u.port && u.port !== '443' || kind === 'a2a' && u.search || u.hash ||
      !u.hostname.includes('.') || /^(?:[0-9.]+|\[.*\])$/.test(u.hostname) ||
      /(?:^|\.)(?:localhost|local|internal)$/.test(u.hostname)) throw new Error('Binding');
  return value;
}
function decodeURL(value) {
  let decoded = value.replace(/\\u([0-9a-f]{4})/gi, (_, s) => String.fromCharCode(parseInt(s, 16))).replace(/\\\//g, '/');
  for (let i = 0; i < 3; i++) { try { const next = decodeURIComponent(decoded); if (next === decoded) break; decoded = next; } catch { break; } }
  return decoded;
}
const projections = new WeakMap();
function projection(binding) {
  if (projections.has(binding)) return projections.get(binding);
  const bounds = binding.bindings.map(raw => new URL(decodeURL(raw)));
  const project = text => {
    if (typeof text !== 'string' || encoder.encode(text).byteLength > binding.max_frame_bytes) throw new Error('Text limit');
    const pattern = /https?(?::|%(?:25){0,2}3a|\\u003a)(?:\/|\\\/|%(?:25){0,2}2f|\\u002f){2}[^\s"'\x60<>\])}]+/gi;
    return text.replace(pattern, raw => {
      let candidate; try { candidate = new URL(decodeURL(raw.replace(/[.,;!?]+$/, ''))); } catch { return raw; }
      const path = candidate.pathname.replace(/\/$/, '') || '/';
      const bound = bounds.some(b => {
        if (candidate.origin !== b.origin) return false;
        const prefix = b.pathname.replace(/\/$/, '') || '/';
        return prefix === '/' || path === prefix || path.startsWith(prefix + '/');
      });
      return bound ? binding.gateway_url : raw;
    });
  };
  projections.set(binding, project);
  return project;
}
function event(name, value) { return encoder.encode('event: ' + name + '\ndata: ' + JSON.stringify(value) + '\n\n'); }

const secretNames = new Set(['key','apikey','xapikey','authorization','proxyauthorization','cookie','setcookie','password','passwd',
  'secret','clientsecret','privatekey','accesstoken','refreshtoken','visitortoken','token','credential','credentials','signature','sig','sessionid','mcpsessionid']);
function publicValue(value, binding, depth = 0) {
  if (depth > 12) return '[Depth limit]';
  if (Array.isArray(value)) {
    if (value.length > 5000) throw new Error('Collection limit');
    return value.map(v => publicValue(v, binding, depth + 1));
  }
  if (object(value)) {
    const result = Object.create(null);
    for (const k of Object.keys(value)) result[k] = secretNames.has(k.toLowerCase().replace(/[^a-z0-9]/g, '')) ? '[REDACTED]' : publicValue(value[k], binding, depth + 1);
    return result;
  }
  if (typeof value === 'string') {
    if (/^\s*[\[{]/.test(value)) {
      let parsed; try { parsed = JSON.parse(value); } catch { /* Plain text. */ }
      if (parsed !== undefined) return JSON.stringify(publicValue(parsed, binding, depth + 1));
    }
    const clean = value.replace(/\b(?:vt_[A-Za-z0-9_-]{16,128})\b/g, '[REDACTED_VISITOR_TOKEN]')
      .replace(/\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi, '$1 [REDACTED]')
      .replace(/\b(api[ _-]?key|access[ _-]?token|refresh[ _-]?token|visitor[ _-]?token|password|secret|credential)\s*[=:]\s*["']?[^\s"'&,;<>]+/gi, '$1=[REDACTED]');
    return projection(binding)(clean);
  }
  return typeof value === 'number' && !Number.isFinite(value) ? null : value;
}

function providerError(outcome, code) {
  const error = new Error('Provider execution unavailable');
  error.outcome = outcome; error.outcome_code = code;
  return error;
}

function normalize(value, binding, format, text) {
  let terminal = null;
  if (!object(value) || value.jsonrpc !== '2.0' || value.id !== binding.request.id ||
      Object.hasOwn(value, 'error') === Object.hasOwn(value, 'result')) throw new Error('Protocol');
  if (Object.hasOwn(value, 'error')) {
    if (!object(value.error) || !Number.isInteger(value.error.code) || typeof value.error.message !== 'string') throw new Error('Protocol');
    const rpcCode = value.error.code;
    throw providerError('failed', [-32601, -32004].includes(rpcCode) ? 'PROVIDER_METHOD_UNSUPPORTED' :
      rpcCode === -32602 ? 'PROVIDER_INPUT_REJECTED' : 'EXECUTION_FAILED');
  }
  if (!object(value.result)) throw new Error('Protocol');
  let obj = value.result;
  if (binding.spec_version === '1.0') {
    if (object(obj.message)) obj = {...obj.message, kind: 'message'};
    else if (object(obj.task)) obj = {...obj.task, kind: 'task'};
    else if (object(obj.statusUpdate)) obj = {...obj.statusUpdate, kind: 'status-update'};
    else if (object(obj.artifactUpdate)) obj = {...obj.artifactUpdate, kind: 'artifact-update'};
  }
  if (obj.kind === 'message') { text(obj.parts); terminal = 'succeeded'; }
  else if (obj.kind === 'artifact-update' && format === 'sse') { if (!object(obj.artifact)) throw new Error('Artifact'); text(obj.artifact.parts); }
  else if (obj.kind === 'task' || obj.kind === 'status-update') {
    if (obj.kind === 'status-update' && format !== 'sse') throw new Error('Protocol');
    const state = typeof obj.status?.state === 'string' ? obj.status.state.toLowerCase().replace(/^task_state_/, '').replace(/_/g, '-') : null;
    if (state === 'completed') terminal = 'succeeded';
    else if (['failed', 'canceled', 'cancelled', 'rejected', 'auth-required', 'input-required'].includes(state)) terminal = 'failed';
    else if (!['submitted', 'working'].includes(state)) throw new Error('Status');
    if (terminal !== 'failed' && obj.kind === 'task' && obj.artifacts !== undefined) {
      if (!Array.isArray(obj.artifacts) || obj.artifacts.length > 100) throw new Error('Artifacts');
      for (const artifact of obj.artifacts) { if (!object(artifact)) throw new Error('Artifact'); text(artifact.parts); }
    }
    if (terminal === 'succeeded' && obj.kind === 'task' && !obj.artifacts?.length && binding.profile === 'catalog-public-v1') {
      const statusMessage = obj.status?.message;
      const last = object(statusMessage) && ['agent','ROLE_AGENT'].includes(statusMessage.role) ? statusMessage : Array.isArray(obj.history) ? [...obj.history].reverse().find(m => ['agent','ROLE_AGENT'].includes(m?.role)) : null;
      if (last?.parts) text(last.parts);
    }
    if (format === 'json' && !terminal) throw providerError('outcome_unknown', 'PROVIDER_TASK_PENDING');
  } else throw new Error('Event contract');
  return terminal;
}

function projectedParts(binding) {
  const project = projection(binding); let output = 0;
  return parts => {
    const values = [];
    if (!Array.isArray(parts) || parts.length > 100) throw new Error('Parts');
    for (const part of parts) {
      if (!object(part)) throw new Error('Part contract');
      const raw = typeof part.text === 'string' && (part.kind === 'text' || binding.spec_version === '1.0') ? part.text :
        binding.profile === 'catalog-public-v1' && object(part.data) ? JSON.stringify(part.data) : null;
      if (raw === null) throw new Error('Part contract');
      const clean = binding.profile === 'catalog-public-v1' ? publicValue(raw, binding) : project(raw); output += encoder.encode(clean).byteLength;
      if (output > binding.max_output_bytes) throw new Error('Output limit');
      if (clean) values.push(clean);
    }
    return values;
  };
}
function jsonOutcome(value, binding) {
  const project = projectedParts(binding), texts = [], output = []; let size = 0;
  const terminal = normalize(value, binding, 'json', parts => {
    if (binding.profile !== 'catalog-public-v1') { texts.push(...project(parts)); return; }
    if (!Array.isArray(parts) || parts.length > 100) throw new Error('Parts');
    for (const part of parts) {
      if (!object(part)) throw new Error('Part');
      let clean;
      if (typeof part.text === 'string') clean = {kind: 'text', text: publicValue(part.text, binding)};
      else if (object(part.data)) clean = {kind: 'data', data: publicValue(part.data, binding)};
      else throw new Error('Part contract');
      size += encoder.encode(JSON.stringify(clean)).byteLength;
      if (size > binding.max_output_bytes) throw new Error('Output limit');
      output.push(clean);
    }
  });
  if (terminal !== 'succeeded') throw providerError(terminal || 'outcome_unknown', terminal === 'failed' ? 'EXECUTION_FAILED' : 'OUTCOME_UNKNOWN');
  if (!texts.length && !output.length) throw providerError('outcome_unknown', 'PROVIDER_PROTOCOL_INVALID');
  return {parts: output.length ? output : texts.map(text => ({kind: 'text', text}))};
}

function resultStream(upstream, binding, controller, completed, format) {
  const reader = upstream.body.getReader(), decode = new TextDecoder('utf-8', {fatal: true}), project = projectedParts(binding);
  let pending = [], buffer = '', lines = [], lineBytes = 0, received = 0, delivered = 0, terminal = null, closed = false, code = null;
  function text(parts) { for (const clean of project(parts)) pending.push(event('delta', {text: clean})); }
  function frame(raw) { terminal = normalize(JSON.parse(raw), binding, format, text) || terminal; }
  async function close(outcome, stream, outcomeCode = null) {
    if (closed) return; closed = true;
    controller.abort(); await reader.cancel().catch(() => {});
    code = outcomeCode || (outcome === 'succeeded' ? null : outcome === 'outcome_unknown' ? 'OUTCOME_UNKNOWN' : 'EXECUTION_FAILED');
    if (stream) {
      const final = event('result', {state: outcome, output: null, error_code: code});
      delivered += final.byteLength; stream.enqueue(final); stream.close();
    }
    completed(outcome, delivered, code);
  }
  function bufferedFrame() {
    let at;
    while ((at = buffer.search(/[\r\n]/)) >= 0) {
      // Defer a trailing CR until the next chunk to distinguish CRLF from CR.
      if (buffer[at] === '\r' && at === buffer.length - 1) return false;
      const line = buffer.slice(0, at);
      buffer = buffer.slice(at + (buffer[at] === '\r' && buffer[at + 1] === '\n' ? 2 : 1));
      lineBytes += encoder.encode(line).byteLength;
      if (lineBytes > binding.max_frame_bytes) throw new Error('Frame limit');
      if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''));
      else if (!line) {
        if (lines.length) frame(lines.join('\n'));
        lines = []; lineBytes = 0;
        if (pending.length || terminal) return true;
      }
    }
    if (encoder.encode(buffer).byteLength + lineBytes > binding.max_frame_bytes) throw new Error('Frame limit');
    return false;
  }
  return new ReadableStream({
    async pull(stream) {
      try {
        while (!pending.length && !terminal) {
          if (format === 'sse' && bufferedFrame()) break;
          const next = await reader.read();
          if (next.done) {
            buffer += decode.decode();
            if (format === 'json') frame(buffer);
            else if (buffer.endsWith('\r')) { buffer += '\n'; bufferedFrame(); }
            if (format === 'sse' && (buffer.trim() || lines.length) || !terminal) throw new Error('Incomplete stream');
            break;
          }
          received += next.value.byteLength;
          if (received > 65536) throw new Error('Response limit');
          buffer += decode.decode(next.value, {stream: true});
        }
        if (pending.length) { const chunk = pending.shift(); delivered += chunk.byteLength; stream.enqueue(chunk); return; }
        if (terminal) await close(terminal, stream);
      } catch (error) {
        pending = [];
        await close(error.outcome || 'outcome_unknown', stream, error.outcome_code || 'PROVIDER_PROTOCOL_INVALID');
      }
    },
    async cancel() { pending = []; await close('outcome_unknown'); }
  });
}

async function rpcBody(response, id) {
  if (!response.ok) {
    await response.body?.cancel();
    throw providerError('failed', [401,403].includes(response.status) ? 'PROVIDER_AUTH_REQUIRED' : 'EXECUTION_FAILED');
  }
  const media = response.headers.get('Content-Type')?.split(';')[0].toLowerCase().trim();
  if (media === 'application/json') return checkedRPC(await boundedJson(response, 65536), id);
  if (media !== 'text/event-stream' || !response.body) throw new Error('Protocol');
  // Native SSE parsing avoids rescanning the accumulated frame on each chunk.
  // The guard retains the raw byte cap and fatal UTF-8 validation before parsing.
  const decode = new TextDecoder('utf-8', {fatal: true}); let bytes = 0;
  const guarded = response.body.pipeThrough(new TransformStream({
    transform(chunk, controller) {
      bytes += chunk.byteLength; if (bytes > 65536) throw new Error('RPC limit');
      decode.decode(chunk, {stream: true}); controller.enqueue(chunk);
    },
    flush() { decode.decode(); }
  }));
  const source = EventSource.from(guarded);
  try {
    return await new Promise((resolve, reject) => {
      source.addEventListener('message', event => {
        try {
          const value = JSON.parse(event.data);
          if (value?.id === undefined && typeof value?.method === 'string') return;
          const result = checkedRPC(value, id); source.close(); resolve(result);
        } catch (error) { source.close(); reject(error); }
      });
      source.addEventListener('error', () => { source.close(); reject(new Error('Incomplete RPC')); });
    });
  } finally { source.close(); }
}
function checkedRPC(value, id) {
  if (!object(value) || value.jsonrpc !== '2.0' || value.id !== id || Object.hasOwn(value, 'error') === Object.hasOwn(value, 'result')) throw new Error('Protocol');
  if (value.error) {
    if (!object(value.error) || !Number.isInteger(value.error.code)) throw new Error('Protocol');
    const error = providerError('failed', value.error.code === -32601 ? 'PROVIDER_METHOD_UNSUPPORTED' : 'EXECUTION_FAILED');
    error.rpc_code = value.error.code; throw error;
  }
  if (!object(value.result)) throw new Error('Protocol');
  return value.result;
}
// A matching full-schema digest preserves the Origin's full input validation.
// Numeric/Unicode serialization differences use the existing signed review.
async function schemaMatches(tools, expected) {
  if (!/^[a-f0-9]{64}$/.test(expected || '') || !Array.isArray(tools) || tools.length > 1000) return false;
  const names = new Set();
  function sorted(value, depth = 0) {
    if (depth > 24 || typeof value === 'number' && (!Number.isFinite(value) || Number.isInteger(value) && !Number.isSafeInteger(value))) throw new Error('Schema limit');
    if (Array.isArray(value)) return value.map(v => sorted(v, depth + 1));
    if (object(value)) return Object.fromEntries(Object.keys(value).sort().map(k => [k, sorted(value[k], depth + 1)]));
    return value;
  }
  try {
    const full = tools.map(t => {
      if (!object(t) || typeof t.name !== 'string' || !t.name.length || t.name.length > 100 || names.has(t.name) ||
          !object(t.inputSchema) && typeof t.inputSchema !== 'boolean') throw new Error('Schema');
      names.add(t.name);
      return Object.fromEntries(['name','description','inputSchema','outputSchema','annotations'].filter(k => Object.hasOwn(t, k)).map(k => [k, t[k]]));
    }).sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    const text = JSON.stringify(sorted(full)).replace(/[\u0080-\uffff]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
    return await sha(text) === expected;
  } catch { return false; }
}
async function preparedMcpOutput(ctx, binding, signal) {
  const prepared = binding.mcp_prepared;
  if (!object(prepared) || !['2024-11-05','2025-03-26','2025-06-18','2025-11-25'].includes(prepared.protocol_version) ||
      !Number.isSafeInteger(prepared.deadline_ms) || prepared.deadline_ms <= Date.now() || prepared.deadline_ms > Date.now() + 8000 ||
      prepared.session_id !== null && (typeof prepared.session_id !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(prepared.session_id))) throw new Error('Preparation');
  const headers = {'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
    'Accept-Encoding': 'identity', 'Mcp-Protocol-Version': prepared.protocol_version};
  if (prepared.session_id) headers['Mcp-Session-Id'] = prepared.session_id;
  const remaining = AbortSignal.timeout(Math.max(1, prepared.deadline_ms - Date.now()));
  const deadline = AbortSignal.any([signal, remaining]);
  try {
    const response = await fetch(binding.endpoint, {method: 'POST', headers, signal: deadline, redirect: 'manual', body: JSON.stringify(binding.request)});
    const output = await rpcBody(response, binding.request.id);
    if (output.isError === true) throw providerError('failed', 'EXECUTION_FAILED');
    if (!Array.isArray(output.content) && !object(output.structuredContent)) throw new Error('Tool output');
    const clean = publicValue(output, binding);
    if (encoder.encode(JSON.stringify(clean)).byteLength > binding.max_output_bytes) throw new Error('Output limit');
    return clean;
  } finally {
    if (prepared.session_id && !prepared.cleanup) ctx.waitUntil(fetch(binding.endpoint, {method: 'DELETE', headers, redirect: 'manual', signal: AbortSignal.timeout(1500)})
      .then(r => r.body?.cancel()).catch(() => {}));
  }
}
async function mcpOutput(env, ctx, binding, run, clientIP, signal) {
  if (binding.mcp_prepared !== undefined) return preparedMcpOutput(ctx, binding, signal);
  const headers = {'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'Accept-Encoding': 'identity'};
  let session = null, dispatched = false;
  const rpc = async (method, params, id) => {
    const response = await fetch(binding.endpoint, {method: 'POST', headers, signal, redirect: 'manual', body: JSON.stringify({jsonrpc: '2.0', id, method, params})});
    const sid = response.headers.get('mcp-session-id'), result = await rpcBody(response, id);
    if (sid && ['initialize','server/discover'].includes(method)) {
      if (!/^[\x21-\x7e]{1,256}$/.test(sid)) throw new Error('Session');
      session = sid; headers['Mcp-Session-Id'] = sid;
    }
    return result;
  };
  try {
    let discovery;
    // The signed catalog observation selects a known handshake revision.
    // Unknown revisions retain automatic discovery; no browser hint is trusted.
    const pinned = ['2024-11-05','2025-03-26','2025-06-18','2025-11-25'].includes(binding.mcp_protocol_version) ? binding.mcp_protocol_version : null;
    if (!pinned) try { discovery = await rpc('server/discover', {}, 1); }
    catch (error) { if (![-32601,-32600].includes(error.rpc_code)) throw error; }
    if (!discovery?.protocolVersion) {
      discovery = await rpc('initialize', {protocolVersion: pinned || '2025-06-18', capabilities: {}, clientInfo: {name: 'agent-concierge', version: '1.0'}}, 1);
      if (typeof discovery.protocolVersion !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(discovery.protocolVersion)) throw new Error('Version');
      headers['Mcp-Protocol-Version'] = discovery.protocolVersion;
      const notify = await fetch(binding.endpoint, {method: 'POST', headers, signal, redirect: 'manual',
        body: JSON.stringify({jsonrpc: '2.0', method: 'notifications/initialized'})});
      await notify.body?.cancel(); if (!notify.ok) throw new Error('Initialization');
    }
    if (typeof discovery.protocolVersion !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(discovery.protocolVersion)) throw new Error('Version');
    headers['Mcp-Protocol-Version'] = discovery.protocolVersion;
    const listed = await rpc('tools/list', {}, 2);
    if (!Array.isArray(listed.tools)) throw new Error('Tools');
    if (!await schemaMatches(listed.tools, binding.mcp_schema_hash)) try {
      const review = await control(env, 'mcp-schema', {run_id: run, attempt_id: binding.attempt_id, tools: listed.tools,
        input: {tool: binding.request.params.name, arguments: binding.request.params.arguments}}, clientIP);
      if (review.approved !== true) throw new Error('Approval');
    } catch (error) { throw providerError('failed', error.code === 'SCHEMA_CHANGED' ? 'PROVIDER_SCHEMA_CHANGED' : 'EXECUTION_FAILED'); }
    dispatched = true;
    const output = await rpc('tools/call', binding.request.params, binding.request.id);
    if (output.isError === true) throw providerError('failed', 'EXECUTION_FAILED');
    if (!Array.isArray(output.content) && !object(output.structuredContent)) throw new Error('Tool output');
    const clean = publicValue(output, binding);
    if (encoder.encode(JSON.stringify(clean)).byteLength > binding.max_output_bytes) throw new Error('Output limit');
    return clean;
  } catch (error) {
    if (!dispatched && !error.outcome) throw providerError('failed', 'EXECUTION_FAILED');
    throw error;
  } finally {
    if (session) ctx.waitUntil(fetch(binding.endpoint, {method: 'DELETE', headers, redirect: 'manual', signal: AbortSignal.timeout(1500)})
      .then(r => r.body?.cancel()).catch(() => {}));
  }
}
function validChallenge(value) {
  if (!object(value) || ![1,2].includes(value.x402Version) || !Array.isArray(value.accepts) || !value.accepts.length || value.accepts.length > 20) return false;
  const safeURL = raw => {
    try { const u = new URL(raw); return ['http:','https:'].includes(u.protocol) && !u.username && !u.password && !u.hash &&
      u.hostname.includes('.') && !/^(?:[0-9.]+|\[.*\])$/.test(u.hostname) && !/(?:^|\.)(?:localhost|local|localdomain|internal|lan|home)$/.test(u.hostname) &&
      ![...u.searchParams.keys()].some(k => secretNames.has(k.toLowerCase().replace(/[^a-z0-9]/g,''))); } catch { return false; }
  };
  if (value.x402Version === 2 ? !safeURL(value.resource?.url) : typeof value.error !== 'string') return false;
  return value.accepts.every(a => object(a) && typeof (value.x402Version === 2 ? a.amount : a.maxAmountRequired) === 'string' && /^\d{1,78}$/.test(value.x402Version === 2 ? a.amount : a.maxAmountRequired) &&
    Number.isFinite(a.maxTimeoutSeconds) && a.maxTimeoutSeconds > 0 && ['scheme','network','asset','payTo'].every(k => typeof a[k] === 'string' && a[k].length > 0 && a[k].length <= 256) &&
    (value.x402Version !== 1 || safeURL(a.resource) && typeof a.description === 'string'));
}
async function probeOutput(binding, signal) {
  const response = await fetch(binding.endpoint, {method: 'GET', redirect: 'manual', signal, headers: {Accept: 'application/json', 'Accept-Encoding': 'identity'}});
  if (response.status >= 300 && response.status < 400) { await response.body?.cancel(); throw providerError('failed', 'PROVIDER_ENDPOINT_UNAVAILABLE'); }
  let output;
  if (response.status === 402) {
    const header = response.headers.get('payment-required');
    if (header && header.length < 48000) { try { output = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(raw64(header))); } catch { /* Try body. */ } }
    if (!validChallenge(output)) output = await boundedJson(response, 65536); else await response.body?.cancel();
    if (!validChallenge(output)) throw providerError('failed', 'EXECUTION_FAILED');
    const clean = publicValue(output, binding);
    if (encoder.encode(JSON.stringify(clean)).byteLength > binding.max_output_bytes) throw new Error('Output limit');
    return {status_code: 402, output: clean, execution_succeeded: false, protocol_valid: true, transport_ok: true,
      task_status: 'authorization-required', error_code: 'AUTH_REQUIRED'};
  }
  if (!response.ok) { await response.body?.cancel(); throw providerError('failed', 'EXECUTION_FAILED'); }
  const raw = await boundedText(response, 65536);
  try { output = JSON.parse(raw); } catch { output = raw; }
  output = publicValue(output, binding);
  if (encoder.encode(JSON.stringify(output)).byteLength > binding.max_output_bytes) throw new Error('Output limit');
  return {status_code: response.status, output, execution_succeeded: true, protocol_valid: true, transport_ok: true, task_status: 'completed'};
}
async function deliver(request, env, ctx, binding, run, clientIP, directJSON = false) {
  let aborter, timer;
  try {
      aborter = new AbortController();
      timer = setTimeout(() => aborter.abort(), binding.timeout_ms);
      request.signal.addEventListener('abort', () => aborter.abort(), {once: true});
      const complete = (outcome, bytes, code = null) => {
        clearTimeout(timer);
        completion(env, ctx, {run_id: run, attempt_id: binding.attempt_id, outcome, output_bytes: bytes, outcome_code: code,
          ...(binding.mcp_prepared?.cleanup ? {mcp_cleanup: binding.mcp_prepared.cleanup} : {})}, clientIP);
      };
      if (binding.protocol === 'mcp') {
        const output = await mcpOutput(env, ctx, binding, run, clientIP, aborter.signal);
        return {output, finish: bytes => complete('succeeded', bytes)};
      }
      if (binding.protocol === 'x402') {
        const managed = await probeOutput(binding, aborter.signal);
        return {managed, finish: bytes => complete(managed.execution_succeeded ? 'succeeded' : 'failed', bytes, managed.error_code ? 'PROVIDER_AUTH_REQUIRED' : null)};
      }
      const upstream = await fetch(binding.endpoint, {method: 'POST', redirect: 'manual', signal: aborter.signal,
        headers: {'Content-Type': 'application/json', Accept: binding.request.method === 'message/send' ? 'application/json, text/event-stream' : 'text/event-stream, application/json',
          'Accept-Encoding': 'identity', ...(binding.spec_version === '1.0' ? {'A2A-Version': '1.0'} : {})}, body: JSON.stringify(binding.request)});
      const media = upstream.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase();
      if (!upstream.ok) {
        await upstream.body?.cancel();
        const code = {404: 'PROVIDER_ENDPOINT_UNAVAILABLE', 401: 'PROVIDER_AUTH_REQUIRED', 403: 'PROVIDER_AUTH_REQUIRED', 429: 'PROVIDER_RATE_LIMITED'}[upstream.status];
        throw providerError(code ? 'failed' : 'outcome_unknown', code || 'OUTCOME_UNKNOWN');
      }
      if (!['text/event-stream', 'application/json'].includes(media) ||
          !upstream.body || !['identity', null].includes(upstream.headers.get('Content-Encoding'))) {
        await upstream.body?.cancel(); throw providerError('outcome_unknown', 'PROVIDER_PROTOCOL_INVALID');
      }
      const finish = (outcome, output_bytes, outcome_code) => {
        clearTimeout(timer);
        completion(env, ctx, {run_id: run, attempt_id: binding.attempt_id, outcome, output_bytes, outcome_code}, clientIP);
      };
      if (directJSON && media === 'application/json') {
        const output = jsonOutcome(await boundedJson(upstream, 65536), binding);
        return {output, finish: bytes => finish('succeeded', bytes, null)};
      }
      return new Response(resultStream(upstream, binding, aborter, finish, media === 'application/json' ? 'json' : 'sse'), {headers: header(env.PUBLIC_ORIGIN)});
  } catch (error) {
    if (timer) clearTimeout(timer); aborter?.abort();
    completion(env, ctx, {run_id: run, attempt_id: binding.attempt_id,
      outcome: error.outcome || 'outcome_unknown', outcome_code: error.outcome_code || 'OUTCOME_UNKNOWN',
      ...(binding.mcp_prepared?.cleanup ? {mcp_cleanup: binding.mcp_prepared.cleanup} : {})}, clientIP);
    const reply = failure('UNAVAILABLE', 503);
    // A classified Provider answer is not an Edge delivery fault; observedOutput strips this marker.
    if (error.outcome) reply.headers.set('X-Edge-Provider-Failure', '1');
    return reply;
  }
}

function jsonReply(value, status = 200, count) {
  const body = JSON.stringify(value);
  if (count) count(encoder.encode(body).byteLength);
  return new Response(body, {status, headers: {'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'"}});
}
async function originRequest(request, body, clientIP, target, token) {
  const headers = new Headers(request.headers);
  for (const name of ['X-Real-IP', 'X-Forwarded-For', 'CF-Connecting-IP', 'Content-Length']) headers.delete(name);
  if (typeof clientIP === 'string' && /^[0-9a-fA-F:.]{3,45}$/.test(clientIP)) headers.set('X-Real-IP', clientIP);
  if (token) { headers.set('Authorization', 'Bearer ' + token); headers.set('Origin', new URL(request.url).origin); }
  const response=await fetch(target || request.url, {method: request.method, headers, body, redirect: 'manual', signal: request.signal});
  const outputHeaders=new Headers(response.headers);outputHeaders.set('X-Edge-Origin-Output','1');
  return new Response(response.body,{status:response.status,headers:outputHeaders});
}
async function normalizedResult(response) {
  if (!response.ok || !response.headers.get('Content-Type')?.startsWith('text/event-stream')) throw new Error('Result unavailable');
  const reader = response.body.getReader(), decode = new TextDecoder('utf-8', {fatal: true});
  let buffer = '', name = '', data = [], bytes = 0, text = '', final = null;
  try {
    while (true) {
      const next = await reader.read(); if (next.done) break;
      bytes += next.value.byteLength; if (bytes > 262144) throw new Error('Result limit');
      buffer += decode.decode(next.value, {stream: true});
      let at;
      while ((at = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, at).replace(/\r$/, ''); buffer = buffer.slice(at + 1);
        if (line.startsWith('event:')) name = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
        else if (!line) {
          if (data.length) {
            const value = JSON.parse(data.join('\n'));
            if (name === 'delta' && typeof value.text === 'string' && !final) text += value.text;
            else if (name === 'result' && !final) final = value;
            else throw new Error('Result contract');
          }
          data = []; name = '';
        }
      }
      if (encoder.encode(text).byteLength > 48000) throw new Error('Result limit');
    }
    decode.decode();
    if (!final || buffer.trim() || data.length) throw new Error('Incomplete result');
    if (object(final.managed)) return {managed: final.managed};
    if (final.state !== 'succeeded') throw new Error('Execution unavailable');
    const parts = final.output?.parts || [{kind: 'text', text}];
    if (!Array.isArray(parts) || !parts.length || parts.some(p => !object(p) || typeof p.text !== 'string')) throw new Error('Result parts');
    return {parts};
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
function publicCORS(response) {
  const headers = new Headers(response.headers);
  headers.set('Access-Control-Allow-Origin', '*');
  headers.set('Access-Control-Expose-Headers', 'Payment-Required, X-AgentConcierge-Payment-Mode');
  return new Response(response.body, {status: response.status, headers});
}
const PAYMENT_HEADERS = ['payment-signature', 'x-payment', 'x-payment-signature', 'x-payment-tx'];
async function legacy(request, env, ctx, rid, testbench, kind = 'a2a') {
  const clientIP = request.headers.get('CF-Connecting-IP'), started = Date.now();
  let raw, input, original, requestId = null, method = 'message/send';
  try {
    if (new URL(request.url).origin !== env.PUBLIC_ORIGIN) return failure('AUTH_REQUIRED', 403);
    if (request.method === 'OPTIONS') return new Response(null, {status: 204, headers: {
      'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Idempotency-Key, A2A-Version, MCP-Protocol-Version, MCP-Session-Id', 'Access-Control-Max-Age': '600'}});
    if (new URL(request.url).search || request.method !== 'POST' && !(kind === 'x402' && request.method === 'GET'))
      return originRequest(request, request.body, clientIP);
    // An attached payment proof is never a probe: the origin explains why it is not processed.
    if (!testbench && kind === 'x402' && PAYMENT_HEADERS.some(name => request.headers.has(name)))
      return originRequest(request, request.method === 'GET' ? null : request.body, clientIP);
    if (request.method === 'GET') { original = {action: 'probe'}; input = original; }
    else {
      if (request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json' ||
          !['identity', null].includes(request.headers.get('Content-Encoding'))) return failure('INVALID_INPUT', 400);
      original = await boundedJson(request, 8192); raw = JSON.stringify(original);
      if (!object(original)) return failure('INVALID_INPUT', 400);
      if (testbench) {
        rid = original.resource_id;
        if (Object.keys(original).some(k => !['resource_id','tool','arguments','message','timeout_seconds'].includes(k)) ||
            original.tool !== undefined && typeof original.tool !== 'string' || original.message !== undefined && typeof original.message !== 'string' ||
            original.arguments !== undefined && !object(original.arguments) ||
            original.timeout_seconds !== undefined && ![8,10].includes(original.timeout_seconds)) return originRequest(request, raw, clientIP);
        input = {message: original.message || '', tool: original.tool || '', arguments: original.arguments || {}};
      } else if (kind === 'x402') {
        if (Object.keys(original).length !== 1 || original.action !== 'probe') return originRequest(request, raw, clientIP);
        input = {action: 'probe'};
      } else {
        requestId = original.id; method = original.method;
        const params = original.params || {};
        if (original.jsonrpc !== '2.0' || !['string','number'].includes(typeof requestId) ||
            typeof requestId === 'number' && !Number.isSafeInteger(requestId) || typeof requestId === 'string' && requestId.length > 128 || !object(params))
          return originRequest(request, raw, clientIP);
        if (kind === 'mcp') {
          if (method !== 'tools/call' || Object.keys(params).some(k => !['name','arguments'].includes(k)) || typeof params.name !== 'string' ||
              params.arguments !== undefined && !object(params.arguments)) return originRequest(request, raw, clientIP);
          input = {tool: params.name, arguments: params.arguments || {}};
        } else {
          const message = params.message || {}, config = params.configuration || {};
          if (!['message/send','SendMessage'].includes(method) || !object(message) || !object(config) ||
              Object.keys(params).some(k => !['message','configuration'].includes(k)) || message.taskId || message.contextId ||
              Object.keys(config).some(k => !['blocking','returnImmediately','acceptedOutputModes'].includes(k)) ||
              config.blocking !== undefined && config.blocking !== true || config.returnImmediately !== undefined && config.returnImmediately !== false ||
              !Array.isArray(message.parts) || !message.parts.length || message.parts.some(p => !object(p) || typeof p.text !== 'string'))
            return originRequest(request, raw, clientIP);
          input = {message: message.parts.map(p => p.text).join('\n')};
        }
      }
    }
    if (!Number.isInteger(rid) || rid <= 0 || rid >= 2**31) return originRequest(request, raw, clientIP);
    const identity = request.headers.get('Idempotency-Key') || hex(crypto.getRandomValues(new Uint8Array(16)));
    const grant = await control(env, 'public-prepare', {resource_id: rid, input, origin: env.PUBLIC_ORIGIN,
      idempotency_key: identity, ...(testbench ? {testbench: true} : {})}, clientIP);
    if (!grant.run_id) return originRequest(request, raw, clientIP);
    input = grant.input || input;
    if (!RUN.test(grant.run_id) || !/^\/api\/(?:edge|origin)-gateway\/v1\/runs\/er_[a-f0-9]{32}\/stream$/.test(grant.stream_path) ||
        !grant.stream_path.includes('/' + grant.run_id + '/') || typeof grant.access_token !== 'string') throw new Error('Grant');
    let response;
    if (grant.backend === 'worker') {
      const binding = safeBinding(grant.binding || await control(env, 'claim', {access_token: grant.access_token, origin: env.PUBLIC_ORIGIN, run_id: grant.run_id, input}, clientIP));
      if (!testbench && kind !== (binding.protocol || 'a2a')) throw new Error('Protocol');
      kind = binding.protocol || 'a2a';
      response = await deliver(request, env, ctx, binding, grant.run_id, clientIP, true);
    } else if (grant.backend === 'origin' && grant.stream_path.startsWith('/api/origin-gateway/')) {
      const headers=new Headers(request.headers);headers.set('Authorization','Bearer '+grant.access_token);headers.set('Origin',env.PUBLIC_ORIGIN);
      response = await signedOrigin(new Request(env.PUBLIC_ORIGIN+grant.stream_path,{method:'POST',headers,signal:request.signal}),env,JSON.stringify(input),clientIP,'X-Edge-Origin-Relay',env.PUBLIC_ORIGIN);
    } else throw new Error('Grant');
    const normalized = response.output || response.managed ? response : await normalizedResult(response);
    const count = response.output || response.managed ? response.finish : undefined;
    const output = normalized.output || normalized;
    const managed = normalized.managed;
    if (managed) kind = managed.protocol || kind;
    const reply=(value,status=200,done)=>{const result=jsonReply(value,status,done);if(grant.backend==='origin')result.headers.set('X-Edge-Origin-Output','1');return result;};
    if (!testbench) {
      if (kind === 'x402') {
        if (managed.status_code === 402) {
          const notice = inspectionNotice(managed.output, env.PUBLIC_ORIGIN, rid);
          let paymentHeader;
          if (managed.output.x402Version === 2) {
            const bytes = encoder.encode(JSON.stringify(notice));
            if (bytes.byteLength > 12000) throw new Error('Challenge header limit');
            paymentHeader = btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''));
          }
          const result = reply(notice, 402, count);
          result.headers.set('X-AgentConcierge-Payment-Mode', 'inspection-only');
          if (paymentHeader) result.headers.set('Payment-Required', paymentHeader);
          return result;
        }
        return reply({ok: managed.execution_succeeded, is_error: !managed.execution_succeeded, simulated: false, protocol: 'x402',
          error_message: managed.execution_succeeded ? null : 'Provider authorization is required.', ...managed}, request.method === 'GET' ? managed.status_code : 200, count);
      }
      const body = managed ? managed.output : output;
      if (managed && !managed.execution_succeeded) {
        const failed = new Error('Execution unavailable');
        failed.provider = typeof managed.error_code === 'string' && /^[A-Z_]{3,40}$/.test(managed.error_code) ? managed.error_code : 'PROVIDER_FAILED';
        throw failed;
      }
      if (kind === 'mcp') return reply({jsonrpc: '2.0', id: requestId, result: body}, 200, count);
      let result = {kind: 'message', role: 'agent', messageId: hex(crypto.getRandomValues(new Uint8Array(16))), parts: body.parts};
      if (method === 'SendMessage') result = {message: {role: 'ROLE_AGENT', messageId: result.messageId,
        parts: body.parts.map(p => p.kind === 'data' ? {data: p.data} : {text: p.text})}};
      return reply({jsonrpc: '2.0', id: requestId, result}, 200, count);
    }
    const success = managed ? managed.execution_succeeded : true, body = managed ? managed.output : output;
    const result = {ok: success, execution_succeeded: success, transport_ok: true, protocol_valid: true,
      task_status: managed?.task_status || 'completed', status_code: managed?.status_code || 200, protocol: kind,
      output: JSON.stringify(body, null, 2), error_message: success ? null : 'Provider authorization is required.', is_error: !success, simulated: false,
      ...(managed?.error_code ? {error_code: managed.error_code} : {}),
      latency_scope: 'gateway-operation', latency_ms: Date.now() - started, tested_at: Date.now() / 1000,
      request_wire: {url: env.PUBLIC_ORIGIN + '/api/test/execute', path: '/api/test/execute', method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: original, scope: 'client-to-gateway', sanitized: true},
      response_wire: {scope: 'gateway-result', simulated: false, transport_ok: true, protocol_valid: true,
        task_status: managed?.task_status || 'completed', execution_succeeded: success, result: body}};
    return reply(result, 200, count);
  } catch (error) {
    // A claimed or ambiguous dispatch never falls back by repeating execution.
    if (error.status === 403) return failure(CODES.has(error.code) ? error.code : 'AUTH_REQUIRED', 403);
    // 11-11: every failure here read "The execution is unavailable." with no code (7 of 30 real tasks were
    // our own rate gate). The reason code, whether a retry can help and what to do instead are public;
    // no Provider detail, address or internal path is included.
    if (!testbench && kind !== 'x402') return jsonReply({jsonrpc: '2.0', id: requestId, error: {code: -32000,
      message: 'The execution is unavailable.', data: gatewayFailure(error)}}, 200);
    return failure(CODES.has(error.code) ? error.code : 'UNAVAILABLE', error.status || 503);
  }
}

const gateway = {
  async fetch(request, env, ctx) {
    const path = new URL(request.url).pathname;
    if (path === '/mcp') return env.DIRECT_RESULTS_ENABLED === 'true' ? machineCall(request,env,ctx) : originRequest(request,request.body,request.headers.get('CF-Connecting-IP'));
    if (new URL(request.url).origin === env.PUBLIC_ORIGIN && request.method === 'GET' && resultPath.test(path))
      return env.DIRECT_RESULTS_ENABLED === 'true' && !new URL(request.url).search ? resultView(request,env) : originRequest(request,undefined,request.headers.get('CF-Connecting-IP'));
    if (new URL(request.url).origin === env.PUBLIC_ORIGIN && request.method === 'POST' && resultPostPath.test(path))
      return env.DIRECT_RESULTS_ENABLED === 'true' && !new URL(request.url).search ? resultView(request,env) : originRequest(request,request.body,request.headers.get('CF-Connecting-IP'));
    // Cloudflare Routes allow trailing wildcards, not infix wildcards. The
    // containing families also include consent, cancel, SDK and CORS handlers.
    // Preserve their original authorization and protocol behavior unchanged.
    if (/^\/api\/(?:owned-data-agents\/|workflows\/run|workflow-apps\/|workflow-apps-v12\/|workspace-apps-v2\/|workspace-flow-apps-v2\/|customer-organizations\/)/.test(path)
        || path.startsWith('/mcp')) return originRequest(request,request.body,request.headers.get('CF-Connecting-IP'));
    const publicGateway = path.match(/^\/api\/gateway\/(a2a|mcp|x402)\/([1-9][0-9]*)$/);
    if (publicGateway || path === '/api/test/execute') return publicCORS(await legacy(request, env, ctx, Number(publicGateway?.[2]), !publicGateway, publicGateway?.[1] || 'a2a'));
    if (path === '/api/edge-gateway/v1/health' && request.method === 'POST') {
      try {
        if (new URL(request.url).origin !== env.PUBLIC_ORIGIN || new URL(request.url).search) return failure('AUTH_REQUIRED', 403);
        const timestamp = request.headers.get('X-Edge-Time') || '', nonce = request.headers.get('X-Edge-Nonce') || '';
        const signature = request.headers.get('X-Edge-Signature') || '';
        if (!/^[0-9]{10}$/.test(timestamp) || Math.abs(Date.now() / 1000 - Number(timestamp)) > 30 || !/^[a-f0-9]{32}$/.test(nonce) || !/^[a-f0-9]{64}$/.test(signature)) return failure('AUTH_REQUIRED', 401);
        const raw=await boundedText(request,256),value=JSON.parse(raw);
        const probe=object(value) && Object.keys(value).sort().join(',')==='probe,size' && value.probe==='direct-result' && [2,40000].includes(value.size);
        if (!object(value) || Object.keys(value).length && !probe) return failure('AUTH_REQUIRED', 401);
        const material = ['POST', path, timestamp, nonce, await sha(raw)].join('\n');
        const bytes = Uint8Array.from(signature.match(/../g), s => parseInt(s, 16));
        if (!await crypto.subtle.verify('HMAC', await key(env, 'edge-service-v1'), bytes, encoder.encode(material))) return failure('AUTH_REQUIRED', 401);
        if(probe) {
          const run='er_'+nonce,parts=[];
          for(let left=value.size;left>0;left-=Math.min(left,15000))parts.push({kind:'text',text:'A'.repeat(Math.min(left,15000))});
          const wire=JSON.stringify({parts}),hash=await sha(wire);
          await cacheResult(env,run,wire,hash);
          if(await assemble(env,{version:1,recipe:[1,run,hash,[]]})!==wire)throw new Error('Delivery probe');
        }
        const body = JSON.stringify({backend: 'worker', nonce, utc_day: new Date().toISOString().slice(0, 10),
          ...(probe?{probe:'direct-result',size:value.size}:{})});
        const proof = hex(await crypto.subtle.sign('HMAC', await key(env, 'edge-health-v1'), encoder.encode(body)));
        return new Response(body, {headers: {'Content-Type': 'application/json', 'Cache-Control': 'private, no-store', 'X-Edge-Health-Signature': proof}});
      } catch { return failure(); }
    }
    const matched = path.match(/^\/api\/edge-gateway\/v1\/runs\/(er_[a-f0-9]{32})\/stream$/);
    if (!matched || request.method !== 'POST' || new URL(request.url).search) return failure('INVALID_REQUEST', 404);
    const origin = request.headers.get('Origin') || env.PUBLIC_ORIGIN;
    if (!clientOrigin(origin) || new URL(request.url).origin !== env.PUBLIC_ORIGIN) return failure('AUTH_REQUIRED', 403);
    let token, input, binding;
    const clientIP = request.headers.get('CF-Connecting-IP');
    const run = matched[1];
    try {
      const auth = request.headers.get('Authorization') || '';
      if (!auth.startsWith('Bearer ') || request.headers.get('Content-Type')?.split(';')[0] !== 'application/json' ||
          !['identity', null].includes(request.headers.get('Content-Encoding'))) return failure('AUTH_REQUIRED', 401);
      token = auth.slice(7);
      try { await ticket(env, token, origin, run); } catch { return failure('AUTH_REQUIRED', 401); }
      input = await boundedJson(request, 8192);
      const receipt = request.headers.get('X-Edge-Result-Format') === 'receipt';
      if (receipt && env.DIRECT_RESULTS_ENABLED !== 'true') return failure('UNAVAILABLE');
      const nativeJSON = receipt || request.headers.get('X-Edge-Result-Format') === 'json';
      const messageInput = object(input) && Object.keys(input).join(',') === 'message' && typeof input.message === 'string';
      const toolInput = object(input) && Object.keys(input).sort().join(',') === 'arguments,tool' && typeof input.tool === 'string' && object(input.arguments);
      const probeInput=object(input) && Object.keys(input).join(',')==='action' && input.action==='probe';
      if (!messageInput && !(nativeJSON && (toolInput||probeInput))) return failure('INVALID_INPUT', 400);
      binding = safeBinding(await control(env, 'claim', {access_token: token, origin, run_id: run, input}, clientIP));
      if(origin!==env.PUBLIC_ORIGIN && binding.admin_delivery!==true) throw new Error('Delivery authority');
      if (nativeJSON) {
        const response = await deliver(request, env, ctx, binding, run, clientIP, true);
        if (response instanceof Response && !response.ok) return response;
        const normalized = response.output || response.managed ? response : await normalizedResult(response);
        if (receipt) {
          const wire = JSON.stringify(normalized.output || normalized), wire_hash = await sha(wire);
          if (encoder.encode(wire).byteLength > 65536) throw new Error('Result size');
          if (response.finish) response.finish(encoder.encode(wire).byteLength);
          // Cache is optional; durable inbound persistence is required for a
          // receipt. A lost receipt never authorizes another Provider call.
          try { await cacheResult(env, run, wire, wire_hash); } catch { /* Recover the existing Origin result on a later GET. */ }
          const saved = await control(env, 'result', {run_id: run, attempt_id: binding.attempt_id, wire, wire_hash}, clientIP);
          if (!object(saved) || saved.ok !== true || saved.run_id !== run || saved.wire_hash !== wire_hash) throw new Error('Result receipt');
          return jsonReply({run_id: run, state: 'succeeded', wire_hash, backend: 'worker'});
        }
        return jsonReply({run_id: run, state: normalized.managed?.execution_succeeded===false?'failed':'succeeded', output: normalized.output || (normalized.managed?{managed:normalized.managed}:normalized), backend: 'worker'}, 200, response.finish);
      }
      return await deliver(request, env, ctx, binding, run, clientIP);
    } catch (error) {
      return failure(CODES.has(error.code) ? error.code : 'UNAVAILABLE', error.status || 503);
    }
  }
};

function clientOrigin(value) {
  try {const u=new URL(value);return ['http:','https:'].includes(u.protocol) && !u.username && !u.password && u.origin===value;}
  catch {return false;}
}
async function outputRelay(request,env) {
  const url=new URL(request.url),path=url.pathname;
  if(url.origin!==env.PUBLIC_ORIGIN||url.search)return failure('AUTH_REQUIRED',403);
  if(path==='/api/edge-gateway/v1/output-publish'&&request.method==='POST') {
    try {
      const timestamp=request.headers.get('X-Edge-Time')||'',nonce=request.headers.get('X-Edge-Nonce')||'',signature=request.headers.get('X-Edge-Signature')||'';
      if(!/^[0-9]{10}$/.test(timestamp)||Math.abs(Date.now()/1000-Number(timestamp))>30||!/^[a-f0-9]{32}$/.test(nonce)||!/^[a-f0-9]{64}$/.test(signature))return failure('AUTH_REQUIRED',401);
      const raw=await boundedText(request,262144),material=['POST',path,timestamp,nonce,await sha(raw)].join('\n');
      if(!await crypto.subtle.verify('HMAC',await key(env,'edge-service-v1'),Uint8Array.from(signature.match(/../g),x=>parseInt(x,16)),encoder.encode(material)))return failure('AUTH_REQUIRED',401);
      const value=JSON.parse(raw);
      if(!object(value)||Object.keys(value).sort().join(',')!=='hash,run,wire'||!RUN.test(value.run)||typeof value.wire!=='string'||encoder.encode(value.wire).byteLength>65536||await sha(value.wire)!==value.hash)throw Error('Output binding');
      JSON.parse(value.wire);
      await cacheResult(env,value.run,value.wire,value.hash);
      return jsonReply({ok:true,run:value.run,hash:value.hash});
    } catch{return failure('UNAVAILABLE',503);}
  }
  const matched=path.match(/^\/api\/edge-gateway\/v1\/outputs\/(er_[a-f0-9]{32})$/);
  if(!matched||request.method!=='GET')return failure('INVALID_REQUEST',404);
  try {
    const header=request.headers.get('Authorization')||'',token=header.startsWith('Bearer ')?header.slice(7):'';
    if(!/^[A-Za-z0-9_-]{1,1024}\.[A-Za-z0-9_-]{43}$/.test(token))return failure('AUTH_REQUIRED',401);
    const [payload,signature]=token.split('.');
    if(!await crypto.subtle.verify('HMAC',await key(env,'edge-output-relay-v1'),unbase(signature),encoder.encode(payload)))return failure('AUTH_REQUIRED',401);
    const value=JSON.parse(decoder.decode(unbase(payload))),now=Date.now()/1000,origin=request.headers.get('Origin')||env.PUBLIC_ORIGIN;
    if(!object(value)||Object.keys(value).sort().join(',')!=='aud,exp,hash,origin,run'||value.aud!=='edge-output-relay-v1'||value.run!==matched[1]||value.origin!==origin||!clientOrigin(origin)||!Number.isInteger(value.exp)||value.exp<=now||value.exp>now+125)return failure('AUTH_REQUIRED',401);
    let result,relayed=false;
    try{result=await cachedResult(env,value.run,value.hash);}
    catch{relayed=true;result=await control(env,'output-relay-read',{run:value.run,capability:token,origin},request.headers.get('CF-Connecting-IP'));}
    // Only a cache miss reads through Origin; a local cache hit is a direct Edge delivery.
    const response=jsonReply(result),headers=new Headers(response.headers);if(relayed)headers.set('X-Edge-Origin-Output','1');
    return new Response(response.body,{status:response.status,headers});
  } catch{return failure('RESULT_UNAVAILABLE',503);}
}
export function gatewayFailure(error) {
  const code = error.provider || (CODES.has(error.code) ? error.code : 'UNAVAILABLE');
  const reason = {CAPACITY_EXCEEDED: 'rate_limited', AUTH_REQUIRED: 'not_authorized', POLICY_DENIED: 'policy_blocked',
    SCHEMA_CHANGED: 'tool_changed', INPUT_CHANGED: 'input_changed', EXPIRED: 'expired', ALREADY_CLAIMED: 'already_running',
    ORIGIN_REQUIRED: 'not_authorized', PROVIDER_FAILED: 'provider_error', UPSTREAM_TOOL_ERROR: 'provider_error',
    PROVIDER_TIMEOUT: 'provider_timeout', PROVIDER_AUTH_REQUIRED: 'provider_auth_required'}[code]
    || (error.provider ? 'provider_error' : 'gateway_unavailable');
  const retryable = ['rate_limited', 'provider_timeout', 'gateway_unavailable', 'already_running'].includes(reason);
  return {error_code: reason, retryable, ...(reason === 'rate_limited' ? {retry_after_seconds: 60} : {}),
    next: retryable ? 'Retry later, or call find_agents for another agent.' : 'Call find_agents for another agent for this task.'};
}
function outputSource(path) {
  if(path.startsWith('/api/edge-gateway/v1/outputs/'))return 'admin';
  if(path==='/chat'||path==='/')return 'chat';if(path==='/a2a'||path==='/a2a/')return 'a2a';if(path==='/mcp')return 'mcp';
  if(path.startsWith('/api/owned-data-agents/'))return 'mcp';
  if(path.includes('workspace')||path.includes('customer-organizations'))return 'workspace';
  if(path.includes('workflow'))return 'workflow';return 'public';
}
function chatUnavailable(status=503) {
  return jsonReply({error_code:'UPSTREAM_UNAVAILABLE',error:'Chat is temporarily unavailable. Please try again shortly.'},status);
}
function chatResponse(request,response) {
  const path=new URL(request.url).pathname;
  if(request.method!=='POST'||!['/chat','/'].includes(path)||response.status<500||
      response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()==='application/json')return response;
  // An intermediary's HTML outage page cannot satisfy Chat's JSON contract.
  // Cancel its body without buffering it or retrying the completed POST.
  if(response.body)response.body.cancel().catch(()=>{});
  const safe=chatUnavailable(response.status),headers=new Headers(response.headers);
  for(const name of ['Content-Length','Content-Encoding','ETag'])headers.delete(name);
  for(const [name,value]of safe.headers)headers.set(name,value);
  return new Response(safe.body,{status:response.status,headers});
}
function observedOutput(request,response,env,ctx,failureReason) {
  const path=new URL(request.url).pathname;
  const eligible=resultPath.test(path)||resultPostPath.test(path)||/^\/api\/(?:owned-data-agents\/[^/]+\/mcp|gateway\/(?:a2a|mcp|x402)\/[1-9][0-9]*|test\/execute|edge-gateway\/v1\/(?:runs\/er_[a-f0-9]{32}\/stream|outputs\/er_[a-f0-9]{32}))$/.test(path)||['/chat','/a2a','/a2a/','/mcp','/'].includes(path)&&request.method==='POST';
  if(!eligible||request.method==='OPTIONS')return response;
  const headers=new Headers(response.headers),providerFailure=headers.get('X-Edge-Provider-Failure')==='1';
  headers.delete('X-Edge-Provider-Failure');
  if(headers.get('X-Execution-Delivery')==='origin')headers.set('X-Edge-Origin-Recovery','same-result');
  headers.set('X-Execution-Delivery','edge');
  const id='eo_'+hex(crypto.getRandomValues(new Uint8Array(16))),source=outputSource(path);let bytes=0,observed=false;
  const observe=(outcome,reason)=>{
    if(observed)return;observed=true;
    reason=reason||(headers.get('X-Edge-Origin-Output')==='1'?'origin_relay':'delivered');
    const observation={id,outcome,source,reason,bytes:Math.min(bytes,2097152)};
    ctx.waitUntil(control(env,'output-observation',observation,request.headers.get('CF-Connecting-IP')).catch(async error=>{
      // Older Origin releases accept only the original reason vocabulary.
      // Retry identical observation identity, never the business request.
      if(error.status===400 && !['delivered','origin_relay','edge_error'].includes(reason))
        await control(env,'output-observation',{...observation,reason:'edge_error'},request.headers.get('CF-Connecting-IP')).catch(()=>{});
    }));
  };
  // HTTP failures are distinct from a broken delivery stream. Keep the original
  // status/body and never replay a POST whose processing may have started.
  // 501 is the Origin's deliberate x402 "payments are not forwarded" answer, delivered intact.
  if(response.status===501&&!failureReason){observe('edge');return new Response(response.body,{status:response.status,headers});}
  if(response.status>=500){observe('error',failureReason||(providerFailure?'provider_failed':null)||(headers.get('X-Edge-Origin-Output')==='1'?'origin_http_':'edge_http_')+response.status);return new Response(response.body,{status:response.status,headers});}
  if(!response.body){observe('edge');return new Response(null,{status:response.status,headers});}
  const stream=new TransformStream({transform(chunk,controller){bytes+=chunk.byteLength;controller.enqueue(chunk);},flush(){observe('edge');}});
  ctx.waitUntil(response.body.pipeTo(stream.writable).catch(()=>observe('error',request.signal.aborted?'client_cancelled':'stream_error')));
  return new Response(stream.readable,{status:response.status,headers});
}
export default {
  async fetch(request,env,ctx) {
    const path=new URL(request.url).pathname;
    const relay=path==='/api/edge-gateway/v1/output-publish'||/^\/api\/edge-gateway\/v1\/outputs\/er_[a-f0-9]{32}$/.test(path);
    const eligible=/^\/api\/edge-gateway\/v1\/runs\/er_[a-f0-9]{32}\/stream$/.test(path)||relay;
    if(!eligible){
      let response;
      // '/a2a/' (trailing slash) reaches the same Origin handler; some A2A clients post there (11-10).
      if(['/','/chat','/a2a','/a2a/'].includes(path)){
        try{response=await originRequest(request,request.body,request.headers.get('CF-Connecting-IP'));}
        catch{
          // A lost connection does not prove that Origin skipped processing.
          // Return bounded JSON without copying an upstream URL or exception.
          const safe=request.method==='POST'&&['/chat','/'].includes(path)?chatUnavailable():failure('UPSTREAM_UNAVAILABLE',503);
          return observedOutput(request,safe,env,ctx,request.signal.aborted?'client_cancelled':'origin_unavailable');
        }
      }else response=await gateway.fetch(request,env,ctx);
      return observedOutput(request,chatResponse(request,response),env,ctx);
    }
    const origin=request.headers.get('Origin');
    const cors=clientOrigin(origin)?{'Access-Control-Allow-Origin':origin,'Vary':'Origin'}:{};
    if(request.method==='OPTIONS')return new Response(null,{status:204,headers:{...cors,
      'Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Authorization, Content-Type, X-Edge-Result-Format',
      'Cache-Control':'private, no-store'}});
    const response=relay?await outputRelay(request,env):await gateway.fetch(request,env,ctx),headers=new Headers(response.headers);
    for(const [k,v] of Object.entries(cors))headers.set(k,v);
    return observedOutput(request,new Response(response.body,{status:response.status,headers}),env,ctx);
  }
};

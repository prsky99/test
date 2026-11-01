import assert from 'node:assert/strict';
import {createHmac, createHash, randomBytes} from 'node:crypto';
import {test} from 'node:test';
import {Miniflare, Response as EdgeResponse} from 'miniflare';
import {fileURLToPath} from 'node:url';
import worker from './worker.mjs';

const origin = 'https://agentconcierge.biz', controlOrigin = 'https://control.example';
const secret = Buffer.alloc(32, 'e'), run = 'er_' + 'a'.repeat(32), attempt = 'ea_' + 'b'.repeat(32);
const endpoint = 'https://provider.example/api', gateway = origin + '/api/gateway/a2a/1';
const derive = purpose => createHmac('sha256', secret).update(purpose).digest();
function ticket(clientOrigin = origin) {
  const payload = Buffer.from(JSON.stringify({aud: 'platform-execution-gateway', run, origin:clientOrigin,
    exp: Math.floor(Date.now() / 1000) + 120})).toString('base64url');
  return payload + '.' + createHmac('sha256', derive('edge-ticket-v1')).update(payload).digest('base64url');
}
const frame = result => 'data: ' + JSON.stringify({jsonrpc: '2.0', id: attempt, result}) + '\n\n';
const delta = text => frame({kind: 'artifact-update', artifact: {parts: [{kind: 'text', text}]}});
const done = frame({kind: 'status-update', status: {state: 'completed'}, final: true});
const path = '/api/edge-gateway/v1/runs/' + run + '/stream';

async function fixture(provider, overrides = {}, controlBase = controlOrigin, options = {}) {
  const calls = [], receipts = [], results = [], observations = []; let claimed = false, complete;
  const completion = new Promise(resolve => { complete = resolve; });
  const binding = {attempt_id: attempt, endpoint, gateway_url: gateway, bindings: [endpoint],
    request: {jsonrpc: '2.0', id: attempt, method: 'message/stream', params: {message: {parts: [{kind: 'text', text: 'Weather?'}]}}},
    max_frame_bytes: 16384, max_output_bytes: 48000, timeout_ms: 8000, profile: 'a2a-03-informational-stream-v1', ...overrides};
  const mf = new Miniflare({modules: true, scriptPath: fileURLToPath(new URL('./worker.mjs', import.meta.url)),
    compatibilityDate: '2026-07-30', compatibilityFlags: ['enable_request_signal'], port: 0,
    bindings: {PUBLIC_ORIGIN: origin, CONTROL_ORIGIN: controlBase, SHARED_SECRET: secret.toString('base64'),
      DIRECT_RESULTS_ENABLED: options.direct ? 'true' : 'false'},
    outboundService: async request => {
      const u = new URL(request.url);
      if(u.origin===controlBase&&u.pathname.endsWith('/output-observation')) {
        const body=await request.text(),stamp=request.headers.get('X-Edge-Time'),nonce=request.headers.get('X-Edge-Nonce');
        const material=[request.method,u.pathname,stamp,nonce,createHash('sha256').update(body).digest('hex')].join('\n');
        assert.equal(request.headers.get('X-Edge-Signature'),createHmac('sha256',derive('edge-service-v1')).update(material).digest('hex'));
        observations.push(JSON.parse(body));
        if(options.legacyObservations && !['edge_error','delivered','origin_relay'].includes(JSON.parse(body).reason))
          return new EdgeResponse('{"error_code":"INVALID_INPUT"}',{status:400,headers:{'Content-Type':'application/json'}});
        return new EdgeResponse('{"ok":true}',{headers:{'Content-Type':'application/json'}});
      }
      calls.push(request);
      if (u.origin === controlBase && (u.pathname.startsWith('/api/edge-gateway-internal/') || options.directOrigin)) {
        const raw = await request.text(), nonce = request.headers.get('X-Edge-Nonce'), timestamp = request.headers.get('X-Edge-Time');
        const material = [request.method, u.pathname, timestamp, nonce, createHash('sha256').update(raw).digest('hex')].join('\n');
        assert.equal(request.headers.get('X-Edge-Signature'), createHmac('sha256', derive('edge-service-v1')).update(material).digest('hex'));
        const body = raw ? JSON.parse(raw) : null;
        if (!u.pathname.startsWith('/api/edge-gateway-internal/')) return options.directOrigin(request, body, results);
        if(u.pathname.endsWith('/output-relay-read')) {assert.ok(options.relayRead);assert.equal(body.run,run);return new EdgeResponse(JSON.stringify(options.relayRead),{headers:{'Content-Type':'application/json'}});}
        if (u.pathname.endsWith('/result')) {
          assert.equal(body.run_id,run); assert.equal(body.attempt_id,attempt);
          assert.equal(body.wire_hash,createHash('sha256').update(body.wire).digest('hex'));
          results.push(body);
          if(options.resultAckLost) return new EdgeResponse('{"error_code":"UNAVAILABLE"}',{status:503,headers:{'Content-Type':'application/json'}});
          return new EdgeResponse(JSON.stringify({ok:true,run_id:run,wire_hash:body.wire_hash}),{headers:{'Content-Type':'application/json'}});
        }
        if (u.pathname.endsWith('/public-prepare')) {
          if (options.prepareDenied) return new EdgeResponse(JSON.stringify({error_code: 'POLICY_DENIED', detail: 'private control policy'}), {status: 403, headers: {'Content-Type': 'application/json'}});
          assert.equal(body.resource_id, 1);
          if (!binding.protocol || binding.protocol === 'a2a') assert.equal(body.input.message, 'Weather?');
          return new EdgeResponse(JSON.stringify(options.grant || {backend: 'worker', run_id: run, stream_path: path, access_token: ticket(), binding}),
            {headers: {'Content-Type': 'application/json'}});
        }
        if (u.pathname.endsWith('/mcp-schema')) {
          assert.equal(body.run_id, run); assert.equal(body.attempt_id, attempt);
          assert.deepEqual(body.input, {tool: binding.request.params.name, arguments: binding.request.params.arguments});
          return new EdgeResponse(JSON.stringify(options.reviewDenied ? {error_code: 'SCHEMA_CHANGED'} : {approved: true}),
            {status: options.reviewDenied ? 409 : 200, headers: {'Content-Type': 'application/json'}});
        }
        if (u.pathname.endsWith('/claim')) {
          if (claimed) return new EdgeResponse(JSON.stringify({error_code: 'ALREADY_CLAIMED'}), {status: 409});
          claimed = true;
          assert.equal(body.run_id, run);
          return new EdgeResponse(JSON.stringify(binding), {headers: {'Content-Type': 'application/json'}});
        }
        assert.ok(u.pathname.endsWith('/complete'));
        if (options.completeResponses?.length) {
          const status = options.completeResponses.shift();
          if (status !== 200) return new EdgeResponse('{"error_code":"UNAVAILABLE"}', {status, headers: {'Content-Type': 'application/json'}});
        }
        receipts.push(body); complete(body);
        return new EdgeResponse('{"ok":true}', {headers: {'Content-Type': 'application/json'}});
      }
      if (u.origin === origin) {
        assert.ok(options.originResponse, 'No unexpected Origin result-body request');
        return options.originResponse(request);
      }
      assert.equal(request.url, endpoint, 'No unexpected network target is permitted');
      assert.equal(request.headers.get('Authorization'), null);
      assert.equal(request.headers.get('Cookie'), null);
      assert.equal(request.headers.get('X-Real-IP'), null);
      assert.equal(request.headers.get('CF-Connecting-IP'), null);
      if (!['mcp','x402'].includes(binding.protocol)) assert.equal((await request.clone().json()).method, binding.request.method);
      return typeof provider === 'function' ? await provider(request) : new EdgeResponse(provider, {headers: {
        'Content-Type': 'text/event-stream', 'Location': endpoint, 'Link': '<' + endpoint + '>', 'X-Provider-Debug': 'private'}});
    }});
  return {mf, calls, receipts, results, observations, completion, async sendLegacy(testbench = false, headers = {}) {
    const kind = binding.protocol || 'a2a';
    const payload = kind === 'mcp' ? {jsonrpc: '2.0', id: 'caller-1', method: 'tools/call', params: binding.request.params} :
      kind === 'x402' ? {action: 'probe'} : {jsonrpc: '2.0', id: 'caller-1', method: options.clientMethod || 'message/send', params: {message: {parts: [{kind: 'text', text: 'Weather?'}]}}};
    return mf.dispatchFetch(origin + (testbench ? '/api/test/execute' : '/api/gateway/' + kind + '/1'), {method: options.get ? 'GET' : 'POST',
      headers: {'Content-Type': 'application/json', Origin: origin, ...headers},
      ...(options.get ? {} : {body: JSON.stringify(testbench ? {resource_id: 1, message: 'Weather?',
        ...(kind === 'mcp' ? {tool: binding.request.params.name, arguments: binding.request.params.arguments} : {})} : payload)})});
  }, async send(headers = {}) {
    return mf.dispatchFetch(origin + path, {method: 'POST', headers: {Origin: origin, Authorization: 'Bearer ' + ticket(),
      'Content-Type': 'application/json', Cookie: 'private-cookie', ...headers}, body: JSON.stringify({message: 'Weather?'})});
  }};
}

test('workerd streams the first event before the Provider completes', async () => {
  let release;
  const upstream = new ReadableStream({start(controller) {
    controller.enqueue(new TextEncoder().encode(delta('First chunk')));
    release = () => { controller.enqueue(new TextEncoder().encode(done)); controller.close(); };
  }});
  const f = await fixture(() => new EdgeResponse(upstream, {headers: {'Content-Type': 'text/event-stream'}}));
  try {
    const response = await f.send();
    assert.equal(response.status, 200);
    const reader = response.body.getReader();
    const first = await Promise.race([reader.read(), new Promise((_, reject) => setTimeout(() => reject(new Error('First chunk blocked on completion')), 2000))]);
    assert.match(new TextDecoder().decode(first.value), /First chunk/);
    release();
    let tail = '';
    while (true) { const part = await reader.read(); if (part.done) break; tail += new TextDecoder().decode(part.value); }
    assert.match(tail, /"state":"succeeded"/);
    const receipt = await f.completion;
    assert.equal(receipt.outcome, 'succeeded');
    assert.ok(receipt.output_bytes > 0);
  } finally { await f.mf.dispose(); }
});

async function outputObservation(f) {
  for(let n=0;n<200 && !f.observations.length;n++)await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(f.observations.length,1,'Exactly one output observation is required');
  return f.observations[0];
}
const chatRequest = mf => mf.dispatchFetch(origin+'/chat',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({message:'Find a documentation agent'})});

// Direct Fetch/Streams harness keeps mid-body failures controllable. Miniflare's
// Node outboundService adapter can wait for a mock Origin body before exposing
// its headers; the existing workerd first-event test separately covers runtime
// backpressure and the common observedOutput wrapper.
function streamingOriginFixture(upstream) {
  const originalFetch=globalThis.fetch,observations=[],pending=[],calls=[];
  globalThis.fetch=async(url,init)=>{
    if(new URL(url).pathname.endsWith('/output-observation')){observations.push(JSON.parse(init.body));return new Response('{"ok":true}');}
    calls.push({url});return new Response(upstream,{headers:{'Content-Type':'application/json'}});
  };
  return {observations,calls,mf:{
    dispatchFetch:(url,init)=>worker.fetch(new Request(url,init),
      {PUBLIC_ORIGIN:origin,CONTROL_ORIGIN:controlOrigin,SHARED_SECRET:secret.toString('base64')},{waitUntil:promise=>pending.push(promise)}),
    dispose:async()=>{await Promise.all(pending);globalThis.fetch=originalFetch;}
  }};
}

test('chat converts intermediary HTML outages to JSON and identifies their Origin status without replay', async () => {
  for(const status of [500,502,503]){
    const body='<html>Temporarily unavailable</html>';
    const f=await fixture('',{},controlOrigin,{originResponse:()=>new EdgeResponse(body,{status,headers:{'Content-Type':'text/html'}})});
    try{
      const response=await chatRequest(f.mf);
      assert.equal(response.status,status);assert.equal((await response.json()).error_code,'UPSTREAM_UNAVAILABLE');
      const observation=await outputObservation(f);
      assert.equal(observation.outcome,'error');assert.equal(observation.source,'chat');
      assert.equal(observation.reason,'origin_http_'+status);
      assert.equal(f.calls.filter(r=>new URL(r.url).origin===origin).length,1);
      assert.equal(f.calls.filter(r=>r.url===endpoint).length,0);
    }finally{await f.mf.dispose();}
  }
});

test('chat preserves a structured service error and its retry policy',async()=>{
  const body=JSON.stringify({error_code:'SERVICE_BUSY',error:'Please try again shortly.'});
  const f=await fixture('',{},controlOrigin,{originResponse:()=>new EdgeResponse(body,{status:503,
    headers:{'Content-Type':'application/json; charset=utf-8','Retry-After':'2'}})});
  try{
    const response=await chatRequest(f.mf);
    assert.equal(await response.text(),body);assert.equal(response.status,503);
    assert.equal(response.headers.get('Retry-After'),'2');
    assert.equal((await outputObservation(f)).reason,'origin_http_503');
  }finally{await f.mf.dispose();}
});

test('new chat diagnostics remain compatible with an older Origin observation API',async()=>{
  const f=await fixture('',{},controlOrigin,{legacyObservations:true,
    originResponse:()=>new EdgeResponse('Unavailable',{status:502})});
  try{
    const response=await chatRequest(f.mf);await response.json();
    for(let n=0;n<200 && f.observations.length<2;n++)await new Promise(resolve=>setTimeout(resolve,10));
    assert.equal(f.observations.length,2);
    assert.deepEqual(f.observations.map(row=>row.reason),['origin_http_502','edge_error']);
    assert.equal(f.observations[0].id,f.observations[1].id);
    assert.equal(f.calls.filter(r=>new URL(r.url).origin===origin).length,1);
  }finally{await f.mf.dispose();}
});

test('a lost chat Origin connection returns bounded JSON and never redispatches the POST', async () => {
  const originalFetch=globalThis.fetch,observations=[],pending=[];let calls=0;
  globalThis.fetch=async(url,init)=>{
    if(new URL(url).pathname.endsWith('/output-observation')){observations.push(JSON.parse(init.body));return new Response('{"ok":true}');}
    calls++;throw Error('Private URL, token and connection details');
  };
  try{
    const response=await worker.fetch(new Request(origin+'/chat',{method:'POST',body:'{}'}),
      {PUBLIC_ORIGIN:origin,CONTROL_ORIGIN:controlOrigin,SHARED_SECRET:secret.toString('base64')},{waitUntil:promise=>pending.push(promise)}),body=await response.json();
    assert.equal(response.status,503);assert.equal(body.error_code,'UPSTREAM_UNAVAILABLE');
    assert.ok(!JSON.stringify(body).includes('Private'));
    await Promise.all(pending);assert.equal(observations.length,1);
    assert.equal(observations[0].reason,'origin_unavailable');assert.equal(calls,1);
  }finally{globalThis.fetch=originalFetch;}
});

test('chat streams before completion and records the completed result once', async () => {
  let finish;
  const upstream=new ReadableStream({start(controller){
    controller.enqueue(new TextEncoder().encode('{"answer":"'));
    finish=()=>{controller.enqueue(new TextEncoder().encode('Ready"}'));controller.close();};
  }});
  const f=streamingOriginFixture(upstream);
  try{
    const response=await chatRequest(f.mf),reader=response.body.getReader();
    const first=await reader.read();assert.match(new TextDecoder().decode(first.value),/answer/);
    assert.equal(f.observations.length,0);finish();
    while(!(await reader.read()).done){}
    const observation=await outputObservation(f);
    assert.equal(observation.outcome,'edge');assert.equal(observation.reason,'origin_relay');
    assert.equal(observation.bytes,Buffer.byteLength('{"answer":"Ready"}'));
  }finally{await f.mf.dispose();}
});

test('a broken chat response stream records failure once without falsely recording success', async () => {
  let fail;
  const upstream=new ReadableStream({start(controller){
    controller.enqueue(new TextEncoder().encode('first chunk'));
    fail=()=>controller.error(Error('Synthetic upstream interruption'));
  }});
  const f=streamingOriginFixture(upstream);
  try{
    const response=await chatRequest(f.mf),reader=response.body.getReader();
    assert.equal(new TextDecoder().decode((await reader.read()).value),'first chunk');
    fail();await assert.rejects(reader.read());
    const observation=await outputObservation(f);
    assert.equal(observation.outcome,'error');assert.equal(observation.reason,'stream_error');
    assert.equal(observation.bytes,Buffer.byteLength('first chunk'));
    assert.equal(f.calls.filter(r=>new URL(r.url).origin===origin).length,1);
  }finally{await f.mf.dispose();}
});

test('chat client cancellation cancels the upstream and is distinct from a server failure', async () => {
  let finish;
  const upstream=new ReadableStream({start(controller){controller.enqueue(new Uint8Array([65]));finish=()=>{try{controller.close();}catch{}};}});
  const f=streamingOriginFixture(upstream);
  try{
    const response=await chatRequest(f.mf),reader=response.body.getReader();
    await reader.read();await reader.cancel();
    const observation=await outputObservation(f);
    assert.equal(observation.outcome,'error');assert.ok(['client_cancelled','stream_error'].includes(observation.reason));
  }finally{finish();await f.mf.dispose();}
});

test('existing public Gateway and Testbench callers receive Provider output directly from the Worker', async () => {
  for (const testbench of [false, true]) {
    const f = await fixture(() => jsonResponse(envelope({kind: 'message', parts: [{kind: 'text', text: 'Ready ' + endpoint}]})), unary);
    try {
      const response = await f.sendLegacy(testbench), raw = await response.text(), value = JSON.parse(raw);
      assert.equal(response.status, 200);
      if (testbench) { assert.equal(value.execution_succeeded, true); assert.match(value.output, /Ready/); }
      else { assert.equal(value.id, 'caller-1'); assert.equal(value.result.kind, 'message'); assert.match(value.result.parts[0].text, /Ready/); }
      assert.ok(!JSON.stringify(value).includes(endpoint));
      const receipt = await f.completion;
      assert.equal(receipt.outcome, 'succeeded');
      assert.equal(receipt.output_bytes, Buffer.byteLength(raw));
      assert.equal(f.calls.filter(r => new URL(r.url).pathname.endsWith('/claim')).length, 0);
      assert.equal(f.calls.filter(r => new URL(r.url).origin === origin).length, 0);
      assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    } finally { await f.mf.dispose(); }
  }
});

test('unapproved Provider passes to the original Origin exactly once without Worker dispatch', async () => {
  const f = await fixture(done, {}, controlOrigin, {grant: {backend: 'origin'}, originResponse: async request => {
    assert.equal(request.url, origin + '/api/gateway/a2a/1');
    assert.equal((await request.json()).id, 'caller-1');
    assert.equal(request.headers.get('X-Real-IP'), '203.0.113.7');
    assert.equal(request.headers.get('X-Forwarded-For'), null);
    return new EdgeResponse('{"legacy":true}', {headers: {'Content-Type': 'application/json'}});
  }});
  try {
    assert.deepEqual(await (await f.sendLegacy(false, {'CF-Connecting-IP': '203.0.113.7', 'X-Real-IP': '198.51.100.4', 'X-Forwarded-For': '192.0.2.1'})).json(), {legacy: true});
    assert.equal(f.calls.filter(r => r.url === endpoint).length, 0);
    assert.equal(f.calls.filter(r => new URL(r.url).origin === origin).length, 1);
  } finally { await f.mf.dispose(); }
});

test('free-limit grant uses the authenticated Origin adapter without Provider redispatch', async () => {
  const originPath = path.replace('/edge-', '/origin-');
  const f = await fixture(done, {}, controlOrigin, {grant: {backend: 'origin', run_id: run, stream_path: originPath, access_token: ticket()},
    originResponse: async request => {
      assert.equal(request.url, origin + originPath); assert.match(request.headers.get('Authorization'), /^Bearer /);
      assert.deepEqual(await request.json(), {message: 'Weather?'});
      return new EdgeResponse('event: result\ndata: ' + JSON.stringify({state: 'succeeded', output: {parts: [{kind: 'text', text: 'Origin result'}]}}) + '\n\n',
        {headers: {'Content-Type': 'text/event-stream'}});
    }});
  try {
    assert.equal((await (await f.sendLegacy()).json()).result.parts[0].text, 'Origin result');
    assert.equal(f.calls.filter(r => r.url === endpoint).length, 0);
    assert.equal(f.calls.filter(r => new URL(r.url).origin === origin).length, 1);
  } finally { await f.mf.dispose(); }
});

test('legacy callers never replay a claimed Provider failure on Origin', async () => {
  const f = await fixture(() => jsonResponse(JSON.stringify({jsonrpc: '2.0', id: attempt, error: {code: -32601, message: endpoint}})), unary);
  try {
    const value = await (await f.sendLegacy()).json();
    assert.equal(value.error.code, -32000); assert.ok(!JSON.stringify(value).includes(endpoint));
    assert.equal((await f.completion).outcome, 'failed');
    assert.equal(f.calls.filter(r => new URL(r.url).origin === origin).length, 0);
    assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
  } finally { await f.mf.dispose(); }
});

test('approved Provider origin paths are hidden while independent citations remain', async () => {
  const f = await fixture(delta('https://provider.example/private/other https://news.example/article') + done,
    {bindings: [endpoint, 'https://provider.example/']});
  try {
    const text = await (await f.send()).text();
    assert.ok(!text.includes('provider.example') && text.includes(gateway) && text.includes('https://news.example/article'));
    assert.equal((await f.completion).outcome, 'succeeded');
  } finally { await f.mf.dispose(); }
});

const envelope = result => JSON.stringify({jsonrpc: '2.0', id: attempt, result});
const jsonResponse = value => new EdgeResponse(value, {headers: {'Content-Type': 'application/json; charset=utf-8',
  Location: endpoint, 'X-Provider-Debug': 'private'}});
const unary = {request_mode: 'json', request: {jsonrpc: '2.0', id: attempt, method: 'message/send', params: {}}};

test('JSON Message and completed Task become platform SSE with binding projection', async () => {
  for (const result of [
    {kind: 'message', parts: [{kind: 'text', text: 'Ready ' + endpoint + ' https://news.example/article'}]},
    {kind: 'task', status: {state: 'completed'}, artifacts: [{parts: [{kind: 'text', text: 'Ready ' + endpoint + ' https://news.example/article'}]}]}
  ]) {
    const f = await fixture(request => {
      assert.match(request.headers.get('Accept'), /application\/json/);
      return jsonResponse(envelope(result));
    }, unary);
    try {
      const response = await f.send(), text = await response.text();
      assert.match(response.headers.get('Content-Type'), /^text\/event-stream/);
      assert.match(text, /Ready/); assert.match(text, /"state":"succeeded"/);
      assert.ok(text.includes(gateway) && text.includes('https://news.example/article') && !text.includes(endpoint));
      assert.equal(response.headers.get('Location'), null);
      assert.equal((await f.completion).outcome, 'succeeded');
      assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    } finally { await f.mf.dispose(); }
  }
});

test('a JSON response to the existing stream request is accepted without a second invocation', async () => {
  const f = await fixture(() => jsonResponse(envelope({kind: 'message', parts: [{kind: 'text', text: 'Ready'}]})));
  try {
    assert.match(await (await f.send()).text(), /"state":"succeeded"/);
    assert.equal((await f.completion).outcome, 'succeeded');
    assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
  } finally { await f.mf.dispose(); }
});

test('JSON-RPC errors over JSON or SSE are classified without disclosing upstream diagnostics or retrying', async () => {
  for (const [code, expected] of [[-32601, 'PROVIDER_METHOD_UNSUPPORTED'], [-32004, 'PROVIDER_METHOD_UNSUPPORTED'], [-32602, 'PROVIDER_INPUT_REJECTED'], [-32603, 'EXECUTION_FAILED']]) {
    for (const sse of [false, true]) {
      const raw = JSON.stringify({jsonrpc: '2.0', id: attempt, error: {code, message: 'private ' + endpoint, data: {secret: 'private'}}});
      const f = await fixture(() => sse ? new EdgeResponse('data: ' + raw + '\n\n', {headers: {'Content-Type': 'text/event-stream'}}) : jsonResponse(raw));
      try {
        const text = await (await f.send()).text(), receipt = await f.completion;
        assert.match(text, /"state":"failed"/); assert.ok(text.includes(expected));
        assert.ok(!text.includes(endpoint) && !text.includes('private'));
        assert.equal(receipt.outcome_code, expected);
        assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
      } finally { await f.mf.dispose(); }
    }
  }
});

test('invalid or nonterminal JSON cannot masquerade as completed work', async () => {
  const message = {kind: 'message', parts: [{kind: 'text', text: 'private ' + endpoint}]};
  for (const [raw, expected] of [
    [JSON.stringify({jsonrpc: '2.0', id: 'wrong', result: message}), 'PROVIDER_PROTOCOL_INVALID'],
    [JSON.stringify({jsonrpc: '2.0', id: attempt, result: message, error: null}), 'PROVIDER_PROTOCOL_INVALID'],
    [envelope({kind: 'task', status: {state: 'working'}, artifacts: [{parts: message.parts}]}), 'PROVIDER_TASK_PENDING'],
    [envelope({kind: 'artifact-update', artifact: {parts: message.parts}}), 'PROVIDER_PROTOCOL_INVALID'],
    [envelope({kind: 'message', parts: [{kind: 'text', text: 'x'.repeat(20000)}]}), 'PROVIDER_PROTOCOL_INVALID'],
    ['x'.repeat(65537), 'PROVIDER_PROTOCOL_INVALID'], ['{', 'PROVIDER_PROTOCOL_INVALID']
  ]) {
    const f = await fixture(() => jsonResponse(raw), unary);
    try {
      const text = await (await f.send()).text();
      assert.ok(text.includes(expected) && !text.includes('succeeded') && !text.includes(endpoint) && !text.includes('x'.repeat(100)));
      assert.equal((await f.completion).outcome, 'outcome_unknown');
      assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    } finally { await f.mf.dispose(); }
  }
});

test('404 is an endpoint failure and never triggers method probing or Origin execution', async () => {
  const f = await fixture(() => new EdgeResponse('private ' + endpoint, {status: 404}));
  try {
    const response = await f.send(), text = await response.text(), receipt = await f.completion;
    assert.equal(response.status, 503); assert.ok(!text.includes(endpoint));
    assert.equal(receipt.outcome, 'failed'); assert.equal(receipt.outcome_code, 'PROVIDER_ENDPOINT_UNAVAILABLE');
    assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    const observation = await outputObservation(f);
    assert.equal(observation.outcome, 'error'); assert.equal(observation.reason, 'provider_failed');
    assert.equal(response.headers.get('X-Edge-Provider-Failure'), null);
  } finally { await f.mf.dispose(); }
});

test('binding method and mode must agree before contacting a Provider', async () => {
  const f = await fixture(done, {request_mode: 'json'});
  try {
    assert.equal((await f.send()).status, 503);
    assert.equal(f.calls.filter(r => r.url === endpoint).length, 0);
  } finally { await f.mf.dispose(); }
});

test('CR-only SSE boundaries remain incremental across fragmented CRLF and EOF', async () => {
  for (const ending of ['\r', '\r\n']) {
    const raw = new TextEncoder().encode((delta('Ready') + done).replace(/\n/g, ending));
    const body = new ReadableStream({start(controller) {
      for (const byte of raw) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    }});
    const f = await fixture(() => new EdgeResponse(body, {headers: {'Content-Type': 'text/event-stream'}}));
    try {
      const text = await (await f.send()).text();
      assert.match(text, /Ready/); assert.match(text, /"state":"succeeded"/);
      assert.equal((await f.completion).outcome, 'succeeded');
    } finally { await f.mf.dispose(); }
  }
});

test('same-origin control retains Cloudflare attribution without trusting browser forwarding headers', async () => {
  const f = await fixture(delta('Ready') + done, {}, origin);
  try {
    const response = await f.send({'CF-Connecting-IP': '203.0.113.7', 'X-Real-IP': '198.51.100.20', 'X-Forwarded-For': '192.0.2.9'});
    assert.equal(response.status, 200);
    await response.text(); await f.completion;
    const controls = f.calls.filter(r => new URL(r.url).origin === origin);
    assert.equal(controls.length, 2);
    for (const r of controls) {
      assert.equal(r.headers.get('X-Real-IP'), '203.0.113.7');
      assert.equal(r.headers.get('X-Forwarded-For'), null);
    }
  } finally { await f.mf.dispose(); }
});

test('a different control origin receives no client IP forwarding header', async () => {
  const f = await fixture(delta('Ready') + done);
  try {
    const response = await f.send({'CF-Connecting-IP': '203.0.113.7'});
    await response.text(); await f.completion;
    for (const r of f.calls) assert.equal(r.headers.get('X-Real-IP'), null);
  } finally { await f.mf.dispose(); }
});

test('multiple events in one chunk preserve text and hide invocation bindings', async () => {
  const f = await fixture(delta('Endpoint ' + endpoint + '; citation https://news.example/article') + delta(' Second') + done);
  try {
    const response = await f.send(), text = await response.text();
    assert.match(text, /Second/); assert.match(text, /succeeded/);
    assert.ok(!text.includes(endpoint)); assert.ok(text.includes(gateway));
    assert.ok(text.includes('https://news.example/article'));
    for (const header of ['location', 'link', 'x-provider-debug']) assert.equal(response.headers.get(header), null);
    const receipt = await f.completion;
    assert.equal(receipt.outcome, 'succeeded');
    assert.equal(receipt.output_bytes, Buffer.byteLength(text));
  } finally { await f.mf.dispose(); }
});

test('fragmented UTF-8 and encoded URLs are validated at complete event boundaries', async () => {
  const raw = new TextEncoder().encode(delta('Weather 서울 ' + encodeURIComponent(endpoint)) + done);
  const body = new ReadableStream({start(controller) {
    for (let i = 0; i < raw.length; i += 7) controller.enqueue(raw.slice(i, i + 7));
    controller.close();
  }});
  const f = await fixture(() => new EdgeResponse(body, {headers: {'Content-Type': 'text/event-stream'}}));
  try {
    const response = await f.send(), text = await response.text();
    assert.ok(text.includes('서울') && text.includes(gateway));
    assert.ok(!text.includes(encodeURIComponent(endpoint)) && !text.includes(endpoint));
    assert.equal((await f.completion).outcome, 'succeeded');
  } finally { await f.mf.dispose(); }
});

test('redirect is never followed and its target or body is never exposed', async () => {
  const f = await fixture(() => new EdgeResponse('private ' + endpoint, {status: 302, headers: {Location: 'http://127.0.0.1/private'}}));
  try {
    const response = await f.send(), text = await response.text();
    assert.equal(response.status, 503); assert.ok(!text.includes(endpoint) && !text.includes('127.0.0.1'));
    assert.equal(f.calls.filter(r => new URL(r.url).hostname === 'provider.example').length, 1);
    assert.equal((await f.completion).outcome, 'outcome_unknown');
  } finally { await f.mf.dispose(); }
});

test('missing terminal event remains unknown even after HTTP 200', async () => {
  const f = await fixture(delta('Partial response'));
  try {
    const response = await f.send(), text = await response.text();
    assert.match(text, /Partial response/); assert.match(text, /outcome_unknown/); assert.ok(!text.includes('succeeded'));
    assert.equal((await f.completion).outcome, 'outcome_unknown');
  } finally { await f.mf.dispose(); }
});

test('raw upstream errors and oversized frames do not become public output', async () => {
  for (const provider of [JSON.stringify({private: endpoint}) + '\n\n', delta('x'.repeat(20000))]) {
    const f = await fixture(provider);
    try {
      const response = await f.send(), text = await response.text();
      assert.match(text, /outcome_unknown/); assert.ok(!text.includes(endpoint) && !text.includes('x'.repeat(100)));
      assert.equal((await f.completion).outcome, 'outcome_unknown');
    } finally { await f.mf.dispose(); }
  }
});

test('forged ticket and untrusted Origin never contact control or Provider', async () => {
  const f = await fixture(done);
  try {
    for (const headers of [{Authorization: 'Bearer invalid'}, {Origin: 'https://evil.example'}]) {
      const response = await f.send(headers); assert.ok(response.status >= 400);
    }
    assert.equal(f.calls.length, 0);
  } finally { await f.mf.dispose(); }
});

test('health proof identifies a real Worker without invoking a Provider', async () => {
  const f = await fixture(done);
  try {
    const healthPath = '/api/edge-gateway/v1/health', nonce = randomBytes(16).toString('hex'), timestamp = String(Math.floor(Date.now() / 1000));
    const body = '{}', material = ['POST', healthPath, timestamp, nonce, createHash('sha256').update(body).digest('hex')].join('\n');
    const response = await f.mf.dispatchFetch(origin + healthPath, {method: 'POST', headers: {'Content-Type': 'application/json',
      'X-Edge-Time': timestamp, 'X-Edge-Nonce': nonce, 'X-Edge-Signature': createHmac('sha256', derive('edge-service-v1')).update(material).digest('hex')}, body});
    const raw = await response.text();
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('x-edge-health-signature'), createHmac('sha256', derive('edge-health-v1')).update(raw).digest('hex'));
    assert.equal(JSON.parse(raw).nonce, nonce); assert.equal(JSON.parse(raw).backend, 'worker');
    assert.equal(f.calls.length, 0);
  } finally { await f.mf.dispose(); }
});

const catalogBinding = (protocol, request, extra = {}) => ({profile: 'catalog-public-v1', protocol, spec_version: '0.3', request_mode: 'json',
  gateway_url: origin + '/api/gateway/' + protocol + '/1', bindings: ['https://provider.example/'], request: {jsonrpc: '2.0', id: attempt, ...request}, ...extra});

test('catalog A2A 1.0 and completed Task status messages preserve typed output and redact secrets', async () => {
  for (const [spec, result] of [
    ['1.0', {message: {role: 'ROLE_AGENT', parts: [{text: 'Ready ' + endpoint}, {data: {api_key: 'private', source: 'https://news.example/article'}}]}}],
    ['0.3', {kind: 'task', status: {state: 'completed', message: {role: 'agent', parts: [{kind: 'text', text: 'Ready ' + endpoint}]}}}]
  ]) {
    const binding = catalogBinding('a2a', {method: spec === '1.0' ? 'SendMessage' : 'message/send', params: {}}, {spec_version: spec});
    const f = await fixture(request => {
      assert.equal(request.headers.get('A2A-Version'), spec === '1.0' ? '1.0' : null);
      return jsonResponse(envelope(result));
    }, binding, controlOrigin, {clientMethod: spec === '1.0' ? 'SendMessage' : 'message/send'});
    try {
      const response = await f.sendLegacy(false, {Origin: 'https://downloaded-app.example'}), raw = await response.text();
      assert.match(raw, /Ready/); assert.ok(!raw.includes('provider.example') && !raw.includes('private'));
      assert.equal(response.headers.get('Access-Control-Allow-Origin'), '*');
      assert.equal((await f.completion).outcome, 'succeeded');
    } finally { await f.mf.dispose(); }
  }
});

test('MCP validates live schema before one tools/call and keeps protocol sessions private', async () => {
  const methods = [];
  let cleaned;
  const cleanup = new Promise(resolve => { cleaned = resolve; });
  const binding = catalogBinding('mcp', {method: 'tools/call', params: {name: 'get_weather', arguments: {city: 'Tokyo'}}});
  const f = await fixture(async request => {
    if (request.method === 'DELETE') { methods.push('DELETE'); assert.equal(request.headers.get('Mcp-Session-Id'), 'provider-session'); cleaned(); return new EdgeResponse(null, {status: 204}); }
    const wire = await request.json(); methods.push(wire.method);
    if (wire.method === 'server/discover') return jsonResponse(JSON.stringify({jsonrpc: '2.0', id: wire.id, error: {code: -32601, message: 'unsupported'}}));
    if (wire.method === 'initialize') return new EdgeResponse(JSON.stringify({jsonrpc: '2.0', id: wire.id, result: {protocolVersion: '2025-06-18'}}), {headers: {'Content-Type': 'application/json', 'Mcp-Session-Id': 'provider-session'}});
    assert.equal(request.headers.get('Mcp-Session-Id'), 'provider-session'); assert.equal(request.headers.get('Mcp-Protocol-Version'), '2025-06-18');
    if (wire.method === 'notifications/initialized') return new EdgeResponse(null, {status: 202});
    if (wire.method === 'tools/list') return jsonResponse(JSON.stringify({jsonrpc: '2.0', id: wire.id, result: {tools: [{name: 'get_weather', inputSchema: {type: 'object'}}]}}));
    assert.equal(wire.method, 'tools/call');
    assert.ok(f.calls.some(r => new URL(r.url).pathname.endsWith('/mcp-schema')));
    return jsonResponse(envelope({content: [{type: 'text', text: 'Weather ' + endpoint}], structuredContent: {access_token: 'private', source: 'https://news.example/article'}}));
  }, binding);
  try {
    const response = await f.sendLegacy(false, {Cookie: 'browser-secret', 'Mcp-Session-Id': 'browser-session'}), value = await response.json();
    assert.equal(value.id, 'caller-1'); assert.match(value.result.content[0].text, /Weather/);
    assert.equal(value.result.structuredContent.access_token, '[REDACTED]');
    assert.ok(!JSON.stringify(value).includes('provider.example') && !JSON.stringify(value).includes('provider-session'));
    assert.equal((await f.completion).outcome, 'succeeded');
    assert.equal(methods.filter(x => x === 'tools/call').length, 1);
    await cleanup; assert.equal(methods.filter(x => x === 'DELETE').length, 1);
  } finally { await f.mf.dispose(); }
});

test('MCP schema rejection never invokes a tool or replays on Origin', async () => {
  let dispatched = 0;
  const binding = catalogBinding('mcp', {method: 'tools/call', params: {name: 'get_weather', arguments: {city: 'Tokyo'}}});
  const f = await fixture(async request => {
    const wire = await request.json();
    if (wire.method === 'tools/call') dispatched++;
    return jsonResponse(JSON.stringify({jsonrpc: '2.0', id: wire.id, result: wire.method === 'server/discover' ? {protocolVersion: '2026-07-28'} : {tools: []}}));
  }, binding, controlOrigin, {reviewDenied: true});
  try {
    assert.ok((await (await f.sendLegacy()).json()).error);
    assert.equal((await f.completion).outcome_code, 'PROVIDER_SCHEMA_CHANGED'); assert.equal(dispatched, 0);
    assert.equal(f.calls.filter(r => new URL(r.url).origin === origin).length, 0);
  } finally { await f.mf.dispose(); }
});

test('x402 payment proofs go only to the Origin, which explains them and never settles', async () => {
  const binding = catalogBinding('x402', {method: 'probe', params: {}});
  for (const get of [false, true]) {
    const seen = [];
    const f = await fixture(() => { throw new Error('A payment proof must never reach the provider'); }, binding, controlOrigin, {get,
      originResponse: request => { seen.push(request);
        return new EdgeResponse(JSON.stringify({error_code: 'PAYMENT_EXECUTION_DISABLED', payment_processed: false, reason: 'invalid_payload'}),
          {status: 501, headers: {'Content-Type': 'application/json'}}); }});
    try {
      const response = await f.sendLegacy(false, {'Payment-Signature': 'never-settle'}), value = await response.json();
      assert.equal(response.status, 501); assert.equal(value.reason, 'invalid_payload'); assert.equal(value.payment_processed, false);
      assert.equal(seen.length, 1); assert.equal(f.calls.filter(r => r.url === endpoint).length, 0);
      if (f.observations) for (const observation of f.observations) assert.equal(observation.outcome, 'edge');
    } finally { await f.mf.dispose(); }
  }
});

test('x402 probe returns a validated challenge without forwarding a payment or credentials', async () => {
  const binding = catalogBinding('x402', {method: 'probe', params: {}});
  const challenge = {x402Version: 2, resource: {url: endpoint}, accepts: [{scheme: 'exact', network: 'eip155:8453', amount: '100', asset: '0xasset', payTo: '0xrecipient', maxTimeoutSeconds: 60}]};
  for (const get of [false, true]) {
    const f = await fixture(request => {
      assert.equal(request.method, 'GET'); assert.equal(request.headers.get('Payment-Signature'), null);
      return new EdgeResponse(JSON.stringify(challenge), {status: 402, headers: {'Content-Type': 'application/json'}});
    }, binding, controlOrigin, {get});
    try {
      const response = await f.sendLegacy(false), value = await response.json();
      assert.equal(response.status, 402);
      const body = value;
      assert.equal(body.inspection_only, true);
      assert.equal(body.gateway_mode, 'inspection_only');
      assert.equal(body.provider_url, null);
      assert.equal(body.provider_details_url, origin + '/api/agents/1');
      for (const key of ['payment_processed','payment_accepted','payment_forwarded','settlement_performed']) assert.equal(body[key], false);
      assert.match(body.instructions, /Do not submit payment proofs here/);
      assert.equal(response.headers.get('X-AgentConcierge-Payment-Mode'), 'inspection-only');
      assert.equal(body.x402Version, 2); assert.equal(body.accepts[0].amount, '100'); assert.equal(body.accepts[0].payTo, '0xrecipient');
      assert.ok(!JSON.stringify(value).includes('provider.example'));
      assert.deepEqual(JSON.parse(Buffer.from(response.headers.get('Payment-Required'), 'base64').toString()), body);
      assert.equal((await f.completion).outcome_code, 'PROVIDER_AUTH_REQUIRED');
      assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    } finally { await f.mf.dispose(); }
  }
});

test('malformed x402 offers never become a valid challenge or trigger a payment', async () => {
  const binding = catalogBinding('x402', {method: 'probe', params: {}});
  for (const challenge of [{x402Version: true, accepts: []}, {x402Version: 2, resource: {url: 'http://127.0.0.1/private'}, accepts: [{}]}]) {
    const f = await fixture(() => new EdgeResponse(JSON.stringify(challenge), {status: 402, headers: {'Content-Type': 'application/json'}}), binding, controlOrigin, {get: true});
    try {
      assert.equal((await f.sendLegacy()).status, 503); assert.equal((await f.completion).outcome, 'failed');
      assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    } finally { await f.mf.dispose(); }
  }
});

test('a full schema digest approved by Origin avoids an extra schema callback; changes still require review', async () => {
  const tool = {name: 'get_weather', description: 'Get current weather for a city', inputSchema: {type: 'object', properties: {city: {type: 'string'}}, required: ['city']}};
  for (const changed of [false, true]) {
    const binding = catalogBinding('mcp', {method: 'tools/call', params: {name: 'get_weather', arguments: {city: 'Tokyo'}}},
      {mcp_schema_hash: '1c3a5d3e42b6b1f11e7ec33a2b4c6726a81372e9fcd9a422887645be2dad605e'});
    const f = await fixture(async request => {
      const wire = await request.json();
      if (wire.method === 'server/discover') return jsonResponse(JSON.stringify({jsonrpc: '2.0', id: wire.id, result: {protocolVersion: '2026-07-28'}}));
      if (wire.method === 'tools/list') return jsonResponse(JSON.stringify({jsonrpc: '2.0', id: wire.id, result: {tools: [changed ? {...tool, description: 'Changed'} : tool]}}));
      assert.equal(wire.method, 'tools/call');
      return jsonResponse(envelope({content: [{type: 'text', text: 'Weather result'}]}));
    }, binding, controlOrigin, {reviewDenied: changed});
    try {
      const value = await (await f.sendLegacy()).json();
      assert.equal((await f.completion).outcome, changed ? 'failed' : 'succeeded');
      assert.equal(f.calls.filter(r => new URL(r.url).pathname.endsWith('/mcp-schema')).length, changed ? 1 : 0);
      assert.equal(Boolean(value.error), changed);
    } finally { await f.mf.dispose(); }
  }
});

test('downloaded web apps can preflight protocol headers without any Provider or control dispatch', async () => {
  const f = await fixture(() => { throw new Error('No dispatch permitted'); });
  try {
    const response = await f.mf.dispatchFetch(origin + '/api/gateway/a2a/1', {method: 'OPTIONS', headers: {
      Origin: 'https://downloaded-app.example', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'a2a-version,content-type'}});
    assert.equal(response.status, 204);
    assert.match(response.headers.get('Access-Control-Allow-Headers'), /A2A-Version/);
    assert.equal(response.headers.get('Access-Control-Allow-Credentials'), null);
    assert.equal(f.calls.length, 0);
  } finally { await f.mf.dispose(); }
});

test('registered MCP handshake skips discovery but still checks live schema before exactly one call', async () => {
  for (const denied of [false, true]) {
    const methods = [];
    const binding = catalogBinding('mcp', {method: 'tools/call', params: {name: 'get_weather', arguments: {city: 'Tokyo'}}},
      {mcp_protocol_version: '2025-06-18'});
    const f = await fixture(async request => {
      const wire = await request.json(); methods.push(wire.method);
      assert.notEqual(wire.method, 'server/discover');
      if (wire.method === 'notifications/initialized') return new EdgeResponse(null, {status: 202});
      const result = wire.method === 'initialize' ? {protocolVersion: '2025-06-18'} :
        wire.method === 'tools/list' ? {tools: [{name: 'get_weather', inputSchema: {type: 'object'}}]} :
        {content: [{type: 'text', text: 'Ready'}]};
      return jsonResponse(JSON.stringify({jsonrpc: '2.0', id: wire.id, result}));
    }, binding, controlOrigin, {reviewDenied: denied});
    try {
      const value = await (await f.sendLegacy()).json();
      assert.equal(Boolean(value.error), denied);
      assert.equal(methods.filter(m => m === 'tools/call').length, denied ? 0 : 1);
      assert.equal(f.calls.filter(r => new URL(r.url).pathname.endsWith('/mcp-schema')).length, 1);
      assert.equal((await f.completion).outcome, denied ? 'failed' : 'succeeded');
    } finally { await f.mf.dispose(); }
  }
});

test('bounded JSON keeps exact byte limits and rejects fragmented oversized or invalid UTF-8 bodies', async () => {
  for (const mode of ['exact', 'oversized', 'utf8']) {
    const prefix = '{"jsonrpc":"2.0","id":"' + attempt + '","result":{"kind":"message","parts":[{"kind":"text","text":"Ready"}]},"padding":"';
    const raw = new TextEncoder().encode(prefix + ' '.repeat(65536 - prefix.length - 2) + '"}');
    assert.equal(raw.byteLength, 65536);
    const bytes = mode === 'oversized' ? new Uint8Array([...raw, 32]) : raw;
    if (mode === 'utf8') bytes[bytes.length - 4] = 0xff;
    const f = await fixture(() => new EdgeResponse(new ReadableStream({start(c) {
      c.enqueue(bytes.slice(0, 317)); c.enqueue(bytes.slice(317)); c.close();
    }}), {headers: {'Content-Type': 'application/json'}}), {request_mode: 'json',
      request: {jsonrpc: '2.0', id: attempt, method: 'message/send', params: {}}});
    try {
      const response = await f.sendLegacy();
      const value = await response.json();
      assert.equal(Boolean(value.result), mode === 'exact');
      assert.equal((await f.completion).outcome, mode === 'exact' ? 'succeeded' : 'outcome_unknown');
      assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    } finally { await f.mf.dispose(); }
  }
});

test('prepared MCP uses one Provider tool call, no metadata callback, private session cleanup and no expired dispatch', async () => {
  for (const expired of [false, true]) {
    const methods = [];
    const binding = catalogBinding('mcp', {method: 'tools/call', params: {name: 'get_weather', arguments: {city: 'Tokyo'}}},
      {mcp_protocol_version: '2025-06-18', mcp_prepared: {protocol_version: '2025-06-18', session_id: 'private-session', deadline_ms: Date.now() + (expired ? -1000 : 7500)}});
    const f = await fixture(async request => {
      assert.equal(request.headers.get('Mcp-Session-Id'), 'private-session');
      if (request.method === 'DELETE') { methods.push('DELETE'); return new EdgeResponse(null, {status: 204}); }
      const wire = await request.json(); methods.push(wire.method); assert.equal(wire.method, 'tools/call');
      return jsonResponse(envelope({content: [{type: 'text', text: 'Ready ' + endpoint}], structuredContent: {session_id: 'private-session'}}));
    }, binding);
    try {
      const response = await f.sendLegacy(); const text = await response.text();
      assert.equal(Boolean(JSON.parse(text).result), !expired);
      assert.ok(!text.includes('provider.example') && !text.includes('private-session'));
      const receipt = await f.completion;
      assert.equal(receipt.outcome, expired ? 'outcome_unknown' : 'succeeded');
      assert.equal(f.calls.filter(r => new URL(r.url).pathname.endsWith('/mcp-schema')).length, 0);
      assert.equal(methods.filter(m => m === 'tools/call').length, expired ? 0 : 1);
    } finally { await f.mf.dispose(); }
  }
});

test('prepared MCP relays signed cleanup authority only on private completion and performs only one Provider fetch', async () => {
  const cleanup = {signature: 'private-authority', session_id: 'private-session'};
  const binding = catalogBinding('mcp', {method: 'tools/call', params: {name: 'get_weather', arguments: {city: 'Tokyo'}}},
    {mcp_prepared: {protocol_version: '2025-06-18', session_id: 'private-session', deadline_ms: Date.now() + 7500, cleanup}});
  let dispatched = 0;
  const f = await fixture(async request => {
    assert.equal(request.method, 'POST');
    const wire = await request.json(); assert.equal(wire.method, 'tools/call'); dispatched++;
    return jsonResponse(envelope({content: [{type: 'text', text: 'Ready'}]}));
  }, binding);
  try {
    const response = await f.sendLegacy(); const text = await response.text();
    assert.ok(JSON.parse(text).result && !text.includes('private-'));
    const receipt = await f.completion;
    assert.deepEqual(receipt.mcp_cleanup, cleanup); assert.equal(dispatched, 1);
    assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
  } finally { await f.mf.dispose(); }
});

test('MCP native SSE accepts fragmented UTF-8, CR/LF line endings and notifications without waiting for EOF', async () => {
  for (const ending of ['\n', '\r\n', '\r']) {
    const binding = catalogBinding('mcp', {method: 'tools/call', params: {name: 'get_weather', arguments: {city: 'Tokyo'}}},
      {mcp_prepared: {protocol_version: '2025-06-18', session_id: null, deadline_ms: Date.now() + 7500}});
    const data = JSON.stringify({jsonrpc: '2.0', id: attempt, result: {content: [{type: 'text', text: '\u6771\u4eac Ready'}]}});
    const split = data.indexOf(',') + 1;
    const text = 'data: {"jsonrpc":"2.0","method":"notifications/progress"}' + ending + ending +
      'event: message' + ending + 'data: ' + data.slice(0, split) + ending + 'data: ' + data.slice(split) + ending + ending;
    const bytes = new TextEncoder().encode(text);
    const f = await fixture(() => new EdgeResponse(new ReadableStream({async start(c) {
      // Deliberately split CRLF and multibyte sequences across separate I/O turns.
      for (let at = 0; at < bytes.length; at += 7) {
        c.enqueue(bytes.slice(at, at + 7)); await new Promise(resolve => setTimeout(resolve, 1));
      }
      // The stream stays open: a complete JSON-RPC SSE event must be sufficient.
    }}), {headers: {'Content-Type': 'text/event-stream'}}), binding);
    try {
      const response = await Promise.race([f.sendLegacy(), new Promise((_, reject) => setTimeout(() => reject(new Error('SSE waited for EOF')), 2000))]);
      const value = await response.json(); assert.match(value.result.content[0].text, /Ready/);
      assert.equal((await f.completion).outcome, 'succeeded');
      assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    } finally { await f.mf.dispose(); }
  }
});

test('native MCP SSE keeps byte bounds and rejects invalid UTF-8 before exposing output', async () => {
  for (const malformed of ['oversized', 'utf8']) {
    const binding = catalogBinding('mcp', {method: 'tools/call', params: {name: 'get_weather', arguments: {city: 'Tokyo'}}},
      {mcp_prepared: {protocol_version: '2025-06-18', session_id: null, deadline_ms: Date.now() + 7500}});
    const bytes = malformed === 'oversized' ? new TextEncoder().encode(':' + 'x'.repeat(65536) + '\n\n') :
      new Uint8Array([...new TextEncoder().encode('data: {"jsonrpc":"2.0","id":"' + attempt + '","result":{"content":[{"type":"text","text":"'), 255,
        ...new TextEncoder().encode('"}]}}\n\n')]);
    const f = await fixture(() => new EdgeResponse(bytes, {headers: {'Content-Type': 'text/event-stream'}}), binding);
    try {
      const value = await (await f.sendLegacy()).json(); assert.ok(value.error);
      assert.equal((await f.completion).outcome, 'outcome_unknown');
      assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    } finally { await f.mf.dispose(); }
  }
});

test('temporary completion failure retries only identical metadata with fresh nonces and one Provider execution', async () => {
  const f = await fixture(done, {}, controlOrigin, {completeResponses: [503,503,200]});
  try {
    await (await f.sendLegacy()).text();
    assert.equal((await f.completion).outcome, 'succeeded');
    const completed = f.calls.filter(r => new URL(r.url).pathname.endsWith('/complete'));
    assert.equal(completed.length, 3);
    assert.equal(new Set(completed.map(r => r.headers.get('X-Edge-Nonce'))).size, 3);
    assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
    assert.equal(f.calls.filter(r => new URL(r.url).origin === origin).length, 0);
  } finally { await f.mf.dispose(); }
});

test('completion conflicts are reported privately without retrying or re-executing a Provider', async () => {
  const f = await fixture(done, {}, controlOrigin, {completeResponses: [409,200]});
  try {
    await (await f.sendLegacy()).text();
    await new Promise(resolve => setTimeout(resolve, 400));
    assert.equal(f.calls.filter(r => new URL(r.url).pathname.endsWith('/complete')).length, 1);
    assert.equal(f.calls.filter(r => r.url === endpoint).length, 1);
  } finally { await f.mf.dispose(); }
});

test('ticketed Native A2A JSON retains one execution and private binding projection', async () => {
  const f = await fixture(() => jsonResponse(envelope({kind:'message',parts:[{kind:'text',text:'Ready '+endpoint}]})),
    {request_mode:'json',request:{jsonrpc:'2.0',id:attempt,method:'message/send',params:{message:{parts:[{kind:'text',text:'Weather?'}]}}}});
  try {
    const response = await f.send({'X-Edge-Result-Format':'json'}),value=await response.json();
    assert.equal(value.run_id,run); assert.equal(value.state,'succeeded');
    assert.ok(!JSON.stringify(value).includes(endpoint));
    assert.equal(f.calls.filter(r=>r.url===endpoint).length,1);
    const receipt=await f.completion;assert.equal(receipt.outcome,'succeeded');
    assert.equal(receipt.output_bytes,Buffer.byteLength(JSON.stringify(value)));
  } finally {await f.mf.dispose();}
});

test('ticketed Native MCP executes pinned arguments once and returns its structured result', async () => {
  const binding=catalogBinding('mcp',{method:'tools/call',params:{name:'get_weather',arguments:{city:'Tokyo'}}},
    {mcp_prepared:{protocol_version:'2025-06-18',session_id:null,deadline_ms:Date.now()+7500}});
  const f=await fixture(async request=>{
    const wire=await request.json();assert.equal(wire.method,'tools/call');
    assert.deepEqual(wire.params,binding.request.params);
    return jsonResponse(envelope({content:[{type:'text',text:'Ready'}],structuredContent:{city:'Tokyo'}}));
  },binding);
  try {
    const response=await f.mf.dispatchFetch(origin+path,{method:'POST',headers:{Origin:origin,Authorization:'Bearer '+ticket(),
      'Content-Type':'application/json','X-Edge-Result-Format':'json'},body:JSON.stringify({tool:'get_weather',arguments:{city:'Tokyo'}})});
    const value=await response.json();assert.equal(value.state,'succeeded');
    assert.deepEqual(value.output.structuredContent,{city:'Tokyo'});
    assert.equal(f.calls.filter(r=>r.url===endpoint).length,1);assert.equal((await f.completion).outcome,'succeeded');
  } finally {await f.mf.dispose();}
});

const resultMedia = 'application/vnd.agentconcierge.edge-result+json';
const recipeResponse = recipe => new EdgeResponse(JSON.stringify({version:1,recipe}),{headers:{'Content-Type':resultMedia,'Cache-Control':'private, no-store'}});

test('Native receipt keeps 40KB output out of the Origin download and serves authenticated result GET from Edge', async () => {
  const text='A'.repeat(40000), persisted=[];
  const binding=catalogBinding('a2a',{method:'message/send',params:{message:{parts:[{kind:'text',text:'Weather?'}]}}},{request_mode:'json'});
  const f=await fixture(request=>new EdgeResponse(JSON.stringify({jsonrpc:'2.0',id:attempt,result:{kind:'message',parts:[{kind:'text',text:text.slice(0,15000)},
    {kind:'text',text:text.slice(15000,30000)},{kind:'text',text:text.slice(30000)}]}}),
    {headers:{'Content-Type':'application/json'}}),binding,controlOrigin,{direct:true,
    directOrigin(request,body,results) {
      assert.equal(request.method,'GET'); assert.equal(request.headers.get('X-Edge-Result-View'),'v1');
      assert.equal(request.headers.get('X-Workflow-Key'),'private-run-key');
      const source=results[0]; persisted.push(source);
      return recipeResponse([2,{status:[0,'succeeded'],data:[1,run,source.wire_hash,[]]}]);
    }});
  try {
    const receipt=await f.send({'X-Edge-Result-Format':'receipt'}), value=await receipt.json();
    assert.equal(receipt.status,200); assert.ok(Buffer.byteLength(JSON.stringify(value))<220);
    assert.ok(!JSON.stringify(value).includes(text)); assert.equal(f.results.length,1);
    const result=await f.mf.dispatchFetch(origin+'/api/workflows/runs/wr_test',{headers:{'X-Workflow-Key':'private-run-key'}});
    assert.equal(result.headers.get('X-Execution-Delivery'),'edge');
    assert.equal((await result.json()).data.parts.map(p=>p.text).join(''),text);
    assert.equal(persisted.length,1); assert.equal(f.calls.filter(r=>r.url===endpoint).length,1);
    const privateURL=origin+'/api/edge-gateway/v1/private-cache/'+value.wire_hash;
    assert.equal((await f.mf.dispatchFetch(privateURL)).status,404,'Ciphertext cache is not a public endpoint');
  } finally {await f.mf.dispose();}
});

for(const route of ['workflows/runs/wr_test','workflow-apps/app/runs/wpr_test','workflow-apps-v12/app/runs/wpr_test',
  'workspace-apps-v2/app/runs/wpr_test','workspace-flow-apps-v2/app/runs/wfr_test','workspace-apps-v2/app/history','workspace-flow-apps-v2/app/history',
  'customer-organizations/ws/authoring/drafts/draft/snapshots/snapshot/runs/run-1','customer-organizations/ws/authoring/drafts/draft/snapshots/snapshot/runs',
  'customer-organizations/ws/authoring/typed/flows/flow/runs/run-1','customer-organizations/ws/authoring/typed/flows/flow/runs',
  'customer-organizations/ws/authoring/templates/drafts/draft/runs']) {
  test('cache loss recovers the same authorized stored result: '+route,async()=>{
    let authorized=0,recovered=0;
    const f=await fixture(()=>assert.fail('No Provider execution on result GET'),{},controlOrigin,{direct:true,
      directOrigin(request) {authorized++;return recipeResponse([1,run,'0'.repeat(64),[]]);},
      originResponse(request) {recovered++;assert.equal(request.method,'GET');assert.equal(new URL(request.url).pathname,'/api/'+route);
        return new EdgeResponse('{"status":"succeeded","data":"Retained result"}',{headers:{'Content-Type':'application/json'}});}});
    try {
      const response=await f.mf.dispatchFetch(origin+'/api/'+route);
      assert.equal(response.headers.get('X-Execution-Delivery'),'edge'); assert.equal((await response.json()).data,'Retained result');
      assert.equal(authorized,1);assert.equal(recovered,1);assert.equal(f.calls.filter(r=>r.url===endpoint).length,0);
    } finally {await f.mf.dispose();}
  });
}

test('result access denial never consults cache or falls back to another authorization path',async()=>{
  const f=await fixture(()=>assert.fail('No Provider IO'),{},controlOrigin,{direct:true,
    directOrigin:()=>new EdgeResponse('{"error":"Unauthorized"}',{status:401,headers:{'Content-Type':'application/json'}}),
    originResponse:()=>assert.fail('Authorization denial must be final')});
  try {const response=await f.mf.dispatchFetch(origin+'/api/workflows/runs/wr_test');assert.equal(response.status,401);}
  finally {await f.mf.dispose();}
});

test('public MCP directly delivers results while Origin receives only compact preparation and projection responses',async()=>{
  const text='Tokyo '.repeat(2000), binding=catalogBinding('mcp',{method:'tools/call',params:{name:'get_weather',arguments:{city:'Tokyo'}}},
    {mcp_prepared:{protocol_version:'2025-06-18',session_id:null,deadline_ms:Date.now()+7500}});
  const phases=[];
  const f=await fixture(async request=>{const body=await request.json();return new EdgeResponse(JSON.stringify({jsonrpc:'2.0',id:body.id,
    result:{content:[{type:'text',text}],isError:false}}),{headers:{'Content-Type':'application/json'}});},binding,controlOrigin,{direct:true,
    directOrigin(request,body,results) {
      assert.equal(request.headers.get('X-Edge-MCP-Prepare'),'v1');phases.push(body._edge_transport.mode);
      assert.equal(body.params.arguments.idempotency_key,'public-request-1');
      if(body._edge_transport.mode==='prepare') return new EdgeResponse(JSON.stringify({_edge_plan:true,backend:'worker',run_id:run,
        stream_path:path,access_token:ticket(),input:{tool:'get_weather',arguments:{city:'Tokyo'}},visitor:{token:'caller-visitor-token'}}),{headers:{'Content-Type':'application/json'}});
      assert.equal(body.params.arguments.visitor_token,'caller-visitor-token');
      return recipeResponse([2,{jsonrpc:[0,'2.0'],id:[0,'agent-1'],result:[2,{isError:[0,false],structuredContent:[2,{execution:
        [2,{ok:[0,true],result:[1,run,results[0].wire_hash,[]]}]}]}]}]);
    }});
  try {
    const response=await f.mf.dispatchFetch(origin+'/mcp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      jsonrpc:'2.0',id:'agent-1',method:'tools/call',params:{name:'call',arguments:{resource_id:1,tool:'get_weather',arguments:{city:'Tokyo'},idempotency_key:'public-request-1'}}})});
    assert.equal(response.headers.get('X-Execution-Delivery'),'edge');
    const body=await response.json();assert.equal(body.result.isError,false);assert.equal(body.result.structuredContent.execution.result.content[0].text,text);
    assert.deepEqual(phases,['prepare','result']);assert.equal(f.calls.filter(r=>r.url===endpoint).length,1);
    assert.ok(!JSON.stringify(body).includes(endpoint));
  } finally {await f.mf.dispose();}
});

test('MCP lost preparation response pauses instead of repeating on Origin',async()=>{
  const f=await fixture(()=>assert.fail('No Provider execution'),{},controlOrigin,{direct:true,
    directOrigin:()=>{throw new Error('Lost preparation');},originResponse:()=>assert.fail('No ambiguous Origin retry')});
  try {
    const response=await f.mf.dispatchFetch(origin+'/mcp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'call',arguments:{resource_id:1,tool:'read',arguments:{}}}})});
    const body=await response.json();assert.equal(body.result.isError,true);assert.equal(body.result.structuredContent.execution.retry_safe,false);
  } finally {await f.mf.dispose();}
});

test('cross-site MCP calls go to Origin with their page Origin instead of the signed preparation',async()=>{
  const seen=[];
  const f=await fixture(()=>assert.fail('No Provider execution'),{},controlOrigin,{direct:true,
    directOrigin:()=>assert.fail('No signed preparation for a cross-site page'),
    originResponse(request){seen.push(request.headers.get('Origin'));
      return new EdgeResponse('{"jsonrpc":"2.0","id":null,"error":{"code":-32001,"message":"read-only"}}',{status:403,headers:{'Content-Type':'application/json'}});}});
  try {
    const response=await f.mf.dispatchFetch(origin+'/mcp',{method:'POST',headers:{'Content-Type':'application/json','Origin':'https://widget.example'},
      body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'call',arguments:{resource_id:1,tool:'read',arguments:{}}}})});
    assert.equal(response.status,403);assert.deepEqual(seen,['https://widget.example']);
  } finally {await f.mf.dispose();}
});

test('disabling direct rollout forwards protocol and status paths to their original handlers',async()=>{
  const paths=[];
  const f=await fixture(()=>assert.fail('No Provider call'),{},controlOrigin,{originResponse(request){paths.push(new URL(request.url).pathname);
    return new EdgeResponse('{"ok":true}',{headers:{'Content-Type':'application/json'}});}});
  try {
    assert.equal((await f.mf.dispatchFetch(origin+'/mcp',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status,200);
    assert.equal((await f.mf.dispatchFetch(origin+'/api/workflows/runs/wr_test')).status,200);
    assert.deepEqual(paths,['/mcp','/api/workflows/runs/wr_test']);
  } finally {await f.mf.dispose();}
});

test('synchronous webapp POST cache miss recovers with GET and never submits the job twice',async()=>{
  let posted=0,recovered=0;
  const workflowRun='wpr_'+'c'.repeat(32);
  const f=await fixture(()=>assert.fail('No Provider call while retrieving a retained result'),{},controlOrigin,{direct:true,
    directOrigin(request,body){posted++;assert.equal(request.method,'POST');assert.deepEqual(body,{approved:true});
      return new EdgeResponse(JSON.stringify({version:1,recipe:[1,run,'0'.repeat(64),[]],recovery:{run_id:workflowRun}}),{headers:{'Content-Type':resultMedia}});},
    originResponse(request){recovered++;assert.equal(request.method,'GET');assert.equal(request.headers.get('authorization'),'Bearer private-app-capability');
      assert.equal(new URL(request.url).pathname,'/api/workflow-apps/app/runs/'+workflowRun);
      return new EdgeResponse('{"run":{"status":"succeeded","output":"Stored result"}}',{headers:{'Content-Type':'application/json'}});}});
  try {
    const response=await f.mf.dispatchFetch(origin+'/api/workflow-apps/app/runs',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer private-app-capability'},body:'{"approved":true}'});
    assert.equal((await response.json()).run.output,'Stored result');
    assert.equal(response.headers.get('X-Execution-Delivery'),'edge');assert.equal(posted,1);assert.equal(recovered,1);
  } finally {await f.mf.dispose();}
});

test('synchronous webapp POST control failure cannot trigger another POST to Origin',async()=>{
  let posted=0;
  const f=await fixture(()=>assert.fail('No Provider call'),{},controlOrigin,{direct:true,
    directOrigin(request){posted++;return new EdgeResponse('Unavailable',{status:503});},
    originResponse:()=>assert.fail('No second submission after an ambiguous POST')});
  try {
    const response=await f.mf.dispatchFetch(origin+'/api/workspace-apps-v2/app/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    assert.equal(response.status,503);assert.equal(posted,1);
  } finally {await f.mf.dispose();}
});

test('tiny results also prefer Edge, and tampered encrypted cache recovers only the stored result',async()=>{
  let recovered=0;
  const f=await fixture(delta('OK')+done,{},controlOrigin,{direct:true,
    directOrigin(request,body,results){return recipeResponse([1,run,results[0].wire_hash,[]]);},
    originResponse(request){recovered++;assert.equal(request.method,'GET');return new EdgeResponse('{"parts":[{"kind":"text","text":"OK"}]}',{headers:{'Content-Type':'application/json'}});}});
  try {
    const receipt=await f.send({'X-Edge-Result-Format':'receipt'});assert.equal(receipt.status,200);
    const first=await f.mf.dispatchFetch(origin+'/api/workflows/runs/wr_test');
    assert.equal(first.headers.get('X-Execution-Delivery'),'edge');assert.equal((await first.json()).parts[0].text,'OK');
    const hash=f.results[0].wire_hash;
    const name=createHmac('sha256',derive('edge-result-cache-v1')).update(run+':'+hash).digest('hex');
    const url=origin+'/api/edge-gateway/v1/private-cache/'+name;
    assert.equal((await f.mf.dispatchFetch(url)).status,404,'No public cache retrieval, even with its exact address');
    const cache=(await f.mf.getCaches()).default, cached=await cache.match(url), bytes=new Uint8Array(await cached.arrayBuffer());
    assert.equal(Buffer.from(bytes).includes(Buffer.from(f.results[0].wire)),false,'Private cache contains ciphertext');
    bytes[bytes.length-1]^=1;
    await cache.put(url,new EdgeResponse(bytes,{headers:{'Cache-Control':'max-age=600'}}));
    const second=await f.mf.dispatchFetch(origin+'/api/workflows/runs/wr_test');
    assert.equal(second.headers.get('X-Execution-Delivery'),'edge');assert.equal((await second.json()).parts[0].text,'OK');
    assert.equal(recovered,1);assert.equal(f.calls.filter(r=>r.url===endpoint).length,1);
  } finally {await f.mf.dispose();}
});

test('wildcard route siblings preserve cancel, consent, SDK and CORS authorization',async()=>{
  const paths=['/api/workflow-apps/app/runs/run-1/cancel','/api/workflow-apps-v12/app/prepare',
    '/api/workspace-apps-v2/app/exchange','/api/workspace-flow-apps-v2/app/status-capability','/api/workflows/runs/run-1/cancel'];
  const seen=[];
  const f=await fixture(()=>assert.fail('No Provider IO'),{},controlOrigin,{direct:true,originResponse(request){seen.push(new URL(request.url).pathname);
    assert.equal(request.headers.get('Authorization'),'Bearer private-capability');return new EdgeResponse(null,{status:204});}});
  try {
    for(const path of paths) assert.equal((await f.mf.dispatchFetch(origin+path,{method:'OPTIONS',headers:{Authorization:'Bearer private-capability'}})).status,204);
    assert.deepEqual(seen,paths);
  } finally {await f.mf.dispose();}
});

test('MCP inputs outside the direct profile retain the original authorized ingress before admission',async()=>{
  const text='large input '.repeat(800);let forwarded=0;
  const f=await fixture(()=>assert.fail('No Edge Provider dispatch'),{},controlOrigin,{direct:true,originResponse:async request=>{
    forwarded++;assert.equal((await request.json()).params.arguments.arguments.text,text);
    return new EdgeResponse('{"jsonrpc":"2.0","id":1,"result":{"isError":false}}',{headers:{'Content-Type':'application/json'}});}});
  try {
    const response=await f.mf.dispatchFetch(origin+'/mcp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'call',arguments:{resource_id:1,tool:'read',arguments:{text}}}})});
    assert.equal((await response.json()).result.isError,false);assert.equal(forwarded,1);
  } finally {await f.mf.dispose();}
});

for(const fault of ['definitive-provider-failure','lost-result-ack']) {
  test('MCP stored-result finalization preserves '+fault+' without another Provider call',async()=>{
    const binding=catalogBinding('mcp',{method:'tools/call',params:{name:'get_weather',arguments:{city:'Tokyo'}}},
      {mcp_prepared:{protocol_version:'2025-06-18',session_id:null,deadline_ms:Date.now()+7500}});
    const phases=[];
    const f=await fixture(async request=>{
      if(fault==='definitive-provider-failure') return new EdgeResponse('',{status:404});
      const body=await request.json();return new EdgeResponse(JSON.stringify({jsonrpc:'2.0',id:body.id,result:{content:[{type:'text',text:'Restored result'}]}}),{headers:{'Content-Type':'application/json'}});
    },binding,controlOrigin,{direct:true,resultAckLost:fault==='lost-result-ack',directOrigin(request,body,results){
      phases.push(body._edge_transport.mode);
      if(body._edge_transport.mode==='prepare') return new EdgeResponse(JSON.stringify({_edge_plan:true,backend:'worker',run_id:run,
        stream_path:path,access_token:ticket(),input:{tool:'get_weather',arguments:{city:'Tokyo'}},visitor:{token:'caller-visitor-token'}}),{headers:{'Content-Type':'application/json'}});
      if(fault==='definitive-provider-failure') return new EdgeResponse(JSON.stringify({jsonrpc:'2.0',id:1,result:{isError:true,structuredContent:{execution:{outcome:'failed',retry_safe:true}}}}),{headers:{'Content-Type':'application/json'}});
      return recipeResponse([2,{jsonrpc:[0,'2.0'],id:[0,1],result:[2,{isError:[0,false],structuredContent:[1,run,results[0].wire_hash,[]]}]}]);
    }});
    try {
      const response=await f.mf.dispatchFetch(origin+'/mcp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'call',arguments:{resource_id:1,tool:'get_weather',arguments:{city:'Tokyo'}}}})});
      const body=await response.json();
      if(fault==='definitive-provider-failure') {assert.equal(body.result.isError,true);assert.equal(body.result.structuredContent.execution.outcome,'failed');assert.equal((await f.completion).outcome,'failed');}
      else {assert.equal(body.result.isError,false);assert.equal(body.result.structuredContent.content[0].text,'Restored result');}
      assert.deepEqual(phases,['prepare','result']);assert.equal(f.calls.filter(r=>r.url===endpoint).length,1);
    } finally {await f.mf.dispose();}
  });
}

for(const route of ['drafts/draft/snapshots/snapshot/runs','typed/flows/flow/runs','templates/drafts/draft/runs']) {
  test('Customer Workspace POST preserves Cookie, Origin and CSRF: '+route,async()=>{
    let posted=0;
    const f=await fixture(delta('Customer completed')+done,{},controlOrigin,{direct:true,directOrigin(request,body,results){
      assert.equal(request.method,'POST');posted++;
      assert.equal(request.headers.get('Cookie'),'customer=private-session');
      assert.equal(request.headers.get('Origin'),origin);assert.equal(request.headers.get('X-Customer-CSRF'),'private-csrf');
      assert.deepEqual(body,{approved:true});
      return recipeResponse([2,{run:[2,{id:[0,'wpr_'+'c'.repeat(32)],status:[0,'succeeded'],output:[1,run,results[0].wire_hash,[]]}]}]);
    }});
    try {
      assert.equal((await f.send({'X-Edge-Result-Format':'receipt'})).status,200);
      const response=await f.mf.dispatchFetch(origin+'/api/customer-organizations/ws/authoring/'+route,{method:'POST',
        headers:{'Content-Type':'application/json',Cookie:'customer=private-session',Origin:origin,'X-Customer-CSRF':'private-csrf'},body:'{"approved":true}'});
      assert.equal(response.headers.get('X-Execution-Delivery'),'edge');
      assert.equal((await response.json()).run.output.parts[0].text,'Customer completed');
      assert.equal(posted,1);assert.equal(f.calls.filter(r=>r.url===endpoint).length,1);
    } finally {await f.mf.dispose();}
  });
}

test('Admin browser receives output directly with an origin-bound ticket and no Admin credential forwarding',async()=>{
  const local='http://localhost:8200';
  const f=await fixture(delta('Direct Admin output')+done,{admin_delivery:true});
  try {
    const options=await f.mf.dispatchFetch(origin+path,{method:'OPTIONS',headers:{Origin:local,'Access-Control-Request-Method':'POST'}});
    assert.equal(options.headers.get('Access-Control-Allow-Origin'),local);
    assert.equal(options.headers.get('Access-Control-Allow-Credentials'),null);
    const response=await f.send({Origin:local,Authorization:'Bearer '+ticket(local),'X-Edge-Result-Format':'json'});
    assert.equal(response.status,200);assert.equal(response.headers.get('Access-Control-Allow-Origin'),local);
    assert.equal((await response.json()).output.parts[0].text,'Direct Admin output');
    const provider=f.calls.find(r=>r.url===endpoint);assert.equal(provider.headers.get('Origin'),null);
    assert.equal(provider.headers.get('Cookie'),null);assert.equal(provider.headers.get('Authorization'),null);
  } finally {await f.mf.dispose();}
});

test('a public ticket cannot be replayed by another browser origin',async()=>{
  const f=await fixture(()=>assert.fail('No Provider IO'));
  try {
    const response=await f.send({Origin:'https://evil.example',Authorization:'Bearer '+ticket(),'X-Edge-Result-Format':'json'});
    assert.equal(response.status,401);assert.equal(f.calls.length,0);
  } finally {await f.mf.dispose();}
});

for(const size of [2,40000])test('signed synthetic direct-result health probe has no Provider or Origin IO: '+size,async()=>{
  const f=await fixture(()=>assert.fail('No Provider IO'));
  try {
    const healthPath='/api/edge-gateway/v1/health',nonce=randomBytes(16).toString('hex'),timestamp=String(Math.floor(Date.now()/1000));
    const body=JSON.stringify({probe:'direct-result',size});
    const material=['POST',healthPath,timestamp,nonce,createHash('sha256').update(body).digest('hex')].join('\n');
    const response=await f.mf.dispatchFetch(origin+healthPath,{method:'POST',headers:{'Content-Type':'application/json',
      'X-Edge-Time':timestamp,'X-Edge-Nonce':nonce,'X-Edge-Signature':createHmac('sha256',derive('edge-service-v1')).update(material).digest('hex')},body});
    assert.equal(response.status,200);const raw=await response.text();
    assert.equal(response.headers.get('X-Edge-Health-Signature'),createHmac('sha256',derive('edge-health-v1')).update(raw).digest('hex'));
    assert.equal(JSON.parse(raw).size,size);assert.equal(f.calls.length,0);
  } finally {await f.mf.dispose();}
});

test('private computed output is published with service proof and delivered only with an origin-bound short capability',async()=>{
  const f=await fixture(()=>assert.fail('Output delivery cannot execute a Provider'));
  try {
    const clientOrigin='http://localhost:8200',wire=JSON.stringify({status:200,body:{output_text:'Private Agent output'}}),hash=createHash('sha256').update(wire).digest('hex');
    const publishPath='/api/edge-gateway/v1/output-publish',raw=JSON.stringify({run,wire,hash}),stamp=String(Math.floor(Date.now()/1000)),nonce=randomBytes(16).toString('hex');
    const signature=createHmac('sha256',derive('edge-service-v1')).update(['POST',publishPath,stamp,nonce,createHash('sha256').update(raw).digest('hex')].join('\n')).digest('hex');
    const denied=await f.mf.dispatchFetch(origin+publishPath,{method:'POST',body:raw});assert.equal(denied.status,401);
    const published=await f.mf.dispatchFetch(origin+publishPath,{method:'POST',body:raw,headers:{'X-Edge-Time':stamp,'X-Edge-Nonce':nonce,'X-Edge-Signature':signature}});
    assert.equal(published.status,200);assert.deepEqual(await published.json(),{ok:true,run,hash});
    const payload=Buffer.from(JSON.stringify({aud:'edge-output-relay-v1',run,origin:clientOrigin,hash,exp:Math.floor(Date.now()/1000)+120})).toString('base64url');
    const capability=payload+'.'+createHmac('sha256',derive('edge-output-relay-v1')).update(payload).digest('base64url');
    const outputPath='/api/edge-gateway/v1/outputs/'+run;
    const stolen=await f.mf.dispatchFetch(origin+outputPath,{headers:{Origin:'https://evil.example',Authorization:'Bearer '+capability}});assert.equal(stolen.status,401);
    const response=await f.mf.dispatchFetch(origin+outputPath,{headers:{Origin:clientOrigin,Authorization:'Bearer '+capability}});
    assert.equal(response.status,200);assert.equal(response.headers.get('X-Execution-Delivery'),'edge');assert.equal(response.headers.get('Access-Control-Allow-Origin'),clientOrigin);
    assert.equal(response.headers.get('Access-Control-Allow-Credentials'),null);assert.deepEqual(await response.json(),JSON.parse(wire));
    assert.equal(f.calls.filter(r=>r.url===endpoint).length,0);
    for(let n=0;n<200&&f.observations.length<2;n++)await new Promise(resolve=>setTimeout(resolve,10));
    assert.deepEqual(f.observations.map(o=>[o.source,o.reason]),[['admin','delivered'],['admin','delivered']]);
  }finally{await f.mf.dispose();}
});


test('an uncached private 40KB output is recovered through signed control and still delivered by Edge',async()=>{
  const saved={status:200,body:{output_text:'A'.repeat(40000)}},hash=createHash('sha256').update(JSON.stringify(saved)).digest('hex');
  const clientOrigin='http://localhost:8200',payload=Buffer.from(JSON.stringify({aud:'edge-output-relay-v1',run,origin:clientOrigin,hash,exp:Math.floor(Date.now()/1000)+120})).toString('base64url');
  const capability=payload+'.'+createHmac('sha256',derive('edge-output-relay-v1')).update(payload).digest('base64url');
  const f=await fixture(()=>assert.fail('No Provider retry'),{},controlOrigin,{relayRead:saved});
  try {
    const response=await f.mf.dispatchFetch(origin+'/api/edge-gateway/v1/outputs/'+run,{headers:{Origin:clientOrigin,Authorization:'Bearer '+capability}});
    assert.equal(response.status,200);assert.equal(response.headers.get('X-Execution-Delivery'),'edge');assert.deepEqual(await response.json(),saved);
    assert.equal(f.calls.filter(r=>r.url===endpoint).length,0);
    assert.equal((await outputObservation(f)).reason,'origin_relay');
  }finally{await f.mf.dispose();}
});

test('first-party Agent output uses the Edge route while computation stays on its local binding',async()=>{
  const f=await fixture(()=>assert.fail('No second Provider request'),{},controlOrigin,{originResponse:request=>{
    assert.equal(new URL(request.url).pathname,'/api/owned-data-agents/weather/mcp');return new EdgeResponse('{"result":{"answer":"Local result"}}',{headers:{'Content-Type':'application/json'}});
  }});
  try {
    const response=await f.mf.dispatchFetch(origin+'/api/owned-data-agents/weather/mcp',{method:'POST',body:'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'});
    assert.equal(response.headers.get('X-Execution-Delivery'),'edge');assert.equal(response.headers.get('X-Edge-Origin-Output'),'1');
    assert.equal((await response.json()).result.answer,'Local result');assert.equal(f.calls.length,1);
  }finally{await f.mf.dispose();}
});

for (const testbench of [false,true]) test(`owned MCP output computes locally once and stays on Edge: testbench=${testbench}`,async()=>{
  let originCalls=0;
  const f=await fixture(()=>assert.fail('No second Provider invocation'),{protocol:'mcp',request:{
    jsonrpc:'2.0',id:attempt,method:'tools/call',params:{name:'search_technology_news',arguments:{query:'artificial intelligence',limit:1}}
  }},controlOrigin,{
    grant:{backend:'origin'},originResponse(request){
      originCalls++;
      assert.equal(new URL(request.url).pathname,testbench?'/api/test/execute':'/api/gateway/mcp/1');
      assert.equal(request.method,'POST');
      const result=testbench?{ok:true,execution_succeeded:true,output:'Local owned result'}:{jsonrpc:'2.0',id:'caller-1',result:{isError:false,content:[{type:'text',text:'Local owned result'}]}};
      return new EdgeResponse(JSON.stringify(result),
        {headers:{'Content-Type':'application/json'}});
    }});
  try {
    const response=await f.sendLegacy(testbench);
    assert.equal(response.status,200);
    assert.equal(response.headers.get('X-Execution-Delivery'),'edge');
    assert.equal(response.headers.get('X-Edge-Origin-Output'),'1');
    const body=await response.json();
    assert.equal(testbench?body.execution_succeeded:body.result.isError,testbench?true:false);
    assert.equal(originCalls,1);
    assert.equal(f.calls.filter(request=>request.url===endpoint).length,0);
  }finally{await f.mf.dispose();}
});

for (const kind of ['mcp','a2a','x402']) test('public policy denial is actionable and does not dispatch: '+kind, async () => {
  const binding = catalogBinding(kind, kind === 'mcp' ? {method:'tools/call',params:{name:'get_weather',arguments:{city:'Tokyo'}}} : kind === 'x402' ? {method:'probe',params:{}} : {method:'message/send',params:{message:{parts:[{kind:'text',text:'Weather?'}]}}});
  const f=await fixture(()=>assert.fail('Policy refusal must not contact a provider'),binding,controlOrigin,{prepareDenied:true});
  try {
    const response=await f.sendLegacy(),body=await response.json();
    assert.equal(response.status,403);assert.equal(body.error_code,'POLICY_DENIED');assert.equal(body.retryable,false);
    assert.match(body.detail,/Choose another agent/);assert.equal(body.next_action.action,'choose_another_agent');
    assert.equal(response.headers.get('Content-Type'),'application/problem+json');
    assert.ok(!JSON.stringify(body).includes('private control policy'));
    assert.equal(f.calls.filter(r=>r.url===endpoint).length,0);
  } finally {await f.mf.dispose();}
});

test('v1 inspection preserves native payment terms without a v2 header',async()=>{
 const binding=catalogBinding('x402',{method:'probe',params:{}});
 const offer={x402Version:1,error:'Payment required',accepts:[{scheme:'exact',network:'base',maxAmountRequired:'100',asset:'0xasset',payTo:'0xrecipient',maxTimeoutSeconds:60,resource:endpoint,description:'Provider requirement'}]};
 for(const get of [false,true]) {
  const f=await fixture(()=>new EdgeResponse(JSON.stringify(offer),{status:402,headers:{'Content-Type':'application/json'}}),binding,controlOrigin,{get});
  try {
   const response=await f.sendLegacy(),body=await response.json();
   assert.equal(response.status,402);assert.equal(body.x402Version,1);assert.equal(body.accepts[0].maxAmountRequired,'100');
   assert.equal(body.inspection_only,true);assert.equal(body.payment_processed,false);assert.equal(response.headers.get('Payment-Required'),null);
  } finally {await f.mf.dispose();}
 }
});

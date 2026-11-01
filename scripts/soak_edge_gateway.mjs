// Isolated long-running Worker validation. All outbound requests are mocked.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {createHash,createHmac,randomBytes} from 'node:crypto';
import {readFileSync,writeFileSync,appendFileSync,mkdirSync,openSync,readSync,closeSync,createReadStream} from 'node:fs';
import {createInterface} from 'node:readline';
import {resolve} from 'node:path';
const require=createRequire(new URL('../cloudflare/edge-gateway/package.json',import.meta.url));
const {Miniflare,Response:EdgeResponse}=require('miniflare');
const flags=Object.fromEntries(process.argv.slice(2).map(x=>{const n=x.indexOf('=');return [x.slice(2,n),x.slice(n+1)];}));
const output=resolve(flags.output||'reports/edge-provider-validation-2026-10-23/soak');mkdirSync(output,{recursive:true});
const duration=Number(flags.seconds||86400),rate=Number(flags.rate||4),limit=Number(flags.requests||Infinity);
const diagnosticGC=flags['diagnostic-gc']==='true';
assert.ok(duration>0&&duration<=259200&&rate>0&&rate<=16&&limit>0);
const source=resolve(flags.source||'cloudflare/edge-gateway/worker.mjs');
const corpusPath=flags.corpus&&resolve(flags.corpus);
const corpus=[];let corpusFd=null,corpusCursor=0;
if(corpusPath){
 let offset=0;const lines=createInterface({input:createReadStream(corpusPath),crlfDelay:Infinity});
 for await(const line of lines){const length=Buffer.byteLength(line);if(line){const item=JSON.parse(line);if(item.full_tools?.length&&item.full_hash)corpus.push({offset,length});}offset+=length+1;}
 corpusFd=openSync(corpusPath,'r');
}
function corpusEntry(index){const item=corpus[index],buffer=Buffer.allocUnsafe(item.length);assert.equal(readSync(corpusFd,buffer,0,item.length,item.offset),item.length);return JSON.parse(buffer.toString('utf8'));}
const secret=Buffer.alloc(32,'e'),origin='https://agentconcierge.biz',control='https://control.example';
const derive=p=>createHmac('sha256',secret).update(p).digest();
const states=new Map(),pending=new Map(),activeMethods=new Map(),covered=new Set();let sequence=0,providerCalls=0,controlCalls=0,deniedOutbound=0;
let stopping=false;process.on('SIGTERM',()=>{stopping=true;});process.on('SIGINT',()=>{stopping=true;});
const stats={status:'running',started_at:Date.now()/1000,duration_target_seconds:duration,rate_target_rps:rate,source_sha256:createHash('sha256').update(readFileSync(source)).digest('hex'),external_provider_calls:0,completed:0,unexpected_failures:0,expected_failures:0,origin_fallbacks:0,per_scenario:{},memory_samples:[],sleep_gaps:[],latency_reservoir_ms:[],corpus_full_schemas:corpus.length};
const scenarios=['a2a-json','a2a-v1','a2a-sse','mcp-json','mcp-sse','mcp-live-schema','x402','provider-429','invalid-utf8','oversized','origin-fallback','schema-reject'];
function frame(v,end='\n'){return 'event: message'+end+'data: '+JSON.stringify(v)+end+end;}
const json=value=>new EdgeResponse(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
function make(rid,scenario){
 const entry=corpus.length?corpusEntry((scenario==='mcp-live-schema'?corpusCursor++:rid-1)%corpus.length):null;
 const mcp=scenario.startsWith('mcp')||scenario==='schema-reject';const protocol=mcp?'mcp':scenario==='x402'?'x402':'a2a';
 const input=mcp?(entry?.input||{tool:'get_weather',arguments:{city:'Tokyo'}}):protocol==='x402'?{action:'probe'}:{message:'Hello! In one or two sentences, what can you help with?'};
 const tools=entry?.full_tools||[{name:'get_weather',inputSchema:{type:'object'}}];
 const id='er_'+randomBytes(16).toString('hex'),attempt='ea_'+randomBytes(16).toString('hex');
 const endpoint='https://provider.example/api/'+rid, gateway=origin+'/api/gateway/'+protocol+'/'+rid;
 const stream=scenario==='a2a-sse',v1=scenario==='a2a-v1';
 const request={jsonrpc:'2.0',id:attempt,method:mcp?'tools/call':protocol==='x402'?'probe':v1?'SendMessage':stream?'message/stream':'message/send',params:mcp?{name:input.tool,arguments:input.arguments}:protocol==='x402'?{}:{message:{parts:[{kind:'text',text:input.message}]}}};
 const binding={profile:'catalog-public-v1',protocol,spec_version:v1?'1.0':'0.3',request_mode:stream?'stream':'json',attempt_id:attempt,endpoint,gateway_url:gateway,bindings:['https://provider.example/'],request,max_frame_bytes:16384,max_output_bytes:48000,timeout_ms:8000};
 if(mcp){
  if(!['mcp-live-schema','schema-reject'].includes(scenario))binding.mcp_prepared={protocol_version:'2025-06-18',session_id:null,deadline_ms:Date.now()+7500};
  else if(entry?.full_hash)binding.mcp_schema_hash=entry.full_hash;
  binding.mcp_protocol_version='2025-06-18';
 }
 return {rid,scenario,protocol,input,tools,id,attempt,binding,entry,providerCalls:0,toolCalls:0,completion:null};
}
const mf=new Miniflare({modules:true,scriptPath:source,compatibilityDate:'2026-07-30',compatibilityFlags:['enable_request_signal'],port:0,inspectorPort:0,
 bindings:{PUBLIC_ORIGIN:origin,CONTROL_ORIGIN:control,SHARED_SECRET:secret.toString('base64')},outboundService:async req=>{
  const u=new URL(req.url);
  if(u.origin===control){
   controlCalls++;const raw=await req.text(),b=JSON.parse(raw),nonce=req.headers.get('X-Edge-Nonce'),time=req.headers.get('X-Edge-Time');
   const material=['POST',u.pathname,time,nonce,createHash('sha256').update(raw).digest('hex')].join('\n');
   assert.equal(req.headers.get('X-Edge-Signature'),createHmac('sha256',derive('edge-service-v1')).update(material).digest('hex'));
   if(u.pathname.endsWith('/public-prepare')){
    const f=pending.get(b.resource_id);assert.ok(f);assert.deepEqual(b.input,f.input);states.set(f.id,f);
    return json({backend:f.scenario==='origin-fallback'?'origin':'worker',run_id:f.id,stream_path:'/api/'+(f.scenario==='origin-fallback'?'origin':'edge')+'-gateway/v1/runs/'+f.id+'/stream',access_token:'isolated-grant',binding:f.binding});
   }
   const f=states.get(b.run_id);assert.ok(f,'Unknown execution');assert.equal(b.attempt_id,f.attempt);
   if(u.pathname.endsWith('/mcp-schema')){if(f.scenario==='schema-reject')return new EdgeResponse('{"error_code":"SCHEMA_CHANGED"}',{status:409,headers:{'Content-Type':'application/json'}});assert.deepEqual(b.tools,f.tools);assert.deepEqual(b.input,f.input);return json({approved:true});}
   assert.ok(u.pathname.endsWith('/complete'));assert.equal(f.completion,null,'Duplicate completion');f.completion=b;states.delete(f.id);return json({ok:true});
  }
  if(u.origin===origin&&u.pathname.startsWith('/api/origin-gateway/')){
   const f=states.get(u.pathname.split('/')[5]);assert.ok(f&&f.scenario==='origin-fallback');states.delete(f.id);
   return new EdgeResponse('event: result\ndata: '+JSON.stringify({state:'succeeded',output:{parts:[{kind:'text',text:'Origin result'}]}})+'\n\n',{headers:{'Content-Type':'text/event-stream'}});
  }
  if(u.origin!=='https://provider.example'){deniedOutbound++;throw new Error('Unexpected outbound target denied');}
  assert.equal(req.headers.get('Authorization'),null);assert.equal(req.headers.get('Cookie'),null);assert.equal(req.headers.get('X-Real-IP'),null);assert.equal(req.headers.get('CF-Connecting-IP'),null);
  const f=pending.get(Number(u.pathname.split('/').pop()));assert.ok(f);f.providerCalls++;providerCalls++;
  if(f.scenario==='provider-429')return new EdgeResponse(null,{status:429});
  if(f.scenario==='invalid-utf8')return new EdgeResponse(new Uint8Array([255,123]),{headers:{'Content-Type':'application/json'}});
  if(f.scenario==='oversized')return new EdgeResponse(' '.repeat(65537),{headers:{'Content-Type':'application/json'}});
  if(f.protocol==='x402')return new EdgeResponse(JSON.stringify({x402Version:2,resource:{url:f.binding.endpoint},accepts:[{scheme:'exact',network:'eip155:8453',amount:'100',asset:'0xasset',payTo:'0xrecipient',maxTimeoutSeconds:60}]}),{status:402,headers:{'Content-Type':'application/json'}});
  const b=await req.json();assert.equal(b.method,f.binding.request.method==='message/stream'?'message/stream':b.method);
  if(f.protocol==='mcp'){
   if(b.method==='initialize')return json({jsonrpc:'2.0',id:b.id,result:{protocolVersion:'2025-06-18'}});
   if(b.method==='notifications/initialized')return new EdgeResponse(null,{status:202});
   if(b.method==='tools/list')return json({jsonrpc:'2.0',id:b.id,result:{tools:f.scenario==='schema-reject'?[]:f.tools}});
   assert.equal(b.method,'tools/call');f.toolCalls++;
   const result={content:[{type:'text',text:'Ready '+f.binding.endpoint+'; source https://news.example/article'}],structuredContent:{access_token:'secret-test-value',unicode:'\u6771\u4eac'}};
   const wire={jsonrpc:'2.0',id:b.id,result};return f.scenario==='mcp-sse'?new EdgeResponse(frame(wire,sequence%2?'\r':'\r\n'),{headers:{'Content-Type':'text/event-stream'}}):json(wire);
  }
  f.toolCalls++;
  const parts=[{kind:'text',text:'Ready '+f.binding.endpoint},{kind:'data',data:{password:'secret-test-value',source:'https://news.example/article'}}];
  const result=f.scenario==='a2a-v1'?{message:{role:'ROLE_AGENT',parts:parts.map(p=>p.kind==='text'?{text:p.text}:{data:p.data})}}:{kind:'message',role:'agent',parts};
  if(f.scenario==='a2a-sse')return new EdgeResponse(frame({jsonrpc:'2.0',id:b.id,result:{kind:'artifact-update',artifact:{parts}}})+frame({jsonrpc:'2.0',id:b.id,result:{kind:'status-update',status:{state:'completed'},final:true}}),{headers:{'Content-Type':'text/event-stream'}});
  return json({jsonrpc:'2.0',id:b.id,result});
 }});
let ws,seq=0;const rpcPending=new Map();
async function cdp(method,params={}){const id=++seq;return new Promise((res,rej)=>{const timer=setTimeout(()=>{rpcPending.delete(id);rej(new Error('Inspector timeout'));},3000);rpcPending.set(id,{res:v=>{clearTimeout(timer);res(v);},rej:e=>{clearTimeout(timer);rej(e);}});ws.send(JSON.stringify({id,method,params}));});}
async function inspector(){const url=await mf.getInspectorURL();const targets=await(await fetch(new URL('/json',url.toString().replace('ws:','http:')))).json();ws=new WebSocket(targets[0].webSocketDebuggerUrl);await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});ws.addEventListener('message',e=>{const v=JSON.parse(e.data),p=rpcPending.get(v.id);if(p){rpcPending.delete(v.id);v.error?p.rej(new Error(v.error.message)):p.res(v.result);}});}
function save(){const values=stats.latency_reservoir_ms.slice().sort((a,b)=>a-b);const out={...stats,latency_reservoir_ms:undefined,local_latency_p50_ms:values[Math.floor(values.length*.5)]??null,local_latency_p95_ms:values[Math.floor(values.length*.95)]??null,local_latency_p99_ms:values[Math.floor(values.length*.99)]??null,provider_mock_calls:providerCalls,control_mock_calls:controlCalls,unexpected_outbound_targets:deniedOutbound,corpus_schemas_covered:covered.size,pending_mock_runs:states.size,node_rss_bytes:process.memoryUsage().rss,last_updated:Date.now()/1000,elapsed_wall_seconds:Date.now()/1000-stats.started_at};writeFileSync(output+'/summary.json.tmp',JSON.stringify(out,null,2));const fs=require('node:fs');fs.renameSync(output+'/summary.json.tmp',output+'/summary.json');}
async function one(){const rid=++sequence,scenario=scenarios[(rid-1)%scenarios.length],f=make(rid,scenario);pending.set(rid,f);const start=performance.now();
 try{
  const body=f.protocol==='mcp'?{jsonrpc:'2.0',id:rid,method:'tools/call',params:{name:f.input.tool,arguments:f.input.arguments}}:f.protocol==='x402'?{action:'probe'}:{jsonrpc:'2.0',id:rid,method:scenario==='a2a-v1'?'SendMessage':'message/send',params:{message:{parts:[{kind:'text',text:f.input.message}]}}};
  const response=await mf.dispatchFetch(origin+'/api/gateway/'+f.protocol+'/'+rid,{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://downloaded-app.example',Cookie:'browser-secret','Idempotency-Key':'isolated-'+rid},body:JSON.stringify(body)});
  const raw=await response.text(),value=JSON.parse(raw);assert.ok(!raw.includes('provider.example')&&!raw.includes('secret-test-value'));assert.equal(response.headers.get('Access-Control-Allow-Origin'),'*');
  const expectedBad=['provider-429','invalid-utf8','oversized','schema-reject'].includes(scenario);
  assert.equal(Boolean(value.error),expectedBad);
  if(scenario==='origin-fallback'){assert.equal(f.providerCalls,0);stats.origin_fallbacks++;}
  else{
   for(let i=0;i<100&&!f.completion;i++)await new Promise(r=>setTimeout(r,5));
   assert.ok(f.completion,'Missing completion');assert.equal(f.completion.outcome,expectedBad?(scenario==='provider-429'||scenario==='schema-reject'?'failed':'outcome_unknown'):scenario==='x402'?'failed':'succeeded');
   if(scenario==='schema-reject')assert.equal(f.toolCalls,0);
   else if(f.protocol==='mcp')assert.equal(f.toolCalls,1);
  }
  if(f.entry&&scenario==='mcp-live-schema')covered.add(f.entry.id);
  stats.completed++;stats.expected_failures+=Number(expectedBad);stats.per_scenario[scenario]=(stats.per_scenario[scenario]||0)+1;
  stats.latency_reservoir_ms.push(performance.now()-start);if(stats.latency_reservoir_ms.length>4096)stats.latency_reservoir_ms.shift();
 }catch(e){stats.unexpected_failures++;appendFileSync(output+'/failures.jsonl',JSON.stringify({at:Date.now()/1000,scenario,iteration:rid,message:String(e.message).slice(0,300)})+'\n');throw e;}
 finally{states.delete(f.id);pending.delete(rid);}
}
try{
 await inspector();let last=Date.now(),nextMemory=0,nextSave=0;let activeMs=0;
 while(!stopping&&activeMs<duration*1000&&sequence<limit){
  const now=Date.now(),gap=now-last;if(gap>10000){stats.sleep_gaps.push({at:now/1000,seconds:gap/1000});if(stats.sleep_gaps.length>200)stats.sleep_gaps.shift();}else activeMs+=Math.max(0,gap);last=now;stats.active_seconds=activeMs/1000;
  if(now>=nextMemory){const memory=await cdp('Runtime.getHeapUsage');stats.memory_samples.push({at:now/1000,...memory});if(stats.memory_samples.length>1500)stats.memory_samples.shift();assert.ok(memory.usedSize+(memory.backingStorageSize||0)<100*1024*1024,'Worker heap safety threshold');nextMemory=now+60000;}
  const batch=await Promise.allSettled(Array.from({length:Math.min(4,limit-sequence)},()=>one()));const bad=batch.find(x=>x.status==='rejected');if(bad)throw bad.reason;
  if(now>=nextSave){save();nextSave=now+10000;}
  await new Promise(r=>setTimeout(r,Math.max(0,1000*Math.min(4,limit)/rate)));
 }
 stats.status=stopping?'stopped':'completed';assert.equal(stats.unexpected_failures,0);assert.equal(states.size,0);
 if(diagnosticGC){try{stats.diagnostic_heap_before_gc=await cdp('Runtime.getHeapUsage');await cdp('HeapProfiler.collectGarbage');stats.diagnostic_heap_after_gc=await cdp('Runtime.getHeapUsage');}catch{stats.diagnostic_gc_unavailable=true;}}
 save();
}catch(e){stats.status='failed';stats.error=String(e.message).slice(0,300);
 if(diagnosticGC&&ws?.readyState===WebSocket.OPEN){try{stats.diagnostic_heap_before_gc=await cdp('Runtime.getHeapUsage');await cdp('HeapProfiler.collectGarbage');stats.diagnostic_heap_after_gc=await cdp('Runtime.getHeapUsage');}catch{stats.diagnostic_gc_unavailable=true;}}
 save();process.exitCode=1;}
finally{ws?.close();if(corpusFd!==null)closeSync(corpusFd);await mf.dispose();}

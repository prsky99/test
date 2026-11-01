// Run tickets carry only one reviewed execution; private staff authority stays on Origin.
export async function executeEdgeTest(payload, local, guard = () => {}) {
  guard();
  const plan=await local('/test/edge/prepare',payload);
  guard();
  if(plan.backend==='origin') {
    const result=await local('/test/execute',payload);
    return {...result,delivery_backend:result.delivery_backend||'origin',delivery_reason:plan.reason};
  }
  if(plan.backend!=='worker'||!/^er_[a-f0-9]{32}$/.test(plan.run_id)||
      plan.base!=='https://agentconcierge.biz'||plan.stream_path!=='/api/edge-gateway/v1/runs/'+plan.run_id+'/stream')
    throw new Error('The execution authority could not be confirmed.');
  const started=Date.now();let wire=null;
  try {
    // The private Admin session is never sent to the public data plane.
    const response=await fetch(plan.base+plan.stream_path,{method:'POST',credentials:'omit',cache:'no-store',
      signal:AbortSignal.timeout(Math.max(2,Math.min(30,payload.timeout_seconds||10))*1000),
      headers:{'Content-Type':'application/json','Authorization':'Bearer '+plan.access_token,'X-Edge-Result-Format':'json'},
      body:JSON.stringify(plan.input)});
    if(response.ok) {
      const value=await response.json();
      if(value.run_id===plan.run_id&&['worker','origin'].includes(value.backend)&&value.output&&typeof value.output==='object')wire=value;
    }
  } catch (_) { /* Inspect the same durable run before any Origin recovery. */ }
  guard();
  let state=await local('/test/edge/finish',{run_id:plan.run_id,recover:!wire});
  for(let i=0;i<12&&state.state==='dispatch_reserved';i++) {
    await new Promise(resolve=>setTimeout(resolve,150));
    guard();
    state=await local('/test/edge/finish',{run_id:plan.run_id});
  }
  if(state.origin_result)wire={...state.origin_result,run_id:plan.run_id,backend:'origin'};
  const certain=['succeeded','failed'].includes(state.state), ok=state.state==='succeeded';
  const managed=plan.protocol==='x402'?(wire?.output?.managed||wire?.managed):wire?.managed;
  const output=managed?.output||wire?.output;
  return {ok:!!(certain&&ok),execution_succeeded:!!(certain&&ok),simulated:false,is_error:!ok,
    protocol:plan.protocol,delivery_backend:state.backend,latency_ms:Date.now()-started,
    status_code:managed?.status_code||(ok?200:null),tested_at:Date.now()/1000,
    output_text:output?JSON.stringify(output,null,2):(certain?'The agent execution failed.':'The outcome is unconfirmed. Inspect this run before retrying.'),
    error_message:ok?null:(certain?'The agent execution failed.':'The outcome is unconfirmed. Inspect this run before retrying.'),
    error_code:state.error_code,target_url:plan.base+plan.stream_path,
    request_wire:{scope:'client-to-edge',url:plan.base+plan.stream_path,method:'POST',body:plan.input},
    response_wire:output||{state:state.state,error_code:state.error_code}};
}

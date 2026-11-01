function createAgentConciergeClient(config) {
  'use strict';
  const cfg=config || JSON.parse(document.getElementById('wfData').textContent);
  const PROFILE='connected-informational-deployment-v1', origin='https://agentconcierge.biz';
  if(!cfg || Object.keys(cfg).sort().join(',')!=='app_id,profile,publish_key,release_id,sdk_version' ||
      !/^capp_[0-9a-f]{32}$/.test(cfg.app_id || '') || !/^pub_[0-9a-f]{32}$/.test(cfg.release_id || '') ||
      typeof cfg.publish_key!=='string' || !/^cpk_[A-Za-z0-9_-]{43}$/.test(cfg.publish_key) || cfg.profile!==PROFILE || cfg.sdk_version!=='1.3.0') {
    throw new Error('Use a reviewed connected SDK 1.3 application package.');
  }
  const base='/api/workflow-connection-apps-v13/'+cfg.app_id;
  const framed=globalThis.self!==globalThis.top;
  const reviews=new WeakMap(), sessions=new WeakMap();let uncertain=false;
  const terminal=new Set(['succeeded','failed','cancelled']);
  const fault=(message,status=0,transient=false,retryAfter=0)=>Object.assign(new Error(message),{status,transient,retryAfter});
  const aborted=()=>new DOMException('The request was cancelled.','AbortError');
  async function request(path,method,body,key,signal,budget=15000) {
    if(signal?.aborted) throw aborted();
    const controller=new AbortController(),abort=()=>controller.abort();
    signal?.addEventListener('abort',abort,{once:true});
    const timer=setTimeout(abort,Math.max(1,Math.min(15000,budget)));
    try {
      const headers={'X-Publish-Key':cfg.publish_key};
      if(body!==undefined) headers['Content-Type']='application/json';
      if(key) headers['X-Workflow-Key']=key;
      let response;
      try {response=await fetch(origin+base+path,{method,headers,...(body===undefined?{}:{body:JSON.stringify(body)}),mode:'cors',
        credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer',signal:controller.signal});}
      catch(_) {if(signal?.aborted)throw aborted();throw fault(controller.signal.aborted?'The connection request timed out.':'The connection is temporarily unavailable.',0,true);}
      if(!response.ok) {
        const raw=response.headers.get('Retry-After');
        const seconds=raw && /^\d+$/.test(raw)?Number(raw):raw?(Date.parse(raw)-Date.now())/1000:0;
        const retryAfter=Number.isFinite(seconds)?Math.max(0,Math.min(15000,seconds*1000)):0;
        throw fault(response.status===429?'This deployment is temporarily limited.':'The deployment or run is unavailable.',response.status,response.status===429 || response.status>=500,retryAfter);
      }
      try {
        const result=await response.json();
        if(!result || typeof result!=='object' || Array.isArray(result)) throw fault('The connection response is unreadable.');
        return result;
      } catch(error) {if(signal?.aborted)throw aborted();if(controller.signal.aborted)throw fault('The connection response was interrupted.',0,true);throw fault('The connection response is unreadable.');}
    } finally {clearTimeout(timer);signal?.removeEventListener('abort',abort);}
  }
  function deepFreeze(value) {
    if(value && typeof value==='object') {for(const item of Object.values(value))deepFreeze(item);Object.freeze(value);}
    return value;
  }
  function preview(value) {
    const s=value?.source,t=value?.target,c=value?.connection;
    if(!s || Object.keys(s).sort().join(',')!=='contract,input,label' || s.contract!=='news.search.v1' || typeof s.label!=='string' || s.label.length>200 ||
        !s.input || Object.keys(s.input).sort().join(',')!=='from_utc,language,limit,query' || typeof s.input.query!=='string' || !s.input.query || s.input.query.length>500 ||
        s.input.language!=='en' || !Number.isInteger(s.input.limit) || s.input.limit<1 || s.input.limit>5 || typeof s.input.from_utc!=='string' ||
        !t || Object.keys(t).sort().join(',')!=='contract,label,settings' || t.contract!=='docs.search.v1' || typeof t.label!=='string' || t.label.length>200 ||
        !t.settings || Object.keys(t.settings).sort().join(',')!=='language,limit' || t.settings.language!=='en' || !Number.isInteger(t.settings.limit) || t.settings.limit<1 || t.settings.limit>5 ||
        !c || Object.keys(c).sort().join(',')!=='path,target_field' || JSON.stringify(c.path)!=='["items",0,"title"]' || c.target_field!=='query' ||
        value.max_calls!==2 || value.max_seconds!==25 || !Number.isFinite(value.expires) || value.expires<=Date.now()/1000) throw fault('The reviewed title connection is unavailable.');
    return deepFreeze(JSON.parse(JSON.stringify(value)));
  }
  function session(handle) {
    const value=handle && typeof handle==='object'?sessions.get(handle):null;
    if(!value) throw fault('Use this client\'s accepted run handle.');
    return value;
  }
  function pause(duration,signal) {
    return new Promise((resolve,reject)=>{
      if(signal?.aborted)return reject(aborted());
      const abort=()=>{clearTimeout(timer);reject(aborted());};
      const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},duration);
      signal?.addEventListener('abort',abort,{once:true});
    });
  }
  const client={origin,version:'1.3.0',
    async prepare({signal}={}) {
      if(framed)throw fault('Open this application directly in its own browser tab before preparing a run.');
      if(uncertain)throw fault('Inspect the previous uncertain run before requesting another start.');
      const response=await request('/prepare','POST',{},null,signal);
      if(response.ok!==true || response.profile!==PROFILE || response.executed!==false || !response.proposal || typeof response.signature!=='string')throw fault('The deployment review could not be verified.');
      const value=preview(response.preview),handle=Object.freeze({preview:value});
      reviews.set(handle,{proposal:response.proposal,signature:response.signature,expires:value.expires});return handle;
    },
    async run(options={}) {
      if(framed)throw fault('Reviews and runs are unavailable inside a frame. Open the application directly.');
      if(uncertain)throw fault('An earlier start or agent outcome is uncertain. Inspect that run first.');
      if(!options || typeof options!=='object' || Array.isArray(options) || Object.keys(options).some(key=>!['preparation','sharingAuthority','runAuthority','signal'].includes(key)))throw fault('Use a fresh reviewed connection without dynamic inputs.');
      const {preparation,sharingAuthority,runAuthority,signal}=options;
      const reviewed=preparation && reviews.get(preparation);
      if(!reviewed || sharingAuthority!==true || runAuthority!==true)throw fault('Review the future-title rule and separately authorize sharing and one live run.');
      if(reviewed.expires<=Date.now()/1000) {reviews.delete(preparation);throw fault('This review expired. Prepare and authorize a fresh review.');}
      reviews.delete(preparation);
      let result;
      try {
        result=await request('/runs','POST',{proposal:reviewed.proposal,signature:reviewed.signature,
          sharing_authority:true,sharing_notice:'workflow-connection-app-v13-share-v1',run_authority:true,run_notice:'workflow-connection-app-v13-run-v1'},null,signal);
        if(result.ok!==true || result.profile!==PROFILE || !/^wr_[0-9a-f]{32}$/.test(result.run_id || '') || !/^[A-Za-z0-9_-]{43}$/.test(result.run_key || ''))throw fault('The accepted start could not be verified.');
      } catch(error) {uncertain=true;error.startUncertain=true;throw error;}
      const handle=Object.freeze({runId:result.run_id,status:result.status});sessions.set(handle,{id:result.run_id,key:result.run_key,cancelled:false});return handle;
    },
    async status(handle,{signal,budgetMs}={}) {
      const accepted=session(handle),result=await request('/runs/'+accepted.id,'GET',undefined,accepted.key,signal,budgetMs);
      if(!['queued','running','succeeded','failed','cancelled'].includes(result.status))throw fault('The run status could not be verified.');
      if(result.execution_outcome==='unknown' || result.outcome==='unknown')uncertain=true;
      return result;
    },
    async cancel(handle,{signal}={}) {
      const accepted=session(handle);if(accepted.cancelled)throw fault('Cancellation was already requested. Inspect the same run status.');
      accepted.cancelled=true;return request('/runs/'+accepted.id+'/cancel','POST',{},accepted.key,signal);
    },
    async wait(handle,{onUpdate,onRetry,signal,intervalMs=750,timeoutMs=90000}={}) {
      session(handle);
      if(!Number.isInteger(intervalMs) || intervalMs<300 || intervalMs>5000 || !Number.isInteger(timeoutMs) || timeoutMs<1000 || timeoutMs>120000 || [onUpdate,onRetry].some(value=>value!==undefined && typeof value!=='function'))throw fault('Use bounded connection status options.');
      const deadline=Date.now()+timeoutMs;let failures=0;
      while(Date.now()<deadline) {
        let result;
        try {result=await client.status(handle,{signal,budgetMs:deadline-Date.now()});}
        catch(error) {
          if(signal?.aborted || error.name==='AbortError' || !error.transient || ++failures>3)throw error;
          const delay=Math.max(error.retryAfter || 0,Math.min(5000,500*2**failures));if(onRetry)onRetry({attempt:failures,delayMs:delay});
          await pause(Math.min(delay,Math.max(0,deadline-Date.now())),signal);continue;
        }
        failures=0;if(onUpdate)onUpdate(result);
        if(terminal.has(result.status) || result.execution_outcome==='unknown' || result.outcome==='unknown')return result;
        await pause(Math.min(intervalMs,Math.max(0,deadline-Date.now())),signal);
      }
      throw fault('Status monitoring paused. The accepted run may still be active.');
    }
  };
  return Object.freeze(client);
}
globalThis.AgentConciergeWorkflow=Object.freeze({createClient:createAgentConciergeClient});

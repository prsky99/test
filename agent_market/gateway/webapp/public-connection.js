(() => {
  'use strict';
  const $ = id => document.getElementById(id), config = JSON.parse($('connectionData').textContent);
  const PROFILE = 'public-news-title-to-docs-v1';
  const BASE = '/api/workflow-connections/' + encodeURIComponent(config.release_id);
  let epoch = 0, review = null, handle = null, busy = false, uncertain = false, stopping = false, controller = null;
  const terminal = value => ['succeeded','failed','cancelled'].includes(value);
  const text = (parent,tag,value) => {const element=document.createElement(tag);element.textContent=value;parent.append(element);return element;};
  const status = value => {$('connectionStatus').textContent=value;};
  function resetReview() {
    review=null;
    for(const id of ['connectionShare','connectionLive']) {$(id).checked=false;$(id).disabled=true;}
    $('connectionRun').disabled=true;
  }
  function update() {
    $('connectionRun').disabled=busy || !review || !$('connectionShare').checked || !$('connectionLive').checked;
    $('connectionPrepare').disabled=busy || !!handle || uncertain;
  }
  function current(token) {return token===epoch;}
  async function request(path='', method='GET', body, key, signal) {
    const response=await fetch(BASE+path,{method,credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer',
      headers:{...(body===undefined ? {} : {'Content-Type':'application/json'}),...(key ? {'X-Workflow-Key':key} : {})},
      ...(body===undefined ? {} : {body:JSON.stringify(body)}),signal:signal ? AbortSignal.any([signal,AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000)});
    if(!response.ok) {const error=new Error('This connection request is unavailable.');error.status=response.status;throw error;}
    const value=await response.json();
    if(!value || typeof value!=='object' || Array.isArray(value)) throw new Error('The connection response is unavailable.');
    return value;
  }
  function validPreview(p) {
    return p && p.source && typeof p.source.label==='string' && p.source.contract==='news.search.v1' && p.source.input &&
      typeof p.source.input.query==='string' && p.source.input.query.length<=500 && p.source.input.language==='en' &&
      Number.isInteger(p.source.input.limit) && p.source.input.limit>=1 && p.source.input.limit<=5 && typeof p.source.input.from_utc==='string' &&
      p.target && typeof p.target.label==='string' && p.target.contract==='docs.search.v1' && p.target.settings && p.target.settings.language==='en' &&
      Number.isInteger(p.target.settings.limit) && p.target.settings.limit>=1 && p.target.settings.limit<=5 &&
      p.connection && JSON.stringify(p.connection.path)==='["items",0,"title"]' && p.connection.target_field==='query' &&
      p.max_calls===2 && p.max_seconds===25 && Number.isFinite(p.expires);
  }
  function renderPreview(p) {
    const view=$('connectionReview');view.replaceChildren();
    text(view,'h3',p.source.label + ' · News search');text(view,'p','Query: ' + p.source.input.query);
    text(view,'p','Language: English · Result limit: ' + p.source.input.limit);text(view,'p','News window starts: ' + p.source.input.from_utc);
    text(view,'h3',p.target.label + ' · Documentation search');
    text(view,'p','Query: the checked first news result title from this run. Its actual text is not known yet.');
    text(view,'p','Language: English · Result limit: ' + p.target.settings.limit);
    text(view,'p','Only this title is forwarded. Empty, sensitive, address-bearing or over-500-character titles stop the documentation call. Titles are never shortened or converted to another type.');
    text(view,'p','At most two agent calls · 25-second execution deadline · No fallback or automatic execution retry.');
    text(view,'p','Review expires: ' + new Date(p.expires*1000).toISOString() + '. Preparation did not call agents.');
  }
  function citation(parent, value) {
    if(typeof value!=='string' || value.length>2048) return;
    try {
      const url=new URL(value);
      if(!['http:','https:'].includes(url.protocol) || url.username || url.password || /(?:^localhost$|\.localhost$|^127\.|^10\.|^192\.168\.|^169\.254\.|^172\.(?:1[6-9]|2[0-9]|3[01])\.|^\[?::1\]?$)/i.test(url.hostname) || /(?:api[_-]?key|token|secret|password|authorization)=/i.test(url.search)) return;
      const link=document.createElement('a');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Source: ' + url.hostname;parent.append(link);
    } catch(_) {}
  }
  function renderOutput(data) {
    const view=$('connectionResults');view.replaceChildren();
    const run=data.run || data;
    const label=({queued:'queued',running:'running',succeeded:'succeeded',failed:'failed',cancelled:'cancelled'})[run.status] || 'unavailable';
    status(run.execution_outcome==='unknown' || run.outcome==='unknown' ? 'Agent outcome unknown' : 'Connection: ' + label);
    const results=Array.isArray(data.node_results) ? data.node_results.filter(item=>item.type!=='trigger') : [];
    for(const [index,item] of results.entries()) {
      const section=document.createElement('section');text(section,'h2',index===0 ? 'News results' : 'Documentation results');view.append(section);
      if(item.status!=='succeeded') {text(section,'p','This search did not complete with a verified result. A blocked search may receive no call.');continue;}
      const value=item.data && typeof item.data==='object' ? item.data : item.output;
      const result=value && typeof value==='object' ? (value.structuredContent || value) : null;
      if(!result || !Array.isArray(result.items) || result.items.length>5 || typeof result.partial!=='boolean') {text(section,'p','Verified structured results are unavailable.');continue;}
      if(result.partial) text(section,'p','These results are partial.');
      if(!result.items.length) text(section,'p','No matching sources were recorded.');
      for(const item of result.items) {
        if(!item || typeof item.title!=='string') continue;
        const article=document.createElement('article');text(article,'h3',item.title);section.append(article);
        for(const key of ['summary','excerpt']) if(typeof item[key]==='string') text(article,'p',item[key]);
        for(const [key,label] of [['published_at','Published'],['retrieved_at','Retrieved'],['version','Version']]) if(typeof item[key]==='string') text(article,'p',label + ': ' + item[key]);
        citation(article,item.url);
      }
    }
    if(data.resolved_input && typeof data.resolved_input.query==='string') text(view,'p','Actual documentation query: ' + data.resolved_input.query);
  }
  async function monitor(token) {
    if(!handle || !current(token)) return;
    const monitoring=new AbortController();controller=monitoring;let failures=0;
    try {
      for(let count=0;count<90;count++) {
        if(!current(token) || !handle) return;
        let response;
        try {response=await request('/runs/'+encodeURIComponent(handle.run_id),'GET',undefined,handle.run_key,monitoring.signal);failures=0;}
        catch(error) {
          if(monitoring.signal.aborted || !current(token)) return;
          if(++failures>3 || (error.status && error.status<500 && error.status!==429)) throw error;
          await new Promise(resolve=>setTimeout(resolve,Math.min(4000,500*2**failures)));continue;
        }
        if(!current(token) || monitoring.signal.aborted) return;
        renderOutput(response);
        const outcome=response.run || response;
        if(outcome.execution_outcome==='unknown' || outcome.outcome==='unknown') {
          busy=false;uncertain=true;stopping=true;$('connectionCancel').disabled=true;$('connectionResume').hidden=false;
          $('connectionNotice').textContent='An agent may have received this request. Do not repeat it. Resume status only inspects the same retained run; ask the publisher to review its outcome.';
          update();return;
        }
        if(terminal(outcome.status)) {
          handle=null;busy=false;stopping=false;$('connectionCancel').disabled=true;$('connectionResume').hidden=true;update();return;
        }
        await new Promise(resolve=>setTimeout(resolve,750));
      }
      throw new Error('Status monitoring paused.');
    } catch(_) {
      if(!current(token)) return;
      busy=false;$('connectionResume').hidden=false;update();
      status('Status is unavailable. The accepted run may still be active.');
      $('connectionNotice').textContent='Resume status checks the same run without starting another. An interrupted response does not prove that no agent call occurred.';
    }
  }
  $('connectionPrepare').onclick=async()=>{
    if(busy || handle || uncertain) return;
    const token=++epoch;busy=true;resetReview();$('connectionReview').replaceChildren();$('connectionResults').replaceChildren();$('connectionNotice').textContent='';update();
    status('Preparing a review without calling agents…');
    try {
      const response=await request('/prepare','POST',{});
      if(!current(token)) return;
      if(response.ok!==true || response.profile!==PROFILE || !response.proposal || typeof response.signature!=='string' || response.executed!==false || !validPreview(response.preview) || response.preview.expires<=Date.now()/1000) throw new Error();
      review=response;renderPreview(response.preview);$('connectionShare').disabled=false;$('connectionLive').disabled=false;
      status('Review ready. Separately authorize title sharing and one live run.');
    } catch(_) {if(current(token)) status('A current review is unavailable. The connection may have expired or been withdrawn.');}
    finally {if(current(token)) {busy=false;update();}}
  };
  for(const id of ['connectionShare','connectionLive']) $(id).onchange=update;
  $('connectionRun').onclick=async()=>{
    if(busy || !review || !$('connectionShare').checked || !$('connectionLive').checked) return;
    if(review.preview.expires<=Date.now()/1000) {resetReview();update();status('This review expired. Prepare and authorize a new review.');return;}
    const prepared=review,token=++epoch;busy=true;resetReview();update();status('Starting one authorized connection. This request will not be automatically repeated.');
    try {
      const response=await request('/runs','POST',{proposal:prepared.proposal,signature:prepared.signature,
        sharing_authority:true,sharing_notice:'workflow-public-flow-share-v1',run_authority:true,run_notice:'workflow-public-flow-run-v1'});
      if(!current(token)) return;
      if(response.ok!==true || !/^wr_[0-9a-f]{32}$/.test(response.run_id || '') || typeof response.run_key!=='string') throw new Error();
      handle={run_id:response.run_id,run_key:response.run_key};$('connectionCancel').disabled=false;monitor(token);
    } catch(_) {
      if(!current(token)) return;
      busy=false;uncertain=true;update();status('The start outcome could not be confirmed.');
      $('connectionNotice').textContent='Do not repeat this request. Ask the publisher to inspect the connection history; a run may already have been accepted.';
    }
  };
  $('connectionResume').onclick=()=>{if(handle && !busy) {busy=true;$('connectionResume').hidden=true;update();monitor(epoch);}};
  $('connectionCancel').onclick=async()=>{
    if(!handle || stopping) return;
    stopping=true;$('connectionCancel').disabled=true;const token=epoch,accepted=handle;controller?.abort();
    try {await request('/runs/'+encodeURIComponent(accepted.run_id)+'/cancel','POST',undefined,accepted.run_key);if(current(token)) {status('Cancellation requested. An in-flight call may finish.');busy=true;monitor(token);}}
    catch(_) {if(current(token)) {busy=false;status('Cancellation could not be confirmed. Resume status to inspect the same run.');$('connectionResume').hidden=false;update();}}
  };
  window.addEventListener('pagehide',()=>{
    epoch++;controller?.abort();resetReview();handle=null;busy=false;uncertain=false;stopping=false;
    $('connectionReview').replaceChildren();$('connectionResults').replaceChildren();$('connectionNotice').textContent='';$('connectionCancel').disabled=true;$('connectionResume').hidden=true;$('connectionPrepare').disabled=true;status('Local review cleared.');
  });
  (async()=>{
    const token=epoch;
    try {
      const result=await request();if(!current(token)) return;
      const connection=result.release;
      if(result.profile!==PROFILE || !connection || connection.id!==config.release_id || typeof connection.title!=='string') throw new Error();
      $('connectionTitle').textContent=connection.title;$('connectionDescription').textContent=connection.description || 'One news search followed by a documentation search using its checked first result title.';
      if(connection.available!==true) {status('This connection is currently unavailable for new runs. Recorded outcomes remain separate from current availability.');return;}
      $('connectionPrepare').disabled=false;status('Ready for a fresh run review. No agents have been called.');
    } catch(_) {if(current(token)) status('This public connection is unavailable or has been withdrawn.');}
  })();
})();

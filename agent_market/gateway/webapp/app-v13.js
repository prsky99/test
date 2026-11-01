(() => {
  'use strict';
  const $=id=>document.getElementById(id),client=createAgentConciergeClient();
  const prepare=$('prepareAppBtn'),run=$('runAppBtn'),cancel=$('cancelAppBtn'),resume=$('resumeAppBtn');
  const share=$('shareAppAuthority'),live=$('liveAppAuthority'),preview=$('inputReview'),output=$('stepsContainer'),notice=$('appNotice');
  let epoch=0,review=null,handle=null,polling=null,busy=false,uncertain=false,cancelling=false;
  if(window.self!==window.top) {
    prepare.disabled=true;run.disabled=true;cancel.disabled=true;resume.hidden=true;share.checked=false;live.checked=false;share.disabled=true;live.disabled=true;
    $('appStatus').textContent='Open this application directly in its own browser tab.';
    notice.textContent='Reviews and runs are unavailable inside a frame. The publisher must configure embedding protection on the hosting server.';
    return;
  }
  const text=(parent,tag,value)=>{const element=document.createElement(tag);element.textContent=value;parent.append(element);return element;};
  const status=value=>{$('appStatus').textContent=value;};
  const current=value=>value===epoch;
  function clearReview() {review=null;share.checked=false;live.checked=false;share.disabled=true;live.disabled=true;run.disabled=true;}
  function update() {run.disabled=busy || !review || !share.checked || !live.checked;prepare.disabled=busy || !!handle || uncertain;}
  function renderReview(value) {
    preview.replaceChildren();text(preview,'h2','Reviewed inputs and title-sharing rule');
    text(preview,'h3',value.source.label+' · News search');text(preview,'p','Exact query: '+value.source.input.query);
    text(preview,'p','Language: English · Result limit: '+value.source.input.limit);text(preview,'p','News window starts: '+value.source.input.from_utc);
    text(preview,'h3',value.target.label+' · Documentation search');
    text(preview,'p','Query: this run\'s checked first news result title. Its actual text is not known before the news call.');
    text(preview,'p','Language: English · Result limit: '+value.target.settings.limit);
    text(preview,'p','Only the checked title is forwarded. A missing or unsafe title stops the documentation call. No title is shortened or converted to another type.');
    text(preview,'p','At most two calls · 25-second execution deadline · No fallback or automatic execution retry.');
    text(preview,'p','Review expires: '+new Date(value.expires*1000).toISOString()+'. Preparation did not call agents.');
  }
  function citation(parent,value) {
    if(typeof value!=='string' || value.length>2048)return;
    try {
      const url=new URL(value);
      if(!['http:','https:'].includes(url.protocol) || url.username || url.password || /(?:^localhost$|\.localhost$|^127\.|^10\.|^192\.168\.|^169\.254\.|^172\.(?:1[6-9]|2[0-9]|3[01])\.|^\[?::1\]?$)/i.test(url.hostname) || /(?:api[_-]?key|token|secret|password|authorization)=/i.test(url.search))return;
      const link=document.createElement('a');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Source: '+url.hostname;parent.append(link);
    }catch(_){}
  }
  function render(data) {
    output.replaceChildren();const unknown=data.execution_outcome==='unknown' || data.outcome==='unknown';
    status(unknown?'Agent outcome unknown':'Connection: '+data.status);
    const rows=Array.isArray(data.node_results)?data.node_results.filter(row=>row.type!=='trigger'):[];
    for(const [index,row] of rows.entries()) {
      const card=document.createElement('section');output.append(card);text(card,'h2',index===0?'News results':'Documentation results');
      if(row.status!=='succeeded') {text(card,'p','This search did not complete with a verified result. A blocked search may receive no call.');continue;}
      const data=row.data && typeof row.data==='object'?row.data:row.output;
      const result=data && typeof data==='object'?(data.structuredContent || data):null;
      if(!result || !Array.isArray(result.items) || result.items.length>5 || typeof result.partial!=='boolean') {text(card,'p','Verified structured results are unavailable.');continue;}
      if(result.partial)text(card,'p','These results are partial.');if(!result.items.length)text(card,'p','No matching sources were recorded.');
      for(const item of result.items) {
        if(!item || typeof item.title!=='string')continue;
        const article=document.createElement('article');card.append(article);text(article,'h3',item.title);
        for(const name of ['summary','excerpt'])if(typeof item[name]==='string')text(article,'p',item[name]);
        for(const [name,label] of [['published_at','Published'],['retrieved_at','Retrieved'],['version','Version']])if(typeof item[name]==='string')text(article,'p',label+': '+item[name]);
        citation(article,item.url);
      }
    }
  }
  function showResume() {resume.hidden=false;cancel.disabled=cancelling || uncertain;update();}
  async function monitor(token) {
    if(!handle || !current(token))return;
    const accepted=handle,controller=new AbortController();polling=controller;
    try {
      const data=await client.wait(accepted,{signal:controller.signal,onUpdate:value=>{if(current(token) && !controller.signal.aborted)render(value);},
        onRetry:()=>{if(current(token) && !controller.signal.aborted)notice.textContent='Reconnecting to status updates. The accepted run continues.';}});
      if(!current(token) || controller.signal.aborted)return;
      busy=false;cancel.disabled=true;
      if(data.execution_outcome==='unknown' || data.outcome==='unknown') {
        uncertain=true;cancelling=true;notice.textContent='An agent may have received this request. Do not repeat it. Resume status inspects only this retained run; ask the publisher to review its outcome.';showResume();
      } else {handle=null;cancelling=false;resume.hidden=true;notice.replaceChildren();update();}
    } catch(_) {
      if(!current(token) || controller.signal.aborted)return;
      busy=false;status('Status is unavailable. The accepted run may still be active.');
      notice.textContent='Resume status checks the same run without starting another. An interrupted response does not prove that no agent call occurred.';showResume();
    }
  }
  prepare.onclick=async()=>{
    if(busy || handle || uncertain)return;
    const token=++epoch;busy=true;clearReview();preview.replaceChildren();output.replaceChildren();notice.replaceChildren();update();status('Preparing a review without calling agents…');
    try {const prepared=await client.prepare();if(!current(token))return;review=prepared;renderReview(prepared.preview);share.disabled=false;live.disabled=false;status('Review ready. Separately authorize title sharing and one live run.');}
    catch(_) {if(current(token))status('A current deployment review is unavailable. The connection or deployment may have changed or been withdrawn.');}
    finally {if(current(token)){busy=false;update();}}
  };
  share.onchange=live.onchange=update;
  run.onclick=async()=>{
    if(busy || !review || !share.checked || !live.checked)return;
    if(review.preview.expires<=Date.now()/1000){clearReview();update();status('This review expired. Prepare and authorize a fresh review.');return;}
    const prepared=review,token=++epoch;busy=true;clearReview();resume.hidden=true;notice.replaceChildren();output.replaceChildren();update();
    status('Starting one authorized connection. This request will not be repeated automatically.');
    try {const accepted=await client.run({preparation:prepared,sharingAuthority:true,runAuthority:true});if(!current(token))return;handle=accepted;cancel.disabled=false;monitor(token);}
    catch(error) {if(!current(token))return;busy=false;uncertain=error.startUncertain===true;update();cancel.disabled=true;status(uncertain?'The start outcome could not be confirmed.':'A fresh reviewed authorization is required.');notice.textContent=uncertain?'Do not repeat this request. Ask the publisher to inspect deployment history; a run may already have been accepted.':'';}
  };
  resume.onclick=()=>{if(!handle || busy)return;busy=true;resume.hidden=true;update();monitor(epoch);};
  cancel.onclick=async()=>{
    if(!handle || cancelling || uncertain)return;
    cancelling=true;cancel.disabled=true;const token=epoch,accepted=handle;polling?.abort();
    try {await client.cancel(accepted);if(current(token)){status('Cancellation requested. An in-flight call may finish.');busy=true;monitor(token);}}
    catch(_) {if(current(token)){busy=false;status('Cancellation could not be confirmed. Inspect this same run with Resume status.');showResume();}}
  };
  window.addEventListener('pagehide',()=>{
    epoch++;polling?.abort();clearReview();handle=null;polling=null;busy=false;uncertain=true;cancelling=false;
    preview.replaceChildren();output.replaceChildren();notice.textContent='Local state was cleared. An accepted server run may continue; closing this page does not cancel it.';
    prepare.disabled=true;cancel.disabled=true;resume.hidden=true;status('Local review cleared. Reload to check deployment availability.');
  });
  clearReview();cancel.disabled=true;resume.hidden=true;update();status('Ready for a fresh connection review. No agents have been called.');
})();

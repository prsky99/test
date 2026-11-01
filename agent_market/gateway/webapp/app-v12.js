function standaloneAppRuntime() {
  const cfg = JSON.parse(document.getElementById('wfData').textContent);
  const run = document.getElementById('runAppBtn'), cancel = document.getElementById('cancelAppBtn');
  const status = document.getElementById('appStatus'), output = document.getElementById('stepsContainer');
  const notice = document.getElementById('appNotice'), preview = document.getElementById('inputReview');
  const prepare = document.getElementById('prepareAppBtn'), share = document.getElementById('shareAppAuthority'), live = document.getElementById('liveAppAuthority');
  const client = createAgentConciergeClient(cfg), cards = new Map();
  let current = null, polling = null, generation = 0, cancellation = false, busy = false, preparation = null;
  function clearReview() {
    preparation = null; share.checked = false; live.checked = false;
    share.disabled = true; live.disabled = true; run.disabled = true;
  }
  function text(parent, tag, value) {const node=document.createElement(tag);node.textContent=value;parent.append(node);return node;}
  function renderReview(value) {
    preview.replaceChildren(); text(preview,'h2','Exact inputs and recipients');
    for (const recipient of value.recipients) {
      text(preview,'h3',recipient.label);
      text(preview,'p','Query: ' + recipient.input.query);
      text(preview,'p','Language: English · Result limit: ' + recipient.input.limit);
      if(recipient.input.from_utc) text(preview,'p','News window starts: ' + recipient.input.from_utc);
    }
    text(preview,'p','Review expires: ' + new Date(value.expires*1000).toISOString() + '. Preparation did not call agents.');
  }
  function updateRun() {run.disabled=busy || !preparation || !share.checked || !live.checked;}
  share.onchange=live.onchange=updateRun;
  prepare.onclick=async()=>{
    if (busy || current) return;
    const token=++generation; busy=true; prepare.disabled=true; clearReview(); preview.replaceChildren();
    setStatus('Preparing an input review without calling agents…');
    try {
      const review=await client.prepare(); if(token!==generation) return;
      preparation=review; renderReview(review.preview); share.disabled=false; live.disabled=false;
      setStatus('Review ready. Separately authorize sharing and one live run.');
    } catch(error) {if(token===generation) setStatus(error.message);}
    finally {if(token===generation) {busy=false;prepare.disabled=false;updateRun();}}
  };
  function setStatus(value) { if (status.textContent !== value) status.textContent = value; }
  function citation(parent, value) {
    if(typeof value !== 'string' || value.length > 2048) return;
    try {
      const url=new URL(value);
      if(!['http:','https:'].includes(url.protocol) || url.username || url.password || /(?:^localhost$|\.localhost$|^127\.|^10\.|^192\.168\.|^169\.254\.|^172\.(?:1[6-9]|2[0-9]|3[01])\.|^\[?::1\]?$)/i.test(url.hostname) || /(?:api[_-]?key|token|secret|password|authorization)=/i.test(url.search)) return;
      const link=document.createElement('a');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Source: ' + url.hostname;parent.append(link);
    } catch(_) {}
  }
  function renderSearch(body, item) {
    body.replaceChildren();
    if(item.status !== 'succeeded') {
      text(body,'p',item.status === 'running' ? 'This search is running.' : item.status === 'queued' ? 'This search is waiting.' : 'This search did not complete with a verified result. Its external outcome may be unknown.');
      return;
    }
    const raw=item.data && typeof item.data === 'object' ? item.data : item.output;
    const result=raw && typeof raw === 'object' ? (raw.structuredContent || raw) : null;
    if(!result || !Array.isArray(result.items) || result.items.length > 5 || typeof result.partial !== 'boolean' || result.items.some(row=>!row || typeof row.title !== 'string')) {
      text(body,'p','Structured search results are unavailable.');return;
    }
    if(result.partial) text(body,'p','These results are partial.');
    if(!result.items.length) text(body,'p','No matching sources were recorded.');
    for(const row of result.items) {
      const article=document.createElement('article');text(article,'h3',row.title);
      const excerpt=typeof row.excerpt === 'string' ? row.excerpt : typeof row.summary === 'string' ? row.summary : '';
      if(excerpt) text(article,'p',excerpt);
      if(typeof row.published_at === 'string') text(article,'p','Published: ' + row.published_at);
      if(typeof row.retrieved_at === 'string') text(article,'p','Retrieved: ' + row.retrieved_at);
      if(typeof row.version === 'string') text(article,'p','Version: ' + row.version);
      citation(article,row.url);body.append(article);
    }
  }
  function render(data) {
    setStatus('Workflow: ' + data.status);
    if (notice.textContent === 'Reconnecting to status updates. The server run continues.') notice.replaceChildren();
    const items=(Array.isArray(data.node_results) ? data.node_results : []).filter(item=>item.type !== 'trigger' && item.node_id !== 'start');
    const used=new Set();
    items.forEach((item,index)=>{
      const key=typeof item.node_id === 'string' ? item.node_id : 'result-' + index;
      if(used.has(key)) return;used.add(key);
      let saved=cards.get(key);
      if(!saved) {
        const card=document.createElement('section'),heading=document.createElement('h2'),body=document.createElement('div');
        card.append(heading,body);saved={card,heading,body,fingerprint:''};cards.set(key,saved);
      }
      const statusLabel=({queued:'Waiting',running:'Running',succeeded:'Succeeded',failed:'Not completed',blocked:'Blocked',cancelled:'Cancelled'})[item.status] || 'Unavailable';
      const heading='Search ' + (index+1) + ' · ' + statusLabel;
      if(saved.heading.textContent !== heading) saved.heading.textContent=heading;
      let fingerprint;try{fingerprint=JSON.stringify([item.status,item.data,item.output]);}catch(_){fingerprint='unavailable';}
      if(saved.fingerprint !== fingerprint) {renderSearch(saved.body,item);saved.fingerprint=fingerprint;}
      const position=output.children[index];if(position !== saved.card) output.insertBefore(saved.card,position || null);
    });
    for(const [key,saved] of cards) if(!used.has(key)) {saved.card.remove();cards.delete(key);}
  }
  function reset() {
    current = null; polling = null; cancellation = false; busy = false; clearReview();
    prepare.disabled = false; cancel.disabled = true;
  }
  async function monitor(handle, controller, token) {
    try {
      await client.wait(handle, {signal:controller.signal,onUpdate:data => {if(generation===token && !controller.signal.aborted) render(data);},
        onFallback:() => { if(generation===token && !controller.signal.aborted) notice.textContent = 'The gateway confirmed a fallback agent was used.'; },
        onRetry:() => { if(generation===token && !controller.signal.aborted) notice.textContent = 'Reconnecting to status updates. The server run continues.'; }});
      if (generation === token) reset();
    } catch (error) {
      if (generation !== token || controller.signal.aborted) return;
      setStatus(error.message);
      notice.textContent = cancellation ? 'Cancellation was requested. Resume status checks the same run without starting another run.' :
        'The run may still be active. Stop requests server cancellation; Resume status reconnects without starting another run.';
      const resume = document.createElement('button'); resume.textContent = 'Resume status'; resume.type = 'button';
      resume.onclick = () => { notice.replaceChildren(); polling = new AbortController(); monitor(handle,polling,token); };
      notice.append(document.createTextNode(' '),resume);
      cancel.disabled = cancellation;
    }
  }
  cancel.onclick = async () => {
    if (!current || cancellation) return;
    cancellation = true; cancel.disabled = true;
    const handle = current, token = generation;
    polling?.abort();
    try {
      await client.cancel(handle);
      if (generation !== token) return;
      setStatus('Cancellation requested. An in-flight request may finish before stopping.');
      notice.replaceChildren();
      const check = document.createElement('button'); check.type = 'button'; check.textContent = 'Check final status';
      check.onclick = () => {
        if (generation !== token) return;
        check.disabled = true; polling = new AbortController(); monitor(handle,polling,token);
      };
      notice.append(check);
      // Keep Run disabled until the server reports a terminal state.
    } catch (error) {
      if (generation === token) { cancellation = false; cancel.disabled = false; setStatus('Cancellation could not be confirmed. You may retry Stop.'); }
    }
  };
  run.onclick = async () => {
    if (busy || !preparation || !share.checked || !live.checked) return;
    const review=preparation;
    busy=true; prepare.disabled=true; clearReview(); cancel.disabled=true; generation+=1;
    const token=generation;
    output.replaceChildren(); cards.clear(); notice.replaceChildren(); setStatus('Starting one authorized workflow…');
    try {
      const handle=await client.run(cfg.workflow_id,{preparation:review,shareAuthority:true,liveAuthority:true});
      if(token!==generation) return;
      current=handle;
      cancel.disabled=false; polling=new AbortController(); monitor(current,polling,token);
    } catch(error) {
      if(token!==generation) return;
      setStatus(error.message);
      if(error.startUncertain) {
        busy=false; prepare.disabled=true; cancel.disabled=true;
        notice.textContent='The start outcome could not be confirmed. Do not repeat this request. Ask the publisher to inspect the deployment history.';
      } else reset();
    }
  };
  window.addEventListener('pagehide',()=>{
    generation++;polling?.abort();clearReview();current=null;polling=null;cancellation=false;busy=false;
    prepare.disabled=false;cancel.disabled=true;preview.replaceChildren();output.replaceChildren();cards.clear();
    setStatus('Local review cleared.');
    notice.textContent='Local state was cleared. An accepted server run may continue; closing this page does not cancel it.';
  });
}
standaloneAppRuntime();

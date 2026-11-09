
/* Public task discovery, accessible suggestions and explicit sharing of public IDs. */
(() => {
  'use strict';
  const q = selector => document.querySelector(selector);
  const make = (tag, text, className) => { const e = document.createElement(tag); if (text) e.textContent = text; if (className) e.className = className; return e; };
  const label = (value, fallback) => typeof chatLabel === 'function' ? chatLabel(value, fallback) : fallback;
  const validId = value => /^\d{1,10}$/.test(String(value)) && Number(value) > 0 && Number(value) < 2147483648;
  const selected = new Set();
  const publicUrl = (ids, compare = false) => {
    const url = new URL('/new/en/chat.html', location.origin);
    url.searchParams.set(compare ? 'compare' : 'agents', ids.filter(validId).slice(0, 4).join(','));
    return url.href;
  };
  const announce = text => { const status = q('#chatStatus'); if (status) status.textContent = text; };
  async function copyPublicLink(ids, compare) {
    const link = publicUrl(ids, compare);
    try { await navigator.clipboard.writeText(link); announce('Public agent link copied. Your questions and conversation are not shared.'); }
    catch { const input = make('input'); input.value = link; input.readOnly = true; input.setAttribute('aria-label', 'Public agent link'); q('#chatForm')?.append(input); input.select(); announce('Copy the public agent link.'); }
  }
  async function readAgent(id, signal) {
    const response = await fetch('/api/agents/' + Number(id), {signal, credentials:'omit'});
    if (!response.ok) throw new Error('Agent unavailable');
    const data = await response.json(); return data.agent || data;
  }
  function comparisonPanel() {
    let panel = q('#agentComparison');
    if (!panel) { panel = make('section', '', 'chat-compare-panel'); panel.id = 'agentComparison'; panel.setAttribute('aria-label','Compare agents'); panel.hidden = true; q('#secChat')?.append(panel); }
    return panel;
  }
  function safeFields(item) {
    return {name:label(item.display_name || item.name,'Agent #' + item.id), protocol:String(item.kind || '').toUpperCase(),
      purpose:label(item.description || item.summary,'Review the provider connection for its task capabilities.'),
      grade:String(item.eval_grade || item.grade || 'Not graded'), checked:item.last_check_at || item.active_checked_at,
      health:String(item.health_status || 'Not recorded'), verification:item.connection_readiness?.verified_callable ? 'Recent execution confirmed' : 'Review recorded evidence'};
  }
  async function showComparison(ids) {
    ids = [...new Set(ids.filter(validId).map(Number))].slice(0,4);
    if (ids.length < 2) { announce('Select two to four agents to compare.'); return; }
    const panel = comparisonPanel(); if (!panel) return;
    panel.hidden = false; panel.replaceChildren(make('h2','Compare agents'),make('p','Loading the current public records…'));
    try {
      const records = await Promise.all(ids.map(id => readAgent(id)));
      const values = records.map(safeFields); const wrap = make('div','','chat-compare-scroll');
      const table = make('table'); table.append(make('caption','Current recorded evidence. Review each connection before running it.'));
      const head = make('thead'), tr = make('tr'), first = make('th','Recorded field'); first.scope = 'col'; tr.append(first);
      values.forEach(item => {const th = make('th',item.name); th.scope='col';tr.append(th);}); head.append(tr);table.append(head);
      const body=make('tbody');
      for (const [title,key] of [['Protocol','protocol'],['Task capability','purpose'],['Connection status','health'],['Quality grade','grade'],['Execution verification','verification'],['Last connection check','checked']]) {
        const row=make('tr'), th=make('th',title);th.scope='row';row.append(th);
        values.forEach(item=>{let value=item[key];if(key==='checked')value=Number.isFinite(Number(value))&&value?new Date(Number(value)*1000).toLocaleString():'Not recorded';row.append(make('td',String(value||'Not recorded')));});body.append(row);
      }
      table.append(body);wrap.append(table);const share=make('button','Copy comparison link','btn sm');share.type='button';share.onclick=()=>copyPublicLink(ids,true);
      panel.replaceChildren(make('h2','Compare agents'),share,wrap);panel.tabIndex=-1;panel.focus();panel.scrollIntoView({block:'start',behavior:'auto'});
    } catch {panel.replaceChildren(make('h2','Compare agents'),make('p','Some agents are no longer available. Choose current results and try again.'));}
  }
  function bindAgentCard(card, item) {
    if (!validId(item.id) || card.dataset.experienceBound) return;
    card.dataset.experienceBound='true';card.dataset.agentId=String(item.id);
    const source=make('div','','chat-provider-description');source.append(make('span','Provider description'),make('p',safeFields(item).purpose));
    card.querySelector('.chat-result-heading')?.after(source);
    const actions=make('div','','chat-extra-actions'); const share=make('button','Share agent','btn sm');share.type='button';share.onclick=()=>copyPublicLink([item.id],false);
    const compare=make('button','Add to comparison','btn sm');compare.type='button';compare.setAttribute('aria-pressed','false');
    compare.onclick=()=>{const id=Number(item.id);if(selected.has(id))selected.delete(id);else if(selected.size<4)selected.add(id);else {announce('Compare up to four agents at a time.');return;}compare.setAttribute('aria-pressed',String(selected.has(id)));compare.textContent=selected.has(id)?'Remove from comparison':'Add to comparison';announce(selected.size+' agents selected.');};
    const open=make('button','Compare selected','btn sm');open.type='button';open.onclick=()=>showComparison([...selected]);actions.append(share,compare,open);card.append(actions);
    const grade=card.querySelector('.chat-grade');
    if(grade){const button=make('button',grade.textContent,'chat-grade chat-grade-button');button.type='button';button.setAttribute('aria-expanded','false');const details=make('section','','chat-quality-details');details.hidden=true;
      const guide=make('a','Read the quality methodology');guide.href='/new/en/learn.html?guide=quality';
      details.append(make('h3','Quality checks'),make('p','Overall grade is based on recorded checks: availability 25, tool definitions 20, security 20, context 15, protocol conformance 10, provenance and maintenance 10. An overall score does not guarantee task success.'),guide);card.append(details);
      button.onclick=()=>{details.hidden=!details.hidden;button.setAttribute('aria-expanded',String(!details.hidden));};grade.replaceWith(button);}
    for(const old of card.querySelectorAll('.chat-feedback-btn')){
      const button=old.cloneNode(true);old.replaceWith(button);
      button.onclick=()=>{if(card.querySelector('.chat-feedback-reason'))return;const form=make('form','','chat-feedback-reason');const id='feedback-'+item.id+'-'+Date.now();const text=make('label','What happened? (optional)');text.htmlFor=id;const select=make('select');select.id=id;
        const reasons=[['','Choose a reason'],['matched_task','Matched my task'],['connection_failed','Could not connect'],['unrelated_result','Results did not match'],['authorization_required','Provider authorization required'],['incomplete_result','Incomplete response'],['other','Other']];
        reasons.forEach(([value,title])=>{const option=make('option',title);option.value=value;select.append(option);});const submit=make('button','Send feedback','btn sm');submit.type='submit';const cancel=make('button','Cancel','btn sm');cancel.type='button';cancel.onclick=()=>form.remove();form.append(text,select,submit,cancel);
        form.onsubmit=event=>{event.preventDefault();const success=button.dataset.outcome==='worked';form.remove();card.querySelectorAll('.chat-feedback-btn').forEach(b=>b.disabled=true);sendChat(success?'worked 1':'failed 1',success?'It worked: '+safeFields(item).name:'It did not work: '+safeFields(item).name,{intent:'outcome',resource_id:Number(item.id),success,feedback_reason:select.value});};card.append(form);select.focus();};
    }
  }
  if (typeof appendChatBubble === 'function') {
    const previous=appendChatBubble;
    appendChatBubble=function(role,text,payload,...rest){const result=previous(role,text,payload,...rest);if(role!=='user'){const items=payload?.data?.recommendations||[];const bubble=q('#chatMessages .chat-bubble.bot');const cards=bubble?.querySelectorAll('.chat-recommendation')||[];cards.forEach((card,index)=>{if(items[index])bindAgentCard(card,items[index]);});}return result;};
  }
  const messages=q('#chatMessages');
  if(messages){messages.tabIndex=0;messages.setAttribute('aria-label','Agent recommendations, newest first. Scroll to read.');const jump=make('button','Jump to newest reply','btn sm chat-jump-newest');jump.type='button';jump.onclick=()=>{messages.scrollIntoView({block:'start'});messages.focus({preventScroll:true});};q('#chatForm .chat-composer-footer')?.append(jump);}

  // Suggestions are local public task names; typing never transmits a query.
  const input=q('#xQ');
  if(input){const shell=make('div','','task-suggestions'),list=make('div');list.id='agentTaskSuggestions';list.role='listbox';list.setAttribute('aria-label','Suggested tasks');shell.append(list);input.after(shell);input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-controls',list.id);input.setAttribute('aria-expanded','false');input.setAttribute('autocomplete','off');list.hidden=true;let active=-1,options=[];
    const tasks=['Weather forecast','Search GitHub issues','Translate a document','Search research papers','Search official documentation','PostgreSQL database queries','Summarize meeting notes','Generate an image','Search public data','Check package security advisories'];
    const close=()=>{list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;};
    const choose=value=>{input.value=value;close();q('#xGo')?.click();};
    const highlight=()=>{options.forEach((e,i)=>e.setAttribute('aria-selected',String(i===active)));if(active>=0)input.setAttribute('aria-activedescendant',options[active].id);};
    input.addEventListener('input',()=>{const term=input.value.trim().toLowerCase();list.replaceChildren();active=-1;const category=[...(q('#xCategory')?.options||[])].filter(o=>o.value).map(o=>o.textContent);const matches=[...new Set([...tasks,...category])].filter(t=>term.length>=2&&t.toLowerCase().includes(term)).slice(0,6);options=matches.map((text,i)=>{const option=make('div',text);option.id='agentTaskOption-'+i;option.role='option';option.setAttribute('aria-selected','false');option.addEventListener('mousedown',event=>event.preventDefault());option.onclick=()=>choose(text);list.append(option);return option;});list.hidden=!options.length;input.setAttribute('aria-expanded',String(Boolean(options.length)));input.removeAttribute('aria-activedescendant');});
    input.addEventListener('keydown',event=>{if(event.key==='Escape'){close();return;}if(list.hidden)return;if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();event.stopImmediatePropagation();active=(active+(event.key==='ArrowDown'?1:-1)+options.length)%options.length;highlight();}else if(event.key==='Enter'&&active>=0){event.preventDefault();event.stopImmediatePropagation();choose(options[active].textContent);}},true);
    input.addEventListener('blur',()=>setTimeout(close,120));
  }
  window.addEventListener('hashchange',()=>{const tab=location.hash.slice(1).split('?')[0];if(typeof TABS!=='undefined'&&TABS.includes(tab)&&typeof currentTab!=='undefined'&&currentTab!==tab)switchTab(tab);});
  const query=new URLSearchParams(location.search);const hash=new URLSearchParams(location.hash.split('?')[1]||'');
  const ids=String(query.get('compare')||query.get('agents')||hash.get('compare')||hash.get('agents')||'').split(',').filter(validId).slice(0,4);
  if(ids.length){switchTab('chat');if(query.has('compare')||hash.has('compare'))showComparison(ids);else Promise.all(ids.map(id=>readAgent(id))).then(items=>{const messages=q('#chatMessages');const bubble=make('div','','chat-bubble bot');for(const item of items){const card=make('article','','chat-recommendation');const heading=make('div','','chat-result-heading');heading.append(make('strong',safeFields(item).name));card.append(heading);bindAgentCard(card,item);bubble.append(card);}messages?.prepend(bubble);}).catch(()=>announce('This public agent link is no longer available. Search for current agents.'));}
  // 11-10: one-click "Worked / Didn't work" on Explore results. Anonymous; the server keeps no IP or user agent and limits abuse.
  if(typeof renderExplore==='function'){
    const priorExplore=renderExplore;
    renderExplore=function(...args){const value=priorExplore(...args);
      for(const card of document.querySelectorAll('#xResults .acard[data-id]')){
        if(card.querySelector('.explore-feedback'))continue;const id=Number(card.dataset.id);if(!Number.isSafeInteger(id)||id<1)continue;
        const box=document.createElement('div');box.className='explore-feedback actions';const label=document.createElement('span');label.className='caption';label.textContent='Tried it?';label.setAttribute('aria-live','polite');
        const name=(card.querySelector('.t')?.textContent||'this agent').trim().slice(0,80);
        const send=worked=>async event=>{event.stopPropagation();event.preventDefault();box.querySelectorAll('button').forEach(b=>{b.disabled=true;});
          try{const r=await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'omit',body:JSON.stringify({resource_id:id,worked,source:'explore'})});
            label.textContent=r.ok?'Thanks, recorded.':r.status===429?'Thanks. Enough reports from you for now.':'Could not record. Try again later.';}
          catch{label.textContent='Could not record. Try again later.';}};
        for(const [text,worked] of [['Worked',true],["Didn't work",false]]){const b=document.createElement('button');b.type='button';b.className='btn sm';b.textContent=text;b.setAttribute('aria-label',text+': '+name);b.addEventListener('click',send(worked));box.append(b);}
        box.prepend(label);card.append(box);}
      return value;};
  }
  if(query.get('guide')==='quality'){switchTab('learn');if(typeof selectLearnSubTab==='function')selectLearnSubTab('quality');}

  // Browser-native tools expose only public discovery; no execution or payment tools.
  const modelContext=document.modelContext||navigator.modelContext;
  if(modelContext&&typeof modelContext.registerTool==='function'){
    const lifecycle=new AbortController();window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
    const protocol=value=>['auto','any','a2a','mcp','x402'].includes(value)?value:'auto';
    const tools=[{name:'search_agents',description:'Search public agents by task and inspect their recorded capabilities.',inputSchema:{type:'object',properties:{query:{type:'string',minLength:2,maxLength:500},protocol:{type:'string',enum:['auto','any','a2a','mcp','x402']}},required:['query'],additionalProperties:false},annotations:{readOnlyHint:true},async execute(input,{signal}={}){if(typeof input?.query!=='string'||input.query.trim().length<2||input.query.length>500)return{error:'Provide a task between 2 and 500 characters.'};const params=new URLSearchParams({q:input.query,kind:protocol(input.protocol),limit:'3'});const response=await fetch('/api/explore?'+params,{signal,credentials:'omit'});if(!response.ok)return{error:'Discovery unavailable',status:response.status};return response.json();}},
    {name:'recommend_agents',description:'Find up to three relevant agents for a task. Records a session conversation; never runs a provider.',inputSchema:{type:'object',properties:{task:{type:'string',minLength:2,maxLength:2000},protocol:{type:'string',enum:['auto','any','a2a','mcp','x402']}},required:['task'],additionalProperties:false},annotations:{readOnlyHint:false},async execute(input,{signal}={}){if(typeof input?.task!=='string'||input.task.trim().length<2||input.task.length>2000)return{error:'Provide a task between 2 and 2000 characters.'};const headers={'Content-Type':'application/json'};try{const token=sessionStorage.getItem('visitorToken');if(token)headers['X-Visitor-Token']=token;}catch{}const response=await fetch('/chat',{method:'POST',headers,signal,body:JSON.stringify({message:input.task,data:{protocol:protocol(input.protocol)}})});const data=await response.json();if(!response.ok)return{error:data.error_code||'Discovery unavailable',status:response.status};const token=response.headers.get('X-Visitor-Token')||data.visitor?.token;if(token)try{sessionStorage.setItem('visitorToken',token);if(typeof activeVisitorToken!=='undefined')activeVisitorToken=token;}catch{}return{reply:data.reply,recommendations:data.data?.recommendations||[]};}}];
    for(const tool of tools){try{Promise.resolve(modelContext.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch{}}
  }
})();


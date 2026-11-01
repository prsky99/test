/* Pearl presentation bridge. Operating execution and identity boundaries are retained. */
'use strict';
(() => {
  const q = (selector, root=document) => root.querySelector(selector);
  const all = (selector, root=document) => [...root.querySelectorAll(selector)];
  const format = value => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('en-US').format(value) : '—';
  let status = null, pending = null, lastRefresh = 0;
  const notice = q('#pearlConnectionNotice');
  if (location.protocol === 'file:' && notice) notice.hidden = false;
  function text(selector, value, root=document) { all(selector, root).forEach(node => { node.textContent = value; }); }
  function recordedOverview(data) {
    if(status||!Array.isArray(data?.resources)||!data.resources.length)return;
    const supported=data.resources.filter(row=>row.active&&['a2a','mcp','x402'].includes(row.kind));
    const total=supported.reduce((n,row)=>n+row.n,0),reachable=supported.filter(row=>['healthy','reachable'].includes(row.status)).reduce((n,row)=>n+row.n,0);
    text('[data-metric="cataloged"]',format(total));text('[data-metric="reachable"]',format(reachable));
    text('[data-metric="cataloged"] ~ p','Recorded catalog snapshot');
    text('[data-metric="reachable"] ~ p',total?Math.round(reachable*1000/total)/10+'% of recorded listings':'Recorded connection observations');
    if(data.verification){text('[data-metric="execution"]',format(data.verification.completed));text('[data-metric="execution"] ~ p',format(data.verification.successful_resources)+' agents with a successful check');}
    for(const [index,kind]of ['a2a','mcp','x402'].entries()){const count=supported.filter(row=>row.kind===kind).reduce((n,row)=>n+row.n,0);const protocol=q('.home-protocols')?.children[index];if(protocol)text('strong',format(count),protocol);}
    const moment=new Date(Number(data.snapshot_at||data.now)*1000);
    if(Number.isFinite(moment.valueOf()))all('#secOverview time').filter(node=>!node.closest('#daily-catalog-statistics')).forEach(node=>{node.dateTime=moment.toISOString();node.textContent='Recorded '+new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'UTC'}).format(moment)+' UTC';});
    text('[data-metric="with_status_check"] ~ p','Open Agent Status for current status-check coverage.');
    text('#uxHomeSnapshotState','Recorded snapshot · refreshing status…');if(q('#uxHomeSnapshotState'))q('#uxHomeSnapshotState').hidden=false;
  }
  function render(data) {
    status = data;
    for (const [key,value] of Object.entries({cataloged:data.cataloged, reachable:data.reachable, with_status_check:data.with_status_check, execution:data.execution_24h.completed})) text('[data-metric="'+key+'"]',format(value));
    const moment = new Date(data.captured_at_utc);
    if (!Number.isNaN(moment.valueOf())) all('#secOverview time, #secStatus time').filter(node=>!node.closest('#daily-catalog-statistics')).forEach(node => { node.dateTime=moment.toISOString();node.textContent='Updated '+new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'UTC'}).format(moment)+' UTC'; });
    text('[data-metric="with_status_check"] ~ p','Recorded connection observations');
    text('.snapshot-panel .caption','Recorded service data');
    text('[data-metric="reachable"] ~ p',data.reachable_share+'% of current listings');
    text('[data-metric="execution"] ~ p',format(data.execution_24h.successful_resources)+' agents with a successful check');
    text('[data-metric="cataloged"] ~ p','+'+format(data.new_24h)+' newly cataloged · last 24h');
    all('.home-protocols article').forEach((node,i) => text('strong',format(data.by_protocol[i]?.n),node));
    all('.protocol-card').forEach((node,i) => {
      const protocol=data.by_protocol[i]; if(!protocol)return;
      const values=all('dd',node);values[0].textContent=format(protocol.n);values[1].textContent=format(protocol.reachable);
    });
    all('.reachable-list > div').forEach((node,i) => { const protocol=data.by_protocol[i];if(!protocol)return; const dd=q('dd',node),strong=document.createElement('strong');strong.textContent=format(protocol.reachable);dd.replaceChildren(strong,document.createTextNode(' of '+format(protocol.n)+' listings')); });
    for(const protocol of data.by_protocol) for(const [key,value] of Object.entries(protocol.status)) text('[data-status-protocol="'+protocol.label+'"] [data-status="'+key+'"]',format(value));
    for(const key of ['succeeded','failed','unknown'])text('[data-outcome="'+key+'"]',format(data.execution_24h[key]));
    const totals=all('.execution-totals strong');if(totals[0])totals[0].textContent=format(data.execution_24h.completed);if(totals[1])totals[1].textContent=format(data.execution_24h.successful_resources);
    text('.arrival-total',format(data.new_24h));
    const changes=all('.change-card h3');if(changes[0])changes[0].textContent=format(data.new_24h)+' new listings in the last 24 hours';if(changes[1])changes[1].textContent=format(data.execution_24h.completed)+' recorded execution checks';
    const outcomeLine=q('.change-card:nth-child(2) h3 + p');if(outcomeLine)outcomeLine.textContent=format(data.execution_24h.succeeded)+' succeeded · '+format(data.execution_24h.failed)+' failed · '+format(data.execution_24h.unknown)+' unknown';
    const scope=Object.entries(data.execution_24h.by_protocol || {}).filter(([,value]) => Object.values(value).some(n=>n>0)).map(([key])=>key==='x402'?'x402':key.toUpperCase()).join(', ') || 'All protocols';
    text('.execution-scope','Recorded execution attempts · '+scope+' · 24 hours');
    text('.change-card:nth-child(2) .caption',scope+' execution evidence in this window.');
    text('#execution-checks > .caption','Recorded task attempts in the stated window. Connection status is shown separately.');
    all('.category-cards .card').forEach((node,i) => {const category=data.categories[i];if(!category)return;text('strong',format(category.n),node);const a=q('a',node);if(a)a.dataset.pearlFilter='category='+encodeURIComponent(category.id);});
    all('#secOverview .catalog-hero .actions a').forEach(node => {if(node.getAttribute('href')==='#explore'){ const label=[...node.childNodes].find(n=>n.nodeType===Node.TEXT_NODE && n.textContent.trim());if(label)label.textContent='Explore agents'; }});
    text('#snapshot-feedback','Recorded connection observations and task execution checks have distinct scopes.');if(q('#snapshot-feedback'))q('#snapshot-feedback').hidden=true;
    text('#uxHomeSnapshotState','');if(q('#uxHomeSnapshotState'))q('#uxHomeSnapshotState').hidden=true;
  }
  async function refresh(user=false) {
    if(pending)return pending;
    if(!user && status && Date.now()-lastRefresh<2500)return;
    const button=q('[data-pearl-action="refresh-status"]');
    if(user&&button){button.disabled=true;button.setAttribute('aria-busy','true');}
    pending=(async()=>{
      for(const panel of all('#secOverview .snapshot-panel,#secStatus'))panel.setAttribute('aria-busy','true');
      try {const data=await api('/api/pearl/status',{silent:true,timeoutMs:30000,retries:0});if(!Array.isArray(data.by_protocol)||!data.execution_24h)throw Error();render(data);lastRefresh=Date.now();}
      catch {recordedOverview(ovCache);text('#snapshot-feedback','Refresh unavailable. Try Refresh data again.');if(q('#snapshot-feedback'))q('#snapshot-feedback').hidden=false;text('#uxHomeSnapshotState','Status refresh unavailable. Open Agent Status to retry.');if(q('#uxHomeSnapshotState'))q('#uxHomeSnapshotState').hidden=false;}
      finally {for(const panel of all('#secOverview .snapshot-panel,#secStatus'))panel.setAttribute('aria-busy','false');if(button){button.disabled=false;button.removeAttribute('aria-busy');}pending=null;}
    })();
    return pending;
  }
  PAGE_METAS.status = {...PAGE_METAS.overview,title:'Agent Status | Agent Concierge',desc:'Inspect catalog scale, recorded endpoint observations and execution checks.'};
  if(['overview','status'].includes(currentTab))updatePageMeta(currentTab);
  function activateReportTab(tab) {
    const group=tab.parentElement;
    all('[role="tab"]',group).forEach(node=>{node.setAttribute('aria-selected',String(node===tab));node.tabIndex=node===tab?0:-1;});
    all('[data-tab-panel]',group.parentElement).forEach(node=>{node.hidden=node.dataset.tabPanel!==tab.dataset.tab;});
  }
  document.addEventListener('click',event=>{const tab=event.target.closest('.evidence-preview [role="tab"]');if(tab)activateReportTab(tab);});
  document.addEventListener('keydown',event=>{const tab=event.target.closest('.evidence-preview [role="tab"]');if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const tabs=all('[role="tab"]',tab.parentElement);const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(tabs.indexOf(tab)+(event.key==='ArrowLeft'?-1:1)+tabs.length)%tabs.length;event.preventDefault();activateReportTab(tabs[next]);tabs[next].focus();});
  const oldExplore = renderExplore;
  function previewAgent(item) {
    const panel=q('#pearlAgentPreview');if(!panel||!item)return;
    const badge=document.createElement('span');badge.className='badge protocol';badge.textContent=String(item.kind||'').toUpperCase();
    const name=document.createElement('h3');name.textContent=item.name||'Agent';
    const description=document.createElement('p');description.textContent=item.description||'Review this agent’s public connection details.';
    const evidence=document.createElement('p');evidence.className='caption';evidence.textContent='Recorded checks describe past observations. Availability can change.';
    const button=document.createElement('button');button.type='button';button.className='btn primary block';button.textContent='Inspect agent and evidence';button.addEventListener('click',()=>openAgent(item.id));
    panel.replaceChildren(badge,name,description,evidence,button);
  }
  renderExplore = function(...args){oldExplore(...args);all('#xResults .acard').forEach(card=>{card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label','View '+(q('.t',card)?.textContent||'agent')+' details');const actions=document.createElement('div');actions.className='pearl-result-actions';const label=document.createElement('span');label.textContent='View details →';actions.append(label);card.append(actions);card.addEventListener('click',()=>previewAgent(EXPLORE_AGENT_MAP.get(card.dataset.id)));});previewAgent(args[0]?.[0]);};
  function workflowChoices() {
    const group=q('#pearlWorkflowChoices');if(!group)return;
    const ordered=frontTemplatesCache.filter(t=>t?.id&&!String(t.name||'').startsWith('[')&&!String(t.tags||'').toLowerCase().includes('test'));
    let form=q('#pearlWorkflowFind',group),state=q('#pearlWorkflowChoiceState',group);
    if(!form){
      form=document.createElement('form');form.id='pearlWorkflowFind';form.setAttribute('role','search');form.setAttribute('aria-label','Find a workflow template');
      const label=document.createElement('label');label.htmlFor='pearlWorkflowSearch';label.textContent='What would you like to do?';
      const row=document.createElement('div');row.className='ux-workflow-find-row';
      const input=document.createElement('input');input.id='pearlWorkflowSearch';input.type='search';input.maxLength=160;input.placeholder='Search a task, topic or agent';input.setAttribute('aria-describedby','pearlWorkflowChoiceState');
      const search=document.createElement('button');search.type='submit';search.className='btn';search.setAttribute('aria-label','Find templates');const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('width','18');icon.setAttribute('height','18');icon.setAttribute('fill','none');icon.setAttribute('stroke','currentColor');icon.setAttribute('stroke-width','2');icon.setAttribute('aria-hidden','true');const circle=document.createElementNS(icon.namespaceURI,'circle');circle.setAttribute('cx','11');circle.setAttribute('cy','11');circle.setAttribute('r','8');const handle=document.createElementNS(icon.namespaceURI,'path');handle.setAttribute('d','m21 21-4.3-4.3');icon.append(circle,handle);const caption=document.createElement('span');caption.textContent='Find templates';search.append(icon,caption);
      row.append(input,search);form.append(label,row);
      form.addEventListener('submit',event=>{event.preventDefault();window.openWorkflowLibrary?.(input.value.trim());});
      state=document.createElement('p');state.id='pearlWorkflowChoiceState';state.className='ux-workflow-find-state';state.setAttribute('role','status');
      group.replaceChildren(form,state);
    }
    group.dataset.selectedId=frontActiveTemplateId?String(frontActiveTemplateId):'';
    group.setAttribute('aria-busy',String(!ordered.length&&!frontTemplatesLoaded&&!frontTemplatesLoadFailed));
    const message=ordered.length?format(ordered.length)+' published templates · Search by task or browse.':frontTemplatesLoadFailed?'Workflows could not be loaded. Use Retry workflows to try again.':!frontTemplatesLoaded?'Loading available workflows…':'No published workflows are available right now.';
    if(state.textContent!==message)state.textContent=message;
  }
  const oldTemplates=renderFrontTemplates;
  renderFrontTemplates=function(...args){oldTemplates(...args);workflowChoices();};
  const oldActiveName=updateFrontActiveName;
  updateFrontActiveName=function(...args){oldActiveName(...args);workflowChoices();};
  if(frontTemplatesCache.length)workflowChoices();
  const originalNodeCenter=getNodeCenterPos;
  getNodeCenterPos=function(id,port){const node=frontCanvasGraph.nodes.find(n=>n.id===id);if(!node)return originalNodeCenter(id,port);const pos=frontNodePosition(node);return {x:pos.x+(port==='input'?75:165),y:pos.y+45};};
  const originalRecipes=renderTestbenchRecipes;
  let initialExampleApplied=location.hash.startsWith('#test?id='),testInputEdited=false;
  document.addEventListener('click',event=>{if(event.target.closest('#drawerTestBtn,.chat-review-task,[data-ac-click="6e3f51eea966"]')){initialExampleApplied=true;testInputEdited=true;}},true);
  for(const type of ['input','change','click'])document.addEventListener(type,event=>{if(event.target.closest('#secTest')&&!event.target.closest('#pearlRetryExamples')&&!initialExampleApplied)testInputEdited=true;},true);
  renderTestbenchRecipes=function(){
    const group=q('#testbenchRecipesGrid');if(!group)return originalRecipes();group.replaceChildren();
    const loading=tbExamplesState==='loading'||tbExamplesState==='idle';
    group.setAttribute('aria-busy',String(loading));
    const message=q('#pearlExampleLoadState'),retry=q('#pearlRetryExamples');
    if(message)message.textContent=tbExamplesState==='error'?'Examples could not be refreshed. Retry or choose another agent.':loading?'Checking example availability…':tbLiveExamples.length?'Choose an example, review its input, then run it.':'No examples are currently published.';
    if(retry){retry.hidden=tbExamplesState!=='error';retry.disabled=loading;}
    if(!tbLiveExamples.length){
      if(loading||tbExamplesState==='error'){
        let previews=[];try{previews=JSON.parse(group.dataset.examplePreviews||'[]');}catch{}
        for(const preview of previews){const button=document.createElement('button');button.type='button';button.className='side-item pearl-example-preview';button.disabled=true;const name=document.createElement('strong');name.textContent=preview.title;const description=document.createElement('span');description.className='pearl-example-description';description.textContent=preview.description;const state=document.createElement('span');state.className='pearl-example-state';state.textContent=loading?'Checking availability…':'Not loaded';button.append(name,description,state);group.append(button);}
      }
      return;
    }
    for(const example of tbLiveExamples){
      const selected=String(q('#tbAgentSelect')?.value)===String(example.resource_id||example.presetId);
      const button=document.createElement('button');button.type='button';button.className='side-item pearl-example-choice'+(selected?' active':'');button.dataset.recipe=example.id;button.setAttribute('data-ac-click','ca285c7fb9a7');button.setAttribute('aria-pressed',String(selected));button.disabled=!example.available;
      button.addEventListener('click',()=>all('.pearl-example-choice').forEach(node=>{const selected=node===button;node.classList.toggle('active',selected);node.setAttribute('aria-pressed',String(selected));}));
      const name=document.createElement('strong');name.textContent=example.title;
      const description=document.createElement('span');description.className='pearl-example-description';description.textContent=example.available?example.desc:(example.execution_availability?.message||'This example is currently unavailable.');
      const state=document.createElement('span');state.className='pearl-example-state';state.textContent=example.available?String(example.protocol||'').toUpperCase()+' · Sample request':'Currently unavailable';
      button.append(name,description,state);group.append(button);
    }
  };
  const originalPopulateTestbench=populateTestbenchAgentSelect;
  populateTestbenchAgentSelect=function(...args){
    const value=originalPopulateTestbench(...args);
    const preferred=tbLiveExamples.find(example=>example.available&&/news/i.test(example.title))||tbLiveExamples.find(example=>example.available);
    if(preferred&&!initialExampleApplied&&!testInputEdited&&currentTab==='test'&&!args[0]&&(!tbSelectionTarget||Number(tbSelectionTarget)<=0||tbLiveExamples.some(example=>String(example.resource_id)===String(tbSelectionTarget)))){initialExampleApplied=true;loadTestbenchRecipe(preferred.id);}
    return value;
  };
  renderTestbenchRecipes();
  q('#pearlRetryExamples')?.addEventListener('click',()=>loadTestbenchUI());
  function policyTabs(){q('#legalModalTabs')?.setAttribute('aria-orientation',innerWidth<=700?'horizontal':'vertical');all('#legalModalTabs .legal-tab-btn').forEach(button=>{const active=button.classList.contains('active');button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;if(active)q('#legalModalBody')?.setAttribute('aria-labelledby',button.id);});}
  const originalSwitchDoc=switchLegalDoc;switchLegalDoc=function(...args){originalSwitchDoc(...args);policyTabs();};
  const originalOpenLegal=openLegalModal;openLegalModal=function(...args){originalOpenLegal(...args);policyTabs();};
  q('#legalModalTabs')?.addEventListener('keydown',event=>{const button=event.target.closest('.legal-tab-btn');if(!button||!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const tabs=all('#legalModalTabs .legal-tab-btn'),index=tabs.indexOf(button),next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(['ArrowUp','ArrowLeft'].includes(event.key)?-1:1)+tabs.length)%tabs.length;switchLegalDoc(tabs[next].dataset.doc);tabs[next].focus({preventScroll:true});});
  const kind=q('#xKind');
  if(kind){
    const segmented=document.createElement('div');segmented.className='pearl-protocol-segmented';segmented.setAttribute('role','group');segmented.setAttribute('aria-label','Search protocol');
    function sync(){all('button',segmented).forEach(button=>{button.setAttribute('aria-pressed',String(button.dataset.kind===kind.value));});}
    segmented.setAttribute('aria-describedby','xProtocolHelp');
    for(const [value,label]of [['','A2A + MCP'],['a2a','A2A'],['mcp','MCP'],['x402','x402']]){const button=document.createElement('button');button.type='button';button.dataset.kind=value;button.textContent=label;button.addEventListener('click',()=>{kind.value=value;kind.dispatchEvent(new Event('change',{bubbles:true}));sync();});segmented.append(button);}
    kind.classList.add('pearl-native-select');kind.tabIndex=-1;kind.setAttribute('aria-hidden','true');kind.parentElement.append(segmented);kind.addEventListener('change',sync);document.addEventListener('explore-state-restored',sync);sync();
    const oldFilter=filter;filter=function(...args){oldFilter(...args);sync();};
  }
  const shortcuts=q('#xChips');
  if(shortcuts){const buttons=all('button',shortcuts),pick=[['News','News',null],['Web Search','Research','research papers'],['PDF & Docs','Documentation','documentation'],['Weather','Weather','weather']];const primary=[];
    for(const [label,query]of [['Stock Quotes','stock quotes'],['Crypto Prices','crypto prices']]){const button=buttons.find(node=>node.textContent.trim()===label);if(button)button.dataset.q=query;}
    for(const [source,label,query]of pick){const button=buttons.find(node=>node.textContent.trim()===source);if(button){button.textContent=label;if(query)button.dataset.q=query;primary.push(button);}}
    const details=document.createElement('details');details.className='pearl-more-tasks';const summary=document.createElement('summary');summary.textContent='More tasks';details.append(summary);for(const button of buttons)if(!primary.includes(button))details.append(button);shortcuts.replaceChildren(...primary,details);
  }
  document.addEventListener('click',event=>{const recipe=event.target.closest('[data-recipe]');if(recipe)all('.testbench-recipe-card').forEach(card=>card.classList.toggle('pearl-selected',card.contains(recipe)));});
  document.addEventListener('keydown',event=>{const card=event.target.closest('.acard');if(card&&event.target===card&&['Enter',' '].includes(event.key)){event.preventDefault();card.click();}});
  const oldOverview = renderOverview;
  renderOverview = function(data){oldOverview(data);recordedOverview(data);if(currentTab==='overview')refresh();};
  recordedOverview(ovCache);
  const oldSwitch = switchTab;
  switchTab = function(tab){oldSwitch(tab);q('#navTabs')?.classList.remove('pearl-open');q('[data-pearl-action="menu"]')?.setAttribute('aria-expanded','false');if(tab==='status'&&!status)refresh();};
  try { const theme=sessionStorage.getItem('pearl-preview:theme');document.body.dataset.theme=theme || (matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'); } catch {document.body.dataset.theme='light';}
  const themeButton=q('[data-pearl-action="theme"]');if(themeButton)themeButton.setAttribute('aria-pressed',String(document.body.dataset.theme==='dark'));
  function filter(query) {
    populateCategorySelects();
    const params=new URLSearchParams(query),protocol=params.get('protocol'),category=params.get('category');
    const categoryIds={'Docs, Knowledge Bases & RAG':'docs_knowledge','Web Search & Scraping':'web_search','Data Utilities & Format Conversion':'data_utility','Database & Analytics':'database_analytics'};
    q('#xKind').value=['A2A','MCP','x402'].includes(protocol)?protocol.toLowerCase():'';
    q('#xQ').value='';
    for(const id of ['xVerified','xNoAuth','xHasReport'])q('#'+id).checked=false;
    if(category){const id=categoryIds[category]||category;if(all('#xCategory option').some(o=>o.value===id))q('#xCategory').value=id;}
    else q('#xCategory').value='';
    const loaded=initializedPanels.has('explore');switchTab('explore');if(loaded)loadExplore(false,false,true);
  }
  document.addEventListener('click',event=>{
    const anchored=event.target.closest('[data-pearl-anchor]');if(anchored){event.preventDefault();const tab=anchored.getAttribute('href').slice(1);if(TABS.includes(tab)){switchTab(tab);q('#'+CSS.escape(anchored.dataset.pearlAnchor))?.scrollIntoView({behavior:'auto',block:'start'});}return;}
    const filtered=event.target.closest('[data-pearl-filter]');if(filtered){event.preventDefault();filter(filtered.dataset.pearlFilter);return;}
    const button=event.target.closest('[data-pearl-action]');if(!button)return;
    const action=button.dataset.pearlAction;
    if(action==='refresh-status')refresh(true);
    if(action==='theme'){const dark=document.body.dataset.theme!=='dark';document.body.dataset.theme=dark?'dark':'light';button.setAttribute('aria-pressed',String(dark));try{sessionStorage.setItem('pearl-preview:theme',dark?'dark':'light');}catch{}}
    if(action==='menu'){const open=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(open));q('#navTabs').classList.toggle('pearl-open',open);}
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){q('#navTabs')?.classList.remove('pearl-open');q('[data-pearl-action="menu"]')?.setAttribute('aria-expanded','false');}});
  const home=q('.home-query');home?.addEventListener('submit',event=>{event.preventDefault();const input=q('#home-task');switchTab('chat');q('#chatInput').value=input.value;const protocol=q('#chatProtocol');if(protocol){protocol.value=q('#home-protocol').value.toLowerCase();protocol.dispatchEvent(new Event('change',{bubbles:true}));}if(input.value.trim())q('#chatForm').requestSubmit();});
  all('[data-tab="status"]').forEach(button=>button.addEventListener('click',()=>{if(!status)refresh();}));
  if(currentTab==='overview'||currentTab==='status')refresh();
  if(location.hash==='#cookie-preferences')openCookiePrefsModal();
})();

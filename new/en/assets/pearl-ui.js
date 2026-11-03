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
    text('.change-card:nth-child(2) .caption','Execution evidence for '+scope.replace(/, ([^,]*)$/,' and $1')+' in this window.');
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

/* Shared Learn interactions and semantic badge presentation. */
'use strict';
(() => {
  const all=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const q=(selector,root=document)=>root.querySelector(selector);
  const guide=q('.reference-learn-body');
  const topics=guide?all('[data-learn-tab]',guide):[];
  function activate(topic,focus=false) {
    const tab=topics.find(node=>node.dataset.learnTab===topic);
    if(!tab)return;
    for(const node of topics){const selected=node===tab;node.classList.toggle('active',selected);node.setAttribute('aria-selected',String(selected));node.tabIndex=selected?0:-1;}
    for(const panel of all('.reference-learn-panels>[role="tabpanel"]',guide))panel.hidden=panel.id!==tab.getAttribute('aria-controls');
    if(focus)tab.focus({preventScroll:true});
  }
  if(guide&&topics.length){
    const search=document.createElement('section');search.className='learn-guide-search card';
    const label=document.createElement('label');label.htmlFor='learnGuideSearch';label.textContent='Search learning guides';
    const input=document.createElement('input');input.type='search';input.id='learnGuideSearch';input.className='input';input.maxLength=120;input.autocomplete='off';input.placeholder='Try MCP, workflows, or verification';input.setAttribute('aria-controls','learnGuideResults');
    const results=document.createElement('div');results.id='learnGuideResults';results.className='learn-guide-results';
    const status=document.createElement('p');status.className='muted';status.setAttribute('role','status');
    search.append(label,input,status,results);guide.prepend(search);
    input.addEventListener('input',()=>{
      results.replaceChildren();const query=input.value.trim().toLocaleLowerCase();
      if(!query){status.textContent='';return;}
      const matches=all('.reference-learn-panels>[role="tabpanel"] h2,.reference-learn-panels>[role="tabpanel"] h3',guide).filter(heading=>{
        const section=heading.closest('.card,article,section')||heading.parentElement;
        return section.textContent.toLocaleLowerCase().includes(query);
      }).slice(0,20);
      const protocols=Object.entries(protocolDetails).filter(([key,values])=>(key+' '+values.join(' ')).toLocaleLowerCase().includes(query));
      const count=matches.length+protocols.length;
      status.textContent=count?count+' matching guides':'No matching guides. Try a protocol or task name.';
      for(const [key,values] of protocols){const button=document.createElement('button');button.type='button';button.className='btn';button.textContent=values[0];button.addEventListener('click',()=>{activate('basics');q('[data-learn-protocol="'+key+'"]')?.click();q('#learn-protocol-context')?.scrollIntoView({block:'center'});});results.append(button);}
      for(const heading of matches){
        const button=document.createElement('button');button.type='button';button.className='btn';button.textContent=heading.textContent;
        button.addEventListener('click',()=>{const panel=heading.closest('[role="tabpanel"]');const tab=topics.find(t=>t.getAttribute('aria-controls')===panel?.id);if(tab)activate(tab.dataset.learnTab);heading.tabIndex=-1;heading.focus({preventScroll:true});heading.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});});
        results.append(button);
      }
    });
  }
  const protocolDetails={
    a2a:['A2A: agent collaboration','Use an agent’s supported connection to delegate a task and inspect its returned result.','Review the selected agent, its expected input and the scope of the task before connecting.'],
    mcp:['MCP: tools and resources','An agent can use exposed tools, data and resources through a supported MCP connection.','Inspect the available capability, its required arguments and the information it receives.'],
    x402:['x402: HTTP service access','A service can communicate its access requirements through HTTP.','Review the provider’s current requirements and the intended request before using the service.']
  };
  document.addEventListener('click',event=>{
    const tab=event.target.closest('[data-learn-tab]');if(tab&&guide?.contains(tab)){activate(tab.dataset.learnTab);return;}
    const protocol=event.target.closest('[data-learn-protocol]');if(!protocol||!protocolDetails[protocol.dataset.learnProtocol])return;
    activate('basics');
    for(const node of all('[data-learn-protocol]')){const selected=node===protocol;node.setAttribute('aria-pressed',String(selected));node.closest('.card')?.classList.toggle('protocol-selected',selected);}
    const context=q('#learn-protocol-context');if(!context)return;
    const [title,description,review]=protocolDetails[protocol.dataset.learnProtocol];
    const heading=document.createElement('h3');heading.textContent=title;
    const text=document.createElement('p');text.textContent=description;
    const note=document.createElement('p');note.textContent=review;
    context.replaceChildren(heading,text,note);context.hidden=false;
  });
  guide?.addEventListener('keydown',event=>{
    const tab=event.target.closest('[data-learn-tab]');if(!tab)return;
    const key=event.key;if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End'].includes(key))return;
    event.preventDefault();const index=topics.indexOf(tab),next=key==='Home'?0:key==='End'?topics.length-1:(index+(['ArrowUp','ArrowLeft'].includes(key)?-1:1)+topics.length)%topics.length;
    activate(topics[next].dataset.learnTab,true);
  });
  const selector='.kind-badge,.badge.protocol,.chat-protocol';
  function decorate(root) {
    if(!(root instanceof Element))return;
    const nodes=[...(root.matches(selector)?[root]:[]),...all(selector,root)];
    for(const node of nodes){const key=node.textContent.trim().toLowerCase();if(!['a2a','mcp','x402','any'].includes(key))continue;const label={a2a:'A2A',mcp:'MCP',x402:'x402',any:'Any'}[key];if(node.textContent!==label)node.textContent=label;if(node.dataset.protocol!==key)node.dataset.protocol=key;}
  }
  // Reconstruct official contact links after edge HTML processing. No injected
  // email-decoding script or broader script policy is needed.
  function contacts(root) {
    if(!(root instanceof Element))return;
    const links=[...(root.matches('[data-service-mailbox]')?[root]:[]),...all('[data-service-mailbox]',root)];
    for(const link of links){const box=link.dataset.serviceMailbox;if(!['contact','privacy','security','support'].includes(box))continue;const address=box+'@'+'agentconcierge.biz';if(link.getAttribute('href')!=='mailto:'+address)link.href='mailto:'+address;if(link.textContent!==address)link.textContent=address;}
  }
  contacts(document.body);
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)contacts(node);}).observe(document.body,{childList:true,subtree:true});
  decorate(document.body);
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)decorate(node);}).observe(document.body,{childList:true,subtree:true});
})();

/* Approved menu layouts use the existing request, evidence and consent handlers. */
'use strict';
(() => {
  const q = (selector, root=document) => root.querySelector(selector);
  const all = (selector, root=document) => [...root.querySelectorAll(selector)];
  function element(tag, className, value) {
    const node=document.createElement(tag);
    if(className)node.className=className;
    if(value!==undefined)node.textContent=value;
    return node;
  }
  function segmented(select, label, labels={}) {
    if(!select)return;
    const group=element('div','pearl-protocol-segmented');
    group.setAttribute('role','group');group.setAttribute('aria-label',label);
    const sync=()=>all('button',group).forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.value===select.value)));
    for(const option of select.options){
      const button=element('button','',labels[option.value]||option.textContent);
      button.type='button';button.dataset.value=option.value;
      button.addEventListener('click',()=>{select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));sync();});
      group.append(button);
    }
    select.classList.add('pearl-native-select');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
    select.after(group);select.addEventListener('change',sync);select.form?.addEventListener('reset',()=>queueMicrotask(sync));sync();
  }
  segmented(q('#chatProtocol'),'Recommendation protocol',{auto:'Auto · A2A → MCP',any:'A2A + MCP',a2a:'A2A',mcp:'MCP',x402:'x402'});
  segmented(q('#regKind'),'Agent protocol',{a2a:'A2A',mcp:'MCP',x402:'x402'});

  function selectedExample(){
    const select=q('#tbAgentSelect');if(!select)return;
    const example=tbLiveExamples.find(item=>String(item.resource_id||item.presetId)===String(select.value));
    q('#pearlTestExampleName').textContent=example?.title||select.selectedOptions[0]?.textContent||'Choose an agent';
    q('#pearlTestExampleDescription').textContent=example?.desc||'Review the selected agent and its request before running.';
    all('.pearl-example-choice').forEach(button=>{const active=button.dataset.recipe===example?.id;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
  }
  const oldAgentChange=onTestbenchAgentChange;
  onTestbenchAgentChange=async function(...args){
    const section=q('#secTest'),state=q('#pearlTestConnectionState');
    const tools=q('#tbToolSelect');if(tools)tools.disabled=true;
    if(section)section.dataset.selectionBusy='true';
    if(state){state.hidden=false;state.textContent='Loading selected agent…';}
    const pending=oldAgentChange(...args),version=tbSelectionVersion;
    try{return await pending;}
    finally{if(version===tbSelectionVersion){
      if(section)section.dataset.selectionBusy='false';
      if(tools)tools.disabled=!tbSelectedAgent||tbSelectedAgent.kind!=='mcp';
      if(state){const demo=Boolean(tbSelectedAgent?.simulated||Number(q('#tbAgentSelect')?.value)<0);state.hidden=Boolean(tbSelectedAgent)&&!demo;state.textContent=demo?'Format demo · no provider will be contacted.':tbSelectedAgent?'':'Connection could not be loaded. Open Choose another agent and try again.';}
      selectedExample();
    }}
  };
  const oldRecipe=loadTestbenchRecipe;
  loadTestbenchRecipe=async function(...args){const value=await oldRecipe(...args);selectedExample();return value;};
  q('#tbAgentSelect')?.addEventListener('change',selectedExample);
  const oldRecipeRender=renderTestbenchRecipes;
  renderTestbenchRecipes=function(...args){const value=oldRecipeRender(...args);queueMicrotask(selectedExample);return value;};
  selectedExample();

  const oldExplore=renderExplore;
  function preview(item){
    const panel=q('#pearlAgentPreview');if(!panel||!item)return;
    const protocol=String(item.kind||'').toLowerCase(),badge=element('span','badge',protocol==='x402'?'x402':protocol.toUpperCase());
    if(['a2a','mcp','x402'].includes(protocol))badge.dataset.protocol=protocol;
    const name=element('h3','',item.name||'Agent'),description=element('p','',item.description||'Review this agent’s public connection details.');
    const checks=element('section','pearl-preview-section');checks.append(element('h4','','Recorded checks'));
    const report=Boolean(item.report_count>0||item.has_report||item.test_report||item.test_reports?.length);
    checks.append(element('p','',report?'A recorded report is available. Inspect its actual output and sources before relying on it.':'No published report is recorded for this listing.'));
    const details=element('section','pearl-preview-section');details.append(element('h4','','Connection details'));
    const fields=element('dl','');for(const [label,value]of [['Protocol',protocol==='x402'?'x402':protocol.toUpperCase()],['Category',item.category||'Not specified'],['Quality grade',item.eval_grade||'Unrated']])fields.append(element('dt','',label),element('dd','',value));details.append(fields);
    const button=element('button','btn primary block','Inspect connection →');button.type='button';button.addEventListener('click',()=>openAgent(item.id));
    panel.replaceChildren(badge,name,description,checks,details,button,element('p','caption','Recorded observations describe past checks. Availability can change.'));
  }
  renderExplore=function(...args){
    oldExplore(...args);
    for(const card of all('#xResults .acard')){
      const badge=q('.kind-badge',card),name=q('.t',card);
      if(name&&badge){const header=element('div','pearl-result-heading');name.before(header);header.append(name,badge);}
      const action=q('.pearl-result-actions',card);
      if(action){const label=q('span',action);if(label)label.textContent='View details →';}
      card.addEventListener('click',()=>preview(EXPLORE_AGENT_MAP.get(card.dataset.id)));
    }
    preview(args[0]?.[0]);
  };
  if(EXPLORE_AGENT_MAP.size){
    for(const card of all('#xResults .acard')){
      const badge=q('.kind-badge',card),name=q('.t',card);
      if(name&&badge){const header=element('div','pearl-result-heading');name.before(header);header.append(name,badge);}
    }
  }

  function workflowDetails(){
    const template=frontTemplatesCache.find(item=>String(item.id)===String(frontActiveTemplateId));
    const description=q('#pearlWorkflowDescription');if(description)description.textContent=template?.description||'Review the selected connection and its inputs.';
    const inputs=q('#pearlWorkflowInputSteps'),details=q('#pearlWorkflowRunDetails');
    if(!inputs||!details)return;inputs.replaceChildren();details.replaceChildren();
    const publishedNodes=Array.isArray(template?.nodes)&&template.nodes.length?template.nodes:[];
    inputs.setAttribute('aria-busy',String(!publishedNodes.length&&frontTemplatesLoading));
    if(!publishedNodes.length){
      const message=frontTemplatesLoadFailed?'Workflow details could not be loaded. Try again.':frontTemplatesLoading?'Loading workflow steps…':'Choose a published workflow to review its steps.';
      const state=element('p','caption pearl-workflow-loading',message);state.setAttribute('role','status');inputs.append(state);
      if(frontTemplatesLoadFailed){const retry=element('button','btn small','Retry workflows');retry.type='button';retry.addEventListener('click',()=>loadFrontTemplates());inputs.append(retry);}
    }
    inputs.style.setProperty('--ux-steps',String(Math.max(1,publishedNodes.length)));
    for(const [index,node]of publishedNodes.entries()){
      const item=element('article','pearl-workflow-step');
      if(node.type==='trigger')item.classList.add('ux-node-trigger');
      const number=element('span','pearl-step-number',String(index+1).padStart(2,'0'));
      const text=element('div','');text.append(element('h4','',node.name||'Workflow step'));
      const protocol=String(node.kind||node.type||'').toLowerCase();
      const label=element('span','badge',protocol==='x402'?'x402':protocol.toUpperCase());
      if(['a2a','mcp','x402'].includes(protocol))label.dataset.protocol=protocol;
      text.append(label);
      const edit=element('button','link-button','Review input →');edit.type='button';
      edit.addEventListener('click',()=>{
        const content=q('#pearlWorkflowInputContent'),dialog=q('#pearlWorkflowInputDialog');
        if(!content||!dialog)return;content.replaceChildren(element('h3','',node.name||'Workflow step'));
        const fields=element('dl','pearl-chat-evidence');
        fields.append(element('dt','','Protocol'),element('dd','',protocol==='x402'?'x402':protocol.toUpperCase()));
        const data=node.data||{};
        if(data.action)fields.append(element('dt','','Action'),element('dd','',String(data.action)));
        content.append(fields);
        const input=data.args??data.arguments??data.input??data.payload??data.message;
        if(input!==undefined)content.append(element('pre','pearl-published-input',typeof input==='string'?input:JSON.stringify(input,null,2)));
        else content.append(element('p','',protocol==='trigger'?'This step starts the published workflow.':'Input is supplied by the preceding step or the published template.'));
        dialog.showModal();
      });
      const pearl=element('button','ux-workflow-pearl');pearl.type='button';pearl.setAttribute('aria-label','Review '+(node.name||'workflow step')+' input');
      if(node.type==='trigger')pearl.append(element('span','ux-trigger-mark','Start'));
      else{const image=element('img','');image.src='/new/en/assets/pearl.webp';image.alt='';image.width=86;image.height=86;pearl.append(image);}
      pearl.addEventListener('click',()=>edit.click());
      text.append(edit);item.append(number,pearl,text);inputs.append(item);
      const row=element('li',''),body=element('div','');body.append(element('h4','',node.name||'Workflow step'),element('p','',protocol==='trigger'?'Starts this workflow.':'Review the request and connection before running.'));row.append(body);details.append(row);
    }
  }
  const oldName=updateFrontActiveName;
  updateFrontActiveName=function(...args){const value=oldName(...args);workflowDetails();return value;};
  const oldNodes=renderFrontNodes;
  renderFrontNodes=function(...args){const value=oldNodes(...args);workflowDetails();return value;};
  const oldWorkflowResult=showFrontRunOutputModal;
  showFrontRunOutputModal=function(result){
    oldWorkflowResult(result);
    const target=q('#pearlWorkflowResult');if(!target)return;
    q('#pearlWorkflowResultState').textContent='Last run: '+String(result.status||'completed');
    const source=q('#frontWfRunModalBody');target.replaceChildren(...[...source.childNodes].map(node=>node.cloneNode(true)));
  };
  workflowDetails();
  q('#pearlCloseWorkflowInput')?.addEventListener('click',()=>q('#pearlWorkflowInputDialog').close());

  function chatDetails(data){
    const item=data?.data?.recommendations?.[0],target=q('#pearlChatSelectedAgent');if(!item||!target)return;
    const name=element('h4','pearl-chat-agent-name',chatLabel(item.name,'Recommended agent'));
    const protocol=String(item.kind||'').toLowerCase(),badge=element('span','badge',chatLabel(item.kind,'Agent'));
    if(['a2a','mcp','x402'].includes(protocol))badge.dataset.protocol=protocol;
    const description=element('p','','Selected for your task. Review its recorded evidence and connection details.');
    const evidence=element('dl','pearl-chat-evidence');
    const report=item.test_report;
    for(const [label,value]of [['Quality grade',item.grade||'Unrated'],['Recorded report',report?'Recorded '+chatTimestamp(report.created_at):'No published report'],['Recent activity',chatTimestamp(item.active_checked_at)]]){
      evidence.append(element('dt','',label),element('dd','',chatLabel(value,'Not recorded')));
    }
    const button=element('button','btn primary block','Calling details →');button.type='button';button.addEventListener('click',()=>openChatAgent(item));
    target.replaceChildren(name,badge,description,evidence,button);
  }
  const oldBubble=appendChatBubble;
  appendChatBubble=function(role,content,data,...rest){const value=oldBubble(role,content,data,...rest);if(role!=='user')chatDetails(data);return value;};
  const authority=q('#pearlRegAuthority'),submit=q('#regSubmitBtn');
  if(authority&&submit){const original=submit.onclick;submit.onclick=async function(event){
    if(!authority.checked){showModalAlert({type:'warning',title:'Authorization required',message:'Confirm that you are authorized to submit this public endpoint.',onClose:()=>authority.focus()});return;}
    return original.call(this,event);
  };}
})();

/* Task-focused layouts preserve the operating request and authorization paths. */
'use strict';
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const all=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const node=(tag,cls,value)=>{const el=document.createElement(tag);el.className=cls;if(value!==undefined)el.textContent=value;return el;};
  const category=value=>[...(q('#xCategory')?.options||[])].find(option=>option.value===value)?.textContent
    || DEFAULT_CATEGORIES[value] || String(value||'General').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
  let view='cards';
  try{if(sessionStorage.getItem('pearl:explore-layout')==='list')view='list';}catch{}
  function setView(next){
    view=next==='list'?'list':'cards';q('#xResults').dataset.layout=view;
    all('[data-ux-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.uxView===view)));
    try{sessionStorage.setItem('pearl:explore-layout',view);}catch{}
  }
  all('[data-ux-view]').forEach(button=>button.addEventListener('click',()=>setView(button.dataset.uxView)));
  setView(view);
  function compactResults(){
    for(const card of all('#xResults .acard:not(.skeleton-card)')){
      const item=EXPLORE_AGENT_MAP.get(card.dataset.id);if(!item)continue;
      const header=q('.pearl-result-heading',card);if(!header)continue;
      const oldTop=card.firstElementChild;
      if(oldTop!==header&&!oldTop.classList.contains('ux-agent-category'))oldTop.remove();
      if(!q('.ux-agent-category',card))header.before(node('span','ux-agent-category',category(item.category)));
      const facts=q('.m',card);if(facts){
        const items=[];
        if(item.catalog_status==='historical')items.push(['Historical entry · unavailable','ux-unavailable']);
        if(item.eval_grade)items.push(['Grade '+String(item.eval_grade),'']);
        if(item.report_count>0||item.has_report||item.test_report||item.test_reports?.length)items.push(['Recorded report','chip-report']);
        if(item.catalog_status!=='historical'&&item.connection_readiness?.verified_callable===true)items.push(['Execution checked','ux-checked']);
        // Whether a listing can be used right away decides the choice, so access and price always show.
        if(item.auth_required===0&&item.kind!=='x402')items.push(['No account required','']);
        if(item.kind==='x402'&&item.price_usdc)items.push([usd(item.price_usdc)+' per call','']);
        if(item.cap_tool_count)items.push([String(item.cap_tool_count)+' tools','']);
        facts.replaceChildren(...items.map(([label,cls])=>node('span','chip '+cls,label)));
      }
    }
    setView(view);
  }
  const originalExplore=renderExplore;
  renderExplore=function(...args){const value=originalExplore(...args);compactResults();return value;};
  compactResults();
  // Phones: category, evidence filters and common tasks fold behind one button so results start on the first screen.
  (()=>{
    const box=q('#secExplore .pearl-filter-bottom');if(!box)return;
    const phone=matchMedia('(max-width:700px)');
    const category=q('#xCategory')?.closest('.field'),search=q('#xGo');
    box.id=box.id||'uxFilterOptions';
    const toggle=node('button','btn sm ux-filter-toggle');toggle.type='button';
    toggle.setAttribute('aria-controls',box.id);toggle.setAttribute('aria-expanded','false');
    const apply=()=>{
      if(category&&search){if(phone.matches&&category.parentNode!==box)box.prepend(category);else if(!phone.matches&&category.parentNode===box)search.before(category);}
      const on=['xVerified','xNoAuth','xHasReport'].filter(id=>q('#'+id)?.checked).length+(phone.matches&&q('#xCategory')?.value?1:0);
      const open=!phone.matches||toggle.getAttribute('aria-expanded')==='true';
      box.style.display=open?'':'none';toggle.hidden=!phone.matches;
      toggle.textContent=(open?'Hide':'Show')+' filters and common tasks'+(on?' ('+on+' on)':'');
    };
    toggle.addEventListener('click',()=>{toggle.setAttribute('aria-expanded',String(toggle.getAttribute('aria-expanded')!=='true'));apply();});
    box.before(toggle);box.addEventListener('change',apply);phone.addEventListener('change',apply);apply();
  })();
  q('#uxClearSearch')?.addEventListener('click',()=>{
    q('#xQ').value='';q('#xKind').value='';q('#xCategory').value='';
    for(const id of ['xVerified','xNoAuth','xHasReport'])q('#'+id).checked=false;
    all('.pearl-search-panel [data-kind]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.kind==='')));
    updateActiveExploreChip('');loadExplore(true,false,true);
  });
  function activeLayout(){document.body.dataset.uxPanel=currentTab;}
  const originalSwitch=switchTab;
  switchTab=function(...args){const value=originalSwitch(...args);activeLayout();return value;};
  activeLayout();

  function testResult(open,scroll=false){
    const panel=q('#uxTestResultPanel'),body=q('#uxTestResultBody'),button=q('#uxToggleTestResult');
    if(!panel||!body)return;
    panel.dataset.expanded=String(open);body.hidden=!open;
    button.setAttribute('aria-expanded',String(open));button.textContent=open?'Hide result':'Show result';
    if(open&&scroll)panel.scrollIntoView({block:'start',behavior:'auto'});
  }
  q('#uxToggleTestResult')?.addEventListener('click',()=>testResult(q('#uxTestResultBody').hidden));
  const originalTest=executeCurrentTestbench;
  executeCurrentTestbench=async function(...args){
    if(tbRunInFlight)return;
    if(q('#tbArgsEditor').value!==renderedArgs)requestFields();
    if(!q('#tbCustomToolInput').value.trim())for(const input of all('#uxRequestFields input,#uxRequestFields select,#uxRequestFields textarea')){if(!input.checkValidity()){input.reportValidity();input.focus();return;}}
    if(tbSelectedAgent?.kind!=='x402'){try{JSON.parse(q('#tbArgsEditor').value||'{}');}catch{return originalTest(...args);}}
    testResult(true,true);q('#uxTestResultHint').textContent='Checking the selected request…';
    try{return await originalTest(...args);}
    finally{q('#uxTestResultHint').textContent=tbLastResult?'Latest test · '+q('#tbKpiStatus').textContent:'No completed test. Review the request and connection before trying again.';}
  };
  const originalTestResult=renderTestbenchResult;
  renderTestbenchResult=function(...args){const value=originalTestResult(...args);testResult(true);q('#uxTestResultHint').textContent='Latest test · '+q('#tbKpiStatus').textContent;return value;};

  let renderedArgs='';
  function requestFields(){
    const host=q('#uxRequestFields'),studio=q('#tbArgsStudio');if(!host)return;
    host.replaceChildren();studio.classList.toggle('hidden',tbSelectedAgent?.kind!=='mcp');
    if(tbSelectedAgent?.kind!=='mcp')return;
    let args;try{args=JSON.parse(q('#tbArgsEditor').value||'{}');}catch{q('#uxRawArgs').open=true;return;}
    renderedArgs=q('#tbArgsEditor').value;
    if(!args||typeof args!=='object'||Array.isArray(args)){q('#uxRawArgs').open=true;return;}
    const tool=tbSelectedAgent.tools?.find(t=>t.name===q('#tbToolSelect').value);
    const schema=tool?.inputSchema||{properties:tool?.params||{},required:tool?.required||[]},properties=schema.properties||{};
    host.append(node('h3','','Request input'),node('p','caption','Sample values are filled in. Review or change them before running this request.'));
    const names=[...new Set([...Object.keys(args),...Object.keys(properties),...(schema.required||[])])];
    if(!names.length)host.append(node('p','caption','This tool has no required input.'));
    for(const key of names){
      const spec=properties[key]||{},value=args[key],field=node('div','field');
      const id='uxArg-'+names.indexOf(key),label=node('label','',spec.title||key.replace(/_/g,' ').replace(/^./,c=>c.toUpperCase()));label.htmlFor=id;
      let input;
      if(Array.isArray(spec.enum)){input=node('select','select');const empty=node('option','','Choose a value');empty.value='';input.append(empty);for(const choice of spec.enum){const option=node('option','',String(choice));option.value=String(choice);input.append(option);}input.value=String(value??'');}
      else if(typeof value==='object'&&value!==null){input=node('textarea','input');input.value=JSON.stringify(value,null,2);input.rows=3;}
      else{input=node('input','input');input.type=spec.type==='boolean'||typeof value==='boolean'?'checkbox':spec.type==='integer'||spec.type==='number'||typeof value==='number'?'number':'text';if(input.type==='checkbox')input.checked=Boolean(value);else input.value=String(value??'');if(input.type==='number')input.step=spec.type==='integer'?'1':'any';}
      input.id=id;input.dataset.argKey=key;input.required=input.type!=='checkbox'&&(schema.required||[]).includes(key);input.classList.add('fs-mask');input.setAttribute('data-clarity-mask','true');
      if(typeof spec.minimum==='number')input.min=String(spec.minimum);if(typeof spec.maximum==='number')input.max=String(spec.maximum);
      input.addEventListener('input',()=>{
        let current;try{current=JSON.parse(q('#tbArgsEditor').value||'{}');}catch{return;}
        if(!current||typeof current!=='object'||Array.isArray(current))return;
        let next=input.type==='checkbox'?input.checked:input.type==='number'?(input.value===''?undefined:Number(input.value)):input.value;
        if(Array.isArray(spec.enum))next=spec.enum.find(choice=>String(choice)===input.value);
        if(typeof value==='object'&&value!==null){try{next=JSON.parse(input.value);input.setCustomValidity('');}catch{input.setCustomValidity('Enter a valid JSON value.');return;}}
        if(next===undefined)delete current[key];else Object.defineProperty(current,key,{value:next,writable:true,enumerable:true,configurable:true});
        q('#tbArgsEditor').value=JSON.stringify(current,null,2);validateTestbenchJson();
      });
      field.append(label,input);if(spec.description)field.append(node('p','caption',spec.description));host.append(field);
    }
  }
  for(const [name,read,write]of [
    ['tool',()=>onTestbenchToolChange,value=>onTestbenchToolChange=value],
    ['arguments',()=>applyDefaultArgsForTool,value=>applyDefaultArgsForTool=value],
    ['agent',()=>applySelectedTestbenchAgent,value=>applySelectedTestbenchAgent=value]
  ]){const original=read();write(function(...args){const value=original(...args);if(name==='agent'){const agent=args[0];q('#uxSelectedConnection').textContent=agent?'Selected agent: '+String(agent.name||'Agent')+' · '+(agent.kind==='x402'?'x402':String(agent.kind||'').toUpperCase()):'';if(agent?.kind==='a2a'){q('#tbArgsEditor').value='{}';validateTestbenchJson();}}requestFields();return value;});}
  const originalRecipe=loadTestbenchRecipe;
  loadTestbenchRecipe=function(id,callback){return originalRecipe(id,()=>{requestFields();if(callback)callback();});};
  q('#tbArgsEditor')?.addEventListener('change',requestFields);
  resetTestbenchParams=function(){
    if(tbRunInFlight)return;
    const example=tbLiveExamples.find(item=>String(item.resource_id)===String(tbSelectedAgent?.id));
    if(example)loadTestbenchRecipe(example.id);
    else if(tbSelectedAgent?.kind==='mcp')onTestbenchToolChange(q('#tbToolSelect').value);
    else if(tbSelectedAgent?.kind==='a2a')q('#tbA2aMessage').value=tbSelectedAgent.sample_args?.message||'Summarize recent technology research with source links.';
    q('#tbTimeoutSelect').value='8.0';requestFields();
  };
  q('#tbResetBtn').setAttribute('aria-label','Reset input for the selected agent');
  requestFields();

  let agentSearchTimer,agentSearchRevision=0,agentSearchController=null;
  function agentOptions(){
    const select=q('#tbAgentSelect'),current=String(tbSelectedAgent?.id??select.value),query=q('#tbAgentSearch').value.trim().toLowerCase();
    const matches=item=>(tbCurrentKind==='all'||item.kind===tbCurrentKind)&&(!query||(item.name+' '+(item.description||'')).toLowerCase().includes(query));
    const groups=[['Live examples',tbLiveExamples.filter(x=>x.available).map(x=>({id:x.resource_id,name:x.title,description:x.desc,kind:x.protocol}))],['Registered agents',tbAgentsCache],['Format demos — no provider calls',tbPresetsCache]];
    select.replaceChildren();let count=0;const seen=new Set();
    for(const [title,items]of groups){const group=node('optgroup','');group.label=title;for(const item of items.filter(matches)){if(seen.has(String(item.id)))continue;seen.add(String(item.id));const option=node('option','',item.name+' ['+String(item.kind||'').toUpperCase()+']');option.value=String(item.id);group.append(option);count++;}if(group.children.length)select.append(group);}
    if(seen.has(current))select.value=current;else{const option=node('option','','Choose a matching agent');option.value='';option.disabled=true;option.selected=true;select.prepend(option);}
    q('#uxAgentSearchStatus').textContent=count+' matching choices. Select one to replace the current request. Format demos do not contact a provider.';
  }
  filterTestbenchKind=function(kind,button){tbCurrentKind=kind;all('#secTest .quick-chips .chip-btn').forEach(b=>b.classList.toggle('active',b.dataset.kind===kind));filterTestbenchAgentList();};
  filterTestbenchAgentList=function(){
    const revision=++agentSearchRevision;clearTimeout(agentSearchTimer);agentSearchController?.abort();agentOptions();
    q('#uxAgentSearchStatus').textContent='Searching registered agents… Your current request is kept.';
    agentSearchTimer=setTimeout(async()=>{const controller=new AbortController();agentSearchController=controller;try{const params=new URLSearchParams({q:q('#tbAgentSearch').value.trim(),limit:'45'});if(tbCurrentKind!=='all')params.set('kind',tbCurrentKind);const result=await api('/api/explore?'+params,{background:true,timeoutMs:30000,retries:0,signal:controller.signal});if(revision!==agentSearchRevision)return;tbAgentsCache=result.items||[];agentOptions();}catch{if(revision===agentSearchRevision)q('#uxAgentSearchStatus').textContent='Catalog search is unavailable. Your current request is kept. Try again.';}finally{if(agentSearchController===controller)agentSearchController=null;}},300);
  };

  const originalWorkflowName=updateFrontActiveName;
  q('#btnFrontResetCanvas').textContent='Use default workflow';
  function workflowState(){
    q('#secWorkflows')?.classList.toggle('ux-workflow-selected',Boolean(frontActiveTemplateId));
  }
  updateFrontActiveName=function(...args){const value=originalWorkflowName(...args);workflowState();return value;};
  workflowState();
  const originalInspector=openFrontNodeInspector;
  openFrontNodeInspector=function(...args){
    const value=originalInspector(...args),inspector=q('#frontWfInspector');
    if(frontCanvasGraph.nodes.some(item=>item.id===args[0])){
      const canvas=q('#frontWfCanvasContainer');canvas.scrollLeft=0;canvas.scrollTop=0;
      inspector.classList.add('open');inspector.setAttribute('aria-hidden','false');
    }
    return value;
  };
  const originalCloseInspector=closeFrontInspector;
  closeFrontInspector=function(...args){const value=originalCloseInspector(...args);q('#frontWfInspector').classList.remove('open');q('#frontWfInspector').setAttribute('aria-hidden','true');return value;};
  const originalSelectNode=selectFrontNode;
  selectFrontNode=function(id,event){const value=originalSelectNode(id,event);if(event?.type==='click')openFrontNodeInspector(id);return value;};
  closeFrontInspector();
  const originalTemplateRender=renderFrontTemplates;
  const templatePage={index:0,key:'',total:0,rendered:false};
  const templatePageSize=matchMedia('(max-width:700px)').matches?4:8;
  window.selectFrontTemplatePage=function(templates){
    if(typeof window.filterWorkflowLibraryTemplates==='function')templates=window.filterWorkflowLibraryTemplates(templates);
    const key=JSON.stringify([frontActiveTmplCategory,q('#frontTmplSearchInput')?.value||'',templates.map(t=>t.id)]);
    if(key!==templatePage.key){templatePage.index=0;templatePage.key=key;}
    templatePage.total=templates.length;templatePage.rendered=true;
    templatePage.index=Math.max(0,Math.min(templatePage.index,Math.ceil(templates.length/templatePageSize)-1));
    return templates.slice(templatePage.index*templatePageSize,(templatePage.index+1)*templatePageSize);
  };
  window.goToFrontTemplatePage=function(page){
    if(!Number.isInteger(page)||page<1||page>Math.max(1,Math.ceil(templatePage.total/templatePageSize)))return;
    templatePage.index=page-1;renderFrontTemplates();
    q('#uxTemplatePager-top .ux-template-page-status')?.focus({preventScroll:true});
  };
  function templatePagination(){
    const grid=q('#frontTemplatesGrid');if(!grid)return;
    for(const where of ['top','bottom']){
      let pager=q('#uxTemplatePager-'+where);
      if(!pager){
        pager=node('nav','ux-template-pagination');pager.id='uxTemplatePager-'+where;pager.setAttribute('aria-label','Template pages, '+where);
        const status=node('p','ux-template-page-status');status.setAttribute('role','status');status.tabIndex=-1;
        const actions=node('div','ux-template-page-actions');
        for(const [label,delta]of [['Previous',-1],['Next',1]]){
          const button=node('button','btn sm',label);button.type='button';button.dataset.direction=String(delta);
          button.addEventListener('click',()=>{
            templatePage.index+=delta;renderFrontTemplates();
            q('#uxTemplatePager-top .ux-template-page-status')?.focus({preventScroll:true});
            q('#uxTemplatePager-top')?.scrollIntoView({block:'start',behavior:'auto'});
          });actions.append(button);
        }
        pager.append(status,actions);if(where==='top')grid.before(pager);else grid.after(pager);
      }
      pager.hidden=!templatePage.rendered||!templatePage.total;
      if(pager.hidden)continue;
      const start=templatePage.index*templatePageSize,end=Math.min(start+templatePageSize,templatePage.total),pages=Math.ceil(templatePage.total/templatePageSize);
      q('.ux-template-page-status',pager).textContent='Showing '+(start+1)+'–'+end+' of '+templatePage.total+' templates · Page '+(templatePage.index+1)+' of '+pages;
      q('[data-direction="-1"]',pager).disabled=templatePage.index===0;
      q('[data-direction="1"]',pager).disabled=templatePage.index>=pages-1;
      pager.dataset.page=String(templatePage.index+1);pager.dataset.total=String(templatePage.total);
    }
  }
  function renderTemplateCategories(){
    const panel=q('#frontTmplCategoryFilters');if(!panel)return;
    const names={all:'All Categories',travel_maps_weather:'Travel & Weather',dev_tools:'Developer Tools',
      data_utility:'Data & Utility',finance_crypto:'Finance & DeFi',automation:'Automation',
      sports_health:'Sports & Health',business_productivity:'Productivity',docs_knowledge:'Docs & Knowledge'};
    if(!q('[data-category="docs_knowledge"]',panel)){
      const button=node('button','btn sm tmpl-cat-btn');button.type='button';button.dataset.category='docs_knowledge';
      button.addEventListener('click',()=>selectFrontTmplCategory('docs_knowledge'));panel.append(button);
    }
    for(const button of all('.tmpl-cat-btn',panel)){
      const category=button.dataset.category;
      const count=frontTemplatesCache.filter(t=>category==='all'||t.category===category).length;
      button.textContent=(names[category]||category.replaceAll('_',' '))+' ('+count+')';
      button.setAttribute('aria-pressed',String(frontActiveTmplCategory===category));
      button.classList.toggle('primary',frontActiveTmplCategory===category);
    }
  }
  renderFrontTemplates=function(...args){
    renderTemplateCategories();
    templatePage.rendered=false;
    const value=originalTemplateRender(...args);
    for(const card of all('#frontTemplatesGrid .template-card')){
      const use=q('button[data-ac-click="64099165e4f4"]',card),id=use?.dataset.id;
      const template=frontTemplatesCache.find(t=>String(t.id)===id);if(!template)continue;
      const title=q(':scope > div:first-child > div:first-child .chip',card);
      if(title)title.textContent=String(template.category||'Workflow').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
      const preview=q(':scope > div:first-child > div:last-child',card);
      if(preview&&Array.isArray(template.steps)){
        const steps=node('ol','ux-hub-steps');
        for(const step of template.steps){const row=node('li','');row.append(node('span','ux-mini-pearl'),node('span','',step.name||'Workflow step'));steps.append(row);}
        preview.replaceChildren(steps);
      }
      if(use&&q('span',use))q('span',use).textContent='Use workflow';
    }
    templatePagination();
    return value;
  };
  const originalWorkflowView=switchFrontWfSubView;
  switchFrontWfSubView=function(view){const value=originalWorkflowView(view);q('#pearlWorkflowTemplates').hidden=view!=='canvas';return value;};
  q('.ux-canvas-editor')?.addEventListener('toggle',event=>{if(event.currentTarget.open)renderFrontCanvas();});
  q('#uxFullRunDetails')?.addEventListener('click',()=>q('#frontWfRunModal').showModal());
  let receivedWorkflowResult=false,lastTemplate=frontActiveTemplateId;
  const originalTemplate=loadFrontTemplateToCanvas;
  loadFrontTemplateToCanvas=function(...args){
    const fromHub=!q('#frontWfTemplatesView')?.classList.contains('hidden');
    const value=originalTemplate(...args);
    if(String(lastTemplate)!==String(frontActiveTemplateId)){
      q('#pearlWorkflowResultState').textContent='No run yet';
      q('#pearlWorkflowResult').replaceChildren(node('p','','Run this workflow to see its actual result here.'));
      q('#uxFullRunDetails').hidden=true;lastTemplate=frontActiveTemplateId;
    }
    const heading=q('#frontWfActiveName');
    if(currentTab==='workflows'&&fromHub&&heading){requestAnimationFrame(()=>heading.scrollIntoView({block:'start',behavior:'auto'}));}
    return value;
  };
  const originalWorkflowOutput=showFrontRunOutputModal;
  showFrontRunOutputModal=function(...args){
    const value=originalWorkflowOutput(...args);receivedWorkflowResult=true;
    q('#uxFullRunDetails').hidden=false;q('#uxWorkflowResultPanel').dataset.expanded='true';return value;
  };
  const originalRun=runFrontCanvasWorkflow;
  runFrontCanvasWorkflow=async function(...args){
    if(frontWorkflowRunning)return;
    receivedWorkflowResult=false;q('#pearlWorkflowResultState').textContent='Starting run…';
    q('#pearlWorkflowResult').replaceChildren(node('p','','Checking the selected published connection. Your result will appear here.'));
    q('#uxFullRunDetails').hidden=true;q('#uxWorkflowResultPanel').dataset.expanded='true';
    q('#uxWorkflowResultPanel').scrollIntoView({block:'start',behavior:'auto'});
    try{return await originalRun(...args);}
    finally{if(!receivedWorkflowResult){q('#pearlWorkflowResultState').textContent='Run not started';q('#pearlWorkflowResult').replaceChildren(node('p','','The run did not start. Review the connection status and try again.'));}}
  };

  all('[data-ux-task]').forEach(button=>button.addEventListener('click',()=>{q('#chatInput').value=button.dataset.uxTask;q('#chatInput').dispatchEvent(new Event('input',{bubbles:true}));sendChat(q('#chatInput').value);}));
  function sizeComposer(){const input=q('#chatInput');if(!input)return;const baseline=Math.max(64,parseFloat(getComputedStyle(input).minHeight)||0);input.style.height=baseline+'px';input.style.height=Math.min(150,Math.max(baseline,input.scrollHeight))+'px';}
  q('#chatInput')?.addEventListener('input',sizeComposer);
  const originalChat=sendChat;
  let requestNumber=0;
  const originalBubble=appendChatBubble;
  appendChatBubble=function(role,...args){
    const value=originalBubble(role,...args);if(role==='user')return value;
    const bubble=q('#chatMessages .chat-bubble.bot');if(!bubble||bubble.classList.contains('chat-welcome'))return value;
    // Number only actual results; guidance and no-match replies are not recommendations.
    const reply=args[1]?.data||{};
    if(!(Array.isArray(reply.recommendations)&&reply.recommendations.length)&&!(Array.isArray(reply.workflows)&&reply.workflows.length))return value;
    const scope={a2a:'A2A',mcp:'MCP',x402:'x402'}[String(reply.protocol||'').toLowerCase()]||'';
    for(const label of all('.ux-chat-request-label'))label.textContent='Recommendation '+label.dataset.number+(label.dataset.scope?' · '+label.dataset.scope:'');
    const label=node('p','ux-chat-request-label','Recommendation '+(++requestNumber)+(scope?' · '+scope:'')+' · Latest');
    label.dataset.number=String(requestNumber);label.dataset.scope=scope;bubble.prepend(label);
    bubble.classList.add('ux-chat-latest');for(const old of all('#chatMessages .ux-chat-latest'))if(old!==bubble)old.classList.remove('ux-chat-latest');
    return value;
  };
  sendChat=async function(message,label,requestData){
    if(q('#chatForm').dataset.busy==='true')return originalChat(message,label,requestData);
    const draft=String(message||'');
    const previous=q('#chatMessages .chat-bubble.bot');
    try{return await originalChat(message,label,requestData);}
    finally{
      if(/^(?:Unable to complete|The request could not be completed)/.test(q('#chatStatus')?.textContent||'')&&!q('#chatInput').value)q('#chatInput').value=draft;
      sizeComposer();
      const latest=q('#chatMessages .chat-bubble.bot');
      if(latest&&latest!==previous&&currentTab==='chat'){latest.tabIndex=-1;q('#chatMessages').scrollTop=0;}
    }
  };

  const inspect=q('#regInspectBtn'),inspectProxy=q('#uxInspectEndpoint');
  function inspectionState(){if(!inspect||!inspectProxy)return;inspectProxy.disabled=inspect.disabled;inspectProxy.setAttribute('aria-busy',String(inspect.disabled));inspectProxy.textContent=inspect.disabled?'Checking endpoint…':'Check and autofill';}
  inspectProxy?.addEventListener('click',()=>{if(inspect.disabled)return;q('#regAutoUrl').value=q('#regUrl').value;inspect.click();inspectionState();});
  if(inspect)new MutationObserver(inspectionState).observe(inspect,{attributes:true,attributeFilter:['disabled']});
  q('#regForm')?.addEventListener('submit',event=>{event.preventDefault();q('#regSubmitBtn').click();});

  for(const link of all('#secOverview a[href="#test"]')){
    const title=link.closest('.card')?.querySelector('h3')?.textContent||link.textContent;
    if(/news|documentation|research/i.test(title))link.addEventListener('click',async()=>{
      const word=/documentation/i.test(title)?'documentation':/research/i.test(title)?'research':'news';
      if(!tbLiveExamples.length){try{const data=await api('/api/test/presets',{background:true});tbLiveExamples=data.live_examples||[];renderTestbenchRecipes();populateTestbenchAgentSelect();}catch{return;}}
      const example=tbLiveExamples.find(x=>x.available&&x.title.toLowerCase().includes(word));if(example)loadTestbenchRecipe(example.id);
    });
  }

  const originalDrawer=renderDrawerAgent;
  renderDrawerAgent=function(agent,state){
    const drawer=q('#drawer'),scroll=drawer.scrollTop,value=originalDrawer(agent,state),content=q('#drawerContent');
    const heading=q('h3',content);heading.id='uxDrawerTitle';
    q('#drawerTestBtn span').textContent='Use in Test';
    const pre=q(':scope > pre',content),title=pre?.previousElementSibling;
    if(pre&&title){const details=node('details','ux-spec-details'),summary=node('summary','','Technical connection metadata');title.replaceWith(details);details.append(summary,pre);}
    const action=q('#drawerTestBtn')?.parentElement;action?.classList.add('ux-drawer-actions');
    drawer.scrollTop=scroll;return value;
  };
  const drawer=q('#drawer');drawer.setAttribute('role','dialog');drawer.setAttribute('aria-modal','true');drawer.setAttribute('aria-label','Agent connection and evidence');
  let drawerReturn=null;
  const originalChatAgent=openChatAgent;
  openChatAgent=function(...args){drawerReturn=document.activeElement;drawer.scrollTop=0;const value=originalChatAgent(...args);q('#closeDrawer').focus({preventScroll:true});return value;};
  const originalOpenAgent=openAgent;
  openAgent=function(...args){drawerReturn=document.activeElement;drawer.scrollTop=0;const value=originalOpenAgent(...args);q('#closeDrawer').focus({preventScroll:true});return value;};
  const originalClose=closeDrawer;
  closeDrawer=function(){originalClose();if(drawerReturn?.isConnected)drawerReturn.focus({preventScroll:true});};
  q('#closeDrawer').onclick=closeDrawer;q('#drawerBackdrop').onclick=closeDrawer;
  drawer.addEventListener('keydown',event=>{if(event.key!=='Tab')return;const controls=all('button:not(:disabled),a[href],input,select,textarea,[tabindex="0"]',drawer).filter(el=>el.getClientRects().length);const first=controls[0],last=controls.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}});
})();

/* Keep the requested task when the user explicitly reviews a recommended connection. */
(() => {
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  let reviewedResourceId=null;
  const applyConnection=applySelectedTestbenchAgent;
  applySelectedTestbenchAgent=function(agent,...args){const result=applyConnection(agent,...args);if(String(agent?.id)!==String(reviewedResourceId))document.querySelector('#chatTaskReview')?.remove();return result;};
  async function reviewTask(item,task,trigger){
    reviewedResourceId=item.id;
    trigger.disabled=true;trigger.setAttribute('aria-busy','true');
    try{
      if(typeof closeDrawer==='function')closeDrawer();
      switchTab('test');history.replaceState(null,'','#test?id='+encodeURIComponent(item.id));
      const select=document.querySelector('#tbAgentSelect');
      if(select&&![...select.options].some(o=>o.value===String(item.id)))select.append(new Option(item.name,String(item.id)));
      if(select)select.value=String(item.id);
      const agent=await onTestbenchAgentChange(item.id);if(!agent||currentTab!=='test'||String(tbSelectedAgent?.id)!==String(item.id))return;
      let copied=false;
      if(agent.kind==='a2a'){
        const message=document.querySelector('#tbA2aMessage');if(message){message.value=task;message.dispatchEvent(new Event('input',{bubbles:true}));copied=true;}
      }else if(agent.kind==='mcp'){
        const requested=item.tools_schema?.[0]?.name||item.tools?.[0],toolSelect=document.querySelector('#tbToolSelect');
        if(requested&&toolSelect&&[...toolSelect.options].some(o=>o.value===requested)){toolSelect.value=requested;toolSelect.dispatchEvent(new Event('change',{bubbles:true}));}
        const tool=(agent.tools||[]).find(t=>t.name===(toolSelect?.value||requested));
        const properties=tool?.inputSchema?.properties||tool?.params||{},fields=Object.keys(properties).filter(k=>['query','q','message','prompt','text','search','search_query','topic'].includes(k)&&properties[k].type==='string');
        const editor=document.querySelector('#tbArgsEditor');
        if(editor&&fields.length===1){try{const args=JSON.parse(editor.value||'{}');args[fields[0]]=task;editor.value=JSON.stringify(args,null,2);editor.dispatchEvent(new Event('change',{bubbles:true}));validateTestbenchJson();copied=true;}catch{}}
      }
      let panel=document.querySelector('#chatTaskReview');
      if(!panel){panel=node('section');panel.id='chatTaskReview';panel.className='card chat-task-review fs-mask';panel.setAttribute('data-clarity-mask','true');const anchor=document.querySelector('#secTest .ux-example-picker')||document.querySelector('#secTest .testbench-studio-grid');if(anchor)anchor.before(panel);else document.querySelector('#secTest').prepend(panel);}
      panel.replaceChildren(node('h3','Your task from Chat'),node('p',task),node('p',copied?'Your request is ready to review. Check the inputs and choose Run test when ready. Nothing has been sent to this agent.':'This tool needs specific inputs. Review them below; your original task is kept here. Nothing has been sent to this agent.'));
      panel.scrollIntoView({block:'start',behavior:'auto'});
    }finally{trigger.disabled=false;trigger.removeAttribute('aria-busy');}
  }
  const original=appendChatBubble;
  appendChatBubble=function(role,content,data,...rest){
    const result=original(role,content,data,...rest);if(role==='user')return result;
    const payload=data?.data||{},task=typeof payload.task==='string'?payload.task.trim():'';if(!task)return result;
    const bubble=document.querySelector('#chatMessages .chat-bubble.bot');if(!bubble)return result;
    const cards=[...bubble.querySelectorAll('.chat-recommendation')];
    (payload.recommendations||[]).slice(0,3).forEach((item,index)=>{
      const card=cards[index];if(!card||!Number.isInteger(item.id)||item.id<=0||!['a2a','mcp'].includes(item.kind)||card.querySelector('.chat-review-task'))return;
      const button=node('button','Review task in Test');button.type='button';button.className='btn sm primary chat-review-task';button.setAttribute('aria-label','Review option '+(index+1)+' in Test');button.addEventListener('click',()=>reviewTask(item,task,button).catch(()=>{const status=document.querySelector('#chatStatus');if(status)status.textContent='The connection could not be opened. Your request is kept in Chat.';}));card.append(button);
    });return result;
  };
})();

/* Native links and history share the operating page state and security gates. */
'use strict';
(() => {
  const q=selector=>document.querySelector(selector);
  const paths=Object.fromEntries([...document.querySelectorAll('#navTabs a[data-tab]')].map(link=>[link.dataset.tab,new URL(link.href).pathname]));
  paths.overview='/';
  const policies={terms:'tos',privacy:'privacy','privacy-choices':'ccpa',accessibility:'accessibility',disclosures:'ai',notifications:'cancellation',contact:'contact',cookies:'cookie-preferences'};
  let restoring=false;
  const modified=event=>event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey;
  function route(tab){
    const fragment=location.hash;
    return (paths[tab]||'/')+(fragment.startsWith('#'+tab+'?')?fragment:'#'+tab);
  }
  function focusHeading(tab){
    if(tab==='chat')return;
    const heading=q('[data-panel="'+tab+'"] h1')||q('[data-panel="'+tab+'"] h2');
    if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}
  }
  const previousSwitch=switchTab;
  switchTab=function(tab){
    const changed=currentTab!==tab,initial=initialRoutingComplete;
    q('#unknownRouteNotice')?.remove();
    if(restoring)initialRoutingComplete=false;
    for(const id of ['legalModal','cookiePrefsModal'])if(q('#'+id)?.open)q('#'+id).close();
    try{previousSwitch(tab);}finally{initialRoutingComplete=initial;}
    history.replaceState(null,'',route(currentTab));
    if(changed)focusHeading(currentTab);
  };
  const previousLegal=openLegalModal;
  openLegalModal=function(doc='tos'){
    const safe=VALID_LEGAL_DOCS.has(doc)?doc:'tos',modal=q('#legalModal');
    if(location.hash!=='#'+safe&&!restoring)history.pushState(null,'','/#'+safe);
    if(!modal.open||q('#legalModalTitle')?.textContent!==LEGAL_DOCS[safe]?.title)previousLegal(safe);
    modal.dataset.route=safe;
    history.replaceState(null,'','/#'+safe);
    document.title=(LEGAL_DOCS[safe]?.title||'Information')+' | Agent Concierge';
  };
  q('#legalModal')?.addEventListener('close',()=>{
    if(!LEGAL_ROUTES.includes(location.hash.slice(1))){history.replaceState(null,'',route(currentTab));updatePageMeta(currentTab);}
  });
  q('#cookiePrefsModal')?.addEventListener('close',()=>{
    if(location.hash==='#cookie-preferences')history.replaceState(null,'',route(currentTab));
  });
  const previousDoc=switchLegalDoc;
  switchLegalDoc=function(doc){previousDoc(doc);if(q('#legalModal')?.open)document.title=(LEGAL_DOCS[doc]?.title||'Information')+' | Agent Concierge';};
  function syncLocation(){
    const raw=location.hash.slice(1).split('?')[0];
    const hash=['ai-transparency','legal/ai'].includes(raw)?'ai':raw;
    restoring=true;
    try{
      if(LEGAL_ROUTES.includes(hash)){openLegalModal(hash);return;}
      if(hash==='cookie-preferences'){if(!q('#cookiePrefsModal')?.open)openCookiePrefsModal();return;}
      if(hash&&!TABS.includes(hash)) {
        if(raw.startsWith('stop-updates=')||document.getElementById(hash))return;
        let notice=q('#unknownRouteNotice');
        if(!notice){notice=document.createElement('section');notice.id='unknownRouteNotice';notice.className='card';
          const heading=document.createElement('h1');heading.textContent='This page could not be found.';
          const text=document.createElement('p');text.textContent='Use the navigation or explore the agent catalog to continue.';
          const link=document.createElement('a');link.href='/new/en/explore.html';link.className='btn';link.textContent='Explore agents';
          notice.append(heading,text,link);(q('main')||document.body).append(notice);}
        for(const panel of document.querySelectorAll('.tab-panel[data-panel]'))panel.classList.add('hidden');
        document.title='Page not found | Agent Concierge';notice.tabIndex=-1;notice.focus({preventScroll:true});
        return;
      }
      const tab=TABS.includes(hash)?hash:(Object.keys(paths).find(key=>paths[key]===location.pathname)||document.body.dataset.pearlEntry);
      if(tab){
        if(currentTab!==tab||q('#legalModal')?.open||q('#cookiePrefsModal')?.open)switchTab(tab);
        else history.replaceState(null,'',route(tab));
      }
    }finally{restoring=false;}
  }
  addEventListener('popstate',syncLocation);
  addEventListener('hashchange',syncLocation);
  for(const link of document.querySelectorAll('#navTabs a[data-tab]'))link.onclick=event=>{
    if(modified(event))return;
    event.preventDefault();switchTab(link.dataset.tab);
  };
  document.addEventListener('click',event=>{
    const link=event.target.closest('a[href]');if(!link)return;
    if(modified(event)){event.stopImmediatePropagation();return;}
    const key=link.dataset.footerKey;if(!key)return;
    event.preventDefault();event.stopImmediatePropagation();
    if(key==='cookies'){
      if(location.hash!=='#cookie-preferences')history.pushState(null,'','/#cookie-preferences');
      openCookiePrefsModal();
    }else openLegalModal(policies[key]||'tos');
  },true);
  syncLocation();

  // This local feedback complements the server's DNS and SSRF checks.
  function endpointError(value){
    if(!value.trim())return 'Enter your public endpoint URL.';
    if(/[\s\x00-\x1f\x7f]/.test(value.trim()))return 'Enter a complete endpoint URL without spaces or control characters.';
    let url;try{url=new URL(value);}catch{return 'Enter a complete http:// or https:// endpoint URL.';}
    if(!['http:','https:'].includes(url.protocol)||url.username||url.password)return 'Use an http:// or https:// URL without embedded login credentials.';
    const host=url.hostname.toLowerCase().replace(/^\[|\]$/g,'').replace(/\.$/,'');
    if(!host.includes(':')&&(!host.includes('.')||host.split('.').some(label=>!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label))))
      return 'Enter a valid public hostname or IP address.';
    const parts=host.split('.').map(Number);
    const privateIP=parts.length===4&&parts.every(n=>Number.isInteger(n)&&n>=0&&n<=255)&&
      (parts[0]===0||parts[0]===10||parts[0]===127||parts[0]>=224||parts[0]===169&&parts[1]===254||
       parts[0]===172&&parts[1]>=16&&parts[1]<=31||parts[0]===192&&parts[1]===168||
       parts[0]===100&&parts[1]>=64&&parts[1]<=127||parts[0]===198&&[18,19].includes(parts[1]));
    if(privateIP||host==='localhost'||host.endsWith('.localhost')||host.endsWith('.local')||
       host.endsWith('.internal')||host==='::'||host==='::1'||/^f[cd][0-9a-f]*:|^fe[89ab][0-9a-f]*:|^::ffff:/i.test(host))
      return 'Use a publicly reachable endpoint. Local and private network addresses are reserved for private connections.';
    return '';
  }
  function validateEndpoint(input,show=true){
    if(!input)return true;
    const error=endpointError(input.value);input.setCustomValidity(error);
    input.setAttribute('aria-invalid',String(Boolean(error)));
    let message=q('#'+input.id+'Error');
    if(!message){
      message=document.createElement('p');message.id=input.id+'Error';message.className='caption endpoint-feedback';message.setAttribute('role','alert');
      input.after(message);input.setAttribute('aria-describedby',((input.getAttribute('aria-describedby')||'')+' '+message.id).trim());
    }
    message.textContent=show?error:'';message.hidden=!show||!error;
    return !error;
  }
  for(const id of ['regUrl','regAutoUrl']){
    const input=q('#'+id);if(!input)continue;
    input.addEventListener('blur',()=>validateEndpoint(input,Boolean(input.value)));
    input.addEventListener('input',()=>{input.setCustomValidity('');input.removeAttribute('aria-invalid');const note=q('#'+id+'Error');if(note)note.hidden=true;});
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('#regSubmitBtn,#regInspectBtn,#uxInspectEndpoint');if(!button)return;
    if(button.id==='regSubmitBtn'){
      const authority=q('#pearlRegAuthority'),consent=q('#regTermsConsent');
      if(authority&&!authority.checked||consent&&!consent.checked)return;
    }
    const input=q(button.id==='regInspectBtn'?'#regAutoUrl':'#regUrl');
    if(!validateEndpoint(input)){event.preventDefault();event.stopImmediatePropagation();input.focus();}
  },true);
})();

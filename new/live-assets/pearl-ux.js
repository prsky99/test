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
        if(item.cap_tool_count)items.push([String(item.cap_tool_count)+' tools','']);
        if(!items.length&&item.auth_required===0&&item.kind!=='x402')items.push(['No account required','']);
        facts.replaceChildren(...items.map(([label,cls])=>node('span','chip '+cls,label)));
      }
    }
    setView(view);
  }
  const originalExplore=renderExplore;
  renderExplore=function(...args){const value=originalExplore(...args);compactResults();return value;};
  compactResults();
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

/* Task-first template discovery. Preview never changes or dispatches a workflow. */
'use strict';
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const view=q('#frontWfTemplatesView'),grid=q('#frontTemplatesGrid'),search=q('#frontTmplSearchInput');
  if(!view||!grid||!search)return;
  const el=(tag,className='',text)=>{const n=document.createElement(tag);n.className=className;if(text!==undefined)n.textContent=text;return n;};
  const button=(label,action,primary=false)=>{const n=el('button','btn'+(primary?' primary':''),label);n.type='button';n.addEventListener('click',action);return n;};
  const categoryNames={all:'All categories',travel_maps_weather:'Travel & Weather',dev_tools:'Developer Tools',data_utility:'Data & Utility',finance_crypto:'Finance & DeFi',automation:'Automation',sports_health:'Sports & Health',business_productivity:'Productivity',docs_knowledge:'Docs & Knowledge'};
  const category=t=>categoryNames[t.category]||String(t.category||'Workflow').replaceAll('_',' ');
  const agents=t=>(t.nodes||[]).filter(n=>n.type==='agent');
  const available=t=>t.execution_availability?.available!==false;
  let pageTemplates=null,previewTrigger=null,querySubmitted=false;

  const header=view.firstElementChild;
  header.classList.add('wf-library-header');
  const title=q('h3',header);title.textContent='Find your next workflow';title.tabIndex=-1;
  q('p',header).textContent='Start with a task. Compare the agents and inputs, then choose a workflow to try.';
  const label=el('label','wf-library-search-label','Search by task, topic or agent');label.htmlFor=search.id;
  search.before(label);search.placeholder='Try “news”, “country comparison” or “package security”';search.type='search';search.maxLength=160;
  const searchBlock=search.parentElement;searchBlock.classList.add('wf-library-search');
  const clear=button('Clear search',()=>{search.value='';filterFrontTemplates();search.focus();});clear.id='wfLibraryClear';search.after(clear);
  const examples=el('div','wf-library-examples');examples.append(el('span','','Try:'));
  for(const [name,term]of [['News & research','news'],['Country comparison','country'],['Package security','package']])examples.append(button(name,()=>{search.value=term;filterFrontTemplates();search.focus();}));
  header.append(examples);
  const categories=q('#frontTmplCategoryFilters');
  const layout=el('div','wf-library-layout'),facets=el('aside','wf-library-facets'),results=el('section','wf-library-results');
  facets.setAttribute('aria-label','Filter workflow templates');results.setAttribute('aria-label','Workflow template results');
  const facetDetails=el('details','wf-library-category-details');facetDetails.open=matchMedia('(min-width:901px)').matches;
  facetDetails.append(el('summary','','Categories'),categories);facets.append(facetDetails);
  const readyLabel=el('label','wf-library-ready'),ready=el('input');ready.type='checkbox';ready.id='wfLibraryReady';ready.addEventListener('change',()=>restartResults());
  readyLabel.append(ready,el('span','','Ready to try'));facets.append(readyLabel,el('p','wf-library-facet-note','Uses recorded connection checks. A completed run is not guaranteed.'));
  const reset=button('Reset all filters',()=>resetFilters());reset.classList.add('wf-library-reset');facets.append(reset);
  const toolbar=el('div','wf-library-results-toolbar'),count=el('p','wf-library-result-count');count.id='wfLibraryCount';count.setAttribute('role','status');
  const sortLabel=el('label','','Sort'),sort=el('select');sort.id='wfLibrarySort';
  for(const [value,name]of [['default','Default order'],['name','Name A–Z'],['steps','Fewest agent steps']])sort.append(new Option(name,value));
  sort.addEventListener('change',()=>restartResults());sortLabel.append(sort);toolbar.append(count,sortLabel);
  results.append(toolbar,grid);layout.append(facets,results);view.append(layout);
  const empty=el('section','wf-library-empty');empty.hidden=true;empty.append(el('h3','','No matching workflows'),el('p','','Try a broader task, a different category or reset the filters.'),button('Reset filters',()=>resetFilters()));grid.after(empty);
  function restartResults(){if(typeof window.goToFrontTemplatePage==='function')window.goToFrontTemplatePage(1);else renderFrontTemplates();}
  function resetFilters(){search.value='';ready.checked=false;sort.value='default';filterFrontTemplates();selectFrontTmplCategory('all');restartResults();search.focus();}

  function necklace(template,large=false){
    const chain=el('div','wf-library-necklace'+(large?' is-large':''));const steps=agents(template);
    chain.setAttribute('role','img');chain.setAttribute('aria-label',steps.length+' connected agent'+(steps.length===1?'':'s'));
    for(const step of steps.slice(0,large?8:4)){const pearl=el('span','wf-library-pearl');pearl.title=step.name||'Agent';chain.append(pearl);}
    if(steps.length>(large?8:4))chain.append(el('span','wf-library-extra','+'+(steps.length-(large?8:4))));
    return chain;
  }
  function choose(template){
    if(!available(template))return;
    if(frontWorkflowRunning){toast('A workflow is running. Stop it or wait before choosing another.');return;}
    if(dialog.open)dialog.close();
    if(String(frontActiveTemplateId)!==String(template.id))loadFrontTemplateToCanvas(template.id);
    else switchFrontWfSubView('canvas');
    requestAnimationFrame(()=>{const heading=q('#frontWfActiveName');heading.tabIndex=-1;heading.focus({preventScroll:true});heading.scrollIntoView({block:'start',behavior:'auto'});});
  }
  const dialog=el('dialog','wf-library-preview');dialog.id='wfLibraryPreview';dialog.setAttribute('aria-labelledby','wfLibraryPreviewTitle');
  const previewBody=el('div','wf-library-preview-body'),previewClose=button('Close preview',()=>dialog.close());previewClose.classList.add('wf-library-close');
  const previewToolbar=el('header','wf-library-preview-toolbar'),previewFooter=el('footer','wf-library-preview-footer');
  previewToolbar.append(el('span','','Workflow preview'),previewClose);dialog.append(previewToolbar,previewBody,previewFooter);view.after(dialog);
  dialog.addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const controls=[...dialog.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled)')].filter(n=>n.getClientRects().length);
    const first=controls[0],last=controls.at(-1);
    if(!first)return;
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  });
  dialog.addEventListener('close',()=>{if(previewTrigger?.isConnected)previewTrigger.focus({preventScroll:true});else if(!view.classList.contains('hidden'))title.focus({preventScroll:true});});
  const fieldNames={query:'Search topic',language:'Language',limit:'Maximum results',country:'Country',country_code:'Country code',package:'Package',package_name:'Package name',version:'Version',indicator:'Indicator'};
  function inputValue(value){if(typeof value==='string'&&value.includes('{{'))return 'Uses a result from an earlier step';if(Array.isArray(value))return value.join(', ');if(value&&typeof value==='object')return Object.entries(value).map(([k,v])=>k+': '+String(v)).join(' · ');return String(value??'');}
  function preview(template,trigger){
    previewTrigger=trigger;previewBody.replaceChildren();
    const badge=el('span','badge',category(template)),heading=el('h2','',template.name);heading.id='wfLibraryPreviewTitle';
    previewBody.append(badge,heading,el('p','wf-library-preview-description',template.description||'A published agent workflow.'),necklace(template,true));
    const steps=agents(template),protocols=[...new Set(steps.map(n=>String(n.kind||'').toUpperCase()).filter(Boolean))];
    previewBody.append(el('p','wf-library-preview-meta',steps.length+' agent'+(steps.length===1?'':'s')+' · '+protocols.join(' + ')),el('h3','','Agents and published inputs'));
    const list=el('ol','wf-library-preview-steps');
    for(const step of steps){const item=el('li'),name=el('h4','',step.name||'Agent step');item.append(name);const inputs=Object.entries(step.data?.input||{});if(inputs.length){const fields=el('dl');for(const [key,value]of inputs)fields.append(el('dt','',fieldNames[key]||key.replaceAll('_',' ')),el('dd','',inputValue(value)));item.append(fields);}else item.append(el('p','','No additional published input.'));list.append(item);}
    previewBody.append(list);
    const state=el('p','wf-library-preview-state',template.execution_availability?.message||'Review the published configuration before running.');state.setAttribute('role','status');
    const use=button('Use this workflow',()=>choose(template),true);use.disabled=!available(template)||frontWorkflowRunning;
    const download=button('Download web app',()=>downloadFrontTemplateWebApp(template.id));download.classList.add('wf-library-download');
    previewBody.append(state,el('p','wf-library-preview-hint','Choosing a template opens it for review. Nothing runs until you select Run workflow.'));
    previewFooter.replaceChildren(use,download);previewBody.scrollTop=0;
    dialog.showModal();previewBody.scrollTop=0;
  }
  window.filterWorkflowLibraryTemplates=function(templates){
    let values=ready.checked?templates.filter(available):templates.slice();
    if(sort.value==='name')values.sort((a,b)=>String(a.name).localeCompare(String(b.name),'en'));
    if(sort.value==='steps')values.sort((a,b)=>agents(a).length-agents(b).length);
    pageTemplates=values;return values;
  };
  function renderCard(template){
    const card=el('article','template-card wf-library-card');card.dataset.templateId=String(template.id);
    const top=el('div','wf-library-card-meta');top.append(el('span','badge',category(template)),el('span','wf-library-agent-count',agents(template).length+' agent'+(agents(template).length===1?'':'s')));
    if(String(template.id)===String(frontActiveTemplateId))top.append(el('span','wf-library-selected','Current workflow'));
    const heading=el('h3','',template.name),description=el('p','wf-library-card-description',template.description||'A published agent workflow.');
    const names=el('p','wf-library-agent-names',agents(template).map(n=>n.name||'Agent').join(' · '));
    const actions=el('div','wf-library-card-actions');let inspect;inspect=button('Preview workflow',()=>preview(template,inspect));inspect.setAttribute('aria-label','Preview '+template.name);
    const use=button('Use workflow',()=>choose(template),true);use.dataset.id=String(template.id);use.disabled=!available(template);
    actions.append(inspect,use);card.append(top,heading,description,necklace(template),names);
    if(!available(template))card.append(el('p','wf-library-unavailable',template.execution_availability?.message||'Currently unavailable. Choose another workflow.'));
    card.append(actions);return card;
  }
  function enhancePagers(){
    for(const where of ['top','bottom']){const pager=q('#uxTemplatePager-'+where);if(!pager)continue;if(where==='top')toolbar.after(pager);else empty.after(pager);
      if(!q('.wf-library-jump',pager)){
        const form=el('form','wf-library-jump'),label=el('label','','Page'),input=el('input');input.type='number';input.min='1';input.step='1';input.required=true;input.setAttribute('aria-label','Page number, '+where);
        const go=el('button','btn sm','Go');go.type='submit';label.append(input);form.append(label,go);
        form.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity())return;window.goToFrontTemplatePage?.(Number(input.value));q('#uxTemplatePager-top')?.scrollIntoView({block:'start',behavior:'auto'});});pager.append(form);
      }
      const pages=Math.max(1,Math.ceil(Number(pager.dataset.total||0)/(matchMedia('(max-width:700px)').matches?4:8))),input=q('input',pager);input.max=String(pages);input.value=pager.dataset.page||'1';
    }
  }
  const originalRender=renderFrontTemplates;
  renderFrontTemplates=function(...args){
    pageTemplates=null;const result=originalRender(...args);
    const rows=[...q('#frontTemplatesGrid').querySelectorAll('.template-card')];
    if(pageTemplates){
      const shown=rows.map(card=>{const id=q('button[data-id]',card)?.dataset.id;return pageTemplates.find(t=>String(t.id)===id);}).filter(Boolean);
      grid.replaceChildren(...shown.map(renderCard));
      count.textContent=pageTemplates.length.toLocaleString('en-US')+' matching workflow'+(pageTemplates.length===1?'':'s');empty.hidden=pageTemplates.length!==0;
    }else{
      const pending=Boolean(search.value.trim()&&filterFrontTemplates.state?.loading),failed=Boolean(search.value.trim()&&filterFrontTemplates.state?.error);
      const loading=frontTemplatesLoading&&!frontTemplatesCache.length;
      count.textContent=pending?'Finding matching workflows…':failed?'Search unavailable':loading?'Loading templates…':'0 matching workflows';
      empty.hidden=pending||failed||loading||frontTemplatesLoadFailed;
      if(!empty.hidden)grid.replaceChildren();
    }
    grid.setAttribute('aria-busy',String(Boolean(search.value.trim()&&filterFrontTemplates.state?.loading)));clear.hidden=!search.value;enhancePagers();return result;
  };
  window.openWorkflowLibrary=function(query){
    search.value=query||'';filterFrontTemplates();querySubmitted=true;switchFrontWfSubView('templates');
    requestAnimationFrame(()=>{search.focus({preventScroll:true});header.scrollIntoView({block:'start',behavior:'auto'});});
  };
  const originalView=switchFrontWfSubView;
  switchFrontWfSubView=function(viewName){const previousFocus=document.activeElement,value=originalView(viewName);if(viewName==='templates'&&!querySubmitted)requestAnimationFrame(()=>{if(document.activeElement===previousFocus&&!dialog.open)search.focus({preventScroll:true});});querySubmitted=false;return value;};
  renderFrontTemplates();
})();

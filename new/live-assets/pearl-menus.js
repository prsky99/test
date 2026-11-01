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
